-- =============================================================================
-- Migration 006: User Connectors (Stage 18 — Google Drive Connector)
-- =============================================================================
-- Stores OAuth credentials and connection state for external providers (e.g. Google Drive).
-- Ensures tokens and client secrets are kept backend-side and strictly isolated per user.
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.user_connectors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    account_email TEXT,
    account_id TEXT,
    access_token TEXT,
    refresh_token TEXT,
    token_type TEXT DEFAULT 'Bearer',
    expires_at TIMESTAMPTZ,
    scopes TEXT[] DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'connected', -- 'connected', 'disconnected', 'revoked', 'expired'
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_user_connectors_owner_provider UNIQUE (owner_id, provider)
);

-- Index for fast lookup by owner and provider
CREATE INDEX IF NOT EXISTS idx_user_connectors_owner_provider 
    ON public.user_connectors(owner_id, provider);

-- Enable Row Level Security
ALTER TABLE public.user_connectors ENABLE ROW LEVEL SECURITY;

-- RLS Policies: Users can only see and manage their own connectors
DROP POLICY IF EXISTS "Users can view their own connectors" ON public.user_connectors;
CREATE POLICY "Users can view their own connectors"
    ON public.user_connectors
    FOR SELECT
    USING (auth.uid() = owner_id);

DROP POLICY IF EXISTS "Users can insert their own connectors" ON public.user_connectors;
CREATE POLICY "Users can insert their own connectors"
    ON public.user_connectors
    FOR INSERT
    WITH CHECK (auth.uid() = owner_id);

DROP POLICY IF EXISTS "Users can update their own connectors" ON public.user_connectors;
CREATE POLICY "Users can update their own connectors"
    ON public.user_connectors
    FOR UPDATE
    USING (auth.uid() = owner_id);

DROP POLICY IF EXISTS "Users can delete their own connectors" ON public.user_connectors;
CREATE POLICY "Users can delete their own connectors"
    ON public.user_connectors
    FOR DELETE
    USING (auth.uid() = owner_id);

-- Restrict sensitive token columns from public/client PostgREST access
REVOKE ALL ON public.user_connectors FROM anon;
REVOKE SELECT (access_token, refresh_token) ON public.user_connectors FROM authenticated;
GRANT ALL ON public.user_connectors TO service_role;
