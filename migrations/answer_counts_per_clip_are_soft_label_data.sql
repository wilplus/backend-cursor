-- 0442 · answer counts per clip are soft-label data; the quorum stays
-- humans only (V4 brief 1.7, founder-signed 2026-10-05/06; decision rows
-- Q1, Q2, Q3; V17 A: In-between counts half; build plan D-ML-11).
--
-- WHY. V4 Phase 1 measures before it serves. Its recognizer will one day
-- learn from SOFT labels: "a clip is labelled with the share who said Yes"
-- (Q2), with Yes = 1, In-between = 1/2, No = 0 (Q1, V17 A). Today the only
-- record of blind human answers is the label ledger (confidence_labels),
-- which is read by the quorum (services/label_quorum.py) and nothing else
-- counts there: two matching human answers settle a clip, the machine holds
-- MACHINE_VOTES = 0 and the human-only lanes are 'coach' and 'game_peer'
-- (Q3). 1.7 asks for the counts to be kept APART from that ledger, so that
-- a soft label never becomes a quorum vote and a quorum rule never reshapes
-- a soft label. Nothing trains on these counts: the training door (P-b) is
-- parked until the founder opens it (M10).
--
-- WHAT. One derived table and one writer:
--
--   clip_answer_counts            one row per clip: how many blind human
--                                 raters said Yes, In-between, No and Not
--                                 sure, how many perceptual answers that is,
--                                 and the soft label (Yes + In-between/2)
--                                 over the perceptual answers, NULL while
--                                 nobody has answered. Rule version
--                                 'soft-label-v1'. Derived: it is rebuilt
--                                 from the ledger, never edited by hand.
--   refresh_clip_answer_counts_v1 recomputes one clip's row from
--                                 confidence_labels, counting ONLY rows that
--                                 the quorum would count as a human vote:
--                                 state 'confidence', lane 'coach' or
--                                 'game_peer', not a self-report, not an
--                                 Audio-unclear abstention, blind (0411),
--                                 with a rater. Historical 'neutral' counts
--                                 as Not sure. One refresh per clip at a
--                                 time (a transaction advisory lock).
--                                 Returns the row.
--
-- WHAT IS NEVER COUNTED (L3; V4 brief M8 "Speaker taps are never labels").
-- The speaker's own answers live in take_feedback_self_report and the
-- owner routes, never in this ledger; a rating the speaker gives on their
-- own clip through a rating surface carries lane 'game_owner' or
-- self_report = true and is excluded twice over. The machine's read is
-- machine_value, a column beside the answer, and is never read here: the
-- machine has no lane, so it has no count. Not sure is kept as a count of
-- its own and takes no share of the soft label (rater uncertainty is not an
-- answer about the clip: label_quorum IDK_VALUES).
--
-- WHAT DOES NOT CHANGE. confidence_labels is not altered; no trigger is
-- added to it (a busy production table takes no lock here). label_quorum
-- reads nothing from the new table. No user payload carries a count or the
-- soft label (AC-9): the app writes the row after a blind rating lands and
-- reads it only inside the machine (dark V4). The refresh is a side write
-- that never blocks the rating it follows (LIVE LOOP).
--
-- Idempotent: IF NOT EXISTS, CREATE OR REPLACE; applied twice it changes
-- nothing. Writes no row on its own. Locks: only the new table (and, at run
-- time, a per-clip transaction advisory lock inside the function).
--
-- Rollback (a new forward migration): DROP FUNCTION
-- public.refresh_clip_answer_counts_v1(uuid); DROP TABLE
-- public.clip_answer_counts. Nothing else depends on either; the ledger is
-- untouched, so the counts can be rebuilt at any time.

BEGIN;

CREATE TABLE IF NOT EXISTS public.clip_answer_counts (
    snippet_id        uuid        PRIMARY KEY,
    yes_count         integer     NOT NULL DEFAULT 0,
    in_between_count  integer     NOT NULL DEFAULT 0,
    no_count          integer     NOT NULL DEFAULT 0,
    not_sure_count    integer     NOT NULL DEFAULT 0,
    perceptual_count  integer     NOT NULL DEFAULT 0,
    soft_label        numeric(6,5) NULL,
    lanes_counted     text[]      NOT NULL DEFAULT ARRAY['coach', 'game_peer'],
    rule_version      text        NOT NULL DEFAULT 'soft-label-v1',
    refreshed_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT clip_answer_counts_non_negative CHECK (
        yes_count >= 0 AND in_between_count >= 0 AND no_count >= 0
        AND not_sure_count >= 0 AND perceptual_count >= 0),
    CONSTRAINT clip_answer_counts_perceptual_sum CHECK (
        perceptual_count = yes_count + in_between_count + no_count),
    CONSTRAINT clip_answer_counts_soft_label_range CHECK (
        soft_label IS NULL OR (soft_label >= 0 AND soft_label <= 1)),
    CONSTRAINT clip_answer_counts_soft_label_needs_answers CHECK (
        (perceptual_count = 0) = (soft_label IS NULL))
);

ALTER TABLE public.clip_answer_counts ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.clip_answer_counts IS
    'Soft-label data per clip (V4 brief 1.7; 0442): how many blind human '
    'raters said Yes, In-between, No, Not sure, and the share who said Yes '
    'with In-between counting half (Q1, V17 A). Rebuilt from '
    'confidence_labels by refresh_clip_answer_counts_v1; counts only the '
    'lanes the quorum counts (coach, game_peer), never a self-report, never '
    'the machine, never the speaker (L3). Kept apart from the label ledger, '
    'which keeps its humans-only quorum (Q3). Never in a user payload (AC-9).';

