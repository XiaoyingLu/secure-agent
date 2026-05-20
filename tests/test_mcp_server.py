import pytest
from unittest.mock import patch, AsyncMock
from fastapi import HTTPException
from src.mcp_server import secure_data_lookup

@pytest.mark.asyncio
async def test_secure_data_lookup_success():
    """
    Test that secure_data_lookup returns data when a valid token is provided.
    """
    mock_claims = {
        "preferred_username": "testuser@example.com",
        "name": "Test User"
    }
    
    # Patch the validation function to return our mock claims
    with patch("src.mcp_server.validate_azure_token", new_callable=AsyncMock) as mock_validate:
        mock_validate.return_value = mock_claims
        
        # auth_token must be at least 10 chars long per mcp_server.py logic
        result = await secure_data_lookup(auth_token="valid_mock_token_string")
        
        assert "Access Granted" in result
        assert "testuser@example.com" in result
        assert "INTERNAL_PROJECT_CODE_404" in result
        mock_validate.assert_called_once()

@pytest.mark.asyncio
async def test_secure_data_lookup_invalid_token():
    """
    Test that secure_data_lookup handles expired or invalid tokens gracefully.
    """
    with patch("src.mcp_server.validate_azure_token", new_callable=AsyncMock) as mock_validate:
        mock_validate.side_effect = HTTPException(status_code=401, detail="Token has expired.")
        
        result = await secure_data_lookup(auth_token="expired_token_value")
        
        assert "Access Denied: Token has expired." in result

@pytest.mark.asyncio
async def test_secure_data_lookup_validation_error():
    """
    Test that the tool returns an error for tokens that are obviously invalid (too short).
    """
    result = await secure_data_lookup(auth_token="too_short")
    assert "Error: A valid auth_token string is required." in result

@pytest.mark.asyncio
async def test_secure_data_lookup_generic_exception():
    """
    Test that unexpected exceptions are caught and returned as error messages.
    """
    with patch("src.mcp_server.validate_azure_token", new_callable=AsyncMock) as mock_validate:
        mock_validate.side_effect = Exception("Unexpected connection error")
        
        result = await secure_data_lookup(auth_token="some_token_value")
        
        assert "Access Denied: Unexpected connection error" in result