-- 0453 · V4 asks coaches two blind questions (V4 Phase 1, B1.8 and B1.9;
-- build plan D-ML-13; founder S-B8 A, Q-B8 A, QG4 B, QG9 A, QB7 B, QB8 A,
-- V18 A, V19 A, V20 A, M9, H7).
--
-- WHY. V4 is tested against human judgement before it serves (BEXIT).
--   B1.8 "Pick the moment for feedback": a coach (and the founder) hears up
--   to three moments of one block, with their words, and picks the one that
--   most needs work, or "None needs it" (QB7 B: praise is not asked here).
--   The founder's picks alone are the golden set (QG4 B); a coach's are
--   compared with them; "None needs it" from both is agreement (V18 A).
--   About ten blocks a week each (H7), mostly where V4 is unsure, plus a
--   random share; about one in ten of a coach's blocks is one they answered
--   two to three weeks before, unmarked (QG9 A).
--   B1.9 "Which sounds surer": the speaker's own words beside a machine
--   version that changes one word quality (V20 A); "Is the new version
--   surer? Yes / No / Can't tell" (V19 A). The queue is 40% passages above
--   the reached bar, 40% below, 20% random (P6, QB8 A), shuffled; the coach
--   never sees the slice. An answer is a WORDS label and, for Yes or No, a
--   preference pair (chosen, rejected). Training stays off (M10).
--
-- BLIND (BLIND COACH). The machine's picks, the slice, the passage's level
-- and the reason a block was asked are stored here and never sent: the
-- coach's sheet carries words, audio and letters only (services/
-- v4_coach_sheets.py). Coach answers are their own provenance and never mix
-- with confidence labels, owner answers or the machine's read (L3).
--
-- WHAT. Two tables, written by the app with the service key, one answer
-- per row, once (the app updates only rows whose answered_at is empty):
--   v4_moment_pick_sheets   one block put to one rater.
--   v4_surer_sheets         one pair put to one rater.
-- Each table's CHECKs pin its versions, its slices, its answer shapes, the
-- answer to the clips shown, and the pair's chosen and rejected texts to
-- its answer.
--
-- WHAT DOES NOT CHANGE. Nothing is served to a speaker; nothing changes a
-- bookmark, a label or the walk. The screens are behind the coach panel
-- switch and the sheets behind V4_COACH_SHEETS_ENABLED (off).
--
-- Idempotent: IF NOT EXISTS; no row written on its own; locks only the new
-- tables. Rollback (forward): drop the two tables.

BEGIN;

CREATE TABLE IF NOT EXISTS public.v4_moment_pick_sheets (
    id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    rater_id            text        NOT NULL,
    rater_role          text        NOT NULL,
    take_session_id     uuid        NOT NULL,
    policy_version      text        NOT NULL,
    picker_version      text        NOT NULL,
    block_id            text        NOT NULL,
    clip_ids            text[]      NOT NULL,
    v4_snippet_id       text        NULL,
    v3_snippet_id       text        NULL,
    slice               text        NOT NULL,
    repick_of           uuid        NULL REFERENCES public.v4_moment_pick_sheets(id)
                                    ON DELETE CASCADE,
    week                text        NOT NULL,
    answer_snippet_id   text        NULL,
    none_needs_it       boolean     NULL,
    answered_at         timestamptz NULL,
    sheet_version       text        NOT NULL DEFAULT 'v4-moment-pick-sheet-v1',
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT v4_moment_pick_sheets_versions CHECK (
        sheet_version = 'v4-moment-pick-sheet-v1'
        AND policy_version = 'take-feedback-policy-v3-universal-dark-v3'
        AND picker_version = 'v4-picker-v1'),
    CONSTRAINT v4_moment_pick_sheets_role CHECK (rater_role IN ('coach', 'founder')),
    CONSTRAINT v4_moment_pick_sheets_slice CHECK (
        slice IN ('unsure', 'random', 'repick')
        AND (slice = 'repick') = (repick_of IS NOT NULL)),
    CONSTRAINT v4_moment_pick_sheets_clips CHECK (
        cardinality(clip_ids) BETWEEN 1 AND 3
        AND (v4_snippet_id IS NULL OR v4_snippet_id = ANY (clip_ids))
        AND (v3_snippet_id IS NULL OR v3_snippet_id = ANY (clip_ids))),
    CONSTRAINT v4_moment_pick_sheets_answer CHECK (
        (answered_at IS NULL)
            = (answer_snippet_id IS NULL AND none_needs_it IS NULL)
        AND (none_needs_it IS NULL OR none_needs_it = true)
        AND NOT (answer_snippet_id IS NOT NULL AND none_needs_it IS NOT NULL)
        AND (answer_snippet_id IS NULL OR answer_snippet_id = ANY (clip_ids)))
);
CREATE UNIQUE INDEX IF NOT EXISTS v4_moment_pick_sheets_once
    ON public.v4_moment_pick_sheets (rater_id, take_session_id, block_id)
    WHERE repick_of IS NULL;
