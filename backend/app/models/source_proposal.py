"""SourceProposal model — LLM-suggested information sources pending user review.

Per project plan P1 信源自动发现: the discovery service asks the LLM to
propose authoritative sources (official gazettes, news, stats APIs, forums)
for a goal. Each proposal is persisted here with a Tavily Extract probe
result so the user can accept (→ promotes to a real ``InformationSource``
with auto_refresh enabled) or reject it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base
from app.models.base import TimestampMixin, UUIDPkMixin
from app.models.types import JSON_DOCUMENT


class SourceProposal(UUIDPkMixin, TimestampMixin, Base):
    """An LLM-proposed information source awaiting user accept/reject.

    Lifecycle: ``proposed`` → ``accepted`` (promoted to InformationSource)
    or ``rejected``. The ``probe_result`` JSONB carries the Tavily Extract
    trial output so the UI can preview liveness and update frequency.
    """

    __tablename__ = "source_proposals"

    goal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("goals.id", ondelete="CASCADE")
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user_profiles.id", ondelete="CASCADE")
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="public")
    # public / official / news / other

    publisher: Mapped[str | None] = mapped_column(String(255), nullable=True)
    proposed_reason: Mapped[str] = mapped_column(Text, nullable=False)

    relevance_score: Mapped[float] = mapped_column(Float, default=0.5)
    credibility_hint: Mapped[str] = mapped_column(String(16), default="pending")
    # high / medium / low / pending

    status: Mapped[str] = mapped_column(String(16), default="proposed")
    # proposed / accepted / rejected

    # Tavily Extract trial result: {ok, title_preview, update_frequency_hint, content_length}
    probe_result: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)

    def __repr__(self) -> str:
        return f"<SourceProposal {self.status}:{self.title[:40]}>"


Index("ix_source_proposals_goal", SourceProposal.goal_id)
Index("ix_source_proposals_user", SourceProposal.user_id)
Index("ix_source_proposals_status", SourceProposal.status)
