"""Chat stream model for background chat execution.

A ``ChatStream`` represents one AI response generation that runs in the
background, decoupled from the SSE connection. This means:

1. The user can close the browser tab and the generation continues.
2. Reopening the tab restores the full response (partial or complete).
3. The frontend reconnects via ``GET /chat/stream/{stream_id}/events``.

Events are persisted as a JSON array so the SSE endpoint can replay them
from any offset — essential for reconnect after a network drop.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.postgres import Base
from app.models.base import TimestampMixin, UUIDPkMixin


class ChatStream(Base, UUIDPkMixin, TimestampMixin):
    """Persisted chat-generation stream."""

    __tablename__ = "chat_streams"

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Status: running → completed | failed | cancelled
    status: Mapped[str] = mapped_column(String(32), default="running", nullable=False)

    # Optional context refs
    goal_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    scenario_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # The user's last message (for display in task lists / notifications).
    # We don't store the full conversation history here — the frontend
    # already has it in localStorage and sends it with every request.
    user_message_preview: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # SSE events list. Each item: {seq, type, data}.
    # Grows as the agent produces tokens / tool calls.
    events: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)

    # The final assembled AI message content (for quick restore without
    # replaying every token event).
    result_content: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Tool calls extracted from the final message (for UI restore).
    result_tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_chat_streams_user_status", "user_id", "status"),
        Index("ix_chat_streams_created_at", "created_at"),
    )


__all__ = ["ChatStream"]
