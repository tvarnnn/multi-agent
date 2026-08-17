import sqlite3
from contextlib import closing

import pytest

from agent_platform.orchestrator.fake_model import FakeModelProvider
from agent_platform.persistence.db import connect
from agent_platform.persistence.spec_version_store import SpecRehydrationError
from agent_platform.server import build_services


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    proj = root / "MyProj"
    proj.mkdir()
    return proj


def test_build_services_wires_sandbox_and_persistence(workspace):
    services = build_services(workspace, FakeModelProvider())
    assert services.sandbox is not None
    assert services.persistence is not None


def test_build_services_creates_agent_db_under_project(workspace):
    build_services(workspace, FakeModelProvider())
    assert (workspace / ".agent" / "agent.db").is_file()


def test_simulated_restart_rehydrates_spec_store(workspace):
    services1 = build_services(workspace, FakeModelProvider())
    spec = services1.spec_store.create("spec-1", goals=("g1",), constraints=(), acceptance_criteria=("file:a.py",))
    services1.persistence.record_spec_version(spec)

    # "restart": brand-new process-lifetime services pointed at the same project
    services2 = build_services(workspace, FakeModelProvider())
    assert services2.spec_store.latest("spec-1").goals == ("g1",)
    assert services2.spec_store is not services1.spec_store


def test_simulated_restart_preserves_persisted_session(workspace):
    services1 = build_services(workspace, FakeModelProvider())
    services1.persistence.create_session("s1", operating_mode="CHAT", session_mode="AUTO", spec_id=None)
    services1.persistence.record_message("s1", speaker="user", content="hello")

    services2 = build_services(workspace, FakeModelProvider())
    record = services2.persistence.get_session("s1")
    assert record is not None
    assert record.operating_mode == "CHAT"
    history = services2.persistence.get_history("s1")
    assert history[0].content == "hello"


def test_corrupted_spec_versions_fails_startup_loudly(workspace):
    services1 = build_services(workspace, FakeModelProvider())
    spec = services1.spec_store.create("spec-1", goals=("g1",), constraints=(), acceptance_criteria=())
    services1.persistence.record_spec_version(spec)

    db_path = workspace / ".agent" / "agent.db"
    with closing(sqlite3.connect(db_path)) as conn:
        # Corrupt the sequence: version 1 becomes version 3, leaving a gap.
        conn.execute("UPDATE spec_versions SET version = 3 WHERE spec_id = 'spec-1' AND version = 1")
        conn.commit()

    with pytest.raises(SpecRehydrationError):
        build_services(workspace, FakeModelProvider())
