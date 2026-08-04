"""User-uploaded plugin ORM model.

Stores metadata for plugins uploaded at runtime via ``POST /plugins/upload``.
The plugin source itself lives on disk under
``backend/plugins/user_uploaded/{plugin_id}.py``; this row tracks the
filename, content hash, size, and enabled/disabled state so the API can
list / toggle / soft-delete uploads without re-importing every file.
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPkMixin
from app.models.types import JSON_DOCUMENT


class UserPlugin(UUIDPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A plugin file uploaded by the user (not bundled with the app).

    ``plugin_id`` matches the module filename (without ``.py``) so the
    runner can import it from ``plugins.user_uploaded.<plugin_id>``.
    """

    __tablename__ = "user_plugins"

    # Owner — the user who uploaded this plugin. In single-user mode this
    # is the default user's id. Plugins are per-user so one user's custom
    # scripts don't affect another user's chat experience.
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=True, index=True
    )

    plugin_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    original_filename: Mapped[str] = mapped_column(String(128), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )
    manifest: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)

    def __repr__(self) -> str:
        return f"<UserPlugin {self.plugin_id}>"
