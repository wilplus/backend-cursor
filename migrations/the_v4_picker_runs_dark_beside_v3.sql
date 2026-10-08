-- 0452 · The V4 picker runs dark beside V3 (V4 Phase 1, B1.6; build plan
-- D-ML-12; founder P1, P2, P3, V13 A, V14 A, V15 A, V15a A, V16a A, QB6 A,
-- QB7 B, H2, S-B1b A).
--
-- WHY. V4 must show it picks better than V3 before the founder switches it
-- on (BEXIT). So on every Take that has its willfidence read (0449), V4
-- records, per block, its own pick (the kind and the moment) beside V3's,
-- its rank (P2: importance x (1 - S*W) x sureness), and whether it fell
-- back to V3's pick because it was too unsure, with the reason (V15 A,
-- never silent). It serves nothing. The rule is services/v4_picker.py.
--
-- WHAT THE DATABASE PROVES before it stores a Take's picks:
--   * the rows are exactly the frame's blocks, each once, after the read;
--   * allowed first (P1): praise only on a block the frame reads
--     confident (delivery band high or mid-high), a clearer version or an
--     exercise only on one read weak, nothing on a block with no read;
--   * the role is one of the six signed roles and its importance is that
--     role's signed weight (version 'v4-moment-roles-v1'), and the role is
--     the one the 0449 read stored for the block;
--   * willfident is the read's S*W and the gap 1 - S*W; strength,
--     disagreement and sureness lie in 0..1 and sureness =
--     strength x (1 - disagreement); rank = importance x gap x sureness
--     (to 1e-9, the app computes in floating point);
--   * a fallback carries its reason ('no_role', 'no_read', 'unsure' below
--     the 0.3 placeholder cut-off) and uses V3's kind and moment; a pick
--     that does not fall back uses V4's own;
--   * picked = ranked among the blocks that may carry a clearer version or
--     an exercise, in the top three (H2).
-- The Take's line keeps the blocks and how many fell back (V15a A: more
-- than one in five fails the exit gate).
--
-- WHAT DOES NOT CHANGE. V3 still serves every Take; Confident Voice stays on
-- the best-sounding moment (P3); nothing here is read by a route (AC-9).
-- Written from the queued read job, never on the request path (LIVE LOOP).
--
-- Idempotent: IF NOT EXISTS, CREATE OR REPLACE; no row written on its own;
-- locks only the new tables. Rollback (forward): drop the function and the
-- two tables.

BEGIN;

