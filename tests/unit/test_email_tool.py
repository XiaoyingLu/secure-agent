"""Unit tests for EmailTool."""

import pytest

from graph.graph_client import GraphAuthError, GraphPermissionError, GraphRateLimitError
from tools.email_tool import EmailTool, EmailToolInput


@pytest.fixture
def email_tool():
    """Fixture providing EmailTool instance."""
    return EmailTool()


@pytest.fixture
def mock_graph_response():
    """Sample Graph API response for messages."""
    return {
        "value": [
            {
                "id": "msg-1",
                "subject": "Test Email 1",
                "from": {"emailAddress": {"name": "John Doe", "address": "john@example.com"}},
                "receivedDateTime": "2026-05-22T10:30:00Z",
                "bodyPreview": "This is a test email with <b>bold</b> text.",
                "isRead": False,
            },
            {
                "id": "msg-2",
                "subject": "Test Email 2",
                "from": {"emailAddress": {"name": "Jane Smith", "address": "jane@example.com"}},
                "receivedDateTime": "2026-05-22T09:15:00Z",
                "bodyPreview": "<p>Another test email with <a href='#'>link</a></p>",
                "isRead": True,
            },
        ]
    }


@pytest.mark.asyncio
async def test_email_tool_name_and_description(email_tool):
    """Test tool has correct name and description."""
    assert email_tool.name == "get_my_emails"
    assert "emails" in email_tool.description.lower()
    assert "Microsoft Graph" in email_tool.description


@pytest.mark.asyncio
async def test_email_tool_input_schema(email_tool):
    """Test input schema matches Pydantic model."""
    schema = email_tool.input_schema()

    assert schema["type"] == "object"
    assert "properties" in schema
    assert "top" in schema["properties"]
    assert "filter_unread" in schema["properties"]

    top_schema = schema["properties"]["top"]
    assert top_schema["type"] == "integer"
    assert top_schema["default"] == 10
    assert "minimum" in top_schema
    assert "maximum" in top_schema

    filter_schema = schema["properties"]["filter_unread"]
    assert filter_schema["type"] == "boolean"
    assert filter_schema["default"] is False


def test_email_tool_input_validation_default_values():
    """Test Pydantic input validation with defaults."""
    input_data = EmailToolInput()
    assert input_data.top == 10
    assert input_data.filter_unread is False


def test_email_tool_input_validation_custom_values():
    """Test Pydantic input validation with custom values."""
    input_data = EmailToolInput(top=25, filter_unread=True)
    assert input_data.top == 25
    assert input_data.filter_unread is True


def test_email_tool_input_validation_top_minimum():
    """Test Pydantic validates top minimum (1)."""
    with pytest.raises(ValueError, match="greater than or equal to 1"):
        EmailToolInput(top=0)


def test_email_tool_input_validation_top_maximum():
    """Test Pydantic validates top maximum (50)."""
    with pytest.raises(ValueError, match="less than or equal to 50"):
        EmailToolInput(top=51)


@pytest.mark.asyncio
async def test_email_tool_execute_success(email_tool, mocker, mock_graph_response):
    """Test successful email retrieval."""
    mock_graph_client = mocker.patch("tools.email_tool.GraphClient")
    mock_client_instance = mocker.AsyncMock()
    mock_graph_client.return_value.__aenter__.return_value = mock_client_instance
    mock_client_instance.get_messages.return_value = mock_graph_response

    result = await email_tool.execute(token="delegated-token", top=10, filter_unread=False)

    mock_client_instance.get_messages.assert_awaited_once_with(
        token="delegated-token",
        top=10,
        filter_unread=False,
    )

    assert "emails" in result
    assert len(result["emails"]) == 2

    email1 = result["emails"][0]
    assert email1["id"] == "msg-1"
    assert email1["subject"] == "Test Email 1"
    assert email1["from"]["emailAddress"]["name"] == "John Doe"
    assert email1["receivedDateTime"] == "2026-05-22T10:30:00Z"
    assert email1["bodyPreview"] == "This is a test email with bold text."


@pytest.mark.asyncio
async def test_email_tool_execute_with_filter_unread(email_tool, mocker):
    """Test email retrieval with filter_unread=True."""
    mock_graph_client = mocker.patch("tools.email_tool.GraphClient")
    mock_client_instance = mocker.AsyncMock()
    mock_graph_client.return_value.__aenter__.return_value = mock_client_instance
    mock_client_instance.get_messages.return_value = {"value": []}

    await email_tool.execute(token="token", top=5, filter_unread=True)

    mock_client_instance.get_messages.assert_awaited_once_with(
        token="token",
        top=5,
        filter_unread=True,
    )


@pytest.mark.asyncio
async def test_email_tool_execute_empty_response(email_tool, mocker):
    """Test email retrieval with no messages."""
    mock_graph_client = mocker.patch("tools.email_tool.GraphClient")
    mock_client_instance = mocker.AsyncMock()
    mock_graph_client.return_value.__aenter__.return_value = mock_client_instance
    mock_client_instance.get_messages.return_value = {"value": []}

    result = await email_tool.execute(token="token")

    assert result == {"emails": []}


