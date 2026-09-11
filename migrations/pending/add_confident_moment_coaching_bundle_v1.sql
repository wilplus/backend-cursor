-- Pending, unnumbered: Confident Moment Coaching Bundle V1 data foundation.
-- Contract Delta D3 / Interface Manifest D5. Runtime and learning gates stay off.
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
 IF p_supersedes_revision_id IS NOT NULL AND (NOT EXISTS(SELECT 1 FROM public.feedback_revisions old WHERE old.id=p_supersedes_revision_id AND old.feedback_membership_id=p_feedback_membership_id AND old.feedback_candidate_id=p_feedback_candidate_id AND old.rater_id=p_reviewer_principal_id AND old.taxonomy_version='feedback-language-coach-revision-v1') OR EXISTS(SELECT 1 FROM public.feedback_revisions newer WHERE newer.supersedes_id=p_supersedes_revision_id AND newer.taxonomy_version='feedback-language-coach-revision-v1')) THEN RAISE EXCEPTION 'FEEDBACK_LANGUAGE_REVISION_INVALID'; END IF;
 digest:=public.exercise_json_sha256_v1(jsonb_build_object('reviewer',p_reviewer_principal_id,'batch',p_review_batch_id,'grant',p_reveal_grant_id,'access',p_reveal_access_id,'assignment',p_review_assignment_id,'judgment',p_blind_judgment_id,'membership',p_feedback_membership_id,'candidate',p_feedback_candidate_id,'output_hash',p_candidate_output_sha256,'kind',p_output_kind,'purpose',p_comment_purpose,'text',p_revision_text,'supersedes',p_supersedes_revision_id));
 SELECT * INTO r FROM public.feedback_revisions WHERE idempotency_key=p_idempotency_key; IF r.id IS NOT NULL THEN IF r.revision_sha256<>digest THEN RAISE EXCEPTION 'FEEDBACK_LANGUAGE_REPLAY_CONFLICT'; END IF; PERFORM public.require_mlc3_service_access_v2(a.acquisition_principal_id,NULL,NULL); RETURN to_jsonb(r); END IF;
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

CREATE OR REPLACE FUNCTION public.ack_feedback_language_revision_render_v1(p_recipient_principal_id uuid,p_revision_delivery_id uuid,p_presentation_id uuid,p_render_instance_id uuid,p_idempotency_key text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE d public.feedback_language_revision_deliveries; p public.ml_presentations; e public.ml_rendered_exposures;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('feedback-language-render:'||p_idempotency_key,0)); SELECT * INTO STRICT d FROM public.feedback_language_revision_deliveries WHERE id=p_revision_delivery_id AND recipient_principal_id=p_recipient_principal_id AND delivery_state<>'invalidated'; PERFORM public.require_mlc3_service_access_v2(p_recipient_principal_id,d.authorization_rollout_revision_id,d.authorization_enrollment_revision_id); SELECT * INTO STRICT p FROM public.ml_presentations WHERE id=p_presentation_id AND actor_principal_id=p_recipient_principal_id AND artifact_id=d.revision_id AND learning_surface_id=(SELECT CASE revision_row.output_kind WHEN 'rephrase' THEN 'correction_generation' WHEN 'comment' THEN CASE revision_row.comment_purpose WHEN 'positive_praise' THEN 'praise_generation' ELSE 'coach_comment_generation' END END FROM public.feedback_revisions revision_row WHERE revision_row.id=d.revision_id) AND delivery_mode<>'shadow'; SELECT * INTO e FROM public.ack_mlc2_rendered_exposure_v1(p.id,p.acknowledgement_token,p_recipient_principal_id,p_render_instance_id,clock_timestamp(),'feedback-language-coach-revision-v1',p.visible_payload_sha256,p_idempotency_key); PERFORM public.require_mlc3_service_access_v2(p_recipient_principal_id,d.authorization_rollout_revision_id,d.authorization_enrollment_revision_id); RETURN to_jsonb(e);
END $$;

