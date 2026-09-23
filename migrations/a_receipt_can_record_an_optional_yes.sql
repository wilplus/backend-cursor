-- 0356 · A receipt can record an optional yes.
--
-- P11's prerequisite. Founder decision 2026-09-23: build this BEFORE
-- republishing the policy, so the republish is one cutover and nothing goes
-- dark.
--
-- ── THE TRAP THIS BREAKS ────────────────────────────────────────────────
--
-- `accept_phase1_processing_authorization_v1` writes receipt purpose rows
-- only `WHERE pp.required_for_core_service`. A purpose someone could DECLINE
-- therefore leaves no evidence in the receipt at all — and for coach_review,
-- whose lawful basis IS consent, that is not a gap in the paperwork, it is
-- the absence of the lawful basis. legal/phase1-2026.1/01-product-legal-
-- approval §6 says exactly this, and held three purposes out of v1 over it.
--
-- Meanwhile `resolve_mlc3_dual_purpose_receipt_v2` gates the entire MLC-3
-- general-user service on the receipt NAMING both
-- `personalized_exercise_recommendation` and `coach_review`.
--
-- Those two facts together meant the only way the exercise service could run
-- was if both purposes were marked required — which is the service-conditional
-- bundled consent doc 01 §3 assesses as invalid under Art 4(11) and Art 7(4)
-- with Recital 43. The lawful policy and the working product were mutually
-- exclusive, and not by anyone's choice: a receipt simply had no way to say
-- "they were asked, separately, and said yes". Now it has one.
--
-- ── WHAT CHANGES, AND WHAT DOES NOT ─────────────────────────────────────
--
-- v2 sits BESIDE v1 and never replaces it. The signature differs, so this
-- could not be a CREATE OR REPLACE of v1 even if that were wanted — and it is
-- not: dropping a live consent writer to change its shape is not something
-- this repository does. v1 keeps working and keeps its grants.
--
-- Called with no optional purposes, v2 does what v1 does, with one deliberate
-- difference: the evidence hash covers the choices. Without that, replaying
-- one idempotency key with a DIFFERENT set of choices would hash identically
-- to the first call, be accepted as a silent no-op, and leave a receipt
-- attesting to a decision the person did not make the second time.
--
-- Three further properties, each because the alternative is a lie in the
-- evidence:
--
--   * a named purpose that is not an optional purpose of THIS policy is
--     REFUSED, not ignored — silently dropping it writes a receipt recording
--     less than the screen asked about;
--   * a named purpose that is REQUIRED is refused too — it is already in the
--     receipt, and accepting it here would let a caller present a compulsory
--     term as though it had been a choice;
--   * the choices are de-duplicated and sorted before hashing, because the
--     order a client sent them in is not a fact about consent.
--
-- ── NOTHING CALLS THIS YET, ON PURPOSE ──────────────────────────────────
--
-- The route still calls v1, and must, until the policy carries optional
-- purposes for v2 to record. Three things ship together, later:
--   1. this function                                              (here)
--   2. the republished policy with coach_review and
--      personalized_exercise_recommendation as
--      required_for_core_service FALSE            (scripts/, by hand, founder)
--   3. the acceptance screen offering the separate tick, and
--      services/processing_authorization.accept() sending it
--                                          (frontend + copy, founder sign-off)
--
-- Landing this one alone changes no behaviour whatsoever. That is the point:
-- it is the piece that has to exist before the other two are possible.
--
-- ADDITIVE AND IDEMPOTENT. One CREATE OR REPLACE FUNCTION of a name that does
-- not exist yet, plus its grants. Nothing belonging to anything else is
-- created, altered or dropped.

