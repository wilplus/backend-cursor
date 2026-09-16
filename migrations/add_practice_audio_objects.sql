-- 0334 · Practice recordings become deletable.
--
-- THE HOLE THIS CLOSES (found 2026-09-16, preparing the phase-1 move).
-- The Confident Voice practice route uploads a speaker's attempt to
-- `confidence-practice/<user>/<practice>/…` and keeps the key on
-- confident_voice_practice_attempt.storage_path. But storage deletion in
-- services/data_purge.py only ever deletes targets of kind `r2_object` /
-- `supabase_object`, and those are produced ONLY from
-- processing_audio_objects and processing_orphan_objects. Practice audio was
-- in neither. So purging a speaker removed their practice ROWS and left the
-- recordings in the bucket, with nothing left pointing at them.
--
-- WHY A THIRD TABLE RATHER THAN REUSING EITHER EXISTING ONE.
--   * processing_audio_objects requires `recording_attempt_id NOT NULL` with
--     UNIQUE(recording_attempt_id). A practice attempt is NOT a Take, so it
--     has no row there. Making that column nullable would weaken a lineage
--     invariant that currently holds for every recording in the system, to
--     accommodate one surface that is not a recording attempt at all.
--   * processing_orphan_objects is swept by orphan_audio_cleanup, which
--     DELETES what it finds. Registering live practice audio as an orphan
--     would delete it out from under an open practice.
-- So practice audio gets its own registry, shaped like its siblings, saying
-- exactly what it is. Nothing existing is relaxed.
--
-- DELETION ORDERING. data_purge freezes the inventory BEFORE resolving
-- targets, so a row here is read into the frozen manifest while it still
-- exists. ON DELETE CASCADE is therefore safe: by the time the attempt row
-- goes, the object's coordinates are already captured for the storage delete.
--
-- Additive and inert: nothing reads this table until the practice routes are
-- reachable, and services/data_purge.py degrades to an empty read for a
-- relation that is not present yet, so code and migration may land in either
-- order.

CREATE TABLE IF NOT EXISTS public.processing_practice_objects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL REFERENCES
        public.owner_principals(id) ON DELETE RESTRICT,
    practice_attempt_id UUID NOT NULL REFERENCES
        public.confident_voice_practice_attempt(id) ON DELETE CASCADE,
    storage_provider TEXT NOT NULL CHECK (storage_provider IN ('r2', 'supabase')),
    bucket TEXT NOT NULL,
    object_key TEXT NOT NULL,
    byte_size BIGINT NOT NULL CHECK (byte_size > 0),
    content_type TEXT NOT NULL,
    exact_bytes_sha256 TEXT NOT NULL CHECK (exact_bytes_sha256 ~ '^[0-9a-f]{64}$'),
    -- Stamped by the purge once the object is gone from storage, so a second
    -- run does not try to delete it again. Mirrors the sibling tables.
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- One registry row per stored object, and one per attempt: a second row
    -- for the same attempt would mean an upload nobody can account for.
    UNIQUE (storage_provider, bucket, object_key),
    UNIQUE (practice_attempt_id)
);

-- The purge selects by principal; the sweep (0335) will select by age.
CREATE INDEX IF NOT EXISTS processing_practice_objects_principal_idx
    ON public.processing_practice_objects (acquisition_principal_id)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS processing_practice_objects_created_idx
    ON public.processing_practice_objects (created_at)
    WHERE deleted_at IS NULL;

ALTER TABLE public.processing_practice_objects ENABLE ROW LEVEL SECURITY;
GRANT ALL ON TABLE public.processing_practice_objects TO service_role;

-- The retention sweep's own lookup: closed practices, oldest first, by the
-- time they CLOSED. The table's existing indexes are (owner_user_id,
-- updated_at) and (take_session_id, status), neither of which serves it.
CREATE INDEX IF NOT EXISTS confident_voice_practice_closed_at_idx
    ON public.confident_voice_practice (closed_at)
    WHERE closed_at IS NOT NULL;
