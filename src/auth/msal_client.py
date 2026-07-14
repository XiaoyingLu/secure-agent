"""MSAL-based Entra ID authorization code + PKCE client."""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import string
import time
import warnings
from dataclasses import dataclass
from typing import Any

import msal

logger = logging.getLogger(__name__)

_PKCE_ALPHABET = string.ascii_letters + string.digits + "-._~"
_DEFAULT_PKCE_LENGTH = 43
_TOKEN_EXPIRY_SKEW_SECONDS = 60


@dataclass(frozen=True)
class PKCEPair:
    """PKCE verifier and S256 challenge for a single authorization attempt."""

    code_verifier: str
    code_challenge: str
    code_challenge_method: str = "S256"


class MSALAuthenticationError(Exception):
    """Raised when Entra ID returns an error response during token acquisition."""


def generate_pkce_pair(length: int = _DEFAULT_PKCE_LENGTH) -> PKCEPair:
    """Generate a PKCE code_verifier and S256 code_challenge (RFC 7636).

    Args:
        length: Verifier length (43–128 characters per RFC 7636).

    Returns:
        PKCEPair with verifier, challenge, and method ``S256``.

    Raises:
        ValueError: If ``length`` is outside the allowed range.
    """
    if not 43 <= length <= 128:
        raise ValueError("PKCE code_verifier length must be between 43 and 128")
    verifier = "".join(secrets.choice(_PKCE_ALPHABET) for _ in range(length))
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return PKCEPair(code_verifier=verifier, code_challenge=challenge)


