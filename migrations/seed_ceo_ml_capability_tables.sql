-- Founder-authored ML capability tables for the Product CEO tree.
--
-- This migration appends one recoverable manual revision to the ML artifacts
-- for Confident Voice Practice and Shadowing. It never changes runtime data,
-- model behavior, labels, or the blind-coach boundary. Re-running it cannot
-- overwrite a later admin edit because the created_by marker is inserted once.

-- Shadowing may already have been created through CEO. Ensure the canonical
-- feature exists so a fresh environment receives the same Product tree.
INSERT INTO public.ceo_features (
    project_key, slug, name, description, position
)
VALUES ('product', 'shadowing', 'Shadowing', '', 3)
ON CONFLICT (project_key, slug) DO NOTHING;

WITH lens_seed(lens, artifact_kind, ownership) AS (
    VALUES
        ('architecture', 'architecture_spec', 'generated'),
        ('ml', 'ml_system_map', 'generated'),
        ('vision', 'vision_document', 'manual')
)
INSERT INTO public.ceo_artifacts (
    project_key, scope_kind, feature_id, lens, artifact_kind,
    default_ownership
)
SELECT
    feature.project_key,
    'feature',
    feature.id,
    lens.lens,
    lens.artifact_kind,
    lens.ownership
FROM public.ceo_features feature
CROSS JOIN lens_seed lens
WHERE feature.project_key = 'product'
  AND feature.slug = 'shadowing'
ON CONFLICT DO NOTHING;

-- Give any newly-created non-ML Shadowing artifacts their normal empty first
-- revision. The ML artifact receives the founder table below instead.
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
    'system_seed'
FROM public.ceo_artifacts artifact
JOIN public.ceo_features feature ON feature.id = artifact.feature_id
WHERE feature.project_key = 'product'
  AND feature.slug = 'shadowing'
  AND artifact.lens IN ('architecture', 'vision')
  AND NOT EXISTS (
      SELECT 1
      FROM public.ceo_artifact_revisions revision
      WHERE revision.artifact_id = artifact.id
  );

