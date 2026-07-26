"""User profile and private upload models."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any

from sqlalchemy import Date, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.postgres import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPkMixin


class RiskTolerance(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class UserProfile(UUIDPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """User profile: demographics, goal preferences, risk tolerance, behavior tags."""

    __tablename__ = "user_profiles"

    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    # Avatar: stored as a data URL (base64-encoded image) for single-user
    # simplicity. Keeps the column narrow (Text) and avoids MinIO coupling.
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---------- Multi-user auth fields ----------
    # bcrypt-hashed password. Null for legacy / pre-existing users created
    # before auth was enabled — those users can't log in until an admin
    # sets a password (or they go through a reset flow).
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # "admin" | "user". Admins can access /admin/* endpoints and manage
    # global config. Role is also enforced via env override
    # (LIFETREE_ADMIN_USER_IDS) so a user can be promoted without DB edits.
    role: Mapped[str] = mapped_column(String(16), default="user", server_default="user")
    # Whether the user account is enabled. Disabled users can't log in.
    is_enabled: Mapped[bool] = mapped_column(default=True, server_default="true")

    # Demographics (free-form JSONB to support multiple scenarios)
    demographics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Preferences
    primary_goal_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("goals.id", ondelete="SET NULL"), nullable=True
    )
    preferred_pathway_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    priority_factors: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    risk_tolerance: Mapped[str] = mapped_column(
        String(16), default="medium"
    )

    # Behavior & progress (updated by profiling service)
    progress: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    implicit_tags: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Notification preferences
    notify_channels: Mapped[dict[str, bool]] = mapped_column(JSONB, default=dict)
    quiet_hours: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    goals: Mapped[list["Goal"]] = relationship(  # type: ignore[name-defined]
        back_populates="user", cascade="all, delete-orphan", foreign_keys="Goal.user_id"
    )
    primary_goal: Mapped["Goal | None"] = relationship(  # type: ignore[name-defined]
        foreign_keys="UserProfile.primary_goal_id", post_update=True
    )

    def __repr__(self) -> str:
        return f"<UserProfile {self.display_name}>"


class UserUpload(UUIDPkMixin, TimestampMixin, Base):
    """Private information uploaded by user (PDF, screenshot, email forward, etc.)."""

    __tablename__ = "user_uploads"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user_profiles.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)  # MinIO key
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(nullable=True)

    # User credibility assessment
    user_credibility: Mapped[str] = mapped_column(String(16), default="pending")
    # 'pending' | 'reliable' | 'questionable'

    # Extracted raw text & metadata
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    legal_acknowledged: Mapped[bool] = mapped_column(default=False)

    user: Mapped["UserProfile"] = relationship(back_populates="uploads")  # type: ignore[name-defined]


# Add reverse relationship on UserProfile
UserProfile.uploads = relationship(
    "UserUpload", back_populates="user", cascade="all, delete-orphan"
)


Index("ix_user_uploads_user", UserUpload.user_id)
