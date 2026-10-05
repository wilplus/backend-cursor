-- 0429. The purge reaches what retention schedule v1.5 decided (founder
-- 2026-10-05, decisions log N50 item 5: P1-P6 A; legal/phase1-2026.1/
-- 22-retention-schedule-v1.5-what-v1.4-left-open-DRAFT.md).
--
-- THE DECISIONS. P1: the nine live records only database functions write
-- (the V3 feedback memberships and the speaker's answers, the learning
-- surfaces, the Ideal Text edit log) are deleted with the account or the
-- project. P6: the learning lineage and the switched-off paths go with the
-- account the same way. P5: in the retired corpora a person's own rows go
-- with the account, table by table. P4: a reference video goes with the
-- account unless it is library content, when only the speaker's link goes.
-- (P2, a free founding pass, and P3, the consent snapshot, need nothing
-- here: the service already reads and deletes those tables.)
--
-- THE PROBLEM. Every table P1 and P6 name is append-only: a guard trigger
-- refuses every DELETE, and the service role holds SELECT at most (0310,
-- 0327, 0389). So the purge could never delete them, and every erasure of
-- someone who had answered a V3 moment stopped for review.
--
-- HOW, WITHOUT OPENING THE TABLES. The pattern of 0424, one step wider:
--   1. phase1_purge_names_row_v1(relation, row) is true only when a purge
--      request is `in_progress` with a sealed inventory, and a `pending`
--      target of it for that relation, frozen by retention schedule v1.5
--      with disposition `delete`, under an ACTIVE rule of category
--      `product_records`, holds the row's own selector value among its
--      frozen locator values (which the freeze checked against the subject
--      graph the server resolves) - AND retention schedule 1.5 is
--      registered in processing_legal_artifacts, which only the founder's
--      signed script writes (scripts/phase1_retention_schedule_v1_5.sql).
--      The service may read those rows but never write them (0310).
--   2. Each guard these tables use gains one branch, added in place before
--      its refusal: a DELETE that function names passes; every other case
--      raises exactly as before, with the message it always had. Nine guard
--      functions: the eight the P1/P6 tables use, and the retired-write
--      guard (P5's reflection clips).
--   3. Three tables had no delete guard at all (an upload recovery, the
--      service allowlist, a rooting-phrase head): they gain one that lets
--      the service role delete only what that function names; the owner's
--      own functions are unchanged.
--   4. The service role gains DELETE on 109 of the 110 tables P1 and P6
--      name, and SELECT on the columns the purge selects them by where it
--      could not read them (the coaching-bundle and service tables 0327 and
--      0326 locked): never on a column that holds what anyone said. The
--      110th, P1's confident_moment_text_update_capabilities, gets nothing:
--      its rows exist only inside the transaction of the function that
--      writes them, which deletes them before it returns.
--   5. check_phase1_purge_delete_v1 (read-only): before anything is frozen,
--      the purge asks of each v1.5 delete whether the service may delete
--      those rows and whether any row it will not delete first still points
--      at them (a kept decision, a kept job, a lineage row no graph
--      reaches). Either one stops the whole erasure for review, instead of
--      failing part-way after the audio is gone.
--   6. The project graph lists the project's V3 memberships
--      (`feedback_v3_membership_ids`) and the project freeze accepts the
--      locator that reaches them: the speaker's answers to V3 moments name
--      only their membership, never the project.
--   7. admin_uploaded_reference_videos.user_id may be empty: P4's library
--      video keeps its row and loses only its link to the speaker.
--
-- Until the founder registers v1.5 no branch opens: every DELETE these
-- tables see still raises exactly as before, and the purge code (services/
-- data_purge.py) acts on nothing v1.5 decided. Running this file touches no
-- row and holds no row removal: the purge deletes through its own reviewed
-- path, at purge time, for a request a person made.
--
-- ADDITIVE AND IDEMPOTENT. Functions are created or patched in place
-- (a patched function carries the marker `/* 0429 v1.5 purge */` and is
-- skipped on a second run; an anchor that is not there exactly once stops
-- the file rather than guess); grants repeat harmlessly; a table, function
-- or role this database lacks is skipped with a NOTICE. Not a D11 writer.

BEGIN;

CREATE OR REPLACE FUNCTION public.phase1_purge_names_row_v1(
    p_relation TEXT,
    p_row JSONB
) RETURNS BOOLEAN
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public
AS $$
    SELECT COALESCE(p_relation <> '' AND p_row IS NOT NULL, false)
       AND EXISTS (
            SELECT 1 FROM public.processing_legal_artifacts artifact
             WHERE artifact.artifact_kind = 'retention_schedule'
               AND artifact.version = '1.5')
       AND EXISTS (
            SELECT 1
              FROM public.data_purge_requests purge
              JOIN public.data_purge_inventory_manifests manifest
                ON manifest.purge_request_id = purge.id
              JOIN public.data_purge_targets target
                ON target.purge_request_id = purge.id
              JOIN public.data_retention_rules rule
                ON rule.id::text = target.metadata ->> 'retention_rule_id'
             WHERE purge.state = 'in_progress'
               AND target.state = 'pending'
               AND target.target_ref =
                   'dependency:' || (target.metadata ->> 'dependency_code')
               AND target.metadata ->> 'relation' = p_relation
               AND target.metadata ->> 'disposition' = 'delete'
               AND target.metadata ->> 'retention_schedule' = '1.5'
               AND rule.active
               AND rule.evidence_category = 'product_records'
               AND jsonb_typeof(target.metadata -> 'locator_values') = 'array'
               AND (target.metadata -> 'locator_values') ?
                   (p_row ->> (target.metadata ->> 'selector_column')))
$$;

REVOKE ALL ON FUNCTION public.phase1_purge_names_row_v1(TEXT, JSONB)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.phase1_purge_names_row_v1(TEXT, JSONB)
    TO service_role;

-- 2. The branch, added in place before each guard's refusal.
DO $$
DECLARE
    patch RECORD;
    function_oid OID;
    definition TEXT;
    found INTEGER;
    branch CONSTANT TEXT := $branch$/* 0429 v1.5 purge */ IF TG_OP = 'DELETE' THEN
        IF public.phase1_purge_names_row_v1(TG_TABLE_NAME, to_jsonb(OLD)) THEN
            RETURN OLD;
        END IF;
    END IF;
    $branch$;
BEGIN
    FOR patch IN SELECT * FROM (VALUES
        ('reject_mlc2_immutable_mutation',
         $a$RAISE EXCEPTION 'MLC canonical records are append-only';$a$),
        ('reject_coach_guidance_d3_mutation_v1',
         $a$RAISE EXCEPTION 'COACH_GUIDANCE_D3_APPEND_ONLY';$a$),
        ('reject_confident_moment_mutation_v1',
         $a$RAISE EXCEPTION 'CONFIDENT_MOMENT_APPEND_ONLY';$a$),
        ('reject_mlc3_general_service_mutation_v1',
         $a$RAISE EXCEPTION 'MLC3_GENERAL_SERVICE_APPEND_ONLY';$a$),
        ('reject_canonical_feedback_mutation',
         $a$RAISE EXCEPTION 'canonical feedback evidence is append-only';$a$),
        ('reject_coach_inline_mutation_v1',
         $a$RAISE EXCEPTION 'COACH_INLINE_EXERCISE_APPEND_ONLY';$a$),
        ('reject_immutable_feedback_mutation',
         $a$RAISE EXCEPTION 'immutable feedback evidence cannot be changed';$a$),
        -- Its first statement refuses every DELETE: the branch goes before it.
        ('guard_exercise_practice_transcription_run_v1',
         $a$IF TG_OP = 'DELETE' OR$a$),
        ('reject_retired_direction_write_v1',
         $a$RAISE EXCEPTION 'RETIRED_DIRECTION_PIPELINE_WRITE_FORBIDDEN';$a$)
    ) AS v(function_name, anchor)
    LOOP
        function_oid := to_regprocedure('public.' || patch.function_name || '()');
        IF function_oid IS NULL THEN
            RAISE NOTICE '0429: public.%() is not present here; skipped',
                patch.function_name;
            CONTINUE;
        END IF;
        definition := pg_get_functiondef(function_oid);
        IF position('/* 0429 v1.5 purge */' IN definition) > 0 THEN
            CONTINUE;
        END IF;
        found := (length(definition)
                  - length(replace(definition, patch.anchor, '')))
                 / length(patch.anchor);
        IF found <> 1 THEN
            RAISE EXCEPTION '0429: public.%() holds its refusal % times, not once; nothing patched',
                patch.function_name, found;
        END IF;
        EXECUTE replace(definition, patch.anchor, branch || patch.anchor);
        IF position('/* 0429 v1.5 purge */' IN pg_get_functiondef(function_oid)) = 0 THEN
            RAISE EXCEPTION '0429: public.%() was not patched', patch.function_name;
        END IF;
    END LOOP;
END;
$$;

-- 3. A guard for the three tables that had none.
CREATE OR REPLACE FUNCTION public.guard_phase1_purge_service_delete_v1()
RETURNS trigger LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
    IF current_user = 'service_role'
       AND NOT public.phase1_purge_names_row_v1(TG_TABLE_NAME, to_jsonb(OLD)) THEN
        RAISE EXCEPTION 'PURGE_DELETE_NOT_NAMED';
    END IF;
    RETURN OLD;
END;
$$;

REVOKE ALL ON FUNCTION public.guard_phase1_purge_service_delete_v1()
    FROM PUBLIC, anon, authenticated;

DO $$
DECLARE
    relation_name TEXT;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'exercise_practice_upload_recoveries',
        'mlc3_service_principal_allowlist',
        'root_phrase_block_heads'
    ] LOOP
        IF to_regclass('public.' || relation_name) IS NULL THEN
            RAISE NOTICE '0429: public.% is not present here; skipped',
                relation_name;
            CONTINUE;
        END IF;
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON public.%I',
                       relation_name || '_purge_delete_guard', relation_name);
        EXECUTE format(
            'CREATE TRIGGER %I BEFORE DELETE ON public.%I FOR EACH ROW '
            'EXECUTE FUNCTION public.guard_phase1_purge_service_delete_v1()',
            relation_name || '_purge_delete_guard', relation_name);
    END LOOP;
