-- 0451 · Each pick learns whether its paragraph rose (V4 Phase 1, B1.5;
-- build plan D-ML-10; ledger B1.5; founder P5, V10b A, V11 B, V12 A).
--
-- WHY. The picker's main teacher is whether the paragraph it picked reads
-- more willfident in the next Take (P5). So for every moment of Take N we
-- store its paragraph's willfidence in Take N and in Take N+1, matched by
-- the paragraph's own identity, and whether it rose.
--
-- THE PARAGRAPH (V10b A: "its place on the slide, with the slide as
-- backup"). When a Take's dark frame is first drawn, the app binds each
-- moment's words to the Ideal Text Paragraph they belong to, by the rule the
-- served path already uses (ideal_text_parts.bind_pieces_to_parts: slide
-- first, span to refine, never a guess), and the database stores it in
-- v4_moment_paragraphs. A Paragraph's id survives rewording (D-ML-2), so the
-- same id in Take N+1 is the same paragraph. A moment whose words straddle
-- two paragraphs, or cannot be proven, has no paragraph.
--
-- THE OUTCOME, per moment of Take N (computed by the database from the 0449
-- reads; only rated moments count):
--   paragraph level  the paragraph's willfidence = the mean of S*W over all
--                    its moments (V12 A), in Take N and in Take N+1;
--   slide level      when the moment has no paragraph, or the paragraph has
--                    no rated moment in either Take: the same over the
--                    moment's slide (the backup, noted as 'slide');
--   not measured     when the slide has no rated moment in either Take (an
--                    unspoken slide keeps its last version, N29).
--   rose             after - before > the margin (V11 B "only a clear
--                    rise"): placeholder 0.05, versioned
--                    'rise-margin-v0-placeholder', set from dark-run data.
-- Every moment gets a row, so any policy's picks can be joined to it; the
-- kinds V3 picked on the moment (rewrite, praise, exercise) are kept beside
-- it from Take N's frame.
--
-- WHAT. Two tables and two writers:
--   v4_moment_paragraphs           one row per moment: its paragraph or none.
--   record_v4_moment_paragraphs_v1 writes a Take's map once; the map must
--                                  name every block of the stored frame,
--                                  each once, with a UUID or null.
--   v4_pick_outcomes               one row per moment of Take N.
--   compute_v4_pick_outcomes_v1    given Take N+1, finds Take N (same
--                                  project and owner, the Take before, a
--                                  spoken Take), and once both Takes have
--                                  their reads, writes Take N's outcomes
--                                  once; else returns why not.
--
-- WHAT DOES NOT CHANGE. Every served path, the frames, the draw and the
-- reads. Called from the queued read job and once per Take on the first
-- draw, never raising into the Take (LIVE LOOP). Internal only (AC-9).
--
-- Idempotent: IF NOT EXISTS, CREATE OR REPLACE; no row written on its own;
-- locks only the new tables. Rollback (forward): drop the two functions and
-- the two tables.

BEGIN;

CREATE TABLE IF NOT EXISTS public.v4_moment_paragraphs (
    take_session_id          uuid        NOT NULL,
    policy_version           text        NOT NULL,
    block_id                 text        NOT NULL,
    slide_index              integer     NULL,
    paragraph_id             uuid        NULL,
    acquisition_principal_id uuid        NOT NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (take_session_id, policy_version, block_id),
    CONSTRAINT v4_moment_paragraphs_frame_fk
        FOREIGN KEY (take_session_id, policy_version)
        REFERENCES public.take_feedback_policy_v3_shadow_frames
            (take_session_id, policy_version)
        ON DELETE CASCADE,
    CONSTRAINT v4_moment_paragraphs_policy CHECK (
        policy_version = 'take-feedback-policy-v3-universal-dark-v3')
);
ALTER TABLE public.v4_moment_paragraphs ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.v4_pick_outcomes (
    take_session_id          uuid        NOT NULL,
    next_take_session_id     uuid        NOT NULL,
    policy_version           text        NOT NULL,
    read_version             text        NOT NULL,
    block_id                 text        NOT NULL,
    slide_index              integer     NULL,
    paragraph_id             uuid        NULL,
    match_level              text        NOT NULL,
    v3_picks                 text[]      NOT NULL,
    willfidence_before       numeric     NULL,
    willfidence_after        numeric     NULL,
    rise                     numeric     NULL,
    margin                   numeric     NOT NULL,
    margin_version           text        NOT NULL,
    outcome                  text        NOT NULL,
    acquisition_principal_id uuid        NOT NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (take_session_id, policy_version, read_version, block_id),
    CONSTRAINT v4_pick_outcomes_frame_fk
        FOREIGN KEY (take_session_id, policy_version)
        REFERENCES public.take_feedback_policy_v3_shadow_frames
            (take_session_id, policy_version)
        ON DELETE CASCADE,
    CONSTRAINT v4_pick_outcomes_versions CHECK (
        policy_version = 'take-feedback-policy-v3-universal-dark-v3'
        AND read_version = 'willfidence-v1-machine'
        AND margin = 0.05 AND margin_version = 'rise-margin-v0-placeholder'),
    CONSTRAINT v4_pick_outcomes_picks CHECK (
        v3_picks <@ ARRAY['rewrite', 'praise', 'exercise']::text[]),
    CONSTRAINT v4_pick_outcomes_level CHECK (
        match_level IN ('paragraph', 'slide', 'not_measured')
        AND (match_level = 'paragraph') <= (paragraph_id IS NOT NULL)),
    CONSTRAINT v4_pick_outcomes_values CHECK (
        (match_level = 'not_measured')
            = (willfidence_before IS NULL OR willfidence_after IS NULL)
        AND (willfidence_before IS NULL OR willfidence_before BETWEEN 0 AND 1)
        AND (willfidence_after IS NULL OR willfidence_after BETWEEN 0 AND 1)
        AND rise IS NOT DISTINCT FROM willfidence_after - willfidence_before),
    CONSTRAINT v4_pick_outcomes_outcome CHECK (
        outcome = CASE
            WHEN rise IS NULL THEN 'not_measured'
            WHEN rise > margin THEN 'rose'
            ELSE 'did_not_rise' END)
);
ALTER TABLE public.v4_pick_outcomes ENABLE ROW LEVEL SECURITY;
CREATE INDEX IF NOT EXISTS v4_pick_outcomes_next_take_idx
    ON public.v4_pick_outcomes (next_take_session_id);

COMMENT ON TABLE public.v4_moment_paragraphs IS
    'V4 B1.5 (0451): the Ideal Text Paragraph each moment of a Take belongs '
    'to (V10b A), or none. Internal (AC-9).';
COMMENT ON TABLE public.v4_pick_outcomes IS
    'V4 B1.5 (0451): per moment of Take N, its paragraph''s (else slide''s) '
    'willfidence in Take N and N+1 and whether it clearly rose (P5, V11 B, '
    'V12 A). Internal (AC-9).';

CREATE OR REPLACE FUNCTION public.record_v4_moment_paragraphs_v1(
    p_take_session_id uuid,
    p_map jsonb
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    v_policy constant text := 'take-feedback-policy-v3-universal-dark-v3';
    v_frame  public.take_feedback_policy_v3_shadow_frames%ROWTYPE;
BEGIN
    IF p_take_session_id IS NULL
       OR jsonb_typeof(p_map) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'V4_MOMENT_PARAGRAPHS_INPUT_INVALID';
    END IF;
    PERFORM pg_advisory_xact_lock(
        hashtext('v4-moment-paragraphs:' || p_take_session_id::text));
    IF EXISTS (SELECT 1 FROM public.v4_moment_paragraphs
                WHERE take_session_id = p_take_session_id
                  AND policy_version = v_policy) THEN
        RETURN jsonb_build_object('outcome', 'stored');
    END IF;
    SELECT * INTO v_frame FROM public.take_feedback_policy_v3_shadow_frames
     WHERE take_session_id = p_take_session_id AND policy_version = v_policy;
    IF v_frame.take_session_id IS NULL THEN
        RETURN jsonb_build_object('outcome', 'no_frame');
    END IF;
    IF jsonb_typeof(v_frame.frame -> 'blocks') IS DISTINCT FROM 'array'
       OR EXISTS (
           SELECT 1 FROM jsonb_array_elements(p_map) m
            WHERE jsonb_typeof(m) IS DISTINCT FROM 'object'
               OR jsonb_typeof(m -> 'block_id') IS DISTINCT FROM 'string'
               OR NOT (jsonb_typeof(m -> 'paragraph_id') IS NULL
                       OR jsonb_typeof(m -> 'paragraph_id') = 'null'
                       OR (jsonb_typeof(m -> 'paragraph_id') = 'string'
                           AND (m ->> 'paragraph_id') ~*
                    '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'))) THEN
        RAISE EXCEPTION 'V4_MOMENT_PARAGRAPHS_INVALID';
    END IF;
    IF EXISTS (
        WITH sides AS (
            SELECT block ->> 'block_id' AS block_id, 1 AS f, 0 AS m
              FROM jsonb_array_elements(v_frame.frame -> 'blocks') block
            UNION ALL
            SELECT m ->> 'block_id', 0, 1 FROM jsonb_array_elements(p_map) m
        )
        SELECT 1 FROM sides GROUP BY block_id HAVING sum(f) <> 1 OR sum(m) <> 1
    ) THEN
        RAISE EXCEPTION 'V4_MOMENT_PARAGRAPHS_DO_NOT_MATCH_THE_FRAME';
    END IF;
    INSERT INTO public.v4_moment_paragraphs (
        take_session_id, policy_version, block_id, slide_index, paragraph_id,
        acquisition_principal_id)
    SELECT p_take_session_id, v_policy, block ->> 'block_id',
           CASE WHEN jsonb_typeof(block -> 'slide_index') = 'number'
                THEN (block ->> 'slide_index')::numeric::integer END,
           NULLIF(m ->> 'paragraph_id', '')::uuid,
           v_frame.acquisition_principal_id
      FROM jsonb_array_elements(v_frame.frame -> 'blocks') block
      JOIN jsonb_array_elements(p_map) m
        ON m ->> 'block_id' = block ->> 'block_id';
    RETURN jsonb_build_object('outcome', 'mapped');
END;
$$;

CREATE OR REPLACE FUNCTION public.compute_v4_pick_outcomes_v1(
    p_next_take_session_id uuid
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    v_policy constant text := 'take-feedback-policy-v3-universal-dark-v3';
    v_read   constant text := 'willfidence-v1-machine';
    v_next   public.v2_sessions%ROWTYPE;
    v_prev   public.v2_sessions%ROWTYPE;
    v_frame  public.take_feedback_policy_v3_shadow_frames%ROWTYPE;
    v_count  integer;
BEGIN
    IF p_next_take_session_id IS NULL THEN
        RAISE EXCEPTION 'V4_PICK_OUTCOMES_INPUT_INVALID';
    END IF;
    SELECT * INTO v_next FROM public.v2_sessions WHERE id = p_next_take_session_id;
    IF v_next.id IS NULL OR v_next.take_index IS NULL OR v_next.take_index < 2 THEN
        RETURN jsonb_build_object('outcome', 'no_previous_take');
    END IF;
    SELECT * INTO v_prev FROM public.v2_sessions
     WHERE arc_id = v_next.arc_id
       AND owner_principal_id IS NOT DISTINCT FROM v_next.owner_principal_id
       AND take_index = v_next.take_index - 1
       AND COALESCE(recording_kind, 'spoken') = 'spoken'
       AND paired_session_id IS NULL
     ORDER BY id LIMIT 1;
    IF v_prev.id IS NULL THEN
        RETURN jsonb_build_object('outcome', 'no_previous_take');
    END IF;
    PERFORM pg_advisory_xact_lock(hashtext('v4-pick-outcomes:' || v_prev.id::text));
    IF EXISTS (SELECT 1 FROM public.v4_pick_outcomes
                WHERE take_session_id = v_prev.id AND policy_version = v_policy
                  AND read_version = v_read) THEN
        RETURN jsonb_build_object('outcome', 'stored');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.v4_willfidence_takes
                    WHERE take_session_id = v_prev.id AND policy_version = v_policy
                      AND read_version = v_read)
       OR NOT EXISTS (SELECT 1 FROM public.v4_willfidence_takes
                       WHERE take_session_id = v_next.id AND policy_version = v_policy
                         AND read_version = v_read) THEN
        RETURN jsonb_build_object('outcome', 'not_ready');
    END IF;
    SELECT * INTO v_frame FROM public.take_feedback_policy_v3_shadow_frames
     WHERE take_session_id = v_prev.id AND policy_version = v_policy;

    INSERT INTO public.v4_pick_outcomes (
        take_session_id, next_take_session_id, policy_version, read_version,
        block_id, slide_index, paragraph_id, match_level, v3_picks,
        willfidence_before, willfidence_after, rise, margin, margin_version,
        outcome, acquisition_principal_id)
    WITH rated AS (
        SELECT r.take_session_id, r.block_id, r.slide_index, mp.paragraph_id,
               r.s * r.w AS sw
          FROM public.v4_willfidence_reads r
          LEFT JOIN public.v4_moment_paragraphs mp
            ON mp.take_session_id = r.take_session_id
           AND mp.policy_version = r.policy_version
           AND mp.block_id = r.block_id
         WHERE r.take_session_id IN (v_prev.id, v_next.id)
           AND r.policy_version = v_policy AND r.read_version = v_read
           AND r.s IS NOT NULL AND r.w IS NOT NULL
    ), moments AS (
        SELECT r.block_id, r.slide_index, mp.paragraph_id
          FROM public.v4_willfidence_reads r
          LEFT JOIN public.v4_moment_paragraphs mp
            ON mp.take_session_id = r.take_session_id
           AND mp.policy_version = r.policy_version
           AND mp.block_id = r.block_id
         WHERE r.take_session_id = v_prev.id
           AND r.policy_version = v_policy AND r.read_version = v_read
    ), measured AS (
        SELECT m.block_id, m.slide_index, m.paragraph_id,
               (SELECT avg(sw) FROM rated WHERE take_session_id = v_prev.id
                   AND paragraph_id = m.paragraph_id) AS p_before,
               (SELECT avg(sw) FROM rated WHERE take_session_id = v_next.id
                   AND paragraph_id = m.paragraph_id) AS p_after,
               (SELECT avg(sw) FROM rated WHERE take_session_id = v_prev.id
                   AND slide_index = m.slide_index) AS s_before,
               (SELECT avg(sw) FROM rated WHERE take_session_id = v_next.id
                   AND slide_index = m.slide_index) AS s_after
          FROM moments m
    ), leveled AS (
        SELECT *,
               CASE WHEN paragraph_id IS NOT NULL AND p_before IS NOT NULL
                         AND p_after IS NOT NULL THEN 'paragraph'
                    WHEN s_before IS NOT NULL AND s_after IS NOT NULL THEN 'slide'
                    ELSE 'not_measured' END AS level
          FROM measured
    ), valued AS (
        SELECT *,
               CASE level WHEN 'paragraph' THEN p_before
                          WHEN 'slide' THEN s_before END AS before,
               CASE level WHEN 'paragraph' THEN p_after
                          WHEN 'slide' THEN s_after END AS after
          FROM leveled
    )
    SELECT v_prev.id, v_next.id, v_policy, v_read, v.block_id, v.slide_index,
           v.paragraph_id, v.level,
           ARRAY(
               SELECT kind FROM (
                   SELECT 'rewrite'::text AS kind
                    WHERE EXISTS (SELECT 1 FROM jsonb_array_elements(COALESCE(
                              v_frame.frame #> '{verbal_lanes,rewrite_clarity,anchors}',
                              '[]'::jsonb)) a WHERE a ->> 'block_id' = v.block_id)
                   UNION ALL
                   SELECT 'praise'
                    WHERE EXISTS (SELECT 1 FROM jsonb_array_elements(COALESCE(
                              v_frame.frame #> '{verbal_lanes,great_formulation,anchors}',
                              '[]'::jsonb)) a WHERE a ->> 'block_id' = v.block_id)
                   UNION ALL
                   SELECT 'exercise'
                    WHERE EXISTS (SELECT 1 FROM jsonb_array_elements(COALESCE(
                              v_frame.frame -> 'blocks', '[]'::jsonb)) b
                                   WHERE b ->> 'block_id' = v.block_id
                                     AND b -> 'carries_exercise' = 'true'::jsonb)
               ) kinds),
           v.before, v.after, v.after - v.before, 0.05,
           'rise-margin-v0-placeholder',
           CASE WHEN v.after - v.before IS NULL THEN 'not_measured'
                WHEN v.after - v.before > 0.05 THEN 'rose'
                ELSE 'did_not_rise' END,
           v_frame.acquisition_principal_id
      FROM valued v;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN jsonb_build_object('outcome', 'computed', 'take_session_id', v_prev.id,
                              'moments', v_count);
END;
$$;

-- ── The door ───────────────────────────────────────────────────────────────
REVOKE ALL ON TABLE public.v4_moment_paragraphs FROM PUBLIC;
REVOKE ALL ON TABLE public.v4_pick_outcomes FROM PUBLIC;
REVOKE ALL ON FUNCTION public.record_v4_moment_paragraphs_v1(uuid, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.compute_v4_pick_outcomes_v1(uuid) FROM PUBLIC;
DO $$
DECLARE
    v_role text;
BEGIN
    FOREACH v_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
            EXECUTE format('REVOKE ALL ON TABLE public.v4_moment_paragraphs FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON TABLE public.v4_pick_outcomes FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON FUNCTION public.record_v4_moment_paragraphs_v1(uuid, jsonb) FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON FUNCTION public.compute_v4_pick_outcomes_v1(uuid) FROM %I', v_role);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        REVOKE ALL ON TABLE public.v4_moment_paragraphs FROM service_role;
        REVOKE ALL ON TABLE public.v4_pick_outcomes FROM service_role;
        GRANT SELECT, DELETE ON TABLE public.v4_moment_paragraphs TO service_role;
        GRANT SELECT, DELETE ON TABLE public.v4_pick_outcomes TO service_role;
        GRANT EXECUTE ON FUNCTION public.record_v4_moment_paragraphs_v1(uuid, jsonb) TO service_role;
        GRANT EXECUTE ON FUNCTION public.compute_v4_pick_outcomes_v1(uuid) TO service_role;
    END IF;
END $$;

COMMIT;
