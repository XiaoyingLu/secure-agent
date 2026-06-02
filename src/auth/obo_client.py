"""On-Behalf-Of (OBO) token exchange for downstream Microsoft Graph access.

We use the OAuth 2.0 OBO flow rather than app-only (client credentials) tokens so
every Graph call runs under the signed-in user's delegated permissions. App-only
tokens bypass user consent boundaries and would let the agent access data the
caller is not entitled to see, which violates this project's zero-trust contract.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any

import msal

logger = logging.getLogger(__name__)

_TOKEN_EXPIRY_SKEW_SECONDS = 60


class OBOError(Exception):
    """Raised when Entra ID OBO token exchange fails."""


@dataclass(frozen=True)
class _CachedOBOToken:
    access_token: str
    expires_at: float


def _hash_user_token(user_token: str) -> str:
    return hashlib.sha256(user_token.encode("utf-8")).hexdigest()


def _expires_at_from_result(result: dict[str, Any], *, acquired_at: float) -> float:
    expires_on = result.get("expires_on")
    if expires_on is not None:
        return float(expires_on)
    expires_in = result.get("expires_in")
    if expires_in is not None:
        return acquired_at + int(expires_in)
    return acquired_at


class OBOClient:
    """Exchange a user assertion for a downstream API access token via MSAL OBO."""

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        *,
        authority: str | None = None,
        app: msal.ConfidentialClientApplication | None = None,
    ) -> None:
        """Initialise the OBO client.

        Args:
            tenant_id: Entra ID tenant ID.
            client_id: Middle-tier application (client) ID.
            client_secret: Client secret for the confidential client.
            authority: Optional authority URL override.
            app: Optional pre-built MSAL application (for unit tests).
        """
        self.tenant_id = tenant_id
        self.client_id = client_id
        self._authority = authority or f"https://login.microsoftonline.com/{tenant_id}"
        self._cca = app or msal.ConfidentialClientApplication(
            client_id,
            authority=self._authority,
            client_credential=client_secret,
        )
        self._cache: dict[tuple[str, frozenset[str]], _CachedOBOToken] = {}

    async def exchange(self, user_token: str, scopes: list[str]) -> str:
        """Exchange the incoming user token for a downstream access token.

        Results are cached in memory keyed by ``(token_hash, frozenset(scopes))``
        until the token expires.

        Args:
            user_token: Bearer token presented to this API (user assertion).
            scopes: Scopes required by the downstream resource (e.g. Graph).

        Returns:
            Access token string for the downstream API.

        Raises:
            OBOError: If MSAL returns an error response.
        """
        scope_key = frozenset(scopes)
        cache_key = (_hash_user_token(user_token), scope_key)

        cached = self._cache.get(cache_key)
        if cached is not None and not self._is_expired(cached.expires_at):
            logger.debug("OBO cache hit for scopes=%s", sorted(scope_key))
            return cached.access_token

        result = await asyncio.to_thread(
            self._cca.acquire_token_on_behalf_of,
            user_token,
            scopes,
        )

        if "error" in result:
            description = result.get("error_description") or result["error"]
            raise OBOError(description)

        if "access_token" not in result:
            raise OBOError("OBO response missing access_token")

        acquired_at = time.time()
        expires_at = _expires_at_from_result(result, acquired_at=acquired_at)
        access_token = result["access_token"]
        self._cache[cache_key] = _CachedOBOToken(
            access_token=access_token,
            expires_at=expires_at,
        )
        logger.debug(
            "OBO token acquired for scopes=%s, expires_at=%s",
            sorted(scope_key),
            expires_at,
        )
        return access_token

    def _is_expired(self, expires_at: float) -> bool:
        return time.time() >= expires_at - _TOKEN_EXPIRY_SKEW_SECONDS

    def clear_cache(self) -> None:
        """Clear the in-memory OBO token cache (useful in tests)."""
        self._cache.clear()
