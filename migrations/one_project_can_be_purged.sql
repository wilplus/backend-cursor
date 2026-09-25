-- One project can be purged (P1-B; SPEC-training-corpus §6.1, §6.4; decisions
-- log N8, N12; founder 2026-09-26: "make the delete work", and the one DROP
-- CONSTRAINT below approved the same day).
--
-- WHAT THIS ADDS, all dark until an operator confirms a request:
--   1. `project_deletion` joins the purge kinds. The old CHECK is replaced by
--      the same list plus that one value (founder-approved DROP CONSTRAINT).
--      0378 already ties it to project_id; at most one unfinished purge per
--      project.
--   2. resolve_phase1_purge_project_graph_v1(principal, project): the same
--      shape as the account graph, restricted to one owned project. Its
--      principal_ids and user_ids are EMPTY on purpose: every tombstone and
--      every account-keyed dependency then reaches nothing outside the
--      project (tombstone_phase1_purge_projects_v1 and _lineage_v1 both scope
--      to "principal in graph OR project in graph and owned by requester").
--   3. freeze_phase1_project_purge_inventory_v1: the account freeze (v4),
--      derived line for line, with the project graph and stricter storage
--      checks (an audio object's attempt, a practice object's practice and a
--      training copy must all belong to THIS project; orphans and provider
--      operations are refused).
--   4. A guard on data_purge_inventory_manifests: a project request can only
--      be frozen by the project freeze, and an account request never by it.
--      So the account freeze (v4, left unchanged) can never run a project
--      request as an account-wide purge.
--   5. confirm_project_deletion_v1 / complete_project_deletion_v1: the
--      operator's confirm creates the purge request (never the user's tap),
--      and the finished purge marks the project request done.
--
-- NOTHING RUNS FROM THIS FILE. Executing a purge still needs
-- PHASE1_PURGE_EXECUTION_ENABLED and an operator repeating the request id.
--
-- ADDITIVE AND IDEMPOTENT apart from the one approved DROP CONSTRAINT, which
-- is replaced in the same transaction by a strictly wider CHECK.

BEGIN;

DO $$
DECLARE
    old_check RECORD;
    replaced BOOLEAN := false;
BEGIN
    FOR old_check IN
        SELECT conname FROM pg_constraint
         WHERE conrelid = 'public.data_purge_requests'::regclass
           AND contype = 'c'
           AND pg_get_constraintdef(oid) LIKE '%trigger_kind%'
           AND pg_get_constraintdef(oid) LIKE '%service_termination%'
           AND pg_get_constraintdef(oid) NOT LIKE '%project_deletion%'
    LOOP
        EXECUTE format('ALTER TABLE public.data_purge_requests DROP CONSTRAINT %I',
                       old_check.conname);
        replaced := true;
    END LOOP;
    -- Only ever a replacement, strictly wider than what it replaces: a
    -- database whose table carries no kind CHECK gets none from here.
    IF replaced AND NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'data_purge_requests_trigger_kind_v2_check'
           AND conrelid = 'public.data_purge_requests'::regclass
    ) THEN
        ALTER TABLE public.data_purge_requests
            ADD CONSTRAINT data_purge_requests_trigger_kind_v2_check
            CHECK (trigger_kind IN (
                'service_termination', 'account_deletion', 'retention_expiry',
                'third_party_audio_report', 'lawful_deletion',
                'project_deletion'));
    END IF;
END;
$$;

CREATE UNIQUE INDEX IF NOT EXISTS data_purge_requests_one_open_project_idx
    ON public.data_purge_requests (project_id)
    WHERE project_id IS NOT NULL AND state <> 'done';

