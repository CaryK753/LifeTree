"""User ↔ OAuth provider binding model.

A single user can bind multiple OAuth providers (GitHub + Google + GitLab, …)
to their account. The ``user_profiles.external_id`` column is kept for
backward compatibility with the OAuth login-creation flow; this table is
the source of truth for the bind/unbind flow on the settings page.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base
from app.models.base import UUIDPkMixin


class UserOAuthLink(UUIDPkMixin, Base):
    """A binding between a user and an OAuth provider's external account.

    ``provider_id`` matches ``OAuthProvider.id`` (stored in app_config).
    ``external_sub`` is the provider-unique subject id (``sub`` / ``id``
    field from the provider's userinfo response).
    """

    __tablename__ = "user_oauth_links"
    __table_args__ = (
        # One binding per provider per user.
        UniqueConstraint("user_id", "provider_id", name="uq_oauth_link_user_provider"),
        # One user per provider account (prevents two LifeTree users from
        # binding the same GitHub/Google identity).
        UniqueConstraint("provider_id", "external_sub", name="uq_oauth_link_provider_sub"),
    )

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    external_sub: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()",
    )

    def __repr__(self) -> str:
        return f"<UserOAuthLink user={self.user_id} provider={self.provider_id}>"