CREATE OR REPLACE FUNCTION public.require_root_phrase_practice_source_live_v1(p_acquisition_principal_id uuid,p_content_version_id uuid,p_practice_attempt_id uuid,p_source_target_speaker_binding_id uuid,p_practice_target_speaker_binding_id uuid) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE
 c public.root_phrase_content_versions; attempt public.exercise_practice_attempts; practice public.exercise_practice_sessions; offer public.exercise_service_offers; lineage public.exercise_audio_lineages;
 source_binding public.mlc3_target_speaker_bindings; practice_binding public.mlc3_target_speaker_bindings; source_revision public.mlc3_speaker_acquisition_revisions; practice_revision public.mlc3_speaker_acquisition_revisions;
 source_object public.processing_audio_objects; practice_object public.processing_audio_objects; digest text;
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
 IF practice.project_id<>c.project_id OR practice.source_take_id<>offer.source_take_id OR offer.feedback_membership_id<>c.feedback_membership_id OR NOT EXISTS(SELECT 1 FROM public.feedback_v3_membership_items item WHERE item.membership_id=offer.feedback_membership_id AND item.candidate_id=offer.feedback_candidate_id AND item.selected AND item.eligibility='eligible' AND item.slide_index=c.slide_index AND item.block_key=c.block_key) OR NOT (offer.feedback_candidate_id=c.feedback_candidate_id OR EXISTS(SELECT 1 FROM public.confident_moment_bundle_attachments attachment WHERE attachment.feedback_membership_id=c.feedback_membership_id AND attachment.attached_candidate_id=c.feedback_candidate_id AND attachment.anchor_candidate_id=offer.feedback_candidate_id AND attachment.acquisition_principal_id=p_acquisition_principal_id)) THEN RAISE EXCEPTION 'ROOTING_PHRASE_PRACTICE_SOURCE_INVALID'; END IF;
 IF public.root_phrase_normalize_transcript_v1(attempt.exact_passage)<>public.root_phrase_normalize_transcript_v1(c.phrase_text) OR public.root_phrase_normalize_transcript_v1(attempt.transcript_text)<>public.root_phrase_normalize_transcript_v1(c.phrase_text) THEN RAISE EXCEPTION 'ROOTING_PHRASE_PRACTICE_SOURCE_INVALID'; END IF;
 SELECT * INTO STRICT source_object FROM public.processing_audio_objects row WHERE row.id=lineage.processing_audio_object_id AND row.recording_attempt_id=lineage.recording_attempt_id AND row.acquisition_principal_id=p_acquisition_principal_id AND row.exact_bytes_sha256=lineage.exact_audio_sha256 AND row.deleted_at IS NULL AND NOT EXISTS(SELECT 1 FROM public.processing_audio_object_deletion_events deletion WHERE deletion.audio_object_id=row.id) FOR SHARE;
 SELECT * INTO STRICT practice_object FROM public.processing_audio_objects row WHERE row.id=attempt.processing_audio_object_id AND row.recording_attempt_id=attempt.processing_recording_attempt_id AND row.acquisition_principal_id=p_acquisition_principal_id AND row.exact_bytes_sha256=attempt.exact_audio_sha256 AND row.deleted_at IS NULL AND NOT EXISTS(SELECT 1 FROM public.processing_audio_object_deletion_events deletion WHERE deletion.audio_object_id=row.id) FOR SHARE;
 SELECT * INTO source_binding FROM public.mlc3_target_speaker_bindings row WHERE row.acquisition_principal_id=p_acquisition_principal_id AND row.recording_attempt_id=lineage.recording_attempt_id ORDER BY row.revision_number DESC LIMIT 1 FOR SHARE;
 SELECT * INTO practice_binding FROM public.mlc3_target_speaker_bindings row WHERE row.acquisition_principal_id=p_acquisition_principal_id AND row.recording_attempt_id=attempt.processing_recording_attempt_id ORDER BY row.revision_number DESC LIMIT 1 FOR SHARE;
 SELECT * INTO source_revision FROM public.mlc3_speaker_acquisition_revisions row WHERE row.acquisition_principal_id=p_acquisition_principal_id AND row.recording_attempt_id=lineage.recording_attempt_id ORDER BY row.revision_number DESC LIMIT 1 FOR SHARE;
 SELECT * INTO practice_revision FROM public.mlc3_speaker_acquisition_revisions row WHERE row.acquisition_principal_id=p_acquisition_principal_id AND row.recording_attempt_id=attempt.processing_recording_attempt_id ORDER BY row.revision_number DESC LIMIT 1 FOR SHARE;
 IF source_binding.id IS DISTINCT FROM p_source_target_speaker_binding_id OR practice_binding.id IS DISTINCT FROM p_practice_target_speaker_binding_id OR source_binding.binding_state<>'active' OR practice_binding.binding_state<>'active' OR source_binding.acquisition_revision_id<>source_revision.id OR practice_binding.acquisition_revision_id<>practice_revision.id OR source_revision.speaker_count_status<>'single' OR practice_revision.speaker_count_status<>'single' OR source_revision.speaker_identity_status<>'resolved' OR practice_revision.speaker_identity_status<>'resolved' OR source_binding.speaker_id<>source_revision.speaker_id OR practice_binding.speaker_id<>practice_revision.speaker_id OR source_binding.speaker_id<>practice_binding.speaker_id OR source_binding.audio_object_id<>source_object.id OR practice_binding.audio_object_id<>practice_object.id OR source_binding.clip_id<>lineage.snippet_id OR source_binding.practice_attempt_id IS NOT NULL OR practice_binding.practice_attempt_id<>attempt.id OR practice_binding.clip_id IS NOT NULL OR source_binding.audio_sha256<>lineage.exact_audio_sha256 OR practice_binding.audio_sha256<>attempt.exact_audio_sha256 THEN RAISE EXCEPTION 'ROOTING_PHRASE_SPEAKER_IDENTITY_INVALID'; END IF;
 PERFORM public.require_mlc3_service_access_v2(p_acquisition_principal_id,attempt.rollout_revision_id,attempt.enrollment_revision_id);
 digest:=public.exercise_json_sha256_v1(jsonb_build_object('guard','root-phrase-practice-source-v1','principal',p_acquisition_principal_id,'content',c.id,'practice_attempt',attempt.id,'practice_session',practice.id,'offer',offer.id,'source_lineage',lineage.id,'source_audio',source_object.id,'practice_audio',practice_object.id,'source_binding',source_binding.id,'practice_binding',practice_binding.id,'speaker',source_binding.speaker_id,'source_revision',source_revision.id,'practice_revision',practice_revision.id,'phrase',c.content_version_sha256,'attempt_hash',attempt.attempt_sha256));
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
 IF body<>original THEN EXECUTE body; END IF;
 body:=pg_get_functiondef('public.remove_synthetic_root_phrase_v1(uuid,integer,integer,uuid,uuid,text)'::regprocedure);
 IF position('UPDATE public.ideal_text_part' in body)>0 OR position('transition_ideal_text_root_state_v1' in body)=0 THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_LEGACY_REMOVAL_SHAPE_DRIFT'; END IF;