CREATE TABLE IF NOT EXISTS public.v4_picks (
    take_session_id          uuid        NOT NULL,
    policy_version           text        NOT NULL,
    picker_version           text        NOT NULL,
    block_id                 text        NOT NULL,
    role                     text        NULL,
    importance               numeric     NULL,
    willfident               numeric     NULL,
    gap                      numeric     NULL,
    strength                 numeric     NOT NULL,
    disagreement             numeric     NOT NULL,
    sureness                 numeric     NOT NULL,
    rank_score               numeric     NULL,
    rank_position            integer     NULL,
    picked                   boolean     NOT NULL,
    v4_kind                  text        NULL,
    v4_snippet_id            text        NULL,
    v3_kind                  text        NULL,
    v3_snippet_id            text        NULL,
    fallback                 boolean     NOT NULL,
    fallback_reason          text        NULL,
    used_kind                text        NULL,
    used_snippet_id          text        NULL,
    roles_version            text        NOT NULL,
    cutoff                   numeric     NOT NULL,
    cutoff_version           text        NOT NULL,
    acquisition_principal_id uuid        NOT NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (take_session_id, policy_version, picker_version, block_id),
    CONSTRAINT v4_picks_frame_fk
        FOREIGN KEY (take_session_id, policy_version)
        REFERENCES public.take_feedback_policy_v3_shadow_frames
            (take_session_id, policy_version)
        ON DELETE CASCADE,
    CONSTRAINT v4_picks_versions CHECK (
        policy_version = 'take-feedback-policy-v3-universal-dark-v3'
        AND picker_version = 'v4-picker-v1'
        AND roles_version = 'v4-moment-roles-v1'
        AND cutoff = 0.3 AND cutoff_version = 'sureness-cutoff-v0-placeholder'),
    CONSTRAINT v4_picks_kinds CHECK (
        (v4_kind IS NULL OR v4_kind IN ('rewrite', 'exercise', 'praise'))
        AND (v3_kind IS NULL OR v3_kind IN ('rewrite', 'exercise', 'praise'))),
    CONSTRAINT v4_picks_role CHECK (
        importance IS NOT DISTINCT FROM CASE role
            WHEN 'opening' THEN 1.0 WHEN 'main_point' THEN 1.0
            WHEN 'close' THEN 1.0 WHEN 'evidence' THEN 0.7
            WHEN 'transition' THEN 0.4 WHEN 'aside' THEN 0.2 END
        AND (role IS NULL OR role IN ('opening', 'main_point', 'close',
                                      'evidence', 'transition', 'aside'))),
    CONSTRAINT v4_picks_ranges CHECK (
        strength BETWEEN 0 AND 1 AND disagreement BETWEEN 0 AND 1
        AND sureness BETWEEN 0 AND 1
        AND abs(sureness - strength * (1 - disagreement)) < 1e-9
        AND (willfident IS NULL OR willfident BETWEEN 0 AND 1)
        AND (gap IS NULL) = (willfident IS NULL)
        AND (gap IS NULL OR abs(gap - (1 - willfident)) < 1e-9)),
    CONSTRAINT v4_picks_rank CHECK (
        (rank_score IS NULL) = (importance IS NULL OR gap IS NULL)
        AND (rank_score IS NULL
             OR abs(rank_score - importance * gap * sureness) < 1e-9)),
    CONSTRAINT v4_picks_fallback CHECK (
        fallback_reason IS NOT DISTINCT FROM CASE
            WHEN importance IS NULL THEN 'no_role'
            WHEN gap IS NULL THEN 'no_read'
            WHEN sureness < cutoff THEN 'unsure' END
        AND fallback = (fallback_reason IS NOT NULL)
        AND used_kind IS NOT DISTINCT FROM CASE WHEN fallback THEN v3_kind ELSE v4_kind END
        AND used_snippet_id IS NOT DISTINCT FROM
            CASE WHEN fallback THEN v3_snippet_id ELSE v4_snippet_id END),
    CONSTRAINT v4_picks_picked CHECK (
        (rank_position IS NULL OR rank_position >= 1)
        AND picked = (rank_position IS NOT NULL AND rank_position <= 3)
        AND (rank_position IS NULL
             OR (v4_kind IN ('rewrite', 'exercise') AND rank_score IS NOT NULL)))
);
ALTER TABLE public.v4_picks ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.v4_pick_takes (
    take_session_id          uuid        NOT NULL,
    policy_version           text        NOT NULL,
    picker_version           text        NOT NULL,
    blocks                   integer     NOT NULL,
    fallback_blocks          integer     NOT NULL,
    acquisition_principal_id uuid        NOT NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (take_session_id, policy_version, picker_version),
    CONSTRAINT v4_pick_takes_frame_fk
        FOREIGN KEY (take_session_id, policy_version)
        REFERENCES public.take_feedback_policy_v3_shadow_frames
            (take_session_id, policy_version)
        ON DELETE CASCADE,
    CONSTRAINT v4_pick_takes_counts CHECK (
        blocks >= 1 AND fallback_blocks BETWEEN 0 AND blocks)
);
ALTER TABLE public.v4_pick_takes ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.v4_picks IS
    'V4 B1.6 (0452): V4''s dark pick per block beside V3''s, its rank and '
    'any fallback with its reason (P1, P2, V15 A, V15a A). Serves nothing. '
    'Internal (AC-9).';

