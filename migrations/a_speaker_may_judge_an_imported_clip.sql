-- a_speaker_may_judge_an_imported_clip (N119, founder 2026-10-23: "I am
-- choosing that my audience is only me, but still I should be getting the
-- judgements to do from the training corpus"; "3 clips (high, middle, low
-- willfidence) from 3 different speakers"; asked, "Yes, the basis covers
-- it"). Outside review: the founder's, before merge (CLAUDE.md).
--
-- The walk's "Other speakers" now plays clips of the imported training
-- corpus, the clips the coaches judge (N101), to speakers: anonymously,
-- audio only, under the corpus basis (CO2, N58). A speaker's answer on one
-- is kept here, one per listener per clip, and is NEVER a label (L3): it
-- does not enter confidence_labels, the coaches' corpus ledger or
-- community_answers, whose checks keep a training clip to the licensed
-- corpus (0432).
--
--   import_clip_answers  the listener (a user id), the imported clip (a
--                        snippet of a training import), the import it
--                        belongs to, the answer, when it was given.
--
-- Purged with the listener and with the import (services/
-- data_purge_registry.py). Read and written by the backend (service role)
-- only. No environment variable needed. Idempotent and additive: IF NOT
-- EXISTS, nothing dropped.

BEGIN;

CREATE TABLE IF NOT EXISTS public.import_clip_answers (
    id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    listener_user_id  text        NOT NULL,
    snippet_id        text        NOT NULL,
    import_session_id text        NOT NULL,
    value             text        NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT import_clip_answers_value_check
        CHECK (value IN ('yes', 'in_between', 'no', 'not_sure', 'audio_unclear')),
    CONSTRAINT import_clip_answers_once UNIQUE (listener_user_id, snippet_id)
);
CREATE INDEX IF NOT EXISTS import_clip_answers_import_idx
    ON public.import_clip_answers (import_session_id);
CREATE INDEX IF NOT EXISTS import_clip_answers_listener_created_idx
    ON public.import_clip_answers (listener_user_id, created_at DESC);

ALTER TABLE public.import_clip_answers ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.import_clip_answers FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.import_clip_answers TO service_role;

COMMENT ON TABLE public.import_clip_answers IS
    'A speaker''s answer on one clip of the imported training corpus in the '
    'walk''s Other speakers (N119): one per listener per clip, never a label '
    '(L3), apart from the coaches'' corpus labels and from community_answers. '
    'Purged with the listener, and with the import it is about.';

COMMIT;
