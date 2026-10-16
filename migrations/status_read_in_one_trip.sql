-- 0473 · The status read on every app open is one round trip.
--
-- Founder 2026-10-16: GET /v2/processing-authorization runs before anything
-- shows and took ~600 ms. After #1093 an ordinary open still pays THREE
-- database round trips, one after another, before it can answer:
--
--   1. owner_principals by user_id        (who is the product owner?)
--   2. resolve_phase1_acquisition_principal_v1   (who acquired the audio?)
--   3. get_phase1_processing_authorization_v1    (what is their authority?)
--      + the newest receipt's country, only on a re-acceptance
--
-- Each is a PostgREST call from Railway to Supabase. This function answers
-- all of them in ONE call, by CALLING THE EXISTING FUNCTIONS. Nothing of
-- their logic is copied here: the resolver (0355, 0414) and the status
-- (0358, 0422) stay the only places their rules live, so a later change to
-- either flows through this read unchanged, and the status this returns is
-- the status those two return, byte for byte.
--
-- WHAT IT RETURNS.
--
--   {"acquisition_principal_id": <uuid>, "status": <jsonb>}
--
-- `status` is exactly get_phase1_processing_authorization_v1's answer for
-- the resolved acquirer, plus `country_of_residence` (the newest receipt's,
-- lower-cased) when, and only when, that answer says
-- `reacceptance_required` -- the same read the application made in Python
-- (ProcessingAuthorizationService.last_country_of_residence). `gate_mode` is
-- a deployment setting the application still adds itself.
--
--   {"acquisition_principal_id": null, "status": null}
--
-- whenever this function cannot do the whole job: no owner principal for
-- the user (the application creates one, which this read never does), no
-- argument at all, or the resolver raising. The application then takes
-- exactly the path it takes today, so a null here can never change an
-- answer -- it only costs the round trips this exists to save.
--
-- WHO IT TRUSTS. Nobody. It is callable by service_role only, like the two
-- functions it wraps. The application resolves a signed-in user by the
-- user id its own token verification produced, and a guest by a principal
-- id it has ALREADY verified against the stored guest secret; this function
-- never sees a token and never verifies one. With both arguments given the
-- user id wins; a guest principal is looked up only as a guest (user_id IS
-- NULL), so an account's principal id can never be read through the guest
-- argument.
--
-- VOLATILITY. Not declared STABLE: resolve_phase1_acquisition_principal_v1
-- is VOLATILE (0355, 0414 declare no volatility), and a wrapper must not
-- promise more than what it calls. The function writes nothing.
--
-- ADDITIVE AND IDEMPOTENT. One CREATE OR REPLACE FUNCTION and its grants.
-- No table, column, row, index or grant is created, altered or dropped; no
-- existing function is touched; no environment variable is needed.

CREATE OR REPLACE FUNCTION public.read_phase1_processing_status_v1(
    p_user_id UUID DEFAULT NULL,
    p_product_owner_principal_id UUID DEFAULT NULL
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

    -- 2. The acquirer, by the one resolver (0355, 0414). Should it raise,
    --    this read answers null and the application resolves it the way it
    --    does today, where the mode decides what a failure means.
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

    -- 3. The status, by the one status function (0358, 0422).
    status := public.get_phase1_processing_authorization_v1(acquirer);
    IF status IS NULL THEN
        RETURN jsonb_build_object(
            'acquisition_principal_id', NULL, 'status', NULL);
    END IF;

    -- 4. N48.4 Q21 A: a re-acceptance shows the country given last time
    --    already chosen. The newest receipt, lower-cased, as
    --    last_country_of_residence reads it; read only then, and never
    --    added when empty.
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

-- Service_role only, as the two functions it calls (0313, 0355, 0358, 0422).
-- Written out here, as every migration that creates a function says in its
-- own text who may call it.
REVOKE ALL ON FUNCTION public.read_phase1_processing_status_v1(UUID,UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.read_phase1_processing_status_v1(UUID,UUID)
    TO service_role;