CREATE INDEX IF NOT EXISTS v4_moment_pick_sheets_rater_idx
    ON public.v4_moment_pick_sheets (rater_id, week);
CREATE INDEX IF NOT EXISTS v4_moment_pick_sheets_take_idx
    ON public.v4_moment_pick_sheets (take_session_id);
ALTER TABLE public.v4_moment_pick_sheets ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.v4_surer_sheets (
    id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    rater_id            text        NOT NULL,
    rater_role          text        NOT NULL,
    take_session_id     uuid        NOT NULL,
    block_id            text        NOT NULL,
    said_text           text        NOT NULL,
    new_text            text        NOT NULL,
    varied_quality      text        NOT NULL,
    version_rule        text        NOT NULL,
    slice               text        NOT NULL,
    level               numeric     NULL,
    bar                 numeric     NOT NULL,
    bar_version         text        NOT NULL,
    week                text        NOT NULL,
    answer              text        NULL,
    chosen_text         text        NULL,
    rejected_text       text        NULL,
    answered_at         timestamptz NULL,
    sheet_version       text        NOT NULL DEFAULT 'v4-surer-sheet-v1',
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT v4_surer_sheets_versions CHECK (
        sheet_version = 'v4-surer-sheet-v1'
        AND version_rule = 'surer-pair-v1-lexical'),
    CONSTRAINT v4_surer_sheets_role CHECK (rater_role IN ('coach', 'founder')),
    CONSTRAINT v4_surer_sheets_quality CHECK (varied_quality IN ('filler', 'hedging')),
    CONSTRAINT v4_surer_sheets_texts CHECK (
        length(btrim(said_text)) > 0 AND length(btrim(new_text)) > 0
        AND said_text <> new_text),
    CONSTRAINT v4_surer_sheets_slice CHECK (
        slice IN ('above', 'below', 'random')
        AND (level IS NULL OR level BETWEEN 0 AND 1)
        AND (slice = 'random' OR level IS NOT NULL)
        AND (slice <> 'above' OR level >= bar)
        AND (slice <> 'below' OR level < bar)),
    CONSTRAINT v4_surer_sheets_answer CHECK (
        (answered_at IS NULL) = (answer IS NULL)
        AND (answer IS NULL OR answer IN ('yes', 'no', 'cant_tell'))
        AND chosen_text IS NOT DISTINCT FROM CASE answer
            WHEN 'yes' THEN new_text WHEN 'no' THEN said_text END
        AND rejected_text IS NOT DISTINCT FROM CASE answer
            WHEN 'yes' THEN said_text WHEN 'no' THEN new_text END)
);
CREATE UNIQUE INDEX IF NOT EXISTS v4_surer_sheets_once
    ON public.v4_surer_sheets (rater_id, take_session_id, block_id, varied_quality);
CREATE INDEX IF NOT EXISTS v4_surer_sheets_rater_idx
    ON public.v4_surer_sheets (rater_id, week);
CREATE INDEX IF NOT EXISTS v4_surer_sheets_take_idx
    ON public.v4_surer_sheets (take_session_id);
ALTER TABLE public.v4_surer_sheets ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.v4_moment_pick_sheets IS
    'V4 B1.8 (0453): one block put to one blind rater; the machine''s picks '
    'and the slice are stored, never sent. The founder''s answers are the '
    'golden set (QG4 B). Internal; coach provenance only (L3).';
COMMENT ON TABLE public.v4_surer_sheets IS
    'V4 B1.9 (0453): the speaker''s words beside one machine version, one '
    'blind Yes / No / Can''t tell; a WORDS label and a preference pair. '
    'Slice and level never sent. Training off (M10).';

-- ── The door ───────────────────────────────────────────────────────────────
REVOKE ALL ON TABLE public.v4_moment_pick_sheets FROM PUBLIC;
REVOKE ALL ON TABLE public.v4_surer_sheets FROM PUBLIC;
DO $$
DECLARE
    v_role text;
BEGIN
    FOREACH v_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
            EXECUTE format('REVOKE ALL ON TABLE public.v4_moment_pick_sheets FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON TABLE public.v4_surer_sheets FROM %I', v_role);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        REVOKE ALL ON TABLE public.v4_moment_pick_sheets FROM service_role;
        REVOKE ALL ON TABLE public.v4_surer_sheets FROM service_role;
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.v4_moment_pick_sheets TO service_role;
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.v4_surer_sheets TO service_role;
    END IF;
END $$;

COMMIT;
