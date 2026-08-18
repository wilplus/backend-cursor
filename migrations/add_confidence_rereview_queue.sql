-- A user-Yes / professional-coach-No Confident Voice disagreement must be
-- heard by a coach a second time. This queue is operational state only: it is
-- neither a vote nor training data, and it never changes project styling.

CREATE TABLE IF NOT EXISTS public.confidence_rereview_queue (
    snippet_id       UUID PRIMARY KEY
                     REFERENCES public.snippets(id) ON DELETE CASCADE,
    session_id       TEXT NOT NULL,
    arc_id            TEXT NOT NULL,
    owner_user_id     UUID NOT NULL,
    status            TEXT NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'confirmed_no')),
    coach_note        TEXT NULL,
    requested_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at       TIMESTAMPTZ NULL,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.confidence_rereview_queue ENABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS idx_confidence_rereview_session_pending
    ON public.confidence_rereview_queue (session_id, requested_at)
    WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_confidence_rereview_owner
    ON public.confidence_rereview_queue (owner_user_id, updated_at DESC);

COMMENT ON TABLE public.confidence_rereview_queue IS
    'Operational second-listen queue for owner-Yes / coach-No Confident Voice disagreements. Not a label or training source.';

GRANT ALL ON TABLE public.confidence_rereview_queue TO service_role;