CREATE OR REPLACE FUNCTION public.resolve_phase1_purge_project_graph_v1(
    p_acquisition_principal_id UUID,
    p_project_id UUID
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER STABLE SET search_path = public
AS $$
DECLARE
    take_values TEXT[]; unresolved_take_values TEXT[]; attempt_values TEXT[];
    recording_values TEXT[]; snippet_values TEXT[]; job_values TEXT[];
    practice_values TEXT[]; practice_attempt_values TEXT[];
    lineage_values TEXT[]; packet_values TEXT[]; delivery_job_values TEXT[];
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.projects project
         WHERE project.id = p_project_id
           AND project.owner_principal_id = p_acquisition_principal_id
    ) THEN RAISE EXCEPTION 'PURGE_PROJECT_NOT_OWNED'; END IF;

    SELECT COALESCE(array_agg(value ORDER BY value), '{}'::text[])
      INTO take_values
      FROM (SELECT session.id::text AS value FROM public.v2_sessions session
             WHERE (session.project_id = p_project_id
                    OR session.arc_id = p_project_id::text)
               AND session.owner_principal_id = p_acquisition_principal_id) rows;

    -- Someone else's take under this project's id is never deleted here; it
    -- stops the purge for a person to look at.
    SELECT COALESCE(array_agg(value ORDER BY value), '{}'::text[])
      INTO unresolved_take_values
      FROM (SELECT session.id::text AS value FROM public.v2_sessions session
             WHERE (session.project_id = p_project_id
                    OR session.arc_id = p_project_id::text)
               AND session.owner_principal_id IS DISTINCT FROM
                   p_acquisition_principal_id) rows;

    SELECT COALESCE(array_agg(value ORDER BY value), '{}'::text[])
      INTO attempt_values
      FROM (SELECT attempt.id::text AS value
              FROM public.processing_recording_attempts attempt
             WHERE attempt.project_id = p_project_id
               AND attempt.acquisition_principal_id = p_acquisition_principal_id) rows;

    SELECT COALESCE(array_agg(value ORDER BY value), '{}'::text[])
      INTO recording_values
      FROM (
          SELECT session.recording_1_id::text AS value
            FROM public.v2_sessions session
           WHERE session.id::text = ANY(take_values)
             AND session.recording_1_id IS NOT NULL
          UNION
          SELECT attempt.recording_id::text
            FROM public.processing_recording_attempts attempt
           WHERE attempt.id::text = ANY(attempt_values)
          UNION
          SELECT recording.id::text
            FROM public.recordings recording
           WHERE recording.session_v2_id::text = ANY(take_values)
              OR recording.session_id::text = ANY(take_values)
          UNION
          SELECT snippet.recording_id::text
            FROM public.snippets snippet
           WHERE snippet.session_id::text = ANY(take_values)
             AND snippet.recording_id IS NOT NULL
      ) rows;

    SELECT COALESCE(array_agg(value ORDER BY value), '{}'::text[])
      INTO snippet_values
      FROM (SELECT snippet.id::text AS value FROM public.snippets snippet
             WHERE snippet.session_id::text = ANY(take_values)) rows;

    SELECT COALESCE(array_agg(value ORDER BY value), '{}'::text[])
      INTO job_values
      FROM (SELECT job.id::text AS value FROM public.phase1_processing_jobs job
             WHERE job.recording_attempt_id::text = ANY(attempt_values)) rows;

    SELECT COALESCE(array_agg(value ORDER BY value), '{}'::text[])
      INTO practice_values
      FROM (SELECT practice.id::text AS value
              FROM public.confident_voice_practice practice
             -- Every practice starts from a take (take_session_id is NOT
             -- NULL); the project's takes are its practice's takes.
             WHERE practice.take_session_id::text = ANY(take_values)) rows;

    SELECT COALESCE(array_agg(value ORDER BY value), '{}'::text[])
      INTO practice_attempt_values
      FROM (SELECT attempt.id::text AS value
              FROM public.confident_voice_practice_attempt attempt
             WHERE attempt.practice_id::text = ANY(practice_values)) rows;

    SELECT COALESCE(array_agg(value ORDER BY value), '{}'::text[])
      INTO lineage_values
      FROM (SELECT lineage.id::text AS value
              FROM public.exercise_audio_lineages lineage
             WHERE lineage.project_id = p_project_id
               AND lineage.acquisition_principal_id = p_acquisition_principal_id) rows;

    SELECT COALESCE(array_agg(value ORDER BY value), '{}'::text[])
      INTO packet_values
      FROM (SELECT packet.id::text AS value
              FROM public.exercise_blind_packets packet
             WHERE packet.audio_lineage_id::text = ANY(lineage_values)) rows;

    SELECT COALESCE(array_agg(value ORDER BY value COLLATE "C"), '{}'::text[])
      INTO delivery_job_values
      FROM (SELECT DISTINCT job.id::text AS value
              FROM public.feedback_language_delivery_materialization_jobs job
              JOIN public.confident_moment_bundle_attachments attachment
                ON attachment.id = job.bundle_attachment_id
             WHERE attachment.project_id = p_project_id) rows;

    RETURN jsonb_build_object(
        'principal_ids', '[]'::jsonb,
        'user_ids', '[]'::jsonb,
        'project_ids', jsonb_build_array(p_project_id::text),
        'take_ids', to_jsonb(take_values),
        'recording_ids', to_jsonb(recording_values),
        'snippet_ids', to_jsonb(snippet_values),
        'permit_ids', '[]'::jsonb,
        'job_ids', to_jsonb(job_values),
        'speaker_ids', '[]'::jsonb,
        'practice_ids', to_jsonb(practice_values),
        'practice_attempt_ids', to_jsonb(practice_attempt_values),
        'exercise_audio_lineage_ids', to_jsonb(lineage_values),
        'exercise_blind_packet_ids', to_jsonb(packet_values),
        'delivery_job_ids', to_jsonb(delivery_job_values),
        'unresolved_legacy_take_ids', to_jsonb(unresolved_take_values)
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.freeze_phase1_project_purge_inventory_v1(
    p_purge_request_id UUID,
    p_resolver_version TEXT,
    p_dependency_manifest_sha256 TEXT,
    p_subject_graph JSONB,
    p_targets JSONB,
    p_catalog_sha256 TEXT,
    p_catalog_unknown_relations TEXT[]
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE req public.data_purge_requests; existing public.data_purge_inventory_manifests;
        item JSONB; kind TEXT; ref TEXT; item_state TEXT; unknown_count INTEGER;
        computed_subject_graph_sha256 TEXT; computed_target_manifest_sha256 TEXT;
        expected_subject_graph JSONB; item_metadata JSONB; locator_key TEXT;
BEGIN
    SELECT * INTO req FROM public.data_purge_requests
     WHERE id = p_purge_request_id FOR UPDATE;
    IF req.id IS NULL THEN RAISE EXCEPTION 'PURGE_REQUEST_NOT_FOUND'; END IF;
    IF req.state = 'done' THEN RAISE EXCEPTION 'PURGE_ALREADY_FINALIZED'; END IF;
    IF jsonb_typeof(p_subject_graph) <> 'object'
       OR jsonb_typeof(p_targets) <> 'array'
       OR jsonb_array_length(p_targets) = 0
    THEN RAISE EXCEPTION 'PURGE_MANIFEST_INVALID'; END IF;
    IF p_resolver_version <> 'phase1-project-purge-resolver-v1' THEN
        RAISE EXCEPTION 'PURGE_RESOLVER_VERSION_INVALID';
    END IF;
    IF req.trigger_kind <> 'project_deletion' OR req.project_id IS NULL THEN
        RAISE EXCEPTION 'PURGE_NOT_A_PROJECT_DELETION';
    END IF;
    -- One project's graph, never the account's (0380).
    expected_subject_graph := public.resolve_phase1_purge_project_graph_v1(
        req.acquisition_principal_id, req.project_id
    );
    IF p_subject_graph IS DISTINCT FROM expected_subject_graph THEN
        RAISE EXCEPTION 'PURGE_SUBJECT_GRAPH_MISMATCH';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(p_targets) candidate
         GROUP BY COALESCE(candidate->>'target_kind', 'unknown'),
                  COALESCE(NULLIF(candidate->>'target_ref', ''), 'unresolved')
        HAVING count(*) > 1
    ) THEN RAISE EXCEPTION 'PURGE_MANIFEST_DUPLICATE_TARGET'; END IF;
    IF p_dependency_manifest_sha256 !~ '^[0-9a-f]{64}$'
       OR p_catalog_sha256 !~ '^[0-9a-f]{64}$'
    THEN RAISE EXCEPTION 'PURGE_MANIFEST_HASH_INVALID'; END IF;

    computed_subject_graph_sha256 := encode(
        extensions.digest(p_subject_graph::text, 'sha256'), 'hex'
    );
    computed_target_manifest_sha256 := encode(
        extensions.digest(p_targets::text, 'sha256'), 'hex'
    );

    SELECT * INTO existing FROM public.data_purge_inventory_manifests
     WHERE purge_request_id = p_purge_request_id;
    IF existing.id IS NOT NULL THEN
        IF existing.resolver_version <> p_resolver_version
           OR existing.dependency_manifest_sha256 <>
              lower(p_dependency_manifest_sha256)
           OR existing.subject_graph_sha256 <> computed_subject_graph_sha256
           OR existing.target_manifest_sha256 <>
              computed_target_manifest_sha256
           OR existing.catalog_sha256 <> lower(p_catalog_sha256)
           OR existing.catalog_unknown_relations <>
              COALESCE(p_catalog_unknown_relations, '{}'::text[])
        THEN RAISE EXCEPTION 'PURGE_INVENTORY_REPLAY_CONFLICT'; END IF;
    ELSE
        INSERT INTO public.data_purge_inventory_manifests (
            purge_request_id, resolver_version, dependency_manifest_sha256,
            subject_graph, subject_graph_sha256, target_manifest_sha256,
            catalog_sha256, catalog_unknown_relations
        ) VALUES (
            p_purge_request_id, p_resolver_version,
            lower(p_dependency_manifest_sha256), p_subject_graph,
            computed_subject_graph_sha256, computed_target_manifest_sha256,
            lower(p_catalog_sha256),
            COALESCE(p_catalog_unknown_relations, '{}'::text[])
        );
    END IF;

    FOR item IN SELECT value FROM jsonb_array_elements(p_targets) LOOP
        kind := COALESCE(item->>'target_kind', 'unknown');
        ref := COALESCE(NULLIF(item->>'target_ref', ''), 'unresolved');
        item_metadata := COALESCE(item->'metadata', '{}'::jsonb);
        IF kind NOT IN (
            'database_row', 'r2_object', 'supabase_object', 'transcript',
            'derived_feedback', 'processing_queue', 'provider_operation',
            'coach_packet', 'cache', 'dataset_lineage', 'model_lineage'
        ) THEN kind := 'unknown'; END IF;
        IF kind <> 'unknown' AND ref LIKE 'dependency:%' THEN
            locator_key := CASE item_metadata->>'locator_kind'
                WHEN 'principal' THEN 'principal_ids'
                WHEN 'user' THEN 'user_ids'
                WHEN 'project' THEN 'project_ids'
                WHEN 'take' THEN 'take_ids'
                WHEN 'recording' THEN 'recording_ids'
                WHEN 'snippet' THEN 'snippet_ids'
                WHEN 'permit' THEN 'permit_ids'
                WHEN 'job' THEN 'job_ids'
                WHEN 'speaker' THEN 'speaker_ids'
                WHEN 'practice' THEN 'practice_ids'
                WHEN 'practice_attempt' THEN 'practice_attempt_ids'
                WHEN 'exercise_audio_lineage' THEN 'exercise_audio_lineage_ids'
                WHEN 'exercise_blind_packet' THEN 'exercise_blind_packet_ids'
                -- 0362: the registry has addressed delivery jobs since 0327.
                WHEN 'delivery_job' THEN 'delivery_job_ids'
                ELSE NULL END;
            IF locator_key IS NULL
               OR length(COALESCE(item_metadata->>'dependency_code', '')) = 0
               OR ref <> ('dependency:' || (item_metadata->>'dependency_code'))
               OR length(COALESCE(item_metadata->>'relation', '')) = 0
               OR length(COALESCE(item_metadata->>'selector_column', '')) = 0
               OR jsonb_typeof(item_metadata->'locator_values') <> 'array'
               OR item_metadata->'locator_values' IS DISTINCT FROM
                  p_subject_graph->locator_key
            THEN RAISE EXCEPTION 'PURGE_DEPENDENCY_TARGET_GRAPH_MISMATCH'; END IF;
        ELSIF kind IN ('r2_object', 'supabase_object') THEN
            IF item_metadata->>'source_relation' = 'processing_audio_objects' THEN
                IF NOT EXISTS (
                    SELECT 1 FROM public.processing_audio_objects object_row
                      JOIN public.processing_recording_attempts attempt
                        ON attempt.id = object_row.recording_attempt_id
                     WHERE object_row.id =
                           (item_metadata->>'source_id')::uuid
                       AND attempt.project_id = req.project_id
                       AND object_row.acquisition_principal_id =
                           req.acquisition_principal_id
                       AND object_row.storage_provider = item_metadata->>'provider'
                       AND object_row.bucket = item_metadata->>'bucket'
                       AND object_row.object_key = item_metadata->>'key'
                       AND object_row.exact_bytes_sha256 =
                           lower(item_metadata->>'sha256')
                ) THEN RAISE EXCEPTION 'PURGE_STORAGE_TARGET_GRAPH_MISMATCH'; END IF;
            ELSIF item_metadata->>'source_relation' =
                  'processing_orphan_objects' THEN
                -- An orphan belongs to no project; a project purge never
                -- takes it (0380).
                RAISE EXCEPTION 'PURGE_STORAGE_TARGET_GRAPH_MISMATCH';
            ELSIF item_metadata->>'source_relation' =
                  'processing_practice_objects' THEN
                -- B-4 (audit 2026-09-22). The orchestrator has emitted this
                -- relation since 0334 and this function never knew it, so a
                -- subject whose only stored audio is a practice recording
                -- could not be purged at all: the freeze raised
                -- SOURCE_INVALID and the request sat at 'requested'.
                -- Verified exactly as its two siblings are.
                IF NOT EXISTS (
                    SELECT 1 FROM public.processing_practice_objects object_row
                      JOIN public.confident_voice_practice_attempt attempt
                        ON attempt.id = object_row.practice_attempt_id
                      JOIN public.confident_voice_practice practice
                        ON practice.id = attempt.practice_id
                     WHERE object_row.id =
                           (item_metadata->>'source_id')::uuid
                       AND practice.take_session_id::text IN (
                           SELECT jsonb_array_elements_text(
                                      p_subject_graph->'take_ids'))
                       AND object_row.acquisition_principal_id =
                           req.acquisition_principal_id
                       AND object_row.storage_provider = item_metadata->>'provider'
                       AND object_row.bucket = item_metadata->>'bucket'
                       AND object_row.object_key = item_metadata->>'key'
                       AND object_row.exact_bytes_sha256 =
                           lower(item_metadata->>'sha256')
                ) THEN RAISE EXCEPTION 'PURGE_STORAGE_TARGET_GRAPH_MISMATCH'; END IF;
            ELSIF item_metadata->>'source_relation' =
                  'training_corpus_items' THEN
                -- P4 (SPEC-training-corpus §6.2): a training copy's audio.
                -- Verified exactly as its siblings are; the key is always
                -- under training-corpus/, never a product object.
                IF NOT EXISTS (
                    SELECT 1 FROM public.training_corpus_items object_row
                     WHERE object_row.id =
                           (item_metadata->>'source_id')::uuid
                       AND object_row.source_project_id::text =
                           req.project_id::text
                       AND object_row.acquisition_principal_id =
                           req.acquisition_principal_id
                       AND object_row.storage_provider = item_metadata->>'provider'
                       AND object_row.bucket = item_metadata->>'bucket'
                       AND object_row.storage_key = item_metadata->>'key'
                       AND object_row.object_sha256 =
                           lower(item_metadata->>'sha256')
                ) THEN RAISE EXCEPTION 'PURGE_STORAGE_TARGET_GRAPH_MISMATCH'; END IF;
            ELSE
                RAISE EXCEPTION 'PURGE_STORAGE_TARGET_SOURCE_INVALID';
            END IF;
            IF (kind = 'r2_object') IS DISTINCT FROM
               (item_metadata->>'provider' = 'r2')
            THEN RAISE EXCEPTION 'PURGE_STORAGE_TARGET_KIND_MISMATCH'; END IF;
        ELSIF kind = 'provider_operation' THEN
            -- Provider operations are account evidence (processor_evidence);
            -- a project purge carries none (0380).
            RAISE EXCEPTION 'PURGE_PROVIDER_TARGET_GRAPH_MISMATCH';
        ELSIF kind <> 'unknown' THEN
            RAISE EXCEPTION 'PURGE_TARGET_SOURCE_INVALID';
        END IF;
        item_state := CASE WHEN kind = 'unknown' THEN 'unknown' ELSE 'pending' END;
        INSERT INTO public.data_purge_targets (
            purge_request_id, target_kind, target_ref, resolver_version,
            state, initial_match_count, metadata
        ) VALUES (
            p_purge_request_id, kind, ref, p_resolver_version, item_state,
            GREATEST(0, COALESCE((item->>'initial_match_count')::integer, 0)),
            item_metadata
        ) ON CONFLICT (purge_request_id, target_kind, target_ref) DO NOTHING;
    END LOOP;
    FOREACH ref IN ARRAY COALESCE(p_catalog_unknown_relations, '{}'::text[]) LOOP
        INSERT INTO public.data_purge_targets (
            purge_request_id, target_kind, target_ref, resolver_version,
            state, metadata
        ) VALUES (
            p_purge_request_id, 'unknown', 'catalog:' || ref,
            p_resolver_version, 'unknown',
            jsonb_build_object('reason_code', 'UNCLASSIFIED_SUBJECT_RELATION')
        ) ON CONFLICT (purge_request_id, target_kind, target_ref) DO NOTHING;
    END LOOP;
    SELECT count(*) INTO unknown_count FROM public.data_purge_targets
     WHERE purge_request_id = p_purge_request_id AND state = 'unknown';
    UPDATE public.data_purge_requests
       SET state = CASE WHEN unknown_count > 0
                        THEN 'review_required' ELSE 'in_progress' END
     WHERE id = p_purge_request_id;
    RETURN jsonb_build_object(
        'purge_request_id', p_purge_request_id,
        'state', CASE WHEN unknown_count > 0
                      THEN 'review_required' ELSE 'in_progress' END,
        'unknown_target_count', unknown_count,
        'inventory_sha256', computed_target_manifest_sha256
    );
END;
$$;

-- A project request is frozen only by the project freeze; an account request
-- never is. Keeps the account freeze (v4, unchanged) from ever running a
-- project request account-wide.
CREATE OR REPLACE FUNCTION public.guard_phase1_purge_manifest_scope_v1()
RETURNS trigger LANGUAGE plpgsql SET search_path = public AS $$
DECLARE
    kind TEXT;
BEGIN
    SELECT trigger_kind INTO kind FROM public.data_purge_requests
     WHERE id = NEW.purge_request_id;
    IF (kind = 'project_deletion')
       IS DISTINCT FROM (NEW.resolver_version = 'phase1-project-purge-resolver-v1')
    THEN
        RAISE EXCEPTION 'PURGE_MANIFEST_SCOPE_MISMATCH';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS data_purge_manifest_scope_guard
    ON public.data_purge_inventory_manifests;
CREATE TRIGGER data_purge_manifest_scope_guard
    BEFORE INSERT ON public.data_purge_inventory_manifests
    FOR EACH ROW EXECUTE FUNCTION public.guard_phase1_purge_manifest_scope_v1();

-- The operator's confirm (N8: an operator confirms every project deletion).
-- The user's tap made a pending request; this makes the purge request, once.
CREATE OR REPLACE FUNCTION public.confirm_project_deletion_v1(
    p_request_id UUID,
    p_operator_id UUID
) RETURNS public.project_deletion_requests
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    request public.project_deletion_requests;
    purge_id UUID;
BEGIN
    SELECT * INTO request FROM public.project_deletion_requests
     WHERE id = p_request_id FOR UPDATE;
    IF request.id IS NULL THEN RAISE EXCEPTION 'PROJECT_DELETION_NOT_FOUND'; END IF;
    IF request.state = 'confirmed' THEN RETURN request; END IF;
    IF request.state <> 'pending' THEN
        RAISE EXCEPTION 'PROJECT_DELETION_NOT_PENDING';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.projects project
         WHERE project.id = request.project_id
           AND project.owner_principal_id = request.acquisition_principal_id
    ) THEN RAISE EXCEPTION 'PURGE_PROJECT_NOT_OWNED'; END IF;

    INSERT INTO public.data_purge_requests (
        acquisition_principal_id, trigger_kind, project_id, idempotency_key
    ) VALUES (
        request.acquisition_principal_id, 'project_deletion',
        request.project_id, 'project-deletion:' || request.id::text
    )
    ON CONFLICT (acquisition_principal_id, idempotency_key) DO NOTHING;
    SELECT id INTO purge_id FROM public.data_purge_requests
     WHERE acquisition_principal_id = request.acquisition_principal_id
       AND idempotency_key = 'project-deletion:' || request.id::text;

    UPDATE public.project_deletion_requests
       SET state = 'confirmed', confirmed_at = now(),
           confirmed_by = p_operator_id, purge_request_id = purge_id
     WHERE id = request.id
    RETURNING * INTO request;
    RETURN request;
