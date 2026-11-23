BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS public.take_review_edits (
    take_session_id uuid PRIMARY KEY REFERENCES public.v2_sessions(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    revision integer NOT NULL CHECK (revision > 0),
    document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object')
);

ALTER TABLE public.take_review_edits ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.take_review_edits FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.take_review_edits TO service_role;

CREATE INDEX IF NOT EXISTS lounge_practice_receipts_by_project
    ON public.lounge_messages (user_id, (metadata->>'arc_id'), id)
    WHERE role = 'user' AND kind = 'walk_step';

NOTIFY pgrst, 'reload schema';
COMMIT;
