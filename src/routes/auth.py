"""OAuth2 authentication routes (MSAL auth-code flow with PKCE)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request, HTTPException, status
from starlette.responses import RedirectResponse, JSONResponse, HTMLResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])
ACCESS_TOKEN_COOKIE_NAME = "secure_agent_access_token"

# Scopes required for the three MCP tools.  These must be delegated permissions
# on the app registration; the user is asked to consent to them once via
# GET /auth/graph-consent before the OBO exchange can succeed.
# Note: offline_access is excluded here because it's a reserved scope that
# must be requested separately during the main login flow, not with resource-specific scopes.
GRAPH_CONSENT_SCOPES = [
    "https://graph.microsoft.com/Calendars.Read",
    "https://graph.microsoft.com/Mail.Read",
    "https://graph.microsoft.com/Sites.Read.All",
]
_GRAPH_CONSENT_STATE_PREFIX = "graphconsent_"


@router.get("/graph-consent", response_model=None)
async def get_graph_consent(request: Request) -> RedirectResponse | HTMLResponse:
    """Initiate a one-time Graph permission consent flow.

    Redirects the user to Entra to consent to the delegated Graph scopes
    required for the MCP tools (Calendars.Read, Mail.Read, Sites.Read.All).
    After the user approves, future OBO token exchanges will succeed.

    Visit this endpoint once if the chat agent returns a 401 error about
    Graph permissions.  Admin consent in the Azure portal is an alternative.
    """
    msal_client = getattr(request.app.state, "msal_client", None)
    if msal_client is None:
        return HTMLResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content="<html><body><h1>MSAL not configured</h1>"
            "<p>Set ENTRA_CLIENT_SECRET to enable authentication.</p></body></html>",
        )

    import secrets as _secrets
    consent_state = f"{_GRAPH_CONSENT_STATE_PREFIX}{_secrets.token_urlsafe(16)}"
    try:
        auth_url = msal_client.build_authorization_url(
            state=consent_state,
            scopes=GRAPH_CONSENT_SCOPES,
        )
    except Exception as exc:
        logger.exception("graph_consent.build_url_failed: %s", exc)
        return HTMLResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=f"<html><body><h1>Error</h1><p>{exc}</p></body></html>",
        )

    logger.info("graph_consent.redirect state=%s", consent_state)
    return RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)


@router.get("/login/status")
async def get_login_status(request: Request) -> JSONResponse:
    """Diagnostic endpoint to check if OAuth2 is configured.
    
    Returns:
        JSON with configuration status and any error messages.
    """
    msal_client = getattr(request.app.state, "msal_client", None)
    settings = getattr(request.app.state, "settings", None)
    
    if msal_client is None:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "configured": False,
                "reason": "MSAL client not initialized",
                "required_env_var": "ENTRA_CLIENT_SECRET",
                "details": "Set ENTRA_CLIENT_SECRET in .env.local to enable confidential-client OAuth2 login flow",
            },
        )
    
    # All good
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "configured": True,
            "client_id": msal_client.client_id,
            "tenant_id": msal_client.tenant_id,
            "redirect_uri": msal_client.redirect_uri,
            "scopes": msal_client.scopes,
            "client_mode": "confidential",
            "message": "OAuth2 is configured. Navigate to /login to start authentication.",
        },
    )


@router.get("/scopes-diagnostic", response_model=None)
async def get_scopes_diagnostic(request: Request) -> JSONResponse | HTMLResponse:
    """Diagnostic endpoint to check what scopes the current user has.
    
    This endpoint checks the user's current access token to show which scopes
    are present, which are missing, and what the next steps should be.
    """
    # Try to get token from cookie first (set by /callback), then Authorization header
    token = request.cookies.get(ACCESS_TOKEN_COOKIE_NAME)
    
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.replace("Bearer ", "")
    
    if not token:
        return HTMLResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content="""
            <html>
                <body style="font-family: Arial; margin: 40px;">
                    <h1>Not Authenticated</h1>
                    <p>Please sign in first:</p>
                    <a href="/auth/login">Sign in with Microsoft</a>
                    <p style="margin-top: 40px; font-size: 12px; color: #666;">
                        After signing in, visit this page again to check your scopes.
                    </p>
                </body>
            </html>
            """,
        )
    
    # Decode the token to check scopes
    try:
        import base64
        import json as _json
        parts = token.split(".")
        if len(parts) < 2:
            raise ValueError("Invalid token format")
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = _json.loads(base64.urlsafe_b64decode(padded))
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": f"Could not decode token: {e}"},
        )
    
    scp = payload.get("scp", "").split()
    required_scopes = ["Calendars.Read", "Mail.Read", "Sites.Read.All"]
    
    missing_scopes = [s for s in required_scopes if s not in scp]
    has_all_scopes = len(missing_scopes) == 0
    
    return JSONResponse(
        status_code=status.HTTP_200_OK if has_all_scopes else status.HTTP_403_FORBIDDEN,
        content={
            "user": {
                "oid": payload.get("oid"),
                "upn": payload.get("upn"),
                "name": payload.get("name"),
            },
            "current_scopes": scp,
            "required_scopes": required_scopes,
            "missing_scopes": missing_scopes,
            "has_all_scopes": has_all_scopes,
            "next_steps": (
                "✅ You have all required Graph scopes! Calendar queries should work."
                if has_all_scopes
                else f"❌ Missing scopes: {', '.join(missing_scopes)}. "
                "Visit /auth/graph-consent to request them."
            ),
        },
    )



@router.get("/login", response_model=None)
async def get_login(request: Request) -> RedirectResponse | HTMLResponse:
    """Initiate OAuth2 authorization code flow with PKCE.

    Redirects to Entra ID login page. After user authenticates, they are
    redirected back to /callback with an authorization code.

    """
    msal_client = getattr(request.app.state, "msal_client", None)
    if msal_client is None:
        return HTMLResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content="""
            <html>
                <body style="font-family: Arial; margin: 40px;">
                    <h1>OAuth2 Not Configured</h1>
                    <p><strong>Error:</strong> MSAL client not initialized.</p>
                    <p><strong>Fix:</strong> Set <code>ENTRA_CLIENT_SECRET</code> in <code>.env.local</code></p>
                    <p>Example:</p>
                    <pre>
