"""Vector search and similarity service for PaperFlow AI Stage 13.

Provides:
- Embedding generation for document chunks
- Persistence to PostgreSQL pgvector
- Semantic vector similarity search with top-k and threshold filtering
- Strict authenticated user scoping and isolation
"""

from __future__ import annotations

import logging
from typing import Any

from models.chunk import ChunkRecord, SearchQuery, SearchResponse, SearchResult
from services import embedding_service
from storage import document_repository

logger = logging.getLogger("paperflow.vector_service")


async def embed_and_store_chunks(
    document_id: str,
    owner_id: str,
    chunks: list[Any],
    token: str | None = None,
) -> list[ChunkRecord]:
    """Generate 384-d embeddings for document chunks and persist them to PostgreSQL.

    Args:
        document_id: Parent document UUID
        owner_id: Authenticated owner UUID
        chunks: List of DocumentChunk objects
        token: Optional user Bearer token for RLS policies

    Returns:
        List of created ChunkRecord instances with embeddings.
    """
    if not chunks:
        return []

    texts = [getattr(c, "content", "") for c in chunks]

    # Use the canonical embedding API defined by the service instead of ad-hoc direct calls.
    embeddings = await embedding_service.get_document_embeddings(texts)

    # 3. Assemble chunk records
    chunk_records: list[ChunkRecord] = []
    for idx, c in enumerate(chunks):
        chunk_id = getattr(c, "id", None)
        page_num = getattr(c, "page_number", None)
        content = getattr(c, "content", "")
        meta = getattr(c, "metadata", {}) or {}

        record = ChunkRecord(
            id=chunk_id or f"chunk-{document_id}-{idx}",
            document_id=document_id,
            owner_id=owner_id,
            chunk_index=idx,
            content=content,
            page_number=page_num,
            embedding=embeddings[idx],
            metadata=meta,
        )
        chunk_records.append(record)

    # 4. Persist to database / repository
    saved_records = document_repository.save_document_chunks(
        chunks=chunk_records,
        owner_id=owner_id,
        token=token,
    )

    logger.info(
        "Embedded and stored %d chunks for document %s (owner: %s)",
        len(saved_records),
        document_id,
        owner_id,
    )
    return saved_records


async def search_vectors(
    search_query: SearchQuery,
    user_id: str,
    token: str | None = None,
) -> SearchResponse:
    """Execute semantic vector similarity search against the user's document chunks.

    Strict security guarantees:
    - Scoped strictly to `owner_id == user_id`.
    - User A can NEVER retrieve User B's chunks or vectors.

    Args:
        search_query: Query parameters (query, top_k, similarity_threshold, document_id)
        user_id: Authenticated user UUID
        token: User auth token for Supabase client

    Returns:
        SearchResponse with sorted SearchResult objects.
    """
    query_text = search_query.query.strip()
    if not query_text:
        return SearchResponse(query=query_text, results=[], total_matches=0)

    # 1. Generate query embedding (384-dimension)
    query_embedding = embedding_service.generate_embedding(query_text)

    # 2. Execute similarity search in repository / pgvector
    matches = document_repository.search_vector_chunks(
        query_embedding=query_embedding,
        owner_id=user_id,
        top_k=search_query.top_k,
        threshold=search_query.similarity_threshold,
        document_id=search_query.document_id,
        token=token,
    )

    return SearchResponse(
        query=query_text,
        results=matches,
        total_matches=len(matches),
    )
