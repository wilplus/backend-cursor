-- the_founder_edits_wills_questions (N83, founder 2026-10-20: "OK" to the
-- prototype https://claude.ai/artifact/WLZ1KY6dX1RBLXiNU73F9N; the outside
-- review waived by the founder the same day)
--
-- Will's questions after a Take (N82) are signed words in code. The founder
-- changes them, and fills two empty slots, from the coach panel ("Will · only
-- you" → "Will's questions"). One row per question the founder changed; a
-- question with no row keeps the signed words in code
-- (services/will_question.py).
--
--   will_question_bank  key (the question's name in code), its words and
--                       its tap answers, when they last changed.
--
-- Copy, like the signed-line catalogue: no row names a person
-- (services/data_purge_registry.py, NON_SUBJECT_RELATIONS). Read and written
-- by the backend (service role) only. No environment variable needed.
-- Idempotent and additive: IF NOT EXISTS, nothing dropped.

BEGIN;

CREATE TABLE IF NOT EXISTS public.will_question_bank (
    key         TEXT PRIMARY KEY,
    question    TEXT NOT NULL DEFAULT '',
    chips       JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT will_question_bank_key_len CHECK (char_length(key) <= 40),
    CONSTRAINT will_question_bank_question_len CHECK (char_length(question) <= 300),
    CONSTRAINT will_question_bank_chips_array CHECK (jsonb_typeof(chips) = 'array')
);

ALTER TABLE public.will_question_bank ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.will_question_bank FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.will_question_bank TO service_role;

COMMIT;
