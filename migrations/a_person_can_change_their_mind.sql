-- 0361 · A person can change their mind.
--
-- FOUNDER 2026-09-25, locked decisions F1/E1-E5.
--
-- TWO PROMISES THE PRODUCT MADE AND COULD NOT KEEP. The acceptance screen says,
-- under the optional "Personalised practice" tick, "I can turn this off at any
-- time and keep using everything else", and under the required sensitive-
-- information tick, "I can withdraw this at any time, which ends my use of
-- recording". There was no way to do either. Worse, the practice tick was
-- recorded (0357) and then read by nothing: a person who left it unticked still
-- had exercises chosen from their recordings.
--
-- WHAT THIS ADDS. One append-only record of later choices, and two functions.
--
--   processing_consent_choice_events: after a receipt is accepted, a person
--   may turn a choice off or back on. Each change is one row, tied to the
--   receipt it changes, never an update of the receipt itself (receipts are
--   immutable evidence, 0310). Two choices exist:
--     * personalised_practice — the one optional tick. It covers every
--       optional purpose of the active policy
--       (personalized_exercise_recommendation, individual_learning_profile),
--       because the screen asks it as one choice.
--     * sensitive_information — the Art 9(2)(a) explicit consent the required
--       tick gives. Withdrawing it stops NEW recording only (E5-A). Reading
--       and exporting what exists is unaffected, and agreeing again resumes
--       recording. It is deliberately NOT a processing_service_blocks
--       restriction, which would lock the person out of their own data with
--       no way back.
--
--   get_phase1_consent_choices_v1(principal): the choices in force now. The
--   receipt decides the starting point (practice on if it records the optional
--   purposes; sensitive information on, because the tick is required to
--   accept) and the latest event for that receipt overrides it. A new receipt
--   (re-acceptance) starts from its own ticks, since events are per receipt.
--
--   set_phase1_consent_choice_v1(...): records one change, only if it changes
--   something. It needs a receipt for the active policy; a person with none
--   has nothing to change yet.
--
-- ENFORCEMENT is in the application, through ProcessingAuthorizationService,
-- the one boundary every processing decision already passes: practice
-- routes, the Feedback Manager's exercise offer, the coach's practice
-- review, and the recording boundary all ask it. This file only makes the
-- answer readable.
--
-- ADDITIVE AND IDEMPOTENT. CREATE ... IF NOT EXISTS and CREATE OR REPLACE
-- FUNCTION only. No DROP of any table or column; no existing row rewritten.
-- The one DROP TRIGGER IF EXISTS re-creates this file's own trigger, the
-- same idiom 0310 uses. No environment variable is read, so no Railway
-- service needs configuration first. The application code that calls these
-- functions ships in the same PR and treats a missing function as "no later
-- change recorded".

