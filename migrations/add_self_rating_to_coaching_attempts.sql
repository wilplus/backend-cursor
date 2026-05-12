-- Phase 8 of the snippet-CTA learning loop: in-chat self-rating.
--
-- After the user completes turn 1 of a contextual chat (and the
-- LLM-based outcome evaluation lands in coaching_attempts), the
-- frontend asks "on a scale of 1-10, how did that feel?" inside the
-- existing chat thread. The user types a number; the backend parses
-- it; this row records it.
--
-- Why these columns
-- -----------------
--   self_rating              — the parsed 1..10 integer. NULL means
--                              the user never submitted (skipped or
--                              the rating ask was never asked).
--   self_rating_text         — the verbatim user reply. Kept so we
--                              can audit parsing decisions later
--                              (e.g. "I'd say 8" → 8). Also useful
--                              when we want a qualitative annotation
--                              on top of the numeric rating.
--   self_rating_submitted_at — capture time. Lets us measure how
--                              long users take to rate, and
--                              distinguish "never rated" from
--                              "rated 0" (which the CHECK forbids
--                              anyway — the constraint is here for
--                              defence in depth).
--
-- Range-checked at the DB so a misbehaving client can't slip an
-- out-of-band score into the column. Parser in routes/v2_routes.py
-- already validates 1..10, but defence-in-depth is cheap.
--
-- Idempotent — safe to re-run; each ADD COLUMN is IF NOT EXISTS and
-- the CHECK constraint uses a NOT VALID + VALIDATE pattern that
-- silently no-ops if it already exists.

ALTER TABLE coaching_attempts
    ADD COLUMN IF NOT EXISTS self_rating SMALLINT,
    ADD COLUMN IF NOT EXISTS self_rating_text TEXT,
    ADD COLUMN IF NOT EXISTS self_rating_submitted_at TIMESTAMPTZ;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'coaching_attempts_self_rating_range'
    ) THEN
        ALTER TABLE coaching_attempts
            ADD CONSTRAINT coaching_attempts_self_rating_range
            CHECK (self_rating IS NULL OR (self_rating BETWEEN 1 AND 10));
    END IF;
END $$;

COMMENT ON COLUMN coaching_attempts.self_rating IS
    'User self-rating 1..10 captured in-chat after the AI evaluation. '
    'NULL = not submitted (skipped or never asked).';
COMMENT ON COLUMN coaching_attempts.self_rating_text IS
    'Verbatim user reply to the rating prompt, kept for audit / qualitative analysis.';
COMMENT ON COLUMN coaching_attempts.self_rating_submitted_at IS
    'Timestamp when the user submitted their self-rating reply.';
