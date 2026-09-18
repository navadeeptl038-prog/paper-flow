"""Gmail API connector for searching and reading emails (Stage 19).

Features:
- Search messages in user's Gmail by query keywords
- Retrieve email metadata: subject, sender, recipient, date, snippet
- Detect and list attachment metadata (filename, MIME type, size)
- Automatic token expiration detection & transparent refresh
- Revocation handling with clean status transitions
- Graceful API error handling (401, 403 quota, 429 rate limit)
- Read-only: never sends, deletes, or modifies email

Security:
- Minimum scope: gmail.readonly + userinfo.email
- No send/delete/modify scopes
- Tokens remain strictly backend-side
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

import httpx

from connectors import google_oauth
from connectors.google_oauth import TokenRevokedError
from models.connector import GmailAttachmentItem, GmailMessageItem
from models.search import UnifiedSearchResultItem
from storage import connector_repository

logger = logging.getLogger("paperflow.connectors.gmail")

GMAIL_MESSAGES_API = "https://gmail.googleapis.com/gmail/v1/users/me/messages"


class GmailAPIError(Exception):
    """Exception raised when Gmail API calls fail."""


async def get_valid_access_token(
    owner_id: str,
    token: str | None = None,
) -> str:
    """Retrieve a valid access token for Gmail, refreshing automatically if expired.

    Raises:
        TokenRevokedError: If access was revoked by user or Google.
        GmailAPIError: If connector is not connected or refresh fails.
    """
    conn = connector_repository.get_connector(owner_id, "gmail", token=token)
    if not conn or conn.get("status") != "connected":
        status_name = conn.get("status", "not_connected") if conn else "not_connected"
        raise GmailAPIError(f"Gmail is not connected (current status: '{status_name}').")

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
        connector_repository.mark_connector_status(owner_id, "gmail", "expired", token=token)
        raise GmailAPIError("Gmail access token expired and no refresh token is available. Please reconnect.")

    try:
        token_data = await google_oauth.refresh_access_token(refresh_token)
        new_access_token = token_data.get("access_token")
        expires_in = int(token_data.get("expires_in", 3600))
        new_expires_at = (now + datetime.timedelta(seconds=expires_in)).isoformat()

        connector_repository.update_connector_tokens(
            owner_id=owner_id,
            provider="gmail",
            new_access_token=new_access_token,
            expires_at=new_expires_at,
            token=token,
        )
        return new_access_token
    except TokenRevokedError as exc:
        connector_repository.mark_connector_status(owner_id, "gmail", "revoked", token=token)
        raise exc
    except Exception as exc:
        logger.error("Failed to refresh Gmail token for user %s: %s", owner_id, exc)
        raise GmailAPIError(f"Could not refresh Gmail token: {exc}")


def _extract_header(headers: list[dict[str, str]], name: str) -> str | None:
    """Extract a header value from Gmail message headers list."""
    name_lower = name.lower()
    for h in headers:
        if h.get("name", "").lower() == name_lower:
            return h.get("value")
    return None


def _extract_attachments(payload: dict[str, Any]) -> list[GmailAttachmentItem]:
    """Recursively extract attachment metadata from message payload parts."""
    attachments: list[GmailAttachmentItem] = []

    parts = payload.get("parts", [])
    for part in parts:
        filename = part.get("filename", "")
        body = part.get("body", {})
        attachment_id = body.get("attachmentId")

        if filename and attachment_id:
            size_bytes = body.get("size")
            attachments.append(
                GmailAttachmentItem(
                    filename=filename,
                    mime_type=part.get("mimeType", "application/octet-stream"),
                    size_bytes=size_bytes,
                    attachment_id=attachment_id,
                )
            )

        # Recurse into nested multipart parts
        if part.get("parts"):
            attachments.extend(_extract_attachments(part))

    return attachments


async def search_gmail_messages(
    access_token: str,
    query: str,
    max_results: int = 15,
) -> list[GmailMessageItem]:
    """Search Gmail for messages matching the query.

    Args:
        access_token: Valid OAuth 2.0 access token with gmail.readonly scope.
        query: Gmail search query (same syntax as Gmail search bar).
        max_results: Maximum messages to retrieve metadata for.

    Returns:
        List of GmailMessageItem objects with metadata and attachment info.
    """
    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            # Step 1: List matching message IDs
            list_params = {
                "q": query.strip(),
                "maxResults": min(max_results, 50),
            }
            list_res = await client.get(GMAIL_MESSAGES_API, headers=headers, params=list_params)

            if list_res.status_code == 401:
                raise TokenRevokedError("Gmail access token expired or revoked.")
            elif list_res.status_code == 403:
                data = list_res.json()
                msg = data.get("error", {}).get("message", "Rate limit or quota exceeded.")
                raise GmailAPIError(f"Gmail API quota or permission error: {msg}")
            elif list_res.status_code == 429:
                raise GmailAPIError("Gmail API rate limit exceeded. Please try again shortly.")
            elif list_res.status_code != 200:
                raise GmailAPIError(f"Gmail API returned HTTP {list_res.status_code}: {list_res.text}")

            list_data = list_res.json()
            message_stubs = list_data.get("messages", [])

            if not message_stubs:
                return []

            # Step 2: Fetch metadata for each message
            results: list[GmailMessageItem] = []
            for stub in message_stubs[:max_results]:
                msg_id = stub["id"]
                msg_url = f"{GMAIL_MESSAGES_API}/{msg_id}"
                msg_params = {"format": "metadata", "metadataHeaders": "Subject,From,To,Date"}

                msg_res = await client.get(msg_url, headers=headers, params=msg_params)

                if msg_res.status_code == 401:
                    raise TokenRevokedError("Gmail access token expired or revoked.")
                elif msg_res.status_code != 200:
                    logger.warning("Failed to fetch Gmail message %s: HTTP %s", msg_id, msg_res.status_code)
                    continue

                msg_data = msg_res.json()
                payload = msg_data.get("payload", {})
                msg_headers = payload.get("headers", [])

                subject = _extract_header(msg_headers, "Subject")
                sender = _extract_header(msg_headers, "From")
                to = _extract_header(msg_headers, "To")
                date = _extract_header(msg_headers, "Date")

                snippet = msg_data.get("snippet", "")
                label_ids = msg_data.get("labelIds", [])

                # Extract attachment metadata
                attachments = _extract_attachments(payload)
                has_attachments = len(attachments) > 0

                results.append(
                    GmailMessageItem(
                        id=msg_id,
                        thread_id=msg_data.get("threadId"),
                        subject=subject,
                        sender=sender,
                        to=to,
                        date=date,
                        snippet=snippet,
                        labels=label_ids,
                        has_attachments=has_attachments,
                        attachments=attachments,
                        source="Gmail",
                    )
                )

            return results

        except httpx.RequestError as exc:
            logger.error("Network error communicating with Gmail API: %s", exc)
            raise GmailAPIError(f"Network error communicating with Gmail: {exc}")


async def search_user_gmail(
    query: str,
    user_id: str,
    top_k: int = 10,
    token: str | None = None,
) -> list[UnifiedSearchResultItem]:
    """Search Gmail for the authenticated user and return normalized UnifiedSearchResultItem list.

    Preserves source, title (subject), reference (message id), relevance, metadata, and authorization context.
    Read-only: does not permanently duplicate messages or download full payloads into local storage / Render.
    """
    clean_q = query.strip()
    if not clean_q:
        return []

    conn = connector_repository.get_connector(user_id, "gmail", token=token)
    if not conn or conn.get("status") != "connected":
        return []

    access_token = await get_valid_access_token(user_id, token=token)
    messages = await search_gmail_messages(access_token, clean_q, max_results=top_k)

    q_lower = clean_q.lower()
    q_words = [w for w in q_lower.split() if len(w) > 1]
    account_email = conn.get("account_email")

    results: list[UnifiedSearchResultItem] = []
    for msg in messages:
        subject = msg.subject or "No Subject"
        subj_lower = subject.lower()
        snip_lower = (msg.snippet or "").lower()

        # Relevance scoring
        if q_lower in subj_lower:
            relevance = 0.90
        elif q_lower in snip_lower:
            relevance = 0.80
        elif q_words and any(w in subj_lower for w in q_words):
            relevance = 0.75
        elif q_words and any(w in snip_lower for w in q_words):
            relevance = 0.70
        else:
            relevance = 0.60

        # Also check if query matches attachment filename
        if msg.attachments:
            for att in msg.attachments:
                if q_lower in att.filename.lower():
                    relevance = max(relevance, 0.88)

        view_url = f"https://mail.google.com/mail/u/0/#inbox/{msg.id}"

        results.append(
            UnifiedSearchResultItem(
                id=f"gmail_{msg.id}",
                source="Gmail",
                title=f"Email: {subject}",
                reference=msg.id,
                relevance=round(relevance, 4),
                snippet=msg.snippet or f"Email from {msg.sender or 'unknown sender'} on {msg.date or 'unknown date'}",
                metadata={
                    "subject": subject,
                    "sender": msg.sender,
                    "to": msg.to,
                    "date": msg.date,
                    "thread_id": msg.thread_id,
                    "labels": msg.labels,
                    "has_attachments": msg.has_attachments,
                    "attachments": [a.model_dump() for a in msg.attachments],
                },
                authorization_context={
                    "owner_id": user_id,
                    "provider": "gmail",
                    "account_email": account_email,
                    "is_authorized": True,
                },
                view_url=view_url,
                download_url=None,
            )
        )

    return sorted(results, key=lambda r: r.relevance, reverse=True)[:top_k]

