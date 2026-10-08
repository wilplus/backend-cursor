-- 0457 · The V4 dark writes keep their word (post-merge review of 0451,
-- 0452 and 0453, 2026-10-08; V4 Phase 1, B1.5, B1.6, B1.8, B1.9).
--
-- Three rules the three files' headers state that their SQL did not hold.
-- Each is replaced or added here; 0451, 0452 and 0453 are not edited.
--
-- 1. AN OUTCOME WAITS FOR BOTH TAKES' MAPS (0451; founder P5, V10b A).
--    compute_v4_pick_outcomes_v1 wrote Take N's outcomes once both Takes
--    had their willfidence reads, whether or not either Take had its
--    moment-to-Paragraph map. With no map every moment was stored at the
--    slide level, as if its words had been tried against the Paragraphs and
--    straddled two, and the first write is final. That happens to a Take
--    whose map write failed (a logged side write, never retried) and to a
--    Take read between 0449 and 0451 shipping (2026-10-08, 14:16 to 15:06),
--    which has reads and no map. The slide is the backup for a MOMENT with
--    no Paragraph (V10b A), not for a Take that was never mapped. So the
--    function now returns 'no_map', and writes nothing, unless Take N and
--    Take N+1 each have their map. The map is written once, at the first
--    draw, before the read is queued (services/ideal_text_changes.py), so
--    the served order already meets this; only a missing map is refused.
--    Rows already stored stay: the runner refuses a row-removal statement,
--    and removing them is a separately authorized retention operation.
--
-- 2. A PICK STORES ONLY WHAT THE READ AND THE BLOCK HOLD (0452; P1, V15 A).
--    record_v4_picks_v1 compared a pick's willfident with the block's read
--    as abs(payload - read) >= 1e-9, which is NULL, so it passed, when the
--    read has no willfident; and it checked V4's clip against the block's
--    clips but not V3's, which a fallback stores as the clip used. It now
--    refuses: a block with no read row; a willfident where the read has none
--    (and none where the read has one, as before); a V3 clip that is not one
--    of the block's clips; a rank position that is not a whole number
--    (it was rounded before). Every other check is 0452's, unchanged.
--
-- 3. A SHEET IS ANSWERED ONCE (0453; QG4 B, V18 A, V19 A).
--    The coach sheets' "one answer per row, once" held only in the app (it
--    updates rows whose answered_at is empty). The founder's picks are the
--    golden set and a Yes or No is a preference pair, so the database now
--    refuses any UPDATE of an answered sheet and any UPDATE of a sheet's
--    question (everything but its answer columns). DELETE is untouched: the
--    purge deletes these rows (registry, take and rater keys). Nothing is
--    read or sent to a coach that was not before (BLIND COACH, AC-9).
--
-- WHAT DOES NOT CHANGE. Every served path. These are dark measures: the
-- callers log a refusal and the Take stands (LIVE LOOP). No environment
-- variable is read, so no Railway service needs configuration first.
--
-- NOTHING RUNS FROM THIS FILE. Two function bodies are replaced with the
-- same signatures (their grants stay) and two trigger functions with their
-- triggers are added; no row is read or changed. CREATE TRIGGER takes a
-- brief SHARE ROW EXCLUSIVE lock on the two sheet tables (written only by
-- the dark coach sheets, behind V4_COACH_SHEETS_ENABLED, off).
--
-- ADDITIVE AND IDEMPOTENT. CREATE OR REPLACE FUNCTION; each trigger is
-- dropped and re-created in this transaction, so there is no instant
-- without it. Rollback (forward): re-issue 0451's and 0452's bodies and drop
-- the two triggers.

BEGIN;

-- ── 1. compute_v4_pick_outcomes_v1: 0451's body, plus 'no_map' ───────────
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
    -- 0457: the slide backs up a moment with no Paragraph, never a Take
    -- with no map. Both Takes' maps, or nothing is written.
    IF NOT EXISTS (SELECT 1 FROM public.v4_moment_paragraphs
                    WHERE take_session_id = v_prev.id AND policy_version = v_policy)
       OR NOT EXISTS (SELECT 1 FROM public.v4_moment_paragraphs
                       WHERE take_session_id = v_next.id AND policy_version = v_policy) THEN
        RETURN jsonb_build_object('outcome', 'no_map');
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