END;
$$;

-- The finished purge marks the project request done; nothing else can.
CREATE OR REPLACE FUNCTION public.complete_project_deletion_v1(
    p_purge_request_id UUID
) RETURNS public.project_deletion_requests
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    request public.project_deletion_requests;
BEGIN
    SELECT * INTO request FROM public.project_deletion_requests
     WHERE purge_request_id = p_purge_request_id FOR UPDATE;
    IF request.id IS NULL THEN RAISE EXCEPTION 'PROJECT_DELETION_NOT_FOUND'; END IF;
    IF request.state = 'done' THEN RETURN request; END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.data_purge_requests purge
         WHERE purge.id = p_purge_request_id AND purge.state = 'done'
    ) THEN RAISE EXCEPTION 'PROJECT_PURGE_NOT_DONE'; END IF;
    UPDATE public.project_deletion_requests
       SET state = 'done', completed_at = now()
     WHERE id = request.id
    RETURNING * INTO request;
    RETURN request;
END;
$$;

REVOKE ALL ON FUNCTION public.resolve_phase1_purge_project_graph_v1(UUID, UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.resolve_phase1_purge_project_graph_v1(UUID, UUID)
    TO service_role;
REVOKE ALL ON FUNCTION public.freeze_phase1_project_purge_inventory_v1(
    UUID, TEXT, TEXT, JSONB, JSONB, TEXT, TEXT[]) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.freeze_phase1_project_purge_inventory_v1(
    UUID, TEXT, TEXT, JSONB, JSONB, TEXT, TEXT[]) TO service_role;
REVOKE ALL ON FUNCTION public.confirm_project_deletion_v1(UUID, UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.confirm_project_deletion_v1(UUID, UUID)
    TO service_role;
REVOKE ALL ON FUNCTION public.complete_project_deletion_v1(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.complete_project_deletion_v1(UUID)
    TO service_role;
REVOKE ALL ON FUNCTION public.guard_phase1_purge_manifest_scope_v1()
    FROM PUBLIC, anon, authenticated;

COMMIT;
