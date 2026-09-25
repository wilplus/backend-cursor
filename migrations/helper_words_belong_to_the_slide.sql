-- Helper words belong to the Slide (contract 13-14, founder 2026-09-25, Q12 A).
--
-- A Take can split a Slide into a different number of Paragraphs than the Take
-- before it, so helper words stored on a Paragraph cannot survive that. This
-- table stores them per Slide, in the order they were picked.
--
-- Q14 A: picks made while reviewing the same Take add up on a Slide; the first
-- pick LOCKED in a later Take replaces the Slide's older set. `take_session_id`
-- is what lets the code tell those apart; `source_part_id` is the Paragraph the
-- words were tapped on, so a re-pick on it replaces instead of adding.
--
-- No backfill. Helper words locked before this table existed keep being served
-- from `ideal_text_part` for any Slide that has no row here yet, so nothing
-- already locked disappears. Additive and idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS public.ideal_text_slide_helper_words (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    arc_id           TEXT        NOT NULL,
    user_id          TEXT        NOT NULL,
    slide_index      INTEGER     NOT NULL CHECK (slide_index >= 0),
    ord              INTEGER     NOT NULL CHECK (ord >= 0),
    phrase           TEXT        NOT NULL CHECK (length(phrase) > 0),
    take_session_id  TEXT        NULL,
    source_part_id   TEXT        NULL,
    locked_at        TIMESTAMPTZ NULL,
    selected_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One phrase per slot. Non-partial so it can arbitrate; rows are replaced
-- per Slide wholesale, so this is an invariant rather than a write arbiter.
CREATE UNIQUE INDEX IF NOT EXISTS uq_slide_helper_words_slot
    ON public.ideal_text_slide_helper_words (arc_id, user_id, slide_index, ord);

ALTER TABLE public.ideal_text_slide_helper_words ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.ideal_text_slide_helper_words
    FROM PUBLIC, anon, authenticated;

COMMENT ON TABLE public.ideal_text_slide_helper_words IS
    'Helper words (orange rooting phrases) per Slide, in pick order. Picks in '
    'the same Take add up; the first pick locked in a later Take replaces the '
    'Slide''s older set (contract 13-14, founder 2026-09-25).';

COMMIT;
