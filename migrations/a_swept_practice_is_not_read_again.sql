-- a_swept_practice_is_not_read_again
--
-- The 30-day practice sweep (services/practice_retention.py, founder
-- 2026-09-16, option A) deletes expired attempts and leaves the practice row
-- as it was. So a closed practice past its 30 days matched the sweep's query
-- for ever, and the query takes the oldest 50: once more than 50 practices
-- were past the cutoff, the same 50 came back every minute and a later one
-- was never read. Its expired recordings were never deleted.
--
--   confident_voice_practice.retention_checked_at
--       When the sweep last looked at this practice. NULL: never. The sweep
--       reads the practices it has never looked at first (oldest closed
--       first), then the ones it looked at more than a day ago (longest ago
--       first), and stamps each one it reads. So every practice is reached,
--       and one with nothing left to delete is read once a day, not once a
--       minute.
--
-- Every existing row starts as NULL, so the first runs after this lands walk
-- the whole backlog once, 50 practices a minute.
--
-- Read and written by the backend (service role) only. No environment
-- variable needed. Deploy with the code that reads it: the old code does not
-- know the column and is unaffected by it.
--
-- Idempotent + additive, per the standing constraint: safe to re-run. Drops
-- nothing.

ALTER TABLE public.confident_voice_practice
    ADD COLUMN IF NOT EXISTS retention_checked_at TIMESTAMPTZ NULL;

-- What the sweep reads: closed practices, by when they were last looked at.
CREATE INDEX IF NOT EXISTS confident_voice_practice_retention_idx
    ON public.confident_voice_practice (retention_checked_at, closed_at)
    WHERE status <> 'open';
