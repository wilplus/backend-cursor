-- 0308 · The frozen-set membership check and immutable owner response are one
-- transaction. This removes the first-click read/write race without relaxing
-- the exact-Take evidence boundary.

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
               'useful', 'not_useful', 'not_sure'
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
    TEXT, UUID, UUID, TEXT, TEXT, TEXT, TEXT
) TO service_role;

COMMIT;
