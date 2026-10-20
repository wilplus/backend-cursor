-- a_project_deletion_finds_its_takes_by_their_arc_as_text (0488)
--
-- THE PROBLEM. Production's v2_sessions.arc_id is a UUID (0114,
-- add_explore_arc.sql). Two functions of the one-project deletion compare it
-- to text:
--
--     session.arc_id = p_project_id::text
--
-- and Postgres has no uuid = text operator, so each raises
-- "operator does not exist: uuid = text" the first time it runs:
--   * void_project_pair_releases_v1 (0456), called by
--     request_project_deletion_v1, start_due_ and confirm_project_deletion_v1:
--     asking to delete a project fails before any row is written;
--   * resolve_phase1_purge_project_graph_v1 (0380): the one-project purge
--     cannot build its subject graph.
-- So no project can be deleted in production. The rehearsal lane's narrow
-- v2_sessions copy declares arc_id TEXT, which is why no test saw it. Found
-- 2026-10-20 when the founder's own SQL hit the same error on the same
-- column while preparing to delete three projects (founder: "Erase just the
-- 3 projects").
--
-- THE FIX. Both comparisons become
--
--     session.arc_id::text = p_project_id::text
--
-- which holds for a UUID column and for the lane's TEXT copy alike, and is
-- served by 0478's expression index on (arc_id::text). Nothing else in
-- either function changes: each body below is the current definition (0380,
-- 0456) with that one comparison rewritten, and keeps its grants.
--
-- WHO IT AFFECTS. Only project deletion, which is off in the app today
-- (frontend PROJECT_DELETE_ENABLED = false). The account purge's graph
-- (0312) already compares session.arc_id::text and is untouched.
--
-- ADDITIVE AND IDEMPOTENT. Two CREATE OR REPLACE FUNCTION statements with
-- unchanged signatures and their REVOKE/GRANT; no table, column, index or
-- row is created, altered or dropped. Safe to re-run. No env var.

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
                    OR session.arc_id::text = p_project_id::text)
               AND session.owner_principal_id = p_acquisition_principal_id) rows;

    -- Someone else's take under this project's id is never deleted here; it
    -- stops the purge for a person to look at.
    SELECT COALESCE(array_agg(value ORDER BY value), '{}'::text[])
      INTO unresolved_take_values
      FROM (SELECT session.id::text AS value FROM public.v2_sessions session
             WHERE (session.project_id = p_project_id
                    OR session.arc_id::text = p_project_id::text)
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
REVOKE ALL ON FUNCTION public.resolve_phase1_purge_project_graph_v1(UUID, UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.resolve_phase1_purge_project_graph_v1(UUID, UUID)
    TO service_role;

CREATE OR REPLACE FUNCTION public.void_project_pair_releases_v1(
    p_project_id UUID
) RETURNS INTEGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
BEGIN
    IF p_project_id IS NULL
       OR to_regclass('public.feedback_pairs') IS NULL THEN
        RETURN 0;
    END IF;
    -- The project's Takes as the one-project purge finds them (0380), by
    -- project_id or by arc_id, whoever's Take it is.
    RETURN public.void_pair_releases_v1(ARRAY(
        SELECT pair.release_id FROM public.feedback_pairs pair
         WHERE pair.release_id IS NOT NULL
           AND pair.take_session_id IN (
               SELECT session.id::text FROM public.v2_sessions session
                WHERE session.project_id = p_project_id
                   OR session.arc_id::text = p_project_id::text)
    ), 'project_erasure_requested');
END;
$$;
REVOKE ALL ON FUNCTION public.void_project_pair_releases_v1(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.void_project_pair_releases_v1(UUID)
    TO service_role;
