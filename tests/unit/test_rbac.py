import pytest
from fastapi import HTTPException

from auth.rbac import (
    AGENT_ADMIN_ROLE_NAME,
    AGENT_USER_ROLE_NAME,
    FORBIDDEN_DETAIL,
    require_role,
)


@pytest.fixture
def mock_request(mocker):
    request = mocker.MagicMock()
    request.state = mocker.MagicMock()
    request.state.user = None
    return request


@pytest.mark.asyncio
async def test_require_role_passes_when_role_present(mock_request):
    mock_request.state.user = {
        "sub": "user-1",
        "roles": [AGENT_USER_ROLE_NAME, AGENT_ADMIN_ROLE_NAME],
    }
    dependency = require_role(AGENT_USER_ROLE_NAME)

    await dependency(mock_request)


@pytest.mark.asyncio
async def test_require_role_raises_403_when_role_missing(mock_request):
    mock_request.state.user = {"sub": "user-1", "roles": [AGENT_ADMIN_ROLE_NAME]}
    dependency = require_role(AGENT_USER_ROLE_NAME)

    with pytest.raises(HTTPException) as exc_info:
        await dependency(mock_request)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == FORBIDDEN_DETAIL


@pytest.mark.asyncio
async def test_require_role_raises_403_when_roles_claim_missing(mock_request):
    mock_request.state.user = {"sub": "user-1"}
    dependency = require_role(AGENT_USER_ROLE_NAME)

    with pytest.raises(HTTPException) as exc_info:
        await dependency(mock_request)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_role_raises_403_when_roles_not_a_list(mock_request):
    mock_request.state.user = {"sub": "user-1", "roles": AGENT_USER_ROLE_NAME}
    dependency = require_role(AGENT_USER_ROLE_NAME)

    with pytest.raises(HTTPException) as exc_info:
        await dependency(mock_request)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_role_raises_403_when_user_state_missing(mock_request):
    mock_request.state.user = None
    dependency = require_role(AGENT_USER_ROLE_NAME)

    with pytest.raises(HTTPException) as exc_info:
        await dependency(mock_request)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_role_raises_403_when_user_not_dict(mock_request):
    mock_request.state.user = "not-a-dict"
    dependency = require_role(AGENT_USER_ROLE_NAME)

    with pytest.raises(HTTPException) as exc_info:
        await dependency(mock_request)

    assert exc_info.value.status_code == 403