@pytest.mark.asyncio
async def test_email_tool_execute_429_rate_limit_error(email_tool, mocker):
    """Test email retrieval propagates 429 rate limit error."""
    mock_graph_client = mocker.patch("tools.email_tool.GraphClient")
    mock_client_instance = mocker.AsyncMock()
    mock_graph_client.return_value.__aenter__.return_value = mock_client_instance

    retry_error = GraphRateLimitError("Too many requests", status_code=429, retry_after=120)
    mock_client_instance.get_messages.side_effect = retry_error

    with pytest.raises(GraphRateLimitError) as exc_info:
        await email_tool.execute(token="token", top=10)

    assert exc_info.value.retry_after == 120
    assert "Too many requests" in str(exc_info.value)


@pytest.mark.asyncio
async def test_email_tool_execute_401_auth_error(email_tool, mocker):
    """Test email retrieval propagates 401 auth error."""
    mock_graph_client = mocker.patch("tools.email_tool.GraphClient")
    mock_client_instance = mocker.AsyncMock()
    mock_graph_client.return_value.__aenter__.return_value = mock_client_instance

    auth_error = GraphAuthError("Invalid authentication token", status_code=401)
    mock_client_instance.get_messages.side_effect = auth_error

    # Add this to confirm the mock is wired up
    assert mock_client_instance.get_messages.side_effect is auth_error

    with pytest.raises(GraphAuthError, match="Invalid authentication token"):
        await email_tool.execute(token="bad-token")


@pytest.mark.asyncio
async def test_email_tool_execute_403_permission_error(email_tool, mocker):
    """Test email retrieval propagates 403 permission error."""
    mock_graph_client = mocker.patch("tools.email_tool.GraphClient")
    mock_client_instance = mocker.AsyncMock()
    mock_graph_client.return_value.__aenter__.return_value = mock_client_instance

    perm_error = GraphPermissionError("Insufficient privileges", status_code=403)
    mock_client_instance.get_messages.side_effect = perm_error

    with pytest.raises(GraphPermissionError, match="Insufficient privileges"):
        await email_tool.execute(token="limited-token")


@pytest.mark.asyncio
async def test_email_tool_strip_html_simple(email_tool):
    """Test HTML stripping with simple tags."""
    html = "<p>Hello <b>world</b></p>"
    result = email_tool._strip_html(html)
    assert result == "Hello world"


@pytest.mark.asyncio
async def test_email_tool_strip_html_complex(email_tool):
    """Test HTML stripping with complex nested tags."""
    html = '<div><span class="highlight"><a href="#">Click here</a></span></div>'
    result = email_tool._strip_html(html)
    assert result == "Click here"


@pytest.mark.asyncio
async def test_email_tool_strip_html_empty_string(email_tool):
    """Test HTML stripping with empty string."""
    result = email_tool._strip_html("")
    assert result == ""


@pytest.mark.asyncio
async def test_email_tool_strip_html_none(email_tool):
    """Test HTML stripping with None."""
    result = email_tool._strip_html(None)
    assert result == ""


@pytest.mark.asyncio
async def test_email_tool_strip_html_no_html(email_tool):
    """Test HTML stripping with plain text."""
    plain = "Just plain text"
    result = email_tool._strip_html(plain)
    assert result == plain


@pytest.mark.asyncio
async def test_email_tool_strip_html_unclosed_tags(email_tool):
    """Test HTML stripping handles unclosed tags gracefully."""
    html = "<div>Unclosed <span>tags"
    result = email_tool._strip_html(html)
    assert result == "Unclosed tags"


@pytest.mark.asyncio
async def test_email_tool_body_preview_stripped_in_result(email_tool, mocker):
    """Test bodyPreview HTML is stripped in returned result."""
    mock_graph_client = mocker.patch("tools.email_tool.GraphClient")
    mock_client_instance = mocker.AsyncMock()
    mock_graph_client.return_value.__aenter__.return_value = mock_client_instance

    response_with_html = {
        "value": [
            {
                "id": "msg-1",
                "subject": "HTML Email",
                "from": {"emailAddress": {"name": "Test", "address": "test@example.com"}},
                "receivedDateTime": "2026-05-22T10:00:00Z",
                "bodyPreview": "<div><p>Paragraph with <strong>bold</strong> and <em>italic</em></p></div>",
            }
        ]
    }
    mock_client_instance.get_messages.return_value = response_with_html

    result = await email_tool.execute(token="token")

    assert result["emails"][0]["bodyPreview"] == "Paragraph with bold and italic"


@pytest.mark.asyncio
async def test_email_tool_to_mcp_schema(email_tool):
    """Test to_mcp_schema returns correct MCP tool definition."""
    schema = email_tool.to_mcp_schema()

    assert schema["name"] == "get_my_emails"
    assert "description" in schema
    assert "inputSchema" in schema
    assert schema["inputSchema"]["type"] == "object"