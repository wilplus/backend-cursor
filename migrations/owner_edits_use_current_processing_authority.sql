-- Ordinary owner edits are F1, not the retired MLC-3 coaching service.
-- Keep the complete CAS, capability guards, part lineage and history writer.
-- Replace ONLY its three authority checks (entry, replay, completion) with
-- the existing F1 serving gate plus current Phase-1 processing authority.
-- No rollout, enrollment, purpose, receipt or learning row is changed.
BEGIN;

CREATE OR REPLACE FUNCTION public.require_ideal_text_owner_authority_v1(
    p_owner_principal_id UUID, p_owner_user_id UUID
) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    acquisition_principal UUID;
    authority JSONB;
BEGIN
    PERFORM public.require_mlc3_service_principal_v1(p_owner_principal_id);
    acquisition_principal := public.resolve_phase1_acquisition_principal_v1(
        p_owner_principal_id, p_owner_user_id
    );
    IF acquisition_principal <> p_owner_principal_id THEN
        PERFORM public.require_mlc3_service_principal_v1(acquisition_principal);
    END IF;
    authority := public.get_phase1_processing_authorization_v1(
        acquisition_principal
    );
    IF (authority->>'authorized')::BOOLEAN IS DISTINCT FROM TRUE THEN
        RAISE EXCEPTION '%', COALESCE(
            authority->>'code', 'PROCESSING_AUTHORIZATION_REQUIRED'
        );
    END IF;
    IF (authority->>'pooled_learning_eligible')::BOOLEAN IS DISTINCT FROM FALSE THEN
        RAISE EXCEPTION 'PHASE1_POOLING_INVARIANT_FAILED';
    END IF;
END;
$$;

REVOKE ALL ON FUNCTION public.require_ideal_text_owner_authority_v1(UUID, UUID)
    FROM PUBLIC, anon, authenticated, service_role;

-- Patch the installed CAS rather than duplicate its transaction body. Abort
-- on source drift; a replay recognizes exactly the three replacement checks.
DO $owner_authority$
DECLARE
    definition TEXT;
    old_check TEXT := 'PERFORM public.require_mlc3_service_access_v2(principal,NULL,NULL);';
    new_check TEXT := 'PERFORM public.require_ideal_text_owner_authority_v1(principal,p_owner_user_id);';
    old_count INTEGER;
    new_count INTEGER;
BEGIN
    SELECT pg_get_functiondef(
        'public.compare_and_set_user_ideal_edit_v1(uuid,text,integer,bigint,text,text,jsonb,text)'::regprocedure
    ) INTO definition;
    old_count := (length(definition) - length(replace(definition, old_check, ''))) / length(old_check);
    new_count := (length(definition) - length(replace(definition, new_check, ''))) / length(new_check);
    IF old_count = 3 AND new_count = 0 THEN
        EXECUTE replace(definition, old_check, new_check);
    ELSIF old_count <> 0 OR new_count <> 3 THEN
        RAISE EXCEPTION 'IDEAL_TEXT_OWNER_AUTHORITY_SOURCE_DRIFT';
    END IF;
END;
$owner_authority$;

-- Retain the released RPC door and wire response. Enrollment renewal is no
-- longer an owner-edit side effect; strict F2 writers keep their own gates.
CREATE OR REPLACE FUNCTION public.compare_and_set_user_ideal_edit_v2(
    p_owner_user_id UUID, p_arc_id TEXT, p_source_document_version INTEGER,
    p_expected_user_text_revision BIGINT, p_expected_user_text_sha256 TEXT,
    p_desired_user_text TEXT, p_desired_parts_lineage JSONB,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE sql SECURITY DEFINER VOLATILE SET search_path = public AS $$
    SELECT public.compare_and_set_user_ideal_edit_v1(
        p_owner_user_id, p_arc_id, p_source_document_version,
        p_expected_user_text_revision, p_expected_user_text_sha256,
        p_desired_user_text, p_desired_parts_lineage, p_idempotency_key
    );
$$;

REVOKE ALL ON FUNCTION public.compare_and_set_user_ideal_edit_v2(
    UUID, TEXT, INTEGER, BIGINT, TEXT, TEXT, JSONB, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.compare_and_set_user_ideal_edit_v2(
    UUID, TEXT, INTEGER, BIGINT, TEXT, TEXT, JSONB, TEXT
) TO service_role;
COMMIT;