END;
$$;

-- 4. DELETE, and SELECT on the selecting columns where it was missing.
DO $$
DECLARE
    item RECORD;
    selector TEXT;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        RAISE NOTICE '0429: no service_role here; no grant made';
        RETURN;
    END IF;
    FOR item IN SELECT * FROM (VALUES
        ('coach_guidance_attachment_versions', ARRAY['acquisition_principal_id']),
        ('coach_guidance_attachments', ARRAY['acquisition_principal_id']),
        ('coach_guidance_independent_media_reviews', ARRAY['acquisition_principal_id', 'reviewer_principal_id']),
        ('coach_guidance_lifecycle_events', ARRAY['acquisition_principal_id']),
        ('coach_guidance_media_bindings', ARRAY['acquisition_principal_id', 'source_acquisition_principal_id']),
        ('coach_guidance_media_validity_events', ARRAY['acquisition_principal_id']),
        ('coach_guidance_publication_invalidations', ARRAY['source_acquisition_principal_id']),
        ('coach_guidance_publications', ARRAY['source_acquisition_principal_id']),
        ('coach_guidance_reveal_accesses', ARRAY['acquisition_principal_id']),
        ('coach_guidance_reveal_grant_judgments', ARRAY['acquisition_principal_id']),
        ('coach_guidance_reveal_grants', ARRAY['acquisition_principal_id']),
        ('coach_guidance_review_batches', ARRAY['acquisition_principal_id']),
        ('coach_guidance_review_frame_items', ARRAY['acquisition_principal_id']),
        ('coach_guidance_review_frames', ARRAY['acquisition_principal_id', 'project_id']),
        ('coach_guidance_upload_events', ARRAY['acquisition_principal_id']),
        ('coach_guidance_upload_permits', ARRAY['acquisition_principal_id']),
        ('coach_guidance_upload_recoveries', ARRAY['acquisition_principal_id']),
        ('coach_inline_context_assessments', ARRAY['acquisition_principal_id', 'reviewer_principal_id']),
        ('coach_inline_exercise_drafts', ARRAY['acquisition_principal_id', 'author_principal_id']),
        ('coach_inline_exercise_eligibility_reviews', ARRAY['acquisition_principal_id']),
        ('coach_inline_source_roles', ARRAY['acquisition_principal_id', 'reviewer_principal_id']),
        ('confident_moment_blind_assignment_bindings', ARRAY['acquisition_principal_id', 'project_id']),
        ('confident_moment_bundle_attachments', ARRAY['acquisition_principal_id', 'project_id']),
        ('confident_moment_bundle_projection_items', ARRAY['acquisition_principal_id']),
        ('confident_moment_bundle_projections', ARRAY['acquisition_principal_id', 'project_id']),
        ('confident_moment_bundle_text_update_bindings', ARRAY['acquisition_principal_id', 'project_id']),
        ('confident_moment_coach_authorability_inventories', ARRAY['acquisition_principal_id', 'project_id']),
        ('confident_moment_coach_authorability_items', ARRAY['acquisition_principal_id']),
        ('confident_moment_coach_wording_authority_bindings', ARRAY['acquisition_principal_id', 'reviewer_principal_id']),
        ('confident_moment_owner_decision_bindings', ARRAY['acquisition_principal_id', 'project_id']),
        ('dataset_exclusions', ARRAY['owner_principal_id']),
        ('dataset_release_items', ARRAY['owner_principal_id']),
        ('dataset_split_assignments', ARRAY['owner_principal_id']),
        ('exercise_assignments', ARRAY['acquisition_principal_id']),
        ('exercise_audio_lineages', ARRAY['id']),
        ('exercise_authoring_drafts', ARRAY['acquisition_principal_id', 'author_principal_id']),
        ('exercise_authorization_checks', ARRAY['acquisition_principal_id']),
        ('exercise_blind_packet_events', ARRAY['blind_packet_id']),
        ('exercise_blind_packets', ARRAY['id']),
        ('exercise_candidate_sets', ARRAY['acquisition_principal_id']),
        ('exercise_candidates', ARRAY['acquisition_principal_id']),
        ('exercise_n1_pattern_candidates', ARRAY['acquisition_principal_id']),
        ('exercise_n1_pattern_snapshots', ARRAY['acquisition_principal_id']),
        ('exercise_n1_source_pattern_results', ARRAY['acquisition_principal_id']),
        ('exercise_pair_assignments', ARRAY['acquisition_principal_id', 'reviewer_principal_id']),
        ('exercise_pair_judgments', ARRAY['acquisition_principal_id', 'reviewer_principal_id']),
        ('exercise_pair_revisions', ARRAY['acquisition_principal_id']),
        ('exercise_practice_attempts', ARRAY['acquisition_principal_id']),
        ('exercise_practice_events', ARRAY['acquisition_principal_id']),
        ('exercise_practice_measurement_revisions', ARRAY['acquisition_principal_id']),
        ('exercise_practice_selection_revisions', ARRAY['acquisition_principal_id']),
        ('exercise_practice_sessions', ARRAY['acquisition_principal_id', 'project_id']),
        ('exercise_practice_transcription_runs', ARRAY['acquisition_principal_id']),
        ('exercise_practice_upload_recoveries', ARRAY['acquisition_principal_id']),
        ('exercise_practice_validity_assessments', ARRAY['acquisition_principal_id']),
        ('exercise_randomization_assignments', ARRAY['acquisition_principal_id']),
        ('exercise_requests', ARRAY['acquisition_principal_id']),
        ('exercise_reviewer_context_events', ARRAY['reviewer_principal_id']),
        ('exercise_selection_feature_snapshots', ARRAY['acquisition_principal_id']),
        ('exercise_service_acquisition_receipts', ARRAY['acquisition_principal_id']),
        ('exercise_service_blind_reveal_accesses', ARRAY['acquisition_principal_id', 'reviewer_principal_id']),
        ('exercise_service_blind_reveal_grants', ARRAY['acquisition_principal_id', 'reviewer_principal_id']),
        ('exercise_service_blind_review_sets', ARRAY['acquisition_principal_id', 'reviewer_principal_id']),
        ('exercise_service_confidence_assignments', ARRAY['acquisition_principal_id', 'project_id', 'reviewer_principal_id']),
        ('exercise_service_confidence_judgments', ARRAY['acquisition_principal_id', 'reviewer_principal_id']),
        ('exercise_service_confidence_render_receipts', ARRAY['acquisition_principal_id', 'reviewer_principal_id']),
        ('exercise_service_offer_candidates', ARRAY['acquisition_principal_id']),
        ('exercise_service_offer_events', ARRAY['acquisition_principal_id']),
        ('exercise_service_offers', ARRAY['acquisition_principal_id', 'project_id']),
        ('exercise_service_requests', ARRAY['acquisition_principal_id']),
        ('feedback_language_revision_deliveries', ARRAY['acquisition_principal_id', 'recipient_principal_id', 'reviewer_principal_id']),
        ('feedback_revisions', ARRAY['acquisition_principal_id', 'rater_id']),
        ('feedback_v3_membership_items', ARRAY['acquisition_principal_id', 'membership_id']),
        ('feedback_v3_memberships', ARRAY['acquisition_principal_id', 'project_id']),
        ('feedback_v3_owner_responses', ARRAY['acquisition_principal_id', 'membership_id']),
        ('feedback_v3_service_render_receipts', ARRAY['acquisition_principal_id', 'membership_id']),
        ('feedback_v3_service_response_bindings', ARRAY['acquisition_principal_id', 'membership_id']),
        ('ideal_text_user_edit_cas_operations', ARRAY['acquisition_principal_id', 'project_id']),
        ('learning_profile_observations', ARRAY['acquisition_principal_id']),
        ('learning_profiles', ARRAY['speaker_id']),
        ('learning_surface_exposure_receipts', ARRAY['owner_principal_id', 'project_id']),
        ('learning_surface_presentations', ARRAY['owner_principal_id', 'project_id']),
        ('ml_candidate_sets', ARRAY['acquisition_principal_id', 'project_id']),
        ('ml_canonical_events', ARRAY['acquisition_principal_id', 'project_id']),
        ('ml_confidence_producer_receipts', ARRAY['acquisition_principal_id', 'take_id']),
        ('ml_evidence_spans', ARRAY['acquisition_principal_id', 'project_id']),
        ('ml_object_artifacts', ARRAY['acquisition_principal_id']),
        ('ml_product_actions', ARRAY['acquisition_principal_id']),
        ('ml_purge_requests', ARRAY['acquisition_principal_id']),
        ('ml_speaker_principals', ARRAY['acquisition_principal_id']),
        ('mlc3_comparison_speaker_eligibility_revisions', ARRAY['acquisition_principal_id']),
        ('mlc3_self_speaker_assertions', ARRAY['acquisition_principal_id']),
        ('mlc3_service_access_events', ARRAY['acquisition_principal_id']),
        ('mlc3_service_cohort_members', ARRAY['acquisition_principal_id']),
        ('mlc3_service_enrollment_revisions', ARRAY['acquisition_principal_id']),
        ('mlc3_service_principal_allowlist', ARRAY['acquisition_principal_id', 'approved_by_principal_id']),
        ('mlc3_speaker_acquisition_revisions', ARRAY['acquisition_principal_id']),
        ('mlc3_target_speaker_bindings', ARRAY['acquisition_principal_id']),
        ('root_phrase_block_heads', ARRAY['acquisition_principal_id', 'project_id']),
        ('root_phrase_content_versions', ARRAY['acquisition_principal_id', 'project_id']),
        ('root_phrase_coverage_frames', ARRAY['acquisition_principal_id', 'project_id']),
        ('root_phrase_coverage_items', ARRAY['acquisition_principal_id']),
        ('root_phrase_owner_alignment_actions', ARRAY['acquisition_principal_id']),
        ('root_phrase_product_actions', ARRAY['acquisition_principal_id', 'project_id']),
        ('root_phrase_qualification_revisions', ARRAY['acquisition_principal_id']),
        ('root_phrase_semantic_input_snapshots', ARRAY['acquisition_principal_id', 'project_id']),
        ('root_phrase_semantic_results', ARRAY['acquisition_principal_id']),
        ('take_feedback_detector_reconciliation', ARRAY['take_session_id']),
        ('take_feedback_policy_v3_shadow_frames', ARRAY['acquisition_principal_id', 'arc_id'])
    ) AS v(relation_name, selectors)
    LOOP
        IF to_regclass('public.' || item.relation_name) IS NULL THEN
            RAISE NOTICE '0429: public.% is not present here; skipped',
                item.relation_name;
            CONTINUE;
        END IF;
        EXECUTE format('GRANT DELETE ON TABLE public.%I TO service_role',
                       item.relation_name);
        FOREACH selector IN ARRAY item.selectors LOOP
            IF EXISTS (
                SELECT 1 FROM information_schema.columns c
                 WHERE c.table_schema = 'public'
                   AND c.table_name = item.relation_name
                   AND c.column_name = selector
            ) THEN
                IF NOT has_column_privilege(
                        'service_role', 'public.' || item.relation_name,
                        selector, 'SELECT') THEN
                    EXECUTE format(
                        'GRANT SELECT (%I) ON TABLE public.%I TO service_role',
                        selector, item.relation_name);
                END IF;
            END IF;
        END LOOP;
    END LOOP;
