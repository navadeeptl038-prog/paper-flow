"""API routes for external OAuth connectors (Stages 18–19 — Google Drive & Gmail).

Endpoints:
  GET    /api/connectors/status                 — list connector statuses for authenticated user
  GET    /api/connectors/google-drive/status    — get Google Drive connection status
  GET    /api/connectors/google-drive/authorize — generate Google OAuth consent URL
  GET    /api/connectors/google-drive/callback  — handle Google OAuth redirect
  GET    /api/connectors/google-drive/search    — search files in connected Google Drive
  POST   /api/connectors/google-drive/disconnect— revoke tokens and disconnect Drive
  GET    /api/connectors/gmail/status           — get Gmail connection status
  GET    /api/connectors/gmail/authorize        — generate Gmail OAuth consent URL
  GET    /api/connectors/gmail/callback         — handle Gmail OAuth redirect
  GET    /api/connectors/gmail/search           — search messages in connected Gmail
  POST   /api/connectors/gmail/disconnect       — revoke tokens and disconnect Gmail
"""

from __future__ import annotations

import logging
import os
import secrets
import urllib.parse
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth.authorization import require_user
from connectors import gmail, google_drive, google_oauth
from connectors.gmail import GmailAPIError
from connectors.google_drive import GoogleDriveAPIError
from connectors.google_oauth import TokenRevokedError
from models.connector import (
    ConnectAuthorizeResponse,
    ConnectorStatusResponse,
    DisconnectResponse,
    DriveSearchResponse,
    GmailSearchResponse,
)
from models.user import AuthenticatedUser
from storage import connector_repository
from utils import security

logger = logging.getLogger("paperflow.connectors.routes")

router = APIRouter(prefix="/api/connectors", tags=["connectors"])
_bearer = HTTPBearer(auto_error=False)

# In-memory mapping of active OAuth states for CSRF validation: dict[state_token, (owner_id, provider)]
_oauth_states: dict[str, str] = {}


def _get_frontend_url() -> str:
    """Retrieve frontend base URL for OAuth redirection."""
    return (os.getenv("FRONTEND_URL") or "http://localhost:5173").rstrip("/")


# ---------------------------------------------------------------------------
# Helper: build ConnectorStatusResponse from stored connector data
# ---------------------------------------------------------------------------

def _build_status(provider: str, name: str, conn: dict[str, Any] | None) -> ConnectorStatusResponse:
    """Build a ConnectorStatusResponse from connector row data (or None)."""
    is_connected = bool(conn and conn.get("status") == "connected")
    return ConnectorStatusResponse(
        provider=provider,
        name=name,
        connected=is_connected,
        account_email=conn.get("account_email") if conn else None,
        status=conn.get("status", "not_connected") if conn else "not_connected",
        scopes=conn.get("scopes", []) if conn else [],
        created_at=conn.get("created_at") if conn else None,
        updated_at=conn.get("updated_at") if conn else None,
        last_synced_at=conn.get("updated_at") if conn else None,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Combined status
# ═══════════════════════════════════════════════════════════════════════════

@router.get(
    "/status",
    response_model=list[ConnectorStatusResponse],
    summary="List connector statuses",
    description="Retrieve connection state and linked account information for all connectors. Never exposes tokens.",
)
async def list_connectors_status(
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> list[ConnectorStatusResponse]:
    """List connection statuses for the authenticated user."""
    token = credentials.credentials if credentials else None

    drive_conn = connector_repository.get_connector(user.user_id, "google_drive", token=token)
    gmail_conn = connector_repository.get_connector(user.user_id, "gmail", token=token)

    return [
        _build_status("google_drive", "Google Drive", drive_conn),
        _build_status("gmail", "Gmail", gmail_conn),
    ]


# ═══════════════════════════════════════════════════════════════════════════
# Google Drive endpoints (Stage 18)
# ═══════════════════════════════════════════════════════════════════════════

@router.get(
    "/google-drive/status",
    response_model=ConnectorStatusResponse,
    summary="Get Google Drive connection status",
)
async def get_google_drive_status(
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> ConnectorStatusResponse:
    """Retrieve Google Drive connector status for authenticated user."""
    token = credentials.credentials if credentials else None
    drive_conn = connector_repository.get_connector(user.user_id, "google_drive", token=token)
    return _build_status("google_drive", "Google Drive", drive_conn)


@router.get(
    "/google-drive/authorize",
    response_model=ConnectAuthorizeResponse,
    summary="Initiate Google Drive OAuth authorization",
    description="Generates Google OAuth 2.0 consent URL with minimum required scopes. Google login != Google Drive connector.",
)
async def authorize_google_drive(
    user: AuthenticatedUser = Depends(require_user),
) -> ConnectAuthorizeResponse:
    """Generate OAuth consent URL for Google Drive."""
    if not google_oauth.is_google_oauth_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured on the backend. Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
        )

    # Cryptographically signed, time-bound OAuth CSRF state token bound to user
    state_token = security.generate_signed_oauth_state(user.user_id)
    _oauth_states[state_token] = user.user_id

    auth_url = google_oauth.get_authorization_url(state=state_token)
    return ConnectAuthorizeResponse(
        provider="google_drive",
        authorization_url=auth_url,
        state=state_token,
    )


@router.get(
    "/google-drive/callback",
    summary="Handle Google OAuth callback",
    description="Exchanges authorization code, fetches user email, and associates connector with PaperFlow user.",
)
async def google_drive_callback(
    code: str | None = Query(None, description="Authorization code from Google"),
    state: str | None = Query(None, description="OAuth state verification token"),
    error: str | None = Query(None, description="Error returned from Google"),
) -> RedirectResponse:
    """OAuth 2.0 callback endpoint handling Google redirect."""
    frontend_base = _get_frontend_url()

    if error:
        logger.warning("Google OAuth error on callback: %s", error)
        return RedirectResponse(
            url=f"{frontend_base}/connectors?status=error&provider=google-drive&message={error}",
            status_code=status.HTTP_302_FOUND,
        )

    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing code or state parameter in OAuth callback.",
        )

    # Cryptographically verify state token (HMAC-SHA256 signature + timestamp expiry)
    owner_id = security.verify_signed_oauth_state(state)
    if not owner_id:
        # Fallback to active in-memory cache check
        owner_id = _oauth_states.pop(state, None)

    if not owner_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid, forged, or expired OAuth state parameter.",
        )

    try:
        tokens = await google_oauth.exchange_code_for_tokens(code)
        account_email = await google_oauth.get_google_user_email(tokens.get("access_token", ""))

        connector_repository.save_connector_tokens(
            owner_id=owner_id,
            provider="google_drive",
            tokens=tokens,
            account_email=account_email,
            scopes=google_oauth.GOOGLE_DRIVE_SCOPES,
        )

        logger.info("Successfully connected Google Drive for user %s (%s)", owner_id, account_email)
        return RedirectResponse(
            url=f"{frontend_base}/connectors?status=connected&provider=google-drive",
            status_code=status.HTTP_302_FOUND,
        )
    except Exception as exc:
        logger.exception("Failed to process Google Drive OAuth callback: %s", exc)
        return RedirectResponse(
            url=f"{frontend_base}/connectors?status=error&provider=google-drive&message={urllib.parse.quote(str(exc))}",
            status_code=status.HTTP_302_FOUND,
        )


