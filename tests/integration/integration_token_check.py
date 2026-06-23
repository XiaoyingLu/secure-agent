import asyncio
import os
import msal
from config import Settings
from auth.token_validator import EntraJWTValidator

async def test_token_flow():
    """
    Interactive test to fetch a token and validate it using the project's validator.
    Requires ENTRA_TENANT_ID and ENTRA_CLIENT_ID to be set in .env.local.
    """
    print("--- 1. Loading Settings ---")
    try:
        settings = Settings.load(env_file=".env.local")
        print(f"Loaded config for Tenant: {settings.entra_tenant_id}")
    except Exception as e:
        print(f"Error loading settings: {e}")
        return

    # 2. Fetch a token interactively (Public Client approach for testing)
    print("\n--- 2. Fetching Token Interactively ---")
    # We use PublicClientApplication for easy local testing without a web server
    authority = f"https://login.microsoftonline.com/{settings.entra_tenant_id}"
    scopes = [f"api://{settings.entra_client_id}/access_as_user"]
    
    app = msal.PublicClientApplication(
        settings.entra_client_id, 
        authority=authority
    )
    
    # This will open a browser window for you to log in
    result = app.acquire_token_interactive(scopes=scopes)
    
    if "access_token" not in result:
        print(f"Failed to acquire token: {result.get('error_description', result.get('error'))}")
        return
    
    token = result["access_token"]
    print("Successfully acquired token.")

    # 3. Validate the token using EntraJWTValidator
    print("\n--- 3. Validating Token ---")
    validator = EntraJWTValidator(
        tenant_id=settings.entra_tenant_id,
        client_id=settings.entra_client_id,
    )
    
    try:
        # Warming the JWKS cache first (simulating lifespan)
        print("Fetching Microsoft public keys...")
        await validator.get_jwks()
        
        # Perform validation
        claims = await validator.validate_token(token)
        print("✅ Validation Successful!")
        print(f"Token Subject: {claims.get('sub')}")
        print(f"User Name: {claims.get('name') or claims.get('preferred_username')}")
        print(f"Roles: {claims.get('roles', 'No roles assigned')}")
        
    except Exception as e:
        print(f"❌ Validation Failed: {str(e)}")
    finally:
        await validator.aclose()

if __name__ == "__main__":
    # Ensure you have 'msal' installed: pip install msal
    # Run from the project root: python tests/integration/integration_token_check.py
    try:
        asyncio.run(test_token_flow())
    except KeyboardInterrupt:
        pass
