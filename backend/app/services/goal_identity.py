"""Goal identity helpers used by REST and advisor creation paths."""

from __future__ import annotations

import hashlib
import re
import unicodedata

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.goal import Goal


_SEPARATOR_RE = re.compile(r"[\W_]+", re.UNICODE)


def normalize_goal_title(title: str) -> str:
    """Return a stable comparison key without changing the displayed title."""
    normalized = unicodedata.normalize("NFKC", title).casefold().strip()
    return _SEPARATOR_RE.sub("", normalized)


def lock_goal_identity(db: Session, user_id: str, title: str) -> None:
    """Serialize equal-title creation transactions on PostgreSQL."""
    if db.get_bind().dialect.name != "postgresql":
        return
    digest = hashlib.blake2b(
        f"{user_id}\0{normalize_goal_title(title)}".encode(), digest_size=8
    ).digest()
    lock_key = int.from_bytes(digest, byteorder="big", signed=True)
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})


def find_equivalent_goal(db: Session, user_id: str, title: str) -> Goal | None:
    """Find a live goal whose normalized title matches ``title``."""
    identity = normalize_goal_title(title)
    if not identity:
        return None
    candidates = db.scalars(
        select(Goal)
        .where(
            Goal.user_id == user_id,
            Goal.deleted_at.is_(None),
            Goal.status != "abandoned",
        )
        .order_by(Goal.created_at.desc())
    )
    return next(
        (goal for goal in candidates if normalize_goal_title(goal.title) == identity),
        None,
    )


__all__ = ["find_equivalent_goal", "lock_goal_identity", "normalize_goal_title"]
