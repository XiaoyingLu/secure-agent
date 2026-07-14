"""MCP tool for retrieving user emails via Microsoft Graph."""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from graph.graph_client import GraphClient
from tools.base_tool import BaseTool

logger = logging.getLogger(__name__)


class EmailToolInput(BaseModel):
    """Input schema for EmailTool."""

    top: int = Field(default=10, ge=1, le=50, description="Maximum number of emails to return (1-50)")
    filter_unread: bool = Field(default=False, description="If True, only return unread emails")


class EmailTool(BaseTool):
    """MCP tool for retrieving the user's emails from Microsoft Graph."""

    def __init__(self) -> None:
        super().__init__(
            name="get_my_emails",
            description="Retrieve the user's emails from Microsoft Graph. Supports filtering by read status and limiting results.",
        )

    async def execute(self, token: str, **kwargs: Any) -> dict[str, Any]:
        """Execute the email retrieval tool.

        Args:
            token: On-Behalf-Of access token for Microsoft Graph.
            **kwargs: Tool arguments (top, filter_unread).

        Returns:
            Dictionary with ``emails`` key containing a list of email dicts.
        """
        input_data = EmailToolInput(**kwargs)

        if not token or not token.strip():
            raise ValueError("OBO token is empty. Cannot call Graph API.")

        async with GraphClient() as client:
            response = await client.get_messages(
                token=token,
                top=input_data.top,
                filter_unread=input_data.filter_unread,
            )

        # get_messages() returns a list directly (already extracted from response.value)
        emails = []
        for msg in response:
            body_preview = msg.get("bodyPreview", "")
            emails.append(
                {
                    "id": msg.get("id"),
                    "subject": msg.get("subject"),
                    "from": msg.get("from"),
                    "receivedDateTime": msg.get("receivedDateTime"),
                    "bodyPreview": self._strip_html(body_preview),
                }
            )

        return {"emails": emails}

    def _strip_html(self, text: str) -> str:
        """Remove HTML tags from text.

        Args:
            text: String potentially containing HTML.

        Returns:
            Plain text without HTML tags.
        """
        if not text:
            return ""
        return re.sub(r"<[^>]+>", "", text)

    def input_schema(self) -> dict[str, Any]:
        """Return JSON Schema for EmailTool arguments."""
        return EmailToolInput.model_json_schema()