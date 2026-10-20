-- 0478 · The status read carries the policy text only when it will be shown.
--
-- Founder 2026-10-20: GET /v2/processing-authorization runs on every app
-- open. Its answer is 53,800 bytes, and 52,000 of them are the Terms, the
-- Privacy Policy and the AI notice -- text a person who has already
-- accepted is never shown. Every hop paid for it: Postgres read it out of
-- TOAST and packed it (PL/pgSQL copies a row's TOASTed columns into a
-- record variable in full, so `SELECT * INTO policy` paid even when nothing
-- read them), PostgREST serialised it, Railway parsed and re-sent it,
-- Vercel compressed it and the browser downloaded it, 467 times a day.
--
-- WHAT CHANGES.
--
--   get_phase1_processing_authorization_v2(principal, p_always_with_copy)
--     The status function (0310, 0358, 0422: the 0422 text, block by
--     deletion request included) with one new choice. TRUE: exactly
--     v1's answer. FALSE: the four copies (terms_copy, privacy_copy,
--     ai_notice_copy, agreement_copy) ride along only when the answer is
--     NOT `authorized` -- a first acceptance, a re-acceptance, a block --
--     which are exactly the answers a screen shows the text for. The
--     versions and the hashes are always there, so the acceptance RPC's
--     check (PROCESSING_POLICY_STALE) sees what it always saw. The text
--     columns are read from the row only when they are sent.
--
--   read_phase1_processing_status_v2(user, owner, p_always_with_copy)
--     The one-trip read (0473) with the same choice, passed through to the
--     status function. Everything else in it is 0473, unchanged.
--
--   get_phase1_processing_authorization_v1(principal)
--   read_phase1_processing_status_v1(user, owner)
--     Keep their signatures, their grants and their answers byte for byte:
--     each now calls its v2 with TRUE. The rules live in one place, and
--     nothing that calls v1 (the accept path, the gate's old path, the
--     rehearsal tests of 0358/0422/0473) changes.
--
-- WHAT DOES NOT CHANGE. `authorized`, `code`, `reacceptance_required` and
-- every other key are computed exactly as before, from the same reads in
-- the same order. No decision moves. `authorized` is the only thing that
-- decides whether the text is sent, so a person who must be shown the text
-- always receives it with the hashes it belongs to.
--
-- WHO IT TRUSTS. Nobody new: service_role only, as the functions it
-- replaces and wraps (0313, 0355, 0358, 0422, 0473).
--
-- VOLATILITY. get_..._v2 is STABLE, as v1 is. read_..._v2 declares none, as
-- 0473's read declares none: the resolver it calls is VOLATILE.
--
-- ADDITIVE AND IDEMPOTENT. CREATE OR REPLACE FUNCTION and grants only. No
-- table, column, row, index or grant is created, altered or dropped; no
-- environment variable is needed. Deploy order: this runs in the
-- pre-deploy step, so the application that calls the v2 read finds it;
-- an application that still calls v1 keeps its answer.

-- ── The status, with the text only when it will be shown ─────────────────

