-- Coach AI conversations: per-student conversation history for the AI coaching assistant.
-- Each student has one conversation thread (like a dedicated ChatGPT).

CREATE TABLE IF NOT EXISTS coach_ai_conversations (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id uuid NOT NULL UNIQUE REFERENCES auth.users(id) ON DELETE CASCADE,
    messages jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Index for fast lookup by user_id (already unique, but explicit for clarity)
CREATE INDEX IF NOT EXISTS idx_coach_ai_conversations_user_id ON coach_ai_conversations(user_id);

-- Grant access to service role
GRANT ALL ON coach_ai_conversations TO service_role;

-- Enable RLS
ALTER TABLE coach_ai_conversations ENABLE ROW LEVEL SECURITY;

-- Service role bypass (admin-only table, no student access needed)
CREATE POLICY "service_role_all" ON coach_ai_conversations
    FOR ALL
    USING (true)
    WITH CHECK (true);
