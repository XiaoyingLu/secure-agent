"""Thread-safe in-memory audit log for demo tool calls."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class AuditEntry:
    """A single tool-call audit record."""

    user: str
    tool: str
    args: dict[str, Any]
    status: str  # "allowed" | "blocked"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "user": self.user,
            "tool": self.tool,
            "args": self.args,
            "status": self.status,
            "timestamp": self.timestamp,
            "reason": self.reason,
        }


class AuditLogger:
    """Thread-safe circular buffer of audit entries."""

    def __init__(self, max_entries: int = 100) -> None:
        self._entries: deque[AuditEntry] = deque(maxlen=max_entries)
        self._lock = threading.Lock()

    def log(
        self,
        user: str,
        tool: str,
        args: dict[str, Any],
        status: str,
        reason: str | None = None,
    ) -> None:
        """Append an audit entry."""
        entry = AuditEntry(user=user, tool=tool, args=args, status=status, reason=reason)
        with self._lock:
            self._entries.append(entry)

    def recent(self, n: int) -> list[AuditEntry]:
        """Return the last *n* entries, oldest first."""
        with self._lock:
            entries = list(self._entries)
        return entries[-n:]

    def entries(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return serializable entries, newest-last to match the route contract."""
        with self._lock:
            entries = list(self._entries)
        if limit is not None:
            entries = entries[-limit:]
        return [entry.to_dict() for entry in entries]
