-- PaperFlow AI — Vector Similarity Search RPC
-- 004_vector_search.sql

-- Match document chunks function for semantic vector search
CREATE OR REPLACE FUNCTION match_document_chunks(
    query_embedding vector(384),
    match_threshold float DEFAULT 0.0,
    match_count int DEFAULT 5,
    filter_owner_id uuid DEFAULT NULL
)
RETURNS TABLE (
    id uuid,
    document_id uuid,
    owner_id uuid,
    chunk_index int,
    content text,
    page_number int,
    similarity float,
    metadata jsonb
)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    target_owner_id uuid;
BEGIN
    -- Strict security: Always verify user identity against auth.uid()
    -- If called by an authenticated user, ALWAYS bind search to auth.uid()
    -- to prevent client-provided filter_owner_id manipulation
    IF auth.uid() IS NOT NULL THEN
        target_owner_id := auth.uid();
    ELSIF auth.role() = 'service_role' THEN
        target_owner_id := filter_owner_id;
    ELSE
        RAISE EXCEPTION 'Authentication required for vector search.';
    END IF;

    IF target_owner_id IS NULL THEN
        RAISE EXCEPTION 'Target user ID is required for vector search.';
    END IF;

    -- Return top-k matching chunks exceeding the similarity threshold
    RETURN QUERY
    SELECT
        dc.id,
        dc.document_id,
        dc.owner_id,
        dc.chunk_index,
        dc.content,
        dc.page_number,
        (1 - (dc.embedding <=> query_embedding))::float AS similarity,
        dc.metadata
    FROM public.document_chunks dc
    WHERE dc.owner_id = target_owner_id
      AND dc.embedding IS NOT NULL
      AND (1 - (dc.embedding <=> query_embedding)) >= match_threshold
    ORDER BY dc.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- Restrict execution permissions: only authenticated users and service_role
REVOKE EXECUTE ON FUNCTION match_document_chunks(vector, float, int, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION match_document_chunks(vector, float, int, uuid) TO authenticated, service_role;

