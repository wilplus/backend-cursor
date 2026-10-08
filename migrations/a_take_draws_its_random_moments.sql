-- 0447 · A Take draws its random moments (V4 Phase 1, B1.2; build plan
-- D-ML-7; ledger B1.2; founder V2 A "from all moments", V3 A "round up").
--
-- WHY. V4 is measured before it serves anyone. Willfidence for a Take or a
-- speaker is the average over RANDOM moments (V4 brief, "Willfidence"; W1:
-- "machine picks plus 20% random; only the random ones are scored"), and
-- testing the picker on past data needs moments the picker did not choose.
-- So every Take that has a dark frame (0441, every speaker since S-V1 A)
-- gets a seeded random 20% of its moments, drawn from the Take's own seed
-- and stored APART from the machine's picks: picks stay in the frame's pick
-- log, the draw lives in its own table, and neither changes the other.
--
-- WHAT A MOMENT IS. One block of the frame: a slide-bounded run of about 75
-- words (contract 24a), the unit every V4 read uses. All of the Take's
-- blocks are drawn from, whether or not any candidate sits in them (V2 A).
--
-- THE DRAW (one rule, written twice so either can check the other: here and
-- services/v4_random_moments.py). n = the frame's blocks; k = ceil(n / 5),
-- so a Take with one to five moments draws one (V3 A). Each block is ranked
-- by sha256('v4-random-draw-v1:' || seed || ':' || block_id) as lowercase
-- hex, compared byte by byte (COLLATE "C"), the block id breaking a tie;
-- the first k are drawn, in that order (draw_rank 1..k). The seed is the
-- frame's pick-log seed, which 0441 already proved is the Take's own
-- (sha256 of 'v4-pick-seed-v1:' and the Take id). So the same Take always
-- draws the same moments, and a replay draws them again exactly. Every
-- block's chance of being drawn is k / n, kept as the two counts.
--
-- WHAT. One table and one writer:
--
--   v4_random_moments              one row per drawn moment: the Take, the
--                                  frame's policy version and hash, the
--                                  block id and slide, the draw rank, n and
--                                  k, the seed and the draw version. Tied to
--                                  its frame by a foreign key.
--   draw_v4_random_moments_v1      draws one Take's moments from its stored
--                                  frame, once. The database reads the frame
--                                  itself, so the app cannot hand it a
--                                  different list of moments or a different
--                                  seed. A second call returns what the
--                                  first stored and draws nothing new. A
--                                  Take with no frame gets nothing
--                                  ('no_frame'). One call per Take at a time
--                                  (a transaction advisory lock).
--
-- WHAT DOES NOT CHANGE. The frame table, its writer (0441) and its checks
-- are untouched; the draw never changes what is served, what V3 picks or
-- what the pick log says. Nothing is scored here: the reads come in B1.3.
-- No route reads this table and no user payload carries a draw (AC-9). The
-- app calls the writer after the frame is stored, as a side write that
-- never raises into the Take pipeline (LIVE LOOP).
--
-- Idempotent: IF NOT EXISTS, CREATE OR REPLACE; applied twice it changes
-- nothing. Writes no row on its own. Locks: only the new table (and, at run
-- time, a per-Take transaction advisory lock inside the function).
--
-- Rollback (a new forward migration): DROP FUNCTION
-- public.draw_v4_random_moments_v1(uuid); DROP TABLE
-- public.v4_random_moments. Nothing depends on either, and every draw can
-- be made again from the frames.

BEGIN;

