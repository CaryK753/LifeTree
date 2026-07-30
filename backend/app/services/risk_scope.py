"""Tenant scope, ownership, and identity helpers for risk factors."""

from __future__ import annotations

import hashlib
import re
import unicodedata

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.goal import RiskFactor

_SEPARATOR_RE = re.compile(r"[\W_]+", re.UNICODE)


def risk_scope_clause(user_id: str):
    """Return the SQL clause for global templates plus one user's risks."""
    return or_(RiskFactor.user_id.is_(None), RiskFactor.user_id == user_id)


def get_visible_risk(db: Session, risk_id: str, user_id: str) -> RiskFactor:
    risk = db.scalar(
        select(RiskFactor).where(
            RiskFactor.id == risk_id,
            RiskFactor.deleted_at.is_(None),
            risk_scope_clause(user_id),
        )
    )
    if risk is None:
        raise NotFoundError("Risk factor not found")
    return risk


def get_mutable_risk(
    db: Session,
    risk_id: str,
    *,
    user_id: str,
    is_admin: bool,
) -> RiskFactor:
    """Allow owners to mutate personal risks and admins to mutate globals."""
    risk = db.get(RiskFactor, risk_id)
    if risk is None or risk.deleted_at is not None:
        raise NotFoundError("Risk factor not found")
    if risk.user_id == user_id or (risk.user_id is None and is_admin):
        return risk
    raise NotFoundError("Risk factor not found")


def risk_identity_key(name: str, risk_type: str, region: str | None) -> str:
    """Build a stable identity for equivalent user-created risks."""
    normalized_name = unicodedata.normalize("NFKC", name).casefold().strip()
    normalized_name = _SEPARATOR_RE.sub("", normalized_name)
    normalized_type = unicodedata.normalize("NFKC", risk_type).casefold().strip()
    normalized_region = unicodedata.normalize("NFKC", region or "").casefold().strip()
    raw = f"{normalized_type}\0{normalized_region}\0{normalized_name}"
    return hashlib.sha256(raw.encode()).hexdigest()


def lock_risk_identity(db: Session, user_id: str, identity_key: str) -> None:
    """Serialize equivalent personal-risk creation on PostgreSQL."""
    if db.get_bind().dialect.name != "postgresql":
        return
    digest = hashlib.blake2b(
        f"{user_id}\0{identity_key}".encode(), digest_size=8
    ).digest()
    lock_key = int.from_bytes(digest, byteorder="big", signed=True)
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})


__all__ = [
    "get_mutable_risk",
    "get_visible_risk",
    "lock_risk_identity",
    "risk_identity_key",
    "risk_scope_clause",
]
