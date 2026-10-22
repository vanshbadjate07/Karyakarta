"""The local HTTP interface the desktop app talks to: access control, task
flow, live stream, and that secrets never come back out of it."""
import json
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from karyakarta.browser.session import BrowserManager
from karyakarta.main import create_app
from tests.conftest import ScriptedModel

H = {"X-Karyakarta-Token": "test-token", "Host": "127.0.0.1:8765"}


@pytest.fixture
def make_client(settings):
    clients = []

    def build(steps):
        app = create_app(settings, model=ScriptedModel(steps), browser=BrowserManager(settings))
        client = TestClient(app, base_url="http://127.0.0.1:8765")
        client.__enter__()
        clients.append(client)
        return client

    yield build
    for c in clients:
        c.__exit__(None, None, None)


def wait_for(fn, timeout=40):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = fn()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError("timed out")


def events_of(client, task_id, kind=None):
    events = client.get(f"/api/tasks/{task_id}/events", headers=H).json()
    return [e for e in events if kind is None or e["kind"] == kind]


def task_status(client, task_id):
    return client.get(f"/api/tasks/{task_id}", headers=H).json()


# ---- access control ----------------------------------------------------------
def test_health_is_open_but_everything_else_needs_the_token(make_client):
    c = make_client([])
    assert c.get("/api/health").json()["ok"] is True
    for path in ("/api/tasks", "/api/system/status", "/api/tasks/1"):
        assert c.get(path).status_code == 401
        assert c.get(path, headers={"X-Karyakarta-Token": "wrong"}).status_code == 401
    assert c.post("/api/tasks", json={"instruction": "do it"}).status_code == 401


def test_requests_with_a_foreign_host_header_are_refused(make_client):
    c = make_client([])
    assert c.get("/api/health", headers={"Host": "evil.example"}).status_code == 403
    assert c.get("/api/health", headers={"Host": "127.0.0.1:9999"}).status_code == 403


