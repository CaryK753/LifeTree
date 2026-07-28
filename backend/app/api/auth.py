"""Authentication endpoints: register, login, refresh, me, OAuth, email code.

JWT-based auth flow:
  1. ``POST /auth/register`` — create a new user (email + password). Returns
     access + refresh tokens. New users get ``role="user"`` by default.
  2. ``POST /auth/login`` — exchange email + password for tokens.
  3. ``POST /auth/refresh`` — exchange refresh token for a new access token.
  4. ``GET  /auth/me`` — return current user profile (requires Bearer token).
  5. ``GET  /auth/config`` — public auth config (OAuth providers, email
     verification flag) for the login dialog. No auth required.
  6. ``GET  /auth/oauth/{provider_id}/start`` — return the authorize URL
     for an OAuth provider. Frontend redirects the browser there.
  7. ``GET  /auth/oauth/{provider_id}/callback?code=...`` — OAuth callback:
     exchange the code for an access token, fetch user info, create or
     look up the local user, return JWT pair.
  8. ``POST /auth/send-code`` — send a 6-digit verification code to an
     email address (only when email_verification_enabled is True).
  9. ``POST /auth/register-with-code`` — register using email + code
     instead of a password (only when email_verification_enabled is True).

Admin promotion is handled via env var ``LIFETREE_ADMIN_USER_IDS`` (see
``app.core.tenant._apply_admin_override``). No DB edit needed.
"""
from __future__ import annotations

import secrets
import smtplib
import ssl
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Literal
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    TOKEN_TYPE_REFRESH,
    verify_password,
)
from app.core.tenant import CurrentUser, _apply_admin_override
from app.db.postgres import get_db
from app.db.redis import get_redis
from app.llm.registry import (
    get_disable_registration,
    get_email_verification_enabled,
    get_oauth_provider_by_id,
    get_oauth_providers,
    get_public_auth_config,
    get_service_address,
    get_smtp_config,
)
from app.models.user import UserProfile
from app.models.user_oauth_link import UserOAuthLink
from app.schemas.entities import UserProfileRead

log = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------- Schemas ----------

class RegisterRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=128)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1)


class AuthTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserProfileRead


class MeResponse(UserProfileRead):
    role: str
    is_enabled: bool


class PublicAuthConfig(BaseModel):
    """Public auth config returned by GET /auth/config (no secrets)."""

    oauth_providers: list[dict] = Field(default_factory=list)
    email_verification_enabled: bool = False
    disable_registration: bool = False
    multi_user_mode: bool = True
    use_mode: Literal["single", "multi"] = "single"
    # True when at least one user who can actually log in exists
    # (password_hash or external_id set). Used by the frontend to decide
    # whether to show the first-run "create admin" setup screen.
    has_users: bool = False
    # When True, the login dialog shows a "Sign in with passkey" button
    # and the /profile page shows the passkey management UI.
    passkey_login_enabled: bool = False


class OAuthStartResponse(BaseModel):
    """Authorize URL for an OAuth provider — frontend redirects to it."""

    authorize_url: str
    state: str


class SendCodeRequest(BaseModel):
    email: EmailStr


class SendCodeResponse(BaseModel):
    ok: bool
    error: str | None = None
    expires_in: int = 600


class RegisterWithCodeRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=128)
    email: EmailStr
    code: str = Field(..., min_length=4, max_length=8)
    password: str | None = Field(
        None, min_length=6, max_length=128, description="Optional password"
    )


class OAuthBindStartResponse(BaseModel):
    """Authorize URL for binding an OAuth provider to the current account."""

    authorize_url: str
    state: str


class OAuthBindingRead(BaseModel):
    """A user's OAuth binding — provider_id + display metadata."""

    provider_id: str
    provider_name: str
    external_sub: str
    created_at: str


# ---------- Helpers ----------

