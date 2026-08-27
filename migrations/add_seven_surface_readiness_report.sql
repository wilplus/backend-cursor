-- 0301 · aggregate-only, read-only readiness report for the seven systems.
--
-- No row-level content, transcript, audio reference, user identifier or
-- control is returned. Null contradiction counts are explicit: a surface
-- without a defined contradiction instrument is not silently reported as 0.

BEGIN;

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
) FROM shaped;
$$;

REVOKE ALL ON FUNCTION public.get_seven_surface_readiness_v1()
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_seven_surface_readiness_v1()
    TO service_role;

COMMENT ON FUNCTION public.get_seven_surface_readiness_v1() IS
    'Aggregate-only, read-only readiness for seven isolated learning systems; it exposes no training or promotion control.';

COMMIT;
