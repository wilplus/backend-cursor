-- CEO Intelligence Sync: immutable evidence -> generated preview -> admin approval.
--
-- This remains observational. Sources are read-only snapshots and every write
-- stays inside ceo_* tables. Generated revisions can never become official
-- without an explicit admin decision.

CREATE TABLE IF NOT EXISTS public.ceo_source_snapshots (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_key  TEXT NOT NULL REFERENCES public.ceo_projects(project_key),
    feature_id   UUID,
    source_type  TEXT NOT NULL,
    source_ref   TEXT NOT NULL,
    title        TEXT NOT NULL,
    content      TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    metadata     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by   UUID,
    captured_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ceo_source_snapshots_feature_project_fk
        FOREIGN KEY (project_key, feature_id)
        REFERENCES public.ceo_features(project_key, id),
    CONSTRAINT ceo_source_snapshots_type_check CHECK (
        source_type IN (
            'backend_code', 'frontend_code', 'migration', 'documentation',
            'research_paper', 'manual_note', 'vision', 'ceo_history'
        )
    ),
    CONSTRAINT ceo_source_snapshots_ref_check
        CHECK (length(btrim(source_ref)) BETWEEN 1 AND 1000),
    CONSTRAINT ceo_source_snapshots_title_check
        CHECK (length(btrim(title)) BETWEEN 1 AND 300),
    CONSTRAINT ceo_source_snapshots_content_check
        CHECK (length(content) BETWEEN 1 AND 120000),
    CONSTRAINT ceo_source_snapshots_hash_check
        CHECK (length(content_hash) = 64),
    CONSTRAINT ceo_source_snapshots_immutable_unique
        UNIQUE (project_key, feature_id, source_ref, content_hash)
);

CREATE INDEX IF NOT EXISTS ceo_source_snapshots_feature_captured_idx
    ON public.ceo_source_snapshots (project_key, feature_id, captured_at DESC);

CREATE TABLE IF NOT EXISTS public.ceo_analysis_runs (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_key              TEXT NOT NULL REFERENCES public.ceo_projects(project_key),
    feature_id               UUID NOT NULL,
    artifact_id              UUID NOT NULL REFERENCES public.ceo_artifacts(id),
    lens                     TEXT NOT NULL,
    trigger_type             TEXT NOT NULL,
    trigger_id               UUID,
    reevaluation_request_id  UUID REFERENCES public.ceo_reevaluation_requests(id),
    reason                   TEXT NOT NULL DEFAULT '',
    status                   TEXT NOT NULL DEFAULT 'queued',
    base_revision_id         UUID NOT NULL REFERENCES public.ceo_artifact_revisions(id),
    proposal_revision_id     UUID REFERENCES public.ceo_artifact_revisions(id),
    source_snapshot_ids      UUID[] NOT NULL DEFAULT '{}'::uuid[],
    model                    TEXT,
    prompt_tokens            INTEGER,
    completion_tokens        INTEGER,
    total_tokens             INTEGER,
    duration_ms              INTEGER,
    error_code               TEXT,
    error_message            TEXT,
    created_by               UUID,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at               TIMESTAMPTZ,
    finished_at              TIMESTAMPTZ,
    reviewed_at              TIMESTAMPTZ,
    reviewed_by              UUID,
    CONSTRAINT ceo_analysis_runs_feature_project_fk
        FOREIGN KEY (project_key, feature_id)
        REFERENCES public.ceo_features(project_key, id),
    CONSTRAINT ceo_analysis_runs_lens_check
        CHECK (lens IN ('architecture', 'ml')),
    CONSTRAINT ceo_analysis_runs_trigger_check
        CHECK (trigger_type IN ('manual', 'comment', 'task_completed', 'source_change')),
    CONSTRAINT ceo_analysis_runs_status_check CHECK (
        status IN (
            'queued', 'running', 'preview_ready', 'approved', 'rejected',
            'failed'
        )
    ),
    CONSTRAINT ceo_analysis_runs_tokens_check CHECK (
        COALESCE(prompt_tokens, 0) >= 0
        AND COALESCE(completion_tokens, 0) >= 0
        AND COALESCE(total_tokens, 0) >= 0
        AND COALESCE(duration_ms, 0) >= 0
    )
);

