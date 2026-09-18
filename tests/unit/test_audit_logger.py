from __future__ import annotations

from secure_agent.audit.audit_logger import AuditLogger


def test_log_and_retrieve():
    logger = AuditLogger(max_entries=5)
    logger.log("alice@example.com", "hr_tool", {"name": "Alice"}, "allowed")
    entries = logger.recent(10)
    assert len(entries) == 1
    assert entries[0].user == "alice@example.com"
    assert entries[0].tool == "hr_tool"
    assert entries[0].status == "allowed"


def test_max_entries_eviction():
    logger = AuditLogger(max_entries=3)
    for i in range(5):
        logger.log("u@example.com", f"tool_{i}", {}, "allowed")
    entries = logger.recent(10)
    assert len(entries) == 3
    assert entries[-1].tool == "tool_4"  # most recent last


def test_recent_limit():
    logger = AuditLogger(max_entries=20)
    for i in range(10):
        logger.log("u@example.com", "tool", {}, "allowed")
    assert len(logger.recent(3)) == 3


def test_blocked_status():
    logger = AuditLogger(max_entries=10)
    logger.log("u@example.com", "hr_tool", {}, "blocked", reason="prompt_injection")
    entry = logger.recent(1)[0]
    assert entry.status == "blocked"
    assert entry.reason == "prompt_injection"
