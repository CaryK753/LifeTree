"""User profile and private upload models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.postgres import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPkMixin

if TYPE_CHECKING:
    from app.models.goal import Goal


class RiskTolerance(StrEnum):
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
    role: Mapped[str] = mapped_column(
        String(16), default="user", server_default="user", index=True
    )
    # Whether the user account is enabled. Disabled users can't log in.
    is_enabled: Mapped[bool] = mapped_column(default=True, server_default="true")
    accepted_terms_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    terms_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    privacy_version: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Demographics (free-form JSONB to support multiple scenarios)
    demographics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Preferences
    primary_goal_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("goals.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
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

    goals: Mapped[list[Goal]] = relationship(
        back_populates="user", cascade="all, delete-orphan", foreign_keys="Goal.user_id"
    )
    primary_goal: Mapped[Goal | None] = relationship(
        foreign_keys="UserProfile.primary_goal_id", post_update=True
    )

    def __repr__(self) -> str:
        return f"<UserProfile {self.display_name}>"

    @property
    def has_password(self) -> bool:
        """True if this user has a password set (can log in via /auth/login)."""
        return self.password_hash is not None

    @property
    def lifecycle_stage(self) -> str:
        """Current lifecycle stage: 'planning', 'submitted', 'in_review', 'waiting_eoi'."""
        return (self.demographics or {}).get("lifecycle_stage", "planning")

    @property
    def cruising_mode(self) -> bool:
        """Whether user has enabled Cruising Mode during long waiting periods."""
        return bool((self.demographics or {}).get("cruising_mode", False))

    @property
    def joint_profiles(self) -> list[dict[str, Any]]:
        """Joint applicant / family profile details."""
        return (self.demographics or {}).get("joint_profiles", [])


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

    user: Mapped[UserProfile] = relationship(back_populates="uploads")


# Add reverse relationship on UserProfile
UserProfile.uploads = relationship(
    "UserUpload", back_populates="user", cascade="all, delete-orphan"
)


Index("ix_user_uploads_user", UserUpload.user_id)
