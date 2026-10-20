-- a_confidence_event_without_a_clip_is_given_up (0487)
--
-- A confidence outbox event whose Take has no clip a blind rater could judge
-- can never be finalized: a candidate set must select one clip
-- (ml_candidate_sets.selected_count > 0), and the Take's snippet rows are
-- written before it is promoted, so the frame the worker builds is the same
-- on every attempt. Production (founder's query, 2026-10-20): two such
-- events, NoEligibleConfidenceClip:confidence_frame_failed, retried 30,903
-- times since 2026-10-08. #1189 stopped new ones being opened and parked the
-- two for a week at a time; this gives them, and any later one, an end.
--
-- THE TERMINAL STATE. Two nullable columns on ml_outbox_events:
-- abandoned_at and abandon_reason_code. An abandoned event is unprocessed
-- (it has no canonical event and no frame, so processed_at stays null and
-- the "processed without frame" health count stays honest), unlocked, and
-- has available_at = 'infinity'. Every claim function filters
-- available_at <= now(), so no claim, this surface's or the shared one,
-- ever offers it again, and none of them had to be re-issued here. A CHECK
-- holds the three together, so a claim cannot lock an abandoned row.
-- Its last_error_code and attempt_count stay as the record of what happened.
-- 'infinity' is a valid timestamptz but not every client maps it (psycopg2
-- reads datetime.max, psycopg3 refuses by default): no application code
-- selects an outbox row's available_at; the RPC's returned row reaches
-- Python through PostgREST as JSON text and is not parsed as a time.
--
-- ONE WAY IN. abandon_mlc2_confidence_outbox_event_v1, for the worker that
-- holds the lease (as fail_mlc2_outbox_event_v1), on the confidence surface
-- only, and only for a reason on its allow-list: 'no_eligible_clip'. Any
-- other failure keeps retrying through fail_mlc2_outbox_event_v1.
--
-- THE TWO STUCK EVENTS. Given up here, once: unprocessed, unlocked
-- confidence events whose last failure is exactly
-- 'NoEligibleConfidenceClip:confidence_frame_failed'. Re-running matches
-- nothing (abandoned_at IS NULL).
--
-- Idempotent + additive: ADD COLUMN IF NOT EXISTS, the constraint added
-- only when absent, CREATE OR REPLACE for the function. Nothing dropped, no
-- row deleted, no env var. The code before this migration never reads the
-- columns; the code after it falls back to a week's wait if the function is
-- missing, so either order of migration and deploy is safe.

ALTER TABLE public.ml_outbox_events
    ADD COLUMN IF NOT EXISTS abandoned_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS abandon_reason_code TEXT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'ml_outbox_abandon_check'
           AND conrelid = 'public.ml_outbox_events'::regclass
    ) THEN
        ALTER TABLE public.ml_outbox_events
            ADD CONSTRAINT ml_outbox_abandon_check CHECK (
                (abandoned_at IS NULL AND abandon_reason_code IS NULL)
                OR (abandoned_at IS NOT NULL
                    AND abandon_reason_code IN ('no_eligible_clip')
                    AND processed_at IS NULL
                    AND locked_by IS NULL
                    AND available_at = 'infinity'::timestamptz)
            ) NOT VALID;
    END IF;
END;
$$;

-- Outside review (2026-10-20): add NOT VALID, then validate, so the scan
-- runs under SHARE UPDATE EXCLUSIVE. The runner wraps this file in one
-- transaction, so the ADD's lock is held to commit anyway; the table is
-- small and every existing row passes (the new columns are null). A
-- second run validates an already-valid constraint, which is a no-op.
ALTER TABLE public.ml_outbox_events
    VALIDATE CONSTRAINT ml_outbox_abandon_check;

CREATE OR REPLACE FUNCTION public.abandon_mlc2_confidence_outbox_event_v1(
    p_outbox_event_id UUID,
    p_worker_id TEXT,
    p_error_code TEXT,
    p_reason_code TEXT
) RETURNS public.ml_outbox_events
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    outbox_event public.ml_outbox_events;
BEGIN
    IF p_reason_code IS DISTINCT FROM 'no_eligible_clip' THEN
        RAISE EXCEPTION 'confidence outbox abandon reason is not terminal';
    END IF;
    UPDATE public.ml_outbox_events
       SET locked_by = NULL,
           lease_expires_at = NULL,
           last_error_code = left(COALESCE(NULLIF(btrim(p_error_code), ''),
                                           p_reason_code), 120),
           last_error_at = now(),
           available_at = 'infinity'::timestamptz,
           abandoned_at = now(),
           abandon_reason_code = p_reason_code
     WHERE id = p_outbox_event_id
       AND learning_surface_id = 'confidence_classification'
       AND event_type = 'confidence_take_ready'
       AND processed_at IS NULL
       AND abandoned_at IS NULL
       AND locked_by = p_worker_id
    RETURNING * INTO outbox_event;
    IF outbox_event.id IS NULL THEN
        RAISE EXCEPTION 'outbox abandon lease is not held by worker';
    END IF;
    RETURN outbox_event;
END;
$$;

REVOKE ALL ON FUNCTION public.abandon_mlc2_confidence_outbox_event_v1(
    UUID, TEXT, TEXT, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.abandon_mlc2_confidence_outbox_event_v1(
    UUID, TEXT, TEXT, TEXT
) TO service_role;

UPDATE public.ml_outbox_events
   SET available_at = 'infinity'::timestamptz,
       abandoned_at = now(),
       abandon_reason_code = 'no_eligible_clip'
 WHERE learning_surface_id = 'confidence_classification'
   AND event_type = 'confidence_take_ready'
   AND processed_at IS NULL
   AND abandoned_at IS NULL
   AND locked_by IS NULL
   AND last_error_code = 'NoEligibleConfidenceClip:confidence_frame_failed';

COMMENT ON COLUMN public.ml_outbox_events.abandoned_at IS
    'When an event that can never be finalized was given up; it is then never claimed again (available_at = infinity). Null for every other event.';
COMMENT ON COLUMN public.ml_outbox_events.abandon_reason_code IS
    'Why the event was given up; allow-listed by ml_outbox_abandon_check.';