END;
$$;

-- 5. Read-only: may the service delete these rows, and does any row it will
-- not delete first still point at them? p_plan lists every delete of the
-- inventory with its rank in the order the purge runs them.
CREATE OR REPLACE FUNCTION public.check_phase1_purge_delete_v1(
    p_relation TEXT,
    p_selector_column TEXT,
    p_values TEXT[],
    p_rank INTEGER,
    p_plan JSONB
) RETURNS JSONB
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    parent_oid OID;
    selector_type TEXT;
    reference RECORD;
    join_on TEXT;
    pointing BIGINT;
    blocked JSONB := '{}'::jsonb;
    child_name TEXT;
BEGIN
    SELECT c.oid INTO parent_oid
      FROM pg_catalog.pg_class c
      JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public' AND c.relname = p_relation
       AND c.relkind IN ('r', 'p');
    IF parent_oid IS NULL THEN
        RAISE EXCEPTION 'PURGE_CHECK_RELATION_INVALID';
    END IF;
    SELECT format_type(a.atttypid, a.atttypmod) INTO selector_type
      FROM pg_catalog.pg_attribute a
     WHERE a.attrelid = parent_oid AND a.attname = p_selector_column
       AND a.attnum > 0 AND NOT a.attisdropped;
    IF selector_type IS NULL THEN
        RAISE EXCEPTION 'PURGE_CHECK_SELECTOR_INVALID';
    END IF;
    IF jsonb_typeof(p_plan) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'PURGE_CHECK_PLAN_INVALID';
    END IF;
    IF p_values IS NOT NULL AND cardinality(p_values) > 0 THEN
        FOR reference IN
            SELECT con.conrelid, con.conkey, con.confkey,
                   child_ns.nspname AS child_schema,
                   child.relname AS child_relation
              FROM pg_catalog.pg_constraint con
              JOIN pg_catalog.pg_class child ON child.oid = con.conrelid
              JOIN pg_catalog.pg_namespace child_ns
                ON child_ns.oid = child.relnamespace
             WHERE con.contype = 'f' AND con.confrelid = parent_oid
             ORDER BY child_ns.nspname, child.relname, con.conname
        LOOP
            SELECT string_agg(format('c.%I = p.%I', ca.attname, pa.attname),
                              ' AND ')
              INTO join_on
              FROM unnest(reference.conkey, reference.confkey)
                   AS k(child_column, parent_column)
              JOIN pg_catalog.pg_attribute ca
                ON ca.attrelid = reference.conrelid
               AND ca.attnum = k.child_column
              JOIN pg_catalog.pg_attribute pa
                ON pa.attrelid = parent_oid AND pa.attnum = k.parent_column;
            -- A pointing row is covered when a delete the purge runs before
            -- this one (or this one, for a row of the same table) selects it.
            EXECUTE format(
                'SELECT count(*) FROM %I.%I c JOIN public.%I p ON %s '
                'WHERE p.%I = ANY($1::%s[]) AND NOT EXISTS ('
                ' SELECT 1 FROM jsonb_array_elements($2) e'
                ' WHERE %L = ''public'' AND e ->> ''relation'' = %L'
                ' AND ((e ->> ''rank'')::int < $3'
                '      OR ((e ->> ''rank'')::int = $3 AND %L = %L))'
                ' AND (e -> ''locator_values'') ?'
                '     (to_jsonb(c) ->> (e ->> ''selector_column'')))',
                reference.child_schema, reference.child_relation, p_relation,
                join_on, p_selector_column, selector_type,
                reference.child_schema, reference.child_relation,
                reference.child_relation, p_relation)
              INTO pointing USING p_values, p_plan, p_rank;
            IF pointing > 0 THEN
                child_name := reference.child_schema || '.'
                              || reference.child_relation;
                blocked := blocked || jsonb_build_object(child_name,
                    COALESCE((blocked ->> child_name)::bigint, 0) + pointing);
            END IF;
        END LOOP;
    END IF;
    RETURN jsonb_build_object(
        'can_delete', EXISTS (SELECT 1 FROM pg_catalog.pg_roles
                               WHERE rolname = 'service_role')
            AND has_table_privilege('service_role', parent_oid, 'DELETE')
            AND has_column_privilege('service_role', parent_oid,
                                     p_selector_column, 'SELECT'),
        'blocked_by', blocked);
