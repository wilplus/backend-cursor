-- CEO Overview editing: manual features, versioned artifacts, and comments.
--
-- CEO remains observational. These writes modify only ceo_* records and queue
-- future analysis; no function here can write application or research data.

CREATE TABLE IF NOT EXISTS public.ceo_artifact_comments (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_id UUID NOT NULL REFERENCES public.ceo_artifacts(id) ON DELETE CASCADE,
    text        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',
    created_by  UUID,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ceo_artifact_comments_text_check CHECK (length(btrim(text)) > 0),
    CONSTRAINT ceo_artifact_comments_status_check
        CHECK (status IN ('open', 'resolved'))
);

CREATE INDEX IF NOT EXISTS ceo_artifact_comments_artifact_created_idx
    ON public.ceo_artifact_comments (artifact_id, created_at DESC);

ALTER TABLE public.ceo_artifact_comments ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.ceo_artifact_comments FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON TABLE public.ceo_artifact_comments TO service_role;

-- Bootstrap stays bounded as manual edits create an unbounded revision log.
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
    ORDER BY revision.artifact_id, revision.version DESC;
$$;

CREATE OR REPLACE FUNCTION public.ceo_create_feature(
    p_project_key TEXT,
    p_name TEXT,
    p_description TEXT,
    p_created_by UUID
) RETURNS TABLE (out_feature_id UUID, out_slug TEXT)
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
    v_feature_id UUID;
    v_base_slug TEXT;
    v_slug TEXT;
    v_suffix INTEGER := 1;
    v_position INTEGER;
BEGIN
    IF p_project_key NOT IN ('product', 'research') THEN
        RAISE EXCEPTION 'invalid CEO project';
    END IF;
    IF length(btrim(COALESCE(p_name, ''))) = 0 THEN
        RAISE EXCEPTION 'feature name is empty';
    END IF;

    v_base_slug := trim(both '-' from regexp_replace(
        lower(btrim(p_name)), '[^a-z0-9]+', '-', 'g'
    ));
    IF v_base_slug = '' THEN
        v_base_slug := 'feature';
    END IF;
    v_slug := v_base_slug;
    WHILE EXISTS (
        SELECT 1 FROM public.ceo_features
         WHERE project_key = p_project_key AND slug = v_slug
    ) LOOP
        v_suffix := v_suffix + 1;
        v_slug := v_base_slug || '-' || v_suffix::text;
    END LOOP;

    SELECT COALESCE(MAX(position), -1) + 1
      INTO v_position
      FROM public.ceo_features
     WHERE project_key = p_project_key AND status = 'active';

    INSERT INTO public.ceo_features (
        project_key, slug, name, description, position
    ) VALUES (
        p_project_key,
        v_slug,
        btrim(p_name),
        btrim(COALESCE(p_description, '')),
        v_position
    ) RETURNING id INTO v_feature_id;

    INSERT INTO public.ceo_artifacts (
        project_key, scope_kind, feature_id, lens, artifact_kind,
        default_ownership
    ) VALUES
        (p_project_key, 'feature', v_feature_id, 'architecture',
            'architecture_spec', 'generated'),
        (p_project_key, 'feature', v_feature_id, 'ml',
            'ml_system_map', 'generated'),
        (p_project_key, 'feature', v_feature_id, 'vision',
            'vision_document', 'manual');

    INSERT INTO public.ceo_artifact_revisions (
        artifact_id, version, content, ownership, status, created_by
    )
    SELECT
        artifact.id,
        1,
        CASE
            WHEN artifact.lens = 'vision' THEN '{"document":""}'::jsonb
            ELSE '{}'::jsonb
        END,
        artifact.default_ownership,
        'official',
        p_created_by::text
    FROM public.ceo_artifacts artifact
    WHERE artifact.feature_id = v_feature_id;

    RETURN QUERY SELECT v_feature_id, v_slug;
END;
$$;

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
    v_version INTEGER;
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
      INTO v_version
      FROM public.ceo_artifact_revisions
     WHERE artifact_id = p_artifact_id;
    IF v_version <> p_expected_version THEN
        -- Returning no row lets the API consistently map a concurrent edit
        -- to HTTP 409 instead of leaking a database exception as HTTP 500.
        RETURN;
    END IF;
    v_version := v_version + 1;

    INSERT INTO public.ceo_artifact_revisions (
        artifact_id, version, content, ownership, status, created_by
    ) VALUES (
        p_artifact_id, v_version, p_content, 'manual', 'official',
        p_created_by::text
    ) RETURNING id, created_at INTO v_revision_id, v_created_at;

    INSERT INTO public.ceo_timeline_events (
        project_key, feature_id, event_type, entity_type, entity_id,
        summary, payload, created_by
    ) VALUES (
        v_project_key, v_feature_id, 'artifact_updated', 'artifact',
        p_artifact_id, initcap(v_lens) || ' updated',
        jsonb_build_object('revision_id', v_revision_id, 'version', v_version),
        p_created_by
    );

    RETURN QUERY SELECT v_revision_id, v_version, v_created_at;
END;
$$;

CREATE OR REPLACE FUNCTION public.ceo_comment_and_request_reevaluation(
    p_artifact_id UUID,
    p_comment TEXT,
    p_created_by UUID
) RETURNS TABLE (out_comment_id UUID, out_request_id UUID)
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
    v_comment_id UUID;
    v_request_id UUID;
    v_project_key TEXT;
    v_feature_id UUID;
BEGIN
    SELECT project_key, feature_id
      INTO v_project_key, v_feature_id
      FROM public.ceo_artifacts
     WHERE id = p_artifact_id;
    IF v_project_key IS NULL THEN
        RAISE EXCEPTION 'CEO artifact does not exist';
    END IF;
    IF length(btrim(COALESCE(p_comment, ''))) = 0 THEN
        RAISE EXCEPTION 'CEO comment is empty';
    END IF;

    INSERT INTO public.ceo_artifact_comments (
        artifact_id, text, created_by
    ) VALUES (
        p_artifact_id, btrim(p_comment), p_created_by
    ) RETURNING id INTO v_comment_id;

    INSERT INTO public.ceo_reevaluation_requests (
        project_key, feature_id, trigger_type, trigger_id, created_by
    ) VALUES (
        v_project_key, v_feature_id, 'admin_requested', v_comment_id,
        p_created_by
    ) RETURNING id INTO v_request_id;

    INSERT INTO public.ceo_timeline_events (
        project_key, feature_id, event_type, entity_type, entity_id,
        summary, payload, created_by
    ) VALUES (
        v_project_key, v_feature_id, 'reevaluation_requested', 'artifact',
        p_artifact_id, left(btrim(p_comment), 160),
        jsonb_build_object('comment_id', v_comment_id, 'request_id', v_request_id),
        p_created_by
    );

    RETURN QUERY SELECT v_comment_id, v_request_id;
END;
$$;

REVOKE ALL ON FUNCTION public.ceo_create_feature(TEXT, TEXT, TEXT, UUID)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.ceo_latest_artifact_revisions()
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.ceo_save_artifact_revision(UUID, JSONB, UUID, INTEGER)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.ceo_comment_and_request_reevaluation(UUID, TEXT, UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ceo_create_feature(TEXT, TEXT, TEXT, UUID)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.ceo_latest_artifact_revisions()
    TO service_role;
GRANT EXECUTE ON FUNCTION public.ceo_save_artifact_revision(UUID, JSONB, UUID, INTEGER)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.ceo_comment_and_request_reevaluation(UUID, TEXT, UUID)
    TO service_role;
