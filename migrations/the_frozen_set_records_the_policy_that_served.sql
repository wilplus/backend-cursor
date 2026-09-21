-- 0347 · The frozen set records whichever policy actually served the Take.
--
-- FOUNDER, 2026-09-21: "we have to make the users act upon it to close the
-- UX loop". Today they cannot. Every Confident Voice answer on a V3-served
-- Take returns "feedback item is not in this Take's frozen set", because the
-- set frozen for that Take is V2's.
--
-- WHAT THIS TABLE IS. `ideal_text_feedback_sets` is the OWNER-ANSWER freeze:
-- the durable record of what this speaker was shown on this Take, so an
-- answer can only ever name something that was actually on screen. It is
-- product state. It is NOT the machine/coach lineage — that lives in
-- `feedback_v3_memberships`, is guarded by
-- `FEEDBACK_V3_SERVICE_SOURCE_NOT_LIVE`, and is untouched here. L3's walls do
-- not move: the owner's answer still lands in `take_feedback_self_report`,
-- separate from machine prediction, blind rating and coach judgement.
--
-- WHY IT HOLDS THE WRONG ANSWER. `_ChangesRun.execute` claims the set at
-- `_claim_or_filter`, and THEN runs `_first_client_feedback`, which replaces
-- the served rows wholesale with V3's. Since the cutover (2026-09-18) the
-- freeze has therefore described a selection the speaker never saw.
--
-- V2's BUDGET WAS WRITTEN INTO FOUR PLACES, and all four had to move or none
-- could: `sanitize_selected_keys` truncates at three, `has_required_families`
-- demands exactly three one-per-family, the table CHECK caps the array at
-- three, and the claim RPC below re-enforces the same rule. Relaxing three of
-- them would have produced a Python layer that believed it had frozen V3's
-- set and a database that had refused it.
--
-- THE NEW RULE, AND WHAT IT DELIBERATELY KEEPS. One requirement survives:
-- the set must contain at least one `confident_voice` item. That is the
-- evaluation this product exists to make, it must never be silently replaced
-- by a third rewrite (the reason the old rule existed), and 24b guarantees
-- V3 produces one per valid block — so it costs V3 nothing and keeps the
-- guarantee V2 had.
--
-- What does NOT survive is "exactly three, one per family". That is V2's
-- versioned budget (24h), and V3's is different by design: one relative-best
-- Confident Voice item per valid 75-word block, plus at most two Praise, one
-- exercise and one rewrite (24f). A fixed three can never describe it.
--
-- The ceiling is integrity, not product budget. The Manager owns the budget
-- (L2); this bound exists so a fault cannot write an unbounded array into a
-- row every reader loads. Sixty-four is far above any real deck's block count
-- and far below anything that would hurt.

BEGIN;

ALTER TABLE public.ideal_text_feedback_sets
    DROP CONSTRAINT IF EXISTS ideal_text_feedback_sets_keys_array;

ALTER TABLE public.ideal_text_feedback_sets
    ADD CONSTRAINT ideal_text_feedback_sets_keys_array CHECK (
        jsonb_typeof(selected_keys) = 'array'
        AND jsonb_array_length(selected_keys) BETWEEN 1 AND 64
        AND selected_keys @> '[{"feedback_family":"confident_voice"}]'::jsonb
    );

