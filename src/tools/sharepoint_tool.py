"""MCP tool for searching SharePoint content via Microsoft Graph Search API.

Security invariant: the delegated OBO token supplied by the caller is
forwarded directly to Graph's Search API.  Graph enforces the authenticated
user's SharePoint ACLs — content from sites the user cannot access will
never appear in results, even if the query would match it.

Required Graph scope: ``Sites.Read.All``
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field, field_validator

from graph.graph_client import GraphClient
from tools.base_tool import BaseTool

logger = logging.getLogger(__name__)

_MAX_TOP = 25
_MIN_QUERY_LENGTH = 2


class SharePointToolInput(BaseModel):
    """Validated input for SharePointTool.

    Attributes:
        query: Free-text search query sent to Graph Search.
        top: Maximum number of results to return (1–25).
    """

    query: str = Field(
        description="Search query string (e.g. 'Q3 budget report').",
        min_length=_MIN_QUERY_LENGTH,
    )
    top: int = Field(
        default=5,
        ge=1,
        le=_MAX_TOP,
        description=f"Maximum number of results to return (1–{_MAX_TOP}).",
    )

    @field_validator("query", mode="before")
    @classmethod
    def _strip_and_check(cls, v: Any) -> str:
        """Strip surrounding whitespace and reject blank queries."""
        if not isinstance(v, str):
            raise ValueError("query must be a string.")
        stripped = v.strip()
        if not stripped:
            raise ValueError("query must not be blank.")
        return stripped


class SharePointTool(BaseTool):
    """MCP tool for searching SharePoint / OneDrive files.

    Searches across all SharePoint sites the authenticated user can access,
    using the Microsoft Graph Search API (``POST /search/query``).  Results
    are ranked by relevance and filtered to ``driveItem`` entities (files).

    Example MCP call::

        {
          "name": "search_sharepoint",
          "arguments": {
            "query": "Q3 budget forecast",
            "top": 5
          }
        }
    """

    def __init__(self) -> None:
        super().__init__(
            name="search_sharepoint",
            description=(
                "Search SharePoint and OneDrive files accessible to the signed-in user "
                "using Microsoft Graph Search. Requires Sites.Read.All scope. "
                "Returns file name, URL, last-modified date, and a relevance summary "
                "for each result. Results respect the user's existing SharePoint permissions."
            ),
        )

    async def execute(self, token: str, **kwargs: Any) -> dict[str, Any]:
        """Search SharePoint for files matching the query.

        Args:
            token: On-Behalf-Of access token with ``Sites.Read.All`` scope.
                   Forwarded directly to Microsoft Graph — never replace with
                   a service-principal credential.
            **kwargs: Tool arguments matching ``SharePointToolInput``:
                      ``query`` (required), ``top`` (optional, default 5).

        Returns:
            A dict with a ``results`` key containing a list of hit dicts::

                {
                  "results": [
                    {
                      "id": "...",
                      "name": "Q3 Budget Forecast.xlsx",
                      "webUrl": "https://contoso.sharepoint.com/...",
                      "lastModifiedDateTime": "2026-04-01T14:00:00Z",
                      "lastModifiedBy": {"user": {"displayName": "Alice"}},
                      "size": 204800,
                      "parentReference": {"siteId": "...", "driveId": "..."},
                      "score": 1,
                      "summary": "...highlighted excerpt..."
                    }
                  ],
                  "total_returned": 1
                }

        Raises:
            pydantic.ValidationError: Query is blank or ``top`` is out of range.
            GraphAuthError: Token is expired or malformed.
            GraphPermissionError: Token lacks ``Sites.Read.All``.
            GraphRateLimitError: Graph is throttling; check ``exc.retry_after``.
            GraphServerError: Transient Graph-side failure.
        """
        input_data = SharePointToolInput(**kwargs)

        if not token or not token.strip():
            raise ValueError("OBO token is empty. Cannot call Graph API.")

        logger.info(
            "SharePointTool.execute: query=%r top=%d",
            input_data.query,
            input_data.top,
        )

        async with GraphClient() as client:
            hits = await client.search_sharepoint(
                token=token,
                query=input_data.query,
                top=input_data.top,
            )

        return {
            "results": hits,
            "total_returned": len(hits),
        }

    def input_schema(self) -> dict[str, Any]:
        """Return JSON Schema for SharePointTool arguments (MCP-compatible)."""
        return SharePointToolInput.model_json_schema()