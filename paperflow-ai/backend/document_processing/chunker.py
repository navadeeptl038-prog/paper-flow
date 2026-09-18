"""Text chunker for PaperFlow AI Stage 12.

Splits document text into clean, contextual chunks while strictly preserving:
- document_id
- chunk order (chunk_index)
- source metadata
- page number when available

Embeddings are NOT generated at this stage.
"""

from __future__ import annotations

import re
import uuid
from typing import Any
from pydantic import BaseModel, Field


class DocumentChunk(BaseModel):
    """Represents an indexed chunk of document text."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    document_id: str
    chunk_index: int
    content: str
    page_number: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def split_text_into_chunks(
    text: str,
    max_chunk_size: int = 600,
    chunk_overlap: int = 100,
) -> list[str]:
    """Split a continuous text string into overlapping chunks, respecting paragraphs and sentence boundaries."""
    text = text.strip()
    if not text:
        return []

    if len(text) <= max_chunk_size:
        return [text]

    # Split into paragraphs first
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        paragraphs = [text]

    chunks: list[str] = []
    current_chunk: list[str] = []
    current_len = 0

    for para in paragraphs:
        # If single paragraph exceeds max size, split by sentences
        if len(para) > max_chunk_size:
            sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", para) if s.strip()]
            for sent in sentences:
                if current_len + len(sent) + 1 > max_chunk_size and current_chunk:
                    chunks.append(" ".join(current_chunk))
                    # Overlap: keep trailing words
                    overlap_text = current_chunk[-1] if current_chunk else ""
                    current_chunk = [overlap_text, sent] if len(overlap_text) < chunk_overlap else [sent]
                    current_len = sum(len(x) + 1 for x in current_chunk)
                else:
                    current_chunk.append(sent)
                    current_len += len(sent) + 1
        else:
            if current_len + len(para) + 2 > max_chunk_size and current_chunk:
                chunks.append("\n\n".join(current_chunk))
                overlap_para = current_chunk[-1] if current_chunk else ""
                current_chunk = [overlap_para, para] if len(overlap_para) < chunk_overlap else [para]
                current_len = sum(len(x) + 2 for x in current_chunk)
            else:
                current_chunk.append(para)
                current_len += len(para) + 2

    if current_chunk:
        chunk_str = "\n\n".join(current_chunk).strip()
        if chunk_str and (not chunks or chunk_str != chunks[-1]):
            chunks.append(chunk_str)

    return chunks


def chunk_document(
    document_id: str,
    pages: list[dict[str, Any]] | None = None,
    full_text: str | None = None,
    source_metadata: dict[str, Any] | None = None,
    chunk_size: int = 600,
    chunk_overlap: int = 100,
) -> list[DocumentChunk]:
    """Create ordered chunks for a document, preserving page numbers and source metadata.

    Args:
        document_id: UUID of the parent document.
        pages: Optional list of page dicts [{"page": int, "text": str}].
        full_text: Fallback raw text if page structure is unavailable.
        source_metadata: Base metadata to attach to every chunk.
        chunk_size: Target character length per chunk.
        chunk_overlap: Overlap characters between consecutive chunks.

    Returns:
        List of DocumentChunk instances with strictly sequential chunk_index.
    """
    base_meta = dict(source_metadata or {})
    chunks: list[DocumentChunk] = []
    chunk_order = 0

    if pages and len(pages) > 0:
        for page_obj in pages:
            p_num = page_obj.get("page")
            p_text = (page_obj.get("text") or "").strip()
            if not p_text:
                continue

            page_chunks = split_text_into_chunks(
                text=p_text,
                max_chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )

            for chunk_content in page_chunks:
                chunk_meta = {
                    **base_meta,
                    "page_number": p_num,
                    "chunk_index": chunk_order,
                    "char_count": len(chunk_content),
                    "word_count": len(chunk_content.split()),
                }
                chunks.append(
                    DocumentChunk(
                        document_id=document_id,
                        chunk_index=chunk_order,
                        content=chunk_content,
                        page_number=p_num,
                        metadata=chunk_meta,
                    )
                )
                chunk_order += 1
    elif full_text and full_text.strip():
        text_chunks = split_text_into_chunks(
            text=full_text,
            max_chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        for chunk_content in text_chunks:
            chunk_meta = {
                **base_meta,
                "chunk_index": chunk_order,
                "char_count": len(chunk_content),
                "word_count": len(chunk_content.split()),
            }
            chunks.append(
                DocumentChunk(
                    document_id=document_id,
                    chunk_index=chunk_order,
                    content=chunk_content,
                    page_number=None,
                    metadata=chunk_meta,
                )
            )
            chunk_order += 1

    return chunks