@router.get(
    "/google-drive/search",
    response_model=DriveSearchResponse,
    summary="Search Google Drive files",
    description="Search files in user's connected Google Drive with automatic token refresh and revocation handling.",
)
async def search_google_drive(
    q: str = Query(..., min_length=1, description="Keywords to search in Google Drive"),
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> DriveSearchResponse:
    """Search files in user's connected Google Drive."""
    token = credentials.credentials if credentials else None

    try:
        access_token = await google_drive.get_valid_access_token(user.user_id, token=token)
        files = await google_drive.search_drive_files(access_token=access_token, query=q)
        return DriveSearchResponse(
            provider="google_drive",
            query=q,
            count=len(files),
            files=files,
        )
    except TokenRevokedError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google Drive access has been revoked or expired. Please reconnect.",
        )
    except GoogleDriveAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


@router.post(
    "/google-drive/disconnect",
    response_model=DisconnectResponse,
    summary="Disconnect Google Drive",
    description="Revokes OAuth tokens with Google and removes connector records.",
)
async def disconnect_google_drive(
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> DisconnectResponse:
    """Disconnect Google Drive and revoke stored credentials."""
    token = credentials.credentials if credentials else None
    conn = connector_repository.get_connector(user.user_id, "google_drive", token=token)

    if conn:
        token_to_revoke = conn.get("refresh_token") or conn.get("access_token")
        if token_to_revoke:
            await google_oauth.revoke_token(token_to_revoke)

    connector_repository.delete_connector(user.user_id, "google_drive", token=token)

    return DisconnectResponse(
        provider="google_drive",
        disconnected=True,
        message="Successfully disconnected Google Drive.",
    )


# ═══════════════════════════════════════════════════════════════════════════
# Gmail endpoints (Stage 19)
# ═══════════════════════════════════════════════════════════════════════════

@router.get(
    "/gmail/status",
    response_model=ConnectorStatusResponse,
    summary="Get Gmail connection status",
)
async def get_gmail_status(
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> ConnectorStatusResponse:
    """Retrieve Gmail connector status for authenticated user."""
    token = credentials.credentials if credentials else None
    gmail_conn = connector_repository.get_connector(user.user_id, "gmail", token=token)
    return _build_status("gmail", "Gmail", gmail_conn)


@router.get(
    "/gmail/authorize",
    response_model=ConnectAuthorizeResponse,
    summary="Initiate Gmail OAuth authorization",
    description="Generates Google OAuth 2.0 consent URL with gmail.readonly scope. Read-only — no send/delete/modify.",
)
async def authorize_gmail(
    user: AuthenticatedUser = Depends(require_user),
) -> ConnectAuthorizeResponse:
    """Generate OAuth consent URL for Gmail (read-only)."""
    if not google_oauth.is_google_oauth_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured on the backend. Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
        )

    # Cryptographically signed, time-bound OAuth CSRF state token bound to user
    state_token = security.generate_signed_oauth_state(user.user_id)
    _oauth_states[state_token] = user.user_id

    auth_url = google_oauth.get_authorization_url_for_provider(
        state=state_token,
        scopes=google_oauth.GMAIL_SCOPES,
        redirect_uri=google_oauth.get_gmail_redirect_uri(),
    )
    return ConnectAuthorizeResponse(
        provider="gmail",
        authorization_url=auth_url,
        state=state_token,
    )


@router.get(
    "/gmail/callback",
    summary="Handle Gmail OAuth callback",
    description="Exchanges authorization code, fetches user email, and associates Gmail connector with PaperFlow user.",
)
async def gmail_callback(
    code: str | None = Query(None, description="Authorization code from Google"),
    state: str | None = Query(None, description="OAuth state verification token"),
    error: str | None = Query(None, description="Error returned from Google"),
) -> RedirectResponse:
    """OAuth 2.0 callback endpoint handling Gmail redirect."""
    frontend_base = _get_frontend_url()

    if error:
        logger.warning("Gmail OAuth error on callback: %s", error)
        return RedirectResponse(
            url=f"{frontend_base}/connectors?status=error&provider=gmail&message={error}",
            status_code=status.HTTP_302_FOUND,
        )

    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing code or state parameter in Gmail OAuth callback.",
        )

    # Cryptographically verify state token (HMAC-SHA256 signature + timestamp expiry)
    owner_id = security.verify_signed_oauth_state(state)
    if not owner_id:
        # Fallback to active in-memory cache check
        owner_id = _oauth_states.pop(state, None)

    if not owner_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid, forged, or expired OAuth state parameter.",
        )

    try:
        gmail_redirect = google_oauth.get_gmail_redirect_uri()
        tokens = await google_oauth.exchange_code_for_tokens(code, redirect_uri=gmail_redirect)
        account_email = await google_oauth.get_google_user_email(tokens.get("access_token", ""))

        connector_repository.save_connector_tokens(
            owner_id=owner_id,
            provider="gmail",
            tokens=tokens,
            account_email=account_email,
            scopes=google_oauth.GMAIL_SCOPES,
        )

        logger.info("Successfully connected Gmail for user %s (%s)", owner_id, account_email)
        return RedirectResponse(
            url=f"{frontend_base}/connectors?status=connected&provider=gmail",
            status_code=status.HTTP_302_FOUND,
        )
    except Exception as exc:
        logger.exception("Failed to process Gmail OAuth callback: %s", exc)
        return RedirectResponse(
            url=f"{frontend_base}/connectors?status=error&provider=gmail&message={urllib.parse.quote(str(exc))}",
            status_code=status.HTTP_302_FOUND,
        )


