"""Unit tests for SharePointTool.

All tests mock GraphClient so no real network calls are made.
The mock path targets the GraphClient imported inside sharepoint_tool.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from graph.graph_client import GraphAuthError, GraphPermissionError, GraphRateLimitError
from tools.sharepoint_tool import SharePointTool, SharePointToolInput

PATCH_TARGET = "tools.sharepoint_tool.GraphClient"
FAKE_TOKEN = "obo-token-sharepoint"  # noqa: S105


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tool() -> SharePointTool:
    return SharePointTool()


@pytest.fixture()
def mock_graph(mocker) -> AsyncMock:
    """Patch GraphClient used inside sharepoint_tool and return the mock instance."""
    mock_cls = mocker.patch(PATCH_TARGET)
    mock_instance = mocker.AsyncMock()
    mock_cls.return_value.__aenter__.return_value = mock_instance
    mock_cls.return_value.__aexit__.return_value = False
    return mock_instance


@pytest.fixture()
def sample_hits() -> list[dict]:
    return [
        {
            "id": "item-1",
            "name": "Q3 Budget Forecast.xlsx",
            "webUrl": "https://contoso.sharepoint.com/sites/finance/Q3 Budget Forecast.xlsx",
            "lastModifiedDateTime": "2026-04-01T14:00:00Z",
            "lastModifiedBy": {"user": {"displayName": "Alice Smith"}},
            "size": 204800,
            "parentReference": {"siteId": "site-abc", "driveId": "drive-xyz"},
            "score": 1,
            "summary": "...Q3 revenue forecast showing <c0>budget</c0> allocations...",
        },
        {
            "id": "item-2",
            "name": "Budget Overview.pptx",
            "webUrl": "https://contoso.sharepoint.com/sites/ops/Budget Overview.pptx",
            "lastModifiedDateTime": "2026-03-15T10:30:00Z",
            "lastModifiedBy": {"user": {"displayName": "Bob Jones"}},
            "size": 512000,
            "parentReference": {"siteId": "site-ops", "driveId": "drive-ops"},
            "score": 2,
            "summary": "...annual <c0>budget</c0> overview presentation...",
        },
    ]


# ---------------------------------------------------------------------------
# Tool identity
# ---------------------------------------------------------------------------


class TestSharePointToolIdentity:
    def test_name(self, tool: SharePointTool) -> None:
        assert tool.name == "search_sharepoint"

    def test_description_mentions_sharepoint(self, tool: SharePointTool) -> None:
        assert "SharePoint" in tool.description

    def test_description_mentions_scope(self, tool: SharePointTool) -> None:
        assert "Sites.Read.All" in tool.description

    def test_description_mentions_permissions(self, tool: SharePointTool) -> None:
        assert "permissions" in tool.description.lower()

    def test_to_mcp_schema_structure(self, tool: SharePointTool) -> None:
        schema = tool.to_mcp_schema()
        assert schema["name"] == "search_sharepoint"
        assert "description" in schema
        assert schema["inputSchema"]["type"] == "object"


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestSharePointToolInputValidation:
    def test_default_top(self) -> None:
        inp = SharePointToolInput(query="budget report")
        assert inp.top == 5

    def test_custom_top(self) -> None:
        inp = SharePointToolInput(query="budget report", top=10)
        assert inp.top == 10

    def test_top_minimum_boundary(self) -> None:
        inp = SharePointToolInput(query="budget report", top=1)
        assert inp.top == 1

    def test_top_maximum_boundary(self) -> None:
        inp = SharePointToolInput(query="budget report", top=25)
        assert inp.top == 25

    def test_rejects_top_zero(self) -> None:
        with pytest.raises(ValueError, match="greater than or equal to 1"):
            SharePointToolInput(query="budget report", top=0)

    def test_rejects_top_over_maximum(self) -> None:
        with pytest.raises(ValueError, match="less than or equal to 25"):
            SharePointToolInput(query="budget report", top=26)

    def test_rejects_blank_query(self) -> None:
        with pytest.raises(ValueError):
            SharePointToolInput(query="   ")

    def test_rejects_empty_query(self) -> None:
        with pytest.raises(ValueError):
            SharePointToolInput(query="")

    def test_rejects_single_char_query(self) -> None:
        with pytest.raises(ValueError):
            SharePointToolInput(query="x")

    def test_strips_surrounding_whitespace_from_query(self) -> None:
        inp = SharePointToolInput(query="  budget report  ")
        assert inp.query == "budget report"

    def test_accepts_multiword_query(self) -> None:
        inp = SharePointToolInput(query="Q3 2026 revenue forecast EMEA")
        assert inp.query == "Q3 2026 revenue forecast EMEA"

    def test_accepts_two_char_minimum_query(self) -> None:
        inp = SharePointToolInput(query="ok")
        assert inp.query == "ok"

    def test_rejects_non_string_query(self) -> None:
        with pytest.raises(ValueError):
            SharePointToolInput(query=123)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------


class TestSharePointToolInputSchema:
    def test_schema_is_object(self, tool: SharePointTool) -> None:
        schema = tool.input_schema()
        assert schema["type"] == "object"

    def test_schema_has_query_and_top(self, tool: SharePointTool) -> None:
        schema = tool.input_schema()
        assert "query" in schema["properties"]
        assert "top" in schema["properties"]

    def test_top_has_correct_defaults_and_bounds(self, tool: SharePointTool) -> None:
        schema = tool.input_schema()
        top = schema["properties"]["top"]
        assert top["default"] == 5
        assert top["minimum"] == 1
        assert top["maximum"] == 25

    def test_query_is_required(self, tool: SharePointTool) -> None:
        schema = tool.input_schema()
        assert "query" in schema.get("required", [])


# ---------------------------------------------------------------------------
# execute — happy path
# ---------------------------------------------------------------------------


class TestSharePointToolExecuteSuccess:
    async def test_returns_results_and_total(
        self, tool: SharePointTool, mock_graph: AsyncMock, sample_hits: list
    ) -> None:
        mock_graph.search_sharepoint.return_value = sample_hits
        result = await tool.execute(token=FAKE_TOKEN, query="budget report")
        assert "results" in result
        assert "total_returned" in result

    async def test_total_returned_matches_results_length(
        self, tool: SharePointTool, mock_graph: AsyncMock, sample_hits: list
    ) -> None:
        mock_graph.search_sharepoint.return_value = sample_hits
        result = await tool.execute(token=FAKE_TOKEN, query="budget report")
        assert result["total_returned"] == len(result["results"])

    async def test_results_content_matches_hits(
        self, tool: SharePointTool, mock_graph: AsyncMock, sample_hits: list
    ) -> None:
        mock_graph.search_sharepoint.return_value = sample_hits
        result = await tool.execute(token=FAKE_TOKEN, query="budget report")
        assert result["results"] == sample_hits

    async def test_first_result_fields(
        self, tool: SharePointTool, mock_graph: AsyncMock, sample_hits: list
    ) -> None:
        mock_graph.search_sharepoint.return_value = sample_hits
        result = await tool.execute(token=FAKE_TOKEN, query="budget report")
        hit = result["results"][0]
        assert hit["name"] == "Q3 Budget Forecast.xlsx"
        assert "sharepoint.com" in hit["webUrl"]
        assert hit["score"] == 1

    async def test_empty_results_returns_zero_total(
        self, tool: SharePointTool, mock_graph: AsyncMock
    ) -> None:
        mock_graph.search_sharepoint.return_value = []
        result = await tool.execute(token=FAKE_TOKEN, query="nonexistent document xyz")
        assert result == {"results": [], "total_returned": 0}

    async def test_passes_obo_token_verbatim(
        self, tool: SharePointTool, mock_graph: AsyncMock
    ) -> None:
        """The OBO token must reach Graph unchanged — never substituted."""
        mock_graph.search_sharepoint.return_value = []
        await tool.execute(token=FAKE_TOKEN, query="budget")
        call_kwargs = mock_graph.search_sharepoint.call_args.kwargs
        assert call_kwargs["token"] == FAKE_TOKEN

    async def test_passes_query_to_graph(
        self, tool: SharePointTool, mock_graph: AsyncMock
    ) -> None:
        mock_graph.search_sharepoint.return_value = []
        await tool.execute(token=FAKE_TOKEN, query="Q3 budget forecast")
        call_kwargs = mock_graph.search_sharepoint.call_args.kwargs
        assert call_kwargs["query"] == "Q3 budget forecast"

    async def test_passes_top_to_graph(
        self, tool: SharePointTool, mock_graph: AsyncMock
    ) -> None:
        mock_graph.search_sharepoint.return_value = []
        await tool.execute(token=FAKE_TOKEN, query="budget", top=12)
        call_kwargs = mock_graph.search_sharepoint.call_args.kwargs
        assert call_kwargs["top"] == 12

    async def test_default_top_is_five(
        self, tool: SharePointTool, mock_graph: AsyncMock
    ) -> None:
        mock_graph.search_sharepoint.return_value = []
        await tool.execute(token=FAKE_TOKEN, query="budget")
        call_kwargs = mock_graph.search_sharepoint.call_args.kwargs
        assert call_kwargs["top"] == 5

    async def test_whitespace_is_stripped_from_query_before_graph_call(
        self, tool: SharePointTool, mock_graph: AsyncMock
    ) -> None:
        mock_graph.search_sharepoint.return_value = []
        await tool.execute(token=FAKE_TOKEN, query="  annual report  ")
        call_kwargs = mock_graph.search_sharepoint.call_args.kwargs
        assert call_kwargs["query"] == "annual report"


# ---------------------------------------------------------------------------
# execute — error propagation
# ---------------------------------------------------------------------------


class TestSharePointToolExecuteErrors:
    async def test_propagates_auth_error(
        self, tool: SharePointTool, mock_graph: AsyncMock
    ) -> None:
        mock_graph.search_sharepoint.side_effect = GraphAuthError(
            "Token expired", status_code=401
        )
        with pytest.raises(GraphAuthError, match="Token expired"):
            await tool.execute(token="bad-token", query="budget")

    async def test_propagates_permission_error(
        self, tool: SharePointTool, mock_graph: AsyncMock
    ) -> None:
        mock_graph.search_sharepoint.side_effect = GraphPermissionError(
            "Missing Sites.Read.All", status_code=403
        )
        with pytest.raises(GraphPermissionError, match="Sites.Read.All"):
            await tool.execute(token=FAKE_TOKEN, query="budget")

    async def test_propagates_rate_limit_with_retry_after(
        self, tool: SharePointTool, mock_graph: AsyncMock
    ) -> None:
        mock_graph.search_sharepoint.side_effect = GraphRateLimitError(
            "Throttled", status_code=429, retry_after=30
        )
        with pytest.raises(GraphRateLimitError) as exc_info:
            await tool.execute(token=FAKE_TOKEN, query="budget")
        assert exc_info.value.retry_after == 30

    async def test_validation_error_does_not_call_graph(
        self, tool: SharePointTool, mock_graph: AsyncMock
    ) -> None:
        """Pydantic must reject bad input before we touch the network."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            await tool.execute(token=FAKE_TOKEN, query="")
        mock_graph.search_sharepoint.assert_not_called()

    async def test_blank_query_does_not_call_graph(
        self, tool: SharePointTool, mock_graph: AsyncMock
    ) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            await tool.execute(token=FAKE_TOKEN, query="   ")
        mock_graph.search_sharepoint.assert_not_called()