CREATE OR REPLACE FUNCTION public.get_phase1_processing_authorization_v2(
    p_acquisition_principal_id UUID,
    p_always_with_copy BOOLEAN DEFAULT TRUE
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER STABLE SET search_path = public
AS $$
DECLARE
    v_policy_id          UUID;
    v_policy_version     TEXT;
    v_terms_version      TEXT;
    v_terms_sha256       TEXT;
    v_privacy_version    TEXT;
    v_privacy_sha256     TEXT;
    v_ai_notice_version  TEXT;
    v_ai_notice_sha256   TEXT;
    v_agreement_sha256   TEXT;
    v_minimum_age        public.processing_policy_versions.minimum_age%TYPE;
    v_allowed_countries  public.processing_policy_versions.allowed_countries%TYPE;
    v_terms_copy         TEXT;
    v_privacy_copy       TEXT;
    v_ai_notice_copy     TEXT;
    v_agreement_copy     TEXT;
    v_receipt_id         UUID;
    v_blocked            BOOLEAN;
    v_held_version       TEXT;
    v_authorized         BOOLEAN;
    v_answer             JSONB;
BEGIN
    -- The policy in force: every column but the four texts, which are the
    -- bulk of the row and are read below only when they are sent.
    SELECT p.id, p.version,
           p.terms_version, p.terms_copy_sha256,
           p.privacy_version, p.privacy_copy_sha256,
           p.ai_notice_version, p.ai_notice_copy_sha256,
           p.agreement_copy_sha256,
           p.minimum_age, p.allowed_countries
      INTO v_policy_id, v_policy_version,
           v_terms_version, v_terms_sha256,
           v_privacy_version, v_privacy_sha256,
           v_ai_notice_version, v_ai_notice_sha256,
           v_agreement_sha256,
           v_minimum_age, v_allowed_countries
      FROM public.processing_policy_versions p
     WHERE p.status = 'active' AND p.activated_at <= now()
       AND (p.retired_at IS NULL OR p.retired_at > now())
     ORDER BY p.activated_at DESC LIMIT 1;
    IF v_policy_id IS NULL THEN
        RETURN jsonb_build_object(
            'authorized', false, 'code', 'PROCESSING_POLICY_INACTIVE',
            'policy_available', false, 'pooled_learning_eligible', false
        );
    END IF;

    -- 0422: an account deletion blocks from the moment it is asked for. A
    -- cancelled one blocks nothing; once its purge starts, the purge's own
    -- block is here too.
    SELECT EXISTS (
        SELECT 1 FROM public.processing_service_blocks b
         WHERE b.acquisition_principal_id = p_acquisition_principal_id
           AND b.effective_at <= now()
    ) OR EXISTS (
        SELECT 1 FROM public.account_deletion_requests d
         WHERE d.acquisition_principal_id = p_acquisition_principal_id
           AND d.state IN ('pending', 'started', 'done')
    ) INTO v_blocked;

    SELECT r.id INTO v_receipt_id
      FROM public.processing_authorization_receipts r
     WHERE r.acquisition_principal_id = p_acquisition_principal_id
       AND r.policy_id = v_policy_id
     ORDER BY r.accepted_at DESC LIMIT 1;

    -- P10 (0422): read only when the active policy has no receipt, so the
    -- re-acceptance screen can say WHICH document moved.
    IF v_receipt_id IS NULL THEN
        SELECT older.version INTO v_held_version
          FROM public.processing_authorization_receipts r
          JOIN public.processing_policy_versions older ON older.id = r.policy_id
         WHERE r.acquisition_principal_id = p_acquisition_principal_id
         ORDER BY r.accepted_at DESC, r.id DESC LIMIT 1;
    END IF;

    v_authorized := v_receipt_id IS NOT NULL AND NOT v_blocked;

    v_answer := jsonb_build_object(
        'authorized', v_authorized,
        'code', CASE
            WHEN v_blocked THEN 'PROCESSING_SERVICE_BLOCKED'
            WHEN v_receipt_id IS NULL THEN 'PROCESSING_AUTHORIZATION_REQUIRED'
            ELSE 'PROCESSING_AUTHORIZED' END,
        'policy_available', true, 'policy_id', v_policy_id,
        'policy_version', v_policy_version,
        'terms_version', v_terms_version,
        'terms_copy_sha256', v_terms_sha256,
        'privacy_version', v_privacy_version,
        'privacy_copy_sha256', v_privacy_sha256,
        'ai_notice_version', v_ai_notice_version,
        'ai_notice_copy_sha256', v_ai_notice_sha256,
        'agreement_copy_sha256', v_agreement_sha256,
        'minimum_age', v_minimum_age,
        'allowed_countries', v_allowed_countries,
        'ai_notice_rendered', EXISTS (
            SELECT 1 FROM public.ai_transparency_exposures e
             WHERE e.acquisition_principal_id = p_acquisition_principal_id
               AND e.ai_notice_version = v_ai_notice_version
        ),
        'receipt_id', v_receipt_id, 'pooled_learning_eligible', false,
        'reacceptance_required',
            v_receipt_id IS NULL AND v_held_version IS NOT NULL AND NOT v_blocked,
        'accepted_policy_version', v_held_version
    );

    -- The text, exactly when a screen will show it: always on request, and
    -- for every answer that is not authorized (first acceptance,
    -- re-acceptance, block). Read from the row only now.
    IF p_always_with_copy OR NOT v_authorized THEN
        SELECT p.terms_copy, p.privacy_copy, p.ai_notice_copy, p.agreement_copy
          INTO v_terms_copy, v_privacy_copy, v_ai_notice_copy, v_agreement_copy
          FROM public.processing_policy_versions p
         WHERE p.id = v_policy_id;
        v_answer := v_answer || jsonb_build_object(
            'terms_copy', v_terms_copy,
            'privacy_copy', v_privacy_copy,
            'ai_notice_copy', v_ai_notice_copy,
            'agreement_copy', v_agreement_copy
        );
    END IF;

    RETURN v_answer;
END;
$$;

REVOKE ALL ON FUNCTION public.get_phase1_processing_authorization_v2(UUID,BOOLEAN)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_phase1_processing_authorization_v2(UUID,BOOLEAN)
    TO service_role;

-- v1 keeps its signature and its answer: v2 with the text, always.
CREATE OR REPLACE FUNCTION public.get_phase1_processing_authorization_v1(
    p_acquisition_principal_id UUID
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER STABLE SET search_path = public
AS $$
BEGIN
    RETURN public.get_phase1_processing_authorization_v2(
        p_acquisition_principal_id, TRUE);
END;
$$;

REVOKE ALL ON FUNCTION public.get_phase1_processing_authorization_v1(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_phase1_processing_authorization_v1(UUID)
    TO service_role;

-- ── The one-trip read (0473), with the same choice passed through ────────

CREATE OR REPLACE FUNCTION public.read_phase1_processing_status_v2(
    p_user_id UUID DEFAULT NULL,
    p_product_owner_principal_id UUID DEFAULT NULL,
    p_always_with_copy BOOLEAN DEFAULT TRUE
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    owner_id UUID;
    acquirer UUID;
    status JSONB;
    country TEXT;
BEGIN
    -- 1. The product owner: the signed-in user's own principal, or the guest
    --    principal the application has already verified.
    IF p_user_id IS NOT NULL THEN
        SELECT p.id INTO owner_id
          FROM public.owner_principals p
         WHERE p.user_id = p_user_id
         LIMIT 1;
    ELSIF p_product_owner_principal_id IS NOT NULL THEN
        SELECT p.id INTO owner_id
          FROM public.owner_principals p
         WHERE p.id = p_product_owner_principal_id
           AND p.user_id IS NULL
         LIMIT 1;
    END IF;
    IF owner_id IS NULL THEN
        RETURN jsonb_build_object(
            'acquisition_principal_id', NULL, 'status', NULL);
    END IF;

    -- 2. The acquirer, by the one resolver (0355, 0414).
    BEGIN
        acquirer := public.resolve_phase1_acquisition_principal_v1(
            owner_id, p_user_id);
    EXCEPTION WHEN OTHERS THEN
        RETURN jsonb_build_object(
            'acquisition_principal_id', NULL, 'status', NULL);
    END;
    IF acquirer IS NULL THEN
        RETURN jsonb_build_object(
            'acquisition_principal_id', NULL, 'status', NULL);
    END IF;

    -- 3. The status, by the one status function, with the text only when
    --    it will be shown.
    status := public.get_phase1_processing_authorization_v2(
        acquirer, p_always_with_copy);
    IF status IS NULL THEN
        RETURN jsonb_build_object(
            'acquisition_principal_id', NULL, 'status', NULL);
    END IF;

    -- 4. N48.4 Q21 A: a re-acceptance shows the country given last time.
    IF (status ->> 'reacceptance_required') = 'true' THEN
        SELECT lower(btrim(r.country_of_residence)) INTO country
          FROM public.processing_authorization_receipts r
         WHERE r.acquisition_principal_id = acquirer
         ORDER BY r.accepted_at DESC, r.id DESC
         LIMIT 1;
        IF country IS NOT NULL AND country <> '' THEN
            status := status
                || jsonb_build_object('country_of_residence', country);
        END IF;
    END IF;

    RETURN jsonb_build_object(
        'acquisition_principal_id', acquirer, 'status', status);
END;
$$;

REVOKE ALL ON FUNCTION public.read_phase1_processing_status_v2(UUID,UUID,BOOLEAN)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.read_phase1_processing_status_v2(UUID,UUID,BOOLEAN)
    TO service_role;

-- 0473's read keeps its signature and its answer: v2 with the text, always.
CREATE OR REPLACE FUNCTION public.read_phase1_processing_status_v1(
    p_user_id UUID DEFAULT NULL,
    p_product_owner_principal_id UUID DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
BEGIN
    RETURN public.read_phase1_processing_status_v2(
        p_user_id, p_product_owner_principal_id, TRUE);
END;
$$;

REVOKE ALL ON FUNCTION public.read_phase1_processing_status_v1(UUID,UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.read_phase1_processing_status_v1(UUID,UUID)
    TO service_role;
