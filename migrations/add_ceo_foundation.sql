-- CEO foundation: the admin-only abstract of Product and Research.
--
-- CEO is observational. These tables hold its own taxonomy, documents, and
-- per-admin navigation state; no foreign key points into the application
-- runtime, experiment, recording, or research datasets. Later ingestion jobs
-- may cite those systems through immutable source snapshots, but must not
-- acquire write authority over them.
--
-- Phase 1 intentionally creates only the stable core:
--   Project -> optional Feature -> Lens -> versioned Artifact
-- plus the last view selected by each admin. Bugs, tasks, evidence, analysis
-- runs, proposals, and settings operations are separate later migrations.

CREATE TABLE IF NOT EXISTS public.ceo_projects (
    project_key TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    position    SMALLINT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ceo_projects_key_check
        CHECK (project_key IN ('product', 'research')),
    CONSTRAINT ceo_projects_position_check CHECK (position >= 0)
);

CREATE TABLE IF NOT EXISTS public.ceo_features (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_key TEXT NOT NULL REFERENCES public.ceo_projects(project_key),
    slug        TEXT NOT NULL,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    position    INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at TIMESTAMPTZ,
    CONSTRAINT ceo_features_project_slug_unique UNIQUE (project_key, slug),
    CONSTRAINT ceo_features_project_id_unique UNIQUE (project_key, id),
    CONSTRAINT ceo_features_position_check CHECK (position >= 0),
    CONSTRAINT ceo_features_status_check CHECK (status IN ('active', 'archived'))
);

CREATE INDEX IF NOT EXISTS ceo_features_project_order_idx
    ON public.ceo_features (project_key, status, position, id);

