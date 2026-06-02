"""MCP tool for retrieving the user's calendar events via Microsoft Graph.

Security invariant: the delegated OBO token supplied by the caller is
forwarded directly to Graph. This tool never holds or requests a
service-principal token, so Graph enforces the authenticated user's own
calendar permissions on every call.

Required Graph scope: ``Calendars.Read``
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from graph.graph_client import GraphClient
from tools.base_tool import BaseTool

logger = logging.getLogger(__name__)

# Maximum events the tool will ever request in a single call.
_MAX_TOP = 50


class CalendarToolInput(BaseModel):
    """Validated input for CalendarTool.

    Attributes:
        start_datetime: Inclusive start of the query window (UTC).
        end_datetime: Inclusive end of the query window (UTC).
        top: Maximum number of events to return (1–50).
    """

    start_datetime: datetime = Field(
        description="Start of the time window (ISO 8601, e.g. '2026-05-27T00:00:00Z')."
    )
    end_datetime: datetime = Field(
        description="End of the time window (ISO 8601, e.g. '2026-05-27T23:59:59Z')."
    )
    top: int = Field(
        default=10,
        ge=1,
        le=_MAX_TOP,
        description=f"Maximum number of events to return (1–{_MAX_TOP}).",
    )

    @field_validator("start_datetime", "end_datetime", mode="before")
    @classmethod
    def _parse_naive_as_utc(cls, v: Any) -> Any:
        """Accept plain strings; Pydantic will parse them via datetime.fromisoformat."""
        return v

    @model_validator(mode="after")
    def _end_after_start(self) -> CalendarToolInput:
        """Ensure the time window is valid (end strictly after start)."""
        # Make both tz-aware for comparison, treating naive as UTC.
        start = self.start_datetime
        end = self.end_datetime

        def _as_utc(dt: datetime) -> datetime:
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)

        if _as_utc(end) <= _as_utc(start):
            raise ValueError(
                f"end_datetime ({end.isoformat()}) must be after "
                f"start_datetime ({start.isoformat()})."
            )
        return self

    def _fmt(self, dt: datetime) -> str:
        """Format a datetime for the Graph $filter parameter.

        Graph expects ISO 8601 without timezone offset in the filter string
        (it treats the value as UTC when the ``Prefer: outlook.timezone`` header
        is absent).  We always normalise to UTC before formatting.
        """
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt.strftime("%Y-%m-%dT%H:%M:%S")


class CalendarTool(BaseTool):
    """MCP tool for retrieving the signed-in user's calendar events.

    Returns events within a requested time window, ordered by start time.
    Each event includes subject, start/end times, organiser, and location.

    Example MCP call::

        {
          "name": "get_my_events",
          "arguments": {
            "start_datetime": "2026-05-27T00:00:00Z",
            "end_datetime":   "2026-05-27T23:59:59Z",
            "top": 10
          }
        }
    """

    def __init__(self) -> None:
        super().__init__(
            name="get_my_events",
            description=(
                "Retrieve the signed-in user's calendar events from Microsoft Graph "
                "within a given time window. Requires Calendars.Read scope. "
                "Returns subject, start/end times, organiser, and location for each event."
            ),
        )

    async def execute(self, token: str, **kwargs: Any) -> dict[str, Any]:
        """Fetch calendar events for the authenticated user.

        Args:
            token: On-Behalf-Of access token with ``Calendars.Read`` scope.
                   This token is forwarded directly to Microsoft Graph —
                   never replace it with a service-principal credential.
            **kwargs: Tool arguments matching ``CalendarToolInput``:
                      ``start_datetime``, ``end_datetime``, ``top``.

        Returns:
            A dict with an ``events`` key containing a list of event dicts::

                {
                  "events": [
                    {
                      "id": "...",
                      "subject": "Team standup",
                      "start": {"dateTime": "2026-05-27T09:00:00", "timeZone": "UTC"},
                      "end":   {"dateTime": "2026-05-27T09:30:00", "timeZone": "UTC"},
                      "organizer": {"emailAddress": {"name": "...", "address": "..."}},
                      "location": {"displayName": "Teams"}
                    }
                  ]
                }

        Raises:
            pydantic.ValidationError: Input fails validation (e.g. end before start).
            GraphAuthError: Token is expired or malformed.
            GraphPermissionError: Token lacks ``Calendars.Read``.
            GraphRateLimitError: Graph is throttling; check ``exc.retry_after``.
            GraphServerError: Transient Graph-side failure.
        """
        input_data = CalendarToolInput(**kwargs)

        start_str = input_data._fmt(input_data.start_datetime)
        end_str = input_data._fmt(input_data.end_datetime)

        logger.info(
            "CalendarTool.execute: start=%s end=%s top=%d",
            start_str,
            end_str,
            input_data.top,
        )

        async with GraphClient() as client:
            events = await client.get_events(
                token=token,
                start_datetime=start_str,
                end_datetime=end_str,
                top=input_data.top,
            )

        return {"events": events}

    def input_schema(self) -> dict[str, Any]:
        """Return JSON Schema for CalendarTool arguments (MCP-compatible)."""
        return CalendarToolInput.model_json_schema()