CREATE OR REPLACE FUNCTION public.record_v4_picks_v1(
    p_take_session_id uuid,
    p_rows jsonb
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    v_policy constant text := 'take-feedback-policy-v3-universal-dark-v3';
    v_picker constant text := 'v4-picker-v1';
    v_frame  public.take_feedback_policy_v3_shadow_frames%ROWTYPE;
    v_n      integer;
BEGIN
    IF p_take_session_id IS NULL OR jsonb_typeof(p_rows) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'V4_PICKS_INPUT_INVALID';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtext('v4-picks:' || p_take_session_id::text));
    IF EXISTS (SELECT 1 FROM public.v4_pick_takes
                WHERE take_session_id = p_take_session_id
                  AND policy_version = v_policy AND picker_version = v_picker) THEN
        RETURN jsonb_build_object('outcome', 'stored');
    END IF;
    SELECT * INTO v_frame FROM public.take_feedback_policy_v3_shadow_frames
     WHERE take_session_id = p_take_session_id AND policy_version = v_policy;
    IF v_frame.take_session_id IS NULL THEN
        RETURN jsonb_build_object('outcome', 'no_frame');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.v4_willfidence_takes
                    WHERE take_session_id = p_take_session_id
                      AND policy_version = v_policy
                      AND read_version = 'willfidence-v1-machine') THEN
        RETURN jsonb_build_object('outcome', 'no_read');
    END IF;

    -- Shape and types first; nothing is cast before its type is known.
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(p_rows) r
         WHERE jsonb_typeof(r) IS DISTINCT FROM 'object'
            OR jsonb_typeof(r -> 'block_id') IS DISTINCT FROM 'string'
            OR jsonb_typeof(r -> 'fallback') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(r -> 'picked') IS DISTINCT FROM 'boolean'
            OR EXISTS (SELECT 1 FROM unnest(ARRAY['strength', 'disagreement', 'sureness'])
                              AS k(key)
                        WHERE jsonb_typeof(r -> k.key) IS DISTINCT FROM 'number')
            OR EXISTS (SELECT 1 FROM unnest(ARRAY['importance', 'willfident', 'gap',
                                                  'rank_score', 'rank_position'])
                              AS k(key)
                        WHERE COALESCE(jsonb_typeof(r -> k.key), 'null')
                              NOT IN ('number', 'null'))
            OR EXISTS (SELECT 1 FROM unnest(ARRAY['role', 'v4_kind', 'v4_snippet_id',
                                                  'v3_kind', 'v3_snippet_id',
                                                  'fallback_reason', 'used_kind',
                                                  'used_snippet_id'])
                              AS k(key)
                        WHERE COALESCE(jsonb_typeof(r -> k.key), 'null')
                              NOT IN ('string', 'null'))
    ) THEN
        RAISE EXCEPTION 'V4_PICKS_INVALID';
    END IF;
    -- Exactly the frame's blocks, each once.
    IF EXISTS (
        WITH sides AS (
            SELECT block ->> 'block_id' AS block_id, 1 AS f, 0 AS r
              FROM jsonb_array_elements(v_frame.frame -> 'blocks') block
            UNION ALL
            SELECT r ->> 'block_id', 0, 1 FROM jsonb_array_elements(p_rows) r
        )
        SELECT 1 FROM sides GROUP BY block_id HAVING sum(f) <> 1 OR sum(r) <> 1
    ) THEN
        RAISE EXCEPTION 'V4_PICKS_DO_NOT_MATCH_THE_FRAME';
    END IF;
    -- Allowed first (P1), against the frame's own read of each block; the
    -- role and S*W are the 0449 read's; each moment is one of the block's
    -- clips.
    IF EXISTS (
        SELECT 1
          FROM jsonb_array_elements(p_rows) r
          JOIN jsonb_array_elements(v_frame.frame -> 'blocks') block
            ON block ->> 'block_id' = r ->> 'block_id'
          LEFT JOIN public.v4_willfidence_reads read
            ON read.take_session_id = p_take_session_id
           AND read.policy_version = v_policy
           AND read.read_version = 'willfidence-v1-machine'
           AND read.block_id = r ->> 'block_id'
         WHERE (r ->> 'v4_kind' = 'praise' AND COALESCE(block ->> 'delivery_band', '')
                    NOT IN ('delivery_signal_high', 'delivery_signal_mid_high'))
            OR (r ->> 'v4_kind' IN ('rewrite', 'exercise')
                AND (block ->> 'delivery_band' IS NULL
                     OR block ->> 'delivery_band' IN ('delivery_signal_high',
                                                      'delivery_signal_mid_high')))
            OR (r ->> 'role') IS DISTINCT FROM read.role
            OR (CASE WHEN jsonb_typeof(r -> 'willfident') = 'number'
                     THEN abs((r ->> 'willfident')::numeric - read.willfident) >= 1e-9
                     ELSE read.willfident IS NOT NULL END)
            OR (r ->> 'v4_snippet_id' IS NOT NULL AND NOT (
                    COALESCE(block -> 'snippet_ids', '[]'::jsonb) ? (r ->> 'v4_snippet_id')))
    ) THEN
        RAISE EXCEPTION 'V4_PICKS_NOT_ALLOWED';
    END IF;

    INSERT INTO public.v4_picks (
        take_session_id, policy_version, picker_version, block_id, role,
        importance, willfident, gap, strength, disagreement, sureness,
        rank_score, rank_position, picked, v4_kind, v4_snippet_id, v3_kind,
        v3_snippet_id, fallback, fallback_reason, used_kind, used_snippet_id,
        roles_version, cutoff, cutoff_version, acquisition_principal_id)
    SELECT p_take_session_id, v_policy, v_picker, r ->> 'block_id', r ->> 'role',
           (r ->> 'importance')::numeric, (r ->> 'willfident')::numeric,
           (r ->> 'gap')::numeric, (r ->> 'strength')::numeric,
           (r ->> 'disagreement')::numeric, (r ->> 'sureness')::numeric,
           (r ->> 'rank_score')::numeric, (r ->> 'rank_position')::numeric::integer,
           (r ->> 'picked')::boolean, r ->> 'v4_kind', r ->> 'v4_snippet_id',
           r ->> 'v3_kind', r ->> 'v3_snippet_id', (r ->> 'fallback')::boolean,
           r ->> 'fallback_reason', r ->> 'used_kind', r ->> 'used_snippet_id',
           'v4-moment-roles-v1', 0.3, 'sureness-cutoff-v0-placeholder',
           v_frame.acquisition_principal_id
      FROM jsonb_array_elements(p_rows) r;

    -- The ranks are a strict order of the improvable blocks by rank_score.
    IF EXISTS (
        SELECT 1 FROM (
            SELECT rank_position,
                   row_number() OVER (ORDER BY rank_score DESC, block_id COLLATE "C") AS expected
              FROM public.v4_picks
             WHERE take_session_id = p_take_session_id AND policy_version = v_policy
               AND picker_version = v_picker
               AND v4_kind IN ('rewrite', 'exercise') AND rank_score IS NOT NULL
        ) ranked WHERE rank_position IS DISTINCT FROM expected
    ) THEN
        RAISE EXCEPTION 'V4_PICKS_RANK_ORDER';
    END IF;

    v_n := jsonb_array_length(p_rows);
    INSERT INTO public.v4_pick_takes (
        take_session_id, policy_version, picker_version, blocks,
        fallback_blocks, acquisition_principal_id)
    SELECT p_take_session_id, v_policy, v_picker, v_n,
           count(*) FILTER (WHERE fallback), v_frame.acquisition_principal_id
      FROM public.v4_picks
     WHERE take_session_id = p_take_session_id AND policy_version = v_policy
       AND picker_version = v_picker;
    RETURN jsonb_build_object('outcome', 'picked', 'blocks', v_n);
END;
$$;

-- ── The door ───────────────────────────────────────────────────────────────
REVOKE ALL ON TABLE public.v4_picks FROM PUBLIC;
REVOKE ALL ON TABLE public.v4_pick_takes FROM PUBLIC;
REVOKE ALL ON FUNCTION public.record_v4_picks_v1(uuid, jsonb) FROM PUBLIC;
DO $$
DECLARE
    v_role text;
BEGIN
    FOREACH v_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
            EXECUTE format('REVOKE ALL ON TABLE public.v4_picks FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON TABLE public.v4_pick_takes FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON FUNCTION public.record_v4_picks_v1(uuid, jsonb) FROM %I', v_role);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        REVOKE ALL ON TABLE public.v4_picks FROM service_role;
        REVOKE ALL ON TABLE public.v4_pick_takes FROM service_role;
        GRANT SELECT, DELETE ON TABLE public.v4_picks TO service_role;
        GRANT SELECT, DELETE ON TABLE public.v4_pick_takes TO service_role;
        GRANT EXECUTE ON FUNCTION public.record_v4_picks_v1(uuid, jsonb) TO service_role;
    END IF;
END $$;

COMMIT;
