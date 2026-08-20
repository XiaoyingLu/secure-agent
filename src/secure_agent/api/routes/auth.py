"""OAuth2 authentication routes (MSAL auth-code flow with PKCE)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])
ACCESS_TOKEN_COOKIE_NAME = "secure_agent_access_token"

GRAPH_CONSENT_SCOPES = [
    "https://graph.microsoft.com/Calendars.Read",
    "https://graph.microsoft.com/Mail.Read",
    "https://graph.microsoft.com/Sites.Read.All",
]
_GRAPH_CONSENT_STATE_PREFIX = "graphconsent_"


@router.get("/graph-consent", response_model=None)
async def get_graph_consent(request: Request) -> RedirectResponse | HTMLResponse:
    """Initiate a one-time Graph permission consent flow."""
    msal_client = getattr(request.app.state, "msal_client", None)
    if msal_client is None:
        return HTMLResponse(
            status_code=503,
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
            status_code=500,
            content=f"<html><body><h1>Error</h1><p>{exc}</p></body></html>",
        )

    logger.info("graph_consent.redirect state=%s", consent_state)
    return RedirectResponse(url=auth_url, status_code=302)


@router.get("/login/status")
async def get_login_status(request: Request) -> JSONResponse:
    """Diagnostic endpoint to check if OAuth2 is configured."""
    msal_client = getattr(request.app.state, "msal_client", None)
    if msal_client is None:
        return JSONResponse(
            status_code=503,
            content={
                "configured": False,
                "reason": "MSAL client not initialized",
                "required_env_var": "ENTRA_CLIENT_SECRET",
                "details": "Set ENTRA_CLIENT_SECRET in .env.local to enable confidential-client OAuth2 login flow",
            },
        )

    return JSONResponse(
        status_code=200,
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
    """Diagnostic endpoint to check what scopes the current user has."""
    token = request.cookies.get(ACCESS_TOKEN_COOKIE_NAME)

    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.replace("Bearer ", "")

    if not token:
        return HTMLResponse(
            status_code=401,
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

    try:
        import base64
        import json as _json

        parts = token.split(".")
        if len(parts) < 2:
            raise ValueError("Invalid token format")
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = _json.loads(base64.urlsafe_b64decode(padded))
    except Exception as exc:
        return JSONResponse(
            status_code=400,
            content={"error": f"Could not decode token: {exc}"},
        )

    scp = payload.get("scp", "").split()
    required_scopes = ["Calendars.Read", "Mail.Read", "Sites.Read.All"]
    missing_scopes = [scope for scope in required_scopes if scope not in scp]
    has_all_scopes = len(missing_scopes) == 0

    return JSONResponse(
        status_code=200 if has_all_scopes else 403,
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
                else f"❌ Missing scopes: {', '.join(missing_scopes)}. Visit /auth/graph-consent to request them."
            ),
        },
    )


@router.get("/login", response_model=None)
async def get_login(request: Request) -> RedirectResponse | HTMLResponse:
    """Initiate OAuth2 authorization code flow with PKCE."""
    msal_client = getattr(request.app.state, "msal_client", None)
    if msal_client is None:
        return HTMLResponse(
            status_code=503,
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
                    "redirect_uri": msal_client.redirect_uri,
                    "scopes": msal_client.scopes,
                }
            },
        )
        return RedirectResponse(url=auth_url, status_code=302)
    except Exception as exc:  # pragma: no cover - safety net for login failure
        logger.exception("login.build_url_failed: %s", exc)
        return HTMLResponse(
            status_code=500,
            content=f"<html><body><h1>Authentication Error</h1><p>{exc}</p></body></html>",
        )


@router.get("/callback")
async def get_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> JSONResponse:
    """Handle the OAuth callback and set the access token as a secure cookie."""
    msal_client = getattr(request.app.state, "msal_client", None)
    if msal_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MSAL client not configured.",
        )

    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Authorization denied: {error}",
        )

    if not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing OAuth state in callback.",
        )

    if not msal_client.is_known_auth_state(state):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSRF state mismatch. Authorization rejected.",
        )

    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing authorization code in callback.",
        )

    token_result = msal_client.exchange_authorization_code(code, state=state)
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
