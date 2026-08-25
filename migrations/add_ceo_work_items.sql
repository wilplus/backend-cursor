-- CEO Phase 2: Product/Research bug capture and agent-ready tasks.
--
-- These work items remain inside CEO. They describe work; they cannot modify
-- repositories, runtime configuration, deployments, experiments, recordings,
-- or research datasets. Product and Research are separated on every row and
-- every feature foreign key.

CREATE TABLE IF NOT EXISTS public.ceo_bugs (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_key           TEXT NOT NULL REFERENCES public.ceo_projects(project_key),
    feature_id            UUID,
    text                  TEXT NOT NULL DEFAULT '',
    attachments           JSONB NOT NULL DEFAULT '[]'::jsonb,
    status                TEXT NOT NULL DEFAULT 'open',
    classification_status TEXT NOT NULL DEFAULT 'pending',
    created_by            UUID,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at           TIMESTAMPTZ,
    legacy_source         TEXT,
    legacy_id             BIGINT,
    CONSTRAINT ceo_bugs_feature_project_fk
        FOREIGN KEY (project_key, feature_id)
        REFERENCES public.ceo_features(project_key, id),
    CONSTRAINT ceo_bugs_content_check
        CHECK (length(btrim(text)) > 0 OR attachments <> '[]'::jsonb),
    CONSTRAINT ceo_bugs_attachments_check
        CHECK (jsonb_typeof(attachments) = 'array'),
    CONSTRAINT ceo_bugs_status_check
        CHECK (status IN ('open', 'archived')),
    CONSTRAINT ceo_bugs_classification_check
        CHECK (classification_status IN ('pending', 'classified', 'failed', 'manual'))
);

