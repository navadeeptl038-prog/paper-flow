"""Pydantic models for External Connectors (Stages 18–19: Google Drive & Gmail).

Defines schemas for connector status, authorization URLs,
Drive file items, Gmail message items, search responses, and disconnection results.
Never exposes client secrets or tokens to the frontend.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class ConnectorStatusResponse(BaseModel):
    """Public status representation of an external connector."""

    provider: str
    name: str
    connected: bool
    account_email: str | None = None
    status: str = "not_connected"  # 'connected', 'not_connected', 'revoked', 'expired'
    scopes: list[str] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None
    last_synced_at: str | None = None


class ConnectAuthorizeResponse(BaseModel):
    """Response containing the OAuth 2.0 authorization URL and state."""

    provider: str
    authorization_url: str
    state: str


class DriveFileItem(BaseModel):
    """Representation of a file discovered or accessed in Google Drive."""

    id: str
    name: str
    mime_type: str
    size_bytes: int | None = None
    modified_at: str | None = None
    view_url: str | None = None
    download_url: str | None = None
    source: str = "Google Drive"


class DriveSearchResponse(BaseModel):
    """Results of searching files within connected Google Drive."""

    provider: str = "google_drive"
    query: str
    count: int
    files: list[DriveFileItem] = Field(default_factory=list)


class DisconnectResponse(BaseModel):
    """Result of disconnecting an external connector."""

    provider: str
    disconnected: bool
    message: str


class GmailAttachmentItem(BaseModel):
    """Metadata for an email attachment discovered via Gmail search."""

    filename: str
    mime_type: str
    size_bytes: int | None = None
    attachment_id: str | None = None


class GmailMessageItem(BaseModel):
    """Representation of an email discovered in Gmail search results."""

    id: str
    thread_id: str | None = None
    subject: str | None = None
    sender: str | None = None
    to: str | None = None
    date: str | None = None
    snippet: str | None = None
    labels: list[str] = Field(default_factory=list)
    has_attachments: bool = False
    attachments: list[GmailAttachmentItem] = Field(default_factory=list)
    source: str = "Gmail"


class GmailSearchResponse(BaseModel):
    """Results of searching messages within connected Gmail."""

    provider: str = "gmail"
    query: str
    count: int
    messages: list[GmailMessageItem] = Field(default_factory=list)


class OAuthCallbackParams(BaseModel):
    """Query parameters received on OAuth 2.0 callback."""

    code: str | None = None
    state: str | None = None
    error: str | None = None
    error_description: str | None = None
