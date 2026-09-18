-- PaperFlow AI — Document Chunks & Vector Storage Schema
-- 003_document_chunks.sql

-- Enable pgvector extension for dense embedding storage
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Document chunks table
CREATE TABLE IF NOT EXISTS public.document_chunks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES public.documents(id) ON DELETE CASCADE,
    owner_id UUID NOT NULL,
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    page_number INT,
    embedding vector(384), -- all-MiniLM-L6-v2 dimension: 384
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for fast filtering and joins
CREATE INDEX IF NOT EXISTS idx_document_chunks_doc ON public.document_chunks(document_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_document_chunks_owner ON public.document_chunks(owner_id);

-- Cosine distance index for pgvector
CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding 
ON public.document_chunks 
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- Enable Row Level Security
ALTER TABLE public.document_chunks ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE tablename = 'document_chunks' AND policyname = 'Users can view their own document chunks'
    ) THEN
        CREATE POLICY "Users can view their own document chunks"
            ON public.document_chunks FOR SELECT
            USING (auth.uid() = owner_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE tablename = 'document_chunks' AND policyname = 'Users can insert their own document chunks'
    ) THEN
        CREATE POLICY "Users can insert their own document chunks"
            ON public.document_chunks FOR INSERT
            WITH CHECK (auth.uid() = owner_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE tablename = 'document_chunks' AND policyname = 'Users can update their own document chunks'
    ) THEN
        CREATE POLICY "Users can update their own document chunks"
            ON public.document_chunks FOR UPDATE
            USING (auth.uid() = owner_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE tablename = 'document_chunks' AND policyname = 'Users can delete their own document chunks'
    ) THEN
        CREATE POLICY "Users can delete their own document chunks"
            ON public.document_chunks FOR DELETE
            USING (auth.uid() = owner_id);
    END IF;
END $$;
