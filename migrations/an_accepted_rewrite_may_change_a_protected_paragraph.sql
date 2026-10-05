-- 0418 · An accepted rewrite may change a protected Paragraph (founder
--        2026-10-05: "it is possible that helper words are attached to the
--        words that are not visible - but exist only in the history; that
--        should be the logic of it"; "build it now as its own PR").
--
-- compare_and_set_user_ideal_edit_v1 (0327) refuses any change to a
-- Paragraph that is locked or carries helper words
-- (IDEAL_TEXT_PART_REQUIRES_UNLOCK), so accepting a rewrite there changed
-- nothing. The founder's rule: the accepted words go in, the Paragraph stays
-- locked, and its helper words stay too -- pointing at the version they were
-- picked from, which stays in the Paragraph's History. The backend moves the
-- words to the Slide row (where words from an earlier Take already live) and
-- clears the in-text span before it writes.
--
-- WHAT CHANGES, AND ONLY THAT. One line of the owner-edit function: a
-- protected Paragraph may change its TEXT -- never its position, never be
-- removed -- when, and only when, it is the one Paragraph named by
-- accept_rewrite_into_part_v1 for this transaction. Every other caller, and
-- every other Paragraph in the same call, is refused exactly as before.
--
-- The line is patched in place from the installed definition, not copied:
-- the function is 300 lines and copying it would fork it. The patch refuses
-- loudly if the line is not found exactly once, and is a no-op when already
-- applied. Grants are kept by CREATE OR REPLACE.
--
-- Changes no rows. Idempotent.

BEGIN;

DO $accept_into_protected$
DECLARE
    target regprocedure :=
        'public.compare_and_set_user_ideal_edit_v1(uuid,text,integer,bigint,text,text,jsonb,text)'::regprocedure;
    definition text;
    patched text;
    marker constant text := '/* 0418 accepted rewrite */';
    refusal constant text :=
        'ELSIF change.is_protected THEN RAISE EXCEPTION ''IDEAL_TEXT_PART_REQUIRES_UNLOCK''; END IF;';
    allowed constant text :=
        'ELSIF change.is_protected AND NOT ' || '/* 0418 accepted rewrite */' || ' ('
        || 'change.old_pos IS NOT NULL AND change.new_pos IS NOT NULL '
        || 'AND change.old_pos=change.new_pos '
        || 'AND change.part_id=NULLIF(current_setting(''willab.accepted_rewrite_part'',true),'''')::uuid'
        || ') THEN RAISE EXCEPTION ''IDEAL_TEXT_PART_REQUIRES_UNLOCK''; END IF;';
BEGIN
    definition := pg_get_functiondef(target);
    IF position(marker IN definition) > 0 THEN
        RETURN;  -- applied by an earlier run
    END IF;
    IF (length(definition) - length(replace(definition, refusal, '')))
       / length(refusal) <> 1 THEN
        RAISE EXCEPTION 'ACCEPTED_REWRITE_GUARD_LINE_NOT_UNIQUE';
    END IF;
    patched := replace(definition, refusal, allowed);
    EXECUTE patched;
    IF position(marker IN pg_get_functiondef(target)) = 0 THEN
        RAISE EXCEPTION 'ACCEPTED_REWRITE_GUARD_EDIT_DID_NOT_LAND';
    END IF;
END
$accept_into_protected$;

-- The one door. It names the Paragraph for this transaction only, calls the
-- unchanged writer (same checks, same revision rows, same capability), and
-- clears the name again before returning.
CREATE OR REPLACE FUNCTION public.accept_rewrite_into_part_v1(
    p_owner_user_id uuid,
    p_arc_id text,
    p_source_document_version integer,
    p_part_id uuid,
    p_desired_user_text text,
    p_desired_parts_lineage jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE result jsonb;
BEGIN
    IF p_part_id IS NULL OR NOT EXISTS(
        SELECT 1 FROM public.ideal_text_part p
         WHERE p.id=p_part_id AND p.arc_id=p_arc_id
           AND p.user_id=p_owner_user_id::text) THEN
        RAISE EXCEPTION 'IDEAL_TEXT_PARTS_REFRESH_REQUIRED';
    END IF;
    PERFORM set_config('willab.accepted_rewrite_part', p_part_id::text, true);
    result := public.compare_and_set_user_ideal_edit_v1(
        p_owner_user_id, p_arc_id, p_source_document_version, NULL, NULL,
        p_desired_user_text, p_desired_parts_lineage, NULL);
    PERFORM set_config('willab.accepted_rewrite_part', '', true);
    RETURN result;
END
$$;

REVOKE ALL ON FUNCTION public.accept_rewrite_into_part_v1(uuid,text,integer,uuid,text,jsonb)
    FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.accept_rewrite_into_part_v1(uuid,text,integer,uuid,text,jsonb)
    TO service_role;

COMMIT;
