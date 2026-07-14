"""Async Microsoft Graph API client."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
_ME_PATH = "/me"


class GraphClientError(Exception):
    """Base class for all Graph API errors."""
 
    def __init__(self, message: str, status_code: int, response_body: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body or {}
 
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(status_code={self.status_code}, message={self.args[0]!r})"


class GraphAuthError(GraphClientError):
    """Raised when Graph returns 401 (invalid or expired token)."""


class GraphPermissionError(GraphClientError):
    """Raised when Graph returns 403 (insufficient delegated permissions)."""


class GraphRateLimitError(GraphClientError):
    """Raised on HTTP 429 — Graph is throttling the caller.
 
    Attributes:
        retry_after: Seconds to wait before retrying, as advised by Graph.
                     None if the Retry-After header was absent.
    """
 
    def __init__(
        self,
        message: str,
        status_code: int,
        retry_after: int | None = None,
        response_body: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, status_code, response_body)
        self.retry_after = retry_after


class GraphNotFoundError(GraphClientError):
    """Raised on HTTP 404 — the requested resource does not exist."""
 
 
class GraphServerError(GraphClientError):
    """Raised on HTTP 5xx — Graph-side failure."""


def _parse_retry_after(response: httpx.Response) -> int | str | None:
    """Parse the Retry-After header from a Graph response."""
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return value


def _graph_error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
        if isinstance(body, dict) and "error" in body:
            err = body["error"]
            if isinstance(err, dict):
                return err.get("message") or err.get("code") or response.reason_phrase
    except Exception:
        pass
    return response.reason_phrase or f"HTTP {response.status_code}"


class GraphClient:
    """Async client for Microsoft Graph API.
 
    All methods forward the caller-supplied delegated token so that Graph
    enforces the authenticated user's own permission boundaries.  The client
    never stores tokens internally.
 
    Usage::
 
        async with GraphClient() as client:
            me = await client.get_me(token=obo_token)
 
    Or reuse a single instance across the app lifetime::
 
        client = GraphClient()
        me = await client.get_me(token=obo_token)
        await client.aclose()
    """
 
    def __init__(
        self,
        base_url: str = GRAPH_BASE_URL,
        timeout: float = 30.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        # Allow injection of a pre-configured client (useful in tests).
        self._client = http_client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = http_client is None
 
    # ------------------------------------------------------------------
    # Context-manager support
    # ------------------------------------------------------------------
 
    async def __aenter__(self) -> GraphClient:
        return self
 
    async def __aexit__(self, *_: object) -> None:
        await self.aclose()
 
    async def aclose(self) -> None:
        """Close the underlying HTTP client if we own it."""
        if self._owns_client:
            await self._client.aclose()
 
    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
 
    def _auth_headers(self, token: str) -> dict[str, str]:
        if not token or not token.strip():
            raise ValueError("Authorization token must not be empty or whitespace")
        auth_header = f"Bearer {token}"
        print(f"[GRAPH] Auth header: Bearer {token[:50]}...")  # DEBUG
        print(f"[GRAPH] Token length: {len(token)}")  # DEBUG
        print(f"[GRAPH] Token starts with: {repr(token[:20])}")  # DEBUG - show any whitespace
        print(f"[GRAPH] Token ends with: {repr(token[-20:])}")  # DEBUG
        print(f"[GRAPH] Full auth header: {repr(auth_header[:100])}")  # DEBUG - see exact format
        logger.debug(
            "Graph auth header: Bearer %s... (len=%d)",
            token[:20],
            len(token),
        )
        return {
            "Authorization": auth_header,
            "Accept": "application/json",
        }
 
    def _raise_for_status(self, response: httpx.Response) -> None:
        """Map Graph HTTP error codes to typed exceptions.
 
        Args:
            response: The completed httpx Response object.
 
        Raises:
            GraphAuthError: HTTP 401.
            GraphPermissionError: HTTP 403.
            GraphRateLimitError: HTTP 429 (includes retry_after seconds).
            GraphNotFoundError: HTTP 404.
            GraphServerError: HTTP 5xx.
            GraphError: Any other non-2xx status.
        """
        if response.is_success:
            return
 
        status = response.status_code
        
        # Log the full response for debugging (without tokens).
        logger.debug(
            "Graph API error response: status=%d url=%s headers=%s body=%s",
            status,
            response.url,
            dict(response.headers),
            response.text[:1000],
        )
        
        # Try to extract Graph's structured error body.
        body: dict[str, Any] = {}
        try:
            body = response.json()
        except Exception as parse_err:
            logger.debug("Failed to parse error response JSON: %s", parse_err)

        error_detail = body.get("error", {})
        code = error_detail.get("code", "Unknown")
        graph_message = error_detail.get("message", response.text or "No message returned")
        message = f"[{code}] {graph_message}"

        logger.error(
            "Graph API error: status=%d code=%s message=%s url=%s",
            status,
            code,
            graph_message[:200],
            response.url,
        )

        if status == 401:
            print(f"[GRAPH] 401 AUTH ERROR: code={code} message={graph_message}")  # DEBUG
            print(f"[GRAPH] 401 ERROR response body: {response.text[:1000]}")  # DEBUG
            raise GraphAuthError(message, status, body)

        if status == 403:
            raise GraphPermissionError(message, status, body)

        if status == 429:
            retry_after = _parse_retry_after(response)
            logger.warning("Graph 429 — throttled. retry_after=%s", retry_after)
            raise GraphRateLimitError(message, status, retry_after=retry_after, response_body=body)

        if status == 404:
            raise GraphNotFoundError(message, status, body)
 
        if status >= 500:
            logger.error("Graph 5xx error. status=%d code=%s", status, code)
            raise GraphServerError(message, status, body)
 
        raise GraphClientError(message, status, body)
 
    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------
 
    async def get_me(self, token: str) -> dict[str, Any]:
        """Return the signed-in user's profile from Graph /me.
 
        Calls the ``/me`` endpoint with the supplied delegated token so that
        Graph returns only the data the authenticated user is allowed to see.
 
        Args:
            token: A valid delegated OBO access token scoped to
                ``https://graph.microsoft.com/User.Read``.
 
        Returns:
            A dict containing the user's profile fields, e.g.::
 
                {
                    "id": "...",
                    "displayName": "Alice Smith",
                    "mail": "alice@contoso.com",
                    "userPrincipalName": "alice@contoso.com",
                    "jobTitle": "Engineer",
                }
 
        Raises:
            GraphAuthError: The token is expired, malformed, or missing.
            GraphPermissionError: The token lacks ``User.Read`` scope.
            GraphRateLimitError: Graph is throttling requests; check
                ``exc.retry_after`` for the suggested wait in seconds.
            GraphServerError: A transient Graph-side failure occurred.
        """
        url = f"{self._base_url}/me"
        logger.debug("GET %s", url)
        print(f"[GRAPH] Testing /me endpoint to validate token")  # DEBUG
 
        response = await self._client.get(url, headers=self._auth_headers(token))
        print(f"[GRAPH] /me response: status={response.status_code}")  # DEBUG
        self._raise_for_status(response)
        return response.json()
 
    async def get_messages(
        self,
        token: str,
        top: int = 10,
        filter_unread: bool = False,
    ) -> list[dict[str, Any]]:
        """Return recent messages from the signed-in user's mailbox.
 
        Args:
            token: A valid delegated OBO token scoped to ``Mail.Read``.
            top: Maximum number of messages to return (1–50).
            filter_unread: When True, only return unread messages.
 
        Returns:
            A list of message dicts with keys: ``id``, ``subject``,
            ``from``, ``receivedDateTime``, ``bodyPreview``.
 
        Raises:
            GraphAuthError: Token is invalid.
            GraphPermissionError: Token lacks ``Mail.Read``.
            GraphRateLimitError: Throttled by Graph.
        """
        params: dict[str, Any] = {
            "$top": top,
            "$select": "id,subject,from,receivedDateTime,bodyPreview",
        }
        if filter_unread:
            params["$filter"] = "isRead eq false"
 
        url = f"{self._base_url}/me/messages"
        logger.debug("GET %s top=%d filter_unread=%s", url, top, filter_unread)
        
        headers = self._auth_headers(token)
        print(f"[GRAPH] Sending request to {url}")  # DEBUG
        print(f"[GRAPH] Authorization header value: {repr(headers.get('Authorization', 'MISSING'))}")  # DEBUG - EXACT VALUE
        print(f"[GRAPH] Headers being sent: {list(headers.keys())}")  # DEBUG
        print(f"[GRAPH] Authorization header present: {'Authorization' in headers}")  # DEBUG
        
        response = await self._client.get(url, headers=headers, params=params)
        print(f"[GRAPH] Response status={response.status_code}")  # DEBUG
        
        # Log what was actually sent (httpx request object)
        print(f"[GRAPH] Actual request headers sent: {dict(response.request.headers)}")  # DEBUG - see what httpx actually sent
        print(f"[GRAPH] Actual Auth header in request: {repr(response.request.headers.get('authorization', 'MISSING'))}")  # DEBUG
        
        self._raise_for_status(response)
        return response.json().get("value", [])
 
    async def search_sharepoint(
        self,
        token: str,
        query: str,
        top: int = 5,
    ) -> list[dict[str, Any]]:
        """Search SharePoint content accessible to the signed-in user.
 
        Uses the Graph Search API (``/search/query``) with a ``driveItem``
        entity type so results are scoped to SharePoint / OneDrive files the
        user can already access.  Graph enforces the user's ACLs — no data
        from sites they lack permission to read will be returned.
 
        Args:
            token: A valid delegated OBO token scoped to ``Sites.Read.All``.
            query: Free-text search query (e.g. ``"Q3 budget report"``).
            top: Maximum number of results to return (1–25).
 
        Returns:
            A flat list of hit dicts, each containing the fields requested
            via ``fields`` in the search request body, plus Graph metadata.
            Returns an empty list when there are no matches.
 
        Raises:
            GraphAuthError: Token is invalid.
            GraphPermissionError: Token lacks ``Sites.Read.All``.
            GraphRateLimitError: Throttled by Graph.
        """
        url = f"{self._base_url}/search/query"
        payload: dict[str, Any] = {
            "requests": [
                {
                    "entityTypes": ["driveItem"],
                    "query": {"queryString": query},
                    "from": 0,
                    "size": top,
                    "fields": [
                        "id",
                        "name",
                        "webUrl",
                        "lastModifiedDateTime",
                        "lastModifiedBy",
                        "size",
                        "parentReference",
                    ],
                }
            ]
        }
        headers = {**self._auth_headers(token), "Content-Type": "application/json"}
        logger.debug("POST %s query=%r top=%d", url, query, top)
 
        response = await self._client.post(url, headers=headers, json=payload)
        self._raise_for_status(response)
 
        # Unwrap the nested Graph Search response envelope.
        hits: list[dict[str, Any]] = []
        for response_block in response.json().get("value", []):
            for hit_container in response_block.get("hitsContainers", []):
                for hit in hit_container.get("hits", []):
                    resource = hit.get("resource", {})
                    hits.append(
                        {
                            "id": resource.get("id"),
                            "name": resource.get("name"),
                            "webUrl": resource.get("webUrl"),
                            "lastModifiedDateTime": resource.get("lastModifiedDateTime"),
                            "lastModifiedBy": resource.get("lastModifiedBy"),
                            "size": resource.get("size"),
                            "parentReference": resource.get("parentReference"),
                            "score": hit.get("rank"),
                            "summary": hit.get("summary"),
                        }
                    )
        return hits
 
    async def get_events(
        self,
        token: str,
        start_datetime: str,
        end_datetime: str,
        top: int = 10,
    ) -> list[dict[str, Any]]:
        """Return calendar events in the given time range.
 
        Args:
            token: A valid delegated OBO token scoped to ``Calendars.Read``.
            start_datetime: ISO 8601 start (e.g. ``"2026-05-21T00:00:00"``).
            end_datetime: ISO 8601 end (e.g. ``"2026-05-28T23:59:59"``).
            top: Maximum number of events to return.
 
        Returns:
            A list of event dicts with keys: ``id``, ``subject``,
            ``start``, ``end``, ``organizer``, ``location``.
 
        Raises:
            GraphAuthError: Token is invalid.
            GraphPermissionError: Token lacks ``Calendars.Read``.
            GraphRateLimitError: Throttled by Graph.
        """
        # Use calendarView (recommended over /me/events?$filter) — it handles
        # recurring event expansion and accepts startDateTime/endDateTime as
        # plain query parameters rather than OData $filter expressions.
        # Note: calendarView returns results in chronological order by default;
        # Graph rejects $orderby on complex properties like 'start'.
        params: dict[str, Any] = {
            "startDateTime": start_datetime,
            "endDateTime": end_datetime,
            "$top": top,
            "$select": "id,subject,start,end,organizer,location",
        }
 
        url = f"{self._base_url}/me/calendarView"
        headers = {
            **self._auth_headers(token),
            "Prefer": 'outlook.timezone="UTC"',
        }
        print(f"[GRAPH] Token={token}")  # DEBUG
        logger.debug("GET %s start=%s end=%s", url, start_datetime, end_datetime)
        print(f"[GRAPH] GET {url} with headers={list(headers.keys())}")  # DEBUG
        
        # Decode token for diagnostics (before sending to Graph)
        try:
            import base64
            import json
            parts = token.split(".")
            if len(parts) >= 2:
                padded = parts[1] + "=" * (-len(parts[1]) % 4)
                payload = json.loads(base64.urlsafe_b64decode(padded))
                aud = payload.get("aud", "NO_AUD")
                scp = payload.get("scp", "NO_SCOPES")
                print(f"[GRAPH] Token aud={aud} scp={scp}")  # DEBUG
        except Exception as e:
            print(f"[GRAPH] Could not decode token: {e}")  # DEBUG
        
        response = await self._client.get(url, headers=headers, params=params)
        print(f"[GRAPH] Response status={response.status_code}")  # DEBUG - calendar GET
        
        # Log what was actually sent (httpx request object)
        print(f"[GRAPH] Actual request headers sent (calendarView): {dict(response.request.headers)}")  # DEBUG
        print(f"[GRAPH] Actual Auth header in request (calendarView): {repr(response.request.headers.get('authorization', 'MISSING'))}")  # DEBUG
        
        self._raise_for_status(response)
        return response.json().get("value", [])
