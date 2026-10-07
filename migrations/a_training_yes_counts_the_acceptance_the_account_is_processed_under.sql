-- 0436 · A training yes counts the acceptance the account is processed under.
--
-- WHY (2026-10-07, founder's screenshot: "Couldn't save that. Try again." on
-- the Help improve WillpowerLab card, every time). record_mlc2_training_
-- consent_grant_v2 (0373, 0412) records the yes under the account's owner
-- principal, and C1 looked for the policy receipt under that same principal
-- only. But an account's processing is authorised by the principal
-- resolve_phase1_acquisition_principal_v1 (0355, 0414) resolves to, which can
-- be a guest claimed into the account: someone who accepted the current Terms
-- as a first-time visitor (Phase 0.5) and then signed in. The app then works
-- for them under that guest's receipt, while C1 found no receipt on the
-- account and refused every yes (TRAINING_CONSENT_NEEDS_POLICY_RECEIPT, shown
-- as "Couldn't save that."). 0412's own header named the case ("a person
-- whose 3.2 receipt was written against a different acquisition principal
-- cannot either") without fixing it.
--
-- THE RULE. C1 accepts a receipt held by the account OR by the principal the
-- account resolves to, with 0412's version rule unchanged. Nothing else
-- changes: the yes is still recorded under the account (training_corpus
-- reads it there), the resolver is 0414's and is only called, the version
-- and its own-act checks are as they were, and an account with no such
-- receipt anywhere is still refused. A claimed guest is the same person
-- (its claim is the proof of sign-in), so no one else's acceptance counts.
--
-- Everything else in the function is byte for byte 0412's. Idempotent:
-- CREATE OR REPLACE. Changes no rows. The grants are 0373's, restated.

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
    -- or one activated after it that still carries the text (0412). The
    -- receipt may sit on the account or on the principal the account's
    -- processing resolves to: a guest claimed into it (0436).
    -- A required version that was never activated keeps the exact match
    -- only (nothing can be "after" it).
    SELECT activated_at INTO required_activated_at
      FROM public.processing_policy_versions
     WHERE version = policy.requires_processing_policy_version;
    IF NOT EXISTS (
        SELECT 1 FROM public.processing_authorization_receipts receipt
          JOIN public.processing_policy_versions version
            ON version.id = receipt.policy_id
         WHERE receipt.acquisition_principal_id IN (
                   p_acquisition_principal_id,
                   public.resolve_phase1_acquisition_principal_v1(
                       p_acquisition_principal_id))
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
