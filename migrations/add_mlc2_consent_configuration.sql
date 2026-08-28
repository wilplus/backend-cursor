-- 0306 · MLC-2 Slice 6A founder consent configuration and status contracts.
--
-- This migration adds service-role-only configuration/status RPCs. It seeds no
-- Product/legal approval, creates no consent, and activates no learning writer.

BEGIN;

CREATE OR REPLACE FUNCTION public.configure_mlc2_consent_policy_v1(
    p_approval_reference TEXT,
    p_approved_copy_sha256 TEXT,
    p_onboarding_copy TEXT,
    p_consent_policy_version TEXT,
    p_terms_version TEXT,
    p_privacy_policy_version TEXT,
    p_approving_authority TEXT,
    p_approved_at TIMESTAMPTZ,
    p_jurisdictions TEXT[],
    p_article_9_treatment TEXT,
    p_evidence_object_key TEXT,
    p_evidence_sha256 TEXT,
    p_active_from TIMESTAMPTZ
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    approval public.ml_product_legal_approvals;
    policy public.ml_consent_policies;
BEGIN
    IF NULLIF(btrim(p_approval_reference), '') IS NULL
       OR NULLIF(btrim(p_consent_policy_version), '') IS NULL
       OR NULLIF(btrim(p_onboarding_copy), '') IS NULL
       OR NULLIF(btrim(p_approving_authority), '') IS NULL
       OR NULLIF(btrim(p_evidence_object_key), '') IS NULL
       OR cardinality(p_jurisdictions) < 1 THEN
        RAISE EXCEPTION 'complete Product/legal consent configuration is required';
    END IF;
    IF length(p_approved_copy_sha256) <> 64
       OR encode(digest(convert_to(p_onboarding_copy, 'UTF8'), 'sha256'), 'hex')
          <> lower(p_approved_copy_sha256) THEN
        RAISE EXCEPTION 'approved onboarding copy SHA-256 does not verify';
    END IF;
    IF length(p_evidence_sha256) <> 64 THEN
        RAISE EXCEPTION 'approval evidence SHA-256 is required';
    END IF;
    IF p_article_9_treatment NOT IN (
        'not_applicable', '9(2)(a)_when_special_category'
    ) THEN
        RAISE EXCEPTION 'invalid Article 9 treatment';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.ml_consent_policies existing
         WHERE (existing.retired_at IS NULL OR existing.retired_at > p_active_from)
           AND existing.version <> p_consent_policy_version
    ) THEN
        RAISE EXCEPTION 'another bundled MLC-2 consent policy is active';
    END IF;

    INSERT INTO public.ml_product_legal_approvals (
        approval_reference, approved_copy_sha256, onboarding_copy,
        consent_policy_version, terms_version, privacy_policy_version,
        approving_authority, approved_at, jurisdictions, article_6_basis,
        article_9_treatment, evidence_object_key, evidence_sha256
    ) VALUES (
        p_approval_reference, lower(p_approved_copy_sha256), p_onboarding_copy,
        p_consent_policy_version, p_terms_version, p_privacy_policy_version,
        p_approving_authority, p_approved_at, p_jurisdictions, '6(1)(a)',
        p_article_9_treatment, p_evidence_object_key, lower(p_evidence_sha256)
    ) ON CONFLICT (approval_reference) DO NOTHING;

    SELECT * INTO approval
      FROM public.ml_product_legal_approvals
     WHERE approval_reference = p_approval_reference;
    IF approval.approved_copy_sha256 <> lower(p_approved_copy_sha256)
       OR approval.onboarding_copy <> p_onboarding_copy
       OR approval.consent_policy_version <> p_consent_policy_version
       OR approval.terms_version <> p_terms_version
       OR approval.privacy_policy_version <> p_privacy_policy_version
       OR approval.approving_authority <> p_approving_authority
       OR approval.approved_at <> p_approved_at
       OR approval.jurisdictions <> p_jurisdictions
       OR approval.article_6_basis <> '6(1)(a)'
       OR approval.article_9_treatment <> p_article_9_treatment
       OR approval.evidence_object_key <> p_evidence_object_key
       OR approval.evidence_sha256 <> lower(p_evidence_sha256) THEN
        RAISE EXCEPTION 'Product/legal approval idempotency collision';
    END IF;

    INSERT INTO public.ml_consent_policies (
        version, product_legal_approval_id, required_for_service, bundled_ui,
        active_from
    ) VALUES (
        p_consent_policy_version, approval.id, true, true, p_active_from
    ) ON CONFLICT (version) DO NOTHING;

    SELECT * INTO policy FROM public.ml_consent_policies
     WHERE version = p_consent_policy_version;
    IF policy.product_legal_approval_id <> approval.id
       OR NOT policy.required_for_service
       OR NOT policy.bundled_ui
       OR policy.active_from <> p_active_from
       OR policy.retired_at IS NOT NULL THEN
        RAISE EXCEPTION 'consent policy idempotency collision';
    END IF;

    RETURN jsonb_build_object(
        'approval_id', approval.id,
        'approval_reference', approval.approval_reference,
        'consent_policy_version', policy.version,
        'active_from', policy.active_from,
        'configured', true
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.accept_mlc2_founder_consent_v1(
    p_acquisition_principal_id UUID,
    p_identity_hash TEXT,
    p_identity_version TEXT,
    p_binding_kind TEXT,
    p_binding_proof_hash TEXT,
    p_bound_by TEXT,
    p_consent_policy_version TEXT,
    p_jurisdiction TEXT,
    p_terms_version TEXT,
    p_privacy_policy_version TEXT,
    p_source_route TEXT,
    p_client_version TEXT,
    p_affirmative_action JSONB,
    p_occurred_at TIMESTAMPTZ,
    p_article_9_applies BOOLEAN,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    binding public.ml_speaker_principals;
    consent_event public.ml_consent_events;
BEGIN
    -- One Postgres transaction binds the verified account identity and appends
    -- the exact consent grant. If either operation fails, neither persists.
    SELECT * INTO binding FROM public.register_ml_speaker_principal_v1(
        p_acquisition_principal_id, p_identity_hash, p_identity_version,
        p_binding_kind, p_binding_proof_hash, p_bound_by,
        'speaker-sha256-80-10-10-v1'
    );
    SELECT * INTO consent_event FROM public.record_mlc2_consent_grant_v1(
        p_acquisition_principal_id, p_consent_policy_version,
        p_jurisdiction, p_terms_version, p_privacy_policy_version,
        p_source_route, p_client_version, p_affirmative_action,
        p_occurred_at, p_article_9_applies, p_idempotency_key
    );
    RETURN jsonb_build_object(
        'binding_id', binding.id,
        'speaker_id', binding.speaker_id,
        'consent_event_id', consent_event.id,
        'accepted', true
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.get_mlc2_principal_consent_status_v1(
    p_acquisition_principal_id UUID
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
STABLE
SET search_path = public
AS $$
DECLARE
    active_policy_count INTEGER;
    policy public.ml_consent_policies;
    approval public.ml_product_legal_approvals;
    grant_event public.ml_consent_events;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.owner_principals
         WHERE id = p_acquisition_principal_id
    ) THEN
        RAISE EXCEPTION 'unknown acquisition principal';
    END IF;

    SELECT count(*) INTO active_policy_count
      FROM public.ml_consent_policies candidate
     WHERE candidate.active_from <= now()
       AND (candidate.retired_at IS NULL OR candidate.retired_at > now());
    IF active_policy_count = 0 THEN
        RETURN jsonb_build_object(
            'configured', false,
            'acquisition_principal_id', p_acquisition_principal_id,
            'granted', false
        );
    END IF;
    IF active_policy_count <> 1 THEN
        RAISE EXCEPTION 'active MLC-2 consent policy count must equal one';
    END IF;

    SELECT * INTO policy FROM public.ml_consent_policies candidate
     WHERE candidate.active_from <= now()
       AND (candidate.retired_at IS NULL OR candidate.retired_at > now());
    SELECT * INTO approval FROM public.ml_product_legal_approvals
     WHERE id = policy.product_legal_approval_id;

    SELECT event.* INTO grant_event
      FROM public.ml_consent_events event
     WHERE event.acquisition_principal_id = p_acquisition_principal_id
       AND event.consent_policy_version = policy.version
       AND event.event_kind = 'grant'
       AND NOT EXISTS (
           SELECT 1 FROM public.ml_consent_events withdrawal
            WHERE withdrawal.event_kind = 'withdraw'
              AND withdrawal.supersedes_event_id = event.id
              AND withdrawal.occurred_at <= now()
       )
       AND (
           SELECT count(*) FROM public.ml_consent_event_purposes purpose
            WHERE purpose.consent_event_id = event.id
              AND purpose.purpose IN (
                  'personalized_coaching', 'pooled_model_improvement'
              )
              AND purpose.article_6_basis = '6(1)(a)'
       ) = 2
     ORDER BY event.occurred_at DESC, event.id DESC
     LIMIT 1;

    RETURN jsonb_build_object(
        'configured', true,
        'acquisition_principal_id', p_acquisition_principal_id,
        'speaker_bound', EXISTS (
            SELECT 1 FROM public.ml_speaker_principals binding
             WHERE binding.acquisition_principal_id = p_acquisition_principal_id
        ),
        'granted', grant_event.id IS NOT NULL AND EXISTS (
            SELECT 1 FROM public.ml_speaker_principals binding
             WHERE binding.acquisition_principal_id = p_acquisition_principal_id
        ),
        'grant_event_id', grant_event.id,
        'consent_policy_version', policy.version,
        'required_for_service', policy.required_for_service,
        'bundled_ui', policy.bundled_ui,
        'approval_reference', approval.approval_reference,
        'approved_copy_sha256', approval.approved_copy_sha256,
        'onboarding_copy', approval.onboarding_copy,
        'terms_version', approval.terms_version,
        'privacy_policy_version', approval.privacy_policy_version,
        'article_6_basis', approval.article_6_basis,
        'article_9_treatment', approval.article_9_treatment
    );
END;
$$;

REVOKE ALL ON FUNCTION public.configure_mlc2_consent_policy_v1(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ, TEXT[], TEXT,
    TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.configure_mlc2_consent_policy_v1(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ, TEXT[], TEXT,
    TEXT, TEXT, TIMESTAMPTZ
) TO service_role;

REVOKE ALL ON FUNCTION public.accept_mlc2_founder_consent_v1(
    UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT,
    JSONB, TIMESTAMPTZ, BOOLEAN, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.accept_mlc2_founder_consent_v1(
    UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT,
    JSONB, TIMESTAMPTZ, BOOLEAN, TEXT
) TO service_role;

REVOKE ALL ON FUNCTION public.get_mlc2_principal_consent_status_v1(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_mlc2_principal_consent_status_v1(UUID)
    TO service_role;

COMMENT ON FUNCTION public.configure_mlc2_consent_policy_v1(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ, TEXT[], TEXT,
    TEXT, TEXT, TIMESTAMPTZ
) IS 'Registers verified immutable Product/legal evidence and one bundled MLC-2 policy; never creates user consent.';
COMMENT ON FUNCTION public.accept_mlc2_founder_consent_v1(
    UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT,
    JSONB, TIMESTAMPTZ, BOOLEAN, TEXT
) IS 'Atomically binds one verified founder principal to its speaker and appends the exact explicit bundled consent.';
COMMENT ON FUNCTION public.get_mlc2_principal_consent_status_v1(UUID) IS
    'Service-only exact-principal status for the founder consent gate.';

COMMIT;
