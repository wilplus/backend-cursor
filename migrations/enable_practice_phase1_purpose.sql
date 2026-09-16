-- 0335 · Confident Voice practice becomes a phase-1 purpose.
--
-- FOUNDER AUTHORIZATION, 2026-09-16. `personalized_exercise_recommendation`
-- was registered as phase2, sitting beside `pooled_model_improvement`, so no
-- consent policy could carry it and no provider permit could be issued for
-- it. That classification says "we are doing something with people's data
-- beyond delivering their own service". Practice is not that: a speaker
-- records an attempt and gets the comparison back, for themselves, at once.
-- Nothing is pooled and no model is trained. The founder reclassified it.
--
-- THIS MIGRATION IS THE LAST STEP, DELIBERATELY. The three controls the
-- registry demands had to be TRUE before they could be declared:
--   * deletion  — until 0334 the purge deleted practice ROWS and left the
--                 recordings in the bucket. It now reaches the objects.
--   * retention — nothing deleted practice attempts by age at all.
--                 services/practice_retention.py is the founder's Option A:
--                 keep while open, then keep only the attempt they chose and
--                 let the rest go after 30 days.
--   * rights    — carried by the same phase-1 controls as every other purpose
--                 here; practice audio is not a new KIND of data, it is more
--                 voice captured for the same speaker's benefit.
-- Declaring them before they existed would have been the paper-only claim
-- this whole boundary exists to prevent.
--
-- WHY THE TWO FUNCTIONS ARE REPLACED. Both named the phase-2 purposes in a
-- hardcoded list, so the registry and the functions could disagree — and did:
-- moving the registry row alone would have left both still refusing it. They
-- now ASK the registry, which makes that disagreement unrepresentable.
-- `pooled_model_improvement` stays refused because it is still phase2.
--
-- Both bodies below are the originals from add_phase1_processing_boundary.sql
-- with exactly that one check rewritten — generated, not retyped, so nothing
-- else in a security-critical function can drift.

BEGIN;

UPDATE public.processing_purpose_registry SET
    phase = 'phase1',
    operational = true,
    authorizes_processing = true,
    capability_version = 'confident-voice-practice-v1',
    reviewed_at = now(),
    retention_control_version = 'practice-retention-option-a-30d-v1',
    deletion_control_version = 'phase1-purge-practice-objects-v1',
    rights_control_version = 'phase1-subject-rights-v1'
WHERE id = 'personalized_exercise_recommendation';

-- The registry's own invariant already refuses an authorizing purpose with a
-- missing control version. This says the same thing at migration time, so a
-- typo above fails here rather than at the first speaker's recording.
DO $guard$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.processing_purpose_registry
         WHERE id = 'personalized_exercise_recommendation'
           AND phase = 'phase1' AND operational AND authorizes_processing
           AND capability_version IS NOT NULL
           AND reviewed_at IS NOT NULL
           AND retention_control_version IS NOT NULL
           AND deletion_control_version IS NOT NULL
           AND rights_control_version IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'PRACTICE_PURPOSE_NOT_FULLY_CONTROLLED';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.processing_purpose_registry
         WHERE id = 'pooled_model_improvement' AND phase = 'phase2'
    ) THEN
        RAISE EXCEPTION 'POOLED_LEARNING_MUST_REMAIN_PHASE2';
    END IF;
END
$guard$;