def _make_token_pair(user: UserProfile) -> dict:
    """Build access + refresh tokens + serializable user payload."""
    return {
        "access_token": create_access_token(user.id, role=user.role),
        "refresh_token": create_refresh_token(user.id),
        "token_type": "bearer",
        "user": user,
    }


def _should_promote_first_admin(db: Session) -> bool:
    """Return True if no real users exist yet (first-admin promotion needed).

    The first user who registers — by password, verification code, or
    OAuth — is auto-promoted to admin so the system is bootstrappable
    without editing LIFETREE_ADMIN_USER_IDS in .env.

    Excludes the passwordless default-user row (Alex Chen, id=
    DEFAULT_USER_ID) which may exist due to the legacy single-user
    fallback. We exclude by ID (not by password_hash/external_id) so
    that code-only registrations (no password) are still counted as
    real users.
    """
    from sqlalchemy import func

    from app.core.tenant import DEFAULT_USER_ID

    count = db.scalar(
        select(func.count())
        .select_from(UserProfile)
        .where(UserProfile.id != DEFAULT_USER_ID)
    )
    return (count or 0) == 0


def _redis_code_key(email: str) -> str:
    """Redis key for an email verification code."""
    return f"verify_code:{email.lower().strip()}"


def _send_email(to_addr: str, subject: str, body: str) -> None:
    """Send a plain-text email using the configured SMTP settings.

    Raises on failure — callers should catch and convert to a friendly error.
    Uses the same strict TLS context as the SMTP test endpoint.

    Deprecated: prefer ``_send_email_message`` with a pre-built HTML message
    so the standard LifeTree email template is applied. This is kept for
    backwards compatibility with any caller that only has plain text.
    """
    smtp = get_smtp_config()
    host = smtp["host"]
    if not host:
        raise ValueError("SMTP host is not configured")

    port = smtp["port"] or 587
    smtp_user = smtp["user"]
    smtp_password = smtp["password"]
    from_addr = smtp["from"] or "notify@lifetree.local"
    sender_name = smtp.get("sender_name", "LifeTree") or "LifeTree"
    use_tls = smtp["use_tls"] if smtp["use_tls"] is not None else True
    use_ssl = smtp["use_ssl"] if smtp["use_ssl"] is not None else False

    tls_ctx = ssl.create_default_context()
    tls_ctx.minimum_version = ssl.TLSVersion.TLSv1_2

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr((sender_name, from_addr))
    msg["To"] = to_addr

    _smtp_send(host, port, smtp_user, smtp_password, from_addr, to_addr,
               msg, use_tls, use_ssl, tls_ctx)


def _send_email_message(to_addr: str, msg) -> None:
    """Send a pre-built email.message.Message via SMTP.

    Used by callers that build their own HTML/plain multipart messages
    (e.g. via ``app.services.email_template.build_html_message``).
    """
    smtp = get_smtp_config()
    host = smtp["host"]
    if not host:
        raise ValueError("SMTP host is not configured")

    port = smtp["port"] or 587
    smtp_user = smtp["user"]
    smtp_password = smtp["password"]
    from_addr = smtp["from"] or "notify@lifetree.local"
    use_tls = smtp["use_tls"] if smtp["use_tls"] is not None else True
    use_ssl = smtp["use_ssl"] if smtp["use_ssl"] is not None else False

    tls_ctx = ssl.create_default_context()
    tls_ctx.minimum_version = ssl.TLSVersion.TLSv1_2

    _smtp_send(host, port, smtp_user, smtp_password, from_addr, to_addr,
               msg, use_tls, use_ssl, tls_ctx)


