-- 0358 · The status can say "you agreed to an older version".
--
-- P10, the re-acceptance surface. Decisions P10.1-P10.4 locked by the founder
-- 2026-09-23.
--
-- WHAT WAS MISSING. `get_phase1_processing_authorization_v1` looks up the
-- receipt for the ACTIVE policy. A receipt against an older policy does not
-- match that lookup, so it answers PROCESSING_AUTHORIZATION_REQUIRED — the
-- same answer it gives someone who has never accepted anything.
--
-- Those are different people and they need different screens. One is meeting
-- the product for the first time. The other has used it for months and is
-- being asked again because a document changed. The acceptance gate
-- (`frontend-cursor`, `Phase1AcceptanceGate`) had no way to tell, so it could
-- only ever show the first-time screen.
--
-- This matters the moment counsel returns revised Terms: every existing
-- speaker goes stale at once, and every one of them meets a screen written
-- for a stranger.
--
-- WHAT THIS ADDS, AND WHAT IT LEAVES ALONE. Two keys on the returned JSONB:
--
--   reacceptance_required   true only when this principal accepted an EARLIER
--                           policy and has not accepted the active one
--   accepted_policy_version the version they last agreed to, so the screen can
--                           name which document moved rather than say
--                           "something changed"
--
-- `authorized` and `code` are untouched. Every existing caller behaves
-- exactly as before, and a reader that ignores the two new keys is still
-- correct — which is why this is a CREATE OR REPLACE of v1 rather than a v2:
-- adding keys to a JSONB return breaks nobody.
--
-- The extra read happens ONLY when the active policy has no receipt. The
-- ordinary authorized path does no additional work.
--
-- BLOCKED IS NOT STALE. A principal under a service block is not being asked
-- to re-accept anything, so `reacceptance_required` is false for them and the
-- existing PROCESSING_SERVICE_BLOCKED code still governs.
--
-- ADDITIVE AND IDEMPOTENT. One CREATE OR REPLACE FUNCTION and the grants it
-- already carries. No table, column, row or grant is created, altered or
-- dropped.

CREATE OR REPLACE FUNCTION public.get_phase1_processing_authorization_v1(
    p_acquisition_principal_id UUID
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER STABLE SET search_path = public
AS $$
DECLARE
    policy processing_policy_versions;
    receipt processing_authorization_receipts;
    blocked BOOLEAN;
    held_version TEXT;
BEGIN
    SELECT * INTO policy FROM processing_policy_versions
     WHERE status = 'active' AND activated_at <= now()
       AND (retired_at IS NULL OR retired_at > now())
     ORDER BY activated_at DESC LIMIT 1;
    IF policy.id IS NULL THEN
        RETURN jsonb_build_object(
            'authorized', false, 'code', 'PROCESSING_POLICY_INACTIVE',
            'policy_available', false, 'pooled_learning_eligible', false
        );
    END IF;
    SELECT EXISTS (
        SELECT 1 FROM processing_service_blocks b
         WHERE b.acquisition_principal_id = p_acquisition_principal_id
           AND b.effective_at <= now()
    ) INTO blocked;
    SELECT r.* INTO receipt FROM processing_authorization_receipts r
     WHERE r.acquisition_principal_id = p_acquisition_principal_id
       AND r.policy_id = policy.id
     ORDER BY r.accepted_at DESC LIMIT 1;

    -- P10. THE CALLER COULD NOT TELL THESE TWO PEOPLE APART, AND THEY NEED
    -- DIFFERENT SCREENS. Someone who has never accepted anything is meeting
    -- the product for the first time; someone whose Terms moved under them
    -- has used it for months and is being asked again. Both answered
    -- PROCESSING_AUTHORIZATION_REQUIRED, because the receipt lookup above
    -- matches on the ACTIVE policy and a receipt for an older one simply does
    -- not match. So the re-acceptance screen had no way to know it was a
    -- re-acceptance.
    --
    -- Read only when the active policy has no receipt — the ordinary
    -- authorized path does no extra work at all.
    IF receipt.id IS NULL THEN
        SELECT older.version INTO held_version
          FROM processing_authorization_receipts r
          JOIN processing_policy_versions older ON older.id = r.policy_id
         WHERE r.acquisition_principal_id = p_acquisition_principal_id
         ORDER BY r.accepted_at DESC, r.id DESC LIMIT 1;
    END IF;

    RETURN jsonb_build_object(
        'authorized', receipt.id IS NOT NULL AND NOT blocked,
        'code', CASE
            WHEN blocked THEN 'PROCESSING_SERVICE_BLOCKED'
            WHEN receipt.id IS NULL THEN 'PROCESSING_AUTHORIZATION_REQUIRED'
            ELSE 'PROCESSING_AUTHORIZED' END,
        'policy_available', true, 'policy_id', policy.id,
        'policy_version', policy.version,
        'terms_version', policy.terms_version,
        'terms_copy', policy.terms_copy,
        'terms_copy_sha256', policy.terms_copy_sha256,
        'privacy_version', policy.privacy_version,
        'privacy_copy', policy.privacy_copy,
        'privacy_copy_sha256', policy.privacy_copy_sha256,
        'ai_notice_version', policy.ai_notice_version,
        'ai_notice_copy', policy.ai_notice_copy,
        'ai_notice_copy_sha256', policy.ai_notice_copy_sha256,
        'agreement_copy', policy.agreement_copy,
        'agreement_copy_sha256', policy.agreement_copy_sha256,
        'minimum_age', policy.minimum_age,
        'allowed_countries', policy.allowed_countries,
        'ai_notice_rendered', EXISTS (
            SELECT 1 FROM ai_transparency_exposures e
             WHERE e.acquisition_principal_id = p_acquisition_principal_id
               AND e.ai_notice_version = policy.ai_notice_version
        ),
        'receipt_id', receipt.id, 'pooled_learning_eligible', false,
        -- Additive. `authorized` and `code` are untouched, so every existing
        -- caller behaves exactly as before and a reader that ignores these
        -- two keys is still correct.
        --
        -- `reacceptance_required` is true ONLY when this principal accepted
        -- some earlier policy and has not accepted the active one. It is
        -- false for a first-time visitor, false once they accept, and false
        -- while they are blocked — a blocked person is not being asked to
        -- re-accept anything.
        'reacceptance_required',
            receipt.id IS NULL AND held_version IS NOT NULL AND NOT blocked,
        -- The version they last agreed to, so the screen can say WHICH
        -- document changed rather than "something changed". Null when they
        -- have never accepted one.
        'accepted_policy_version', held_version
    );
END;
$$;

REVOKE ALL ON FUNCTION public.get_phase1_processing_authorization_v1(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_phase1_processing_authorization_v1(UUID)
    TO service_role;
