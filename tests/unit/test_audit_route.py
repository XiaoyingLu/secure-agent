from __future__ import annotations

from fastapi import FastAPI
from secure_agent.audit.audit_logger import AuditLogger
from fastapi.testclient import TestClient

from secure_agent.api.routes.audit import router


def _make_app(logger: AuditLogger | None = None) -> FastAPI:
    app = FastAPI()
    if logger is not None:
        app.state.audit_logger = logger
    app.include_router(router)
    return app


def test_audit_returns_entries():
    log = AuditLogger()
    log.log("alice@example.com", "hr_tool", {"name": "Alice"}, "allowed")
    log.log("alice@example.com", "hr_tool", {"name": "Nobody"}, "blocked", reason="prompt_injection")
    client = TestClient(_make_app(log))
    resp = client.get("/audit")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["entries"]) == 2
    assert data["entries"][1]["status"] == "blocked"
    assert data["entries"][1]["reason"] == "prompt_injection"


def test_audit_limit():
    log = AuditLogger()
    for i in range(25):
        log.log("u@example.com", "tool", {}, "allowed")
    client = TestClient(_make_app(log))
    resp = client.get("/audit")
    assert len(resp.json()["entries"]) == 20


def test_audit_no_logger():
    client = TestClient(_make_app())
    resp = client.get("/audit")
    assert resp.status_code == 200
    assert resp.json()["entries"] == []
