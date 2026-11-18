-- An owner must not lose an Ideal Text edit merely because they accepted a
-- newer processing-authority receipt after their MLC-3 enrollment was made.
--
-- The released CAS writer deliberately calls require_mlc3_service_access_v2
-- before and after the write.  That is still the authority boundary.  This
-- wrapper repairs only the one recoverable state: the latest enrollment is
-- active for this owner and rollout, but names an older authority receipt.
-- It refreshes that enrollment through the canonical, ownership-checking
-- writer and then delegates the complete text/parts/revision transaction to
-- the unchanged CAS.  Every other authority error still propagates.

BEGIN;

CREATE OR REPLACE FUNCTION public.compare_and_set_user_ideal_edit_v2(
    p_owner_user_id UUID,
    p_arc_id TEXT,
    p_source_document_version INTEGER,
    p_expected_user_text_revision BIGINT,
    p_expected_user_text_sha256 TEXT,
    p_desired_user_text TEXT,
    p_desired_parts_lineage JSONB,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    principal_id UUID;
    authority JSONB;
    enrollment_key TEXT;
BEGIN
    -- Keep the wrapper's authority scope no broader than the CAS it guards:
    -- this user must own this exact Project before enrollment can be renewed.
    SELECT principal.id INTO STRICT principal_id
      FROM public.owner_principals principal
      JOIN public.projects project
        ON project.owner_principal_id = principal.id
     WHERE principal.user_id = p_owner_user_id
       AND project.id::TEXT = p_arc_id;

    BEGIN
        PERFORM public.require_mlc3_service_access_v2(
            principal_id, NULL, NULL
        );
    EXCEPTION WHEN SQLSTATE 'P0001' THEN
        IF SQLERRM <> 'MLC3_ENROLLMENT_AUTHORITY_STALE' THEN
            RAISE;
        END IF;

        -- Bind the renewal key to the current receipt, never to the speaker's
        -- words.  A replay under this authority returns the same enrollment;
        -- a later receipt receives a distinct append-only enrollment revision.
        authority := public.resolve_mlc3_dual_purpose_receipt_v2(principal_id);
        enrollment_key := format(
            'ideal-text-owner-edit:%s:%s',
            principal_id,
            authority->>'receipt_id'
        );
        PERFORM public.ensure_mlc3_service_enrollment_v2(
            principal_id, p_owner_user_id, enrollment_key
        );
    END;

    RETURN public.compare_and_set_user_ideal_edit_v1(
        p_owner_user_id => p_owner_user_id,
        p_arc_id => p_arc_id,
        p_source_document_version => p_source_document_version,
        p_expected_user_text_revision => p_expected_user_text_revision,
        p_expected_user_text_sha256 => p_expected_user_text_sha256,
        p_desired_user_text => p_desired_user_text,
        p_desired_parts_lineage => p_desired_parts_lineage,
        p_idempotency_key => p_idempotency_key
    );
END;
$$;

REVOKE ALL ON FUNCTION public.compare_and_set_user_ideal_edit_v2(
    UUID, TEXT, INTEGER, BIGINT, TEXT, TEXT, JSONB, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.compare_and_set_user_ideal_edit_v2(
    UUID, TEXT, INTEGER, BIGINT, TEXT, TEXT, JSONB, TEXT
) TO service_role;

COMMIT;
