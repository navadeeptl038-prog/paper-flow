"""Repository for persisting and querying document metadata and chunks in PostgreSQL."""

from __future__ import annotations

import datetime
import logging
import uuid
from typing import Any

from models.chunk import ChunkRecord, SearchResult
from models.document import DocumentCreate, DocumentResponse
from services.supabase_client import get_supabase_client
from utils import security

logger = logging.getLogger("paperflow.documents.repo")

# User-isolated fallback store for test environments
# Structure: dict[owner_id, dict[doc_id, doc_dict]]
_mem_documents: dict[str, dict[str, Any]] = {}

# User-isolated chunks fallback store: dict[owner_id, dict[chunk_id, ChunkRecord]]
_mem_chunks: dict[str, dict[str, ChunkRecord]] = {}


def _cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = sum(a * a for a in v1) ** 0.5
    norm2 = sum(b * b for b in v2) ** 0.5
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return dot / (norm1 * norm2)


def save_document(
    doc: DocumentCreate,
    owner_id: str,
    doc_id: str | None = None,
    token: str | None = None,
) -> DocumentResponse:
    """Save a document record to the database under the authenticated owner."""
    document_uuid = doc_id or str(uuid.uuid4())
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    row_data = {
        "id": document_uuid,
        "owner_id": owner_id,
        "original_filename": doc.original_filename,
        "storage_path": doc.storage_path,
        "file_type": doc.file_type,
        "processing_status": "uploaded",
        "source": "local_upload",
        "metadata": doc.metadata,
        "created_at": now_iso,
        "updated_at": now_iso,
    }

    try:
        client = get_supabase_client()
        if token:
            try:
                client.postgrest.auth(token)
            except Exception:
                pass

        res = client.table("documents").insert(row_data).execute()
        if res.data:
            r = res.data[0]
            return DocumentResponse(
                id=str(r["id"]),
                owner_id=str(r["owner_id"]),
                original_filename=r["original_filename"],
                storage_path=r["storage_path"],
                file_type=r["file_type"],
                processing_status=r.get("processing_status") or "uploaded",
                source=r.get("source") or "local_upload",
                metadata=r.get("metadata") or {},
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
    except Exception as exc:
        logger.warning(
            "Database insert failed for document %s (%s). Using isolated memory store.",
            document_uuid,
            exc,
        )

    if owner_id not in _mem_documents:
        _mem_documents[owner_id] = {}
    _mem_documents[owner_id][document_uuid] = row_data

    return DocumentResponse(**row_data)


def get_document_by_id(
    doc_id: str,
    owner_id: str,
    token: str | None = None,
) -> DocumentResponse | None:
    """Retrieve document metadata by ID, strictly enforcing owner_id."""
    try:
        client = get_supabase_client()
        if token:
            try:
                client.postgrest.auth(token)
            except Exception:
                pass

        res = (
            client.table("documents")
            .select("*")
            .eq("id", doc_id)
            .eq("owner_id", owner_id)
            .limit(1)
            .execute()
        )
        if res.data:
            r = res.data[0]
            return DocumentResponse(
                id=str(r["id"]),
                owner_id=str(r["owner_id"]),
                original_filename=r["original_filename"],
                storage_path=r["storage_path"],
                file_type=r["file_type"],
                processing_status=r.get("processing_status") or "uploaded",
                source=r.get("source") or "local_upload",
                metadata=r.get("metadata") or {},
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
    except Exception:
        pass

    user_docs = _mem_documents.get(owner_id, {})
    doc_dict = user_docs.get(doc_id)
    if doc_dict:
        return DocumentResponse(**doc_dict)

    return None


def get_document_any_owner(
    doc_id: str,
) -> DocumentResponse | None:
    """Retrieve document metadata by ID across users for ownership validation.

    Never expose the returned document directly to an unauthorized caller.
    """
    try:
        client = get_supabase_client()
        res = client.table("documents").select("*").eq("id", doc_id).limit(1).execute()
        if res.data:
            r = res.data[0]
            return DocumentResponse(
                id=str(r["id"]),
                owner_id=str(r["owner_id"]),
                original_filename=r["original_filename"],
                storage_path=r["storage_path"],
                file_type=r["file_type"],
                processing_status=r.get("processing_status") or "uploaded",
                source=r.get("source") or "local_upload",
                metadata=r.get("metadata") or {},
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
    except Exception:
        pass

    for _, docs in _mem_documents.items():
        if doc_id in docs:
            return DocumentResponse(**docs[doc_id])

    return None


def list_user_documents(
    owner_id: str,
    token: str | None = None,
) -> list[DocumentResponse]:
    """List all documents for an owner, newest first."""
    db_docs = []
    try:
        client = get_supabase_client()
        if token:
            try:
                client.postgrest.auth(token)
            except Exception:
                pass

        res = (
            client.table("documents")
            .select("*")
            .eq("owner_id", owner_id)
            .order("created_at", desc=True)
            .execute()
        )
        db_docs = res.data or []
    except Exception:
        pass

    # Merge with memory-isolated store
    user_mem = _mem_documents.get(owner_id, {})
    all_map: dict[str, dict[str, Any]] = {d["id"]: d for d in db_docs}
    for did, ddata in user_mem.items():
        if did not in all_map:
            all_map[did] = ddata

    sorted_docs = sorted(
        all_map.values(),
        key=lambda d: str(d.get("created_at") or ""),
        reverse=True,
    )

    return [
        DocumentResponse(
            id=str(r["id"]),
            owner_id=str(r["owner_id"]),
            original_filename=r["original_filename"],
            storage_path=r["storage_path"],
            file_type=r["file_type"],
            processing_status=r.get("processing_status") or "uploaded",
            source=r.get("source") or "local_upload",
            metadata=r.get("metadata") or {},
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )
        for r in sorted_docs
    ]


def delete_document(
    doc_id: str,
    owner_id: str,
    token: str | None = None,
) -> bool:
    """Delete a document record, strictly enforcing owner_id."""
    deleted = False
    try:
        client = get_supabase_client()
        if token:
            try:
                client.postgrest.auth(token)
            except Exception:
                pass

        res = (
            client.table("documents")
            .delete()
            .eq("id", doc_id)
            .eq("owner_id", owner_id)
            .execute()
        )
        if res.data:
            deleted = True
    except Exception:
        pass

    user_docs = _mem_documents.get(owner_id, {})
    if doc_id in user_docs:
        del user_docs[doc_id]
        deleted = True

    # Also remove chunks
    user_chunks = _mem_chunks.get(owner_id, {})
    to_delete = [cid for cid, c in user_chunks.items() if c.document_id == doc_id]
    for cid in to_delete:
        del user_chunks[cid]

    return deleted


# ---------------------------------------------------------------------------
# Document Chunks & Vector Search Persistence
# ---------------------------------------------------------------------------

def save_document_chunks(
    chunks: list[ChunkRecord],
    owner_id: str,
    token: str | None = None,
) -> list[ChunkRecord]:
    """Persist document chunks with 384-d embeddings to PostgreSQL pgvector and fallback cache."""
    if not chunks:
        return []

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    rows = []
    for c in chunks:
        # Neutralize prompt injection attempts embedded within document text
        sanitized_content = security.sanitize_document_text_for_llm(c.content)
        c.content = sanitized_content
        row = {
            "id": c.id,
            "document_id": c.document_id,
            "owner_id": owner_id,
            "chunk_index": c.chunk_index,
            "content": sanitized_content,
            "page_number": c.page_number,
            "embedding": c.embedding,
            "metadata": c.metadata,
            "created_at": c.created_at or now_iso,
            "updated_at": now_iso,
        }
        rows.append(row)

    # 1. Attempt PostgreSQL insert via Supabase
    try:
        client = get_supabase_client()
        if token:
            try:
                client.postgrest.auth(token)
            except Exception:
                pass

        res = client.table("document_chunks").insert(rows).execute()
        if res.data:
            saved = []
            for r in res.data:
                saved.append(ChunkRecord(**r))
            return saved
    except Exception as exc:
        logger.debug("Database insert into document_chunks skipped/failed: %s", exc)

    # 2. In-memory user-isolated fallback
    if owner_id not in _mem_chunks:
        _mem_chunks[owner_id] = {}

    for c in chunks:
        c.owner_id = owner_id
        c.created_at = c.created_at or now_iso
        c.updated_at = now_iso
        _mem_chunks[owner_id][c.id] = c

    return chunks


def get_document_chunks_by_doc(
    document_id: str,
    owner_id: str,
    token: str | None = None,
) -> list[ChunkRecord]:
    """Retrieve all chunks belonging to a document under owner_id, ordered by chunk_index."""
    try:
        client = get_supabase_client()
        if token:
            try:
                client.postgrest.auth(token)
            except Exception:
                pass

        res = (
            client.table("document_chunks")
            .select("*")
            .eq("document_id", document_id)
            .eq("owner_id", owner_id)
            .order("chunk_index", desc=False)
            .execute()
        )
        if res.data:
            return [ChunkRecord(**r) for r in res.data]
    except Exception:
        pass

    user_chunks = _mem_chunks.get(owner_id, {})
    doc_chunks = [c for c in user_chunks.values() if c.document_id == document_id]
    doc_chunks.sort(key=lambda c: c.chunk_index)
    return doc_chunks


def search_vector_chunks(
    query_embedding: list[float],
    owner_id: str,
    top_k: int = 5,
    threshold: float = 0.0,
    document_id: str | None = None,
    token: str | None = None,
) -> list[SearchResult]:
    """Execute vector similarity search strictly scoped to owner_id.

    User isolation is enforced at both SQL function and fallback levels.
    """
    # 1. Attempt pgvector RPC search in Supabase
    try:
        client = get_supabase_client()
        if token:
            try:
                client.postgrest.auth(token)
            except Exception:
                pass

        params = {
            "query_embedding": query_embedding,
            "match_threshold": float(threshold),
            "match_count": int(top_k),
            "filter_owner_id": owner_id,
        }
        res = client.rpc("match_document_chunks", params).execute()
        if res.data:
            results = []
            for r in res.data:
                if document_id and str(r.get("document_id")) != document_id:
                    continue
                results.append(
                    SearchResult(
                        id=str(r["id"]),
                        document_id=str(r["document_id"]),
                        owner_id=str(r["owner_id"]),
                        chunk_index=int(r["chunk_index"]),
                        content=str(r["content"]),
                        page_number=r.get("page_number"),
                        similarity=float(r["similarity"]),
                        metadata=r.get("metadata") or {},
                    )
                )
            return results
    except Exception as exc:
        logger.debug("pgvector RPC match_document_chunks skipped/failed: %s", exc)

    # 2. In-memory user-isolated fallback search
    user_chunks = _mem_chunks.get(owner_id, {})
    scored_results: list[SearchResult] = []

    for chunk in user_chunks.values():
        # User ownership verification
        if chunk.owner_id != owner_id:
            continue
        # Optional document filter
        if document_id and chunk.document_id != document_id:
            continue
        if not chunk.embedding:
            continue

        sim = _cosine_similarity(query_embedding, chunk.embedding)
        if sim >= threshold:
            scored_results.append(
                SearchResult(
                    id=chunk.id,
                    document_id=chunk.document_id,
                    owner_id=chunk.owner_id,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    page_number=chunk.page_number,
                    similarity=round(sim, 4),
                    metadata=chunk.metadata,
                )
            )

    # Sort descending by similarity
    scored_results.sort(key=lambda x: x.similarity, reverse=True)
    return scored_results[:top_k]


def search_documents_by_keyword(
    owner_id: str,
    query: str,
    target_hint: str | None = None,
    token: str | None = None,
) -> list[DocumentResponse]:
    """Search documents owned by owner_id matching query terms or target hint.

    Strictly enforces user isolation: never returns documents of another user.

    Args:
        owner_id: Authenticated user ID.
        query: Raw query or search terms.
        target_hint: Optional extracted document entity hint (e.g. 'passport', 'atm card').
        token: Optional user Bearer token.

    Returns:
        List of matching DocumentResponse objects sorted by relevance.
    """
    import re

    # 1. Fetch user documents (already scoped to owner_id)
    user_docs = list_user_documents(owner_id=owner_id, token=token)
    if not user_docs:
        return []

    # Stopwords to filter out from query
    stop_words = {
        "find", "my", "the", "where", "is", "locate", "show", "get", "give", "me",
        "please", "a", "an", "this", "that", "original", "copy", "i", "need", "to",
        "can", "you", "view", "download", "open", "file", "document",
    }

    clean_text = re.sub(r"[^a-zA-Z0-9\s_-]", " ", query.lower()).strip()
    raw_tokens = clean_text.split()
    tokens = [t for t in raw_tokens if t not in stop_words and len(t) >= 2]

    hint_clean = target_hint.lower().strip() if target_hint else None

    scored_docs: list[tuple[float, DocumentResponse]] = []

    for doc in user_docs:
        score = 0.0
        fname_lower = (doc.original_filename or "").lower()
        meta_str = str(doc.metadata or {}).lower()

        # 1. Exact match with target hint
        if hint_clean:
            if hint_clean in fname_lower:
                score += 15.0
            elif all(h in fname_lower for h in hint_clean.split()):
                score += 10.0
            elif any(h in fname_lower for h in hint_clean.split() if len(h) >= 3):
                score += 5.0

            if hint_clean in meta_str:
                score += 5.0

        # 2. Token matches in filename
        for token_item in tokens:
            if token_item in fname_lower:
                score += 6.0
            elif token_item in meta_str:
                score += 2.0

        # 3. Check chunks content if score is still 0
        if score == 0:
            user_chunks = get_document_chunks_by_doc(doc.id, owner_id, token)
            for chunk in user_chunks:
                chunk_text = (chunk.content or "").lower()
                if hint_clean and hint_clean in chunk_text:
                    score += 4.0
                    break
                for token_item in tokens:
                    if len(token_item) >= 3 and token_item in chunk_text:
                        score += 2.0
                        break
                if score > 0:
                    break

        if score > 0:
            scored_docs.append((score, doc))

    # Sort descending by score
    scored_docs.sort(key=lambda x: x[0], reverse=True)
    return [doc for _, doc in scored_docs]
