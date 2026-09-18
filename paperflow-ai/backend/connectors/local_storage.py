"""Local storage upload connector for PaperFlow AI.

Processes file uploads directly from browser streams to private Supabase Storage
and records metadata in the database without storing files permanently on the local filesystem.
"""

from __future__ import annotations

import logging
import uuid
from typing import BinaryIO

from fastapi import UploadFile

from models.chunk import SearchQuery
from models.document import DocumentCreate, DocumentResponse
from models.search import UnifiedSearchResultItem
from services import vector_service
from storage import document_repository, supabase_storage
from utils.file_utils import build_user_storage_path, compute_sha256, infer_file_type, sanitize_filename
from utils.validators import (
    validate_file_extension,
    validate_file_size,
    validate_filename_security,
    validate_mime_type,
)

logger = logging.getLogger("paperflow.connectors.local")


async def process_file_upload(
    upload_file: UploadFile,
    user_id: str,
    token: str | None = None,
) -> DocumentResponse:
    """Validate, store, and register a user document upload.

    Args:
        upload_file: FastAPI UploadFile from multipart request
        user_id: Authenticated user UUID
        token: Optional user auth Bearer token

    Returns:
        DocumentResponse with processing_status='uploaded' (never 'ready' at Stage 11)
    """
    raw_filename = upload_file.filename or "uploaded_document"

    # 1. Security & format validation
    clean_name = validate_filename_security(raw_filename)
    extension = validate_file_extension(clean_name)
    mime_type = validate_mime_type(upload_file.content_type)

    # 2. Read content in memory (avoid permanent disk writes on Render)
    content = await upload_file.read()
    validate_file_size(len(content))

    # 3. Path construction & hashing
    doc_id = str(uuid.uuid4())
    safe_name = sanitize_filename(clean_name)
    storage_path = build_user_storage_path(user_id, doc_id, safe_name)
    sha256_hash = compute_sha256(content)
    file_type = infer_file_type(extension)

    # 4. Upload to private Supabase Storage
    supabase_storage.upload_document_file(
        storage_path=storage_path,
        data=content,
        mime_type=mime_type,
        token=token,
    )

    # 5. Record metadata in PostgreSQL
    metadata = {
        "file_size_bytes": len(content),
        "mime_type": mime_type,
        "extension": extension,
        "sha256": sha256_hash,
    }

    doc_create = DocumentCreate(
        original_filename=clean_name,
        storage_path=storage_path,
        file_type=file_type,
        file_size_bytes=len(content),
        metadata=metadata,
    )

    saved_doc = document_repository.save_document(
        doc=doc_create,
        owner_id=user_id,
        doc_id=doc_id,
        token=token,
    )

    logger.info("Processed upload for document %s (owner: %s)", saved_doc.id, user_id)
    return saved_doc


