-- 0456 · An erasure voids the released copies (door 2, ML-8/ML-9; the
--        erasure promise of N48.4 Q14 A and Q17 A; PLF-T2, PLF-T3, L3).
--
-- THE GAP. Door 2 exports (draft, final) pairs once a week to the private
-- release bucket (services/pair_release.py): one pairs.jsonl and one
-- manifest.json per surface per week, recorded in pair_releases. New
-- releases are already safe: the export decides every pair again at release
-- time (services/pair_release_eligibility.py) and keeps out a pair whose
-- project is leaving or whose owner's service is ending. Files ALREADY
-- released were voided, and their objects deleted by the sweep, only by the
-- weekly refresh (refresh_feedback_pair_consent_v1, latest 0422), and only
-- when one of the release's pairs STILL EXISTED and was not releasable:
--
--   * a project deletion (0364, 0380, 0422) never made the project's pairs
--     not releasable, and the one-project purge deletes them by Take
--     (feedback_pairs_by_take). Once they were gone the refresh had no row
--     to see, so a released file kept the deleted project's passages and
--     coach finals;
--   * an account deletion made the person's pairs not releasable at the
--     request (stop_phase1_learning_v1, 0422), but voiding waited for the
--     weekly refresh: a weekly job that did not run inside the seven days
--     let the purge delete the pairs first, and the file stayed.
--
-- WHAT THIS DOES. The void is decided when the erasure is asked for and
-- recorded on the release itself, so it no longer needs the rows the purge
-- deletes. A voided release keeps its row; the sweep deletes its objects
-- (weekly, and now also at the end of each hourly deletion run that
-- executes, services/deletion_completion.py).
--
--   1. void_pair_releases_v1(release ids, reason) voids the live releases
--      among those given and sends every pair they held back to waiting,
--      exactly as the refresh does for a voided release (release_id and
--      exported_at cleared). Two reasons of its own, apart from the
--      refresh's 'consent_withdrawn' and 'owner_service_ended':
--      'owner_erasure_requested' and 'project_erasure_requested'.
--   2. stop_phase1_learning_v1 (0422) also voids every release that lists
--      the person as an owner (pair_release_owners) or holds one of their
--      pairs. It already runs at the account deletion request (0422) and at
--      every purge request that blocks the person (0310 via 0422), so both
--      void at once. Nothing else in it changes.
--   3. void_project_pair_releases_v1(project) voids every release holding a
--      pair of the project. A pair is the project's when its Take is, by
--      project_id or arc_id, as the one-project purge finds a project's
--      Takes (0380), whoever's Take it is: a release is voided once too
--      often rather than once too few. It runs at the request
--      (request_project_deletion_v1, 0364), and again when the purge request
--      is made (start_due_project_deletion_v1, 0422, and the operator's
--      confirm_project_deletion_v1, 0380), so a pair that left in between
--      is voided before the purge deletes it. Each of the three gains that
--      one statement and nothing else. A pair sent back to waiting does not
--      leave again while its project is leaving: the export's eligibility
--      decision keeps it out (reason project_leaving).
--   4. Erasures asked for before this file: every person whose learning has
--      stopped (phase1_learning_stopped_v1) and every project whose
--      deletion is pending or confirmed gets now what its request would
--      have done.
--
-- A cancel needs nothing new. A voided release stays voided; the pairs it
-- held went back to waiting and leave again in a later week's file once
-- the export's decision lets them (a cancelled deletion no longer keeps
-- them out).
--
-- L3. The consent ledger is neither read nor written by anything added
-- here: only copies are voided, and no pair's consent state changes. AC-9:
-- nothing here reaches a speaker or a coach.
--
-- ADDITIVE AND IDEMPOTENT. CREATE OR REPLACE FUNCTION only, and a DO block
-- that voids at most what the requests would have voided (a second run finds
-- every such release voided already). No table, column, constraint or row
-- is dropped or deleted. No environment variable is read, so no Railway
-- service needs configuration first. The application code that sweeps from
-- the deletion run ships in the same change.