CREATE INDEX IF NOT EXISTS ceo_analysis_runs_artifact_created_idx
    ON public.ceo_analysis_runs (artifact_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ceo_analysis_runs_feature_status_idx
    ON public.ceo_analysis_runs (project_key, feature_id, status, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS ceo_analysis_runs_one_open_proposal_idx
    ON public.ceo_analysis_runs (artifact_id)
    WHERE status IN ('queued', 'running', 'preview_ready');

CREATE TABLE IF NOT EXISTS public.ceo_artifact_revision_sources (
    revision_id       UUID NOT NULL REFERENCES public.ceo_artifact_revisions(id)
        ON DELETE CASCADE,
    source_snapshot_id UUID NOT NULL REFERENCES public.ceo_source_snapshots(id),
    PRIMARY KEY (revision_id, source_snapshot_id)
);

CREATE INDEX IF NOT EXISTS ceo_artifact_revision_sources_source_idx
    ON public.ceo_artifact_revision_sources (source_snapshot_id, revision_id);

ALTER TABLE public.ceo_source_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ceo_analysis_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ceo_artifact_revision_sources ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.ceo_source_snapshots FROM anon, authenticated;
REVOKE ALL ON TABLE public.ceo_analysis_runs FROM anon, authenticated;
REVOKE ALL ON TABLE public.ceo_artifact_revision_sources FROM anon, authenticated;

-- Snapshots are immutable: service_role may read and append, never update or delete.
GRANT SELECT, INSERT ON TABLE public.ceo_source_snapshots TO service_role;
GRANT SELECT, INSERT, UPDATE ON TABLE public.ceo_analysis_runs TO service_role;
GRANT SELECT, INSERT ON TABLE public.ceo_artifact_revision_sources TO service_role;

CREATE OR REPLACE FUNCTION public.ceo_capture_source_snapshot(
    p_project_key TEXT,
    p_feature_id UUID,
    p_source_type TEXT,
    p_source_ref TEXT,
    p_title TEXT,
    p_content TEXT,
    p_content_hash TEXT,
    p_metadata JSONB,
    p_created_by UUID
) RETURNS TABLE (out_snapshot_id UUID)
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
    v_snapshot_id UUID;
BEGIN
    INSERT INTO public.ceo_source_snapshots (
        project_key, feature_id, source_type, source_ref, title, content,
        content_hash, metadata, created_by
    ) VALUES (
        p_project_key, p_feature_id, p_source_type, btrim(p_source_ref),
        btrim(p_title), p_content, p_content_hash,
        COALESCE(p_metadata, '{}'::jsonb), p_created_by
    )
    ON CONFLICT (project_key, feature_id, source_ref, content_hash) DO NOTHING
    RETURNING id INTO v_snapshot_id;

    IF v_snapshot_id IS NULL THEN
        SELECT snapshot.id INTO v_snapshot_id
          FROM public.ceo_source_snapshots snapshot
         WHERE snapshot.project_key = p_project_key
           AND snapshot.feature_id IS NOT DISTINCT FROM p_feature_id
           AND snapshot.source_ref = btrim(p_source_ref)
           AND snapshot.content_hash = p_content_hash
         LIMIT 1;
    END IF;
    RETURN QUERY SELECT v_snapshot_id;
END;
$$;

-- The official bootstrap must ignore generated previews until approval.
CREATE OR REPLACE FUNCTION public.ceo_latest_artifact_revisions()
RETURNS TABLE (
    id UUID,
    artifact_id UUID,
    version INTEGER,
    content JSONB,
    ownership TEXT,
    status TEXT,
    created_by TEXT,
    created_at TIMESTAMPTZ
)
LANGUAGE sql
STABLE
SET search_path = public
AS $$
    SELECT DISTINCT ON (revision.artifact_id)
        revision.id,
        revision.artifact_id,
        revision.version,
        revision.content,
        revision.ownership,
        revision.status,
        revision.created_by,
        revision.created_at
    FROM public.ceo_artifact_revisions revision
    WHERE revision.status = 'official'
    ORDER BY revision.artifact_id, revision.version DESC;
$$;

-- Manual editing compares against the latest official revision, not a hidden
-- preview. It still allocates the next global version so rejected previews
-- remain immutable history instead of colliding with a later manual save.
CREATE OR REPLACE FUNCTION public.ceo_save_artifact_revision(
    p_artifact_id UUID,
    p_content JSONB,
    p_created_by UUID,
    p_expected_version INTEGER
) RETURNS TABLE (
    out_revision_id UUID,
    out_version INTEGER,
    out_created_at TIMESTAMPTZ
)
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
    v_revision_id UUID;
    v_official_version INTEGER;
    v_next_version INTEGER;
    v_created_at TIMESTAMPTZ;
    v_project_key TEXT;
    v_feature_id UUID;
    v_lens TEXT;
BEGIN
    SELECT project_key, feature_id, lens
      INTO v_project_key, v_feature_id, v_lens
      FROM public.ceo_artifacts
     WHERE id = p_artifact_id
     FOR UPDATE;
    IF v_project_key IS NULL THEN
        RAISE EXCEPTION 'CEO artifact does not exist';
    END IF;

    SELECT COALESCE(MAX(version), 0)
      INTO v_official_version
      FROM public.ceo_artifact_revisions
     WHERE artifact_id = p_artifact_id
       AND status = 'official';
    IF v_official_version <> p_expected_version THEN
        RETURN;
    END IF;
    SELECT COALESCE(MAX(version), 0) + 1
      INTO v_next_version
      FROM public.ceo_artifact_revisions
     WHERE artifact_id = p_artifact_id;

    INSERT INTO public.ceo_artifact_revisions (
        artifact_id, version, content, ownership, status, created_by
    ) VALUES (
        p_artifact_id, v_next_version, p_content, 'manual', 'official',
        p_created_by::text
    ) RETURNING id, created_at INTO v_revision_id, v_created_at;

    INSERT INTO public.ceo_timeline_events (
        project_key, feature_id, event_type, entity_type, entity_id,
        summary, payload, created_by
    ) VALUES (
        v_project_key, v_feature_id, 'artifact_updated', 'artifact',
        p_artifact_id, initcap(v_lens) || ' updated',
        jsonb_build_object(
            'revision_id', v_revision_id, 'version', v_next_version
        ), p_created_by
    );

    RETURN QUERY SELECT v_revision_id, v_next_version, v_created_at;
END;
$$;

CREATE OR REPLACE FUNCTION public.ceo_create_analysis_run(
    p_artifact_id UUID,
    p_trigger_type TEXT,
    p_trigger_id UUID,
    p_reevaluation_request_id UUID,
    p_reason TEXT,
    p_created_by UUID
) RETURNS TABLE (out_run_id UUID, out_created BOOLEAN)
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
    v_project_key TEXT;
    v_feature_id UUID;
    v_lens TEXT;
    v_base_revision_id UUID;
    v_existing UUID;
    v_run_id UUID;
BEGIN
    SELECT artifact.project_key, artifact.feature_id, artifact.lens
      INTO v_project_key, v_feature_id, v_lens
      FROM public.ceo_artifacts artifact
     WHERE artifact.id = p_artifact_id
       AND artifact.scope_kind = 'feature'
       AND artifact.lens IN ('architecture', 'ml')
     FOR UPDATE;
    IF v_feature_id IS NULL THEN
        RAISE EXCEPTION 'CEO analysis requires a feature Architecture or ML artifact';
    END IF;
    IF p_trigger_type NOT IN ('manual', 'comment', 'task_completed', 'source_change') THEN
        RAISE EXCEPTION 'invalid CEO analysis trigger';
    END IF;

    SELECT revision.id
      INTO v_base_revision_id
      FROM public.ceo_artifact_revisions revision
     WHERE revision.artifact_id = p_artifact_id
       AND revision.status = 'official'
     ORDER BY revision.version DESC
     LIMIT 1;
    IF v_base_revision_id IS NULL THEN
        RAISE EXCEPTION 'CEO artifact has no official base revision';
    END IF;

    -- A worker can disappear after claiming a run. Do not let that stale row
    -- permanently block all future proposals for the artifact.
    UPDATE public.ceo_reevaluation_requests request
       SET status = 'failed', processed_at = now()
     WHERE request.id IN (
        SELECT stale.reevaluation_request_id
          FROM public.ceo_analysis_runs stale
         WHERE stale.artifact_id = p_artifact_id
           AND stale.status IN ('queued', 'running')
           AND COALESCE(stale.started_at, stale.created_at)
               < now() - interval '30 minutes'
           AND stale.reevaluation_request_id IS NOT NULL
     );
    UPDATE public.ceo_analysis_runs run
       SET status = 'failed', finished_at = now(),
           error_code = 'STALE_ANALYSIS_RUN',
           error_message = 'The analysis worker did not finish in time.'
     WHERE run.artifact_id = p_artifact_id
       AND run.status IN ('queued', 'running')
       AND COALESCE(run.started_at, run.created_at) < now() - interval '30 minutes';

    SELECT run.id
      INTO v_existing
      FROM public.ceo_analysis_runs run
     WHERE run.artifact_id = p_artifact_id
       AND run.status IN ('queued', 'running', 'preview_ready')
     ORDER BY run.created_at DESC
     LIMIT 1;
    IF v_existing IS NOT NULL THEN
        IF p_reevaluation_request_id IS NOT NULL THEN
            UPDATE public.ceo_reevaluation_requests
               SET status = 'failed', processed_at = now()
             WHERE id = p_reevaluation_request_id
               AND status = 'pending';
        END IF;
        RETURN QUERY SELECT v_existing, false;
        RETURN;
    END IF;

    INSERT INTO public.ceo_analysis_runs (
        project_key, feature_id, artifact_id, lens, trigger_type, trigger_id,
        reevaluation_request_id, reason, base_revision_id, created_by
    ) VALUES (
        v_project_key, v_feature_id, p_artifact_id, v_lens, p_trigger_type,
        p_trigger_id, p_reevaluation_request_id,
        left(btrim(COALESCE(p_reason, '')), 2000), v_base_revision_id,
        p_created_by
    ) RETURNING id INTO v_run_id;

    IF p_reevaluation_request_id IS NOT NULL THEN
        UPDATE public.ceo_reevaluation_requests
           SET status = 'processing'
         WHERE id = p_reevaluation_request_id
           AND status = 'pending';
    END IF;

    RETURN QUERY SELECT v_run_id, true;
END;
$$;

CREATE OR REPLACE FUNCTION public.ceo_finish_analysis_run(
    p_run_id UUID,
    p_content JSONB,
    p_source_snapshot_ids UUID[],
    p_model TEXT,
    p_prompt_tokens INTEGER,
    p_completion_tokens INTEGER,
    p_total_tokens INTEGER,
    p_duration_ms INTEGER
) RETURNS TABLE (out_revision_id UUID, out_version INTEGER)
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
    v_run public.ceo_analysis_runs%ROWTYPE;
    v_revision_id UUID;
    v_version INTEGER;
BEGIN
    SELECT * INTO v_run
      FROM public.ceo_analysis_runs
     WHERE id = p_run_id
       AND status = 'running'
     FOR UPDATE;
    IF v_run.id IS NULL THEN
        RETURN;
    END IF;

    SELECT COALESCE(MAX(revision.version), 0) + 1
      INTO v_version
      FROM public.ceo_artifact_revisions revision
     WHERE revision.artifact_id = v_run.artifact_id;

    INSERT INTO public.ceo_artifact_revisions (
        artifact_id, version, content, ownership, status, created_by
    ) VALUES (
        v_run.artifact_id, v_version, p_content, 'generated', 'preview',
        COALESCE(v_run.created_by::text, 'ceo_intelligence')
    ) RETURNING id INTO v_revision_id;

    INSERT INTO public.ceo_artifact_revision_sources (
        revision_id, source_snapshot_id
    )
    SELECT v_revision_id, source.id
      FROM unnest(COALESCE(p_source_snapshot_ids, '{}'::uuid[]))
           AS source_ids(source_id)
      JOIN public.ceo_source_snapshots source
        ON source.id = source_ids.source_id
     WHERE source.project_key = v_run.project_key
       AND (source.feature_id IS NULL OR source.feature_id = v_run.feature_id)
    ON CONFLICT DO NOTHING;

    UPDATE public.ceo_analysis_runs
       SET status = 'preview_ready',
           proposal_revision_id = v_revision_id,
           source_snapshot_ids = COALESCE(p_source_snapshot_ids, '{}'::uuid[]),
           model = left(COALESCE(p_model, ''), 120),
           prompt_tokens = GREATEST(COALESCE(p_prompt_tokens, 0), 0),
           completion_tokens = GREATEST(COALESCE(p_completion_tokens, 0), 0),
           total_tokens = GREATEST(COALESCE(p_total_tokens, 0), 0),
           duration_ms = GREATEST(COALESCE(p_duration_ms, 0), 0),
           finished_at = now(),
           error_code = NULL,
           error_message = NULL
     WHERE id = p_run_id;

    IF v_run.reevaluation_request_id IS NOT NULL THEN
        UPDATE public.ceo_reevaluation_requests
           SET status = 'completed', processed_at = now()
         WHERE id = v_run.reevaluation_request_id;
    END IF;

    INSERT INTO public.ceo_timeline_events (
        project_key, feature_id, event_type, entity_type, entity_id,
        summary, payload, created_by
    ) VALUES (
        v_run.project_key, v_run.feature_id, 'analysis_preview_ready',
        'artifact', v_run.artifact_id, initcap(v_run.lens) || ' proposal ready',
        jsonb_build_object('run_id', p_run_id, 'revision_id', v_revision_id),
        v_run.created_by
    );

    RETURN QUERY SELECT v_revision_id, v_version;
END;
$$;

CREATE OR REPLACE FUNCTION public.ceo_claim_analysis_run(p_run_id UUID)
RETURNS TABLE (
    out_run_id UUID,
    out_project_key TEXT,
    out_feature_id UUID,
    out_artifact_id UUID,
    out_lens TEXT,
    out_base_revision_id UUID,
    out_reason TEXT,
    out_created_by UUID
)
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
    RETURN QUERY
    UPDATE public.ceo_analysis_runs run
       SET status = 'running', started_at = now(), error_code = NULL,
           error_message = NULL
     WHERE run.id = p_run_id
       AND run.status = 'queued'
    RETURNING run.id, run.project_key, run.feature_id, run.artifact_id,
        run.lens, run.base_revision_id, run.reason, run.created_by;
END;
$$;

CREATE OR REPLACE FUNCTION public.ceo_fail_analysis_run(
    p_run_id UUID,
    p_error_code TEXT,
    p_error_message TEXT
) RETURNS VOID
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
    v_request_id UUID;
BEGIN
    UPDATE public.ceo_analysis_runs
       SET status = 'failed', finished_at = now(),
           error_code = left(COALESCE(p_error_code, 'ANALYSIS_FAILED'), 120),
           error_message = left(COALESCE(p_error_message, 'Analysis failed.'), 2000)
     WHERE id = p_run_id
       AND status IN ('queued', 'running')
    RETURNING reevaluation_request_id INTO v_request_id;
    IF v_request_id IS NOT NULL THEN
        UPDATE public.ceo_reevaluation_requests
           SET status = 'failed', processed_at = now()
         WHERE id = v_request_id;
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.ceo_review_analysis_run(
    p_run_id UUID,
    p_decision TEXT,
    p_admin_user_id UUID
) RETURNS TABLE (
    out_run_id UUID,
    out_status TEXT,
    out_revision_id UUID,
    out_conflict BOOLEAN
)
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
    v_run public.ceo_analysis_runs%ROWTYPE;
    v_latest_official UUID;
BEGIN
    IF p_decision NOT IN ('approve', 'reject') THEN
        RAISE EXCEPTION 'invalid CEO analysis decision';
    END IF;
    SELECT * INTO v_run
      FROM public.ceo_analysis_runs
     WHERE id = p_run_id
       AND status = 'preview_ready'
     FOR UPDATE;
    IF v_run.id IS NULL THEN
        RETURN;
    END IF;

    IF p_decision = 'reject' THEN
        UPDATE public.ceo_analysis_runs
           SET status = 'rejected', reviewed_at = now(),
               reviewed_by = p_admin_user_id
         WHERE id = p_run_id;
        INSERT INTO public.ceo_timeline_events (
            project_key, feature_id, event_type, entity_type, entity_id,
            summary, payload, created_by
        ) VALUES (
            v_run.project_key, v_run.feature_id, 'analysis_rejected', 'artifact',
            v_run.artifact_id, initcap(v_run.lens) || ' proposal rejected',
            jsonb_build_object(
                'run_id', p_run_id, 'revision_id', v_run.proposal_revision_id
            ), p_admin_user_id
        );
        RETURN QUERY SELECT p_run_id, 'rejected'::text,
            v_run.proposal_revision_id, false;
        RETURN;
    END IF;

    SELECT revision.id INTO v_latest_official
      FROM public.ceo_artifact_revisions revision
     WHERE revision.artifact_id = v_run.artifact_id
       AND revision.status = 'official'
     ORDER BY revision.version DESC
     LIMIT 1;
    IF v_latest_official IS DISTINCT FROM v_run.base_revision_id THEN
        RETURN QUERY SELECT p_run_id, 'preview_ready'::text,
            v_run.proposal_revision_id, true;
        RETURN;
    END IF;

    UPDATE public.ceo_artifact_revisions
       SET status = 'official'
     WHERE id = v_run.proposal_revision_id
       AND status = 'preview';
    UPDATE public.ceo_analysis_runs
       SET status = 'approved', reviewed_at = now(),
           reviewed_by = p_admin_user_id
     WHERE id = p_run_id;

    INSERT INTO public.ceo_timeline_events (
        project_key, feature_id, event_type, entity_type, entity_id,
        summary, payload, created_by
    ) VALUES (
        v_run.project_key, v_run.feature_id, 'analysis_approved', 'artifact',
        v_run.artifact_id, initcap(v_run.lens) || ' proposal approved',
        jsonb_build_object(
            'run_id', p_run_id, 'revision_id', v_run.proposal_revision_id
        ), p_admin_user_id
    );

    RETURN QUERY SELECT p_run_id, 'approved'::text,
        v_run.proposal_revision_id, false;
END;
$$;

REVOKE ALL ON FUNCTION public.ceo_latest_artifact_revisions()
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.ceo_save_artifact_revision(UUID, JSONB, UUID, INTEGER)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.ceo_capture_source_snapshot(TEXT, UUID, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, UUID)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.ceo_create_analysis_run(UUID, TEXT, UUID, UUID, TEXT, UUID)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.ceo_finish_analysis_run(UUID, JSONB, UUID[], TEXT, INTEGER, INTEGER, INTEGER, INTEGER)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.ceo_claim_analysis_run(UUID)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.ceo_fail_analysis_run(UUID, TEXT, TEXT)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.ceo_review_analysis_run(UUID, TEXT, UUID)
    FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.ceo_latest_artifact_revisions()
    TO service_role;
GRANT EXECUTE ON FUNCTION public.ceo_save_artifact_revision(UUID, JSONB, UUID, INTEGER)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.ceo_capture_source_snapshot(TEXT, UUID, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, UUID)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.ceo_create_analysis_run(UUID, TEXT, UUID, UUID, TEXT, UUID)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.ceo_finish_analysis_run(UUID, JSONB, UUID[], TEXT, INTEGER, INTEGER, INTEGER, INTEGER)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.ceo_claim_analysis_run(UUID)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.ceo_fail_analysis_run(UUID, TEXT, TEXT)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.ceo_review_analysis_run(UUID, TEXT, UUID)
    TO service_role;
