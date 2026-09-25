-- A training yes is its own act (SPEC-training-corpus-and-project-purge §3,
-- phase P2; founder locks C1, C2, Q4 = A, 2026-09-25).
--
-- The training yes lives in the MLC-2 consent tables, recorded per person,
-- withdrawable on its own, and read by one function. Bundled-era grants
-- (`mlc2-bundled-consent-v1`) are never a training yes: the reader selects by
-- `grant_scope`, so nothing is copied, migrated or rewritten.
--
-- DARK. No `training_only` policy row is created here, so no grant can be
-- recorded and the reader answers "no" for everyone. Registering the policy,
-- the toggle and its wording are P5 (counsel review + founder sign-off).
--
-- THE ONE NON-ADDITIVE STEP, approved by the founder 2026-09-26: the two
-- column CHECKs `required_for_service` and `bundled_ui` on
-- `ml_consent_policies` are removed, because a training-only policy is by
-- definition optional and unbundled. No row changes. The replacement table
-- CHECK below keeps the old rule for every `bundled_v1` row and adds the
-- opposite rule for `training_only`.
--
-- The `_v1` consent functions are left exactly as they are and are never
-- called by the new path.

BEGIN;

ALTER TABLE public.ml_consent_policies
    DROP CONSTRAINT IF EXISTS ml_consent_policies_required_for_service_check;
ALTER TABLE public.ml_consent_policies
    DROP CONSTRAINT IF EXISTS ml_consent_policies_bundled_ui_check;

ALTER TABLE public.ml_consent_policies
    ADD COLUMN IF NOT EXISTS grant_scope TEXT NOT NULL DEFAULT 'bundled_v1';
-- C1: a training yes needs the person's receipt for the processing policy
-- version that introduced training. Only a training_only policy names it.
ALTER TABLE public.ml_consent_policies
    ADD COLUMN IF NOT EXISTS requires_processing_policy_version TEXT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'ml_consent_policy_grant_scope_check'
           AND conrelid = 'public.ml_consent_policies'::regclass
    ) THEN
        ALTER TABLE public.ml_consent_policies
            ADD CONSTRAINT ml_consent_policy_grant_scope_check CHECK (
                (grant_scope = 'bundled_v1'
                 AND required_for_service AND bundled_ui
                 AND requires_processing_policy_version IS NULL)
                OR
                (grant_scope = 'training_only'
                 AND NOT required_for_service AND NOT bundled_ui
                 AND NULLIF(btrim(requires_processing_policy_version), '')
                     IS NOT NULL)
            );
    END IF;
END;
$$;

-- ── Register a training-only policy (P5 calls this; nothing calls it now) ──
CREATE OR REPLACE FUNCTION public.configure_mlc2_training_consent_policy_v1(
    p_approval_reference TEXT,
    p_approved_copy_sha256 TEXT,
    p_toggle_copy TEXT,
    p_consent_policy_version TEXT,
    p_terms_version TEXT,
    p_privacy_policy_version TEXT,
    p_approving_authority TEXT,
    p_approved_at TIMESTAMPTZ,
    p_jurisdictions TEXT[],
    p_evidence_object_key TEXT,
    p_evidence_sha256 TEXT,
    p_requires_processing_policy_version TEXT,
    p_active_from TIMESTAMPTZ
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    approval public.ml_product_legal_approvals;
    policy public.ml_consent_policies;
BEGIN
    IF NULLIF(btrim(p_approval_reference), '') IS NULL
       OR NULLIF(btrim(p_consent_policy_version), '') IS NULL
       OR NULLIF(btrim(p_toggle_copy), '') IS NULL
       OR NULLIF(btrim(p_approving_authority), '') IS NULL
       OR NULLIF(btrim(p_evidence_object_key), '') IS NULL
       OR NULLIF(btrim(p_requires_processing_policy_version), '') IS NULL
       OR cardinality(p_jurisdictions) < 1 THEN
        RAISE EXCEPTION 'TRAINING_POLICY_CONFIGURATION_INCOMPLETE';
    END IF;
    IF length(p_approved_copy_sha256) <> 64
       OR encode(extensions.digest(convert_to(p_toggle_copy, 'UTF8'), 'sha256'), 'hex')
          <> lower(p_approved_copy_sha256) THEN
        RAISE EXCEPTION 'TRAINING_POLICY_COPY_HASH_DOES_NOT_VERIFY';
    END IF;
    IF length(p_evidence_sha256) <> 64 THEN
        RAISE EXCEPTION 'TRAINING_POLICY_EVIDENCE_HASH_REQUIRED';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.processing_policy_versions
                    WHERE version = p_requires_processing_policy_version) THEN
        RAISE EXCEPTION 'TRAINING_POLICY_PROCESSING_VERSION_UNKNOWN';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.ml_consent_policies existing
         WHERE existing.grant_scope = 'training_only'
           AND existing.version <> p_consent_policy_version
           AND (existing.retired_at IS NULL OR existing.retired_at > p_active_from)
    ) THEN
        RAISE EXCEPTION 'ANOTHER_TRAINING_POLICY_IS_ACTIVE';
    END IF;

    -- Voice is not biometric data here (counsel, 2026-09-25): no Article 9.
    INSERT INTO public.ml_product_legal_approvals (
        approval_reference, approved_copy_sha256, onboarding_copy,
        consent_policy_version, terms_version, privacy_policy_version,
        approving_authority, approved_at, jurisdictions, article_6_basis,
        article_9_treatment, evidence_object_key, evidence_sha256
    ) VALUES (
        p_approval_reference, lower(p_approved_copy_sha256), p_toggle_copy,
        p_consent_policy_version, p_terms_version, p_privacy_policy_version,
        p_approving_authority, p_approved_at, p_jurisdictions, '6(1)(a)',
        'not_applicable', p_evidence_object_key, lower(p_evidence_sha256)
    ) ON CONFLICT (approval_reference) DO NOTHING;

    SELECT * INTO approval FROM public.ml_product_legal_approvals
     WHERE approval_reference = p_approval_reference;
    IF approval.approved_copy_sha256 <> lower(p_approved_copy_sha256)
       OR approval.consent_policy_version <> p_consent_policy_version
       OR approval.terms_version <> p_terms_version
       OR approval.privacy_policy_version <> p_privacy_policy_version THEN
        RAISE EXCEPTION 'TRAINING_POLICY_IDEMPOTENCY_COLLISION';
    END IF;

    INSERT INTO public.ml_consent_policies (
        version, product_legal_approval_id, required_for_service, bundled_ui,
        grant_scope, requires_processing_policy_version, active_from
    ) VALUES (
        p_consent_policy_version, approval.id, false, false,
        'training_only', p_requires_processing_policy_version, p_active_from
    ) ON CONFLICT (version) DO NOTHING;

    SELECT * INTO policy FROM public.ml_consent_policies
     WHERE version = p_consent_policy_version;
    IF policy.product_legal_approval_id <> approval.id
       OR policy.grant_scope <> 'training_only'
       OR policy.requires_processing_policy_version
          IS DISTINCT FROM p_requires_processing_policy_version
       OR policy.active_from <> p_active_from THEN
        RAISE EXCEPTION 'TRAINING_POLICY_IDEMPOTENCY_COLLISION';
    END IF;
    RETURN jsonb_build_object(
        'consent_policy_version', policy.version,
        'grant_scope', policy.grant_scope,
        'requires_processing_policy_version',
            policy.requires_processing_policy_version,
        'active_from', policy.active_from);