CREATE OR REPLACE FUNCTION public.accept_phase1_processing_authorization_v2(
    p_acquisition_principal_id UUID, p_policy_version TEXT,
    p_terms_copy_sha256 TEXT, p_privacy_copy_sha256 TEXT,
    p_ai_notice_copy_sha256 TEXT, p_agreement_copy_sha256 TEXT,
    p_explicit_action TEXT, p_age_18_attested BOOLEAN,
    p_country_of_residence TEXT, p_locale TEXT, p_client_version TEXT,
    p_accepted_at TIMESTAMPTZ, p_idempotency_key TEXT,
    -- The optional purposes this person affirmatively chose. Empty is the
    -- normal case and behaves exactly as v1 does.
    p_optional_purposes TEXT[] DEFAULT '{}'::TEXT[]
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    policy processing_policy_versions;
    receipt processing_authorization_receipts;
    evidence_hash TEXT;
    existing_hash TEXT;
    chosen TEXT[];
    unknown_purpose TEXT;
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

    -- The choices, canonicalised: blanks dropped, de-duplicated, sorted. The
    -- order a client happened to send them in is not a fact about consent,
    -- and two clients sending the same set differently must not produce two
    -- different evidence hashes for the same decision.
    SELECT COALESCE(array_agg(DISTINCT btrim(value) ORDER BY btrim(value)),
                    '{}'::TEXT[])
      INTO chosen
      FROM unnest(COALESCE(p_optional_purposes, '{}'::TEXT[])) AS value
     WHERE COALESCE(btrim(value), '') <> '';

    -- A name that is not an OPTIONAL purpose of THIS policy is refused rather
    -- than ignored. Silently dropping it would write a receipt recording less
    -- than the screen asked about; and accepting a REQUIRED purpose here would
    -- let a caller present a compulsory term as though it had been a choice.
    SELECT value INTO unknown_purpose
      FROM unnest(chosen) AS value
     WHERE NOT EXISTS (
         SELECT 1 FROM processing_policy_purposes pp
          WHERE pp.policy_id = policy.id
            AND pp.purpose_id = value
            AND NOT pp.required_for_core_service
     ) LIMIT 1;
    IF unknown_purpose IS NOT NULL THEN
        RAISE EXCEPTION 'PROCESSING_OPTIONAL_PURPOSE_INVALID: %',
            unknown_purpose;
    END IF;

    evidence_hash := encode(extensions.digest(concat_ws(':',
        p_acquisition_principal_id::text, policy.id::text,
        p_terms_copy_sha256, p_privacy_copy_sha256, p_ai_notice_copy_sha256,
        p_agreement_copy_sha256, p_explicit_action,
        p_age_18_attested::text, lower(btrim(p_country_of_residence)),
        p_locale, p_client_version, p_accepted_at::text, p_idempotency_key,
        -- WITHOUT THIS, TWO DIFFERENT DECISIONS HASH THE SAME. A replay of one
        -- idempotency key with a different set of choices would hash
        -- identically to the first, be accepted as a silent no-op, and leave a
        -- receipt attesting to a decision the person did not make the second
        -- time. It raises IDEMPOTENCY_CONFLICT instead, which is what that
        -- error is for.
        array_to_string(chosen, ',')
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
    -- Required purposes, exactly as v1 writes them, PLUS the optional ones
    -- this person chose. One statement, so a receipt can never hold half of a
    -- decision, and each row still carries the POLICY's lawful basis for that
    -- purpose rather than one invented here.
    INSERT INTO processing_authorization_receipt_purposes (
        receipt_id, purpose_id, lawful_basis_code
    ) SELECT receipt.id, pp.purpose_id, pp.lawful_basis_code
        FROM processing_policy_purposes pp
       WHERE pp.policy_id = policy.id
         AND (pp.required_for_core_service OR pp.purpose_id = ANY(chosen))
    ON CONFLICT DO NOTHING;
    RETURN jsonb_build_object(
        'authorized', true, 'receipt_id', receipt.id,
        'policy_version', policy.version, 'pooled_learning_eligible', false,
        'optional_purposes_recorded', to_jsonb(chosen)
    );
END;
$$;

-- Same grants v1 carries: service_role only, by exact signature. The route is
-- the only caller there will ever be, and it runs as service_role.
REVOKE ALL ON FUNCTION public.accept_phase1_processing_authorization_v2(
    UUID,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,BOOLEAN,TEXT,TEXT,TEXT,TIMESTAMPTZ,TEXT,
    TEXT[]
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.accept_phase1_processing_authorization_v2(
    UUID,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,BOOLEAN,TEXT,TEXT,TEXT,TIMESTAMPTZ,TEXT,
    TEXT[]
) TO service_role;