def test_other_websites_get_no_cross_origin_permission(make_client):
    c = make_client([])
    ok = c.options("/api/tasks", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
    bad = c.options("/api/tasks", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in bad.headers


def test_websocket_needs_the_token(make_client):
    c = make_client([])
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect("/api/ws/tasks/1?token=wrong", headers={"Host": "127.0.0.1:8765"}):
            pass


# ---- validation --------------------------------------------------------------
@pytest.mark.parametrize("body", [
    {"instruction": ""},
    {"instruction": "ab"},
    {"instruction": "x" * 2001},
    {"instruction": "      "},
    {"instruction": "open it", "start_url": "javascript:alert(1)"},
    {"instruction": "open it", "start_url": "file:///etc/passwd"},
    {},
])
def test_bad_task_requests_are_rejected(make_client, body):
    assert make_client([]).post("/api/tasks", json=body, headers=H).status_code == 422


def test_unknown_task_is_404(make_client):
    c = make_client([])
    assert c.get("/api/tasks/999", headers=H).status_code == 404
    assert c.post("/api/tasks/999/cancel", headers=H).status_code == 404


# ---- task flow ---------------------------------------------------------------
def test_task_runs_and_exposes_events_steps_and_screenshots(make_client, site):
    c = make_client([
        {"action": "type", "label": "Search books", "value": "dune"},
        {"action": "click", "label": "Search"},
        {"action": "extract"},
        {"action": "done", "value": "Dune costs $12.99"},
    ])
    task = c.post("/api/tasks", json={"instruction": "Find the price of Dune", "start_url": f"{site}/search.html"}, headers=H).json()
    assert task["status"] in ("queued", "running")
    wait_for(lambda: task_status(c, task["id"])["status"] == "completed")

    done = task_status(c, task["id"])
    assert done["result"] == "Dune costs $12.99" and [s["action"] for s in done["steps"]] == ["type", "click", "extract", "done"]
    assert c.get("/api/tasks", headers=H).json()[0]["id"] == task["id"]
    assert events_of(c, task["id"], "task_complete")
    first_shot = done["steps"][0]["screenshot"].split("/")[1]
    image = c.get(f"/api/tasks/{task['id']}/screenshots/{first_shot}", headers=H)
    assert image.status_code == 200 and image.headers["content-type"] == "image/jpeg" and image.content[:2] == b"\xff\xd8"
    assert c.get(f"/api/tasks/{task['id']}/screenshots/..%2Fkaryakarta.db", headers=H).status_code in (400, 404)
    assert c.get(f"/api/tasks/{task['id']}/screenshots/missing.jpg", headers=H).status_code == 404


def test_live_stream_replays_history_then_ends_when_the_task_finishes(make_client, site):
    c = make_client([{"action": "done", "value": "ok"}])
    task = c.post("/api/tasks", json={"instruction": "Say ok", "start_url": f"{site}/index.html"}, headers=H).json()
    wait_for(lambda: task_status(c, task["id"])["status"] == "completed")
    seen = []
    with c.websocket_connect(f"/api/ws/tasks/{task['id']}?token=test-token", headers={"Host": "127.0.0.1:8765"}) as ws:
        while True:
            try:
                seen.append(ws.receive_json())
            except WebSocketDisconnect:
                break
    kinds = [e["kind"] for e in seen]
    assert kinds[0] == "task_queued" and kinds[-1] == "task_complete"
    assert [e["seq"] for e in seen] == sorted(e["seq"] for e in seen)


def test_confirmation_over_http_and_stale_answers_are_refused(make_client, site):
    c = make_client([{"action": "click", "label": "Send message"}, {"action": "done", "value": "sent"}])
    task = c.post("/api/tasks", json={"instruction": "Send", "start_url": f"{site}/contact.html"}, headers=H).json()
    tid = task["id"]
    assert c.post(f"/api/tasks/{tid}/credential", json={"value": "x"}, headers=H).status_code == 409
    wait_for(lambda: events_of(c, tid, "confirmation_request"))
    assert c.post(f"/api/tasks/{tid}/credential", json={"value": "x"}, headers=H).status_code == 409  # wrong kind
    assert c.post(f"/api/tasks/{tid}/confirm", json={"approved": True}, headers=H).status_code == 200
    wait_for(lambda: task_status(c, tid)["status"] == "completed")
    assert c.post(f"/api/tasks/{tid}/confirm", json={"approved": True}, headers=H).status_code == 409  # nothing pending now


def test_password_sent_over_http_is_used_but_never_returned_or_stored(make_client, site):
    c = make_client([
        {"action": "type", "label": "Email", "value": "demo@example.com"},
        {"action": "type", "label": "Password", "value": "model-guess"},
        {"action": "click", "label": "Sign in"},
        {"action": "done", "value": "in"},
    ])
    tid = c.post("/api/tasks", json={"instruction": "Log in", "start_url": f"{site}/login.html"}, headers=H).json()["id"]
    wait_for(lambda: events_of(c, tid, "credential_request"))
    assert c.post(f"/api/tasks/{tid}/credential", json={"value": ""}, headers=H).status_code == 422
    assert c.post(f"/api/tasks/{tid}/credential", json={"value": "secret123"}, headers=H).status_code == 200
    wait_for(lambda: task_status(c, tid)["status"] == "completed")
    blob = json.dumps([task_status(c, tid), events_of(c, tid)])
    assert "secret123" not in blob and "model-guess" not in blob


def test_cancel_and_delete_rules(make_client, site):
    c = make_client([{"action": "click", "label": "Send message"}])
    tid = c.post("/api/tasks", json={"instruction": "Send", "start_url": f"{site}/contact.html"}, headers=H).json()["id"]
    wait_for(lambda: events_of(c, tid, "confirmation_request"))
    assert c.delete(f"/api/tasks/{tid}", headers=H).status_code == 409  # still running
    assert c.post(f"/api/tasks/{tid}/cancel", headers=H).status_code == 200
    wait_for(lambda: task_status(c, tid)["status"] == "cancelled")
    assert c.post(f"/api/tasks/{tid}/cancel", headers=H).status_code == 409  # already over
    assert c.delete(f"/api/tasks/{tid}", headers=H).status_code == 204
    assert c.get(f"/api/tasks/{tid}", headers=H).status_code == 404


def test_system_status_reports_readiness(make_client):
    c = make_client([])
    body = c.get("/api/system/status", headers=H).json()
    assert body["engine_running"] and body["model_installed"] and body["browser_installed"] and body["ready"] is True
    assert body["current_task"] is None
