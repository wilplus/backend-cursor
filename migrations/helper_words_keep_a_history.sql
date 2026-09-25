-- Helper words keep a history (contract 16, founder 2026-09-25).
--
-- A Paragraph's bookmark opens its history: the Slide's words Take by Take
-- (from `ideal_text_versions.document`, 0370) and which helper words were
-- locked when. `ideal_text_slide_helper_words` holds only the current set, so
-- this append-only log records each change to a Slide's LOCKED set.
-- Additive and idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS public.ideal_text_slide_helper_words_log (
    id           BIGSERIAL   PRIMARY KEY,
    arc_id       TEXT        NOT NULL,
    user_id      TEXT        NOT NULL,
    slide_index  INTEGER     NOT NULL CHECK (slide_index >= 0),
    phrases      JSONB       NOT NULL DEFAULT '[]'::jsonb
                             CHECK (jsonb_typeof(phrases) = 'array'),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_slide_helper_words_log_slide
    ON public.ideal_text_slide_helper_words_log (arc_id, user_id, slide_index, id);

ALTER TABLE public.ideal_text_slide_helper_words_log ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.ideal_text_slide_helper_words_log
    FROM PUBLIC, anon, authenticated;

COMMENT ON TABLE public.ideal_text_slide_helper_words_log IS
    'Append-only: each change to a Slide''s locked helper words, for the '
    'Paragraph history behind the bookmark (contract 16).';

COMMIT;