END;
$$;

-- ── The training yes (SPEC §3.3) ──────────────────────────────────────────
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
    -- C1: every user re-accepts the policy version that introduced training.
    IF NOT EXISTS (
        SELECT 1 FROM public.processing_authorization_receipts receipt
          JOIN public.processing_policy_versions version
            ON version.id = receipt.policy_id
         WHERE receipt.acquisition_principal_id = p_acquisition_principal_id
           AND version.version = policy.requires_processing_policy_version
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

-- ── Withdraw one purpose (SPEC §3.4) ──────────────────────────────────────
-- Only a training_only grant, and only its training purpose. Withdrawing
-- "training" from a bundled grant through here would read, to the v1
-- readers, as withdrawing coaching too, and a bundled grant is never a
-- training yes anyway (C2). The corpus purge this enqueues arrives with P4;
-- until then there is no corpus to purge.
CREATE OR REPLACE FUNCTION public.record_mlc2_consent_withdrawal_v2(
    p_acquisition_principal_id UUID,
    p_grant_event_id UUID,
    p_purpose TEXT,
    p_source_route TEXT,
    p_client_version TEXT,
    p_affirmative_action JSONB,
    p_occurred_at TIMESTAMPTZ,
    p_idempotency_key TEXT
) RETURNS public.ml_consent_events
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    grant_event public.ml_consent_events;
    policy public.ml_consent_policies;
    withdrawal public.ml_consent_events;
BEGIN
    IF p_purpose IS DISTINCT FROM 'pooled_model_improvement' THEN
        RAISE EXCEPTION 'WITHDRAWAL_PURPOSE_NOT_SUPPORTED';
    END IF;
    IF NULLIF(btrim(p_idempotency_key), '') IS NULL
       OR jsonb_typeof(p_affirmative_action) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'TRAINING_WITHDRAWAL_INPUT_INVALID';
    END IF;
    SELECT * INTO grant_event FROM public.ml_consent_events
     WHERE id = p_grant_event_id
       AND acquisition_principal_id = p_acquisition_principal_id
       AND event_kind = 'grant';
    SELECT * INTO policy FROM public.ml_consent_policies
     WHERE version = grant_event.consent_policy_version;
    IF grant_event.id IS NULL OR policy.grant_scope IS DISTINCT FROM 'training_only'
       OR NOT EXISTS (SELECT 1 FROM public.ml_consent_event_purposes
                       WHERE consent_event_id = grant_event.id
                         AND purpose = p_purpose) THEN
        RAISE EXCEPTION 'TRAINING_GRANT_NOT_FOUND';
    END IF;
    IF p_occurred_at < grant_event.occurred_at THEN
        RAISE EXCEPTION 'WITHDRAWAL_CANNOT_PRECEDE_GRANT';
    END IF;

    INSERT INTO public.ml_consent_events (
        acquisition_principal_id, consent_policy_version,
        product_legal_approval_id, accepted_copy_sha256, event_kind,
        jurisdiction, terms_version, privacy_policy_version, source_route,
        client_version, affirmative_action, occurred_at, idempotency_key,
        supersedes_event_id
    ) VALUES (
        p_acquisition_principal_id, grant_event.consent_policy_version,
        grant_event.product_legal_approval_id, grant_event.accepted_copy_sha256,
        'withdraw', grant_event.jurisdiction, grant_event.terms_version,
        grant_event.privacy_policy_version, p_source_route, p_client_version,
        p_affirmative_action, p_occurred_at, p_idempotency_key, grant_event.id
    ) ON CONFLICT (idempotency_key) DO NOTHING;

    SELECT * INTO withdrawal FROM public.ml_consent_events
     WHERE idempotency_key = p_idempotency_key;
    IF withdrawal.supersedes_event_id IS DISTINCT FROM grant_event.id
       OR withdrawal.event_kind <> 'withdraw' THEN
        RAISE EXCEPTION 'TRAINING_WITHDRAWAL_IDEMPOTENCY_COLLISION';
    END IF;

    -- Only the withdrawn purpose; every other purpose stays as it was.
    INSERT INTO public.ml_consent_event_purposes (
        consent_event_id, purpose, article_6_basis, article_9_basis
    )
    SELECT withdrawal.id, purpose, article_6_basis, article_9_basis
      FROM public.ml_consent_event_purposes
     WHERE consent_event_id = grant_event.id AND purpose = p_purpose
    ON CONFLICT (consent_event_id, purpose) DO NOTHING;
    RETURN withdrawal;
END;
$$;

-- ── The one reader (SPEC §3.5) ─────────────────────────────────────────────
-- Active training yes: the latest grant under a training_only policy that is
-- in force now, carrying pooled_model_improvement, with no withdrawal of that
-- purpose superseding it. Bundled grants are never read. Never raises on the
-- number of active policies.
CREATE OR REPLACE FUNCTION public.get_mlc2_training_consent_status_v2(
    p_acquisition_principal_id UUID
) RETURNS JSONB
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public
AS $$
    WITH latest AS (
        SELECT event.*
          FROM public.ml_consent_events event
          JOIN public.ml_consent_policies policy
            ON policy.version = event.consent_policy_version
         WHERE event.acquisition_principal_id = p_acquisition_principal_id
           AND event.event_kind = 'grant'
           AND policy.grant_scope = 'training_only'
           AND policy.active_from <= now()
           AND (policy.retired_at IS NULL OR policy.retired_at > now())
           AND event.occurred_at <= now()
           AND EXISTS (SELECT 1 FROM public.ml_consent_event_purposes purpose
                        WHERE purpose.consent_event_id = event.id
                          AND purpose.purpose = 'pooled_model_improvement')
         ORDER BY event.occurred_at DESC, event.id DESC
         LIMIT 1
    )
    SELECT CASE
        WHEN latest.id IS NULL THEN jsonb_build_object('active', false)
        WHEN EXISTS (
            SELECT 1 FROM public.ml_consent_events withdrawal
              JOIN public.ml_consent_event_purposes purpose
                ON purpose.consent_event_id = withdrawal.id
               AND purpose.purpose = 'pooled_model_improvement'
             WHERE withdrawal.supersedes_event_id = latest.id
               AND withdrawal.event_kind = 'withdraw'
               AND withdrawal.occurred_at <= now()
        ) THEN jsonb_build_object('active', false,
                                  'grant_event_id', latest.id,
                                  'withdrawn', true)
        ELSE jsonb_build_object(
            'active', true,
            'grant_event_id', latest.id,
            'consent_policy_version', latest.consent_policy_version,
            'granted_at', latest.occurred_at)
    END
    FROM (SELECT 1) one LEFT JOIN latest ON true
$$;

REVOKE ALL ON FUNCTION public.configure_mlc2_training_consent_policy_v1(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ, TEXT[], TEXT, TEXT,
    TEXT, TIMESTAMPTZ) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.configure_mlc2_training_consent_policy_v1(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ, TEXT[], TEXT, TEXT,
    TEXT, TIMESTAMPTZ) TO service_role;

REVOKE ALL ON FUNCTION public.record_mlc2_training_consent_grant_v2(
    UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, TIMESTAMPTZ, TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_mlc2_training_consent_grant_v2(
    UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, TIMESTAMPTZ, TEXT)
    TO service_role;

REVOKE ALL ON FUNCTION public.record_mlc2_consent_withdrawal_v2(
    UUID, UUID, TEXT, TEXT, TEXT, JSONB, TIMESTAMPTZ, TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_mlc2_consent_withdrawal_v2(
    UUID, UUID, TEXT, TEXT, TEXT, JSONB, TIMESTAMPTZ, TEXT) TO service_role;

REVOKE ALL ON FUNCTION public.get_mlc2_training_consent_status_v2(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_mlc2_training_consent_status_v2(UUID)
    TO service_role;

COMMIT;
