-- will_learns_from_takes_coach_words_and_chat (0482; founder 2026-10-20,
-- "Will learns from transcripts, coach words and chat history", step 2)
--
-- Will's private note about each speaker (0480, services/speaker_memory.py)
-- now also learns from three new sources, each a new event kind:
--
--   transcript  a spoken Take's transcript is final: a short opening and
--               closing, never the whole transcript
--   coach_word  what the coach SENT the speaker: a shared Take word, its
--               video's transcript, a shared moment answer (never a draft)
--   chat        the speaker's own chat message (never Will's reply, never an
--               answer to "Did this help?")
--
-- What this file does, and nothing else:
--
--   1. Widens the kind CHECK on speaker_memory_events to the five kinds
--      (DROP CONSTRAINT IF EXISTS, then ADD). Every existing row is
--      'answer' or 'take', which the new CHECK still allows.
--   2. Adds a nullable arc_id (the project) to speaker_memory_events, so an
--      erased project takes its events with it (registry code
--      speaker_memory_events_by_project). Nullable, no default: adding it
--      rewrites no row.
--   3. Two indexes, for the purge's selectors: by Take and by project.
--
-- Locks: ALTER TABLE on speaker_memory_events only (ACCESS EXCLUSIVE, held
-- for the length of the CHECK's validation over this small table, written
-- only by the backend in the background) and SHARE for the two index
-- builds. No other table is touched or locked.
--
-- Read and written by the backend (service role) only, as 0480. Purged with
-- the account, the Take and the project (services/data_purge_registry.py).
-- No environment variable needed. Idempotent and additive: IF NOT EXISTS
-- everywhere, the only DROP is of the CHECK it re-adds wider, in the same
-- transaction.

ALTER TABLE public.speaker_memory_events
    DROP CONSTRAINT IF EXISTS speaker_memory_events_kind_check;
ALTER TABLE public.speaker_memory_events
    ADD CONSTRAINT speaker_memory_events_kind_check
    CHECK (kind IN ('answer', 'take', 'transcript', 'coach_word', 'chat'));

ALTER TABLE public.speaker_memory_events
    ADD COLUMN IF NOT EXISTS arc_id UUID;

CREATE INDEX IF NOT EXISTS speaker_memory_events_take_idx
    ON public.speaker_memory_events (take_session_id)
    WHERE take_session_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS speaker_memory_events_arc_idx
    ON public.speaker_memory_events (arc_id)
    WHERE arc_id IS NOT NULL;
