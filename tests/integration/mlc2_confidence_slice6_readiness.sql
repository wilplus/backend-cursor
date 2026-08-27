\set ON_ERROR_STOP on

-- Run after 0302–0305 in a disposable PostgreSQL database. Every fixture is
-- rolled back; no producer or application cutover flag is touched.
BEGIN;

INSERT INTO public.owner_principals (id, guest_secret_hash) VALUES (
    'c0000000-0000-4000-8000-000000000001', 'slice6-founder'
);
INSERT INTO public.ml_product_legal_approvals (
    id, approval_reference, approved_copy_sha256, onboarding_copy,
    consent_policy_version, terms_version, privacy_policy_version,
    approving_authority, approved_at, jurisdictions, article_6_basis,
    article_9_treatment, evidence_object_key, evidence_sha256
) VALUES (
    'c1000000-0000-4000-8000-000000000001',
    'SLICE6-REHEARSAL-ONLY', repeat('1', 64), 'Rehearsal copy',
    'slice6-consent-v1', 'terms-v1', 'privacy-v1', 'isolated-test',
    '2026-08-27T00:00:00Z', ARRAY['EU'], '6(1)(a)',
    '9(2)(a)_when_special_category', 'legal/slice6.json', repeat('2', 64)
);
INSERT INTO public.ml_consent_policies (
    version, product_legal_approval_id, required_for_service, bundled_ui,
    active_from
) VALUES (
    'slice6-consent-v1', 'c1000000-0000-4000-8000-000000000001',
    true, true, '2026-08-27T00:00:00Z'
);

SET ROLE service_role;

SELECT public.record_mlc2_consent_grant_v1(
    'c0000000-0000-4000-8000-000000000001', 'slice6-consent-v1',
    'EU', 'terms-v1', 'privacy-v1', '/slice6', 'rehearsal-client',
    jsonb_build_object(
        'accepted', true, 'copy_sha256', repeat('1', 64),
        'purposes', jsonb_build_array(
            'personalized_coaching', 'pooled_model_improvement'
        )
    ), '2026-08-27T12:00:00Z', true, 'slice6-consent-grant'
);

DO $$
DECLARE
    health JSONB;
BEGIN
    health := public.get_mlc2_confidence_canary_readiness_v1(
        'c0000000-0000-4000-8000-000000000001'
    );
    IF health ->> 'readiness_contract_version'
          <> 'mlc2-confidence-canary-readiness-v1'
       OR (health ->> 'active_consent_policy_count')::integer <> 1
       OR (health ->> 'valid_active_consent_policy_count')::integer <> 1
       OR (health ->> 'founder_active_bundled_consent_grant_count')::integer
          <> 1
       OR (health ->> 'founder_producer_receipt_count')::integer <> 0
       OR (health ->> 'nonfounder_producer_receipt_count')::integer <> 0
       OR (health ->> 'nonfounder_canonical_event_count')::integer <> 0
       OR (health ->> 'pending_confidence_outbox_count')::integer <> 0
       OR (health ->> 'dataset_creation_enabled')::boolean
       OR (health ->> 'training_enabled')::boolean
       OR (health ->> 'promotion_enabled')::boolean THEN
        RAISE EXCEPTION 'Slice 6 aggregate readiness evidence is invalid: %',
            health;
    END IF;
END;
$$;

RESET ROLE;

DO $$
BEGIN
    IF has_function_privilege(
        'anon',
        'public.get_mlc2_confidence_canary_readiness_v1(uuid)',
        'EXECUTE'
    ) OR has_function_privilege(
        'authenticated',
        'public.get_mlc2_confidence_canary_readiness_v1(uuid)',
        'EXECUTE'
    ) THEN
        RAISE EXCEPTION 'browser role can execute Slice 6 readiness RPC';
    END IF;
END;
$$;

ROLLBACK;