ENTRA_TENANT_ID=your-tenant-id
ENTRA_CLIENT_ID=your-client-id
ENTRA_CLIENT_SECRET=your-client-secret
ENTRA_REDIRECT_URIS=http://127.0.0.1:8000/auth/callback
                    </pre>
                    <p><a href="/login/status">Check OAuth2 Status</a></p>
                </body>
            </html>
            """,
        )

    try:
        # Build authorization URL (includes PKCE in public-client mode)
        logger.debug(
            "Building auth URL with scopes=%s, redirect_uri=%s",
            msal_client.scopes,
            msal_client.redirect_uri,
        )
        auth_url = msal_client.build_authorization_url()

        logger.info(
            "login.redirect",
            extra={
                "custom_dimensions": {
                    "client_id": msal_client.client_id,
                    "auth_url_host": auth_url.split("?")[0] if "?" in auth_url else auth_url,
                }
            },
        )

        return RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)
    except Exception as exc:
        logger.exception("login.failed: %s", exc)
        return HTMLResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=f"""
            <html>
                <body style="font-family: Arial; margin: 40px;">
                    <h1>Login Failed</h1>
                    <p><strong>Error:</strong> {str(exc)}</p>
                    <p>Check the server logs for more details.</p>
                    <p><a href="/login/status">Check OAuth2 Status</a></p>
                </body>
            </html>
            """,
        )


@router.get("/callback")
async def get_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None) -> JSONResponse:
    """Handle OAuth2 authorization code callback from Entra ID.

    Exchanges the authorization code + PKCE verifier for access & refresh tokens.

    Query Parameters:
        code: Authorization code from Entra ID.
        state: CSRF state from authorization URL (validated).
        error: Error code if the user denied the request.

    Returns:
        JSON with ``access_token`` and ``expires_in`` on success.
    """
    msal_client = getattr(request.app.state, "msal_client", None)
    if msal_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MSAL client not configured.",
        )

    # Check for authorization errors (e.g., user denied consent)
    if error:
        logger.warning(
            "callback.auth_error",
            extra={
                "custom_dimensions": {
                    "error": error,
                }
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Authorization denied: {error}",
        )

    # Validate state parameter
    if not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing OAuth state in callback.",
        )

    if not msal_client.is_known_auth_state(state):
        logger.error(
            "callback.state_mismatch",
            extra={
                "custom_dimensions": {
                    "received": state,
                }
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSRF state mismatch. Authorization rejected.",
        )

    # Ensure we have an authorization code
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing authorization code in callback.",
        )

    try:
        # Exchange authorization code for tokens
        logger.debug(
            "callback.exchange_start",
            extra={
                "custom_dimensions": {
                    "code_length": len(code) if code else 0,
                    "redirect_uri": msal_client.redirect_uri,
                    "client_id": msal_client.client_id,
                }
            },
        )
        token_result = msal_client.exchange_authorization_code(code, state=state)

        is_graph_consent = isinstance(state, str) and state.startswith(_GRAPH_CONSENT_STATE_PREFIX)

        if is_graph_consent:
            logger.info("graph_consent.complete: user consented to Graph scopes")
            # Decode token to check what scopes we got back
            try:
                import base64
                import json as _json
                access_token = token_result.get("access_token", "")
                if access_token:
                    parts = access_token.split(".")
                    if len(parts) >= 2:
                        padded = parts[1] + "=" * (-len(parts[1]) % 4)
                        payload = _json.loads(base64.urlsafe_b64decode(padded))
                        returned_scopes = payload.get("scp", "").split()
                        logger.info(
                            "graph_consent.token_scopes",
                            extra={
                                "custom_dimensions": {
                                    "returned_scopes": returned_scopes,
                                    "token_has_calendars": "Calendars.Read" in returned_scopes,
                                    "token_has_mail": "Mail.Read" in returned_scopes,
                                    "token_has_sharepoint": "Sites.Read.All" in returned_scopes,
                                }
                            },
                        )
            except Exception as e:
                logger.warning("Could not decode graph consent token: %s", e)
            
            # Set cookie with new token that includes Graph scopes
            response = HTMLResponse(
                status_code=status.HTTP_200_OK,
                content="""
                <html>
                <head><meta charset="utf-8"><title>Graph Access Granted</title></head>
                <body style="font-family:Arial;margin:40px;max-width:600px">
                <h1>&#10003; Graph permissions granted</h1>
                <p>You have successfully consented to the required Microsoft Graph permissions
                (Calendar, Mail, SharePoint). The AI agent can now read your calendar and email.</p>
                <p><a href="/auth/scopes-diagnostic">Check your current scopes</a></p>
                <p><a href="/">Return to the app</a></p>
                <script>setTimeout(function(){window.location='/';},3000);</script>
                </body></html>
                """,
            )
            access_token = token_result.get("access_token")
            if isinstance(access_token, str) and access_token:
                max_age = int(token_result.get("expires_in") or 3600)
                response.set_cookie(
                    key=ACCESS_TOKEN_COOKIE_NAME,
                    value=access_token,
                    httponly=True,
                    secure=False,
                    samesite="lax",
                    max_age=max_age,
                    path="/",
                )
            return response

        user_id = token_result.get("oid") or token_result.get("sub", "unknown")
        logger.info(
            "callback.success",
            extra={
                "custom_dimensions": {
                    "user_id": user_id,
                    "token_type": token_result.get("token_type", "unknown"),
                }
            },
        )

        # Return token and set an HTTP-only cookie so browser sessions can call
        # authenticated endpoints without manually copying bearer tokens.
        response = JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "access_token": token_result.get("access_token"),
                "token_type": token_result.get("token_type", "Bearer"),
                "expires_in": token_result.get("expires_in"),
                "scope": " ".join(msal_client.scopes),
            },
        )
        access_token = token_result.get("access_token")
        if isinstance(access_token, str) and access_token:
            max_age = int(token_result.get("expires_in") or 3600)
            response.set_cookie(
                key=ACCESS_TOKEN_COOKIE_NAME,
                value=access_token,
                httponly=True,
                secure=False,
                samesite="lax",
                max_age=max_age,
                path="/",
            )
        return response
    except Exception as exc:
        logger.exception("callback.token_exchange_failed: %s", str(exc))
        error_detail = str(exc)
        
        return HTMLResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=f"""
            <html>
                <body style="font-family: Arial; margin: 40px;">
                    <h1>Token Exchange Failed</h1>
                    <p><strong>Error:</strong> {error_detail}</p>
                    <h2>Debug Info:</h2>
                    <ul>
                        <li><strong>Redirect URI:</strong> {msal_client.redirect_uri}</li>
                        <li><strong>Client ID:</strong> {msal_client.client_id}</li>
                        <li><strong>Tenant:</strong> {msal_client.tenant_id}</li>
                        <li><strong>Code Length:</strong> {len(code) if code else 0}</li>
                        <li><strong>OAuth State:</strong> {state[:20] if state else 'None'}...</li>
                    </ul>
                    <h2>Common Fixes:</h2>
                    <ol>
                        <li>Verify <code>ENTRA_REDIRECT_URIS</code> in .env.local matches the redirect URI in Azure Portal app registration</li>
                        <li>Check that app registration has API permissions for Microsoft Graph (Mail.Read, Calendar.Read, etc.)</li>
                        <li>Ensure the authorization code hasn't expired (try again from <a href="/auth/login">login</a>)</li>
                        <li>Check server logs for detailed error message</li>
                    </ol>
                    <p><a href="/auth/login">Try Login Again</a> | <a href="/auth/login/status">Check OAuth2 Status</a></p>
                </body>
            </html>
            """,
        )