async def search_local_storage(
    query: str,
    user_id: str,
    top_k: int = 10,
    similarity_threshold: float = 0.20,
    token: str | None = None,
) -> list[UnifiedSearchResultItem]:
    """Search indexed user documents in Supabase Storage.

    Combines vector semantic search over document chunks with filename keyword matching,
    normalizing results into UnifiedSearchResultItem format.

    Args:
        query: Search keywords or semantic query
        user_id: Authenticated user UUID
        top_k: Max results to return
        similarity_threshold: Minimum vector similarity threshold
        token: User auth Bearer token

    Returns:
        List of UnifiedSearchResultItem objects scoped to Supabase Storage.
    """
    clean_q = query.strip()
    if not clean_q:
        return []

    results_by_doc: dict[str, UnifiedSearchResultItem] = {}

    # 1. Fetch user's indexed documents
    user_docs: list[DocumentResponse] = []
    try:
        user_docs = document_repository.list_user_documents(user_id, token)
    except Exception as exc:
        logger.warning("Failed to list user documents for local search: %s", exc)

    doc_map = {d.id: d for d in user_docs}
    q_words = [w.lower() for w in clean_q.split() if len(w) > 1]

    # 2. Check for filename / title keyword matches
    for doc in user_docs:
        name_lower = doc.original_filename.lower()
        title_lower = (doc.metadata.get("title") or "").lower() if doc.metadata else ""

        match_score = 0.0
        # Exact match
        if clean_q.lower() in name_lower or (title_lower and clean_q.lower() in title_lower):
            match_score = 0.92
        elif q_words:
            matched_words = sum(1 for w in q_words if w in name_lower or w in title_lower)
            if matched_words > 0:
                match_score = 0.60 + 0.30 * (matched_words / len(q_words))

        if match_score >= similarity_threshold:
            # Generate view/download URLs
            signed_url = None
            try:
                signed_url = supabase_storage.create_signed_download_url(
                    storage_path=doc.storage_path,
                    expires_in=3600,
                    token=token,
                )
            except Exception:
                signed_url = f"/api/documents/{doc.id}/download"

            results_by_doc[doc.id] = UnifiedSearchResultItem(
                id=f"supabase_{doc.id}",
                source="Supabase Storage",
                title=doc.original_filename,
                reference=doc.id,
                relevance=round(match_score, 4),
                snippet=f"Document: {doc.original_filename} ({doc.file_type.upper()})",
                metadata={
                    "file_type": doc.file_type,
                    "file_size_bytes": getattr(doc, "file_size_bytes", None) or (doc.metadata.get("file_size_bytes") if doc.metadata else None),
                    "storage_path": doc.storage_path,
                    "created_at": str(doc.created_at),
                },
                authorization_context={
                    "owner_id": user_id,
                    "provider": "supabase_storage",
                    "is_authorized": True,
                },
                view_url=signed_url or f"/api/documents/{doc.id}/view",
                download_url=signed_url or f"/api/documents/{doc.id}/download",
            )

    # 3. Vector semantic search across chunks
    try:
        search_query = SearchQuery(
            query=clean_q,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
        )
        vector_res = await vector_service.search_vectors(
            search_query=search_query,
            user_id=user_id,
            token=token,
        )

        for chunk in vector_res.results:
            doc_id = chunk.document_id
            doc_obj = doc_map.get(doc_id)
            doc_name = doc_obj.original_filename if doc_obj else "Document"
            storage_path = doc_obj.storage_path if doc_obj else ""
            file_type = doc_obj.file_type if doc_obj else "pdf"

            chunk_sim = round(chunk.similarity, 4)

            # Generate URL if not already present
            view_url = f"/api/documents/{doc_id}/view"
            download_url = f"/api/documents/{doc_id}/download"
            if storage_path:
                try:
                    signed_url = supabase_storage.create_signed_download_url(
                        storage_path=storage_path,
                        expires_in=3600,
                        token=token,
                    )
                    if signed_url:
                        view_url = signed_url
                        download_url = signed_url
                except Exception:
                    pass

            if doc_id in results_by_doc:
                # Update existing entry with chunk content if higher relevance or better snippet
                existing = results_by_doc[doc_id]
                if chunk_sim > existing.relevance:
                    existing.relevance = chunk_sim
                existing.snippet = chunk.content.strip()
                existing.metadata["page_number"] = chunk.page_number
                existing.metadata["chunk_index"] = chunk.chunk_index
            else:
                results_by_doc[doc_id] = UnifiedSearchResultItem(
                    id=f"supabase_{chunk.id or doc_id}",
                    source="Supabase Storage",
                    title=doc_name,
                    reference=doc_id,
                    relevance=chunk_sim,
                    snippet=chunk.content.strip(),
                    metadata={
                        "file_type": file_type,
                        "storage_path": storage_path,
                        "page_number": chunk.page_number,
                        "chunk_index": chunk.chunk_index,
                        "created_at": str(doc_obj.created_at) if doc_obj else None,
                    },
                    authorization_context={
                        "owner_id": user_id,
                        "provider": "supabase_storage",
                        "is_authorized": True,
                    },
                    view_url=view_url,
                    download_url=download_url,
                )
    except Exception as exc:
        logger.warning("Local vector search failed: %s", exc)

    sorted_results = sorted(results_by_doc.values(), key=lambda r: r.relevance, reverse=True)
    return sorted_results[:top_k]

