-- Phase 13: smart EBCP routing — baseline_established flag.
--
-- The first 4 turns of every interview are a hardcoded EBCP
-- Baseline Mapping script (math → relief → familiarity). That's the
-- right experience for a NEW user — it gives acoustics across
-- known stress/charisma conditions. For RETURNING users it's a
-- groundhog-day repeat that ignores everything we know about them.
--
-- This flag splits the routing:
--   FALSE (default) → scripted EBCP for turns 1-4, then LLM from
--                     turn 5+. Identical to pre-Phase-13 behaviour.
--   TRUE            → bypass the script entirely; LLM generates
--                     contextual turn 1 immediately, alternating
--                     tone, with the user's long-term profile soft-
--                     injected and previous_turns wired in.
--
-- The flag flips to TRUE when a user first asks for turn 5 — that
-- moment proves they completed the 4-turn script. From their next
-- session onward they're in the bypass regime. Admin can flip it
-- back to FALSE to force a fresh baseline (e.g. after a long gap).
--
-- Idempotent.

ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS baseline_established BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS baseline_established_at TIMESTAMPTZ;

COMMENT ON COLUMN user_settings.baseline_established IS
    'Phase 13 — TRUE once the user has completed the EBCP Baseline '
    'Mapping script (turns 1-4) at least once. Returning users with '
    'this flag skip the scripted opener and go straight to LLM-'
    'generated contextual coaching from turn 1.';
COMMENT ON COLUMN user_settings.baseline_established_at IS
    'When the baseline graduation happened. NULL while still in the '
    'scripted regime.';

NOTIFY pgrst, 'reload schema';