END $$;

CREATE OR REPLACE FUNCTION public.record_root_phrase_product_action_v2(p_acquisition_principal_id uuid,p_project_id uuid,p_take_id uuid,p_paragraph_id uuid,p_block_key integer,p_action text,p_expected_block_head_action_id uuid,p_source_candidate_id uuid,p_source_evidence_span_id uuid,p_source_feedback_exposure_id uuid,p_source_owner_response_id uuid,p_source_practice_attempt_id uuid,p_source_ideal_text_revision_id bigint,p_source_target_speaker_binding_id uuid,p_practice_target_speaker_binding_id uuid,p_restore_product_action_id uuid,p_policy_version text,p_idempotency_key text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE c public.root_phrase_content_versions; h public.root_phrase_block_heads; old public.root_phrase_product_actions; r public.root_phrase_product_actions; part public.ideal_text_part; u uuid; origin text; persistence text; qualification text; mapped text; rev bigint; digest text; expected_revision bigint; practice_guard jsonb; practice_guard_hash text;
BEGIN
 IF p_policy_version<>'rooting-coverage-30-80-100-v1' OR p_action NOT IN('activate_automatic_root','save_owner_selected_root','lock_current_root','restore_previous_root','unlock_current_root','remove_current_root') OR p_block_key<0 OR COALESCE(btrim(p_idempotency_key),'')='' THEN RAISE EXCEPTION 'ROOTING_PHRASE_AUTOMATIC_POLICY_INVALID'; END IF;
 IF NOT ((p_action='activate_automatic_root' AND p_source_candidate_id IS NOT NULL AND p_source_evidence_span_id IS NOT NULL AND p_source_feedback_exposure_id IS NOT NULL AND p_source_owner_response_id IS NOT NULL AND p_source_practice_attempt_id IS NULL AND p_source_target_speaker_binding_id IS NULL AND p_practice_target_speaker_binding_id IS NULL AND p_restore_product_action_id IS NULL) OR (p_action='save_owner_selected_root' AND p_source_candidate_id IS NOT NULL AND p_source_evidence_span_id IS NOT NULL AND ((p_source_practice_attempt_id IS NULL AND p_source_target_speaker_binding_id IS NULL AND p_practice_target_speaker_binding_id IS NULL) OR (p_source_practice_attempt_id IS NOT NULL AND p_source_target_speaker_binding_id IS NOT NULL AND p_practice_target_speaker_binding_id IS NOT NULL)) AND ((p_source_feedback_exposure_id IS NULL AND p_source_owner_response_id IS NULL) OR (p_source_feedback_exposure_id IS NOT NULL AND p_source_owner_response_id IS NOT NULL)) AND p_restore_product_action_id IS NULL) OR (p_action IN('lock_current_root','unlock_current_root','remove_current_root') AND p_source_candidate_id IS NULL AND p_source_evidence_span_id IS NULL AND p_source_feedback_exposure_id IS NULL AND p_source_owner_response_id IS NULL AND p_source_practice_attempt_id IS NULL AND p_source_ideal_text_revision_id IS NULL AND p_source_target_speaker_binding_id IS NULL AND p_practice_target_speaker_binding_id IS NULL AND p_restore_product_action_id IS NULL) OR (p_action='restore_previous_root' AND p_source_candidate_id IS NULL AND p_source_evidence_span_id IS NULL AND p_source_feedback_exposure_id IS NULL AND p_source_owner_response_id IS NULL AND p_source_practice_attempt_id IS NULL AND p_source_ideal_text_revision_id IS NULL AND p_source_target_speaker_binding_id IS NULL AND p_practice_target_speaker_binding_id IS NULL AND p_restore_product_action_id IS NOT NULL)) THEN RAISE EXCEPTION 'ROOTING_PHRASE_SOURCE_COMBINATION_INVALID'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('root-action-v2:'||p_idempotency_key,0)); PERFORM pg_advisory_xact_lock(hashtextextended('root-block:'||p_project_id::text||':'||p_block_key::text,0)); PERFORM public.require_mlc3_service_access_v2(p_acquisition_principal_id,NULL,NULL); SELECT user_id INTO STRICT u FROM public.owner_principals WHERE id=p_acquisition_principal_id;
 SELECT * INTO r FROM public.root_phrase_product_actions WHERE idempotency_key=p_idempotency_key;
 IF r.id IS NOT NULL THEN
  SELECT * INTO STRICT c FROM public.root_phrase_content_versions WHERE id=r.content_version_id AND project_id=p_project_id AND acquisition_principal_id=p_acquisition_principal_id AND source_ideal_part_id=p_paragraph_id AND block_key=p_block_key;
  PERFORM public.require_synthetic_root_content_live_v1(c.id);
  SELECT * INTO STRICT h FROM public.root_phrase_block_heads WHERE project_id=p_project_id AND slide_index=c.slide_index AND block_key=p_block_key FOR UPDATE;
  mapped:=CASE WHEN p_action='remove_current_root' THEN 'root_remove' WHEN p_expected_block_head_action_id IS NULL THEN 'root_activate' ELSE 'root_replace' END;
  IF p_source_practice_attempt_id IS NOT NULL THEN practice_guard:=public.require_root_phrase_practice_source_live_v1(p_acquisition_principal_id,c.id,p_source_practice_attempt_id,p_source_target_speaker_binding_id,p_practice_target_speaker_binding_id); practice_guard_hash:=practice_guard->>'practice_guard_sha256'; END IF;
  digest:=public.exercise_json_sha256_v1(jsonb_build_object('principal',p_acquisition_principal_id,'project',p_project_id,'take',p_take_id,'paragraph',p_paragraph_id,'block',p_block_key,'action',p_action,'head',p_expected_block_head_action_id,'content',c.id,'origin',r.activation_origin,'persistence',r.persistence_state,'qualification',r.qualification_state,'revision',r.interaction_state_revision,'candidate',p_source_candidate_id,'evidence',p_source_evidence_span_id,'exposure',p_source_feedback_exposure_id,'owner_response',p_source_owner_response_id,'practice_attempt',p_source_practice_attempt_id,'ideal_text_revision',p_source_ideal_text_revision_id,'source_binding',p_source_target_speaker_binding_id,'practice_binding',p_practice_target_speaker_binding_id,'practice_guard',practice_guard_hash,'restore_action',p_restore_product_action_id,'policy',p_policy_version));
  IF r.action<>mapped OR r.interaction_action<>p_action OR r.supersedes_action_id IS DISTINCT FROM p_expected_block_head_action_id OR r.take_id<>p_take_id OR r.owner_user_id<>u OR r.source_candidate_id IS DISTINCT FROM p_source_candidate_id OR r.source_evidence_span_id IS DISTINCT FROM p_source_evidence_span_id OR r.source_feedback_exposure_id IS DISTINCT FROM p_source_feedback_exposure_id OR r.source_owner_response_id IS DISTINCT FROM p_source_owner_response_id OR r.source_practice_attempt_id IS DISTINCT FROM p_source_practice_attempt_id OR r.source_ideal_text_revision_id IS DISTINCT FROM p_source_ideal_text_revision_id OR r.source_target_speaker_binding_id IS DISTINCT FROM p_source_target_speaker_binding_id OR r.practice_target_speaker_binding_id IS DISTINCT FROM p_practice_target_speaker_binding_id OR r.practice_guard_sha256 IS DISTINCT FROM practice_guard_hash OR r.restore_product_action_id IS DISTINCT FROM p_restore_product_action_id OR r.policy_version<>p_policy_version OR r.action_sha256<>digest OR (p_action='remove_current_root' AND (h.active_root_action_id IS NOT NULL OR h.interaction_state_revision<>r.interaction_state_revision)) OR (p_action<>'remove_current_root' AND (h.active_root_action_id<>r.id OR h.interaction_state_revision<>r.interaction_state_revision)) THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_REPLAY_CONFLICT'; END IF;
  PERFORM public.require_mlc3_service_access_v2(p_acquisition_principal_id,NULL,NULL); RETURN to_jsonb(r);
 END IF;
 SELECT * INTO c FROM public.root_phrase_content_versions WHERE project_id=p_project_id AND acquisition_principal_id=p_acquisition_principal_id AND source_ideal_part_id=p_paragraph_id AND block_key=p_block_key AND (p_source_candidate_id IS NULL OR feedback_candidate_id=p_source_candidate_id) ORDER BY created_at DESC,id DESC LIMIT 1; IF c.id IS NULL THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_SOURCE_NOT_LIVE'; END IF; PERFORM public.require_synthetic_root_content_live_v1(c.id);
 SELECT * INTO h FROM public.root_phrase_block_heads WHERE project_id=p_project_id AND slide_index=c.slide_index AND block_key=p_block_key FOR UPDATE; IF h.active_root_action_id IS DISTINCT FROM p_expected_block_head_action_id THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_STALE_REVISION'; END IF; SELECT * INTO part FROM public.ideal_text_part WHERE id=p_paragraph_id AND arc_id=p_project_id AND user_id=u FOR UPDATE; IF part.id IS NULL THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_SOURCE_NOT_LIVE'; END IF; SELECT id INTO expected_revision FROM public.ideal_text_part_revision WHERE part_id=part.id ORDER BY id DESC LIMIT 1;
 IF (p_action='restore_previous_root') IS DISTINCT FROM (p_restore_product_action_id IS NOT NULL) OR (p_action IN('lock_current_root','unlock_current_root','remove_current_root') AND h.active_root_action_id IS NULL) THEN RAISE EXCEPTION 'ROOTING_PHRASE_AUTOMATIC_POLICY_INVALID'; END IF;
 SELECT * INTO old FROM public.root_phrase_product_actions WHERE id=h.active_root_action_id;
 IF old.persistence_state='owner_locked' AND p_action IN('activate_automatic_root','save_owner_selected_root','restore_previous_root') THEN RAISE EXCEPTION 'ROOTING_PHRASE_OWNER_LOCKED'; END IF;
 IF p_source_candidate_id IS NOT NULL AND (c.feedback_candidate_id<>p_source_candidate_id OR c.evidence_span_id<>p_source_evidence_span_id) THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_SOURCE_NOT_LIVE'; END IF;
 IF (c.source_part_version_kind='existing_part_revision_v1' AND p_source_ideal_text_revision_id IS DISTINCT FROM c.source_part_revision_id) OR (c.source_part_version_kind<>'existing_part_revision_v1' AND p_source_ideal_text_revision_id IS NOT NULL) THEN RAISE EXCEPTION 'ROOTING_PHRASE_SOURCE_COMBINATION_INVALID'; END IF;
 IF p_source_feedback_exposure_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.feedback_v3_owner_responses response_row JOIN public.feedback_v3_service_response_bindings response_binding ON response_binding.v3_owner_response_id=response_row.id WHERE response_row.id=p_source_owner_response_id AND response_row.membership_id=c.feedback_membership_id AND response_row.candidate_id=c.feedback_candidate_id AND response_binding.feedback_exposure_id=p_source_feedback_exposure_id) THEN RAISE EXCEPTION 'ROOTING_PHRASE_SOURCE_COMBINATION_INVALID'; END IF;
 IF p_action='save_owner_selected_root' AND p_source_practice_attempt_id IS NULL AND p_source_owner_response_id IS NULL AND c.text_origin<>'manual_edit' THEN RAISE EXCEPTION 'ROOTING_PHRASE_SOURCE_COMBINATION_INVALID'; END IF;
 IF p_action='activate_automatic_root' THEN IF p_source_candidate_id IS NULL OR p_source_evidence_span_id IS NULL OR p_source_feedback_exposure_id IS NULL OR p_source_owner_response_id IS NULL OR NOT EXISTS(SELECT 1 FROM public.feedback_v3_owner_responses x JOIN public.feedback_v3_service_response_bindings b ON b.v3_owner_response_id=x.id WHERE x.id=p_source_owner_response_id AND x.membership_id=c.feedback_membership_id AND x.candidate_id=c.feedback_candidate_id AND x.response='confident_yes' AND b.feedback_exposure_id=p_source_feedback_exposure_id) OR (SELECT z.result FROM public.root_phrase_semantic_results z WHERE z.content_version_id=c.id ORDER BY z.completed_at DESC,z.id DESC LIMIT 1) IS DISTINCT FROM 'aligned' OR NOT EXISTS(SELECT 1 FROM public.root_phrase_coverage_items i JOIN public.root_phrase_coverage_frames f ON f.id=i.frame_id WHERE f.take_id=p_take_id AND f.feedback_membership_id=c.feedback_membership_id AND i.anchor_candidate_id=p_source_candidate_id AND i.content_version_id=c.id AND i.coverage_item_state='eligible_automatic_proposal') THEN RAISE EXCEPTION 'ROOTING_PHRASE_AUTOMATIC_POLICY_INVALID'; END IF; origin:='automatic_product_selection'; persistence:='automatic_replaceable'; qualification:='not_qualified_reference';
 ELSIF p_action IN('save_owner_selected_root','restore_previous_root') THEN origin:='owner_selection'; persistence:='automatic_replaceable'; qualification:='not_qualified_reference';
 ELSE origin:=COALESCE(old.activation_origin,'owner_selection'); persistence:=CASE p_action WHEN 'lock_current_root' THEN 'owner_locked' WHEN 'unlock_current_root' THEN 'automatic_replaceable' ELSE COALESCE(old.persistence_state,'automatic_replaceable') END; qualification:=COALESCE(old.qualification_state,'not_qualified_reference'); END IF;
 IF p_restore_product_action_id IS NOT NULL THEN SELECT * INTO STRICT old FROM public.root_phrase_product_actions WHERE id=p_restore_product_action_id AND project_id=p_project_id AND acquisition_principal_id=p_acquisition_principal_id AND action IN('root_activate','root_replace'); SELECT * INTO STRICT c FROM public.root_phrase_content_versions WHERE id=old.content_version_id AND source_ideal_part_id=p_paragraph_id AND block_key=p_block_key; PERFORM public.require_synthetic_root_content_live_v1(c.id); END IF;
 IF p_source_practice_attempt_id IS NOT NULL THEN practice_guard:=public.require_root_phrase_practice_source_live_v1(p_acquisition_principal_id,c.id,p_source_practice_attempt_id,p_source_target_speaker_binding_id,p_practice_target_speaker_binding_id); practice_guard_hash:=practice_guard->>'practice_guard_sha256'; END IF;
 rev:=COALESCE(h.interaction_state_revision,0)+1; mapped:=CASE WHEN p_action='remove_current_root' THEN 'root_remove' WHEN h.active_root_action_id IS NULL THEN 'root_activate' ELSE 'root_replace' END; digest:=public.exercise_json_sha256_v1(jsonb_build_object('principal',p_acquisition_principal_id,'project',p_project_id,'take',p_take_id,'paragraph',p_paragraph_id,'block',p_block_key,'action',p_action,'head',p_expected_block_head_action_id,'content',c.id,'origin',origin,'persistence',persistence,'qualification',qualification,'revision',rev,'candidate',p_source_candidate_id,'evidence',p_source_evidence_span_id,'exposure',p_source_feedback_exposure_id,'owner_response',p_source_owner_response_id,'practice_attempt',p_source_practice_attempt_id,'ideal_text_revision',p_source_ideal_text_revision_id,'source_binding',p_source_target_speaker_binding_id,'practice_binding',p_practice_target_speaker_binding_id,'practice_guard',practice_guard_hash,'restore_action',p_restore_product_action_id,'policy',p_policy_version));
 INSERT INTO public.root_phrase_product_actions(acquisition_principal_id,project_id,content_version_id,qualification_revision_id,owner_user_id,action,supersedes_action_id,interaction_state_revision,action_sha256,idempotency_key,take_id,interaction_action,activation_origin,persistence_state,qualification_state,source_candidate_id,source_evidence_span_id,source_feedback_exposure_id,source_owner_response_id,source_practice_attempt_id,source_ideal_text_revision_id,source_target_speaker_binding_id,practice_target_speaker_binding_id,practice_guard_sha256,restore_product_action_id,policy_version) VALUES(p_acquisition_principal_id,p_project_id,c.id,NULL,u,mapped,h.active_root_action_id,rev,digest,p_idempotency_key,p_take_id,p_action,origin,persistence,qualification,p_source_candidate_id,p_source_evidence_span_id,p_source_feedback_exposure_id,p_source_owner_response_id,p_source_practice_attempt_id,p_source_ideal_text_revision_id,p_source_target_speaker_binding_id,p_practice_target_speaker_binding_id,practice_guard_hash,p_restore_product_action_id,p_policy_version) RETURNING * INTO r;
 PERFORM public.transition_ideal_text_root_state_v1(p_acquisition_principal_id,p_project_id,p_take_id,c.id,expected_revision,CASE p_action WHEN 'activate_automatic_root' THEN 'set_automatic_root' WHEN 'save_owner_selected_root' THEN 'set_owner_selected_root' WHEN 'restore_previous_root' THEN 'restore_owner_selected_root' ELSE p_action END,p_idempotency_key||':ideal-text');
 INSERT INTO public.root_phrase_block_heads(acquisition_principal_id,project_id,slide_index,block_key,active_root_action_id,interaction_state_revision) VALUES(p_acquisition_principal_id,p_project_id,c.slide_index,p_block_key,CASE WHEN p_action='remove_current_root' THEN NULL ELSE r.id END,rev) ON CONFLICT(project_id,slide_index,block_key) DO UPDATE SET active_root_action_id=EXCLUDED.active_root_action_id,interaction_state_revision=EXCLUDED.interaction_state_revision,updated_at=clock_timestamp(); PERFORM public.require_mlc3_service_access_v2(p_acquisition_principal_id,NULL,NULL); RETURN to_jsonb(r);
