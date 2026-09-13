-- Pending, unnumbered: Confident Moment Coaching Bundle V1 data foundation.
-- Contract Delta D3 / Interface Manifest D11. Runtime and learning gates stay off.
BEGIN;

CREATE TABLE IF NOT EXISTS public.confident_moment_bundle_attachments (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), acquisition_principal_id uuid NOT NULL REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
 project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE RESTRICT, take_id uuid NOT NULL REFERENCES public.v2_sessions(id) ON DELETE RESTRICT,
 feedback_membership_id uuid NOT NULL REFERENCES public.feedback_v3_memberships(id) ON DELETE RESTRICT,
 bundle_subject_kind text NOT NULL CHECK(bundle_subject_kind IN ('confidence_anchor','no_anchor_paragraph_trigger')),
 bundle_subject_candidate_id uuid NOT NULL, bundle_subject_evidence_span_id uuid NOT NULL, attached_candidate_id uuid NOT NULL, attached_evidence_span_id uuid NOT NULL,
 anchor_candidate_id uuid NULL, anchor_evidence_span_id uuid NULL, paragraph_id uuid NOT NULL,
 document_snapshot_id uuid NOT NULL REFERENCES public.ideal_text_document_snapshots(id) ON DELETE RESTRICT, canonical_feedback_presentation_id uuid NOT NULL,
 canonical_position integer NOT NULL CHECK(canonical_position>0), attachment_policy_version text NOT NULL CHECK(attachment_policy_version IN ('confident-moment-attachment-v1','confident-moment-no-anchor-trigger-v1')),
 presentation_identity_sha256 text NOT NULL CHECK(presentation_identity_sha256 ~ '^[0-9a-f]{64}$'), attachment_input_sha256 text NOT NULL CHECK(attachment_input_sha256 ~ '^[0-9a-f]{64}$'),
 idempotency_key text NOT NULL UNIQUE CHECK(length(btrim(idempotency_key)) BETWEEN 1 AND 200), prepared_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 serves_user boolean NOT NULL DEFAULT false CHECK(NOT serves_user), dataset_eligible boolean NOT NULL DEFAULT false CHECK(NOT dataset_eligible),
 FOREIGN KEY(feedback_membership_id,acquisition_principal_id) REFERENCES public.feedback_v3_memberships(id,acquisition_principal_id) ON DELETE RESTRICT,
 FOREIGN KEY(feedback_membership_id,bundle_subject_candidate_id) REFERENCES public.feedback_v3_membership_items(membership_id,candidate_id) ON DELETE RESTRICT,
 FOREIGN KEY(feedback_membership_id,attached_candidate_id) REFERENCES public.feedback_v3_membership_items(membership_id,candidate_id) ON DELETE RESTRICT,
 FOREIGN KEY(bundle_subject_candidate_id,bundle_subject_evidence_span_id) REFERENCES public.feedback_candidates(id,evidence_span_id) ON DELETE RESTRICT,
 FOREIGN KEY(attached_candidate_id,attached_evidence_span_id) REFERENCES public.feedback_candidates(id,evidence_span_id) ON DELETE RESTRICT,
 FOREIGN KEY(canonical_feedback_presentation_id,attached_candidate_id) REFERENCES public.feedback_exposures(id,candidate_id) ON DELETE RESTRICT,
 CHECK((bundle_subject_kind='confidence_anchor' AND anchor_candidate_id=bundle_subject_candidate_id AND anchor_evidence_span_id=bundle_subject_evidence_span_id AND attachment_policy_version='confident-moment-attachment-v1') OR (bundle_subject_kind='no_anchor_paragraph_trigger' AND anchor_candidate_id IS NULL AND anchor_evidence_span_id IS NULL AND attached_candidate_id=bundle_subject_candidate_id AND attached_evidence_span_id=bundle_subject_evidence_span_id AND attachment_policy_version='confident-moment-no-anchor-trigger-v1')),
 UNIQUE(id,acquisition_principal_id), UNIQUE(feedback_membership_id,attached_candidate_id)
);

CREATE TABLE IF NOT EXISTS public.root_phrase_coverage_frames (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), acquisition_principal_id uuid NOT NULL REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
 project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE RESTRICT, take_id uuid NOT NULL REFERENCES public.v2_sessions(id) ON DELETE RESTRICT,
 feedback_membership_id uuid NOT NULL REFERENCES public.feedback_v3_memberships(id) ON DELETE RESTRICT, document_snapshot_id uuid NOT NULL REFERENCES public.ideal_text_document_snapshots(id) ON DELETE RESTRICT,
 take_ordinal integer NOT NULL CHECK(take_ordinal>0), slide_denominator integer NOT NULL CHECK(slide_denominator>0), target_slide_count integer NOT NULL, achieved_slide_count integer NOT NULL,
 target_met boolean GENERATED ALWAYS AS (achieved_slide_count>=target_slide_count) STORED, policy_version text NOT NULL CHECK(policy_version='rooting-coverage-30-80-100-v1'),
 clause_policy_version text NOT NULL CHECK(clause_policy_version='root-exact-clause-v1'), routing_policy_version text NOT NULL CHECK(routing_policy_version='root-lexicographic-routing-v1'),
 inventory_sha256 text NOT NULL CHECK(inventory_sha256 ~ '^[0-9a-f]{64}$'), frame_sha256 text NOT NULL CHECK(frame_sha256 ~ '^[0-9a-f]{64}$'), idempotency_key text NOT NULL UNIQUE,
 frozen_at timestamptz NOT NULL DEFAULT clock_timestamp(), serves_user boolean NOT NULL DEFAULT false CHECK(NOT serves_user), dataset_eligible boolean NOT NULL DEFAULT false CHECK(NOT dataset_eligible),
 FOREIGN KEY(feedback_membership_id,acquisition_principal_id) REFERENCES public.feedback_v3_memberships(id,acquisition_principal_id) ON DELETE RESTRICT,
 CHECK(target_slide_count BETWEEN 1 AND slide_denominator), CHECK(achieved_slide_count BETWEEN 0 AND slide_denominator), UNIQUE(id,acquisition_principal_id), UNIQUE(take_id,feedback_membership_id,document_snapshot_id,policy_version)
);

CREATE TABLE IF NOT EXISTS public.root_phrase_coverage_items (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), frame_id uuid NOT NULL REFERENCES public.root_phrase_coverage_frames(id) ON DELETE RESTRICT,
 acquisition_principal_id uuid NOT NULL REFERENCES public.owner_principals(id) ON DELETE RESTRICT, slide_index integer NOT NULL CHECK(slide_index>=0), block_key integer NOT NULL CHECK(block_key>=0),
 anchor_candidate_id uuid NULL REFERENCES public.feedback_candidates(id) ON DELETE RESTRICT, anchor_evidence_span_id uuid NULL REFERENCES public.evidence_spans(id) ON DELETE RESTRICT,
 content_version_id uuid NULL REFERENCES public.root_phrase_content_versions(id) ON DELETE RESTRICT, root_action_id uuid NULL REFERENCES public.root_phrase_product_actions(id) ON DELETE RESTRICT,
 coverage_item_state text NOT NULL CHECK(coverage_item_state IN ('covered_existing_owner_lock','covered_automatic_root','covered_owner_selected','eligible_automatic_proposal','eligible_owner_proposal','pending_rerecord','uncovered_no_aligned_clause','uncovered_owner_declined','excluded_unusable_source','invalidated')),
 exclusion_reason text NULL, canonical_position integer NOT NULL CHECK(canonical_position>0), item_sha256 text NOT NULL CHECK(item_sha256 ~ '^[0-9a-f]{64}$'), serves_user boolean NOT NULL DEFAULT false CHECK(NOT serves_user), dataset_eligible boolean NOT NULL DEFAULT false CHECK(NOT dataset_eligible),
 FOREIGN KEY(frame_id,acquisition_principal_id) REFERENCES public.root_phrase_coverage_frames(id,acquisition_principal_id) ON DELETE RESTRICT,
 CHECK((anchor_candidate_id IS NULL)=(anchor_evidence_span_id IS NULL)), UNIQUE(frame_id,slide_index,block_key), UNIQUE(frame_id,canonical_position)
);

ALTER TABLE public.feedback_revisions ADD COLUMN IF NOT EXISTS feedback_membership_id uuid, ADD COLUMN IF NOT EXISTS feedback_candidate_id uuid, ADD COLUMN IF NOT EXISTS candidate_output_version text, ADD COLUMN IF NOT EXISTS candidate_output_sha256 text, ADD COLUMN IF NOT EXISTS output_kind text, ADD COLUMN IF NOT EXISTS comment_purpose text, ADD COLUMN IF NOT EXISTS review_batch_id uuid, ADD COLUMN IF NOT EXISTS reveal_grant_id uuid, ADD COLUMN IF NOT EXISTS reveal_access_id uuid, ADD COLUMN IF NOT EXISTS review_assignment_id uuid, ADD COLUMN IF NOT EXISTS blind_judgment_id uuid, ADD COLUMN IF NOT EXISTS acquisition_principal_id uuid, ADD COLUMN IF NOT EXISTS revision_sha256 text;
DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='feedback_revision_bundle_membership_candidate_fk') THEN
 ALTER TABLE public.feedback_revisions ADD CONSTRAINT feedback_revision_bundle_membership_candidate_fk FOREIGN KEY(feedback_membership_id,feedback_candidate_id) REFERENCES public.feedback_v3_membership_items(membership_id,candidate_id) ON DELETE RESTRICT NOT VALID;
 ALTER TABLE public.feedback_revisions ADD CONSTRAINT feedback_revision_bundle_candidate_evidence_fk FOREIGN KEY(feedback_candidate_id,evidence_span_id) REFERENCES public.feedback_candidates(id,evidence_span_id) ON DELETE RESTRICT NOT VALID;
 ALTER TABLE public.feedback_revisions ADD CONSTRAINT feedback_revision_bundle_batch_fk FOREIGN KEY(review_batch_id) REFERENCES public.coach_guidance_review_batches(id) ON DELETE RESTRICT NOT VALID;
 ALTER TABLE public.feedback_revisions ADD CONSTRAINT feedback_revision_bundle_reveal_grant_fk FOREIGN KEY(reveal_grant_id) REFERENCES public.coach_guidance_reveal_grants(id) ON DELETE RESTRICT NOT VALID;
 ALTER TABLE public.feedback_revisions ADD CONSTRAINT feedback_revision_bundle_reveal_access_fk FOREIGN KEY(reveal_access_id) REFERENCES public.coach_guidance_reveal_accesses(id) ON DELETE RESTRICT NOT VALID;
 ALTER TABLE public.feedback_revisions ADD CONSTRAINT feedback_revision_bundle_assignment_fk FOREIGN KEY(review_assignment_id) REFERENCES public.ml_review_assignments(id) ON DELETE RESTRICT NOT VALID;
 ALTER TABLE public.feedback_revisions ADD CONSTRAINT feedback_revision_bundle_judgment_fk FOREIGN KEY(blind_judgment_id) REFERENCES public.ml_judgments(id) ON DELETE RESTRICT NOT VALID;
 ALTER TABLE public.feedback_revisions ADD CONSTRAINT feedback_revision_bundle_principal_fk FOREIGN KEY(acquisition_principal_id) REFERENCES public.owner_principals(id) ON DELETE RESTRICT NOT VALID;
 ALTER TABLE public.feedback_revisions ADD CONSTRAINT feedback_revision_bundle_v1_shape CHECK(taxonomy_version<>'feedback-language-coach-revision-v1' OR (feedback_membership_id IS NOT NULL AND feedback_candidate_id IS NOT NULL AND candidate_output_version='feedback-candidate-output-v1' AND candidate_output_sha256 ~ '^[0-9a-f]{64}$' AND output_kind IN ('comment','rephrase') AND ((output_kind='rephrase' AND comment_purpose IS NULL) OR (output_kind='comment' AND comment_purpose IN ('confidence_explanation','actionable_observation','positive_praise'))) AND review_batch_id IS NOT NULL AND reveal_grant_id IS NOT NULL AND reveal_access_id IS NOT NULL AND review_assignment_id IS NOT NULL AND blind_judgment_id IS NOT NULL AND acquisition_principal_id IS NOT NULL AND revision_sha256 ~ '^[0-9a-f]{64}$')) NOT VALID;
END IF; END $$;
CREATE UNIQUE INDEX IF NOT EXISTS feedback_language_coach_revision_original_idx ON public.feedback_revisions(feedback_membership_id,feedback_candidate_id,rater_id) WHERE taxonomy_version='feedback-language-coach-revision-v1' AND supersedes_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS feedback_language_coach_revision_supersedes_idx ON public.feedback_revisions(supersedes_id) WHERE taxonomy_version='feedback-language-coach-revision-v1' AND supersedes_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.feedback_language_revision_deliveries (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), revision_id uuid NOT NULL REFERENCES public.feedback_revisions(id) ON DELETE RESTRICT,
 acquisition_principal_id uuid NOT NULL REFERENCES public.owner_principals(id) ON DELETE RESTRICT, recipient_principal_id uuid NOT NULL REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
 target_take_id uuid NOT NULL REFERENCES public.v2_sessions(id) ON DELETE RESTRICT, anchor_candidate_id uuid NOT NULL REFERENCES public.feedback_candidates(id) ON DELETE RESTRICT,
 delivery_state text NOT NULL CHECK(delivery_state IN ('scheduled_current_take','scheduled_next_take','invalidated')), delivery_revision integer NOT NULL CHECK(delivery_revision>0),
 authorization_rollout_revision_id uuid NOT NULL REFERENCES public.mlc3_service_rollout_revisions(id) ON DELETE RESTRICT, authorization_enrollment_revision_id uuid NOT NULL REFERENCES public.mlc3_service_enrollment_revisions(id) ON DELETE RESTRICT,
 delivery_sha256 text NOT NULL CHECK(delivery_sha256 ~ '^[0-9a-f]{64}$'), idempotency_key text NOT NULL UNIQUE, scheduled_at timestamptz NOT NULL DEFAULT clock_timestamp(), serves_user boolean NOT NULL DEFAULT false CHECK(NOT serves_user), dataset_eligible boolean NOT NULL DEFAULT false CHECK(NOT dataset_eligible),
 UNIQUE(id,recipient_principal_id), UNIQUE(revision_id,recipient_principal_id,target_take_id,delivery_revision)
);

-- D11 immutable currentness.  Legacy rows remain nullable and cannot become
-- current v2 delivery/revision authority.
ALTER TABLE public.feedback_language_revision_deliveries
 ADD COLUMN IF NOT EXISTS feedback_membership_id uuid,
 ADD COLUMN IF NOT EXISTS feedback_candidate_id uuid,
 ADD COLUMN IF NOT EXISTS reviewer_principal_id uuid,
 ADD COLUMN IF NOT EXISTS revision_taxonomy_version text,
 ADD COLUMN IF NOT EXISTS candidate_output_version text,
 ADD COLUMN IF NOT EXISTS candidate_output_sha256 text,
 ADD COLUMN IF NOT EXISTS delivery_subject_sha256 text,
 ADD COLUMN IF NOT EXISTS supersedes_delivery_id uuid,
 ADD COLUMN IF NOT EXISTS delivery_policy_version text;
CREATE UNIQUE INDEX IF NOT EXISTS feedback_language_revision_exact_identity_idx
 ON public.feedback_revisions(id,taxonomy_version,feedback_membership_id,
 feedback_candidate_id,rater_id,acquisition_principal_id,
 candidate_output_version,candidate_output_sha256);
CREATE UNIQUE INDEX IF NOT EXISTS feedback_language_delivery_original_v2_idx
 ON public.feedback_language_revision_deliveries(recipient_principal_id,target_take_id,
 feedback_membership_id,feedback_candidate_id)
 WHERE delivery_policy_version='feedback-language-delivery-v2'
 AND supersedes_delivery_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS feedback_language_delivery_successor_v2_idx
 ON public.feedback_language_revision_deliveries(supersedes_delivery_id)
 WHERE delivery_policy_version='feedback-language-delivery-v2'
 AND supersedes_delivery_id IS NOT NULL;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='feedback_language_delivery_v2_revision_fk') THEN
  ALTER TABLE public.feedback_language_revision_deliveries
   ADD CONSTRAINT feedback_language_delivery_v2_revision_fk
   FOREIGN KEY(revision_id,revision_taxonomy_version,feedback_membership_id,
    feedback_candidate_id,reviewer_principal_id,acquisition_principal_id,
    candidate_output_version,candidate_output_sha256)
   REFERENCES public.feedback_revisions(id,taxonomy_version,feedback_membership_id,
    feedback_candidate_id,rater_id,acquisition_principal_id,
    candidate_output_version,candidate_output_sha256) NOT VALID;
 END IF;
END $$;
DROP FUNCTION IF EXISTS public.record_root_phrase_product_action_v2(uuid,uuid,uuid,uuid,integer,text,uuid,uuid,uuid,uuid,uuid,uuid,bigint,uuid,uuid,uuid,text,text);

CREATE TABLE IF NOT EXISTS public.confident_moment_bundle_projections (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), acquisition_principal_id uuid NOT NULL REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
 project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE RESTRICT,take_id uuid NOT NULL REFERENCES public.v2_sessions(id) ON DELETE RESTRICT,
 feedback_membership_id uuid NOT NULL REFERENCES public.feedback_v3_memberships(id) ON DELETE RESTRICT,document_snapshot_id uuid NOT NULL REFERENCES public.ideal_text_document_snapshots(id) ON DELETE RESTRICT,
 document_snapshot_sha256 text NOT NULL CHECK(document_snapshot_sha256 ~ '^[0-9a-f]{64}$'),projection_policy_version text NOT NULL CHECK(projection_policy_version='confident-moment-secure-projection-v1'),projection_code_version text NOT NULL CHECK(projection_code_version='confident-moment-projection-sql-v1'),stabilized_inventory_sha256 text NOT NULL CHECK(stabilized_inventory_sha256 ~ '^[0-9a-f]{64}$'),response_sha256 text NOT NULL CHECK(response_sha256 ~ '^[0-9a-f]{64}$'),idempotency_key text NOT NULL UNIQUE,frozen_at timestamptz NOT NULL DEFAULT clock_timestamp(),serves_user boolean NOT NULL DEFAULT false CHECK(NOT serves_user),dataset_eligible boolean NOT NULL DEFAULT false CHECK(NOT dataset_eligible),UNIQUE(id,acquisition_principal_id),UNIQUE(acquisition_principal_id,project_id,take_id,stabilized_inventory_sha256)
);
CREATE TABLE IF NOT EXISTS public.confident_moment_bundle_projection_items (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),projection_id uuid NOT NULL,acquisition_principal_id uuid NOT NULL REFERENCES public.owner_principals(id) ON DELETE RESTRICT,bundle_attachment_id uuid NOT NULL REFERENCES public.confident_moment_bundle_attachments(id) ON DELETE RESTRICT,bundle_subject_candidate_id uuid NOT NULL REFERENCES public.feedback_candidates(id) ON DELETE RESTRICT,attached_candidate_id uuid NOT NULL REFERENCES public.feedback_candidates(id) ON DELETE RESTRICT,anchor_candidate_id uuid NULL REFERENCES public.feedback_candidates(id) ON DELETE RESTRICT,resolution_state text NOT NULL CHECK(resolution_state IN('coach_revision','machine_fallback','excluded')),exclusion_reason text NULL,revision_id uuid NULL REFERENCES public.feedback_revisions(id) ON DELETE RESTRICT,delivery_id uuid NULL REFERENCES public.feedback_language_revision_deliveries(id) ON DELETE RESTRICT,candidate_output_sha256 text NULL,output_sha256 text NULL,canonical_position integer NOT NULL CHECK(canonical_position>0),exercise_present boolean NOT NULL DEFAULT false CHECK(NOT exercise_present),item_sha256 text NOT NULL CHECK(item_sha256 ~ '^[0-9a-f]{64}$'),serves_user boolean NOT NULL DEFAULT false CHECK(NOT serves_user),dataset_eligible boolean NOT NULL DEFAULT false CHECK(NOT dataset_eligible),FOREIGN KEY(projection_id,acquisition_principal_id) REFERENCES public.confident_moment_bundle_projections(id,acquisition_principal_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,CHECK((resolution_state='excluded')=(exclusion_reason IS NOT NULL)),UNIQUE(projection_id,bundle_attachment_id),UNIQUE(projection_id,canonical_position)
);
ALTER TABLE public.confident_moment_bundle_projection_items
 ADD COLUMN IF NOT EXISTS presentation_id uuid NULL REFERENCES public.ml_presentations(id) ON DELETE RESTRICT,
 ADD COLUMN IF NOT EXISTS rendered_exposure_id uuid NULL REFERENCES public.ml_rendered_exposures(id) ON DELETE RESTRICT,
 ADD COLUMN IF NOT EXISTS unread boolean NOT NULL DEFAULT false,
 ADD COLUMN IF NOT EXISTS feedback_family text,
 ADD COLUMN IF NOT EXISTS canonical_feedback_exposure_id uuid REFERENCES public.feedback_exposures(id) ON DELETE RESTRICT;
ALTER TABLE public.confident_moment_bundle_projection_items
 ADD COLUMN IF NOT EXISTS owner_decision jsonb NULL;

-- D49: a Bundle response is not inferred from the historical family tables.
-- This append-only row is the exact bridge between the rendered Bundle item
-- and the already-canonical family decision.  It is product routing
-- provenance only and is never a learning label.
CREATE TABLE IF NOT EXISTS public.confident_moment_owner_decision_bindings (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 acquisition_principal_id uuid NOT NULL REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
 project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE RESTRICT,
 take_id uuid NOT NULL REFERENCES public.v2_sessions(id) ON DELETE RESTRICT,
 feedback_membership_id uuid NOT NULL REFERENCES public.feedback_v3_memberships(id) ON DELETE RESTRICT,
 bundle_subject_candidate_id uuid NOT NULL REFERENCES public.feedback_candidates(id) ON DELETE RESTRICT,
 bundle_attachment_id uuid NOT NULL REFERENCES public.confident_moment_bundle_attachments(id) ON DELETE RESTRICT,
 candidate_id uuid NOT NULL REFERENCES public.feedback_candidates(id) ON DELETE RESTRICT,
 feedback_family text NOT NULL CHECK(feedback_family IN('confident_voice','rewrite_clarity','great_formulation')),
 evidence_span_id uuid NOT NULL REFERENCES public.evidence_spans(id) ON DELETE RESTRICT,
 canonical_feedback_presentation_id uuid NOT NULL REFERENCES public.feedback_exposures(id) ON DELETE RESTRICT,
 render_receipt_id uuid NOT NULL REFERENCES public.feedback_v3_service_render_receipts(id) ON DELETE RESTRICT,
 decision_id uuid NOT NULL,
 owner_response_id uuid NULL REFERENCES public.feedback_v3_owner_responses(id) ON DELETE RESTRICT,
 response_binding_id uuid NULL REFERENCES public.feedback_v3_service_response_bindings(id) ON DELETE RESTRICT,
 correction_decision_id uuid NULL REFERENCES public.correction_decisions(id) ON DELETE RESTRICT,
 praise_helpfulness_id uuid NULL REFERENCES public.praise_helpfulness(id) ON DELETE RESTRICT,
 interaction_response text NOT NULL,
 canonical_response text NOT NULL,
 response_taxonomy_version text NOT NULL,
 decision_sha256 text NOT NULL CHECK(decision_sha256 ~ '^[0-9a-f]{64}$'),
 idempotency_key text NOT NULL UNIQUE CHECK(length(btrim(idempotency_key)) BETWEEN 1 AND 200),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 serves_user boolean NOT NULL DEFAULT false CHECK(NOT serves_user),
 dataset_eligible boolean NOT NULL DEFAULT false CHECK(NOT dataset_eligible),
 UNIQUE(bundle_attachment_id),
 FOREIGN KEY(feedback_membership_id,candidate_id)
  REFERENCES public.feedback_v3_membership_items(membership_id,candidate_id) ON DELETE RESTRICT,
 CHECK(
  (feedback_family='confident_voice' AND owner_response_id=decision_id
   AND response_binding_id IS NOT NULL AND correction_decision_id IS NULL
   AND praise_helpfulness_id IS NULL)
  OR (feedback_family='rewrite_clarity' AND correction_decision_id=decision_id
   AND owner_response_id IS NULL AND response_binding_id IS NULL
   AND praise_helpfulness_id IS NULL)
  OR (feedback_family='great_formulation' AND praise_helpfulness_id=decision_id
   AND owner_response_id IS NULL AND response_binding_id IS NULL
   AND correction_decision_id IS NULL))
);
ALTER TABLE public.confident_moment_bundle_projection_items
 ALTER COLUMN feedback_family SET NOT NULL,
 ALTER COLUMN canonical_feedback_exposure_id SET NOT NULL;
DO $confident_moment_d15_item_identity$ BEGIN
 ALTER TABLE public.confident_moment_bundle_projection_items
  DROP CONSTRAINT IF EXISTS confident_moment_projection_item_feedback_family_check;
 ALTER TABLE public.confident_moment_bundle_projection_items
  ADD CONSTRAINT confident_moment_projection_item_feedback_family_check CHECK(
   feedback_family IN('confident_voice','rewrite_clarity','great_formulation'));
 ALTER TABLE public.confident_moment_bundle_projection_items
  DROP CONSTRAINT IF EXISTS confident_moment_projection_item_feedback_exposure_fk;
 ALTER TABLE public.confident_moment_bundle_projection_items
  ADD CONSTRAINT confident_moment_projection_item_feedback_exposure_fk
  FOREIGN KEY(canonical_feedback_exposure_id,attached_candidate_id)
  REFERENCES public.feedback_exposures(id,candidate_id) ON DELETE RESTRICT;
 ALTER TABLE public.confident_moment_bundle_projection_items
  DROP CONSTRAINT IF EXISTS confident_moment_projection_feedback_exposure_unique;
 ALTER TABLE public.confident_moment_bundle_projection_items
  ADD CONSTRAINT confident_moment_projection_feedback_exposure_unique
  UNIQUE(projection_id,canonical_feedback_exposure_id);
END $confident_moment_d15_item_identity$;
-- Structural consistency: a projection item's resolution state fully
-- determines which currentness leaves it may carry.  Cross-attachment leakage
-- of a revision, delivery, presentation, rendered exposure, unread flag or
-- coach output hash cannot be persisted even if the projection body regresses.
-- Stable constraint names with DROP IF EXISTS keep the migration replay-safe.
DO $confident_moment_item_shape$ BEGIN
 ALTER TABLE public.confident_moment_bundle_projection_items
  DROP CONSTRAINT IF EXISTS confident_moment_projection_item_state_shape_check;
 ALTER TABLE public.confident_moment_bundle_projection_items
 ADD CONSTRAINT confident_moment_projection_item_state_shape_check CHECK(
   (resolution_state='coach_revision' AND revision_id IS NOT NULL
     AND delivery_id IS NOT NULL AND exclusion_reason IS NULL
     AND output_sha256 IS NOT NULL)
   OR (resolution_state='machine_fallback' AND revision_id IS NULL
     AND delivery_id IS NULL AND presentation_id IS NULL
     AND rendered_exposure_id IS NULL AND NOT unread
     AND exclusion_reason IS NULL)
   OR (resolution_state='excluded' AND revision_id IS NULL
     AND presentation_id IS NULL AND rendered_exposure_id IS NULL
     AND NOT unread AND exclusion_reason IS NOT NULL
     -- Only the invalidated-delivery exclusion may retain a delivery_id.
     AND (delivery_id IS NULL OR exclusion_reason='delivery_explicitly_invalidated')));
 ALTER TABLE public.confident_moment_bundle_projection_items
  DROP CONSTRAINT IF EXISTS confident_moment_projection_item_render_shape_check;
 ALTER TABLE public.confident_moment_bundle_projection_items
  ADD CONSTRAINT confident_moment_projection_item_render_shape_check CHECK(
   (rendered_exposure_id IS NULL OR presentation_id IS NOT NULL)
   AND unread=(resolution_state='coach_revision' AND rendered_exposure_id IS NULL));
 ALTER TABLE public.confident_moment_bundle_projection_items
  DROP CONSTRAINT IF EXISTS confident_moment_projection_item_output_shape_check;
 ALTER TABLE public.confident_moment_bundle_projection_items
  ADD CONSTRAINT confident_moment_projection_item_output_shape_check CHECK(
   candidate_output_sha256 IS NOT NULL AND output_sha256 IS NOT NULL
   AND candidate_output_sha256 ~ '^[0-9a-f]{64}$' AND output_sha256 ~ '^[0-9a-f]{64}$'
   AND (resolution_state='coach_revision' OR output_sha256=candidate_output_sha256));
 ALTER TABLE public.confident_moment_bundle_projection_items
  DROP CONSTRAINT IF EXISTS confident_moment_projection_item_exclusion_reason_check;
 ALTER TABLE public.confident_moment_bundle_projection_items
 ADD CONSTRAINT confident_moment_projection_item_exclusion_reason_check CHECK(
   exclusion_reason IS NULL OR exclusion_reason IN(
    'machine_output_invalid','delivery_explicitly_invalidated'));
 ALTER TABLE public.confident_moment_bundle_projection_items
  DROP CONSTRAINT IF EXISTS confident_moment_projection_item_coach_presentation_check;
 ALTER TABLE public.confident_moment_bundle_projection_items
  ADD CONSTRAINT confident_moment_projection_item_coach_presentation_check CHECK(
   resolution_state<>'coach_revision' OR presentation_id IS NOT NULL);
END $confident_moment_item_shape$;

CREATE OR REPLACE FUNCTION public.validate_confident_moment_projection_item_v1()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE projection_row public.confident_moment_bundle_projections;
 attachment_row public.confident_moment_bundle_attachments;
 feedback_exposure_row public.feedback_exposures;
 revision_row public.feedback_revisions;
 delivery_row public.feedback_language_revision_deliveries;
 presentation_row public.ml_presentations;
 exposure_row public.ml_rendered_exposures;
 expected_surface text;
 presentation_count integer;
BEGIN
 SELECT * INTO projection_row FROM public.confident_moment_bundle_projections
  WHERE id=NEW.projection_id AND acquisition_principal_id=NEW.acquisition_principal_id;
 SELECT * INTO attachment_row FROM public.confident_moment_bundle_attachments
  WHERE id=NEW.bundle_attachment_id
    AND acquisition_principal_id=NEW.acquisition_principal_id;
 SELECT * INTO feedback_exposure_row FROM public.feedback_exposures
  WHERE id=NEW.canonical_feedback_exposure_id
    AND candidate_id=NEW.attached_candidate_id
    AND feedback_family=NEW.feedback_family;
 IF projection_row.id IS NULL OR attachment_row.id IS NULL
  OR feedback_exposure_row.id IS NULL
  OR attachment_row.project_id IS DISTINCT FROM projection_row.project_id
  OR attachment_row.take_id IS DISTINCT FROM projection_row.take_id
  OR attachment_row.feedback_membership_id IS DISTINCT FROM projection_row.feedback_membership_id
  OR attachment_row.document_snapshot_id IS DISTINCT FROM projection_row.document_snapshot_id
  OR attachment_row.bundle_subject_candidate_id IS DISTINCT FROM NEW.bundle_subject_candidate_id
  OR attachment_row.attached_candidate_id IS DISTINCT FROM NEW.attached_candidate_id
  OR attachment_row.anchor_candidate_id IS DISTINCT FROM NEW.anchor_candidate_id
  OR attachment_row.canonical_position IS DISTINCT FROM NEW.canonical_position
  OR attachment_row.canonical_feedback_presentation_id IS DISTINCT FROM NEW.canonical_feedback_exposure_id
  OR feedback_exposure_row.candidate_set_id IS DISTINCT FROM
     (SELECT candidate_set_id FROM public.feedback_v3_memberships WHERE id=projection_row.feedback_membership_id)
  OR NOT feedback_exposure_row.is_selected
  OR NEW.candidate_output_sha256 IS DISTINCT FROM public.feedback_candidate_output_sha256_v1(NEW.attached_candidate_id) THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_ITEM_LINEAGE_INVALID';
 END IF;
 IF NEW.resolution_state='coach_revision' THEN
  SELECT * INTO revision_row FROM public.feedback_revisions WHERE id=NEW.revision_id;
  SELECT * INTO delivery_row FROM public.feedback_language_revision_deliveries WHERE id=NEW.delivery_id;
  IF revision_row.id IS NULL OR delivery_row.id IS NULL
   OR revision_row.taxonomy_version IS DISTINCT FROM 'feedback-language-coach-revision-v1'
   OR revision_row.acquisition_principal_id IS DISTINCT FROM NEW.acquisition_principal_id
   OR revision_row.feedback_membership_id IS DISTINCT FROM projection_row.feedback_membership_id
   OR revision_row.feedback_candidate_id IS DISTINCT FROM NEW.attached_candidate_id
   OR revision_row.revision_sha256 IS DISTINCT FROM NEW.output_sha256
   OR delivery_row.revision_id IS DISTINCT FROM revision_row.id
   OR delivery_row.recipient_principal_id IS DISTINCT FROM NEW.acquisition_principal_id
   OR delivery_row.acquisition_principal_id IS DISTINCT FROM NEW.acquisition_principal_id
   OR delivery_row.target_take_id IS DISTINCT FROM projection_row.take_id
   OR delivery_row.feedback_membership_id IS DISTINCT FROM projection_row.feedback_membership_id
   OR delivery_row.feedback_candidate_id IS DISTINCT FROM NEW.attached_candidate_id
   OR delivery_row.anchor_candidate_id IS DISTINCT FROM COALESCE(attachment_row.anchor_candidate_id,attachment_row.bundle_subject_candidate_id)
   OR delivery_row.reviewer_principal_id IS DISTINCT FROM revision_row.rater_id
   OR delivery_row.candidate_output_version IS DISTINCT FROM revision_row.candidate_output_version
   OR delivery_row.candidate_output_sha256 IS DISTINCT FROM revision_row.candidate_output_sha256
   OR delivery_row.delivery_policy_version IS DISTINCT FROM 'feedback-language-delivery-v2'
   OR delivery_row.delivery_state='invalidated'
   OR EXISTS(SELECT 1 FROM public.feedback_language_revision_deliveries successor WHERE successor.supersedes_delivery_id=delivery_row.id AND successor.delivery_policy_version='feedback-language-delivery-v2')
   OR EXISTS(SELECT 1 FROM public.feedback_revisions successor WHERE successor.supersedes_id=revision_row.id AND successor.taxonomy_version='feedback-language-coach-revision-v1') THEN
   RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_ITEM_LINEAGE_INVALID';
  END IF;
  PERFORM public.require_feedback_language_coach_source_live_v1(
   revision_row.id,NEW.acquisition_principal_id,projection_row.feedback_membership_id,
   NEW.attached_candidate_id,NEW.candidate_output_sha256,
   'CONFIDENT_MOMENT_PROJECTION_ITEM_LINEAGE_INVALID');
 expected_surface:=CASE revision_row.output_kind WHEN 'rephrase' THEN 'correction_generation' WHEN 'comment' THEN CASE revision_row.comment_purpose WHEN 'positive_praise' THEN 'praise_generation' ELSE 'coach_comment_generation' END END;
  SELECT count(*) INTO presentation_count FROM public.ml_presentations canonical_presentation
   WHERE canonical_presentation.artifact_id=revision_row.id
     AND canonical_presentation.actor_principal_id=NEW.acquisition_principal_id
     AND canonical_presentation.learning_surface_id=expected_surface
     AND canonical_presentation.delivery_mode<>'shadow';
  SELECT * INTO presentation_row FROM public.ml_presentations WHERE id=NEW.presentation_id;
  IF presentation_count<>1 OR presentation_row.id IS NULL
    OR presentation_row.artifact_id IS DISTINCT FROM revision_row.id
    OR presentation_row.actor_principal_id IS DISTINCT FROM NEW.acquisition_principal_id
    OR presentation_row.learning_surface_id IS DISTINCT FROM expected_surface
    OR presentation_row.delivery_mode='shadow' THEN
   RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_ITEM_LINEAGE_INVALID'; END IF;
  IF NEW.rendered_exposure_id IS NOT NULL THEN
   SELECT * INTO exposure_row FROM public.ml_rendered_exposures WHERE id=NEW.rendered_exposure_id;
   IF exposure_row.id IS NULL OR exposure_row.presentation_id IS DISTINCT FROM NEW.presentation_id
    OR exposure_row.actor_principal_id IS DISTINCT FROM NEW.acquisition_principal_id
    OR exposure_row.payload_sha256 IS DISTINCT FROM presentation_row.visible_payload_sha256 THEN
    RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_ITEM_LINEAGE_INVALID'; END IF;
  END IF;
 ELSIF NEW.resolution_state='excluded' AND NEW.delivery_id IS NOT NULL THEN
  SELECT * INTO delivery_row FROM public.feedback_language_revision_deliveries WHERE id=NEW.delivery_id;
  SELECT * INTO revision_row FROM public.feedback_revisions WHERE id=delivery_row.revision_id;
  IF delivery_row.id IS NULL OR revision_row.id IS NULL
   OR delivery_row.delivery_state IS DISTINCT FROM 'invalidated'
   OR delivery_row.delivery_policy_version IS DISTINCT FROM 'feedback-language-delivery-v2'
   OR delivery_row.recipient_principal_id IS DISTINCT FROM NEW.acquisition_principal_id
   OR delivery_row.acquisition_principal_id IS DISTINCT FROM NEW.acquisition_principal_id
   OR delivery_row.target_take_id IS DISTINCT FROM projection_row.take_id
   OR delivery_row.feedback_membership_id IS DISTINCT FROM projection_row.feedback_membership_id
   OR delivery_row.feedback_candidate_id IS DISTINCT FROM NEW.attached_candidate_id
   OR delivery_row.anchor_candidate_id IS DISTINCT FROM COALESCE(attachment_row.anchor_candidate_id,attachment_row.bundle_subject_candidate_id)
   OR revision_row.taxonomy_version IS DISTINCT FROM 'feedback-language-coach-revision-v1'
   OR revision_row.acquisition_principal_id IS DISTINCT FROM NEW.acquisition_principal_id
   OR revision_row.feedback_membership_id IS DISTINCT FROM projection_row.feedback_membership_id
   OR revision_row.feedback_candidate_id IS DISTINCT FROM NEW.attached_candidate_id
   OR delivery_row.reviewer_principal_id IS DISTINCT FROM revision_row.rater_id
   OR delivery_row.candidate_output_version IS DISTINCT FROM revision_row.candidate_output_version
   OR delivery_row.candidate_output_sha256 IS DISTINCT FROM revision_row.candidate_output_sha256
   OR revision_row.candidate_output_sha256 IS DISTINCT FROM NEW.candidate_output_sha256
   OR EXISTS(SELECT 1 FROM public.feedback_language_revision_deliveries successor WHERE successor.supersedes_delivery_id=delivery_row.id AND successor.delivery_policy_version='feedback-language-delivery-v2')
   OR EXISTS(SELECT 1 FROM public.feedback_revisions successor WHERE successor.supersedes_id=revision_row.id AND successor.taxonomy_version='feedback-language-coach-revision-v1') THEN
   RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_ITEM_LINEAGE_INVALID'; END IF;
  PERFORM public.require_feedback_language_coach_source_live_v1(
   revision_row.id,NEW.acquisition_principal_id,projection_row.feedback_membership_id,
   NEW.attached_candidate_id,NEW.candidate_output_sha256,
   'CONFIDENT_MOMENT_PROJECTION_ITEM_LINEAGE_INVALID');
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS confident_moment_projection_item_lineage_v1
 ON public.confident_moment_bundle_projection_items;
CREATE CONSTRAINT TRIGGER confident_moment_projection_item_lineage_v1 AFTER INSERT
 ON public.confident_moment_bundle_projection_items DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
 EXECUTE FUNCTION public.validate_confident_moment_projection_item_v1();

-- Reapply is an audit, never a backfill.  Existing projection rows must satisfy
-- the same exact relational contract as newly inserted rows.
DO $confident_moment_existing_projection_audit$
BEGIN
 IF EXISTS(
  SELECT 1
  FROM public.confident_moment_bundle_projection_items item
  LEFT JOIN public.confident_moment_bundle_projections projection
    ON projection.id=item.projection_id
   AND projection.acquisition_principal_id=item.acquisition_principal_id
  LEFT JOIN public.confident_moment_bundle_attachments attachment
    ON attachment.id=item.bundle_attachment_id
   AND attachment.acquisition_principal_id=item.acquisition_principal_id
  LEFT JOIN public.feedback_exposures feedback_exposure
    ON feedback_exposure.id=item.canonical_feedback_exposure_id
   AND feedback_exposure.candidate_id=item.attached_candidate_id
   AND feedback_exposure.feedback_family=item.feedback_family
  WHERE projection.id IS NULL OR attachment.id IS NULL
     OR feedback_exposure.id IS NULL
     OR attachment.project_id IS DISTINCT FROM projection.project_id
     OR attachment.take_id IS DISTINCT FROM projection.take_id
     OR attachment.feedback_membership_id IS DISTINCT FROM projection.feedback_membership_id
     OR attachment.document_snapshot_id IS DISTINCT FROM projection.document_snapshot_id
     OR attachment.bundle_subject_candidate_id IS DISTINCT FROM item.bundle_subject_candidate_id
     OR attachment.attached_candidate_id IS DISTINCT FROM item.attached_candidate_id
     OR attachment.anchor_candidate_id IS DISTINCT FROM item.anchor_candidate_id
     OR attachment.canonical_position IS DISTINCT FROM item.canonical_position
     OR attachment.canonical_feedback_presentation_id IS DISTINCT FROM item.canonical_feedback_exposure_id
     OR feedback_exposure.candidate_set_id IS DISTINCT FROM
        (SELECT candidate_set_id FROM public.feedback_v3_memberships WHERE id=projection.feedback_membership_id)
     OR NOT feedback_exposure.is_selected
     OR item.candidate_output_sha256 IS DISTINCT FROM public.feedback_candidate_output_sha256_v1(item.attached_candidate_id)
 ) OR EXISTS(
  SELECT 1
  FROM public.confident_moment_bundle_projection_items item
  JOIN public.confident_moment_bundle_projections projection ON projection.id=item.projection_id
  LEFT JOIN public.confident_moment_bundle_attachments attachment ON attachment.id=item.bundle_attachment_id
  LEFT JOIN public.feedback_revisions revision ON revision.id=item.revision_id
  LEFT JOIN public.feedback_language_revision_deliveries delivery ON delivery.id=item.delivery_id
  LEFT JOIN public.ml_presentations presentation ON presentation.id=item.presentation_id
  LEFT JOIN public.ml_rendered_exposures exposure ON exposure.id=item.rendered_exposure_id
  WHERE item.resolution_state='coach_revision' AND (
    revision.id IS NULL OR delivery.id IS NULL
    OR revision.taxonomy_version IS DISTINCT FROM 'feedback-language-coach-revision-v1'
    OR revision.acquisition_principal_id IS DISTINCT FROM item.acquisition_principal_id
    OR revision.feedback_membership_id IS DISTINCT FROM projection.feedback_membership_id
    OR revision.feedback_candidate_id IS DISTINCT FROM item.attached_candidate_id
    OR revision.revision_sha256 IS DISTINCT FROM item.output_sha256
    OR delivery.revision_id IS DISTINCT FROM revision.id
    OR delivery.recipient_principal_id IS DISTINCT FROM item.acquisition_principal_id
    OR delivery.acquisition_principal_id IS DISTINCT FROM item.acquisition_principal_id
    OR delivery.target_take_id IS DISTINCT FROM projection.take_id
    OR delivery.feedback_membership_id IS DISTINCT FROM projection.feedback_membership_id
    OR delivery.feedback_candidate_id IS DISTINCT FROM item.attached_candidate_id
    OR delivery.anchor_candidate_id IS DISTINCT FROM COALESCE(attachment.anchor_candidate_id,attachment.bundle_subject_candidate_id)
    OR delivery.reviewer_principal_id IS DISTINCT FROM revision.rater_id
    OR delivery.candidate_output_version IS DISTINCT FROM revision.candidate_output_version
    OR delivery.candidate_output_sha256 IS DISTINCT FROM revision.candidate_output_sha256
    OR delivery.delivery_policy_version IS DISTINCT FROM 'feedback-language-delivery-v2'
    OR delivery.delivery_state='invalidated'
    OR EXISTS(SELECT 1 FROM public.feedback_language_revision_deliveries successor
      WHERE successor.supersedes_delivery_id=delivery.id
        AND successor.delivery_policy_version='feedback-language-delivery-v2')
    OR EXISTS(SELECT 1 FROM public.feedback_revisions successor
      WHERE successor.supersedes_id=revision.id
        AND successor.taxonomy_version='feedback-language-coach-revision-v1')
    OR item.presentation_id IS NULL
    OR presentation.id IS NULL OR presentation.artifact_id IS DISTINCT FROM revision.id
      OR presentation.actor_principal_id IS DISTINCT FROM item.acquisition_principal_id
      OR presentation.learning_surface_id IS DISTINCT FROM CASE revision.output_kind
        WHEN 'rephrase' THEN 'correction_generation'
        WHEN 'comment' THEN CASE revision.comment_purpose
          WHEN 'positive_praise' THEN 'praise_generation'
          ELSE 'coach_comment_generation' END END
      OR presentation.delivery_mode='shadow'
    OR (SELECT count(*) FROM public.ml_presentations canonical_presentation
      WHERE canonical_presentation.artifact_id=revision.id
        AND canonical_presentation.actor_principal_id=item.acquisition_principal_id
        AND canonical_presentation.learning_surface_id=CASE revision.output_kind
          WHEN 'rephrase' THEN 'correction_generation'
          WHEN 'comment' THEN CASE revision.comment_purpose
            WHEN 'positive_praise' THEN 'praise_generation'
            ELSE 'coach_comment_generation' END END
        AND canonical_presentation.delivery_mode<>'shadow')<>1
    OR (item.rendered_exposure_id IS NOT NULL AND (
      exposure.id IS NULL OR exposure.presentation_id IS DISTINCT FROM item.presentation_id
      OR exposure.actor_principal_id IS DISTINCT FROM item.acquisition_principal_id
      OR exposure.payload_sha256 IS DISTINCT FROM presentation.visible_payload_sha256))
  )
 ) OR EXISTS(
  SELECT 1
  FROM public.confident_moment_bundle_projection_items item
  JOIN public.confident_moment_bundle_projections projection ON projection.id=item.projection_id
  LEFT JOIN public.confident_moment_bundle_attachments attachment ON attachment.id=item.bundle_attachment_id
  LEFT JOIN public.feedback_language_revision_deliveries delivery ON delivery.id=item.delivery_id
  LEFT JOIN public.feedback_revisions revision ON revision.id=delivery.revision_id
  WHERE item.resolution_state='excluded' AND item.delivery_id IS NOT NULL
    AND (delivery.id IS NULL OR revision.id IS NULL
      OR delivery.delivery_state IS DISTINCT FROM 'invalidated'
      OR delivery.delivery_policy_version IS DISTINCT FROM 'feedback-language-delivery-v2'
      OR delivery.recipient_principal_id IS DISTINCT FROM item.acquisition_principal_id
      OR delivery.acquisition_principal_id IS DISTINCT FROM item.acquisition_principal_id
      OR delivery.target_take_id IS DISTINCT FROM projection.take_id
      OR delivery.feedback_membership_id IS DISTINCT FROM projection.feedback_membership_id
      OR delivery.feedback_candidate_id IS DISTINCT FROM item.attached_candidate_id
      OR delivery.anchor_candidate_id IS DISTINCT FROM COALESCE(attachment.anchor_candidate_id,attachment.bundle_subject_candidate_id)
      OR revision.taxonomy_version IS DISTINCT FROM 'feedback-language-coach-revision-v1'
      OR revision.acquisition_principal_id IS DISTINCT FROM item.acquisition_principal_id
      OR revision.feedback_membership_id IS DISTINCT FROM projection.feedback_membership_id
      OR revision.feedback_candidate_id IS DISTINCT FROM item.attached_candidate_id
      OR delivery.reviewer_principal_id IS DISTINCT FROM revision.rater_id
      OR delivery.candidate_output_version IS DISTINCT FROM revision.candidate_output_version
      OR delivery.candidate_output_sha256 IS DISTINCT FROM revision.candidate_output_sha256
      OR revision.candidate_output_sha256 IS DISTINCT FROM item.candidate_output_sha256
      OR EXISTS(SELECT 1 FROM public.feedback_language_revision_deliveries successor
        WHERE successor.supersedes_delivery_id=delivery.id
          AND successor.delivery_policy_version='feedback-language-delivery-v2')
      OR EXISTS(SELECT 1 FROM public.feedback_revisions successor
        WHERE successor.supersedes_id=revision.id
          AND successor.taxonomy_version='feedback-language-coach-revision-v1'))
 ) THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_EXISTING_PROJECTION_LINEAGE_INVALID';
 END IF;
END
$confident_moment_existing_projection_audit$;

-- D11 section 4.3 exact coach authority, in ONE canonical implementation.
-- The secure projection and the render acknowledgement must enforce identical
-- reviewer access, blind assignment, source authority and source
-- deletion/purge validity; duplicating the chain let the exposure writer drift
-- weaker than the reader.  p_invalid_error preserves each caller's frozen
-- typed error identity.
CREATE OR REPLACE FUNCTION public.require_feedback_language_coach_source_live_v1(
 p_revision_id uuid,p_acquisition_principal_id uuid,p_feedback_membership_id uuid,
 p_feedback_candidate_id uuid,p_candidate_output_sha256 text,p_invalid_error text
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE reviewer_principal_id uuid; assignment_id uuid; live_membership public.feedback_v3_memberships;
BEGIN
 IF NOT EXISTS(SELECT 1 FROM public.feedback_revisions revision_row
   JOIN public.feedback_v3_memberships membership
     ON membership.id=revision_row.feedback_membership_id
    AND membership.acquisition_principal_id=revision_row.acquisition_principal_id
   JOIN public.coach_guidance_reveal_accesses access_row
     ON access_row.id=revision_row.reveal_access_id
    AND access_row.reveal_grant_id=revision_row.reveal_grant_id
    AND access_row.reviewer_principal_id=revision_row.rater_id
    AND access_row.review_assignment_id=revision_row.review_assignment_id
    AND access_row.blind_judgment_id=revision_row.blind_judgment_id
    AND access_row.acquisition_principal_id=revision_row.acquisition_principal_id
    AND access_row.access_purpose='guidance_authoring'
   JOIN public.coach_guidance_reveal_grants grant_row
    ON grant_row.id=revision_row.reveal_grant_id
    AND grant_row.review_batch_id=revision_row.review_batch_id
    AND grant_row.reviewer_principal_id=revision_row.rater_id
   JOIN public.coach_guidance_reveal_grant_judgments grant_judgment
     ON grant_judgment.reveal_grant_id=grant_row.id
    AND grant_judgment.review_assignment_id=revision_row.review_assignment_id
    AND grant_judgment.judgment_id=revision_row.blind_judgment_id
    AND grant_judgment.acquisition_principal_id=revision_row.acquisition_principal_id
   JOIN public.coach_guidance_review_batches batch
     ON batch.id=revision_row.review_batch_id
    AND batch.acquisition_principal_id=revision_row.acquisition_principal_id
    AND batch.reviewer_principal_id=revision_row.rater_id
   JOIN public.coach_guidance_review_frames frame
     ON frame.id=batch.frame_id
    AND frame.acquisition_principal_id=batch.acquisition_principal_id
    AND frame.reviewer_principal_id=batch.reviewer_principal_id
   JOIN public.coach_guidance_review_frame_items frame_item
     ON frame_item.frame_id=frame.id
    AND frame_item.review_assignment_id=revision_row.review_assignment_id
    AND frame_item.acquisition_principal_id=revision_row.acquisition_principal_id
    AND frame_item.reviewer_principal_id=revision_row.rater_id
    AND frame_item.membership_state='required'
   JOIN public.ml_judgments judgment
     ON judgment.id=revision_row.blind_judgment_id
    AND judgment.review_assignment_id=revision_row.review_assignment_id
    AND judgment.actor_principal_id=revision_row.rater_id
    AND judgment.actor_provenance='blind_coach'
   JOIN public.coach_inline_source_roles source_role
     ON source_role.review_batch_id=batch.id
    AND source_role.review_assignment_id=revision_row.review_assignment_id
    AND source_role.acquisition_principal_id=revision_row.acquisition_principal_id
    AND source_role.reviewer_principal_id=revision_row.rater_id
    AND source_role.evidence_role='source_before_exercise'
   JOIN public.exercise_blind_packets packet
     ON packet.id=source_role.blind_packet_id
    AND packet.id=frame_item.blind_packet_id
    AND packet.review_assignment_id=source_role.review_assignment_id
    AND packet.audio_lineage_id=source_role.audio_lineage_id
    AND packet.reviewer_principal_id=revision_row.rater_id
   JOIN public.exercise_audio_lineages lineage
     ON lineage.id=packet.audio_lineage_id
    AND lineage.acquisition_principal_id=revision_row.acquisition_principal_id
   JOIN public.processing_audio_objects audio_object
     ON audio_object.id=lineage.processing_audio_object_id
    AND audio_object.acquisition_principal_id=lineage.acquisition_principal_id
    AND audio_object.recording_attempt_id=lineage.recording_attempt_id
    AND audio_object.exact_bytes_sha256=lineage.exact_audio_sha256
    AND audio_object.deleted_at IS NULL
   JOIN public.snippets snippet
     ON snippet.id=lineage.snippet_id AND snippet.session_id=lineage.take_id
    AND snippet.recording_id=lineage.recording_id
   JOIN public.ml_review_assignments assignment
     ON assignment.id=revision_row.review_assignment_id
    AND assignment.reviewer_principal_id=revision_row.rater_id
    AND assignment.reviewer_role='coach'
    AND assignment.learning_surface_id='confidence_classification'
   JOIN public.ml_evidence_spans evidence
     ON evidence.id=assignment.evidence_span_id
    AND evidence.id=revision_row.evidence_span_id
    AND evidence.acquisition_principal_id=revision_row.acquisition_principal_id
    AND evidence.recording_attempt_id=lineage.recording_attempt_id
    AND evidence.take_id=lineage.take_id
   JOIN public.feedback_v3_membership_items exact_item
     ON exact_item.membership_id=revision_row.feedback_membership_id
    AND exact_item.candidate_id=revision_row.feedback_candidate_id
    AND exact_item.evidence_span_id=evidence.id
    AND exact_item.snippet_id=snippet.id
    AND exact_item.selected
   WHERE revision_row.id=p_revision_id
     AND revision_row.taxonomy_version='feedback-language-coach-revision-v1'
     AND revision_row.feedback_membership_id=p_feedback_membership_id
     AND revision_row.feedback_candidate_id=p_feedback_candidate_id
     AND revision_row.acquisition_principal_id=p_acquisition_principal_id
     AND revision_row.rater_role='coach'
     AND revision_row.candidate_output_sha256=p_candidate_output_sha256
     AND NOT EXISTS(SELECT 1 FROM public.processing_audio_object_deletion_events deletion WHERE deletion.audio_object_id=audio_object.id)
     AND public.feedback_candidate_output_sha256_v1(revision_row.feedback_candidate_id)=p_candidate_output_sha256) THEN
  RAISE EXCEPTION USING MESSAGE=p_invalid_error;
 END IF;
 SELECT revision_row.rater_id,revision_row.review_assignment_id
   INTO STRICT reviewer_principal_id,assignment_id
   FROM public.feedback_revisions revision_row WHERE revision_row.id=p_revision_id;
 PERFORM public.require_coach_guidance_reviewer_access_v1(reviewer_principal_id);
 PERFORM public.require_coach_guidance_assignment_live_v1(
  assignment_id,p_acquisition_principal_id,'coach_review');
 live_membership:=public.require_feedback_v3_service_membership_live_v1(
  p_feedback_membership_id,p_acquisition_principal_id);
END $$;

-- Existing coach-backed projection items are also a live-authority audit on
-- reapply. Explicit delivery invalidation does not preserve stale reviewer or
-- deleted source authority.
DO $confident_moment_existing_projection_authority_audit$
DECLARE projection_item record;
BEGIN
 FOR projection_item IN
  SELECT item.acquisition_principal_id,item.attached_candidate_id,
         item.candidate_output_sha256,projection.feedback_membership_id,
         COALESCE(item.revision_id,delivery.revision_id) revision_id
  FROM public.confident_moment_bundle_projection_items item
  JOIN public.confident_moment_bundle_projections projection
    ON projection.id=item.projection_id
  LEFT JOIN public.feedback_language_revision_deliveries delivery
    ON delivery.id=item.delivery_id
  WHERE item.resolution_state='coach_revision'
     OR (item.resolution_state='excluded'
         AND item.exclusion_reason='delivery_explicitly_invalidated')
 LOOP
  PERFORM public.require_feedback_language_coach_source_live_v1(
   projection_item.revision_id,projection_item.acquisition_principal_id,
   projection_item.feedback_membership_id,projection_item.attached_candidate_id,
   projection_item.candidate_output_sha256,
   'CONFIDENT_MOMENT_EXISTING_PROJECTION_LINEAGE_INVALID');
 END LOOP;
END
$confident_moment_existing_projection_authority_audit$;

CREATE OR REPLACE FUNCTION public.derive_confident_moment_owner_decision_v1(
 p_acquisition_principal_id uuid,p_feedback_membership_id uuid,
 p_bundle_attachment_id uuid
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE a public.confident_moment_bundle_attachments;
 owner_binding public.confident_moment_owner_decision_bindings;
 decision_count integer; canonical_value text;
BEGIN
 SELECT * INTO STRICT a FROM public.confident_moment_bundle_attachments x
  WHERE x.id=p_bundle_attachment_id AND x.acquisition_principal_id=p_acquisition_principal_id
    AND x.feedback_membership_id=p_feedback_membership_id;
 SELECT count(*),(array_agg(b.id ORDER BY b.created_at,b.id))[1]
 INTO decision_count,owner_binding.id
 FROM public.confident_moment_owner_decision_bindings b
 WHERE b.bundle_attachment_id=a.id
   AND b.acquisition_principal_id=p_acquisition_principal_id
   AND b.feedback_membership_id=p_feedback_membership_id;
 IF decision_count=0 THEN RETURN NULL; END IF;
 IF decision_count<>1 THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_INVALID'; END IF;
 SELECT * INTO STRICT owner_binding
 FROM public.confident_moment_owner_decision_bindings b WHERE b.id=owner_binding.id;
 IF owner_binding.project_id<>a.project_id OR owner_binding.take_id<>a.take_id
    OR owner_binding.bundle_subject_candidate_id<>a.bundle_subject_candidate_id
    OR owner_binding.candidate_id<>a.attached_candidate_id
    OR owner_binding.evidence_span_id<>a.attached_evidence_span_id
    OR owner_binding.canonical_feedback_presentation_id<>a.canonical_feedback_presentation_id
 THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_INVALID'; END IF;
 IF owner_binding.feedback_family='confident_voice' THEN
  PERFORM public.require_feedback_v3_service_response_v1(
   owner_binding.response_binding_id,p_acquisition_principal_id,p_feedback_membership_id,
   a.attached_candidate_id,a.canonical_feedback_presentation_id);
  SELECT response INTO STRICT canonical_value FROM public.feedback_v3_owner_responses
   WHERE id=owner_binding.owner_response_id AND acquisition_principal_id=p_acquisition_principal_id;
 ELSIF owner_binding.feedback_family='rewrite_clarity' THEN
  SELECT value INTO STRICT canonical_value FROM public.correction_decisions
   WHERE id=owner_binding.correction_decision_id AND evidence_span_id=a.attached_evidence_span_id;
 ELSE
  SELECT value INTO STRICT canonical_value FROM public.praise_helpfulness
   WHERE id=owner_binding.praise_helpfulness_id AND evidence_span_id=a.attached_evidence_span_id;
 END IF;
 IF canonical_value<>owner_binding.canonical_response THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_INVALID'; END IF;
 RETURN jsonb_build_object('feedback_family',owner_binding.feedback_family,
  'response',owner_binding.interaction_response,'decision_id',owner_binding.decision_id,
  'owner_response_id',owner_binding.owner_response_id,
  'response_binding_id',owner_binding.response_binding_id);
END $$;

CREATE OR REPLACE FUNCTION public.project_confident_moment_bundles_v1(
 p_acquisition_principal_id uuid,p_project_id uuid,p_take_id uuid
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE membership public.feedback_v3_memberships; snapshot public.ideal_text_document_snapshots;
 attachment record; subject record; audio_id uuid; inventory_before text; inventory_after text;
 projection public.confident_moment_bundle_projections; projection_key text;
 bundles jsonb:='[]'::jsonb; summary_items jsonb:='[]'::jsonb; coverage jsonb;
 bundle jsonb; summary jsonb; body jsonb; response_hash text; summary_hash text;
 root_head public.root_phrase_block_heads; root_action public.root_phrase_product_actions;
 feedback_language_items jsonb; item_output jsonb; item_coach_update jsonb;
 source_passage_payload jsonb; update_text_available boolean; bundle_has_update boolean;
 coach_revision_id uuid; unread boolean;
 resolution text; exclusion text; output_hash text; delivery_id uuid;
 current_presentation_id uuid; current_rendered_exposure_id uuid; presentation_count integer;
 rendered_count integer; current_count integer; item_hash text;
 owner_decision jsonb;
 bundle_unread boolean; revision_sha256 text; delivery_subject_sha256 text;
 delivery_anchor_candidate_id uuid;
BEGIN
 PERFORM public.lock_confident_moment_inventory_v1(p_acquisition_principal_id,p_project_id,p_take_id);
 PERFORM public.require_mlc3_service_access_v2(p_acquisition_principal_id,NULL,NULL);
 SELECT count(*) INTO current_count FROM public.feedback_v3_memberships candidate_membership
  JOIN public.ideal_text_document_heads head ON head.snapshot_id=candidate_membership.document_snapshot_id
  WHERE candidate_membership.acquisition_principal_id=p_acquisition_principal_id
    AND candidate_membership.project_id=p_project_id AND candidate_membership.take_id=p_take_id;
 IF current_count<>1 THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_MEMBERSHIP_INVALID'; END IF;
 SELECT candidate_membership.* INTO STRICT membership FROM public.feedback_v3_memberships candidate_membership
  JOIN public.ideal_text_document_heads head ON head.snapshot_id=candidate_membership.document_snapshot_id
  WHERE candidate_membership.acquisition_principal_id=p_acquisition_principal_id
    AND candidate_membership.project_id=p_project_id AND candidate_membership.take_id=p_take_id;
 membership:=public.require_feedback_v3_service_membership_live_v1(membership.id,p_acquisition_principal_id);
 SELECT * INTO STRICT snapshot FROM public.ideal_text_document_snapshots WHERE id=membership.document_snapshot_id;
 SELECT public.exercise_json_sha256_v1(jsonb_build_object(
  'membership',membership.id,'snapshot',snapshot.id,
  'attachments',COALESCE((SELECT jsonb_agg(jsonb_build_array(a.id,a.bundle_subject_candidate_id,a.attached_candidate_id,c.feedback_family,a.canonical_feedback_presentation_id,a.canonical_position) ORDER BY a.canonical_position,a.attached_candidate_id) FROM public.confident_moment_bundle_attachments a JOIN public.feedback_candidates c ON c.id=a.attached_candidate_id WHERE a.acquisition_principal_id=p_acquisition_principal_id AND a.project_id=p_project_id AND a.take_id=p_take_id),'[]'::jsonb),
  'heads',COALESCE((SELECT jsonb_agg(jsonb_build_array(h.slide_index,h.block_key,h.active_root_action_id,h.interaction_state_revision) ORDER BY h.slide_index,h.block_key) FROM public.root_phrase_block_heads h WHERE h.acquisition_principal_id=p_acquisition_principal_id AND h.project_id=p_project_id),'[]'::jsonb),
  'deliveries',COALESCE((SELECT jsonb_agg(jsonb_build_array(d.id,d.revision_id,d.anchor_candidate_id,d.delivery_state,d.delivery_revision,d.supersedes_delivery_id) ORDER BY d.feedback_candidate_id,d.delivery_revision,d.id) FROM public.feedback_language_revision_deliveries d WHERE d.recipient_principal_id=p_acquisition_principal_id AND d.target_take_id=p_take_id AND d.delivery_policy_version='feedback-language-delivery-v2'),'[]'::jsonb),
  'render_state',COALESCE((SELECT jsonb_agg(jsonb_build_array(d.id,p.id,e.id,e.render_instance_id,e.payload_sha256) ORDER BY d.feedback_candidate_id,d.delivery_revision,d.id,p.id,e.authenticated_at,e.id) FROM public.feedback_language_revision_deliveries d JOIN public.feedback_revisions r ON r.id=d.revision_id JOIN public.ml_presentations p ON p.artifact_id=d.revision_id AND p.actor_principal_id=d.recipient_principal_id AND p.delivery_mode<>'shadow' AND p.learning_surface_id=(CASE r.output_kind WHEN 'rephrase' THEN 'correction_generation' WHEN 'comment' THEN CASE r.comment_purpose WHEN 'positive_praise' THEN 'praise_generation' ELSE 'coach_comment_generation' END END) LEFT JOIN public.ml_rendered_exposures e ON e.presentation_id=p.id AND e.actor_principal_id=d.recipient_principal_id WHERE d.recipient_principal_id=p_acquisition_principal_id AND d.target_take_id=p_take_id AND d.delivery_policy_version='feedback-language-delivery-v2'),'[]'::jsonb),
  'audio_state',jsonb_build_object('objects',COALESCE((SELECT jsonb_agg(jsonb_build_array(o.id,o.exact_bytes_sha256,o.deleted_at) ORDER BY o.id) FROM public.processing_audio_objects o WHERE o.acquisition_principal_id=p_acquisition_principal_id AND o.recording_attempt_id=p_take_id),'[]'::jsonb),'deletions',COALESCE((SELECT jsonb_agg(jsonb_build_array(x.id,x.audio_object_id,x.purge_request_id,x.evidence_sha256) ORDER BY x.id) FROM public.processing_audio_object_deletion_events x JOIN public.processing_audio_objects o ON o.id=x.audio_object_id WHERE o.acquisition_principal_id=p_acquisition_principal_id AND o.recording_attempt_id=p_take_id),'[]'::jsonb),'purges',COALESCE((SELECT jsonb_agg(jsonb_build_array(q.id,q.state) ORDER BY q.id) FROM public.data_purge_requests q WHERE q.acquisition_principal_id=p_acquisition_principal_id),'[]'::jsonb)),
  'revisions',COALESCE((SELECT jsonb_agg(jsonb_build_array(r.id,r.supersedes_id,r.revision_sha256) ORDER BY r.feedback_candidate_id,r.rater_id,r.created_at,r.id) FROM public.feedback_revisions r WHERE r.acquisition_principal_id=p_acquisition_principal_id AND r.feedback_membership_id=membership.id AND r.taxonomy_version='feedback-language-coach-revision-v1'),'[]'::jsonb),
  'owner_decisions',COALESCE((SELECT jsonb_agg(jsonb_build_array(
    b.id,b.bundle_attachment_id,b.candidate_id,b.feedback_family,b.decision_id,
    b.owner_response_id,b.response_binding_id,b.interaction_response,
    b.canonical_response,b.decision_sha256) ORDER BY b.bundle_attachment_id,b.id)
   FROM public.confident_moment_owner_decision_bindings b
   WHERE b.acquisition_principal_id=p_acquisition_principal_id
     AND b.feedback_membership_id=membership.id),'[]'::jsonb))) INTO inventory_before;
 PERFORM pg_advisory_xact_lock(hashtextextended('feedback-v3-membership-current:'||membership.id::text,0));
 PERFORM pg_advisory_xact_lock(hashtextextended('ideal-text-document-head:'||p_project_id::text,0));
 PERFORM pg_advisory_xact_lock(hashtextextended('ideal-text-document-snapshot:'||snapshot.id::text,0));
 FOR audio_id IN SELECT DISTINCT object_row.recording_attempt_id FROM public.processing_audio_objects object_row WHERE object_row.acquisition_principal_id=p_acquisition_principal_id AND object_row.recording_attempt_id=p_take_id ORDER BY object_row.recording_attempt_id LOOP
  PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-speaker-attempt:'||audio_id::text,0));
 END LOOP;
 FOR audio_id IN SELECT object_row.id FROM public.processing_audio_objects object_row WHERE object_row.recording_attempt_id=p_take_id AND object_row.acquisition_principal_id=p_acquisition_principal_id ORDER BY object_row.id LOOP
  PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-processing-audio-object:'||audio_id::text,0));
 END LOOP;
 FOR attachment IN SELECT * FROM public.confident_moment_bundle_attachments a WHERE a.acquisition_principal_id=p_acquisition_principal_id AND a.project_id=p_project_id AND a.take_id=p_take_id ORDER BY a.canonical_position,a.bundle_subject_candidate_id LOOP
  PERFORM pg_advisory_xact_lock(hashtextextended('confident-moment-bundle-subject:'||membership.id::text||':'||attachment.bundle_subject_candidate_id::text,0));
 END LOOP;
 FOR attachment IN SELECT * FROM public.confident_moment_bundle_attachments a
  WHERE a.acquisition_principal_id=p_acquisition_principal_id
    AND a.project_id=p_project_id AND a.take_id=p_take_id
  ORDER BY convert_to(a.feedback_membership_id::text||':'||a.attached_candidate_id::text||':'||a.id::text,'UTF8') LOOP
  PERFORM pg_advisory_xact_lock(hashtextextended(
   'confident-moment-owner-decision:'||attachment.feedback_membership_id::text||':'||
   attachment.attached_candidate_id::text||':'||attachment.id::text,0));
 END LOOP;
 FOR subject IN SELECT DISTINCT item.slide_index,item.block_key FROM public.confident_moment_bundle_attachments a JOIN public.feedback_v3_membership_items item ON item.membership_id=a.feedback_membership_id AND item.candidate_id=a.bundle_subject_candidate_id WHERE a.acquisition_principal_id=p_acquisition_principal_id AND a.project_id=p_project_id AND a.take_id=p_take_id ORDER BY item.slide_index,item.block_key LOOP
  PERFORM pg_advisory_xact_lock(hashtextextended('root-block:'||p_project_id::text||':'||subject.slide_index::text||':'||subject.block_key::text,0));
 END LOOP;
 FOR subject IN SELECT d.feedback_candidate_id,d.reviewer_principal_id,d.recipient_principal_id,d.target_take_id,d.feedback_membership_id FROM public.feedback_language_revision_deliveries d WHERE d.recipient_principal_id=p_acquisition_principal_id AND d.target_take_id=p_take_id AND d.delivery_policy_version='feedback-language-delivery-v2' ORDER BY d.feedback_candidate_id,d.reviewer_principal_id,d.id LOOP
  PERFORM pg_advisory_xact_lock(hashtextextended('feedback-language-candidate:'||subject.feedback_candidate_id::text||':'||subject.reviewer_principal_id::text,0));
  PERFORM pg_advisory_xact_lock(hashtextextended('feedback-language-delivery-subject:'||subject.recipient_principal_id::text||':'||subject.target_take_id::text||':'||subject.feedback_membership_id::text||':'||subject.feedback_candidate_id::text,0));
  PERFORM pg_advisory_xact_lock(hashtextextended('feedback-language-revision-head:'||subject.feedback_membership_id::text||':'||subject.feedback_candidate_id::text||':'||subject.reviewer_principal_id::text,0));
 END LOOP;
 SELECT public.exercise_json_sha256_v1(jsonb_build_object(
  'membership',membership.id,'snapshot',snapshot.id,
  'attachments',COALESCE((SELECT jsonb_agg(jsonb_build_array(a.id,a.bundle_subject_candidate_id,a.attached_candidate_id,c.feedback_family,a.canonical_feedback_presentation_id,a.canonical_position) ORDER BY a.canonical_position,a.attached_candidate_id) FROM public.confident_moment_bundle_attachments a JOIN public.feedback_candidates c ON c.id=a.attached_candidate_id WHERE a.acquisition_principal_id=p_acquisition_principal_id AND a.project_id=p_project_id AND a.take_id=p_take_id),'[]'::jsonb),
  'heads',COALESCE((SELECT jsonb_agg(jsonb_build_array(h.slide_index,h.block_key,h.active_root_action_id,h.interaction_state_revision) ORDER BY h.slide_index,h.block_key) FROM public.root_phrase_block_heads h WHERE h.acquisition_principal_id=p_acquisition_principal_id AND h.project_id=p_project_id),'[]'::jsonb),
  'deliveries',COALESCE((SELECT jsonb_agg(jsonb_build_array(d.id,d.revision_id,d.anchor_candidate_id,d.delivery_state,d.delivery_revision,d.supersedes_delivery_id) ORDER BY d.feedback_candidate_id,d.delivery_revision,d.id) FROM public.feedback_language_revision_deliveries d WHERE d.recipient_principal_id=p_acquisition_principal_id AND d.target_take_id=p_take_id AND d.delivery_policy_version='feedback-language-delivery-v2'),'[]'::jsonb),
  'render_state',COALESCE((SELECT jsonb_agg(jsonb_build_array(d.id,p.id,e.id,e.render_instance_id,e.payload_sha256) ORDER BY d.feedback_candidate_id,d.delivery_revision,d.id,p.id,e.authenticated_at,e.id) FROM public.feedback_language_revision_deliveries d JOIN public.feedback_revisions r ON r.id=d.revision_id JOIN public.ml_presentations p ON p.artifact_id=d.revision_id AND p.actor_principal_id=d.recipient_principal_id AND p.delivery_mode<>'shadow' AND p.learning_surface_id=(CASE r.output_kind WHEN 'rephrase' THEN 'correction_generation' WHEN 'comment' THEN CASE r.comment_purpose WHEN 'positive_praise' THEN 'praise_generation' ELSE 'coach_comment_generation' END END) LEFT JOIN public.ml_rendered_exposures e ON e.presentation_id=p.id AND e.actor_principal_id=d.recipient_principal_id WHERE d.recipient_principal_id=p_acquisition_principal_id AND d.target_take_id=p_take_id AND d.delivery_policy_version='feedback-language-delivery-v2'),'[]'::jsonb),
  'audio_state',jsonb_build_object('objects',COALESCE((SELECT jsonb_agg(jsonb_build_array(o.id,o.exact_bytes_sha256,o.deleted_at) ORDER BY o.id) FROM public.processing_audio_objects o WHERE o.acquisition_principal_id=p_acquisition_principal_id AND o.recording_attempt_id=p_take_id),'[]'::jsonb),'deletions',COALESCE((SELECT jsonb_agg(jsonb_build_array(x.id,x.audio_object_id,x.purge_request_id,x.evidence_sha256) ORDER BY x.id) FROM public.processing_audio_object_deletion_events x JOIN public.processing_audio_objects o ON o.id=x.audio_object_id WHERE o.acquisition_principal_id=p_acquisition_principal_id AND o.recording_attempt_id=p_take_id),'[]'::jsonb),'purges',COALESCE((SELECT jsonb_agg(jsonb_build_array(q.id,q.state) ORDER BY q.id) FROM public.data_purge_requests q WHERE q.acquisition_principal_id=p_acquisition_principal_id),'[]'::jsonb)),
  'revisions',COALESCE((SELECT jsonb_agg(jsonb_build_array(r.id,r.supersedes_id,r.revision_sha256) ORDER BY r.feedback_candidate_id,r.rater_id,r.created_at,r.id) FROM public.feedback_revisions r WHERE r.acquisition_principal_id=p_acquisition_principal_id AND r.feedback_membership_id=membership.id AND r.taxonomy_version='feedback-language-coach-revision-v1'),'[]'::jsonb),
  'owner_decisions',COALESCE((SELECT jsonb_agg(jsonb_build_array(
    b.id,b.bundle_attachment_id,b.candidate_id,b.feedback_family,b.decision_id,
    b.owner_response_id,b.response_binding_id,b.interaction_response,
    b.canonical_response,b.decision_sha256) ORDER BY b.bundle_attachment_id,b.id)
   FROM public.confident_moment_owner_decision_bindings b
   WHERE b.acquisition_principal_id=p_acquisition_principal_id
     AND b.feedback_membership_id=membership.id),'[]'::jsonb))) INTO inventory_after;
 IF inventory_after<>inventory_before THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_RETRY_REQUIRED'; END IF;
 membership:=public.require_feedback_v3_service_membership_live_v1(membership.id,p_acquisition_principal_id);
 IF NOT EXISTS(SELECT 1 FROM public.ideal_text_document_heads WHERE snapshot_id=snapshot.id) THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_STALE_REVISION'; END IF;
 SELECT * INTO projection FROM public.confident_moment_bundle_projections p
  WHERE p.acquisition_principal_id=p_acquisition_principal_id AND p.project_id=p_project_id
    AND p.take_id=p_take_id AND p.stabilized_inventory_sha256=inventory_after;
 IF projection.id IS NULL THEN projection.id:=gen_random_uuid(); END IF;
 FOR subject IN SELECT DISTINCT ON(a.bundle_subject_candidate_id) a.*,item.slide_index,item.block_key FROM public.confident_moment_bundle_attachments a JOIN public.feedback_v3_membership_items item ON item.membership_id=a.feedback_membership_id AND item.candidate_id=a.bundle_subject_candidate_id WHERE a.acquisition_principal_id=p_acquisition_principal_id AND a.project_id=p_project_id AND a.take_id=p_take_id ORDER BY a.bundle_subject_candidate_id,a.canonical_position LOOP
  SELECT * INTO root_head FROM public.root_phrase_block_heads h WHERE h.acquisition_principal_id=p_acquisition_principal_id AND h.project_id=p_project_id AND h.slide_index=subject.slide_index AND h.block_key=subject.block_key;
  SELECT * INTO root_action FROM public.root_phrase_product_actions WHERE id=root_head.active_root_action_id;
  feedback_language_items:='[]'::jsonb; bundle_unread:=false; bundle_has_update:=false;
  FOR attachment IN SELECT a.*,candidate.feedback_family,candidate.generated_output FROM public.confident_moment_bundle_attachments a JOIN public.feedback_candidates candidate ON candidate.id=a.attached_candidate_id WHERE a.feedback_membership_id=membership.id AND a.bundle_subject_candidate_id=subject.bundle_subject_candidate_id AND a.acquisition_principal_id=p_acquisition_principal_id AND a.project_id=p_project_id AND a.take_id=p_take_id ORDER BY a.canonical_position,a.attached_candidate_id LOOP
   resolution:='machine_fallback'; exclusion:=NULL; delivery_id:=NULL;
   -- Every attachment-scoped leaf is cleared here.  A coach-updated
   -- attachment must not leak its revision, presentation, rendered
   -- exposure or unread state into the next machine-only attachment.
   coach_revision_id:=NULL; unread:=false; presentation_count:=NULL;
   rendered_count:=NULL; item_output:=NULL; item_coach_update:=NULL;
   revision_sha256:=NULL; delivery_subject_sha256:=NULL;
   current_presentation_id:=NULL; current_rendered_exposure_id:=NULL;
   owner_decision:=public.derive_confident_moment_owner_decision_v1(
    p_acquisition_principal_id,membership.id,attachment.id);
   output_hash:=public.feedback_candidate_output_sha256_v1(attachment.attached_candidate_id);
   SELECT jsonb_build_object('evidence_span_id',span.id,'text',span.exact_text,
    'text_sha256',public.exercise_text_sha256_v1(span.exact_text)) INTO STRICT source_passage_payload
   FROM public.evidence_spans span WHERE span.id=attachment.attached_evidence_span_id;
   SELECT attachment.feedback_family='rewrite_clarity'
      AND attachment.generated_output ? 'proposed_text'
      AND span.ideal_text_target_locator_v1 IS NOT NULL
      AND span.ideal_text_target_snapshot_id=membership.document_snapshot_id
    INTO update_text_available FROM public.evidence_spans span WHERE span.id=attachment.attached_evidence_span_id;
   SELECT count(*) INTO current_count FROM public.feedback_language_revision_deliveries d WHERE d.delivery_policy_version='feedback-language-delivery-v2' AND d.recipient_principal_id=p_acquisition_principal_id AND d.target_take_id=p_take_id AND d.feedback_membership_id=membership.id AND d.feedback_candidate_id=attachment.attached_candidate_id AND NOT EXISTS(SELECT 1 FROM public.feedback_language_revision_deliveries successor WHERE successor.supersedes_delivery_id=d.id AND successor.delivery_policy_version='feedback-language-delivery-v2');
   IF current_count>1 THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_INVALID'; END IF;
   SELECT d.id,d.revision_id,d.delivery_subject_sha256,d.anchor_candidate_id INTO delivery_id,coach_revision_id,delivery_subject_sha256,delivery_anchor_candidate_id FROM public.feedback_language_revision_deliveries d WHERE d.delivery_policy_version='feedback-language-delivery-v2' AND d.recipient_principal_id=p_acquisition_principal_id AND d.target_take_id=p_take_id AND d.feedback_membership_id=membership.id AND d.feedback_candidate_id=attachment.attached_candidate_id AND NOT EXISTS(SELECT 1 FROM public.feedback_language_revision_deliveries successor WHERE successor.supersedes_delivery_id=d.id AND successor.delivery_policy_version='feedback-language-delivery-v2');
   IF delivery_id IS NOT NULL THEN
   IF delivery_anchor_candidate_id IS DISTINCT FROM COALESCE(attachment.anchor_candidate_id,attachment.bundle_subject_candidate_id) THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_INVALID'; END IF;
   PERFORM public.require_feedback_language_coach_source_live_v1(
    coach_revision_id,p_acquisition_principal_id,membership.id,
    attachment.attached_candidate_id,
    public.feedback_candidate_output_sha256_v1(attachment.attached_candidate_id),
    'CONFIDENT_MOMENT_PROJECTION_INVALID');
   IF EXISTS(SELECT 1 FROM public.feedback_language_revision_deliveries d WHERE d.id=delivery_id AND d.delivery_state='invalidated') THEN resolution:='excluded'; exclusion:='delivery_explicitly_invalidated'; coach_revision_id:=NULL; unread:=false;
   ELSIF EXISTS(SELECT 1 FROM public.feedback_revisions successor WHERE successor.supersedes_id=coach_revision_id AND successor.taxonomy_version='feedback-language-coach-revision-v1') THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_INVALID';
    ELSE
     SELECT count(*),(array_agg(p.id ORDER BY p.prepared_at,p.id))[1] INTO presentation_count,current_presentation_id
      FROM public.ml_presentations p JOIN public.feedback_revisions r ON r.id=coach_revision_id
      WHERE p.artifact_id=coach_revision_id AND p.actor_principal_id=p_acquisition_principal_id
       AND p.learning_surface_id=(CASE r.output_kind WHEN 'rephrase' THEN 'correction_generation' WHEN 'comment' THEN CASE r.comment_purpose WHEN 'positive_praise' THEN 'praise_generation' ELSE 'coach_comment_generation' END END)
       AND p.delivery_mode<>'shadow';
     IF presentation_count<>1 THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_INVALID'; END IF;
     SELECT count(*),(array_agg(e.id ORDER BY e.authenticated_at,e.id))[1]
      INTO rendered_count,current_rendered_exposure_id FROM public.ml_rendered_exposures e
      WHERE e.presentation_id=current_presentation_id AND e.actor_principal_id=p_acquisition_principal_id
     ;
     IF rendered_count>1 THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_INVALID'; END IF;
     unread:=current_rendered_exposure_id IS NULL;
     resolution:='coach_revision';
     SELECT jsonb_build_object('output_kind',r.output_kind,'comment_purpose',r.comment_purpose,'text',r.value,'origin','coach'),r.revision_sha256
      INTO item_output,revision_sha256 FROM public.feedback_revisions r
      WHERE r.id=coach_revision_id AND r.feedback_membership_id=membership.id
       AND r.feedback_candidate_id=attachment.attached_candidate_id;
     output_hash:=revision_sha256;
     item_coach_update:=jsonb_build_object(
      'current_revision_id',coach_revision_id,'revision_sha256',revision_sha256,
      'revision_delivery_id',delivery_id,'delivery_subject_sha256',delivery_subject_sha256,
      'presentation_id',current_presentation_id,
      'rendered_exposure_id',current_rendered_exposure_id,'unread',unread);
    END IF;
   ELSIF attachment.feedback_family='rewrite_clarity' THEN
    IF NULLIF(btrim(attachment.generated_output->>'proposed_text'),'') IS NOT NULL THEN
     item_output:=jsonb_build_object('output_kind','rephrase','comment_purpose',NULL,'text',attachment.generated_output->>'proposed_text','origin','machine');
    ELSIF NULLIF(btrim(attachment.generated_output->>'observation'),'') IS NOT NULL THEN
     item_output:=jsonb_build_object('output_kind','comment','comment_purpose','actionable_observation','text',attachment.generated_output->>'observation','origin','machine');
    ELSE resolution:='excluded'; exclusion:='machine_output_invalid'; END IF;
   ELSIF attachment.feedback_family='great_formulation' THEN
    IF NULLIF(btrim(COALESCE(attachment.generated_output->>'comment',attachment.generated_output->>'quote')),'') IS NULL THEN resolution:='excluded'; exclusion:='machine_output_invalid'; ELSE item_output:=jsonb_build_object('output_kind','comment','comment_purpose','positive_praise','text',COALESCE(attachment.generated_output->>'comment',attachment.generated_output->>'quote'),'origin','machine'); END IF;
   ELSIF attachment.feedback_family='confident_voice' THEN
    IF NULLIF(btrim(COALESCE(attachment.generated_output->>'comment',attachment.generated_output->>'quote')),'') IS NULL THEN resolution:='excluded'; exclusion:='machine_output_invalid'; ELSE item_output:=jsonb_build_object('output_kind','comment','comment_purpose','confidence_explanation','text',COALESCE(attachment.generated_output->>'comment',attachment.generated_output->>'quote'),'origin','machine'); END IF;
   END IF;
   item_hash:=public.exercise_json_sha256_v1(jsonb_build_object('attachment',attachment.id,'family',attachment.feedback_family,'feedback_exposure',attachment.canonical_feedback_presentation_id,'resolution',resolution,'exclusion',exclusion,'revision',coach_revision_id,'delivery',delivery_id,'presentation',current_presentation_id,'rendered_exposure',current_rendered_exposure_id,'unread',unread,'owner_decision',owner_decision,'output_hash',output_hash,'position',attachment.canonical_position,'exercise',false));
   INSERT INTO public.confident_moment_bundle_projection_items(projection_id,acquisition_principal_id,bundle_attachment_id,bundle_subject_candidate_id,attached_candidate_id,feedback_family,canonical_feedback_exposure_id,anchor_candidate_id,resolution_state,exclusion_reason,revision_id,delivery_id,presentation_id,rendered_exposure_id,unread,candidate_output_sha256,output_sha256,canonical_position,exercise_present,item_sha256,source_passage,update_text_available,coach_authoring_exclusion_reason,owner_decision)
   VALUES(projection.id,p_acquisition_principal_id,attachment.id,attachment.bundle_subject_candidate_id,attachment.attached_candidate_id,attachment.feedback_family,attachment.canonical_feedback_presentation_id,attachment.anchor_candidate_id,resolution,exclusion,coach_revision_id,delivery_id,current_presentation_id,current_rendered_exposure_id,unread,public.feedback_candidate_output_sha256_v1(attachment.attached_candidate_id),output_hash,attachment.canonical_position,false,item_hash,source_passage_payload,update_text_available,
    (SELECT CASE WHEN authorability_status='source_audio_unavailable' THEN 'source_audio_unavailable' END
     FROM public.confident_moment_coach_authorability_items ai
     JOIN public.confident_moment_coach_authorability_inventories ah ON ah.id=ai.inventory_id
     WHERE ai.bundle_attachment_id=attachment.id AND ah.feedback_membership_id=membership.id
     ORDER BY ah.inventory_revision DESC LIMIT 1),owner_decision)
   ON CONFLICT(projection_id,bundle_attachment_id) DO NOTHING;
   feedback_language_items:=feedback_language_items||jsonb_build_array(jsonb_build_object(
    'bundle_attachment_id',attachment.id,'attached_candidate_id',attachment.attached_candidate_id,
    'feedback_family',attachment.feedback_family,
    'canonical_feedback_exposure_id',attachment.canonical_feedback_presentation_id,
    'source_passage',source_passage_payload,'update_text_available',update_text_available,
    'coach_authoring_exclusion_reason',(SELECT CASE WHEN authorability_status='source_audio_unavailable' THEN 'source_audio_unavailable' END
      FROM public.confident_moment_coach_authorability_items ai JOIN public.confident_moment_coach_authorability_inventories ah ON ah.id=ai.inventory_id
      WHERE ai.bundle_attachment_id=attachment.id AND ah.feedback_membership_id=membership.id ORDER BY ah.inventory_revision DESC LIMIT 1),
    'canonical_position',attachment.canonical_position,'resolution_state',resolution,'owner_decision',owner_decision,
    'exclusion_reason',exclusion,'output',CASE WHEN resolution='excluded' THEN NULL ELSE item_output END,
    'coach_update',CASE WHEN resolution='coach_revision' THEN item_coach_update ELSE NULL END));
   IF resolution='coach_revision' THEN
   bundle_unread:=bundle_unread OR unread;
   bundle_has_update:=bundle_has_update OR resolution='coach_revision';
   END IF;
  END LOOP;
  bundle:=jsonb_build_object('bundle_id',subject.bundle_subject_candidate_id,'bundle_subject_kind',subject.bundle_subject_kind,'slide_index',subject.slide_index,'block_key',subject.block_key,'paragraph_id',subject.paragraph_id,'subject',jsonb_build_object('candidate_id',subject.bundle_subject_candidate_id,'evidence_span_id',subject.bundle_subject_evidence_span_id,'canonical_feedback_presentation_id',subject.canonical_feedback_presentation_id),'confidence_anchor',CASE WHEN subject.bundle_subject_kind='confidence_anchor' THEN jsonb_build_object('candidate_id',subject.bundle_subject_candidate_id,'evidence_span_id',subject.bundle_subject_evidence_span_id,'playback_reference_id',subject.canonical_feedback_presentation_id) ELSE NULL END,'feedback_language_items',feedback_language_items,'exercise',NULL,'root',jsonb_build_object('is_orange',root_head.active_root_action_id IS NOT NULL,'is_locked',COALESCE(root_action.persistence_state='owner_locked',false),'can_restore_previous',COALESCE(root_action.restore_product_action_id IS NOT NULL OR root_action.supersedes_action_id IS NOT NULL,false),'active_root_action_id',root_head.active_root_action_id,'interaction_state_revision',GREATEST(COALESCE(root_head.interaction_state_revision,0),1)::text,'restore_product_action_id',COALESCE(root_action.restore_product_action_id,root_action.supersedes_action_id)),'state_revision',GREATEST(COALESCE(root_head.interaction_state_revision,0),1));
  bundles:=bundles||jsonb_build_array(bundle);
  summary_items:=summary_items||jsonb_build_array(jsonb_build_object('bundle_id',subject.bundle_subject_candidate_id,'paragraph_id',subject.paragraph_id,'slide_index',subject.slide_index,'block_key',subject.block_key,'marker_present',true,'is_orange',root_head.active_root_action_id IS NOT NULL,'is_locked',COALESCE(root_action.persistence_state='owner_locked',false),'has_coach_update',bundle_has_update,'has_unread_coach_update',bundle_unread,'state_revision',GREATEST(COALESCE(root_head.interaction_state_revision,0),1)));
 END LOOP;
 SELECT COALESCE((SELECT jsonb_build_object('target_slide_count',f.target_slide_count,'achieved_slide_count',f.achieved_slide_count,'target_met',f.target_met) FROM public.root_phrase_coverage_frames f WHERE f.acquisition_principal_id=p_acquisition_principal_id AND f.take_id=p_take_id AND f.feedback_membership_id=membership.id AND f.document_snapshot_id=snapshot.id ORDER BY f.frozen_at DESC LIMIT 1),jsonb_build_object('target_slide_count',0,'achieved_slide_count',0,'target_met',false)) INTO coverage;
 body:=jsonb_build_object('contract_version','confident-moment-coaching-bundle-v2','feedback_language_shape_version','feedback-language-items-v2','project_id',p_project_id,'take_id',p_take_id,'document_snapshot_id',snapshot.id,'feedback_membership_id',membership.id,'bundles',bundles,'coverage',coverage);
 response_hash:=public.exercise_json_sha256_v1(body); body:=body||jsonb_build_object('response_sha256',response_hash);
 summary:=jsonb_build_object('contract_version','confident-moment-core-summary-v1','document_snapshot_id',snapshot.id,'items',summary_items); summary_hash:=public.exercise_json_sha256_v1(summary); summary:=summary||jsonb_build_object('summary_sha256',summary_hash);
 projection_key:='confident-moment-projection:'||p_acquisition_principal_id::text||':'||p_project_id::text||':'||p_take_id::text||':'||inventory_after;
 -- Authority is refreshed before persistence; the held D4 serializers prevent
 -- an authority writer from crossing the remaining insert/return boundary.
 PERFORM public.require_mlc3_service_access_v2(p_acquisition_principal_id,NULL,NULL);
 INSERT INTO public.confident_moment_bundle_projections(id,acquisition_principal_id,project_id,take_id,feedback_membership_id,document_snapshot_id,document_snapshot_sha256,projection_policy_version,projection_code_version,stabilized_inventory_sha256,response_sha256,idempotency_key)
 VALUES(projection.id,p_acquisition_principal_id,p_project_id,p_take_id,membership.id,snapshot.id,snapshot.payload_sha256,'confident-moment-secure-projection-v1','confident-moment-projection-sql-v1',inventory_after,response_hash,projection_key)
 ON CONFLICT(acquisition_principal_id,project_id,take_id,stabilized_inventory_sha256) DO NOTHING;
 SELECT * INTO STRICT projection FROM public.confident_moment_bundle_projections p
  WHERE p.acquisition_principal_id=p_acquisition_principal_id AND p.project_id=p_project_id
    AND p.take_id=p_take_id AND p.stabilized_inventory_sha256=inventory_after;
 IF projection.response_sha256<>response_hash THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_INVALID'; END IF;
 RETURN jsonb_build_object('bundle_projection',body,'confident_moment_summary',summary);
END $$;

-- The canonical definitions of confident_moment_bundle_projections and
-- confident_moment_bundle_projection_items live once, above.  A second,
-- divergent CREATE TABLE IF NOT EXISTS pair used to sit here; it was dead on
-- any clean apply and lacked presentation_id/rendered_exposure_id/unread and
-- the shape constraints, so it could only mislead a later edit.

ALTER TABLE public.root_phrase_product_actions ADD COLUMN IF NOT EXISTS take_id uuid REFERENCES public.v2_sessions(id) ON DELETE RESTRICT, ADD COLUMN IF NOT EXISTS interaction_action text, ADD COLUMN IF NOT EXISTS activation_origin text, ADD COLUMN IF NOT EXISTS persistence_state text, ADD COLUMN IF NOT EXISTS qualification_state text, ADD COLUMN IF NOT EXISTS source_candidate_id uuid REFERENCES public.feedback_candidates(id) ON DELETE RESTRICT, ADD COLUMN IF NOT EXISTS source_evidence_span_id uuid REFERENCES public.evidence_spans(id) ON DELETE RESTRICT, ADD COLUMN IF NOT EXISTS source_feedback_exposure_id uuid REFERENCES public.feedback_exposures(id) ON DELETE RESTRICT, ADD COLUMN IF NOT EXISTS source_owner_response_id uuid REFERENCES public.feedback_v3_owner_responses(id) ON DELETE RESTRICT, ADD COLUMN IF NOT EXISTS source_practice_attempt_id uuid REFERENCES public.exercise_practice_attempts(id) ON DELETE RESTRICT, ADD COLUMN IF NOT EXISTS source_ideal_text_revision_id bigint REFERENCES public.ideal_text_part_revision(id) ON DELETE RESTRICT, ADD COLUMN IF NOT EXISTS source_target_speaker_binding_id uuid REFERENCES public.mlc3_target_speaker_bindings(id) ON DELETE RESTRICT, ADD COLUMN IF NOT EXISTS practice_target_speaker_binding_id uuid REFERENCES public.mlc3_target_speaker_bindings(id) ON DELETE RESTRICT, ADD COLUMN IF NOT EXISTS practice_guard_sha256 text, ADD COLUMN IF NOT EXISTS restore_product_action_id uuid REFERENCES public.root_phrase_product_actions(id) ON DELETE RESTRICT, ADD COLUMN IF NOT EXISTS policy_version text;
DO $$ BEGIN
 ALTER TABLE public.root_phrase_product_actions DROP CONSTRAINT IF EXISTS root_phrase_product_action_v2_axes_check;
 ALTER TABLE public.root_phrase_product_actions ADD CONSTRAINT root_phrase_product_action_v2_axes_check CHECK(policy_version IS NULL OR (policy_version='rooting-coverage-30-80-100-v1' AND take_id IS NOT NULL AND interaction_action IN('activate_automatic_root','save_owner_selected_root','lock_current_root','restore_previous_root','unlock_current_root','remove_current_root') AND activation_origin IN('automatic_product_selection','owner_selection') AND persistence_state IN('automatic_replaceable','owner_locked') AND qualification_state IN('not_qualified_reference','qualified_confident_reference'))) NOT VALID;
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='public.root_phrase_product_actions'::regclass AND conname='root_phrase_product_action_v2_candidate_evidence_fk') THEN ALTER TABLE public.root_phrase_product_actions ADD CONSTRAINT root_phrase_product_action_v2_candidate_evidence_fk FOREIGN KEY(source_candidate_id,source_evidence_span_id) REFERENCES public.feedback_candidates(id,evidence_span_id) ON DELETE RESTRICT NOT VALID; END IF;
 ALTER TABLE public.root_phrase_product_actions DROP CONSTRAINT IF EXISTS root_phrase_product_action_v2_source_matrix_check;
 ALTER TABLE public.root_phrase_product_actions ADD CONSTRAINT root_phrase_product_action_v2_source_matrix_check CHECK(policy_version IS NULL OR
  (interaction_action='activate_automatic_root' AND source_candidate_id IS NOT NULL AND source_evidence_span_id IS NOT NULL AND source_feedback_exposure_id IS NOT NULL AND source_owner_response_id IS NOT NULL AND source_practice_attempt_id IS NULL AND source_target_speaker_binding_id IS NULL AND practice_target_speaker_binding_id IS NULL AND practice_guard_sha256 IS NULL AND restore_product_action_id IS NULL) OR
  (interaction_action='save_owner_selected_root' AND source_candidate_id IS NOT NULL AND source_evidence_span_id IS NOT NULL AND ((source_practice_attempt_id IS NULL AND source_target_speaker_binding_id IS NULL AND practice_target_speaker_binding_id IS NULL AND practice_guard_sha256 IS NULL) OR (source_practice_attempt_id IS NOT NULL AND source_target_speaker_binding_id IS NOT NULL AND practice_target_speaker_binding_id IS NOT NULL AND practice_guard_sha256 ~ '^[0-9a-f]{64}$')) AND ((source_feedback_exposure_id IS NULL AND source_owner_response_id IS NULL) OR (source_feedback_exposure_id IS NOT NULL AND source_owner_response_id IS NOT NULL)) AND restore_product_action_id IS NULL) OR
  (interaction_action IN('lock_current_root','unlock_current_root','remove_current_root') AND source_candidate_id IS NULL AND source_evidence_span_id IS NULL AND source_feedback_exposure_id IS NULL AND source_owner_response_id IS NULL AND source_practice_attempt_id IS NULL AND source_ideal_text_revision_id IS NULL AND source_target_speaker_binding_id IS NULL AND practice_target_speaker_binding_id IS NULL AND practice_guard_sha256 IS NULL AND restore_product_action_id IS NULL) OR
  (interaction_action='restore_previous_root' AND source_candidate_id IS NULL AND source_evidence_span_id IS NULL AND source_feedback_exposure_id IS NULL AND source_owner_response_id IS NULL AND source_practice_attempt_id IS NULL AND source_ideal_text_revision_id IS NULL AND source_target_speaker_binding_id IS NULL AND practice_target_speaker_binding_id IS NULL AND practice_guard_sha256 IS NULL AND restore_product_action_id IS NOT NULL)) NOT VALID;
END $$;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='public.root_phrase_product_actions'::regclass AND conname='root_phrase_product_actions_check1' AND contype='c') THEN
  ALTER TABLE public.root_phrase_product_actions DROP CONSTRAINT root_phrase_product_actions_check1;
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='public.root_phrase_product_actions'::regclass AND conname='root_phrase_product_actions_qualification_source_check') THEN
  ALTER TABLE public.root_phrase_product_actions ADD CONSTRAINT root_phrase_product_actions_qualification_source_check CHECK(((action IN('root_activate','root_replace')) AND ((policy_version IS NULL AND qualification_revision_id IS NOT NULL) OR (policy_version='rooting-coverage-30-80-100-v1' AND qualification_revision_id IS NULL))) OR (action IN('paragraph_lock','root_remove') AND qualification_revision_id IS NULL)) NOT VALID;
 END IF;
END $$;

CREATE OR REPLACE FUNCTION public.reject_confident_moment_mutation_v1() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$ BEGIN RAISE EXCEPTION 'CONFIDENT_MOMENT_APPEND_ONLY'; END $$;

CREATE OR REPLACE FUNCTION public.lock_confident_moment_inventory_v1(
 p_acquisition_principal_id uuid,p_project_id uuid,p_take_id uuid
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-rollout-policy-v2',0));
 PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-service-principal:'||p_acquisition_principal_id::text,0));
 PERFORM pg_advisory_xact_lock(hashtextextended('confident-moment-project-inventory:'||p_project_id::text,0));
 PERFORM pg_advisory_xact_lock(hashtextextended('confident-moment-take-inventory:'||p_take_id::text,0));
 PERFORM pg_advisory_xact_lock(hashtextextended('feedback-v3-membership-inventory:'||p_project_id::text||':'||p_take_id::text,0));
END $$;

-- D11 closes every pre-existing writer that can change the stabilized read
-- inventory.  Rewriting the installed definition preserves each historical
-- signature and result contract while placing the shared serializers at the
-- first executable boundary.  A missing/drifted overload aborts the migration.
DO $confident_moment_writer_closure$
DECLARE
 spec jsonb;
 target regprocedure;
 definition text;
 injection text;
BEGIN
 FOR spec IN SELECT value FROM jsonb_array_elements($registry$
 [
  {"signature":"public.freeze_synthetic_feedback_v3_membership_v1(uuid,uuid,uuid,uuid,uuid,text,jsonb,text,text)","marker":"D11 writer: synthetic membership","sql":" PERFORM public.lock_confident_moment_inventory_v1(p_acquisition_principal_id,p_project_id,p_take_id);\n"},
  {"signature":"public.freeze_feedback_v3_service_membership_v1(uuid,uuid,uuid,uuid,uuid,text,jsonb,text)","marker":"D11 writer: service membership","sql":" PERFORM public.lock_confident_moment_inventory_v1(p_acquisition_principal_id,p_project_id,p_take_id);\n"},
  {"signature":"public.publish_ideal_text_document_snapshot_v1(text,text,uuid,uuid,uuid,integer,bigint,text,jsonb,jsonb)","marker":"D11 writer: document snapshot","sql":" PERFORM public.lock_confident_moment_inventory_v1(p_acquisition_principal_id,p_project_id,p_source_take_session_id);\n PERFORM pg_advisory_xact_lock(hashtextextended('ideal-text-document-head:'||p_project_id::text,0));\n"},
  {"signature":"public.ack_feedback_v3_service_render_v1(uuid,uuid,uuid,uuid,uuid,uuid,text,timestamptz,text,text)","marker":"D11 writer: canonical render","sql":" PERFORM public.lock_confident_moment_inventory_v1(p_acquisition_principal_id,(SELECT project_id FROM public.feedback_v3_memberships WHERE id=p_membership_id),(SELECT take_id FROM public.feedback_v3_memberships WHERE id=p_membership_id));\n PERFORM pg_advisory_xact_lock(hashtextextended('feedback-v3-membership-current:'||p_membership_id::text,0));\n"},
  {"signature":"public.ensure_mlc3_service_enrollment_v2(uuid,uuid,text)","marker":"D11 writer: enrollment","sql":" PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-rollout-policy-v2',0));\n PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-service-principal:'||p_acquisition_principal_id::text,0));\n"},
  {"signature":"public.accept_phase1_processing_authorization_v1(uuid,text,text,text,text,text,text,boolean,text,text,text,timestamptz,text)","marker":"D11 writer: authorization receipt","sql":" PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-rollout-policy-v2',0));\n PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-service-principal:'||p_acquisition_principal_id::text,0));\n"}
 ]$registry$::jsonb) LOOP
  target:=to_regprocedure(spec->>'signature');
  IF target IS NULL THEN
   RAISE EXCEPTION 'CONFIDENT_MOMENT_WRITER_REGISTRY_DRIFT: %',spec->>'signature';
  END IF;
  definition:=pg_get_functiondef(target);
  IF position(spec->>'marker' IN definition)=0 THEN
   IF position(E'\nBEGIN\n' IN definition)=0 THEN
    RAISE EXCEPTION 'CONFIDENT_MOMENT_WRITER_BODY_DRIFT: %',spec->>'signature';
   END IF;
   injection:=' -- '||(spec->>'marker')||E'\n'||(spec->>'sql');
   definition:=regexp_replace(definition,E'\nBEGIN\n',E'\nBEGIN\n'||injection);
   EXECUTE definition;
  END IF;
 END LOOP;
END
$confident_moment_writer_closure$;

DO $confident_moment_authority_leaf_closure$
DECLARE
 spec jsonb;
 target regprocedure;
 definition text;
 injection text;
BEGIN
 FOR spec IN SELECT value FROM jsonb_array_elements($registry$
 [
  {"signature":"public.register_mlc3_general_rollout_v2(uuid,uuid,jsonb,jsonb,uuid,timestamptz,text)","marker":"D11 writer: rollout revision","sql":" PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-rollout-policy-v2',0));\n"},
  {"signature":"public.halt_mlc3_service_rollout_v1(text,text)","marker":"D11 writer: rollout halt","sql":" PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-rollout-policy-v2',0));\n"},
  {"signature":"public.activate_phase1_policy_v1(text,text,text)","marker":"D11 writer: policy activation","sql":" PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-rollout-policy-v2',0));\n PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-service-principal:'||principal.id::text,0)) FROM public.owner_principals principal ORDER BY principal.id;\n"},
  {"signature":"public.mark_phase1_storage_object_purged_v1(uuid,text,uuid,text,text,text,text)","marker":"D11 writer: object purge","sql":" PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-rollout-policy-v2',0));\n PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-service-principal:'||request.acquisition_principal_id::text,0)) FROM public.data_purge_requests request WHERE request.id=p_purge_request_id;\n PERFORM pg_advisory_xact_lock(hashtextextended('confident-moment-project-inventory:'||project_row.id::text,0)) FROM public.projects project_row JOIN public.data_purge_requests request ON request.acquisition_principal_id=project_row.owner_principal_id WHERE request.id=p_purge_request_id ORDER BY project_row.id;\n PERFORM pg_advisory_xact_lock(hashtextextended('confident-moment-take-inventory:'||take_row.id::text,0)) FROM public.v2_sessions take_row JOIN public.data_purge_requests request ON request.acquisition_principal_id=take_row.owner_principal_id WHERE request.id=p_purge_request_id ORDER BY take_row.id;\n PERFORM pg_advisory_xact_lock(hashtextextended('feedback-v3-membership-inventory:'||membership.project_id::text||':'||membership.take_id::text,0)) FROM public.feedback_v3_memberships membership JOIN public.data_purge_requests request ON request.acquisition_principal_id=membership.acquisition_principal_id WHERE request.id=p_purge_request_id ORDER BY membership.project_id,membership.take_id;\n PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-speaker-attempt:'||object_row.recording_attempt_id::text,0)) FROM public.processing_audio_objects object_row JOIN public.data_purge_requests request ON request.acquisition_principal_id=object_row.acquisition_principal_id WHERE request.id=p_purge_request_id ORDER BY object_row.recording_attempt_id;\n PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-processing-audio-object:'||object_row.id::text,0)) FROM public.processing_audio_objects object_row JOIN public.data_purge_requests request ON request.acquisition_principal_id=object_row.acquisition_principal_id WHERE request.id=p_purge_request_id ORDER BY object_row.id;\n"},
  {"signature":"public.finalize_phase1_purge_v3(uuid,text)","marker":"D11 writer: purge finalize","sql":" PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-rollout-policy-v2',0));\n PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-service-principal:'||request.acquisition_principal_id::text,0)) FROM public.data_purge_requests request WHERE request.id=p_purge_request_id;\n PERFORM pg_advisory_xact_lock(hashtextextended('confident-moment-project-inventory:'||project_row.id::text,0)) FROM public.projects project_row JOIN public.data_purge_requests request ON request.acquisition_principal_id=project_row.owner_principal_id WHERE request.id=p_purge_request_id ORDER BY project_row.id;\n PERFORM pg_advisory_xact_lock(hashtextextended('confident-moment-take-inventory:'||take_row.id::text,0)) FROM public.v2_sessions take_row JOIN public.data_purge_requests request ON request.acquisition_principal_id=take_row.owner_principal_id WHERE request.id=p_purge_request_id ORDER BY take_row.id;\n PERFORM pg_advisory_xact_lock(hashtextextended('feedback-v3-membership-inventory:'||membership.project_id::text||':'||membership.take_id::text,0)) FROM public.feedback_v3_memberships membership JOIN public.data_purge_requests request ON request.acquisition_principal_id=membership.acquisition_principal_id WHERE request.id=p_purge_request_id ORDER BY membership.project_id,membership.take_id;\n PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-speaker-attempt:'||object_row.recording_attempt_id::text,0)) FROM public.processing_audio_objects object_row JOIN public.data_purge_requests request ON request.acquisition_principal_id=object_row.acquisition_principal_id WHERE request.id=p_purge_request_id ORDER BY object_row.recording_attempt_id;\n PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-processing-audio-object:'||object_row.id::text,0)) FROM public.processing_audio_objects object_row JOIN public.data_purge_requests request ON request.acquisition_principal_id=object_row.acquisition_principal_id WHERE request.id=p_purge_request_id ORDER BY object_row.id;\n"}
 ]$registry$::jsonb) LOOP
  target:=to_regprocedure(spec->>'signature');
  IF target IS NULL THEN
   RAISE EXCEPTION 'CONFIDENT_MOMENT_WRITER_REGISTRY_DRIFT: %',spec->>'signature';
  END IF;
  definition:=pg_get_functiondef(target);
  IF position(spec->>'marker' IN definition)=0 THEN
   IF position(E'\nBEGIN\n' IN definition)=0 THEN
    RAISE EXCEPTION 'CONFIDENT_MOMENT_WRITER_BODY_DRIFT: %',spec->>'signature';
   END IF;
   injection:=' -- '||(spec->>'marker')||E'\n'||(spec->>'sql');
   definition:=regexp_replace(definition,E'\nBEGIN\n',E'\nBEGIN\n'||injection);
   EXECUTE definition;
  END IF;
 END LOOP;
END
$confident_moment_authority_leaf_closure$;

DO $confident_moment_trigger_closure$
DECLARE
 spec jsonb;
 target regprocedure;
 definition text;
 injection text;
BEGIN
 FOR spec IN SELECT value FROM jsonb_array_elements($registry$
 [
  {"signature":"public.advance_ideal_text_document_generation_v1()","marker":"D11 trigger writer: document generation","sql":" PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-rollout-policy-v2',0));\n PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-service-principal:'||project_row.owner_principal_id::text,0)) FROM public.projects project_row WHERE project_row.id::text=COALESCE(to_jsonb(NEW)->>'project_id',to_jsonb(NEW)->>'arc_id') ORDER BY project_row.owner_principal_id;\n PERFORM pg_advisory_xact_lock(hashtextextended('confident-moment-project-inventory:'||project_row.id::text,0)) FROM public.projects project_row WHERE project_row.id::text=COALESCE(to_jsonb(NEW)->>'project_id',to_jsonb(NEW)->>'arc_id') ORDER BY project_row.id;\n PERFORM pg_advisory_xact_lock(hashtextextended('confident-moment-take-inventory:'||take_row.id::text,0)) FROM public.v2_sessions take_row WHERE take_row.project_id::text=COALESCE(to_jsonb(NEW)->>'project_id',to_jsonb(NEW)->>'arc_id') ORDER BY take_row.id;\n PERFORM pg_advisory_xact_lock(hashtextextended('feedback-v3-membership-inventory:'||membership.project_id::text||':'||membership.take_id::text,0)) FROM public.feedback_v3_memberships membership WHERE membership.project_id::text=COALESCE(to_jsonb(NEW)->>'project_id',to_jsonb(NEW)->>'arc_id') ORDER BY membership.project_id,membership.take_id;\n"},
  {"signature":"public.serialize_mlc3_service_purge_v1()","marker":"D11 trigger writer: purge request","sql":" PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-rollout-policy-v2',0));\n PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-service-principal:'||(to_jsonb(NEW)->>'acquisition_principal_id'),0));\n PERFORM pg_advisory_xact_lock(hashtextextended('confident-moment-project-inventory:'||project_row.id::text,0)) FROM public.projects project_row WHERE project_row.owner_principal_id=(to_jsonb(NEW)->>'acquisition_principal_id')::uuid ORDER BY project_row.id;\n PERFORM pg_advisory_xact_lock(hashtextextended('confident-moment-take-inventory:'||take_row.id::text,0)) FROM public.v2_sessions take_row WHERE take_row.owner_principal_id=(to_jsonb(NEW)->>'acquisition_principal_id')::uuid ORDER BY take_row.id;\n PERFORM pg_advisory_xact_lock(hashtextextended('feedback-v3-membership-inventory:'||membership.project_id::text||':'||membership.take_id::text,0)) FROM public.feedback_v3_memberships membership WHERE membership.acquisition_principal_id=(to_jsonb(NEW)->>'acquisition_principal_id')::uuid ORDER BY membership.project_id,membership.take_id;\n"},
  {"signature":"public.serialize_mlc3_processing_audio_leaf_v1()","marker":"D11 trigger writer: audio leaf","sql":" PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-rollout-policy-v2',0));\n PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-service-principal:'||(to_jsonb(NEW)->>'acquisition_principal_id'),0));\n PERFORM pg_advisory_xact_lock(hashtextextended('confident-moment-project-inventory:'||project_row.id::text,0)) FROM public.projects project_row WHERE project_row.owner_principal_id=(to_jsonb(NEW)->>'acquisition_principal_id')::uuid ORDER BY project_row.id;\n PERFORM pg_advisory_xact_lock(hashtextextended('confident-moment-take-inventory:'||take_row.id::text,0)) FROM public.v2_sessions take_row WHERE take_row.owner_principal_id=(to_jsonb(NEW)->>'acquisition_principal_id')::uuid ORDER BY take_row.id;\n PERFORM pg_advisory_xact_lock(hashtextextended('feedback-v3-membership-inventory:'||membership.project_id::text||':'||membership.take_id::text,0)) FROM public.feedback_v3_memberships membership WHERE membership.acquisition_principal_id=(to_jsonb(NEW)->>'acquisition_principal_id')::uuid ORDER BY membership.project_id,membership.take_id;\n PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-speaker-attempt:'||object_row.recording_attempt_id::text,0)) FROM public.processing_audio_objects object_row WHERE object_row.id=COALESCE((to_jsonb(NEW)->>'audio_object_id')::uuid,(to_jsonb(NEW)->>'id')::uuid) ORDER BY object_row.recording_attempt_id;\n PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-processing-audio-object:'||object_row.id::text,0)) FROM public.processing_audio_objects object_row WHERE object_row.id=COALESCE((to_jsonb(NEW)->>'audio_object_id')::uuid,(to_jsonb(NEW)->>'id')::uuid) ORDER BY object_row.id;\n"}
 ]$registry$::jsonb) LOOP
  target:=to_regprocedure(spec->>'signature');
  IF target IS NULL THEN
   RAISE EXCEPTION 'CONFIDENT_MOMENT_TRIGGER_REGISTRY_DRIFT: %',spec->>'signature';
  END IF;
  definition:=pg_get_functiondef(target);
  IF position(spec->>'marker' IN definition)=0 THEN
   IF position(E'\nBEGIN\n' IN definition)=0 THEN
    RAISE EXCEPTION 'CONFIDENT_MOMENT_TRIGGER_BODY_DRIFT: %',spec->>'signature';
   END IF;
   injection:=' -- '||(spec->>'marker')||E'\n'||(spec->>'sql');
   definition:=regexp_replace(definition,E'\nBEGIN\n',E'\nBEGIN\n'||injection);
   EXECUTE definition;
  END IF;
 END LOOP;
END
$confident_moment_trigger_closure$;

-- RPCs are exact disabled-gate boundaries. They reuse existing live guards and ledgers.
CREATE OR REPLACE FUNCTION public.prepare_confident_moment_bundle_v1(p_acquisition_principal_id uuid,p_project_id uuid,p_take_id uuid,p_feedback_membership_id uuid,p_bundle_subject_candidate_id uuid,p_idempotency_key text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE
 m public.feedback_v3_memberships;
 subject public.feedback_v3_membership_items;
 item record;
 e public.feedback_exposures;
 a public.confident_moment_bundle_attachments;
 kind text;
 policy text;
 digest text;
 presentation_digest text;
 result jsonb:='[]'::jsonb;
BEGIN
 IF COALESCE(btrim(p_idempotency_key),'')='' OR length(p_idempotency_key)>150 THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_EXACT_IDENTITY_REQUIRED'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('confident-moment-bundle:'||p_idempotency_key,0));
 PERFORM public.lock_confident_moment_inventory_v1(p_acquisition_principal_id,p_project_id,p_take_id);
 PERFORM pg_advisory_xact_lock(hashtextextended('confident-moment-bundle-subject:'||p_feedback_membership_id::text||':'||p_bundle_subject_candidate_id::text,0));
 PERFORM public.require_mlc3_service_access_v2(p_acquisition_principal_id,NULL,NULL);
 m:=public.require_feedback_v3_service_membership_live_v1(p_feedback_membership_id,p_acquisition_principal_id);
 IF m.project_id<>p_project_id OR m.take_id<>p_take_id THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_MEMBERSHIP_INVALID'; END IF;
 SELECT * INTO STRICT subject FROM public.feedback_v3_membership_items WHERE membership_id=m.id AND candidate_id=p_bundle_subject_candidate_id AND selected AND eligibility='eligible';
 IF subject.feedback_family='confident_voice' THEN kind:='confidence_anchor'; policy:='confident-moment-attachment-v1';
 ELSIF subject.feedback_family='rewrite_clarity' AND NOT EXISTS(SELECT 1 FROM public.feedback_v3_membership_items x WHERE x.membership_id=m.id AND x.selected AND x.eligibility='eligible' AND x.feedback_family='confident_voice' AND x.slide_index=subject.slide_index) THEN kind:='no_anchor_paragraph_trigger'; policy:='confident-moment-no-anchor-trigger-v1';
 ELSE RAISE EXCEPTION 'CONFIDENT_MOMENT_ANCHOR_INVALID'; END IF;
 FOR item IN
  WITH selected_items AS (
   SELECT candidate_item.*,evidence.start_char,
          COALESCE((SELECT ord::integer FROM public.ideal_text_document_snapshots snapshot_row CROSS JOIN LATERAL jsonb_array_elements(COALESCE(snapshot_row.payload->'pieces','[]'::jsonb)) WITH ORDINALITY piece(value,ord) WHERE snapshot_row.id=m.document_snapshot_id AND piece.value->>'part_id'=candidate_item.source_ideal_part_id::text LIMIT 1),2147483647) AS paragraph_position
     FROM public.feedback_v3_membership_items candidate_item
     JOIN public.evidence_spans evidence ON evidence.id=candidate_item.evidence_span_id
    WHERE candidate_item.membership_id=m.id AND candidate_item.selected AND candidate_item.eligibility='eligible' AND candidate_item.slide_index=subject.slide_index
  ), attached AS (
   SELECT candidate_item.*,
          CASE WHEN candidate_item.feedback_family='confident_voice' THEN candidate_item.candidate_id ELSE (SELECT anchor.candidate_id FROM selected_items anchor WHERE anchor.feedback_family='confident_voice' ORDER BY abs(anchor.paragraph_position-candidate_item.paragraph_position),abs(anchor.start_char-candidate_item.start_char),anchor.paragraph_position,anchor.start_char,anchor.candidate_id LIMIT 1) END AS nearest_anchor_candidate_id
     FROM selected_items candidate_item
  )
  SELECT candidate_item.*,anchor.evidence_span_id AS nearest_anchor_evidence_span_id
    FROM attached candidate_item
    LEFT JOIN selected_items anchor ON anchor.candidate_id=candidate_item.nearest_anchor_candidate_id
   WHERE (kind='no_anchor_paragraph_trigger' AND candidate_item.candidate_id=subject.candidate_id) OR (kind='confidence_anchor' AND candidate_item.nearest_anchor_candidate_id=subject.candidate_id)
   ORDER BY candidate_item.paragraph_position,candidate_item.start_char,candidate_item.position_shown,candidate_item.candidate_id
 LOOP
  SELECT * INTO STRICT e FROM public.feedback_exposures WHERE candidate_set_id=m.candidate_set_id AND candidate_id=item.candidate_id AND is_selected FOR UPDATE;
  presentation_digest:=public.exercise_json_sha256_v1(jsonb_build_object('membership',m.id,'candidate',item.candidate_id,'evidence',item.evidence_span_id,'presentation',e.id,'snapshot',m.document_snapshot_id));
  digest:=public.exercise_json_sha256_v1(jsonb_build_object('membership',m.id,'subject',subject.candidate_id,'subject_evidence',subject.evidence_span_id,'attached',item.candidate_id,'attached_evidence',item.evidence_span_id,'anchor',CASE WHEN kind='confidence_anchor' THEN subject.candidate_id END,'anchor_evidence',CASE WHEN kind='confidence_anchor' THEN subject.evidence_span_id END,'paragraph',item.source_ideal_part_id,'snapshot',m.document_snapshot_id,'presentation',e.id,'policy',policy,'position',item.position_shown));
  SELECT * INTO a FROM public.confident_moment_bundle_attachments WHERE feedback_membership_id=m.id AND attached_candidate_id=item.candidate_id;
  IF a.id IS NOT NULL THEN
   IF a.bundle_subject_kind<>kind OR a.bundle_subject_candidate_id<>subject.candidate_id OR a.attachment_input_sha256<>digest OR a.canonical_feedback_presentation_id<>e.id THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_REPLAY_CONFLICT'; END IF;
  ELSE
   IF e.shown_at IS NOT NULL THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_ATTACHMENT_INVALID'; END IF;
   INSERT INTO public.confident_moment_bundle_attachments(acquisition_principal_id,project_id,take_id,feedback_membership_id,bundle_subject_kind,bundle_subject_candidate_id,bundle_subject_evidence_span_id,attached_candidate_id,attached_evidence_span_id,anchor_candidate_id,anchor_evidence_span_id,paragraph_id,document_snapshot_id,canonical_feedback_presentation_id,canonical_position,attachment_policy_version,presentation_identity_sha256,attachment_input_sha256,idempotency_key)
   VALUES(p_acquisition_principal_id,p_project_id,p_take_id,m.id,kind,subject.candidate_id,subject.evidence_span_id,item.candidate_id,item.evidence_span_id,CASE WHEN kind='confidence_anchor' THEN subject.candidate_id END,CASE WHEN kind='confidence_anchor' THEN subject.evidence_span_id END,item.source_ideal_part_id,m.document_snapshot_id,e.id,item.position_shown,policy,presentation_digest,digest,p_idempotency_key||':'||item.candidate_id::text) RETURNING * INTO a;
  END IF;
  result:=result||jsonb_build_array(to_jsonb(a));
 END LOOP;
 IF jsonb_array_length(result)=0 THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_ANCHOR_INVALID'; END IF;
 PERFORM public.require_mlc3_service_access_v2(p_acquisition_principal_id,NULL,NULL);
 RETURN jsonb_build_object('bundle_id',subject.candidate_id,'bundle_subject_kind',kind,'attachments',result,'serves_user',false,'dataset_eligible',false);
END $$;

-- security closure deferred until all RPC declarations
-- function closure and commit deferred until all RPC declarations

CREATE OR REPLACE FUNCTION public.record_feedback_language_coach_revision_v1(p_reviewer_principal_id uuid,p_review_batch_id uuid,p_reveal_grant_id uuid,p_reveal_access_id uuid,p_review_assignment_id uuid,p_blind_judgment_id uuid,p_feedback_membership_id uuid,p_feedback_candidate_id uuid,p_candidate_output_sha256 text,p_output_kind text,p_comment_purpose text,p_revision_text text,p_supersedes_revision_id uuid,p_idempotency_key text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE a public.coach_guidance_reveal_accesses; i public.feedback_v3_membership_items; r public.feedback_revisions; digest text;
BEGIN
 IF COALESCE(btrim(p_idempotency_key),'')='' OR COALESCE(btrim(p_revision_text),'')='' OR p_candidate_output_sha256 !~ '^[0-9a-f]{64}$' OR p_output_kind NOT IN('comment','rephrase') OR (p_output_kind='rephrase' AND p_comment_purpose IS NOT NULL) OR (p_output_kind='comment' AND p_comment_purpose NOT IN('confidence_explanation','actionable_observation','positive_praise')) THEN RAISE EXCEPTION 'FEEDBACK_LANGUAGE_REVISION_INVALID'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('feedback-language:'||p_idempotency_key,0));
 PERFORM pg_advisory_xact_lock(hashtextextended('feedback-language-candidate:'||p_feedback_candidate_id::text||':'||p_reviewer_principal_id::text,0));
 SELECT * INTO STRICT a FROM public.coach_guidance_reveal_accesses WHERE id=p_reveal_access_id AND reveal_grant_id=p_reveal_grant_id AND reviewer_principal_id=p_reviewer_principal_id AND review_assignment_id=p_review_assignment_id AND blind_judgment_id=p_blind_judgment_id;
 PERFORM public.require_coach_guidance_reviewer_access_v1(p_reviewer_principal_id);
 PERFORM public.require_coach_guidance_assignment_live_v1(p_review_assignment_id,a.acquisition_principal_id,'coach_review');
 IF NOT EXISTS(SELECT 1 FROM public.coach_guidance_reveal_grants g WHERE g.id=p_reveal_grant_id AND g.review_batch_id=p_review_batch_id) OR NOT EXISTS(SELECT 1 FROM public.ml_judgments j WHERE j.id=p_blind_judgment_id AND j.review_assignment_id=p_review_assignment_id AND j.actor_principal_id=p_reviewer_principal_id AND j.actor_provenance='blind_coach') THEN RAISE EXCEPTION 'FEEDBACK_LANGUAGE_REVEAL_REQUIRED'; END IF;
 PERFORM public.require_mlc3_service_access_v2(a.acquisition_principal_id,NULL,NULL); SELECT * INTO STRICT i FROM public.feedback_v3_membership_items WHERE membership_id=p_feedback_membership_id AND candidate_id=p_feedback_candidate_id AND selected;
 IF NOT EXISTS(SELECT 1 FROM public.coach_inline_source_roles source_role JOIN public.exercise_blind_packets packet ON packet.id=source_role.blind_packet_id AND packet.review_assignment_id=source_role.review_assignment_id JOIN public.exercise_audio_lineages lineage ON lineage.id=source_role.audio_lineage_id AND lineage.id=packet.audio_lineage_id JOIN public.ml_review_assignments assignment_row ON assignment_row.id=source_role.review_assignment_id AND assignment_row.evidence_span_id=i.evidence_span_id AND assignment_row.learning_surface_id='confidence_classification' WHERE source_role.review_batch_id=p_review_batch_id AND source_role.review_assignment_id=p_review_assignment_id AND source_role.reviewer_principal_id=p_reviewer_principal_id AND source_role.acquisition_principal_id=a.acquisition_principal_id AND lineage.snippet_id=i.snippet_id) THEN RAISE EXCEPTION 'FEEDBACK_LANGUAGE_REVEAL_REQUIRED'; END IF;
 IF public.feedback_candidate_output_sha256_v1(p_feedback_candidate_id)<>p_candidate_output_sha256 OR (p_comment_purpose='positive_praise' AND i.feedback_family<>'great_formulation') OR (p_comment_purpose='actionable_observation' AND i.feedback_family<>'rewrite_clarity') OR (p_comment_purpose='confidence_explanation' AND i.feedback_family<>'confident_voice') OR (p_output_kind='rephrase' AND i.feedback_family<>'rewrite_clarity') THEN RAISE EXCEPTION 'FEEDBACK_LANGUAGE_REVISION_INVALID'; END IF;
 digest:=public.exercise_json_sha256_v1(jsonb_build_object('reviewer',p_reviewer_principal_id,'batch',p_review_batch_id,'grant',p_reveal_grant_id,'access',p_reveal_access_id,'assignment',p_review_assignment_id,'judgment',p_blind_judgment_id,'membership',p_feedback_membership_id,'candidate',p_feedback_candidate_id,'output_hash',p_candidate_output_sha256,'kind',p_output_kind,'purpose',p_comment_purpose,'text',p_revision_text,'supersedes',p_supersedes_revision_id));
 SELECT * INTO r FROM public.feedback_revisions WHERE idempotency_key=p_idempotency_key; IF r.id IS NOT NULL THEN IF r.revision_sha256<>digest THEN RAISE EXCEPTION 'FEEDBACK_LANGUAGE_REPLAY_CONFLICT'; END IF; PERFORM public.require_mlc3_service_access_v2(a.acquisition_principal_id,NULL,NULL); RETURN to_jsonb(r); END IF;
 IF p_supersedes_revision_id IS NOT NULL AND (NOT EXISTS(SELECT 1 FROM public.feedback_revisions old WHERE old.id=p_supersedes_revision_id AND old.feedback_membership_id=p_feedback_membership_id AND old.feedback_candidate_id=p_feedback_candidate_id AND old.rater_id=p_reviewer_principal_id AND old.taxonomy_version='feedback-language-coach-revision-v1') OR EXISTS(SELECT 1 FROM public.feedback_revisions newer WHERE newer.supersedes_id=p_supersedes_revision_id AND newer.taxonomy_version='feedback-language-coach-revision-v1')) THEN RAISE EXCEPTION 'FEEDBACK_LANGUAGE_REVISION_INVALID'; END IF;
 INSERT INTO public.feedback_revisions(id,evidence_span_id,value,rater_role,rater_id,taxonomy_version,revision_payload,supersedes_id,idempotency_key,feedback_membership_id,feedback_candidate_id,candidate_output_version,candidate_output_sha256,output_kind,comment_purpose,review_batch_id,reveal_grant_id,reveal_access_id,review_assignment_id,blind_judgment_id,acquisition_principal_id,revision_sha256) VALUES(gen_random_uuid(),i.evidence_span_id,p_revision_text,'coach',p_reviewer_principal_id,'feedback-language-coach-revision-v1',jsonb_build_object('output_kind',p_output_kind,'comment_purpose',p_comment_purpose),p_supersedes_revision_id,p_idempotency_key,p_feedback_membership_id,p_feedback_candidate_id,'feedback-candidate-output-v1',p_candidate_output_sha256,p_output_kind,p_comment_purpose,p_review_batch_id,p_reveal_grant_id,p_reveal_access_id,p_review_assignment_id,p_blind_judgment_id,a.acquisition_principal_id,digest) RETURNING * INTO r;
 PERFORM public.require_coach_guidance_reviewer_access_v1(p_reviewer_principal_id); PERFORM public.require_coach_guidance_assignment_live_v1(p_review_assignment_id,a.acquisition_principal_id,'coach_review'); PERFORM public.require_mlc3_service_access_v2(a.acquisition_principal_id,NULL,NULL); RETURN to_jsonb(r);
END $$;

CREATE OR REPLACE FUNCTION public.schedule_feedback_language_revision_v1(p_revision_id uuid,p_recipient_principal_id uuid,p_target_take_id uuid,p_anchor_candidate_id uuid,p_idempotency_key text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE r public.feedback_revisions; auth jsonb; d public.feedback_language_revision_deliveries; digest text; n integer;
BEGIN
 IF COALESCE(btrim(p_idempotency_key),'')='' THEN RAISE EXCEPTION 'FEEDBACK_LANGUAGE_REVISION_INVALID'; END IF; PERFORM pg_advisory_xact_lock(hashtextextended('feedback-language-delivery:'||p_idempotency_key,0)); PERFORM pg_advisory_xact_lock(hashtextextended('feedback-language-delivery-revision:'||p_revision_id::text||':'||p_recipient_principal_id::text||':'||p_target_take_id::text,0)); SELECT * INTO STRICT r FROM public.feedback_revisions WHERE id=p_revision_id AND taxonomy_version='feedback-language-coach-revision-v1' AND acquisition_principal_id=p_recipient_principal_id; auth:=public.require_mlc3_service_access_v2(p_recipient_principal_id,NULL,NULL);
 IF NOT EXISTS(SELECT 1 FROM public.v2_sessions target_take JOIN public.feedback_v3_memberships source_membership ON source_membership.id=r.feedback_membership_id WHERE target_take.id=p_target_take_id AND target_take.owner_principal_id=p_recipient_principal_id AND target_take.project_id=source_membership.project_id) OR NOT EXISTS(SELECT 1 FROM public.feedback_v3_membership_items WHERE membership_id=r.feedback_membership_id AND candidate_id=p_anchor_candidate_id AND feedback_family='confident_voice' AND selected) THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_ANCHOR_INVALID'; END IF;
 SELECT COALESCE(max(delivery_revision),0)+1 INTO n FROM public.feedback_language_revision_deliveries WHERE revision_id=r.id AND recipient_principal_id=p_recipient_principal_id AND target_take_id=p_target_take_id;
 digest:=public.exercise_json_sha256_v1(jsonb_build_object('revision',r.id,'recipient',p_recipient_principal_id,'take',p_target_take_id,'anchor',p_anchor_candidate_id,'rollout',auth->>'rollout_revision_id','enrollment',auth->>'enrollment_revision_id'));
 SELECT * INTO d FROM public.feedback_language_revision_deliveries WHERE idempotency_key=p_idempotency_key; IF d.id IS NOT NULL THEN IF d.delivery_sha256<>digest THEN RAISE EXCEPTION 'FEEDBACK_LANGUAGE_REPLAY_CONFLICT'; END IF; RETURN to_jsonb(d); END IF;
 INSERT INTO public.feedback_language_revision_deliveries(revision_id,acquisition_principal_id,recipient_principal_id,target_take_id,anchor_candidate_id,delivery_state,delivery_revision,authorization_rollout_revision_id,authorization_enrollment_revision_id,delivery_sha256,idempotency_key) VALUES(r.id,p_recipient_principal_id,p_recipient_principal_id,p_target_take_id,p_anchor_candidate_id,'scheduled_next_take',n,(auth->>'rollout_revision_id')::uuid,(auth->>'enrollment_revision_id')::uuid,digest,p_idempotency_key) RETURNING * INTO d;
 PERFORM public.require_mlc3_service_access_v2(p_recipient_principal_id,d.authorization_rollout_revision_id,d.authorization_enrollment_revision_id); RETURN to_jsonb(d);
END $$;

CREATE OR REPLACE FUNCTION public.ack_feedback_language_revision_render_v3(p_recipient_principal_id uuid,p_bundle_id uuid,p_bundle_attachment_id uuid,p_revision_id uuid,p_revision_delivery_id uuid,p_presentation_id uuid,p_render_instance_id uuid,p_idempotency_key text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE d public.feedback_language_revision_deliveries; revision public.feedback_revisions;
 membership public.feedback_v3_memberships; p public.ml_presentations;
 attachment public.confident_moment_bundle_attachments;
 e public.ml_rendered_exposures; affected_take_id uuid;
 audio_inventory_before text; audio_inventory_after text; exposure_count integer;
BEGIN
 IF COALESCE(btrim(p_idempotency_key),'')='' THEN RAISE EXCEPTION 'FEEDBACK_LANGUAGE_RENDER_INVALID'; END IF;
 SELECT * INTO STRICT d FROM public.feedback_language_revision_deliveries
  WHERE id=p_revision_delivery_id AND recipient_principal_id=p_recipient_principal_id;
 SELECT * INTO STRICT revision FROM public.feedback_revisions
  WHERE id=p_revision_id AND id=d.revision_id
    AND taxonomy_version='feedback-language-coach-revision-v1';
 SELECT * INTO STRICT membership FROM public.feedback_v3_memberships
  WHERE id=revision.feedback_membership_id AND acquisition_principal_id=p_recipient_principal_id;
 SELECT * INTO STRICT attachment FROM public.confident_moment_bundle_attachments
  WHERE id=p_bundle_attachment_id
    AND bundle_subject_candidate_id=p_bundle_id
    AND acquisition_principal_id=p_recipient_principal_id
    AND feedback_membership_id=membership.id
    AND attached_candidate_id=revision.feedback_candidate_id
    AND project_id=membership.project_id AND take_id=membership.take_id;
 PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-rollout-policy-v2',0));
 PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-service-principal:'||p_recipient_principal_id::text,0));
 PERFORM pg_advisory_xact_lock(hashtextextended('confident-moment-project-inventory:'||membership.project_id::text,0));
 FOR affected_take_id IN SELECT id FROM (VALUES(membership.take_id),(d.target_take_id)) affected(id) ORDER BY id LOOP
  PERFORM pg_advisory_xact_lock(hashtextextended('confident-moment-take-inventory:'||affected_take_id::text,0));
 END LOOP;
 FOR affected_take_id IN SELECT id FROM (VALUES(membership.take_id),(d.target_take_id)) affected(id) ORDER BY id LOOP
  PERFORM pg_advisory_xact_lock(hashtextextended('feedback-v3-membership-inventory:'||membership.project_id::text||':'||affected_take_id::text,0));
 END LOOP;
 -- D11 order 60/70. Freeze the complete affected audio/deletion/purge identity
 -- before waiting, acquire both speaker-attempt serializers unconditionally,
 -- then lock the exact pre-lock object set and rederive. A writer that wins the
 -- race produces a typed retry before any exposure mutation.
 SELECT public.exercise_json_sha256_v1(jsonb_build_object(
  'takes',(SELECT jsonb_agg(id ORDER BY id) FROM (VALUES(membership.take_id),(d.target_take_id)) affected(id)),
  'audio',COALESCE((SELECT jsonb_agg(jsonb_build_array(object_row.id,object_row.recording_attempt_id,object_row.exact_bytes_sha256,object_row.deleted_at) ORDER BY object_row.id) FROM public.processing_audio_objects object_row WHERE object_row.acquisition_principal_id=p_recipient_principal_id AND object_row.recording_attempt_id IN(membership.take_id,d.target_take_id)),'[]'::jsonb),
  'deletions',COALESCE((SELECT jsonb_agg(jsonb_build_array(deletion.id,deletion.audio_object_id,deletion.purge_request_id,deletion.exact_bytes_sha256,deletion.evidence_sha256) ORDER BY deletion.id) FROM public.processing_audio_object_deletion_events deletion JOIN public.processing_audio_objects object_row ON object_row.id=deletion.audio_object_id WHERE object_row.acquisition_principal_id=p_recipient_principal_id AND object_row.recording_attempt_id IN(membership.take_id,d.target_take_id)),'[]'::jsonb),
  'purges',COALESCE((SELECT jsonb_agg(jsonb_build_array(purge.id,purge.state) ORDER BY purge.id) FROM public.data_purge_requests purge WHERE purge.acquisition_principal_id=p_recipient_principal_id),'[]'::jsonb)
 )) INTO audio_inventory_before;
 FOR affected_take_id IN SELECT id FROM (VALUES(membership.take_id),(d.target_take_id)) affected(id) ORDER BY id LOOP
  PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-speaker-attempt:'||affected_take_id::text,0));
 END LOOP;
 FOR affected_take_id IN SELECT object_row.id FROM public.processing_audio_objects object_row
   WHERE object_row.acquisition_principal_id=p_recipient_principal_id
     AND object_row.recording_attempt_id IN (membership.take_id,d.target_take_id)
   ORDER BY 1 LOOP
  PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-processing-audio-object:'||affected_take_id::text,0));
 END LOOP;
 SELECT public.exercise_json_sha256_v1(jsonb_build_object(
  'takes',(SELECT jsonb_agg(id ORDER BY id) FROM (VALUES(membership.take_id),(d.target_take_id)) affected(id)),
  'audio',COALESCE((SELECT jsonb_agg(jsonb_build_array(object_row.id,object_row.recording_attempt_id,object_row.exact_bytes_sha256,object_row.deleted_at) ORDER BY object_row.id) FROM public.processing_audio_objects object_row WHERE object_row.acquisition_principal_id=p_recipient_principal_id AND object_row.recording_attempt_id IN(membership.take_id,d.target_take_id)),'[]'::jsonb),
  'deletions',COALESCE((SELECT jsonb_agg(jsonb_build_array(deletion.id,deletion.audio_object_id,deletion.purge_request_id,deletion.exact_bytes_sha256,deletion.evidence_sha256) ORDER BY deletion.id) FROM public.processing_audio_object_deletion_events deletion JOIN public.processing_audio_objects object_row ON object_row.id=deletion.audio_object_id WHERE object_row.acquisition_principal_id=p_recipient_principal_id AND object_row.recording_attempt_id IN(membership.take_id,d.target_take_id)),'[]'::jsonb),
  'purges',COALESCE((SELECT jsonb_agg(jsonb_build_array(purge.id,purge.state) ORDER BY purge.id) FROM public.data_purge_requests purge WHERE purge.acquisition_principal_id=p_recipient_principal_id),'[]'::jsonb)
 )) INTO audio_inventory_after;
 IF audio_inventory_after IS DISTINCT FROM audio_inventory_before THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_RETRY_REQUIRED';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('feedback-language-candidate:'||revision.feedback_candidate_id::text||':'||revision.rater_id::text,0));
 PERFORM pg_advisory_xact_lock(hashtextextended('feedback-language-delivery-subject:'||p_recipient_principal_id::text||':'||d.target_take_id::text||':'||membership.id::text||':'||revision.feedback_candidate_id::text,0));
 PERFORM pg_advisory_xact_lock(hashtextextended('feedback-language-revision-head:'||membership.id::text||':'||revision.feedback_candidate_id::text||':'||revision.rater_id::text,0));
 PERFORM pg_advisory_xact_lock(hashtextextended('feedback-language-render:'||p_idempotency_key,0));
 SELECT * INTO d FROM public.feedback_language_revision_deliveries delivery
  WHERE delivery.id=p_revision_delivery_id AND delivery.recipient_principal_id=p_recipient_principal_id
    AND delivery.delivery_state<>'invalidated'
    AND NOT EXISTS(SELECT 1 FROM public.feedback_language_revision_deliveries successor
      WHERE successor.supersedes_delivery_id=delivery.id AND successor.delivery_policy_version='feedback-language-delivery-v2');
 IF d.id IS NULL THEN RAISE EXCEPTION 'FEEDBACK_LANGUAGE_RENDER_STALE'; END IF;
 IF EXISTS(SELECT 1 FROM public.feedback_revisions successor
   WHERE successor.supersedes_id=revision.id AND successor.taxonomy_version='feedback-language-coach-revision-v1') THEN
  RAISE EXCEPTION 'FEEDBACK_LANGUAGE_STALE_REVISION'; END IF;
 -- The current head must be an exact D11 section 4.2 v2 delivery whose lineage
 -- matches the revision it exposes.  A legacy or forked delivery can never
 -- authorise an exposure.  IS DISTINCT FROM so a NULL legacy column fails.
 IF d.delivery_policy_version IS DISTINCT FROM 'feedback-language-delivery-v2'
  OR d.feedback_membership_id IS DISTINCT FROM membership.id
  OR d.feedback_candidate_id IS DISTINCT FROM revision.feedback_candidate_id
  OR d.anchor_candidate_id IS DISTINCT FROM COALESCE(attachment.anchor_candidate_id,attachment.bundle_subject_candidate_id)
  OR d.reviewer_principal_id IS DISTINCT FROM revision.rater_id
  OR d.revision_taxonomy_version IS DISTINCT FROM revision.taxonomy_version
  OR d.candidate_output_sha256 IS DISTINCT FROM revision.candidate_output_sha256 THEN
  RAISE EXCEPTION 'FEEDBACK_LANGUAGE_DELIVERY_LINEAGE_INVALID'; END IF;
 PERFORM public.require_mlc3_service_access_v2(p_recipient_principal_id,d.authorization_rollout_revision_id,d.authorization_enrollment_revision_id);
 -- Same exact coach/source validity the secure projection enforces, checked
 -- BEFORE the potentially blocking exposure write so a rejection creates none.
 PERFORM public.require_feedback_language_coach_source_live_v1(
  revision.id,p_recipient_principal_id,membership.id,revision.feedback_candidate_id,
  public.feedback_candidate_output_sha256_v1(revision.feedback_candidate_id),
  'FEEDBACK_LANGUAGE_COACH_AUTHORITY_INVALID');
 SELECT count(*) INTO exposure_count FROM public.ml_presentations canonical_presentation
  WHERE canonical_presentation.artifact_id=d.revision_id
    AND canonical_presentation.actor_principal_id=p_recipient_principal_id
    AND canonical_presentation.learning_surface_id=(CASE revision.output_kind WHEN 'rephrase' THEN 'correction_generation' WHEN 'comment' THEN CASE revision.comment_purpose WHEN 'positive_praise' THEN 'praise_generation' ELSE 'coach_comment_generation' END END)
    AND canonical_presentation.delivery_mode<>'shadow';
 IF exposure_count<>1 THEN RAISE EXCEPTION 'FEEDBACK_LANGUAGE_RENDER_PRESENTATION_CARDINALITY_INVALID'; END IF;
 SELECT * INTO STRICT p FROM public.ml_presentations WHERE id=p_presentation_id
  AND actor_principal_id=p_recipient_principal_id AND artifact_id=d.revision_id
  AND learning_surface_id=(CASE revision.output_kind WHEN 'rephrase' THEN 'correction_generation' WHEN 'comment' THEN CASE revision.comment_purpose WHEN 'positive_praise' THEN 'praise_generation' ELSE 'coach_comment_generation' END END)
  AND delivery_mode<>'shadow';
 SELECT count(*) INTO exposure_count FROM public.ml_rendered_exposures existing
  WHERE existing.presentation_id=p.id
    AND existing.actor_principal_id=p_recipient_principal_id;
 IF exposure_count>1 THEN RAISE EXCEPTION 'FEEDBACK_LANGUAGE_RENDER_INVALID'; END IF;
 -- Lost-ack replay is considered only after the presentation has been proven
 -- to be the exact current delivery/revision/surface identity.
 SELECT * INTO e FROM public.ml_rendered_exposures replayed
  WHERE replayed.presentation_id=p.id
    AND replayed.render_instance_id=p_render_instance_id
    AND replayed.actor_principal_id=p_recipient_principal_id;
 IF e.id IS NOT NULL THEN
  IF e.idempotency_key<>p_idempotency_key THEN
   RAISE EXCEPTION 'FEEDBACK_LANGUAGE_REPLAY_CONFLICT'; END IF;
  IF attachment.bundle_subject_candidate_id IS DISTINCT FROM p_bundle_id THEN
   RAISE EXCEPTION 'CONFIDENT_MOMENT_ATTACHMENT_INVALID'; END IF;
  RETURN jsonb_build_object(
   'render_contract_version','feedback-language-revision-render-v3',
   'bundle_id',p_bundle_id,
   'bundle_attachment_id',attachment.id,
   'current_revision_id',revision.id,
   'revision_delivery_id',d.id,
   'presentation_id',p.id,
   'render_instance_id',e.render_instance_id,
   'rendered_exposure_id',e.id,
   'dataset_eligible',false);
 END IF;
 SELECT * INTO e FROM public.ack_mlc2_rendered_exposure_v1(p.id,p.acknowledgement_token,p_recipient_principal_id,p_render_instance_id,clock_timestamp(),'feedback-language-coach-revision-v1',p.visible_payload_sha256,p_idempotency_key);
 SELECT count(*) INTO exposure_count FROM public.ml_rendered_exposures existing
  WHERE existing.presentation_id=p.id
    AND existing.actor_principal_id=p_recipient_principal_id;
 IF exposure_count<>1 THEN RAISE EXCEPTION 'FEEDBACK_LANGUAGE_RENDER_INVALID'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.feedback_language_revision_deliveries current_delivery
   WHERE current_delivery.id=d.id AND current_delivery.delivery_state<>'invalidated'
   AND NOT EXISTS(SELECT 1 FROM public.feedback_language_revision_deliveries successor WHERE successor.supersedes_delivery_id=current_delivery.id AND successor.delivery_policy_version='feedback-language-delivery-v2'))
  OR EXISTS(SELECT 1 FROM public.feedback_revisions successor WHERE successor.supersedes_id=revision.id AND successor.taxonomy_version='feedback-language-coach-revision-v1') THEN
  RAISE EXCEPTION 'FEEDBACK_LANGUAGE_RENDER_STALE'; END IF;
 PERFORM public.require_mlc3_service_access_v2(p_recipient_principal_id,d.authorization_rollout_revision_id,d.authorization_enrollment_revision_id);
 -- Revalidated after the contended exposure write.  A reviewer-access
 -- withdrawal or source deletion/purge that won the race aborts the whole
 -- transaction, so the exposure row never becomes visible.
 PERFORM public.require_feedback_language_coach_source_live_v1(
  revision.id,p_recipient_principal_id,membership.id,revision.feedback_candidate_id,
  public.feedback_candidate_output_sha256_v1(revision.feedback_candidate_id),
  'FEEDBACK_LANGUAGE_COACH_AUTHORITY_INVALID');
 IF attachment.bundle_subject_candidate_id IS DISTINCT FROM p_bundle_id THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_ATTACHMENT_INVALID'; END IF;
 RETURN jsonb_build_object(
  'render_contract_version','feedback-language-revision-render-v3',
  'bundle_id',p_bundle_id,
  'bundle_attachment_id',attachment.id,
  'current_revision_id',revision.id,
  'revision_delivery_id',d.id,
  'presentation_id',p.id,
  'render_instance_id',e.render_instance_id,
  'rendered_exposure_id',e.id,
  'dataset_eligible',false);
END $$;
DROP FUNCTION IF EXISTS public.ack_feedback_language_revision_render_v1(uuid,uuid,uuid,uuid,text);
DROP FUNCTION IF EXISTS public.ack_feedback_language_revision_render_v2(uuid,uuid,uuid,uuid,uuid,uuid,text);

-- D49 sole target-speaker currentness resolver.  Callers must already follow
-- the global attempt(60)/audio(70) order; reacquiring the same keys is safe.
CREATE OR REPLACE FUNCTION public.resolve_confident_moment_target_speaker_binding_v1(
 p_acquisition_principal_id uuid,p_recording_attempt_id uuid,p_audio_object_id uuid,
 p_target_kind text,p_clip_id uuid,p_practice_attempt_id uuid
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE acquisition public.mlc3_speaker_acquisition_revisions;
 binding public.mlc3_target_speaker_bindings; media public.processing_audio_objects;
 n integer; body jsonb; result_hash text;
BEGIN
 IF NOT ((p_target_kind='source_clip' AND p_clip_id IS NOT NULL AND p_practice_attempt_id IS NULL)
      OR (p_target_kind='practice_attempt' AND p_practice_attempt_id IS NOT NULL AND p_clip_id IS NULL)) THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_TARGET_SPEAKER_INVALID'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-speaker-attempt:'||p_recording_attempt_id::text,0));
 PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-processing-audio-object:'||p_audio_object_id::text,0));
 SELECT * INTO STRICT media FROM public.processing_audio_objects o
  WHERE o.id=p_audio_object_id AND o.recording_attempt_id=p_recording_attempt_id
    AND o.acquisition_principal_id=p_acquisition_principal_id AND o.deleted_at IS NULL
    AND NOT EXISTS(SELECT 1 FROM public.processing_audio_object_deletion_events d
      WHERE d.audio_object_id=o.id);
 SELECT count(*),(array_agg(r.id ORDER BY r.revision_number DESC,r.id DESC))[1]
  INTO n,acquisition.id FROM public.mlc3_speaker_acquisition_revisions r
  WHERE r.acquisition_principal_id=p_acquisition_principal_id
    AND r.recording_attempt_id=p_recording_attempt_id AND r.audio_object_id=p_audio_object_id
    AND NOT EXISTS(SELECT 1 FROM public.mlc3_speaker_acquisition_revisions successor
      WHERE successor.supersedes_revision_id=r.id);
 IF n<>1 THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_TARGET_SPEAKER_INVALID'; END IF;
 SELECT * INTO STRICT acquisition FROM public.mlc3_speaker_acquisition_revisions r
  WHERE r.id=acquisition.id AND r.speaker_identity_status='resolved'
    AND r.speaker_id IS NOT NULL AND r.audio_sha256=media.exact_bytes_sha256;
 SELECT count(*),(array_agg(b.id ORDER BY b.revision_number DESC,b.id DESC))[1]
  INTO n,binding.id FROM public.mlc3_target_speaker_bindings b
  WHERE b.acquisition_principal_id=p_acquisition_principal_id
    AND b.recording_attempt_id=p_recording_attempt_id AND b.audio_object_id=p_audio_object_id
    AND b.acquisition_revision_id=acquisition.id AND b.binding_state='active'
    AND b.speaker_id=acquisition.speaker_id AND b.audio_sha256=media.exact_bytes_sha256
    AND ((p_target_kind='source_clip' AND b.clip_id=p_clip_id AND b.practice_attempt_id IS NULL)
      OR (p_target_kind='practice_attempt' AND b.practice_attempt_id=p_practice_attempt_id AND b.clip_id IS NULL))
    AND NOT EXISTS(SELECT 1 FROM public.mlc3_target_speaker_bindings successor
      WHERE successor.supersedes_binding_id=b.id);
 IF n<>1 THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_TARGET_SPEAKER_INVALID'; END IF;
 SELECT * INTO STRICT binding FROM public.mlc3_target_speaker_bindings b WHERE b.id=binding.id;
 body:=jsonb_build_object('contract_version','confident-moment-target-speaker-binding-v1',
  'target_kind',p_target_kind,'acquisition_revision_id',acquisition.id,
  'target_speaker_binding_id',binding.id,'speaker_id',binding.speaker_id);
 result_hash:=public.exercise_json_sha256_v1(body||jsonb_build_object(
  'acquisition_principal_id',p_acquisition_principal_id,
  'recording_attempt_id',p_recording_attempt_id,'audio_object_id',p_audio_object_id,
  'audio_sha256',media.exact_bytes_sha256,
  'target_identity',COALESCE(p_clip_id,p_practice_attempt_id)));
 RETURN body||jsonb_build_object('result_sha256',result_hash);
EXCEPTION WHEN no_data_found THEN
 RAISE EXCEPTION 'CONFIDENT_MOMENT_TARGET_SPEAKER_INVALID';
END $$;

CREATE OR REPLACE FUNCTION public.require_root_phrase_practice_source_live_v1(p_acquisition_principal_id uuid,p_content_version_id uuid,p_practice_attempt_id uuid,p_source_target_speaker_binding_id uuid,p_practice_target_speaker_binding_id uuid) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE
 c public.root_phrase_content_versions; attempt public.exercise_practice_attempts; practice public.exercise_practice_sessions; offer public.exercise_service_offers; lineage public.exercise_audio_lineages;
 source_binding public.mlc3_target_speaker_bindings; practice_binding public.mlc3_target_speaker_bindings;
 source_object public.processing_audio_objects; practice_object public.processing_audio_objects; digest text;
 correlation jsonb; correlated_attachment public.confident_moment_bundle_attachments;
 source_result jsonb; practice_result jsonb;
BEGIN
 IF p_practice_attempt_id IS NULL OR p_source_target_speaker_binding_id IS NULL OR p_practice_target_speaker_binding_id IS NULL THEN RAISE EXCEPTION 'ROOTING_PHRASE_PRACTICE_SOURCE_INVALID'; END IF;
 SELECT * INTO STRICT c FROM public.root_phrase_content_versions WHERE id=p_content_version_id AND acquisition_principal_id=p_acquisition_principal_id;
 SELECT * INTO STRICT attempt FROM public.exercise_practice_attempts WHERE id=p_practice_attempt_id AND acquisition_principal_id=p_acquisition_principal_id;
 SELECT * INTO STRICT practice FROM public.exercise_practice_sessions WHERE id=attempt.session_id AND acquisition_principal_id=p_acquisition_principal_id;
 SELECT * INTO STRICT offer FROM public.exercise_service_offers WHERE id=practice.source_offer_id AND acquisition_principal_id=p_acquisition_principal_id;
 SELECT * INTO STRICT lineage FROM public.exercise_audio_lineages WHERE id=offer.source_audio_lineage_id AND acquisition_principal_id=p_acquisition_principal_id;
 PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-speaker-attempt:'||least(lineage.recording_attempt_id,attempt.processing_recording_attempt_id)::text,0));
 PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-speaker-attempt:'||greatest(lineage.recording_attempt_id,attempt.processing_recording_attempt_id)::text,0));
 PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-processing-audio-object:'||least(lineage.processing_audio_object_id,attempt.processing_audio_object_id)::text,0));
 PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-processing-audio-object:'||greatest(lineage.processing_audio_object_id,attempt.processing_audio_object_id)::text,0));
 PERFORM public.require_mlc3_service_access_v2(p_acquisition_principal_id,attempt.rollout_revision_id,attempt.enrollment_revision_id);
 practice:=public.require_practice_source_live_v1(attempt.session_id,p_acquisition_principal_id);
 offer:=public.require_exercise_service_offer_live_v1(practice.source_offer_id,p_acquisition_principal_id);
 SELECT * INTO STRICT attempt FROM public.exercise_practice_attempts row WHERE row.id=p_practice_attempt_id AND row.session_id=practice.id AND row.acquisition_principal_id=p_acquisition_principal_id AND row.processing_recording_attempt_id IS NOT NULL AND row.processing_audio_object_id IS NOT NULL AND row.state IN('captured','processed') AND row.transcript_state='available' AND row.operation_mode=public.current_mlc3_operation_mode_v2() FOR SHARE;
 SELECT * INTO STRICT lineage FROM public.exercise_audio_lineages row WHERE row.id=offer.source_audio_lineage_id AND row.acquisition_principal_id=p_acquisition_principal_id AND row.project_id=c.project_id AND row.take_id=offer.source_take_id FOR SHARE;
 SELECT * INTO STRICT correlated_attachment FROM public.confident_moment_bundle_attachments a
  WHERE a.acquisition_principal_id=p_acquisition_principal_id
    AND a.feedback_membership_id=offer.feedback_membership_id
    AND a.bundle_subject_kind='confidence_anchor'
    AND a.bundle_subject_candidate_id=offer.feedback_candidate_id
    AND a.attached_candidate_id=offer.feedback_candidate_id;
 correlation:=public.resolve_confident_moment_exercise_offer_v1(
  p_acquisition_principal_id,correlated_attachment.bundle_subject_candidate_id,
  correlated_attachment.id);
 IF correlation->>'status'<>'available' OR (correlation->>'offer_id')::uuid<>offer.id
    OR (correlation->>'source_target_speaker_binding_id')::uuid
       IS DISTINCT FROM p_source_target_speaker_binding_id THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_INVALID'; END IF;
 IF practice.project_id<>c.project_id OR practice.source_take_id<>offer.source_take_id OR offer.feedback_membership_id<>c.feedback_membership_id OR NOT EXISTS(SELECT 1 FROM public.feedback_v3_membership_items item WHERE item.membership_id=offer.feedback_membership_id AND item.candidate_id=offer.feedback_candidate_id AND item.selected AND item.eligibility='eligible' AND item.slide_index=c.slide_index AND item.block_key=c.block_key) OR NOT (offer.feedback_candidate_id=c.feedback_candidate_id OR EXISTS(SELECT 1 FROM public.confident_moment_bundle_attachments attachment WHERE attachment.feedback_membership_id=c.feedback_membership_id AND attachment.attached_candidate_id=c.feedback_candidate_id AND attachment.anchor_candidate_id=offer.feedback_candidate_id AND attachment.acquisition_principal_id=p_acquisition_principal_id)) THEN RAISE EXCEPTION 'ROOTING_PHRASE_PRACTICE_SOURCE_INVALID'; END IF;
 IF public.root_phrase_normalize_transcript_v1(attempt.exact_passage)<>public.root_phrase_normalize_transcript_v1(c.phrase_text) OR public.root_phrase_normalize_transcript_v1(attempt.transcript_text)<>public.root_phrase_normalize_transcript_v1(c.phrase_text) THEN RAISE EXCEPTION 'ROOTING_PHRASE_PRACTICE_SOURCE_INVALID'; END IF;
 SELECT * INTO STRICT source_object FROM public.processing_audio_objects row WHERE row.id=lineage.processing_audio_object_id AND row.recording_attempt_id=lineage.recording_attempt_id AND row.acquisition_principal_id=p_acquisition_principal_id AND row.exact_bytes_sha256=lineage.exact_audio_sha256 AND row.deleted_at IS NULL AND NOT EXISTS(SELECT 1 FROM public.processing_audio_object_deletion_events deletion WHERE deletion.audio_object_id=row.id) FOR SHARE;
 SELECT * INTO STRICT practice_object FROM public.processing_audio_objects row WHERE row.id=attempt.processing_audio_object_id AND row.recording_attempt_id=attempt.processing_recording_attempt_id AND row.acquisition_principal_id=p_acquisition_principal_id AND row.exact_bytes_sha256=attempt.exact_audio_sha256 AND row.deleted_at IS NULL AND NOT EXISTS(SELECT 1 FROM public.processing_audio_object_deletion_events deletion WHERE deletion.audio_object_id=row.id) FOR SHARE;
 source_result:=public.resolve_confident_moment_target_speaker_binding_v1(
  p_acquisition_principal_id,lineage.recording_attempt_id,lineage.processing_audio_object_id,
  'source_clip',lineage.snippet_id,NULL);
 practice_result:=public.resolve_confident_moment_target_speaker_binding_v1(
  p_acquisition_principal_id,attempt.processing_recording_attempt_id,attempt.processing_audio_object_id,
  'practice_attempt',NULL,attempt.id);
 SELECT * INTO STRICT source_binding FROM public.mlc3_target_speaker_bindings
  WHERE id=(source_result->>'target_speaker_binding_id')::uuid;
 SELECT * INTO STRICT practice_binding FROM public.mlc3_target_speaker_bindings
  WHERE id=(practice_result->>'target_speaker_binding_id')::uuid;
 IF source_binding.id IS DISTINCT FROM p_source_target_speaker_binding_id
    OR practice_binding.id IS DISTINCT FROM p_practice_target_speaker_binding_id
    OR source_binding.acquisition_principal_id<>p_acquisition_principal_id
    OR practice_binding.acquisition_principal_id<>p_acquisition_principal_id THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_INVALID'; END IF;
 IF source_binding.speaker_id<>practice_binding.speaker_id
    OR source_binding.audio_object_id<>source_object.id
    OR practice_binding.audio_object_id<>practice_object.id THEN
  RAISE EXCEPTION 'ROOTING_PHRASE_SPEAKER_IDENTITY_INVALID'; END IF;
 PERFORM public.require_mlc3_service_access_v2(p_acquisition_principal_id,attempt.rollout_revision_id,attempt.enrollment_revision_id);
 digest:=public.exercise_json_sha256_v1(jsonb_build_object('guard','root-phrase-practice-source-v1','principal',p_acquisition_principal_id,'content',c.id,'practice_attempt',attempt.id,'practice_session',practice.id,'offer',offer.id,'source_lineage',lineage.id,'source_audio',source_object.id,'practice_audio',practice_object.id,'source_binding_result',source_result,'practice_binding_result',practice_result,'speaker',source_binding.speaker_id,'phrase',c.content_version_sha256,'attempt_hash',attempt.attempt_sha256));
 RETURN jsonb_build_object('practice_guard_sha256',digest,'source_target_speaker_binding_id',source_binding.id,'practice_target_speaker_binding_id',practice_binding.id);
EXCEPTION WHEN no_data_found THEN RAISE EXCEPTION 'ROOTING_PHRASE_PRACTICE_SOURCE_INVALID';
END $$;

CREATE OR REPLACE FUNCTION public.transition_ideal_text_root_state_v1(p_acquisition_principal_id uuid,p_project_id uuid,p_take_id uuid,p_content_version_id uuid,p_expected_part_revision_id bigint,p_transition_action text,p_idempotency_key text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE
 c public.root_phrase_content_versions;
 s public.ideal_text_document_snapshots;
 p public.ideal_text_part;
 latest bigint;
 lock_revision_id bigint;
 root_revision_id bigint;
 review_version integer;
 must_set_root boolean;
 must_remove_root boolean;
 must_lock boolean;
 must_unlock boolean;
BEGIN
 IF p_transition_action NOT IN('set_automatic_root','set_owner_selected_root','lock_current_root','restore_owner_selected_root','unlock_current_root','remove_current_root','legacy_qualified_lock_and_activate','legacy_qualified_activate','legacy_qualified_remove') OR COALESCE(btrim(p_idempotency_key),'')='' THEN RAISE EXCEPTION 'ROOT_IDEAL_TEXT_TRANSITION_INVALID'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('ideal-root-transition:'||p_idempotency_key,0));
 SELECT * INTO c FROM public.require_synthetic_root_content_live_v1(p_content_version_id);
 IF c.acquisition_principal_id<>p_acquisition_principal_id OR c.project_id<>p_project_id OR NOT EXISTS(SELECT 1 FROM public.feedback_v3_memberships m WHERE m.id=c.feedback_membership_id AND m.take_id=p_take_id) THEN RAISE EXCEPTION 'ROOT_IDEAL_TEXT_TRANSITION_INVALID'; END IF;
 SELECT * INTO STRICT s FROM public.ideal_text_document_snapshots WHERE id=c.document_snapshot_id AND project_id=p_project_id;
 PERFORM 1 FROM public.ideal_text_document_heads WHERE snapshot_id=s.id FOR SHARE;
 PERFORM public.lock_confident_moment_position_100_v1(ARRAY[]::text[],ARRAY[]::text[],ARRAY[
  'ideal-text-part-revision-head:'||s.arc_id||':'||s.actor_id||':'||c.source_ideal_part_id::text]);
 SELECT * INTO STRICT p FROM public.ideal_text_part WHERE id=c.source_ideal_part_id AND arc_id=s.arc_id AND user_id=s.actor_id AND text=c.paragraph_text FOR UPDATE;
 SELECT id INTO latest FROM public.ideal_text_part_revision WHERE part_id=p.id ORDER BY id DESC LIMIT 1;
 IF latest IS DISTINCT FROM p_expected_part_revision_id THEN RAISE EXCEPTION 'ROOT_IDEAL_TEXT_STALE_REVISION'; END IF;
 SELECT take_index INTO STRICT review_version FROM public.feedback_v3_memberships WHERE id=c.feedback_membership_id AND take_id=p_take_id;
 must_set_root:=p_transition_action IN('set_automatic_root','set_owner_selected_root','restore_owner_selected_root','legacy_qualified_lock_and_activate','legacy_qualified_activate');
 must_remove_root:=p_transition_action IN('remove_current_root','legacy_qualified_remove');
 must_lock:=p_transition_action IN('lock_current_root','legacy_qualified_lock_and_activate');
 must_unlock:=p_transition_action='unlock_current_root';
 IF p_transition_action IN('lock_current_root','unlock_current_root') AND (p.root_phrase IS DISTINCT FROM c.phrase_text OR p.root_start IS DISTINCT FROM c.phrase_start OR p.root_end IS DISTINCT FROM c.phrase_end) THEN RAISE EXCEPTION 'ROOT_IDEAL_TEXT_TRANSITION_INVALID'; END IF;
 IF p_transition_action='legacy_qualified_activate' AND p.locked_at IS NULL THEN RAISE EXCEPTION 'ROOT_ACTIVATION_REQUIRES_LOCK'; END IF;
 IF must_lock AND p.locked_at IS NULL THEN
  UPDATE public.ideal_text_part SET locked_at=clock_timestamp(),iteration=iteration+1,updated_at=clock_timestamp() WHERE id=p.id;
  INSERT INTO public.ideal_text_part_revision(arc_id,user_id,part_id,action,text,root_phrase,take_session_id,review_version) VALUES(s.arc_id,s.actor_id,p.id,'lock',p.text,p.root_phrase,p_take_id,review_version) RETURNING id INTO lock_revision_id;
 ELSIF p_transition_action='lock_current_root' THEN RAISE EXCEPTION 'ROOT_IDEAL_TEXT_TRANSITION_INVALID';
 END IF;
 IF must_unlock THEN
  IF p.locked_at IS NULL THEN RAISE EXCEPTION 'ROOT_IDEAL_TEXT_TRANSITION_INVALID'; END IF;
  UPDATE public.ideal_text_part SET locked_at=NULL,updated_at=clock_timestamp() WHERE id=p.id;
  INSERT INTO public.ideal_text_part_revision(arc_id,user_id,part_id,action,text,root_phrase,take_session_id,review_version) VALUES(s.arc_id,s.actor_id,p.id,'unlock',p.text,p.root_phrase,p_take_id,review_version) RETURNING id INTO root_revision_id;
 ELSIF must_set_root THEN
  UPDATE public.ideal_text_part SET root_phrase=c.phrase_text,root_start=c.phrase_start,root_end=c.phrase_end,root_selected_at=clock_timestamp(),updated_at=clock_timestamp() WHERE id=p.id;
  INSERT INTO public.ideal_text_part_revision(arc_id,user_id,part_id,action,text,root_phrase,take_session_id,review_version) VALUES(s.arc_id,s.actor_id,p.id,'root_set',p.text,c.phrase_text,p_take_id,review_version) RETURNING id INTO root_revision_id;
 ELSIF must_remove_root THEN
  IF p.root_phrase IS DISTINCT FROM c.phrase_text OR p.root_start IS DISTINCT FROM c.phrase_start OR p.root_end IS DISTINCT FROM c.phrase_end THEN RAISE EXCEPTION 'ROOT_IDEAL_TEXT_TRANSITION_INVALID'; END IF;
  UPDATE public.ideal_text_part SET root_phrase=NULL,root_start=NULL,root_end=NULL,root_selected_at=NULL,updated_at=clock_timestamp() WHERE id=p.id;
  INSERT INTO public.ideal_text_part_revision(arc_id,user_id,part_id,action,text,root_phrase,take_session_id,review_version) VALUES(s.arc_id,s.actor_id,p.id,'root_skipped',p.text,NULL,p_take_id,review_version) RETURNING id INTO root_revision_id;
 END IF;
 PERFORM public.require_synthetic_root_content_live_v1(c.id);
 RETURN jsonb_build_object('part_id',p.id,'lock_revision_id',lock_revision_id,'part_revision_id',COALESCE(root_revision_id,lock_revision_id),'transition_action',p_transition_action);
END $$;

DO $$ DECLARE body text; original text; BEGIN
 body:=pg_get_functiondef('public.activate_synthetic_root_phrase_v1(uuid,uuid,boolean,boolean,text)'::regprocedure); original:=body;
 IF position('transition_ideal_text_root_state_v1' in body)=0 THEN
  body:=replace(body,'action_hash TEXT; revision BIGINT;','action_hash TEXT; revision BIGINT; latest_part_revision BIGINT;');
  body:=regexp_replace(body,'(?s)        IF canonical_part\.locked_at IS NULL THEN.*?        action_hash :=',$r$        -- Canonical lock mutation is delegated below.
        action_hash :=$r$);
  body:=regexp_replace(body,'(?s)    UPDATE public\.ideal_text_part.*?    IF NOT FOUND THEN RAISE EXCEPTION ''ROOT_CANONICAL_ROOT_FAILED''; END IF;',$r$    SELECT id INTO latest_part_revision FROM public.ideal_text_part_revision WHERE part_id=canonical_part.id ORDER BY id DESC LIMIT 1;
    PERFORM public.transition_ideal_text_root_state_v1(content.acquisition_principal_id,content.project_id,membership.take_id,content.id,latest_part_revision,CASE WHEN p_lock_and_root THEN 'legacy_qualified_lock_and_activate' ELSE 'legacy_qualified_activate' END,p_idempotency_key||':ideal-text');$r$);
  IF body=original THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_LEGACY_ACTIVATION_SHAPE_DRIFT'; END IF;
  EXECUTE body;
  body:=pg_get_functiondef('public.activate_synthetic_root_phrase_v1(uuid,uuid,boolean,boolean,text)'::regprocedure);
 END IF;
 IF position('D11 legacy root writer: global inventory before root block' in body)=0 THEN
  body:=replace(body,
   E'    PERFORM pg_advisory_xact_lock(hashtextextended(\n        ''root-block:'' || content.project_id::TEXT',
   E'    -- D11 legacy root writer: global inventory before root block\n    PERFORM public.lock_confident_moment_inventory_v1(content.acquisition_principal_id,content.project_id,membership.take_id);\n    PERFORM pg_advisory_xact_lock(hashtextextended(\n        ''root-block:'' || content.project_id::TEXT');
 END IF;
 IF body<>original THEN EXECUTE body; END IF;
 body:=pg_get_functiondef('public.activate_synthetic_root_phrase_v1(uuid,uuid,boolean,boolean,text)'::regprocedure);
 IF position('UPDATE public.ideal_text_part' in body)>0 OR position('INSERT INTO public.ideal_text_part_revision' in body)>0 OR position('transition_ideal_text_root_state_v1' in body)=0 THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_LEGACY_ACTIVATION_SHAPE_DRIFT'; END IF;
 body:=pg_get_functiondef('public.remove_synthetic_root_phrase_v1(uuid,integer,integer,uuid,uuid,text)'::regprocedure); original:=body;
 IF position('transition_ideal_text_root_state_v1' in body)=0 THEN
  body:=replace(body,'revision BIGINT; action_hash TEXT;','revision BIGINT; action_hash TEXT; latest_part_revision BIGINT;');
  body:=regexp_replace(body,'(?s)    UPDATE public\.ideal_text_part.*?    IF NOT FOUND THEN RAISE EXCEPTION ''ROOT_REMOVAL_CANONICAL_CLEAR_FAILED''; END IF;',$r$    SELECT id INTO latest_part_revision FROM public.ideal_text_part_revision WHERE part_id=canonical_part.id ORDER BY id DESC LIMIT 1;
    PERFORM public.transition_ideal_text_root_state_v1(content.acquisition_principal_id,content.project_id,(SELECT take_id FROM public.feedback_v3_memberships WHERE id=content.feedback_membership_id),content.id,latest_part_revision,'legacy_qualified_remove',p_idempotency_key||':ideal-text');$r$);
 END IF;
 IF position('require_synthetic_root_content_live_v1(remove_action.content_version_id)' in body)=0 THEN
  body:=regexp_replace(body,'        RETURN jsonb_build_object\(',$r$        PERFORM public.require_synthetic_root_content_live_v1(remove_action.content_version_id);
        RETURN jsonb_build_object($r$);
 END IF;
 IF position('D11 legacy root writer: global inventory before root block' in body)=0 THEN
  body:=replace(body,
   E'    PERFORM pg_advisory_xact_lock(hashtextextended(\n        ''root-block:'' || p_project_id::TEXT',
   E'    -- D11 legacy root writer: global inventory before root block\n    PERFORM public.lock_confident_moment_inventory_v1(\n        (SELECT block_head.acquisition_principal_id FROM public.root_phrase_block_heads block_head WHERE block_head.project_id=p_project_id AND block_head.slide_index=p_slide_index AND block_head.block_key=p_block_key),\n        p_project_id,\n        (SELECT source_membership.take_id FROM public.root_phrase_block_heads block_head JOIN public.root_phrase_product_actions source_action ON source_action.id=block_head.active_root_action_id JOIN public.root_phrase_content_versions source_content ON source_content.id=source_action.content_version_id JOIN public.feedback_v3_memberships source_membership ON source_membership.id=source_content.feedback_membership_id WHERE block_head.project_id=p_project_id AND block_head.slide_index=p_slide_index AND block_head.block_key=p_block_key));\n    PERFORM pg_advisory_xact_lock(hashtextextended(\n        ''root-block:'' || p_project_id::TEXT');
 END IF;
 IF body<>original THEN EXECUTE body; END IF;
 body:=pg_get_functiondef('public.remove_synthetic_root_phrase_v1(uuid,integer,integer,uuid,uuid,text)'::regprocedure);
 IF position('UPDATE public.ideal_text_part' in body)>0 OR position('transition_ideal_text_root_state_v1' in body)=0 THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_LEGACY_REMOVAL_SHAPE_DRIFT'; END IF;
END $$;

CREATE OR REPLACE FUNCTION public.record_root_phrase_product_action_v2(p_acquisition_principal_id uuid,p_project_id uuid,p_take_id uuid,p_paragraph_id uuid,p_block_key integer,p_action text,p_expected_block_head_action_id uuid,p_source_candidate_id uuid,p_source_evidence_span_id uuid,p_source_feedback_exposure_id uuid,p_source_owner_response_id uuid,p_source_practice_attempt_id uuid,p_source_ideal_text_revision_id bigint,p_source_text_update_binding_id uuid,p_source_target_speaker_binding_id uuid,p_practice_target_speaker_binding_id uuid,p_restore_product_action_id uuid,p_policy_version text,p_idempotency_key text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE c public.root_phrase_content_versions; h public.root_phrase_block_heads; old public.root_phrase_product_actions; r public.root_phrase_product_actions; part public.ideal_text_part; u uuid; origin text; persistence text; qualification text; mapped text; rev bigint; digest text; expected_revision bigint; practice_guard jsonb; practice_guard_hash text;
BEGIN
 IF p_policy_version<>'rooting-coverage-30-80-100-v1' OR p_action NOT IN('activate_automatic_root','save_owner_selected_root','lock_current_root','restore_previous_root','unlock_current_root','remove_current_root') OR p_block_key<0 OR COALESCE(btrim(p_idempotency_key),'')='' THEN RAISE EXCEPTION 'ROOTING_PHRASE_AUTOMATIC_POLICY_INVALID'; END IF;
 IF p_source_text_update_binding_id IS NOT NULL AND p_action<>'save_owner_selected_root' THEN RAISE EXCEPTION 'ROOTING_PHRASE_SOURCE_COMBINATION_INVALID'; END IF;
 IF NOT ((p_action='activate_automatic_root' AND p_source_candidate_id IS NOT NULL AND p_source_evidence_span_id IS NOT NULL AND p_source_feedback_exposure_id IS NOT NULL AND p_source_owner_response_id IS NOT NULL AND p_source_practice_attempt_id IS NULL AND p_source_text_update_binding_id IS NULL AND p_source_target_speaker_binding_id IS NULL AND p_practice_target_speaker_binding_id IS NULL AND p_restore_product_action_id IS NULL) OR (p_action='save_owner_selected_root' AND p_source_candidate_id IS NOT NULL AND p_source_evidence_span_id IS NOT NULL AND ((p_source_practice_attempt_id IS NULL AND p_source_target_speaker_binding_id IS NULL AND p_practice_target_speaker_binding_id IS NULL) OR (p_source_practice_attempt_id IS NOT NULL AND p_source_text_update_binding_id IS NULL AND p_source_target_speaker_binding_id IS NOT NULL AND p_practice_target_speaker_binding_id IS NOT NULL)) AND ((p_source_feedback_exposure_id IS NULL AND p_source_owner_response_id IS NULL) OR (p_source_feedback_exposure_id IS NOT NULL AND p_source_owner_response_id IS NOT NULL)) AND p_restore_product_action_id IS NULL) OR (p_action IN('lock_current_root','unlock_current_root','remove_current_root') AND p_source_candidate_id IS NULL AND p_source_evidence_span_id IS NULL AND p_source_feedback_exposure_id IS NULL AND p_source_owner_response_id IS NULL AND p_source_practice_attempt_id IS NULL AND p_source_ideal_text_revision_id IS NULL AND p_source_text_update_binding_id IS NULL AND p_source_target_speaker_binding_id IS NULL AND p_practice_target_speaker_binding_id IS NULL AND p_restore_product_action_id IS NULL) OR (p_action='restore_previous_root' AND p_source_candidate_id IS NULL AND p_source_evidence_span_id IS NULL AND p_source_feedback_exposure_id IS NULL AND p_source_owner_response_id IS NULL AND p_source_practice_attempt_id IS NULL AND p_source_ideal_text_revision_id IS NULL AND p_source_text_update_binding_id IS NULL AND p_source_target_speaker_binding_id IS NULL AND p_practice_target_speaker_binding_id IS NULL AND p_restore_product_action_id IS NOT NULL)) THEN RAISE EXCEPTION 'ROOTING_PHRASE_SOURCE_COMBINATION_INVALID'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('root-action-v2:'||p_idempotency_key,0)); PERFORM public.lock_confident_moment_inventory_v1(p_acquisition_principal_id,p_project_id,p_take_id); PERFORM public.require_mlc3_service_access_v2(p_acquisition_principal_id,NULL,NULL); SELECT user_id INTO STRICT u FROM public.owner_principals WHERE id=p_acquisition_principal_id;
 SELECT * INTO r FROM public.root_phrase_product_actions WHERE idempotency_key=p_idempotency_key;
 IF r.id IS NOT NULL THEN
  SELECT * INTO STRICT c FROM public.root_phrase_content_versions WHERE id=r.content_version_id AND project_id=p_project_id AND acquisition_principal_id=p_acquisition_principal_id AND source_ideal_part_id=p_paragraph_id AND block_key=p_block_key;
  PERFORM public.require_synthetic_root_content_live_v1(c.id);
  IF p_source_practice_attempt_id IS NOT NULL THEN
   practice_guard:=public.require_root_phrase_practice_source_live_v1(
    p_acquisition_principal_id,c.id,p_source_practice_attempt_id,
    p_source_target_speaker_binding_id,p_practice_target_speaker_binding_id);
   practice_guard_hash:=practice_guard->>'practice_guard_sha256';
  END IF;
  SELECT * INTO STRICT h FROM public.root_phrase_block_heads WHERE project_id=p_project_id AND slide_index=c.slide_index AND block_key=p_block_key FOR UPDATE;
  mapped:=CASE WHEN p_action='remove_current_root' THEN 'root_remove' WHEN p_expected_block_head_action_id IS NULL THEN 'root_activate' ELSE 'root_replace' END;
  digest:=public.exercise_json_sha256_v1(jsonb_build_object('principal',p_acquisition_principal_id,'project',p_project_id,'take',p_take_id,'paragraph',p_paragraph_id,'block',p_block_key,'action',p_action,'head',p_expected_block_head_action_id,'content',c.id,'origin',r.activation_origin,'persistence',r.persistence_state,'qualification',r.qualification_state,'revision',r.interaction_state_revision,'candidate',p_source_candidate_id,'evidence',p_source_evidence_span_id,'exposure',p_source_feedback_exposure_id,'owner_response',p_source_owner_response_id,'practice_attempt',p_source_practice_attempt_id,'ideal_text_revision',p_source_ideal_text_revision_id,'text_update_binding',p_source_text_update_binding_id,'source_binding',p_source_target_speaker_binding_id,'practice_binding',p_practice_target_speaker_binding_id,'practice_guard',practice_guard_hash,'restore_action',p_restore_product_action_id,'policy',p_policy_version));
  IF r.action<>mapped OR r.interaction_action<>p_action OR r.supersedes_action_id IS DISTINCT FROM p_expected_block_head_action_id OR r.take_id<>p_take_id OR r.owner_user_id<>u OR r.source_candidate_id IS DISTINCT FROM p_source_candidate_id OR r.source_evidence_span_id IS DISTINCT FROM p_source_evidence_span_id OR r.source_feedback_exposure_id IS DISTINCT FROM p_source_feedback_exposure_id OR r.source_owner_response_id IS DISTINCT FROM p_source_owner_response_id OR r.source_practice_attempt_id IS DISTINCT FROM p_source_practice_attempt_id OR r.source_ideal_text_revision_id IS DISTINCT FROM p_source_ideal_text_revision_id OR r.source_text_update_binding_id IS DISTINCT FROM p_source_text_update_binding_id OR r.source_target_speaker_binding_id IS DISTINCT FROM p_source_target_speaker_binding_id OR r.practice_target_speaker_binding_id IS DISTINCT FROM p_practice_target_speaker_binding_id OR r.practice_guard_sha256 IS DISTINCT FROM practice_guard_hash OR r.restore_product_action_id IS DISTINCT FROM p_restore_product_action_id OR r.policy_version<>p_policy_version OR r.action_sha256<>digest OR (p_action='remove_current_root' AND (h.active_root_action_id IS NOT NULL OR h.interaction_state_revision<>r.interaction_state_revision)) OR (p_action<>'remove_current_root' AND (h.active_root_action_id<>r.id OR h.interaction_state_revision<>r.interaction_state_revision)) THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_REPLAY_CONFLICT'; END IF;
  PERFORM public.require_mlc3_service_access_v2(p_acquisition_principal_id,NULL,NULL); RETURN to_jsonb(r);
 END IF;
 SELECT * INTO c FROM public.root_phrase_content_versions WHERE project_id=p_project_id AND acquisition_principal_id=p_acquisition_principal_id AND source_ideal_part_id=p_paragraph_id AND block_key=p_block_key AND (p_source_candidate_id IS NULL OR feedback_candidate_id=p_source_candidate_id) ORDER BY created_at DESC,id DESC LIMIT 1; IF c.id IS NULL THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_SOURCE_NOT_LIVE'; END IF; PERFORM public.require_synthetic_root_content_live_v1(c.id);
 IF p_source_practice_attempt_id IS NOT NULL THEN
  practice_guard:=public.require_root_phrase_practice_source_live_v1(
   p_acquisition_principal_id,c.id,p_source_practice_attempt_id,
   p_source_target_speaker_binding_id,p_practice_target_speaker_binding_id);
  practice_guard_hash:=practice_guard->>'practice_guard_sha256';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('root-block:'||p_project_id::text||':'||c.slide_index::text||':'||p_block_key::text,0)); SELECT * INTO h FROM public.root_phrase_block_heads WHERE project_id=p_project_id AND slide_index=c.slide_index AND block_key=p_block_key FOR UPDATE; IF h.active_root_action_id IS DISTINCT FROM p_expected_block_head_action_id THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_STALE_REVISION'; END IF; SELECT * INTO part FROM public.ideal_text_part WHERE id=p_paragraph_id AND arc_id=p_project_id::text AND user_id=u::text FOR UPDATE; IF part.id IS NULL THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_SOURCE_NOT_LIVE'; END IF; SELECT id INTO expected_revision FROM public.ideal_text_part_revision WHERE part_id=part.id ORDER BY id DESC LIMIT 1;
 IF (p_action='restore_previous_root') IS DISTINCT FROM (p_restore_product_action_id IS NOT NULL) OR (p_action IN('lock_current_root','unlock_current_root','remove_current_root') AND h.active_root_action_id IS NULL) THEN RAISE EXCEPTION 'ROOTING_PHRASE_AUTOMATIC_POLICY_INVALID'; END IF;
 SELECT * INTO old FROM public.root_phrase_product_actions WHERE id=h.active_root_action_id;
 IF old.persistence_state='owner_locked' AND p_action IN('activate_automatic_root','save_owner_selected_root','restore_previous_root') THEN RAISE EXCEPTION 'ROOTING_PHRASE_OWNER_LOCKED'; END IF;
 IF p_source_candidate_id IS NOT NULL AND (
    c.feedback_candidate_id<>p_source_candidate_id OR NOT EXISTS(
      SELECT 1 FROM public.feedback_candidates candidate
       WHERE candidate.id=c.feedback_candidate_id
         AND candidate.evidence_span_id=p_source_evidence_span_id)) THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_SOURCE_NOT_LIVE'; END IF;
 IF (c.source_part_version_kind='existing_part_revision_v1' AND p_source_ideal_text_revision_id IS DISTINCT FROM c.source_part_revision_id) OR (c.source_part_version_kind<>'existing_part_revision_v1' AND p_source_ideal_text_revision_id IS NOT NULL) THEN RAISE EXCEPTION 'ROOTING_PHRASE_SOURCE_COMBINATION_INVALID'; END IF;
 IF p_source_text_update_binding_id IS NOT NULL AND NOT EXISTS(
  SELECT 1 FROM public.confident_moment_bundle_text_update_bindings text_binding
   WHERE text_binding.id=p_source_text_update_binding_id
     AND text_binding.acquisition_principal_id=p_acquisition_principal_id
     AND text_binding.project_id=p_project_id
     AND text_binding.target_part_id=p_paragraph_id
     AND text_binding.result_part_revision_id=p_source_ideal_text_revision_id) THEN
  RAISE EXCEPTION 'ROOTING_PHRASE_SOURCE_COMBINATION_INVALID';
 END IF;
 IF p_source_feedback_exposure_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.feedback_v3_owner_responses response_row JOIN public.feedback_v3_service_response_bindings response_binding ON response_binding.v3_owner_response_id=response_row.id WHERE response_row.id=p_source_owner_response_id AND response_row.membership_id=c.feedback_membership_id AND response_row.candidate_id=c.feedback_candidate_id AND response_binding.feedback_exposure_id=p_source_feedback_exposure_id) THEN RAISE EXCEPTION 'ROOTING_PHRASE_SOURCE_COMBINATION_INVALID'; END IF;
 IF p_action='save_owner_selected_root' AND p_source_practice_attempt_id IS NULL AND p_source_owner_response_id IS NULL AND c.text_origin<>'manual_edit' THEN RAISE EXCEPTION 'ROOTING_PHRASE_SOURCE_COMBINATION_INVALID'; END IF;
 IF p_action='activate_automatic_root' THEN IF p_source_candidate_id IS NULL OR p_source_evidence_span_id IS NULL OR p_source_feedback_exposure_id IS NULL OR p_source_owner_response_id IS NULL OR NOT EXISTS(SELECT 1 FROM public.feedback_v3_owner_responses x JOIN public.feedback_v3_service_response_bindings b ON b.v3_owner_response_id=x.id WHERE x.id=p_source_owner_response_id AND x.membership_id=c.feedback_membership_id AND x.candidate_id=c.feedback_candidate_id AND x.response='confident_yes' AND b.feedback_exposure_id=p_source_feedback_exposure_id) OR (SELECT z.result FROM public.root_phrase_semantic_results z WHERE z.content_version_id=c.id ORDER BY z.completed_at DESC,z.id DESC LIMIT 1) IS DISTINCT FROM 'aligned' OR NOT EXISTS(SELECT 1 FROM public.root_phrase_coverage_items i JOIN public.root_phrase_coverage_frames f ON f.id=i.frame_id WHERE f.take_id=p_take_id AND f.feedback_membership_id=c.feedback_membership_id AND i.anchor_candidate_id=p_source_candidate_id AND i.content_version_id=c.id AND i.coverage_item_state='eligible_automatic_proposal') THEN RAISE EXCEPTION 'ROOTING_PHRASE_AUTOMATIC_POLICY_INVALID'; END IF; origin:='automatic_product_selection'; persistence:='automatic_replaceable'; qualification:='not_qualified_reference';
 ELSIF p_action IN('save_owner_selected_root','restore_previous_root') THEN origin:='owner_selection'; persistence:='automatic_replaceable'; qualification:='not_qualified_reference';
 ELSE origin:=COALESCE(old.activation_origin,'owner_selection'); persistence:=CASE p_action WHEN 'lock_current_root' THEN 'owner_locked' WHEN 'unlock_current_root' THEN 'automatic_replaceable' ELSE COALESCE(old.persistence_state,'automatic_replaceable') END; qualification:=COALESCE(old.qualification_state,'not_qualified_reference'); END IF;
 IF p_restore_product_action_id IS NOT NULL THEN SELECT * INTO STRICT old FROM public.root_phrase_product_actions WHERE id=p_restore_product_action_id AND project_id=p_project_id AND acquisition_principal_id=p_acquisition_principal_id AND action IN('root_activate','root_replace'); SELECT * INTO STRICT c FROM public.root_phrase_content_versions WHERE id=old.content_version_id AND source_ideal_part_id=p_paragraph_id AND block_key=p_block_key; PERFORM public.require_synthetic_root_content_live_v1(c.id); END IF;
 rev:=COALESCE(h.interaction_state_revision,0)+1; mapped:=CASE WHEN p_action='remove_current_root' THEN 'root_remove' WHEN h.active_root_action_id IS NULL THEN 'root_activate' ELSE 'root_replace' END; digest:=public.exercise_json_sha256_v1(jsonb_build_object('principal',p_acquisition_principal_id,'project',p_project_id,'take',p_take_id,'paragraph',p_paragraph_id,'block',p_block_key,'action',p_action,'head',p_expected_block_head_action_id,'content',c.id,'origin',origin,'persistence',persistence,'qualification',qualification,'revision',rev,'candidate',p_source_candidate_id,'evidence',p_source_evidence_span_id,'exposure',p_source_feedback_exposure_id,'owner_response',p_source_owner_response_id,'practice_attempt',p_source_practice_attempt_id,'ideal_text_revision',p_source_ideal_text_revision_id,'text_update_binding',p_source_text_update_binding_id,'source_binding',p_source_target_speaker_binding_id,'practice_binding',p_practice_target_speaker_binding_id,'practice_guard',practice_guard_hash,'restore_action',p_restore_product_action_id,'policy',p_policy_version));
 INSERT INTO public.root_phrase_product_actions(acquisition_principal_id,project_id,content_version_id,qualification_revision_id,owner_user_id,action,supersedes_action_id,interaction_state_revision,action_sha256,idempotency_key,take_id,interaction_action,activation_origin,persistence_state,qualification_state,source_candidate_id,source_evidence_span_id,source_feedback_exposure_id,source_owner_response_id,source_practice_attempt_id,source_ideal_text_revision_id,source_text_update_binding_id,source_target_speaker_binding_id,practice_target_speaker_binding_id,practice_guard_sha256,restore_product_action_id,policy_version) VALUES(p_acquisition_principal_id,p_project_id,c.id,NULL,u,mapped,h.active_root_action_id,rev,digest,p_idempotency_key,p_take_id,p_action,origin,persistence,qualification,p_source_candidate_id,p_source_evidence_span_id,p_source_feedback_exposure_id,p_source_owner_response_id,p_source_practice_attempt_id,p_source_ideal_text_revision_id,p_source_text_update_binding_id,p_source_target_speaker_binding_id,p_practice_target_speaker_binding_id,practice_guard_hash,p_restore_product_action_id,p_policy_version) RETURNING * INTO r;
 PERFORM public.transition_ideal_text_root_state_v1(p_acquisition_principal_id,p_project_id,p_take_id,c.id,expected_revision,CASE p_action WHEN 'activate_automatic_root' THEN 'set_automatic_root' WHEN 'save_owner_selected_root' THEN 'set_owner_selected_root' WHEN 'restore_previous_root' THEN 'restore_owner_selected_root' ELSE p_action END,p_idempotency_key||':ideal-text');
 INSERT INTO public.root_phrase_block_heads(acquisition_principal_id,project_id,slide_index,block_key,active_root_action_id,interaction_state_revision) VALUES(p_acquisition_principal_id,p_project_id,c.slide_index,p_block_key,CASE WHEN p_action='remove_current_root' THEN NULL ELSE r.id END,rev) ON CONFLICT(project_id,slide_index,block_key) DO UPDATE SET active_root_action_id=EXCLUDED.active_root_action_id,interaction_state_revision=EXCLUDED.interaction_state_revision,updated_at=clock_timestamp(); PERFORM public.require_mlc3_service_access_v2(p_acquisition_principal_id,NULL,NULL); RETURN to_jsonb(r);
END $$;

-- Security closure is applied after every function declaration below.
-- deferred
-- deferred
-- Function execution closure is applied after every declaration below.
-- transaction remains open through all declarations

CREATE OR REPLACE FUNCTION public.record_feedback_language_coach_revision_v2(
 p_reviewer_principal_id uuid,p_review_batch_id uuid,p_reveal_grant_id uuid,
 p_reveal_access_id uuid,p_review_assignment_id uuid,p_blind_judgment_id uuid,
 p_feedback_membership_id uuid,p_feedback_candidate_id uuid,
 p_candidate_output_sha256 text,p_output_kind text,p_comment_purpose text,
 p_revision_text text,p_expected_current_revision_id uuid,p_idempotency_key text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE membership public.feedback_v3_memberships; current_head uuid; result jsonb;
 replay_revision public.feedback_revisions; requested_sha256 text;
BEGIN
 SELECT * INTO STRICT membership FROM public.feedback_v3_memberships
  WHERE id=p_feedback_membership_id;
 PERFORM public.lock_confident_moment_inventory_v1(
  membership.acquisition_principal_id,membership.project_id,membership.take_id);
 PERFORM public.require_mlc3_service_access_v2(
  membership.acquisition_principal_id,NULL,NULL);
 PERFORM pg_advisory_xact_lock(hashtextextended(
  'feedback-v3-membership-current:'||membership.id::text,0));
 PERFORM pg_advisory_xact_lock(hashtextextended(
  'feedback-language-candidate:'||p_feedback_candidate_id::text||':'||p_reviewer_principal_id::text,0));
 PERFORM pg_advisory_xact_lock(hashtextextended(
  'feedback-language-revision-head:'||membership.id::text||':'||p_feedback_candidate_id::text||':'||p_reviewer_principal_id::text,0));
 requested_sha256:=public.exercise_json_sha256_v1(jsonb_build_object(
  'reviewer',p_reviewer_principal_id,'batch',p_review_batch_id,
  'grant',p_reveal_grant_id,'access',p_reveal_access_id,
  'assignment',p_review_assignment_id,'judgment',p_blind_judgment_id,
  'membership',p_feedback_membership_id,'candidate',p_feedback_candidate_id,
  'output_hash',p_candidate_output_sha256,'kind',p_output_kind,
  'purpose',p_comment_purpose,'text',p_revision_text,
  'supersedes',p_expected_current_revision_id));
 SELECT * INTO replay_revision FROM public.feedback_revisions
  WHERE idempotency_key=p_idempotency_key;
 SELECT revision.id INTO current_head FROM public.feedback_revisions revision
  WHERE revision.taxonomy_version='feedback-language-coach-revision-v1'
    AND revision.feedback_membership_id=membership.id
    AND revision.feedback_candidate_id=p_feedback_candidate_id
    AND revision.rater_id=p_reviewer_principal_id
    AND NOT EXISTS(SELECT 1 FROM public.feedback_revisions successor
      WHERE successor.supersedes_id=revision.id
        AND successor.taxonomy_version='feedback-language-coach-revision-v1');
 IF replay_revision.id IS NOT NULL THEN
  IF replay_revision.taxonomy_version<>'feedback-language-coach-revision-v1'
   OR replay_revision.feedback_membership_id<>p_feedback_membership_id
   OR replay_revision.feedback_candidate_id<>p_feedback_candidate_id
   OR replay_revision.rater_id<>p_reviewer_principal_id
   OR replay_revision.supersedes_id IS DISTINCT FROM p_expected_current_revision_id
   OR replay_revision.revision_sha256<>requested_sha256 THEN
   RAISE EXCEPTION 'FEEDBACK_LANGUAGE_REPLAY_CONFLICT';
  END IF;
  IF current_head IS DISTINCT FROM replay_revision.id THEN
   RAISE EXCEPTION 'FEEDBACK_LANGUAGE_STALE_REVISION';
  END IF;
  RETURN public.record_feedback_language_coach_revision_v1(
   p_reviewer_principal_id,p_review_batch_id,p_reveal_grant_id,p_reveal_access_id,
   p_review_assignment_id,p_blind_judgment_id,p_feedback_membership_id,
   p_feedback_candidate_id,p_candidate_output_sha256,p_output_kind,
   p_comment_purpose,p_revision_text,p_expected_current_revision_id,p_idempotency_key);
 END IF;
 IF current_head IS DISTINCT FROM p_expected_current_revision_id THEN
  RAISE EXCEPTION 'FEEDBACK_LANGUAGE_STALE_REVISION'; END IF;
 result:=public.record_feedback_language_coach_revision_v1(
  p_reviewer_principal_id,p_review_batch_id,p_reveal_grant_id,p_reveal_access_id,
  p_review_assignment_id,p_blind_judgment_id,p_feedback_membership_id,
  p_feedback_candidate_id,p_candidate_output_sha256,p_output_kind,
  p_comment_purpose,p_revision_text,p_expected_current_revision_id,p_idempotency_key);
 PERFORM public.require_mlc3_service_access_v2(
  membership.acquisition_principal_id,NULL,NULL);
 RETURN result;
END $$;

CREATE OR REPLACE FUNCTION public.transition_feedback_language_delivery_v2(
 p_revision_id uuid,p_recipient_principal_id uuid,p_target_take_id uuid,
 p_anchor_candidate_id uuid,p_expected_current_delivery_id uuid,
 p_action text,p_idempotency_key text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE revision public.feedback_revisions; membership public.feedback_v3_memberships;
 attachment public.confident_moment_bundle_attachments; expected_anchor_candidate_id uuid;
 current_delivery public.feedback_language_revision_deliveries; result public.feedback_language_revision_deliveries;
 access jsonb; next_revision integer; subject_hash text; delivery_hash text;
 affected_take_id uuid;
BEGIN
 IF p_action NOT IN('schedule','invalidate') OR COALESCE(btrim(p_idempotency_key),'')='' THEN
  RAISE EXCEPTION 'FEEDBACK_LANGUAGE_DELIVERY_INVALID'; END IF;
 SELECT * INTO STRICT revision FROM public.feedback_revisions
  WHERE id=p_revision_id AND taxonomy_version='feedback-language-coach-revision-v1'
    AND acquisition_principal_id=p_recipient_principal_id;
 SELECT * INTO STRICT membership FROM public.feedback_v3_memberships
  WHERE id=revision.feedback_membership_id AND acquisition_principal_id=p_recipient_principal_id;
 SELECT * INTO STRICT attachment FROM public.confident_moment_bundle_attachments bundle_attachment
  WHERE bundle_attachment.acquisition_principal_id=p_recipient_principal_id
    AND bundle_attachment.feedback_membership_id=membership.id
    AND bundle_attachment.attached_candidate_id=revision.feedback_candidate_id;
 expected_anchor_candidate_id:=COALESCE(
  attachment.anchor_candidate_id,attachment.bundle_subject_candidate_id);
 IF p_anchor_candidate_id IS DISTINCT FROM expected_anchor_candidate_id
  OR NOT EXISTS(SELECT 1 FROM public.v2_sessions target_take
   WHERE target_take.id=p_target_take_id
     AND target_take.owner_principal_id=p_recipient_principal_id
     AND target_take.project_id=membership.project_id) THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_ANCHOR_INVALID';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-rollout-policy-v2',0));
 PERFORM pg_advisory_xact_lock(hashtextextended(
  'mlc3-service-principal:'||p_recipient_principal_id::text,0));
 PERFORM pg_advisory_xact_lock(hashtextextended(
  'confident-moment-project-inventory:'||membership.project_id::text,0));
 FOR affected_take_id IN SELECT id FROM (VALUES(membership.take_id),(p_target_take_id)) affected(id) ORDER BY id LOOP
  PERFORM pg_advisory_xact_lock(hashtextextended(
   'confident-moment-take-inventory:'||affected_take_id::text,0));
 END LOOP;
 FOR affected_take_id IN SELECT id FROM (VALUES(membership.take_id),(p_target_take_id)) affected(id) ORDER BY id LOOP
  PERFORM pg_advisory_xact_lock(hashtextextended(
   'feedback-v3-membership-inventory:'||membership.project_id::text||':'||affected_take_id::text,0));
 END LOOP;
 membership:=public.require_feedback_v3_service_membership_live_v1(
 membership.id,p_recipient_principal_id);
 SELECT * INTO STRICT attachment FROM public.confident_moment_bundle_attachments bundle_attachment
  WHERE bundle_attachment.id=attachment.id
    AND bundle_attachment.acquisition_principal_id=p_recipient_principal_id
    AND bundle_attachment.feedback_membership_id=membership.id
    AND bundle_attachment.attached_candidate_id=revision.feedback_candidate_id;
 expected_anchor_candidate_id:=COALESCE(
  attachment.anchor_candidate_id,attachment.bundle_subject_candidate_id);
 IF p_anchor_candidate_id IS DISTINCT FROM expected_anchor_candidate_id THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_RETRY_REQUIRED';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM public.v2_sessions target_take
   WHERE target_take.id=p_target_take_id
     AND target_take.owner_principal_id=p_recipient_principal_id
     AND target_take.project_id=membership.project_id) THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_RETRY_REQUIRED';
 END IF;
 access:=public.require_mlc3_service_access_v2(p_recipient_principal_id,NULL,NULL);
 PERFORM pg_advisory_xact_lock(hashtextextended(
  'feedback-language-delivery-subject:'||p_recipient_principal_id::text||':'||p_target_take_id::text||':'||membership.id::text||':'||revision.feedback_candidate_id::text,0));
 PERFORM pg_advisory_xact_lock(hashtextextended(
  'feedback-language-revision-head:'||membership.id::text||':'||revision.feedback_candidate_id::text||':'||revision.rater_id::text,0));
 SELECT delivery.* INTO current_delivery FROM public.feedback_language_revision_deliveries delivery
  WHERE delivery.delivery_policy_version='feedback-language-delivery-v2'
    AND delivery.recipient_principal_id=p_recipient_principal_id
    AND delivery.target_take_id=p_target_take_id
    AND delivery.feedback_membership_id=membership.id
    AND delivery.feedback_candidate_id=revision.feedback_candidate_id
    AND NOT EXISTS(SELECT 1 FROM public.feedback_language_revision_deliveries successor
      WHERE successor.supersedes_delivery_id=delivery.id
        AND successor.delivery_policy_version='feedback-language-delivery-v2');
 IF EXISTS(SELECT 1 FROM public.feedback_revisions successor
   WHERE successor.supersedes_id=revision.id
     AND successor.taxonomy_version='feedback-language-coach-revision-v1') THEN
  RAISE EXCEPTION 'FEEDBACK_LANGUAGE_STALE_REVISION'; END IF;
 PERFORM public.require_coach_guidance_reviewer_access_v1(revision.rater_id);
 PERFORM public.require_coach_guidance_assignment_live_v1(
  revision.review_assignment_id,p_recipient_principal_id,'coach_review');
 IF NOT EXISTS(SELECT 1 FROM public.coach_guidance_reveal_accesses access_row
   JOIN public.coach_guidance_reveal_grants grant_row
     ON grant_row.id=access_row.reveal_grant_id
    AND grant_row.review_batch_id=revision.review_batch_id
   JOIN public.ml_judgments judgment
     ON judgment.id=access_row.blind_judgment_id
    AND judgment.review_assignment_id=revision.review_assignment_id
    AND judgment.actor_principal_id=revision.rater_id
    AND judgment.actor_provenance='blind_coach'
   WHERE access_row.id=revision.reveal_access_id
     AND access_row.reveal_grant_id=revision.reveal_grant_id
     AND access_row.reviewer_principal_id=revision.rater_id
     AND access_row.review_assignment_id=revision.review_assignment_id
     AND access_row.blind_judgment_id=revision.blind_judgment_id) THEN
  RAISE EXCEPTION 'FEEDBACK_LANGUAGE_REVEAL_REQUIRED';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('feedback-language-delivery:'||p_idempotency_key,0));
 SELECT * INTO result FROM public.feedback_language_revision_deliveries WHERE idempotency_key=p_idempotency_key;
 subject_hash:=public.exercise_json_sha256_v1(jsonb_build_object('recipient',p_recipient_principal_id,'take',p_target_take_id,'membership',membership.id,'candidate',revision.feedback_candidate_id,'reviewer',revision.rater_id,'output_hash',revision.candidate_output_sha256));
 IF result.id IS NOT NULL THEN next_revision:=result.delivery_revision;
 ELSE next_revision:=COALESCE(current_delivery.delivery_revision,0)+1; END IF;
 delivery_hash:=public.exercise_json_sha256_v1(jsonb_build_object('revision',revision.id,'subject',subject_hash,'anchor',expected_anchor_candidate_id,'predecessor',p_expected_current_delivery_id,'action',p_action,'delivery_revision',next_revision));
 IF result.id IS NOT NULL THEN
  IF result.revision_id<>p_revision_id
   OR result.recipient_principal_id<>p_recipient_principal_id
   OR result.target_take_id<>p_target_take_id
   OR result.anchor_candidate_id<>expected_anchor_candidate_id
   OR result.supersedes_delivery_id IS DISTINCT FROM p_expected_current_delivery_id
   OR result.delivery_state<>(CASE p_action WHEN 'schedule' THEN 'scheduled_next_take' ELSE 'invalidated' END)
   OR result.delivery_subject_sha256<>subject_hash
   OR result.delivery_sha256<>delivery_hash THEN
   RAISE EXCEPTION 'FEEDBACK_LANGUAGE_REPLAY_CONFLICT';
  END IF;
  IF current_delivery.id IS DISTINCT FROM result.id THEN
   RAISE EXCEPTION 'FEEDBACK_LANGUAGE_DELIVERY_STALE';
  END IF;
  access:=public.require_mlc3_service_access_v2(p_recipient_principal_id,
   result.authorization_rollout_revision_id,result.authorization_enrollment_revision_id);
  RETURN to_jsonb(result);
 END IF;
 IF current_delivery.id IS DISTINCT FROM p_expected_current_delivery_id THEN
  RAISE EXCEPTION 'FEEDBACK_LANGUAGE_DELIVERY_STALE'; END IF;
 -- The rollout/principal serializers above remain held.  Refresh authority at
 -- the final pre-write boundary; a writer cannot cross this insert.
 access:=public.require_mlc3_service_access_v2(p_recipient_principal_id,
  (access->>'rollout_revision_id')::uuid,(access->>'enrollment_revision_id')::uuid);
 INSERT INTO public.feedback_language_revision_deliveries(revision_id,acquisition_principal_id,recipient_principal_id,target_take_id,anchor_candidate_id,delivery_state,delivery_revision,authorization_rollout_revision_id,authorization_enrollment_revision_id,delivery_sha256,idempotency_key,feedback_membership_id,feedback_candidate_id,reviewer_principal_id,revision_taxonomy_version,candidate_output_version,candidate_output_sha256,delivery_subject_sha256,supersedes_delivery_id,delivery_policy_version)
 VALUES(revision.id,p_recipient_principal_id,p_recipient_principal_id,p_target_take_id,expected_anchor_candidate_id,CASE p_action WHEN 'schedule' THEN 'scheduled_next_take' ELSE 'invalidated' END,next_revision,(access->>'rollout_revision_id')::uuid,(access->>'enrollment_revision_id')::uuid,delivery_hash,p_idempotency_key,membership.id,revision.feedback_candidate_id,revision.rater_id,revision.taxonomy_version,revision.candidate_output_version,revision.candidate_output_sha256,subject_hash,p_expected_current_delivery_id,'feedback-language-delivery-v2') RETURNING * INTO result;
 RETURN to_jsonb(result);
END $$;

CREATE OR REPLACE FUNCTION public.ack_confident_moment_bundle_item_render_v3(p_acquisition_principal_id uuid,p_bundle_id uuid,p_bundle_attachment_id uuid,p_feedback_exposure_id uuid,p_render_instance_id uuid,p_idempotency_key text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE a public.confident_moment_bundle_attachments; m public.feedback_v3_memberships; u uuid; r public.feedback_v3_service_render_receipts;
BEGIN
 SELECT * INTO STRICT a FROM public.confident_moment_bundle_attachments WHERE id=p_bundle_attachment_id AND acquisition_principal_id=p_acquisition_principal_id AND bundle_subject_candidate_id=p_bundle_id; PERFORM public.lock_confident_moment_inventory_v1(p_acquisition_principal_id,a.project_id,a.take_id); PERFORM public.require_mlc3_service_access_v2(p_acquisition_principal_id,NULL,NULL); PERFORM pg_advisory_xact_lock(hashtextextended('feedback-v3-membership-current:'||a.feedback_membership_id::text,0)); PERFORM pg_advisory_xact_lock(hashtextextended('confident-moment-bundle-subject:'||a.feedback_membership_id::text||':'||a.bundle_subject_candidate_id::text,0));
 -- D11 global order: the shared natural/inventory serializers above always
 -- precede this operation-local idempotency serializer.  This keeps exact
 -- replay serialization from inverting the lock graph used by projection and
 -- every inventory writer.
 PERFORM pg_advisory_xact_lock(hashtextextended('confident-moment-render:'||p_idempotency_key,0));
 m:=public.require_feedback_v3_service_membership_live_v1(a.feedback_membership_id,p_acquisition_principal_id);
 IF m.project_id<>a.project_id OR m.take_id<>a.take_id
  OR m.document_snapshot_id<>a.document_snapshot_id
  OR NOT EXISTS(SELECT 1 FROM public.feedback_v3_membership_items item
    WHERE item.membership_id=m.id AND item.candidate_id=a.attached_candidate_id
      AND item.evidence_span_id=a.attached_evidence_span_id AND item.selected
      AND item.eligibility='eligible')
  OR NOT EXISTS(SELECT 1 FROM public.feedback_v3_membership_items subject
    WHERE subject.membership_id=m.id AND subject.candidate_id=a.bundle_subject_candidate_id
      AND subject.evidence_span_id=a.bundle_subject_evidence_span_id AND subject.selected
      AND subject.eligibility='eligible') THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_ATTACHMENT_INVALID'; END IF;
 IF a.canonical_feedback_presentation_id<>p_feedback_exposure_id THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_ATTACHMENT_INVALID'; END IF; SELECT user_id INTO STRICT u FROM public.owner_principals WHERE id=p_acquisition_principal_id;
 SELECT * INTO r FROM public.feedback_v3_service_render_receipts receipt
  WHERE receipt.idempotency_key=p_idempotency_key;
 IF r.id IS NOT NULL THEN
  IF r.acquisition_principal_id<>p_acquisition_principal_id
   OR r.owner_user_id<>u OR r.membership_id<>a.feedback_membership_id
   OR r.candidate_id<>a.attached_candidate_id
   OR r.feedback_exposure_id<>a.canonical_feedback_presentation_id
   OR r.render_instance_id<>p_render_instance_id
   OR r.content_identity_sha256<>(SELECT content_identity_sha256 FROM public.feedback_v3_memberships WHERE id=a.feedback_membership_id)
   OR r.client_version<>'confident-moment-coaching-bundle-v1' THEN
   RAISE EXCEPTION 'CONFIDENT_MOMENT_REPLAY_CONFLICT'; END IF;
  IF NOT EXISTS(SELECT 1 FROM public.feedback_exposures exposure
   WHERE exposure.id=r.feedback_exposure_id AND exposure.shown_at IS NOT NULL) THEN
   RAISE EXCEPTION 'CONFIDENT_MOMENT_ATTACHMENT_INVALID'; END IF;
  m:=public.require_feedback_v3_service_membership_live_v1(a.feedback_membership_id,p_acquisition_principal_id);
  IF m.document_snapshot_id<>a.document_snapshot_id
   OR m.project_id<>a.project_id OR m.take_id<>a.take_id THEN
   RAISE EXCEPTION 'CONFIDENT_MOMENT_ATTACHMENT_INVALID'; END IF;
  IF r.id=r.feedback_exposure_id THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_ATTACHMENT_INVALID'; END IF;
  RETURN jsonb_build_object('render_contract_version','confident-moment-bundle-item-render-v3','bundle_id',p_bundle_id,'bundle_attachment_id',a.id,'feedback_exposure_id',r.feedback_exposure_id,'render_instance_id',r.render_instance_id,'render_receipt_id',r.id,'dataset_eligible',false);
 END IF;
 SELECT * INTO r FROM public.ack_feedback_v3_service_render_v1(p_acquisition_principal_id,u,a.feedback_membership_id,a.attached_candidate_id,a.canonical_feedback_presentation_id,p_render_instance_id,(SELECT content_identity_sha256 FROM public.feedback_v3_memberships WHERE id=a.feedback_membership_id),clock_timestamp(),'confident-moment-coaching-bundle-v1',p_idempotency_key);
 IF a.bundle_subject_candidate_id IS DISTINCT FROM p_bundle_id THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_ATTACHMENT_INVALID'; END IF;
 PERFORM public.require_mlc3_service_access_v2(p_acquisition_principal_id,NULL,NULL);
 m:=public.require_feedback_v3_service_membership_live_v1(a.feedback_membership_id,p_acquisition_principal_id);
 IF m.document_snapshot_id<>a.document_snapshot_id
  OR m.project_id<>a.project_id OR m.take_id<>a.take_id THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_ATTACHMENT_INVALID'; END IF;
 IF r.id=r.feedback_exposure_id THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_ATTACHMENT_INVALID'; END IF;
 RETURN jsonb_build_object('render_contract_version','confident-moment-bundle-item-render-v3','bundle_id',p_bundle_id,'bundle_attachment_id',a.id,'feedback_exposure_id',r.feedback_exposure_id,'render_instance_id',r.render_instance_id,'render_receipt_id',r.id,'dataset_eligible',false);
END $$;
DROP FUNCTION IF EXISTS public.ack_confident_moment_bundle_item_render_v1(uuid,uuid,uuid,uuid,text);
DROP FUNCTION IF EXISTS public.ack_confident_moment_bundle_item_render_v2(uuid,uuid,uuid,uuid,uuid,text);

CREATE OR REPLACE FUNCTION public.freeze_root_phrase_coverage_frame_v1(p_acquisition_principal_id uuid,p_project_id uuid,p_take_id uuid,p_feedback_membership_id uuid,p_document_snapshot_id uuid,p_policy_version text,p_idempotency_key text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE m public.feedback_v3_memberships; s public.ideal_text_document_snapshots; f public.root_phrase_coverage_frames; n integer; target integer; achieved integer; inventory text; digest text; x record; pos integer:=0; state text;
BEGIN
 IF p_policy_version<>'rooting-coverage-30-80-100-v1' OR COALESCE(btrim(p_idempotency_key),'')='' THEN RAISE EXCEPTION 'ROOTING_COVERAGE_INVENTORY_INVALID'; END IF; PERFORM pg_advisory_xact_lock(hashtextextended('root-coverage:'||p_idempotency_key,0)); PERFORM public.lock_confident_moment_inventory_v1(p_acquisition_principal_id,p_project_id,p_take_id); PERFORM pg_advisory_xact_lock(hashtextextended('root-coverage-frame:'||p_take_id::text||':'||p_feedback_membership_id::text||':'||p_document_snapshot_id::text,0)); PERFORM public.require_mlc3_service_access_v2(p_acquisition_principal_id,NULL,NULL);
 m:=public.require_feedback_v3_service_membership_live_v1(p_feedback_membership_id,p_acquisition_principal_id); IF m.project_id<>p_project_id OR m.take_id<>p_take_id OR m.document_snapshot_id<>p_document_snapshot_id THEN RAISE EXCEPTION 'ROOTING_COVERAGE_INVENTORY_INVALID'; END IF;
 SELECT * INTO STRICT s FROM public.ideal_text_document_snapshots WHERE id=p_document_snapshot_id; SELECT count(DISTINCT(piece->>'slide_index')::integer) INTO n FROM jsonb_array_elements(COALESCE(s.payload->'pieces','[]'::jsonb)) piece; IF n<1 THEN RAISE EXCEPTION 'ROOTING_COVERAGE_INVENTORY_INVALID'; END IF;
 target:=CASE m.take_index WHEN 1 THEN GREATEST(1,ceil(n*.30)::integer) WHEN 2 THEN GREATEST(1,ceil(n*.80)::integer) ELSE n END; SELECT count(DISTINCT head.slide_index) INTO achieved FROM public.root_phrase_block_heads head JOIN public.root_phrase_product_actions action_row ON action_row.id=head.active_root_action_id JOIN public.root_phrase_content_versions content_row ON content_row.id=action_row.content_version_id WHERE head.project_id=p_project_id AND head.acquisition_principal_id=p_acquisition_principal_id AND content_row.document_snapshot_id=p_document_snapshot_id;
 SELECT public.exercise_json_sha256_v1(COALESCE(jsonb_agg(jsonb_build_object('candidate',i.candidate_id,'slide',i.slide_index,'block',i.block_key,'selected',i.selected,'response',r.response) ORDER BY i.slide_index,i.block_key,i.position_shown,i.candidate_id),'[]'::jsonb)) INTO inventory FROM public.feedback_v3_membership_items i LEFT JOIN public.feedback_v3_owner_responses r ON r.membership_id=i.membership_id AND r.candidate_id=i.candidate_id WHERE i.membership_id=m.id;
 digest:=public.exercise_json_sha256_v1(jsonb_build_object('principal',p_acquisition_principal_id,'project',p_project_id,'take',p_take_id,'membership',m.id,'snapshot',s.id,'ordinal',m.take_index,'slides',n,'target',target,'achieved',achieved,'inventory',inventory,'policy',p_policy_version));
 SELECT * INTO f FROM public.root_phrase_coverage_frames WHERE idempotency_key=p_idempotency_key; IF f.id IS NOT NULL THEN IF f.frame_sha256<>digest THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_REPLAY_CONFLICT'; END IF; RETURN to_jsonb(f); END IF;
 INSERT INTO public.root_phrase_coverage_frames(acquisition_principal_id,project_id,take_id,feedback_membership_id,document_snapshot_id,take_ordinal,slide_denominator,target_slide_count,achieved_slide_count,policy_version,clause_policy_version,routing_policy_version,inventory_sha256,frame_sha256,idempotency_key) VALUES(p_acquisition_principal_id,p_project_id,p_take_id,m.id,s.id,m.take_index,n,target,achieved,p_policy_version,'root-exact-clause-v1','root-lexicographic-routing-v1',inventory,digest,p_idempotency_key) RETURNING * INTO f;
 FOR x IN SELECT i.*,r.response,c.id content_id,h.active_root_action_id,a.activation_origin,a.persistence_state,(SELECT z.result FROM public.root_phrase_semantic_results z WHERE z.content_version_id=c.id ORDER BY z.completed_at DESC,z.id DESC LIMIT 1) semantic_result FROM public.feedback_v3_membership_items i LEFT JOIN public.feedback_v3_owner_responses r ON r.membership_id=i.membership_id AND r.candidate_id=i.candidate_id LEFT JOIN LATERAL (SELECT cv.id FROM public.root_phrase_content_versions cv WHERE cv.feedback_membership_id=i.membership_id AND cv.feedback_candidate_id=i.candidate_id ORDER BY cv.created_at DESC,cv.id DESC LIMIT 1) c ON true LEFT JOIN public.root_phrase_block_heads h ON h.project_id=p_project_id AND h.slide_index=i.slide_index AND h.block_key=i.block_key LEFT JOIN public.root_phrase_product_actions a ON a.id=h.active_root_action_id WHERE i.membership_id=m.id AND i.feedback_family='confident_voice' AND i.selected ORDER BY CASE WHEN i.slide_index=0 THEN 0 ELSE 1 END,i.slide_index,i.block_key,i.position_shown,i.candidate_id LOOP
  pos:=pos+1; state:=CASE WHEN x.active_root_action_id IS NOT NULL AND x.persistence_state='owner_locked' THEN 'covered_existing_owner_lock' WHEN x.active_root_action_id IS NOT NULL AND x.activation_origin='automatic_product_selection' THEN 'covered_automatic_root' WHEN x.active_root_action_id IS NOT NULL THEN 'covered_owner_selected' WHEN x.response='confident_yes' AND x.semantic_result='aligned' THEN 'eligible_automatic_proposal' WHEN x.response='confident_in_between' THEN 'eligible_owner_proposal' WHEN x.content_id IS NULL THEN 'excluded_unusable_source' ELSE 'uncovered_no_aligned_clause' END;
  INSERT INTO public.root_phrase_coverage_items(frame_id,acquisition_principal_id,slide_index,block_key,anchor_candidate_id,anchor_evidence_span_id,content_version_id,root_action_id,coverage_item_state,exclusion_reason,canonical_position,item_sha256) VALUES(f.id,p_acquisition_principal_id,x.slide_index,x.block_key,x.candidate_id,x.evidence_span_id,x.content_id,x.active_root_action_id,state,CASE WHEN state LIKE 'uncovered%' OR state LIKE 'excluded%' THEN state END,pos,public.exercise_json_sha256_v1(jsonb_build_object('frame',f.id,'candidate',x.candidate_id,'state',state,'position',pos)));
 END LOOP; PERFORM public.require_mlc3_service_access_v2(p_acquisition_principal_id,NULL,NULL); RETURN to_jsonb(f);
END $$;

-- D14-D25 transport, authoring, owner-edit and blind-authorability closure.
-- These objects remain product-only and unreachable unless the independently
-- controlled application gates are enabled.

ALTER TABLE public.evidence_spans
 ADD COLUMN IF NOT EXISTS ideal_text_target_locator_v1 jsonb NULL,
 ADD COLUMN IF NOT EXISTS ideal_text_target_snapshot_id uuid NULL
  REFERENCES public.ideal_text_document_snapshots(id) ON DELETE RESTRICT,
 ADD COLUMN IF NOT EXISTS ideal_text_target_locator_sha256 text NULL;
DO $cm_locator_shape$ BEGIN
 ALTER TABLE public.evidence_spans DROP CONSTRAINT IF EXISTS evidence_span_ideal_text_locator_v1_shape;
 ALTER TABLE public.evidence_spans ADD CONSTRAINT evidence_span_ideal_text_locator_v1_shape CHECK (
  (ideal_text_target_locator_v1 IS NULL AND ideal_text_target_snapshot_id IS NULL
   AND ideal_text_target_locator_sha256 IS NULL)
  OR
  (ideal_text_target_locator_v1 IS NOT NULL AND ideal_text_target_snapshot_id IS NOT NULL
   AND ideal_text_target_locator_sha256 ~ '^[0-9a-f]{64}$'
   AND jsonb_typeof(ideal_text_target_locator_v1)='object'
   AND ideal_text_target_locator_v1->>'version'='ideal-text-target-locator-v1'
   AND ideal_text_target_locator_v1->>'surface'='ideal_text'
   AND ideal_text_target_locator_v1 <@ jsonb_build_object(
    'version',ideal_text_target_locator_v1->'version',
    'surface',ideal_text_target_locator_v1->'surface',
    'surface_hash',ideal_text_target_locator_v1->'surface_hash',
    'start',ideal_text_target_locator_v1->'start',
    'end',ideal_text_target_locator_v1->'end',
    'exact_text',ideal_text_target_locator_v1->'exact_text')
   AND (ideal_text_target_locator_v1->>'surface_hash') ~ '^[0-9a-f]{64}$'
   AND jsonb_typeof(ideal_text_target_locator_v1->'start')='number'
   AND jsonb_typeof(ideal_text_target_locator_v1->'end')='number'
   AND (ideal_text_target_locator_v1->>'start')::numeric=trunc((ideal_text_target_locator_v1->>'start')::numeric)
   AND (ideal_text_target_locator_v1->>'end')::numeric=trunc((ideal_text_target_locator_v1->>'end')::numeric)
   AND (ideal_text_target_locator_v1->>'start')::numeric>=0
   AND (ideal_text_target_locator_v1->>'end')::numeric>(ideal_text_target_locator_v1->>'start')::numeric
   AND jsonb_typeof(ideal_text_target_locator_v1->'exact_text')='string')
 );
END $cm_locator_shape$;

ALTER TABLE public.user_arc_ideal_notes
 ADD COLUMN IF NOT EXISTS user_text text NULL,
 ADD COLUMN IF NOT EXISTS user_text_version integer NULL,
 ADD COLUMN IF NOT EXISTS user_text_revision bigint NULL;
DO $cm_owner_lane_shape$ BEGIN
 UPDATE public.user_arc_ideal_notes SET user_text_revision=1
  WHERE user_text IS NOT NULL AND user_text_version>0 AND user_text_revision IS NULL;
 ALTER TABLE public.user_arc_ideal_notes DROP CONSTRAINT IF EXISTS user_arc_ideal_notes_owner_lane_shape;
 ALTER TABLE public.user_arc_ideal_notes ADD CONSTRAINT user_arc_ideal_notes_owner_lane_shape CHECK (
  (user_text IS NULL AND user_text_version IS NULL AND user_text_revision IS NULL)
  OR (user_text IS NOT NULL AND length(user_text)>0 AND user_text_version>0 AND user_text_revision>0)
 );
 IF EXISTS(SELECT 1 FROM public.user_arc_ideal_notes
   WHERE (user_text IS NULL)<>(user_text_version IS NULL)) THEN
  RAISE EXCEPTION 'IDEAL_TEXT_OWNER_LANE_INVALID';
 END IF;
END $cm_owner_lane_shape$;

CREATE TABLE IF NOT EXISTS public.ideal_text_user_edit_cas_operations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_user_id uuid NOT NULL,
 acquisition_principal_id uuid NOT NULL REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
 project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE RESTRICT,
 arc_id text NOT NULL, source_document_version integer NOT NULL CHECK(source_document_version>0),
 operation_kind text NOT NULL CHECK(operation_kind IN('ordinary_owner_edit','bundle_text_update','legacy_owner_edit')),
 operation_key_sha256 text NOT NULL UNIQUE CHECK(operation_key_sha256 ~ '^[0-9a-f]{64}$'),
 previous_user_text_revision bigint NULL, result_user_text_revision bigint NOT NULL CHECK(result_user_text_revision>0),
 previous_user_text_sha256 text NULL, result_user_text_sha256 text NOT NULL CHECK(result_user_text_sha256 ~ '^[0-9a-f]{64}$'),
 desired_parts_lineage_sha256 text NOT NULL CHECK(desired_parts_lineage_sha256 ~ '^[0-9a-f]{64}$'),
 result_payload jsonb NOT NULL CHECK(jsonb_typeof(result_payload)='object'),
 idempotency_key text NOT NULL UNIQUE CHECK(length(btrim(idempotency_key))>0),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 serves_user boolean NOT NULL DEFAULT false CHECK(NOT serves_user),
 dataset_eligible boolean NOT NULL DEFAULT false CHECK(NOT dataset_eligible),
 UNIQUE(id,owner_user_id,arc_id)
);

ALTER TABLE public.ideal_text_part_revision
 ADD COLUMN IF NOT EXISTS previous_revision_id bigint NULL REFERENCES public.ideal_text_part_revision(id) ON DELETE RESTRICT,
 ADD COLUMN IF NOT EXISTS owner_edit_revision bigint NULL,
 ADD COLUMN IF NOT EXISTS previous_position integer NULL,
 ADD COLUMN IF NOT EXISTS result_position integer NULL,
 ADD COLUMN IF NOT EXISTS owner_edit_operation_id uuid NULL REFERENCES public.ideal_text_user_edit_cas_operations(id) ON DELETE RESTRICT,
 ADD COLUMN IF NOT EXISTS revision_contract_version text NULL;
DO $cm_part_action_shape$ BEGIN
 ALTER TABLE public.ideal_text_part_revision DROP CONSTRAINT IF EXISTS ideal_text_part_revision_action_check;
 ALTER TABLE public.ideal_text_part_revision ADD CONSTRAINT ideal_text_part_revision_action_check CHECK(action IN(
  'user_edit','lock','unlock','keep_evolving','root_set','root_skipped',
  'owner_part_created','owner_part_text_updated','owner_part_reordered',
  'owner_part_text_updated_and_reordered','owner_part_removed'));
 ALTER TABLE public.ideal_text_part_revision DROP CONSTRAINT IF EXISTS ideal_text_part_revision_v2_shape;
 ALTER TABLE public.ideal_text_part_revision ADD CONSTRAINT ideal_text_part_revision_v2_shape CHECK(
  action NOT IN('owner_part_created','owner_part_text_updated','owner_part_reordered','owner_part_text_updated_and_reordered','owner_part_removed')
  OR (revision_contract_version='ideal-text-part-revision-v2'
      AND owner_edit_revision>0 AND owner_edit_operation_id IS NOT NULL
      AND CASE action
       WHEN 'owner_part_created' THEN previous_position IS NULL AND result_position>=0
       WHEN 'owner_part_removed' THEN previous_position>=0 AND result_position IS NULL
       WHEN 'owner_part_text_updated' THEN previous_position>=0 AND result_position=previous_position
       WHEN 'owner_part_reordered' THEN previous_position>=0 AND result_position>=0 AND result_position<>previous_position
       WHEN 'owner_part_text_updated_and_reordered' THEN previous_position>=0 AND result_position>=0 AND result_position<>previous_position
       ELSE false
      END));
END $cm_part_action_shape$;

CREATE TABLE IF NOT EXISTS public.confident_moment_bundle_text_update_bindings (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), acquisition_principal_id uuid NOT NULL REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
 project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE RESTRICT, source_take_id uuid NOT NULL REFERENCES public.v2_sessions(id) ON DELETE RESTRICT,
 bundle_id uuid NOT NULL, bundle_attachment_id uuid NOT NULL REFERENCES public.confident_moment_bundle_attachments(id) ON DELETE RESTRICT,
 feedback_membership_id uuid NOT NULL REFERENCES public.feedback_v3_memberships(id) ON DELETE RESTRICT,
 feedback_candidate_id uuid NOT NULL REFERENCES public.feedback_candidates(id) ON DELETE RESTRICT,
 correction_decision_id uuid NOT NULL REFERENCES public.correction_decisions(id) ON DELETE RESTRICT,
 feedback_exposure_id uuid NOT NULL REFERENCES public.feedback_exposures(id) ON DELETE RESTRICT,
 render_receipt_id uuid NOT NULL REFERENCES public.feedback_v3_service_render_receipts(id) ON DELETE RESTRICT,
 source_document_snapshot_id uuid NOT NULL REFERENCES public.ideal_text_document_snapshots(id) ON DELETE RESTRICT,
 result_document_snapshot_id uuid NOT NULL REFERENCES public.ideal_text_document_snapshots(id) ON DELETE RESTRICT,
 source_document_version integer NOT NULL CHECK(source_document_version>0), target_part_id uuid NOT NULL,
 result_part_revision_id bigint NOT NULL REFERENCES public.ideal_text_part_revision(id) ON DELETE RESTRICT,
 owner_edit_operation_id uuid NOT NULL REFERENCES public.ideal_text_user_edit_cas_operations(id) ON DELETE RESTRICT,
 previous_user_text_revision bigint NULL, result_user_text_revision bigint NOT NULL CHECK(result_user_text_revision>0),
 previous_user_text_sha256 text NULL, result_user_text_sha256 text NOT NULL CHECK(result_user_text_sha256 ~ '^[0-9a-f]{64}$'),
 before_part_inventory_sha256 text NOT NULL CHECK(before_part_inventory_sha256 ~ '^[0-9a-f]{64}$'),
 after_part_inventory_sha256 text NOT NULL CHECK(after_part_inventory_sha256 ~ '^[0-9a-f]{64}$'),
 locator_sha256 text NOT NULL CHECK(locator_sha256 ~ '^[0-9a-f]{64}$'), binding_sha256 text NOT NULL CHECK(binding_sha256 ~ '^[0-9a-f]{64}$'),
 idempotency_key text NOT NULL UNIQUE, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 serves_user boolean NOT NULL DEFAULT false CHECK(NOT serves_user), dataset_eligible boolean NOT NULL DEFAULT false CHECK(NOT dataset_eligible),
 CHECK(source_document_snapshot_id=result_document_snapshot_id), UNIQUE(id,bundle_attachment_id,result_part_revision_id)
);
ALTER TABLE public.root_phrase_product_actions
 ADD COLUMN IF NOT EXISTS source_text_update_binding_id uuid NULL
 REFERENCES public.confident_moment_bundle_text_update_bindings(id) ON DELETE RESTRICT;

CREATE TABLE IF NOT EXISTS public.confident_moment_text_update_capabilities (
 capability_id uuid PRIMARY KEY, transaction_id bigint NOT NULL, backend_pid integer NOT NULL,
 operation_name text NOT NULL CHECK(operation_name IN('apply_confident_moment_bundle_text_update_v1','compare_and_set_user_ideal_edit_v1')),
 acquisition_principal_id uuid NOT NULL, owner_user_id uuid NOT NULL, project_id uuid NOT NULL,
 arc_id text NOT NULL, bundle_id uuid NULL, bundle_attachment_id uuid NULL, target_part_id uuid NULL,
 notes_mutation_kind text NOT NULL CHECK(notes_mutation_kind IN('insert','update')),
 expected_notes_row_present boolean NOT NULL, expected_user_text_sha256 text NULL,
 result_user_text_sha256 text NOT NULL, expected_user_text_version integer NULL, result_user_text_version integer NOT NULL,
 expected_user_text_revision bigint NULL, result_user_text_revision bigint NOT NULL,
 expected_part_text_sha256 text NULL, result_part_text_sha256 text NULL,
 desired_parts_lineage_sha256 text NOT NULL, notes_guard_consumed boolean NOT NULL DEFAULT false,
 notes_trigger_consumed boolean NOT NULL DEFAULT false, part_trigger_consumed boolean NOT NULL DEFAULT false,
 capability_sha256 text NOT NULL CHECK(capability_sha256 ~ '^[0-9a-f]{64}$'), created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE OR REPLACE FUNCTION public.exercise_text_sha256_v1(p_text text)
RETURNS text LANGUAGE sql IMMUTABLE STRICT SET search_path=public,extensions AS $$
 SELECT encode(extensions.digest(convert_to(p_text,'UTF8'),'sha256'),'hex')
$$;

CREATE OR REPLACE FUNCTION public.guard_user_ideal_edit_cas_v1()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE capability uuid;
BEGIN
 IF TG_OP='INSERT' AND NEW.user_text IS NULL AND NEW.user_text_version IS NULL
   AND NEW.user_text_revision IS NULL THEN RETURN NEW; END IF;
 IF TG_OP='UPDATE' AND NEW.user_text IS NOT DISTINCT FROM OLD.user_text
   AND NEW.user_text_version IS NOT DISTINCT FROM OLD.user_text_version
   AND NEW.user_text_revision IS NOT DISTINCT FROM OLD.user_text_revision THEN
  RETURN NEW;
 END IF;
 SELECT capability_id INTO capability FROM public.confident_moment_text_update_capabilities
  WHERE transaction_id=txid_current() AND backend_pid=pg_backend_pid()
    AND owner_user_id=NEW.user_id AND arc_id=NEW.arc_id AND NOT notes_guard_consumed
    AND result_user_text_sha256=public.exercise_text_sha256_v1(NEW.user_text)
    AND result_user_text_version=NEW.user_text_version
    AND result_user_text_revision=NEW.user_text_revision
    AND ((TG_OP='INSERT' AND notes_mutation_kind='insert' AND NOT expected_notes_row_present)
      OR (TG_OP='UPDATE' AND notes_mutation_kind='update' AND expected_notes_row_present
       AND expected_user_text_revision IS NOT DISTINCT FROM OLD.user_text_revision
       AND expected_user_text_sha256 IS NOT DISTINCT FROM
         CASE WHEN OLD.user_text IS NULL THEN NULL ELSE public.exercise_text_sha256_v1(OLD.user_text) END))
  FOR UPDATE;
 IF capability IS NULL THEN RAISE EXCEPTION 'IDEAL_TEXT_OWNER_LANE_RPC_REQUIRED'; END IF;
 UPDATE public.confident_moment_text_update_capabilities SET notes_guard_consumed=true WHERE capability_id=capability;
 RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS user_arc_ideal_notes_user_text_cas_guard ON public.user_arc_ideal_notes;
CREATE TRIGGER user_arc_ideal_notes_user_text_cas_guard
BEFORE INSERT OR UPDATE ON public.user_arc_ideal_notes
FOR EACH ROW EXECUTE FUNCTION public.guard_user_ideal_edit_cas_v1();

-- D19: the normal generation trigger remains authoritative.  The sole Bundle
-- dual-storage writer can suppress exactly its two internally authorised row
-- changes; any mismatch falls through to the released generation behaviour
-- and later makes the wrapper roll back for incomplete capability use.
CREATE OR REPLACE FUNCTION public.advance_ideal_text_document_generation_v1()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE changed_arc text; cap uuid;
BEGIN
 IF TG_TABLE_NAME='ideal_text_part' AND TG_OP='UPDATE' THEN
  -- Root activation/lock state is presentation provenance, not a semantic
  -- document text/order mutation.  Keeping the released generation stable
  -- lets the exact source snapshot remain live for immutable action replay.
  IF NEW.text IS NOT DISTINCT FROM OLD.text
     AND NEW.ord IS NOT DISTINCT FROM OLD.ord THEN
   RETURN NEW;
  END IF;
  SELECT capability_id INTO cap FROM public.confident_moment_text_update_capabilities
   WHERE transaction_id=txid_current() AND backend_pid=pg_backend_pid()
     AND operation_name='apply_confident_moment_bundle_text_update_v1'
     AND target_part_id=NEW.id AND arc_id=NEW.arc_id AND NOT part_trigger_consumed
     AND expected_part_text_sha256=public.exercise_text_sha256_v1(OLD.text)
     AND result_part_text_sha256=public.exercise_text_sha256_v1(NEW.text)
   FOR UPDATE;
  IF cap IS NOT NULL THEN
   UPDATE public.confident_moment_text_update_capabilities SET part_trigger_consumed=true WHERE capability_id=cap;
   RETURN NEW;
  END IF;
 END IF;
 IF TG_TABLE_NAME='user_arc_ideal_notes' AND TG_OP IN('INSERT','UPDATE') THEN
  SELECT capability_id INTO cap FROM public.confident_moment_text_update_capabilities
   WHERE transaction_id=txid_current() AND backend_pid=pg_backend_pid()
     AND operation_name='apply_confident_moment_bundle_text_update_v1'
     AND owner_user_id=NEW.user_id AND arc_id=NEW.arc_id AND NOT notes_trigger_consumed
     AND result_user_text_sha256=public.exercise_text_sha256_v1(NEW.user_text)
     AND ((TG_OP='INSERT' AND notes_mutation_kind='insert' AND NOT expected_notes_row_present)
       OR (TG_OP='UPDATE' AND notes_mutation_kind='update' AND expected_notes_row_present
        AND expected_user_text_sha256 IS NOT DISTINCT FROM
          CASE WHEN OLD.user_text IS NULL THEN NULL ELSE public.exercise_text_sha256_v1(OLD.user_text) END))
   FOR UPDATE;
  IF cap IS NOT NULL THEN
   UPDATE public.confident_moment_text_update_capabilities SET notes_trigger_consumed=true WHERE capability_id=cap;
   RETURN NEW;
  END IF;
 END IF;
 IF TG_TABLE_NAME='v2_sessions' THEN
  IF TG_OP='INSERT' THEN
   IF NEW.analysis_state IS DISTINCT FROM 'ready' OR COALESCE(NEW.recording_kind,'spoken')<>'spoken'
      OR NEW.paired_session_id IS NOT NULL OR NULLIF(trim(NEW.arc_id::text),'') IS NULL THEN RETURN NEW; END IF;
  ELSIF TG_OP='UPDATE' THEN
   IF NEW.analysis_state IS DISTINCT FROM 'ready' OR OLD.analysis_state IS NOT DISTINCT FROM 'ready'
      OR COALESCE(NEW.recording_kind,'spoken')<>'spoken' OR NEW.paired_session_id IS NOT NULL
      OR NULLIF(trim(NEW.arc_id::text),'') IS NULL THEN RETURN NEW; END IF;
  ELSE RETURN OLD; END IF;
 END IF;
 IF TG_TABLE_NAME='user_arc_ideal_notes' THEN
  IF TG_OP='INSERT' AND NEW.user_text IS NULL THEN RETURN NEW; END IF;
  IF TG_OP='UPDATE' AND NEW.user_text IS NOT DISTINCT FROM OLD.user_text
    AND NEW.user_text_version IS NOT DISTINCT FROM OLD.user_text_version THEN RETURN NEW; END IF;
  IF TG_OP='DELETE' AND OLD.user_text IS NULL THEN RETURN OLD; END IF;
 END IF;
 changed_arc:=CASE WHEN TG_OP='DELETE' THEN OLD.arc_id ELSE NEW.arc_id END;
 INSERT INTO public.ideal_text_document_generations(arc_id,generation,updated_at)
 VALUES(changed_arc,1,clock_timestamp()) ON CONFLICT(arc_id) DO UPDATE
 SET generation=public.ideal_text_document_generations.generation+1,updated_at=clock_timestamp();
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;

CREATE TABLE IF NOT EXISTS public.confident_moment_coach_authorability_inventories (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), acquisition_principal_id uuid NOT NULL REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
 project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE RESTRICT, source_take_id uuid NOT NULL REFERENCES public.v2_sessions(id) ON DELETE RESTRICT,
 feedback_membership_id uuid NOT NULL REFERENCES public.feedback_v3_memberships(id) ON DELETE RESTRICT,
 document_snapshot_id uuid NOT NULL REFERENCES public.ideal_text_document_snapshots(id) ON DELETE RESTRICT,
 bundle_inventory_sha256 text NOT NULL CHECK(bundle_inventory_sha256 ~ '^[0-9a-f]{64}$'), cutoff_at timestamptz NOT NULL,
 cutoff_source_generation bigint NOT NULL CHECK(cutoff_source_generation>=0), inventory_revision integer NOT NULL CHECK(inventory_revision>0),
 supersedes_inventory_id uuid NULL REFERENCES public.confident_moment_coach_authorability_inventories(id) ON DELETE RESTRICT,
 item_count integer NOT NULL CHECK(item_count>=0), audio_backed_count integer NOT NULL CHECK(audio_backed_count>=0),
 source_audio_unavailable_count integer NOT NULL CHECK(source_audio_unavailable_count>=0),
 inventory_sha256 text NOT NULL CHECK(inventory_sha256 ~ '^[0-9a-f]{64}$'), idempotency_key text NOT NULL UNIQUE,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), serves_user boolean NOT NULL DEFAULT false CHECK(NOT serves_user),
 dataset_eligible boolean NOT NULL DEFAULT false CHECK(NOT dataset_eligible),
 CHECK(item_count=audio_backed_count+source_audio_unavailable_count), UNIQUE(id,acquisition_principal_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS confident_moment_authorability_successor_idx
 ON public.confident_moment_coach_authorability_inventories(supersedes_inventory_id) WHERE supersedes_inventory_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS public.confident_moment_coach_authorability_items (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), inventory_id uuid NOT NULL REFERENCES public.confident_moment_coach_authorability_inventories(id) ON DELETE RESTRICT,
 acquisition_principal_id uuid NOT NULL REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
 bundle_id uuid NOT NULL, bundle_attachment_id uuid NOT NULL REFERENCES public.confident_moment_bundle_attachments(id) ON DELETE RESTRICT,
 canonical_position integer NOT NULL CHECK(canonical_position>0), evidence_span_id uuid NOT NULL REFERENCES public.evidence_spans(id) ON DELETE RESTRICT,
 authorability_status text NOT NULL CHECK(authorability_status IN('audio_backed','source_audio_unavailable')),
 audio_identity jsonb NULL, item_sha256 text NOT NULL CHECK(item_sha256 ~ '^[0-9a-f]{64}$'), created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 serves_user boolean NOT NULL DEFAULT false CHECK(NOT serves_user), dataset_eligible boolean NOT NULL DEFAULT false CHECK(NOT dataset_eligible),
 CHECK((authorability_status='audio_backed' AND audio_identity IS NOT NULL AND jsonb_typeof(audio_identity)='object')
    OR (authorability_status='source_audio_unavailable' AND audio_identity IS NULL)),
 UNIQUE(inventory_id,bundle_attachment_id), UNIQUE(inventory_id,canonical_position)
);
ALTER TABLE public.confident_moment_coach_authorability_items
 ADD COLUMN IF NOT EXISTS acquisition_principal_id uuid NULL REFERENCES public.owner_principals(id) ON DELETE RESTRICT;
UPDATE public.confident_moment_coach_authorability_items item SET acquisition_principal_id=inventory.acquisition_principal_id
 FROM public.confident_moment_coach_authorability_inventories inventory
 WHERE inventory.id=item.inventory_id AND item.acquisition_principal_id IS NULL;
ALTER TABLE public.confident_moment_coach_authorability_items ALTER COLUMN acquisition_principal_id SET NOT NULL;
DO $cm_authorability_item_principal_fk$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='confident_moment_authorability_item_principal_fk') THEN
  ALTER TABLE public.confident_moment_coach_authorability_items ADD CONSTRAINT confident_moment_authorability_item_principal_fk
   FOREIGN KEY(inventory_id,acquisition_principal_id)
   REFERENCES public.confident_moment_coach_authorability_inventories(id,acquisition_principal_id) ON DELETE RESTRICT;
 END IF;
END $cm_authorability_item_principal_fk$;
CREATE TABLE IF NOT EXISTS public.confident_moment_blind_assignment_bindings (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), inventory_id uuid NOT NULL REFERENCES public.confident_moment_coach_authorability_inventories(id) ON DELETE RESTRICT,
 review_batch_id uuid NOT NULL REFERENCES public.coach_guidance_review_batches(id) ON DELETE RESTRICT,
 review_assignment_id uuid NOT NULL REFERENCES public.ml_review_assignments(id) ON DELETE RESTRICT,
 blind_packet_id uuid NOT NULL REFERENCES public.exercise_blind_packets(id) ON DELETE RESTRICT,
 audio_lineage_id uuid NOT NULL, audio_sha256 text NOT NULL CHECK(audio_sha256 ~ '^[0-9a-f]{64}$'),
 evidence_span_id uuid NOT NULL REFERENCES public.evidence_spans(id) ON DELETE RESTRICT,
 evidence_hash text NOT NULL CHECK(NULLIF(btrim(evidence_hash),'') IS NOT NULL),
 acquisition_principal_id uuid NOT NULL REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
 project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE RESTRICT, source_take_id uuid NOT NULL REFERENCES public.v2_sessions(id) ON DELETE RESTRICT,
 feedback_membership_id uuid NOT NULL REFERENCES public.feedback_v3_memberships(id) ON DELETE RESTRICT,
 bundle_id uuid NOT NULL, bundle_attachment_id uuid NOT NULL REFERENCES public.confident_moment_bundle_attachments(id) ON DELETE RESTRICT,
 binding_role text NOT NULL CHECK(binding_role IN('bundle_subject','bundle_attachment')),
 assignment_identity_sha256 text NOT NULL CHECK(assignment_identity_sha256 ~ '^[0-9a-f]{64}$'), binding_sha256 text NOT NULL CHECK(binding_sha256 ~ '^[0-9a-f]{64}$'),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), serves_user boolean NOT NULL DEFAULT false CHECK(NOT serves_user),
 dataset_eligible boolean NOT NULL DEFAULT false CHECK(NOT dataset_eligible), UNIQUE(review_batch_id,bundle_attachment_id)
);
CREATE TABLE IF NOT EXISTS public.confident_moment_coach_wording_authority_bindings (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), feedback_revision_id uuid NOT NULL REFERENCES public.feedback_revisions(id) ON DELETE RESTRICT,
 blind_assignment_binding_id uuid NOT NULL REFERENCES public.confident_moment_blind_assignment_bindings(id) ON DELETE RESTRICT,
 review_batch_id uuid NOT NULL REFERENCES public.coach_guidance_review_batches(id) ON DELETE RESTRICT,
 reveal_grant_id uuid NOT NULL REFERENCES public.coach_guidance_reveal_grants(id) ON DELETE RESTRICT,
 reveal_access_id uuid NOT NULL REFERENCES public.coach_guidance_reveal_accesses(id) ON DELETE RESTRICT,
 review_assignment_id uuid NOT NULL REFERENCES public.ml_review_assignments(id) ON DELETE RESTRICT,
 blind_judgment_id uuid NOT NULL REFERENCES public.ml_judgments(id) ON DELETE RESTRICT,
 reviewer_principal_id uuid NOT NULL REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
 acquisition_principal_id uuid NOT NULL REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
 bundle_id uuid NOT NULL, source_review_attachment_id uuid NOT NULL REFERENCES public.confident_moment_bundle_attachments(id) ON DELETE RESTRICT,
 source_review_candidate_id uuid NOT NULL REFERENCES public.feedback_candidates(id) ON DELETE RESTRICT,
 source_review_evidence_span_id uuid NOT NULL REFERENCES public.evidence_spans(id) ON DELETE RESTRICT,
 target_bundle_attachment_id uuid NOT NULL REFERENCES public.confident_moment_bundle_attachments(id) ON DELETE RESTRICT,
 target_feedback_candidate_id uuid NOT NULL REFERENCES public.feedback_candidates(id) ON DELETE RESTRICT,
 target_feedback_family text NOT NULL CHECK(target_feedback_family IN('confident_voice','rewrite_clarity','great_formulation')),
 authority_scope text NOT NULL CHECK(authority_scope='same_bundle_post_reveal_product_wording_v1'),
 binding_sha256 text NOT NULL CHECK(binding_sha256 ~ '^[0-9a-f]{64}$'), created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 serves_user boolean NOT NULL DEFAULT false CHECK(NOT serves_user), dataset_eligible boolean NOT NULL DEFAULT false CHECK(NOT dataset_eligible),
 UNIQUE(feedback_revision_id), UNIQUE(id,feedback_revision_id),CHECK(source_review_attachment_id=target_bundle_attachment_id)
);
CREATE TABLE IF NOT EXISTS public.feedback_language_delivery_materialization_jobs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), revision_id uuid NOT NULL REFERENCES public.feedback_revisions(id) ON DELETE RESTRICT,
 bundle_attachment_id uuid NOT NULL REFERENCES public.confident_moment_bundle_attachments(id) ON DELETE RESTRICT,
 acquisition_principal_id uuid NOT NULL REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
 job_state text NOT NULL CHECK(job_state IN('pending','completed','closed_stale','failed_retryable')),
 attempt_count integer NOT NULL DEFAULT 0 CHECK(attempt_count>=0), job_sha256 text NOT NULL CHECK(job_sha256 ~ '^[0-9a-f]{64}$'),
 idempotency_key text NOT NULL UNIQUE, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 serves_user boolean NOT NULL DEFAULT false CHECK(NOT serves_user), dataset_eligible boolean NOT NULL DEFAULT false CHECK(NOT dataset_eligible)
);
CREATE TABLE IF NOT EXISTS public.feedback_language_delivery_materialization_job_events (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), job_id uuid NOT NULL REFERENCES public.feedback_language_delivery_materialization_jobs(id) ON DELETE RESTRICT,
 event_kind text NOT NULL CHECK(event_kind IN('completed','closed_stale','failed_retryable')),
 delivery_id uuid NULL REFERENCES public.feedback_language_revision_deliveries(id) ON DELETE RESTRICT,
 attempt_number integer NOT NULL CHECK(attempt_number>0), event_sha256 text NOT NULL CHECK(event_sha256 ~ '^[0-9a-f]{64}$'),
 idempotency_key text NOT NULL UNIQUE, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 serves_user boolean NOT NULL DEFAULT false CHECK(NOT serves_user), dataset_eligible boolean NOT NULL DEFAULT false CHECK(NOT dataset_eligible),
 UNIQUE(job_id,event_kind)
);

ALTER TABLE public.confident_moment_bundle_projection_items
 ADD COLUMN IF NOT EXISTS source_passage jsonb NULL,
 ADD COLUMN IF NOT EXISTS update_text_available boolean NOT NULL DEFAULT false,
 ADD COLUMN IF NOT EXISTS coach_authoring_exclusion_reason text NULL;

CREATE OR REPLACE FUNCTION public.lock_confident_moment_position_100_v1(
 p_root_blocks text[],p_transition_keys text[],p_part_heads text[])
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE x text;
BEGIN
 FOR x IN SELECT value FROM (SELECT DISTINCT value FROM unnest(COALESCE(p_root_blocks,ARRAY[]::text[])) value) frozen ORDER BY convert_to(value,'UTF8') LOOP
  IF x !~ '^root-block:' THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_LOCK_GRAPH_INVALID'; END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended(x,0));
 END LOOP;
 FOR x IN SELECT value FROM (SELECT DISTINCT value FROM unnest(COALESCE(p_transition_keys,ARRAY[]::text[])) value) frozen ORDER BY convert_to(value,'UTF8') LOOP
  IF x !~ '^ideal-root-transition:' THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_LOCK_GRAPH_INVALID'; END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended(x,0));
 END LOOP;
 FOR x IN SELECT value FROM (SELECT DISTINCT value FROM unnest(COALESCE(p_part_heads,ARRAY[]::text[])) value) frozen ORDER BY convert_to(value,'UTF8') LOOP
  IF x !~ '^ideal-text-part-revision-head:' THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_LOCK_GRAPH_INVALID'; END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended(x,0));
 END LOOP;
END $$;

CREATE OR REPLACE FUNCTION public.read_feedback_v3_candidate_source_snapshot_v1(
 p_acquisition_principal_id uuid,p_project_id uuid,p_take_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER STABLE SET search_path=public AS $$
DECLARE s public.ideal_text_document_snapshots; surface text;
BEGIN
 PERFORM public.lock_confident_moment_inventory_v1(p_acquisition_principal_id,p_project_id,p_take_id);
 PERFORM public.require_mlc3_service_access_v2(p_acquisition_principal_id,NULL,NULL);
 SELECT snapshot.* INTO STRICT s
 FROM public.ideal_text_document_heads head
 JOIN public.ideal_text_document_snapshots snapshot ON snapshot.id=head.snapshot_id
 WHERE snapshot.acquisition_principal_id=p_acquisition_principal_id
   AND snapshot.project_id=p_project_id AND snapshot.source_take_session_id=p_take_id
 FOR SHARE OF snapshot;
 surface:=COALESCE(s.payload->>'ideal_text',s.payload->>'text');
 IF surface IS NULL OR public.exercise_json_sha256_v1(s.payload)<>s.payload_sha256 THEN
  RAISE EXCEPTION 'FEEDBACK_V3_SOURCE_SNAPSHOT_INVALID';
 END IF;
 RETURN jsonb_build_object('snapshot_contract_version','feedback-v3-candidate-source-snapshot-v1',
  'document_snapshot_id',s.id,'source_generation',s.source_generation,'surface',surface,
  'surface_sha256',public.exercise_text_sha256_v1(surface));
END $$;

CREATE OR REPLACE FUNCTION public.record_confident_moment_bundle_family_response_v1(
 p_acquisition_principal_id uuid,p_bundle_id uuid,p_bundle_attachment_id uuid,
 p_feedback_exposure_id uuid,p_render_receipt_id uuid,p_response text,p_idempotency_key text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE a public.confident_moment_bundle_attachments; m public.feedback_v3_memberships;
 u uuid; family text; b public.feedback_v3_service_response_bindings; d jsonb;
 decision uuid; canonical_value text; binding public.confident_moment_owner_decision_bindings;
 decision_hash text; result jsonb;
BEGIN
 IF COALESCE(btrim(p_idempotency_key),'')='' THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_RESPONSE_INVALID'; END IF;
 SELECT * INTO STRICT a FROM public.confident_moment_bundle_attachments
  WHERE id=p_bundle_attachment_id AND acquisition_principal_id=p_acquisition_principal_id;
 IF a.bundle_subject_candidate_id<>p_bundle_id
    OR a.canonical_feedback_presentation_id<>p_feedback_exposure_id THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_RESPONSE_INVALID'; END IF;
 PERFORM public.lock_confident_moment_inventory_v1(
  p_acquisition_principal_id,a.project_id,a.take_id);
 SELECT * INTO STRICT a FROM public.confident_moment_bundle_attachments
  WHERE id=p_bundle_attachment_id AND acquisition_principal_id=p_acquisition_principal_id
    AND bundle_subject_candidate_id=p_bundle_id
    AND canonical_feedback_presentation_id=p_feedback_exposure_id;
 m:=public.require_feedback_v3_service_membership_live_v1(a.feedback_membership_id,p_acquisition_principal_id);
 SELECT user_id INTO STRICT u FROM public.owner_principals
  WHERE id=p_acquisition_principal_id AND user_id IS NOT NULL;
 SELECT feedback_family INTO STRICT family FROM public.feedback_v3_membership_items
  WHERE membership_id=m.id AND candidate_id=a.attached_candidate_id
    AND selected AND eligibility='eligible';
 IF NOT EXISTS(SELECT 1 FROM public.feedback_v3_service_render_receipts r
   WHERE r.id=p_render_receipt_id AND r.feedback_exposure_id=p_feedback_exposure_id
   AND r.acquisition_principal_id=p_acquisition_principal_id AND r.owner_user_id=u
   AND r.membership_id=m.id AND r.candidate_id=a.attached_candidate_id) THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_RESPONSE_INVALID'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(
  'confident-moment-owner-decision:'||m.id::text||':'||a.attached_candidate_id::text||':'||a.id::text,0));
 SELECT * INTO binding FROM public.confident_moment_owner_decision_bindings
  WHERE bundle_attachment_id=a.id;
 IF binding.id IS NOT NULL THEN
  IF binding.acquisition_principal_id<>p_acquisition_principal_id
     OR binding.canonical_feedback_presentation_id<>p_feedback_exposure_id
     OR binding.render_receipt_id<>p_render_receipt_id
     OR binding.feedback_family<>family
     OR binding.interaction_response<>p_response
     OR binding.idempotency_key<>p_idempotency_key THEN
   RAISE EXCEPTION 'CONFIDENT_MOMENT_RESPONSE_REPLAY_CONFLICT'; END IF;
  PERFORM public.require_mlc3_service_access_v2(p_acquisition_principal_id,NULL,NULL);
  RETURN jsonb_build_object('family_response_contract_version','confident-moment-family-response-v1',
   'bundle_id',p_bundle_id,'bundle_attachment_id',a.id,'feedback_family',family,
   'response',binding.interaction_response,'decision_id',binding.decision_id,
   'owner_response_id',binding.owner_response_id,'response_binding_id',binding.response_binding_id,
   'dataset_eligible',false);
 END IF;
 IF family='confident_voice' THEN
  IF p_response NOT IN('yes','in_between','no','not_sure','audio_unclear') THEN
   RAISE EXCEPTION 'CONFIDENT_MOMENT_RESPONSE_INVALID'; END IF;
  canonical_value:='confident_'||p_response;
  SELECT * INTO b FROM public.record_feedback_v3_service_response_v1(m.project_id,m.take_id,
   p_acquisition_principal_id,u,m.id,a.attached_candidate_id,p_feedback_exposure_id,
   p_render_receipt_id,canonical_value,p_idempotency_key);
  decision:=b.v3_owner_response_id;
 ELSIF family='rewrite_clarity' THEN
  IF p_response NOT IN('apply_suggestion','keep_wording') THEN
   RAISE EXCEPTION 'CONFIDENT_MOMENT_RESPONSE_INVALID'; END IF;
  canonical_value:=CASE p_response WHEN 'apply_suggestion' THEN 'accept_proposed' ELSE 'keep_original' END;
  d:=public.record_feedback_human_decision_v1(m.project_id,m.take_id,u,m.id,a.attached_candidate_id,
   p_feedback_exposure_id,family,canonical_value,'correction-response-v1',p_idempotency_key);
  decision:=(d->>'id')::uuid;
 ELSE
  IF family<>'great_formulation' OR p_response NOT IN('useful','not_useful','not_sure') THEN
   RAISE EXCEPTION 'CONFIDENT_MOMENT_RESPONSE_INVALID'; END IF;
  canonical_value:=p_response;
  d:=public.record_feedback_human_decision_v1(m.project_id,m.take_id,u,m.id,a.attached_candidate_id,
   p_feedback_exposure_id,family,canonical_value,'praise-helpfulness-v1',p_idempotency_key);
  decision:=(d->>'id')::uuid;
 END IF;
 decision_hash:=public.exercise_json_sha256_v1(jsonb_build_object(
  'principal',p_acquisition_principal_id,'project',m.project_id,'take',m.take_id,
  'membership',m.id,'bundle_subject',p_bundle_id,'attachment',a.id,
  'candidate',a.attached_candidate_id,'family',family,'evidence',a.attached_evidence_span_id,
  'presentation',p_feedback_exposure_id,'render_receipt',p_render_receipt_id,
  'decision',decision,'response',p_response,'canonical_response',canonical_value,
  'idempotency_key',p_idempotency_key));
 INSERT INTO public.confident_moment_owner_decision_bindings(
  acquisition_principal_id,project_id,take_id,feedback_membership_id,
  bundle_subject_candidate_id,bundle_attachment_id,candidate_id,feedback_family,
  evidence_span_id,canonical_feedback_presentation_id,render_receipt_id,decision_id,
  owner_response_id,response_binding_id,correction_decision_id,praise_helpfulness_id,
  interaction_response,canonical_response,response_taxonomy_version,decision_sha256,idempotency_key)
 VALUES(p_acquisition_principal_id,m.project_id,m.take_id,m.id,p_bundle_id,a.id,
  a.attached_candidate_id,family,a.attached_evidence_span_id,p_feedback_exposure_id,
  p_render_receipt_id,decision,CASE WHEN family='confident_voice' THEN decision END,
  CASE WHEN family='confident_voice' THEN b.id END,
  CASE WHEN family='rewrite_clarity' THEN decision END,
  CASE WHEN family='great_formulation' THEN decision END,p_response,canonical_value,
  CASE family WHEN 'confident_voice' THEN 'confidence-owner-five-state-v1'
   WHEN 'rewrite_clarity' THEN 'correction-response-v1' ELSE 'praise-helpfulness-v1' END,
  decision_hash,p_idempotency_key) RETURNING * INTO binding;
 PERFORM public.require_mlc3_service_access_v2(p_acquisition_principal_id,NULL,NULL);
 result:=jsonb_build_object('family_response_contract_version','confident-moment-family-response-v1',
  'bundle_id',p_bundle_id,'bundle_attachment_id',a.id,'feedback_family',family,
  'response',p_response,'decision_id',decision,'owner_response_id',binding.owner_response_id,
  'response_binding_id',binding.response_binding_id,'dataset_eligible',false);
 RETURN result;
END $$;

CREATE OR REPLACE FUNCTION public.record_confident_moment_bundle_root_action_v1(
 p_acquisition_principal_id uuid,p_bundle_id uuid,p_bundle_attachment_id uuid,p_action text,
 p_expected_block_head_action_id uuid,p_source_feedback_exposure_id uuid,p_source_owner_response_id uuid,
 p_source_practice_attempt_id uuid,p_source_ideal_text_revision_id bigint,p_source_text_update_binding_id uuid,
 p_source_target_speaker_binding_id uuid,p_practice_target_speaker_binding_id uuid,p_restore_product_action_id uuid,
 p_policy_version text,p_idempotency_key text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE a public.confident_moment_bundle_attachments; r jsonb; active uuid; revision bigint;
BEGIN
 SELECT * INTO STRICT a FROM public.confident_moment_bundle_attachments WHERE id=p_bundle_attachment_id;
 IF a.bundle_subject_candidate_id<>p_bundle_id THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_ROOT_ACTION_INVALID'; END IF;
 IF p_source_text_update_binding_id IS NOT NULL AND NOT EXISTS(
  SELECT 1 FROM public.confident_moment_bundle_text_update_bindings b
  WHERE b.id=p_source_text_update_binding_id AND b.bundle_attachment_id=a.id
    AND b.result_part_revision_id=p_source_ideal_text_revision_id) THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_ROOT_ACTION_INVALID'; END IF;
 r:=public.record_root_phrase_product_action_v2(p_acquisition_principal_id,a.project_id,a.take_id,a.paragraph_id,
  (SELECT block_key FROM public.feedback_v3_membership_items WHERE membership_id=a.feedback_membership_id AND candidate_id=a.attached_candidate_id),
  p_action,p_expected_block_head_action_id,a.attached_candidate_id,a.attached_evidence_span_id,
  p_source_feedback_exposure_id,p_source_owner_response_id,p_source_practice_attempt_id,p_source_ideal_text_revision_id,
  p_source_text_update_binding_id,p_source_target_speaker_binding_id,p_practice_target_speaker_binding_id,
  p_restore_product_action_id,p_policy_version,p_idempotency_key);
 active:=NULLIF(r->>'active_root_action_id','')::uuid;
 revision:=(r->>'interaction_state_revision')::bigint;
 RETURN jsonb_build_object('root_action_contract_version','confident-moment-root-action-v1',
  'bundle_id',p_bundle_id,'bundle_attachment_id',a.id,'product_action_id',(r->>'id')::uuid,
  'active_root_action_id',active,'interaction_state_revision',revision::text,
  'is_orange',active IS NOT NULL,'is_locked',COALESCE(r->>'persistence_state','')='owner_locked',
  'can_restore_previous',r->>'restore_product_action_id' IS NOT NULL,
  'restore_product_action_id',NULLIF(r->>'restore_product_action_id','')::uuid,'dataset_eligible',false);
END $$;

CREATE OR REPLACE FUNCTION public.compare_and_set_user_ideal_edit_v1(
 p_owner_user_id uuid,p_arc_id text,p_source_document_version integer,p_expected_user_text_revision bigint,
 p_expected_user_text_sha256 text,p_desired_user_text text,p_desired_parts_lineage jsonb,p_idempotency_key text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE n public.user_arc_ideal_notes; op public.ideal_text_user_edit_cas_operations;
 principal uuid; project uuid; source_take uuid; source_snapshot public.ideal_text_document_snapshots;
 current_hash text; result_revision bigint; lineage_hash text; desired_inventory_hash text; response jsonb;
 effective_key text; operation_key text;
 expected_parts jsonb; desired_parts jsonb; actual_parts jsonb; current_desired_parts jsonb; desired_join text;
 revision_plan jsonb:='[]'::jsonb; public_revisions jsonb:='[]'::jsonb; change record;
 new_revision_id bigint; protected boolean;
 legacy_request boolean; effective_expected_revision bigint; effective_expected_hash text;
BEGIN
 IF COALESCE(btrim(p_desired_user_text),'')='' THEN RAISE EXCEPTION 'IDEAL_TEXT_USER_EDIT_INVALID'; END IF;
 legacy_request:=p_desired_parts_lineage IS NULL OR jsonb_typeof(p_desired_parts_lineage)='array';
 IF NOT legacy_request AND jsonb_typeof(p_desired_parts_lineage)<>'object' THEN
  RAISE EXCEPTION 'IDEAL_TEXT_USER_EDIT_INVALID';
 END IF;
 SELECT id INTO STRICT principal FROM public.owner_principals WHERE user_id=p_owner_user_id;
 SELECT id INTO STRICT project FROM public.projects
  WHERE id::text=p_arc_id AND owner_principal_id=principal;
 SELECT snapshot.* INTO STRICT source_snapshot
 FROM public.ideal_text_document_heads head
 JOIN public.ideal_text_document_snapshots snapshot ON snapshot.id=head.snapshot_id
 WHERE head.arc_id=p_arc_id
   AND head.actor_id IN(p_owner_user_id::text,principal::text)
   AND snapshot.acquisition_principal_id=principal
   AND snapshot.project_id=project
   AND snapshot.version=p_source_document_version;
 source_take:=source_snapshot.source_take_session_id;
 PERFORM public.lock_confident_moment_inventory_v1(principal,project,source_take);
 PERFORM pg_advisory_xact_lock(hashtextextended('ideal-text-document-head:'||project::text,0));
 IF (SELECT count(*) FROM public.ideal_text_document_heads head
      JOIN public.ideal_text_document_snapshots snapshot ON snapshot.id=head.snapshot_id
      WHERE head.arc_id=p_arc_id
        AND head.actor_id IN(p_owner_user_id::text,principal::text)
        AND snapshot.acquisition_principal_id=principal
        AND snapshot.project_id=project
        AND snapshot.version=p_source_document_version
        AND snapshot.source_take_session_id=source_take)<>1 THEN
  RAISE EXCEPTION 'IDEAL_TEXT_DOCUMENT_SOURCE_STALE';
 END IF;
 PERFORM public.require_mlc3_service_access_v2(principal,NULL,NULL);
 IF legacy_request AND EXISTS(SELECT 1 FROM public.confident_moment_bundle_text_update_bindings binding
    WHERE binding.acquisition_principal_id=principal AND binding.project_id=project) THEN
  RAISE EXCEPTION 'IDEAL_TEXT_CAS_REQUIRED';
 END IF;
 SELECT * INTO n FROM public.user_arc_ideal_notes WHERE arc_id=p_arc_id AND user_id=p_owner_user_id;
 current_hash:=CASE WHEN n.user_text IS NULL THEN NULL ELSE public.exercise_text_sha256_v1(n.user_text) END;
 SELECT COALESCE(jsonb_agg(jsonb_build_object('position',p.ord,'part_id',p.id,
   'text_sha256',public.exercise_text_sha256_v1(p.text),'locked',p.locked_at IS NOT NULL,
   'current_part_revision_id',CASE WHEN head.id IS NULL THEN NULL ELSE to_jsonb(head.id::text) END)
   ORDER BY p.ord),'[]'::jsonb),
  COALESCE(jsonb_agg(jsonb_build_object('position',p.ord,'part_id',p.id,'text',p.text)
   ORDER BY p.ord),'[]'::jsonb)
 INTO actual_parts,current_desired_parts FROM public.ideal_text_part p
 LEFT JOIN LATERAL(SELECT r.id FROM public.ideal_text_part_revision r
   WHERE r.arc_id=p.arc_id AND r.user_id=p.user_id AND r.part_id=p.id ORDER BY r.id DESC LIMIT 1) head ON true
 WHERE p.arc_id=p_arc_id AND p.user_id=p_owner_user_id::text;
 effective_expected_revision:=CASE WHEN legacy_request THEN n.user_text_revision ELSE p_expected_user_text_revision END;
 effective_expected_hash:=CASE WHEN legacy_request THEN current_hash ELSE p_expected_user_text_sha256 END;
 IF legacy_request THEN
  expected_parts:=actual_parts;
  IF p_desired_parts_lineage IS NULL THEN
   desired_parts:=current_desired_parts;
   SELECT string_agg(item->>'text',E'\n\n' ORDER BY (item->>'position')::integer)
    INTO desired_join FROM jsonb_array_elements(desired_parts) item;
   IF COALESCE(desired_join,'') IS DISTINCT FROM p_desired_user_text THEN
    RAISE EXCEPTION 'IDEAL_TEXT_CAS_REQUIRED';
   END IF;
  ELSE
   IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_desired_parts_lineage) WITH ORDINALITY legacy(item,item_index)
      WHERE jsonb_typeof(item)<>'object' OR (item->>'id')::uuid IS NULL
       OR jsonb_typeof(item->'text')<>'string' OR btrim(item->>'text')=''
       OR (item ? 'ord' AND (item->>'ord')::integer<>item_index-1)) THEN
    RAISE EXCEPTION 'IDEAL_TEXT_USER_EDIT_INVALID';
   END IF;
   SELECT COALESCE(jsonb_agg(jsonb_build_object('position',item_index-1,
      'part_id',(item->>'id')::uuid,'text',btrim(item->>'text')) ORDER BY item_index),'[]'::jsonb)
    INTO desired_parts FROM jsonb_array_elements(p_desired_parts_lineage) WITH ORDINALITY legacy(item,item_index);
  END IF;
  p_desired_parts_lineage:=jsonb_build_object('expected_parts',expected_parts,'desired_parts',desired_parts);
 ELSE
  expected_parts:=p_desired_parts_lineage->'expected_parts'; desired_parts:=p_desired_parts_lineage->'desired_parts';
 END IF;
 IF NOT (p_desired_parts_lineage <@ jsonb_build_object('expected_parts',p_desired_parts_lineage->'expected_parts',
    'desired_parts',p_desired_parts_lineage->'desired_parts')
   AND jsonb_build_object('expected_parts',p_desired_parts_lineage->'expected_parts',
    'desired_parts',p_desired_parts_lineage->'desired_parts') <@ p_desired_parts_lineage)
   OR jsonb_typeof(p_desired_parts_lineage->'expected_parts')<>'array'
   OR jsonb_typeof(p_desired_parts_lineage->'desired_parts')<>'array' THEN
  RAISE EXCEPTION 'IDEAL_TEXT_USER_EDIT_INVALID';
 END IF;
 desired_inventory_hash:=public.exercise_json_sha256_v1(desired_parts);
 IF jsonb_array_length(desired_parts)=0 THEN RAISE EXCEPTION 'IDEAL_TEXT_USER_EDIT_INVALID'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(expected_parts) WITH ORDINALITY e(item,item_index)
   WHERE NOT (item <@ jsonb_build_object('position',item->'position','part_id',item->'part_id',
      'text_sha256',item->'text_sha256','locked',item->'locked','current_part_revision_id',item->'current_part_revision_id')
    AND jsonb_build_object('position',item->'position','part_id',item->'part_id',
      'text_sha256',item->'text_sha256','locked',item->'locked','current_part_revision_id',item->'current_part_revision_id') <@ item)
    OR jsonb_typeof(item->'position')<>'number' OR (item->>'position')::integer<>item_index-1
    OR (item->>'part_id')::uuid IS NULL OR (item->>'text_sha256') !~ '^[0-9a-f]{64}$'
    OR jsonb_typeof(item->'locked')<>'boolean'
    OR (item->'current_part_revision_id'<>'null'::jsonb AND (item->>'current_part_revision_id') !~ '^[1-9][0-9]*$'))
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(desired_parts) WITH ORDINALITY d(item,item_index)
   WHERE NOT (item <@ jsonb_build_object('position',item->'position','part_id',item->'part_id','text',item->'text')
    AND jsonb_build_object('position',item->'position','part_id',item->'part_id','text',item->'text') <@ item)
    OR jsonb_typeof(item->'position')<>'number' OR (item->>'position')::integer<>item_index-1
    OR (item->>'part_id')::uuid IS NULL OR jsonb_typeof(item->'text')<>'string' OR item->>'text'='')
  OR (SELECT count(*)<>count(DISTINCT item->>'part_id') FROM jsonb_array_elements(expected_parts) item)
  OR (SELECT count(*)<>count(DISTINCT item->>'part_id') FROM jsonb_array_elements(desired_parts) item) THEN
  RAISE EXCEPTION 'IDEAL_TEXT_USER_EDIT_INVALID';
 END IF;
 SELECT string_agg(item->>'text',E'\n\n' ORDER BY (item->>'position')::integer) INTO desired_join
  FROM jsonb_array_elements(desired_parts) item;
 IF desired_join IS DISTINCT FROM p_desired_user_text THEN RAISE EXCEPTION 'IDEAL_TEXT_USER_EDIT_INVALID'; END IF;
 lineage_hash:=public.exercise_json_sha256_v1(p_desired_parts_lineage);
 operation_key:=CASE WHEN NULLIF(btrim(p_idempotency_key),'') IS NOT NULL
  THEN public.exercise_text_sha256_v1('ordinary:'||btrim(p_idempotency_key))
  ELSE public.exercise_json_sha256_v1(jsonb_build_object(
   'namespace','legacy-ideal-text-user-edit-v2','acquisition_principal_id',principal,
   'owner_user_id',p_owner_user_id,'arc_id',p_arc_id,'source_document_version',p_source_document_version,
   'desired_user_text_sha256',public.exercise_text_sha256_v1(p_desired_user_text),
   'desired_part_inventory_sha256',desired_inventory_hash)) END;
 effective_key:=COALESCE(NULLIF(btrim(p_idempotency_key),''),'legacy:'||operation_key);
 PERFORM public.lock_confident_moment_position_100_v1(
  ARRAY(SELECT DISTINCT 'root-block:'||head.project_id::text||':'||head.slide_index::text||':'||head.block_key::text
   FROM public.root_phrase_block_heads head
   JOIN public.root_phrase_product_actions action ON action.id=head.active_root_action_id
   JOIN public.root_phrase_content_versions content ON content.id=action.content_version_id
   WHERE content.source_ideal_part_id IN(
    SELECT (item->>'part_id')::uuid FROM jsonb_array_elements(expected_parts||desired_parts) item)
   ORDER BY 1),
  ARRAY[]::text[],
  ARRAY(SELECT DISTINCT 'ideal-text-part-revision-head:'||p_arc_id||':'||p_owner_user_id||':'||(item->>'part_id')
   FROM jsonb_array_elements(expected_parts||desired_parts) item ORDER BY 1));
 SELECT * INTO n FROM public.user_arc_ideal_notes WHERE arc_id=p_arc_id AND user_id=p_owner_user_id FOR UPDATE;
 current_hash:=CASE WHEN n.user_text IS NULL THEN NULL ELSE public.exercise_text_sha256_v1(n.user_text) END;
 SELECT COALESCE(jsonb_agg(jsonb_build_object('position',p.ord,'part_id',p.id,
   'text_sha256',public.exercise_text_sha256_v1(p.text),'locked',p.locked_at IS NOT NULL,
   'current_part_revision_id',CASE WHEN head.id IS NULL THEN NULL ELSE to_jsonb(head.id::text) END)
   ORDER BY p.ord),'[]'::jsonb)
 INTO actual_parts FROM public.ideal_text_part p
 LEFT JOIN LATERAL(SELECT r.id FROM public.ideal_text_part_revision r
   WHERE r.arc_id=p.arc_id AND r.user_id=p.user_id AND r.part_id=p.id ORDER BY r.id DESC LIMIT 1) head ON true
 WHERE p.arc_id=p_arc_id AND p.user_id=p_owner_user_id::text;
 SELECT COALESCE(jsonb_agg(jsonb_build_object('position',p.ord,'part_id',p.id,'text',p.text)
  ORDER BY p.ord),'[]'::jsonb) INTO current_desired_parts FROM public.ideal_text_part p
  WHERE p.arc_id=p_arc_id AND p.user_id=p_owner_user_id::text;
 SELECT * INTO op FROM public.ideal_text_user_edit_cas_operations WHERE idempotency_key=effective_key;
 IF op.id IS NOT NULL THEN
  IF op.operation_key_sha256<>operation_key
    OR op.owner_user_id<>p_owner_user_id OR op.acquisition_principal_id<>principal
    OR op.project_id<>project OR op.arc_id<>p_arc_id
    OR op.source_document_version<>p_source_document_version
    OR (NOT legacy_request AND op.previous_user_text_revision IS DISTINCT FROM effective_expected_revision)
    OR (NOT legacy_request AND op.previous_user_text_sha256 IS DISTINCT FROM effective_expected_hash)
    OR op.result_user_text_sha256<>public.exercise_text_sha256_v1(p_desired_user_text)
    OR op.result_user_text_revision IS DISTINCT FROM n.user_text_revision
    OR op.result_user_text_sha256 IS DISTINCT FROM current_hash
    OR (NOT legacy_request AND op.desired_parts_lineage_sha256<>lineage_hash)
    OR current_desired_parts<>desired_parts THEN
   IF NULLIF(btrim(p_idempotency_key),'') IS NULL THEN
    RAISE EXCEPTION 'IDEAL_TEXT_LEGACY_REPLAY_CONFLICT';
   END IF;
   RAISE EXCEPTION 'IDEAL_TEXT_USER_EDIT_CONFLICT';
  END IF;
  PERFORM public.require_mlc3_service_access_v2(principal,NULL,NULL);
  RETURN op.result_payload;
 END IF;
 IF actual_parts<>expected_parts THEN RAISE EXCEPTION 'IDEAL_TEXT_PARTS_REFRESH_REQUIRED'; END IF;
 IF n.user_text_revision IS DISTINCT FROM effective_expected_revision OR current_hash IS DISTINCT FROM effective_expected_hash THEN
  RAISE EXCEPTION 'IDEAL_TEXT_USER_EDIT_CONFLICT'; END IF;
 result_revision:=COALESCE(n.user_text_revision,0)+1;
 -- Freeze the complete structural plan before any product write.  Protected
 -- parts must survive byte-identically in their exact slot.
 FOR change IN
  WITH e AS (SELECT (x->>'part_id')::uuid part_id,(x->>'position')::integer old_pos,x->>'text_sha256' old_hash
    FROM jsonb_array_elements(expected_parts) x),
  d AS (SELECT (x->>'part_id')::uuid part_id,(x->>'position')::integer new_pos,x->>'text' new_text
    FROM jsonb_array_elements(desired_parts) x)
  SELECT COALESCE(e.part_id,d.part_id) part_id,e.old_pos,d.new_pos,e.old_hash,d.new_text,
    p.text old_text,p.locked_at IS NOT NULL OR p.root_phrase IS NOT NULL
      OR EXISTS(SELECT 1 FROM public.root_phrase_content_versions qualified_content
       JOIN public.root_phrase_qualification_revisions qualification
         ON qualification.content_version_id=qualified_content.id
       WHERE qualified_content.source_ideal_part_id=p.id)
      OR EXISTS(SELECT 1 FROM public.root_phrase_content_versions content
       JOIN public.root_phrase_product_actions action ON action.content_version_id=content.id
       JOIN public.root_phrase_block_heads head ON head.active_root_action_id=action.id
       WHERE content.source_ideal_part_id=p.id) AS is_protected,
    (SELECT r.id FROM public.ideal_text_part_revision r WHERE r.arc_id=p_arc_id
      AND r.user_id=p_owner_user_id::text AND r.part_id=COALESCE(e.part_id,d.part_id) ORDER BY r.id DESC LIMIT 1) previous_revision
  FROM e FULL JOIN d USING(part_id)
  LEFT JOIN public.ideal_text_part p ON p.id=COALESCE(e.part_id,d.part_id) AND p.arc_id=p_arc_id AND p.user_id=p_owner_user_id::text
  WHERE e.part_id IS NULL OR d.part_id IS NULL OR e.old_pos<>d.new_pos
    OR e.old_hash<>public.exercise_text_sha256_v1(d.new_text)
  ORDER BY d.new_pos NULLS LAST,e.old_pos,COALESCE(e.part_id,d.part_id)
 LOOP
  IF change.old_pos IS NULL THEN
   IF EXISTS(SELECT 1 FROM public.ideal_text_part p WHERE p.id=change.part_id)
     OR EXISTS(SELECT 1 FROM public.ideal_text_part_revision r WHERE r.part_id=change.part_id) THEN
    RAISE EXCEPTION 'IDEAL_TEXT_PART_ID_REUSE_FORBIDDEN'; END IF;
  ELSIF change.is_protected THEN RAISE EXCEPTION 'IDEAL_TEXT_PART_REQUIRES_UNLOCK'; END IF;
  new_revision_id:=nextval(pg_get_serial_sequence('public.ideal_text_part_revision','id'));
  revision_plan:=revision_plan||jsonb_build_array(jsonb_build_object('part_id',change.part_id,
   'revision_id',new_revision_id::text,'action',CASE
    WHEN change.old_pos IS NULL THEN 'owner_part_created'
    WHEN change.new_pos IS NULL THEN 'owner_part_removed'
    WHEN change.old_pos<>change.new_pos AND change.old_hash<>public.exercise_text_sha256_v1(change.new_text)
      THEN 'owner_part_text_updated_and_reordered'
    WHEN change.old_pos<>change.new_pos THEN 'owner_part_reordered'
    ELSE 'owner_part_text_updated' END,
   'previous_position',change.old_pos,'result_position',change.new_pos,
   'previous_revision_id',CASE WHEN change.previous_revision IS NULL THEN NULL ELSE to_jsonb(change.previous_revision::text) END,
   '_old_text',change.old_text,'_new_text',change.new_text));
 END LOOP;
 SELECT COALESCE(jsonb_agg(item-ARRAY['_old_text','_new_text'] ORDER BY
   COALESCE((item->>'result_position')::integer,2147483647),
   COALESCE((item->>'previous_position')::integer,2147483647),item->>'part_id'),'[]'::jsonb)
 INTO public_revisions FROM jsonb_array_elements(revision_plan) item;
 response:=jsonb_build_object('ideal_text_user_edit_contract_version','ideal-text-user-edit-cas-v2','saved',true,
  'arc_id',p_arc_id,'source_document_version',p_source_document_version,
  'previous_user_text_revision',CASE WHEN n.user_text_revision IS NULL THEN NULL ELSE to_jsonb(n.user_text_revision::text) END,
  'result_user_text_revision',result_revision::text,'result_user_text_sha256',public.exercise_text_sha256_v1(p_desired_user_text),
  'desired_parts_lineage_sha256',lineage_hash,'part_revisions',public_revisions,'dataset_eligible',false);
 INSERT INTO public.ideal_text_user_edit_cas_operations(owner_user_id,acquisition_principal_id,project_id,arc_id,source_document_version,
  operation_kind,operation_key_sha256,previous_user_text_revision,result_user_text_revision,previous_user_text_sha256,
  result_user_text_sha256,desired_parts_lineage_sha256,result_payload,idempotency_key)
 VALUES(p_owner_user_id,principal,project,p_arc_id,p_source_document_version,
  CASE WHEN NULLIF(btrim(p_idempotency_key),'') IS NULL THEN 'legacy_owner_edit' ELSE 'ordinary_owner_edit' END,
  operation_key,n.user_text_revision,result_revision,current_hash,
  public.exercise_text_sha256_v1(p_desired_user_text),lineage_hash,response,effective_key) RETURNING * INTO op;
 INSERT INTO public.confident_moment_text_update_capabilities(capability_id,transaction_id,backend_pid,operation_name,
  acquisition_principal_id,owner_user_id,project_id,arc_id,notes_mutation_kind,expected_notes_row_present,
  expected_user_text_sha256,result_user_text_sha256,expected_user_text_version,result_user_text_version,
  expected_user_text_revision,result_user_text_revision,desired_parts_lineage_sha256,capability_sha256)
 VALUES(gen_random_uuid(),txid_current(),pg_backend_pid(),'compare_and_set_user_ideal_edit_v1',principal,p_owner_user_id,
  project,p_arc_id,CASE WHEN n.arc_id IS NULL THEN 'insert' ELSE 'update' END,n.arc_id IS NOT NULL,current_hash,
  public.exercise_text_sha256_v1(p_desired_user_text),CASE WHEN n.arc_id IS NULL THEN NULL ELSE n.user_text_version END,
  p_source_document_version,n.user_text_revision,result_revision,lineage_hash,
  public.exercise_json_sha256_v1(jsonb_build_object('operation',op.id,'result_revision',result_revision)));
 -- Free changed slots without touching protected parts, then write the exact
 -- desired inventory and one immutable revision/tombstone per changed part.
 UPDATE public.ideal_text_part p SET ord=-1000000000-p.ord,updated_at=clock_timestamp()
 WHERE p.arc_id=p_arc_id AND p.user_id=p_owner_user_id::text
   AND EXISTS(SELECT 1 FROM jsonb_array_elements(revision_plan) item
    WHERE (item->>'part_id')::uuid=p.id AND item->>'action' IN(
     'owner_part_reordered','owner_part_text_updated_and_reordered','owner_part_removed'));
 FOR change IN SELECT item FROM jsonb_array_elements(revision_plan) item
  ORDER BY COALESCE((item->>'result_position')::integer,2147483647),
    COALESCE((item->>'previous_position')::integer,2147483647),item->>'part_id'
 LOOP
  IF change.item->>'action'='owner_part_created' THEN
   INSERT INTO public.ideal_text_part(id,arc_id,user_id,ord,text,iteration)
    VALUES((change.item->>'part_id')::uuid,p_arc_id,p_owner_user_id::text,
     (change.item->>'result_position')::integer,change.item->>'_new_text',0);
  ELSIF change.item->>'action'='owner_part_removed' THEN
   NULL;
  ELSE
   UPDATE public.ideal_text_part SET ord=(change.item->>'result_position')::integer,
    text=change.item->>'_new_text',updated_at=clock_timestamp()
    WHERE id=(change.item->>'part_id')::uuid AND arc_id=p_arc_id AND user_id=p_owner_user_id::text;
   IF NOT FOUND THEN RAISE EXCEPTION 'IDEAL_TEXT_PARTS_REFRESH_REQUIRED'; END IF;
  END IF;
  INSERT INTO public.ideal_text_part_revision(id,arc_id,user_id,part_id,action,text,
   previous_revision_id,owner_edit_revision,previous_position,result_position,owner_edit_operation_id,revision_contract_version)
  VALUES((change.item->>'revision_id')::bigint,p_arc_id,p_owner_user_id::text,(change.item->>'part_id')::uuid,
   change.item->>'action',COALESCE(change.item->>'_new_text',change.item->>'_old_text'),
   NULLIF(change.item->>'previous_revision_id','')::bigint,result_revision,
   NULLIF(change.item->>'previous_position','')::integer,NULLIF(change.item->>'result_position','')::integer,
   op.id,'ideal-text-part-revision-v2');
  IF change.item->>'action'='owner_part_removed' THEN
   DELETE FROM public.ideal_text_part WHERE id=(change.item->>'part_id')::uuid
    AND arc_id=p_arc_id AND user_id=p_owner_user_id::text;
   IF NOT FOUND THEN RAISE EXCEPTION 'IDEAL_TEXT_PARTS_REFRESH_REQUIRED'; END IF;
  END IF;
 END LOOP;
 -- No unchanged row may be missing or differ after applying the frozen plan.
 IF (SELECT COALESCE(jsonb_agg(jsonb_build_object('position',p.ord,'part_id',p.id,'text',p.text)
      ORDER BY p.ord),'[]'::jsonb) FROM public.ideal_text_part p
     WHERE p.arc_id=p_arc_id AND p.user_id=p_owner_user_id::text)<>desired_parts THEN
  RAISE EXCEPTION 'IDEAL_TEXT_PARTS_REFRESH_REQUIRED';
 END IF;
 IF n.arc_id IS NULL THEN
  INSERT INTO public.user_arc_ideal_notes(arc_id,user_id,text,user_text,user_text_version,user_text_revision)
  VALUES(p_arc_id,p_owner_user_id,p_desired_user_text,p_desired_user_text,p_source_document_version,result_revision);
 ELSE
  UPDATE public.user_arc_ideal_notes SET user_text=p_desired_user_text,user_text_version=p_source_document_version,
   user_text_revision=result_revision WHERE arc_id=p_arc_id AND user_id=p_owner_user_id;
 END IF;
 IF NOT EXISTS(SELECT 1 FROM public.ideal_text_document_heads head
   JOIN public.ideal_text_document_snapshots snapshot ON snapshot.id=head.snapshot_id
   WHERE head.arc_id=p_arc_id
     AND head.actor_id IN(p_owner_user_id::text,principal::text)
     AND snapshot.id=source_snapshot.id
     AND snapshot.acquisition_principal_id=principal
     AND snapshot.project_id=project
     AND snapshot.version=p_source_document_version
     AND snapshot.source_take_session_id=source_take) THEN
  RAISE EXCEPTION 'IDEAL_TEXT_DOCUMENT_SOURCE_STALE';
 END IF;
 PERFORM public.require_mlc3_service_access_v2(principal,NULL,NULL);
 IF NOT EXISTS(SELECT 1 FROM public.confident_moment_text_update_capabilities
   WHERE transaction_id=txid_current() AND backend_pid=pg_backend_pid() AND notes_guard_consumed) THEN
  RAISE EXCEPTION 'IDEAL_TEXT_OWNER_LANE_GUARD_NOT_CONSUMED'; END IF;
 DELETE FROM public.confident_moment_text_update_capabilities WHERE transaction_id=txid_current() AND backend_pid=pg_backend_pid();
 RETURN response;
END $$;

CREATE OR REPLACE FUNCTION public.apply_confident_moment_bundle_text_update_v1(
 p_owner_user_id uuid,p_bundle_id uuid,p_attachment_id uuid,p_correction_decision_id uuid,
 p_feedback_exposure_id uuid,p_render_receipt_id uuid,p_source_document_snapshot_id uuid,p_source_document_version integer,
 p_expected_current_part_revision_id bigint,p_expected_user_text_revision bigint,p_expected_user_text_sha256 text,
 p_expected_part_inventory jsonb,p_idempotency_key text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE a public.confident_moment_bundle_attachments; e public.evidence_spans; c public.correction_decisions;
 existing public.confident_moment_bundle_text_update_bindings; part public.ideal_text_part; note public.user_arc_ideal_notes;
 loc jsonb; replacement text; local_start integer; local_end integer; result_text text; part_revision bigint;
 source_document text; result_document text;
 prefix_length integer; actual_inventory jsonb;
 principal uuid; operation_id uuid:=gen_random_uuid(); binding_id uuid:=gen_random_uuid(); previous_hash text; result_hash text;
 before_hash text; after_hash text; response jsonb; result_owner_revision bigint;
BEGIN
 SELECT * INTO existing FROM public.confident_moment_bundle_text_update_bindings WHERE idempotency_key=p_idempotency_key;
 IF existing.id IS NOT NULL THEN
  RETURN jsonb_build_object('bundle_text_update_contract_version','bundle-text-update-v1','binding_id',existing.id,
   'source_document_snapshot_id',existing.source_document_snapshot_id,'source_document_version',existing.source_document_version,
   'previous_user_text_revision',CASE WHEN existing.previous_user_text_revision IS NULL THEN NULL ELSE to_jsonb(existing.previous_user_text_revision::text) END,
   'result_user_text_revision',existing.result_user_text_revision::text,'previous_user_text_sha256',existing.previous_user_text_sha256,
   'result_user_text_sha256',existing.result_user_text_sha256,'target_part_id',existing.target_part_id,
   'result_part_revision_id',existing.result_part_revision_id::text,'dataset_eligible',false);
 END IF;
 SELECT * INTO STRICT a FROM public.confident_moment_bundle_attachments WHERE id=p_attachment_id;
 IF a.bundle_subject_candidate_id<>p_bundle_id OR a.document_snapshot_id<>p_source_document_snapshot_id
  OR a.canonical_feedback_presentation_id<>p_feedback_exposure_id THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_TEXT_UPDATE_INVALID'; END IF;
 SELECT * INTO STRICT e FROM public.evidence_spans WHERE id=a.attached_evidence_span_id;
 loc:=e.ideal_text_target_locator_v1;
 IF loc IS NULL OR e.ideal_text_target_snapshot_id<>p_source_document_snapshot_id THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_TEXT_TARGET_INVALID'; END IF;
 SELECT * INTO STRICT c FROM public.correction_decisions WHERE id=p_correction_decision_id
  AND feedback_membership_id=a.feedback_membership_id AND candidate_id=a.attached_candidate_id
  AND feedback_exposure_id=p_feedback_exposure_id AND value='accept_proposed';
 IF NOT EXISTS(SELECT 1 FROM public.feedback_v3_service_render_receipts WHERE id=p_render_receipt_id AND feedback_exposure_id=p_feedback_exposure_id) THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_TEXT_UPDATE_INVALID'; END IF;
 SELECT COALESCE(generated_output->>'replacement_text',generated_output->>'text') INTO replacement
 FROM public.feedback_candidates WHERE id=a.attached_candidate_id;
 IF replacement IS NULL THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_TEXT_UPDATE_INVALID'; END IF;
 PERFORM public.lock_confident_moment_position_100_v1(ARRAY[]::text[],ARRAY[]::text[],ARRAY[
  'ideal-text-part-revision-head:'||(SELECT arc_id FROM public.ideal_text_document_snapshots WHERE id=a.document_snapshot_id)
   ||':'||p_owner_user_id::text||':'||a.paragraph_id::text]);
 SELECT * INTO STRICT part FROM public.ideal_text_part WHERE id=a.paragraph_id AND arc_id=(SELECT arc_id FROM public.ideal_text_document_snapshots WHERE id=a.document_snapshot_id)
  AND user_id=p_owner_user_id::text FOR UPDATE;
 SELECT string_agg(text,E'\n\n' ORDER BY ord) INTO source_document FROM public.ideal_text_part
  WHERE arc_id=part.arc_id AND user_id=part.user_id;
 IF source_document IS NULL OR EXISTS(SELECT 1 FROM public.ideal_text_part p
    WHERE p.arc_id=part.arc_id AND p.user_id=part.user_id AND p.text='')
   OR public.exercise_text_sha256_v1(source_document)<>loc->>'surface_hash'
   OR substring(source_document FROM (loc->>'start')::integer+1
        FOR (loc->>'end')::integer-(loc->>'start')::integer)<>loc->>'exact_text' THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_TEXT_TARGET_INVALID';
 END IF;
 SELECT COALESCE(jsonb_agg(jsonb_build_object('position',p.ord,'part_id',p.id,
   'text_sha256',public.exercise_text_sha256_v1(p.text),'locked',p.locked_at IS NOT NULL,
   'current_part_revision_id',CASE WHEN head.id IS NULL THEN NULL ELSE to_jsonb(head.id::text) END)
   ORDER BY p.ord),'[]'::jsonb)
 INTO actual_inventory
 FROM public.ideal_text_part p
 LEFT JOIN LATERAL(SELECT r.id FROM public.ideal_text_part_revision r
   WHERE r.arc_id=p.arc_id AND r.user_id=p.user_id AND r.part_id=p.id ORDER BY r.id DESC LIMIT 1) head ON true
 WHERE p.arc_id=part.arc_id AND p.user_id=part.user_id;
 IF jsonb_typeof(p_expected_part_inventory)<>'array' OR p_expected_part_inventory<>actual_inventory THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_TEXT_UPDATE_INVENTORY_STALE';
 END IF;
 SELECT * INTO note FROM public.user_arc_ideal_notes WHERE arc_id=part.arc_id AND user_id=p_owner_user_id FOR UPDATE;
 previous_hash:=CASE WHEN note.user_text IS NULL THEN NULL ELSE public.exercise_text_sha256_v1(note.user_text) END;
 IF note.user_text IS NOT NULL AND note.user_text<>source_document THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_IDEAL_TEXT_STORAGE_DIVERGED'; END IF;
 IF note.user_text_revision IS DISTINCT FROM p_expected_user_text_revision OR previous_hash IS DISTINCT FROM p_expected_user_text_sha256 THEN
  RAISE EXCEPTION 'IDEAL_TEXT_USER_EDIT_CONFLICT'; END IF;
 SELECT COALESCE(max(id),0) INTO part_revision FROM public.ideal_text_part_revision WHERE arc_id=part.arc_id AND user_id=part.user_id AND part_id=part.id;
 IF NULLIF(part_revision,0) IS DISTINCT FROM p_expected_current_part_revision_id THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_TEXT_UPDATE_INVALID'; END IF;
 SELECT COALESCE(sum(length(p.text)+2),0) INTO prefix_length
 FROM public.ideal_text_part p WHERE p.arc_id=part.arc_id AND p.user_id=part.user_id AND p.ord<part.ord;
 local_start:=(loc->>'start')::integer-prefix_length;
 local_end:=(loc->>'end')::integer-prefix_length;
 IF local_start<0 OR local_end>length(part.text) THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_TEXT_TARGET_INVALID'; END IF;
 IF substring(part.text FROM local_start+1 FOR local_end-local_start)<>loc->>'exact_text' THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_TEXT_TARGET_INVALID'; END IF;
 result_text:=substring(part.text FROM 1 FOR local_start)||replacement||substring(part.text FROM local_end+1);
 IF result_text=part.text THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_TEXT_UPDATE_NO_CHANGE'; END IF;
 SELECT string_agg(CASE WHEN id=part.id THEN result_text ELSE text END,E'\n\n' ORDER BY ord)
  INTO result_document FROM public.ideal_text_part WHERE arc_id=part.arc_id AND user_id=part.user_id;
 before_hash:=public.exercise_json_sha256_v1(p_expected_part_inventory); result_owner_revision:=COALESCE(note.user_text_revision,0)+1;
 part_revision:=nextval(pg_get_serial_sequence('public.ideal_text_part_revision','id'));
 result_hash:=public.exercise_text_sha256_v1(result_document); after_hash:=public.exercise_json_sha256_v1(jsonb_build_object('part',part.id,'text_sha256',public.exercise_text_sha256_v1(result_text)));
 response:=jsonb_build_object('bundle_text_update_contract_version','bundle-text-update-v1','binding_id',binding_id,
  'source_document_snapshot_id',p_source_document_snapshot_id,'source_document_version',p_source_document_version,
  'previous_user_text_revision',CASE WHEN note.user_text_revision IS NULL THEN NULL ELSE to_jsonb(note.user_text_revision::text) END,
  'result_user_text_revision',result_owner_revision::text,'previous_user_text_sha256',previous_hash,'result_user_text_sha256',result_hash,
  'target_part_id',part.id,'result_part_revision_id',part_revision::text,'dataset_eligible',false);
 INSERT INTO public.ideal_text_user_edit_cas_operations(id,owner_user_id,acquisition_principal_id,project_id,arc_id,source_document_version,
  operation_kind,operation_key_sha256,previous_user_text_revision,result_user_text_revision,previous_user_text_sha256,result_user_text_sha256,
  desired_parts_lineage_sha256,result_payload,idempotency_key)
 VALUES(operation_id,p_owner_user_id,a.acquisition_principal_id,a.project_id,part.arc_id,p_source_document_version,'bundle_text_update',
  public.exercise_text_sha256_v1('bundle:'||p_idempotency_key),note.user_text_revision,result_owner_revision,previous_hash,
  result_hash,before_hash,response,p_idempotency_key||':operation');
 INSERT INTO public.confident_moment_text_update_capabilities(capability_id,transaction_id,backend_pid,operation_name,
  acquisition_principal_id,owner_user_id,project_id,arc_id,bundle_id,bundle_attachment_id,target_part_id,
  notes_mutation_kind,expected_notes_row_present,expected_user_text_sha256,result_user_text_sha256,
  expected_user_text_version,result_user_text_version,expected_user_text_revision,result_user_text_revision,
  expected_part_text_sha256,result_part_text_sha256,desired_parts_lineage_sha256,capability_sha256)
 VALUES(gen_random_uuid(),txid_current(),pg_backend_pid(),'apply_confident_moment_bundle_text_update_v1',a.acquisition_principal_id,
  p_owner_user_id,a.project_id,part.arc_id,p_bundle_id,a.id,part.id,CASE WHEN note.arc_id IS NULL THEN 'insert' ELSE 'update' END,
  note.arc_id IS NOT NULL,previous_hash,result_hash,CASE WHEN note.arc_id IS NULL THEN NULL ELSE note.user_text_version END,
  p_source_document_version,note.user_text_revision,result_owner_revision,public.exercise_text_sha256_v1(part.text),public.exercise_text_sha256_v1(result_text),
  before_hash,public.exercise_json_sha256_v1(jsonb_build_object('operation',operation_id,'binding',binding_id)));
 UPDATE public.ideal_text_part SET text=result_text,updated_at=clock_timestamp() WHERE id=part.id;
 INSERT INTO public.ideal_text_part_revision(id,arc_id,user_id,part_id,action,text,previous_revision_id,owner_edit_revision,
  previous_position,result_position,owner_edit_operation_id,revision_contract_version)
 VALUES(part_revision,part.arc_id,part.user_id,part.id,'owner_part_text_updated',result_text,p_expected_current_part_revision_id,result_owner_revision,
  part.ord,part.ord,operation_id,'ideal-text-part-revision-v2');
 IF note.arc_id IS NULL THEN
  INSERT INTO public.user_arc_ideal_notes(arc_id,user_id,text,user_text,user_text_version,user_text_revision)
  VALUES(part.arc_id,p_owner_user_id,(SELECT COALESCE(payload->>'ideal_text',payload->>'text') FROM public.ideal_text_document_snapshots WHERE id=p_source_document_snapshot_id),
   result_document,p_source_document_version,result_owner_revision);
 ELSE UPDATE public.user_arc_ideal_notes SET user_text=result_document,user_text_version=p_source_document_version,user_text_revision=result_owner_revision
  WHERE arc_id=part.arc_id AND user_id=p_owner_user_id; END IF;
 INSERT INTO public.confident_moment_bundle_text_update_bindings(id,acquisition_principal_id,project_id,source_take_id,bundle_id,bundle_attachment_id,
  feedback_membership_id,feedback_candidate_id,correction_decision_id,feedback_exposure_id,render_receipt_id,source_document_snapshot_id,
  result_document_snapshot_id,source_document_version,target_part_id,result_part_revision_id,owner_edit_operation_id,
  previous_user_text_revision,result_user_text_revision,previous_user_text_sha256,result_user_text_sha256,before_part_inventory_sha256,
  after_part_inventory_sha256,locator_sha256,binding_sha256,idempotency_key)
 VALUES(binding_id,a.acquisition_principal_id,a.project_id,a.take_id,p_bundle_id,a.id,a.feedback_membership_id,a.attached_candidate_id,
  c.id,p_feedback_exposure_id,p_render_receipt_id,p_source_document_snapshot_id,p_source_document_snapshot_id,p_source_document_version,
  part.id,part_revision,operation_id,note.user_text_revision,result_owner_revision,previous_hash,result_hash,before_hash,after_hash,
  e.ideal_text_target_locator_sha256,public.exercise_json_sha256_v1(jsonb_build_object('binding',binding_id,'revision',part_revision)),p_idempotency_key);
 IF NOT EXISTS(SELECT 1 FROM public.confident_moment_text_update_capabilities
   WHERE transaction_id=txid_current() AND backend_pid=pg_backend_pid()
     AND notes_guard_consumed AND notes_trigger_consumed AND part_trigger_consumed) THEN
  RAISE EXCEPTION 'IDEAL_TEXT_OWNER_LANE_GUARD_NOT_CONSUMED'; END IF;
 DELETE FROM public.confident_moment_text_update_capabilities WHERE transaction_id=txid_current() AND backend_pid=pg_backend_pid();
 RETURN response;
END $$;

CREATE OR REPLACE FUNCTION public.freeze_confident_moment_coach_authorability_inventory_v1(
 p_acquisition_principal_id uuid,p_project_id uuid,p_source_take_id uuid,p_feedback_membership_id uuid,
 p_document_snapshot_id uuid,p_idempotency_key text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE h public.confident_moment_coach_authorability_inventories; a record; pos integer:=0;
 items jsonb:='[]'::jsonb; audio_count integer:=0; unavailable_count integer:=0; item_status text;
 item_audio jsonb; item_hash text; inventory_hash text;
BEGIN
 PERFORM public.lock_confident_moment_inventory_v1(p_acquisition_principal_id,p_project_id,p_source_take_id);
 PERFORM public.require_mlc3_service_access_v2(p_acquisition_principal_id,NULL,NULL);
 SELECT * INTO h FROM public.confident_moment_coach_authorability_inventories WHERE idempotency_key=p_idempotency_key;
 IF h.id IS NOT NULL THEN RETURN to_jsonb(h); END IF;
 FOR a IN SELECT attachment.*,span.evidence_hash,item.snippet_id
  FROM public.confident_moment_bundle_attachments attachment
  JOIN public.feedback_v3_membership_items item ON item.membership_id=attachment.feedback_membership_id AND item.candidate_id=attachment.attached_candidate_id
  JOIN public.evidence_spans span ON span.id=attachment.attached_evidence_span_id
  WHERE attachment.acquisition_principal_id=p_acquisition_principal_id AND attachment.project_id=p_project_id
    AND attachment.take_id=p_source_take_id AND attachment.feedback_membership_id=p_feedback_membership_id
    AND attachment.document_snapshot_id=p_document_snapshot_id ORDER BY attachment.bundle_subject_candidate_id,attachment.canonical_position,attachment.id
 LOOP
  pos:=pos+1; item_audio:=NULL;
  -- An exact tuple is frozen only when the released lineage supplies every
  -- required member.  Partial media is deliberately classified unavailable.
  SELECT jsonb_build_object('audio_lineage_id',lineage.id,'media_object_id',lineage.processing_audio_object_id,
    'audio_sha256',object.exact_bytes_sha256,'start_ms',lineage.start_offset_ms,
    'end_ms',lineage.start_offset_ms+lineage.duration_ms,
    'evidence_span_id',a.attached_evidence_span_id,'evidence_hash',a.evidence_hash,
    'target_speaker_binding_id',speaker_binding.id,'review_policy_version','confident-moment-blind-audio-v1')
   INTO item_audio FROM public.exercise_audio_lineages lineage
   JOIN public.processing_audio_objects object ON object.id=lineage.processing_audio_object_id
   JOIN LATERAL(SELECT binding.id FROM public.mlc3_target_speaker_bindings binding
     WHERE binding.acquisition_principal_id=lineage.acquisition_principal_id
       AND binding.recording_attempt_id=lineage.recording_attempt_id
       AND binding.audio_object_id=lineage.processing_audio_object_id
       AND binding.audio_sha256=lineage.exact_audio_sha256
       AND binding.binding_state='active'
       AND binding.target_start_ms=lineage.start_offset_ms
       AND binding.target_duration_ms=lineage.duration_ms
       AND NOT EXISTS(SELECT 1 FROM public.mlc3_target_speaker_bindings successor
         WHERE successor.supersedes_binding_id=binding.id)
     ORDER BY binding.revision_number DESC,binding.id LIMIT 1) speaker_binding ON true
   JOIN public.evidence_spans span ON span.id=a.attached_evidence_span_id
   WHERE lineage.snippet_id=a.snippet_id AND object.exact_bytes_sha256=lineage.exact_audio_sha256
     AND object.deleted_at IS NULL AND lineage.start_offset_ms>=0 AND lineage.duration_ms>0
     AND span.start_ms=lineage.start_offset_ms
     AND span.end_ms=lineage.start_offset_ms+lineage.duration_ms
   ORDER BY lineage.created_at DESC,lineage.id LIMIT 1;
  item_status:=CASE WHEN item_audio IS NULL THEN 'source_audio_unavailable' ELSE 'audio_backed' END;
  audio_count:=audio_count+(item_status='audio_backed')::integer;
  unavailable_count:=unavailable_count+(item_status='source_audio_unavailable')::integer;
  item_hash:=public.exercise_json_sha256_v1(jsonb_build_object('attachment',a.id,'position',pos,'status',item_status,'audio',item_audio));
  items:=items||jsonb_build_array(jsonb_build_object('bundle_id',a.bundle_subject_candidate_id,'bundle_attachment_id',a.id,
   'canonical_position',pos,'evidence_span_id',a.attached_evidence_span_id,'authorability_status',item_status,
   'audio_identity',item_audio,'item_sha256',item_hash));
 END LOOP;
 inventory_hash:=public.exercise_json_sha256_v1(items);
 INSERT INTO public.confident_moment_coach_authorability_inventories(acquisition_principal_id,project_id,source_take_id,
  feedback_membership_id,document_snapshot_id,bundle_inventory_sha256,cutoff_at,cutoff_source_generation,inventory_revision,
  item_count,audio_backed_count,source_audio_unavailable_count,inventory_sha256,idempotency_key)
 VALUES(p_acquisition_principal_id,p_project_id,p_source_take_id,p_feedback_membership_id,p_document_snapshot_id,
  inventory_hash,clock_timestamp(),(SELECT source_generation FROM public.ideal_text_document_snapshots WHERE id=p_document_snapshot_id),
  1,pos,audio_count,unavailable_count,inventory_hash,p_idempotency_key) RETURNING * INTO h;
 INSERT INTO public.confident_moment_coach_authorability_items(inventory_id,acquisition_principal_id,bundle_id,bundle_attachment_id,canonical_position,
  evidence_span_id,authorability_status,audio_identity,item_sha256)
 SELECT h.id,p_acquisition_principal_id,(x->>'bundle_id')::uuid,(x->>'bundle_attachment_id')::uuid,(x->>'canonical_position')::integer,
  (x->>'evidence_span_id')::uuid,x->>'authorability_status',NULLIF(x->'audio_identity','null'::jsonb),x->>'item_sha256'
 FROM jsonb_array_elements(items) x;
 -- Bind every exact required frozen assignment whose evidence/audio tuple is
 -- the attachment's tuple.  This is the D18 per-evidence authority map: it is
 -- materialized by the reviewed freeze wrapper, never inferred by a browser
 -- and never widened to same-Slide or same-snippet siblings.
 INSERT INTO public.confident_moment_blind_assignment_bindings(
  inventory_id,review_batch_id,review_assignment_id,blind_packet_id,
  audio_lineage_id,audio_sha256,evidence_span_id,evidence_hash,
  acquisition_principal_id,project_id,source_take_id,feedback_membership_id,
  bundle_id,bundle_attachment_id,binding_role,assignment_identity_sha256,binding_sha256)
 SELECT h.id,batch.id,frame_item.review_assignment_id,frame_item.blind_packet_id,
  packet.audio_lineage_id,lineage.exact_audio_sha256,attachment.attached_evidence_span_id,
  span.evidence_hash,p_acquisition_principal_id,p_project_id,p_source_take_id,
  p_feedback_membership_id,attachment.bundle_subject_candidate_id,attachment.id,
  CASE WHEN attachment.attached_candidate_id=attachment.bundle_subject_candidate_id
    THEN 'bundle_subject' ELSE 'bundle_attachment' END,
  public.exercise_json_sha256_v1(jsonb_build_object(
   'review_assignment_id',frame_item.review_assignment_id,
   'blind_packet_id',frame_item.blind_packet_id,'audio_lineage_id',packet.audio_lineage_id,
   'audio_sha256',lineage.exact_audio_sha256,
   'evidence_span_id',attachment.attached_evidence_span_id,'evidence_hash',span.evidence_hash)),
  public.exercise_json_sha256_v1(jsonb_build_object(
   'inventory_id',h.id,'review_batch_id',batch.id,
   'review_assignment_id',frame_item.review_assignment_id,
   'bundle_attachment_id',attachment.id,'bundle_id',attachment.bundle_subject_candidate_id))
 FROM public.confident_moment_bundle_attachments attachment
 JOIN public.evidence_spans span ON span.id=attachment.attached_evidence_span_id
 JOIN public.feedback_v3_membership_items membership_item
   ON membership_item.membership_id=attachment.feedback_membership_id
  AND membership_item.candidate_id=attachment.attached_candidate_id
 JOIN public.ml_review_assignments assignment
   ON assignment.evidence_span_id=attachment.attached_evidence_span_id
 JOIN public.exercise_blind_packets packet
   ON packet.review_assignment_id=assignment.id
 JOIN public.exercise_audio_lineages lineage ON lineage.id=packet.audio_lineage_id
 JOIN public.coach_guidance_review_frame_items frame_item
   ON frame_item.review_assignment_id=assignment.id
  AND frame_item.blind_packet_id=packet.id
  AND frame_item.membership_state='required'
 JOIN public.coach_guidance_review_batches batch ON batch.frame_id=frame_item.frame_id
 WHERE attachment.acquisition_principal_id=p_acquisition_principal_id
   AND attachment.project_id=p_project_id AND attachment.take_id=p_source_take_id
   AND attachment.feedback_membership_id=p_feedback_membership_id
   AND attachment.document_snapshot_id=p_document_snapshot_id
   AND batch.acquisition_principal_id=p_acquisition_principal_id
   AND lineage.acquisition_principal_id=p_acquisition_principal_id
   AND lineage.project_id=p_project_id AND lineage.snippet_id=membership_item.snippet_id
 ON CONFLICT(review_batch_id,bundle_attachment_id) DO NOTHING;
 RETURN to_jsonb(h)||jsonb_build_object('items',items);
END $$;

CREATE OR REPLACE FUNCTION public.publish_confident_moment_coach_feedback_language_v1(
 p_reviewer_principal_id uuid,p_bundle_id uuid,p_bundle_attachment_id uuid,p_review_batch_id uuid,
 p_reveal_grant_id uuid,p_reveal_access_id uuid,p_review_assignment_id uuid,p_output_kind text,p_comment_purpose text,
 p_revision_text text,p_expected_current_revision_id uuid,p_expected_current_delivery_id uuid,p_idempotency_key text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE a public.confident_moment_bundle_attachments; binding public.confident_moment_blind_assignment_bindings;
 access public.coach_guidance_reveal_accesses; rev jsonb; delivery jsonb; created_revision_id uuid; authority_id uuid:=gen_random_uuid();
 output_hash text; response jsonb; target_take uuid; target_state text; materialization_job_id uuid;
BEGIN
 SELECT * INTO STRICT a FROM public.confident_moment_bundle_attachments WHERE id=p_bundle_attachment_id;
 IF a.bundle_subject_candidate_id<>p_bundle_id THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_COACH_AUTHORITY_INVALID'; END IF;
 SELECT * INTO STRICT binding FROM public.confident_moment_blind_assignment_bindings
  WHERE bundle_attachment_id=a.id AND review_batch_id=p_review_batch_id AND review_assignment_id=p_review_assignment_id;
 SELECT * INTO STRICT access FROM public.coach_guidance_reveal_accesses
  WHERE id=p_reveal_access_id AND reveal_grant_id=p_reveal_grant_id AND review_assignment_id=p_review_assignment_id
    AND reviewer_principal_id=p_reviewer_principal_id AND acquisition_principal_id=a.acquisition_principal_id;
 PERFORM public.require_coach_guidance_reviewer_access_v1(p_reviewer_principal_id);
 PERFORM public.require_coach_guidance_assignment_live_v1(
  p_review_assignment_id,a.acquisition_principal_id,'coach_review');
 PERFORM public.require_mlc3_service_access_v2(a.acquisition_principal_id,NULL,NULL);
 output_hash:=public.feedback_candidate_output_sha256_v1(a.attached_candidate_id);
 rev:=public.record_feedback_language_coach_revision_v2(p_reviewer_principal_id,p_review_batch_id,p_reveal_grant_id,
 p_reveal_access_id,p_review_assignment_id,access.blind_judgment_id,a.feedback_membership_id,a.attached_candidate_id,
  output_hash,p_output_kind,p_comment_purpose,p_revision_text,p_expected_current_revision_id,p_idempotency_key||':revision');
 created_revision_id:=(rev->>'id')::uuid;
 PERFORM public.require_feedback_language_coach_source_live_v1(
  created_revision_id,a.acquisition_principal_id,a.feedback_membership_id,
  a.attached_candidate_id,output_hash,'CONFIDENT_MOMENT_COACH_AUTHORITY_INVALID');
 INSERT INTO public.confident_moment_coach_wording_authority_bindings(id,feedback_revision_id,blind_assignment_binding_id,
  review_batch_id,reveal_grant_id,reveal_access_id,review_assignment_id,blind_judgment_id,reviewer_principal_id,
  acquisition_principal_id,bundle_id,source_review_attachment_id,source_review_candidate_id,source_review_evidence_span_id,
  target_bundle_attachment_id,target_feedback_candidate_id,target_feedback_family,
  authority_scope,binding_sha256)
 VALUES(authority_id,created_revision_id,binding.id,p_review_batch_id,p_reveal_grant_id,p_reveal_access_id,p_review_assignment_id,
  access.blind_judgment_id,p_reviewer_principal_id,a.acquisition_principal_id,p_bundle_id,a.id,a.attached_candidate_id,
  a.attached_evidence_span_id,a.id,a.attached_candidate_id,
  (SELECT feedback_family FROM public.feedback_v3_membership_items WHERE membership_id=a.feedback_membership_id AND candidate_id=a.attached_candidate_id),
 'same_bundle_post_reveal_product_wording_v1',public.exercise_json_sha256_v1(jsonb_build_object('revision',created_revision_id,'binding',binding.id)))
 ON CONFLICT(feedback_revision_id) DO NOTHING;
 IF NOT EXISTS(SELECT 1 FROM public.confident_moment_coach_wording_authority_bindings authority
   WHERE authority.feedback_revision_id=created_revision_id
     AND authority.blind_assignment_binding_id=binding.id
     AND authority.review_batch_id=p_review_batch_id
     AND authority.reveal_grant_id=p_reveal_grant_id
     AND authority.reveal_access_id=p_reveal_access_id
     AND authority.review_assignment_id=p_review_assignment_id
     AND authority.blind_judgment_id=access.blind_judgment_id
     AND authority.reviewer_principal_id=p_reviewer_principal_id
     AND authority.acquisition_principal_id=a.acquisition_principal_id
     AND authority.bundle_id=p_bundle_id
     AND authority.source_review_attachment_id=a.id
     AND authority.source_review_candidate_id=a.attached_candidate_id
     AND authority.source_review_evidence_span_id=a.attached_evidence_span_id
     AND authority.target_bundle_attachment_id=a.id
     AND authority.target_feedback_candidate_id=a.attached_candidate_id
     AND authority.authority_scope='same_bundle_post_reveal_product_wording_v1'
     AND authority.binding_sha256=public.exercise_json_sha256_v1(
      jsonb_build_object('revision',created_revision_id,'binding',binding.id))) THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_COACH_AUTHORITY_INVALID';
 END IF;
 -- D14 routing is database-derived.  An unresolved source overlay receives the
 -- update on that Take; otherwise only an already-existing later Take may be
 -- targeted.  Absence creates durable routing work, never a fake delivery.
 IF NOT EXISTS(SELECT 1 FROM public.feedback_v3_service_response_bindings response_binding
    WHERE response_binding.membership_id=a.feedback_membership_id
      AND response_binding.candidate_id=a.attached_candidate_id
      AND response_binding.acquisition_principal_id=a.acquisition_principal_id) THEN
  target_take:=a.take_id; target_state:='scheduled_current_take';
 ELSE
  SELECT later.id INTO target_take FROM public.v2_sessions source
   JOIN public.v2_sessions later ON later.project_id=source.project_id
    AND later.id<>source.id AND later.take_index>source.take_index
   WHERE source.id=a.take_id ORDER BY later.take_index,later.id LIMIT 1;
  IF target_take IS NOT NULL THEN target_state:='scheduled_next_take'; END IF;
 END IF;
 IF target_take IS NOT NULL THEN
  delivery:=public.transition_feedback_language_delivery_v2(created_revision_id,a.acquisition_principal_id,target_take,
   COALESCE(a.anchor_candidate_id,a.bundle_subject_candidate_id),p_expected_current_delivery_id,'schedule',p_idempotency_key||':delivery');
 ELSE
  IF p_expected_current_delivery_id IS NOT NULL THEN RAISE EXCEPTION 'FEEDBACK_LANGUAGE_DELIVERY_STALE'; END IF;
  INSERT INTO public.feedback_language_delivery_materialization_jobs(revision_id,bundle_attachment_id,
   acquisition_principal_id,job_state,job_sha256,idempotency_key)
  VALUES(created_revision_id,a.id,a.acquisition_principal_id,'pending',
   public.exercise_json_sha256_v1(jsonb_build_object('revision',created_revision_id,'attachment',a.id,
    'principal',a.acquisition_principal_id,'state','pending')),p_idempotency_key||':materialization')
  ON CONFLICT(idempotency_key) DO NOTHING;
  SELECT id INTO STRICT materialization_job_id FROM public.feedback_language_delivery_materialization_jobs
   WHERE idempotency_key=p_idempotency_key||':materialization' AND revision_id=created_revision_id
     AND bundle_attachment_id=a.id AND acquisition_principal_id=a.acquisition_principal_id;
 END IF;
 PERFORM public.require_feedback_language_coach_source_live_v1(
  created_revision_id,a.acquisition_principal_id,a.feedback_membership_id,
  a.attached_candidate_id,output_hash,'CONFIDENT_MOMENT_COACH_AUTHORITY_INVALID');
 PERFORM public.require_mlc3_service_access_v2(a.acquisition_principal_id,NULL,NULL);
 response:=jsonb_build_object('coach_feedback_language_contract_version','confident-moment-coach-feedback-language-v1',
  'bundle_id',p_bundle_id,'bundle_attachment_id',a.id,'revision_id',created_revision_id,'revision_sha256',rev->>'revision_sha256',
  'delivery_id',CASE WHEN delivery IS NULL THEN NULL ELSE delivery->'id' END,
  'delivery_state',CASE WHEN delivery IS NULL THEN NULL ELSE to_jsonb(target_state) END,
  'target_take_id',CASE WHEN delivery IS NULL THEN NULL ELSE to_jsonb(target_take) END,'dataset_eligible',false);
 RETURN response;
END $$;

CREATE OR REPLACE FUNCTION public.materialize_feedback_language_delivery_job_v1(p_job_id uuid,p_idempotency_key text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE j public.feedback_language_delivery_materialization_jobs; a public.confident_moment_bundle_attachments;
 d jsonb; event_row public.feedback_language_delivery_materialization_job_events;
BEGIN
 SELECT * INTO STRICT j FROM public.feedback_language_delivery_materialization_jobs WHERE id=p_job_id FOR UPDATE;
 SELECT * INTO event_row FROM public.feedback_language_delivery_materialization_job_events
  WHERE job_id=j.id AND event_kind='completed';
 IF event_row.id IS NOT NULL THEN RETURN jsonb_build_object('job_id',j.id,'job_state','completed','delivery_id',event_row.delivery_id,'dataset_eligible',false); END IF;
 SELECT * INTO STRICT a FROM public.confident_moment_bundle_attachments WHERE id=j.bundle_attachment_id;
 d:=public.transition_feedback_language_delivery_v2(j.revision_id,j.acquisition_principal_id,a.take_id,
  COALESCE(a.anchor_candidate_id,a.bundle_subject_candidate_id),NULL,'schedule',p_idempotency_key||':delivery');
 INSERT INTO public.feedback_language_delivery_materialization_job_events(job_id,event_kind,delivery_id,attempt_number,event_sha256,idempotency_key)
 VALUES(j.id,'completed',(d->>'id')::uuid,j.attempt_count+1,
  public.exercise_json_sha256_v1(jsonb_build_object('job',j.id,'delivery',d->>'id','attempt',j.attempt_count+1)),p_idempotency_key)
 RETURNING * INTO event_row;
 RETURN jsonb_build_object('job_id',j.id,'job_state','completed','delivery_id',event_row.delivery_id,'dataset_eligible',false);
END $$;

CREATE OR REPLACE FUNCTION public.project_confident_moment_coach_authoring_context_v1(
 p_project_id uuid,p_acquisition_principal_id uuid,p_reviewer_principal_id uuid,p_idempotency_key text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE base jsonb; projected_items jsonb:='[]'::jsonb; source_item jsonb; source_binding record;
 targets jsonb; source_context jsonb;
BEGIN
 base:=public.prepare_coach_inline_guidance_context_v1(p_project_id,p_acquisition_principal_id,p_reviewer_principal_id,p_idempotency_key||':base');
 -- D17/D18: enrich each exact revealed D5 source item in place.  Authority is
 -- never widened to an unbound sibling merely because it shares a Bundle.
 FOR source_item IN SELECT value FROM jsonb_array_elements(COALESCE(base->'items','[]'::jsonb))
 LOOP
  source_context:=NULL;
  SELECT binding.id,binding.bundle_id,binding.bundle_attachment_id,binding.review_batch_id,
         binding.review_assignment_id,binding.audio_sha256,binding.evidence_span_id,binding.evidence_hash,
         access.id AS reveal_access_id
    INTO source_binding
    FROM public.confident_moment_blind_assignment_bindings binding
    JOIN public.coach_guidance_reveal_accesses access
      ON access.review_assignment_id=binding.review_assignment_id
     AND access.reviewer_principal_id=p_reviewer_principal_id
     AND access.id=(source_item->>'reveal_access_id')::uuid
   WHERE binding.review_batch_id=(source_item->>'review_batch_id')::uuid
     AND binding.review_assignment_id=(source_item->>'review_assignment_id')::uuid
     AND binding.acquisition_principal_id=p_acquisition_principal_id
     AND binding.project_id=p_project_id
   ORDER BY (binding.binding_role='bundle_subject') DESC,binding.bundle_attachment_id
   LIMIT 1;
  IF FOUND THEN
   SELECT COALESCE(jsonb_agg(jsonb_build_object(
     'bundle_attachment_id',target.id,
     'review_assignment_id',target_binding.review_assignment_id,
     'reveal_access_id',target_access.id,
     'feedback_family',membership_item.feedback_family,
     'allowed_output_kind',CASE WHEN membership_item.feedback_family='rewrite_clarity' THEN 'rephrase' ELSE 'comment' END,
     'allowed_comment_purpose',CASE membership_item.feedback_family
       WHEN 'confident_voice' THEN 'confidence_explanation'
       WHEN 'great_formulation' THEN 'positive_praise' ELSE NULL END,
     'source_passage',jsonb_build_object('evidence_span_id',span.id,'text',span.exact_text,
       'text_sha256',public.exercise_text_sha256_v1(span.exact_text)),
     'expected_current_revision_id',revision_head.id,
     'expected_current_delivery_id',delivery_head.id
    ) ORDER BY target.canonical_position,target.id),'[]'::jsonb)
    INTO targets
    FROM public.confident_moment_blind_assignment_bindings target_binding
    JOIN public.confident_moment_bundle_attachments target ON target.id=target_binding.bundle_attachment_id
    JOIN public.feedback_v3_membership_items membership_item
      ON membership_item.membership_id=target.feedback_membership_id
     AND membership_item.candidate_id=target.attached_candidate_id
    JOIN public.evidence_spans span ON span.id=target.attached_evidence_span_id
    JOIN public.coach_guidance_reveal_accesses target_access
      ON target_access.review_assignment_id=target_binding.review_assignment_id
     AND target_access.reviewer_principal_id=p_reviewer_principal_id
     AND target_access.reveal_grant_id=(source_item->>'reveal_grant_id')::uuid
    LEFT JOIN LATERAL (
      SELECT revision.id FROM public.feedback_revisions revision
       JOIN public.confident_moment_coach_wording_authority_bindings authority
         ON authority.feedback_revision_id=revision.id
        AND authority.blind_assignment_binding_id=target_binding.id
        AND authority.reviewer_principal_id=p_reviewer_principal_id
       WHERE revision.feedback_membership_id=target.feedback_membership_id
         AND revision.feedback_candidate_id=target.attached_candidate_id
         AND revision.taxonomy_version='feedback-language-coach-revision-v1'
         AND NOT EXISTS(SELECT 1 FROM public.feedback_revisions successor
          WHERE successor.supersedes_id=revision.id
            AND successor.taxonomy_version='feedback-language-coach-revision-v1')
       ORDER BY revision.created_at,revision.id LIMIT 1
    ) revision_head ON true
    LEFT JOIN LATERAL (
      SELECT delivery.id FROM public.feedback_language_revision_deliveries delivery
       WHERE delivery.revision_id=revision_head.id
         AND delivery.recipient_principal_id=p_acquisition_principal_id
         AND delivery.feedback_membership_id=target.feedback_membership_id
         AND delivery.feedback_candidate_id=target.attached_candidate_id
         AND delivery.delivery_policy_version='feedback-language-delivery-v2'
         AND NOT EXISTS(SELECT 1 FROM public.feedback_language_revision_deliveries successor
          WHERE successor.supersedes_delivery_id=delivery.id
            AND successor.delivery_policy_version='feedback-language-delivery-v2')
       ORDER BY delivery.delivery_revision,delivery.id LIMIT 1
    ) delivery_head ON true
    WHERE target_binding.bundle_id=source_binding.bundle_id
      AND target_binding.review_batch_id=source_binding.review_batch_id
      AND target_binding.review_assignment_id=source_binding.review_assignment_id
      AND target_binding.audio_sha256=source_binding.audio_sha256
      AND target_binding.evidence_span_id=source_binding.evidence_span_id
      AND target_binding.evidence_hash=source_binding.evidence_hash
      AND target.project_id=p_project_id
      AND target.acquisition_principal_id=p_acquisition_principal_id;
   source_context:=jsonb_build_object('bundle_id',source_binding.bundle_id,
     'source_review_attachment_id',source_binding.bundle_attachment_id,
     'authorized_targets',targets);
  END IF;
  projected_items:=projected_items||jsonb_build_array(
    CASE WHEN source_context IS NULL THEN source_item
         ELSE source_item||jsonb_build_object('bundle_authoring_context',source_context) END);
 END LOOP;
 RETURN jsonb_set(base,'{items}',projected_items,false);
END $$;

CREATE OR REPLACE FUNCTION public.project_confident_moment_coach_authoring_context_v2(
 p_project_id uuid,p_reviewer_principal_id uuid,p_idempotency_key text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE derived_principal uuid; result jsonb;
BEGIN
 IF COALESCE(btrim(p_idempotency_key),'')='' THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_COACH_CONTEXT_INVALID'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-rollout-policy-v2',0));
 SELECT owner_principal_id INTO STRICT derived_principal FROM public.projects WHERE id=p_project_id FOR SHARE;
 PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-service-principal:'||derived_principal::text,0));
 PERFORM pg_advisory_xact_lock(hashtextextended('confident-moment-project-inventory:'||p_project_id::text,0));
 IF (SELECT owner_principal_id FROM public.projects WHERE id=p_project_id) IS DISTINCT FROM derived_principal THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_RETRY_REQUIRED';
 END IF;
 PERFORM public.require_mlc3_service_access_v2(derived_principal,NULL,NULL);
 PERFORM public.require_coach_guidance_reviewer_access_v1(p_reviewer_principal_id);
 result:=public.project_confident_moment_coach_authoring_context_v1(p_project_id,derived_principal,
  p_reviewer_principal_id,p_idempotency_key||':principal:'||derived_principal::text);
 IF (SELECT owner_principal_id FROM public.projects WHERE id=p_project_id) IS DISTINCT FROM derived_principal THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_RETRY_REQUIRED';
 END IF;
 PERFORM public.require_mlc3_service_access_v2(derived_principal,NULL,NULL);
 RETURN result;
END $$;

-- D27-D37: the canonical Ideal Text read and durable, bounded coach-delivery
-- scheduler.  These objects are operational provenance only; none serves a
-- user or is eligible for a dataset.
ALTER TABLE public.feedback_language_delivery_materialization_jobs
 DROP CONSTRAINT IF EXISTS feedback_language_delivery_materialization_jobs_job_state_check;
ALTER TABLE public.feedback_language_delivery_materialization_jobs
 ADD CONSTRAINT feedback_language_delivery_materialization_jobs_job_state_check
 CHECK(job_state IN('pending','completed','closed_stale','failed_retryable','exhausted'));

CREATE TABLE IF NOT EXISTS public.feedback_language_delivery_job_claim_attempts (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 job_id uuid NOT NULL REFERENCES public.feedback_language_delivery_materialization_jobs(id) ON DELETE RESTRICT,
 attempt_number integer NOT NULL CHECK(attempt_number BETWEEN 1 AND 12),
 worker_id text NOT NULL CHECK(worker_id ~ '^[0-9a-f]{64}$'),
 claimed_at timestamptz NOT NULL,
 lease_expires_at timestamptz NOT NULL CHECK(lease_expires_at>claimed_at),
 claim_sha256 text NOT NULL CHECK(claim_sha256 ~ '^[0-9a-f]{64}$'),
 serves_user boolean NOT NULL DEFAULT false CHECK(NOT serves_user),
 dataset_eligible boolean NOT NULL DEFAULT false CHECK(NOT dataset_eligible),
 UNIQUE(job_id,attempt_number), UNIQUE(id,job_id,attempt_number)
);
CREATE TABLE IF NOT EXISTS public.feedback_language_delivery_job_claim_heads (
 job_id uuid PRIMARY KEY REFERENCES public.feedback_language_delivery_materialization_jobs(id) ON DELETE RESTRICT,
 current_claim_attempt_id uuid NOT NULL,
 attempt_count integer NOT NULL CHECK(attempt_count BETWEEN 1 AND 12),
 lease_expires_at timestamptz NOT NULL,
 updated_at timestamptz NOT NULL,
 serves_user boolean NOT NULL DEFAULT false CHECK(NOT serves_user),
 dataset_eligible boolean NOT NULL DEFAULT false CHECK(NOT dataset_eligible),
 FOREIGN KEY(current_claim_attempt_id,job_id,attempt_count)
  REFERENCES public.feedback_language_delivery_job_claim_attempts(id,job_id,attempt_number) ON DELETE RESTRICT
);

ALTER TABLE public.feedback_language_delivery_materialization_job_events
 ADD COLUMN IF NOT EXISTS claim_attempt_id uuid NULL,
 ADD COLUMN IF NOT EXISTS contract_version text NULL,
 ADD COLUMN IF NOT EXISTS cause_code text NULL;
ALTER TABLE public.feedback_language_delivery_materialization_job_events
 DROP CONSTRAINT IF EXISTS feedback_language_delivery_materialization_job_events_event_kind_check,
 DROP CONSTRAINT IF EXISTS feedback_language_delivery_materialization_job_events_job_id_event_kind_key,
 DROP CONSTRAINT IF EXISTS feedback_language_delivery_job_event_attempt_range,
 DROP CONSTRAINT IF EXISTS feedback_language_delivery_job_event_v2_shape,
 DROP CONSTRAINT IF EXISTS feedback_language_delivery_job_event_claim_fk;
ALTER TABLE public.feedback_language_delivery_materialization_job_events
 ADD CONSTRAINT feedback_language_delivery_materialization_job_events_event_kind_check
 CHECK(event_kind IN('completed','closed_stale','failed_retryable','exhausted')),
 ADD CONSTRAINT feedback_language_delivery_job_event_attempt_range CHECK(attempt_number BETWEEN 1 AND 12),
 ADD CONSTRAINT feedback_language_delivery_job_event_v2_shape CHECK(
   (contract_version IS NULL AND claim_attempt_id IS NULL AND cause_code IS NULL
      AND event_kind IN('completed','closed_stale','failed_retryable'))
   OR
   (contract_version='feedback-language-delivery-job-event-v2' AND claim_attempt_id IS NOT NULL
      AND CASE event_kind
       WHEN 'completed' THEN delivery_id IS NOT NULL AND cause_code='delivery_materialized'
       WHEN 'closed_stale' THEN delivery_id IS NULL AND cause_code IN(
        'revision_superseded','authority_withdrawn','source_deleted_or_purged',
        'attachment_invalidated','recipient_or_project_invalid','delivery_already_resolved_elsewhere')
       WHEN 'failed_retryable' THEN delivery_id IS NULL AND cause_code IN(
        'lock_timeout','target_take_changed','temporary_database_failure','enqueue_lease_expired')
       WHEN 'exhausted' THEN delivery_id IS NULL AND cause_code='claim_attempt_limit_reached' AND attempt_number=12
       ELSE false END)),
 ADD CONSTRAINT feedback_language_delivery_job_event_claim_fk
 FOREIGN KEY(claim_attempt_id,job_id,attempt_number)
 REFERENCES public.feedback_language_delivery_job_claim_attempts(id,job_id,attempt_number) ON DELETE RESTRICT;
CREATE UNIQUE INDEX IF NOT EXISTS feedback_language_delivery_job_one_terminal_idx
 ON public.feedback_language_delivery_materialization_job_events(job_id)
 WHERE event_kind IN('completed','closed_stale','exhausted');
CREATE UNIQUE INDEX IF NOT EXISTS feedback_language_delivery_job_one_retry_per_attempt_idx
 ON public.feedback_language_delivery_materialization_job_events(job_id,attempt_number,event_kind)
 WHERE event_kind='failed_retryable';

CREATE OR REPLACE FUNCTION public.guard_feedback_language_delivery_job_event_v2_v1()
RETURNS trigger LANGUAGE plpgsql SET search_path=public AS $$
DECLARE expected_sha256 text;
BEGIN
 IF NEW.contract_version IS DISTINCT FROM 'feedback-language-delivery-job-event-v2'
    OR NEW.claim_attempt_id IS NULL THEN
  RAISE EXCEPTION 'FEEDBACK_LANGUAGE_DELIVERY_JOB_EVENT_INVALID';
 END IF;
 expected_sha256:=public.exercise_json_sha256_v1(jsonb_build_object(
  'id',NEW.id,'job_id',NEW.job_id,'event_kind',NEW.event_kind,
  'delivery_id',NEW.delivery_id,'attempt_number',NEW.attempt_number,
  'claim_attempt_id',NEW.claim_attempt_id,'contract_version',NEW.contract_version,
  'cause_code',NEW.cause_code,'idempotency_key',NEW.idempotency_key,
  'created_at',NEW.created_at,'serves_user',NEW.serves_user,
  'dataset_eligible',NEW.dataset_eligible));
 -- The database owns this digest.  Callers cannot omit a structural field or
 -- smuggle a digest computed over a weaker subset of the immutable event.
 NEW.event_sha256:=expected_sha256;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS feedback_language_delivery_job_event_v2_insert
 ON public.feedback_language_delivery_materialization_job_events;
CREATE TRIGGER feedback_language_delivery_job_event_v2_insert
 BEFORE INSERT ON public.feedback_language_delivery_materialization_job_events
 FOR EACH ROW EXECUTE FUNCTION public.guard_feedback_language_delivery_job_event_v2_v1();

CREATE TABLE IF NOT EXISTS public.feedback_language_delivery_job_due_heads (
 job_id uuid PRIMARY KEY REFERENCES public.feedback_language_delivery_materialization_jobs(id) ON DELETE RESTRICT,
 scheduling_state text NOT NULL CHECK(scheduling_state IN('pending','terminal')),
 next_probe_at timestamptz NULL, last_probe_at timestamptz NULL,
 probe_count bigint NOT NULL DEFAULT 0 CHECK(probe_count>=0), updated_at timestamptz NOT NULL,
 serves_user boolean NOT NULL DEFAULT false CHECK(NOT serves_user),
 dataset_eligible boolean NOT NULL DEFAULT false CHECK(NOT dataset_eligible),
 CHECK((scheduling_state='pending' AND next_probe_at IS NOT NULL) OR
       (scheduling_state='terminal' AND next_probe_at IS NULL)),
 CHECK((probe_count=0 AND last_probe_at IS NULL) OR (probe_count>0 AND last_probe_at IS NOT NULL)),
 CHECK(last_probe_at IS NULL OR last_probe_at<=updated_at)
);
CREATE INDEX IF NOT EXISTS feedback_language_delivery_due_pending_idx
 ON public.feedback_language_delivery_job_due_heads(next_probe_at,job_id)
 WHERE scheduling_state='pending';

CREATE OR REPLACE FUNCTION public.create_feedback_language_delivery_due_head_v1()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
BEGIN
 INSERT INTO public.feedback_language_delivery_job_due_heads(job_id,scheduling_state,next_probe_at,
  last_probe_at,probe_count,updated_at)
 VALUES(NEW.id,'pending',NEW.created_at,NULL,0,NEW.created_at)
 ON CONFLICT(job_id) DO NOTHING;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS feedback_language_delivery_job_due_head_insert
 ON public.feedback_language_delivery_materialization_jobs;
CREATE TRIGGER feedback_language_delivery_job_due_head_insert
 AFTER INSERT ON public.feedback_language_delivery_materialization_jobs
 FOR EACH ROW EXECUTE FUNCTION public.create_feedback_language_delivery_due_head_v1();
INSERT INTO public.feedback_language_delivery_job_due_heads(job_id,scheduling_state,next_probe_at,last_probe_at,probe_count,updated_at)
SELECT j.id,CASE WHEN EXISTS(SELECT 1 FROM public.feedback_language_delivery_materialization_job_events e
 WHERE e.job_id=j.id AND e.event_kind IN('completed','closed_stale','exhausted')) THEN 'terminal' ELSE 'pending' END,
 CASE WHEN EXISTS(SELECT 1 FROM public.feedback_language_delivery_materialization_job_events e
 WHERE e.job_id=j.id AND e.event_kind IN('completed','closed_stale','exhausted')) THEN NULL ELSE j.created_at END,
 NULL,0,j.created_at FROM public.feedback_language_delivery_materialization_jobs j
ON CONFLICT(job_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.feedback_language_delivery_scan_runs (
 run_id uuid PRIMARY KEY, worker_id_sha256 text NOT NULL CHECK(worker_id_sha256 ~ '^[0-9a-f]{64}$'),
 run_contract_version text NOT NULL CHECK(run_contract_version='feedback-language-delivery-scan-run-v1'),
 started_at timestamptz NOT NULL, scanner_started_at timestamptz NULL,
 finished_at timestamptz NULL, result_code text NULL,
 result_sha256 text NULL CHECK(result_sha256 IS NULL OR result_sha256 ~ '^[0-9a-f]{64}$'),
 serves_user boolean NOT NULL DEFAULT false CHECK(NOT serves_user),
 dataset_eligible boolean NOT NULL DEFAULT false CHECK(NOT dataset_eligible),
 CHECK((finished_at IS NULL AND result_code IS NULL AND result_sha256 IS NULL)
    OR (finished_at>=started_at AND result_code IN('claimed','no_due_job','deferred_no_target',
       'skipped_contention','abandoned_before_scan','stalled_scan_halted') AND result_sha256 IS NOT NULL))
);
ALTER TABLE public.feedback_language_delivery_scan_runs DROP COLUMN IF EXISTS begin_idempotency_key;
CREATE INDEX IF NOT EXISTS feedback_language_delivery_scan_unfinished_idx
 ON public.feedback_language_delivery_scan_runs(scanner_started_at,run_id)
 WHERE scanner_started_at IS NOT NULL AND finished_at IS NULL;

CREATE TABLE IF NOT EXISTS public.feedback_language_delivery_stalled_scan_halt_receipts (
 receipt_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 receipt_contract_version text NOT NULL CHECK(receipt_contract_version='feedback-language-stalled-scan-halt-receipt-v1'),
 monitor_run_id uuid NOT NULL, observation_cutoff timestamptz NOT NULL,
 unfinished_count integer NOT NULL CHECK(unfinished_count>0), unfinished_set_sha256 text NOT NULL CHECK(unfinished_set_sha256 ~ '^[0-9a-f]{64}$'),
 oldest_started_at timestamptz NOT NULL, source_rollout_revision_id uuid NOT NULL REFERENCES public.mlc3_service_rollout_revisions(id) ON DELETE RESTRICT,
 halt_operation_id uuid NOT NULL REFERENCES public.mlc3_service_rollout_revisions(id) ON DELETE RESTRICT,
 disabled_state_sha256 text NOT NULL CHECK(disabled_state_sha256 ~ '^[0-9a-f]{64}$'),
 receipt_sha256 text NOT NULL UNIQUE CHECK(receipt_sha256 ~ '^[0-9a-f]{64}$'), created_at timestamptz NOT NULL,
 serves_user boolean NOT NULL DEFAULT false CHECK(NOT serves_user), dataset_eligible boolean NOT NULL DEFAULT false CHECK(NOT dataset_eligible),
 CHECK(oldest_started_at<observation_cutoff), UNIQUE(source_rollout_revision_id,unfinished_set_sha256)
);
CREATE TABLE IF NOT EXISTS public.feedback_language_delivery_take_arm_operations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), take_id uuid NOT NULL REFERENCES public.v2_sessions(id) ON DELETE RESTRICT,
 operation_key_sha256 text NOT NULL UNIQUE CHECK(operation_key_sha256 ~ '^[0-9a-f]{64}$'),
 idempotency_key text NOT NULL UNIQUE, armed_count integer NOT NULL CHECK(armed_count>=0),
 armed_set_sha256 text NOT NULL CHECK(armed_set_sha256 ~ '^[0-9a-f]{64}$'), result_payload jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), serves_user boolean NOT NULL DEFAULT false CHECK(NOT serves_user),
 dataset_eligible boolean NOT NULL DEFAULT false CHECK(NOT dataset_eligible)
);

CREATE OR REPLACE FUNCTION public.begin_feedback_language_delivery_scan_run_v1(
 p_run_id uuid,p_worker_id_sha256 text,p_idempotency_key text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE r public.feedback_language_delivery_scan_runs;
BEGIN
 IF p_worker_id_sha256 !~ '^[0-9a-f]{64}$'
    OR p_idempotency_key IS DISTINCT FROM 'delivery-scan-begin-v1:'||p_run_id::text||':'||p_worker_id_sha256 THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_DELIVERY_SCAN_INVALID'; END IF;
 SELECT * INTO r FROM public.feedback_language_delivery_scan_runs WHERE run_id=p_run_id;
 IF FOUND THEN
  IF r.worker_id_sha256<>p_worker_id_sha256 THEN
   RAISE EXCEPTION 'CONFIDENT_MOMENT_DELIVERY_SCAN_REPLAY_MISMATCH'; END IF;
 ELSE
  INSERT INTO public.feedback_language_delivery_scan_runs(run_id,worker_id_sha256,run_contract_version,
   started_at) VALUES(p_run_id,p_worker_id_sha256,'feedback-language-delivery-scan-run-v1',
   clock_timestamp()) RETURNING * INTO r;
 END IF;
 RETURN jsonb_build_object('scan_run_contract_version',r.run_contract_version,'run_id',r.run_id,
  'started_at',to_char(r.started_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),'dataset_eligible',false);
END $$;

CREATE OR REPLACE FUNCTION public.mark_feedback_language_delivery_scan_started_v1(
 p_run_id uuid,p_worker_id_sha256 text,p_idempotency_key text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE r public.feedback_language_delivery_scan_runs;
BEGIN
 IF p_idempotency_key IS DISTINCT FROM 'delivery-scan-start-v1:'||p_run_id::text||':'||p_worker_id_sha256 THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_DELIVERY_SCAN_INVALID'; END IF;
 SELECT * INTO STRICT r FROM public.feedback_language_delivery_scan_runs WHERE run_id=p_run_id FOR UPDATE NOWAIT;
 IF r.worker_id_sha256<>p_worker_id_sha256 OR r.finished_at IS NOT NULL THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_DELIVERY_SCAN_INVALID'; END IF;
 UPDATE public.feedback_language_delivery_scan_runs SET scanner_started_at=COALESCE(scanner_started_at,clock_timestamp())
  WHERE run_id=p_run_id RETURNING * INTO r;
 RETURN jsonb_build_object('run_id',r.run_id,'scanner_started_at',r.scanner_started_at,'dataset_eligible',false);
END $$;

CREATE OR REPLACE FUNCTION public.abandon_feedback_language_delivery_scan_run_v1(
 p_run_id uuid,p_worker_id_sha256 text,p_idempotency_key text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE r public.feedback_language_delivery_scan_runs; finished timestamptz; digest text;
BEGIN
 IF p_idempotency_key IS DISTINCT FROM 'delivery-scan-abandon-v1:'||p_run_id::text||':'||p_worker_id_sha256 THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_DELIVERY_SCAN_INVALID'; END IF;
 SELECT * INTO STRICT r FROM public.feedback_language_delivery_scan_runs WHERE run_id=p_run_id FOR UPDATE NOWAIT;
 IF r.worker_id_sha256<>p_worker_id_sha256 OR r.scanner_started_at IS NOT NULL THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_DELIVERY_SCAN_INVALID'; END IF;
 IF r.finished_at IS NULL THEN
  finished:=clock_timestamp(); digest:=public.exercise_json_sha256_v1(jsonb_build_object('run',r.run_id,'result','abandoned_before_scan','finished',finished));
  UPDATE public.feedback_language_delivery_scan_runs SET finished_at=finished,result_code='abandoned_before_scan',result_sha256=digest WHERE run_id=r.run_id RETURNING * INTO r;
 END IF;
 RETURN jsonb_build_object('run_id',r.run_id,'result_code',r.result_code,'dataset_eligible',false);
END $$;

CREATE OR REPLACE FUNCTION public.require_feedback_language_delivery_scan_authority_v1(
 p_acquisition_principal_id uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER STABLE SET search_path=public AS $$
DECLARE rollout public.mlc3_service_rollout_revisions; enrollment public.mlc3_service_enrollment_revisions;
 receipt_id uuid; policy_id uuid; wall_now timestamptz:=clock_timestamp();
BEGIN
 SELECT * INTO rollout FROM public.mlc3_service_rollout_revisions r ORDER BY r.revision_number DESC LIMIT 1;
 IF rollout.id IS NULL OR rollout.rollout_state NOT IN('explicit_cohort','generally_available')
    OR rollout.effective_at>wall_now THEN RAISE EXCEPTION 'MLC3_ROLLOUT_NOT_ACTIVE'; END IF;
 SELECT * INTO enrollment FROM public.mlc3_service_enrollment_revisions e
  WHERE e.acquisition_principal_id=p_acquisition_principal_id ORDER BY e.revision_number DESC LIMIT 1;
 IF enrollment.id IS NULL OR enrollment.enrollment_state<>'active' OR enrollment.rollout_revision_id<>rollout.id
    OR enrollment.operation_mode<>(CASE rollout.rollout_state WHEN 'explicit_cohort' THEN 'cohort_service' ELSE 'general_service' END)
    OR (rollout.rollout_state='explicit_cohort' AND NOT EXISTS(SELECT 1 FROM public.mlc3_service_cohort_members m
      WHERE m.cohort_set_id=rollout.cohort_set_id AND m.acquisition_principal_id=p_acquisition_principal_id)) THEN
  RAISE EXCEPTION 'MLC3_CURRENT_ENROLLMENT_REQUIRED'; END IF;
 SELECT receipt.id,receipt.policy_id INTO receipt_id,policy_id FROM public.processing_authorization_receipts receipt
 JOIN public.processing_policy_versions policy ON policy.id=receipt.policy_id AND policy.status='active'
  AND policy.activated_at<=wall_now AND (policy.retired_at IS NULL OR policy.retired_at>wall_now)
 WHERE receipt.acquisition_principal_id=p_acquisition_principal_id
  AND NOT EXISTS(SELECT 1 FROM public.processing_service_blocks b WHERE b.acquisition_principal_id=p_acquisition_principal_id AND b.effective_at<=wall_now)
  AND NOT EXISTS(SELECT 1 FROM public.data_purge_requests p WHERE p.acquisition_principal_id=p_acquisition_principal_id AND p.state<>'done')
  AND NOT EXISTS(SELECT 1 FROM (VALUES('personalized_exercise_recommendation'::text),('coach_review'::text)) required(purpose_id)
    WHERE NOT EXISTS(SELECT 1 FROM public.processing_authorization_receipt_purposes rp
      JOIN public.processing_policy_purposes pp ON pp.policy_id=receipt.policy_id AND pp.purpose_id=rp.purpose_id
      JOIN public.processing_purpose_registry registry ON registry.id=rp.purpose_id AND registry.operational AND registry.authorizes_processing
      WHERE rp.receipt_id=receipt.id AND rp.purpose_id=required.purpose_id))
 ORDER BY receipt.accepted_at DESC,receipt.id DESC LIMIT 1;
 IF receipt_id IS NULL OR policy_id<>rollout.required_policy_id OR enrollment.authorization_receipt_id<>receipt_id
    OR enrollment.authorization_policy_id<>policy_id THEN RAISE EXCEPTION 'MLC3_DUAL_PURPOSE_AUTHORITY_REQUIRED'; END IF;
 RETURN;
END $$;

CREATE OR REPLACE FUNCTION public.scan_due_feedback_language_delivery_jobs_v1(
 p_run_id uuid,p_worker_id_sha256 text,p_limit integer,p_lease_seconds integer,p_server_budget_ms integer)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE r public.feedback_language_delivery_scan_runs; cutoff timestamptz; probe_cutoff timestamptz;
 frozen_ids uuid[]; jid uuid; due public.feedback_language_delivery_job_due_heads;
 j public.feedback_language_delivery_materialization_jobs; a public.confident_moment_bundle_attachments;
 revision public.feedback_revisions; affected_take uuid;
 target_take uuid; rederived_target_take uuid; target_identity_sha256 text;
 rederived_target_identity_sha256 text; attempt_no integer; claim_id uuid; terminal_event_id uuid;
 claimed_at timestamptz; lease_until timestamptz;
 jobs jsonb:='[]'::jsonb; item_results jsonb:='[]'::jsonb; final_code text:='no_due_job';
 frozen_count integer:=0; acquired integer:=0; contended integer:=0; current_miss integer:=0;
 finished timestamptz; run_hash text; got boolean;
BEGIN
 IF p_limit IS DISTINCT FROM 3 OR p_lease_seconds NOT BETWEEN 1 AND 3600
    OR p_server_budget_ms NOT BETWEEN 1 AND 1500 OR p_worker_id_sha256 !~ '^[0-9a-f]{64}$' THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_DELIVERY_SCAN_INVALID'; END IF;
 PERFORM set_config('lock_timeout',LEAST(100,GREATEST(1,p_server_budget_ms/10))::text||'ms',true);
 cutoff:=clock_timestamp()+make_interval(secs=>p_server_budget_ms::double precision/1000.0);
 probe_cutoff:=clock_timestamp();
 BEGIN
  SELECT * INTO STRICT r FROM public.feedback_language_delivery_scan_runs WHERE run_id=p_run_id FOR UPDATE NOWAIT;
 EXCEPTION WHEN lock_not_available THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_DELIVERY_SCAN_RUN_BUSY';
 END;
 IF r.worker_id_sha256<>p_worker_id_sha256 OR r.scanner_started_at IS NULL OR r.finished_at IS NOT NULL THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_DELIVERY_SCAN_INVALID'; END IF;
 SELECT COALESCE(array_agg(x.job_id ORDER BY x.next_probe_at,x.job_id),ARRAY[]::uuid[]) INTO frozen_ids
 FROM (SELECT h.job_id,h.next_probe_at FROM public.feedback_language_delivery_job_due_heads h
       WHERE h.scheduling_state='pending' AND h.next_probe_at<=probe_cutoff
       ORDER BY h.next_probe_at,h.job_id LIMIT 3) x;
 frozen_count:=cardinality(frozen_ids);
 FOREACH jid IN ARRAY frozen_ids LOOP
  IF clock_timestamp()>=cutoff THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_DELIVERY_SCAN_SERVER_BUDGET_EXCEEDED'; END IF;
  BEGIN
   SELECT * INTO due FROM public.feedback_language_delivery_job_due_heads h
    WHERE h.job_id=jid AND h.scheduling_state='pending' AND h.next_probe_at<=probe_cutoff FOR UPDATE NOWAIT;
  EXCEPTION WHEN lock_not_available THEN
   contended:=contended+1; item_results:=item_results||jsonb_build_array(jsonb_build_object('result','contention_nowait'));
   CONTINUE;
  END;
  IF NOT FOUND THEN current_miss:=current_miss+1; item_results:=item_results||jsonb_build_array(jsonb_build_object('result','currentness_miss')); CONTINUE; END IF;
  acquired:=acquired+1;
  -- The due-head PK is the only NOWAIT probe counted as D36 contention.
  -- Everything below follows the same 10..140 writer-shared graph as the
  -- materializer before a mutable job/claim row is touched.
  SELECT * INTO j FROM public.feedback_language_delivery_materialization_jobs WHERE id=jid;
  IF NOT FOUND OR EXISTS(SELECT 1 FROM public.feedback_language_delivery_materialization_job_events e
    WHERE e.job_id=jid AND e.event_kind IN('completed','closed_stale','exhausted')) THEN
   current_miss:=current_miss+1;
   item_results:=item_results||jsonb_build_array(jsonb_build_object('result','currentness_miss'));
   CONTINUE; END IF;
  SELECT * INTO STRICT a FROM public.confident_moment_bundle_attachments WHERE id=j.bundle_attachment_id;
  SELECT * INTO STRICT revision FROM public.feedback_revisions WHERE id=j.revision_id;
  SELECT later.id INTO target_take FROM public.v2_sessions source
   JOIN public.v2_sessions later ON later.project_id=source.project_id AND later.owner_principal_id=source.owner_principal_id
    AND later.id<>source.id AND later.take_index>source.take_index
   WHERE source.id=a.take_id ORDER BY later.take_index,later.id LIMIT 1;
  target_identity_sha256:=public.exercise_json_sha256_v1(jsonb_build_object(
   'source_take_id',a.take_id,'target_take_id',target_take));
  IF NOT pg_try_advisory_xact_lock(hashtextextended('mlc3-rollout-policy-v2',0))
     OR NOT pg_try_advisory_xact_lock(hashtextextended('mlc3-service-principal:'||j.acquisition_principal_id::text,0))
     OR NOT pg_try_advisory_xact_lock(hashtextextended('confident-moment-project-inventory:'||a.project_id::text,0)) THEN
   item_results:=item_results||jsonb_build_array(jsonb_build_object('result','advisory_contention')); CONTINUE;
  END IF;
  got:=true;
  FOR affected_take IN SELECT id FROM (SELECT a.take_id id UNION SELECT target_take WHERE target_take IS NOT NULL) x ORDER BY id LOOP
   got:=got AND pg_try_advisory_xact_lock(hashtextextended('confident-moment-take-inventory:'||affected_take::text,0));
  END LOOP;
  FOR affected_take IN SELECT id FROM (SELECT a.take_id id UNION SELECT target_take WHERE target_take IS NOT NULL) x ORDER BY id LOOP
   got:=got AND pg_try_advisory_xact_lock(hashtextextended('feedback-v3-membership-inventory:'||a.project_id::text||':'||affected_take::text,0));
  END LOOP;
  IF NOT got THEN item_results:=item_results||jsonb_build_array(jsonb_build_object('result','advisory_contention')); CONTINUE; END IF;
  IF target_take IS NOT NULL THEN
   got:=pg_try_advisory_xact_lock(hashtextextended('feedback-language-delivery-subject:'||j.acquisition_principal_id::text||':'||target_take::text||':'||a.feedback_membership_id::text||':'||a.attached_candidate_id::text,0));
   IF NOT got THEN item_results:=item_results||jsonb_build_array(jsonb_build_object('result','advisory_contention')); CONTINUE; END IF;
  END IF;
  got:=pg_try_advisory_xact_lock(hashtextextended('feedback-language-revision-head:'||a.feedback_membership_id::text||':'||a.attached_candidate_id::text||':'||revision.rater_id::text,0));
  IF NOT got THEN item_results:=item_results||jsonb_build_array(jsonb_build_object('result','advisory_contention')); CONTINUE; END IF;
  got:=pg_try_advisory_xact_lock(hashtextextended('confident-moment-delivery-job:'||jid::text,0));
  IF NOT got THEN item_results:=item_results||jsonb_build_array(jsonb_build_object('result','advisory_contention')); CONTINUE; END IF;
  SELECT later.id INTO rederived_target_take FROM public.v2_sessions source
   JOIN public.v2_sessions later ON later.project_id=source.project_id
    AND later.owner_principal_id=source.owner_principal_id
    AND later.id<>source.id AND later.take_index>source.take_index
   WHERE source.id=a.take_id ORDER BY later.take_index,later.id LIMIT 1;
  rederived_target_identity_sha256:=public.exercise_json_sha256_v1(jsonb_build_object(
   'source_take_id',a.take_id,'target_take_id',rederived_target_take));
  IF rederived_target_identity_sha256<>target_identity_sha256 THEN
   current_miss:=current_miss+1;
   item_results:=item_results||jsonb_build_array(jsonb_build_object('result','currentness_miss'));
   CONTINUE;
  END IF;
  SELECT * INTO j FROM public.feedback_language_delivery_materialization_jobs WHERE id=jid FOR UPDATE;
  IF NOT FOUND OR EXISTS(SELECT 1 FROM public.feedback_language_delivery_materialization_job_events e
    WHERE e.job_id=jid AND e.event_kind IN('completed','closed_stale','exhausted')) THEN
   current_miss:=current_miss+1;
   item_results:=item_results||jsonb_build_array(jsonb_build_object('result','currentness_miss'));
   CONTINUE; END IF;
  BEGIN
   PERFORM public.require_feedback_language_delivery_scan_authority_v1(j.acquisition_principal_id);
  EXCEPTION WHEN OTHERS THEN
   IF SQLERRM IN('MLC3_ROLLOUT_NOT_ACTIVE','MLC3_CURRENT_ENROLLMENT_REQUIRED',
      'MLC3_COHORT_MEMBERSHIP_REQUIRED','MLC3_DUAL_PURPOSE_AUTHORITY_REQUIRED') THEN
    SELECT h.current_claim_attempt_id,h.attempt_count
      INTO claim_id,attempt_no
      FROM public.feedback_language_delivery_job_claim_heads h
     WHERE h.job_id=jid FOR UPDATE;
    IF NOT FOUND THEN
     attempt_no:=1; claim_id:=gen_random_uuid(); claimed_at:=clock_timestamp();
     lease_until:=claimed_at+make_interval(secs=>p_lease_seconds);
     INSERT INTO public.feedback_language_delivery_job_claim_attempts(
       id,job_id,attempt_number,worker_id,claimed_at,lease_expires_at,claim_sha256)
     VALUES(claim_id,jid,attempt_no,p_worker_id_sha256,claimed_at,lease_until,
       public.exercise_json_sha256_v1(jsonb_build_object(
        'job',jid,'attempt',attempt_no,'worker',p_worker_id_sha256,
        'claimed_at',claimed_at,'lease_expires_at',lease_until,
        'target_take',target_take,'policy','feedback-language-delivery-claim-v1')));
     INSERT INTO public.feedback_language_delivery_job_claim_heads(
       job_id,current_claim_attempt_id,attempt_count,lease_expires_at,updated_at)
     VALUES(jid,claim_id,attempt_no,lease_until,claimed_at);
    END IF;
    terminal_event_id:=gen_random_uuid();
    INSERT INTO public.feedback_language_delivery_materialization_job_events(
      id,job_id,event_kind,delivery_id,attempt_number,claim_attempt_id,
      contract_version,cause_code,event_sha256,idempotency_key,created_at)
    VALUES(terminal_event_id,jid,'closed_stale',NULL,attempt_no,claim_id,
      'feedback-language-delivery-job-event-v2','authority_withdrawn',
      repeat('0',64),'feedback-language-delivery-authority-closed:'||jid::text,
      clock_timestamp());
    UPDATE public.feedback_language_delivery_job_due_heads
       SET scheduling_state='terminal',next_probe_at=NULL,
           last_probe_at=probe_cutoff,probe_count=probe_count+1,
           updated_at=clock_timestamp()
     WHERE job_id=jid;
    UPDATE public.feedback_language_delivery_materialization_jobs
       SET job_state='closed_stale',attempt_count=attempt_no WHERE id=jid;
    item_results:=item_results||jsonb_build_array(jsonb_build_object(
      'result','closed_stale','cause_code','authority_withdrawn'));
    CONTINUE;
   END IF;
   RAISE;
  END;
  IF target_take IS NULL THEN
   UPDATE public.feedback_language_delivery_job_due_heads SET last_probe_at=probe_cutoff,
    probe_count=probe_count+1,next_probe_at=probe_cutoff+LEAST(interval '24 hours',interval '15 minutes' * power(2,LEAST(probe_count,7))::double precision),
    updated_at=probe_cutoff WHERE job_id=jid;
   final_code:='deferred_no_target'; item_results:=item_results||jsonb_build_array(jsonb_build_object('result','deferred_no_target')); CONTINUE;
  END IF;
  SELECT h.attempt_count,h.lease_expires_at INTO attempt_no,lease_until
   FROM public.feedback_language_delivery_job_claim_heads h WHERE h.job_id=jid FOR UPDATE;
  IF FOUND AND lease_until>probe_cutoff THEN item_results:=item_results||jsonb_build_array(jsonb_build_object('result','active_lease')); CONTINUE; END IF;
  IF attempt_no=12 THEN
   INSERT INTO public.feedback_language_delivery_materialization_job_events(job_id,event_kind,delivery_id,attempt_number,
    claim_attempt_id,contract_version,cause_code,event_sha256,idempotency_key)
   SELECT jid,'exhausted',NULL,12,h.current_claim_attempt_id,'feedback-language-delivery-job-event-v2','claim_attempt_limit_reached',
    public.exercise_json_sha256_v1(jsonb_build_object('job',jid,'attempt',12,'event','exhausted')),
    'feedback-language-delivery-exhausted:'||jid::text FROM public.feedback_language_delivery_job_claim_heads h WHERE h.job_id=jid
   ON CONFLICT DO NOTHING;
   UPDATE public.feedback_language_delivery_job_due_heads SET scheduling_state='terminal',next_probe_at=NULL,updated_at=probe_cutoff WHERE job_id=jid;
   UPDATE public.feedback_language_delivery_materialization_jobs
    SET job_state='exhausted',attempt_count=12 WHERE id=jid;
   item_results:=item_results||jsonb_build_array(jsonb_build_object('result','exhausted')); CONTINUE;
  END IF;
  attempt_no:=COALESCE(attempt_no,0)+1; claim_id:=gen_random_uuid(); claimed_at:=clock_timestamp();
  lease_until:=claimed_at+make_interval(secs=>p_lease_seconds);
  INSERT INTO public.feedback_language_delivery_job_claim_attempts(id,job_id,attempt_number,worker_id,claimed_at,lease_expires_at,claim_sha256)
   VALUES(claim_id,jid,attempt_no,p_worker_id_sha256,claimed_at,lease_until,
    public.exercise_json_sha256_v1(jsonb_build_object('job',jid,'attempt',attempt_no,'worker',p_worker_id_sha256,
      'claimed_at',claimed_at,'lease_expires_at',lease_until,'target_take',target_take,'policy','feedback-language-delivery-claim-v1')));
  INSERT INTO public.feedback_language_delivery_job_claim_heads(job_id,current_claim_attempt_id,attempt_count,lease_expires_at,updated_at)
   VALUES(jid,claim_id,attempt_no,lease_until,claimed_at)
   ON CONFLICT(job_id) DO UPDATE SET current_claim_attempt_id=EXCLUDED.current_claim_attempt_id,
    attempt_count=EXCLUDED.attempt_count,lease_expires_at=EXCLUDED.lease_expires_at,updated_at=EXCLUDED.updated_at;
  UPDATE public.feedback_language_delivery_materialization_jobs
   SET job_state='pending',attempt_count=attempt_no WHERE id=jid;
  UPDATE public.feedback_language_delivery_job_due_heads SET last_probe_at=claimed_at,probe_count=probe_count+1,
   next_probe_at=lease_until,updated_at=claimed_at WHERE job_id=jid;
  jobs:=jobs||jsonb_build_array(jsonb_build_object('job_id',jid));
  item_results:=item_results||jsonb_build_array(jsonb_build_object('result','claimed'));
 END LOOP;
 IF jsonb_array_length(jobs)>0 THEN final_code:='claimed';
 ELSIF contended>0 THEN final_code:='skipped_contention'; END IF;
 IF clock_timestamp()>=cutoff THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_DELIVERY_SCAN_SERVER_BUDGET_EXCEEDED'; END IF;
 finished:=clock_timestamp(); run_hash:=public.exercise_json_sha256_v1(jsonb_build_object('run',p_run_id,'worker',p_worker_id_sha256,
  'finished',finished,'result',final_code,'frozen_window_count',frozen_count,'acquired_count',acquired,
  'contention_nowait_count',contended,'currentness_miss_count',current_miss));
 UPDATE public.feedback_language_delivery_scan_runs SET finished_at=finished,result_code=final_code,result_sha256=run_hash WHERE run_id=p_run_id;
 IF clock_timestamp()>=cutoff THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_DELIVERY_SCAN_SERVER_BUDGET_EXCEEDED'; END IF;
 RETURN jsonb_build_object('delivery_job_claim_contract_version','feedback-language-delivery-claim-v1','jobs',jobs,
  'has_more',frozen_count=3,
  'frozen_window_count',frozen_count,'acquired_count',acquired,'contention_nowait_count',contended,
  'currentness_miss_count',current_miss,'item_results',item_results,'dataset_eligible',false);
END $$;
DROP FUNCTION IF EXISTS public.claim_due_feedback_language_delivery_jobs_v1(uuid,text,integer,integer,integer);

-- D38--D43: internal, read-only authority for the exact source clip.  The
-- browser never receives this object; the application invokes the same
-- resolver before and after the bounded private-object read.
CREATE OR REPLACE FUNCTION public.resolve_confident_moment_source_playback_authority_v1(
 p_acquisition_principal_id uuid,p_bundle_id uuid,p_bundle_attachment_id uuid
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE started timestamptz:=clock_timestamp(); a public.confident_moment_bundle_attachments;
 m public.feedback_v3_memberships; span public.evidence_spans;
 lineage public.exercise_audio_lineages; media public.processing_audio_objects;
 auth jsonb; before_hash text; after_hash text; result_body jsonb; authority_hash text;
 source_snippet_id uuid;
BEGIN
 PERFORM set_config('lock_timeout','50ms',true);
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_USER_READ_RETRY_REQUIRED'; END IF;
 IF NOT pg_try_advisory_xact_lock(hashtextextended('mlc3-rollout-policy-v2',0))
    OR NOT pg_try_advisory_xact_lock(hashtextextended('mlc3-service-principal:'||p_acquisition_principal_id::text,0)) THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_USER_READ_RETRY_REQUIRED'; END IF;
 SELECT * INTO STRICT a FROM public.confident_moment_bundle_attachments x
  WHERE x.id=p_bundle_attachment_id AND x.bundle_subject_candidate_id=p_bundle_id
    AND x.acquisition_principal_id=p_acquisition_principal_id;
 SELECT * INTO STRICT m FROM public.feedback_v3_memberships x
  WHERE x.id=a.feedback_membership_id AND x.acquisition_principal_id=p_acquisition_principal_id;
 IF NOT pg_try_advisory_xact_lock(hashtextextended('confident-moment-project-inventory:'||a.project_id::text,0))
    OR NOT pg_try_advisory_xact_lock(hashtextextended('confident-moment-take-inventory:'||a.take_id::text,0))
    OR NOT pg_try_advisory_xact_lock(hashtextextended('feedback-v3-membership-inventory:'||a.project_id::text||':'||a.take_id::text,0))
    OR NOT pg_try_advisory_xact_lock(hashtextextended('confident-moment-bundle-subject:'||m.id::text||':'||p_bundle_id::text,0)) THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_USER_READ_RETRY_REQUIRED'; END IF;
 SELECT * INTO STRICT span FROM public.evidence_spans x WHERE x.id=a.attached_evidence_span_id
  AND x.owner_principal_id=p_acquisition_principal_id AND x.project_id=a.project_id AND x.take_id=a.take_id
  AND x.start_ms IS NOT NULL AND x.end_ms>x.start_ms;
 SELECT item.snippet_id INTO STRICT source_snippet_id FROM public.feedback_v3_membership_items item
  WHERE item.membership_id=m.id AND item.candidate_id=a.attached_candidate_id
    AND item.evidence_span_id=span.id AND item.selected AND item.eligibility='eligible';
 SELECT l.* INTO STRICT lineage FROM public.exercise_audio_lineages l
  WHERE l.acquisition_principal_id=p_acquisition_principal_id AND l.snippet_id=source_snippet_id
    AND l.start_offset_ms=span.start_ms AND l.duration_ms=span.end_ms-span.start_ms
  ORDER BY l.created_at DESC,l.id DESC LIMIT 1;
 SELECT * INTO STRICT media FROM public.processing_audio_objects x
  WHERE x.id=lineage.processing_audio_object_id AND x.acquisition_principal_id=p_acquisition_principal_id
    AND x.recording_attempt_id=lineage.recording_attempt_id AND x.storage_provider='r2'
    AND x.exact_bytes_sha256=lineage.exact_audio_sha256 AND x.byte_size=lineage.object_byte_size;
 before_hash:=public.exercise_json_sha256_v1(jsonb_build_object('attachment',a.id,'membership',m.id,
  'candidate',a.attached_candidate_id,'span',span.id,'presentation',a.canonical_feedback_presentation_id,
  'attempt',lineage.recording_attempt_id,'lineage',lineage.id,'media',media.id,'bucket',media.bucket,
  'key',media.object_key,'size',media.byte_size,'hash',media.exact_bytes_sha256));
 IF NOT pg_try_advisory_xact_lock(hashtextextended('mlc3-speaker-attempt:'||lineage.recording_attempt_id::text,0))
    OR NOT pg_try_advisory_xact_lock(hashtextextended('mlc3-processing-audio-object:'||media.id::text,0)) THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_USER_READ_RETRY_REQUIRED'; END IF;
 BEGIN
  PERFORM 1 FROM public.confident_moment_bundle_attachments WHERE id=a.id FOR SHARE NOWAIT;
  PERFORM 1 FROM public.processing_audio_objects WHERE id=media.id FOR SHARE NOWAIT;
 EXCEPTION WHEN lock_not_available THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_USER_READ_RETRY_REQUIRED'; END;
 SELECT * INTO STRICT media FROM public.processing_audio_objects x WHERE x.id=media.id
  AND x.deleted_at IS NULL AND x.storage_provider='r2' AND x.byte_size BETWEEN 1 AND 26214400
  AND x.exact_bytes_sha256=lineage.exact_audio_sha256 AND x.byte_size=lineage.object_byte_size;
 IF EXISTS(SELECT 1 FROM public.processing_audio_object_deletion_events d WHERE d.audio_object_id=media.id)
    OR EXISTS(SELECT 1 FROM public.data_purge_requests p WHERE p.acquisition_principal_id=p_acquisition_principal_id AND p.state<>'done') THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_SOURCE_MEDIA_POLICY_INVALID'; END IF;
 auth:=public.require_mlc3_service_access_v2(p_acquisition_principal_id,NULL,NULL);
 PERFORM public.require_feedback_v3_service_membership_live_v1(m.id,p_acquisition_principal_id);
 after_hash:=public.exercise_json_sha256_v1(jsonb_build_object('attachment',a.id,'membership',m.id,
  'candidate',a.attached_candidate_id,'span',span.id,'presentation',a.canonical_feedback_presentation_id,
  'attempt',lineage.recording_attempt_id,'lineage',lineage.id,'media',media.id,'bucket',media.bucket,
  'key',media.object_key,'size',media.byte_size,'hash',media.exact_bytes_sha256));
 IF after_hash<>before_hash OR clock_timestamp()-started>=interval '500 milliseconds' THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_USER_READ_RETRY_REQUIRED'; END IF;
 result_body:=jsonb_build_object('contract_version','confident-moment-source-playback-authority-v1',
  'acquisition_principal_id',p_acquisition_principal_id,'bundle_id',p_bundle_id,
  'bundle_attachment_id',a.id,'project_id',a.project_id,'source_take_id',a.take_id,
  'feedback_membership_id',m.id,'feedback_candidate_id',a.attached_candidate_id,
  'evidence_span_id',span.id,'canonical_feedback_presentation_id',a.canonical_feedback_presentation_id,
  'recording_attempt_id',lineage.recording_attempt_id,'audio_lineage_id',lineage.id,
  'media_object_id',media.id,'bucket',media.bucket,'object_key',media.object_key,
  'object_version',media.exact_bytes_sha256,'byte_size',media.byte_size,
  'exact_bytes_sha256',media.exact_bytes_sha256,'content_type',media.content_type,
  'rollout_revision_id',auth->'rollout_revision_id','enrollment_revision_id',auth->'enrollment_revision_id',
  'policy_id',auth->'authorization_policy_id','authorization_receipt_id',auth->'authorization_receipt_id',
  'dataset_eligible',false);
 authority_hash:=public.exercise_json_sha256_v1(result_body);
 RETURN result_body||jsonb_build_object('authority_sha256',authority_hash);
EXCEPTION WHEN lock_not_available OR query_canceled THEN
 RAISE EXCEPTION 'CONFIDENT_MOMENT_USER_READ_RETRY_REQUIRED';
END $$;

CREATE OR REPLACE FUNCTION public.resolve_confident_moment_exercise_offer_v1(
 p_acquisition_principal_id uuid,p_bundle_id uuid,p_bundle_attachment_id uuid
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE a public.confident_moment_bundle_attachments; family text; binding public.feedback_v3_service_response_bindings;
 offer public.exercise_service_offers; receipt_id uuid; n integer; body jsonb; correlation text;
 source_lineage public.exercise_audio_lineages; source_binding_result jsonb;
BEGIN
 PERFORM set_config('lock_timeout','50ms',true);
 IF NOT pg_try_advisory_xact_lock(hashtextextended('mlc3-rollout-policy-v2',0))
    OR NOT pg_try_advisory_xact_lock(hashtextextended('mlc3-service-principal:'||p_acquisition_principal_id::text,0)) THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_USER_READ_RETRY_REQUIRED'; END IF;
 SELECT * INTO STRICT a FROM public.confident_moment_bundle_attachments x
  WHERE x.id=p_bundle_attachment_id AND x.bundle_subject_candidate_id=p_bundle_id
    AND x.acquisition_principal_id=p_acquisition_principal_id;
 SELECT feedback_family INTO STRICT family FROM public.feedback_v3_membership_items
  WHERE membership_id=a.feedback_membership_id AND candidate_id=a.attached_candidate_id;
 IF family<>'confident_voice' OR a.bundle_subject_kind<>'confidence_anchor'
    OR a.attached_candidate_id<>a.bundle_subject_candidate_id THEN
  body:=jsonb_build_object('contract_version','confident-moment-exercise-correlation-v2','status','not_supplied',
   'bundle_id',p_bundle_id,'bundle_attachment_id',a.id,'offer_id',NULL,'dataset_eligible',false);
  RETURN body||jsonb_build_object('correlation_sha256',public.exercise_json_sha256_v1(body));
 END IF;
 SELECT count(*),(array_agg(b.id ORDER BY b.created_at,b.id))[1] INTO n,binding.id
  FROM public.feedback_v3_service_response_bindings b WHERE b.acquisition_principal_id=p_acquisition_principal_id
   AND b.membership_id=a.feedback_membership_id AND b.candidate_id=a.attached_candidate_id
   AND b.feedback_exposure_id=a.canonical_feedback_presentation_id;
 IF n=0 THEN
  body:=jsonb_build_object('contract_version','confident-moment-exercise-correlation-v2','status','not_supplied',
   'bundle_id',p_bundle_id,'bundle_attachment_id',a.id,'offer_id',NULL,'dataset_eligible',false);
  RETURN body||jsonb_build_object('correlation_sha256',public.exercise_json_sha256_v1(body));
 ELSIF n<>1 THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_INVALID'; END IF;
 SELECT * INTO STRICT binding FROM public.require_feedback_v3_service_response_v1(binding.id,p_acquisition_principal_id,
  a.feedback_membership_id,a.attached_candidate_id,a.canonical_feedback_presentation_id);
 SELECT count(*),(array_agg(o.id ORDER BY o.prepared_at,o.id))[1] INTO n,offer.id FROM public.exercise_service_offers o
  WHERE o.acquisition_principal_id=p_acquisition_principal_id AND o.project_id=a.project_id
   AND o.source_take_id=a.take_id AND o.feedback_membership_id=a.feedback_membership_id
   AND o.feedback_candidate_id=a.attached_candidate_id AND o.feedback_response_binding_id=binding.id
   AND o.outcome='service_matched' AND o.serves_user AND NOT o.dataset_eligible;
 IF n=0 THEN
  body:=jsonb_build_object('contract_version','confident-moment-exercise-correlation-v2','status','not_supplied',
   'bundle_id',p_bundle_id,'bundle_attachment_id',a.id,'offer_id',NULL,'dataset_eligible',false);
  RETURN body||jsonb_build_object('correlation_sha256',public.exercise_json_sha256_v1(body));
 ELSIF n<>1 THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_INVALID'; END IF;
 SELECT * INTO STRICT offer FROM public.exercise_service_offers o WHERE o.id=offer.id;
 PERFORM public.require_exercise_service_offer_live_v1(offer.id,p_acquisition_principal_id);
 SELECT * INTO STRICT source_lineage FROM public.exercise_audio_lineages l
  WHERE l.id=offer.source_audio_lineage_id AND l.acquisition_principal_id=p_acquisition_principal_id;
 IF NOT pg_try_advisory_xact_lock(hashtextextended(
    'mlc3-speaker-attempt:'||source_lineage.recording_attempt_id::text,0)) THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_USER_READ_RETRY_REQUIRED'; END IF;
 source_binding_result:=public.resolve_confident_moment_target_speaker_binding_v1(
  p_acquisition_principal_id,source_lineage.recording_attempt_id,
  source_lineage.processing_audio_object_id,'source_clip',source_lineage.snippet_id,NULL);
 SELECT count(*),(array_agg(r.id ORDER BY r.created_at,r.id))[1] INTO n,receipt_id
  FROM public.exercise_service_acquisition_receipts r JOIN public.exercise_audio_lineages l
   ON l.processing_audio_object_id=r.processing_audio_object_id
  WHERE l.id=offer.source_audio_lineage_id AND r.acquisition_principal_id=p_acquisition_principal_id
   AND r.acquisition_kind='source_recording';
 IF n<>1 THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_INVALID'; END IF;
 body:=jsonb_build_object('contract_version','confident-moment-exercise-correlation-v2','status','available',
  'bundle_id',p_bundle_id,'bundle_attachment_id',a.id,'offer_id',offer.id,
  'feedback_response_binding_id',binding.id,'n1_candidate_set_id',offer.n1_candidate_set_id,
  'authorization_check_id',offer.authorization_check_id,'source_acquisition_receipt_id',receipt_id,
  'source_target_speaker_binding_id',(source_binding_result->>'target_speaker_binding_id')::uuid,
  'dataset_eligible',false);
 correlation:=public.exercise_json_sha256_v1(body);
 RETURN body||jsonb_build_object('correlation_sha256',correlation);
EXCEPTION WHEN lock_not_available OR query_canceled THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_USER_READ_RETRY_REQUIRED';
END $$;

-- D44--D46: stateless phase-3 decision.  Calling the phase-1 resolver here is
-- deliberate: it reacquires/rederives the complete writer-shared graph in this
-- transaction and retains those transaction locks through the return boundary.
CREATE OR REPLACE FUNCTION public.authorize_confident_moment_source_playback_emit_v1(
 p_acquisition_principal_id uuid,p_bundle_id uuid,p_bundle_attachment_id uuid,
 p_expected_authority_sha256 text,p_buffered_bytes_sha256 text,p_playback_request_id uuid
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE authority jsonb; authorized_at timestamptz; body jsonb;
BEGIN
 IF p_playback_request_id IS NULL
    OR COALESCE(p_expected_authority_sha256,'') !~ '^[0-9a-f]{64}$'
    OR COALESCE(p_buffered_bytes_sha256,'') !~ '^[0-9a-f]{64}$' THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_SOURCE_MEDIA_POLICY_INVALID'; END IF;
 authority:=public.resolve_confident_moment_source_playback_authority_v1(
  p_acquisition_principal_id,p_bundle_id,p_bundle_attachment_id);
 IF authority->>'authority_sha256'<>p_expected_authority_sha256 THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_USER_READ_RETRY_REQUIRED'; END IF;
 IF authority->>'exact_bytes_sha256'<>p_buffered_bytes_sha256 THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_SOURCE_MEDIA_POLICY_INVALID'; END IF;
 authorized_at:=clock_timestamp();
 body:=jsonb_build_object(
  'contract_version','confident-moment-source-playback-emit-v1',
  'playback_request_id',p_playback_request_id,
  'acquisition_principal_id',p_acquisition_principal_id,
  'bundle_id',p_bundle_id,'bundle_attachment_id',p_bundle_attachment_id,
  'authority_sha256',p_expected_authority_sha256,
  'buffered_bytes_sha256',p_buffered_bytes_sha256,
  'authorized_at',authorized_at,'emit_authorized',true,'dataset_eligible',false);
 RETURN body||jsonb_build_object(
  'emit_authorization_sha256',public.exercise_json_sha256_v1(body));
END $$;

CREATE OR REPLACE FUNCTION public.arm_feedback_language_delivery_jobs_for_take_v1(p_take_id uuid,p_idempotency_key text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE principal uuid; project uuid; armed integer; ids uuid[]; digest text; operation_key text;
 stored public.feedback_language_delivery_take_arm_operations; response jsonb;
BEGIN
 IF COALESCE(btrim(p_idempotency_key),'')='' THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_DELIVERY_ARM_INVALID'; END IF;
 SELECT owner_principal_id,project_id INTO STRICT principal,project FROM public.v2_sessions WHERE id=p_take_id;
 PERFORM pg_advisory_xact_lock(hashtextextended('confident-moment-delivery-arm:'||p_take_id::text,0));
 operation_key:=public.exercise_json_sha256_v1(jsonb_build_object('contract','feedback-language-delivery-take-arm-v1',
  'take_id',p_take_id,'promotion_idempotency_key',p_idempotency_key));
 SELECT * INTO stored FROM public.feedback_language_delivery_take_arm_operations WHERE operation_key_sha256=operation_key;
 IF FOUND THEN
  IF stored.take_id<>p_take_id OR stored.idempotency_key<>p_idempotency_key THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_DELIVERY_ARM_REPLAY_MISMATCH'; END IF;
  RETURN stored.result_payload;
 END IF;
 WITH affected AS (SELECT h.job_id FROM public.feedback_language_delivery_job_due_heads h
   JOIN public.feedback_language_delivery_materialization_jobs j ON j.id=h.job_id
   JOIN public.confident_moment_bundle_attachments a ON a.id=j.bundle_attachment_id
   JOIN public.v2_sessions s ON s.id=a.take_id
   WHERE h.scheduling_state='pending' AND j.acquisition_principal_id=principal AND s.project_id=project
     AND s.take_index<(SELECT take_index FROM public.v2_sessions WHERE id=p_take_id)
   ORDER BY h.job_id FOR UPDATE OF h), changed AS (
    UPDATE public.feedback_language_delivery_job_due_heads h SET next_probe_at=LEAST(h.next_probe_at,clock_timestamp()),updated_at=clock_timestamp()
    FROM affected x WHERE h.job_id=x.job_id RETURNING h.job_id)
 SELECT count(*),array_agg(job_id ORDER BY job_id) INTO armed,ids FROM changed;
 digest:=public.exercise_json_sha256_v1(to_jsonb(COALESCE(ids,ARRAY[]::uuid[])));
 response:=jsonb_build_object('delivery_job_arm_contract_version','feedback-language-delivery-take-arm-v1',
  'armed_count',COALESCE(armed,0),'armed_set_sha256',digest,'dataset_eligible',false);
 INSERT INTO public.feedback_language_delivery_take_arm_operations(take_id,operation_key_sha256,idempotency_key,
  armed_count,armed_set_sha256,result_payload) VALUES(p_take_id,operation_key,p_idempotency_key,COALESCE(armed,0),digest,response);
 RETURN response;
END $$;

CREATE OR REPLACE FUNCTION public.materialize_feedback_language_delivery_job_v1(p_job_id uuid,p_idempotency_key text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE j public.feedback_language_delivery_materialization_jobs; a public.confident_moment_bundle_attachments;
 h public.feedback_language_delivery_job_claim_heads; attempt public.feedback_language_delivery_job_claim_attempts;
 event_row public.feedback_language_delivery_materialization_job_events; revision public.feedback_revisions;
 d jsonb; target_take uuid; rederived_target_take uuid; now_at timestamptz; final_event_kind text; cause text; delivery_id uuid;
 affected_take uuid; event_key text; event_hash text; target_identity_sha256 text; rederived_target_identity_sha256 text;
 event_id uuid; event_created_at timestamptz;
BEGIN
 IF p_idempotency_key IS DISTINCT FROM 'materialize:'||p_job_id::text THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_DELIVERY_MATERIALIZE_REPLAY_MISMATCH';
 END IF;
 -- Immutable discovery precedes the shared D11 serializer graph.  No mutable
 -- job/head/delivery row is locked until all 10..130 serializers and the
 -- position-140 job serializer are held.
 SELECT * INTO STRICT j FROM public.feedback_language_delivery_materialization_jobs WHERE id=p_job_id;
 SELECT * INTO STRICT a FROM public.confident_moment_bundle_attachments WHERE id=j.bundle_attachment_id;
 SELECT * INTO STRICT revision FROM public.feedback_revisions WHERE id=j.revision_id;
 SELECT later.id INTO target_take FROM public.v2_sessions source JOIN public.v2_sessions later
  ON later.project_id=source.project_id AND later.owner_principal_id=source.owner_principal_id
  AND later.take_index>source.take_index WHERE source.id=a.take_id ORDER BY later.take_index,later.id LIMIT 1;
 target_identity_sha256:=public.exercise_json_sha256_v1(jsonb_build_object(
  'source_take_id',a.take_id,'target_take_id',target_take));
 PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-rollout-policy-v2',0));
 PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-service-principal:'||j.acquisition_principal_id::text,0));
 PERFORM pg_advisory_xact_lock(hashtextextended('confident-moment-project-inventory:'||a.project_id::text,0));
 FOR affected_take IN SELECT id FROM (SELECT a.take_id id UNION SELECT target_take WHERE target_take IS NOT NULL) x ORDER BY id LOOP
  PERFORM pg_advisory_xact_lock(hashtextextended('confident-moment-take-inventory:'||affected_take::text,0));
 END LOOP;
 FOR affected_take IN SELECT id FROM (SELECT a.take_id id UNION SELECT target_take WHERE target_take IS NOT NULL) x ORDER BY id LOOP
  PERFORM pg_advisory_xact_lock(hashtextextended('feedback-v3-membership-inventory:'||a.project_id::text||':'||affected_take::text,0));
 END LOOP;
 IF target_take IS NOT NULL THEN
  PERFORM pg_advisory_xact_lock(hashtextextended('feedback-language-delivery-subject:'||j.acquisition_principal_id::text||':'||target_take::text||':'||a.feedback_membership_id::text||':'||a.attached_candidate_id::text,0));
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('feedback-language-revision-head:'||a.feedback_membership_id::text||':'||a.attached_candidate_id::text||':'||revision.rater_id::text,0));
 PERFORM pg_advisory_xact_lock(hashtextextended('confident-moment-delivery-job:'||j.id::text,0));

 SELECT later.id INTO rederived_target_take FROM public.v2_sessions source JOIN public.v2_sessions later
  ON later.project_id=source.project_id AND later.owner_principal_id=source.owner_principal_id
  AND later.take_index>source.take_index WHERE source.id=a.take_id ORDER BY later.take_index,later.id LIMIT 1;
 rederived_target_identity_sha256:=public.exercise_json_sha256_v1(jsonb_build_object(
  'source_take_id',a.take_id,'target_take_id',rederived_target_take));

 SELECT * INTO STRICT j FROM public.feedback_language_delivery_materialization_jobs WHERE id=p_job_id FOR UPDATE;
 SELECT * INTO event_row FROM public.feedback_language_delivery_materialization_job_events
  WHERE job_id=j.id AND event_kind IN('completed','closed_stale','exhausted') FOR SHARE;
 IF FOUND THEN RETURN jsonb_build_object('job_id',j.id,'job_state',event_row.event_kind,
   'delivery_id',event_row.delivery_id,'cause_code',event_row.cause_code,'dataset_eligible',false); END IF;
 SELECT * INTO STRICT h FROM public.feedback_language_delivery_job_claim_heads WHERE job_id=j.id FOR UPDATE;
 SELECT * INTO STRICT attempt FROM public.feedback_language_delivery_job_claim_attempts
  WHERE id=h.current_claim_attempt_id AND job_id=j.id AND attempt_number=h.attempt_count FOR SHARE;
 SELECT * INTO event_row FROM public.feedback_language_delivery_materialization_job_events
  WHERE job_id=j.id AND attempt_number=h.attempt_count AND event_kind='failed_retryable' FOR SHARE;
 IF FOUND THEN RETURN jsonb_build_object('job_id',j.id,'job_state','failed_retryable','delivery_id',NULL,'cause_code',event_row.cause_code,'dataset_eligible',false); END IF;
 now_at:=clock_timestamp();
 IF h.lease_expires_at<=now_at THEN cause:='enqueue_lease_expired';
 ELSIF rederived_target_identity_sha256<>target_identity_sha256 THEN
  final_event_kind:='failed_retryable'; cause:='target_take_changed';
 ELSIF EXISTS(SELECT 1 FROM public.feedback_revisions successor WHERE successor.supersedes_id=j.revision_id) THEN
  final_event_kind:='closed_stale'; cause:='revision_superseded';
 ELSIF target_take IS NULL THEN cause:='target_take_changed';
 ELSIF attempt.claim_sha256<>public.exercise_json_sha256_v1(jsonb_build_object('job',j.id,'attempt',attempt.attempt_number,
    'worker',attempt.worker_id,'claimed_at',attempt.claimed_at,'lease_expires_at',attempt.lease_expires_at,
    'target_take',target_take,'policy','feedback-language-delivery-claim-v1')) THEN cause:='target_take_changed';
 END IF;
 IF cause IS NULL THEN
  BEGIN
   PERFORM public.require_mlc3_service_access_v2(j.acquisition_principal_id,NULL,NULL);
   PERFORM public.require_feedback_language_coach_source_live_v1(j.revision_id,j.acquisition_principal_id,
    a.feedback_membership_id,a.attached_candidate_id,public.feedback_candidate_output_sha256_v1(a.attached_candidate_id),
    'CONFIDENT_MOMENT_COACH_AUTHORITY_INVALID');
  EXCEPTION WHEN OTHERS THEN
   IF EXISTS(SELECT 1 FROM public.data_purge_requests p
      WHERE p.acquisition_principal_id=j.acquisition_principal_id AND p.state<>'done')
      OR EXISTS(SELECT 1 FROM public.processing_service_blocks b
       WHERE b.acquisition_principal_id=j.acquisition_principal_id) THEN
    final_event_kind:='closed_stale'; cause:='source_deleted_or_purged';
   ELSIF SQLERRM IN(
    'CONFIDENT_MOMENT_COACH_AUTHORITY_INVALID','MLC3_ROLLOUT_NOT_ACTIVE',
    'MLC3_CURRENT_ENROLLMENT_REQUIRED','MLC3_COHORT_MEMBERSHIP_REQUIRED',
    'MLC3_ENROLLMENT_AUTHORITY_STALE','MLC3_DUAL_PURPOSE_AUTHORITY_REQUIRED',
    'PROCESSING_AUTHORIZATION_REQUIRED') THEN
    final_event_kind:='closed_stale'; cause:='authority_withdrawn';
   ELSE
    RAISE;
   END IF;
  END;
 END IF;
 IF cause IS NULL THEN
  BEGIN
   d:=public.transition_feedback_language_delivery_v2(j.revision_id,j.acquisition_principal_id,target_take,
    COALESCE(a.anchor_candidate_id,a.bundle_subject_candidate_id),NULL,'schedule',p_idempotency_key||':delivery');
   PERFORM public.require_feedback_language_coach_source_live_v1(j.revision_id,j.acquisition_principal_id,
    a.feedback_membership_id,a.attached_candidate_id,public.feedback_candidate_output_sha256_v1(a.attached_candidate_id),
    'CONFIDENT_MOMENT_COACH_AUTHORITY_INVALID');
   final_event_kind:='completed'; cause:='delivery_materialized'; delivery_id:=(d->>'id')::uuid;
  EXCEPTION WHEN lock_not_available OR query_canceled THEN
   final_event_kind:='failed_retryable'; cause:='lock_timeout'; delivery_id:=NULL;
  WHEN serialization_failure OR deadlock_detected THEN
   final_event_kind:='failed_retryable'; cause:='temporary_database_failure'; delivery_id:=NULL;
  WHEN unique_violation THEN
   final_event_kind:='closed_stale'; cause:='delivery_already_resolved_elsewhere'; delivery_id:=NULL;
  WHEN OTHERS THEN
   IF SQLERRM IN('FEEDBACK_LANGUAGE_DELIVERY_STALE','FEEDBACK_LANGUAGE_DELIVERY_REPLAY_MISMATCH') THEN
    final_event_kind:='closed_stale'; cause:='delivery_already_resolved_elsewhere'; delivery_id:=NULL;
   ELSE
    RAISE;
   END IF;
  END;
 END IF;
 final_event_kind:=COALESCE(final_event_kind,'failed_retryable');
 event_key:='feedback-language-delivery-job-event-v2:'||public.exercise_json_sha256_v1(jsonb_build_object(
  'job',j.id,'claim',h.current_claim_attempt_id,'event',final_event_kind,
  'delivery',delivery_id,'cause',cause,'policy','feedback-language-delivery-job-event-v2'));
 event_id:=gen_random_uuid(); event_created_at:=clock_timestamp();
 event_hash:=public.exercise_json_sha256_v1(jsonb_build_object(
  'id',event_id,'job_id',j.id,'event_kind',final_event_kind,
  'delivery_id',delivery_id,'attempt_number',h.attempt_count,
  'claim_attempt_id',h.current_claim_attempt_id,
  'contract_version','feedback-language-delivery-job-event-v2',
  'cause_code',cause,'idempotency_key',event_key,'created_at',event_created_at,
  'serves_user',false,'dataset_eligible',false));
 INSERT INTO public.feedback_language_delivery_materialization_job_events(id,job_id,event_kind,delivery_id,attempt_number,
  claim_attempt_id,contract_version,cause_code,event_sha256,idempotency_key,created_at,serves_user,dataset_eligible)
 VALUES(event_id,j.id,final_event_kind,delivery_id,h.attempt_count,h.current_claim_attempt_id,
  'feedback-language-delivery-job-event-v2',cause,event_hash,event_key,event_created_at,false,false)
 ON CONFLICT DO NOTHING RETURNING * INTO event_row;
 IF event_row.id IS NULL THEN SELECT * INTO STRICT event_row FROM public.feedback_language_delivery_materialization_job_events
  WHERE job_id=j.id AND attempt_number=h.attempt_count AND event_kind=final_event_kind; END IF;
 IF final_event_kind IN('completed','closed_stale') THEN
  UPDATE public.feedback_language_delivery_job_due_heads SET scheduling_state='terminal',next_probe_at=NULL,updated_at=clock_timestamp() WHERE job_id=j.id;
 ELSE
  UPDATE public.feedback_language_delivery_job_due_heads SET scheduling_state='pending',next_probe_at=h.lease_expires_at,updated_at=clock_timestamp() WHERE job_id=j.id;
 END IF;
 UPDATE public.feedback_language_delivery_materialization_jobs
  SET job_state=final_event_kind,attempt_count=h.attempt_count WHERE id=j.id;
 RETURN jsonb_build_object('job_id',j.id,'job_state',final_event_kind,'delivery_id',event_row.delivery_id,
  'cause_code',event_row.cause_code,'dataset_eligible',false);
END $$;

CREATE OR REPLACE FUNCTION public.read_ideal_text_document_core_v2(p_arc_id text,p_actor_id text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE s public.ideal_text_document_snapshots; owner_note public.user_arc_ideal_notes;
 parts jsonb; owner_edit jsonb; summary jsonb; status jsonb; snapshot_json jsonb; overlay jsonb; result jsonb;
 derived_principal uuid; derived_project uuid; derived_take uuid;
BEGIN
 SELECT id,owner_principal_id INTO STRICT derived_project,derived_principal FROM public.projects WHERE id::text=p_arc_id;
 IF NOT EXISTS(SELECT 1 FROM public.owner_principals p WHERE p.id=derived_principal
   AND (p.user_id::text=p_actor_id OR p.id::text=p_actor_id)) THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_INVALID'; END IF;
 SELECT snapshot.source_take_session_id INTO STRICT derived_take
 FROM public.ideal_text_document_heads head JOIN public.ideal_text_document_snapshots snapshot ON snapshot.id=head.snapshot_id
 WHERE head.arc_id=p_arc_id AND head.actor_id=p_actor_id;
 PERFORM public.lock_confident_moment_inventory_v1(derived_principal,derived_project,derived_take);
 SELECT snapshot.* INTO STRICT s FROM public.ideal_text_document_heads head
 JOIN public.ideal_text_document_snapshots snapshot ON snapshot.id=head.snapshot_id
 WHERE head.arc_id=p_arc_id AND head.actor_id=p_actor_id AND snapshot.arc_id=p_arc_id AND snapshot.actor_id=p_actor_id FOR SHARE OF head,snapshot;
 IF s.arc_id='' OR s.actor_id='' OR s.acquisition_principal_id<>derived_principal
    OR s.project_id<>derived_project OR s.source_take_session_id<>derived_take THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_INVALID'; END IF;
 SELECT * INTO owner_note FROM public.user_arc_ideal_notes n WHERE n.arc_id=p_arc_id AND n.user_id=(SELECT user_id FROM public.owner_principals WHERE id=s.acquisition_principal_id) FOR SHARE;
 SELECT COALESCE(jsonb_agg(jsonb_build_object('id',p.id,'ord',p.ord,'text',p.text,
   'locked',COALESCE(l.locked,false),'current_part_revision_id',l.current_part_revision_id) ORDER BY p.ord,p.id),'[]'::jsonb)
 INTO parts FROM public.ideal_text_part p LEFT JOIN LATERAL(
   SELECT r.id current_part_revision_id,(r.action='lock') locked FROM public.ideal_text_part_revision r
   WHERE r.arc_id=p.arc_id AND r.user_id=p.user_id AND r.part_id=p.id ORDER BY r.id DESC LIMIT 1) l ON true
 WHERE p.arc_id=p_arc_id AND p.user_id=p_actor_id;
 owner_edit:=jsonb_build_object('text',owner_note.user_text,'source_document_version',owner_note.user_text_version,
  'user_text_revision',CASE WHEN owner_note.user_text_revision IS NULL THEN NULL ELSE owner_note.user_text_revision::text END,
  'user_text_sha256',CASE WHEN owner_note.user_text IS NULL THEN NULL ELSE public.exercise_text_sha256_v1(owner_note.user_text) END,
  'parts',parts,'current_bundle_text_update_binding',NULL);
 BEGIN
  summary:=public.project_confident_moment_bundles_v1(s.acquisition_principal_id,s.project_id,s.source_take_session_id)->'summary';
  status:=jsonb_build_object('state','available','code',NULL,'retryable',false);
 EXCEPTION WHEN no_data_found THEN
  summary:=NULL; status:=jsonb_build_object('state','unavailable','code',NULL,'retryable',false);
 WHEN OTHERS THEN
  IF SQLERRM LIKE '%DISABLED%' THEN summary:=NULL; status:=jsonb_build_object('state','disabled','code',NULL,'retryable',false);
  ELSE RAISE; END IF;
 END;
 snapshot_json:=jsonb_build_object('id',s.id::text,'arc_id',s.arc_id,'actor_id',s.actor_id,
  'acquisition_principal_id',s.acquisition_principal_id::text,'project_id',s.project_id::text,
  'source_take_session_id',s.source_take_session_id::text,'version',s.version,'source_generation',s.source_generation::text,
  'source_fingerprint_sha256',s.source_fingerprint_sha256,'payload_sha256',s.payload_sha256,'payload',s.payload,
  'enrichment_seed',s.enrichment_seed,'supersedes_id',CASE WHEN s.supersedes_id IS NULL THEN NULL ELSE s.supersedes_id::text END,
  'created_at',to_char(s.created_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'));
 overlay:=jsonb_build_object('owner_edit',owner_edit,'confident_moment_summary',summary,'confident_moment_summary_status',status);
 result:=jsonb_build_object('ideal_text_core_read_contract_version','ideal-text-document-core-v2','snapshot',snapshot_json,'dynamic_overlay',overlay);
 RETURN result||jsonb_build_object('read_sha256',public.exercise_json_sha256_v1(result));
END $$;

CREATE OR REPLACE FUNCTION public.get_mlc3_general_service_monitor_v2()
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE base jsonb; cutoff timestamptz:=clock_timestamp(); unfinished integer; oldest timestamptz;
 set_hash text; contention integer;
BEGIN
 base:=public.get_mlc3_general_service_monitor_v1();
 SELECT count(*),min(scanner_started_at),
  CASE WHEN count(*)=0 THEN NULL ELSE public.exercise_text_sha256_v1(string_agg(run_id::text,',' ORDER BY run_id)) END
 INTO unfinished,oldest,set_hash FROM public.feedback_language_delivery_scan_runs
 WHERE scanner_started_at IS NOT NULL AND finished_at IS NULL AND scanner_started_at<cutoff-interval '5 seconds';
 SELECT count(*) INTO contention FROM public.feedback_language_delivery_scan_runs
 WHERE result_code='skipped_contention' AND finished_at>=cutoff-interval '60 seconds';
 RETURN base||jsonb_build_object('confident_moment_delivery_scanner',jsonb_build_object(
  'unfinished_over_5s_count',unfinished,'unfinished_set_sha256',set_hash,
  'oldest_started_at',CASE WHEN oldest IS NULL THEN NULL ELSE to_char(oldest AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"') END,
  'skipped_contention_60s_count',contention,'hard_stop',unfinished>0));
END $$;

CREATE OR REPLACE FUNCTION public.halt_mlc3_for_stalled_delivery_scan_v1(
 p_monitor_run_id uuid,p_observation_cutoff timestamptz,p_expected_unfinished_set_sha256 text,p_idempotency_key text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE ids uuid[]; actual_hash text; oldest timestamptz; source_rollout public.mlc3_service_rollout_revisions;
 halted public.mlc3_service_rollout_revisions; receipt public.feedback_language_delivery_stalled_scan_halt_receipts;
 receipt_id uuid:=gen_random_uuid(); created timestamptz:=clock_timestamp(); disabled_hash text; receipt_hash text;
BEGIN
 IF p_expected_unfinished_set_sha256 !~ '^[0-9a-f]{64}$' OR COALESCE(btrim(p_idempotency_key),'')='' THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_STALLED_SCAN_HALT_INVALID'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-rollout-policy-v2',0));
 SELECT * INTO source_rollout FROM public.mlc3_service_rollout_revisions ORDER BY revision_number DESC LIMIT 1 FOR SHARE;
 SELECT * INTO receipt FROM public.feedback_language_delivery_stalled_scan_halt_receipts
  WHERE unfinished_set_sha256=p_expected_unfinished_set_sha256 ORDER BY created_at LIMIT 1;
 IF FOUND THEN RETURN jsonb_build_object('receipt_id',receipt.receipt_id,'receipt_sha256',receipt.receipt_sha256,
   'unfinished_count',receipt.unfinished_count,'hard_stop',true,'dataset_eligible',false); END IF;
 SELECT array_agg(run_id ORDER BY run_id),min(scanner_started_at) INTO ids,oldest
 FROM public.feedback_language_delivery_scan_runs WHERE scanner_started_at IS NOT NULL AND finished_at IS NULL
  AND scanner_started_at<p_observation_cutoff-interval '5 seconds';
 IF cardinality(COALESCE(ids,ARRAY[]::uuid[]))=0 THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_STALLED_SCAN_SET_CHANGED'; END IF;
 actual_hash:=public.exercise_text_sha256_v1(array_to_string(ids,','));
 IF actual_hash<>p_expected_unfinished_set_sha256 THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_STALLED_SCAN_SET_CHANGED'; END IF;
 halted:=public.halt_mlc3_service_rollout_v1('confident_moment_delivery_scanner_stalled',actual_hash);
 IF halted.rollout_state NOT IN('disabled','halted','retired') THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_STALLED_SCAN_HALT_FAILED'; END IF;
 disabled_hash:=public.exercise_json_sha256_v1(jsonb_build_object('rollout_revision_id',halted.id,'state',halted.rollout_state));
 receipt_hash:=public.exercise_json_sha256_v1(jsonb_build_object('contract','feedback-language-stalled-scan-halt-receipt-v1',
  'receipt_id',receipt_id,'monitor_run_id',p_monitor_run_id,'observation_cutoff',p_observation_cutoff,
  'unfinished_count',cardinality(ids),'unfinished_set_sha256',actual_hash,'oldest_started_at',oldest,
  'source_rollout_revision_id',source_rollout.id,'halt_operation_id',halted.id,'disabled_state_sha256',disabled_hash,
  'created_at',created,'serves_user',false,'dataset_eligible',false));
 INSERT INTO public.feedback_language_delivery_stalled_scan_halt_receipts(receipt_id,receipt_contract_version,
  monitor_run_id,observation_cutoff,unfinished_count,unfinished_set_sha256,oldest_started_at,
  source_rollout_revision_id,halt_operation_id,disabled_state_sha256,receipt_sha256,created_at)
 VALUES(receipt_id,'feedback-language-stalled-scan-halt-receipt-v1',p_monitor_run_id,p_observation_cutoff,
  cardinality(ids),actual_hash,oldest,source_rollout.id,halted.id,disabled_hash,receipt_hash,created) RETURNING * INTO receipt;
 UPDATE public.feedback_language_delivery_scan_runs SET finished_at=created,result_code='stalled_scan_halted',
  result_sha256=public.exercise_json_sha256_v1(jsonb_build_object('run',run_id,'result','stalled_scan_halted','receipt',receipt.receipt_id))
 WHERE run_id=ANY(ids) AND finished_at IS NULL;
 RETURN jsonb_build_object('receipt_id',receipt.receipt_id,'receipt_sha256',receipt.receipt_sha256,
  'unfinished_count',receipt.unfinished_count,'hard_stop',true,'dataset_eligible',false);
END $$;

DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['confident_moment_bundle_attachments','confident_moment_owner_decision_bindings','root_phrase_coverage_frames','root_phrase_coverage_items','feedback_language_revision_deliveries','confident_moment_bundle_projections','confident_moment_bundle_projection_items',
  'ideal_text_user_edit_cas_operations','confident_moment_bundle_text_update_bindings',
  'confident_moment_coach_authorability_inventories','confident_moment_coach_authorability_items',
  'confident_moment_blind_assignment_bindings','confident_moment_coach_wording_authority_bindings',
  'feedback_language_delivery_materialization_job_events'] LOOP
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t); EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('REVOKE ALL ON TABLE public.%I FROM PUBLIC,anon,authenticated,service_role',t);
  EXECUTE format('DROP TRIGGER IF EXISTS %I ON public.%I',t||'_append_only',t);
  EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.reject_confident_moment_mutation_v1()',t||'_append_only',t);
 END LOOP;
END $$;
-- The job identity and its hash are immutable, while these two compatibility
-- columns mirror the guarded claim-head / terminal-event projection.  Runtime
-- roles have no table write grants; only the reviewed scanner/materializer
-- SECURITY DEFINER functions may advance them.
ALTER TABLE public.feedback_language_delivery_materialization_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.feedback_language_delivery_materialization_jobs FORCE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.feedback_language_delivery_materialization_jobs
 FROM PUBLIC,anon,authenticated,service_role;
DROP TRIGGER IF EXISTS feedback_language_delivery_materialization_jobs_append_only
 ON public.feedback_language_delivery_materialization_jobs;
ALTER TABLE public.confident_moment_text_update_capabilities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.confident_moment_text_update_capabilities FORCE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.confident_moment_text_update_capabilities FROM PUBLIC,anon,authenticated,service_role;
DROP TRIGGER IF EXISTS feedback_revisions_append_only ON public.feedback_revisions;
CREATE TRIGGER feedback_revisions_append_only BEFORE UPDATE OR DELETE ON public.feedback_revisions FOR EACH ROW EXECUTE FUNCTION public.reject_confident_moment_mutation_v1();
ALTER TABLE public.feedback_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.feedback_revisions FORCE ROW LEVEL SECURITY;
ALTER TABLE public.root_phrase_product_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.root_phrase_product_actions FORCE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.feedback_revisions,public.root_phrase_product_actions FROM PUBLIC,anon,authenticated,service_role;
ALTER TABLE public.user_arc_ideal_notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_arc_ideal_notes FORCE ROW LEVEL SECURITY;
ALTER TABLE public.ideal_text_part ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ideal_text_part FORCE ROW LEVEL SECURITY;
ALTER TABLE public.ideal_text_part_revision ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ideal_text_part_revision FORCE ROW LEVEL SECURITY;
REVOKE INSERT,UPDATE,DELETE,TRUNCATE ON TABLE public.user_arc_ideal_notes,public.ideal_text_part,
 public.ideal_text_part_revision FROM PUBLIC,anon,authenticated,service_role;
DO $$ DECLARE f text; BEGIN
FOREACH f IN ARRAY ARRAY['public.reject_confident_moment_mutation_v1()','public.exercise_text_sha256_v1(text)','public.guard_user_ideal_edit_cas_v1()','public.require_feedback_language_coach_source_live_v1(uuid,uuid,uuid,uuid,text,text)','public.lock_confident_moment_inventory_v1(uuid,uuid,uuid)','public.lock_confident_moment_position_100_v1(text[],text[],text[])','public.require_root_phrase_practice_source_live_v1(uuid,uuid,uuid,uuid,uuid)','public.resolve_confident_moment_target_speaker_binding_v1(uuid,uuid,uuid,text,uuid,uuid)','public.transition_ideal_text_root_state_v1(uuid,uuid,uuid,uuid,bigint,text,text)','public.prepare_confident_moment_bundle_v1(uuid,uuid,uuid,uuid,uuid,text)','public.ack_confident_moment_bundle_item_render_v3(uuid,uuid,uuid,uuid,uuid,text)','public.freeze_root_phrase_coverage_frame_v1(uuid,uuid,uuid,uuid,uuid,text,text)','public.record_feedback_language_coach_revision_v1(uuid,uuid,uuid,uuid,uuid,uuid,uuid,uuid,text,text,text,text,uuid,text)','public.record_feedback_language_coach_revision_v2(uuid,uuid,uuid,uuid,uuid,uuid,uuid,uuid,text,text,text,text,uuid,text)','public.schedule_feedback_language_revision_v1(uuid,uuid,uuid,uuid,text)','public.transition_feedback_language_delivery_v2(uuid,uuid,uuid,uuid,uuid,text,text)','public.ack_feedback_language_revision_render_v3(uuid,uuid,uuid,uuid,uuid,uuid,uuid,text)','public.project_confident_moment_bundles_v1(uuid,uuid,uuid)','public.record_root_phrase_product_action_v2(uuid,uuid,uuid,uuid,integer,text,uuid,uuid,uuid,uuid,uuid,uuid,bigint,uuid,uuid,uuid,uuid,text,text)',
 'public.read_feedback_v3_candidate_source_snapshot_v1(uuid,uuid,uuid)',
 'public.record_confident_moment_bundle_family_response_v1(uuid,uuid,uuid,uuid,uuid,text,text)',
 'public.record_confident_moment_bundle_root_action_v1(uuid,uuid,uuid,text,uuid,uuid,uuid,uuid,bigint,uuid,uuid,uuid,uuid,text,text)',
 'public.compare_and_set_user_ideal_edit_v1(uuid,text,integer,bigint,text,text,jsonb,text)',
 'public.apply_confident_moment_bundle_text_update_v1(uuid,uuid,uuid,uuid,uuid,uuid,uuid,integer,bigint,bigint,text,jsonb,text)',
 'public.freeze_confident_moment_coach_authorability_inventory_v1(uuid,uuid,uuid,uuid,uuid,text)',
 'public.publish_confident_moment_coach_feedback_language_v1(uuid,uuid,uuid,uuid,uuid,uuid,uuid,text,text,text,uuid,uuid,text)',
 'public.materialize_feedback_language_delivery_job_v1(uuid,text)',
 'public.project_confident_moment_coach_authoring_context_v1(uuid,uuid,uuid,text)',
 'public.project_confident_moment_coach_authoring_context_v2(uuid,uuid,text)'] LOOP
  EXECUTE 'REVOKE ALL ON FUNCTION '||f||' FROM PUBLIC,anon,authenticated,service_role';
 END LOOP;
END $$;
REVOKE ALL ON FUNCTION public.validate_confident_moment_projection_item_v1()
 FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION public.project_confident_moment_bundles_v1(uuid,uuid,uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.record_feedback_language_coach_revision_v2(uuid,uuid,uuid,uuid,uuid,uuid,uuid,uuid,text,text,text,text,uuid,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.transition_feedback_language_delivery_v2(uuid,uuid,uuid,uuid,uuid,text,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.ack_feedback_language_revision_render_v3(uuid,uuid,uuid,uuid,uuid,uuid,uuid,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.ack_confident_moment_bundle_item_render_v3(uuid,uuid,uuid,uuid,uuid,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.read_feedback_v3_candidate_source_snapshot_v1(uuid,uuid,uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.record_confident_moment_bundle_family_response_v1(uuid,uuid,uuid,uuid,uuid,text,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.record_confident_moment_bundle_root_action_v1(uuid,uuid,uuid,text,uuid,uuid,uuid,uuid,bigint,uuid,uuid,uuid,uuid,text,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.compare_and_set_user_ideal_edit_v1(uuid,text,integer,bigint,text,text,jsonb,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.apply_confident_moment_bundle_text_update_v1(uuid,uuid,uuid,uuid,uuid,uuid,uuid,integer,bigint,bigint,text,jsonb,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.freeze_confident_moment_coach_authorability_inventory_v1(uuid,uuid,uuid,uuid,uuid,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.publish_confident_moment_coach_feedback_language_v1(uuid,uuid,uuid,uuid,uuid,uuid,uuid,text,text,text,uuid,uuid,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.materialize_feedback_language_delivery_job_v1(uuid,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.project_confident_moment_coach_authoring_context_v2(uuid,uuid,text) TO service_role;

-- Closed D11 writer/trigger registry.  An unexpected overload or a missing,
-- renamed, disabled, or rebound trigger aborts the entire transaction.
DO $confident_moment_registry_verifier$
DECLARE
 expected_functions text[]:=ARRAY[
  'public.freeze_synthetic_feedback_v3_membership_v1(uuid,uuid,uuid,uuid,uuid,text,jsonb,text,text)',
  'public.freeze_feedback_v3_service_membership_v1(uuid,uuid,uuid,uuid,uuid,text,jsonb,text)',
  'public.publish_ideal_text_document_snapshot_v1(text,text,uuid,uuid,uuid,integer,bigint,text,jsonb,jsonb)',
  'public.prepare_confident_moment_bundle_v1(uuid,uuid,uuid,uuid,uuid,text)',
  'public.freeze_root_phrase_coverage_frame_v1(uuid,uuid,uuid,uuid,uuid,text,text)',
  'public.record_root_phrase_product_action_v2(uuid,uuid,uuid,uuid,integer,text,uuid,uuid,uuid,uuid,uuid,uuid,bigint,uuid,uuid,uuid,uuid,text,text)',
  'public.activate_synthetic_root_phrase_v1(uuid,uuid,boolean,boolean,text)',
  'public.remove_synthetic_root_phrase_v1(uuid,integer,integer,uuid,uuid,text)',
  'public.transition_ideal_text_root_state_v1(uuid,uuid,uuid,uuid,bigint,text,text)',
  'public.record_feedback_language_coach_revision_v1(uuid,uuid,uuid,uuid,uuid,uuid,uuid,uuid,text,text,text,text,uuid,text)',
  'public.record_feedback_language_coach_revision_v2(uuid,uuid,uuid,uuid,uuid,uuid,uuid,uuid,text,text,text,text,uuid,text)',
  'public.schedule_feedback_language_revision_v1(uuid,uuid,uuid,uuid,text)',
  'public.transition_feedback_language_delivery_v2(uuid,uuid,uuid,uuid,uuid,text,text)',
  'public.ack_feedback_language_revision_render_v3(uuid,uuid,uuid,uuid,uuid,uuid,uuid,text)',
  'public.ack_confident_moment_bundle_item_render_v3(uuid,uuid,uuid,uuid,uuid,text)',
  'public.ack_feedback_v3_service_render_v1(uuid,uuid,uuid,uuid,uuid,uuid,text,timestamptz,text,text)',
  'public.record_feedback_human_decision_v1(uuid,uuid,uuid,text,text,text,text,text)',
  'public.record_feedback_human_decision_v1(uuid,uuid,uuid,uuid,uuid,uuid,text,text,text,text)',
  'public.record_confident_moment_bundle_family_response_v1(uuid,uuid,uuid,uuid,uuid,text,text)',
  'public.register_mlc3_general_rollout_v2(uuid,uuid,jsonb,jsonb,uuid,timestamptz,text)',
  'public.halt_mlc3_service_rollout_v1(text,text)',
  'public.ensure_mlc3_service_enrollment_v2(uuid,uuid,text)',
  'public.activate_phase1_policy_v1(text,text,text)',
  'public.accept_phase1_processing_authorization_v1(uuid,text,text,text,text,text,text,boolean,text,text,text,timestamptz,text)',
  'public.mark_phase1_storage_object_purged_v1(uuid,text,uuid,text,text,text,text)',
  'public.finalize_phase1_purge_v3(uuid,text)'
 ];
 signature text;
 actual_count integer;
 expected_count integer;
BEGIN
 FOREACH signature IN ARRAY expected_functions LOOP
  IF to_regprocedure(signature) IS NULL THEN
   RAISE EXCEPTION 'CONFIDENT_MOMENT_WRITER_REGISTRY_DRIFT: %',signature;
  END IF;
 END LOOP;
 expected_count:=cardinality(expected_functions);
 SELECT count(*) INTO actual_count FROM pg_proc procedure
  JOIN pg_namespace namespace ON namespace.oid=procedure.pronamespace
  WHERE namespace.nspname='public' AND procedure.proname=ANY(ARRAY[
   'freeze_synthetic_feedback_v3_membership_v1','freeze_feedback_v3_service_membership_v1','publish_ideal_text_document_snapshot_v1','prepare_confident_moment_bundle_v1','freeze_root_phrase_coverage_frame_v1','record_root_phrase_product_action_v2','activate_synthetic_root_phrase_v1','remove_synthetic_root_phrase_v1','transition_ideal_text_root_state_v1','record_feedback_language_coach_revision_v1','record_feedback_language_coach_revision_v2','schedule_feedback_language_revision_v1','transition_feedback_language_delivery_v2','ack_feedback_language_revision_render_v3','ack_confident_moment_bundle_item_render_v3','ack_feedback_v3_service_render_v1','record_feedback_human_decision_v1','record_confident_moment_bundle_family_response_v1','register_mlc3_general_rollout_v2','halt_mlc3_service_rollout_v1','ensure_mlc3_service_enrollment_v2','activate_phase1_policy_v1','accept_phase1_processing_authorization_v1','mark_phase1_storage_object_purged_v1','finalize_phase1_purge_v3']);
 IF actual_count<>expected_count THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_WRITER_OVERLOAD_DRIFT';
 END IF;
 IF EXISTS(
  SELECT 1 FROM (VALUES
   ('public.activate_synthetic_root_phrase_v1(uuid,uuid,boolean,boolean,text)'),
   ('public.remove_synthetic_root_phrase_v1(uuid,integer,integer,uuid,uuid,text)')
  ) expected(signature)
  CROSS JOIN LATERAL (SELECT pg_get_functiondef(expected.signature::regprocedure) body) installed
  WHERE position('D11 legacy root writer: global inventory before root block' in installed.body)=0
     OR position('lock_confident_moment_inventory_v1' in installed.body)=0
     OR position('root-block:' in installed.body)=0
     OR position('lock_confident_moment_inventory_v1' in installed.body)
        > position('root-block:' in installed.body)
 ) THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_LEGACY_ROOT_LOCK_ORDER_DRIFT'; END IF;
 IF EXISTS(
  WITH expected(name,relation_name,function_name) AS (VALUES
   ('confident_moment_projection_item_lineage_v1','confident_moment_bundle_projection_items','validate_confident_moment_projection_item_v1'),
   ('confident_moment_owner_decision_bindings_append_only','confident_moment_owner_decision_bindings','reject_confident_moment_mutation_v1'),
   ('coach_ideal_text_advances_document_generation','coach_arc_ideal_text','advance_ideal_text_document_generation_v1'),
   ('user_ideal_edit_advances_document_generation','user_arc_ideal_notes','advance_ideal_text_document_generation_v1'),
   ('ideal_text_part_advances_document_generation','ideal_text_part','advance_ideal_text_document_generation_v1'),
   ('ready_take_advances_ideal_text_document_generation','v2_sessions','advance_ideal_text_document_generation_v1'),
   ('data_purge_requests_mlc3_service_serialization','data_purge_requests','serialize_mlc3_service_purge_v1'),
   ('processing_audio_deletion_mlc3_serialization','processing_audio_object_deletion_events','serialize_mlc3_processing_audio_leaf_v1'),
   ('processing_audio_object_mlc3_serialization','processing_audio_objects','serialize_mlc3_processing_audio_leaf_v1'),
   ('feedback_v3_membership_complete','feedback_v3_memberships','validate_feedback_v3_membership_v1')
  )
  SELECT 1 FROM expected
  LEFT JOIN pg_trigger trigger_row ON trigger_row.tgname=expected.name AND NOT trigger_row.tgisinternal
  LEFT JOIN pg_class relation ON relation.oid=trigger_row.tgrelid
  LEFT JOIN pg_proc procedure ON procedure.oid=trigger_row.tgfoid
  WHERE trigger_row.oid IS NULL OR relation.relname<>expected.relation_name
     OR procedure.proname<>expected.function_name OR NOT trigger_row.tgenabled IN('O','A')
  ) THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_TRIGGER_REGISTRY_DRIFT'; END IF;
 IF to_regprocedure('public.validate_confident_moment_projection_item_v1()') IS NULL THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_TRIGGER_FUNCTION_REGISTRY_DRIFT';
 END IF;
END
$confident_moment_registry_verifier$;

DO $cm_delivery_scheduler_rls$
DECLARE relation_name text;
BEGIN
 FOREACH relation_name IN ARRAY ARRAY[
  'feedback_language_delivery_job_claim_attempts',
  'feedback_language_delivery_job_claim_heads',
  'feedback_language_delivery_job_due_heads',
  'feedback_language_delivery_scan_runs',
  'feedback_language_delivery_stalled_scan_halt_receipts',
  'feedback_language_delivery_take_arm_operations'
 ] LOOP
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',relation_name);
  EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',relation_name);
  EXECUTE format('REVOKE ALL ON TABLE public.%I FROM PUBLIC,anon,authenticated,service_role',relation_name);
 END LOOP;
END $cm_delivery_scheduler_rls$;

REVOKE ALL ON FUNCTION public.guard_feedback_language_delivery_job_event_v2_v1()
 FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.create_feedback_language_delivery_due_head_v1()
 FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.begin_feedback_language_delivery_scan_run_v1(uuid,text,text)
 FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.mark_feedback_language_delivery_scan_started_v1(uuid,text,text)
 FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.abandon_feedback_language_delivery_scan_run_v1(uuid,text,text)
 FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.require_feedback_language_delivery_scan_authority_v1(uuid)
 FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.scan_due_feedback_language_delivery_jobs_v1(uuid,text,integer,integer,integer)
 FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.arm_feedback_language_delivery_jobs_for_take_v1(uuid,text)
 FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.read_ideal_text_document_core_v2(text,text)
 FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.get_mlc3_general_service_monitor_v2()
 FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.halt_mlc3_for_stalled_delivery_scan_v1(uuid,timestamptz,text,text)
 FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.derive_confident_moment_owner_decision_v1(uuid,uuid,uuid)
 FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.resolve_confident_moment_source_playback_authority_v1(uuid,uuid,uuid)
 FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.resolve_confident_moment_exercise_offer_v1(uuid,uuid,uuid)
 FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.authorize_confident_moment_source_playback_emit_v1(uuid,uuid,uuid,text,text,uuid)
 FROM PUBLIC,anon,authenticated,service_role;

GRANT EXECUTE ON FUNCTION public.begin_feedback_language_delivery_scan_run_v1(uuid,text,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.mark_feedback_language_delivery_scan_started_v1(uuid,text,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.abandon_feedback_language_delivery_scan_run_v1(uuid,text,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.scan_due_feedback_language_delivery_jobs_v1(uuid,text,integer,integer,integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.arm_feedback_language_delivery_jobs_for_take_v1(uuid,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.read_ideal_text_document_core_v2(text,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.get_mlc3_general_service_monitor_v2() TO service_role;
GRANT EXECUTE ON FUNCTION public.halt_mlc3_for_stalled_delivery_scan_v1(uuid,timestamptz,text,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.resolve_confident_moment_source_playback_authority_v1(uuid,uuid,uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.resolve_confident_moment_exercise_offer_v1(uuid,uuid,uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.authorize_confident_moment_source_playback_emit_v1(uuid,uuid,uuid,text,text,uuid) TO service_role;

DO $cm_delivery_scheduler_closure$
DECLARE signature text;
BEGIN
 FOREACH signature IN ARRAY ARRAY[
  'public.begin_feedback_language_delivery_scan_run_v1(uuid,text,text)',
  'public.mark_feedback_language_delivery_scan_started_v1(uuid,text,text)',
  'public.abandon_feedback_language_delivery_scan_run_v1(uuid,text,text)',
  'public.scan_due_feedback_language_delivery_jobs_v1(uuid,text,integer,integer,integer)',
  'public.arm_feedback_language_delivery_jobs_for_take_v1(uuid,text)',
  'public.materialize_feedback_language_delivery_job_v1(uuid,text)',
  'public.read_ideal_text_document_core_v2(text,text)',
  'public.get_mlc3_general_service_monitor_v2()',
  'public.halt_mlc3_for_stalled_delivery_scan_v1(uuid,timestamptz,text,text)'
  ,'public.resolve_confident_moment_source_playback_authority_v1(uuid,uuid,uuid)'
  ,'public.resolve_confident_moment_exercise_offer_v1(uuid,uuid,uuid)'
  ,'public.authorize_confident_moment_source_playback_emit_v1(uuid,uuid,uuid,text,text,uuid)'
 ] LOOP
  IF to_regprocedure(signature) IS NULL THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_DELIVERY_REGISTRY_DRIFT: %',signature; END IF;
 END LOOP;
 IF to_regprocedure('public.claim_due_feedback_language_delivery_jobs_v1(uuid,text,integer,integer,integer)') IS NOT NULL
    OR to_regprocedure('public.claim_due_feedback_language_delivery_jobs_v1(text,integer,integer,integer)') IS NOT NULL
    OR to_regprocedure('public.scan_due_feedback_language_delivery_jobs_v1(uuid,text,integer,integer)') IS NOT NULL
    OR to_regprocedure('public.scan_due_feedback_language_delivery_jobs_v1(uuid,text,integer)') IS NOT NULL THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_DELIVERY_RETIRED_SCANNER_PRESENT';
 END IF;
 IF EXISTS(SELECT 1 FROM pg_proc p CROSS JOIN LATERAL aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) acl
      WHERE p.oid='public.scan_due_feedback_language_delivery_jobs_v1(uuid,text,integer,integer,integer)'::regprocedure
        AND acl.grantee=0 AND acl.privilege_type='EXECUTE')
    OR has_function_privilege('anon','public.scan_due_feedback_language_delivery_jobs_v1(uuid,text,integer,integer,integer)','EXECUTE')
    OR has_function_privilege('authenticated','public.scan_due_feedback_language_delivery_jobs_v1(uuid,text,integer,integer,integer)','EXECUTE')
    OR NOT has_function_privilege('service_role','public.scan_due_feedback_language_delivery_jobs_v1(uuid,text,integer,integer,integer)','EXECUTE') THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_DELIVERY_SCANNER_PERMISSION_DRIFT';
 END IF;
END $cm_delivery_scheduler_closure$;
NOTIFY pgrst,'reload schema';
COMMIT;
