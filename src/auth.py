import jwt
import os
from load_dotenv import load_dotenv
import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# --- CONFIGURATION ---
load_dotenv()

# Replace with your actual Azure Tenant ID and App Registration Client ID (Audience)
TENANT_ID = os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")

# Microsoft OIDC Configuration endpoints for v2.0 tokens
# AZURE_ISSUER = f"https://login.microsoftonline.com/{TENANT_ID}/v2.0"
AZURE_ISSUER = f"https://sts.windows.net/{TENANT_ID}/"  # the token is a legacy v1.0 format
JWKS_URL = f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys"

# Azure AD tokens often use the Application ID URI as the audience.
ALLOWED_AUDIENCES = [CLIENT_ID, f"api://{CLIENT_ID}"]

# Cache the Microsoft public keys globally to avoid making an HTTP request on every single API call
_jwks_cache = None

async def get_ms_public_keys():
    """Fetches and caches Microsoft's public keys."""
    global _jwks_cache
    if _jwks_cache is None:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(JWKS_URL, timeout=5)
                response.raise_for_status()
                _jwks_cache = response.json().get("keys", [])
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not fetch Microsoft public keys for token validation."
            )
    return _jwks_cache

# Initialize the standard FastAPI Bearer token extractor
security_scheme = HTTPBearer()

async def validate_azure_token(credentials: HTTPAuthorizationCredentials = Depends(security_scheme)) -> dict:
    """
    FastAPI dependency that extracts, decodes, and validates an Azure AD token.
    Returns the decoded claims dictionary if valid.
    """
    token = credentials.credentials
    
    try:
        # 1. Unverified decode to get the token header (specifically 'kid' - Key ID)
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if not kid:
            raise HTTPException(status_code=401, detail="Token header missing 'kid'.")
        
        # 2. Find the matching public key from Microsoft's JWKS
        public_keys = await get_ms_public_keys()
        matching_key = next((key for key in public_keys if key["kid"] == kid), None)
        
        if not matching_key:
            # If key isn't found, clear cache and retry once (handles Microsoft rolling keys)
            global _jwks_cache
            _jwks_cache = None
            public_keys = await get_ms_public_keys()
            matching_key = next((key for key in public_keys if key["kid"] == kid), None)
            
            if not matching_key:
                raise HTTPException(status_code=401, detail="Signing key not found in Microsoft's JWKS.")
        
        # 3. Construct the public key object using PyJWT
        # PyJWT converts the JWK dictionary automatically into an RSA key instance
        rsa_key = jwt.PyJWK(matching_key).key
        
        # 4. Decode and cryptographically validate the token
        payload = jwt.decode(
            token,
            key=rsa_key,
            algorithms=["RS256"],
        audience=ALLOWED_AUDIENCES,
            issuer=AZURE_ISSUER
        )
        
        return payload

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired.")
    except jwt.InvalidIssuerError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token issuer.")
    except jwt.InvalidAudienceError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token audience.")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {str(e)}")
    

if __name__ == "__main__":
    # Simple test to validate the token validation logic
    print("Testing Azure token validation...")