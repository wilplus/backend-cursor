-- Founder-authored learning implementation urgency for CEO ML tables.
--
-- The numbering spans both Product features: Confident Voice Practice owns
-- item 1, and Shadowing owns items 2–7. It communicates implementation
-- urgency, not product importance. Previous revisions remain recoverable.

WITH
headers(column_id, label, position) AS (
    VALUES
        ('capability', 'Learning capability', 0),
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
            'learning-1-confident-voice-classifier',
            0,
            '1. Confident Voice Classifier',
            'Most urgent. Learns which valid audio intervals people perceive as confident.',
            'Speaker-Linked Confidence Evidence',
            'Exact audio interval, seven acoustic features, speaker-relative baseline, alignment, clip quality and version metadata.',
            'Deterministic Seven-Cue Scoring',
            'Hardcoded acoustic weights, thresholds and quality gates. The highest eligible score is selected deterministically.',
            'Blind, Provenance-Separated Labels',
            'User self-report, blind coach judgment and blind peer rating remain independent. Audio unclear is excluded from the confidence target.',
            'Speaker-Disjoint Supervised Classifier',
            'Start with logistic regression. Consider a neural classifier only if it performs materially better on unseen speakers.'
        ),
        (
            'shadowing',
            'learning-2-verbal-correction-generator',
            0,
            '2. Verbal-Correction Generator',
            'Learns how to rewrite an exact phrase more clearly without changing the user’s intended meaning.',
            'Correction Generation Record',
            'Original exact text span, paragraph, slide, audience, goal, call to action, project context and locked-text state.',
            'Validated GPT-4o-mini Generation',
            'Structured generation followed by deterministic exact-span, coherence and locked-text validation.',
            'Explicit Text Preference',
            'User accepts the replacement, keeps the original or leaves it unanswered. Coach corrections create immutable revisions.',
            'Surface-Specific Correction SFT/DPO',
            'Train say_it_stronger and moment_suggestion from their own preference releases. Do not mix them blindly.'
        ),
        (
            'shadowing',
            'learning-3-coach-comment-generator',
            1,
            '3. Coach-Comment Generator',
            'Learns to produce a better first draft for the coach while leaving publication under human control.',
            'Coach Draft Context',
            'Transcript, slide, presentation goal, exact evidence, qualitative observations and relevant Take comparison.',
            'Structured GPT-4o-mini Drafting',
            'Produces a versioned draft attached to exact evidence. It is never published automatically.',
            'Coach Draft-to-Final Pair',
            'The original machine draft and the coach’s published revision are both retained as an explicit preference pair.',
            'Dedicated Coach-Comment SFT/DPO',
            'Train only from reviewed coach draft-to-final examples belonging to the coach_comment_draft surface.'
        ),
        (
            'shadowing',
            'learning-4-praise-wording-generator',
            2,
            '4. Praise Wording Generator',
            'Learns how to explain genuine strengths in language that feels useful, specific and credible.',
            'Evidence-Backed Praise Record',
            'Exact transcript span plus structural, verbal or acoustic evidence supporting the positive observation.',
            'Templates and Guarded GPT-4o-mini',
            'Evidence templates constrain generated wording so praise cannot invent words or unsupported strengths.',
            'Praise Helpfulness Signal',
            'User chooses Useful, Not useful or Not sure. Coach-improved wording may provide stronger preference pairs.',
            'Dedicated Praise SFT/DPO',
            'Train praise wording separately from confidence explanations, corrections and coach comments.'
        ),
        (
            'shadowing',
            'learning-5-praise-selector',
            3,
            '5. Praise Selector',
            'Learns which valid positive observation is most useful to surface during a particular Take.',
            'Complete Praise Exposure Record',
            'Every available candidate, its evidence and score, the candidate shown, its position and selector version.',
            'Deterministic Manager Rules',
            'Hardcoded thresholds, lane budgets, caps and slide-coverage rules currently determine what appears.',
            'Helpfulness After Exposure',
            'Useful, Not useful and Not sure apply only to the shown candidate. Skip remains unanswered; unshown does not mean rejected.',
            'Praise Ranking Model',
            'Start with logistic regression after the exposure ledger is complete. Evaluate learning-to-rank later.'
        ),
        (
            'shadowing',
            'learning-6-verbal-correction-selector',
            4,
            '6. Verbal-Correction Selector',
            'Learns which valid clarity or structure problem most deserves the user’s limited attention.',
            'Complete Correction Candidate Set',
            'All validated candidates, evidence spans, locks, prior decisions, slide context, scores and exposure metadata.',
            'Deterministic Correction Manager',
            'Uses budgets, collisions, focus rules, slide coverage and locked-text protection. Ranking is currently largely rule-based.',
            'Correction Outcome Signal',
            'User accept/keep decisions and coach outcomes remain separate. Unanswered and unshown candidates are not negatives.',
            'Dedicated Correction Ranker',
            'Start with an interpretable logistic model. Keep it separate from the model that generates correction wording.'
        ),
        (
            'shadowing',
            'learning-7-ideal-text-generator',
            5,
            '7. Ideal Text Generator',
            'Least urgent to train because it is the broadest and highest-risk learning surface.',
            'Versioned Presentation State',
            'Slides, transcripts across Takes, setup context, accepted corrections, user edits, selected formulations and paragraph locks.',
            'Constrained Ideal Text Pipeline',
            'Deterministic assembly plus low-temperature GPT-4o-mini stitching, coherence checks and locked-text quality gates.',
            'Authoritative User and Coach Revisions',
            'User edits and locks remain authoritative. Coach revisions cannot silently overwrite previously accepted text.',
            'Dedicated Ideal Text SFT/DPO',
            'Train only after the narrower systems are reliable and an evaluation suite proves meaning, locks and project boundaries are preserved.'
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
            'next_steps',
                COALESCE(target.latest_content->'next_steps', '[]'::jsonb)
                || jsonb_build_array(jsonb_build_object(
                    'id', 'learning-implementation-urgency-rule',
                    'text', 'The numbering represents recommended learning implementation urgency, not product importance. Systems with cleaner labels and lower training risk come first.'
                )),
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
    'founder_seed_ceo_ml_learning_urgency_v3'
FROM versioned
WHERE NOT EXISTS (
    SELECT 1
    FROM public.ceo_artifact_revisions existing
    WHERE existing.artifact_id = versioned.artifact_id
      AND existing.created_by = 'founder_seed_ceo_ml_learning_urgency_v3'
);
