-- Spoken vs read recording (founder 2026-07-14) — the two recordings of a
-- take: the ORIGINAL spoken delivery, and the RE-READ of the suggestion-
-- corrected text. Both go to the coach as snippets, each self-describing its
-- kind. The read is a PAIRED VARIANT of its spoken take (paired_session_id),
-- and does NOT count as one of the 3 arc takes.
--
-- Idempotent; safe to re-run. No backfill — older sessions read as 'spoken'
-- (the default) at the application layer.

ALTER TABLE public.v2_sessions
    ADD COLUMN IF NOT EXISTS recording_kind    text,   -- 'spoken' | 'read'
    ADD COLUMN IF NOT EXISTS paired_session_id uuid;   -- read → its spoken take

-- Take-count / arc-grouping lookups filter on this.
CREATE INDEX IF NOT EXISTS idx_v2_sessions_paired
    ON public.v2_sessions (paired_session_id);
