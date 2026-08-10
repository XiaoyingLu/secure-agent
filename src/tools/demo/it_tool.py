"""Demo tool: IT ticket lookup from static fixture."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from tools.base_tool import BaseTool

_FIXTURE = Path(__file__).parent / "fixtures" / "tickets.json"


class ITToolInput(BaseModel):
    assignee: str | None = Field(default=None, description="Filter tickets by assignee name")
    status: str | None = Field(default=None, description="Filter by status: open, in_progress, or resolved")


class ITTool(BaseTool):
    """Demo tool: look up IT support tickets."""

    def __init__(self) -> None:
        super().__init__(
            name="lookup_it_tickets",
            description="Look up open IT support tickets, optionally filtered by assignee or status.",
        )
        with _FIXTURE.open() as f:
            self._tickets: list[dict[str, Any]] = json.load(f)

    def input_schema(self) -> dict[str, Any]:
        return ITToolInput.model_json_schema()

    async def execute(self, token: str, **kwargs: Any) -> dict[str, Any]:
        if os.getenv("DEMO_MODE", "false").lower() != "true":
            raise RuntimeError("ITTool is only available when DEMO_MODE=true")
        inp = ITToolInput(**kwargs)
        tickets = self._tickets
        if inp.assignee:
            tickets = [t for t in tickets if inp.assignee.lower() in t["assignee"].lower()]
        if inp.status:
            tickets = [t for t in tickets if t["status"] == inp.status]
        return {"tickets": tickets}
