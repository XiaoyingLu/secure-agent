import httpx
import pytest

from graph.graph_client import (
    GraphAuthError,
    GraphClient,
    GraphClientError,
    GraphPermissionError,
    GraphRateLimitError,
    GraphServerError,
)

def _mock_response(
    mocker,
    *,
    status_code: int,
    json_data: dict | None = None,
    headers: dict | None = None,
    reason: str = "OK",
    text: str | None = None,
) -> httpx.Response:
    response = mocker.MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.reason_phrase = reason
    response.text = text or reason
    response.headers = httpx.Headers(headers or {})
    response.is_success = 200 <= status_code < 300
    if json_data is not None:
        response.json.return_value = json_data
    else:
        response.json.side_effect = ValueError("no body")
    return response


@pytest.fixture
def mock_http(mocker):
    return mocker.AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def graph_client(mock_http):
    return GraphClient(http_client=mock_http)


@pytest.mark.asyncio
async def test_get_me_success(graph_client, mock_http, mocker):
    profile = {"id": "user-1", "displayName": "Test User", "mail": "test@contoso.com"}
    mock_http.get.return_value = _mock_response(
        mocker, status_code=200, json_data=profile
    )

    result = await graph_client.get_me("delegated-token")

    assert result == profile
    mock_http.get.assert_awaited_once_with(
        "https://graph.microsoft.com/v1.0/me",
        headers={"Authorization": "Bearer delegated-token", 'Accept': 'application/json'},
    )


@pytest.mark.asyncio
async def test_get_me_401_raises_graph_auth_error(graph_client, mock_http, mocker):
    mock_http.get.return_value = _mock_response(
        mocker,
        status_code=401,
        json_data={"error": {"code": "InvalidAuthenticationToken", "message": "Token expired"}},
        reason="Unauthorized",
    )

    with pytest.raises(GraphAuthError, match="Token expired"):
        await graph_client.get_me("bad-token")


@pytest.mark.asyncio
async def test_get_me_403_raises_graph_permission_error(graph_client, mock_http, mocker):
    mock_http.get.return_value = _mock_response(
        mocker,
        status_code=403,
        json_data={
            "error": {
                "code": "Forbidden",
                "message": "Insufficient privileges to complete the operation.",
            }
        },
        reason="Forbidden",
    )

    with pytest.raises(GraphPermissionError, match="Insufficient privileges"):
        await graph_client.get_me("limited-token")


@pytest.mark.asyncio
async def test_get_me_429_raises_graph_rate_limit_error_with_retry_after(
    graph_client, mock_http, mocker
):
    mock_http.get.return_value = _mock_response(
        mocker,
        status_code=429,
        json_data={"error": {"code": "TooManyRequests", "message": "Throttled"}},
        headers={"Retry-After": "120"},
        reason="Too Many Requests",
    )

    with pytest.raises(GraphRateLimitError) as exc_info:
        await graph_client.get_me("token")

    assert exc_info.value.retry_after == 120
    assert "Throttled" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_me_429_without_retry_after_header(graph_client, mock_http, mocker):
    mock_http.get.return_value = _mock_response(
        mocker,
        status_code=429,
        json_data={"error": {"message": "Slow down"}},
        reason="Too Many Requests",
    )

    with pytest.raises(GraphRateLimitError) as exc_info:
        await graph_client.get_me("token")

    assert exc_info.value.retry_after is None


@pytest.mark.asyncio
async def test_get_me_500_raises_graph_server_error(graph_client, mock_http, mocker):
    mock_http.get.return_value = _mock_response(
        mocker,
        status_code=500,
        reason="Internal Server Error",
        text="Internal Server Error",
    )

    with pytest.raises(GraphServerError, match="Internal Server Error"):
        await graph_client.get_me("token")


@pytest.mark.asyncio
async def test_get_messages_success(graph_client, mock_http, mocker):
    messages = [{"id": "msg-1", "subject": "Test Email"}]
    mock_http.get.return_value = _mock_response(
        mocker, status_code=200, json_data={"value": messages}
    )

    result = await graph_client.get_messages("token", top=5, filter_unread=True)

    assert result == messages
    mock_http.get.assert_awaited_once()
    call_kwargs = mock_http.get.call_args.kwargs
    assert call_kwargs["params"]["$top"] == 5
    assert "isRead eq false" in call_kwargs["params"]["$filter"]


@pytest.mark.asyncio
async def test_search_sharepoint_success(graph_client, mock_http, mocker):
    hits = [
        {
            "resource": {
                "id": "item-1",
                "name": "Report.docx",
                "webUrl": "https://sharepoint.com/doc",
            },
            "rank": 1,
        }
    ]
    mock_http.post.return_value = _mock_response(
        mocker,
        status_code=200,
        json_data={"value": [{"hitsContainers": [{"hits": hits}]}]},
    )

    result = await graph_client.search_sharepoint("token", "financial report", top=1)

    assert len(result) == 1
    assert result[0]["id"] == "item-1"
    assert result[0]["name"] == "Report.docx"
    assert result[0]["score"] == 1

    mock_http.post.assert_awaited_once()
    call_kwargs = mock_http.post.call_args.kwargs
    payload = call_kwargs["json"]
    assert payload["requests"][0]["query"]["queryString"] == "financial report"
    assert payload["requests"][0]["size"] == 1


@pytest.mark.asyncio
async def test_get_events_success(graph_client, mock_http, mocker):
    events = [{"id": "event-1", "subject": "Sync"}]
    mock_http.get.return_value = _mock_response(
        mocker, status_code=200, json_data={"value": events}
    )

    result = await graph_client.get_events(
        "token", "2026-05-21T00:00:00", "2026-05-28T23:59:59", top=3
    )

    assert result == events
    mock_http.get.assert_awaited_once()
    call_kwargs = mock_http.get.call_args.kwargs
    params = call_kwargs["params"]
    assert params["$top"] == 3
    assert "start/dateTime ge '2026-05-21T00:00:00'" in params["$filter"]
    assert "end/dateTime le '2026-05-28T23:59:59'" in params["$filter"]


@pytest.mark.asyncio
async def test_owned_client_lifecycle(mocker):
    mock_client = mocker.AsyncMock(spec=httpx.AsyncClient)
    mocker.patch("graph.graph_client.httpx.AsyncClient", return_value=mock_client)

    async with GraphClient() as client:
        mock_client.get.return_value = _mock_response(
            mocker, status_code=200, json_data={"id": "1"}
        )
        await client.get_me("token")

    mock_client.aclose.assert_awaited_once()
