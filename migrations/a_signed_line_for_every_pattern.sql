-- A signed line for every pattern (founder 2026-09-30, E3 and C4; phase 1
-- close-out task P1-4).
--
-- THE CATALOGUE. Until now the praise the speaker read after a Yes came
-- from the frontend's constant per delivery cue, or, on a cold start, from
-- the Manager's fallback: the shortest sentence praised for its concision in
-- tentative words. The rewrite's reason line was a frontend constant keyed
-- by why_key. Neither could be written by the founder or a coach without a
-- deploy, and neither grows from the coach's answers.
--
-- This table holds one signed line per pattern:
--   lane 'praise'   pattern_kind 'read'    key 'confident_read'   (a read)
--   lane 'praise'   pattern_kind 'cue'     key one of delivery_cues.CUE_KEYS
--   lane 'praise'   pattern_kind 'device'  key a structural/delivery device
--   lane 'rewrite'  pattern_kind 'move'    key a rewrite why_key
-- The Manager reads the catalogue before its fallback: a served praise row
-- carries `praise_line`, a served rewrite row carries `rewrite_move`, and the
-- sheet renders the signed line where one exists and its constant where none
-- does (an honest empty lane still shows nothing invented, contract 24f).
--
-- Rows are versioned, never edited: a new line for the same key is a new
-- version, and the newest active version is the one served. `signed_by` is
-- the authenticated author (L3: a self-declared author is not provenance).
-- Nothing here is a score, a verdict, or evidence that a pattern occurred in
-- a recording (AC-9, L3): a row is a sentence and the pattern it belongs to.
-- The coach panel's Home screen (phase 2, C4) writes here too.
--
-- Additive. Idempotent. No env var.

BEGIN;

CREATE TABLE IF NOT EXISTS public.feedback_catalogue (
    id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    lane          text        NOT NULL,
    pattern_kind  text        NOT NULL,
    pattern_key   text        NOT NULL,
    text          text        NOT NULL,
    version       integer     NOT NULL DEFAULT 1,
    signed_by     text,
    active        boolean     NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT feedback_catalogue_lane_check
        CHECK (lane IN ('praise', 'rewrite')),
    CONSTRAINT feedback_catalogue_kind_check
        CHECK (pattern_kind IN ('read', 'cue', 'device', 'move')),
    CONSTRAINT feedback_catalogue_lane_kind_check
        CHECK ((lane = 'praise' AND pattern_kind IN ('read', 'cue', 'device'))
            OR (lane = 'rewrite' AND pattern_kind = 'move')),
    CONSTRAINT feedback_catalogue_text_check
        CHECK (length(btrim(text)) BETWEEN 1 AND 400),
    CONSTRAINT feedback_catalogue_version_check CHECK (version >= 1),
    CONSTRAINT feedback_catalogue_one_version_per_key
        UNIQUE (lane, pattern_kind, pattern_key, version)
);

CREATE INDEX IF NOT EXISTS idx_feedback_catalogue_active_key
    ON public.feedback_catalogue (lane, pattern_kind, pattern_key, version DESC)
    WHERE active;

-- Service role only, like every authoring table (the BE is the one reader
-- and writer; the sheet receives the line on the served row).
ALTER TABLE public.feedback_catalogue ENABLE ROW LEVEL SECURITY;

COMMIT;
