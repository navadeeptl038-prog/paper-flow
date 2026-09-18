-- PaperFlow AI — Initial Schema
-- 001_initial_schema.sql
-- Covers conversations and messages tables with Row Level Security (RLS)

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ---------------------------------------------------------------------------
-- CONVERSATIONS
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.conversations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    owner_id UUID NOT NULL,
    title TEXT NOT NULL DEFAULT 'New chat',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversations_owner ON public.conversations (owner_id, updated_at DESC);

-- Enable RLS
ALTER TABLE public.conversations ENABLE ROW LEVEL SECURITY;

-- Conversations RLS policies
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE tablename = 'conversations' AND policyname = 'Users can view their own conversations'
    ) THEN
        CREATE POLICY "Users can view their own conversations"
            ON public.conversations FOR SELECT
            USING (auth.uid() = owner_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE tablename = 'conversations' AND policyname = 'Users can insert their own conversations'
    ) THEN
        CREATE POLICY "Users can insert their own conversations"
            ON public.conversations FOR INSERT
            WITH CHECK (auth.uid() = owner_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE tablename = 'conversations' AND policyname = 'Users can update their own conversations'
    ) THEN
        CREATE POLICY "Users can update their own conversations"
            ON public.conversations FOR UPDATE
            USING (auth.uid() = owner_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE tablename = 'conversations' AND policyname = 'Users can delete their own conversations'
    ) THEN
        CREATE POLICY "Users can delete their own conversations"
            ON public.conversations FOR DELETE
            USING (auth.uid() = owner_id);
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- MESSAGES
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID NOT NULL REFERENCES public.conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sources JSONB DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON public.messages (conversation_id, created_at ASC);

-- Enable RLS
ALTER TABLE public.messages ENABLE ROW LEVEL SECURITY;

-- Messages RLS policies (must belong to a conversation owned by the user)
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE tablename = 'messages' AND policyname = 'Users can view messages in their conversations'
    ) THEN
        CREATE POLICY "Users can view messages in their conversations"
            ON public.messages FOR SELECT
            USING (
                EXISTS (
                    SELECT 1 FROM public.conversations c
                    WHERE c.id = messages.conversation_id AND c.owner_id = auth.uid()
                )
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE tablename = 'messages' AND policyname = 'Users can insert messages in their conversations'
    ) THEN
        CREATE POLICY "Users can insert messages in their conversations"
            ON public.messages FOR INSERT
            WITH CHECK (
                EXISTS (
                    SELECT 1 FROM public.conversations c
                    WHERE c.id = messages.conversation_id AND c.owner_id = auth.uid()
                )
            );
    END IF;
END $$;
