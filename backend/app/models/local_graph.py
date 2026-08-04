"""Local-only graph projection tables, excluded from server Alembic metadata."""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Float, Index, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class LocalGraphBase(DeclarativeBase):
    pass


class LocalGraphNode(LocalGraphBase):
    __tablename__ = "local_graph_nodes"

    node_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    node_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    properties: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class LocalGraphEdge(LocalGraphBase):
    __tablename__ = "local_graph_edges"
    __table_args__ = (
        UniqueConstraint("source_id", "relation", "target_id", name="uq_local_graph_edge"),
    )

    edge_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    relation: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    weight: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    properties: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


Index("ix_local_graph_edge_pair", LocalGraphEdge.source_id, LocalGraphEdge.target_id)

__all__ = ["LocalGraphBase", "LocalGraphEdge", "LocalGraphNode"]
