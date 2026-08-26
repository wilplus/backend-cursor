-- Founder-authored learning summary for the Product CEO ML tables.
--
-- Confident Voice Practice owns the first row. Shadowing owns the remaining
-- six rows. Previous artifact revisions remain recoverable, while existing
-- risks, next steps, and citations remain attached to the new table revision.

WITH
headers(column_id, label, position) AS (
    VALUES
        ('app-component', 'App component', 0),
        ('learning-target', 'What it will learn', 1),
        ('training-signal', 'Training signal', 2),
        ('likely-model', 'Likely model', 3)
),
capability_rows(
    feature_slug,
    row_id,
    position,
    app_component,
    learning_target,
    training_signal,
    likely_model
) AS (
    VALUES
        (
            'confident-voice-practice',
            'learning-confident-voice-detection-selection',
            0,
            'Confident Voice detection/selection',
            'Which audio moments humans perceive as confident',
            'Separate user, blind coach and blind peer labels',
            'Logistic regression first; neural classifier only if better'
        ),
        (
            'shadowing',
            'learning-praise-wording',
            0,
            'Praise wording',
            'How to explain a genuine strength usefully and naturally',
            'Useful/not useful plus coach-improved wording',
            'Dedicated SFT/DPO language model'
        ),
        (
            'shadowing',
            'learning-praise-selection',
            1,
            'Praise selection',
            'Which genuine praise candidate is most useful to show',
            'Complete candidate exposure plus helpfulness response',
            'Logistic ranker, later learning-to-rank'
        ),
        (
            'shadowing',
            'learning-verbal-correction-wording',
            2,
            'Verbal correction wording',
            'How to rewrite an exact phrase more clearly while preserving intent',
            'Accept/keep-original decisions and coach corrections',
            'Dedicated SFT/DPO language model'
        ),
        (
            'shadowing',
            'learning-verbal-correction-selection',
            3,
            'Verbal correction selection',
            'Which clarity problem is important enough to surface',
            'Candidate exposure, user decision and coach outcome',
            'Separate logistic/ranking model'
        ),
        (
            'shadowing',
            'learning-ideal-text-generation',
            4,
            'Ideal Text generation',
            'How to assemble a stronger presentation while respecting accepted and locked text',
            'User edits, explicit correction choices and coach revisions',
            'Dedicated Ideal Text SFT/DPO model'
        ),
        (
            'shadowing',
            'learning-coach-comment-drafting',
            5,
            'Coach comment drafting',
            'How to produce a better first draft for the coach',
            'Generated draft versus coach’s final version',
            'Dedicated coach-comment SFT/DPO model'
        )
),
feature_seeds AS (
    SELECT DISTINCT row.feature_slug
    FROM capability_rows row
),
seed_content AS (
    SELECT
        seed.feature_slug,
        jsonb_build_object(
            'columns', (
                SELECT jsonb_agg(
                    jsonb_build_object('id', header.column_id, 'label', header.label)
                    ORDER BY header.position
                )
                FROM headers header
            ),
            'rows', (
                SELECT jsonb_agg(
                    jsonb_build_object('id', row.row_id)
                    ORDER BY row.position
                )
                FROM capability_rows row
                WHERE row.feature_slug = seed.feature_slug
            ),
            'nodes', (
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'id', row.row_id || '-' || cell.column_id,
                        'row_id', row.row_id,
                        'column_id', cell.column_id,
                        'label', cell.value,
                        'detail', ''
                    )
                    ORDER BY row.position, cell.position
                )
                FROM capability_rows row
                CROSS JOIN LATERAL (
                    VALUES
                        ('app-component', row.app_component, 0),
                        ('learning-target', row.learning_target, 1),
                        ('training-signal', row.training_signal, 2),
                        ('likely-model', row.likely_model, 3)
                ) AS cell(column_id, value, position)
                WHERE row.feature_slug = seed.feature_slug
            ),
            'edges', '[]'::jsonb
        ) AS content
    FROM feature_seeds seed
),
target_artifacts AS (
    SELECT
        artifact.id AS artifact_id,
        seed.content,
        latest.content AS latest_content
    FROM seed_content seed
    JOIN public.ceo_features feature
      ON feature.project_key = 'product'
     AND feature.slug = seed.feature_slug
    JOIN public.ceo_artifacts artifact
      ON artifact.feature_id = feature.id
     AND artifact.project_key = feature.project_key
     AND artifact.scope_kind = 'feature'
     AND artifact.lens = 'ml'
     AND artifact.artifact_kind = 'ml_system_map'
    LEFT JOIN LATERAL (
        SELECT revision.content
        FROM public.ceo_artifact_revisions revision
        WHERE revision.artifact_id = artifact.id
          AND revision.status = 'official'
        ORDER BY revision.version DESC
        LIMIT 1
    ) latest ON true
),
merged_content AS (
    SELECT
        target.artifact_id,
        target.content || jsonb_build_object(
            'risks', COALESCE(target.latest_content->'risks', '[]'::jsonb),
            'next_steps', COALESCE(target.latest_content->'next_steps', '[]'::jsonb),
            'citations', COALESCE(target.latest_content->'citations', '[]'::jsonb)
        ) AS content
    FROM target_artifacts target
),
versioned AS (
    SELECT
        merged.artifact_id,
        merged.content,
        COALESCE(MAX(revision.version), 0) + 1 AS next_version
    FROM merged_content merged
    LEFT JOIN public.ceo_artifact_revisions revision
      ON revision.artifact_id = merged.artifact_id
    GROUP BY merged.artifact_id, merged.content
)
INSERT INTO public.ceo_artifact_revisions (
    artifact_id, version, content, ownership, status, created_by
)
SELECT
    versioned.artifact_id,
    versioned.next_version,
    versioned.content,
    'manual',
    'official',
    'founder_seed_ceo_ml_learning_table_v3'
FROM versioned
WHERE NOT EXISTS (
    SELECT 1
    FROM public.ceo_artifact_revisions existing
    WHERE existing.artifact_id = versioned.artifact_id
      AND existing.created_by = 'founder_seed_ceo_ml_learning_table_v3'
);