CREATE TABLE IF NOT EXISTS public.v4_random_moments (
    take_session_id          uuid        NOT NULL,
    policy_version           text        NOT NULL,
    draw_version             text        NOT NULL,
    block_id                 text        NOT NULL,
    slide_index              integer     NULL,
    draw_rank                integer     NOT NULL,
    moments_in_take          integer     NOT NULL,
    drawn_count              integer     NOT NULL,
    seed                     text        NOT NULL,
    frame_hash               text        NOT NULL,
    acquisition_principal_id uuid        NOT NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (take_session_id, draw_version, block_id),
    CONSTRAINT v4_random_moments_frame_fk
        FOREIGN KEY (take_session_id, policy_version)
        REFERENCES public.take_feedback_policy_v3_shadow_frames
            (take_session_id, policy_version)
        ON DELETE CASCADE,
    CONSTRAINT v4_random_moments_draw_version CHECK (
        draw_version = 'v4-random-draw-v1'),
    CONSTRAINT v4_random_moments_block_id CHECK (length(block_id) > 0),
    CONSTRAINT v4_random_moments_counts CHECK (
        moments_in_take >= 1
        AND drawn_count = (moments_in_take + 4) / 5
        AND draw_rank BETWEEN 1 AND drawn_count),
    CONSTRAINT v4_random_moments_seed CHECK (seed ~ '^[0-9]{1,16}$'),
    CONSTRAINT v4_random_moments_frame_hash CHECK (
        frame_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT v4_random_moments_rank_once UNIQUE (
        take_session_id, draw_version, draw_rank)
);

ALTER TABLE public.v4_random_moments ENABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS v4_random_moments_principal_idx
    ON public.v4_random_moments (acquisition_principal_id);

COMMENT ON TABLE public.v4_random_moments IS
    'V4 Phase 1 B1.2 (0447): each Take''s seeded random 20% of moments '
    '(frame blocks), k = ceil(n/5), ranked by sha256 of the draw version, the '
    'Take''s pick-log seed and the block id. Stored apart from the machine''s '
    'picks (the frame''s pick log). Written only by '
    'draw_v4_random_moments_v1 from the stored frame. Internal: never in a '
    'user payload (AC-9).';

CREATE OR REPLACE FUNCTION public.draw_v4_random_moments_v1(
    p_take_session_id uuid
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    v_policy  constant text := 'take-feedback-policy-v3-universal-dark-v3';
    v_draw    constant text := 'v4-random-draw-v1';
    v_frame   public.take_feedback_policy_v3_shadow_frames%ROWTYPE;
    v_seed    text;
    v_n       integer;
    v_k       integer;
    v_stored  integer;
BEGIN
    IF p_take_session_id IS NULL THEN
        RAISE EXCEPTION 'V4_RANDOM_MOMENTS_INPUT_INVALID';
    END IF;

    -- One draw per Take at a time: a second caller waits, then finds the
    -- first caller's rows and returns them.
    PERFORM pg_advisory_xact_lock(
        hashtext('v4-random-draw:' || p_take_session_id::text));

    SELECT count(*) INTO v_stored
      FROM public.v4_random_moments
     WHERE take_session_id = p_take_session_id
       AND draw_version = v_draw;
    IF v_stored > 0 THEN
        RETURN jsonb_build_object(
            'outcome', 'stored', 'draw_version', v_draw, 'drawn', v_stored);
    END IF;

    SELECT * INTO v_frame
      FROM public.take_feedback_policy_v3_shadow_frames
     WHERE take_session_id = p_take_session_id
       AND policy_version = v_policy;
    IF v_frame.take_session_id IS NULL THEN
        RETURN jsonb_build_object('outcome', 'no_frame');
    END IF;

    -- The frame was checked by its writer (0441); the draw still proves the
    -- two things it reads before it reads them, each its own statement so
    -- nothing is expanded before its type is known.
    v_seed := v_frame.frame #>> '{pick_log,seed}';
    IF COALESCE(v_seed, '') !~ '^[0-9]{1,16}$'
       OR jsonb_typeof(v_frame.frame -> 'blocks') IS DISTINCT FROM 'array'
       OR jsonb_array_length(v_frame.frame -> 'blocks') = 0 THEN
        RAISE EXCEPTION 'V4_RANDOM_MOMENTS_FRAME_INVALID';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM jsonb_array_elements(v_frame.frame -> 'blocks') block
         WHERE jsonb_typeof(block) IS DISTINCT FROM 'object'
            OR jsonb_typeof(block -> 'block_id') IS DISTINCT FROM 'string'
            OR length(block ->> 'block_id') = 0
            OR (block ? 'slide_index'
                AND jsonb_typeof(block -> 'slide_index')
                    NOT IN ('number', 'null'))
    ) THEN
        RAISE EXCEPTION 'V4_RANDOM_MOMENTS_FRAME_INVALID';
    END IF;
    -- A moment is drawn at most once: two blocks with one id refuse the
    -- draw rather than doubling that moment's chance.
    IF EXISTS (
        SELECT 1
          FROM jsonb_array_elements(v_frame.frame -> 'blocks') block
         GROUP BY block ->> 'block_id'
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'V4_RANDOM_MOMENTS_FRAME_INVALID';
    END IF;

    v_n := jsonb_array_length(v_frame.frame -> 'blocks');
    v_k := (v_n + 4) / 5;  -- ceil(n / 5): 20%, rounded up (V3 A)

    INSERT INTO public.v4_random_moments (
        take_session_id, policy_version, draw_version, block_id,
        slide_index, draw_rank, moments_in_take, drawn_count, seed,
        frame_hash, acquisition_principal_id
    )
    SELECT p_take_session_id, v_policy, v_draw, ranked.block_id,
           ranked.slide_index, ranked.draw_rank, v_n, v_k, v_seed,
           v_frame.frame_hash, v_frame.acquisition_principal_id
      FROM (
          SELECT block ->> 'block_id' AS block_id,
                 CASE WHEN jsonb_typeof(block -> 'slide_index') = 'number'
                      THEN (block ->> 'slide_index')::numeric::integer
                 END AS slide_index,
                 row_number() OVER (
                     ORDER BY encode(extensions.digest(
                                  v_draw || ':' || v_seed || ':'
                                  || (block ->> 'block_id'), 'sha256'),
                                  'hex') COLLATE "C",
                              (block ->> 'block_id') COLLATE "C"
                 ) AS draw_rank
            FROM jsonb_array_elements(v_frame.frame -> 'blocks') block
      ) ranked
     WHERE ranked.draw_rank <= v_k;

    RETURN jsonb_build_object(
        'outcome', 'drawn', 'draw_version', v_draw, 'drawn', v_k,
        'moments', v_n);
END;
$$;

COMMENT ON FUNCTION public.draw_v4_random_moments_v1(uuid) IS
    'Draw one Take''s seeded random 20% of moments from its stored dark '
    'frame (0447, V4 B1.2): k = ceil(n/5) blocks ranked by sha256 of '
    '''v4-random-draw-v1:'' || seed || '':'' || block_id. Once per Take; a '
    'second call returns the stored draw. service_role only.';

-- ── The door ───────────────────────────────────────────────────────────────
-- Browser roles get nothing. The app reads the table and calls the writer
-- with the service key, and the purge deletes a Take's rows with the Take;
-- the table is written only through the writer.
REVOKE ALL ON TABLE public.v4_random_moments FROM PUBLIC;
REVOKE ALL ON FUNCTION public.draw_v4_random_moments_v1(uuid) FROM PUBLIC;
DO $$
DECLARE
    v_role text;
BEGIN
    FOREACH v_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
            EXECUTE format('REVOKE ALL ON TABLE public.v4_random_moments FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON FUNCTION public.draw_v4_random_moments_v1(uuid) FROM %I', v_role);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        REVOKE ALL ON TABLE public.v4_random_moments FROM service_role;
        GRANT SELECT, DELETE ON TABLE public.v4_random_moments TO service_role;
        GRANT EXECUTE ON FUNCTION public.draw_v4_random_moments_v1(uuid) TO service_role;
    END IF;
END $$;

COMMIT;
