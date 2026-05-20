import os
from pathlib import Path
import requests
import pytest
from fastapi.testclient import TestClient

# Import your actual FastAPI application instance
# from src import main 

TOKEN_FILE_PATH = Path(__file__).parent / "azure_token.txt"

@pytest.fixture(scope="module")
def bearer_token():
    """
    Fixture that safely reads, cleans, and supplies the 
    stored token string from the local text file.
    """
    if not TOKEN_FILE_PATH.exists():
        pytest.fail(
            f"❌ Test aborted: Missing token file at '{TOKEN_FILE_PATH}'. "
            f"Please run your login script and dump the raw token string into this file first."
        )
        
    with open(TOKEN_FILE_PATH, "r", encoding="utf-8") as f:
        # .strip() is vital to drop trailing '\n' line breaks appended by text editors
        token_string = f.read().strip()
        
    if not token_string:
        pytest.fail(f"❌ Test aborted: '{TOKEN_FILE_PATH}' exists but is empty.")
        
    return token_string


# @pytest.fixture(scope="module")
# def client():
#     """Fixture initializing the FastAPI internal test environment."""
#     return TestClient(main.app)

API_URL = "http://127.0.0.1:8000/secure"

# --- THE TEST CASES ---

def test_secure_endpoint_success(bearer_token):
    """
    GIVEN a valid Azure active directory token inside our text file
    WHEN making an authorized request to /secure
    THEN the server should validate it via Microsoft's JWKS and respond 200 OK
    """
    headers = {"Authorization": f"Bearer {bearer_token}"}
    
    # response = client.get("/secure", headers=headers)
    response = requests.get(API_URL, headers=headers)
    print(f"Status Code: {response.status_code}")
    print(response.json())
    
    # Assertions
    assert response.status_code == 200
    data = response.json()
    assert "azure_claims" in data
    assert "message" in data


def test_secure_endpoint_fails_if_no_header():
    """
    GIVEN no authorization header
    WHEN making a request to /secure
    THEN FastAPI should block the request with a 403 or 401 response early
    """
    # response = client.get("/secure")
    response = requests.get(API_URL)
    assert response.status_code in [401, 403]