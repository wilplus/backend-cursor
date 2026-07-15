-- The user's PERSONAL notebook copy of the ideal text (founder 2026-07-15).
-- Editing in the notebook NEVER touches the coach-approved canonical
-- (L1: the deliverable stays the coach-approved select). One copy per
-- (arc, user). Idempotent; RLS on, no policy (service-role only).

CREATE TABLE IF NOT EXISTS public.user_arc_ideal_notes (
    arc_id     TEXT NOT NULL,
    user_id    UUID NOT NULL,
    text       TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (arc_id, user_id)
);
ALTER TABLE public.user_arc_ideal_notes ENABLE ROW LEVEL SECURITY;
