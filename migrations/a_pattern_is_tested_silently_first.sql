-- A pattern is tested silently first (founder 2026-09-28, D2 + D3; step 4 of
-- the exercise routing plan).
--
-- THE SHADOW STAGE. The speaking error library had two states: `observed` (a
-- person named it, no code finds it) and `detected` (code finds it, and it
-- routes exercises). D3 puts a stage between them: `shadow` — a detector
-- exists and runs on real Takes, its verdicts are logged, and it routes
-- NOTHING. Every routing path reads `status = 'detected'` and nothing else, so
-- a shadow cue is inert by construction; promotion to `detected` stays a
-- separate, deliberate migration once its verdicts have been checked against
-- coaches' independent judgments.
--
-- THE FIRST SHADOW CUES (D2): three spoken-word habits, read from the clip's
-- transcript. Their definitions below are written from the thresholds in
-- services/verbal_cues.py (VERBAL_CUES_VERSION), not from an intention. v1 is
-- English only: English audio is transcribed with a prompt that keeps "um" and
-- "uh", other languages are not, so a filler count on them would read "none"
-- where fillers were simply never written down.
--
-- THE LOG. verbal_cue_shadow_observations holds one verdict per (clip, cue,
-- detector version), fired or not, with the counts behind it. It serves no
-- user and no dataset (CHECKs below), is written insert-once, and is never
-- changed. Nothing here is a label, a training input, or shown to anyone but
-- the team.
--
-- Additive except the two CHECKs on speaking_error, which are widened (every
-- existing row still satisfies them). Idempotent. No env var.

BEGIN;

ALTER TABLE public.speaking_error
    DROP CONSTRAINT IF EXISTS speaking_error_status_check;
ALTER TABLE public.speaking_error
    ADD CONSTRAINT speaking_error_status_check
    CHECK (status IN ('observed', 'shadow', 'detected'));

ALTER TABLE public.speaking_error
    DROP CONSTRAINT IF EXISTS speaking_error_detected_needs_detector;
ALTER TABLE public.speaking_error
    ADD CONSTRAINT speaking_error_detected_needs_detector
    CHECK (status NOT IN ('detected', 'shadow') OR detector_ref IS NOT NULL);

