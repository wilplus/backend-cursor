-- 0412 · A training yes counts a receipt for the version that introduced
-- training OR any version activated after it.
--
-- WHY (2026-10-03, founder's screenshot "Couldn't save that. Try again." on
-- the Help improve WillpowerLab card, the day after Privacy 3.3 went live).
-- record_mlc2_training_consent_grant_v2 (0373, C1) checked that the person
-- holds a processing receipt for EXACTLY the policy version named by the
-- training policy's requires_processing_policy_version: phase1-2026-10-01,
-- Privacy 3.2, the version that introduced the training section. Privacy
-- 3.3 (phase1-2026-10-02, N24) carries that section unchanged, and from the
-- moment it was activated every new acceptance is a 3.3 receipt. Under the
-- exact match a person who first accepted on 3.3 can never turn training
-- on, and a person whose 3.2 receipt was written against a different
-- acquisition principal cannot either. C1's point is that nobody says yes
-- to training without having read the text that describes it; a later
-- version that still carries the text satisfies that, an earlier one does
-- not. So: the receipt's version must be the required one, or one activated
-- after it. Order is by activated_at, never by the version string.
--
-- Everything else in the function is byte for byte 0373's. Idempotent:
-- CREATE OR REPLACE.

CREATE OR REPLACE FUNCTION public.record_mlc2_training_consent_grant_v2(
    p_acquisition_principal_id UUID,
    p_consent_policy_version TEXT,
    p_jurisdiction TEXT,
    p_terms_version TEXT,
    p_privacy_policy_version TEXT,
    p_source_route TEXT,
    p_client_version TEXT,
    p_affirmative_action JSONB,
    p_occurred_at TIMESTAMPTZ,
    p_idempotency_key TEXT
) RETURNS public.ml_consent_events
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    policy public.ml_consent_policies;
    approval public.ml_product_legal_approvals;
    consent_event public.ml_consent_events;
    required_activated_at TIMESTAMPTZ;
BEGIN
    IF NULLIF(btrim(p_idempotency_key), '') IS NULL
       OR p_acquisition_principal_id IS NULL OR p_occurred_at IS NULL THEN
        RAISE EXCEPTION 'TRAINING_CONSENT_INPUT_INVALID';
    END IF;
    SELECT * INTO policy FROM public.ml_consent_policies
     WHERE version = p_consent_policy_version
       AND active_from <= p_occurred_at
       AND (retired_at IS NULL OR retired_at > p_occurred_at);
    IF policy.version IS NULL THEN
        RAISE EXCEPTION 'TRAINING_POLICY_NOT_ACTIVE';
    END IF;
    IF policy.grant_scope <> 'training_only' OR policy.bundled_ui
       OR policy.required_for_service THEN
        RAISE EXCEPTION 'TRAINING_POLICY_NOT_TRAINING_ONLY';
    END IF;
    SELECT * INTO approval FROM public.ml_product_legal_approvals
     WHERE id = policy.product_legal_approval_id;
    IF approval.id IS NULL
       OR p_terms_version IS DISTINCT FROM approval.terms_version
       OR p_privacy_policy_version IS DISTINCT FROM approval.privacy_policy_version
       OR p_affirmative_action ->> 'copy_sha256'
          IS DISTINCT FROM approval.approved_copy_sha256 THEN
        RAISE EXCEPTION 'TRAINING_CONSENT_DOES_NOT_MATCH_APPROVAL';
    END IF;
    -- Its own act: the training toggle, and nothing else. A yes captured on
    -- sign-up, the processing acceptance or a combined screen is refused.
    IF jsonb_typeof(p_affirmative_action) <> 'object'
       OR p_affirmative_action ->> 'accepted' IS DISTINCT FROM 'true'
       OR p_affirmative_action ->> 'control' IS DISTINCT FROM 'training_toggle' THEN
        RAISE EXCEPTION 'TRAINING_CONSENT_NOT_ITS_OWN_ACT';
    END IF;
    -- C1: every user re-accepts the policy version that introduced training,
    -- or one activated after it that still carries the text (0412).
    -- A required version that was never activated keeps the exact match
    -- only (nothing can be "after" it).
    SELECT activated_at INTO required_activated_at
      FROM public.processing_policy_versions
     WHERE version = policy.requires_processing_policy_version;
    IF NOT EXISTS (
        SELECT 1 FROM public.processing_authorization_receipts receipt
          JOIN public.processing_policy_versions version
            ON version.id = receipt.policy_id
         WHERE receipt.acquisition_principal_id = p_acquisition_principal_id
           AND (version.version = policy.requires_processing_policy_version
                OR (required_activated_at IS NOT NULL
                    AND version.activated_at IS NOT NULL
                    AND version.activated_at >= required_activated_at))
    ) THEN
        RAISE EXCEPTION 'TRAINING_CONSENT_NEEDS_POLICY_RECEIPT';
    END IF;

    INSERT INTO public.ml_consent_events (
        acquisition_principal_id, consent_policy_version,
        product_legal_approval_id, accepted_copy_sha256, event_kind,
        jurisdiction, terms_version, privacy_policy_version, source_route,
        client_version, affirmative_action, occurred_at, idempotency_key
    ) VALUES (
        p_acquisition_principal_id, policy.version, approval.id,
        approval.approved_copy_sha256, 'grant',
        p_jurisdiction, p_terms_version, p_privacy_policy_version,
        p_source_route, p_client_version, p_affirmative_action,
        p_occurred_at, p_idempotency_key
    ) ON CONFLICT (idempotency_key) DO NOTHING;

    SELECT * INTO consent_event FROM public.ml_consent_events
     WHERE idempotency_key = p_idempotency_key;
    IF consent_event.acquisition_principal_id <> p_acquisition_principal_id
       OR consent_event.event_kind <> 'grant'
       OR consent_event.consent_policy_version <> policy.version THEN
        RAISE EXCEPTION 'TRAINING_CONSENT_IDEMPOTENCY_COLLISION';
    END IF;

    -- Exactly one purpose row. Voice is not biometric here: no Article 9.
    INSERT INTO public.ml_consent_event_purposes (
        consent_event_id, purpose, article_6_basis, article_9_basis
    ) VALUES (consent_event.id, 'pooled_model_improvement', '6(1)(a)', NULL)
    ON CONFLICT (consent_event_id, purpose) DO NOTHING;
    IF (SELECT count(*) FROM public.ml_consent_event_purposes
         WHERE consent_event_id = consent_event.id) <> 1 THEN
        RAISE EXCEPTION 'TRAINING_CONSENT_IDEMPOTENCY_COLLISION';
    END IF;
    RETURN consent_event;
END;
$$;

-- Rule 2 (tests/test_migration_security_rules.py): the redefinition keeps
-- the grants 0373 gave it. Browser roles call nothing.
REVOKE ALL ON FUNCTION public.record_mlc2_training_consent_grant_v2(
    UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, TIMESTAMPTZ, TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_mlc2_training_consent_grant_v2(
    UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, TIMESTAMPTZ, TEXT)
    TO service_role;
