-- 0297 · canonical RecordingAttempt -> successful Take boundary.
--
-- Additive parity migration. v2_sessions remains the compatibility row used
-- by existing product reads. A recording_attempt exists as soon as durable
-- audio and ownership coordinates exist; a canonical take is minted only by
-- successful terminal promotion. Failed attempts retain their recording and
-- never consume a canonical project Take ordinal.

BEGIN;

ALTER TABLE public.v2_sessions
    ADD COLUMN IF NOT EXISTS canonical_take_index INTEGER NULL CHECK (
        canonical_take_index IS NULL OR canonical_take_index > 0
    );

CREATE UNIQUE INDEX IF NOT EXISTS v2_sessions_project_canonical_take_idx
    ON public.v2_sessions(project_id, canonical_take_index)
    WHERE project_id IS NOT NULL AND canonical_take_index IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.recording_attempts (
    id                       UUID PRIMARY KEY
        REFERENCES public.v2_sessions(id) ON DELETE RESTRICT,
    owner_principal_id       UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    project_id               UUID NOT NULL
        REFERENCES public.projects(id) ON DELETE RESTRICT,
    upload_idempotency_key   TEXT NOT NULL,
    recording_id             UUID NULL,
    storage_bucket           TEXT NULL,
    storage_key              TEXT NULL,
    recording_kind           TEXT NOT NULL CHECK (
        recording_kind IN ('spoken', 'read')
    ),
    status                   TEXT NOT NULL CHECK (status IN (
        'received', 'processing', 'retryable', 'succeeded', 'failed',
        'failed_ideal_text_unconfirmed'
    )),
    attempt_count            INTEGER NOT NULL DEFAULT 1 CHECK (
        attempt_count > 0
    ),
    provenance_eligible      BOOLEAN NOT NULL DEFAULT true,
    ineligibility_reason     TEXT NULL,
    last_error               JSONB NULL,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    terminal_at              TIMESTAMPTZ NULL,
    CONSTRAINT recording_attempt_terminal_check CHECK (
        (status IN ('succeeded', 'failed',
                    'failed_ideal_text_unconfirmed')
         AND terminal_at IS NOT NULL)
        OR (status IN ('received', 'processing', 'retryable')
            AND terminal_at IS NULL)
    ),
    UNIQUE (project_id, upload_idempotency_key),
    UNIQUE (id, project_id, owner_principal_id)
);

CREATE TABLE IF NOT EXISTS public.takes (
    id                       UUID PRIMARY KEY
        REFERENCES public.v2_sessions(id) ON DELETE RESTRICT,
    recording_attempt_id     UUID NOT NULL UNIQUE,
    owner_principal_id       UUID NOT NULL,
    project_id               UUID NOT NULL,
    take_index               INTEGER NOT NULL CHECK (take_index > 0),
    completion_hash          TEXT NOT NULL,
    completed_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT take_identity_matches_attempt CHECK (
        id = recording_attempt_id
    ),
    CONSTRAINT take_attempt_coordinates_fk FOREIGN KEY (
        recording_attempt_id, project_id, owner_principal_id
    ) REFERENCES public.recording_attempts(
        id, project_id, owner_principal_id
    ) ON DELETE RESTRICT,
    UNIQUE (project_id, take_index),
    UNIQUE (id, project_id, owner_principal_id)
);

