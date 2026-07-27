"""WebAuthn / FIDO2 passkey service.

Thin wrapper around the ``webauthn`` PyPI package that adapts its API to
LifeTree's persistence layer. Handles:

  * Building registration / authentication options
  * Verifying registration responses (storing new credentials)
  * Verifying authentication assertions (issuing JWT tokens)
  * Tracking the server-side signature counter for replay-attack detection

The challenge bytes are stored in Redis with a short TTL so the
verification step can validate the challenge returned by the client.

Origin / RP ID resolution:
  * ``RP_ID`` defaults to the host of ``APP_PUBLIC_URL`` (or
    ``SERVICE_ADDRESS``), falling back to ``localhost`` for local dev.
  * ``RP_ORIGIN`` is the full origin (scheme + host + port) the browser
    will use when calling ``navigator.credentials.*``. WebAuthn strictly
    validates this against the actual request origin.
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlparse

from app.core.logging import get_logger
from app.db.redis import get_redis
from app.llm.registry import get_service_address

log = get_logger(__name__)


def _rp_id() -> str:
    """Return the WebAuthn RP ID (domain only, no scheme/port).

    Priority:
      1. ``WEBAUTHN_RP_ID`` env var (explicit override)
      2. Host of ``service_address`` (admin-configured public URL)
      3. Host of ``APP_PUBLIC_URL`` env var
      4. ``localhost`` (local dev fallback — only works on localhost)
    """
    explicit = os.environ.get("WEBAUTHN_RP_ID", "").strip()
    if explicit:
        return explicit
    svc = get_service_address().strip()
    if svc:
        host = urlparse(svc).hostname
        if host:
            return host
    public = os.environ.get("APP_PUBLIC_URL", "").strip()
    if public:
        host = urlparse(public).hostname
        if host:
            return host
    return "localhost"


def _rp_name() -> str:
    """Return a human-readable RP name shown in the OS passkey prompt."""
    return os.environ.get("WEBAUTHN_RP_NAME", "LifeTree").strip() or "LifeTree"


def _rp_origin() -> str:
    """Return the full origin (scheme://host[:port]) the browser will use.

    Defaults to ``http://localhost:13000`` for local dev.
    """
    svc = get_service_address().strip()
    if svc and "://" in svc:
        return svc.rstrip("/")
    public = os.environ.get("APP_PUBLIC_URL", "").strip()
    if public:
        return public.rstrip("/")
    return "http://localhost:13000"


def _expected_origins() -> list[str]:
    """Return all valid origins for WebAuthn verification.

    Includes the primary RP origin plus an optional
    ``WEBAUTHN_EXTRA_ORIGINS`` (comma-separated) for deployments where the
    app is reachable via multiple hostnames (e.g. localhost + LAN IP).
    """
    origins = [_rp_origin()]
    extra = os.environ.get("WEBAUTHN_EXTRA_ORIGINS", "").strip()
    if extra:
        for o in extra.split(","):
            o = o.strip()
            if o and o not in origins:
                origins.append(o)
    return origins


# ---------- Redis challenge store ----------

_CHALLENGE_PREFIX = "webauthn_challenge:"
_CHALLENGE_TTL = 300  # 5 minutes


def _redis_challenge_key(challenge_b64: str) -> str:
    return f"{_CHALLENGE_PREFIX}{challenge_b64}"


def _store_challenge(challenge_b64: str, payload: dict[str, Any]) -> None:
    """Store the challenge + metadata for the verification step."""
    redis = get_redis()
    redis.setex(
        _redis_challenge_key(challenge_b64),
        _CHALLENGE_TTL,
        json.dumps(payload),
    )


def _load_challenge(challenge_b64: str) -> dict[str, Any] | None:
    """Retrieve and consume the stored challenge. Returns None if missing."""
    redis = get_redis()
    raw = redis.get(_redis_challenge_key(challenge_b64))
    if raw is None:
        return None
    # One-shot: delete after read.
    redis.delete(_redis_challenge_key(challenge_b64))
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="ignore")
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


# ---------- Registration (attestation) ----------

def generate_registration_options(
    *,
    user_id: str,
    user_display_name: str,
    exclude_credential_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build a PublicKeyCredentialCreationOptions dict for the client.

    Returns a JSON-serializable dict that the frontend can pass directly
    to ``navigator.credentials.create({ publicKey: ... })``. The challenge
    is stored in Redis so the verify step can validate it.
    """
    from webauthn import generate_registration_options as gen_opts
    from webauthn.helpers import bytes_to_base64url
    from webauthn.helpers.structs import (
        AuthenticatorSelectionCriteria,
        ResidentKeyRequirement,
        UserVerificationRequirement,
    )

    options = gen_opts(
        rp_id=_rp_id(),
        rp_name=_rp_name(),
        user_id=user_id.encode("utf-8"),
        user_name=user_display_name or "user",
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=None,  # exclude_credential_ids handled below
        timeout=_CHALLENGE_TTL * 1000,
    )

    # If we have existing credential ids to exclude, attach them as raw bytes.
    if exclude_credential_ids:
        from webauthn.helpers import base64url_to_bytes
        from webauthn.helpers.structs import PublicKeyCredentialDescriptor

        options.exclude_credentials = [
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(cid))
            for cid in exclude_credential_ids
            if cid
        ]

    challenge_b64 = bytes_to_base64url(options.challenge)
    _store_challenge(challenge_b64, {
        "type": "registration",
        "user_id": user_id,
    })

    # Serialize to JSON-able dict via the library helper. The options
    # object contains bytes fields (challenge, user.id) that need to be
    # base64url-encoded for JSON transport.
    from webauthn.helpers import options_to_json_dict
    return options_to_json_dict(options)


