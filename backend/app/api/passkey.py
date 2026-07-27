"""Passkey (WebAuthn) authentication endpoints.

Flow:
  1. Registration (bound to current user — requires auth):
       POST /auth/passkey/registration/options  → PublicKeyCredentialCreationOptions
       POST /auth/passkey/registration/verify   → { ok, passkey }

  2. Authentication (no auth — replaces password login):
       POST /auth/passkey/auth/options          → PublicKeyCredentialRequestOptions
       POST /auth/passkey/auth/verify           → AuthTokenResponse (JWT pair)

  3. Management (bound to current user — requires auth):
       GET    /auth/passkeys                    → list[PasskeyRead]
       DELETE /auth/passkeys/{id}               → { ok }

All endpoints except the auth-options / auth-verify ones are gated behind
``passkey_login_enabled`` — the admin must turn on the flag in /admin
before users can register or use passkeys.

Registration is only available to authenticated users (you can't bind a
passkey to a non-existent account). Authentication is open to anyone —
but only valid passkeys signed by a registered authenticator will succeed.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.tenant import CurrentUser, _apply_admin_override
from app.db.postgres import get_db
from app.llm.registry import get_passkey_login_enabled
from app.models.user import UserProfile
from app.models.user_passkey import UserPasskey
from app.schemas.entities import UserProfileRead
from app.services import webauthn as webauthn_service

log = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth", "passkey"])


# ---------- Schemas ----------

class PasskeyRegistrationOptionsRequest(BaseModel):
    """Empty payload — the user is inferred from the auth token."""


class PasskeyRegistrationOptionsResponse(BaseModel):
    """PublicKeyCredentialCreationOptions — JSON-serializable.

    The exact shape is determined by the webauthn library; we just pass it
    through as a generic dict so the frontend can hand it directly to
    ``navigator.credentials.create({ publicKey: ... })``.
    """

    options: dict


class PasskeyRegistrationVerifyRequest(BaseModel):
    """Verify a registration response from the client."""

    credential: dict = Field(..., description="PublicKeyCredential JSON from navigator.credentials.create()")
    nickname: str = Field("", max_length=128, description="Optional label for the passkey")


class PasskeyRead(BaseModel):
    """A passkey owned by the current user."""

    id: str
    nickname: str
    device_type: str
    backed_up: bool
    transports: list[str]
    aaguid: str
    created_at: str


class PasskeyRegistrationVerifyResponse(BaseModel):
    ok: bool
    passkey: PasskeyRead


class PasskeyAuthOptionsResponse(BaseModel):
    """PublicKeyCredentialRequestOptions — JSON-serializable."""

    options: dict


class PasskeyAuthVerifyRequest(BaseModel):
    """Verify an authentication assertion from the client."""

    credential: dict = Field(..., description="PublicKeyCredential JSON from navigator.credentials.get()")


class AuthTokenResponse(BaseModel):
    """JWT pair returned after successful passkey login."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserProfileRead


# ---------- Helpers ----------

def _require_passkey_enabled() -> None:
    """Block all passkey endpoints when the admin flag is off."""
    if not get_passkey_login_enabled():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Passkey login is not enabled. Contact the administrator.",
        )


def _passkey_to_read(pk: UserPasskey) -> PasskeyRead:
    return PasskeyRead(
        id=pk.id,
        nickname=pk.nickname or "",
        device_type=pk.device_type,
        backed_up=bool(pk.backed_up),
        transports=list(pk.transports or []),
        aaguid=pk.aaguid or "00000000-0000-0000-0000-000000000000",
        created_at=pk.created_at.isoformat() if pk.created_at else "",
    )


def _make_token_pair(user: UserProfile) -> dict:
    """Build access + refresh tokens + serializable user payload."""
    from app.core.security import create_access_token, create_refresh_token

    return {
        "access_token": create_access_token(user.id, role=user.role),
        "refresh_token": create_refresh_token(user.id),
        "token_type": "bearer",
        "user": user,
    }


# ---------- Registration (current user) ----------

