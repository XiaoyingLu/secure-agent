from mcp.server.fastmcp import FastMCP
from src.auth import validate_azure_token
from fastapi.security import HTTPAuthorizationCredentials
from fastapi import HTTPException

# Initialize the FastMCP server. 
# This provides a high-level API for creating MCP servers.
mcp = FastMCP("Secure Agent Server")

@mcp.tool()
async def secure_data_lookup(auth_token: str) -> str:
    """
    Exposes a secure data lookup tool.
    
    Args:
        auth_token: The raw Azure AD access token string required for authorization.
    """
    try:
        if not auth_token or len(auth_token) < 10:
            return "Error: A valid auth_token string is required."

        # We wrap the incoming token string into the credentials object 
        # that our existing validation logic in auth.py expects.
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=auth_token)
        
        # Use our existing validation logic to verify the token with Microsoft
        # This checks the signature, issuer, audience, and expiration.
        claims = await validate_azure_token(credentials)
        
        # If validation passes, we can access the claims and return the data
        user = claims.get("preferred_username") or claims.get("name", "Authorized User")
        return f"Access Granted. Hello {user}! The requested secure data is: 'INTERNAL_PROJECT_CODE_404'."
        
    except HTTPException as e:
        # Provide the specific error detail (e.g., "Token has expired") to the LLM
        return f"Access Denied: {e.detail}"
    except Exception as e:
        # Returning the error as a string allows the host/LLM to handle the failure gracefully
        return f"Access Denied: {str(e)}"

if __name__ == "__main__":
    # This starts the server using the stdio transport by default.
    mcp.run()