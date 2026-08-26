-- 0298 · immutable guest -> authenticated ownership claim audit.
--
-- A claim is an ownership event, not evidence deletion. The original guest
-- principal remains as an inert alias, the exact source -> target transfer is
-- append-only, and only that audited transaction may rewrite current owner
-- coordinates. Evidence content, decisions and versions remain immutable.

BEGIN;

ALTER TABLE public.owner_principals
    ADD COLUMN IF NOT EXISTS claimed_by_owner_principal_id UUID NULL;

ALTER TABLE public.owner_principals
    DROP CONSTRAINT IF EXISTS owner_principal_identity_check;
ALTER TABLE public.owner_principals
    ADD CONSTRAINT owner_principal_identity_check CHECK (
        (user_id IS NOT NULL
         AND guest_secret_hash IS NULL
         AND claimed_by_owner_principal_id IS NULL)
        OR
        (user_id IS NULL
         AND guest_secret_hash IS NOT NULL
         AND claimed_by_owner_principal_id IS NULL
         AND claimed_at IS NULL)
        OR
        (user_id IS NULL
         AND guest_secret_hash IS NULL
         AND claimed_by_owner_principal_id IS NOT NULL
         AND claimed_at IS NOT NULL)
    );

CREATE TABLE IF NOT EXISTS public.owner_claim_events (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_owner_principal_id UUID NOT NULL,
    target_owner_principal_id UUID NOT NULL,
    claimed_user_id          UUID NOT NULL,
    claim_proof_hash         TEXT NOT NULL,
    idempotency_key          TEXT NOT NULL UNIQUE,
    source_created_at        TIMESTAMPTZ NOT NULL,
    claimed_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (length(claim_proof_hash) = 64)
);

CREATE UNIQUE INDEX IF NOT EXISTS owner_claim_events_source_once_idx
    ON public.owner_claim_events(source_owner_principal_id);
CREATE INDEX IF NOT EXISTS owner_claim_events_target_time_idx
    ON public.owner_claim_events(target_owner_principal_id, claimed_at);

ALTER TABLE public.owner_claim_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.owner_claim_events FROM anon, authenticated;
GRANT ALL ON TABLE public.owner_claim_events TO service_role;

DROP TRIGGER IF EXISTS owner_claim_events_append_only
    ON public.owner_claim_events;
CREATE TRIGGER owner_claim_events_append_only
    BEFORE UPDATE OR DELETE ON public.owner_claim_events
    FOR EACH ROW EXECUTE FUNCTION public.reject_canonical_feedback_mutation();

-- Composite provenance constraints must be checked at transaction commit so
-- the parent and children can move together without a half-transferred graph.
ALTER TABLE public.takes
    DROP CONSTRAINT IF EXISTS take_attempt_coordinates_fk;
ALTER TABLE public.takes
    ADD CONSTRAINT take_attempt_coordinates_fk FOREIGN KEY (
        recording_attempt_id, project_id, owner_principal_id
    ) REFERENCES public.recording_attempts(
        id, project_id, owner_principal_id
    ) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE public.processing_transition_events
    DROP CONSTRAINT IF EXISTS transition_attempt_coordinates_fk;
ALTER TABLE public.processing_transition_events
    ADD CONSTRAINT transition_attempt_coordinates_fk FOREIGN KEY (
        recording_attempt_id, project_id, owner_principal_id
    ) REFERENCES public.recording_attempts(
        id, project_id, owner_principal_id
    ) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;

-- Canonical evidence remains append-only. This single exception accepts an
-- UPDATE only when (a) an immutable claim event named in transaction-local
-- settings proves the exact source and target and (b) owner_principal_id is
-- literally the only changed field.
CREATE OR REPLACE FUNCTION public.reject_canonical_feedback_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    event_id TEXT := current_setting('willab.owner_claim_event_id', true);
    source_id TEXT := current_setting('willab.owner_claim_source', true);
    target_id TEXT := current_setting('willab.owner_claim_target', true);
    old_row JSONB;
    new_row JSONB;
