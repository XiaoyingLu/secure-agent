"""Audit endpoints for demo-mode diagnostics."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

router = APIRouter(tags=["audit"])


@router.get("/audit")
async def audit_logs(request: Request) -> dict[str, object]:
    """Return recent audit entries when the demo logger is enabled."""
    logger = getattr(request.app.state, "audit_logger", None)
    if logger is None:
        return {"entries": []}

    return {"entries": logger.entries(limit=20)}