CREATE TABLE IF NOT EXISTS public.processing_consent_choice_events (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Order of record. created_at is the transaction start; seq is assigned
    -- at insert, so "the latest change" is never a tie.
    seq                       BIGINT GENERATED ALWAYS AS IDENTITY,
    acquisition_principal_id  UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    receipt_id                UUID NOT NULL
        REFERENCES public.processing_authorization_receipts(id)
        ON DELETE RESTRICT,
    choice                    TEXT NOT NULL,
    event_kind                TEXT NOT NULL,
    idempotency_key           TEXT NOT NULL,
    client_version            TEXT NULL,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT processing_consent_choice_events_choice_check
        CHECK (choice IN ('personalised_practice', 'sensitive_information')),
    CONSTRAINT processing_consent_choice_events_kind_check
        CHECK (event_kind IN ('grant', 'withdraw')),
    CONSTRAINT processing_consent_choice_events_key_check
        CHECK (char_length(idempotency_key) BETWEEN 8 AND 200),
    CONSTRAINT processing_consent_choice_events_client_check
        CHECK (client_version IS NULL
               OR char_length(client_version) BETWEEN 1 AND 120),
    CONSTRAINT processing_consent_choice_events_idempotency
        UNIQUE (acquisition_principal_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS processing_consent_choice_events_receipt_idx
    ON public.processing_consent_choice_events (receipt_id, choice, seq);

-- Evidence: never updated, never deleted, like the receipt it qualifies.
DROP TRIGGER IF EXISTS processing_consent_choice_events_immutable
    ON public.processing_consent_choice_events;
CREATE TRIGGER processing_consent_choice_events_immutable
    BEFORE UPDATE OR DELETE ON public.processing_consent_choice_events
    FOR EACH ROW EXECUTE FUNCTION public.reject_phase1_immutable_mutation();

ALTER TABLE public.processing_consent_choice_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.processing_consent_choice_events
    FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON public.processing_consent_choice_events TO service_role;

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
    SELECT r.* INTO receipt FROM processing_authorization_receipts r
     WHERE r.acquisition_principal_id = p_acquisition_principal_id
       AND r.policy_id = policy.id
     ORDER BY r.accepted_at DESC, r.id DESC LIMIT 1;
    IF receipt.id IS NULL THEN
        RETURN jsonb_build_object(
            'has_receipt', false, 'policy_available', true,
            'policy_id', policy.id, 'optional_purposes', to_jsonb(optional_ids));
    END IF;
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
    latest := NULL;
    SELECT e.event_kind INTO latest FROM processing_consent_choice_events e
     WHERE e.receipt_id = receipt.id AND e.choice = 'sensitive_information'
     ORDER BY e.seq DESC LIMIT 1;
    IF latest IS NOT NULL THEN sensitive_on := (latest = 'grant'); END IF;
    RETURN jsonb_build_object(
        'has_receipt', true, 'policy_available', true,
        'policy_id', policy.id, 'receipt_id', receipt.id,
        'optional_purposes', to_jsonb(optional_ids),
        'personalised_practice', practice_on,
        'sensitive_information', sensitive_on);
END;
$$;

CREATE OR REPLACE FUNCTION public.set_phase1_consent_choice_v1(
    p_acquisition_principal_id UUID,
    p_choice TEXT,
    p_enabled BOOLEAN,
    p_idempotency_key TEXT,
    p_client_version TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    state JSONB;
    current_on BOOLEAN;
BEGIN
    IF p_choice NOT IN ('personalised_practice', 'sensitive_information') THEN
        RAISE EXCEPTION 'CONSENT_CHOICE_INVALID';
    END IF;
    IF p_enabled IS NULL THEN
        RAISE EXCEPTION 'CONSENT_CHOICE_INVALID';
    END IF;
    -- One change per person at a time, so two taps cannot both read "on"
    -- and both write "withdraw".
    PERFORM 1 FROM owner_principals
     WHERE id = p_acquisition_principal_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'PROCESSING_PRINCIPAL_UNRESOLVED';
    END IF;
    -- A replayed request answers with the state, not a second row.
    IF EXISTS (SELECT 1 FROM processing_consent_choice_events
                WHERE acquisition_principal_id = p_acquisition_principal_id
                  AND idempotency_key = p_idempotency_key) THEN
        RETURN get_phase1_consent_choices_v1(p_acquisition_principal_id);
    END IF;
    state := get_phase1_consent_choices_v1(p_acquisition_principal_id);
    IF NOT COALESCE((state->>'has_receipt')::BOOLEAN, false) THEN
        RAISE EXCEPTION 'PROCESSING_AUTHORIZATION_REQUIRED';
    END IF;
    IF p_choice = 'personalised_practice'
       AND jsonb_array_length(state->'optional_purposes') = 0 THEN
        RAISE EXCEPTION 'CONSENT_CHOICE_INVALID';
    END IF;
    current_on := (state->>p_choice)::BOOLEAN;
    IF current_on IS DISTINCT FROM p_enabled THEN
        INSERT INTO processing_consent_choice_events (
            acquisition_principal_id, receipt_id, choice, event_kind,
            idempotency_key, client_version
        ) VALUES (
            p_acquisition_principal_id, (state->>'receipt_id')::UUID, p_choice,
            CASE WHEN p_enabled THEN 'grant' ELSE 'withdraw' END,
            p_idempotency_key, NULLIF(btrim(p_client_version), '')
        );
    END IF;
    RETURN get_phase1_consent_choices_v1(p_acquisition_principal_id);
END;
$$;

REVOKE ALL ON FUNCTION public.get_phase1_consent_choices_v1(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_phase1_consent_choices_v1(UUID)
    TO service_role;
REVOKE ALL ON FUNCTION public.set_phase1_consent_choice_v1(
    UUID, TEXT, BOOLEAN, TEXT, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.set_phase1_consent_choice_v1(
    UUID, TEXT, BOOLEAN, TEXT, TEXT
) TO service_role;
