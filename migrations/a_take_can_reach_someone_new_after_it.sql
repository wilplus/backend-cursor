-- a_take_can_reach_someone_new_after_it (matching people after a Take;
-- founder, the Claude Code chat, 4 November 2026, N477, N478, N481, N485,
-- N486, N493 and N504)
--
-- One table, take_matches: the one suggestion a Take may get, after it,
-- of someone new who fits it (N477), and what came of it (N478):
--
--   session_id     The speaker's Take (v2_sessions.id). One suggestion per
--                  Take at most (unique).
--   speaker_id     Who recorded the Take.
--   candidate_id   Who was suggested: someone in one of the speaker's
--                  communities with no chat with them yet.
--   arm            The experiment's arm (N481 item 3): 'topics' (knowledge
--                  only, while skills are off, N481 item 4), 'similar_level'
--                  or 'further_along' (speaking skills); 'similar_style' and
--                  'opposite_style' are kept for N463 item 5's style arms.
--   fit            How well the candidate fitted the Take, the words they
--                  shared (shared_terms) and what made the fit (signals:
--                  knowledge, skills, progress, the communication profile's
--                  distance): for WillpowerLab's own review only, never
--                  shown to anyone (Never 1).
--   status         offered (the page came back with them), closed (the
--                  speaker's Not now), sent (an inquiry: a new chat in the
--                  candidate's list, N485), accepted ("Open Take": the
--                  speaker's name and Take shown, N493 item 7), sending (an
--                  answer within its five seconds of Undo, N493 item 5),
--                  answered (the chat between the two was made, thread_id),
--                  declined (the candidate's Not now: nobody is told; who
--                  declined whose Take and when stay, N504 item 2).
--   speaker_name   The speaker's name as they go by in the chats, kept at
--                  Send; shown to the candidate only after Open Take.
--   candidate_name, answer_session_id, answer_ms, answer_due_at: the answer
--                  while it waits for its Undo, for the chat it then makes.
--   thread_id, and the time of each step.
--
-- Nothing reads this table but the backend (the matcher, its routes, the
-- weekly review): service role only, nothing for anon or authenticated. It
-- goes with either account (services/data_purge_registry.py). No ring row is
-- written: with none, the feature "take_match" is off for everyone, the
-- founder included, until the founder adds it in the rings panel. No
-- environment variable is needed.
--
-- Idempotent and additive: CREATE ... IF NOT EXISTS; nothing is dropped and
-- no row is written, rewritten or removed. One transaction; explicit grants
-- to service_role, as 0505 to 0509.
--
-- Rollback (a new forward migration): leave it; dropping it is a separate,
-- previewed retention operation.

BEGIN;

CREATE TABLE IF NOT EXISTS public.take_matches (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id        UUID NOT NULL,
    speaker_id        TEXT NOT NULL,
    candidate_id      TEXT NOT NULL,
    arm               TEXT NOT NULL DEFAULT 'topics'
                      CHECK (arm IN ('topics', 'similar_level', 'further_along',
                                     'similar_style', 'opposite_style')),
    fit               REAL NOT NULL DEFAULT 0,
    shared_terms      TEXT[] NOT NULL DEFAULT '{}',
    signals           JSONB NOT NULL DEFAULT '{}'::jsonb
                      CHECK (jsonb_typeof(signals) = 'object'),
    status            TEXT NOT NULL DEFAULT 'offered'
                      CHECK (status IN ('offered', 'closed', 'sent', 'accepted',
                                        'sending', 'answered', 'declined')),
    speaker_name      TEXT CHECK (speaker_name IS NULL
                                  OR char_length(speaker_name) BETWEEN 1 AND 120),
    candidate_name    TEXT CHECK (candidate_name IS NULL
                                  OR char_length(candidate_name) BETWEEN 1 AND 120),
    answer_session_id UUID,
    answer_ms         INTEGER CHECK (answer_ms IS NULL OR answer_ms > 0),
    answer_due_at     TIMESTAMPTZ,
    thread_id         UUID,
    offered_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at           TIMESTAMPTZ,
    closed_at         TIMESTAMPTZ,
    accepted_at       TIMESTAMPTZ,
    declined_at       TIMESTAMPTZ,
    answered_at       TIMESTAMPTZ,
    CHECK (speaker_id <> candidate_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS take_matches_once_per_take
    ON public.take_matches (session_id);
CREATE INDEX IF NOT EXISTS take_matches_by_speaker
    ON public.take_matches (speaker_id);
CREATE INDEX IF NOT EXISTS take_matches_by_candidate
    ON public.take_matches (candidate_id);
-- The inquiries waiting on a person (status sent, accepted or sending),
-- read each time they open their chats (outside review, 4 November 2026).
CREATE INDEX IF NOT EXISTS take_matches_by_candidate_status
    ON public.take_matches (candidate_id, status);

ALTER TABLE public.take_matches ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.take_matches FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.take_matches TO service_role;

COMMIT;