CREATE INDEX IF NOT EXISTS ceo_bugs_project_status_created_idx
    ON public.ceo_bugs (project_key, status, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS ceo_bugs_legacy_unique_idx
    ON public.ceo_bugs (legacy_source, legacy_id)
    WHERE legacy_source IS NOT NULL AND legacy_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.ceo_tasks (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_key       TEXT NOT NULL REFERENCES public.ceo_projects(project_key),
    feature_id        UUID,
    bug_id            UUID UNIQUE REFERENCES public.ceo_bugs(id) ON DELETE CASCADE,
    title             TEXT NOT NULL,
    user_story        TEXT,
    body              TEXT NOT NULL,
    attachments       JSONB NOT NULL DEFAULT '[]'::jsonb,
    priority          SMALLINT NOT NULL DEFAULT 2,
    order_key         DOUBLE PRECISION NOT NULL DEFAULT 0,
    status            TEXT NOT NULL DEFAULT 'active',
    generation_status TEXT NOT NULL DEFAULT 'pending',
    manually_edited   BOOLEAN NOT NULL DEFAULT false,
    created_by        UUID,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    done_at           TIMESTAMPTZ,
    archived_at       TIMESTAMPTZ,
    legacy_source     TEXT,
    legacy_id         BIGINT,
    CONSTRAINT ceo_tasks_feature_project_fk
        FOREIGN KEY (project_key, feature_id)
        REFERENCES public.ceo_features(project_key, id),
    CONSTRAINT ceo_tasks_title_check CHECK (length(btrim(title)) > 0),
    CONSTRAINT ceo_tasks_body_check CHECK (length(btrim(body)) > 0),
    CONSTRAINT ceo_tasks_attachments_check
        CHECK (jsonb_typeof(attachments) = 'array'),
    CONSTRAINT ceo_tasks_priority_check CHECK (priority BETWEEN 1 AND 3),
    CONSTRAINT ceo_tasks_status_check
        CHECK (status IN ('active', 'done', 'archived')),
    CONSTRAINT ceo_tasks_generation_check
        CHECK (generation_status IN ('pending', 'ready', 'failed', 'manual'))
);

CREATE INDEX IF NOT EXISTS ceo_tasks_project_status_order_idx
    ON public.ceo_tasks (project_key, status, order_key, id);
CREATE INDEX IF NOT EXISTS ceo_tasks_project_feature_idx
    ON public.ceo_tasks (project_key, feature_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS ceo_tasks_legacy_unique_idx
    ON public.ceo_tasks (legacy_source, legacy_id)
    WHERE legacy_source IS NOT NULL AND legacy_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.ceo_timeline_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_key TEXT NOT NULL REFERENCES public.ceo_projects(project_key),
    feature_id  UUID,
    event_type  TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id   UUID NOT NULL,
    summary     TEXT NOT NULL DEFAULT '',
    payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by  UUID,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ceo_timeline_feature_project_fk
        FOREIGN KEY (project_key, feature_id)
        REFERENCES public.ceo_features(project_key, id),
    CONSTRAINT ceo_timeline_entity_check
        CHECK (entity_type IN ('bug', 'task', 'artifact'))
);

CREATE INDEX IF NOT EXISTS ceo_timeline_project_created_idx
    ON public.ceo_timeline_events (project_key, created_at DESC);

CREATE TABLE IF NOT EXISTS public.ceo_reevaluation_requests (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_key  TEXT NOT NULL REFERENCES public.ceo_projects(project_key),
    feature_id   UUID,
    trigger_type TEXT NOT NULL,
    trigger_id   UUID NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    created_by   UUID,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ,
    CONSTRAINT ceo_reevaluation_feature_project_fk
        FOREIGN KEY (project_key, feature_id)
        REFERENCES public.ceo_features(project_key, id),
    CONSTRAINT ceo_reevaluation_trigger_check
        CHECK (trigger_type IN ('task_completed', 'admin_requested')),
    CONSTRAINT ceo_reevaluation_status_check
        CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    CONSTRAINT ceo_reevaluation_trigger_unique UNIQUE (trigger_type, trigger_id)
);

CREATE INDEX IF NOT EXISTS ceo_reevaluation_pending_idx
    ON public.ceo_reevaluation_requests (status, created_at);

ALTER TABLE public.ceo_bugs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ceo_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ceo_timeline_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ceo_reevaluation_requests ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.ceo_bugs FROM anon, authenticated;
REVOKE ALL ON TABLE public.ceo_tasks FROM anon, authenticated;
REVOKE ALL ON TABLE public.ceo_timeline_events FROM anon, authenticated;
REVOKE ALL ON TABLE public.ceo_reevaluation_requests FROM anon, authenticated;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.ceo_bugs TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.ceo_tasks TO service_role;
GRANT SELECT, INSERT ON TABLE public.ceo_timeline_events TO service_role;
GRANT SELECT, INSERT, UPDATE ON TABLE public.ceo_reevaluation_requests TO service_role;

-- One atomic command guarantees that every accepted bug has exactly one task,
-- even before asynchronous enrichment runs or when the model is unavailable.
CREATE OR REPLACE FUNCTION public.ceo_create_bug_with_task(
    p_project_key TEXT,
    p_text TEXT,
    p_attachments JSONB,
    p_created_by UUID
) RETURNS TABLE (out_bug_id UUID, out_task_id UUID)
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
    v_bug_id UUID;
    v_task_id UUID;
    v_title TEXT;
    v_body TEXT;
    v_order DOUBLE PRECISION;
BEGIN
    IF length(btrim(COALESCE(p_text, ''))) = 0
       AND COALESCE(p_attachments, '[]'::jsonb) = '[]'::jsonb THEN
        RAISE EXCEPTION 'bug content is empty';
    END IF;

    v_title := COALESCE(
        NULLIF(left(btrim(COALESCE(p_text, '')), 100), ''),
        'Review attached bug'
    );
    v_body := 'Investigate and resolve this ' || initcap(p_project_key) ||
        ' bug.' || E'\n\nReported:\n' ||
        COALESCE(NULLIF(btrim(p_text), ''), '[See attachment]') ||
        E'\n\nAcceptance:\n- Reproduce or verify the issue.\n' ||
        '- Implement the smallest durable fix.\n' ||
        '- Add focused regression coverage.';

    SELECT COALESCE(MAX(order_key), 0) + 1000
      INTO v_order
      FROM public.ceo_tasks
     WHERE project_key = p_project_key;

    INSERT INTO public.ceo_bugs (
        project_key, text, attachments, created_by
    ) VALUES (
        p_project_key,
        btrim(COALESCE(p_text, '')),
        COALESCE(p_attachments, '[]'::jsonb),
        p_created_by
    ) RETURNING id INTO v_bug_id;

    INSERT INTO public.ceo_tasks (
        project_key, bug_id, title, body, attachments, priority, order_key,
        generation_status, created_by
    ) VALUES (
        p_project_key, v_bug_id, v_title, v_body,
        COALESCE(p_attachments, '[]'::jsonb), 2, v_order, 'pending', p_created_by
    ) RETURNING id INTO v_task_id;

    INSERT INTO public.ceo_timeline_events (
        project_key, event_type, entity_type, entity_id, summary, created_by
    ) VALUES
        (p_project_key, 'bug_created', 'bug', v_bug_id, v_title, p_created_by),
        (p_project_key, 'task_created', 'task', v_task_id, v_title, p_created_by);

    RETURN QUERY SELECT v_bug_id, v_task_id;
END;
$$;

-- Completion is likewise atomic: the status, immutable timeline event, and
-- request for a later Overview reevaluation either all happen or none do.
CREATE OR REPLACE FUNCTION public.ceo_complete_task(
    p_task_id UUID,
    p_admin_user_id UUID
) RETURNS TABLE (
    out_task_id UUID,
    out_project_key TEXT,
    out_feature_id UUID
)
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
    v_task_id UUID;
    v_project_key TEXT;
    v_feature_id UUID;
    v_title TEXT;
BEGIN
    UPDATE public.ceo_tasks
       SET status = 'done',
           done_at = now(),
           archived_at = NULL,
           updated_at = now()
     WHERE id = p_task_id
       AND status = 'active'
    RETURNING id, project_key, feature_id, title
         INTO v_task_id, v_project_key, v_feature_id, v_title;

    IF v_task_id IS NULL THEN
        RETURN;
    END IF;

    INSERT INTO public.ceo_timeline_events (
        project_key, feature_id, event_type, entity_type, entity_id,
        summary, created_by
    ) VALUES (
        v_project_key, v_feature_id, 'task_completed', 'task', v_task_id,
        v_title, p_admin_user_id
    );

    INSERT INTO public.ceo_reevaluation_requests (
        project_key, feature_id, trigger_type, trigger_id, created_by
    ) VALUES (
        v_project_key, v_feature_id, 'task_completed', v_task_id,
        p_admin_user_id
    ) ON CONFLICT (trigger_type, trigger_id) DO NOTHING;

    RETURN QUERY SELECT v_task_id, v_project_key, v_feature_id;
END;
$$;

REVOKE ALL ON FUNCTION public.ceo_create_bug_with_task(TEXT, TEXT, JSONB, UUID)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.ceo_complete_task(UUID, UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ceo_create_bug_with_task(TEXT, TEXT, JSONB, UUID)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.ceo_complete_task(UUID, UUID)
    TO service_role;

-- Preserve the old founder tool inside Product. Legacy rows are marked so this
-- migration is re-runnable and so their origin remains inspectable.
INSERT INTO public.ceo_bugs (
    project_key, text, attachments, status, classification_status,
    created_at, archived_at, legacy_source, legacy_id
)
SELECT
    'product',
    d.text,
    CASE
        WHEN jsonb_array_length(COALESCE(d.images, '[]'::jsonb)) > 0
            THEN d.images
        WHEN d.image_url IS NOT NULL
            THEN jsonb_build_array(d.image_url)
        ELSE '[]'::jsonb
    END,
    CASE WHEN d.status = 'shipped' THEN 'archived' ELSE 'open' END,
    'manual',
    d.created_at,
    CASE WHEN d.status = 'shipped' THEN COALESCE(d.sent_at, d.created_at) END,
    'dev_bugs',
    d.id
FROM public.dev_bugs d
ON CONFLICT DO NOTHING;

WITH ranked_legacy_tasks AS (
    SELECT
        d.*,
        row_number() OVER (PARTITION BY d.bug_id ORDER BY d.id) AS bug_rank
    FROM public.dev_tasks d
)
INSERT INTO public.ceo_tasks (
    project_key, bug_id, title, user_story, body, attachments, priority,
    order_key, status, generation_status, manually_edited, created_at,
    done_at, legacy_source, legacy_id
)
SELECT
    'product',
    CASE WHEN d.bug_id IS NOT NULL AND d.bug_rank = 1 THEN b.id ELSE NULL END,
    COALESCE(
        NULLIF(left(btrim(COALESCE(d.user_story, '')), 100), ''),
        NULLIF(left(btrim(COALESCE(d.body, '')), 100), ''),
        'Imported task'
    ),
    d.user_story,
    COALESCE(NULLIF(btrim(d.body), ''), 'Review imported task.'),
    COALESCE(d.images, '[]'::jsonb),
    d.priority,
    d.order_key,
    CASE WHEN d.status = 'archived' THEN 'done' ELSE 'active' END,
    'manual',
    true,
    d.created_at,
    CASE WHEN d.status = 'archived' THEN d.archived_at END,
    'dev_tasks',
    d.id
FROM ranked_legacy_tasks d
LEFT JOIN public.ceo_bugs b
  ON b.legacy_source = 'dev_bugs' AND b.legacy_id = d.bug_id
ON CONFLICT DO NOTHING;

-- Old bugs created while task generation was disabled still receive a paired
-- fallback task. This restores the Phase-2 invariant without inventing model
-- output or overwriting any imported task.
INSERT INTO public.ceo_tasks (
    project_key, bug_id, title, body, attachments, priority, order_key,
    status, generation_status, manually_edited, created_at,
    legacy_source, legacy_id
)
SELECT
    b.project_key,
    b.id,
    COALESCE(NULLIF(left(btrim(b.text), 100), ''), 'Review attached bug'),
    'Investigate and resolve this Product bug.' || E'\n\nReported:\n' ||
        COALESCE(NULLIF(btrim(b.text), ''), '[See attachment]'),
    b.attachments,
    2,
    900000000000000 + row_number() OVER (ORDER BY b.created_at, b.id),
    CASE WHEN b.status = 'archived' THEN 'done' ELSE 'active' END,
    'manual',
    true,
    b.created_at,
    'dev_bug_fallback',
    b.legacy_id
FROM public.ceo_bugs b
WHERE b.legacy_source = 'dev_bugs'
  AND NOT EXISTS (
      SELECT 1 FROM public.ceo_tasks t WHERE t.bug_id = b.id
  )
ON CONFLICT DO NOTHING;