END;
$$;

REVOKE ALL ON FUNCTION public.check_phase1_purge_delete_v1(
    TEXT, TEXT, TEXT[], INTEGER, JSONB) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.check_phase1_purge_delete_v1(
    TEXT, TEXT, TEXT[], INTEGER, JSONB) TO service_role;

-- 6. The project graph lists the project's V3 memberships; the project
-- freeze accepts the locator that reaches them.
DO $$
DECLARE
    graph_oid OID := to_regprocedure(
        'public.resolve_phase1_purge_project_graph_v1(uuid,uuid)');
    freeze_oid OID := to_regprocedure(
        'public.freeze_phase1_project_purge_inventory_v1('
        'uuid,text,text,jsonb,jsonb,text,text[])');
    definition TEXT;
    graph_anchor CONSTANT TEXT :=
        $a$'delivery_job_ids', to_jsonb(delivery_job_values),$a$;
    graph_addition TEXT;
    freeze_anchor CONSTANT TEXT :=
        $a$WHEN 'delivery_job' THEN 'delivery_job_ids'$a$;
    freeze_addition CONSTANT TEXT := $b$
                /* 0429 v1.5 purge */ WHEN 'feedback_v3_membership'
                    THEN 'feedback_v3_membership_ids'$b$;
BEGIN
    IF graph_oid IS NULL OR freeze_oid IS NULL THEN
        RAISE NOTICE '0429: the project purge is not present here; skipped';
        RETURN;
    END IF;
    IF to_regclass('public.feedback_v3_memberships') IS NULL THEN
        graph_addition := $c$
        /* 0429 v1.5 purge */ 'feedback_v3_membership_ids', '[]'::jsonb,$c$;
    ELSE
        graph_addition := $c$
        /* 0429 v1.5 purge */ 'feedback_v3_membership_ids', COALESCE((
            SELECT jsonb_agg(membership.id::text
                             ORDER BY membership.id::text COLLATE "C")
              FROM public.feedback_v3_memberships membership
             WHERE membership.project_id = p_project_id
               AND membership.acquisition_principal_id =
                   p_acquisition_principal_id), '[]'::jsonb),$c$;
    END IF;
    definition := pg_get_functiondef(graph_oid);
    IF position('/* 0429 v1.5 purge */' IN definition) = 0 THEN
        IF (length(definition) - length(replace(definition, graph_anchor, '')))
           / length(graph_anchor) <> 1 THEN
            RAISE EXCEPTION '0429: the project graph does not end as expected; nothing patched';
        END IF;
        EXECUTE replace(definition, graph_anchor, graph_anchor || graph_addition);
    END IF;
    definition := pg_get_functiondef(freeze_oid);
    IF position('/* 0429 v1.5 purge */' IN definition) = 0 THEN
        IF (length(definition) - length(replace(definition, freeze_anchor, '')))
           / length(freeze_anchor) <> 1 THEN
            RAISE EXCEPTION '0429: the project freeze does not map locators as expected; nothing patched';
        END IF;
        EXECUTE replace(definition, freeze_anchor,
                        freeze_anchor || freeze_addition);
    END IF;
    IF position('/* 0429 v1.5 purge */' IN pg_get_functiondef(graph_oid)) = 0
       OR position('/* 0429 v1.5 purge */' IN pg_get_functiondef(freeze_oid)) = 0 THEN
        RAISE EXCEPTION '0429: the project purge was not patched';
    END IF;
END;
$$;

-- 7. A library video keeps its row and loses only its link to the speaker.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = 'admin_uploaded_reference_videos'
           AND column_name = 'user_id' AND is_nullable = 'NO'
    ) THEN
        ALTER TABLE public.admin_uploaded_reference_videos
            ALTER COLUMN user_id DROP NOT NULL;
    END IF;
END;
$$;

COMMIT;
