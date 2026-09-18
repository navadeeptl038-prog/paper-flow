"""Pydantic models for Stage 17 Requirement Checker.

Defines schemas for requirement analysis, matching documents,
and presenting checklists with Present/Missing status.
"""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class MatchedDocumentInfo(BaseModel):
    """Metadata and access links for a matched document."""

    id: str
    filename: str
    source: str = "Local Storage"
    file_type: str | None = None
    view_url: str | None = None
    download_url: str | None = None
    similarity: float | None = None


class RequirementItem(BaseModel):
    """An individual required document item and its fulfillment state."""

    name: str
    status: Literal["present", "missing"] = "missing"
    matched_document: MatchedDocumentInfo | None = None
    duplicates: list[MatchedDocumentInfo] = Field(default_factory=list)
    description: str = ""
    is_mandatory: bool = True


class RequirementChecklistResponse(BaseModel):
    """Comprehensive requirement checklist result for visa and document queries."""

    query: str
    category: str = "visa"
    destination: str | None = None
    purpose: str | None = None
    requires_clarification: bool = False
    clarification_prompt: str | None = None
    disclaimer: str = (
        "Note: These requirements are compiled for guidance based on standard checklists and do not constitute an official government determination. "
        "Please consult the official embassy or consulate website for definitive requirements."
    )
    authoritative_source: str | None = None
    all_present: bool = False
    total_required: int = 0
    present_count: int = 0
    missing_count: int = 0
    items: list[RequirementItem] = Field(default_factory=list)
    summary: str = ""


class RequirementCheckRequest(BaseModel):
    """Request payload for manual requirement verification."""

    query: str
    destination: str | None = None
    purpose: str | None = None
    conversation_id: str | None = None