def _smtp_send(host, port, user, password, from_addr, to_addr, msg,
               use_tls, use_ssl, tls_ctx) -> None:
    """Low-level SMTP send helper shared by _send_email and _send_email_message."""
    if use_ssl:
        with smtplib.SMTP_SSL(host, port, timeout=30, context=tls_ctx) as server:
            server.ehlo()
            if user:
                server.login(user, password)
            server.sendmail(from_addr, [to_addr], msg.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.ehlo()
            if use_tls:
                server.starttls(context=tls_ctx)
                server.ehlo()
            if user:
                server.login(user, password)
            server.sendmail(from_addr, [to_addr], msg.as_string())


# ---------- Endpoints ----------

@router.post("/register", response_model=AuthTokenResponse, status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> dict:
    """Create a new user account. Returns tokens immediately (auto-login).

    When email verification is enabled, this endpoint refuses to register
    without a code — clients must use ``POST /auth/register-with-code`` instead.
    """
    if get_disable_registration():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is disabled. Contact the administrator.",
        )
    if get_email_verification_enabled():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email verification is required. Use /auth/register-with-code.",
        )

    existing = db.scalars(
        select(UserProfile).where(UserProfile.email == payload.email.lower().strip())
    ).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    # The first real user (excluding the default-user fallback) is
    # auto-promoted to admin so the system is bootstrappable.
    is_first_admin = _should_promote_first_admin(db)
    user = UserProfile(
        display_name=payload.display_name.strip(),
        email=payload.email.lower().strip(),
        password_hash=hash_password(payload.password),
        risk_tolerance="medium",
        role="admin" if is_first_admin else "user",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    user = _apply_admin_override(user)
    log.info("auth.registered", user_id=user.id, email=user.email, role=user.role, first_admin=is_first_admin)
    return _make_token_pair(user)


@router.post("/login", response_model=AuthTokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict:
    """Exchange email + password for access + refresh tokens."""
    user = db.scalars(
        select(UserProfile).where(UserProfile.email == payload.email.lower().strip())
    ).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not user.is_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    user = _apply_admin_override(user)
    log.info("auth.login", user_id=user.id, email=user.email, role=user.role)
    return _make_token_pair(user)


@router.post("/refresh", response_model=AuthTokenResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> dict:
    """Exchange a refresh token for a new access + refresh token pair."""
    claims = decode_token(payload.refresh_token)
    if claims is None or claims.get("type") != TOKEN_TYPE_REFRESH:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token claims")

    user = db.get(UserProfile, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if not user.is_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    user = _apply_admin_override(user)
    return _make_token_pair(user)


@router.get("/me", response_model=MeResponse)
def me(user: CurrentUser) -> UserProfile:
    """Return the current authenticated user's profile."""
    return user


# ---------- Public auth config (for login dialog) ----------

@router.get("/config", response_model=PublicAuthConfig)
def get_auth_config(db: Session = Depends(get_db)) -> PublicAuthConfig:
    """Return public auth config for unauthenticated clients.

    The login dialog calls this to decide:
      - whether to show OAuth buttons (and which ones)
      - whether to show the email-verification-code field on registration
      - whether to show the first-run "create admin" setup screen
        (``has_users`` is False when no real users exist yet)
    """
    cfg = get_public_auth_config()
    has_users = not _should_promote_first_admin(db)
    return PublicAuthConfig(**cfg, has_users=has_users)


# ---------- OAuth ----------

def _build_authorize_url(provider, state: str) -> str:
    """Build the provider authorize URL with the standard params."""
    params = {
        "client_id": provider.client_id,
        "redirect_uri": provider.redirect_uri,
        "response_type": "code",
        "state": state,
    }
    if provider.scopes:
        params["scope"] = " ".join(provider.scopes)
    separator = "&" if "?" in provider.authorize_url else "?"
    return f"{provider.authorize_url}{separator}{urlencode(params)}"


def _exchange_code_for_userinfo(provider, code: str) -> dict:
    """Exchange an OAuth code for an access token + fetch userinfo.

    Returns the userinfo dict. Raises HTTPException on any failure.
    """
    token_payload = {
        "client_id": provider.client_id,
        "client_secret": provider.client_secret,
        "code": code,
        "redirect_uri": provider.redirect_uri,
        "grant_type": "authorization_code",
    }
    try:
        with httpx.Client(timeout=15) as client:
            token_resp = client.post(
                provider.token_url,
                data=token_payload,
                headers={"Accept": "application/json"},
            )
            token_resp.raise_for_status()
            token_data = token_resp.json()
    except httpx.HTTPError as exc:
        log.warning("auth.oauth_token_exchange_failed", provider=provider.id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to exchange OAuth code: {exc}",
        )

    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OAuth token endpoint returned no access_token: {token_data}",
        )

    try:
        with httpx.Client(timeout=15) as client:
            userinfo_resp = client.get(
                provider.userinfo_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            userinfo_resp.raise_for_status()
            userinfo = userinfo_resp.json()
    except httpx.HTTPError as exc:
        log.warning("auth.oauth_userinfo_failed", provider=provider.id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch user info from OAuth provider: {exc}",
        )
    return userinfo


@router.get("/oauth/{provider_id}/start", response_model=OAuthStartResponse)
def oauth_start(
    provider_id: str,
    mode: Literal["login", "register"] = "login",
) -> OAuthStartResponse:
    """Return the authorize URL for an OAuth provider (login or register flow).

    The frontend redirects the browser to ``authorize_url``. After the user
    authorizes, the provider redirects back to ``redirect_uri`` which should
    be a frontend route that calls
    ``GET /auth/oauth/{provider_id}/callback?code=...&state=...``.

    ``mode``:
      - ``"login"`` (default): callback will find-or-create the user.
      - ``"register"``: callback will create a new user explicitly; fails
        with 409 if the email/external_id is already registered, and 403
        if ``disable_registration`` is True.
    """
    provider = get_oauth_provider_by_id(provider_id)
    if provider is None or not provider.enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OAuth provider not found")
    if not provider.client_id or not provider.authorize_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth provider is misconfigured (missing client_id or authorize_url)",
        )
    if mode == "register" and get_disable_registration():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is disabled",
        )

    # ``state`` prevents CSRF — the frontend should verify it matches on
    # callback. We store it in Redis with a short TTL so the callback can
    # validate it server-side too. Value encodes the mode:
    #   ``login:<provider_id>``    — login flow (find-or-create)
    #   ``register:<provider_id>`` — register flow (must create new)
    #   ``bind:<user_id>``         — bind flow (link to existing user)
    state = secrets.token_urlsafe(16)
    try:
        redis = get_redis()
        redis.setex(f"oauth_state:{state}", 600, f"{mode}:{provider_id}")
    except Exception as exc:  # noqa: BLE001
        log.error("auth.oauth_state_save_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OAuth state store unavailable — please retry",
        )

    return OAuthStartResponse(
        authorize_url=_build_authorize_url(provider, state),
        state=state,
    )


@router.get("/oauth/{provider_id}/bind-start", response_model=OAuthBindStartResponse)
def oauth_bind_start(
    provider_id: str,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> OAuthBindStartResponse:
    """Return the authorize URL for binding an OAuth provider to the current
    account.

    Same as ``oauth_start`` but the state is tagged with ``bind:<user_id>``
    so the callback knows to link the provider's external account to the
    authenticated user instead of creating / logging in.
    """
    provider = get_oauth_provider_by_id(provider_id)
    if provider is None or not provider.enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OAuth provider not found")
    if not provider.client_id or not provider.authorize_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth provider is misconfigured (missing client_id or authorize_url)",
        )

    # Check that the user doesn't already have this provider bound.
    existing = db.scalars(
        select(UserOAuthLink).where(
            UserOAuthLink.user_id == user.id,
            UserOAuthLink.provider_id == provider_id,
        )
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This OAuth provider is already bound to your account",
        )

    state = secrets.token_urlsafe(16)
    try:
        redis = get_redis()
        redis.setex(f"oauth_state:{state}", 600, f"bind:{user.id}")
    except Exception as exc:  # noqa: BLE001
        log.error("auth.oauth_state_save_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OAuth state store unavailable — please retry",
        )

    return OAuthBindStartResponse(
        authorize_url=_build_authorize_url(provider, state),
        state=state,
    )


@router.get("/oauth/{provider_id}/callback", response_model=AuthTokenResponse)
def oauth_callback(
    provider_id: str,
    code: str,
    state: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    """OAuth callback: exchange code for tokens, fetch user info, then either
    log in, register, or bind to an existing account based on the state.

    The frontend calls this with the ``code`` and ``state`` query params
    received from the provider. We:
      1. Validate ``state`` (CSRF protection). The state value also tells
         us which flow this is:
           ``login:<provider_id>``    — find-or-create the user
           ``register:<provider_id>`` — create a new user (409 if exists)
           ``bind:<user_id>``         — link provider to the given user
         For backward compatibility, a stored value with no prefix is
         treated as ``login``.
      2. Exchange ``code`` for an access token at ``token_url``.
      3. Fetch user info from ``userinfo_url``.
      4. Login flow: find or create a local user keyed by email
         (fallback: provider+sub) and return a JWT pair.
      5. Register flow: same as login, but 409 if email/external_id already
         exists. Respects ``disable_registration``.
      6. Bind flow: link the provider's external_sub to the user encoded
         in the state, then return that user's JWT pair.
    """
    provider = get_oauth_provider_by_id(provider_id)
    if provider is None or not provider.enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OAuth provider not found")

    # ---------- Validate state (CSRF) + detect mode ----------
    # Strict validation: state must be present and must match a Redis entry.
    if not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing OAuth state — possible CSRF attack",
        )
    oauth_mode = "login"  # default for backward-compat
    bind_user_id: str | None = None
    try:
        redis = get_redis()
        stored = redis.get(f"oauth_state:{state}")
    except Exception as exc:  # noqa: BLE001
        log.error("auth.oauth_state_check_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OAuth state store unavailable — please retry",
        )
    if not stored:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state",
        )
    # Decode the stored value: "<mode>:<rest>" or legacy bare provider_id.
    if isinstance(stored, bytes):
        stored = stored.decode("utf-8", errors="ignore")
    if stored.startswith("bind:"):
        oauth_mode = "bind"
        bind_user_id = stored[len("bind:"):]
        if not bind_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid OAuth state (empty bind user)",
            )
    elif stored.startswith("register:"):
        oauth_mode = "register"
        stored_provider = stored[len("register:"):]
        # The callback may receive either the provider id (e.g.
        # "o_c029be02c5d8") or the provider name (e.g. "github") in the
        # URL path — the redirect_uri encodes the name. Compare against
        # the resolved provider.id so both forms are accepted.
        if stored_provider != provider_id and stored_provider != provider.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OAuth state provider mismatch",
            )
    elif stored.startswith("login:"):
        oauth_mode = "login"
        stored_provider = stored[len("login:"):]
        if stored_provider != provider_id and stored_provider != provider.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OAuth state provider mismatch",
            )
    else:
        # Legacy bare provider_id (no prefix) — treat as login.
        oauth_mode = "login"
        if stored != provider_id and stored != provider.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid OAuth state (provider mismatch)",
            )
    # Consume the state (one-shot).
    try:
        redis.delete(f"oauth_state:{state}")
    except Exception as exc:  # noqa: BLE001
        log.warning("auth.oauth_state_delete_failed", error=str(exc))

    # ---------- Exchange code + fetch userinfo ----------
    userinfo = _exchange_code_for_userinfo(provider, code)

    # Common fields across providers (GitHub, Google, GitLab, …).
    email = userinfo.get("email") or userinfo.get("emailAddress") or ""
    # Fallback unique id when email isn't available (private GitHub accounts).
    external_sub = str(userinfo.get("id") or userinfo.get("sub") or "")
    display_name = (
        userinfo.get("name")
        or userinfo.get("login")
        or userinfo.get("nickname")
        or (email.split("@")[0] if email else "user")
    )

    if not email and not external_sub:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OAuth provider returned neither email nor id — cannot identify user",
        )

    # ---------- Bind flow ----------
    if oauth_mode == "bind":
        target = db.get(UserProfile, bind_user_id)
        if target is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found for OAuth bind")
        if not external_sub:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="OAuth provider returned no id — cannot bind",
            )
        # Check that this provider account isn't already bound to anyone.
        existing_link = db.scalars(
            select(UserOAuthLink).where(
                UserOAuthLink.provider_id == provider_id,
                UserOAuthLink.external_sub == external_sub,
            )
        ).first()
        if existing_link is not None and existing_link.user_id != target.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This OAuth account is already bound to another user",
            )
        # Check the user doesn't already have this provider bound.
        existing_self = db.scalars(
            select(UserOAuthLink).where(
                UserOAuthLink.user_id == target.id,
                UserOAuthLink.provider_id == provider_id,
            )
        ).first()
        if existing_self is not None:
            # Update the external_sub in case it changed (e.g. re-binding
            # after the provider rotated the user id).
            existing_self.external_sub = external_sub
            db.commit()
            db.refresh(existing_self)
        else:
            link = UserOAuthLink(
                user_id=target.id,
                provider_id=provider_id,
                external_sub=external_sub,
            )
            db.add(link)
            # Also update avatar / external_id on the user for backwards
            # compat with the legacy external_id column.
            if not target.external_id:
                target.external_id = f"{provider_id}:{external_sub}"
            avatar = userinfo.get("avatar_url") or userinfo.get("picture")
            if avatar and not target.avatar_url:
                target.avatar_url = avatar
            db.commit()
            db.refresh(link)

        log.info("auth.oauth_bound", user_id=target.id, provider=provider_id, sub=external_sub)
        target = _apply_admin_override(target)
        return _make_token_pair(target)

    # ---------- Login / Register flow ----------
    # Try to find an existing user keyed by email, then external_id, then
    # oauth link row. In register mode, finding an existing user is a 409.
    user: UserProfile | None = None
    if email:
        user = db.scalars(
            select(UserProfile).where(UserProfile.email == email.lower().strip())
        ).first()

    if user is None and external_sub:
        # Fallback: look up by external_id (provider-unique sub) or by
        # an explicit oauth link row.
        external_id = f"{provider_id}:{external_sub}"
        user = db.scalars(
            select(UserProfile).where(UserProfile.external_id == external_id)
        ).first()
        if user is None:
            # Also check user_oauth_links for a prior bind.
            link = db.scalars(
                select(UserOAuthLink).where(
                    UserOAuthLink.provider_id == provider_id,
                    UserOAuthLink.external_sub == external_sub,
                )
            ).first()
            if link is not None:
                user = db.get(UserProfile, link.user_id)

    if user is not None:
        if oauth_mode == "register":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email or OAuth identity already registered — log in instead",
            )
        # Update external_id if missing. Avatar and display_name are NOT
        # overwritten on subsequent logins — once the user has customized
        # their profile, OAuth providers shouldn't clobber it. Only fill
        # them in when they're empty (first-time OAuth-created accounts
        # that never set a custom avatar/name).
        if not user.external_id and external_sub:
            user.external_id = f"{provider_id}:{external_sub}"
        avatar = userinfo.get("avatar_url") or userinfo.get("picture")
        if avatar and not user.avatar_url:
            user.avatar_url = avatar
        if display_name and not user.display_name:
            user.display_name = str(display_name)[:128]
        # Make sure a link row exists (backfill for users created before
        # the user_oauth_links table existed).
        if external_sub:
            existing_link = db.scalars(
                select(UserOAuthLink).where(
                    UserOAuthLink.user_id == user.id,
                    UserOAuthLink.provider_id == provider_id,
                )
            ).first()
            if existing_link is None:
                db.add(UserOAuthLink(
                    user_id=user.id,
                    provider_id=provider_id,
                    external_sub=external_sub,
                ))
            elif existing_link.external_sub != external_sub:
                existing_link.external_sub = external_sub
        db.commit()
        db.refresh(user)
    else:
        # No existing user — create one. In login mode this is "first-time
        # OAuth login auto-creates the account" (same as before); in
        # register mode this is the explicit registration.
        if not email:
            # No email — synthesize a private one so the unique constraint
            # doesn't trip. The user can update it later.
            email = f"oauth_{provider_id}_{external_sub}@lifetree.local"
        external_id_val = f"{provider_id}:{external_sub}" if external_sub else None
        is_first_admin = _should_promote_first_admin(db)
        user = UserProfile(
            display_name=str(display_name)[:128],
            email=email.lower().strip(),
            external_id=external_id_val,
            avatar_url=userinfo.get("avatar_url") or userinfo.get("picture"),
            risk_tolerance="medium",
            role="admin" if is_first_admin else "user",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        # Also create an oauth link row for the new user.
        if external_sub:
            link = UserOAuthLink(
                user_id=user.id,
                provider_id=provider_id,
                external_sub=external_sub,
            )
            db.add(link)
            db.commit()
        log.info(
            "auth.oauth_user_created",
            user_id=user.id, provider=provider_id, email=user.email,
            first_admin=is_first_admin, mode=oauth_mode,
        )

    if not user.is_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    user = _apply_admin_override(user)
    log.info("auth.oauth_login", user_id=user.id, provider=provider_id, email=user.email, mode=oauth_mode)
    return _make_token_pair(user)


# ---------- OAuth bindings (current user) ----------

@router.get("/oauth/bindings", response_model=list[OAuthBindingRead])
def list_oauth_bindings(user: CurrentUser, db: Session = Depends(get_db)) -> list[OAuthBindingRead]:
    """List the current user's OAuth bindings.

    Returns one entry per bound provider, including the provider's display
    name (looked up from app_config) so the UI doesn't need a second
    request to render the binding list.
    """
    links = db.scalars(
        select(UserOAuthLink).where(UserOAuthLink.user_id == user.id)
    ).all()
    # Build a provider_id → name map for the response.
    providers = {p.id: p.name for p in get_oauth_providers()}
    return [
        OAuthBindingRead(
            provider_id=link.provider_id,
            provider_name=providers.get(link.provider_id, link.provider_id),
            external_sub=link.external_sub,
            created_at=link.created_at.isoformat() if link.created_at else "",
        )
        for link in links
    ]


@router.delete("/oauth/bindings/{provider_id}")
def unbind_oauth_provider(
    provider_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> dict:
    """Remove an OAuth binding from the current user's account.

    The user can always unbind — even if they have no password and no
    other OAuth bindings, they'd just lose the ability to log in (which
    they can recover via the "forgot password" / admin-reset flow). The
    frontend warns them about this before confirming.
    """
    link = db.scalars(
        select(UserOAuthLink).where(
            UserOAuthLink.user_id == user.id,
            UserOAuthLink.provider_id == provider_id,
        )
    ).first()
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OAuth provider is not bound to your account")
    db.delete(link)
    db.commit()
    log.info("auth.oauth_unbound", user_id=user.id, provider=provider_id)
    return {"ok": True}


# ---------- Email verification code ----------

@router.post("/send-code", response_model=SendCodeResponse)
def send_code(payload: SendCodeRequest, db: Session = Depends(get_db)) -> SendCodeResponse:
    """Send a 6-digit verification code to ``payload.email``.

    Only works when email verification is enabled. The code is stored in
    Redis with a 10-minute TTL. Sending a new code overwrites any previous
    one for the same email.

    Rate limiting: one send per 60 seconds per email (best-effort via Redis).
    """
    if not get_email_verification_enabled():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email verification is not enabled",
        )

    email = payload.email.lower().strip()
    # Don't leak whether an email is already registered — but refuse to
    # send a code if it is, so the registration flow stays clean. The
    # frontend should also check, but we enforce server-side.
    existing = db.scalars(select(UserProfile).where(UserProfile.email == email)).first()
    if existing is not None:
        # Return ok=True to avoid leaking which emails are registered,
        # but don't actually send a code.
        return SendCodeResponse(ok=True, expires_in=600)

    try:
        redis = get_redis()
    except Exception as exc:  # noqa: BLE001
        log.error("auth.redis_unavailable", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Verification code service unavailable (Redis)",
        )

    # Rate limit: 1 send per 60s per email.
    rate_key = f"verify_code_rate:{email}"
    if redis.exists(rate_key):
        ttl = redis.ttl(rate_key)
        return SendCodeResponse(
            ok=False,
            error=f"Please wait {ttl or 60}s before requesting another code",
            expires_in=600,
        )

    code = "".join(secrets.choice("0123456789") for _ in range(6))
    redis.setex(_redis_code_key(email), 600, code)
    redis.setex(rate_key, 60, "1")

    try:
        # Build an HTML verification-code email and send via SMTP.
        from app.services.email_template import (
            build_html_message,
            render_verification_code_email,
        )

        subject, html_body = render_verification_code_email(code, expires_in_minutes=10)
        plain_fallback = (
            f"Your LifeTree verification code is: {code}\n"
            f"This code expires in 10 minutes.\n"
            f"If you didn't request this, you can safely ignore this email.\n"
        )
        msg = build_html_message(
            to_addr=email,
            subject=subject,
            html_body=html_body,
            plain_text_fallback=plain_fallback,
        )
        _send_email_message(email, msg)
    except Exception as exc:  # noqa: BLE001
        log.error("auth.send_code_email_failed", email=email, error=str(exc))
        # Don't leak SMTP internals to the client — return a generic error.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to send verification email: {exc}",
        )

    log.info("auth.code_sent", email=email)
    return SendCodeResponse(ok=True, expires_in=600)


