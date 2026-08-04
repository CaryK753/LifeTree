from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.postgres import Base
from app.models.event import Event
from app.models.user import UserProfile
from app.services.runtime.vector_search import search_event_vectors


def test_local_vector_search_ranks_cosine_similarity() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = UserProfile(display_name="Vector User")
        db.add(user)
        db.flush()
        db.add_all(
            [
                Event(
                    user_id=user.id,
                    subject="Closest",
                    action="match",
                    embedding=[1.0, 0.0],
                ),
                Event(
                    user_id=user.id,
                    subject="Farther",
                    action="match",
                    embedding=[0.5, 0.5],
                ),
                Event(
                    user_id=user.id,
                    subject="Wrong dimension",
                    action="skip",
                    embedding=[1.0, 0.0, 0.0],
                ),
            ]
        )
        db.commit()

        results = search_event_vectors(
            db,
            user_id=user.id,
            query_vector=[1.0, 0.0],
            limit=10,
        )

    assert [item["title"] for item in results] == [
        "Closest match",
        "Farther match",
    ]


def test_local_vector_search_ignores_zero_query() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        assert (
            search_event_vectors(
                db,
                user_id="user",
                query_vector=[],
                limit=10,
            )
            == []
        )
