-- 0346 · An answer is checked against the freeze that actually served it.
--
-- FOUNDER, 2026-09-20, on a take whose bookmarks had finally appeared, with
-- the Confident Voice question on screen and a red bar under it:
-- "feedback item is not in this Take's frozen set".
--
-- He was answering an item the product had just shown him. The product was
-- right that it was not in the frozen set it looked in, and wrong about which
-- set to look in.
--
-- TWO FREEZES, ONE READER. `_ChangesRun.execute` claims the V2 compatibility
-- set into `ideal_text_feedback_sets` at `_claim_or_filter`, and THEN runs
-- `_first_client_feedback`, which replaces `self.changes` wholesale with V3's
-- rows. Since the founder's V3 cutover (2026-09-18) those rows are what the
-- user sees, and their ids live in `feedback_v3_membership_items` — not in
-- the V2 set, which still holds the three items V2 would have chosen.
-- `record_take_feedback_response_v1` consults only the V2 set, so EVERY
-- answer to a V3-served item returns `not_member`. Not an edge case: the
-- served policy and the answer gate have disagreed about what exists since
-- the day V3 started serving.
--
-- WHY NOT JUST RE-FREEZE V2's SET WITH V3's KEYS. Three reasons, any one
-- sufficient. `claim_feedback_set` is insert-once, so takes already recorded
-- could never be repaired. The claim runs BEFORE V3 selects, so there is
-- nothing to write at the only moment it could be written. And
-- `has_required_families` requires exactly three items, one per family —
-- V3's output (one per 75-word block, plus up to two praise, one exercise and
-- one rewrite, contract 24f) can never satisfy it. The V2 set is superseded
-- history and is correct as it stands (24h); it is simply not the set the
-- user was answering.
--
-- WHY IN THE FUNCTION AND NOT THE ROUTE. The membership check and the insert
-- are one transaction on purpose — 0308's own note says there is deliberately
-- no read/insert fallback "because it would recreate the first-click race
-- this boundary removes". Checking V3 membership in Python and then calling
-- this would put that race straight back.
--
-- WHAT THIS DOES NOT WIDEN.
--
--   · Only `selected` items. An excluded or unselected V3 candidate stays
--     unanswerable, because answering a Candidate the Manager did not
--     approve is exactly what L2 forbids.
--   · V2 is consulted FIRST and its behaviour is byte-for-byte unchanged. A
--     take with a V2 set that contains the item takes the old path and never
--     reaches the new code. This is additive; it cannot regress a V2 take.
--   · The answer still lands in `take_feedback_self_report`, the owner
--     routing table, exactly as before. Nothing is copied between provenance
--     lanes: V3's freeze is READ to establish that the item was served, and
--     the owner's answer is written where owner answers go (L3).
--   · `selected_keys` in the result feeds `input_provenance` on the human-
--     decision stage record. For a V3 member it returns THAT item's frozen
--     key, marked with its source and policy version, rather than V2's
--     unrelated three — a provenance record naming the wrong freeze is worse
--     than none.
--
-- The function is reproduced from 0333 with the membership lookup replaced.

BEGIN;

