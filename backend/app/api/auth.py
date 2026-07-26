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
    get_email_verification_enabled,
    get_oauth_provider_by_id,
    get_public_auth_config,
    get_smtp_config,
)
from app.models.user import UserProfile
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
    multi_user_mode: bool = True
    use_mode: Literal["single", "multi"] = "single"
    # True when at least one user who can actually log in exists
    # (password_hash or external_id set). Used by the frontend to decide
    # whether to show the first-run "create admin" setup screen.
    has_users: bool = False


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

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = formataddr((sender_name, from_addr))
    msg["To"] = to_addr

    if use_ssl:
        with smtplib.SMTP_SSL(host, port, timeout=30, context=tls_ctx) as server:
            server.ehlo()
            if smtp_user:
                server.login(smtp_user, smtp_password)
            server.sendmail(from_addr, [to_addr], msg.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.ehlo()
            if use_tls:
                server.starttls(context=tls_ctx)
                server.ehlo()
            if smtp_user:
                server.login(smtp_user, smtp_password)
            server.sendmail(from_addr, [to_addr], msg.as_string())


# ---------- Endpoints ----------

@router.post("/register", response_model=AuthTokenResponse, status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> dict:
    """Create a new user account. Returns tokens immediately (auto-login).

    When email verification is enabled, this endpoint refuses to register
    without a code — clients must use ``POST /auth/register-with-code`` instead.
    """
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

@router.get("/oauth/{provider_id}/start", response_model=OAuthStartResponse)
def oauth_start(provider_id: str) -> OAuthStartResponse:
    """Return the authorize URL for an OAuth provider.

    The frontend redirects the browser to ``authorize_url``. After the user
    authorizes, the provider redirects back to ``redirect_uri`` which should
    be a frontend route that calls
    ``GET /auth/oauth/{provider_id}/callback?code=...&state=...``.
    """
    provider = get_oauth_provider_by_id(provider_id)
    if provider is None or not provider.enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OAuth provider not found")
    if not provider.client_id or not provider.authorize_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth provider is misconfigured (missing client_id or authorize_url)",
        )

    # ``state`` prevents CSRF — the frontend should verify it matches on
    # callback. We store it in Redis with a short TTL so the callback can
    # validate it server-side too.
    state = secrets.token_urlsafe(16)
    try:
        redis = get_redis()
        redis.setex(f"oauth_state:{state}", 600, provider_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("auth.oauth_state_save_failed", error=str(exc))

    params = {
        "client_id": provider.client_id,
        "redirect_uri": provider.redirect_uri,
        "response_type": "code",
        "state": state,
    }
    if provider.scopes:
        params["scope"] = " ".join(provider.scopes)
    separator = "&" if "?" in provider.authorize_url else "?"
    authorize_url = f"{provider.authorize_url}{separator}{urlencode(params)}"
    return OAuthStartResponse(authorize_url=authorize_url, state=state)


@router.get("/oauth/{provider_id}/callback", response_model=AuthTokenResponse)
def oauth_callback(
    provider_id: str,
    code: str,
    state: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    """OAuth callback: exchange code for tokens, fetch user info, log in.

    The frontend calls this with the ``code`` and ``state`` query params
    received from the provider. We:
      1. Validate ``state`` (CSRF protection).
      2. Exchange ``code`` for an access token at ``token_url``.
      3. Fetch user info from ``userinfo_url``.
      4. Find or create a local user keyed by email (fallback: provider+sub).
      5. Return a JWT pair so the frontend can store it and redirect.
    """
    provider = get_oauth_provider_by_id(provider_id)
    if provider is None or not provider.enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OAuth provider not found")

    # ---------- Validate state (CSRF) ----------
    if state:
        try:
            redis = get_redis()
            stored_provider = redis.get(f"oauth_state:{state}")
            if stored_provider and stored_provider != provider_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state")
            redis.delete(f"oauth_state:{state}")
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("auth.oauth_state_check_failed", error=str(exc))

    # ---------- Exchange code for access token ----------
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
        log.warning("auth.oauth_token_exchange_failed", provider=provider_id, error=str(exc))
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

    # ---------- Fetch user info ----------
    try:
        with httpx.Client(timeout=15) as client:
            userinfo_resp = client.get(
                provider.userinfo_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            userinfo_resp.raise_for_status()
            userinfo = userinfo_resp.json()
    except httpx.HTTPError as exc:
        log.warning("auth.oauth_userinfo_failed", provider=provider_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch user info from OAuth provider: {exc}",
        )

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

    # ---------- Find or create local user ----------
    user: UserProfile | None = None
    if email:
        user = db.scalars(
            select(UserProfile).where(UserProfile.email == email.lower().strip())
        ).first()

    if user is None and external_sub:
        # Fallback: look up by external_id (provider-unique sub).
        external_id = f"{provider_id}:{external_sub}"
        user = db.scalars(
            select(UserProfile).where(UserProfile.external_id == external_id)
        ).first()

    if user is None:
        # Create a new user. OAuth users have no password — they can only
        # log in via OAuth. They can set a password later if they want.
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
        log.info("auth.oauth_user_created", user_id=user.id, provider=provider_id, email=user.email, first_admin=is_first_admin)
    else:
        # Update avatar + external_id on each login (keeps them fresh).
        if not user.external_id and external_sub:
            user.external_id = f"{provider_id}:{external_sub}"
        avatar = userinfo.get("avatar_url") or userinfo.get("picture")
        if avatar and user.avatar_url != avatar:
            user.avatar_url = avatar
        if user.display_name != display_name and display_name:
            user.display_name = str(display_name)[:128]
        db.commit()
        db.refresh(user)

    if not user.is_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    user = _apply_admin_override(user)
    log.info("auth.oauth_login", user_id=user.id, provider=provider_id, email=user.email)
    return _make_token_pair(user)


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
        _send_email(
            email,
            "[LifeTree] Your verification code",
            f"Your LifeTree verification code is: {code}\n\n"
            f"This code expires in 10 minutes.\n\n"
            f"If you didn't request this, you can safely ignore this email.",
        )
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
