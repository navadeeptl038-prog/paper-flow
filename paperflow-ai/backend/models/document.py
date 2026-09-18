"""Pydantic models for Document metadata and upload management."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class DocumentMetadata(BaseModel):
    """File metadata stored in document JSONB field."""
    file_size_bytes: int
    mime_type: str
    sha256: str | None = None
    extension: str | None = None


class DocumentCreate(BaseModel):
    """Internal model for registering document record."""
    original_filename: str
    storage_path: str
    file_type: str
    file_size_bytes: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentResponse(BaseModel):
    """Public representation of an uploaded document."""
    id: str
    owner_id: str
    original_filename: str
    storage_path: str
    file_type: str
    file_size_bytes: int | None = None
    processing_status: str = Field(default="uploaded", description="'uploaded' or 'pending'. Never 'ready' at Stage 11.")
    source: str = "local_upload"
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | str
    updated_at: datetime | str


class DocumentUploadResponse(BaseModel):
    """Response returned upon file upload."""
    documents: list[DocumentResponse]
    count: int
    message: str = "Documents uploaded successfully."