BEGIN
    IF TG_OP = 'UPDATE' AND NULLIF(event_id, '') IS NOT NULL THEN
        old_row := to_jsonb(OLD);
        new_row := to_jsonb(NEW);
        IF old_row ? 'owner_principal_id'
           AND new_row ? 'owner_principal_id'
           AND old_row ->> 'owner_principal_id' = source_id
           AND new_row ->> 'owner_principal_id' = target_id
           AND (old_row - 'owner_principal_id') =
               (new_row - 'owner_principal_id')
           AND EXISTS (
               SELECT 1 FROM public.owner_claim_events event
                WHERE event.id::text = event_id
                  AND event.source_owner_principal_id::text = source_id
                  AND event.target_owner_principal_id::text = target_id
           ) THEN
            RETURN NEW;
        END IF;
    END IF;
    RAISE EXCEPTION 'canonical feedback evidence is append-only';
END;
$$;

CREATE OR REPLACE FUNCTION public.protect_recording_attempt_coordinates()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    event_id TEXT := current_setting('willab.owner_claim_event_id', true);
    source_id TEXT := current_setting('willab.owner_claim_source', true);
    target_id TEXT := current_setting('willab.owner_claim_target', true);
    old_row JSONB;
    new_row JSONB;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'recording attempt provenance is immutable';
    END IF;
    IF TG_OP = 'UPDATE' AND NULLIF(event_id, '') IS NOT NULL THEN
        old_row := to_jsonb(OLD);
        new_row := to_jsonb(NEW);
        IF old_row ->> 'owner_principal_id' = source_id
           AND new_row ->> 'owner_principal_id' = target_id
           AND (old_row - 'owner_principal_id') =
               (new_row - 'owner_principal_id')
           AND EXISTS (
               SELECT 1 FROM public.owner_claim_events event
                WHERE event.id::text = event_id
                  AND event.source_owner_principal_id::text = source_id
                  AND event.target_owner_principal_id::text = target_id
           ) THEN
            RETURN NEW;
        END IF;
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

REVOKE ALL ON FUNCTION public.reject_canonical_feedback_mutation()
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.protect_recording_attempt_coordinates()
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.reject_canonical_feedback_mutation()
    TO service_role;
GRANT EXECUTE ON FUNCTION public.protect_recording_attempt_coordinates()
    TO service_role;

CREATE OR REPLACE FUNCTION public.claim_guest_owner(
    p_owner_principal_id UUID,
    p_guest_secret_hash TEXT,
    p_user_id UUID
) RETURNS public.owner_principals
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    claimed public.owner_principals;
    target public.owner_principals;
    replay public.owner_claim_events;
    claim_event_id UUID := gen_random_uuid();
    proof_hash TEXT;
    claim_key TEXT;