WITH
headers(column_id, label, position) AS (
    VALUES
        ('capability', 'Capability', 0),
        ('evidence-input', 'Evidence / Input', 1),
        ('current-mechanism', 'Current mechanism', 2),
        ('human-safeguard', 'Human signal / safeguard', 3),
        ('learning-destination', 'Learning destination', 4)
),
capability_rows(
    feature_slug,
    row_id,
    position,
    capability,
    evidence_input,
    current_mechanism,
    human_safeguard,
    learning_destination
) AS (
    VALUES
        (
            'confident-voice-practice',
            'cv-candidate-detection',
            0,
            'Confident Voice candidate detection',
            'Audio interval, acoustic features and speaker-relative baseline',
            'Deterministic seven-cue acoustic score with hardcoded weights and thresholds',
            'Candidate is presented as possible, not objective truth',
            'Supervised confidence classifier; logistic regression as the first baseline'
        ),
        (
            'confident-voice-practice',
            'cv-candidate-selection',
            1,
            'Confident Voice candidate selection',
            'Candidate scores, acoustic evidence, clip quality and take context',
            'Deterministic ranking and quality gates',
            'User responses must not retroactively change which clips were exposed',
            'Evaluated selector trained from an immutable exposure ledger'
        ),
        (
            'confident-voice-practice',
            'cv-user-self-report',
            2,
            'User confidence self-report',
            'Exact audio clip and its project, take, slide and paragraph references',
            'Five-state structured response: Yes, In-between, No, Not sure, Audio unclear',
            'Immutable self-report; kept separate from machine, coach and peer labels',
            'Clean user-label dataset; not automatically treated as ground truth'
        ),
        (
            'confident-voice-practice',
            'cv-blind-coach-judgment',
            3,
            'Blind coach confidence judgment',
            'Exact audio clip without user or machine answers',
            'Independent five-state coach rating',
            'User and machine labels revealed only after the coach submits an immutable judgment',
            'High-quality supervised evaluation and training labels'
        ),
        (
            'confident-voice-practice',
            'cv-blind-peer-judgment',
            4,
            'Blind peer confidence judgment',
            'Exact audio clip without contextual feedback',
            'Independent five-state peer rating',
            'Internal training/evaluation only; never controls user feedback or styling',
            'Additional evaluation data with peer provenance preserved'
        ),
        (
            'confident-voice-practice',
            'cv-explanation',
            5,
            'Confidence explanation',
            'Acoustic evidence and the user’s answer',
            'Deterministic, evidence-calibrated explanation',
            'A No must only be acknowledged; uncertain evidence must not produce exaggerated praise',
            'Remain deterministic for MVP; evaluate a separate explanation model later'
        ),
        (
            'confident-voice-practice',
            'cv-styling-eligibility',
            6,
            'Project styling eligibility',
            'Machine result plus user response',
            'Deterministic rule: user Yes may permit styling; user No blocks it',
            'Styling always requires an explicit user decision',
            'Remain deterministic'
        ),
        (
            'confident-voice-practice',
            'cv-album-admission',
            7,
            'Voice Album admission',
            'Machine Yes, user Yes and coach Yes for the same exact clip',
            'Deterministic three-signal admission rule',
            'Coach evaluates the specific clip independently; no peer-vote influence',
            'Remain deterministic and explainable'
        ),
        (
            'shadowing',
            'shadow-praise-generation',
            0,
            'Praise candidate generation',
            'Exact transcript span, paragraph context and supporting evidence',
            'Templates and guarded GPT-4o-mini generation',
            'Praise cannot invent words or claim unsupported strengths',
            'Praise-specific SFT/DPO model'
        ),
        (
            'shadowing',
            'shadow-praise-selection',
            1,
            'Praise candidate selection',
            'Complete candidate set, evidence, scores and slide coverage',
            'Hardcoded thresholds plus deterministic Manager rules',
            'Weak candidates require modest language; showing an item is not a positive label',
            'Logistic selection baseline, followed by learning-to-rank if justified'
        ),
        (
            'shadowing',
            'shadow-praise-helpfulness',
            2,
            'Praise helpfulness',
            'Exact shown praise, its evidence and exposure metadata',
            'Structured response: Useful, Not useful, Not sure',
            'Stored separately from locking; skipping remains unanswered',
            'Training and evaluation signal for praise generation and selection'
        ),
        (
            'shadowing',
            'shadow-correction-generation',
            3,
            'Verbal correction generation',
            'Original text span, paragraph, slide, audience, goal and context',
            'Structured GPT-4o-mini output with exact-span validation',
            'User sees a proposal; no text changes before explicit acceptance',
            'Verbal-correction-specific SFT/DPO model'
        ),
        (
            'shadowing',
            'shadow-correction-selection',
            4,
            'Verbal correction selection',
            'Valid correction candidates, evidence, locks, prior decisions and slide coverage',
            'Deterministic Manager budgets, collision rules and focus rules',
            'Must preserve locked text and may return no correction when none is defensible',
            'Separate correction ranker after clean exposure data exists'
        ),
        (
            'shadowing',
            'shadow-correction-decision',
            5,
            'Correction decision',
            'Shown original text and proposed replacement',
            'Use clearer version, Keep mine or no response',
            'Accept applies the change; Keep mine rejects it; no response remains unresolved',
            'Preference pairs for the verbal-correction DPO dataset'
        ),
        (
            'shadowing',
            'shadow-ideal-text-generation',
            6,
            'Ideal Text generation',
            'Slides, transcripts, setup information, accepted changes and locked paragraphs',
            'Deterministic assembly plus constrained GPT-4o-mini stitching and quality gates',
            'Accepted and locked text cannot be silently overwritten',
            'Dedicated Ideal Text SFT/DPO model'
        ),
        (
            'shadowing',
            'shadow-roadmap-decision',
            7,
            'Paragraph roadmap decision',
            'Current paragraph, accepted phrase and user decision',
            'Deterministic Lock for next Take or Keep evolving state',
            'Independent from whether praise was useful',
            'Remain deterministic'
        ),
        (
            'shadowing',
            'shadow-coach-refinement',
            8,
            'Coach correction and refinement',
            'Machine recommendation, exact evidence, project context and coach’s final version',
            'Structured coach drafting and immutable revision history',
            'Coach can supersede reasoning but cannot silently overwrite accepted user text',
            'Surface-specific coach-correction DPO/SFT datasets'
        ),
        (
            'shadowing',
            'shadow-feedback-orchestration',
            9,
            'Three-item feedback orchestration',
            'Best available confidence, correction and praise candidates',
            'Deterministic Manager with lane priorities and substitution rules',
            'Preserve provenance; weak evidence must not become false certainty',
            'Remain deterministic initially; individual selectors may learn independently'
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
                        ('capability', row.capability, 0),
                        ('evidence-input', row.evidence_input, 1),
                        ('current-mechanism', row.current_mechanism, 2),
                        ('human-safeguard', row.human_safeguard, 3),
                        ('learning-destination', row.learning_destination, 4)
                ) AS cell(column_id, value, position)
                WHERE row.feature_slug = seed.feature_slug
            ),
            'edges', '[]'::jsonb,
            'risks', '[]'::jsonb,
            'next_steps', '[]'::jsonb,
            'citations', '[]'::jsonb
        ) AS content
    FROM feature_seeds seed
),
target_artifacts AS (
    SELECT
        artifact.id AS artifact_id,
        seed.content || jsonb_build_object(
            'risks', COALESCE(latest.content->'risks', '[]'::jsonb),
            'next_steps', COALESCE(latest.content->'next_steps', '[]'::jsonb),
            'citations', COALESCE(latest.content->'citations', '[]'::jsonb)
        ) AS content
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
versioned AS (
    SELECT
        target.artifact_id,
        target.content,
        COALESCE(MAX(revision.version), 0) + 1 AS next_version
    FROM target_artifacts target
    LEFT JOIN public.ceo_artifact_revisions revision
      ON revision.artifact_id = target.artifact_id
    GROUP BY target.artifact_id, target.content
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
    'founder_seed_ceo_ml_capability_tables_v1'
FROM versioned
WHERE NOT EXISTS (
    SELECT 1
    FROM public.ceo_artifact_revisions existing
    WHERE existing.artifact_id = versioned.artifact_id
      AND existing.created_by = 'founder_seed_ceo_ml_capability_tables_v1'
);
