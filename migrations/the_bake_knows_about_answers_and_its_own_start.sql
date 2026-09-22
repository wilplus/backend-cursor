-- 0351 · The stored bookmark set is invalidated by a V3 answer, and it is
--        dated from the moment its computation STARTED.
--
-- PRODUCTION, 2026-09-22. Project "j" opened with a faint circle after every
-- paragraph for about seven seconds, then the bookmarks arrived. The timed
-- read showed why: the Manager finished in 4.5 s with four marks, which is
-- longer than the 2 s cold-open budget and shorter than the 30 s retry
-- budget, so EVERY open paid a full live computation, three of them in ten
-- seconds (cold read, retry, retry). `ideal_text_feedback_bakes` had no row
-- for the project, and the backend service carried
-- `IDEAL_TEXT_FEEDBACK_BAKE_ENABLED=0`, left over from the #584 rollback.
--
-- Before that flag can be turned back on, the freshness rule 0345 wrote has
-- to know about two writers that did not exist when it was written:
--
--   * `take_feedback_self_report` — the legacy answer route
--     (`/user/takes/<id>/feedback-response`), which is the route every
--     non-canary account answers a bookmark through today.
--   * `feedback_v3_owner_responses` — the service answer route
--     (`/user/mlc3/feedback/respond`), reached through a membership whose
--     take names the arc.
--
-- The stored block carries each item's status (`_mark_answered_service_items`
-- runs inside the computation), so a bake that survived an answer would put
-- an answered bookmark back on the page after a reload — the exact
-- inconsistency the founder has been circling ("sometimes they do appear but
-- then a while later they are gone"). 0345's rule is coarse on purpose: any
-- write to the surface, for this arc, at all. These two tables ARE that
-- surface now, so they join the rule.
--
-- THE SECOND CHANGE IS THE COMPUTATION'S OWN CLOCK. `baked_at` was
-- `clock_timestamp()` at the WRITE, but the block was computed over the
-- 4-40 seconds before it. An answer committed inside that window was not
-- seen by the computation, yet `touched >= baked_at` would call the bake
-- fresh and serve the stale status until the next unrelated write. That
-- window is not theoretical: with the bake on, a live computation runs right
-- after an answer (the answer invalidated the previous bake), which is
-- exactly when the next answer arrives.
--
-- The writer therefore takes how long the computation took
-- (`p_computed_over_ms`, measured by the caller on its own monotonic clock,
-- so no two machines' wall clocks are compared) and dates the bake from the
-- START of that window. A write between start and end now invalidates,
-- because `touched >= baked_at`. The only cost of over-stating the window is
-- one unnecessary live computation, which is today's behaviour.
--
-- The four-argument signature is dropped rather than overloaded: PostgREST
-- resolves an RPC by parameter names, and two candidates that both accept
-- the same four names is an ambiguity error, not a fallback. The new
-- parameter defaults to 0, so a container that has not yet learned to pass
-- it still writes — dated at the write, as before.
--
-- NOT A CACHE OF THE DOCUMENT. Nothing here touches the words (L1); the
-- Manager still arbitrates, only earlier (L2); no provenance moves (L3).
-- Nothing surfaces a score, a number or a coach guess.
BEGIN;

-- ── The mutable surface, now including both answer routes ─────────────────
CREATE OR REPLACE FUNCTION public.ideal_text_feedback_surface_touched_at_v1(
    p_arc_id TEXT
) RETURNS TIMESTAMPTZ
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public AS $$
  SELECT max(touched) FROM (
    SELECT max(GREATEST(decision.created_at, decision.updated_at)) AS touched
      FROM public.intervention_decisions decision
     WHERE decision.arc_id = p_arc_id
    UNION ALL
    SELECT max(tap.created_at) AS touched
      FROM public.user_suggestion_feedback tap
      JOIN public.v2_sessions session ON session.id = tap.session_id
     WHERE session.arc_id::text = p_arc_id
    UNION ALL
    -- The legacy answer route. `arc_id` is stored on the row itself.
    SELECT max(report.created_at) AS touched
      FROM public.take_feedback_self_report report
     WHERE report.arc_id = p_arc_id
    UNION ALL
    -- The service answer route. An answer names its membership; the
    -- membership names its take; the take names the arc.
    SELECT max(answer.created_at) AS touched
      FROM public.feedback_v3_owner_responses answer
      JOIN public.feedback_v3_memberships membership
        ON membership.id = answer.membership_id
      JOIN public.v2_sessions session ON session.id = membership.take_id
     WHERE session.arc_id::text = p_arc_id
  ) AS surface;
$$;

-- ── The writer, dated from the computation's start ────────────────────────
DROP FUNCTION IF EXISTS public.write_ideal_text_feedback_bake_v1(
    TEXT, TEXT, UUID, JSONB);

CREATE OR REPLACE FUNCTION public.write_ideal_text_feedback_bake_v1(
    p_arc_id TEXT,
    p_actor_id TEXT,
    p_document_snapshot_id UUID,
    p_payload JSONB,
    p_computed_over_ms INTEGER DEFAULT 0
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE
  written public.ideal_text_feedback_bakes;
  started TIMESTAMPTZ;
BEGIN
  IF NULLIF(trim(p_arc_id),'') IS NULL
     OR NULLIF(trim(p_actor_id),'') IS NULL
     OR p_document_snapshot_id IS NULL
     OR jsonb_typeof(p_payload) <> 'object'
  THEN RAISE EXCEPTION 'IDEAL_TEXT_FEEDBACK_BAKE_INVALID'; END IF;

  -- The snapshot must be this arc/actor's own. A bake pointing at someone
  -- else's document would serve their feedback under this user's words.
  IF NOT EXISTS (
    SELECT 1 FROM public.ideal_text_document_snapshots snapshot
     WHERE snapshot.id = p_document_snapshot_id
       AND snapshot.arc_id = p_arc_id
       AND snapshot.actor_id = p_actor_id
  ) THEN RAISE EXCEPTION 'IDEAL_TEXT_FEEDBACK_BAKE_SNAPSHOT_NOT_OWNED'; END IF;

  -- clock_timestamp(), not now(): now() is the transaction start, and this
  -- write can sit at the end of a transaction that took seconds. The window
  -- is then subtracted so `baked_at` is when the computation BEGAN — the
  -- last moment whose writes it is guaranteed to have seen.
  started := clock_timestamp()
             - make_interval(secs => GREATEST(COALESCE(p_computed_over_ms, 0), 0) / 1000.0);

  INSERT INTO public.ideal_text_feedback_bakes AS bake (
    arc_id, actor_id, document_snapshot_id, payload, baked_at
  ) VALUES (
    p_arc_id, p_actor_id, p_document_snapshot_id, p_payload, started
  )
  ON CONFLICT (arc_id, actor_id) DO UPDATE
    SET document_snapshot_id = EXCLUDED.document_snapshot_id,
        payload = EXCLUDED.payload,
        baked_at = EXCLUDED.baked_at
  RETURNING * INTO written;

  RETURN jsonb_build_object(
    'document_snapshot_id', written.document_snapshot_id,
    'baked_at', written.baked_at
  );
END $$;

-- ── GRANTS — the door, restated for the new signature ─────────────────────
-- A dropped-and-recreated function starts with Postgres' default EXECUTE to
-- PUBLIC and Supabase's direct grant to anon/authenticated. Both are closed
-- here exactly as 0345 closed them; the touched-at function keeps its ACL
-- through CREATE OR REPLACE and is restated only so this file is
-- self-describing. Roles are guarded: anon / authenticated / service_role
-- exist on Supabase but not on a bare Postgres.
REVOKE ALL ON FUNCTION public.write_ideal_text_feedback_bake_v1(
    TEXT, TEXT, UUID, JSONB, INTEGER) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.ideal_text_feedback_surface_touched_at_v1(
    TEXT) FROM PUBLIC;

DO $$
DECLARE
    r   text;
    sig text;
BEGIN
    FOREACH sig IN ARRAY ARRAY[
        'public.ideal_text_feedback_surface_touched_at_v1(text)',
        'public.write_ideal_text_feedback_bake_v1(text, text, uuid, jsonb, integer)'
    ] LOOP
        FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                EXECUTE format('REVOKE ALL ON FUNCTION %s FROM %I', sig, r);
            END IF;
        END LOOP;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
            EXECUTE format(
                'GRANT EXECUTE ON FUNCTION %s TO service_role', sig);
        END IF;
    END LOOP;
END $$;

NOTIFY pgrst, 'reload schema';

COMMIT;
