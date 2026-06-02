"""Unit tests for CalendarTool.

All tests mock GraphClient so no real network calls are made.
The mock path targets the GraphClient imported inside calendar_tool.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from graph.graph_client import GraphAuthError, GraphPermissionError, GraphRateLimitError
from tools.calendar_tool import CalendarTool, CalendarToolInput

PATCH_TARGET = "tools.calendar_tool.GraphClient"
FAKE_TOKEN = "obo-token-calendar"  # noqa: S105


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tool() -> CalendarTool:
    return CalendarTool()


@pytest.fixture()
def mock_graph(mocker) -> AsyncMock:
    """Patch GraphClient used inside calendar_tool and return the mock instance."""
    mock_cls = mocker.patch(PATCH_TARGET)
    mock_instance = mocker.AsyncMock()
    mock_cls.return_value.__aenter__.return_value = mock_instance
    mock_cls.return_value.__aexit__.return_value = False
    return mock_instance


@pytest.fixture()
def sample_events() -> list[dict]:
    return [
        {
            "id": "evt-1",
            "subject": "Team standup",
            "start": {"dateTime": "2026-05-27T09:00:00", "timeZone": "UTC"},
            "end": {"dateTime": "2026-05-27T09:30:00", "timeZone": "UTC"},
            "organizer": {"emailAddress": {"name": "Alice", "address": "alice@contoso.com"}},
            "location": {"displayName": "Microsoft Teams"},
        },
        {
            "id": "evt-2",
            "subject": "Sprint review",
            "start": {"dateTime": "2026-05-27T14:00:00", "timeZone": "UTC"},
            "end": {"dateTime": "2026-05-27T15:00:00", "timeZone": "UTC"},
            "organizer": {"emailAddress": {"name": "Bob", "address": "bob@contoso.com"}},
            "location": {"displayName": "Room 4B"},
        },
    ]


# ---------------------------------------------------------------------------
# Tool identity
# ---------------------------------------------------------------------------


class TestCalendarToolIdentity:
    def test_name(self, tool: CalendarTool) -> None:
        assert tool.name == "get_my_events"

    def test_description_mentions_calendar(self, tool: CalendarTool) -> None:
        assert "calendar" in tool.description.lower()

    def test_description_mentions_graph(self, tool: CalendarTool) -> None:
        assert "Microsoft Graph" in tool.description

    def test_description_mentions_scope(self, tool: CalendarTool) -> None:
        assert "Calendars.Read" in tool.description

    def test_to_mcp_schema_structure(self, tool: CalendarTool) -> None:
        schema = tool.to_mcp_schema()
        assert schema["name"] == "get_my_events"
        assert "description" in schema
        assert schema["inputSchema"]["type"] == "object"


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestCalendarToolInputValidation:
    def test_default_top(self) -> None:
        inp = CalendarToolInput(
            start_datetime="2026-05-27T00:00:00Z",
            end_datetime="2026-05-27T23:59:59Z",
        )
        assert inp.top == 10

    def test_custom_top(self) -> None:
        inp = CalendarToolInput(
            start_datetime="2026-05-27T00:00:00Z",
            end_datetime="2026-05-27T23:59:59Z",
            top=20,
        )
        assert inp.top == 20

    def test_top_minimum_boundary(self) -> None:
        inp = CalendarToolInput(
            start_datetime="2026-05-27T00:00:00Z",
            end_datetime="2026-05-27T23:59:59Z",
            top=1,
        )
        assert inp.top == 1

    def test_top_maximum_boundary(self) -> None:
        inp = CalendarToolInput(
            start_datetime="2026-05-27T00:00:00Z",
            end_datetime="2026-05-27T23:59:59Z",
            top=50,
        )
        assert inp.top == 50

    def test_rejects_top_zero(self) -> None:
        with pytest.raises(ValueError, match="greater than or equal to 1"):
            CalendarToolInput(
                start_datetime="2026-05-27T00:00:00Z",
                end_datetime="2026-05-27T23:59:59Z",
                top=0,
            )

    def test_rejects_top_over_maximum(self) -> None:
        with pytest.raises(ValueError, match="less than or equal to 50"):
            CalendarToolInput(
                start_datetime="2026-05-27T00:00:00Z",
                end_datetime="2026-05-27T23:59:59Z",
                top=51,
            )

    def test_rejects_end_before_start(self) -> None:
        with pytest.raises(ValueError, match="end_datetime.*must be after"):
            CalendarToolInput(
                start_datetime="2026-05-27T23:59:59Z",
                end_datetime="2026-05-27T00:00:00Z",
            )

    def test_rejects_end_equal_to_start(self) -> None:
        with pytest.raises(ValueError, match="end_datetime.*must be after"):
            CalendarToolInput(
                start_datetime="2026-05-27T12:00:00Z",
                end_datetime="2026-05-27T12:00:00Z",
            )

    def test_accepts_datetime_objects(self) -> None:
        start = datetime(2026, 5, 27, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 5, 27, 23, 59, 59, tzinfo=timezone.utc)
        inp = CalendarToolInput(start_datetime=start, end_datetime=end)
        assert inp.start_datetime == start
        assert inp.end_datetime == end

    def test_accepts_naive_datetimes(self) -> None:
        """Naive datetimes should be accepted and treated as UTC."""
        inp = CalendarToolInput(
            start_datetime="2026-05-27T00:00:00",
            end_datetime="2026-05-27T23:59:59",
        )
        assert inp.start_datetime.year == 2026

    def test_fmt_strips_timezone(self) -> None:
        inp = CalendarToolInput(
            start_datetime="2026-05-27T09:00:00+02:00",
            end_datetime="2026-05-27T23:59:59+02:00",
        )
        formatted = inp._fmt(inp.start_datetime)
        # Should be UTC without offset
        assert formatted == "2026-05-27T07:00:00"
        assert "+" not in formatted
        assert "Z" not in formatted


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------


class TestCalendarToolInputSchema:
    def test_schema_is_object(self, tool: CalendarTool) -> None:
        schema = tool.input_schema()
        assert schema["type"] == "object"

    def test_schema_has_required_properties(self, tool: CalendarTool) -> None:
        schema = tool.input_schema()
        props = schema["properties"]
        assert "start_datetime" in props
        assert "end_datetime" in props
        assert "top" in props

    def test_top_has_correct_bounds(self, tool: CalendarTool) -> None:
        schema = tool.input_schema()
        top = schema["properties"]["top"]
        assert top["default"] == 10
        assert top["minimum"] == 1
        assert top["maximum"] == 50

    def test_start_and_end_are_required(self, tool: CalendarTool) -> None:
        schema = tool.input_schema()
        required = schema.get("required", [])
        assert "start_datetime" in required
        assert "end_datetime" in required


# ---------------------------------------------------------------------------
# execute — happy path
# ---------------------------------------------------------------------------


class TestCalendarToolExecuteSuccess:
    async def test_returns_events_list(
        self, tool: CalendarTool, mock_graph: AsyncMock, sample_events: list
    ) -> None:
        mock_graph.get_events.return_value = sample_events
        result = await tool.execute(
            token=FAKE_TOKEN,
            start_datetime="2026-05-27T00:00:00Z",
            end_datetime="2026-05-27T23:59:59Z",
        )
        assert "events" in result
        assert result["events"] == sample_events

    async def test_returns_correct_event_count(
        self, tool: CalendarTool, mock_graph: AsyncMock, sample_events: list
    ) -> None:
        mock_graph.get_events.return_value = sample_events
        result = await tool.execute(
            token=FAKE_TOKEN,
            start_datetime="2026-05-27T00:00:00Z",
            end_datetime="2026-05-27T23:59:59Z",
        )
        assert len(result["events"]) == 2

    async def test_first_event_fields(
        self, tool: CalendarTool, mock_graph: AsyncMock, sample_events: list
    ) -> None:
        mock_graph.get_events.return_value = sample_events
        result = await tool.execute(
            token=FAKE_TOKEN,
            start_datetime="2026-05-27T00:00:00Z",
            end_datetime="2026-05-27T23:59:59Z",
        )
        evt = result["events"][0]
        assert evt["id"] == "evt-1"
        assert evt["subject"] == "Team standup"
        assert evt["organizer"]["emailAddress"]["name"] == "Alice"

    async def test_empty_response_returns_empty_list(
        self, tool: CalendarTool, mock_graph: AsyncMock
    ) -> None:
        mock_graph.get_events.return_value = []
        result = await tool.execute(
            token=FAKE_TOKEN,
            start_datetime="2026-05-27T00:00:00Z",
            end_datetime="2026-05-27T23:59:59Z",
        )
        assert result == {"events": []}

    async def test_passes_obo_token_to_graph(
        self, tool: CalendarTool, mock_graph: AsyncMock
    ) -> None:
        """The OBO token must be forwarded verbatim — never swapped for another."""
        mock_graph.get_events.return_value = []
        await tool.execute(
            token=FAKE_TOKEN,
            start_datetime="2026-05-27T00:00:00Z",
            end_datetime="2026-05-27T23:59:59Z",
        )
        call_kwargs = mock_graph.get_events.call_args.kwargs
        assert call_kwargs["token"] == FAKE_TOKEN

    async def test_passes_top_to_graph(
        self, tool: CalendarTool, mock_graph: AsyncMock
    ) -> None:
        mock_graph.get_events.return_value = []
        await tool.execute(
            token=FAKE_TOKEN,
            start_datetime="2026-05-27T00:00:00Z",
            end_datetime="2026-05-27T23:59:59Z",
            top=3,
        )
        call_kwargs = mock_graph.get_events.call_args.kwargs
        assert call_kwargs["top"] == 3

    async def test_formats_datetimes_for_graph(
        self, tool: CalendarTool, mock_graph: AsyncMock
    ) -> None:
        """Datetimes forwarded to Graph must be UTC strings without timezone suffix."""
        mock_graph.get_events.return_value = []
        await tool.execute(
            token=FAKE_TOKEN,
            start_datetime="2026-05-27T09:00:00+02:00",
            end_datetime="2026-05-27T18:00:00+02:00",
        )
        call_kwargs = mock_graph.get_events.call_args.kwargs
        # +02:00 → 07:00 UTC; no offset suffix
        assert call_kwargs["start_datetime"] == "2026-05-27T07:00:00"
        assert call_kwargs["end_datetime"] == "2026-05-27T16:00:00"


# ---------------------------------------------------------------------------
# execute — error propagation
# ---------------------------------------------------------------------------


class TestCalendarToolExecuteErrors:
    async def test_propagates_auth_error(
        self, tool: CalendarTool, mock_graph: AsyncMock
    ) -> None:
        mock_graph.get_events.side_effect = GraphAuthError(
            "Token expired", status_code=401
        )
        with pytest.raises(GraphAuthError, match="Token expired"):
            await tool.execute(
                token="bad-token",
                start_datetime="2026-05-27T00:00:00Z",
                end_datetime="2026-05-27T23:59:59Z",
            )

    async def test_propagates_permission_error(
        self, tool: CalendarTool, mock_graph: AsyncMock
    ) -> None:
        mock_graph.get_events.side_effect = GraphPermissionError(
            "Missing Calendars.Read", status_code=403
        )
        with pytest.raises(GraphPermissionError, match="Calendars.Read"):
            await tool.execute(
                token=FAKE_TOKEN,
                start_datetime="2026-05-27T00:00:00Z",
                end_datetime="2026-05-27T23:59:59Z",
            )

    async def test_propagates_rate_limit_error_with_retry_after(
        self, tool: CalendarTool, mock_graph: AsyncMock
    ) -> None:
        mock_graph.get_events.side_effect = GraphRateLimitError(
            "Too many requests", status_code=429, retry_after=60
        )
        with pytest.raises(GraphRateLimitError) as exc_info:
            await tool.execute(
                token=FAKE_TOKEN,
                start_datetime="2026-05-27T00:00:00Z",
                end_datetime="2026-05-27T23:59:59Z",
            )
        assert exc_info.value.retry_after == 60

    async def test_raises_validation_error_for_bad_input(
        self, tool: CalendarTool, mock_graph: AsyncMock
    ) -> None:
        """Pydantic validation errors must surface before any Graph call."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            await tool.execute(
                token=FAKE_TOKEN,
                start_datetime="2026-05-27T23:00:00Z",
                end_datetime="2026-05-27T01:00:00Z",  # end before start
            )
        mock_graph.get_events.assert_not_called()