@router.get(
    "/gmail/search",
    response_model=GmailSearchResponse,
    summary="Search Gmail messages",
    description="Search messages in user's connected Gmail with automatic token refresh and revocation handling. Read-only.",
)
async def search_gmail(
    q: str = Query(..., min_length=1, description="Keywords to search in Gmail"),
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> GmailSearchResponse:
    """Search messages in user's connected Gmail."""
    token = credentials.credentials if credentials else None

    try:
        access_token = await gmail.get_valid_access_token(user.user_id, token=token)
        messages = await gmail.search_gmail_messages(access_token=access_token, query=q)
        return GmailSearchResponse(
            provider="gmail",
            query=q,
            count=len(messages),
            messages=messages,
        )
    except TokenRevokedError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Gmail access has been revoked or expired. Please reconnect.",
        )
    except GmailAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


@router.post(
    "/gmail/disconnect",
    response_model=DisconnectResponse,
    summary="Disconnect Gmail",
    description="Revokes OAuth tokens with Google and removes Gmail connector records.",
)
async def disconnect_gmail(
    user: AuthenticatedUser = Depends(require_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> DisconnectResponse:
    """Disconnect Gmail and revoke stored credentials."""
    token = credentials.credentials if credentials else None
    conn = connector_repository.get_connector(user.user_id, "gmail", token=token)

    if conn:
        token_to_revoke = conn.get("refresh_token") or conn.get("access_token")
        if token_to_revoke:
            await google_oauth.revoke_token(token_to_revoke)

    connector_repository.delete_connector(user.user_id, "gmail", token=token)

    return DisconnectResponse(
        provider="gmail",
        disconnected=True,
        message="Successfully disconnected Gmail.",
    )
