import json
import threading
import time

import httpx
import pytest

from agent_platform.orchestrator.fake_model import FakeModelProvider
from agent_platform.server import (
    HOST,
    bind_loopback_socket,
    build_server,
    build_services,
    generate_token,
    startup_line,
)


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "Projects"
    root.mkdir()
    proj = root / "MyProj"
    proj.mkdir()
    return proj


# --------------------------------------------------------------- token

def test_generate_token_is_long_and_random():
    a = generate_token()
    b = generate_token()
    assert a != b
    assert len(a) >= 32


# ------------------------------------------------------------- binding

def test_bind_loopback_socket_binds_127_0_0_1_never_0_0_0_0():
    sock = bind_loopback_socket(0)
    try:
        host, port = sock.getsockname()
        assert host == "127.0.0.1"
        assert host == HOST
        assert port > 0
    finally:
        sock.close()


def test_bind_loopback_socket_lets_os_assign_a_free_port():
    sock1 = bind_loopback_socket(0)
    sock2 = bind_loopback_socket(0)
    try:
        assert sock1.getsockname()[1] != sock2.getsockname()[1]
    finally:
        sock1.close()
        sock2.close()


# ----------------------------------------------------------- startup line

def test_startup_line_is_single_json_line_with_port_and_token():
    line = startup_line(54231, "abc123")
    assert "\n" not in line
    parsed = json.loads(line)
    assert parsed == {"port": 54231, "token": "abc123"}


# -------------------------------------------------------------- services

def test_build_services_binds_to_the_given_project_root(workspace):
    services = build_services(workspace, FakeModelProvider())
    assert services.project_root == workspace


# --------------------------------------------------- authenticated loopback

def test_authenticated_loopback_request_succeeds_and_wrong_token_is_rejected(workspace):
    model = FakeModelProvider(chat_responses=[{"message": "hi there"}])
    server, sock, token = build_server(workspace, model, port=0)
    port = sock.getsockname()[1]

    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5.0
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started, "server did not report started within the timeout"

        base_url = f"http://127.0.0.1:{port}"
        unauth = httpx.post(f"{base_url}/sessions", json={"operating_mode": "CHAT"}, timeout=5.0)
        assert unauth.status_code == 401

        wrong = httpx.post(f"{base_url}/sessions", json={"operating_mode": "CHAT"},
                            headers={"Authorization": "Bearer wrong"}, timeout=5.0)
        assert wrong.status_code == 401

        authed = httpx.post(f"{base_url}/sessions", json={"operating_mode": "CHAT"},
                             headers={"Authorization": f"Bearer {token}"}, timeout=5.0)
        assert authed.status_code == 200
        session_id = authed.json()["session_id"]

        msg = httpx.post(f"{base_url}/sessions/{session_id}/messages", json={"message": "hello"},
                          headers={"Authorization": f"Bearer {token}"}, timeout=5.0)
        assert msg.status_code == 200
        assert msg.json()["message"] == "hi there"
    finally:
        server.should_exit = True
        thread.join(timeout=5.0)