-- Reproduced from `add_feedback_manager_and_part_commits.sql` with exactly
-- the budget guard replaced. Every provenance check below is unchanged: the
-- Take must exist, be owned by this user, belong to this arc, be spoken,
-- be unpaired, and its review version must equal its Take index.
CREATE OR REPLACE FUNCTION public.claim_ideal_text_feedback_set_v1(
    p_arc_id TEXT,
    p_owner_user_id UUID,
    p_take_session_id UUID,
    p_take_index INTEGER,
    p_review_version INTEGER,
    p_selected_keys JSONB
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    s public.v2_sessions%ROWTYPE;
    claimed public.ideal_text_feedback_sets%ROWTYPE;
BEGIN
    -- AT LEAST ONE CONFIDENT VOICE ITEM, AND A SANE CEILING.
    --
    -- The old rule was `<> 3` plus one of each family. That is V2's budget,
    -- and V3 — one item per valid 75-word block, plus at most two Praise,
    -- one exercise and one rewrite — cannot satisfy it on any real Take.
    -- Keeping it here while relaxing the Python layer would leave the
    -- database refusing sets the service believed it had frozen.
    --
    -- The Confident Voice requirement stays because it is the claim this
    -- product makes. A set without it is a Take whose evaluation was
    -- silently replaced by something else, which is what this guard has
    -- always been for.
    IF jsonb_typeof(p_selected_keys) <> 'array'
       OR jsonb_array_length(p_selected_keys) < 1
       OR jsonb_array_length(p_selected_keys) > 64
       OR NOT p_selected_keys @> '[{"feedback_family":"confident_voice"}]'::jsonb
    THEN
        RAISE EXCEPTION
            'feedback set requires at least one confident_voice item';
    END IF;
    IF p_review_version IS DISTINCT FROM p_take_index THEN
        RAISE EXCEPTION 'review version must equal Take index';
    END IF;
    SELECT * INTO s FROM public.v2_sessions WHERE id = p_take_session_id;
    IF s.id IS NULL THEN RAISE EXCEPTION 'Take not found'; END IF;
    IF s.user_id IS DISTINCT FROM p_owner_user_id
       OR s.arc_id::text IS DISTINCT FROM p_arc_id
       OR s.take_index IS DISTINCT FROM p_take_index THEN
        RAISE EXCEPTION 'feedback set provenance mismatch';
    END IF;
    IF COALESCE(s.recording_kind, 'spoken') <> 'spoken'
       OR s.paired_session_id IS NOT NULL THEN
        RAISE EXCEPTION 'feedback set requires a spoken Take';
    END IF;
    SELECT * INTO claimed FROM public.ideal_text_feedback_sets
     WHERE arc_id = p_arc_id AND take_session_id = p_take_session_id;
    IF claimed.arc_id IS NULL THEN
        INSERT INTO public.ideal_text_feedback_sets (
            arc_id, take_session_id, take_index, review_version, selected_keys
        ) VALUES (
            p_arc_id, p_take_session_id, p_take_index,
            p_review_version, p_selected_keys
        ) ON CONFLICT DO NOTHING;
        SELECT * INTO claimed FROM public.ideal_text_feedback_sets
         WHERE arc_id = p_arc_id
           AND (take_session_id = p_take_session_id
                OR review_version = p_review_version)
         ORDER BY created_at LIMIT 1;
    END IF;
    IF claimed.arc_id IS NULL THEN
        RAISE EXCEPTION 'feedback set could not be claimed';
    END IF;
    IF claimed.take_session_id IS DISTINCT FROM p_take_session_id
       OR claimed.take_index IS DISTINCT FROM p_take_index
       OR claimed.review_version IS DISTINCT FROM p_review_version THEN
        RAISE EXCEPTION 'feedback set claim conflicts with Take provenance';
    END IF;
    RETURN to_jsonb(claimed);
END;
$$;

-- Supabase grants `anon` and `authenticated` EXECUTE directly through
-- `ALTER DEFAULT PRIVILEGES`, so a REVOKE FROM PUBLIC alone leaves both
-- holding it on a SECURITY DEFINER function that writes another user's
-- feedback membership. Both are named, as the original revision named them.
REVOKE ALL ON FUNCTION public.claim_ideal_text_feedback_set_v1(
    TEXT, UUID, UUID, INTEGER, INTEGER, JSONB
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_ideal_text_feedback_set_v1(
    TEXT, UUID, UUID, INTEGER, INTEGER, JSONB
) TO service_role;

COMMIT;
