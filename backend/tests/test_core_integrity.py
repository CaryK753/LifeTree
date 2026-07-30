from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.exceptions import NotFoundError, ValidationFailedError
from app.models.action import Action
from app.models.event import InformationSource
from app.models.goal import Goal, Pathway, Requirement
from app.schemas.api import ActionCreate
from app.services.action_integrity import (
    get_user_action,
    set_action_status,
    validate_action_links,
)
from app.services.backup import BackupService
from app.services.cross_validation import CrossValidationService
from app.services.source_discovery import SourceDiscoveryService


class _Session:
    def __init__(self, objects=None, scalar_result=None):
        self.objects = objects or {}
        self.scalar_result = scalar_result
        self.added = []
        self.statement = ""

    def get(self, model, object_id):
        return self.objects.get((model, object_id))

    def scalar(self, statement):
        self.statement = str(statement)
        return self.scalar_result

    def scalars(self, statement):
        self.statement = str(statement)
        return iter([])

    def add(self, value):
        self.added.append(value)


class _Savepoint:
    def __init__(self):
        self.is_active = True
        self.committed = False
        self.rolled_back = False

    def commit(self):
        self.committed = True
        self.is_active = False

    def rollback(self):
        self.rolled_back = True
        self.is_active = False


class _ImportSession(_Session):
    def __init__(self):
        super().__init__()
        self.savepoints = []

    def begin_nested(self):
        savepoint = _Savepoint()
        self.savepoints.append(savepoint)
        return savepoint

    def flush(self):
        pass


class _CrossSession(_Session):
    def __init__(self, relationships, sources):
        super().__init__()
        self.relationships = relationships
        self.sources = sources
        self.scalar_calls = 0
        self.committed = False

    def scalars(self, statement):
        self.statement = str(statement)
        self.scalar_calls += 1
        return iter(self.relationships if self.scalar_calls == 1 else [])

    def get(self, model, object_id):
        if model is InformationSource:
            return self.sources.get(object_id)
        return None

    def commit(self):
        self.committed = True


def test_action_rejects_cross_goal_requirement() -> None:
    goal = SimpleNamespace(id="goal-1", user_id="user-1")
    other_pathway = SimpleNamespace(id="path-2", goal_id="goal-2")
    requirement = SimpleNamespace(id="req-2", pathway_id="path-2")
    db = _Session(
        {
            (Goal, "goal-1"): goal,
            (Pathway, "path-2"): other_pathway,
            (Requirement, "req-2"): requirement,
        }
    )

    with pytest.raises(ValidationFailedError):
        validate_action_links(
            db,
            user_id="user-1",
            goal_id="goal-1",
            requirement_id="req-2",
        )


def test_action_owner_check_does_not_grant_admin_write_access() -> None:
    action = SimpleNamespace(id="action-1", user_id="user-2")
    db = _Session({(Action, "action-1"): action})

    with pytest.raises(NotFoundError):
        get_user_action(db, "action-1", "admin-user")


def test_invalid_completion_does_not_mutate_action() -> None:
    action = SimpleNamespace(
        status="pending",
        completed_at=None,
        requirement_id="req-2",
        goal_id="goal-1",
    )
    db = _Session()

    with pytest.raises(ValidationFailedError):
        set_action_status(db, action, "completed")

    assert action.status == "pending"
    assert action.completed_at is None


def test_action_numeric_inputs_are_bounded() -> None:
    with pytest.raises(ValidationError):
        ActionCreate(goal_id="goal-1", title="Task", cost=1.1)
    with pytest.raises(ValidationError):
        ActionCreate(goal_id="goal-1", title="Task", expected_prob_lift=-0.1)


def test_cross_validation_query_is_tenant_scoped() -> None:
    db = _Session()
    CrossValidationService(db, "user-1").detect_conflicts()

    assert "JOIN information_sources" in db.statement
    assert "information_sources.user_id" in db.statement


def test_conflict_resolution_penalizes_only_disagreeing_sources() -> None:
    relationships = [
        SimpleNamespace(source_id="winner", object_id="value-a", object_type="Event"),
        SimpleNamespace(source_id="supporter", object_id="value-a", object_type="Event"),
        SimpleNamespace(source_id="loser", object_id="value-b", object_type="Event"),
    ]
    sources = {
        source_id: SimpleNamespace(
            id=source_id,
            user_id="user-1",
            credibility_score=0.5,
        )
        for source_id in ("winner", "supporter", "loser")
    }
    db = _CrossSession(relationships, sources)

    result = CrossValidationService(db, "user-1").resolve_conflict(
        "subject-1", "AFFECTS", "winner"
    )

    assert result["ok"] is True
    assert sources["winner"].credibility_score == pytest.approx(0.6)
    assert sources["supporter"].credibility_score == pytest.approx(0.5)
    assert sources["loser"].credibility_score == pytest.approx(0.4)
    assert db.committed


def test_source_proposal_query_is_tenant_scoped() -> None:
    db = _Session()
    SourceDiscoveryService(db, llm_client=object()).list_proposals("user-1")

    assert "source_proposals.user_id" in db.statement


def test_backup_entity_failure_rolls_back_only_its_savepoint(monkeypatch) -> None:
    db = _ImportSession()
    service = BackupService(db)
    summary = {
        "imported": {"sources": 0},
        "skipped": 0,
        "errors": [],
    }

    def fields(data, _model):
        if data["id"] == "bad":
            raise ValueError("invalid source")
        return {"title": data["title"]}

    monkeypatch.setattr(service, "_pick_fields", fields)
    service._import_sources(
        "user-1",
        [{"id": "good", "title": "Good"}, {"id": "bad", "title": "Bad"}],
        {"source:good": "new-good", "source:bad": "new-bad"},
        summary,
    )

    assert summary["imported"]["sources"] == 1
    assert len(summary["errors"]) == 1
    assert db.savepoints[0].committed
    assert db.savepoints[1].rolled_back
