-- Per-(user, session) archive flags for the Copilot Training Studio queue.
-- Replaces frontend localStorage hack — persists across browsers and admins.
-- Safe to run multiple times.

CREATE TABLE IF NOT EXISTS public.admin_copilot_queue_archives (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  session_id UUID NOT NULL,
  archived_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  archived_by UUID NULL REFERENCES auth.users(id) ON DELETE SET NULL,
  UNIQUE (user_id, session_id)
);

CREATE INDEX IF NOT EXISTS idx_admin_copilot_queue_archives_user
  ON public.admin_copilot_queue_archives (user_id);

CREATE INDEX IF NOT EXISTS idx_admin_copilot_queue_archives_session
  ON public.admin_copilot_queue_archives (session_id);

GRANT ALL ON TABLE public.admin_copilot_queue_archives TO service_role;

ALTER TABLE public.admin_copilot_queue_archives ENABLE ROW LEVEL SECURITY;
