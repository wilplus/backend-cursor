\set ON_ERROR_STOP on

-- Extra production-coordinate shape required to rehearse the real 0297 Take
-- promotion RPC after the shared minimal MLC-2 prerequisites. Disposable only.

CREATE OR REPLACE FUNCTION public.reject_canonical_feedback_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'canonical rehearsal record is append-only';
END;
$$;

CREATE TABLE IF NOT EXISTS public.v2_sessions (
    id UUID PRIMARY KEY,
    owner_principal_id UUID NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    project_id UUID NULL REFERENCES public.projects(id) ON DELETE RESTRICT,
    canonical_take_index INTEGER NULL
);

CREATE TABLE IF NOT EXISTS public.processing_jobs (
    id UUID PRIMARY KEY
);

ALTER TABLE public.recording_attempts
    ADD COLUMN IF NOT EXISTS upload_idempotency_key TEXT,
    ADD COLUMN IF NOT EXISTS recording_id UUID NULL,
    ADD COLUMN IF NOT EXISTS storage_bucket TEXT NULL,
    ADD COLUMN IF NOT EXISTS storage_key TEXT NULL,
    ADD COLUMN IF NOT EXISTS recording_kind TEXT,
    ADD COLUMN IF NOT EXISTS status TEXT,
    ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS provenance_eligible BOOLEAN NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS ineligibility_reason TEXT NULL,
    ADD COLUMN IF NOT EXISTS last_error JSONB NULL,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS terminal_at TIMESTAMPTZ NULL;

ALTER TABLE public.recording_attempts
    ALTER COLUMN upload_idempotency_key SET NOT NULL,
    ALTER COLUMN recording_kind SET NOT NULL,
    ALTER COLUMN status SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS rehearsal_attempt_upload_idx
    ON public.recording_attempts(project_id, upload_idempotency_key);
CREATE UNIQUE INDEX IF NOT EXISTS rehearsal_attempt_coordinates_idx
    ON public.recording_attempts(id, project_id, owner_principal_id);

ALTER TABLE public.takes
    ADD COLUMN IF NOT EXISTS take_index INTEGER,
    ADD COLUMN IF NOT EXISTS completion_hash TEXT,
    ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE public.takes
    ALTER COLUMN take_index SET NOT NULL,
    ALTER COLUMN completion_hash SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS rehearsal_take_project_index_idx
    ON public.takes(project_id, take_index);
CREATE UNIQUE INDEX IF NOT EXISTS rehearsal_take_coordinates_idx
    ON public.takes(id, project_id, owner_principal_id);
CREATE UNIQUE INDEX IF NOT EXISTS rehearsal_take_attempt_idx
    ON public.takes(recording_attempt_id);
