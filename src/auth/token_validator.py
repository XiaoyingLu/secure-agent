"""Entra ID JWT validation for FastAPI (dependency and middleware)."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx
import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

load_dotenv()

logger = logging.getLogger(__name__)

TENANT_ID = os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")

# Legacy v1.0 issuer used by some tokens in this project
AZURE_ISSUER = f"https://sts.windows.net/{TENANT_ID}/"
JWKS_URL = f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys"
ALLOWED_AUDIENCES = [CLIENT_ID, f"api://{CLIENT_ID}"]

JWKS_TTL_SECONDS = 3600
INVALID_TOKEN_BODY = {"error": "invalid_token"}
DEFAULT_EXCLUDE_PATHS = frozenset({"/health", "/docs", "/openapi.json", "/redoc"})


def _jwks_url_for_tenant(tenant_id: str) -> str:
    return f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"


def _default_issuer_v2(tenant_id: str) -> str:
    return f"https://login.microsoftonline.com/{tenant_id}/v2.0"


def _default_audiences(client_id: str) -> list[str]:
    return [client_id, f"api://{client_id}"]


class EntraJWTValidator:
    """Validates Entra ID JWTs using JWKS-fetched signing keys."""

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        *,
        issuer: str | None = None,
        audiences: list[str] | None = None,
        jwks_url: str | None = None,
        jwks_ttl_seconds: int = JWKS_TTL_SECONDS,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.issuer = issuer or _default_issuer_v2(tenant_id)
        self.audiences = audiences or _default_audiences(client_id)
        self.jwks_url = jwks_url or _jwks_url_for_tenant(tenant_id)
        self.jwks_ttl_seconds = jwks_ttl_seconds
        self._http_client = http_client
        self._owns_http_client = http_client is None
        self._jwks_fetched_at: float | None = None
        self._jwks_keys: list[dict[str, Any]] | None = None

    async def aclose(self) -> None:
        if self._owns_http_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    def _http(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient()
        return self._http_client

    def _jwks_cache_valid(self) -> bool:
        if self._jwks_keys is None or self._jwks_fetched_at is None:
            return False
        return (time.time() - self._jwks_fetched_at) < self.jwks_ttl_seconds

    async def get_jwks(self, *, force_refresh: bool = False) -> list[dict[str, Any]]:
        """Fetch JWKS keys, using an in-memory cache with TTL.

        Args:
            force_refresh: Bypass cache and fetch fresh keys from Entra.

        Returns:
            List of JWK dicts from Microsoft's discovery document.
        """
        if not force_refresh and self._jwks_cache_valid():
            return self._jwks_keys  # type: ignore[return-value]

        response = await self._http().get(self.jwks_url, timeout=5.0)
        response.raise_for_status()
        keys = response.json().get("keys", [])
        self._jwks_keys = keys
        self._jwks_fetched_at = time.time()
        return keys

    async def validate_token(self, token: str) -> dict[str, Any]:
        """Verify signature and validate ``iss``, ``aud``, ``exp``, and ``nbf``.

        Args:
            token: Raw JWT access or ID token string.

        Returns:
            Decoded JWT claims.

        Raises:
            jwt.InvalidTokenError: On any validation failure.
            ValueError: If the token header is missing ``kid``.
        """
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if not kid:
            raise ValueError("Token header missing 'kid'.")

        matching_key = await self._resolve_signing_key(kid)
        rsa_key = jwt.PyJWK(matching_key).key

        return jwt.decode(
            token,
            key=rsa_key,
            algorithms=["RS256"],
            audience=self.audiences,
            issuer=self.issuer,
            options={"verify_nbf": True},
        )

    async def _resolve_signing_key(self, kid: str) -> dict[str, Any]:
        keys = await self.get_jwks()
        matching_key = next((key for key in keys if key.get("kid") == kid), None)
        if matching_key is not None:
            return matching_key

        keys = await self.get_jwks(force_refresh=True)
        matching_key = next((key for key in keys if key.get("kid") == kid), None)
        if matching_key is None:
            raise ValueError("Signing key not found in JWKS.")
        return matching_key


SERVICE_UNAVAILABLE_BODY = {"error": "service_unavailable"}


class EntraJWTMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that validates Bearer JWTs and sets ``request.state.user``."""

    def __init__(
        self,
        app: ASGIApp,
        tenant_id: str | None = None,
        client_id: str | None = None,
        *,
        validator: EntraJWTValidator | None = None,
        issuer: str | None = None,
        audiences: list[str] | None = None,
        exclude_paths: frozenset[str] | set[str] | None = None,
    ) -> None:
        super().__init__(app)
        if validator is not None:
            self._fallback_validator = validator
        elif tenant_id and client_id:
            self._fallback_validator = EntraJWTValidator(
                tenant_id,
                client_id,
                issuer=issuer,
                audiences=audiences,
            )
        else:
            self._fallback_validator = None
        self.exclude_paths = exclude_paths or DEFAULT_EXCLUDE_PATHS

    def _resolve_validator(self, request: Request) -> EntraJWTValidator | None:
        app_validator = getattr(request.app.state, "jwt_validator", None)
        if app_validator is not None:
            return app_validator
        return self._fallback_validator

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.url.path in self.exclude_paths:
            return await call_next(request)

        validator = self._resolve_validator(request)
        if validator is None:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content=SERVICE_UNAVAILABLE_BODY,
            )

        token = _extract_bearer_token(request.headers.get("Authorization"))
        if token is None:
            return JSONResponse(status_code=401, content=INVALID_TOKEN_BODY)

        try:
            claims = await validator.validate_token(token)
        except Exception:
            logger.debug("JWT validation failed for path %s", request.url.path)
            return JSONResponse(status_code=401, content=INVALID_TOKEN_BODY)

        request.state.user = {**claims, "access_token": token}
        return await call_next(request)


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, credentials = authorization.partition(" ")
    if scheme.lower() != "bearer" or not credentials:
        return None
    return credentials.strip()


# --- Legacy FastAPI dependency (v1 issuer) ---
_jwks_cache: list[dict[str, Any]] | None = None
security_scheme = HTTPBearer()


async def get_ms_public_keys() -> list[dict[str, Any]]:
    """Fetches and caches Microsoft's public keys (legacy global cache)."""
    global _jwks_cache
    if _jwks_cache is None:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(JWKS_URL, timeout=5)
                response.raise_for_status()
                _jwks_cache = response.json().get("keys", [])
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not fetch Microsoft public keys for token validation.",
            )
    return _jwks_cache


def _env_validator() -> EntraJWTValidator:
    return EntraJWTValidator(
        tenant_id=TENANT_ID or "",
        client_id=CLIENT_ID or "",
        issuer=AZURE_ISSUER,
        audiences=[a for a in ALLOWED_AUDIENCES if a],
        jwks_url=JWKS_URL,
    )


async def validate_azure_token(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
) -> dict[str, Any]:
    """FastAPI dependency that validates an Azure AD Bearer token."""
    try:
        return await _env_validator().validate_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired."
        )
    except jwt.InvalidIssuerError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token issuer."
        )
    except jwt.InvalidAudienceError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token audience."
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        )


if __name__ == "__main__":
    print("Testing Azure token validation...")