-- ── 2. record_v4_picks_v1: 0452's body, its checks closed ────────────────
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
            -- 0457: a rank position is a whole number, never rounded to one.
            --       CASE, so the cast runs only on a number.
            OR (CASE WHEN jsonb_typeof(r -> 'rank_position') = 'number'
                     THEN (r ->> 'rank_position')::numeric
                          <> trunc((r ->> 'rank_position')::numeric)
                     ELSE false END)
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
            -- 0457: every block has its read row.
            OR read.block_id IS NULL
            OR (r ->> 'role') IS DISTINCT FROM read.role
            -- 0457: a number only where the read has one, and the same one.
            OR (CASE WHEN jsonb_typeof(r -> 'willfident') = 'number'
                     THEN read.willfident IS NULL
                          OR abs((r ->> 'willfident')::numeric - read.willfident) >= 1e-9
                     ELSE read.willfident IS NOT NULL END)
            OR (r ->> 'v4_snippet_id' IS NOT NULL AND NOT (
                    COALESCE(block -> 'snippet_ids', '[]'::jsonb) ? (r ->> 'v4_snippet_id')))
            -- 0457: V3's clip, too, is one of the block's clips.
            OR (r ->> 'v3_snippet_id' IS NOT NULL AND NOT (
                    COALESCE(block -> 'snippet_ids', '[]'::jsonb) ? (r ->> 'v3_snippet_id')))
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

-- ── 3. A sheet is answered once ───────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.reject_v4_pick_sheet_rewrite_v1()
RETURNS trigger LANGUAGE plpgsql SET search_path = public
AS $$
BEGIN
    IF OLD.answered_at IS NOT NULL THEN
        RAISE EXCEPTION 'V4_SHEET_ANSWERED_ONCE';
    END IF;
    IF (to_jsonb(OLD) - ARRAY['answer_snippet_id', 'none_needs_it', 'answered_at'])
       IS DISTINCT FROM
       (to_jsonb(NEW) - ARRAY['answer_snippet_id', 'none_needs_it', 'answered_at']) THEN
        RAISE EXCEPTION 'V4_SHEET_QUESTION_IS_FIXED';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.reject_v4_surer_sheet_rewrite_v1()
RETURNS trigger LANGUAGE plpgsql SET search_path = public
AS $$
BEGIN
    IF OLD.answered_at IS NOT NULL THEN
        RAISE EXCEPTION 'V4_SHEET_ANSWERED_ONCE';
    END IF;
    IF (to_jsonb(OLD) - ARRAY['answer', 'chosen_text', 'rejected_text', 'answered_at'])
       IS DISTINCT FROM
       (to_jsonb(NEW) - ARRAY['answer', 'chosen_text', 'rejected_text', 'answered_at']) THEN
        RAISE EXCEPTION 'V4_SHEET_QUESTION_IS_FIXED';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS v4_moment_pick_sheets_answered_once
    ON public.v4_moment_pick_sheets;
CREATE TRIGGER v4_moment_pick_sheets_answered_once
    BEFORE UPDATE ON public.v4_moment_pick_sheets
    FOR EACH ROW EXECUTE FUNCTION public.reject_v4_pick_sheet_rewrite_v1();

DROP TRIGGER IF EXISTS v4_surer_sheets_answered_once
    ON public.v4_surer_sheets;
CREATE TRIGGER v4_surer_sheets_answered_once
    BEFORE UPDATE ON public.v4_surer_sheets
    FOR EACH ROW EXECUTE FUNCTION public.reject_v4_surer_sheet_rewrite_v1();

-- ── The door ───────────────────────────────────────────────────────────────
-- The two replaced functions keep their signatures, so their grants stand
-- (service_role only, 0451/0452); they are re-stated here so this file alone
-- shows the door. The trigger functions need no caller's EXECUTE.
REVOKE ALL ON FUNCTION public.compute_v4_pick_outcomes_v1(uuid)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.record_v4_picks_v1(uuid, jsonb)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.reject_v4_pick_sheet_rewrite_v1()
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.reject_v4_surer_sheet_rewrite_v1()
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.compute_v4_pick_outcomes_v1(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.record_v4_picks_v1(uuid, jsonb) TO service_role;

COMMIT;