def verify_registration_response(
    *,
    credential: dict[str, Any],
    nickname: str = "",
) -> dict[str, Any]:
    """Verify a registration response from the client.

    Returns a dict with the stored credential fields:
      { credential_id, public_key, sign_count, transports, aaguid,
        device_type, backed_up }

    Raises ValueError on verification failure.
    """
    from webauthn import verify_registration_response as verify_resp
    from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

    # Re-encode the credential as JSON for the library helper.
    credential_json = json.dumps(credential)
    challenge_b64 = credential.get("response", {}).get("clientDataJSON", "")
    if not challenge_b64:
        raise ValueError("Missing clientDataJSON in credential response")

    # Decode the challenge from clientDataJSON.
    try:
        import base64
        client_data_raw = base64.urlsafe_b64decode(challenge_b64 + "==")
        client_data = json.loads(client_data_raw)
        challenge_from_client = client_data.get("challenge", "")
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Failed to decode clientDataJSON: {exc}") from exc

    stored = _load_challenge(challenge_from_client)
    if stored is None:
        raise ValueError("Registration challenge expired or invalid")
    if stored.get("type") != "registration":
        raise ValueError("Challenge type mismatch — expected registration")

    verification = verify_resp(
        credential=credential_json,
        expected_challenge=base64url_to_bytes(challenge_from_client),
        expected_origin=_expected_origins(),
        expected_rp_id=_rp_id(),
    )

    return {
        "credential_id": bytes_to_base64url(verification.credential_id),
        "public_key": bytes_to_base64url(verification.credential_public_key),
        "sign_count": verification.sign_count or 0,
        "transports": list(credential.get("response", {}).get("transports", []) or []),
        "aaguid": str(verification.aaguid),
        # webauthn 3.0.0 renamed these fields:
        #   device_type → credential_device_type
        #   backed_up   → credential_backed_up
        "device_type": str(verification.credential_device_type),
        "backed_up": bool(verification.credential_backed_up),
        "nickname": nickname.strip()[:128] if nickname else "",
    }


# ---------- Authentication (assertion) ----------

def generate_authentication_options(
    *,
    allow_credential_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build a PublicKeyCredentialRequestOptions dict for the client.

    Returns a JSON-serializable dict that the frontend can pass directly
    to ``navigator.credentials.get({ publicKey: ... })``. The challenge
    is stored in Redis so the verify step can validate it.
    """
    from webauthn import generate_authentication_options as gen_opts
    from webauthn.helpers import bytes_to_base64url
    from webauthn.helpers.structs import UserVerificationRequirement

    options = gen_opts(
        rp_id=_rp_id(),
        timeout=_CHALLENGE_TTL * 1000,
        user_verification=UserVerificationRequirement.PREFERRED,
    )

    challenge_b64 = bytes_to_base64url(options.challenge)
    _store_challenge(challenge_b64, {
        "type": "authentication",
    })

    from webauthn.helpers import options_to_json_dict
    return options_to_json_dict(options)


def verify_authentication_response(
    *,
    credential: dict[str, Any],
    stored_credential_id: str,
    stored_public_key: str,
    stored_sign_count: int,
) -> int:
    """Verify an authentication assertion from the client.

    Returns the new sign count to persist. Raises ValueError on failure.
    """
    from webauthn import verify_authentication_response as verify_resp
    from webauthn.helpers import base64url_to_bytes

    credential_json = json.dumps(credential)
    challenge_b64 = credential.get("response", {}).get("clientDataJSON", "")
    if not challenge_b64:
        raise ValueError("Missing clientDataJSON in credential response")

    # Decode the challenge from clientDataJSON.
    try:
        import base64
        client_data_raw = base64.urlsafe_b64decode(challenge_b64 + "==")
        client_data = json.loads(client_data_raw)
        challenge_from_client = client_data.get("challenge", "")
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Failed to decode clientDataJSON: {exc}") from exc

    stored = _load_challenge(challenge_from_client)
    if stored is None:
        raise ValueError("Authentication challenge expired or invalid")
    if stored.get("type") != "authentication":
        raise ValueError("Challenge type mismatch — expected authentication")

    verification = verify_resp(
        credential=credential_json,
        expected_challenge=base64url_to_bytes(challenge_from_client),
        expected_origin=_expected_origins(),
        expected_rp_id=_rp_id(),
        credential_public_key=base64url_to_bytes(stored_public_key),
        credential_current_sign_count=stored_sign_count,
    )

    return verification.new_sign_count
