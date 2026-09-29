-- 0395 · Module 8 is counted (founder 2026-09-29, decision 2; audit G-5, the
-- 29 Sep report's item Q7).
--
-- EIGHT LEARNING SURFACES, SEVEN PACKETS. The registry ml_learning_surfaces
-- has held eight rows since 0313 inserted exercise_adequacy_classification,
-- the learner that will one day rank exercises by which ones helped. Three
-- Python sets, the dataset-release CHECKs (0300), the readiness report (0301)
-- and three tests went on saying seven, so the eighth read as forgotten, and
-- nothing wrote down that it was different on purpose. This migration and
-- services/learning_surfaces.py write it down and make the lists agree.
--
-- WHY THE PACKET AND RECEIPT TABLES (0299) STAY AT SEVEN. A presentation
-- packet freezes what a Feedback card showed; an exercise is not shown as a
-- frozen packet but as a card that plays a coach's video, and its exposure
-- is recorded once per frozen 80/20 assignment when the speaker's own client
-- confirms the card rendered (confident_voice_exercise_exposures, 0387). Its
-- label is the practice outcome (exercise-adequacy-label-v1,
-- practice_more_confident_outcomes), never a speaker's or a coach's answer
-- about the exercise. It therefore needs no seven-surface packet and gets
-- none; the 0299 CHECKs are correct as they are.
--
-- WHAT CHANGES.
--   * dataset_releases and dataset_release_items: the learning_surface CHECKs
--     name eight, so a release manifest MAY name module 8 like any surface.
--     Whether one is ever authorized is a separate founder decision; the
--     constants that would let a release run (MLC2_DATASET_RELEASES_ENABLED
--     and its siblings) stay False and ml_contract_epochs' CHECK stays.
--   * get_seven_surface_readiness_v1 returns eight rows. Row 8 is read from
--     the exercise tables: prepared = frozen assignments, visible exposures =
--     confirmed renders, shown = distinct assignments with a render, answered
--     = practices opened on a rendered assignment, versions = the matching
--     and exposure policy pairs. No contradiction instrument (null, and said
--     so), no release, no split. Same status CASE as the seven.
--   * The function KEEPS ITS NAME. Every caller (services/db.py,
--     services/ceo.py, the CEO page) reads it by that name; a rename would be
--     a deploy-ordered change for no reader's benefit. "Seven" in the name is
--     historical from here on, and this header is where that is said.
--   * The registry comment says eight.
--
-- Read-only report, internal only: no number here reaches a speaker or a
-- coach (AC-9); nothing here is a label, a dataset or a training input.
-- Additive and idempotent (drop-if-exists then add for the CHECKs, create or
-- replace for the function); no data is rewritten; no env var. Merging runs
-- it on the next container start.

BEGIN;

-- ── The release vocabulary: eight ────────────────────────────────────────

ALTER TABLE public.dataset_releases
    DROP CONSTRAINT IF EXISTS dataset_releases_learning_surface_check;
ALTER TABLE public.dataset_releases
    ADD CONSTRAINT dataset_releases_learning_surface_check CHECK (
        learning_surface IN (
            'confidence_classification', 'correction_generation',
            'coach_comment_generation', 'praise_generation',
            'praise_selection', 'correction_selection',
            'ideal_text_generation', 'exercise_adequacy_classification'
        )
    );

ALTER TABLE public.dataset_release_items
    DROP CONSTRAINT IF EXISTS dataset_release_items_learning_surface_check;
ALTER TABLE public.dataset_release_items
    ADD CONSTRAINT dataset_release_items_learning_surface_check CHECK (
        learning_surface IN (
            'confidence_classification', 'correction_generation',
            'coach_comment_generation', 'praise_generation',
            'praise_selection', 'correction_selection',
            'ideal_text_generation', 'exercise_adequacy_classification'
        )
    );

-- ── The readiness report: eight rows ─────────────────────────────────────

CREATE OR REPLACE FUNCTION public.get_seven_surface_readiness_v1()
RETURNS JSONB
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = public
AS $$
WITH surfaces(surface, position) AS (VALUES
    ('confidence_classification', 1),
    ('correction_generation', 2),
    ('coach_comment_generation', 3),
    ('praise_generation', 4),
    ('praise_selection', 5),
    ('correction_selection', 6),
    ('ideal_text_generation', 7)
), presentation_stats AS (
    SELECT p.learning_surface AS surface,
           count(*) FILTER (WHERE NOT p.evaluation_only)::integer AS prepared,
           count(*) FILTER (WHERE p.evaluation_only)::integer AS shadow,
           count(*) FILTER (
               WHERE NOT p.evaluation_only AND p.versions <> '{}'::jsonb
           )::integer AS versioned,
           count(DISTINCT p.take_id) FILTER (
               WHERE NOT p.evaluation_only
           )::integer AS takes,
           count(DISTINCT p.owner_principal_id) FILTER (
               WHERE NOT p.evaluation_only
           )::integer AS owners,
           count(DISTINCT p.project_id) FILTER (
               WHERE NOT p.evaluation_only
           )::integer AS projects,
           count(DISTINCT p.actor_id) FILTER (
               WHERE NOT p.evaluation_only AND p.actor_role = 'coach'
           )::integer AS coaches,
           COALESCE(jsonb_agg(DISTINCT p.versions) FILTER (
               WHERE NOT p.evaluation_only AND p.versions <> '{}'::jsonb
           ), '[]'::jsonb) AS versions
      FROM public.learning_surface_presentations p
     GROUP BY p.learning_surface
), receipt_stats AS (
    SELECT r.learning_surface AS surface,
           count(*)::integer AS receipts,
           count(DISTINCT r.presentation_id)::integer AS shown_presentations
      FROM public.learning_surface_exposure_receipts r
     GROUP BY r.learning_surface
), decision_stats AS (
    SELECT p.learning_surface AS surface,
           count(DISTINCT p.id) FILTER (WHERE
               (p.learning_surface = 'confidence_classification' AND (
                   (p.actor_role = 'owner' AND EXISTS (
                       SELECT 1 FROM public.confidence_self_reports decision
                        WHERE decision.evidence_span_id = p.evidence_span_id
                          AND decision.rater_id = p.actor_id
                   )) OR (p.actor_role = 'coach' AND EXISTS (
                       SELECT 1 FROM public.confidence_coach_labels decision
                        WHERE decision.evidence_span_id = p.evidence_span_id
                          AND decision.rater_id = p.actor_id
                   )) OR (p.actor_role = 'peer' AND EXISTS (
                       SELECT 1 FROM public.confidence_peer_labels decision
                        WHERE decision.evidence_span_id = p.evidence_span_id
                          AND decision.rater_id = p.actor_id
                   ))
               )) OR (p.learning_surface IN (
                   'correction_generation', 'correction_selection'
               ) AND EXISTS (
                   SELECT 1 FROM public.correction_decisions decision
                    WHERE decision.evidence_span_id = p.evidence_span_id
                      AND decision.rater_id = p.actor_id
               )) OR (p.learning_surface IN (
                   'praise_generation', 'praise_selection'
               ) AND EXISTS (
                   SELECT 1 FROM public.praise_helpfulness decision
                    WHERE decision.evidence_span_id = p.evidence_span_id
                      AND decision.rater_id = p.actor_id
               )) OR (p.learning_surface = 'coach_comment_generation'
               AND EXISTS (
                   SELECT 1 FROM public.feedback_revisions decision
                    WHERE decision.evidence_span_id = p.evidence_span_id
                      AND decision.rater_id = p.actor_id
               ))
           )::integer AS answered
      FROM public.learning_surface_presentations p
      JOIN public.learning_surface_exposure_receipts receipt
        ON receipt.presentation_id = p.id
     GROUP BY p.learning_surface
), release_stats AS (
    SELECT release.learning_surface AS surface,
           count(DISTINCT release.id)::integer AS releases,
           count(DISTINCT release.id) FILTER (
               WHERE release.consent_retention_status ->>
                     'training_authorized' = 'true'
           )::integer AS authorized_releases,
           count(item.id) FILTER (
               WHERE item.eligibility_decision = 'eligible'
           )::integer AS eligible_items,
           count(item.id) FILTER (
               WHERE item.eligibility_decision = 'research_only'
           )::integer AS research_only_items
      FROM public.dataset_releases release
      LEFT JOIN public.dataset_release_items item
        ON item.release_id = release.id
     GROUP BY release.learning_surface
), exclusion_counts AS (
    SELECT release.learning_surface AS surface,
           exclusion.reason_code,
           count(*)::integer AS count
      FROM public.dataset_releases release
      JOIN public.dataset_exclusions exclusion
        ON exclusion.release_id = release.id
     GROUP BY release.learning_surface, exclusion.reason_code
), exclusion_stats AS (
    SELECT surface, sum(count)::integer AS exclusions,
           jsonb_object_agg(reason_code, count ORDER BY reason_code)
               AS by_reason
      FROM exclusion_counts
     GROUP BY surface
), split_stats AS (
    SELECT p.learning_surface AS surface,
           count(DISTINCT assignment.owner_principal_id)::integer AS owners
      FROM public.learning_surface_presentations p
      JOIN public.dataset_split_assignments assignment
        ON assignment.owner_principal_id = p.owner_principal_id
     WHERE NOT p.evaluation_only
     GROUP BY p.learning_surface
), confidence_contradictions AS (
    SELECT count(DISTINCT self.evidence_span_id)::integer AS count
      FROM public.confidence_self_reports self
      JOIN public.confidence_coach_labels coach
        ON coach.evidence_span_id = self.evidence_span_id
     WHERE self.value IN ('yes', 'in_between', 'no')
       AND coach.value IN ('yes', 'in_between', 'no')
       AND self.value IS DISTINCT FROM coach.value
), totals AS (
    SELECT count(*)::integer AS canonical_takes FROM public.takes
), shaped AS (
    SELECT s.surface,
           s.position,
           COALESCE(p.prepared, 0) AS prepared,
           COALESCE(p.shadow, 0) AS shadow,
           COALESCE(p.versioned, 0) AS versioned,
           COALESCE(p.takes, 0) AS covered_takes,
           COALESCE(p.owners, 0) AS covered_owners,
           COALESCE(p.projects, 0) AS covered_projects,
           COALESCE(p.coaches, 0) AS covered_coaches,
           COALESCE(p.versions, '[]'::jsonb) AS versions,
           COALESCE(r.receipts, 0) AS receipts,
           COALESCE(r.shown_presentations, 0) AS shown_presentations,
           COALESCE(d.answered, 0) AS answered,
           COALESCE(rel.releases, 0) AS releases,
           COALESCE(rel.authorized_releases, 0) AS authorized_releases,
           COALESCE(rel.eligible_items, 0) AS eligible_items,
           COALESCE(rel.research_only_items, 0) AS research_only_items,
           COALESCE(ex.exclusions, 0) AS exclusions,
           COALESCE(ex.by_reason, '{}'::jsonb) AS exclusions_by_reason,
           COALESCE(split.owners, 0) AS split_ready_owners,
           CASE WHEN s.surface = 'confidence_classification'
                THEN cc.count ELSE NULL END AS contradiction_count,
           (s.surface = 'confidence_classification') AS
                contradictions_supported,
           totals.canonical_takes
      FROM surfaces s
      CROSS JOIN totals
      CROSS JOIN confidence_contradictions cc
      LEFT JOIN presentation_stats p ON p.surface = s.surface
      LEFT JOIN receipt_stats r ON r.surface = s.surface
      LEFT JOIN decision_stats d ON d.surface = s.surface
      LEFT JOIN release_stats rel ON rel.surface = s.surface
      LEFT JOIN exclusion_stats ex ON ex.surface = s.surface
      LEFT JOIN split_stats split ON split.surface = s.surface
), exercise_assignments AS (
    -- MODULE 8 (0395): the frozen 80/20 choice is the "prepared" unit, the
    -- confirmed render (0387) is its receipt, and the practice opened on
    -- that assignment is its answer.
    SELECT count(*)::integer AS prepared,
           count(DISTINCT a.take_session_id)::integer AS takes,
           count(DISTINCT a.owner_user_id)::integer AS owners,
           COALESCE(jsonb_agg(DISTINCT jsonb_build_object(
               'matching_policy_version', a.matching_policy_version,
               'exposure_policy_version', a.exposure_policy_version
           )), '[]'::jsonb) AS versions
      FROM public.confident_voice_exercise_assignments a
), exercise_exposures AS (
    SELECT count(*)::integer AS receipts,
           count(DISTINCT e.assignment_id)::integer AS shown
      FROM public.confident_voice_exercise_exposures e
), exercise_practices AS (
    SELECT count(DISTINCT practice.id)::integer AS answered,
           count(DISTINCT practice.project_id)::integer AS projects
      FROM public.confident_voice_practice practice
      JOIN public.confident_voice_exercise_exposures e
        ON e.assignment_id::text =
           practice.machine_assessment ->> 'exercise_assignment_id'
), exercise_shaped AS (
    SELECT 'exercise_adequacy_classification'::text AS surface,
           8 AS position,
           ea.prepared,
           0 AS shadow,
           ea.prepared AS versioned,
           ea.takes AS covered_takes,
           ea.owners AS covered_owners,
           ep.projects AS covered_projects,
           0 AS covered_coaches,
           ea.versions,
           ee.receipts,
           ee.shown AS shown_presentations,
           ep.answered,
           0 AS releases,
           0 AS authorized_releases,
           0 AS eligible_items,
           0 AS research_only_items,
           0 AS exclusions,
           '{}'::jsonb AS exclusions_by_reason,
           0 AS split_ready_owners,
           NULL::integer AS contradiction_count,
           false AS contradictions_supported,
           totals.canonical_takes
      FROM exercise_assignments ea
      CROSS JOIN exercise_exposures ee
      CROSS JOIN exercise_practices ep
      CROSS JOIN totals
), rows AS (
    SELECT * FROM shaped
    UNION ALL
    SELECT * FROM exercise_shaped
)
SELECT jsonb_build_object(
    'contract_version', 'readiness-v1',
    'generated_at', now(),
    'read_only', true,
    'surfaces', jsonb_agg(jsonb_build_object(
        'learning_surface', surface,
        'status', CASE
            WHEN authorized_releases > 0 AND shown_presentations > 0
                 AND prepared = versioned THEN 'release_candidate_ready'
            WHEN shown_presentations > 0 THEN 'collecting'
            WHEN prepared > 0 THEN 'blocked'
            ELSE 'not_collecting_correctly'
        END,
        'canonical_take_count', canonical_takes,
        'covered_take_count', covered_takes,
        'covered_owner_count', covered_owners,
        'covered_speaker_count', covered_owners,
        'covered_project_count', covered_projects,
        'covered_coach_count', covered_coaches,
        'prepared_presentation_count', prepared,
        'visible_exposure_count', receipts,
        'shown_presentation_count', shown_presentations,
        'answer_instrument_defined',
            surface <> 'ideal_text_generation',
        'answered_exposure_count', CASE
            WHEN surface = 'ideal_text_generation' THEN NULL ELSE answered END,
        'unanswered_exposure_count', CASE
            WHEN surface = 'ideal_text_generation' THEN NULL
            ELSE GREATEST(shown_presentations - answered, 0) END,
        'shadow_evaluation_count', shadow,
        'unacknowledged_presentation_count',
            GREATEST(prepared - shown_presentations, 0),
        'visible_coverage_ratio', CASE WHEN prepared = 0 THEN 0
            ELSE round(shown_presentations::numeric / prepared, 4) END,
        'versioned_presentation_count', versioned,
        'version_coverage_ratio', CASE WHEN prepared = 0 THEN 0
            ELSE round(versioned::numeric / prepared, 4) END,
        'versions', versions,
        'coverage_dimensions', jsonb_build_object(
            'language', jsonb_build_object('status', 'not_captured'),
            'device', jsonb_build_object('status', 'not_captured'),
            'recording_condition', jsonb_build_object(
                'status', 'not_captured')
        ),
        'missing_metadata', jsonb_build_object(
            'ownership', 0,
            'take', 0,
            'evidence', CASE WHEN surface = 'ideal_text_generation'
                             THEN 0 ELSE 0 END,
            'versions', GREATEST(prepared - versioned, 0),
            'consent', CASE WHEN authorized_releases = 0
                            THEN shown_presentations ELSE NULL END
        ),
        'contradictions_supported', contradictions_supported,
        'contradiction_count', contradiction_count,
        'potential_duplicate_count', NULL,
        'duplicate_check_status', 'idempotency_constraint_only',
        'dataset_release_count', releases,
        'authorized_dataset_release_count', authorized_releases,
        'eligible_item_count', eligible_items,
        'research_only_item_count', research_only_items,
        'exclusion_count', exclusions,
        'exclusions_by_reason', exclusions_by_reason,
        'speaker_disjoint_split', jsonb_build_object(
            'strategy_version', 'speaker-sha256-80-10-10-v1',
            'covered_owner_count', covered_owners,
            'assigned_owner_count', split_ready_owners,
            'ready', covered_owners > 0 AND split_ready_owners = covered_owners
        ),
        'blockers', (CASE WHEN canonical_takes = 0
            THEN jsonb_build_array('no_canonical_takes')
            ELSE '[]'::jsonb END)
          || (CASE WHEN prepared = 0
            THEN jsonb_build_array('no_production_presentations')
            ELSE '[]'::jsonb END)
          || (CASE WHEN shown_presentations = 0
            THEN jsonb_build_array('no_visible_exposure_receipts')
            ELSE '[]'::jsonb END)
          || (CASE WHEN versioned < prepared
            THEN jsonb_build_array('incomplete_version_provenance')
            ELSE '[]'::jsonb END)
          || (CASE WHEN authorized_releases = 0
            THEN jsonb_build_array('no_authorized_consent_release')
            ELSE '[]'::jsonb END)
          || (CASE WHEN NOT contradictions_supported
            THEN jsonb_build_array('contradiction_metric_not_defined')
            ELSE '[]'::jsonb END)
          || jsonb_build_array(
              'language_coverage_not_captured',
              'device_coverage_not_captured',
              'recording_condition_coverage_not_captured',
              'semantic_duplicate_metric_not_defined'
          )
          || (CASE WHEN split_ready_owners < covered_owners
            THEN jsonb_build_array('speaker_split_incomplete')
            ELSE '[]'::jsonb END)
    ) ORDER BY position)
) FROM rows;
$$;

REVOKE ALL ON FUNCTION public.get_seven_surface_readiness_v1()
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_seven_surface_readiness_v1()
    TO service_role;

COMMENT ON FUNCTION public.get_seven_surface_readiness_v1() IS
    'Aggregate-only, read-only readiness for the eight learning surfaces (the name is historical: seven carry packets, module 8 is read from the exercise tables); it exposes no training or promotion control.';

COMMENT ON TABLE public.ml_learning_surfaces IS
    'Sole authoritative registry for the eight canonical learning surfaces. Seven carry presentation packets (0299); exercise_adequacy_classification is exposed through confident_voice_exercise_exposures (0387), labelled by the practice outcome, and counted by its own bar (300/30).';

COMMIT;
