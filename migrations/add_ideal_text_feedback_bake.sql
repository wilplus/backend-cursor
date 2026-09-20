-- Bookmarks that arrive with the words.
--
-- FOUNDER, 2026-09-20: "it's unacceptable that we open the ideal text after
-- the processing and there are no bookmarks. There need to be bookmarks right
-- away the moment we see it. Otherwise, that makes no sense because people
-- will quit."
--
-- THE DEFECT IS ARCHITECTURAL, not a timeout. The bookmarks are not stored
-- anywhere. `document_layers` runs `_tracked_changes_block` -> the whole
-- ~20-stage Manager pipeline (relocate, candidates, selection, span checks,
-- V3 arbitration) on EVERY GET. They are COMPUTED when the document opens,
-- not read. No client retry budget can make a computation instant.
--
-- The core document already solved this: `publish_for_arc` materialises it at
-- a write boundary and the cold-open endpoint performs one read. This table
-- is that same move for the feedback that hangs off it.
--
-- WHY A SEPARATE TABLE AND NOT THE SNAPSHOT PAYLOAD. The snapshot is
-- immutable by trigger, and V3 cannot be computed before it exists:
-- `read_feedback_v3_candidate_source_snapshot_v1` requires
-- `surface = served_text` against the CURRENT published snapshot, so the bake
-- has to happen after publication. Writing it into the payload would mean
-- either republishing (a loop) or breaking immutability (the thing that makes
-- the core trustworthy). A row that POINTS AT a snapshot keeps both.
--
-- FRESHNESS IS TIME-BASED AND CONSERVATIVE, on purpose. The block depends on
-- the snapshot (frozen, so the id covers it) and on mutable per-user feedback
-- state: which proposals have been decided, and which suggestions have been
-- applied. Those writes do NOT advance the document generation, so a bake
-- keyed on the snapshot alone would go stale the moment a user decided
-- something — and serving a bookmark the user already dismissed is worse than
-- serving it slowly.
--
-- So the read refuses the bake if ANYTHING was written to that surface after
-- the bake was made. Not "which rows changed" — any row, for this arc, at
-- all. That is deliberately coarse: it cannot be fooled by a writer nobody
-- remembered to enumerate, and the penalty for a false miss is one live
-- computation, which is exactly today's behaviour. Correctness first, speed
-- when it is provably safe.
--
-- What this buys, concretely: the cold open after processing. Take 1 has no
-- decisions yet; Take 2+ republishes and re-bakes AFTER every earlier
-- decision, so its bake is fresh too. Once the user starts deciding, reads go
-- live again — and by then they are interacting, not staring at a blank
-- document wondering whether the product works.
--
-- NOT A CACHE OF THE DOCUMENT. The words, their order, and Ideal Text itself
-- are untouched (L1). The Manager still arbitrates exactly as it does now,
-- just earlier (L2). No provenance is mixed or reused (L3). Nothing here
-- surfaces a score, a number or a coach guess.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS public.ideal_text_feedback_bakes (
    arc_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    -- The exact immutable document this block was computed over. A new
    -- snapshot is a new document, so its bake is simply absent until made.
    document_snapshot_id UUID NOT NULL
        REFERENCES public.ideal_text_document_snapshots(id) ON DELETE CASCADE,
    payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    -- clock_timestamp(), not now(): now() is the transaction start, and the
    -- bake runs at the END of a publish transaction that may have taken
    -- seconds. A baked_at earlier than writes the bake actually saw would
    -- make a FRESH bake look stale — harmless here (it falls back to live)
    -- but it would quietly disable the whole feature.
    baked_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (arc_id, actor_id)
);

CREATE INDEX IF NOT EXISTS ideal_text_feedback_bake_snapshot
    ON public.ideal_text_feedback_bakes (document_snapshot_id);

ALTER TABLE public.ideal_text_feedback_bakes ENABLE ROW LEVEL SECURITY;

-- The mutable surface, named in ONE place so the read and any future writer
-- cannot disagree about what staleness means. Returns the newest write this
-- arc has taken on its per-user feedback state, or NULL when it has none.
--
-- `user_suggestion_feedback` is session-scoped, so it reaches the arc through
-- v2_sessions. `intervention_decisions.arc_id` is TEXT and v2_sessions.arc_id
-- is not, hence the explicit casts.
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
  ) AS surface;
