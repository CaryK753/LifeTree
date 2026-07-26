"""Shared SQLAlchemy mixins for all ORM models."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UUIDPkMixin:
    """UUID primary key mixin."""

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )


class TimestampMixin:
    """created_at / updated_at mixin."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=_utcnow,
        onupdate=_utcnow,
    )


class SoftDeleteMixin:
    """Soft-delete mixin; rows are flagged rather than removed."""

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
