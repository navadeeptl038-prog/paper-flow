"""Pydantic data models for document chunks and vector search results in PaperFlow AI."""

from __future__ import annotations

import uuid
from typing import Any
from pydantic import BaseModel, Field


class ChunkRecord(BaseModel):
    """Database record for a document chunk with vector embedding."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    document_id: str
    owner_id: str
    chunk_index: int
    content: str
    page_number: int | None = None
    embedding: list[float] | None = None  # 384-dimensional vector
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None


class SearchResult(BaseModel):
    """Vector similarity search match result."""

    id: str
    document_id: str
    owner_id: str
    chunk_index: int
    content: str
    page_number: int | None = None
    similarity: float  # Cosine similarity score [0.0 - 1.0]
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchQuery(BaseModel):
    """Request payload for semantic vector similarity search."""

    query: str = Field(..., min_length=1, description="Natural language search query")
    top_k: int = Field(default=5, ge=1, le=50, description="Maximum number of results to return")
    similarity_threshold: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Minimum cosine similarity cutoff"
    )
    document_id: str | None = Field(
        default=None, description="Optional document UUID to constrain search"
    )


class SearchResponse(BaseModel):
    """Response payload containing matching chunks ordered by similarity."""

    query: str
    results: list[SearchResult]
    total_matches: int
