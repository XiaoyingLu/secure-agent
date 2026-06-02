from auth.entra_config import EntraConfig
from auth.msal_client import MSALAuthenticationError, MSALClient, PKCEPair, generate_pkce_pair
from auth.obo_client import OBOClient, OBOError
from auth.rbac import (
    AGENT_ADMIN_ROLE_ID,
    AGENT_ADMIN_ROLE_NAME,
    AGENT_USER_ROLE_ID,
    AGENT_USER_ROLE_NAME,
    require_role,
)
from auth.token_validator import EntraJWTMiddleware, EntraJWTValidator, validate_azure_token

__all__ = [
    "AGENT_ADMIN_ROLE_ID",
    "AGENT_ADMIN_ROLE_NAME",
    "AGENT_USER_ROLE_ID",
    "AGENT_USER_ROLE_NAME",
    "EntraConfig",
    "EntraJWTMiddleware",
    "EntraJWTValidator",
    "MSALAuthenticationError",
    "MSALClient",
    "OBOClient",
    "OBOError",
    "PKCEPair",
    "generate_pkce_pair",
    "require_role",
    "validate_azure_token",
]