CREATE OR REPLACE FUNCTION public.record_take_feedback_response_v1(
    p_arc_id TEXT,
    p_take_session_id UUID,
    p_owner_user_id UUID,
    p_feedback_id TEXT,
    p_feedback_family TEXT,
    p_response TEXT,
    p_supplied_snippet_id TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    take_row public.v2_sessions%ROWTYPE;
    frozen_row public.ideal_text_feedback_sets%ROWTYPE;
    selected JSONB;
    member JSONB;
    member_snippet TEXT;
    v3_key TEXT;
    v3_family TEXT;
    v3_snippet TEXT;
    v3_policy TEXT;
    existing public.take_feedback_self_report%ROWTYPE;
    saved public.take_feedback_self_report%ROWTYPE;
BEGIN
    IF COALESCE(btrim(p_feedback_id), '') = ''
       OR p_feedback_family NOT IN (
           'confident_voice', 'rewrite_clarity', 'great_formulation'
       )
       OR NOT (
           (p_feedback_family = 'confident_voice' AND p_response IN (
               'yes', 'in_between', 'no', 'not_sure', 'audio_unclear'
           )) OR
           (p_feedback_family = 'rewrite_clarity' AND p_response IN (
               'apply_suggestion', 'edit_myself', 'keep_wording'
           )) OR
           (p_feedback_family = 'great_formulation' AND p_response IN (
               'useful', 'not_useful', 'not_sure', 'acknowledged'
           ))
       ) THEN
        RAISE EXCEPTION 'invalid typed feedback response';
    END IF;

    SELECT * INTO take_row
      FROM public.v2_sessions
     WHERE id = p_take_session_id
     FOR SHARE;
    IF take_row.id IS NULL
       OR take_row.user_id IS DISTINCT FROM p_owner_user_id
       OR take_row.arc_id::text IS DISTINCT FROM p_arc_id
       OR COALESCE(take_row.recording_kind, 'spoken') <> 'spoken'
       OR take_row.paired_session_id IS NOT NULL THEN
        RAISE EXCEPTION 'Take provenance mismatch';
    END IF;

    -- THE V2 SET FIRST, and unchanged. A take whose item is here behaves
    -- exactly as it did before this migration and never reaches the V3
    -- branch. The only difference from 0333 is that an absent set no longer
    -- returns immediately: a take can legitimately have no V2 set at all
    -- (the claim is refused when `has_required_families` fails) while V3
    -- served it perfectly well from the candidate pool.
    SELECT * INTO frozen_row
      FROM public.ideal_text_feedback_sets
     WHERE arc_id = p_arc_id
       AND take_session_id = p_take_session_id
     FOR SHARE;
    selected := frozen_row.selected_keys;
    IF selected IS NOT NULL THEN
        SELECT item INTO member
          FROM jsonb_array_elements(selected) AS item
         WHERE item->>'id' = p_feedback_id
           AND item->>'feedback_family' = p_feedback_family
         LIMIT 1;
    END IF;

    -- THE V3 FREEZE SECOND. `to_regclass` rather than assuming the table:
    -- migrations degrade gracefully here, and an environment without the V3
    -- serving tables must answer "not a member" rather than raise.
    --
    -- `i.selected` is load-bearing. The items table holds the whole
    -- deliberation — eligible and excluded rows alike — and only the selected
    -- ones were ever shown. Answering an unselected row would be answering a
    -- raw Candidate (L2).
    --
    -- `FOR SHARE` on both rows for the same reason the V2 lookup takes it:
    -- the membership must not move between the check and the insert.
    IF member IS NULL
       AND to_regclass('public.feedback_v3_membership_items') IS NOT NULL THEN
        SELECT i.candidate_key, i.feedback_family, i.snippet_id::text,
               m.policy_version
          INTO v3_key, v3_family, v3_snippet, v3_policy
          FROM public.feedback_v3_membership_items i
          JOIN public.feedback_v3_memberships m ON m.id = i.membership_id
         WHERE m.take_id = p_take_session_id
           AND i.candidate_key = p_feedback_id
           AND i.feedback_family = p_feedback_family
           AND i.selected
         ORDER BY m.frozen_at DESC
         LIMIT 1
           FOR SHARE OF i, m;
        IF v3_key IS NOT NULL THEN
            member := jsonb_build_object(
                'id', v3_key,
                'feedback_family', v3_family,
                'snippet_id', v3_snippet,
                'source', 'feedback_v3_membership',
                'policy_version', v3_policy
            );
            -- The provenance record names the freeze that authorised this
            -- answer. V2's three items did not, and claiming them here would
            -- file the answer under a selection that never showed it.
            selected := jsonb_build_array(member);
        END IF;
    END IF;

    IF member IS NULL THEN
        RETURN jsonb_build_object(
            'outcome', 'not_member', 'selected_keys', selected
        );
    END IF;

    member_snippet := NULLIF(member->>'snippet_id', '');
    IF p_supplied_snippet_id IS NOT NULL
       AND NULLIF(btrim(p_supplied_snippet_id), '')
           IS DISTINCT FROM member_snippet THEN
        RETURN jsonb_build_object(
            'outcome', 'provenance_mismatch', 'selected_keys', selected
        );
    END IF;

    SELECT * INTO existing
      FROM public.take_feedback_self_report
     WHERE take_session_id = p_take_session_id
       AND owner_user_id = p_owner_user_id
       AND feedback_id = p_feedback_id;
    IF existing.id IS NOT NULL THEN
        IF existing.arc_id = p_arc_id
           AND existing.feedback_family = p_feedback_family
           AND existing.response = p_response
           AND existing.snippet_id::text IS NOT DISTINCT FROM member_snippet THEN
            RETURN jsonb_build_object(
                'outcome', 'replayed',
                'row', to_jsonb(existing),
                'selected_keys', selected
            );
        END IF;
        RETURN jsonb_build_object(
            'outcome', 'conflict', 'selected_keys', selected
        );
    END IF;

    INSERT INTO public.take_feedback_self_report (
        arc_id, take_session_id, owner_user_id, feedback_id,
        feedback_family, snippet_id, response
    ) VALUES (
        p_arc_id, p_take_session_id, p_owner_user_id, p_feedback_id,
        p_feedback_family,
        CASE WHEN member_snippet IS NULL THEN NULL ELSE member_snippet::uuid END,
        p_response
    )
    ON CONFLICT (take_session_id, owner_user_id, feedback_id) DO NOTHING
    RETURNING * INTO saved;

    IF saved.id IS NULL THEN
        SELECT * INTO existing
          FROM public.take_feedback_self_report
         WHERE take_session_id = p_take_session_id
           AND owner_user_id = p_owner_user_id
           AND feedback_id = p_feedback_id;
        IF existing.id IS NOT NULL
           AND existing.arc_id = p_arc_id
           AND existing.feedback_family = p_feedback_family
           AND existing.response = p_response
           AND existing.snippet_id::text IS NOT DISTINCT FROM member_snippet THEN
            RETURN jsonb_build_object(
                'outcome', 'replayed',
                'row', to_jsonb(existing),
                'selected_keys', selected
            );
        END IF;
        RETURN jsonb_build_object(
            'outcome', 'conflict', 'selected_keys', selected
        );
    END IF;

    RETURN jsonb_build_object(
        'outcome', 'saved',
        'row', to_jsonb(saved),
        'selected_keys', selected
    );
END;
$$;

-- SUPABASE GRANTS ANON AND AUTHENTICATED DIRECTLY through
-- `ALTER DEFAULT PRIVILEGES`, so a `REVOKE ... FROM PUBLIC` alone leaves both
-- roles holding EXECUTE on a SECURITY DEFINER function. Both are named, as
-- every prior revision of this function has named them.
REVOKE ALL ON FUNCTION public.record_take_feedback_response_v1(
    TEXT, UUID, UUID, TEXT, TEXT, TEXT, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_take_feedback_response_v1(
    TEXT, UUID, UUID, TEXT, TEXT, TEXT, TEXT
) TO service_role;

COMMIT;
