-- The upload retry collapse (founder 2026-08-10: "why there was this
-- double recording with the snippets").
--
-- The dual-lane uploader (Worker → BFF fallback) legitimately re-sends the
-- same FormData when the Worker socket dies AFTER the body already reached
-- the backend; the spent-session guard then — correctly, per its own lane
-- rule — refuses to reuse the session and mints a fresh one, so one take
-- lands as take N and take N+1 with identical audio. The FE now mints ONE
-- key per take and sends it on every attempt; the POST finds the first
-- session by key and echoes it instead of minting again.
--
-- Existing table — column + partial unique index only, both idempotent.

ALTER TABLE v2_sessions
    ADD COLUMN IF NOT EXISTS upload_idempotency_key TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_v2_sessions_upload_key
    ON v2_sessions (upload_idempotency_key)
    WHERE upload_idempotency_key IS NOT NULL;