END $$;

-- Security closure is applied after every function declaration below.
-- deferred
-- deferred
-- Function execution closure is applied after every declaration below.
-- transaction remains open through all declarations

CREATE OR REPLACE FUNCTION public.ack_confident_moment_bundle_item_render_v1(p_acquisition_principal_id uuid,p_bundle_attachment_id uuid,p_presentation_id uuid,p_render_instance_id uuid,p_idempotency_key text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE a public.confident_moment_bundle_attachments; u uuid; r public.feedback_v3_service_render_receipts;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('confident-moment-render:'||p_idempotency_key,0)); SELECT * INTO STRICT a FROM public.confident_moment_bundle_attachments WHERE id=p_bundle_attachment_id AND acquisition_principal_id=p_acquisition_principal_id;
 IF a.canonical_feedback_presentation_id<>p_presentation_id THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_ATTACHMENT_INVALID'; END IF; SELECT user_id INTO STRICT u FROM public.owner_principals WHERE id=p_acquisition_principal_id;
 SELECT * INTO r FROM public.ack_feedback_v3_service_render_v1(p_acquisition_principal_id,u,a.feedback_membership_id,a.attached_candidate_id,a.canonical_feedback_presentation_id,p_render_instance_id,(SELECT content_identity_sha256 FROM public.feedback_v3_memberships WHERE id=a.feedback_membership_id),clock_timestamp(),'confident-moment-coaching-bundle-v1',p_idempotency_key);
 RETURN jsonb_build_object('render_receipt_id',r.id,'feedback_exposure_id',r.feedback_exposure_id,'dataset_eligible',false);
