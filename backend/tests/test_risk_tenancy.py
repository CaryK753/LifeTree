from types import SimpleNamespace

import pytest

from app.core.exceptions import NotFoundError
from app.models.goal import Goal, Pathway, RiskFactor
from app.services.backup import BackupService
from app.services.risk_adoption import adopt_risk_for_pathway
from app.services.risk_scope import (
    get_mutable_risk,
    get_visible_risk,
    risk_scope_clause,
)


class _FirstResult:
    def __init__(self, value):
        self.value = value

    def first(self):
        return self.value


class _Dialect:
    name = "sqlite"


class _Bind:
    dialect = _Dialect()


class _AdoptionSession:
    def __init__(self, *, owner_id: str = "user-1", existing_risk=None):
        self.pathway = SimpleNamespace(id="path-1", goal_id="goal-1")
        self.goal = SimpleNamespace(id="goal-1", user_id=owner_id)
        self.risk = existing_risk
        self.links: set[tuple[str, str]] = set()
        self.added_risks = 0

    def get_bind(self):
        return _Bind()

    def get(self, model, object_id):
        if model is Pathway and object_id == self.pathway.id:
            return self.pathway
        if model is Goal and object_id == self.goal.id:
            return self.goal
        return None

    def scalar(self, statement):
        if "FROM risk_factors" in str(statement):
            return self.risk
        return None

    def add(self, value):
        if isinstance(value, RiskFactor):
            self.added_risks += 1
            self.risk = value

    def flush(self):
        if self.risk is not None and self.risk.id is None:
            self.risk.id = "risk-1"

    def execute(self, statement):
        sql = str(statement)
        params = statement.compile().params
        if sql.startswith("SELECT") and "pathway_risk_factors" in sql:
            key = (params["pathway_id_1"], params["risk_factor_id_1"])
            return _FirstResult(key if key in self.links else None)
        if sql.startswith("INSERT INTO pathway_risk_factors"):
            self.links.add((params["pathway_id"], params["risk_factor_id"]))
        return _FirstResult(None)

    def commit(self):
        pass

    def refresh(self, _value):
        pass


class _ScalarRows:
    def __init__(self, rows):
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)

    def all(self):
        return self.rows


class _BackupSession:
    def __init__(self):
        self.statements = []
        self.calls = 0

    def scalars(self, statement):
        self.statements.append(str(statement))
        self.calls += 1
        if self.calls == 1:
            return _ScalarRows(["risk-own"])
        if self.calls == 2:
            return _ScalarRows([])
        return _ScalarRows([])


def test_risk_scope_includes_only_global_and_current_user() -> None:
    sql = str(risk_scope_clause("user-1"))

    assert "risk_factors.user_id IS NULL" in sql
    assert "risk_factors.user_id =" in sql


def test_visible_risk_query_is_tenant_scoped() -> None:
    db = SimpleNamespace(
        statement=None,
        scalar=lambda statement: setattr(db, "statement", str(statement)),
    )

    with pytest.raises(NotFoundError):
        get_visible_risk(db, "risk-1", "user-1")

    assert "risk_factors.user_id" in db.statement
    assert "risk_factors.deleted_at IS NULL" in db.statement


def test_mutation_allows_owner_and_admin_global_only() -> None:
    personal = SimpleNamespace(id="own", user_id="user-1", deleted_at=None)
    global_risk = SimpleNamespace(id="global", user_id=None, deleted_at=None)
    other = SimpleNamespace(id="other", user_id="user-2", deleted_at=None)
    rows = {"own": personal, "global": global_risk, "other": other}
    db = SimpleNamespace(get=lambda _model, object_id: rows.get(object_id))

    assert get_mutable_risk(db, "own", user_id="user-1", is_admin=False) is personal
    assert get_mutable_risk(db, "global", user_id="admin", is_admin=True) is global_risk
    with pytest.raises(NotFoundError):
        get_mutable_risk(db, "global", user_id="user-1", is_admin=False)
    with pytest.raises(NotFoundError):
        get_mutable_risk(db, "other", user_id="admin", is_admin=True)


def test_repeated_adoption_creates_and_links_only_once() -> None:
    db = _AdoptionSession()
    values = {"level": "high", "urgency": "urgent"}

    first = adopt_risk_for_pathway(
        db,
        user_id="user-1",
        pathway_id="path-1",
        name="Policy volatility",
        risk_type="policy",
        region="CA",
        values=values,
    )
    second = adopt_risk_for_pathway(
        db,
        user_id="user-1",
        pathway_id="path-1",
        name="Policy volatility",
        risk_type="policy",
        region="CA",
        values=values,
    )

    assert first.created and first.linked
    assert not second.created and not second.linked
    assert db.added_risks == 1
    assert db.links == {("path-1", "risk-1")}


def test_adoption_rejects_another_users_pathway() -> None:
    db = _AdoptionSession(owner_id="user-2")

    with pytest.raises(NotFoundError):
        adopt_risk_for_pathway(
            db,
            user_id="user-1",
            pathway_id="path-1",
            name="Risk",
            risk_type="other",
            region=None,
            values={},
        )


def test_backup_risk_export_is_tenant_scoped() -> None:
    db = _BackupSession()

    assert BackupService(db)._export_risk_factors("user-1") == []
    risk_query = db.statements[-1]
    assert "risk_factors.user_id" in risk_query
    assert "risk_factors.deleted_at IS NULL" in risk_query
