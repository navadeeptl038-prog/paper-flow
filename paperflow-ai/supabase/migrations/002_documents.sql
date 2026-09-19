-- PaperFlow AI — Documents Table Schema
-- 002_documents.sql

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS public.documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    owner_id UUID NOT NULL,
    original_filename TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    file_type TEXT NOT NULL,
    processing_status TEXT NOT NULL DEFAULT 'uploaded',
    source TEXT NOT NULL DEFAULT 'local_upload',
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_documents_owner ON public.documents (owner_id, updated_at DESC);

-- Enable RLS
ALTER TABLE public.documents ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE tablename = 'documents' AND policyname = 'Users can view their own documents'
    ) THEN
        CREATE POLICY "Users can view their own documents"
            ON public.documents FOR SELECT
            USING (auth.uid() = owner_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE tablename = 'documents' AND policyname = 'Users can insert their own documents'
    ) THEN
        CREATE POLICY "Users can insert their own documents"
            ON public.documents FOR INSERT
            WITH CHECK (auth.uid() = owner_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE tablename = 'documents' AND policyname = 'Users can update their own documents'
    ) THEN
        CREATE POLICY "Users can update their own documents"
            ON public.documents FOR UPDATE
            USING (auth.uid() = owner_id)
            WITH CHECK (auth.uid() = owner_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE tablename = 'documents' AND policyname = 'Users can delete their own documents'
    ) THEN
        CREATE POLICY "Users can delete their own documents"
            ON public.documents FOR DELETE
            USING (auth.uid() = owner_id);
    END IF;
END $$;
