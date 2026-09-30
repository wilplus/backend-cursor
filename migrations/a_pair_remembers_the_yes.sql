-- A pair remembers the yes (founder 2026-09-30, L1, L2, L5; build plan
-- group 7: ML-8, ML-9). The machinery of doors 1 and 2, with both doors
-- still closed in code.
--
-- 1. EVERY PAIR CARRIES ITS OWNER'S CONSENT. feedback_pairs gains the
--    owner's principal, the consent state the pair was recorded under, the
--    grant it rests on, and whether it is RELEASABLE: a pair from a speaker
--    without the training yes is marked not releasable (ML-8's pass line).
--    Which surfaces need the yes is code (services/pair_consent.py, per
--    counsel); the refresh below takes that list as an argument.
--
-- 2. THE YES IS REVOCABLE AND REVOCATION VOIDS THE COPIES. A weekly refresh
--    recomputes every pair's releasability from the latest training-only
--    grant and withdrawal, and voids any release that carried a pair whose
--    owner has since withdrawn; the weekly sweep then deletes the object.
--
-- 3. A RELEASE IS ONE FILE PER SURFACE PER WEEK (ML-9): pair_releases
--    records where it went, its manifest, the file's sha256 and a signature
--    over the manifest; pair_release_owners lists whose passages it holds,
--    so a withdrawal can find it. Exports run only for a surface the founder
--    authorised by a reviewed change carrying his sentence (config).
--
-- Idempotent. No env var needed to apply. RLS on every new table. Nothing
-- here opens a door.

BEGIN;

ALTER TABLE public.feedback_pairs
    ADD COLUMN IF NOT EXISTS owner_principal_id     uuid NULL,
    ADD COLUMN IF NOT EXISTS consent_state          text NOT NULL DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS consent_grant_event_id uuid NULL,
    ADD COLUMN IF NOT EXISTS consent_policy_version text NULL,
    ADD COLUMN IF NOT EXISTS releasable             boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS release_id             uuid NULL;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'feedback_pairs_consent_state_check') THEN
        ALTER TABLE public.feedback_pairs
            ADD CONSTRAINT feedback_pairs_consent_state_check
            CHECK (consent_state IN ('yes', 'no', 'not_needed', 'unknown'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS feedback_pairs_releasable_idx
    ON public.feedback_pairs (surface, created_at)
    WHERE releasable AND exported_at IS NULL;

-- Pairs written before this migration name their owner by user id; find
-- the principal once, so the refresh can read the consent ledger.
UPDATE public.feedback_pairs pair
   SET owner_principal_id = principal.id
  FROM public.owner_principals principal
 WHERE pair.owner_principal_id IS NULL
   AND pair.owner_user_id IS NOT NULL
   AND principal.user_id::text = pair.owner_user_id;

CREATE TABLE IF NOT EXISTS public.pair_releases (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    release_version text        NOT NULL,
    surface         text        NOT NULL CHECK (surface IN (
        'praise_line', 'clearer_version', 'exercise_script')),
    week_start      date        NOT NULL,
    item_count      integer     NOT NULL CHECK (item_count > 0),
    storage_bucket  text        NOT NULL,
    storage_key     text        NOT NULL,
    manifest        jsonb       NOT NULL,
    manifest_sha256 text        NOT NULL CHECK (length(manifest_sha256) = 64),
    file_sha256     text        NOT NULL CHECK (length(file_sha256) = 64),
    signature       text        NOT NULL,
    signing_key_id  text        NOT NULL,
    exported_at     timestamptz NOT NULL DEFAULT now(),
    voided_at       timestamptz NULL,
    voided_reason   text        NULL,
    purged_at       timestamptz NULL,
    CONSTRAINT pair_releases_one_per_week UNIQUE (surface, week_start),
    CONSTRAINT pair_releases_key_prefix CHECK (storage_key LIKE 'pair-releases/%')
);
ALTER TABLE public.pair_releases ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.pair_releases IS
    'One exported file per surface per week (ML-9): where it went, its '
    'manifest, hashes and signature. Voided when an owner withdraws; purged '
    'when the object is gone. Never a browser read.';

CREATE TABLE IF NOT EXISTS public.pair_release_owners (
    release_id         uuid NOT NULL REFERENCES public.pair_releases(id) ON DELETE CASCADE,
    owner_principal_id uuid NOT NULL,
    PRIMARY KEY (release_id, owner_principal_id)
);
CREATE INDEX IF NOT EXISTS pair_release_owners_owner_idx
    ON public.pair_release_owners (owner_principal_id);
ALTER TABLE public.pair_release_owners ENABLE ROW LEVEL SECURITY;

-- The latest training-only yes for a principal, as get_mlc2_training_consent
-- _status_v2 reads it (0373), minus the withdrawn ones. One row per principal.
CREATE OR REPLACE VIEW public.training_consent_active_grants AS
    WITH latest AS (
        SELECT DISTINCT ON (event.acquisition_principal_id)
               event.id, event.acquisition_principal_id,
               event.consent_policy_version, event.occurred_at
          FROM public.ml_consent_events event
          JOIN public.ml_consent_policies policy
            ON policy.version = event.consent_policy_version
         WHERE event.event_kind = 'grant'
           AND policy.grant_scope = 'training_only'
           AND policy.active_from <= now()
           AND (policy.retired_at IS NULL OR policy.retired_at > now())
           AND event.occurred_at <= now()
           AND EXISTS (SELECT 1 FROM public.ml_consent_event_purposes purpose
                        WHERE purpose.consent_event_id = event.id
                          AND purpose.purpose = 'pooled_model_improvement')
         ORDER BY event.acquisition_principal_id, event.occurred_at DESC, event.id DESC
    )
    SELECT latest.*
      FROM latest
     WHERE NOT EXISTS (
        SELECT 1 FROM public.ml_consent_events withdrawal
          JOIN public.ml_consent_event_purposes purpose
            ON purpose.consent_event_id = withdrawal.id
           AND purpose.purpose = 'pooled_model_improvement'
         WHERE withdrawal.supersedes_event_id = latest.id
           AND withdrawal.event_kind = 'withdraw'
           AND withdrawal.occurred_at <= now());
REVOKE ALL ON public.training_consent_active_grants FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.training_consent_active_grants TO service_role;

-- The weekly refresh (ML-8): every pair's consent state and releasability
-- from the ledger as it stands, and the voiding of releases whose owner
-- withdrew. p_required_surfaces names the surfaces that need the yes
-- (services/pair_consent.py, per counsel); a surface outside it is
-- releasable without one. Returns counts about the system.
CREATE OR REPLACE FUNCTION public.refresh_feedback_pair_consent_v1(
    p_required_surfaces text[]
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    v_refreshed integer := 0;
    v_releasable integer := 0;
    v_voided integer := 0;
    v_reset integer := 0;
BEGIN
    UPDATE public.feedback_pairs pair
       SET owner_principal_id = principal.id
      FROM public.owner_principals principal
     WHERE pair.owner_principal_id IS NULL
       AND pair.owner_user_id IS NOT NULL
       AND principal.user_id::text = pair.owner_user_id;

    WITH stamped AS (
        SELECT pair.id,
               CASE
                   WHEN NOT (pair.surface = ANY (p_required_surfaces)) THEN 'not_needed'
                   WHEN pair.owner_principal_id IS NULL THEN 'unknown'
                   WHEN grant_row.id IS NOT NULL THEN 'yes'
                   ELSE 'no'
               END AS state,
               grant_row.id AS grant_id,
               grant_row.consent_policy_version AS policy_version
          FROM public.feedback_pairs pair
          LEFT JOIN public.training_consent_active_grants grant_row
            ON grant_row.acquisition_principal_id = pair.owner_principal_id
    )
    UPDATE public.feedback_pairs pair
       SET consent_state = stamped.state,
           consent_grant_event_id = stamped.grant_id,
           consent_policy_version = stamped.policy_version,
           releasable = stamped.state IN ('yes', 'not_needed')
      FROM stamped
     WHERE stamped.id = pair.id;
    GET DIAGNOSTICS v_refreshed = ROW_COUNT;

    -- A release that holds a pair no longer releasable is void: its owner
    -- withdrew, or the surface now needs a yes it lacks. The sweep deletes
    -- the object; the pairs go back to waiting (they leave again only if
    -- they become releasable again).
    WITH void AS (
        UPDATE public.pair_releases release
           SET voided_at = now(), voided_reason = 'consent_withdrawn'
         WHERE release.voided_at IS NULL
           AND EXISTS (SELECT 1 FROM public.feedback_pairs pair
                        WHERE pair.release_id = release.id
                          AND NOT pair.releasable)
        RETURNING release.id
    )
    SELECT count(*) INTO v_voided FROM void;

    UPDATE public.feedback_pairs pair
       SET release_id = NULL, exported_at = NULL
      FROM public.pair_releases release
     WHERE pair.release_id = release.id
       AND release.voided_at IS NOT NULL;
    GET DIAGNOSTICS v_reset = ROW_COUNT;

    SELECT count(*) INTO v_releasable
      FROM public.feedback_pairs WHERE releasable AND exported_at IS NULL;

    RETURN jsonb_build_object(
        'refreshed', v_refreshed, 'releasable_waiting', v_releasable,
        'voided_releases', v_voided, 'pairs_reset', v_reset);
END;
$$;
REVOKE ALL ON FUNCTION public.refresh_feedback_pair_consent_v1(text[])
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.refresh_feedback_pair_consent_v1(text[]) TO service_role;

-- Marking a release's pairs as exported, atomically with the release row
-- the job just wrote: a pair leaves once, under one release.
CREATE OR REPLACE FUNCTION public.mark_feedback_pairs_released_v1(
    p_release_id uuid,
    p_pair_ids uuid[]
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    v_count integer := 0;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.pair_releases WHERE id = p_release_id) THEN
        RAISE EXCEPTION 'PAIR_RELEASE_UNKNOWN';
    END IF;
    UPDATE public.feedback_pairs
       SET release_id = p_release_id, exported_at = now()
     WHERE id = ANY (p_pair_ids)
       AND releasable
       AND exported_at IS NULL;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    IF v_count <> coalesce(array_length(p_pair_ids, 1), 0) THEN
        RAISE EXCEPTION 'PAIR_RELEASE_PAIRS_NOT_RELEASABLE';
    END IF;
    RETURN v_count;
END;
$$;
REVOKE ALL ON FUNCTION public.mark_feedback_pairs_released_v1(uuid, uuid[])
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.mark_feedback_pairs_released_v1(uuid, uuid[]) TO service_role;

COMMIT;
