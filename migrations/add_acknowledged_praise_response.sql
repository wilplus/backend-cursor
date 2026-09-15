-- 0333 · "acknowledged": praise is read, not rated.
--
-- Founder 2026-09-15, rebuilding the bookmark sheet as a one-decision ladder:
-- the praise screen ("Good job") stops asking Useful / Not useful / Not sure
-- and offers one Continue. A black CTA on a question about your own praise
-- does not merely bias the answer — it makes disagreeing feel like refusing.
--
-- But the RATING IS WHAT MARKS THE ITEM DECIDED. Drop the write with the
-- rating and praise is re-offered every time the paragraph is opened, forever.
-- So Continue still writes; it writes an acknowledgement instead of a verdict.
--
-- WHAT THIS DELIBERATELY DOES NOT WIDEN. `acknowledged` is added to the owner
-- self-report only. It is NOT added to `praise_helpfulness`, to
-- `record_feedback_human_decision_v1`, or to the canonical praise lane in
-- 0327 — those hold a HELPFULNESS JUDGEMENT, and "I read this" is not one. A
-- canonical decision is simply never produced, exactly as `edit_myself`
-- already produces none (services/feedback_data_contract._DECISION_MAP has no
-- entry for it, and canonical_feedback_decision returns None). Widening the
-- praise-helpfulness scale to hold a non-rating would corrupt the one table
-- whose values are supposed to mean something on a scale.
--
-- Two gates hold the owner self-report, and both must widen together or the
-- write fails at whichever is stricter: the table CHECK below, and the guard
-- inside record_take_feedback_response_v1. The function is reproduced from
-- 0308 with exactly one line changed.

BEGIN;

ALTER TABLE public.take_feedback_self_report
    DROP CONSTRAINT IF EXISTS take_feedback_self_report_response;

ALTER TABLE public.take_feedback_self_report
    ADD CONSTRAINT take_feedback_self_report_response CHECK (
        (feedback_family = 'confident_voice' AND response IN (
            'yes', 'in_between', 'no', 'not_sure', 'audio_unclear'
        )) OR
        (feedback_family = 'rewrite_clarity' AND response IN (
            'apply_suggestion', 'edit_myself', 'keep_wording'
        )) OR
        (feedback_family = 'great_formulation' AND response IN (
            'useful', 'not_useful', 'not_sure', 'acknowledged'
        ))
    );

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

    SELECT * INTO frozen_row
      FROM public.ideal_text_feedback_sets
     WHERE arc_id = p_arc_id
       AND take_session_id = p_take_session_id
     FOR SHARE;
    IF frozen_row.arc_id IS NULL THEN
        RETURN jsonb_build_object('outcome', 'not_member');
    END IF;
    selected := frozen_row.selected_keys;
    SELECT item INTO member
      FROM jsonb_array_elements(selected) AS item
     WHERE item->>'id' = p_feedback_id
       AND item->>'feedback_family' = p_feedback_family
     LIMIT 1;
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

REVOKE ALL ON FUNCTION public.record_take_feedback_response_v1(
    TEXT, UUID, UUID, TEXT, TEXT, TEXT, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_take_feedback_response_v1(
REVOKE ALL ON FUNCTION public.record_take_feedback_response_v1(
    TEXT, UUID, UUID, TEXT, TEXT, TEXT, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_take_feedback_response_v1(
    TEXT, UUID, UUID, TEXT, TEXT, TEXT, TEXT
) TO service_role;

COMMIT;