END $$;

CREATE OR REPLACE FUNCTION public.freeze_root_phrase_coverage_frame_v1(p_acquisition_principal_id uuid,p_project_id uuid,p_take_id uuid,p_feedback_membership_id uuid,p_document_snapshot_id uuid,p_policy_version text,p_idempotency_key text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE m public.feedback_v3_memberships; s public.ideal_text_document_snapshots; f public.root_phrase_coverage_frames; n integer; target integer; achieved integer; inventory text; digest text; x record; pos integer:=0; state text;
BEGIN
 IF p_policy_version<>'rooting-coverage-30-80-100-v1' OR COALESCE(btrim(p_idempotency_key),'')='' THEN RAISE EXCEPTION 'ROOTING_COVERAGE_INVENTORY_INVALID'; END IF; PERFORM pg_advisory_xact_lock(hashtextextended('root-coverage:'||p_idempotency_key,0)); PERFORM pg_advisory_xact_lock(hashtextextended('root-coverage-frame:'||p_take_id::text||':'||p_feedback_membership_id::text||':'||p_document_snapshot_id::text,0)); PERFORM public.require_mlc3_service_access_v2(p_acquisition_principal_id,NULL,NULL);
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

DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['confident_moment_bundle_attachments','root_phrase_coverage_frames','root_phrase_coverage_items','feedback_language_revision_deliveries'] LOOP
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t); EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('REVOKE ALL ON TABLE public.%I FROM PUBLIC,anon,authenticated,service_role',t);
  EXECUTE format('DROP TRIGGER IF EXISTS %I ON public.%I',t||'_append_only',t);
  EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.reject_confident_moment_mutation_v1()',t||'_append_only',t);
 END LOOP;
