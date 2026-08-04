"""User memory entries — the unbounded "remember this" channel.

Per project plan §4.4, the user profile holds a fixed set of typed fields
(demographics, preferences). Memories are the *unbounded* complement: any
free-form fact the user mentions in chat ("I have a 3-year-old daughter",
"I work at Acme", "I'm allergic to shellfish", "I previously lived in
Vancouver") that the advisor LLM should remember and reason with.

Each memory is a short string with:
- a category (auto-inferred by the LLM or set explicitly)
- importance 0..1 (LLM assigns)
- optional source (chat / upload / plugin)
- soft delete + timestamp

Memories are exposed both as a tool the LLM can call (`remember`,
`update_memory`, `forget`) and as a REST endpoint for the profile page to
list / edit / delete them.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, UUIDPkMixin
from app.models.types import JSON_DOCUMENT


class UserMemory(UUIDPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A single remembered fact about a user.

    Examples:
        {"category": "family", "content": "Has a 3-year-old daughter"}
        {"category": "career", "content": "Software engineer at Acme (2021-)"}
        {"category": "health", "content": "Allergic to shellfish"}
    """

    __tablename__ = "user_memories"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user_profiles.id", ondelete="CASCADE"), index=True
    )

    # Free-form short statement. Keep it small (<500 chars) for prompt-friendly
    # inclusion in advisor context.
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Coarse category for filtering / display. Examples: 'family', 'career',
    # 'health', 'finance', 'education', 'location', 'preference', 'goal',
    # 'constraint', 'other'. LLM infers if not provided.
    category: Mapped[str] = mapped_column(String(32), default="other", index=True)

    # Importance 0..1 — used to prioritize which memories to surface in the
    # advisor system prompt when the list grows long.
    importance: Mapped[float] = mapped_column(Float, default=0.5)

    # Where this memory came from.
    # 'chat' = LLM extracted it from a chat turn
    # 'manual' = user typed it in the profile page
    # 'upload' = derived from an uploaded document
    # 'plugin' = derived from a plugin run
    source: Mapped[str] = mapped_column(String(16), default="chat")

    # Optional structured payload (e.g. {"date": "2024-03-15", "amount": 50000})
    meta: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)


Index("ix_user_memories_user_category", UserMemory.user_id, UserMemory.category)
Index("ix_user_memories_importance", UserMemory.importance.desc())
