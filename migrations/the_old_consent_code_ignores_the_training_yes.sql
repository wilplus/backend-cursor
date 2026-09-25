-- The old consent code ignores the training yes (P5 packet §4, items 1 and 2;
-- SPEC-training-corpus §3.6; founder N11 answer 8, "build the switched-off
-- pieces now").
--
-- 0373 lets a second kind of MLC-2 consent policy exist: `training_only`,
-- beside the original `bundled_v1`. The code written before it assumes there
-- is only one kind. None of that is live today, because no training policy
-- exists in production. It would break the day one is registered:
--
--   * get_mlc2_principal_consent_status_v1 raises "active MLC-2 consent
--     policy count must equal one" once a training policy is active beside a
--     bundled one;
--   * configure_mlc2_consent_policy_v1 refuses to register a bundled policy
--     while a training one is active;
--   * get_mlc2_confidence_canary_readiness_v1 counts two policies and reports
--     the canary blocked;
--   * record_mlc2_consent_grant_v1 would record a bundled, two-purpose yes
--     against the training policy;
--   * record_mlc2_consent_withdrawal_v1 would turn training off without
--     making the copies due (only the v2 withdrawal does, 0376), leaving
--     training copies behind after a "no".
--
-- Each is re-issued from its source with one filter or one refusal added,
-- and nothing else changed. configure_v1 keeps the `extensions, public`
-- search_path 0307 gave it.
--
-- THE RECEIPT. accept_phase1_processing_authorization_v2 records the optional
-- purposes a person ticked on the acceptance screen. Training is never one of
-- them: the yes to training is its own act, on its own screen, through the
-- training writer (N7, SPEC §3.6 invariant 8). Today the policy registry
-- refuses any policy naming `pooled_model_improvement` (PHASE2_PURPOSE_FORBIDDEN),
-- so this is a second wall for the day that is lifted for the new policy.
--
-- v2 is a D11 writer (0366). Re-issuing it from source would drop the lock
-- preamble 0366 injected. So, like 0366, this edits the INSTALLED definition:
-- it inserts one refusal after the existing optional-purpose check, re-runs
-- the definition, and checks that both its own marker and the D11 marker are
-- in the result. It refuses if the anchor is missing or appears more than once.
--
-- OPENS NOTHING. Every call that succeeds today still succeeds, with the same
-- result. No table, column or row is created, altered or removed.

BEGIN;

CREATE OR REPLACE FUNCTION public.record_mlc2_consent_grant_v1(
    p_acquisition_principal_id UUID,
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
) RETURNS public.ml_consent_events
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    policy public.ml_consent_policies;
    approval public.ml_product_legal_approvals;
    consent_event public.ml_consent_events;
BEGIN
    SELECT * INTO policy FROM public.ml_consent_policies
     WHERE version = p_consent_policy_version
       AND active_from <= p_occurred_at
       AND (retired_at IS NULL OR retired_at > p_occurred_at);
    IF policy.version IS NULL THEN
        RAISE EXCEPTION 'consent policy is not approved and active';
    END IF;
    -- 0377: this writer records the bundled yes (two purposes). A training
    -- policy is recorded only by record_mlc2_training_consent_grant_v2.
    IF policy.grant_scope IS DISTINCT FROM 'bundled_v1' THEN
        RAISE EXCEPTION 'TRAINING_POLICY_NEEDS_THE_TRAINING_WRITER';
    END IF;
    SELECT * INTO approval FROM public.ml_product_legal_approvals
     WHERE id = policy.product_legal_approval_id;
    IF approval.id IS NULL
       OR p_terms_version <> approval.terms_version
       OR p_privacy_policy_version <> approval.privacy_policy_version
       OR p_affirmative_action ->> 'copy_sha256'
          IS DISTINCT FROM approval.approved_copy_sha256 THEN
        RAISE EXCEPTION 'consent does not match documented Product/legal approval';
    END IF;
    IF jsonb_typeof(p_affirmative_action) <> 'object'
       OR p_affirmative_action ->> 'accepted' IS DISTINCT FROM 'true' THEN
        RAISE EXCEPTION 'explicit affirmative consent is required';
    END IF;

    INSERT INTO public.ml_consent_events (
        acquisition_principal_id, consent_policy_version,
        product_legal_approval_id, accepted_copy_sha256, event_kind,
        jurisdiction, terms_version, privacy_policy_version, source_route,
        client_version, affirmative_action, occurred_at, idempotency_key
    ) VALUES (
        p_acquisition_principal_id, p_consent_policy_version, approval.id,
        approval.approved_copy_sha256, 'grant',
        p_jurisdiction, p_terms_version, p_privacy_policy_version,
        p_source_route, p_client_version, p_affirmative_action,
        p_occurred_at, p_idempotency_key
    ) ON CONFLICT (idempotency_key) DO NOTHING;

    SELECT * INTO consent_event FROM public.ml_consent_events
     WHERE idempotency_key = p_idempotency_key;
    IF consent_event.acquisition_principal_id <> p_acquisition_principal_id
       OR consent_event.event_kind <> 'grant' THEN
        RAISE EXCEPTION 'consent idempotency collision';
    END IF;

    INSERT INTO public.ml_consent_event_purposes (
        consent_event_id, purpose, article_6_basis, article_9_basis
    ) VALUES
        (consent_event.id, 'personalized_coaching', '6(1)(a)',
         CASE WHEN p_article_9_applies THEN '9(2)(a)' ELSE NULL END),
        (consent_event.id, 'pooled_model_improvement', '6(1)(a)',
         CASE WHEN p_article_9_applies THEN '9(2)(a)' ELSE NULL END)
    ON CONFLICT (consent_event_id, purpose) DO NOTHING;
    IF (SELECT count(*) FROM public.ml_consent_event_purposes purpose
         WHERE purpose.consent_event_id = consent_event.id
           AND purpose.article_6_basis = '6(1)(a)'
           AND purpose.article_9_basis IS NOT DISTINCT FROM CASE
               WHEN p_article_9_applies THEN '9(2)(a)' ELSE NULL
           END) <> 2 THEN
        RAISE EXCEPTION 'consent purpose idempotency collision';
    END IF;
    RETURN consent_event;
END;
$$;

CREATE OR REPLACE FUNCTION public.record_mlc2_consent_withdrawal_v1(
    p_acquisition_principal_id UUID,
    p_grant_event_id UUID,
    p_source_route TEXT,
    p_client_version TEXT,
    p_affirmative_action JSONB,
    p_occurred_at TIMESTAMPTZ,
    p_idempotency_key TEXT
) RETURNS public.ml_consent_events
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    grant_event public.ml_consent_events;
    withdrawal public.ml_consent_events;
    purge_request public.ml_purge_requests;
BEGIN
    SELECT * INTO grant_event FROM public.ml_consent_events
     WHERE id = p_grant_event_id
       AND acquisition_principal_id = p_acquisition_principal_id
       AND event_kind = 'grant';
    IF grant_event.id IS NULL THEN
        RAISE EXCEPTION 'matching consent grant not found';
    END IF;
    -- 0377: turning training off must also make the copies due
    -- (record_mlc2_consent_withdrawal_v2, 0376). This writer does not, so it
    -- refuses a training grant rather than leave copies behind.
    IF NOT EXISTS (
        SELECT 1 FROM public.ml_consent_policies policy
         WHERE policy.version = grant_event.consent_policy_version
           AND policy.grant_scope = 'bundled_v1'
    ) THEN
        RAISE EXCEPTION 'TRAINING_WITHDRAWAL_NEEDS_THE_TRAINING_WRITER';
    END IF;
    IF p_occurred_at < grant_event.occurred_at THEN
        RAISE EXCEPTION 'withdrawal cannot precede grant';
    END IF;

    INSERT INTO public.ml_consent_events (
        acquisition_principal_id, consent_policy_version,
        product_legal_approval_id, accepted_copy_sha256, event_kind,
        jurisdiction, terms_version, privacy_policy_version, source_route,
        client_version, affirmative_action, occurred_at, idempotency_key,
        supersedes_event_id
    ) VALUES (
        p_acquisition_principal_id, grant_event.consent_policy_version,
        grant_event.product_legal_approval_id,
        grant_event.accepted_copy_sha256,
        'withdraw', grant_event.jurisdiction, grant_event.terms_version,
        grant_event.privacy_policy_version, p_source_route, p_client_version,
        p_affirmative_action, p_occurred_at, p_idempotency_key,
        grant_event.id
    ) ON CONFLICT (idempotency_key) DO NOTHING;

    SELECT * INTO withdrawal FROM public.ml_consent_events
     WHERE idempotency_key = p_idempotency_key;
    IF withdrawal.supersedes_event_id IS DISTINCT FROM grant_event.id THEN
        RAISE EXCEPTION 'consent withdrawal idempotency collision';
    END IF;

    INSERT INTO public.ml_consent_event_purposes (
        consent_event_id, purpose, article_6_basis, article_9_basis
    )
    SELECT withdrawal.id, purpose, article_6_basis, article_9_basis
      FROM public.ml_consent_event_purposes
     WHERE consent_event_id = grant_event.id
    ON CONFLICT (consent_event_id, purpose) DO NOTHING;

    INSERT INTO public.ml_purge_requests (
        acquisition_principal_id, speaker_id, withdrawal_event_id, reason,
        requested_at, requested_by, idempotency_key
    )
    SELECT p_acquisition_principal_id, binding.speaker_id, withdrawal.id,
           'consent_withdrawal', p_occurred_at,
           'record_mlc2_consent_withdrawal_v1',
           p_idempotency_key || ':purge'
      FROM public.ml_speaker_principals binding
     WHERE binding.acquisition_principal_id = p_acquisition_principal_id
    ON CONFLICT (idempotency_key) DO NOTHING;

    SELECT * INTO purge_request FROM public.ml_purge_requests
     WHERE idempotency_key = p_idempotency_key || ':purge';
    IF purge_request.id IS NOT NULL THEN
        INSERT INTO public.ml_purge_events (
            purge_request_id, event_kind, detail, occurred_at, idempotency_key
        ) VALUES (
            purge_request.id, 'requested', jsonb_build_object(
                'trigger', 'consent_withdrawal',
                'withdrawal_event_id', withdrawal.id
            ), p_occurred_at, p_idempotency_key || ':purge:requested'
        ) ON CONFLICT (idempotency_key) DO NOTHING;
    END IF;
    RETURN withdrawal;
END;
$$;

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
SET search_path = extensions, public
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
           AND existing.grant_scope = 'bundled_v1'
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
       AND (candidate.retired_at IS NULL OR candidate.retired_at > now())
       AND candidate.grant_scope = 'bundled_v1';
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
       AND (candidate.retired_at IS NULL OR candidate.retired_at > now())
       AND candidate.grant_scope = 'bundled_v1';
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

CREATE OR REPLACE FUNCTION public.get_mlc2_confidence_canary_readiness_v1(
    p_founder_principal_id UUID DEFAULT NULL
) RETURNS JSONB
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = public
AS $$
SELECT jsonb_build_object(
    'readiness_contract_version', 'mlc2-confidence-canary-readiness-v1',
    'learning_contract_version', 'MLC-2',
    'data_epoch', 1,
    'learning_surface', 'confidence_classification',
    'founder_principal_configured', p_founder_principal_id IS NOT NULL,
    'active_consent_policy_count', (
        SELECT count(*) FROM ml_consent_policies policy
         WHERE policy.active_from <= now()
           AND (policy.retired_at IS NULL OR policy.retired_at > now())
           AND policy.grant_scope = 'bundled_v1'
    ),
    'valid_active_consent_policy_count', (
        SELECT count(*)
          FROM ml_consent_policies policy
          JOIN ml_product_legal_approvals approval
            ON approval.id = policy.product_legal_approval_id
         WHERE policy.active_from <= now()
           AND (policy.retired_at IS NULL OR policy.retired_at > now())
           AND policy.required_for_service
           AND policy.bundled_ui
           AND policy.grant_scope = 'bundled_v1'
           AND approval.consent_policy_version = policy.version
           AND approval.article_6_basis = '6(1)(a)'
           AND approval.article_9_treatment IN (
               'not_applicable', '9(2)(a)_when_special_category'
           )
           AND length(approval.approved_copy_sha256) = 64
           AND length(approval.evidence_sha256) = 64
           AND NULLIF(btrim(approval.approval_reference), '') IS NOT NULL
           AND NULLIF(btrim(approval.evidence_object_key), '') IS NOT NULL
    ),
    'founder_active_bundled_consent_grant_count', (
        SELECT count(*)
          FROM ml_consent_events consent_event
          JOIN ml_consent_policies policy
            ON policy.version = consent_event.consent_policy_version
         WHERE p_founder_principal_id IS NOT NULL
           AND consent_event.acquisition_principal_id = p_founder_principal_id
           AND consent_event.event_kind = 'grant'
           AND policy.grant_scope = 'bundled_v1'
           AND policy.active_from <= now()
           AND (policy.retired_at IS NULL OR policy.retired_at > now())
           AND NOT EXISTS (
               SELECT 1 FROM ml_consent_events withdrawal
                WHERE withdrawal.event_kind = 'withdraw'
                  AND withdrawal.supersedes_event_id = consent_event.id
                  AND withdrawal.occurred_at <= now()
           )
           AND (
               SELECT count(*) FROM ml_consent_event_purposes purpose
                WHERE purpose.consent_event_id = consent_event.id
                  AND purpose.purpose IN (
                      'personalized_coaching', 'pooled_model_improvement'
                  )
                  AND purpose.article_6_basis = '6(1)(a)'
           ) = 2
    ),
    'founder_producer_receipt_count', (
        SELECT count(*) FROM ml_confidence_producer_receipts receipt
         WHERE p_founder_principal_id IS NOT NULL
           AND receipt.acquisition_principal_id = p_founder_principal_id
    ),
    'nonfounder_producer_receipt_count', (
        SELECT count(*) FROM ml_confidence_producer_receipts receipt
         WHERE p_founder_principal_id IS NULL
            OR receipt.acquisition_principal_id <> p_founder_principal_id
    ),
    'nonfounder_canonical_event_count', (
        SELECT count(*) FROM ml_canonical_events event
         WHERE event.learning_surface_id = 'confidence_classification'
           AND (p_founder_principal_id IS NULL
                OR event.acquisition_principal_id <> p_founder_principal_id)
    ),
    'pending_confidence_outbox_count', (
        SELECT count(*) FROM ml_outbox_events event
         WHERE event.learning_surface_id = 'confidence_classification'
           AND event.event_type = 'confidence_take_ready'
           AND event.processed_at IS NULL
    ),
    'failed_confidence_outbox_count', (
        SELECT count(*) FROM ml_outbox_events event
         WHERE event.learning_surface_id = 'confidence_classification'
           AND event.event_type = 'confidence_take_ready'
           AND event.processed_at IS NULL
           AND event.last_error_code IS NOT NULL
    ),
    'oldest_pending_confidence_outbox_at', (
        SELECT min(event.created_at) FROM ml_outbox_events event
         WHERE event.learning_surface_id = 'confidence_classification'
           AND event.event_type = 'confidence_take_ready'
           AND event.processed_at IS NULL
    ),
    'receipt_without_outbox_count', (
        SELECT count(*) FROM ml_confidence_producer_receipts receipt
         WHERE NOT EXISTS (
             SELECT 1 FROM ml_outbox_events event
              WHERE event.id = receipt.outbox_event_id
         )
    ),
    'processed_without_frame_count', (
        SELECT count(*) FROM ml_confidence_producer_receipts receipt
        JOIN ml_outbox_events event ON event.id = receipt.outbox_event_id
         WHERE event.processed_at IS NOT NULL
           AND NOT EXISTS (
               SELECT 1 FROM ml_canonical_events canonical
               JOIN ml_candidate_sets candidate_set
                 ON candidate_set.canonical_event_id = canonical.id
                WHERE canonical.source_outbox_event_id = event.id
           )
    ),
    'blind_assignment_without_packet_count', (
        SELECT count(*) FROM ml_review_assignments assignment
         WHERE assignment.learning_surface_id = 'confidence_classification'
           AND NOT EXISTS (
               SELECT 1 FROM ml_confidence_blind_packets packet
                WHERE packet.review_assignment_id = assignment.id
           )
    ),
    'revealed_without_judgment_count', (
        SELECT count(*) FROM ml_review_assignment_events assignment_event
         WHERE assignment_event.event_kind = 'revealed'
           AND NOT EXISTS (
               SELECT 1 FROM ml_judgments judgment
                WHERE judgment.review_assignment_id =
                      assignment_event.review_assignment_id
           )
    ),
    'dataset_creation_enabled', false,
    'training_enabled', false,
    'promotion_enabled', false
);
$$;

REVOKE ALL ON FUNCTION public.record_mlc2_consent_grant_v1(
    UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, TIMESTAMPTZ,
    BOOLEAN, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_mlc2_consent_grant_v1(
    UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, TIMESTAMPTZ,
    BOOLEAN, TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.record_mlc2_consent_withdrawal_v1(
    UUID, UUID, TEXT, TEXT, JSONB, TIMESTAMPTZ, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_mlc2_consent_withdrawal_v1(
    UUID, UUID, TEXT, TEXT, JSONB, TIMESTAMPTZ, TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.configure_mlc2_consent_policy_v1(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ, TEXT[], TEXT,
    TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.configure_mlc2_consent_policy_v1(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ, TEXT[], TEXT,
    TEXT, TEXT, TIMESTAMPTZ
) TO service_role;
REVOKE ALL ON FUNCTION public.get_mlc2_principal_consent_status_v1(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_mlc2_principal_consent_status_v1(UUID)
    TO service_role;
REVOKE ALL ON FUNCTION public.get_mlc2_confidence_canary_readiness_v1(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_mlc2_confidence_canary_readiness_v1(UUID)
    TO service_role;

DO $receipt_refuses_training$
DECLARE
 target regprocedure := to_regprocedure(
  'public.accept_phase1_processing_authorization_v2(uuid,text,text,text,text,text,text,boolean,text,text,text,timestamptz,text,text[])');
 marker text := 'TRAINING_IS_NOT_A_RECEIPT_CHOICE';
 anchor text := E'        RAISE EXCEPTION ''PROCESSING_OPTIONAL_PURPOSE_INVALID: %'',\n            unknown_purpose;\n    END IF;\n';
 refusal text := E'    -- 0377: training is its own yes, on its own screen (N7).\n    IF ''pooled_model_improvement'' = ANY(chosen) THEN\n        RAISE EXCEPTION ''TRAINING_IS_NOT_A_RECEIPT_CHOICE'';\n    END IF;\n';
 definition text;
 anchors integer;
BEGIN
 IF target IS NULL THEN
  RAISE EXCEPTION 'RECEIPT_WRITER_MISSING';
 END IF;
 definition := pg_get_functiondef(target);
 IF position(marker IN definition) > 0 THEN
  RETURN;
 END IF;
 anchors := (length(definition) - length(replace(definition, anchor, ''))) / length(anchor);
 IF anchors <> 1 THEN
  RAISE EXCEPTION 'RECEIPT_WRITER_BODY_DRIFT: % anchors', anchors;
 END IF;
 EXECUTE replace(definition, anchor, anchor || refusal);
 definition := pg_get_functiondef(target);
 IF position(marker IN definition) = 0
    OR position('D11 writer: authorization receipt' IN definition) = 0 THEN
  RAISE EXCEPTION 'RECEIPT_WRITER_BODY_DRIFT: markers';
 END IF;
END
$receipt_refuses_training$;

REVOKE ALL ON FUNCTION public.accept_phase1_processing_authorization_v2(
    UUID,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,BOOLEAN,TEXT,TEXT,TEXT,TIMESTAMPTZ,TEXT,
    TEXT[]
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.accept_phase1_processing_authorization_v2(
    UUID,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,BOOLEAN,TEXT,TEXT,TEXT,TIMESTAMPTZ,TEXT,
    TEXT[]
) TO service_role;

COMMIT;
