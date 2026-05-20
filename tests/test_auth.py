import requests
import os
from load_dotenv import load_dotenv
from msal import PublicClientApplication

# --- CONFIGURATION (Match your FastAPI config) ---
load_dotenv()
TENANT_ID = os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
API_URL = "http://127.0.0.1:8000/secure"

# The scope we exposed in the Azure Portal
SCOPES = [f"api://{CLIENT_ID}/access_as_user"]

# Initialize MSAL Public Client
app = PublicClientApplication(
    CLIENT_ID, 
    authority=f"https://login.microsoftonline.com/{TENANT_ID}"
)

print("Opening browser for Microsoft Sign-In...")
# 1. This triggers an interactive login window in your default browser
auth_result = app.acquire_token_interactive(scopes=SCOPES)

if "access_token" in auth_result:
    token = auth_result["access_token"]
    print("\n✅ Token successfully retrieved!")

    # 🔴 ADD THIS LINE TO PRINT THE RAW STRING
    print(f"\n--- RAW ACCESS TOKEN ---\n{token}\n-----------------------")

    # import jwt  # Temporarily import pyjwt in your test script
    # unverified_payload = jwt.decode(token, options={"verify_signature": False})
    # print(f"👉 REAL ISSUER IN TOKEN: {unverified_payload.get('iss')}")
    
    # 2. Send the token to your FastAPI /secure endpoint
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(API_URL, headers=headers)
    
    print("\n--- FastAPI Response ---")
    print(f"Status Code: {response.status_code}")
    print(response.json())
else:
    print("\n❌ Authentication failed!")
    print(auth_result.get("error_description"))