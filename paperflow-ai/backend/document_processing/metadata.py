"""Metadata extraction and aggregation helper for PaperFlow AI Stage 12."""

from __future__ import annotations

import datetime
from typing import Any


def build_processing_metadata(
    file_type: str,
    extraction_result: dict[str, Any],
    chunk_count: int,
    original_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Combine file, extraction, and chunking statistics into a unified metadata dictionary."""
    base = dict(original_metadata or {})
    extracted_meta = extraction_result.get("metadata", {})
    text = extraction_result.get("text", "")
    pages = extraction_result.get("pages", [])

    is_scanned = extracted_meta.get("is_scanned", False)
    extraction_method = "ocr" if (file_type == "image" or is_scanned) else "native_text"

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    return {
        **base,
        **extracted_meta,
        "file_type": file_type,
        "extraction_method": extraction_method,
        "page_count": len(pages) if pages else extracted_meta.get("page_count", 1),
        "chunk_count": chunk_count,
        "total_chars": len(text),
        "total_words": len(text.split()) if text else 0,
        "processed_at": now_iso,
    }


def build_error_metadata(
    error_type: str,
    error_message: str,
    original_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construct metadata for a failed document processing run."""
    base = dict(original_metadata or {})
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    return {
        **base,
        "error_type": error_type,
        "error_message": error_message,
        "failed_at": now_iso,
    }
