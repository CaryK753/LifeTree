from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from threading import Event

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from app.api.runtime import build_runtime_capabilities, get_runtime_capabilities
from app.db.postgres import Base
from app.models.action import Action
from app.models.goal import Goal
from app.models.user import UserProfile
from app.services.runtime.blob_store import LocalFileBlobStore
from app.services.runtime.job_runner import CeleryJobRunner, InProcessJobRunner


def test_local_blob_store_round_trip_and_deduplication(tmp_path: Path) -> None:
    store = LocalFileBlobStore(tmp_path / "objects")
    store.prepare()

    first = store.put_bytes(b"LifeTree", content_type="text/plain")
    second = store.put_bytes(b"LifeTree", content_type="text/plain")

    assert first == second
    assert first.key.startswith("sha256/")
    assert store.exists(first.key)
    assert store.get_bytes(first.key) == b"LifeTree"
    assert store.delete(first.key) is True
    assert store.delete(first.key) is False


def test_local_blob_store_rejects_caller_paths(tmp_path: Path) -> None:
    store = LocalFileBlobStore(tmp_path / "objects")

    with pytest.raises(ValueError, match="Invalid content-addressed"):
        store.get_bytes("../../private.txt")


def test_in_process_runner_executes_submitted_job() -> None:
    runner = InProcessJobRunner()
    completed = Event()
    values: list[str] = []

    def task(*, value: str) -> None:
        values.append(value)
        completed.set()

    submission = runner.submit(task, value="done")

    assert submission.backend == "in_process"
    assert completed.wait(timeout=2)
    assert values == ["done"]
    runner.shutdown()


def test_celery_runner_uses_delay() -> None:
    class FakeResult:
        id = "job-1"

    class FakeTask:
        def delay(self, **kwargs: str) -> FakeResult:
            assert kwargs == {"value": "queued"}
            return FakeResult()

    submission = CeleryJobRunner().submit(FakeTask(), value="queued")

    assert submission.id == "job-1"
    assert submission.backend == "celery"


def test_server_runtime_capabilities_do_not_claim_local_readiness() -> None:
    capabilities = get_runtime_capabilities()

    assert capabilities.storage_mode == "server"
    assert capabilities.local_private_ready is False
    assert {adapter.key for adapter in capabilities.adapters} == {
        "database",
        "blobs",
        "jobs",
        "graph",
        "vectors",
    }


def test_local_capabilities_report_partial_adapter_readiness() -> None:
    capabilities = build_runtime_capabilities("local")
    statuses = {adapter.key: adapter.status for adapter in capabilities.adapters}

    assert statuses["database"] == "ready"
    assert statuses["blobs"] == "ready"
    assert statuses["jobs"] == "ready"
    assert statuses["graph"] == "ready"
    assert statuses["vectors"] == "ready"
    assert statuses["desktop_bundle"] == "ready"
    assert capabilities.local_private_ready is True


def test_sqlite_schema_round_trips_goal_and_action() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        user = UserProfile(display_name="Local User", email="local@lifetree.invalid")
        db.add(user)
        db.flush()
        goal = Goal(
            user_id=user.id,
            title="Local Goal",
            scenario="generic",
            success_probability={"p50": 0.5},
        )
        db.add(goal)
        db.flush()
        db.add(Action(user_id=user.id, goal_id=goal.id, title="Local Action"))
        db.commit()

        stored_goal = db.scalar(select(Goal).where(Goal.id == goal.id))
        stored_action = db.scalar(select(Action).where(Action.goal_id == goal.id))
        assert stored_goal is not None
        assert stored_goal.success_probability == {"p50": 0.5}
        assert stored_action is not None
        assert stored_action.title == "Local Action"


def test_postgres_schema_keeps_jsonb() -> None:
    ddl = str(CreateTable(Goal.__table__).compile(dialect=postgresql.dialect()))

    assert "JSONB" in ddl


def test_local_app_boots_without_server_infrastructure(tmp_path: Path) -> None:
    backend_root = Path(__file__).parents[1]
    environment = os.environ.copy()
    environment.update(
        {
            "LIFETREE_STORAGE_MODE": "local",
            "LIFETREE_DATA_DIR": str(tmp_path / "runtime"),
            "LIFETREE_LOCAL_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
            "APP_DEBUG": "false",
        }
    )
    code = """
from fastapi.testclient import TestClient
from app.core.legal import PRIVACY_VERSION, TERMS_VERSION
from app.main import app
with TestClient(app) as client:
    response = client.get('/api/v1/runtime/capabilities')
    assert response.status_code == 200
    assert response.json()['storage_mode'] == 'local'
    registered = client.post('/api/v1/auth/register', json={
        'display_name': 'Desktop User',
        'email': 'desktop@example.com',
        'password': 'local-password',
        'accepted_terms': True,
        'terms_version': TERMS_VERSION,
        'privacy_version': PRIVACY_VERSION,
    })
    assert registered.status_code == 201, registered.text
    headers = {'Authorization': f"Bearer {registered.json()['access_token']}"}
    goal = client.post('/api/v1/goals', json={
        'title': 'Offline Goal',
        'scenario': 'generic',
    }, headers=headers)
    assert goal.status_code == 201, goal.text
    action = client.post('/api/v1/actions', json={
        'goal_id': goal.json()['id'],
        'title': 'Offline Action',
    }, headers=headers)
    assert action.status_code == 201, action.text
    assert client.get('/api/v1/goals', headers=headers).json()[0]['title'] == 'Offline Goal'
    assert client.get('/api/v1/actions', headers=headers).json()[0]['title'] == 'Offline Action'
    upload = client.post('/api/v1/ingest/upload', headers=headers,
        files={'file': ('offline.txt', b'offline evidence', 'text/plain')},
        data={'skip_llm': 'true'})
    assert upload.status_code == 200, upload.text
    system = client.get('/api/v1/system/components', headers=headers)
    assert system.status_code == 200, system.text
    components = {item['key']: item for item in system.json()['components']}
    assert set(components) == {'sqlite', 'embedded_graph', 'in_process_jobs', 'filesystem'}
    # embedded_graph must mirror runtime.py's graph=ready handshake; otherwise
    # the desktop shell keeps the local_private entry locked while the
    # capabilities endpoint claims it is unlocked.
    assert components['embedded_graph']['available'] is True
    assert components['embedded_graph']['enabled'] is True

    caps = client.get('/api/v1/runtime/capabilities').json()
    graph_adapter = next(a for a in caps['adapters'] if a['key'] == 'graph')
    assert graph_adapter['status'] == 'ready'
"""
    subprocess.run(
        [sys.executable, "-c", code],
        cwd=backend_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert (tmp_path / "runtime" / "lifetree.sqlite3").is_file()
    assert list((tmp_path / "runtime" / "objects" / "sha256").rglob("*.blob"))
