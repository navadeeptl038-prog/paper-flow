"""Retrieval and Unified Search service for PaperFlow AI (Stage 14 & Stage 20).

Coordinates:
- Unified search across Supabase Storage, Google Drive, and Gmail
- Deduplication and relevance ranking
- Grounded context assembly for RAG
"""

from __future__ import annotations

import logging
import re
from typing import Any
from pydantic import BaseModel, Field

from connectors import gmail, google_drive, local_storage
from models.chunk import SearchQuery, SearchResult
from models.search import (
    UnifiedSearchRequest,
    UnifiedSearchResponse,
    UnifiedSearchResultItem,
)
from services import intent_service, vector_service
from storage import connector_repository, document_repository

logger = logging.getLogger("paperflow.retrieval_service")


class SourceReference(BaseModel):
    """Source citation reference for RAG answer grounding."""

    document_id: str
    filename: str
    source: str = "Supabase Storage"
    page_number: int | None = None
    chunk_index: int = 0
    similarity: float = 0.0
    reference: str | None = None
    metadata: dict[str, Any] | None = None


class RetrievalResult(BaseModel):
    """Result of vector retrieval and grounded context assembly."""

    query: str
    chunks: list[SearchResult] = Field(default_factory=list)
    grounded_context: str
    source_references: list[SourceReference] = Field(default_factory=list)
    has_relevant_context: bool = False
    searched_sources: list[str] = Field(default_factory=list)
    failed_sources: dict[str, str] = Field(default_factory=dict)



