-- willab — star suggestions on the SD ideal text (founder 2026-07-18).
--
-- One row per suggestion-flagged snippet: the generated suggestion the grey
-- star opens. kind 'emphasize' (clean charisma lean → bold+orange on
-- Approve) or 'replace' (threat lean / profanity / very low slide
-- stickiness → the generated audience-appropriate rephrase). `trigger`
-- records WHY (threat|profanity|stickiness|coach) for analytics/tuning.
-- Approve/Revert live in user_suggestion_feedback (targets
-- moment_emphasize/moment_replace) — never here.
--
-- L1 (founder sign-off 2026-07-18): an approved replacement writes the
-- STUDENT's copy at serve time only — the canonical coach_arc_ideal_text
-- is never mutated by suggestions.
--
-- Idempotent; RLS on, no policy (service-role only).
CREATE TABLE IF NOT EXISTS public.moment_suggestions (
    snippet_id       TEXT PRIMARY KEY,
    arc_id           TEXT NOT NULL,
    kind             TEXT NOT NULL CHECK (kind IN ('emphasize', 'replace')),
    replacement_text TEXT NULL,
    why              TEXT NULL,
    trigger          TEXT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_moment_suggestions_arc
    ON public.moment_suggestions (arc_id);
ALTER TABLE public.moment_suggestions ENABLE ROW LEVEL SECURITY;