$$;

REVOKE ALL ON FUNCTION
    public.ideal_text_feedback_surface_touched_at_v1(TEXT) FROM PUBLIC;

-- Store one block against one snapshot. Overwrites this actor's previous bake
-- unconditionally: only the current document is ever served, so keeping older
-- ones would be storage with no reader.
CREATE OR REPLACE FUNCTION public.write_ideal_text_feedback_bake_v1(
    p_arc_id TEXT,
    p_actor_id TEXT,
    p_document_snapshot_id UUID,
    p_payload JSONB
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE written public.ideal_text_feedback_bakes;
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

  INSERT INTO public.ideal_text_feedback_bakes AS bake (
    arc_id, actor_id, document_snapshot_id, payload, baked_at
  ) VALUES (
    p_arc_id, p_actor_id, p_document_snapshot_id, p_payload, clock_timestamp()
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

REVOKE ALL ON FUNCTION public.write_ideal_text_feedback_bake_v1(
    TEXT, TEXT, UUID, JSONB) FROM PUBLIC;

-- Serve the block ONLY when it is provably the right one: same snapshot, and
-- nothing written to the mutable feedback surface since it was made. Returns
-- NULL on every other outcome, and the caller computes live — which is
-- exactly the behaviour that exists today, so a miss can never be a
-- regression.
CREATE OR REPLACE FUNCTION public.read_ideal_text_feedback_bake_v1(
    p_arc_id TEXT,
    p_actor_id TEXT,
    p_document_snapshot_id UUID
) RETURNS JSONB
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=public AS $$
DECLARE
  bake public.ideal_text_feedback_bakes;
  touched TIMESTAMPTZ;
BEGIN
  IF NULLIF(trim(p_arc_id),'') IS NULL
     OR NULLIF(trim(p_actor_id),'') IS NULL
     OR p_document_snapshot_id IS NULL
  THEN RETURN NULL; END IF;

  SELECT * INTO bake FROM public.ideal_text_feedback_bakes candidate
   WHERE candidate.arc_id = p_arc_id
     AND candidate.actor_id = p_actor_id
     AND candidate.document_snapshot_id = p_document_snapshot_id;
  IF NOT FOUND THEN RETURN NULL; END IF;

  touched := public.ideal_text_feedback_surface_touched_at_v1(p_arc_id);
  -- `>=` and not `>`: a decision committed in the same clock tick as the bake
  -- may or may not have been visible to it, and "may" is not good enough for
  -- a row the user has already acted on.
  IF touched IS NOT NULL AND touched >= bake.baked_at THEN RETURN NULL; END IF;

  RETURN jsonb_build_object(
    'document_snapshot_id', bake.document_snapshot_id,
    'baked_at', bake.baked_at,
    'payload', bake.payload
  );
END $$;

REVOKE ALL ON FUNCTION public.read_ideal_text_feedback_bake_v1(
    TEXT, TEXT, UUID) FROM PUBLIC;

-- ── GRANTS — the door ──────────────────────────────────────────────────────
--
-- PostgREST publishes EVERY function in the exposed schema at
-- /rest/v1/rpc/<name>, callable with the anon key lifted from the browser
-- bundle. Postgres grants EXECUTE on a new function to PUBLIC by default, and
-- Supabase's ALTER DEFAULT PRIVILEGES hands anon/authenticated a DIRECT grant
-- on functions in `public` — which a REVOKE aimed at PUBLIC does not touch.
-- Both roles have to be named.
--
-- It matters here in both directions. These functions are SECURITY DEFINER,
-- so `read_...` would hand any visitor another user's Manager feedback for any
-- arc id, and `write_...` would let them replace what a speaker sees on their
-- own document. RLS does not cover this: RLS is table-level.
--
-- Roles are guarded — anon / authenticated / service_role exist on Supabase
-- but not on a bare Postgres, and a missing role must not abort the migration.
DO $$
DECLARE
    r   text;
    sig text;
BEGIN
    FOREACH sig IN ARRAY ARRAY[
        'public.ideal_text_feedback_surface_touched_at_v1(text)',
        'public.write_ideal_text_feedback_bake_v1(text, text, uuid, jsonb)',
        'public.read_ideal_text_feedback_bake_v1(text, text, uuid)'
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

COMMIT;
