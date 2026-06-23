import os

import pytest
from azure.core.exceptions import ResourceNotFoundError

from config import (
    ENV_APPLICATIONINSIGHTS_CONNECTION_STRING,
    ENV_AZURE_CONTENT_SAFETY_ENDPOINT,
    ENV_AZURE_CONTENT_SAFETY_KEY,
    ENV_AZURE_KEY_VAULT_URL,
    ENV_AZURE_OPENAI_ENDPOINT,
    ENV_ENTRA_CLIENT_ID,
    ENV_ENTRA_CLIENT_SECRET,
    ENV_ENTRA_TENANT_ID,
    ENV_REDIS_CONNECTION_STRING,
    ENV_ENTRA_REDIRECT_URIS,
    KV_SECRET_APPLICATIONINSIGHTS_CONNECTION_STRING,
    KV_SECRET_AZURE_CONTENT_SAFETY_ENDPOINT,
    KV_SECRET_AZURE_CONTENT_SAFETY_KEY,
    KV_SECRET_AZURE_OPENAI_ENDPOINT,
    KV_SECRET_ENTRA_CLIENT_ID,
    KV_SECRET_ENTRA_CLIENT_SECRET,
    KV_SECRET_ENTRA_TENANT_ID,
    KV_SECRET_REDIS_CONNECTION_STRING,
    KV_SECRET_ENTRA_REDIRECT_URIS,
    ConfigurationError,
    Settings,
)

def _secret_value(name: str) -> str:
    return f"value-for-{name}"


@pytest.fixture
def mock_secret_client(mocker):
    client = mocker.MagicMock()

    def get_secret(name: str):
        secret = mocker.MagicMock()
        if name == KV_SECRET_ENTRA_CLIENT_SECRET:
            raise ResourceNotFoundError(message="not found")
        elif name == KV_SECRET_ENTRA_REDIRECT_URIS:
            secret.value = "https://kv.example.com/callback, http://localhost:8000/kv_callback"
        else:
            secret.value = _secret_value(name)
        return secret

    client.get_secret.side_effect = get_secret
    return client


@pytest.fixture(autouse=True)
def clear_settings_env(monkeypatch):
    for key in (
        ENV_AZURE_KEY_VAULT_URL,
        ENV_ENTRA_TENANT_ID,
        ENV_ENTRA_CLIENT_ID,
        ENV_ENTRA_CLIENT_SECRET,
        ENV_AZURE_OPENAI_ENDPOINT,
        ENV_AZURE_CONTENT_SAFETY_ENDPOINT,
        ENV_AZURE_CONTENT_SAFETY_KEY,
        ENV_REDIS_CONNECTION_STRING,
        ENV_APPLICATIONINSIGHTS_CONNECTION_STRING,
        ENV_ENTRA_REDIRECT_URIS,
    ):
        monkeypatch.delenv(key, raising=False)


def test_load_from_key_vault(mock_secret_client, monkeypatch): # monkeypatch is not used here, but kept for consistency if needed later
    monkeypatch.setenv(ENV_AZURE_KEY_VAULT_URL, "https://test-vault.vault.azure.net/")

    settings = Settings.load(secret_client=mock_secret_client)

    assert settings.azure_key_vault_url == "https://test-vault.vault.azure.net/"
    assert settings.entra_tenant_id == _secret_value(KV_SECRET_ENTRA_TENANT_ID)
    assert settings.entra_client_id == _secret_value(KV_SECRET_ENTRA_CLIENT_ID)
    assert settings.entra_client_secret is None
    assert settings.azure_openai_endpoint == _secret_value(
        KV_SECRET_AZURE_OPENAI_ENDPOINT
    )
    assert settings.azure_content_safety_endpoint == _secret_value(
        KV_SECRET_AZURE_CONTENT_SAFETY_ENDPOINT
    )
    assert settings.azure_content_safety_key == _secret_value(
        KV_SECRET_AZURE_CONTENT_SAFETY_KEY
    )
    assert settings.redis_connection_string == _secret_value(
        KV_SECRET_REDIS_CONNECTION_STRING
    )
    assert settings.applicationinsights_connection_string == _secret_value(
        KV_SECRET_APPLICATIONINSIGHTS_CONNECTION_STRING
    )
    assert settings.entra_redirect_uris == [
        "https://kv.example.com/callback",
        "http://localhost:8000/kv_callback",
    ]

    mock_secret_client.get_secret.assert_any_call(KV_SECRET_ENTRA_TENANT_ID)
    mock_secret_client.get_secret.assert_any_call(KV_SECRET_ENTRA_CLIENT_ID)
    mock_secret_client.get_secret.assert_any_call(KV_SECRET_ENTRA_CLIENT_SECRET)


