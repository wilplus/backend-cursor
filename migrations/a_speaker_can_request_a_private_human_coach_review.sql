BEGIN;

CREATE TABLE IF NOT EXISTS public.human_coach_reviews (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    recipient_user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    take_session_id uuid NOT NULL UNIQUE REFERENCES public.v2_sessions(id) ON DELETE CASCADE,
    note text NOT NULL DEFAULT '' CHECK (char_length(note) <= 300),
    document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object'),
    requested_at timestamptz NOT NULL DEFAULT now(),
    email_claimed_at timestamptz,
    email_sent_at timestamptz,
    provider_email_id text,
    feedback text CHECK (char_length(feedback) BETWEEN 1 AND 6000),
    feedback_at timestamptz,
    CHECK (owner_user_id <> recipient_user_id),
    CHECK ((feedback IS NULL) = (feedback_at IS NULL))
);

CREATE INDEX IF NOT EXISTS human_coach_reviews_project_owner
    ON public.human_coach_reviews (project_id, owner_user_id, requested_at);
CREATE INDEX IF NOT EXISTS human_coach_reviews_recipient
    ON public.human_coach_reviews (recipient_user_id);

ALTER TABLE public.human_coach_reviews ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.human_coach_reviews FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.human_coach_reviews TO service_role;

ALTER TABLE public.bookings ADD COLUMN IF NOT EXISTS human_coach_request_id uuid;
CREATE INDEX IF NOT EXISTS bookings_human_coach_request
    ON public.bookings (human_coach_request_id) WHERE human_coach_request_id IS NOT NULL;

COMMENT ON TABLE public.human_coach_reviews IS
    'N688: speaker-requested private review of one Take. Service access only. Excluded from training and blind coach queues.';

COMMIT;
