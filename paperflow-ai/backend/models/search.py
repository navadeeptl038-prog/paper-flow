"""Pydantic models for chat conversations, messages, and search queries."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    """Payload to create a new conversation."""
    title: str | None = Field(default=None, description="Optional title. Defaults to 'New chat' if omitted.")


class ConversationUpdate(BaseModel):
    """Payload to update conversation properties."""
    title: str = Field(..., min_length=1, max_length=200, description="New conversation title.")


class MessageCreate(BaseModel):
    """Payload to append a message to a conversation."""
    content: str = Field(..., min_length=1, description="Message text content.")
    role: str = Field(default="user", description="Sender role: 'user' or 'assistant'.")
    sources: list[dict[str, Any]] | None = Field(default=None, description="Optional document source citations.")


class MessageResponse(BaseModel):
    """Structured representation of a chat message."""
    id: str
    conversation_id: str
    role: str
    content: str
    created_at: datetime | str
    sources: list[dict[str, Any]] | str | None = None


class ConversationResponse(BaseModel):
    """Metadata summary of a conversation for continuous list views."""
    id: str
    owner_id: str
    title: str
    created_at: datetime | str
    updated_at: datetime | str
    last_message: str | None = None


class ConversationDetailResponse(BaseModel):
    """Full conversation including its sequence of messages."""
    id: str
    owner_id: str
    title: str
    created_at: datetime | str
    updated_at: datetime | str
    messages: list[MessageResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Stage 15 & Stage 20 — Information Query & Unified Search Models
# ---------------------------------------------------------------------------


class SearchSource(str, Enum):
    """Supported unified search sources."""
    SUPABASE_STORAGE = "Supabase Storage"
    GOOGLE_DRIVE = "Google Drive"
    GMAIL = "Gmail"


class DocumentSourceMetadata(BaseModel):
    """Source reference with document and page metadata for RAG answers."""

    document_id: str
    filename: str
    source: str = "Supabase Storage"
    page_number: int | None = None
    chunk_index: int | None = None
    similarity: float | None = None
    reference: str | None = None
    metadata: dict[str, Any] | None = None


class FileActionItem(BaseModel):
    """Action item for viewing/downloading an original file (only when explicitly requested)."""

    action_type: str = Field(..., description="Action type: 'view' or 'download'")
    document_id: str
    filename: str
    source: str = "Supabase Storage"
    download_url: str | None = None
    view_url: str | None = None


class UnifiedSearchResultItem(BaseModel):
    """Standardized search result across all sources (Stage 20).

    Preserves source, title/filename, reference, relevance, metadata, and authorization context.
    """

    id: str = Field(..., description="Unique search item ID")
    source: str = Field(..., description="Origin source: 'Supabase Storage', 'Google Drive', 'Gmail'")
    title: str = Field(..., description="Title, filename, or email subject")
    reference: str = Field(..., description="Unique document ID, file ID, or message ID")
    relevance: float = Field(default=0.0, ge=0.0, le=1.0, description="Relevance score (0.0 to 1.0)")
    snippet: str | None = Field(default=None, description="Relevant text snippet or summary excerpt")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Source-specific metadata")
    authorization_context: dict[str, Any] = Field(
        default_factory=dict,
        description="Authorization context (owner_id, provider, account_email, is_authorized)",
    )
    view_url: str | None = Field(default=None, description="Direct or signed view URL")
    download_url: str | None = Field(default=None, description="Direct or signed download URL")
    duplicates: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Other matching duplicate entries across or within sources",
    )


class UnifiedSearchRequest(BaseModel):
    """Payload for submitting a unified search query across sources."""

    query: str = Field(..., min_length=1, description="Search query keywords or question.")
    sources: list[str] | None = Field(
        default=None,
        description="Optional list of sources to search: ['Supabase Storage', 'Google Drive', 'Gmail']. If omitted, automatically determined.",
    )
    top_k: int = Field(default=10, ge=1, le=50, description="Max results to return.")
    similarity_threshold: float = Field(
        default=0.20, ge=0.0, le=1.0, description="Minimum cosine similarity cutoff."
    )


class UnifiedSearchResponse(BaseModel):
    """Response payload for unified source search."""

    query: str
    searched_sources: list[str] = Field(default_factory=list, description="Sources that were queried")
    connected_sources: list[str] = Field(default_factory=list, description="All connected sources for this user")
    failed_sources: dict[str, str] = Field(default_factory=dict, description="Sources that failed and their error messages")
    results: list[UnifiedSearchResultItem] = Field(default_factory=list, description="Ranked, deduplicated results")
    total_count: int = 0
    is_exhaustive: bool = False
    disclaimer: str = (
        "Search results are combined across your authorized sources. "
        "Search across external sources is not guaranteed to be exhaustive."
    )


class InformationQueryRequest(BaseModel):
    """Payload for submitting an Information Query."""

    query: str = Field(..., min_length=1, description="User question or prompt.")
    conversation_id: str | None = Field(default=None, description="Optional conversation UUID to persist messages.")
    document_id: str | None = Field(default=None, description="Optional document UUID constraint.")
    sources: list[str] | None = Field(default=None, description="Optional list of sources to query.")
    top_k: int = Field(default=5, ge=1, le=20, description="Max context chunks to retrieve.")
    similarity_threshold: float = Field(
        default=0.25, ge=0.0, le=1.0, description="Minimum cosine similarity cutoff."
    )


class InformationQueryResponse(BaseModel):
    """Response payload for an Information Query workflow."""

    query: str
    intent: str
    category: str | None = None
    answer: str
    sources: list[DocumentSourceMetadata] = Field(default_factory=list)
    has_found_info: bool = False
    show_file_actions: bool = False
    file_actions: list[FileActionItem] = Field(default_factory=list)
    conversation_id: str | None = None
    message_id: str | None = None
    disclaimer: str = (
        "Answers are grounded strictly in your retrieved documents. "
        "While RAG significantly reduces inaccuracies, it does not eliminate hallucinations completely."
    )