CREATE OR REPLACE FUNCTION public.accept_phase1_processing_authorization_v1(
    p_acquisition_principal_id UUID, p_policy_version TEXT,
    p_terms_copy_sha256 TEXT, p_privacy_copy_sha256 TEXT,
    p_ai_notice_copy_sha256 TEXT, p_agreement_copy_sha256 TEXT,
    p_explicit_action TEXT, p_age_18_attested BOOLEAN,
    p_country_of_residence TEXT, p_locale TEXT, p_client_version TEXT,
    p_accepted_at TIMESTAMPTZ, p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    policy processing_policy_versions;
    receipt processing_authorization_receipts;
    evidence_hash TEXT;
    existing_hash TEXT;
BEGIN
    SELECT * INTO policy FROM processing_policy_versions
     WHERE version = p_policy_version AND status = 'active'
       AND activated_at <= now()
       AND (retired_at IS NULL OR retired_at > now()) LIMIT 1;
    IF policy.id IS NULL OR policy.product_legal_artifact_id IS NULL THEN
        RAISE EXCEPTION 'PROCESSING_POLICY_UNAPPROVED';
    END IF;
    IF p_explicit_action <> 'agree_and_continue' OR NOT p_age_18_attested THEN
        RAISE EXCEPTION 'EXPLICIT_ACCEPTANCE_REQUIRED';
    END IF;
    IF NOT (lower(btrim(p_country_of_residence)) = ANY(policy.allowed_countries)) THEN
        RAISE EXCEPTION 'COUNTRY_NOT_ALLOWED';
    END IF;
    IF p_terms_copy_sha256 <> policy.terms_copy_sha256
       OR p_privacy_copy_sha256 <> policy.privacy_copy_sha256
       OR p_ai_notice_copy_sha256 <> policy.ai_notice_copy_sha256
       OR p_agreement_copy_sha256 <> policy.agreement_copy_sha256 THEN
        RAISE EXCEPTION 'PROCESSING_POLICY_STALE';
    END IF;
    IF EXISTS (
        SELECT 1 FROM processing_policy_purposes pp
        JOIN processing_purpose_registry pr ON pr.id = pp.purpose_id
          WHERE pp.policy_id = policy.id AND pp.required_for_core_service
            AND (NOT pr.operational OR NOT pr.authorizes_processing)
    ) THEN RAISE EXCEPTION 'PROCESSING_PURPOSE_NOT_OPERATIONAL'; END IF;
    IF EXISTS (
        SELECT 1 FROM processing_policy_purposes pp
        JOIN processing_purpose_registry pr ON pr.id = pp.purpose_id
         WHERE pp.policy_id = policy.id AND pr.phase = 'phase2'
    ) THEN RAISE EXCEPTION 'PHASE2_PURPOSE_FORBIDDEN'; END IF;

    evidence_hash := encode(extensions.digest(concat_ws(':',
        p_acquisition_principal_id::text, policy.id::text,
        p_terms_copy_sha256, p_privacy_copy_sha256, p_ai_notice_copy_sha256,
        p_agreement_copy_sha256, p_explicit_action,
        p_age_18_attested::text, lower(btrim(p_country_of_residence)),
        p_locale, p_client_version, p_accepted_at::text, p_idempotency_key
    ), 'sha256'), 'hex');
    SELECT evidence_sha256 INTO existing_hash
      FROM processing_authorization_receipts
     WHERE acquisition_principal_id = p_acquisition_principal_id
       AND idempotency_key = p_idempotency_key;
    IF existing_hash IS NOT NULL AND existing_hash <> evidence_hash THEN
        RAISE EXCEPTION 'IDEMPOTENCY_CONFLICT';
    END IF;
    INSERT INTO processing_authorization_receipts (
        acquisition_principal_id, policy_id, idempotency_key, explicit_action,
        age_18_attested, country_of_residence, locale, client_version,
        accepted_at, evidence_sha256, pooled_learning_eligible
    ) VALUES (
        p_acquisition_principal_id, policy.id, p_idempotency_key,
        p_explicit_action, p_age_18_attested,
        lower(btrim(p_country_of_residence)), p_locale, p_client_version,
        p_accepted_at, evidence_hash, false
    ) ON CONFLICT (acquisition_principal_id, idempotency_key) DO NOTHING;
    SELECT * INTO receipt FROM processing_authorization_receipts
     WHERE acquisition_principal_id = p_acquisition_principal_id
       AND idempotency_key = p_idempotency_key;
    INSERT INTO processing_authorization_receipt_purposes (
        receipt_id, purpose_id, lawful_basis_code
    ) SELECT receipt.id, pp.purpose_id, pp.lawful_basis_code
        FROM processing_policy_purposes pp
       WHERE pp.policy_id = policy.id AND pp.required_for_core_service
    ON CONFLICT DO NOTHING;
    RETURN jsonb_build_object(
        'authorized', true, 'receipt_id', receipt.id,
        'policy_version', policy.version, 'pooled_learning_eligible', false
    );
END;
$$;
-- Re-stated, not inherited. A reader of this file can see who may execute the
-- function it replaces without going back to the migration that created it.
REVOKE ALL ON FUNCTION public.accept_phase1_processing_authorization_v1(
    UUID,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,BOOLEAN,TEXT,TEXT,TEXT,TIMESTAMPTZ,TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.accept_phase1_processing_authorization_v1(
    UUID,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,BOOLEAN,TEXT,TEXT,TEXT,TIMESTAMPTZ,TEXT
) TO service_role;

CREATE OR REPLACE FUNCTION public.register_phase1_policy_v1(
    p_policy JSONB, p_product_legal JSONB,
    p_power_score_classification JSONB, p_article50 JSONB,
    p_purposes JSONB, p_actor TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    legal_id UUID; power_id UUID; article50_id UUID; v_policy_id UUID;
    item JSONB; v_purpose_id TEXT; existing_purpose processing_policy_purposes;
    registry_purpose processing_purpose_registry; policy_preexisting BOOLEAN := false;
    registration_hash TEXT;
BEGIN
    -- Serializes the reviewed admin-only registration path, so the explicit
    -- select-then-insert append-only pattern cannot race on unique versions.
    PERFORM pg_advisory_xact_lock(hashtext('phase1-policy-registry'));
    IF jsonb_typeof(p_purposes) <> 'array' OR jsonb_array_length(p_purposes) = 0
    THEN RAISE EXCEPTION 'POLICY_PURPOSES_REQUIRED'; END IF;
    IF encode(extensions.digest(COALESCE(p_policy->>'terms_copy', ''),
                                'sha256'), 'hex') <>
           COALESCE(p_policy->>'terms_copy_sha256', '')
       OR encode(extensions.digest(COALESCE(p_policy->>'privacy_copy', ''),
                                   'sha256'), 'hex') <>
           COALESCE(p_policy->>'privacy_copy_sha256', '')
       OR encode(extensions.digest(COALESCE(p_policy->>'ai_notice_copy', ''),
                                   'sha256'), 'hex') <>
           COALESCE(p_policy->>'ai_notice_copy_sha256', '')
       OR encode(extensions.digest(COALESCE(p_policy->>'agreement_copy', ''),
                                   'sha256'), 'hex') <>
           COALESCE(p_policy->>'agreement_copy_sha256', '')
    THEN RAISE EXCEPTION 'POLICY_COPY_HASH_MISMATCH'; END IF;
    IF COALESCE(p_product_legal->>'artifact_kind', '') <> 'product_legal_approval'
       OR COALESCE(p_power_score_classification->>'artifact_kind', '') <>
          'power_score_classification'
       OR COALESCE(p_article50->>'artifact_kind', '') <> 'article_50_assessment'
    THEN RAISE EXCEPTION 'LEGAL_ARTIFACT_KIND_INVALID'; END IF;
    IF COALESCE((p_power_score_classification->'metadata'->>
                 'biometric_identification')::boolean, true)
       OR COALESCE((p_power_score_classification->'metadata'->>
                    'sex_gender_inference')::boolean, true)
       OR COALESCE((p_power_score_classification->'metadata'->>
                    'emotion_intention_inference')::boolean, true)
    THEN RAISE EXCEPTION 'POWER_SCORE_CLASSIFICATION_CONFLICT'; END IF;
    IF COALESCE(p_power_score_classification->'metadata'->>'pipeline_version', '')
       <> 'voice-confidence-universal-v3'
    THEN RAISE EXCEPTION 'POWER_SCORE_PIPELINE_VERSION_UNAPPROVED'; END IF;

    SELECT id INTO legal_id FROM processing_legal_artifacts
     WHERE artifact_kind = 'product_legal_approval'
       AND version = p_product_legal->>'version';
    IF legal_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM processing_legal_artifacts WHERE id = legal_id
          AND approving_authority = p_product_legal->>'approving_authority'
          AND approved_at = (p_product_legal->>'approved_at')::timestamptz
          AND object_key = p_product_legal->>'object_key'
          AND sha256 = p_product_legal->>'sha256'
          AND metadata = COALESCE(p_product_legal->'metadata', '{}'::jsonb)
    ) THEN RAISE EXCEPTION 'LEGAL_ARTIFACT_VERSION_CONFLICT'; END IF;
    IF legal_id IS NULL THEN
        INSERT INTO processing_legal_artifacts (
            artifact_kind, version, approving_authority, approved_at,
            object_key, sha256, metadata
        ) VALUES (
            p_product_legal->>'artifact_kind', p_product_legal->>'version',
            p_product_legal->>'approving_authority',
            (p_product_legal->>'approved_at')::timestamptz,
            p_product_legal->>'object_key', p_product_legal->>'sha256',
            COALESCE(p_product_legal->'metadata', '{}'::jsonb)
        ) RETURNING id INTO legal_id;
    END IF;

    SELECT id INTO power_id FROM processing_legal_artifacts
     WHERE artifact_kind = 'power_score_classification'
       AND version = p_power_score_classification->>'version';
    IF power_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM processing_legal_artifacts WHERE id = power_id
          AND approving_authority = p_power_score_classification->>'approving_authority'
          AND approved_at = (p_power_score_classification->>'approved_at')::timestamptz
          AND object_key = p_power_score_classification->>'object_key'
          AND sha256 = p_power_score_classification->>'sha256'
          AND metadata = COALESCE(
              p_power_score_classification->'metadata', '{}'::jsonb)
    ) THEN RAISE EXCEPTION 'POWER_SCORE_ARTIFACT_VERSION_CONFLICT'; END IF;
    IF power_id IS NULL THEN
        INSERT INTO processing_legal_artifacts (
            artifact_kind, version, approving_authority, approved_at,
            object_key, sha256, metadata
        ) VALUES (
            p_power_score_classification->>'artifact_kind',
            p_power_score_classification->>'version',
            p_power_score_classification->>'approving_authority',
            (p_power_score_classification->>'approved_at')::timestamptz,
            p_power_score_classification->>'object_key',
            p_power_score_classification->>'sha256',
            COALESCE(p_power_score_classification->'metadata', '{}'::jsonb)
        ) RETURNING id INTO power_id;
    END IF;

    SELECT id INTO article50_id FROM processing_legal_artifacts
     WHERE artifact_kind = 'article_50_assessment'
       AND version = p_article50->>'version';
    IF article50_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM processing_legal_artifacts WHERE id = article50_id
          AND approving_authority = p_article50->>'approving_authority'
          AND approved_at = (p_article50->>'approved_at')::timestamptz
          AND object_key = p_article50->>'object_key'
          AND sha256 = p_article50->>'sha256'
          AND metadata = COALESCE(p_article50->'metadata', '{}'::jsonb)
    ) THEN RAISE EXCEPTION 'ARTICLE50_ARTIFACT_VERSION_CONFLICT'; END IF;
    IF article50_id IS NULL THEN
        INSERT INTO processing_legal_artifacts (
            artifact_kind, version, approving_authority, approved_at,
            object_key, sha256, metadata
        ) VALUES (
            p_article50->>'artifact_kind', p_article50->>'version',
            p_article50->>'approving_authority',
            (p_article50->>'approved_at')::timestamptz,
            p_article50->>'object_key', p_article50->>'sha256',
            COALESCE(p_article50->'metadata', '{}'::jsonb)
        ) RETURNING id INTO article50_id;
    END IF;

    SELECT id INTO v_policy_id FROM processing_policy_versions
     WHERE version = p_policy->>'version';
    policy_preexisting := v_policy_id IS NOT NULL;
    IF policy_preexisting AND NOT EXISTS (
        SELECT 1 FROM processing_policy_versions policy
         WHERE policy.id = v_policy_id
           AND policy.status IN ('approved', 'active')
           AND policy.product_legal_artifact_id = legal_id
           AND policy.power_score_classification_artifact_id = power_id
           AND policy.article50_artifact_id = article50_id
           AND policy.terms_version = p_policy->>'terms_version'
           AND policy.terms_copy = p_policy->>'terms_copy'
           AND policy.terms_copy_sha256 = p_policy->>'terms_copy_sha256'
           AND policy.privacy_version = p_policy->>'privacy_version'
           AND policy.privacy_copy = p_policy->>'privacy_copy'
           AND policy.privacy_copy_sha256 = p_policy->>'privacy_copy_sha256'
           AND policy.ai_notice_version = p_policy->>'ai_notice_version'
           AND policy.ai_notice_copy = p_policy->>'ai_notice_copy'
           AND policy.ai_notice_copy_sha256 = p_policy->>'ai_notice_copy_sha256'
           AND policy.agreement_copy = p_policy->>'agreement_copy'
           AND policy.agreement_copy_sha256 = p_policy->>'agreement_copy_sha256'
           AND policy.allowed_countries = ARRAY(
               SELECT lower(value) FROM jsonb_array_elements_text(
                   p_policy->'allowed_countries'
               ) AS value ORDER BY lower(value)
           )
    ) THEN RAISE EXCEPTION 'POLICY_VERSION_CONFLICT'; END IF;
    IF v_policy_id IS NULL THEN
        INSERT INTO processing_policy_versions (
            version, status, product_legal_artifact_id,
            power_score_classification_artifact_id, article50_artifact_id,
            terms_version, terms_copy, terms_copy_sha256,
            privacy_version, privacy_copy, privacy_copy_sha256,
            ai_notice_version, ai_notice_copy, ai_notice_copy_sha256,
            agreement_copy, agreement_copy_sha256, allowed_countries,
            created_by
        ) VALUES (
            p_policy->>'version', 'approved', legal_id, power_id, article50_id,
            p_policy->>'terms_version', p_policy->>'terms_copy',
            p_policy->>'terms_copy_sha256', p_policy->>'privacy_version',
            p_policy->>'privacy_copy', p_policy->>'privacy_copy_sha256',
            p_policy->>'ai_notice_version', p_policy->>'ai_notice_copy',
            p_policy->>'ai_notice_copy_sha256', p_policy->>'agreement_copy',
            p_policy->>'agreement_copy_sha256', ARRAY(
                SELECT lower(value) FROM jsonb_array_elements_text(
                    p_policy->'allowed_countries'
                ) AS value ORDER BY lower(value)
            ), p_actor
        ) RETURNING id INTO v_policy_id;
    END IF;

    FOR item IN SELECT value FROM jsonb_array_elements(p_purposes) LOOP
        v_purpose_id := item->>'purpose_id';
        IF EXISTS (
            SELECT 1 FROM processing_purpose_registry
             WHERE id = v_purpose_id AND phase = 'phase2'
        ) THEN RAISE EXCEPTION 'PHASE2_PURPOSE_FORBIDDEN'; END IF;
        SELECT * INTO registry_purpose FROM processing_purpose_registry
         WHERE id = v_purpose_id AND phase = 'phase1' FOR UPDATE;
        IF registry_purpose.id IS NULL THEN
            RAISE EXCEPTION 'UNKNOWN_PHASE1_PURPOSE';
        END IF;
        IF registry_purpose.operational AND (
            registry_purpose.capability_version IS DISTINCT FROM
                item->>'capability_version'
            OR registry_purpose.reviewed_at IS DISTINCT FROM
                (item->>'reviewed_at')::timestamptz
            OR registry_purpose.retention_control_version IS DISTINCT FROM
                item->>'retention_control_version'
            OR registry_purpose.deletion_control_version IS DISTINCT FROM
                item->>'deletion_control_version'
            OR registry_purpose.rights_control_version IS DISTINCT FROM
                item->>'rights_control_version'
        ) THEN RAISE EXCEPTION 'PURPOSE_CONTROL_VERSION_CONFLICT'; END IF;
        UPDATE processing_purpose_registry SET operational = true,
            authorizes_processing = true,
            capability_version = item->>'capability_version',
            reviewed_at = (item->>'reviewed_at')::timestamptz,
            retention_control_version = item->>'retention_control_version',
            deletion_control_version = item->>'deletion_control_version',
            rights_control_version = item->>'rights_control_version'
         WHERE id = v_purpose_id AND phase = 'phase1';
        SELECT * INTO existing_purpose FROM processing_policy_purposes
         WHERE policy_id = v_policy_id
           AND purpose_id = v_purpose_id;
        IF existing_purpose.policy_id IS NOT NULL AND (
            existing_purpose.lawful_basis_code IS DISTINCT FROM
                item->>'lawful_basis_code'
            OR existing_purpose.required_for_core_service IS DISTINCT FROM
                COALESCE((item->>'required_for_core_service')::boolean, false)
        ) THEN RAISE EXCEPTION 'POLICY_PURPOSE_CONFLICT'; END IF;
        INSERT INTO processing_policy_purposes (
            policy_id, purpose_id, lawful_basis_code,
            required_for_core_service
        ) VALUES (
            v_policy_id, v_purpose_id, item->>'lawful_basis_code',
            COALESCE((item->>'required_for_core_service')::boolean, false)
        ) ON CONFLICT (policy_id, purpose_id) DO NOTHING;
    END LOOP;
    IF policy_preexisting AND EXISTS (
        SELECT 1 FROM processing_policy_purposes existing
         WHERE existing.policy_id = v_policy_id
           AND NOT EXISTS (
               SELECT 1 FROM jsonb_array_elements(p_purposes) supplied
                WHERE supplied->>'purpose_id' = existing.purpose_id
           )
    ) THEN RAISE EXCEPTION 'POLICY_PURPOSE_SET_CONFLICT'; END IF;
    registration_hash := encode(extensions.digest(
        p_policy::text || p_product_legal::text ||
        p_power_score_classification::text || p_article50::text ||
        p_purposes::text, 'sha256'), 'hex');
    IF NOT EXISTS (
        SELECT 1 FROM phase1_authorization_admin_events
         WHERE event_kind = 'policy_registered'
           AND target_ref = v_policy_id::text
    ) THEN
        INSERT INTO phase1_authorization_admin_events (
            event_kind, actor, target_ref, payload_sha256
        ) VALUES (
            'policy_registered', p_actor, v_policy_id::text, registration_hash
        );
    END IF;
    RETURN jsonb_build_object('policy_id', v_policy_id, 'status', 'approved');
END;
$$;
REVOKE ALL ON FUNCTION public.register_phase1_policy_v1(
    JSONB,JSONB,JSONB,JSONB,JSONB,TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.register_phase1_policy_v1(
    JSONB,JSONB,JSONB,JSONB,JSONB,TEXT
) TO service_role;

COMMIT;
