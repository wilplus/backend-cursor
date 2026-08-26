-- Founder-authored revision of the Product CEO ML capability tables.
--
-- Supersedes the v1 table layout with the consolidated Confident Voice and
-- Shadowing capabilities. Prior revisions remain recoverable. Existing risks,
-- next steps, and citations are preserved; the explicit confidence-dataset
-- separation rule is appended once as a safeguard below the table.

WITH
headers(column_id, label, position) AS (
    VALUES
        ('capability', 'Capability', 0),
        ('evidence-input', 'Evidence / input', 1),
        ('current-mechanism', 'Current mechanism', 2),
        ('human-safeguard', 'Human signal / safeguard', 3),
        ('learning-destination', 'Learning destination', 4)
),
capability_rows(
    feature_slug,
    row_id,
    position,
    capability_label,
    capability_detail,
    evidence_label,
    evidence_detail,
    mechanism_label,
    mechanism_detail,
    safeguard_label,
    safeguard_detail,
    destination_label,
    destination_detail
) AS (
    VALUES
        (
            'confident-voice-practice',
            'cv-selection',
            0,
            'Confident Voice Selection',
            'Detects and ranks the strongest available possible Confident Voice moment from the recording.',
            'Confidence Candidate Package',
            'Exact audio interval, seven acoustic features, speaker-relative baseline, transcript alignment, clip quality and version metadata.',
            'Deterministic Seven-Cue Selector',
            'Uses a hardcoded acoustic composite, thresholds and quality gates. There is no trained production confidence classifier yet.',
            'Provenance-Separated Confidence Labels',
            'User self-report, independent blind coach judgment and blind peer labels are stored separately. Peer labels remain internal only.',
            'Speaker-Disjoint Confidence Classifier',
            'Begin with logistic regression trained and evaluated on unseen speakers. Use a neural model only if it demonstrates a meaningful improvement.'
        ),
        (
            'confident-voice-practice',
            'cv-comment',
            1,
            'Confident Voice Comment',
            'Explains why the selected clip may sound confident without overstating uncertain acoustic evidence.',
            'Selected Confidence Evidence',
            'The exact selected audio clip, its transcript phrase and qualitative acoustic evidence supporting the selection.',
            'Evidence-Calibrated Templates',
            'The core card uses deterministic wording rather than GPT-4o. The strength of the language should match the strength of the evidence.',
            'User Calibration and Coach Explanation',
            'The user answers first. A coach can explain agreement or disagreement only after submitting an independent blind judgment.',
            'Deterministic MVP Explanation',
            'Keep this deterministic initially. A future explanation model requires its own evaluated wording corpus and must not use the confidence-classification dataset.'
        ),
        (
            'shadowing',
            'shadow-praise-generation',
            0,
            'Praise Comment Generation',
            'Produces an evidence-backed explanation of something genuinely effective in the user’s presentation.',
            'Praise Evidence Record',
            'An exact transcript span plus the structural, verbal or acoustic evidence supporting the praise.',
            'Guarded Praise Generator',
            'Uses deterministic evidence templates and GPT-4o-mini for constrained wording. It must not invent words or unsupported strengths.',
            'Praise Helpfulness Label',
            'User chooses Useful, Not useful or Not sure. This is stored separately from the paragraph’s Lock or Keep evolving decision.',
            'Praise-Specific Wording Model',
            'Explicit usefulness and coach-correction data may eventually support a dedicated praise SFT/DPO corpus.'
        ),
        (
            'shadowing',
            'shadow-praise-selection',
            1,
            'Praise Selection',
            'Chooses which genuine praise candidate deserves the limited user attention available during a Take.',
            'Complete Praise Candidate Set',
            'All eligible praise candidates, their evidence, scores, thresholds, positions and the candidate eventually shown.',
            'Deterministic Praise Manager',
            'Uses hardcoded gates, caps, coverage and Manager rules. The current Manager does not learn a true ranking function.',
            'Helpfulness and Exposure Outcomes',
            'User helpfulness is the primary outcome. A skipped card remains unanswered, and an unshown candidate is not automatically negative.',
            'Praise Ranking Model',
            'Start with logistic regression after the complete exposure ledger exists. Evaluate learning-to-rank only after establishing a reliable baseline.'
        ),
        (
            'shadowing',
            'shadow-correction-generation',
            2,
            'Verbal Correction Generation',
            'Generates a clearer replacement for an exact part of the user’s presentation without changing it automatically.',
            'Correction Context Record',
            'Original exact text span, paragraph, slide, audience, goal, call to action and relevant project context.',
            'Validated Structured Generation',
            'GPT-4o-mini produces structured output followed by exact-span, locked-text, coherence and quality validation.',
            'Explicit Correction Preference',
            'User accepts the clearer version, keeps the original or leaves it unanswered. A coach may later provide an immutable corrected revision.',
            'Correction-Specific DPO/SFT',
            'Build separate preference corpora for say_it_stronger and moment_suggestion. Do not combine them with praise or confidence data.'
        ),
        (
            'shadowing',
            'shadow-correction-selection',
            3,
            'Verbal Correction Selection',
            'Chooses which valid correction opportunity is important enough to surface to the user.',
            'Correction Candidate Set',
            'All valid correction candidates, evidence spans, locks, prior decisions, slide context and exposure information.',
            'Deterministic Correction Manager',
            'Applies budgets, collision handling, focus rules, slide coverage and locked-text protection. Candidate priority is currently largely rule-based.',
            'User and Coach Outcomes',
            'Acceptance, rejection and coach correction are preserved separately. Complete exposure must be recorded before learning selection.',
            'Dedicated Correction Ranker',
            'Start with logistic regression. This selector must use a different dataset and model from correction text generation.'
        ),
        (
            'shadowing',
            'shadow-ideal-text-generation',
            4,
            'Ideal Text Generation',
            'Builds and iteratively improves the project-specific presentation text across Takes.',
            'Versioned Presentation Context',
            'Slides, transcripts across Takes, project setup, selected formulations, accepted corrections, user edits and locked paragraphs.',
            'Constrained Ideal Text Pipeline',
            'Combines deterministic candidate assembly with low-temperature GPT-4o-mini stitching and final coherence and locked-text quality gates.',
            'User-Controlled Text State',
            'User edits and locks are authoritative. Coach revisions cannot silently overwrite text the user has already accepted.',
            'Dedicated Ideal Text DPO/SFT',
            'Train only from versioned Ideal Text preference and revision pairs belonging to this exact generation surface.'
        ),
        (
            'shadowing',
            'shadow-coach-comment-drafting',
            5,
            'Coach Comment Drafting',
            'Creates a structured starting draft that the coach can review and rewrite before publication.',
            'Coach Draft Context',
            'Transcript, slide, presentation goal, exact evidence, qualitative acoustic observations and relevant Take comparison.',
            'Structured Coach Draft Generator',
            'GPT-4o-mini generates a draft while preserving exact evidence references and the distinction between machine suggestion and coach judgment.',
            'Coach Draft-to-Final Revision',
            'The coach’s published version is stored separately from the generated draft, creating an explicit preferred-versus-rejected pair.',
            'Coach-Comment DPO/SFT',
            'Use a dedicated coach_comment_draft corpus. Never combine these preferences with user-facing praise or correction datasets.'
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
                        'label', cell.label,
                        'detail', cell.detail
                    )
                    ORDER BY row.position, cell.position
                )
                FROM capability_rows row
                CROSS JOIN LATERAL (
                    VALUES
                        ('capability', row.capability_label, row.capability_detail, 0),
                        ('evidence-input', row.evidence_label, row.evidence_detail, 1),
                        ('current-mechanism', row.mechanism_label, row.mechanism_detail, 2),
                        ('human-safeguard', row.safeguard_label, row.safeguard_detail, 3),
                        ('learning-destination', row.destination_label, row.destination_detail, 4)
                ) AS cell(column_id, label, detail, position)
                WHERE row.feature_slug = seed.feature_slug
            ),
            'edges', '[]'::jsonb
        ) AS content
    FROM feature_seeds seed
),
target_artifacts AS (
    SELECT
        artifact.id AS artifact_id,
        seed.feature_slug,
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
            'risks', CASE
                WHEN target.feature_slug = 'confident-voice-practice' THEN
                    COALESCE(target.latest_content->'risks', '[]'::jsonb)
                    || jsonb_build_array(jsonb_build_object(
                        'id', 'cv-confidence-data-rule',
                        'text', 'Confident Voice data rule — Confidence labels train the classifier. They do not train praise generation, verbal corrections or general text rewriting.'
                    ))
                ELSE COALESCE(target.latest_content->'risks', '[]'::jsonb)
            END,
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
    'founder_seed_ceo_ml_capability_tables_v2'
FROM versioned
WHERE NOT EXISTS (
    SELECT 1
    FROM public.ceo_artifact_revisions existing
    WHERE existing.artifact_id = versioned.artifact_id
      AND existing.created_by = 'founder_seed_ceo_ml_capability_tables_v2'
);