class MSALClient:
    """Entra ID OAuth2 authorization-code client with PKCE and silent refresh."""

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        scopes: list[str],
        *,
        authority: str | None = None,
        app: Any | None = None,
        token_cache: msal.SerializableTokenCache | None = None,
    ) -> None:
        """Initialize the client.

        Args:
            tenant_id: Entra ID tenant ID (or ``common`` / ``organizations``).
            client_id: Application (client) ID.
            client_secret: Client secret for confidential client auth.
            redirect_uri: Registered redirect URI for the auth code flow.
            scopes: Delegated permission scopes to request.
            authority: Optional authority URL override.
            app: Optional pre-built MSAL application (for testing).
            token_cache: Optional serializable token cache instance.
        """
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.scopes = scopes
        self._authority = authority or f"https://login.microsoftonline.com/{tenant_id}"
        self._pkce: PKCEPair | None = None
        self._auth_state: str | None = None
        self._active_auth_states: set[str] = set()
        self._pkce_by_state: dict[str, PKCEPair] = {}
        self._scopes_by_state: dict[str, list[str]] = {}
        self._token_result: dict[str, Any] | None = None
        self._token_acquired_at: float | None = None
        self._account: dict[str, Any] | None = None
        if not client_secret:
            raise ValueError("MSALClient requires ENTRA_CLIENT_SECRET for confidential-client auth.")
        if app is not None:
            self._cca = app
        else:
            self._cca = msal.ConfidentialClientApplication(
                client_id,
                authority=self._authority,
                client_credential=client_secret,
                token_cache=token_cache or msal.SerializableTokenCache(),
            )

    def generate_pkce(self, length: int = _DEFAULT_PKCE_LENGTH) -> PKCEPair:
        """Generate and store PKCE credentials for the current login session.

        Args:
            length: Verifier length (43–128).

        Returns:
            The generated PKCE pair.
        """
        self._pkce = generate_pkce_pair(length)
        return self._pkce

    @property
    def pkce(self) -> PKCEPair | None:
        """Active PKCE pair, if :meth:`generate_pkce` was called."""
        return self._pkce

    @property
    def auth_state(self) -> str | None:
        """OAuth ``state`` value from the last authorization URL build."""
        return self._auth_state

    def is_known_auth_state(self, state: str | None) -> bool:
        """Return True when ``state`` matches an active auth attempt."""
        return bool(state) and state in self._active_auth_states

    def get_scopes_for_state(self, state: str) -> list[str] | None:
        """Return the scopes that were requested for the given auth state, if any."""
        return self._scopes_by_state.get(state)

    def build_authorization_url(
        self,
        *,
        state: str | None = None,
        login_hint: str | None = None,
        scopes: list[str] | None = None,
    ) -> str:
        """Build the Entra ID authorization URL (optionally with PKCE parameters).

        Args:
            state: Optional CSRF state; generated if omitted.
            login_hint: Optional UPN or email hint for sign-in.

        Returns:
            Authorization URL to redirect the resource owner to.
        """
        self._auth_state = state or secrets.token_urlsafe(16)
        self._active_auth_states.add(self._auth_state)
        effective_scopes = scopes if scopes is not None else self.scopes
        self._scopes_by_state[self._auth_state] = effective_scopes
        decorated_scopes = self._cca._decorate_scope(effective_scopes)
        pkce_for_request: PKCEPair | None = None
        if self._pkce:
            # Bind PKCE to the generated state so callback can use the matching verifier.
            pkce_for_request = self._pkce
            self._pkce_by_state[self._auth_state] = pkce_for_request
            self._pkce = None

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            
            # Build base auth request URI
            if pkce_for_request:
                # Include PKCE parameters if available
                auth_url = self._cca.client.build_auth_request_uri(
                    "code",
                    redirect_uri=self.redirect_uri,
                    scope=decorated_scopes,
                    state=self._auth_state,
                    login_hint=login_hint,
                    code_challenge=pkce_for_request.code_challenge,
                    code_challenge_method=pkce_for_request.code_challenge_method,
                )
            else:
                # Build without PKCE (for confidential clients)
                auth_url = self._cca.client.build_auth_request_uri(
                    "code",
                    redirect_uri=self.redirect_uri,
                    scope=decorated_scopes,
                    state=self._auth_state,
                    login_hint=login_hint,
                )

        logger.debug(
            "Built authorization URL for client_id=%s (PKCE=%s)",
            self.client_id,
            pkce_for_request is not None,
        )
        return auth_url

    def exchange_authorization_code(self, code: str, *, state: str | None = None) -> dict[str, Any]:
        """Exchange an authorization code for tokens.

        When PKCE is enabled, ``state`` is used to locate the exact
        verifier/challenge pair generated during ``build_authorization_url``.

        Args:
            code: Authorization code from the redirect callback.
            state: Optional state value from callback query parameters.

        Returns:
            MSAL token response containing ``access_token`` and typically
            ``refresh_token``.

        Raises:
            MSALAuthenticationError: If Entra returns an error payload.
        """
        result = None
        pkce_for_exchange: PKCEPair | None = None

        if state is not None:
            if state not in self._active_auth_states:
                raise MSALAuthenticationError(
                    "invalid_state: Unknown or expired OAuth state. Start login again."
                )
            pkce_for_exchange = self._pkce_by_state.get(state)
            self._active_auth_states.discard(state)
            self._pkce_by_state.pop(state, None)
        elif self._pkce is not None:
            pkce_for_exchange = self._pkce

        # Use the scopes that were originally requested for this auth state.
        exchange_scopes = self._scopes_by_state.pop(state, None) if state else None
        exchange_scopes = exchange_scopes or self.scopes

        if pkce_for_exchange is not None:
            # PKCE was used in auth request; try passing code_verifier
            try:
                logger.debug("Exchanging code with PKCE code_verifier")
                result = self._cca.acquire_token_by_authorization_code(
                    code,
                    scopes=exchange_scopes,
                    redirect_uri=self.redirect_uri,
                    code_verifier=pkce_for_exchange.code_verifier,
                )
            except (TypeError, AttributeError) as e:
                logger.debug("PKCE code_verifier not supported by MSAL, retrying without it: %s", str(e))
                result = None  # Fall through to non-PKCE path
        
        # If PKCE wasn't used or failed, try without code_verifier
        if result is None:
            logger.debug("Exchanging code without PKCE (confidential client)")
            result = self._cca.acquire_token_by_authorization_code(
                code,
                scopes=exchange_scopes,
                redirect_uri=self.redirect_uri,
            )
        
        if not result or "error" in result:
            error_msg = result.get("error_description") if result else "Unknown error"
            error_code = result.get("error") if result else "unknown_error"
            raise MSALAuthenticationError(
                f"{error_code}: {error_msg}" if error_msg else f"Token exchange failed: {error_code}"
            )

        self._apply_token_result(result)
        accounts = self._cca.get_accounts()
        self._account = accounts[0] if accounts else None
        return result

    def get_valid_access_token(self, *, force_refresh: bool = False) -> dict[str, Any]:
        """Return a valid access token, silently refreshing when expired.

        Args:
            force_refresh: Skip cache lookup and force a refresh token exchange.

        Returns:
            Token response dict including ``access_token``.

        Raises:
            RuntimeError: If not authenticated or silent refresh fails.
        """
        if self._account is None:
            raise RuntimeError(
                "No authenticated session. Call exchange_authorization_code() first."
            )

        if (
            not force_refresh
            and self._token_result is not None
            and not self._is_access_token_expired()
        ):
            return self._token_result

        refreshed = self._cca.acquire_token_silent(
            self.scopes,
            account=self._account,
            force_refresh=force_refresh,
        )
        if not refreshed or "error" in refreshed:
            raise RuntimeError("Silent token refresh failed; re-authentication required.")

        self._apply_token_result(refreshed)
        return refreshed

    def _apply_token_result(self, result: dict[str, Any]) -> None:
        self._token_result = result
        self._token_acquired_at = time.time()

    def _is_access_token_expired(self) -> bool:
        if self._token_result is None:
            return True

        expires_on = self._token_result.get("expires_on")
        if expires_on is not None:
            return time.time() >= int(expires_on) - _TOKEN_EXPIRY_SKEW_SECONDS

        expires_in = self._token_result.get("expires_in")
        if expires_in is not None and self._token_acquired_at is not None:
            return (
                time.time()
                >= self._token_acquired_at + int(expires_in) - _TOKEN_EXPIRY_SKEW_SECONDS
            )

        return True