END $$;
DROP TRIGGER IF EXISTS feedback_revisions_append_only ON public.feedback_revisions;
CREATE TRIGGER feedback_revisions_append_only BEFORE UPDATE OR DELETE ON public.feedback_revisions FOR EACH ROW EXECUTE FUNCTION public.reject_confident_moment_mutation_v1();
ALTER TABLE public.feedback_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.feedback_revisions FORCE ROW LEVEL SECURITY;
ALTER TABLE public.root_phrase_product_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.root_phrase_product_actions FORCE ROW LEVEL SECURITY;
REVOKE INSERT,UPDATE,DELETE ON public.feedback_revisions,public.root_phrase_product_actions FROM PUBLIC,anon,authenticated,service_role;
DO $$ DECLARE f text; BEGIN
 FOREACH f IN ARRAY ARRAY['public.reject_confident_moment_mutation_v1()','public.require_root_phrase_practice_source_live_v1(uuid,uuid,uuid,uuid,uuid)','public.transition_ideal_text_root_state_v1(uuid,uuid,uuid,uuid,bigint,text,text)','public.prepare_confident_moment_bundle_v1(uuid,uuid,uuid,uuid,uuid,text)','public.ack_confident_moment_bundle_item_render_v1(uuid,uuid,uuid,uuid,text)','public.freeze_root_phrase_coverage_frame_v1(uuid,uuid,uuid,uuid,uuid,text,text)','public.record_feedback_language_coach_revision_v1(uuid,uuid,uuid,uuid,uuid,uuid,uuid,uuid,text,text,text,text,uuid,text)','public.schedule_feedback_language_revision_v1(uuid,uuid,uuid,uuid,text)','public.ack_feedback_language_revision_render_v1(uuid,uuid,uuid,uuid,text)','public.record_root_phrase_product_action_v2(uuid,uuid,uuid,uuid,integer,text,uuid,uuid,uuid,uuid,uuid,uuid,bigint,uuid,uuid,uuid,text,text)'] LOOP
  EXECUTE 'REVOKE ALL ON FUNCTION '||f||' FROM PUBLIC,anon,authenticated,service_role';
 END LOOP;
END $$;
NOTIFY pgrst,'reload schema';
COMMIT;
