"""add chat_streams table

Revision ID: s2f3a4b5c6d7
Revises: r1e2f3a4b5c6
Create Date: 2026-08-07 23:00:00.000000

Implements background chat execution: the ``chat_streams`` table stores
one row per AI response generation. The agent runs in a background
``asyncio.Task`` (or Celery worker in server mode), writing SSE events
to the ``events`` JSON column as it produces tokens / tool calls.

The SSE endpoint ``GET /chat/stream/{stream_id}/events`` replays events
from any offset, enabling reconnect after a network drop or browser
close. The frontend never loses a response — it can always restore the
full (partial or complete) result.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision: str = "s2f3a4b5c6d7"
down_revision: Union[str, None] = "r1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_streams",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("user_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="running"),
        sa.Column("goal_id", sa.String(length=36), nullable=True),
        sa.Column("scenario_id", sa.String(length=36), nullable=True),
        sa.Column("model_id", sa.String(length=36), nullable=True),
        sa.Column("user_message_preview", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "events",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("result_content", sa.Text(), nullable=True),
        sa.Column(
            "result_tool_calls",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_streams_user_status", "chat_streams", ["user_id", "status"])
    op.create_index("ix_chat_streams_created_at", "chat_streams", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_chat_streams_created_at", table_name="chat_streams")
    op.drop_index("ix_chat_streams_user_status", table_name="chat_streams")
    op.drop_table("chat_streams")