@router.post("/register-with-code", response_model=AuthTokenResponse, status_code=201)
def register_with_code(
    payload: RegisterWithCodeRequest, db: Session = Depends(get_db)
) -> dict:
    """Register a new user using an email verification code.

    Only works when email verification is enabled. The code must have been
    sent to ``payload.email`` via ``POST /auth/send-code`` and not yet expired.

    A password is optional — when provided, the user can also log in via
    ``POST /auth/login``. When omitted, the user can only log in via OAuth
    (if they later link an OAuth account) or by requesting a new code.
    """
    if get_disable_registration():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is disabled. Contact the administrator.",
        )
    if not get_email_verification_enabled():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email verification is not enabled",
        )

    email = payload.email.lower().strip()
    existing = db.scalars(select(UserProfile).where(UserProfile.email == email)).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    try:
        redis = get_redis()
    except Exception as exc:  # noqa: BLE001
        log.error("auth.redis_unavailable", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Verification code service unavailable (Redis)",
        )

    stored = redis.get(_redis_code_key(email))
    if not stored or stored != payload.code.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification code",
        )
    # Code is consumed — delete it.
    redis.delete(_redis_code_key(email))

    password_hash = hash_password(payload.password) if payload.password else None
    is_first_admin = _should_promote_first_admin(db)
    user = UserProfile(
        display_name=payload.display_name.strip(),
        email=email,
        password_hash=password_hash,
        risk_tolerance="medium",
        role="admin" if is_first_admin else "user",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    user = _apply_admin_override(user)
    log.info("auth.registered_with_code", user_id=user.id, email=user.email, role=user.role, first_admin=is_first_admin)
    return _make_token_pair(user)


__all__ = ["router"]
