import httpx
import pytest

from graph.graph_client import (
    GraphAuthError,
    GraphClient,
    GraphClientError,
    GraphPermissionError,
    GraphRateLimitError,
)


def _mock_response(
    mocker,
    *,
    status_code: int,
    json_data: dict | None = None,
    headers: dict | None = None,
    reason: str = "OK",
) -> httpx.Response:
    response = mocker.MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.reason_phrase = reason
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
    return GraphClient(client=mock_http)


@pytest.mark.asyncio
async def test_get_me_success(graph_client, mock_http, mocker):
    profile = {"id": "user-1", "displayName": "Test User", "mail": "test@contoso.com"}
    mock_http.get.return_value = _mock_response(
        mocker, status_code=200, json_data=profile
    )

    result = await graph_client.get_me("delegated-token")

    assert result == profile
    mock_http.get.assert_awaited_once_with(
        "/me",
        headers={"Authorization": "Bearer delegated-token"},
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
async def test_get_me_500_raises_graph_client_error(graph_client, mock_http, mocker):
    mock_http.get.return_value = _mock_response(
        mocker,
        status_code=500,
        reason="Internal Server Error",
    )

    with pytest.raises(GraphClientError, match="Internal Server Error"):
        await graph_client.get_me("token")


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
