-- The ideal text as ONE coach-reviewed block (founder 2026-07-15) — replaces
-- per-slide slot editing as the coach's review surface. Auto-assembled by the
-- system after the 3-take arc completes, edited/approved by the coach in the
-- same minimalist editor the user later sees, and only served to the student
-- once approved (approved_at set) AND the $25 arc unlock is owned.
-- Text carries the existing marker subset (**bold** openings,
-- [[moment:<snippet_id>|<session_id>]]…[[/moment]] key-moment anchors).
-- Idempotent; RLS on, no policy (service-role only).

CREATE TABLE IF NOT EXISTS public.coach_arc_ideal_text (
    arc_id      TEXT PRIMARY KEY,
    text        TEXT NOT NULL,
    approved_at TIMESTAMPTZ NULL,
    updated_by  UUID NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE public.coach_arc_ideal_text ENABLE ROW LEVEL SECURITY;
