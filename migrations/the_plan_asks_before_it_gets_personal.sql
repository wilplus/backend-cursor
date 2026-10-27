-- the_plan_asks_before_it_gets_personal (the plan's own yes; backend N211,
-- Privacy 3.9 section 4e; frontend docs/flows/the-plan.md D)
--
-- The plan's personal answers (what worries the speaker, how stressed and how
-- ready they feel, how they feel before a Take, and how it went when the plan
-- ends) are asked only after the speaker says yes, once, to a question of its
-- own ("Yes, ask me" or "Not now"), and a card in Data & consent turns the yes
-- off again, which also deletes those answers.
--
--   plan_consent_events   Append-only: one row per answer, grant, decline or
--                         withdraw, with the sha256 of the exact sentence the
--                         yes was given to and the policy version in force. The
--                         newest row is the answer. A row is never changed (a
--                         trigger refuses an UPDATE); it is deleted only with
--                         the account (the purge), as every plan table is.
--
-- Read and written by the backend (service role) only. No environment variable
-- is read here. The code that reads it is switched off (PLAN_CONSENT_ENABLED)
-- until Privacy 3.9 is published, so merging this changes nothing for anyone.
-- Idempotent and additive: IF NOT EXISTS and CREATE OR REPLACE only, nothing
-- dropped, no existing row touched. One transaction.

BEGIN;

CREATE TABLE IF NOT EXISTS public.plan_consent_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    seq             BIGINT GENERATED ALWAYS AS IDENTITY,
    user_id         UUID NOT NULL,
    event_kind      TEXT NOT NULL,
    copy_sha256     TEXT NOT NULL,
    policy_version  TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT plan_consent_events_kind_check
        CHECK (event_kind IN ('grant', 'decline', 'withdraw')),
    CONSTRAINT plan_consent_events_sha_check
        CHECK (copy_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS plan_consent_events_user_idx
    ON public.plan_consent_events (user_id, seq);

-- Evidence: never changed. (reject_phase1_immutable_mutation is 0310's.)
CREATE OR REPLACE TRIGGER plan_consent_events_no_update
    BEFORE UPDATE ON public.plan_consent_events
    FOR EACH ROW EXECUTE FUNCTION public.reject_phase1_immutable_mutation();

ALTER TABLE public.plan_consent_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.plan_consent_events FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, DELETE ON TABLE public.plan_consent_events TO service_role;

COMMIT;