def normalize_title_for_dedup(title: str) -> str:
    """Normalize a title/filename for duplicate detection across and within sources."""
    t = re.sub(r"^(email:\s*|document:\s*)", "", title, flags=re.IGNORECASE)
    t = re.sub(r"\.(pdf|docx|png|jpg|jpeg|webp|txt)$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"[^a-zA-Z0-9]", "", t).lower().strip()
    return t


def deduplicate_and_rank(
    items: list[UnifiedSearchResultItem],
    top_k: int = 10,
) -> list[UnifiedSearchResultItem]:
    """Deduplicate results across sources and rank by relevance descending.

    If matching documents/files are found (e.g. same normalized title across Supabase Storage
    and Google Drive), the higher-relevance item is retained as primary, and the other is
    recorded under `primary.duplicates`.
    """
    if not items:
        return []

    # Sort descending by relevance
    sorted_items = sorted(items, key=lambda x: x.relevance, reverse=True)

    deduped: list[UnifiedSearchResultItem] = []
    seen_keys: dict[str, UnifiedSearchResultItem] = {}

    for item in sorted_items:
        norm_key = normalize_title_for_dedup(item.title)
        if not norm_key:
            norm_key = item.reference

        if norm_key in seen_keys:
            primary = seen_keys[norm_key]
            # Record duplicate reference
            primary.duplicates.append({
                "id": item.id,
                "source": item.source,
                "title": item.title,
                "reference": item.reference,
                "relevance": item.relevance,
                "view_url": item.view_url,
                "download_url": item.download_url,
                "metadata": item.metadata,
            })
        else:
            seen_keys[norm_key] = item
            deduped.append(item)

    return deduped[:top_k]


async def execute_unified_search(
    request: UnifiedSearchRequest,
    user_id: str,
    token: str | None = None,
) -> UnifiedSearchResponse:
    """Execute unified search across all authorized and requested sources.

    Sources supported:
    1. Supabase Storage indexed documents
    2. Google Drive
    3. Gmail

    Flow:
    User query
    → intent detection & determine required sources
    → search authorized sources
    → normalize results
    → rank & deduplicate
    → return UnifiedSearchResponse
    """
    clean_q = request.query.strip()
    if not clean_q:
        return UnifiedSearchResponse(
            query=request.query,
            searched_sources=[],
            connected_sources=["Supabase Storage"],
            results=[],
            total_count=0,
            is_exhaustive=False,
        )

    # 1. Determine connected sources for this user
    connected_sources = ["Supabase Storage"]
    drive_conn = connector_repository.get_connector(user_id, "google_drive", token=token)
    if drive_conn and drive_conn.get("status") == "connected":
        connected_sources.append("Google Drive")

    gmail_conn = connector_repository.get_connector(user_id, "gmail", token=token)
    if gmail_conn and gmail_conn.get("status") == "connected":
        connected_sources.append("Gmail")

    # 2. Determine required sources
    requested_sources: list[str] = []
    if request.sources:
        for s in request.sources:
            s_clean = s.strip()
            s_lower = s_clean.lower()
            if "drive" in s_lower:
                requested_sources.append("Google Drive")
            elif "gmail" in s_lower or "email" in s_lower:
                requested_sources.append("Gmail")
            elif "supabase" in s_lower or "local" in s_lower:
                requested_sources.append("Supabase Storage")
            else:
                requested_sources.append(s_clean)
    else:
        intent_res = intent_service.detect_intent(clean_q)
        if intent_res.target_sources:
            requested_sources = intent_res.target_sources
        else:
            requested_sources = list(connected_sources)

    # 3. Search authorized sources
    searched_sources: list[str] = []
    failed_sources: dict[str, str] = {}
    collected_results: list[UnifiedSearchResultItem] = []

    for src in requested_sources:
        if src == "Supabase Storage":
            searched_sources.append("Supabase Storage")
            try:
                local_results = await local_storage.search_local_storage(
                    query=clean_q,
                    user_id=user_id,
                    top_k=request.top_k,
                    similarity_threshold=request.similarity_threshold,
                    token=token,
                )
                collected_results.extend(local_results)
            except Exception as exc:
                logger.warning("Supabase Storage search failed: %s", exc)
                failed_sources["Supabase Storage"] = str(exc)

        elif src == "Google Drive":
            if "Google Drive" not in connected_sources:
                failed_sources["Google Drive"] = "Google Drive is not connected."
                continue

            searched_sources.append("Google Drive")
            try:
                drive_results = await google_drive.search_user_drive(
                    query=clean_q,
                    user_id=user_id,
                    top_k=request.top_k,
                    token=token,
                )
                collected_results.extend(drive_results)
            except Exception as exc:
                logger.warning("Google Drive search failed: %s", exc)
                failed_sources["Google Drive"] = str(exc)

        elif src == "Gmail":
            if "Gmail" not in connected_sources:
                failed_sources["Gmail"] = "Gmail is not connected."
                continue

            searched_sources.append("Gmail")
            try:
                gmail_results = await gmail.search_user_gmail(
                    query=clean_q,
                    user_id=user_id,
                    top_k=request.top_k,
                    token=token,
                )
                collected_results.extend(gmail_results)
            except Exception as exc:
                logger.warning("Gmail search failed: %s", exc)
                failed_sources["Gmail"] = str(exc)

    # 4. Deduplicate and rank results
    final_results = deduplicate_and_rank(collected_results, top_k=request.top_k)

    return UnifiedSearchResponse(
        query=clean_q,
        searched_sources=searched_sources,
        connected_sources=connected_sources,
        failed_sources=failed_sources,
        results=final_results,
        total_count=len(final_results),
        is_exhaustive=False,
        disclaimer=(
            "Search results are combined across your authorized sources. "
            "Search across external sources is not guaranteed to be exhaustive."
        ),
    )


async def retrieve_context(
    query: str,
    user_id: str,
    top_k: int = 5,
    similarity_threshold: float = 0.25,
    document_id: str | None = None,
    target_document_hint: str | None = None,
    token: str | None = None,
    sources: list[str] | None = None,
    include_external: bool = True,
) -> RetrievalResult:
    """Retrieve relevant chunks and assemble grounded context for LLM prompt.

    Supports local vector search and seamlessly incorporates external connected sources
    (Google Drive, Gmail) into grounded context when available.

    Args:
        query: User question
        user_id: Authenticated user UUID (strict isolation)
        top_k: Maximum chunks to retrieve
        similarity_threshold: Minimum cosine similarity cutoff
        document_id: Optional filter for a specific document
        target_document_hint: Optional keyword/topic hint to match document names
        token: User auth token
        sources: Optional list of sources to constrain retrieval to
        include_external: Whether to include authorized external connectors

    Returns:
        RetrievalResult containing chunks, formatted grounded context, and source references.
    """
    clean_query = query.strip()
    if not clean_query:
        return RetrievalResult(
            query=query,
            chunks=[],
            grounded_context="",
            source_references=[],
            has_relevant_context=False,
            searched_sources=[],
            failed_sources={},
        )

    effective_doc_id = document_id
    searched_sources = ["Supabase Storage"]
    failed_sources: dict[str, str] = {}

    # If document_id is unset but target_document_hint is given, look for matching document
    if not effective_doc_id and target_document_hint:
        try:
            user_docs = document_repository.list_user_documents(user_id, token)
            hint_clean = target_document_hint.lower().replace(" ", "")
            hint_alts = [
                hint_clean,
                hint_clean.replace("chapter", "ch"),
                hint_clean.replace("ch", "chapter"),
            ]
            for d in user_docs:
                doc_name = d.original_filename.lower().replace(" ", "").replace("_", "").replace("-", "")
                meta_title = (
                    (d.metadata.get("title") or "").lower().replace(" ", "").replace("_", "").replace("-", "")
                    if d.metadata
                    else ""
                )
                if any(alt in doc_name or alt in meta_title for alt in hint_alts):
                    effective_doc_id = d.id
                    break
        except Exception:
            pass

    # 1. Search vector database for user's chunks
    chunks: list[SearchResult] = []
    try:
        search_query = SearchQuery(
            query=clean_query,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
            document_id=effective_doc_id,
        )

        search_response = await vector_service.search_vectors(
            search_query=search_query,
            user_id=user_id,
            token=token,
        )
        chunks = search_response.results

        # Fallback to unscoped search if scoped search yielded no chunks
        if not chunks and effective_doc_id and not document_id:
            search_query.document_id = None
            search_response = await vector_service.search_vectors(
                search_query=search_query,
                user_id=user_id,
                token=token,
            )
            chunks = search_response.results
    except Exception as exc:
        logger.warning("Vector search in retrieve_context failed: %s", exc)
        failed_sources["Supabase Storage"] = str(exc)

    # 2. Build references & fetch document filenames for clean citations
    doc_cache: dict[str, str] = {}
    source_refs: list[SourceReference] = []
    context_blocks: list[str] = []

    for c in chunks:
        doc_name = doc_cache.get(c.document_id)
        if not doc_name:
            doc_obj = document_repository.get_document_by_id(c.document_id, user_id, token)
            doc_name = doc_obj.original_filename if doc_obj else "Document"
            doc_cache[c.document_id] = doc_name

        page_str = f"Page {c.page_number}" if c.page_number else "Section"
        ref_header = f"[Supabase Storage | {doc_name} | {page_str} | Chunk {c.chunk_index}]"

        context_blocks.append(f"{ref_header}\n{c.content.strip()}")

        source_refs.append(
            SourceReference(
                document_id=c.document_id,
                filename=doc_name,
                source="Supabase Storage",
                page_number=c.page_number,
                chunk_index=c.chunk_index,
                similarity=round(c.similarity, 4),
                reference=c.document_id,
            )
        )

    # 3. Retrieve from external sources if applicable (and document_id was not explicitly forced)
    if include_external and not document_id:
        try:
            # Check which external sources are connected or requested
            ext_sources = []
            if sources:
                for s in sources:
                    if "drive" in s.lower():
                        ext_sources.append("Google Drive")
                    elif "gmail" in s.lower() or "email" in s.lower():
                        ext_sources.append("Gmail")
            else:
                # Check connected status
                drive_conn = connector_repository.get_connector(user_id, "google_drive", token=token)
                if drive_conn and drive_conn.get("status") == "connected":
                    ext_sources.append("Google Drive")
                gmail_conn = connector_repository.get_connector(user_id, "gmail", token=token)
                if gmail_conn and gmail_conn.get("status") == "connected":
                    ext_sources.append("Gmail")

            if ext_sources:
                ext_req = UnifiedSearchRequest(
                    query=clean_query,
                    sources=ext_sources,
                    top_k=top_k,
                    similarity_threshold=similarity_threshold,
                )
                ext_res = await execute_unified_search(ext_req, user_id=user_id, token=token)
                searched_sources.extend(ext_res.searched_sources)
                failed_sources.update(ext_res.failed_sources)

                for item in ext_res.results:
                    header = f"[{item.source} | {item.title}]"
                    body = item.snippet or item.title
                    context_blocks.append(f"{header}\n{body.strip()}")
                    source_refs.append(
                        SourceReference(
                            document_id=item.reference,
                            filename=item.title,
                            source=item.source,
                            page_number=item.metadata.get("page_number"),
                            chunk_index=0,
                            similarity=round(item.relevance, 4),
                            reference=item.reference,
                            metadata=item.metadata,
                        )
                    )
        except Exception as exc:
            logger.warning("External retrieval in retrieve_context failed: %s", exc)

    grounded_context = "\n\n---\n\n".join(context_blocks)

    return RetrievalResult(
        query=clean_query,
        chunks=chunks,
        grounded_context=grounded_context,
        source_references=source_refs,
        has_relevant_context=len(source_refs) > 0,
        searched_sources=searched_sources,
        failed_sources=failed_sources,
    )


async def find_authoritative_requirement_source(
    category: str,
    destination: str | None,
    user_id: str,
    token: str | None = None,
) -> str | None:
    """Check for authoritative requirement sources or official checklists stored in user documents."""
    search_terms = [
        f"{destination} visa checklist" if destination else "visa checklist",
        "visa requirements",
        "embassy guidelines",
    ]
    for term in search_terms:
        try:
            result = await retrieve_context(
                query=term,
                user_id=user_id,
                top_k=2,
                similarity_threshold=0.35,
                token=token,
            )
            if result.has_relevant_context and result.source_references:
                top_ref = result.source_references[0]
                fname_lower = top_ref.filename.lower()
                if any(
                    k in fname_lower
                    for k in ["checklist", "guideline", "embassy", "consulate", "vfs", "official", "requirement"]
                ):
                    return f"User Document Reference: {top_ref.filename}"
        except Exception:
            pass

    return None