CREATE TABLE IF NOT EXISTS public.ceo_artifacts (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_key       TEXT NOT NULL REFERENCES public.ceo_projects(project_key),
    scope_kind        TEXT NOT NULL,
    feature_id        UUID,
    lens              TEXT NOT NULL,
    artifact_kind     TEXT NOT NULL,
    default_ownership TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ceo_artifacts_feature_project_fk
        FOREIGN KEY (project_key, feature_id)
        REFERENCES public.ceo_features(project_key, id),
    CONSTRAINT ceo_artifacts_scope_check CHECK (
        (scope_kind = 'project' AND feature_id IS NULL)
        OR (scope_kind = 'feature' AND feature_id IS NOT NULL)
    ),
    CONSTRAINT ceo_artifacts_lens_check
        CHECK (lens IN ('architecture', 'ml', 'vision')),
    CONSTRAINT ceo_artifacts_kind_check CHECK (
        artifact_kind IN ('architecture_spec', 'ml_system_map', 'vision_document')
    ),
    CONSTRAINT ceo_artifacts_lens_kind_check CHECK (
        (lens = 'architecture' AND artifact_kind = 'architecture_spec')
        OR (lens = 'ml' AND artifact_kind = 'ml_system_map')
        OR (lens = 'vision' AND artifact_kind = 'vision_document')
    ),
    CONSTRAINT ceo_artifacts_ownership_check
        CHECK (default_ownership IN ('manual', 'generated')),
    CONSTRAINT ceo_artifacts_vision_manual_check CHECK (
        lens <> 'vision' OR default_ownership = 'manual'
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS ceo_artifacts_project_address_unique_idx
    ON public.ceo_artifacts (project_key, lens, artifact_kind)
    WHERE scope_kind = 'project';

CREATE UNIQUE INDEX IF NOT EXISTS ceo_artifacts_feature_address_unique_idx
    ON public.ceo_artifacts (project_key, feature_id, lens, artifact_kind)
    WHERE scope_kind = 'feature';

CREATE TABLE IF NOT EXISTS public.ceo_artifact_revisions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_id  UUID NOT NULL REFERENCES public.ceo_artifacts(id),
    version      INTEGER NOT NULL,
    content      JSONB NOT NULL DEFAULT '{}'::jsonb,
    ownership    TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'official',
    created_by   TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ceo_artifact_revisions_version_unique UNIQUE (artifact_id, version),
    CONSTRAINT ceo_artifact_revisions_version_check CHECK (version > 0),
    CONSTRAINT ceo_artifact_revisions_ownership_check
        CHECK (ownership IN ('manual', 'generated')),
    CONSTRAINT ceo_artifact_revisions_status_check
        CHECK (status IN ('official', 'preview'))
);

CREATE INDEX IF NOT EXISTS ceo_artifact_revisions_latest_idx
    ON public.ceo_artifact_revisions (artifact_id, version DESC);

CREATE TABLE IF NOT EXISTS public.ceo_admin_view_state (
    admin_user_id    UUID NOT NULL,
    project_key      TEXT NOT NULL REFERENCES public.ceo_projects(project_key),
    surface          TEXT NOT NULL DEFAULT 'bugs',
    active_feature_id UUID,
    active_lens      TEXT NOT NULL DEFAULT 'architecture',
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (admin_user_id, project_key),
    CONSTRAINT ceo_admin_view_state_feature_project_fk
        FOREIGN KEY (project_key, active_feature_id)
        REFERENCES public.ceo_features(project_key, id),
    CONSTRAINT ceo_admin_view_state_surface_check
        CHECK (surface IN ('overview', 'bugs', 'tasks', 'settings')),
    CONSTRAINT ceo_admin_view_state_lens_check
        CHECK (active_lens IN ('architecture', 'ml', 'vision')),
    CONSTRAINT ceo_admin_view_state_surface_feature_check CHECK (
        surface IN ('overview', 'tasks') OR active_feature_id IS NULL
    )
);

-- Service-role only. The browser reaches CEO exclusively through admin JWT
-- routes; authenticated and anonymous PostgREST clients receive no table API.
ALTER TABLE public.ceo_projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ceo_features ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ceo_artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ceo_artifact_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ceo_admin_view_state ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.ceo_projects FROM anon, authenticated;
REVOKE ALL ON TABLE public.ceo_features FROM anon, authenticated;
REVOKE ALL ON TABLE public.ceo_artifacts FROM anon, authenticated;
REVOKE ALL ON TABLE public.ceo_artifact_revisions FROM anon, authenticated;
REVOKE ALL ON TABLE public.ceo_admin_view_state FROM anon, authenticated;

GRANT SELECT, INSERT, UPDATE ON TABLE public.ceo_projects TO service_role;
GRANT SELECT, INSERT, UPDATE ON TABLE public.ceo_features TO service_role;
GRANT SELECT, INSERT, UPDATE ON TABLE public.ceo_artifacts TO service_role;
GRANT SELECT, INSERT, UPDATE ON TABLE public.ceo_artifact_revisions TO service_role;
GRANT SELECT, INSERT, UPDATE ON TABLE public.ceo_admin_view_state TO service_role;

-- Seed the two hard boundaries and the founder-defined first feature set.
-- ON CONFLICT never overwrites later manual naming, ordering, or descriptions.
INSERT INTO public.ceo_projects (project_key, name, position)
VALUES ('product', 'Product', 0), ('research', 'Research', 1)
ON CONFLICT (project_key) DO NOTHING;

INSERT INTO public.ceo_features (project_key, slug, name, position)
VALUES
    ('product', 'confident-voice-practice', 'Confident Voice Practice', 0),
    ('product', 'stress-reduction', 'Stress Reduction', 1),
    ('product', 'strategy-and-principles', 'Strategy & Principles', 2),
    ('research', 'confident-voice-lowering-stress',
        'Confident Voice — Lowering Stress', 0),
    ('research', 'challenge-threat-state-from-voice',
        'Recognizing Challenge and Threat Cognitive States From Voice', 1)
ON CONFLICT (project_key, slug) DO NOTHING;

-- Every project and feature receives the same fixed lenses. They are empty
-- until an admin writes Vision or a later approved analysis creates an
-- Architecture/ML revision.
WITH lens_seed(lens, artifact_kind, ownership) AS (
    VALUES
        ('architecture', 'architecture_spec', 'generated'),
        ('ml', 'ml_system_map', 'generated'),
        ('vision', 'vision_document', 'manual')
)
INSERT INTO public.ceo_artifacts (
    project_key, scope_kind, feature_id, lens, artifact_kind, default_ownership
)
SELECT p.project_key, 'project', NULL, l.lens, l.artifact_kind, l.ownership
FROM public.ceo_projects p CROSS JOIN lens_seed l
ON CONFLICT DO NOTHING;

WITH lens_seed(lens, artifact_kind, ownership) AS (
    VALUES
        ('architecture', 'architecture_spec', 'generated'),
        ('ml', 'ml_system_map', 'generated'),
        ('vision', 'vision_document', 'manual')
)
INSERT INTO public.ceo_artifacts (
    project_key, scope_kind, feature_id, lens, artifact_kind, default_ownership
)
SELECT f.project_key, 'feature', f.id, l.lens, l.artifact_kind, l.ownership
FROM public.ceo_features f CROSS JOIN lens_seed l
ON CONFLICT DO NOTHING;

-- A seeded revision means the UI has a real, versioned empty state from day
-- one. It does not pretend an analysis ran: generated lenses contain no
-- sections and identify system_seed as their creator; Vision is an empty
-- manual document, as specified by the founder.
INSERT INTO public.ceo_artifact_revisions (
    artifact_id, version, content, ownership, status, created_by
)
SELECT
    a.id,
    1,
    CASE
        WHEN a.lens = 'vision' THEN '{"document":""}'::jsonb
        ELSE '{"sections":[]}'::jsonb
    END,
    a.default_ownership,
    'official',
    'system_seed'
FROM public.ceo_artifacts a
WHERE NOT EXISTS (
    SELECT 1 FROM public.ceo_artifact_revisions r
    WHERE r.artifact_id = a.id
);
