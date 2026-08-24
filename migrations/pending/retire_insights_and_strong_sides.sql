-- MANUAL DESTRUCTIVE CLEANUP — intentionally absent from manifest.txt.
--
-- The runtime has retired both persistence shapes: exact-evidence
-- FeedbackItems replace insights_payload, and Voice Album is the sole
-- user-facing collection for positive speaking moments. Apply this file only
-- through the reviewed destructive-migration procedure after taking a backup.
-- Keeping it outside the automatic Railway migration path ensures a normal
-- application deploy can never delete production data.
--
-- This cleanup is unrelated to the canonical guest-first experience. It must
-- not remove guest_funnel rows, funnel_config, v2_sessions.guest_claimed_at,
-- rejected_takes.guest_session_id, or any guest-owned recording graph.

ALTER TABLE IF EXISTS public.v2_sessions
    DROP COLUMN IF EXISTS insights_payload;

DROP TABLE IF EXISTS public.strong_sides_library;