BEGIN;

-- ── 1. The void ─────────────────────────────────────────────────────────────

-- The live releases among those given are voided with the reason given, and
-- every pair they held goes back to waiting, as the refresh sends back a
-- voided release's pairs (0405). Returns how many releases it voided.
CREATE OR REPLACE FUNCTION public.void_pair_releases_v1(
    p_release_ids UUID[],
    p_reason TEXT
) RETURNS INTEGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    v_voided UUID[];
BEGIN
    IF p_reason IS NULL OR p_reason NOT IN (
        'owner_erasure_requested', 'project_erasure_requested'
    ) THEN
        RAISE EXCEPTION 'PAIR_RELEASE_VOID_REASON_INVALID';
    END IF;
    WITH void AS (
        UPDATE public.pair_releases release
           SET voided_at = now(), voided_reason = p_reason
         WHERE release.id = ANY (p_release_ids)
           AND release.voided_at IS NULL
        RETURNING release.id
    )
    SELECT COALESCE(array_agg(void.id), '{}'::uuid[]) INTO v_voided FROM void;

    UPDATE public.feedback_pairs pair
       SET release_id = NULL, exported_at = NULL
     WHERE pair.release_id = ANY (v_voided);
    RETURN COALESCE(array_length(v_voided, 1), 0);
