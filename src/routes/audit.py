"""GET /audit route — returns last 20 audit log entries."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(tags=["audit"])


@router.get("/audit")
async def get_audit(request: Request) -> dict[str, Any]:
    """Return the last 20 audit log entries."""
    audit_logger = getattr(request.app.state, "audit_logger", None)
    if audit_logger is None:
        return {"entries": []}
    entries = audit_logger.recent(20)
    return {"entries": [e.to_dict() for e in entries]}
