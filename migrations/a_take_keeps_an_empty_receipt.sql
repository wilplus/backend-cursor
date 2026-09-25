-- A take keeps an empty receipt (founder decision N12, 2026-09-26: "keep an
-- empty receipt"; decisions log N9 is the same rule for the project row).
--
-- THE PROBLEM. Every real upload writes a permanent record: the recording
-- attempt, the take, its processing transitions, and the canonical transcript,
-- slides, paragraphs, evidence and generated feedback built on it. Those
-- tables refuse UPDATE and DELETE (reject_canonical_feedback_mutation, and
-- protect_recording_attempt_coordinates refuses DELETE), and they point at the
-- take session (v2_sessions) and the project ON DELETE RESTRICT. So the purge
-- could neither remove them nor remove the take session they point at, and no
-- deletion could finish for anyone who had recorded.
--
-- THE RULE (N12). The record stays as identifiers and timestamps. Every word,
-- every piece of generated feedback and every pointer to audio is erased:
--   * text content becomes '[erased]' (several columns must stay non-empty);
--   * JSON content becomes '{}';
--   * the take session keeps only its identity, ownership, index, kind, state
--     and times; every other nullable column becomes NULL. That list is a
--     KEEP-list on purpose: production's v2_sessions has columns no migration
--     in this repository created, and a keep-list erases those too.
-- Labels that are one word from a fixed list (a coach's yes/no, a status) are
-- kept: they are the judgment on record, not something the person said.
--
-- HOW, WITHOUT OPENING THE TABLES. reject_canonical_feedback_mutation already
-- allows one governed UPDATE (an owner claim, proved by an immutable event in
-- transaction-local settings). This adds a second, as narrow:
--   * only inside tombstone_phase1_purge_lineage_v1, which sets
--     willab.purge_wipe_request_id for its own transaction;
--   * only while that purge request is `in_progress` with a frozen inventory;
--   * only the columns this file lists for that table may change, and only to
--     '[erased]', '{}' or NULL. Any other change still raises.
-- Nothing else in the product can set that setting to a running purge's id.
--
-- WHICH ROWS. Exactly the rows of the request's frozen subject graph: owned by
-- a principal in it, or, for a project deletion, in one of its projects and
-- owned by the requester (the rule tombstone_phase1_purge_projects_v1 uses).
-- Rows that hang off those (candidates of a candidate set, labels and
-- revisions of an evidence span) follow their parent.
--
-- The migration runner forbids table-removal and row-removal statements
-- anywhere in a file; this one only UPDATEs, inside the function, at purge
-- time. No row is touched by running this file.
--
-- ADDITIVE AND IDEMPOTENT. CREATE OR REPLACE FUNCTION only; the two trigger
-- functions are re-issued with their existing behaviour kept exactly and one
-- branch added. Neither is a D11 writer.

BEGIN;

-- What may be erased, per table. A column a given database lacks is skipped.
CREATE OR REPLACE FUNCTION public.purge_lineage_erasable_columns_v1(
    p_relation TEXT
) RETURNS TEXT[]
LANGUAGE sql IMMUTABLE SET search_path = public
AS $$
    SELECT CASE p_relation
        WHEN 'transcript_versions' THEN ARRAY['transcript_text']
        WHEN 'slides' THEN ARRAY['title', 'source_payload']
        WHEN 'paragraphs' THEN ARRAY['paragraph_text']
        WHEN 'evidence_spans' THEN ARRAY[
            'exact_text', 'replacement_text', 'audio_ref',
            'technical_metadata', 'target_locator',
            'ideal_text_target_locator_v1']
        WHEN 'acoustic_feature_snapshots' THEN ARRAY['features']
        WHEN 'feedback_candidates' THEN ARRAY['rank_evidence', 'generated_output']
        WHEN 'machine_predictions' THEN ARRAY['complete_output']
        WHEN 'generation_runs' THEN ARRAY['complete_output']
        WHEN 'processing_stage_runs' THEN ARRAY['error']
        WHEN 'processing_transition_events' THEN ARRAY['error']
        WHEN 'feedback_revisions' THEN ARRAY['revision_payload']
        WHEN 'accepted_flagships' THEN ARRAY['exact_text']
        WHEN 'root_phrases' THEN ARRAY['exact_text']
        WHEN 'recording_attempts' THEN ARRAY['last_error']
        ELSE NULL
    END
$$;

-- Is this value already erased? '[erased]', '{}', '[]' or NULL.
CREATE OR REPLACE FUNCTION public.purge_lineage_value_erased_v1(p_value JSONB)
RETURNS BOOLEAN
LANGUAGE sql IMMUTABLE SET search_path = public
AS $$
    SELECT p_value IS NULL OR p_value IN (
        'null'::jsonb, '"[erased]"'::jsonb, '{}'::jsonb, '[]'::jsonb)
$$;

CREATE OR REPLACE FUNCTION public.reject_canonical_feedback_mutation()
RETURNS trigger LANGUAGE plpgsql SET search_path = public AS $$
DECLARE
    event_id TEXT := current_setting('willab.owner_claim_event_id', true);
    source_id TEXT := current_setting('willab.owner_claim_source', true);
    target_id TEXT := current_setting('willab.owner_claim_target', true);
    wipe_request TEXT := current_setting('willab.purge_wipe_request_id', true);
    erasable TEXT[];
    old_row JSONB;
    new_row JSONB;
BEGIN
    IF TG_OP = 'UPDATE' AND NULLIF(event_id, '') IS NOT NULL THEN
        old_row := to_jsonb(OLD);
        new_row := to_jsonb(NEW);
        IF old_row ? 'owner_principal_id'
           AND new_row ? 'owner_principal_id'
           AND old_row ->> 'owner_principal_id' = source_id
           AND new_row ->> 'owner_principal_id' = target_id
           AND (old_row - 'owner_principal_id') =
               (new_row - 'owner_principal_id')
           AND EXISTS (
               SELECT 1 FROM public.owner_claim_events event
                WHERE event.id::text = event_id
                  AND event.source_owner_principal_id::text = source_id
                  AND event.target_owner_principal_id::text = target_id
           ) THEN
            RETURN NEW;
        END IF;
    END IF;
    -- N12: a running, frozen purge may erase the listed content columns, and
    -- nothing else, to an erased value.
    IF TG_OP = 'UPDATE' AND NULLIF(wipe_request, '') IS NOT NULL THEN
        erasable := public.purge_lineage_erasable_columns_v1(TG_TABLE_NAME);
        old_row := to_jsonb(OLD);
        new_row := to_jsonb(NEW);
        IF erasable IS NOT NULL
           AND (old_row - erasable) = (new_row - erasable)
           AND NOT EXISTS (
               SELECT 1 FROM unnest(erasable) AS c(name)
                WHERE new_row -> c.name IS DISTINCT FROM old_row -> c.name
                  AND NOT public.purge_lineage_value_erased_v1(new_row -> c.name)
           )
           AND EXISTS (
               SELECT 1 FROM public.data_purge_requests purge
                JOIN public.data_purge_inventory_manifests manifest
                  ON manifest.purge_request_id = purge.id
               WHERE purge.id::text = wipe_request
                 AND purge.state = 'in_progress'
           ) THEN
            RETURN NEW;
        END IF;
    END IF;
    RAISE EXCEPTION 'canonical feedback evidence is append-only';
END;
$$;

CREATE OR REPLACE FUNCTION public.tombstone_phase1_purge_lineage_v1(
    p_purge_request_id UUID
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    req public.data_purge_requests;
    manifest public.data_purge_inventory_manifests;
    principal_values TEXT[];
    project_values TEXT[];
    scope TEXT;
    rel TEXT;
    parent TEXT;
    link TEXT;
    cols TEXT[];
    set_list TEXT;
    dirty TEXT;
    touched INTEGER;
    wiped INTEGER := 0;
    remaining INTEGER;
    not_blank INTEGER := 0;
    keep CONSTANT TEXT[] := ARRAY[
        'id', 'arc_id', 'owner_principal_id', 'user_id', 'project_id',
        'take_index', 'canonical_take_index', 'recording_kind',
        'analysis_state', 'paired_session_id', 'created_at', 'updated_at',
        'completed_at'];
BEGIN
    SELECT * INTO req FROM public.data_purge_requests
     WHERE id = p_purge_request_id FOR UPDATE;
    IF req.id IS NULL THEN RAISE EXCEPTION 'PURGE_REQUEST_NOT_FOUND'; END IF;
    IF req.state <> 'in_progress' THEN
        RAISE EXCEPTION 'PURGE_TOMBSTONE_REQUEST_NOT_IN_PROGRESS';
    END IF;
    SELECT * INTO manifest FROM public.data_purge_inventory_manifests
     WHERE purge_request_id = req.id;
    IF manifest.id IS NULL THEN RAISE EXCEPTION 'PURGE_INVENTORY_NOT_SEALED'; END IF;

    SELECT ARRAY(SELECT jsonb_array_elements_text(
                   COALESCE(manifest.subject_graph->'principal_ids', '[]'::jsonb)))
      INTO principal_values;
    SELECT ARRAY(SELECT jsonb_array_elements_text(
                   COALESCE(manifest.subject_graph->'project_ids', '[]'::jsonb)))
      INTO project_values;

    -- The frozen scope, as tombstone_phase1_purge_projects_v1 draws it.
    scope := format(
        '(t.owner_principal_id::text = ANY(%L::text[]) OR '
        '(t.project_id::text = ANY(%L::text[]) AND t.owner_principal_id = %L::uuid))',
        principal_values, project_values, req.acquisition_principal_id);

    PERFORM set_config('willab.purge_wipe_request_id', req.id::text, true);

    -- Owned tables first, then the rows that hang off a parent.
    FOR rel, parent, link IN
        SELECT * FROM (VALUES
            ('transcript_versions', NULL, NULL),
            ('slides', NULL, NULL),
            ('paragraphs', NULL, NULL),
            ('evidence_spans', NULL, NULL),
            ('acoustic_feature_snapshots', NULL, NULL),
            ('machine_predictions', NULL, NULL),
            ('generation_runs', NULL, NULL),
            ('processing_stage_runs', NULL, NULL),
            ('processing_transition_events', NULL, NULL),
            ('recording_attempts', NULL, NULL),
            ('feedback_candidates', 'candidate_sets', 'candidate_set_id'),
            ('feedback_revisions', 'evidence_spans', 'evidence_span_id'),
            ('accepted_flagships', 'evidence_spans', 'evidence_span_id'),
            ('root_phrases', 'paragraphs', 'paragraph_id')
        ) AS plan(plan_relation, plan_parent, plan_link)
    LOOP
        IF to_regclass('public.' || rel) IS NULL
           OR (parent IS NOT NULL AND to_regclass('public.' || parent) IS NULL) THEN
            CONTINUE;
        END IF;
        cols := ARRAY(
            SELECT c.column_name FROM information_schema.columns c
             WHERE c.table_schema = 'public' AND c.table_name = rel
               AND c.column_name = ANY(public.purge_lineage_erasable_columns_v1(rel))
             ORDER BY c.column_name);
        IF cardinality(cols) = 0 THEN CONTINUE; END IF;
        -- A parent must carry the scope columns; a child without its link
        -- column in this database cannot be reached and is skipped.
        IF parent IS NULL AND NOT EXISTS (
               SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = rel
                  AND column_name = 'project_id') THEN
            CONTINUE;
        END IF;
        IF parent IS NOT NULL AND (NOT EXISTS (
               SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = rel
                  AND column_name = link) OR NOT EXISTS (
               SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = parent
                  AND column_name = 'project_id')) THEN
            CONTINUE;
        END IF;
        SELECT string_agg(format(
                   '%1$I = CASE WHEN t.%1$I IS NULL THEN NULL ELSE %2$s END',
                   c.column_name,
                   CASE WHEN c.data_type IN ('json', 'jsonb')
                        THEN '''{}''::jsonb' ELSE '''[erased]''' END), ', '),
               string_agg(format(
                   'NOT public.purge_lineage_value_erased_v1(to_jsonb(t.%I))',
                   c.column_name), ' OR ')
          INTO set_list, dirty
          FROM information_schema.columns c
         WHERE c.table_schema = 'public' AND c.table_name = rel
           AND c.column_name = ANY(cols);
        IF parent IS NULL THEN
            EXECUTE format('UPDATE public.%I t SET %s WHERE %s AND (%s)',
                           rel, set_list, scope, dirty);
            GET DIAGNOSTICS touched = ROW_COUNT;
            EXECUTE format('SELECT count(*) FROM public.%I t WHERE %s AND (%s)',
                           rel, scope, dirty) INTO remaining;
        ELSE
            EXECUTE format(
                'UPDATE public.%I c SET %s FROM public.%I t '
                'WHERE c.%I = t.id AND %s AND (%s)',
                rel, replace(set_list, 't.', 'c.'), parent, link, scope,
                replace(dirty, 't.', 'c.'));
            GET DIAGNOSTICS touched = ROW_COUNT;
            EXECUTE format(
                'SELECT count(*) FROM public.%I c JOIN public.%I t ON c.%I = t.id '
                'WHERE %s AND (%s)',
                rel, parent, link, scope, replace(dirty, 't.', 'c.'))
              INTO remaining;
        END IF;
        wiped := wiped + touched;
        not_blank := not_blank + remaining;
    END LOOP;

    -- The take session: identity, ownership, index, kind, state and times
    -- stay; every other nullable column is emptied.
    IF to_regclass('public.v2_sessions') IS NOT NULL THEN
        SELECT string_agg(format('%I = NULL', c.column_name), ', '),
               string_agg(format('t.%I IS NOT NULL', c.column_name), ' OR ')
          INTO set_list, dirty
          FROM information_schema.columns c
         WHERE c.table_schema = 'public' AND c.table_name = 'v2_sessions'
           AND c.is_nullable = 'YES'
           AND NOT (c.column_name = ANY(keep));
        IF set_list IS NOT NULL THEN
            EXECUTE format('UPDATE public.v2_sessions t SET %s WHERE %s AND (%s)',
                           set_list, scope, dirty);
            GET DIAGNOSTICS touched = ROW_COUNT;
            wiped := wiped + touched;
            EXECUTE format('SELECT count(*) FROM public.v2_sessions t WHERE %s AND (%s)',
                           scope, dirty) INTO remaining;
            not_blank := not_blank + remaining;
        END IF;
    END IF;

    PERFORM set_config('willab.purge_wipe_request_id', '', true);
    RETURN jsonb_build_object('tombstoned', wiped, 'not_blank', not_blank);
END;
$$;

REVOKE ALL ON FUNCTION public.tombstone_phase1_purge_lineage_v1(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.tombstone_phase1_purge_lineage_v1(UUID)
    TO service_role;
REVOKE ALL ON FUNCTION public.purge_lineage_erasable_columns_v1(TEXT)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.purge_lineage_value_erased_v1(JSONB)
    FROM PUBLIC, anon, authenticated;

COMMIT;
