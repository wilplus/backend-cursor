-- 0454 · Practice is part of the service.
--
-- FOUNDER 2026-10-06 (N55, WQ3a B) and 2026-10-08 (N66.2): personalised
-- practice stops being a consent choice and becomes part of what people sign
-- up for. The founder signed the Privacy 3.4 / Terms 3.4 text in place of
-- counsel (counsel's review was not obtained). Under 3.4 the two practice
-- purposes (personalized_exercise_recommendation, individual_learning_profile)
-- are registered as 'contract' and required_for_core_service, so the policy
-- has no optional purpose left.
--
-- WHY THE DATABASE MUST KNOW. get_phase1_consent_choices_v1 (0361) reads the
-- practice choice as "the receipt records every optional purpose". Under a
-- policy with no optional purpose that is FALSE for everyone, and every
-- practice gate (seven routes, the Feedback Manager's exercise offer, the
-- coach's practice review, the rings) would refuse every speaker the moment
-- 3.4 is activated. So:
--
--   1. get_phase1_consent_choices_v1 reads, from the ACTIVE policy, whether
--      practice is part of the service (personalized_exercise_recommendation
--      is required there). When it is, practice is on for every receipt of
--      that policy and no earlier withdraw event can turn it off: those
--      events name receipts of earlier policies, and a new receipt starts from
--      its own terms (0361). The answer carries `practice_in_service`. Under
--      3.3, where the purpose is optional, every answer is exactly what it was.
--      set_phase1_consent_choice_v1 already refuses a practice change when the
--      policy has no optional purpose (CONSENT_CHOICE_INVALID): unchanged.
--
--   2. The coach's blind accuracy check (Privacy §4, legitimate interest) had
--      one off switch, Personalised practice. Under 3.4 it has none, and the
--      signed text says a speaker may object "by writing to
--      contact@willpowerlab.com: from then on no clip of yours is chosen for a
--      check". blind_check_objections records that objection, once per person,
--      by an operator (scripts/record_blind_check_objection.sql);
--      has_blind_check_objection_v1 answers for the whole person (every
--      principal a claim joins, both ways: a guest who signed up is one
--      person).
--      The application refuses to sample a clip of anyone who objected
--      (services/error_presence_audit.py), and fails closed when the answer
--      cannot be read. An objection is not a consent: it never expires with a
--      receipt and is kept until the account is erased (purge registry,
--      `blind_check_objections`, delete).
--
-- NOTHING RUNS FROM THIS FILE. It replaces one function body and adds one
-- table and two functions; no existing row is read or changed. Practice reads
-- as part of the service only once a policy that makes it so is ACTIVE, and
-- that happens only when the founder runs scripts/phase1_policy_publish_3_4.sql
-- by hand. No environment variable is read, so no Railway service needs
-- configuration first.
--
-- ADDITIVE AND IDEMPOTENT. CREATE TABLE / INDEX IF NOT EXISTS, CREATE OR
-- REPLACE FUNCTION. No DROP of any table or column.

BEGIN;

CREATE TABLE IF NOT EXISTS public.blind_check_objections (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id  UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    recorded_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    recorded_by               TEXT NOT NULL,
    source                    TEXT NOT NULL,
    CONSTRAINT blind_check_objections_one_per_principal
        UNIQUE (acquisition_principal_id),
    CONSTRAINT blind_check_objections_recorded_by_check
        CHECK (char_length(btrim(recorded_by)) BETWEEN 1 AND 200),
    CONSTRAINT blind_check_objections_source_check
        CHECK (source IN ('email'))
);

ALTER TABLE public.blind_check_objections ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.blind_check_objections
    FROM PUBLIC, anon, authenticated;
GRANT SELECT, DELETE ON public.blind_check_objections TO service_role;

CREATE OR REPLACE FUNCTION public.record_blind_check_objection_v1(
    p_acquisition_principal_id UUID,
    p_recorded_by TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
AS $$
DECLARE
    existing blind_check_objections;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM owner_principals
                    WHERE id = p_acquisition_principal_id) THEN
        RAISE EXCEPTION 'PROCESSING_PRINCIPAL_UNRESOLVED';
    END IF;
    IF char_length(btrim(COALESCE(p_recorded_by, ''))) NOT BETWEEN 1 AND 200 THEN
        RAISE EXCEPTION 'BLIND_CHECK_OBJECTION_RECORDER_REQUIRED';
    END IF;
    INSERT INTO blind_check_objections (
        acquisition_principal_id, recorded_by, source
    ) VALUES (p_acquisition_principal_id, btrim(p_recorded_by), 'email')
    ON CONFLICT (acquisition_principal_id) DO NOTHING;
    SELECT * INTO existing FROM blind_check_objections
     WHERE acquisition_principal_id = p_acquisition_principal_id;
    RETURN jsonb_build_object(
        'acquisition_principal_id', existing.acquisition_principal_id,
        'recorded_at', existing.recorded_at);
END;
$$;

-- The whole person: every principal joined to this one by a claim (a guest
-- who signed up), followed both ways to the end, as the purge graph's own
-- claim walk does (0312). Walked here rather than read from the purge graph,
-- so the answer depends on nothing but the claim record; an objection given
-- under any of those principals counts for all of them.
CREATE OR REPLACE FUNCTION public.has_blind_check_objection_v1(
    p_acquisition_principal_id UUID
) RETURNS BOOLEAN
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = public, pg_temp
AS $$
    WITH RECURSIVE claim_edges(source_id, target_id) AS (
        SELECT source_owner_principal_id, target_owner_principal_id
          FROM owner_claim_events
        UNION ALL
        SELECT target_owner_principal_id, source_owner_principal_id
          FROM owner_claim_events
    ), person(id) AS (
        SELECT p_acquisition_principal_id
        UNION
        SELECT edge.target_id
          FROM claim_edges edge
          JOIN person ON person.id = edge.source_id
    )
    SELECT EXISTS (
        SELECT 1 FROM blind_check_objections o
          JOIN person ON person.id = o.acquisition_principal_id);
$$;

CREATE OR REPLACE FUNCTION public.get_phase1_consent_choices_v1(
    p_acquisition_principal_id UUID
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER STABLE SET search_path = public
AS $$
DECLARE
    policy processing_policy_versions;
    receipt processing_authorization_receipts;
    optional_ids TEXT[];
    practice_on BOOLEAN;
    sensitive_on BOOLEAN := TRUE;
    latest TEXT;
    in_service BOOLEAN;
BEGIN
    SELECT * INTO policy FROM processing_policy_versions
     WHERE status = 'active' AND activated_at <= now()
       AND (retired_at IS NULL OR retired_at > now())
     ORDER BY activated_at DESC LIMIT 1;
    IF policy.id IS NULL THEN
        RETURN jsonb_build_object('has_receipt', false,
                                  'policy_available', false);
    END IF;
    SELECT COALESCE(array_agg(pp.purpose_id ORDER BY pp.purpose_id),
                    '{}'::TEXT[])
      INTO optional_ids
      FROM processing_policy_purposes pp
     WHERE pp.policy_id = policy.id AND NOT pp.required_for_core_service;
    -- 0454: practice is part of the service when the active policy makes
    -- its purpose required (Privacy 3.4, N55, N66.2).
    in_service := EXISTS (
        SELECT 1 FROM processing_policy_purposes pp
         WHERE pp.policy_id = policy.id
           AND pp.purpose_id = 'personalized_exercise_recommendation'
           AND pp.required_for_core_service);
    SELECT r.* INTO receipt FROM processing_authorization_receipts r
     WHERE r.acquisition_principal_id = p_acquisition_principal_id
       AND r.policy_id = policy.id
     ORDER BY r.accepted_at DESC, r.id DESC LIMIT 1;
    IF receipt.id IS NULL THEN
        RETURN jsonb_build_object(
            'has_receipt', false, 'policy_available', true,
            'policy_id', policy.id, 'optional_purposes', to_jsonb(optional_ids),
            'practice_in_service', in_service);
    END IF;
    IF in_service THEN
        -- Part of the service: on, and no switch can turn it off.
        practice_on := TRUE;
    ELSE
        -- The tick: on when the receipt records the optional purposes.
        practice_on := cardinality(optional_ids) > 0 AND NOT EXISTS (
            SELECT 1 FROM unnest(optional_ids) AS o(purpose_id)
             WHERE NOT EXISTS (
                 SELECT 1 FROM processing_authorization_receipt_purposes rp
                  WHERE rp.receipt_id = receipt.id
                    AND rp.purpose_id = o.purpose_id));
        SELECT e.event_kind INTO latest FROM processing_consent_choice_events e
         WHERE e.receipt_id = receipt.id AND e.choice = 'personalised_practice'
         ORDER BY e.seq DESC LIMIT 1;
        IF latest IS NOT NULL THEN practice_on := (latest = 'grant'); END IF;
    END IF;
    latest := NULL;
    SELECT e.event_kind INTO latest FROM processing_consent_choice_events e
     WHERE e.receipt_id = receipt.id AND e.choice = 'sensitive_information'
     ORDER BY e.seq DESC LIMIT 1;
    IF latest IS NOT NULL THEN sensitive_on := (latest = 'grant'); END IF;
    RETURN jsonb_build_object(
        'has_receipt', true, 'policy_available', true,
        'policy_id', policy.id, 'receipt_id', receipt.id,
        'optional_purposes', to_jsonb(optional_ids),
        'practice_in_service', in_service,
        'personalised_practice', practice_on,
        'sensitive_information', sensitive_on);
END;
$$;

REVOKE ALL ON FUNCTION public.get_phase1_consent_choices_v1(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_phase1_consent_choices_v1(UUID)
    TO service_role;
REVOKE ALL ON FUNCTION public.record_blind_check_objection_v1(UUID, TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_blind_check_objection_v1(UUID, TEXT)
    TO service_role;
REVOKE ALL ON FUNCTION public.has_blind_check_objection_v1(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.has_blind_check_objection_v1(UUID)
    TO service_role;

COMMIT;