def test_load_from_key_vault_includes_optional_client_secret(
    mock_secret_client, mocker, monkeypatch
):
    monkeypatch.setenv(ENV_AZURE_KEY_VAULT_URL, "https://test-vault.vault.azure.net/")

    def get_secret(name: str):
        secret = mocker.MagicMock()
        secret.value = _secret_value(name)
        return secret

    mock_secret_client.get_secret.side_effect = get_secret

    settings = Settings.load(secret_client=mock_secret_client)

    assert settings.entra_client_secret == _secret_value(KV_SECRET_ENTRA_CLIENT_SECRET)


def test_load_from_env_local(monkeypatch, tmp_path):
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "\n".join(
            [
                f"{ENV_ENTRA_TENANT_ID}=local-tenant",
                f"{ENV_ENTRA_CLIENT_ID}=local-client",
                f"{ENV_ENTRA_CLIENT_SECRET}=local-secret",
                f"{ENV_AZURE_OPENAI_ENDPOINT}=https://local.openai.azure.com/",
                f"{ENV_AZURE_CONTENT_SAFETY_ENDPOINT}="
                "https://local-safety.cognitiveservices.azure.com/",
                f"{ENV_AZURE_CONTENT_SAFETY_KEY}=local-safety-key",
                f"{ENV_REDIS_CONNECTION_STRING}=redis://localhost:6379",
                f"{ENV_ENTRA_REDIRECT_URIS}=http://127.0.0.1:8000/callback, https://local.example.com/callback",
                f"{ENV_APPLICATIONINSIGHTS_CONNECTION_STRING}=InstrumentationKey=local",
            ]
        )
    )

    settings = Settings.load(env_file=env_file)

    assert settings.azure_key_vault_url is None
    assert settings.entra_tenant_id == "local-tenant"
    assert settings.entra_client_id == "local-client"
    assert settings.entra_client_secret == "local-secret"
    assert settings.azure_openai_endpoint == "https://local.openai.azure.com/"
    assert settings.azure_content_safety_endpoint == (
        "https://local-safety.cognitiveservices.azure.com/"
    )
    assert settings.azure_content_safety_key == "local-safety-key"
    assert settings.redis_connection_string == "redis://localhost:6379"
    assert settings.applicationinsights_connection_string == "InstrumentationKey=local"
    assert settings.entra_redirect_uris == [
        "http://127.0.0.1:8000/callback",
        "https://local.example.com/callback",
    ]


def test_load_from_env_raises_when_required_missing(monkeypatch, tmp_path):
    env_file = tmp_path / ".env.local"
    env_file.write_text(f"{ENV_ENTRA_TENANT_ID}=only-tenant\n")

    with pytest.raises(
        ConfigurationError,
        match="Missing required environment variables",
    ):
        Settings.load(env_file=env_file)


def test_load_raises_when_no_vault_and_no_env_file(monkeypatch, tmp_path):
    missing = tmp_path / "missing.env"

    with pytest.raises(ConfigurationError, match="Missing"):
        Settings.load(env_file=missing)


def test_parse_list_handles_none_and_empty():
    """Verify that _parse_list returns an empty list for None or empty string."""
    assert Settings._parse_list(None) == []
    assert Settings._parse_list("") == []


def test_parse_list_splits_commas_and_newlines():
    """Verify that _parse_list correctly handles comma and newline separators."""
    comma_raw = "http://a.com, http://b.com"
    assert Settings._parse_list(comma_raw) == ["http://a.com", "http://b.com"]

    newline_raw = "http://a.com\nhttp://b.com"
    assert Settings._parse_list(newline_raw) == ["http://a.com", "http://b.com"]


def test_parse_list_removes_whitespace_and_empty_items():
    """Verify that _parse_list cleans up messy input strings."""
    raw = "  http://a.com , , \n http://b.com \n\n "
    assert Settings._parse_list(raw) == ["http://a.com", "http://b.com"]
