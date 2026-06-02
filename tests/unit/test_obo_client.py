import time

import pytest

from auth.obo_client import OBOClient, OBOError


@pytest.fixture
def mock_cca(mocker):
    return mocker.MagicMock()


@pytest.fixture
def obo_client(mock_cca):
    return OBOClient(
        tenant_id="test-tenant",
        client_id="test-client-id",
        client_secret="test-secret",
        app=mock_cca,
    )


@pytest.mark.asyncio
async def test_exchange_returns_access_token(obo_client, mock_cca):
    mock_cca.acquire_token_on_behalf_of.return_value = {
        "access_token": "obo-access-token",
        "expires_on": int(time.time()) + 3600,
    }

    token = await obo_client.exchange("incoming-user-jwt", ["User.Read"])

    assert token == "obo-access-token"
    mock_cca.acquire_token_on_behalf_of.assert_called_once_with(
        "incoming-user-jwt",
        ["User.Read"],
    )


@pytest.mark.asyncio
async def test_exchange_raises_obo_error_with_msal_description(obo_client, mock_cca):
    mock_cca.acquire_token_on_behalf_of.return_value = {
        "error": "invalid_grant",
        "error_description": "AADSTS50013: Assertion is invalid.",
    }

    with pytest.raises(OBOError, match="Assertion is invalid"):
        await obo_client.exchange("bad-token", ["User.Read"])


@pytest.mark.asyncio
async def test_exchange_raises_when_access_token_missing(obo_client, mock_cca):
    mock_cca.acquire_token_on_behalf_of.return_value = {"expires_in": 3600}

    with pytest.raises(OBOError, match="missing access_token"):
        await obo_client.exchange("user-token", ["User.Read"])


@pytest.mark.asyncio
async def test_exchange_uses_cache_until_expiry(obo_client, mock_cca, monkeypatch):
    now = 1_700_000_000.0
    monkeypatch.setattr("auth.obo_client.time.time", lambda: now)
    mock_cca.acquire_token_on_behalf_of.return_value = {
        "access_token": "cached-token",
        "expires_on": int(now) + 3600,
    }

    first = await obo_client.exchange("user-token", ["User.Read"])
    second = await obo_client.exchange("user-token", ["User.Read"])

    assert first == second == "cached-token"
    mock_cca.acquire_token_on_behalf_of.assert_called_once()


@pytest.mark.asyncio
async def test_exchange_refetches_after_cache_expiry(obo_client, mock_cca, monkeypatch):
    now = 1_700_000_000.0
    times = [now]

    def fake_time() -> float:
        return times[-1]

    monkeypatch.setattr("auth.obo_client.time.time", fake_time)
    mock_cca.acquire_token_on_behalf_of.side_effect = [
        {"access_token": "token-a", "expires_on": int(now) + 60},
        {"access_token": "token-b", "expires_on": int(now) + 3600},
    ]

    first = await obo_client.exchange("user-token", ["User.Read"])
    times.append(now + 120)
    second = await obo_client.exchange("user-token", ["User.Read"])

    assert first == "token-a"
    assert second == "token-b"
    assert mock_cca.acquire_token_on_behalf_of.call_count == 2


@pytest.mark.asyncio
async def test_cache_key_includes_scopes(obo_client, mock_cca):
    mock_cca.acquire_token_on_behalf_of.side_effect = [
        {"access_token": "token-read", "expires_in": 3600},
        {"access_token": "token-mail", "expires_in": 3600},
    ]

    read = await obo_client.exchange("user-token", ["User.Read"])
    mail = await obo_client.exchange("user-token", ["Mail.Read"])

    assert read == "token-read"
    assert mail == "token-mail"
    assert mock_cca.acquire_token_on_behalf_of.call_count == 2


@pytest.mark.asyncio
async def test_cache_key_includes_user_token_hash(obo_client, mock_cca):
    mock_cca.acquire_token_on_behalf_of.side_effect = [
        {"access_token": "token-user-a", "expires_in": 3600},
        {"access_token": "token-user-b", "expires_in": 3600},
    ]

    a = await obo_client.exchange("user-a", ["User.Read"])
    b = await obo_client.exchange("user-b", ["User.Read"])

    assert a == "token-user-a"
    assert b == "token-user-b"
    assert mock_cca.acquire_token_on_behalf_of.call_count == 2
