"""Google OAuth 2.0 lifecycle manager for Google Drive & Gmail Connectors (Stages 18–19).

Features:
- Authorization URL construction with minimum required scopes per provider
- Authorization code to token exchange
- Offline refresh token handling & transparent access token refresh
- Token revocation on disconnect
- Safe error handling (invalid_grant, revoked access, network timeouts)
- Strictly keeps client secret and tokens on the backend
"""

from __future__ import annotations

import logging
import os
import urllib.parse
from typing import Any

import httpx

logger = logging.getLogger("paperflow.connectors.google_oauth")

# Minimum required scopes for Google Drive document search and user email association
GOOGLE_DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
]

# Minimum required scopes for Gmail read-only search (no send/delete/modify)
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
]

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
GOOGLE_USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v2/userinfo"


class GoogleOAuthError(Exception):
    """Base exception for Google OAuth failures."""


class TokenRevokedError(GoogleOAuthError):
    """Raised when Google indicates the token has been revoked or expired."""


class TokenExchangeError(GoogleOAuthError):
    """Raised when code exchange fails."""


def get_google_client_id() -> str:
    """Retrieve Google OAuth Client ID from environment."""
    return (os.getenv("GOOGLE_CLIENT_ID") or "").strip()


def get_google_client_secret() -> str:
    """Retrieve Google OAuth Client Secret from environment."""
    return (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()


def get_google_redirect_uri() -> str:
    """Retrieve configured OAuth callback redirect URI for Google Drive."""
    return (
        os.getenv("GOOGLE_REDIRECT_URI")
        or "http://localhost:8000/api/connectors/google-drive/callback"
    ).strip()


def get_gmail_redirect_uri() -> str:
    """Retrieve configured OAuth callback redirect URI for Gmail."""
    return (
        os.getenv("GMAIL_REDIRECT_URI")
        or "http://localhost:8000/api/connectors/gmail/callback"
    ).strip()


def is_google_oauth_configured() -> bool:
    """Check if Google OAuth credentials are configured."""
    return bool(get_google_client_id() and get_google_client_secret())


def get_authorization_url(state: str) -> str:
    """Generate the Google OAuth 2.0 consent authorization URL.

    Requirements:
    - prompt=consent: ensures refresh_token is always issued on authorization.
    - access_type=offline: requests refresh_token for background operation.
    - scope: minimum required scopes only.
    - state: CSRF protection token bound to authenticated user.
    """
    client_id = get_google_client_id()
    redirect_uri = get_google_redirect_uri()

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(GOOGLE_DRIVE_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "include_granted_scopes": "true",
    }
    return f"{GOOGLE_AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"


def get_authorization_url_for_provider(
    state: str,
    scopes: list[str],
    redirect_uri: str | None = None,
) -> str:
    """Generate a Google OAuth 2.0 consent URL for any provider.

    Args:
        state: CSRF protection token bound to authenticated user.
        scopes: List of OAuth scopes to request.
        redirect_uri: Override redirect URI. Falls back to default Drive redirect.
    """
    client_id = get_google_client_id()
    redir = redirect_uri or get_google_redirect_uri()

    params = {
        "client_id": client_id,
        "redirect_uri": redir,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "include_granted_scopes": "true",
    }
    return f"{GOOGLE_AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"


async def exchange_code_for_tokens(code: str, redirect_uri: str | None = None) -> dict[str, Any]:
    """Exchange authorization code for access and refresh tokens.

    Args:
        code: Authorization code from Google OAuth callback.
        redirect_uri: The redirect URI used in the authorization request.
                      Must match the redirect_uri used when generating the auth URL.
                      Defaults to the Google Drive redirect URI if not specified.
    """
    client_id = get_google_client_id()
    client_secret = get_google_client_secret()
    redir = redirect_uri or get_google_redirect_uri()

    payload = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redir,
        "grant_type": "authorization_code",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            res = await client.post(GOOGLE_TOKEN_ENDPOINT, data=payload)
            data = res.json()
            if res.status_code != 200:
                err_desc = data.get("error_description") or data.get("error") or res.text
                logger.error("Token exchange failed: %s (status %s)", err_desc, res.status_code)
                raise TokenExchangeError(f"Failed to exchange code: {err_desc}")

            return data
        except httpx.RequestError as exc:
            logger.error("Network error during token exchange: %s", exc)
            raise GoogleOAuthError(f"Network error communicating with Google OAuth: {exc}")


async def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    """Obtain a fresh access token using the stored refresh token.

    Handles revoked tokens (invalid_grant) by raising TokenRevokedError.
    """
    client_id = get_google_client_id()
    client_secret = get_google_client_secret()

    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            res = await client.post(GOOGLE_TOKEN_ENDPOINT, data=payload)
            data = res.json()
            if res.status_code != 200:
                err = data.get("error", "")
                desc = data.get("error_description", "")
                if "invalid_grant" in err or "revoked" in desc.lower():
                    logger.warning("Google refresh token was revoked: %s", desc)
                    raise TokenRevokedError("Google Drive access has been revoked or expired.")

                logger.error("Token refresh failed: %s (%s)", desc or err, res.status_code)
                raise GoogleOAuthError(f"Could not refresh access token: {desc or err}")

            return data
        except httpx.RequestError as exc:
            logger.error("Network error during token refresh: %s", exc)
            raise GoogleOAuthError(f"Network error communicating with Google OAuth: {exc}")


async def revoke_token(token: str) -> bool:
    """Revoke an access or refresh token with Google's revocation endpoint."""
    if not token:
        return True

    params = {"token": token}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.post(GOOGLE_REVOKE_ENDPOINT, params=params)
            return res.status_code == 200
        except Exception as exc:
            logger.warning("Token revocation request failed: %s", exc)
            return False


async def get_google_user_email(access_token: str) -> str | None:
    """Fetch the connected Google user's email address."""
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.get(GOOGLE_USERINFO_ENDPOINT, headers=headers)
            if res.status_code == 200:
                data = res.json()
                return data.get("email")
        except Exception as exc:
            logger.warning("Could not retrieve Google user profile: %s", exc)

    return None