CREATE OR REPLACE FUNCTION public.refresh_clip_answer_counts_v1(
    p_snippet_id uuid
) RETURNS public.clip_answer_counts
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    v_yes        integer := 0;
    v_in_between integer := 0;
    v_no         integer := 0;
    v_not_sure   integer := 0;
    v_perceptual integer := 0;
    v_soft       numeric(6,5) := NULL;
    v_row        public.clip_answer_counts;
BEGIN
    IF p_snippet_id IS NULL THEN
        RAISE EXCEPTION 'CLIP_ANSWER_COUNTS_INPUT_INVALID';
    END IF;

    -- One refresh per clip at a time: two ratings landing together each
    -- recount after the other has committed, so a slower recount can never
    -- overwrite a newer one with an older snapshot. Held to the end of the
    -- caller's transaction; other clips are not touched.
    -- This holds under READ COMMITTED, the isolation every caller uses (the
    -- app reaches this function only through a PostgREST rpc, one statement
    -- per transaction): the recount's snapshot is taken after the wait.
    PERFORM pg_advisory_xact_lock(hashtext(p_snippet_id::text));

    -- Exactly the rows the quorum would count as a human vote (Q3;
    -- services/label_quorum.py QUORUM_LANES, is_self_report,
    -- is_audio_unclear, and the blind rule of 0411: a rating made after the
    -- rater saw the clip's non-blind side is not a label). One row per
    -- rater is the ledger's own key. Historical v1 'neutral' is the old
    -- spelling of Not sure (label_quorum IDK_VALUES) and is counted with it.
    SELECT count(*) FILTER (WHERE value = 'yes'),
           count(*) FILTER (WHERE value = 'in_between'),
           count(*) FILTER (WHERE value = 'no'),
           count(*) FILTER (WHERE value IN ('not_sure', 'neutral'))
      INTO v_yes, v_in_between, v_no, v_not_sure
      FROM public.confidence_labels label
     WHERE label.snippet_id = p_snippet_id
       AND COALESCE(label.state_id, 'confidence') = 'confidence'
       AND label.lane IN ('coach', 'game_peer')
       AND COALESCE(label.self_report, false) = false
       AND COALESCE(label.unrateable, false) = false
       AND label.blind IS NOT FALSE
       AND label.rater_id IS NOT NULL;

    v_perceptual := v_yes + v_in_between + v_no;
    IF v_perceptual > 0 THEN
        -- Q1: Yes 1, In-between 1/2, No 0, averaged over the perceptual
        -- answers. Not sure is rater uncertainty and takes no share.
        v_soft := round((v_yes + v_in_between / 2.0) / v_perceptual, 5);
    END IF;

    INSERT INTO public.clip_answer_counts AS counts (
        snippet_id, yes_count, in_between_count, no_count, not_sure_count,
        perceptual_count, soft_label, lanes_counted, rule_version, refreshed_at
    ) VALUES (
        p_snippet_id, v_yes, v_in_between, v_no, v_not_sure,
        v_perceptual, v_soft, ARRAY['coach', 'game_peer'], 'soft-label-v1', now()
    )
    ON CONFLICT (snippet_id) DO UPDATE
       SET yes_count        = EXCLUDED.yes_count,
           in_between_count = EXCLUDED.in_between_count,
           no_count         = EXCLUDED.no_count,
           not_sure_count   = EXCLUDED.not_sure_count,
           perceptual_count = EXCLUDED.perceptual_count,
           soft_label       = EXCLUDED.soft_label,
           lanes_counted    = EXCLUDED.lanes_counted,
           rule_version     = EXCLUDED.rule_version,
           refreshed_at     = now()
    RETURNING * INTO v_row;
    RETURN v_row;
END;
$$;

COMMENT ON FUNCTION public.refresh_clip_answer_counts_v1(uuid) IS
    'Rebuild one clip''s soft-label counts from confidence_labels (0442, V4 '
    'brief 1.7): coach and game_peer lanes, blind rows only, no self-report, '
    'no abstention, no machine; historical neutral counts as Not sure. One '
    'refresh per clip at a time. Returns the row. service_role only.';

-- ── The door ───────────────────────────────────────────────────────────────
-- Browser roles get nothing on the table or the function, whatever default
-- privileges the schema carries (Supabase grants anon/authenticated on
-- public by default; RLS with no policy already returns no row, and this
-- makes the boundary explicit). The app reads the table and calls the
-- function with the service key, and the purge deletes a clip's row with
-- the clip; the table is written only through the function. Roles are
-- guarded: they exist on Supabase, not on a bare Postgres.
REVOKE ALL ON TABLE public.clip_answer_counts FROM PUBLIC;
REVOKE ALL ON FUNCTION public.refresh_clip_answer_counts_v1(uuid) FROM PUBLIC;
DO $$
DECLARE
    v_role text;
BEGIN
    FOREACH v_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
            EXECUTE format('REVOKE ALL ON TABLE public.clip_answer_counts FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON FUNCTION public.refresh_clip_answer_counts_v1(uuid) FROM %I', v_role);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        REVOKE ALL ON TABLE public.clip_answer_counts FROM service_role;
        GRANT SELECT, DELETE ON TABLE public.clip_answer_counts TO service_role;
        GRANT EXECUTE ON FUNCTION public.refresh_clip_answer_counts_v1(uuid) TO service_role;
    END IF;
END $$;

COMMIT;
