"""Google Drive v3 API connector for searching and accessing files (Stage 18).

Features:
- Search files in user's Drive by query keywords
- Automatic token expiration detection & transparent refresh
- Revocation handling with clean status transitions
- Graceful API error handling (401, 403 quota, 429 rate limit)
- Returns structured DriveFileItem with view and download links
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

import httpx

from connectors import google_oauth
from connectors.google_oauth import TokenRevokedError
from models.connector import DriveFileItem
from models.search import UnifiedSearchResultItem
from storage import connector_repository

logger = logging.getLogger("paperflow.connectors.google_drive")

DRIVE_FILES_API = "https://www.googleapis.com/drive/v3/files"


class GoogleDriveAPIError(Exception):
    """Exception raised when Google Drive API calls fail."""


async def get_valid_access_token(
    owner_id: str,
    token: str | None = None,
) -> str:
    """Retrieve a valid access token for the user, refreshing automatically if expired.

    Raises:
        TokenRevokedError: If access was revoked by user or Google.
        GoogleDriveAPIError: If connector is not connected or refresh fails.
    """
    conn = connector_repository.get_connector(owner_id, "google_drive", token=token)
    if not conn or conn.get("status") != "connected":
        status_name = conn.get("status", "not_connected") if conn else "not_connected"
        raise GoogleDriveAPIError(f"Google Drive is not connected (current status: '{status_name}').")

    access_token = conn.get("access_token")
    refresh_token = conn.get("refresh_token")
    expires_at_str = conn.get("expires_at")

    now = datetime.datetime.now(datetime.timezone.utc)
    is_expired = False

    if expires_at_str:
        try:
            expires_at = datetime.datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            # Treat as expired if within 60 seconds of expiration
            if now + datetime.timedelta(seconds=60) >= expires_at:
                is_expired = True
        except Exception:
            is_expired = True
    elif not access_token:
        is_expired = True

    # If token is still valid, return it directly
    if not is_expired and access_token:
        return access_token

    # Token needs refresh
    if not refresh_token:
        connector_repository.mark_connector_status(owner_id, "google_drive", "expired", token=token)
        raise GoogleDriveAPIError("Google Drive access token expired and no refresh token is available. Please reconnect.")

    try:
        token_data = await google_oauth.refresh_access_token(refresh_token)
        new_access_token = token_data.get("access_token")
        expires_in = int(token_data.get("expires_in", 3600))
        new_expires_at = (now + datetime.timedelta(seconds=expires_in)).isoformat()

        connector_repository.update_connector_tokens(
            owner_id=owner_id,
            provider="google_drive",
            new_access_token=new_access_token,
            expires_at=new_expires_at,
            token=token,
        )
        return new_access_token
    except TokenRevokedError as exc:
        connector_repository.mark_connector_status(owner_id, "google_drive", "revoked", token=token)
        raise exc
    except Exception as exc:
        logger.error("Failed to refresh Google Drive token for user %s: %s", owner_id, exc)
        raise GoogleDriveAPIError(f"Could not refresh Google Drive token: {exc}")


async def search_drive_files(
    access_token: str,
    query: str,
    page_size: int = 15,
) -> list[DriveFileItem]:
    """Execute a file search query against Google Drive v3 API.

    Args:
        access_token: Valid OAuth 2.0 access token
        query: Search keywords
        page_size: Maximum items to retrieve

    Returns:
        List of matching DriveFileItem objects.
    """
    clean_q = query.replace("'", "\\'").strip()

    # Search by filename or full text matching in Drive
    drive_filter = f"name contains '{clean_q}' and trashed = false"

    params = {
        "q": drive_filter,
        "pageSize": min(page_size, 50),
        "fields": "files(id, name, mimeType, size, modifiedTime, webViewLink, webContentLink)",
        "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true",
    }

    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            res = await client.get(DRIVE_FILES_API, headers=headers, params=params)

            if res.status_code == 401:
                raise TokenRevokedError("Google Drive access token expired or revoked.")
            elif res.status_code == 403:
                data = res.json()
                msg = data.get("error", {}).get("message", "Rate limit or quota exceeded.")
                raise GoogleDriveAPIError(f"Google Drive API quota or permission error: {msg}")
            elif res.status_code == 429:
                raise GoogleDriveAPIError("Google Drive API rate limit exceeded. Please try again shortly.")
            elif res.status_code != 200:
                raise GoogleDriveAPIError(f"Google Drive API returned HTTP {res.status_code}: {res.text}")

            data = res.json()
            drive_files = data.get("files", [])

            results: list[DriveFileItem] = []
            for f in drive_files:
                size_val = None
                if f.get("size"):
                    try:
                        size_val = int(f["size"])
                    except Exception:
                        pass

                results.append(
                    DriveFileItem(
                        id=f["id"],
                        name=f.get("name", "Untitled"),
                        mime_type=f.get("mimeType", "application/octet-stream"),
                        size_bytes=size_val,
                        modified_at=f.get("modifiedTime"),
                        view_url=f.get("webViewLink"),
                        download_url=f.get("webContentLink"),
                        source="Google Drive",
                    )
                )

            return results
        except httpx.RequestError as exc:
            logger.error("Network error communicating with Google Drive API: %s", exc)
            raise GoogleDriveAPIError(f"Network error communicating with Google Drive: {exc}")


async def search_user_drive(
    query: str,
    user_id: str,
    top_k: int = 10,
    token: str | None = None,
) -> list[UnifiedSearchResultItem]:
    """Search Google Drive for the authenticated user and return normalized UnifiedSearchResultItem list.

    Preserves source, title, reference, relevance, metadata, and authorization context.
    Does NOT download full files into local storage or Render.
    """
    clean_q = query.strip()
    if not clean_q:
        return []

    conn = connector_repository.get_connector(user_id, "google_drive", token=token)
    if not conn or conn.get("status") != "connected":
        return []

    access_token = await get_valid_access_token(user_id, token=token)
    drive_items = await search_drive_files(access_token, clean_q, page_size=top_k)

    q_lower = clean_q.lower()
    q_words = [w for w in q_lower.split() if len(w) > 1]
    account_email = conn.get("account_email")

    results: list[UnifiedSearchResultItem] = []
    for item in drive_items:
        name_lower = item.name.lower()
        if q_lower in name_lower:
            relevance = 0.90
        elif q_words and any(w in name_lower for w in q_words):
            matched = sum(1 for w in q_words if w in name_lower)
            relevance = 0.60 + 0.30 * (matched / len(q_words))
        else:
            relevance = 0.65

        results.append(
            UnifiedSearchResultItem(
                id=f"gdrive_{item.id}",
                source="Google Drive",
                title=item.name,
                reference=item.id,
                relevance=round(relevance, 4),
                snippet=f"Google Drive file: {item.name} ({item.mime_type})",
                metadata={
                    "mime_type": item.mime_type,
                    "size_bytes": item.size_bytes,
                    "modified_at": item.modified_at,
                    "external_id": item.id,
                },
                authorization_context={
                    "owner_id": user_id,
                    "provider": "google_drive",
                    "account_email": account_email,
                    "is_authorized": True,
                },
                view_url=item.view_url,
                download_url=item.download_url,
            )
        )

    return sorted(results, key=lambda r: r.relevance, reverse=True)[:top_k]

