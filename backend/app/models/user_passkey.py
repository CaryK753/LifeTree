"""User passkey (WebAuthn) credential model.

Stores registered passkey credentials so users can authenticate without a
password. A single user may bind multiple passkeys (e.g. one per device:
laptop Touch ID, phone Face ID, hardware YubiKey, …).

Schema:
  - id                 UUID primary key
  - user_id            FK → user_profiles.id (CASCADE)
  - credential_id      Base64url-encoded credential id (unique)
  - public_key         Base64url-encoded COSE-encoded public key
  - sign_count         Server-side replay-attack counter (FIDO §6.1.1)
  - transports         List of allowed transports (internal/usb/nfc/ble/hybrid)
  - aaguid             Authenticator Attestation GUID (identifies model)
  - device_type        'singleDevice' | 'multiDevice' (FIDO Passkey)
  - nickname           Human-readable label set by the user
  - created_at         Timestamp
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base
from app.models.base import UUIDPkMixin


class UserPasskey(UUIDPkMixin, Base):
    """A registered WebAuthn passkey credential owned by a user."""

    __tablename__ = "user_passkeys"

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Base64url-encoded credential id. Unique so the same credential can't
    # be bound to two LifeTree users.
    credential_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    # Base64url-encoded COSE public key (CBOR-encoded).
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    # Server-side signature counter — starts at 0, bumped on each successful
    # assertion (FIDO Client to Authenticator Protocol §6.1.1).
    sign_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Allowed transports (e.g. ["internal", "hybrid"]). Empty list = unknown.
    transports: Mapped[list[str]] = mapped_column(JSONB, default=list)
    # Authenticator Attestation GUID — identifies the authenticator model
    # (e.g. YubiKey 5C, MacBook Touch ID, …). May be all-zeros for
    # attestation-less registrations.
    aaguid: Mapped[str] = mapped_column(String(64), default="00000000-0000-0000-0000-000000000000")
    # 'singleDevice' (device-bound) or 'multiDevice' (synced passkey).
    device_type: Mapped[str] = mapped_column(String(32), default="multiDevice")
    # Backed up to a synced passkey provider (iCloud Keychain, Google
    # Password Manager, 1Password, …). FIDO "backed_up" flag.
    backed_up: Mapped[bool] = mapped_column(default=False)
    # Human-readable label set by the user when registering the passkey.
    nickname: Mapped[str] = mapped_column(String(128), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()",
    )

    def __repr__(self) -> str:
        return f"<UserPasskey user={self.user_id} nickname={self.nickname!r}>"
