-- PaperFlow AI — Supabase Storage Bucket & RLS Policies
-- 005_storage_policies.sql

-- Ensure private paperflow-documents bucket exists
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'paperflow-documents',
    'paperflow-documents',
    false, -- Private bucket
    52428800, -- 50MB max file size
    ARRAY[
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'image/jpeg',
        'image/png',
        'image/webp',
        'image/heic',
        'image/heif'
    ]
)
ON CONFLICT (id) DO UPDATE SET public = false;

-- Storage object RLS policies
-- Path structure: <user_id>/<uuid>/<safe_filename>

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE tablename = 'objects' AND policyname = 'Users can upload their own documents'
    ) THEN
        CREATE POLICY "Users can upload their own documents"
        ON storage.objects FOR INSERT TO authenticated
        WITH CHECK (
            bucket_id = 'paperflow-documents' AND
            (storage.foldername(name))[1] = auth.uid()::text
        );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE tablename = 'objects' AND policyname = 'Users can view their own documents'
    ) THEN
        CREATE POLICY "Users can view their own documents"
        ON storage.objects FOR SELECT TO authenticated
        USING (
            bucket_id = 'paperflow-documents' AND
            (storage.foldername(name))[1] = auth.uid()::text
        );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE tablename = 'objects' AND policyname = 'Users can delete their own documents'
    ) THEN
        CREATE POLICY "Users can delete their own documents"
        ON storage.objects FOR DELETE TO authenticated
        USING (
            bucket_id = 'paperflow-documents' AND
            (storage.foldername(name))[1] = auth.uid()::text
        );
    END IF;
END $$;