@router.post(
    "/passkey/registration/options",
    response_model=PasskeyRegistrationOptionsResponse,
)
def passkey_registration_options(
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> PasskeyRegistrationOptionsResponse:
    """Build a PublicKeyCredentialCreationOptions for the current user.

    Excludes any credential ids already bound to this user so the
    authenticator doesn't re-register the same passkey.
    """
    _require_passkey_enabled()
    existing_ids = db.scalars(
        select(UserPasskey.credential_id).where(UserPasskey.user_id == user.id)
    ).all()
    options = webauthn_service.generate_registration_options(
        user_id=user.id,
        user_display_name=user.display_name,
        exclude_credential_ids=list(existing_ids),
    )
    return PasskeyRegistrationOptionsResponse(options=options)


@router.post(
    "/passkey/registration/verify",
    response_model=PasskeyRegistrationVerifyResponse,
)
def passkey_registration_verify(
    payload: PasskeyRegistrationVerifyRequest,
    user: CurrentUser,
    db: Session = Depends(get_db),
) -> PasskeyRegistrationVerifyResponse:
    """Verify the registration response and persist the new credential."""
    _require_passkey_enabled()
    try:
        verified = webauthn_service.verify_registration_response(
            credential=payload.credential,
            nickname=payload.nickname,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    # Check that this credential isn't already bound to another user.
    existing = db.scalars(
        select(UserPasskey).where(
            UserPasskey.credential_id == verified["credential_id"]
        )
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This passkey is already registered to another account",
        )

    pk = UserPasskey(
        user_id=user.id,
        credential_id=verified["credential_id"],
        public_key=verified["public_key"],
        sign_count=verified["sign_count"],
        transports=verified["transports"],
        aaguid=verified["aaguid"],
        device_type=verified["device_type"],
        backed_up=verified["backed_up"],
        nickname=verified["nickname"],
    )
    db.add(pk)
    db.commit()
    db.refresh(pk)
    log.info(
        "passkey.registered",
        user_id=user.id,
        passkey_id=pk.id,
        device_type=pk.device_type,
        backed_up=pk.backed_up,
    )
    return PasskeyRegistrationVerifyResponse(ok=True, passkey=_passkey_to_read(pk))


# ---------- Authentication (no auth required) ----------

@router.post(
    "/passkey/auth/options",
    response_model=PasskeyAuthOptionsResponse,
)
def passkey_auth_options() -> PasskeyAuthOptionsResponse:
    """Build a PublicKeyCredentialRequestOptions for passwordless login.

    No allow_credentials list is sent — this enables discoverable
    credentials (resident keys) so the user doesn't have to type their
    email first. The authenticator returns whichever passkey the user
    picks; the server then looks up the user by credential id.
    """
    _require_passkey_enabled()
    options = webauthn_service.generate_authentication_options()
    return PasskeyAuthOptionsResponse(options=options)


@router.post(
    "/passkey/auth/verify",
    response_model=AuthTokenResponse,
)
def passkey_auth_verify(
    payload: PasskeyAuthVerifyRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Verify the authentication assertion and issue a JWT pair.

    The credential id in the response is used to look up the stored
    public key + sign count. After verification, the sign count is
    bumped to detect replay attacks.
    """
    _require_passkey_enabled()

    # Extract the raw credential id from the response.
    raw_id = payload.credential.get("id", "")
    if not raw_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing credential id",
        )

    pk = db.scalars(
        select(UserPasskey).where(UserPasskey.credential_id == raw_id)
    ).first()
    if pk is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown passkey credential",
        )

    try:
        new_count = webauthn_service.verify_authentication_response(
            credential=payload.credential,
            stored_credential_id=pk.credential_id,
            stored_public_key=pk.public_key,
            stored_sign_count=pk.sign_count or 0,
        )
    except ValueError as exc:
        log.warning(
            "passkey.auth_failed",
            user_id=pk.user_id,
            passkey_id=pk.id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        )

    # Bump the sign count — if the authenticator reports a higher count
    # than we stored, we update ours; if it reports a lower or equal
    # count, the verify step above already raised (replay attack).
    pk.sign_count = new_count
    db.commit()

    user = db.get(UserProfile, pk.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found for passkey",
        )
    if not user.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account disabled",
        )

    user = _apply_admin_override(user)
    log.info("passkey.login", user_id=user.id, passkey_id=pk.id)
    return _make_token_pair(user)


# ---------- Management (current user) ----------

@router.get("/passkeys", response_model=list[PasskeyRead])
def list_passkeys(user: CurrentUser, db: Session = Depends(get_db)) -> list[PasskeyRead]:
    """List the current user's registered passkeys."""
    _require_passkey_enabled()
    pks = db.scalars(
        select(UserPasskey)
        .where(UserPasskey.user_id == user.id)
        .order_by(UserPasskey.created_at)
    ).all()
    return [_passkey_to_read(pk) for pk in pks]


@router.delete("/passkeys/{passkey_id}")
def delete_passkey(
    passkey_id: str, user: CurrentUser, db: Session = Depends(get_db)
) -> dict:
    """Delete a passkey by id. Only the owner can delete their own passkeys."""
    _require_passkey_enabled()
    pk = db.get(UserPasskey, passkey_id)
    if pk is None or pk.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Passkey not found",
        )
    db.delete(pk)
    db.commit()
    log.info("passkey.deleted", user_id=user.id, passkey_id=pk.id)
    return {"ok": True}


__all__ = ["router"]
