-- Per-suggestion user feedback (founder 2026-07-14) — the Apply / ✓-prefer
-- taps on the instant view's suggestion rows (word swap, phrase swap, the
-- auto/coach comment, the comment-with-video). A SECOND-ORDER preference
-- signal strictly below coach truth (mirrors snippet_peer_labels): it feeds
-- the learning loop about which suggestions users actually adopt, and is
-- NEVER joined into training_labels and never surfaced back as any score
-- (AC-9 — capture only).
--
-- Idempotent; safe to re-run. RLS ON with no policies = service-role only
-- (writes go through the backend route, reads are training-side only).

CREATE TABLE IF NOT EXISTS public.user_suggestion_feedback (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snippet_id         UUID NOT NULL,          -- the piece row the suggestion rode
    session_id         UUID NULL,              -- denormalized for session-level pulls
    user_id            UUID NULL,              -- NULL = guest (session-capability path)
    suggestion_version TEXT NULL,              -- the card's version at tap time
    target             TEXT NOT NULL,          -- upgrade | rewrite_your_voice |
                                               -- rewrite_polished | comment | comment_video
    upgrade_index      INTEGER NULL,           -- which upgrades[] row (target=upgrade)
    action             TEXT NOT NULL,          -- applied | preferred | apply_all
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.user_suggestion_feedback ENABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS idx_user_suggestion_feedback_snippet
    ON public.user_suggestion_feedback (snippet_id);
CREATE INDEX IF NOT EXISTS idx_user_suggestion_feedback_user
    ON public.user_suggestion_feedback (user_id);