CREATE TABLE IF NOT EXISTS public.processing_transition_events (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recording_attempt_id     UUID NOT NULL
        REFERENCES public.recording_attempts(id) ON DELETE RESTRICT,
    processing_job_id        UUID NULL
        REFERENCES public.processing_jobs(id) ON DELETE SET NULL,
    owner_principal_id       UUID NOT NULL,
    project_id               UUID NOT NULL,
    from_status              TEXT NULL,
    to_status                TEXT NOT NULL CHECK (to_status IN (
        'received', 'processing', 'retryable', 'succeeded', 'failed',
        'failed_ideal_text_unconfirmed'
    )),
    stage                    TEXT NOT NULL,
    attempt_count            INTEGER NOT NULL CHECK (attempt_count > 0),
    input_hash               TEXT NOT NULL,
    output_hash              TEXT NULL,
    error                    JSONB NULL,
    idempotency_key          TEXT NOT NULL UNIQUE,
    occurred_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT transition_attempt_coordinates_fk FOREIGN KEY (
        recording_attempt_id, project_id, owner_principal_id
    ) REFERENCES public.recording_attempts(
        id, project_id, owner_principal_id
    ) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS recording_attempts_owner_created_idx
    ON public.recording_attempts(owner_principal_id, created_at DESC);
CREATE INDEX IF NOT EXISTS recording_attempts_project_status_idx
    ON public.recording_attempts(project_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS takes_owner_completed_idx
    ON public.takes(owner_principal_id, completed_at DESC);
CREATE INDEX IF NOT EXISTS processing_transitions_attempt_time_idx
    ON public.processing_transition_events(
        recording_attempt_id, occurred_at, id
    );
CREATE INDEX IF NOT EXISTS processing_transitions_job_time_idx
    ON public.processing_transition_events(processing_job_id, occurred_at)
    WHERE processing_job_id IS NOT NULL;

ALTER TABLE public.recording_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.takes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.processing_transition_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.recording_attempts FROM anon, authenticated;
REVOKE ALL ON TABLE public.takes FROM anon, authenticated;
REVOKE ALL ON TABLE public.processing_transition_events
    FROM anon, authenticated;
GRANT ALL ON TABLE public.recording_attempts TO service_role;
GRANT ALL ON TABLE public.takes TO service_role;
GRANT ALL ON TABLE public.processing_transition_events TO service_role;

DROP TRIGGER IF EXISTS takes_append_only ON public.takes;
CREATE TRIGGER takes_append_only
    BEFORE UPDATE OR DELETE ON public.takes
    FOR EACH ROW EXECUTE FUNCTION public.reject_canonical_feedback_mutation();
DROP TRIGGER IF EXISTS processing_transition_events_append_only
    ON public.processing_transition_events;
CREATE TRIGGER processing_transition_events_append_only
    BEFORE UPDATE OR DELETE ON public.processing_transition_events
    FOR EACH ROW EXECUTE FUNCTION public.reject_canonical_feedback_mutation();

CREATE OR REPLACE FUNCTION public.protect_recording_attempt_coordinates()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'recording attempt provenance is immutable';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.owner_principal_id IS DISTINCT FROM OLD.owner_principal_id
       OR NEW.project_id IS DISTINCT FROM OLD.project_id
       OR NEW.upload_idempotency_key IS DISTINCT FROM
          OLD.upload_idempotency_key
       OR NEW.recording_id IS DISTINCT FROM OLD.recording_id
       OR NEW.storage_bucket IS DISTINCT FROM OLD.storage_bucket
       OR NEW.storage_key IS DISTINCT FROM OLD.storage_key
       OR NEW.recording_kind IS DISTINCT FROM OLD.recording_kind
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.provenance_eligible IS DISTINCT FROM OLD.provenance_eligible
       OR NEW.ineligibility_reason IS DISTINCT FROM OLD.ineligibility_reason
    THEN
        RAISE EXCEPTION 'recording attempt provenance is immutable';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS recording_attempt_coordinates_immutable
    ON public.recording_attempts;
CREATE TRIGGER recording_attempt_coordinates_immutable
    BEFORE UPDATE OR DELETE ON public.recording_attempts
    FOR EACH ROW EXECUTE FUNCTION public.protect_recording_attempt_coordinates();

CREATE OR REPLACE FUNCTION public.register_recording_attempt_v1(
    p_attempt_id UUID,
    p_owner_principal_id UUID,
    p_project_id UUID,
    p_upload_idempotency_key TEXT,
    p_recording_id UUID,
    p_storage_bucket TEXT,
    p_storage_key TEXT,
    p_recording_kind TEXT,
    p_input_hash TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    session_row public.v2_sessions%ROWTYPE;
    existing public.recording_attempts%ROWTYPE;
BEGIN
    IF NULLIF(trim(p_upload_idempotency_key), '') IS NULL
       OR NULLIF(trim(p_input_hash), '') IS NULL
       OR p_recording_kind NOT IN ('spoken', 'read') THEN
        RAISE EXCEPTION 'recording attempt payload is incomplete';
    END IF;
    SELECT * INTO session_row FROM public.v2_sessions
     WHERE id = p_attempt_id AND project_id = p_project_id
       AND owner_principal_id = p_owner_principal_id
     FOR SHARE;
    IF session_row.id IS NULL OR NOT EXISTS (
        SELECT 1 FROM public.projects project
         WHERE project.id = p_project_id
           AND project.owner_principal_id = p_owner_principal_id
    ) THEN
        RAISE EXCEPTION 'recording attempt ownership rejected';
    END IF;
    SELECT * INTO existing FROM public.recording_attempts row
     WHERE row.project_id = p_project_id
       AND row.upload_idempotency_key = p_upload_idempotency_key;
    IF existing.id IS NOT NULL THEN
        IF existing.id IS DISTINCT FROM p_attempt_id
           OR existing.owner_principal_id IS DISTINCT FROM
              p_owner_principal_id
           OR existing.recording_id IS DISTINCT FROM p_recording_id
           OR existing.storage_bucket IS DISTINCT FROM p_storage_bucket
           OR existing.storage_key IS DISTINCT FROM p_storage_key
           OR existing.recording_kind IS DISTINCT FROM p_recording_kind THEN
            RAISE EXCEPTION 'recording attempt idempotency conflict';
        END IF;
        RETURN jsonb_build_object(
            'recording_attempt_id', existing.id,
            'status', existing.status,
            'replayed', true
        );
    END IF;
    INSERT INTO public.recording_attempts (
        id, owner_principal_id, project_id, upload_idempotency_key,
        recording_id, storage_bucket, storage_key, recording_kind, status
    ) VALUES (
        p_attempt_id, p_owner_principal_id, p_project_id,
        p_upload_idempotency_key, p_recording_id, p_storage_bucket,
        p_storage_key, p_recording_kind, 'received'
    );
    INSERT INTO public.processing_transition_events (
        recording_attempt_id, owner_principal_id, project_id,
        from_status, to_status, stage, attempt_count, input_hash,
        idempotency_key
    ) VALUES (
        p_attempt_id, p_owner_principal_id, p_project_id,
        NULL, 'received', 'upload', 1, p_input_hash,
        'recording-attempt:' || p_attempt_id::text || ':received'
    );
    RETURN jsonb_build_object(
        'recording_attempt_id', p_attempt_id,
        'status', 'received',
        'replayed', false
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.record_processing_transition_v1(
    p_recording_attempt_id UUID,
    p_processing_job_id UUID,
    p_to_status TEXT,
    p_stage TEXT,
    p_attempt_count INTEGER,
    p_input_hash TEXT,
    p_output_hash TEXT,
    p_error JSONB,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    attempt public.recording_attempts%ROWTYPE;
    existing public.processing_transition_events%ROWTYPE;
BEGIN
    IF p_to_status NOT IN (
        'received', 'processing', 'retryable', 'succeeded', 'failed',
        'failed_ideal_text_unconfirmed'
    ) OR p_attempt_count < 1
      OR NULLIF(trim(p_stage), '') IS NULL
      OR NULLIF(trim(p_input_hash), '') IS NULL
      OR NULLIF(trim(p_idempotency_key), '') IS NULL THEN
        RAISE EXCEPTION 'processing transition payload is incomplete';
    END IF;
    SELECT * INTO attempt FROM public.recording_attempts row
     WHERE row.id = p_recording_attempt_id FOR UPDATE;
    IF attempt.id IS NULL THEN
        RAISE EXCEPTION 'recording attempt not found';
    END IF;
    SELECT * INTO existing FROM public.processing_transition_events row
     WHERE row.idempotency_key = p_idempotency_key;
    IF existing.id IS NOT NULL THEN
        IF existing.recording_attempt_id IS DISTINCT FROM
              p_recording_attempt_id
           OR existing.to_status IS DISTINCT FROM p_to_status
           OR existing.stage IS DISTINCT FROM p_stage
           OR existing.attempt_count IS DISTINCT FROM p_attempt_count
           OR existing.input_hash IS DISTINCT FROM p_input_hash THEN
            RAISE EXCEPTION 'processing transition idempotency conflict';
        END IF;
        RETURN jsonb_build_object(
            'transition_id', existing.id,
            'status', existing.to_status,
            'replayed', true
        );
    END IF;
    IF attempt.status IN (
        'succeeded', 'failed', 'failed_ideal_text_unconfirmed'
    ) AND attempt.status IS DISTINCT FROM p_to_status
      AND NOT (
          attempt.status = 'failed'
          AND p_to_status = 'processing'
          AND p_stage = 'manual_retry'
      ) AND NOT (
          attempt.status = 'failed_ideal_text_unconfirmed'
          AND p_to_status = 'processing'
          AND p_stage = 'ideal_text_retry'
      ) THEN
        RAISE EXCEPTION 'terminal recording attempt is immutable';
    END IF;
    INSERT INTO public.processing_transition_events (
        recording_attempt_id, processing_job_id, owner_principal_id,
        project_id, from_status, to_status, stage, attempt_count,
        input_hash, output_hash, error, idempotency_key
    ) VALUES (
        attempt.id, p_processing_job_id, attempt.owner_principal_id,
        attempt.project_id, attempt.status, p_to_status, p_stage,
        p_attempt_count, p_input_hash, p_output_hash, p_error,
        p_idempotency_key
    ) RETURNING * INTO existing;
    UPDATE public.recording_attempts
       SET status = p_to_status,
           attempt_count = GREATEST(attempt_count, p_attempt_count),
           last_error = p_error,
           terminal_at = CASE WHEN p_to_status IN (
               'succeeded', 'failed', 'failed_ideal_text_unconfirmed'
           ) THEN now() ELSE NULL END
     WHERE id = attempt.id;
    RETURN jsonb_build_object(
        'transition_id', existing.id,
        'status', p_to_status,
        'replayed', false
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.promote_recording_attempt_to_take_v1(
    p_recording_attempt_id UUID,
    p_completion_hash TEXT,
    p_processing_job_id UUID,
    p_attempt_count INTEGER,
    p_input_hash TEXT,
    p_output_hash TEXT,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    attempt public.recording_attempts%ROWTYPE;
    existing public.takes%ROWTYPE;
    next_index INTEGER;
BEGIN
    IF NULLIF(trim(p_completion_hash), '') IS NULL
       OR NULLIF(trim(p_input_hash), '') IS NULL
       OR NULLIF(trim(p_idempotency_key), '') IS NULL
       OR p_attempt_count < 1 THEN
        RAISE EXCEPTION 'Take promotion payload is incomplete';
    END IF;
    SELECT * INTO attempt FROM public.recording_attempts row
     WHERE row.id = p_recording_attempt_id FOR UPDATE;
    IF attempt.id IS NULL OR attempt.recording_kind <> 'spoken' THEN
        RAISE EXCEPTION 'only a spoken recording attempt can become a Take';
    END IF;
    SELECT * INTO existing FROM public.takes row
     WHERE row.recording_attempt_id = attempt.id;
    IF existing.id IS NOT NULL THEN
        IF existing.completion_hash IS DISTINCT FROM p_completion_hash THEN
            RAISE EXCEPTION 'Take promotion idempotency conflict';
        END IF;
        RETURN jsonb_build_object(
            'take_id', existing.id,
            'take_index', existing.take_index,
            'replayed', true
        );
    END IF;
    PERFORM 1 FROM public.projects project
     WHERE project.id = attempt.project_id
       AND project.owner_principal_id = attempt.owner_principal_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Take promotion ownership rejected';
    END IF;
    SELECT COALESCE(max(row.take_index), 0) + 1 INTO next_index
      FROM public.takes row WHERE row.project_id = attempt.project_id;
    INSERT INTO public.takes (
        id, recording_attempt_id, owner_principal_id, project_id,
        take_index, completion_hash
    ) VALUES (
        attempt.id, attempt.id, attempt.owner_principal_id,
        attempt.project_id, next_index, p_completion_hash
    ) RETURNING * INTO existing;
    UPDATE public.v2_sessions
       SET canonical_take_index = next_index
     WHERE id = attempt.id AND project_id = attempt.project_id
       AND owner_principal_id = attempt.owner_principal_id;
    PERFORM public.record_processing_transition_v1(
        attempt.id, p_processing_job_id, 'succeeded', 'complete',
        p_attempt_count, p_input_hash, p_output_hash, NULL,
        p_idempotency_key
    );
    RETURN jsonb_build_object(
        'take_id', existing.id,
        'take_index', existing.take_index,
        'replayed', false
    );
END;
$$;

REVOKE ALL ON FUNCTION public.protect_recording_attempt_coordinates()
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.register_recording_attempt_v1(
    UUID, UUID, UUID, TEXT, UUID, TEXT, TEXT, TEXT, TEXT
) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.record_processing_transition_v1(
    UUID, UUID, TEXT, TEXT, INTEGER, TEXT, TEXT, JSONB, TEXT
) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.promote_recording_attempt_to_take_v1(
    UUID, TEXT, UUID, INTEGER, TEXT, TEXT, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.register_recording_attempt_v1(
    UUID, UUID, UUID, TEXT, UUID, TEXT, TEXT, TEXT, TEXT
) TO service_role;
GRANT EXECUTE ON FUNCTION public.record_processing_transition_v1(
    UUID, UUID, TEXT, TEXT, INTEGER, TEXT, TEXT, JSONB, TEXT
) TO service_role;
GRANT EXECUTE ON FUNCTION public.promote_recording_attempt_to_take_v1(
    UUID, TEXT, UUID, INTEGER, TEXT, TEXT, TEXT
) TO service_role;

COMMENT ON TABLE public.recording_attempts IS
    'Durable upload/processing identity. Failed attempts retain audio and never consume a canonical Take ordinal.';
COMMENT ON TABLE public.takes IS
    'Successfully processed spoken Takes only, with contiguous project-scoped ordinals.';
COMMENT ON TABLE public.processing_transition_events IS
    'Append-only lifecycle events; current job/attempt status is a read model, never the audit history.';

COMMIT;