BEGIN
    IF p_user_id IS NULL OR NULLIF(trim(p_guest_secret_hash), '') IS NULL THEN
        RAISE EXCEPTION 'guest owner claim rejected';
    END IF;
    proof_hash := encode(digest(p_guest_secret_hash, 'sha256'), 'hex');
    claim_key := encode(digest(
        p_owner_principal_id::text || ':' || p_user_id::text,
        'sha256'
    ), 'hex');

    SELECT * INTO replay FROM public.owner_claim_events event
     WHERE event.source_owner_principal_id = p_owner_principal_id
       AND event.claimed_user_id = p_user_id
       AND event.claim_proof_hash = proof_hash
       AND event.idempotency_key = claim_key;
    IF replay.id IS NOT NULL THEN
        SELECT * INTO target FROM public.owner_principals owner
         WHERE owner.id = replay.target_owner_principal_id;
        IF target.id IS NULL THEN
            RAISE EXCEPTION 'claimed owner target is unavailable';
        END IF;
        RETURN target;
    END IF;

    SELECT * INTO claimed FROM public.owner_principals owner
     WHERE owner.id = p_owner_principal_id
       AND owner.user_id IS NULL
       AND owner.claimed_by_owner_principal_id IS NULL
       AND owner.guest_secret_hash = p_guest_secret_hash
     FOR UPDATE;
    IF claimed.id IS NULL THEN
        RAISE EXCEPTION 'guest owner claim rejected';
    END IF;

    SELECT * INTO target FROM public.owner_principals owner
     WHERE owner.user_id = p_user_id
     FOR UPDATE;
    IF target.id IS NULL THEN
        target := claimed;
    END IF;

    INSERT INTO public.owner_claim_events (
        id, source_owner_principal_id, target_owner_principal_id,
        claimed_user_id, claim_proof_hash, idempotency_key,
        source_created_at
    ) VALUES (
        claim_event_id, claimed.id, target.id, p_user_id,
        proof_hash, claim_key, claimed.created_at
    );

    IF target.id = claimed.id THEN
        UPDATE public.owner_principals
           SET user_id = p_user_id,
               guest_secret_hash = NULL,
               claimed_at = now()
         WHERE id = claimed.id
        RETURNING * INTO target;
        RETURN target;
    END IF;

    PERFORM set_config(
        'willab.owner_claim_event_id', claim_event_id::text, true);
    PERFORM set_config(
        'willab.owner_claim_source', claimed.id::text, true);
    PERFORM set_config(
        'willab.owner_claim_target', target.id::text, true);

    -- Match Take promotion's lock order (Attempt, then Project) so a signup
    -- racing the final worker cannot create a circular wait or half-transfer.
    PERFORM 1 FROM public.recording_attempts attempt
     WHERE attempt.owner_principal_id = claimed.id
     ORDER BY attempt.id
     FOR UPDATE;

    UPDATE public.projects
       SET owner_principal_id = target.id, updated_at = now()
     WHERE owner_principal_id = claimed.id;
    UPDATE public.v2_sessions
       SET owner_principal_id = target.id, user_id = p_user_id
     WHERE owner_principal_id = claimed.id;
    UPDATE public.rejected_takes
       SET owner_principal_id = target.id
     WHERE owner_principal_id = claimed.id;
    UPDATE public.moment_suggestions
       SET owner_principal_id = target.id
     WHERE owner_principal_id = claimed.id;

    UPDATE public.transcript_versions SET owner_principal_id = target.id
     WHERE owner_principal_id = claimed.id;
    UPDATE public.slides SET owner_principal_id = target.id
     WHERE owner_principal_id = claimed.id;
    UPDATE public.paragraphs SET owner_principal_id = target.id
     WHERE owner_principal_id = claimed.id;
    UPDATE public.evidence_spans SET owner_principal_id = target.id
     WHERE owner_principal_id = claimed.id;
    UPDATE public.acoustic_feature_snapshots
       SET owner_principal_id = target.id
     WHERE owner_principal_id = claimed.id;
    UPDATE public.candidate_sets SET owner_principal_id = target.id
     WHERE owner_principal_id = claimed.id;
    UPDATE public.machine_predictions SET owner_principal_id = target.id
     WHERE owner_principal_id = claimed.id;
    UPDATE public.generation_runs SET owner_principal_id = target.id
     WHERE owner_principal_id = claimed.id;
    UPDATE public.processing_stage_runs SET owner_principal_id = target.id
     WHERE owner_principal_id = claimed.id;

    UPDATE public.takes SET owner_principal_id = target.id
     WHERE owner_principal_id = claimed.id;
    UPDATE public.processing_transition_events
       SET owner_principal_id = target.id
     WHERE owner_principal_id = claimed.id;
    UPDATE public.recording_attempts SET owner_principal_id = target.id
     WHERE owner_principal_id = claimed.id;

    UPDATE public.recording_1
       SET user_id = p_user_id
     WHERE session_v2_id IN (
         SELECT id FROM public.v2_sessions
          WHERE owner_principal_id = target.id AND user_id = p_user_id
     );
    UPDATE public.charisma_snippets
       SET user_id = p_user_id
     WHERE session_id IN (
         SELECT id FROM public.v2_sessions
          WHERE owner_principal_id = target.id AND user_id = p_user_id
     );

    UPDATE public.owner_principals
       SET guest_secret_hash = NULL,
           claimed_by_owner_principal_id = target.id,
           claimed_at = now()
     WHERE id = claimed.id;
    RETURN target;
END;
$$;

REVOKE ALL ON FUNCTION public.claim_guest_owner(UUID, TEXT, UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_guest_owner(UUID, TEXT, UUID)
    TO service_role;

COMMENT ON TABLE public.owner_claim_events IS
    'Immutable guest-origin to authenticated-owner transfer ledger; proof hashes support exact idempotent replay without retaining the supplied credential hash.';
COMMENT ON COLUMN public.owner_principals.claimed_by_owner_principal_id IS
    'For an inert claimed guest alias, the permanent owner principal that now owns its graph.';

COMMIT;