INSERT INTO public.speaking_error (
    error_id, label, definition, asks, status, detector_ref
) VALUES
(
    'filler_cluster',
    'Filler cluster',
    'Hesitation sounds gather in one passage. Counted on the clip''s '
    'transcript as the English hesitation tokens (um, uh, erm, hmm and their '
    'lengthenings): at least 2 of them, and at least 5 per 100 words. English '
    'transcripts only, because only English audio is transcribed with them '
    'kept. Words that are sometimes fillers ("like", "so", "you know") are not '
    'counted.',
    'Did hesitation sounds gather in this passage?',
    'shadow',
    'verbal_cues:filler_cluster'
),
(
    'hedging',
    'Hedging',
    'The passage softens its own claims. Counted on the clip''s transcript as '
    'the unambiguous English hedges in services/verbal_markers.py ("I think", '
    '"sort of", "maybe", "probably" and the like): at least 2 of them. Modal '
    'verbs and other words with common non-hedging uses ("might", "could", '
    '"about") are not counted. English only.',
    'Did the speaker soften their own claims in this passage?',
    'shadow',
    'verbal_cues:hedging'
),
(
    'restart_repair',
    'Restarts',
    'The speaker starts a word again. Counted on the clip''s transcript as the '
    'same word said twice in a row with nothing between ("we we", "the the"): '
    'at least 2 such repeats. English only in this version.',
    'Did the speaker restart words in this passage?',
    'shadow',
    'verbal_cues:restart_repair'
)
ON CONFLICT (error_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.verbal_cue_shadow_observations (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    take_session_id   TEXT        NOT NULL CHECK (length(take_session_id) > 0),
    snippet_id        TEXT        NOT NULL CHECK (length(snippet_id) > 0),
    recording_id      TEXT        NULL,
    error_id          TEXT        NOT NULL
        REFERENCES public.speaking_error(error_id) ON DELETE RESTRICT,
    detector_version  TEXT        NOT NULL CHECK (length(detector_version) > 0),
    language          TEXT        NOT NULL CHECK (length(language) > 0),
    fired             BOOLEAN     NOT NULL,
    measurements      JSONB       NOT NULL CHECK (jsonb_typeof(measurements) = 'object'),
    serves_user       BOOLEAN     NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible  BOOLEAN     NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT verbal_cue_shadow_unit UNIQUE (snippet_id, error_id, detector_version)
);

CREATE INDEX IF NOT EXISTS idx_verbal_cue_shadow_take
    ON public.verbal_cue_shadow_observations (take_session_id);
CREATE INDEX IF NOT EXISTS idx_verbal_cue_shadow_error
    ON public.verbal_cue_shadow_observations (error_id, detector_version);

ALTER TABLE public.verbal_cue_shadow_observations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.verbal_cue_shadow_observations FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.verbal_cue_shadow_observations FROM service_role;
GRANT SELECT, DELETE ON public.verbal_cue_shadow_observations TO service_role;

CREATE OR REPLACE FUNCTION public.reject_verbal_cue_shadow_update_v1()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public
AS $$
BEGIN
    RAISE EXCEPTION 'VERBAL_CUE_SHADOW_IMMUTABLE';
END;
$$;
REVOKE ALL ON FUNCTION public.reject_verbal_cue_shadow_update_v1()
    FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS verbal_cue_shadow_immutable
    ON public.verbal_cue_shadow_observations;
CREATE TRIGGER verbal_cue_shadow_immutable
    BEFORE UPDATE ON public.verbal_cue_shadow_observations
    FOR EACH ROW EXECUTE FUNCTION public.reject_verbal_cue_shadow_update_v1();

-- One Take's verdicts in one call. Insert-once per (clip, cue, version): a
-- retried job writes nothing new. Only a cue the library holds as `shadow` or
-- `detected` may be logged — a verdict about a name with no detector behind
-- it would be a verdict about nothing. Returns how many rows were new.
CREATE OR REPLACE FUNCTION public.record_verbal_cue_shadow_v1(p_rows JSONB)
RETURNS INTEGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    item JSONB;
    added INTEGER := 0;
    n INTEGER;
BEGIN
    IF p_rows IS NULL OR jsonb_typeof(p_rows) <> 'array' THEN
        RAISE EXCEPTION 'VERBAL_CUE_SHADOW_INPUT_INVALID';
    END IF;
    FOR item IN SELECT value FROM jsonb_array_elements(p_rows) LOOP
        IF jsonb_typeof(item) <> 'object'
           OR COALESCE(btrim(item->>'take_session_id'), '') = ''
           OR COALESCE(btrim(item->>'snippet_id'), '') = ''
           OR COALESCE(btrim(item->>'error_id'), '') = ''
           OR COALESCE(btrim(item->>'detector_version'), '') = ''
           OR COALESCE(btrim(item->>'language'), '') = ''
           OR jsonb_typeof(item->'fired') IS DISTINCT FROM 'boolean'
           OR jsonb_typeof(item->'measurements') IS DISTINCT FROM 'object'
        THEN
            RAISE EXCEPTION 'VERBAL_CUE_SHADOW_INPUT_INVALID';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM public.speaking_error
             WHERE error_id = item->>'error_id'
               AND status IN ('shadow', 'detected')
        ) THEN
            RAISE EXCEPTION 'VERBAL_CUE_SHADOW_CUE_NOT_MEASURED';
        END IF;
        INSERT INTO public.verbal_cue_shadow_observations (
            take_session_id, snippet_id, recording_id, error_id,
            detector_version, language, fired, measurements
        ) VALUES (
            item->>'take_session_id', item->>'snippet_id',
            NULLIF(item->>'recording_id', ''), item->>'error_id',
            item->>'detector_version', item->>'language',
            (item->>'fired')::boolean, item->'measurements'
        )
        ON CONFLICT (snippet_id, error_id, detector_version) DO NOTHING;
        GET DIAGNOSTICS n = ROW_COUNT;
        added := added + n;
    END LOOP;
    RETURN added;
END;
$$;

REVOKE ALL ON FUNCTION public.record_verbal_cue_shadow_v1(JSONB)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_verbal_cue_shadow_v1(JSONB) TO service_role;

COMMENT ON TABLE public.verbal_cue_shadow_observations IS
    'Silent verdicts of shadow-stage detectors, one per (clip, cue, detector '
    'version), fired or not, with the counts behind them (founder 2026-09-28, '
    'D3). Serves no user and no dataset; routes nothing.';

COMMIT;