END;
$$;
REVOKE ALL ON FUNCTION public.void_pair_releases_v1(UUID[], TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.void_pair_releases_v1(UUID[], TEXT)
    TO service_role;

-- ── 2. A person's erasure voids at once ────────────────────────────────────

-- 0422's stop, with one statement added after the pairs leave the pool:
-- every release that lists the person or holds one of their pairs is voided.
CREATE OR REPLACE FUNCTION public.stop_phase1_learning_v1(
    p_acquisition_principal_id UUID
) RETURNS INTEGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    v_user TEXT;
    v_count INTEGER := 0;
BEGIN
    IF p_acquisition_principal_id IS NULL
       OR to_regclass('public.feedback_pairs') IS NULL THEN
        RETURN 0;
    END IF;
    SELECT principal.user_id::text INTO v_user
      FROM public.owner_principals principal
     WHERE principal.id = p_acquisition_principal_id;
    IF v_user IS NOT NULL THEN
        UPDATE public.feedback_pairs pair
           SET owner_principal_id = p_acquisition_principal_id
         WHERE pair.owner_principal_id IS NULL
           AND pair.owner_user_id = v_user;
    END IF;
    UPDATE public.feedback_pairs pair
       SET releasable = false
     WHERE pair.owner_principal_id = p_acquisition_principal_id
       AND pair.releasable;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    -- 0456: the copies already released go now, not at the weekly refresh,
    -- which no longer finds a pair once the purge has deleted it.
    PERFORM public.void_pair_releases_v1(ARRAY(
        SELECT listed.release_id FROM public.pair_release_owners listed
         WHERE listed.owner_principal_id = p_acquisition_principal_id
        UNION
        SELECT pair.release_id FROM public.feedback_pairs pair
         WHERE pair.owner_principal_id = p_acquisition_principal_id
           AND pair.release_id IS NOT NULL
    ), 'owner_erasure_requested');
    RETURN v_count;
END;
$$;
REVOKE ALL ON FUNCTION public.stop_phase1_learning_v1(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.stop_phase1_learning_v1(UUID) TO service_role;

-- ── 3. A project's erasure voids at once ───────────────────────────────────

-- Every release holding a pair of the project is voided. Returns how many.
CREATE OR REPLACE FUNCTION public.void_project_pair_releases_v1(
    p_project_id UUID
) RETURNS INTEGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
BEGIN
    IF p_project_id IS NULL
       OR to_regclass('public.feedback_pairs') IS NULL THEN
        RETURN 0;
    END IF;
    -- The project's Takes as the one-project purge finds them (0380), by
    -- project_id or by arc_id, whoever's Take it is.
    RETURN public.void_pair_releases_v1(ARRAY(
        SELECT pair.release_id FROM public.feedback_pairs pair
         WHERE pair.release_id IS NOT NULL
           AND pair.take_session_id IN (
               SELECT session.id::text FROM public.v2_sessions session
                WHERE session.project_id = p_project_id
                   OR session.arc_id = p_project_id::text)
    ), 'project_erasure_requested');
END;
$$;
REVOKE ALL ON FUNCTION public.void_project_pair_releases_v1(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.void_project_pair_releases_v1(UUID)
    TO service_role;

-- 0364's request, with one statement added once the new request is written.
CREATE OR REPLACE FUNCTION public.request_project_deletion_v1(
    p_acquisition_principal_id UUID,
    p_project_id UUID,
    p_idempotency_key TEXT
) RETURNS public.project_deletion_requests
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    request public.project_deletion_requests;
BEGIN
    IF COALESCE(btrim(p_idempotency_key), '') = '' THEN
        RAISE EXCEPTION 'PROJECT_DELETION_IDEMPOTENCY_KEY_REQUIRED';
    END IF;

    SELECT * INTO request FROM public.project_deletion_requests
     WHERE acquisition_principal_id = p_acquisition_principal_id
       AND idempotency_key = p_idempotency_key;
    IF request.id IS NOT NULL THEN
        IF request.project_id <> p_project_id THEN
            RAISE EXCEPTION 'IDEMPOTENCY_CONFLICT';
        END IF;
        RETURN request;
    END IF;

    PERFORM 1 FROM public.projects
     WHERE id = p_project_id
       AND owner_principal_id = p_acquisition_principal_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'PROJECT_NOT_FOUND';
    END IF;

    SELECT * INTO request FROM public.project_deletion_requests
     WHERE project_id = p_project_id
       AND state IN ('pending', 'confirmed');
    IF request.id IS NOT NULL THEN
        RETURN request;
    END IF;

    INSERT INTO public.project_deletion_requests (
        acquisition_principal_id, project_id, requested_at, due_at,
        idempotency_key
    ) VALUES (
        p_acquisition_principal_id, p_project_id, now(),
        now() + interval '7 days', p_idempotency_key
    )
    RETURNING * INTO request;
    -- 0456: the project's released copies are voided now, seven days
    -- before any purge.
    PERFORM public.void_project_pair_releases_v1(p_project_id);
    RETURN request;
END;
$$;
REVOKE ALL ON FUNCTION public.request_project_deletion_v1(UUID, UUID, TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.request_project_deletion_v1(UUID, UUID, TEXT)
    TO service_role;

-- 0422's system confirm, with one statement added once the purge request
-- exists: whatever was released since the request is voided before the purge.
CREATE OR REPLACE FUNCTION public.start_due_project_deletion_v1(
    p_request_id UUID
) RETURNS public.project_deletion_requests
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    request public.project_deletion_requests;
    purge_id UUID;
BEGIN
    SELECT * INTO request FROM public.project_deletion_requests
     WHERE id = p_request_id FOR UPDATE;
    IF request.id IS NULL THEN
        RAISE EXCEPTION 'PROJECT_DELETION_NOT_FOUND';
    END IF;
    IF request.state IN ('confirmed', 'done') THEN
        RETURN request;
    END IF;
    IF request.state <> 'pending' THEN
        RAISE EXCEPTION 'PROJECT_DELETION_NOT_PENDING';
    END IF;
    IF now() < request.due_at THEN
        RAISE EXCEPTION 'PROJECT_DELETION_WINDOW_OPEN';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.projects project
         WHERE project.id = request.project_id
           AND project.owner_principal_id = request.acquisition_principal_id
    ) THEN
        RAISE EXCEPTION 'PURGE_PROJECT_NOT_OWNED';
    END IF;

    INSERT INTO public.data_purge_requests (
        acquisition_principal_id, trigger_kind, project_id, idempotency_key
    ) VALUES (
        request.acquisition_principal_id, 'project_deletion',
        request.project_id, 'project-deletion:' || request.id::text
    )
    ON CONFLICT (acquisition_principal_id, idempotency_key) DO NOTHING;
    SELECT id INTO purge_id FROM public.data_purge_requests
     WHERE acquisition_principal_id = request.acquisition_principal_id
       AND idempotency_key = 'project-deletion:' || request.id::text;
    -- 0456: at the latest before the purge deletes the pairs.
    PERFORM public.void_project_pair_releases_v1(request.project_id);

    UPDATE public.project_deletion_requests
       SET state = 'confirmed', confirmed_at = now(),
           confirmed_by = NULL, purge_request_id = purge_id
     WHERE id = request.id
    RETURNING * INTO request;
    RETURN request;
END;
$$;
REVOKE ALL ON FUNCTION public.start_due_project_deletion_v1(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.start_due_project_deletion_v1(UUID)
    TO service_role;

-- 0380's operator confirm, with the same one statement.
CREATE OR REPLACE FUNCTION public.confirm_project_deletion_v1(
    p_request_id UUID,
    p_operator_id UUID
) RETURNS public.project_deletion_requests
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    request public.project_deletion_requests;
    purge_id UUID;
BEGIN
    SELECT * INTO request FROM public.project_deletion_requests
     WHERE id = p_request_id FOR UPDATE;
    IF request.id IS NULL THEN RAISE EXCEPTION 'PROJECT_DELETION_NOT_FOUND'; END IF;
    IF request.state = 'confirmed' THEN RETURN request; END IF;
    IF request.state <> 'pending' THEN
        RAISE EXCEPTION 'PROJECT_DELETION_NOT_PENDING';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.projects project
         WHERE project.id = request.project_id
           AND project.owner_principal_id = request.acquisition_principal_id
    ) THEN RAISE EXCEPTION 'PURGE_PROJECT_NOT_OWNED'; END IF;

    INSERT INTO public.data_purge_requests (
        acquisition_principal_id, trigger_kind, project_id, idempotency_key
    ) VALUES (
        request.acquisition_principal_id, 'project_deletion',
        request.project_id, 'project-deletion:' || request.id::text
    )
    ON CONFLICT (acquisition_principal_id, idempotency_key) DO NOTHING;
    SELECT id INTO purge_id FROM public.data_purge_requests
     WHERE acquisition_principal_id = request.acquisition_principal_id
       AND idempotency_key = 'project-deletion:' || request.id::text;
    -- 0456: at the latest before the purge deletes the pairs.
    PERFORM public.void_project_pair_releases_v1(request.project_id);

    UPDATE public.project_deletion_requests
       SET state = 'confirmed', confirmed_at = now(),
           confirmed_by = p_operator_id, purge_request_id = purge_id
     WHERE id = request.id
    RETURNING * INTO request;
    RETURN request;
END;
$$;
REVOKE ALL ON FUNCTION public.confirm_project_deletion_v1(UUID, UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.confirm_project_deletion_v1(UUID, UUID)
    TO service_role;

-- ── 4. Erasures asked for before this file ─────────────────────────────────

-- Each gets now what its request would have done. A second run finds every
-- such release voided already.
DO $$
BEGIN
    PERFORM public.stop_phase1_learning_v1(principal.id)
       FROM public.owner_principals principal
      WHERE public.phase1_learning_stopped_v1(principal.id);
    PERFORM public.void_project_pair_releases_v1(request.project_id)
       FROM public.project_deletion_requests request
      WHERE request.state IN ('pending', 'confirmed');
END;
$$;

COMMIT;
