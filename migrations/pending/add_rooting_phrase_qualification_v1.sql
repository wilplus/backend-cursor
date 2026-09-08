-- Rooting Phrase Qualification V1. Pending and deliberately unassigned.
-- Product-routing only: no judgment, supervision, exposure, or dataset rows.
-- All writers remain synthetic-only and no runtime route is enabled.

BEGIN;

CREATE TABLE IF NOT EXISTS public.root_phrase_content_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    project_id UUID NOT NULL REFERENCES public.projects(id) ON DELETE RESTRICT,
    feedback_membership_id UUID NOT NULL
        REFERENCES public.feedback_v3_memberships(id) ON DELETE RESTRICT,
    feedback_candidate_id UUID NOT NULL,
    authorization_check_id UUID NOT NULL
        REFERENCES public.exercise_authorization_checks(id) ON DELETE RESTRICT,
    document_snapshot_id UUID NOT NULL
        REFERENCES public.ideal_text_document_snapshots(id) ON DELETE RESTRICT,
    source_ideal_part_id UUID NOT NULL,
    source_part_revision_id BIGINT NULL
        REFERENCES public.ideal_text_part_revision(id) ON DELETE RESTRICT,
    source_correction_decision_id UUID NULL
        REFERENCES public.correction_decisions(id) ON DELETE RESTRICT,
    source_part_version_kind TEXT NOT NULL CHECK (source_part_version_kind IN (
        'existing_part_revision_v1', 'canonical_snapshot_baseline_v1'
    )),
    slide_index INTEGER NOT NULL CHECK (slide_index >= 0),
    block_key INTEGER NOT NULL CHECK (block_key >= 0),
    paragraph_text TEXT NOT NULL,
    paragraph_text_sha256 TEXT NOT NULL CHECK (
        paragraph_text_sha256 ~ '^[0-9a-f]{64}$'
    ),
    phrase_text TEXT NOT NULL CHECK (length(btrim(phrase_text)) > 0),
    phrase_start INTEGER NOT NULL CHECK (phrase_start >= 0),
    phrase_end INTEGER NOT NULL CHECK (phrase_end > phrase_start),
    transcript_normalization_version TEXT NOT NULL CHECK (
        transcript_normalization_version = 'root-transcript-normalization-v1'
    ),
    text_origin TEXT NOT NULL CHECK (text_origin IN (
        'unchanged_manager', 'accepted_rewrite', 'manual_edit'
    )),
    content_version_kind TEXT NOT NULL CHECK (
        content_version_kind = 'canonical_snapshot_part_v1'
    ),
    content_version_sha256 TEXT NOT NULL CHECK (
        content_version_sha256 ~ '^[0-9a-f]{64}$'
    ),
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    FOREIGN KEY (feedback_membership_id, feedback_candidate_id)
        REFERENCES public.feedback_v3_membership_items(membership_id, candidate_id)
        ON DELETE RESTRICT,
    UNIQUE (feedback_membership_id, feedback_candidate_id, source_ideal_part_id,
            phrase_start, phrase_end, content_version_sha256),
    UNIQUE (id, acquisition_principal_id),
    CHECK ((source_part_version_kind = 'existing_part_revision_v1'
            AND source_part_revision_id IS NOT NULL)
        OR (source_part_version_kind = 'canonical_snapshot_baseline_v1'
            AND source_part_revision_id IS NULL)),
    CHECK ((text_origin = 'accepted_rewrite'
            AND source_correction_decision_id IS NOT NULL)
        OR (text_origin <> 'accepted_rewrite'
            AND source_correction_decision_id IS NULL)),
    CHECK (text_origin <> 'manual_edit'
        OR source_part_version_kind = 'existing_part_revision_v1'),
    CHECK (phrase_end <= length(paragraph_text))
);

-- The file is still unassigned, but corrective review may reapply it over the
-- preceding synthetic snapshot.  Preserve those historical rows while making
-- them fail closed: only newly proven rows may satisfy the live helper.
ALTER TABLE public.root_phrase_content_versions
    ADD COLUMN IF NOT EXISTS authorization_check_id UUID,
    ADD COLUMN IF NOT EXISTS source_correction_decision_id UUID;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'root_content_authorization_check_fk') THEN
        ALTER TABLE public.root_phrase_content_versions
          ADD CONSTRAINT root_content_authorization_check_fk
          FOREIGN KEY (authorization_check_id)
          REFERENCES public.exercise_authorization_checks(id) ON DELETE RESTRICT
          NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'root_content_correction_decision_fk') THEN
        ALTER TABLE public.root_phrase_content_versions
          ADD CONSTRAINT root_content_correction_decision_fk
          FOREIGN KEY (source_correction_decision_id)
          REFERENCES public.correction_decisions(id) ON DELETE RESTRICT
          NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'root_content_authorization_required') THEN
        ALTER TABLE public.root_phrase_content_versions
          ADD CONSTRAINT root_content_authorization_required
          CHECK (authorization_check_id IS NOT NULL) NOT VALID;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.root_phrase_semantic_input_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content_version_id UUID NOT NULL
        REFERENCES public.root_phrase_content_versions(id) ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    project_id UUID NOT NULL REFERENCES public.projects(id) ON DELETE RESTRICT,
    document_snapshot_id UUID NOT NULL
        REFERENCES public.ideal_text_document_snapshots(id) ON DELETE RESTRICT,
    project_goal_snapshot JSONB NOT NULL CHECK (
        jsonb_typeof(project_goal_snapshot) = 'object'
    ),
    slide_context_snapshot JSONB NOT NULL CHECK (
        jsonb_typeof(slide_context_snapshot) = 'object'
    ),
    project_goal_sha256 TEXT NOT NULL CHECK (
        project_goal_sha256 ~ '^[0-9a-f]{64}$'
    ),
    slide_context_sha256 TEXT NOT NULL CHECK (
        slide_context_sha256 ~ '^[0-9a-f]{64}$'
    ),
    input_snapshot_sha256 TEXT NOT NULL CHECK (
        input_snapshot_sha256 ~ '^[0-9a-f]{64}$'
    ),
    snapshot_schema_version TEXT NOT NULL CHECK (
        snapshot_schema_version = 'root-semantic-input-v1'
    ),
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    FOREIGN KEY (content_version_id, acquisition_principal_id)
        REFERENCES public.root_phrase_content_versions(id, acquisition_principal_id)
        ON DELETE RESTRICT,
    UNIQUE (content_version_id, input_snapshot_sha256),
    UNIQUE (id, acquisition_principal_id)
);

CREATE TABLE IF NOT EXISTS public.root_phrase_semantic_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content_version_id UUID NOT NULL
        REFERENCES public.root_phrase_content_versions(id) ON DELETE RESTRICT,
    semantic_input_snapshot_id UUID NOT NULL
        REFERENCES public.root_phrase_semantic_input_snapshots(id) ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    result TEXT NOT NULL CHECK (result IN (
        'aligned', 'uncertain', 'not_aligned', 'unavailable'
    )),
    reason_code TEXT NOT NULL,
    result_origin TEXT NOT NULL CHECK (result_origin = 'machine_policy'),
    project_goal_sha256 TEXT NOT NULL CHECK (project_goal_sha256 ~ '^[0-9a-f]{64}$'),
    slide_context_sha256 TEXT NOT NULL CHECK (slide_context_sha256 ~ '^[0-9a-f]{64}$'),
    prompt_version TEXT NOT NULL,
    policy_version TEXT NOT NULL CHECK (
        policy_version = 'root-semantic-alignment-v1'
    ),
    model_version TEXT NOT NULL,
    code_version TEXT NOT NULL,
    input_sha256 TEXT NOT NULL CHECK (input_sha256 ~ '^[0-9a-f]{64}$'),
    output_sha256 TEXT NOT NULL CHECK (output_sha256 ~ '^[0-9a-f]{64}$'),
    completed_at TIMESTAMPTZ NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    FOREIGN KEY (content_version_id, acquisition_principal_id)
        REFERENCES public.root_phrase_content_versions(id, acquisition_principal_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (semantic_input_snapshot_id, acquisition_principal_id)
        REFERENCES public.root_phrase_semantic_input_snapshots(id, acquisition_principal_id)
        ON DELETE RESTRICT,
    UNIQUE (content_version_id, policy_version, input_sha256),
    UNIQUE (id, acquisition_principal_id)
);

ALTER TABLE public.root_phrase_semantic_results
    ADD COLUMN IF NOT EXISTS semantic_input_snapshot_id UUID;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'root_semantic_input_snapshot_fk') THEN
        ALTER TABLE public.root_phrase_semantic_results
          ADD CONSTRAINT root_semantic_input_snapshot_fk
          FOREIGN KEY (semantic_input_snapshot_id)
          REFERENCES public.root_phrase_semantic_input_snapshots(id)
          ON DELETE RESTRICT NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'root_semantic_input_snapshot_required') THEN
        ALTER TABLE public.root_phrase_semantic_results
          ADD CONSTRAINT root_semantic_input_snapshot_required
          CHECK (semantic_input_snapshot_id IS NOT NULL) NOT VALID;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.root_phrase_owner_alignment_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content_version_id UUID NOT NULL
        REFERENCES public.root_phrase_content_versions(id) ON DELETE RESTRICT,
    semantic_result_id UUID NOT NULL
        REFERENCES public.root_phrase_semantic_results(id) ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    owner_user_id UUID NOT NULL,
    action TEXT NOT NULL CHECK (action IN (
        'root_alignment_confirm', 'root_alignment_reject'
    )),
    idempotency_key TEXT NOT NULL UNIQUE,
    acted_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    UNIQUE (content_version_id, semantic_result_id, owner_user_id),
    FOREIGN KEY (content_version_id, acquisition_principal_id)
        REFERENCES public.root_phrase_content_versions(id, acquisition_principal_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (semantic_result_id, acquisition_principal_id)
        REFERENCES public.root_phrase_semantic_results(id, acquisition_principal_id)
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS public.root_phrase_qualification_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    content_version_id UUID NOT NULL
        REFERENCES public.root_phrase_content_versions(id) ON DELETE RESTRICT,
    semantic_result_id UUID NOT NULL
        REFERENCES public.root_phrase_semantic_results(id) ON DELETE RESTRICT,
    owner_alignment_action_id UUID NULL
        REFERENCES public.root_phrase_owner_alignment_actions(id) ON DELETE RESTRICT,
    confidence_response_id UUID NULL
        REFERENCES public.feedback_v3_owner_responses(id) ON DELETE RESTRICT,
    practice_selection_revision_id UUID NULL
        REFERENCES public.exercise_practice_selection_revisions(id) ON DELETE RESTRICT,
    practice_attempt_id UUID NULL
        REFERENCES public.exercise_practice_attempts(id) ON DELETE RESTRICT,
    qualification_path TEXT NOT NULL CHECK (qualification_path IN (
        'unchanged_confident_voice', 'accepted_rewrite',
        'manual_edit', 'strong_formulation'
    )),
    routing_state TEXT NOT NULL CHECK (routing_state IN (
        'eligible_direct', 'eligible_after_rerecord', 'pending_recording',
        'pending_owner_alignment_confirmation', 'blocked_semantic_mismatch',
        'blocked_semantic_unavailable', 'blocked_confidence_response',
        'blocked_audio_or_transcript', 'blocked_existing_block_root',
        'stale_text_revision', 'invalidated'
    )),
    evidence_sha256 TEXT NOT NULL CHECK (evidence_sha256 ~ '^[0-9a-f]{64}$'),
    qualification_policy_version TEXT NOT NULL CHECK (
        qualification_policy_version = 'rooting-phrase-qualification-v1'
    ),
    idempotency_key TEXT NOT NULL UNIQUE,
    qualified_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    FOREIGN KEY (content_version_id, acquisition_principal_id)
        REFERENCES public.root_phrase_content_versions(id, acquisition_principal_id)
        ON DELETE RESTRICT,
    CHECK ((practice_selection_revision_id IS NULL AND practice_attempt_id IS NULL)
        OR (practice_selection_revision_id IS NOT NULL AND practice_attempt_id IS NOT NULL)),
    UNIQUE (id, acquisition_principal_id)
);

CREATE TABLE IF NOT EXISTS public.root_phrase_product_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    project_id UUID NOT NULL REFERENCES public.projects(id) ON DELETE RESTRICT,
    content_version_id UUID NOT NULL
        REFERENCES public.root_phrase_content_versions(id) ON DELETE RESTRICT,
    qualification_revision_id UUID NULL
        REFERENCES public.root_phrase_qualification_revisions(id) ON DELETE RESTRICT,
    owner_user_id UUID NOT NULL,
    action TEXT NOT NULL CHECK (action IN (
        'paragraph_lock', 'root_activate', 'root_replace', 'root_remove'
    )),
    supersedes_action_id UUID NULL
        REFERENCES public.root_phrase_product_actions(id) ON DELETE RESTRICT,
    interaction_state_revision BIGINT NULL CHECK (interaction_state_revision > 0),
    action_sha256 TEXT NOT NULL CHECK (action_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE,
    acted_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    FOREIGN KEY (content_version_id, acquisition_principal_id)
        REFERENCES public.root_phrase_content_versions(id, acquisition_principal_id)
        ON DELETE RESTRICT,
    CHECK ((action = 'paragraph_lock' AND interaction_state_revision IS NULL)
        OR (action <> 'paragraph_lock' AND interaction_state_revision IS NOT NULL)),
    CHECK ((action IN ('root_activate','root_replace')
            AND qualification_revision_id IS NOT NULL)
        OR (action IN ('paragraph_lock','root_remove')
            AND qualification_revision_id IS NULL)),
    UNIQUE (id, acquisition_principal_id)
);

CREATE TABLE IF NOT EXISTS public.root_phrase_block_heads (
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    project_id UUID NOT NULL REFERENCES public.projects(id) ON DELETE RESTRICT,
    slide_index INTEGER NOT NULL CHECK (slide_index >= 0),
    block_key INTEGER NOT NULL CHECK (block_key >= 0),
    active_root_action_id UUID NULL,
    interaction_state_revision BIGINT NOT NULL CHECK (interaction_state_revision > 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (project_id, slide_index, block_key),
    FOREIGN KEY (active_root_action_id, acquisition_principal_id)
        REFERENCES public.root_phrase_product_actions(id, acquisition_principal_id)
        ON DELETE RESTRICT
);

-- Canonical correction decisions predate exact candidate/output provenance.
-- Preserve historical rows as evidence, but make them ineligible for RPQ and
-- require every new correction response to bind the precise exposed artifact.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'feedback_candidates_id_evidence_unique') THEN
        ALTER TABLE public.feedback_candidates
          ADD CONSTRAINT feedback_candidates_id_evidence_unique
          UNIQUE (id, evidence_span_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'feedback_exposures_id_candidate_unique') THEN
        ALTER TABLE public.feedback_exposures
          ADD CONSTRAINT feedback_exposures_id_candidate_unique
          UNIQUE (id, candidate_id);
    END IF;
END $$;

ALTER TABLE public.correction_decisions
    ADD COLUMN IF NOT EXISTS candidate_id UUID,
    ADD COLUMN IF NOT EXISTS feedback_membership_id UUID,
    ADD COLUMN IF NOT EXISTS feedback_exposure_id UUID,
    ADD COLUMN IF NOT EXISTS candidate_output_sha256 TEXT,
    ADD COLUMN IF NOT EXISTS candidate_output_contract_version TEXT;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'correction_decision_candidate_evidence_fk') THEN
        ALTER TABLE public.correction_decisions
          ADD CONSTRAINT correction_decision_candidate_evidence_fk
          FOREIGN KEY (candidate_id, evidence_span_id)
          REFERENCES public.feedback_candidates(id, evidence_span_id)
          ON DELETE RESTRICT NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'correction_decision_membership_candidate_fk') THEN
        ALTER TABLE public.correction_decisions
          ADD CONSTRAINT correction_decision_membership_candidate_fk
          FOREIGN KEY (feedback_membership_id, candidate_id)
          REFERENCES public.feedback_v3_membership_items(membership_id, candidate_id)
          ON DELETE RESTRICT NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'correction_decision_exposure_candidate_fk') THEN
        ALTER TABLE public.correction_decisions
          ADD CONSTRAINT correction_decision_exposure_candidate_fk
          FOREIGN KEY (feedback_exposure_id, candidate_id)
          REFERENCES public.feedback_exposures(id, candidate_id)
          ON DELETE RESTRICT NOT VALID;
    END IF;
END $$;
ALTER TABLE public.correction_decisions
    DROP CONSTRAINT IF EXISTS correction_decision_exact_output_required;
ALTER TABLE public.correction_decisions
    ADD CONSTRAINT correction_decision_exact_output_required CHECK (
        candidate_id IS NOT NULL
        AND feedback_membership_id IS NOT NULL
        AND feedback_exposure_id IS NOT NULL
        AND candidate_output_sha256 ~ '^[0-9a-f]{64}$'
        AND candidate_output_contract_version = 'feedback-candidate-output-v1'
    ) NOT VALID;

CREATE OR REPLACE FUNCTION public.feedback_candidate_output_sha256_v1(
    p_candidate_id UUID
) RETURNS TEXT LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=public AS $$
DECLARE candidate public.feedback_candidates;
BEGIN
    SELECT * INTO STRICT candidate FROM public.feedback_candidates
     WHERE id = p_candidate_id;
    RETURN public.exercise_json_sha256_v1(jsonb_build_object(
        'candidate_id', candidate.id,
        'candidate_set_id', candidate.candidate_set_id,
        'evidence_span_id', candidate.evidence_span_id,
        'candidate_key', candidate.candidate_key,
        'feedback_family', candidate.feedback_family,
        'lane', candidate.lane,
        'generated_output', candidate.generated_output,
        'output_contract_version', 'feedback-candidate-output-v1'));
END;
$$;

CREATE OR REPLACE FUNCTION public.record_feedback_human_decision_v1(
    p_project_id UUID,
    p_take_id UUID,
    p_rater_id UUID,
    p_feedback_membership_id UUID,
    p_candidate_id UUID,
    p_feedback_exposure_id UUID,
    p_feedback_family TEXT,
    p_value TEXT,
    p_taxonomy_version TEXT,
    p_idempotency_key TEXT
) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE
    take_row public.v2_sessions;
    membership_row public.feedback_v3_memberships;
    membership_item public.feedback_v3_membership_items;
    owner_id UUID;
    candidate_row public.feedback_candidates;
    exposure_row public.feedback_exposures;
    decision_id UUID := gen_random_uuid();
    existing_id UUID; existing_evidence_id UUID; existing_rater_id UUID;
    existing_value TEXT; existing_candidate_id UUID;
    existing_membership_id UUID; existing_exposure_id UUID;
    existing_output_sha256 TEXT; existing_output_version TEXT;
    current_correction public.correction_decisions;
    candidate_output_sha256 TEXT;
BEGIN
    SELECT * INTO take_row FROM public.v2_sessions
     WHERE id = p_take_id AND project_id = p_project_id FOR SHARE;
    IF take_row.id IS NULL OR take_row.user_id IS DISTINCT FROM p_rater_id THEN
        RAISE EXCEPTION 'feedback decision ownership rejected';
    END IF;
    SELECT id INTO owner_id FROM public.owner_principals
     WHERE id = take_row.owner_principal_id AND user_id = p_rater_id;
    IF owner_id IS NULL THEN
        RAISE EXCEPTION 'feedback decision principal rejected';
    END IF;
    SELECT * INTO membership_row
      FROM public.require_synthetic_feedback_v3_membership_live_v1(
          p_feedback_membership_id);
    IF membership_row.take_id <> p_take_id
       OR membership_row.project_id <> p_project_id
       OR membership_row.acquisition_principal_id <> owner_id
    THEN RAISE EXCEPTION 'feedback decision membership rejected'; END IF;
    SELECT * INTO STRICT membership_item
      FROM public.feedback_v3_membership_items item
     WHERE item.membership_id = membership_row.id
       AND item.candidate_id = p_candidate_id
       AND item.selected = true
       AND item.eligibility = 'eligible'
       AND item.feedback_family = p_feedback_family;
    SELECT candidate.* INTO STRICT candidate_row
      FROM public.feedback_candidates candidate
     WHERE candidate.id = membership_item.candidate_id
       AND candidate.candidate_set_id = membership_row.candidate_set_id
       AND candidate.evidence_span_id = membership_item.evidence_span_id
       AND candidate.feedback_family = p_feedback_family;
    SELECT exposure.* INTO STRICT exposure_row
      FROM public.feedback_exposures exposure
     WHERE exposure.id = p_feedback_exposure_id
       AND exposure.candidate_id = candidate_row.id
       AND exposure.candidate_set_id = membership_row.candidate_set_id
       AND exposure.feedback_family = p_feedback_family
       AND exposure.is_selected = true
       AND exposure.position_shown = membership_item.position_shown;

    IF p_feedback_family = 'confident_voice' THEN
        IF p_value NOT IN ('yes','in_between','no','not_sure','audio_unclear') THEN
            RAISE EXCEPTION 'invalid confidence self-report';
        END IF;
        SELECT id,evidence_span_id,rater_id,value
          INTO existing_id,existing_evidence_id,existing_rater_id,existing_value
          FROM public.confidence_self_reports
         WHERE idempotency_key=p_idempotency_key;
        IF existing_id IS NULL THEN
            INSERT INTO public.confidence_self_reports(
                id,evidence_span_id,value,rater_id,taxonomy_version,idempotency_key)
            VALUES(decision_id,candidate_row.evidence_span_id,p_value,p_rater_id,
                   p_taxonomy_version,p_idempotency_key);
        ELSE
            IF existing_evidence_id IS DISTINCT FROM candidate_row.evidence_span_id
               OR existing_rater_id IS DISTINCT FROM p_rater_id
               OR existing_value IS DISTINCT FROM p_value THEN
                RAISE EXCEPTION 'confidence decision idempotency conflict';
            END IF;
            decision_id:=existing_id;
        END IF;
    ELSIF p_feedback_family = 'great_formulation' THEN
        IF p_value NOT IN ('useful','not_useful','not_sure') THEN
            RAISE EXCEPTION 'invalid praise response';
        END IF;
        SELECT id,evidence_span_id,rater_id,value
          INTO existing_id,existing_evidence_id,existing_rater_id,existing_value
          FROM public.praise_helpfulness WHERE idempotency_key=p_idempotency_key;
        IF existing_id IS NULL THEN
            INSERT INTO public.praise_helpfulness(
                id,evidence_span_id,value,rater_id,taxonomy_version,idempotency_key)
            VALUES(decision_id,candidate_row.evidence_span_id,p_value,p_rater_id,
                   p_taxonomy_version,p_idempotency_key);
        ELSE
            IF existing_evidence_id IS DISTINCT FROM candidate_row.evidence_span_id
               OR existing_rater_id IS DISTINCT FROM p_rater_id
               OR existing_value IS DISTINCT FROM p_value THEN
                RAISE EXCEPTION 'praise decision idempotency conflict';
            END IF;
            decision_id:=existing_id;
        END IF;
    ELSIF p_feedback_family = 'rewrite_clarity' THEN
        IF p_value NOT IN ('accept_proposed','keep_original') THEN
            RAISE EXCEPTION 'invalid correction decision';
        END IF;
        candidate_output_sha256 :=
            public.feedback_candidate_output_sha256_v1(candidate_row.id);
        PERFORM pg_advisory_xact_lock(hashtextextended(
            'canonical-correction:' || candidate_row.evidence_span_id::TEXT ||
            ':' || p_rater_id::TEXT, 0));
        SELECT decision.id,decision.evidence_span_id,decision.rater_id,
               decision.value,decision.candidate_id,
               decision.feedback_membership_id,
               decision.feedback_exposure_id,
               decision.candidate_output_sha256,
               decision.candidate_output_contract_version
          INTO existing_id,existing_evidence_id,existing_rater_id,existing_value,
               existing_candidate_id,existing_membership_id,existing_exposure_id,
               existing_output_sha256,existing_output_version
          FROM public.correction_decisions decision
         WHERE decision.idempotency_key=p_idempotency_key;
        IF existing_id IS NOT NULL THEN
            IF existing_evidence_id IS DISTINCT FROM candidate_row.evidence_span_id
               OR existing_rater_id IS DISTINCT FROM p_rater_id
               OR existing_value IS DISTINCT FROM p_value
               OR existing_candidate_id IS DISTINCT FROM candidate_row.id
               OR existing_membership_id IS DISTINCT FROM membership_row.id
               OR existing_exposure_id IS DISTINCT FROM exposure_row.id
               OR existing_output_sha256 IS DISTINCT FROM candidate_output_sha256
               OR existing_output_version IS DISTINCT FROM
                    'feedback-candidate-output-v1' THEN
                RAISE EXCEPTION 'correction decision idempotency conflict';
            END IF;
            decision_id:=existing_id;
        ELSE
            SELECT decision.* INTO current_correction
              FROM public.correction_decisions decision
             WHERE decision.evidence_span_id=candidate_row.evidence_span_id
               AND decision.rater_id=p_rater_id
               AND NOT EXISTS (
                   SELECT 1 FROM public.correction_decisions later_decision
                    WHERE later_decision.supersedes_id=decision.id)
             ORDER BY decision.created_at DESC,decision.id DESC LIMIT 1
             FOR UPDATE;
            INSERT INTO public.correction_decisions(
                id,evidence_span_id,value,rater_id,taxonomy_version,
                supersedes_id,candidate_id,feedback_membership_id,
                feedback_exposure_id,candidate_output_sha256,
                candidate_output_contract_version,idempotency_key)
            VALUES(decision_id,candidate_row.evidence_span_id,p_value,p_rater_id,
                p_taxonomy_version,current_correction.id,candidate_row.id,
                membership_row.id,exposure_row.id,candidate_output_sha256,
                'feedback-candidate-output-v1',
                p_idempotency_key);
        END IF;
    ELSE
        RAISE EXCEPTION 'unknown feedback family';
    END IF;
    RETURN jsonb_build_object(
        'decision_id',decision_id,
        'evidence_span_id',candidate_row.evidence_span_id,
        'candidate_id',candidate_row.id,
        'feedback_membership_id',membership_row.id,
        'feedback_exposure_id',exposure_row.id,
        'candidate_output_sha256',CASE WHEN p_feedback_family='rewrite_clarity'
            THEN candidate_output_sha256 ELSE NULL END,
        'candidate_output_contract_version',CASE
            WHEN p_feedback_family='rewrite_clarity'
            THEN 'feedback-candidate-output-v1' ELSE NULL END,
        'feedback_family',p_feedback_family,'value',p_value);
END;
$$;

-- The historical key-based signature cannot prove which regenerated artifact
-- was clicked. Preserve its name for clear failure, but make it incapable of
-- creating any new decision.
CREATE OR REPLACE FUNCTION public.record_feedback_human_decision_v1(
    p_project_id UUID,
    p_take_id UUID,
    p_rater_id UUID,
    p_feedback_id TEXT,
    p_feedback_family TEXT,
    p_value TEXT,
    p_taxonomy_version TEXT,
    p_idempotency_key TEXT
) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
BEGIN
    RAISE EXCEPTION 'FEEDBACK_EXACT_IDENTITY_REQUIRED';
END;
$$;

REVOKE ALL ON public.correction_decisions
    FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT ON public.correction_decisions TO service_role;
REVOKE ALL ON FUNCTION public.feedback_candidate_output_sha256_v1(UUID)
    FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.record_feedback_human_decision_v1(
    UUID,UUID,UUID,TEXT,TEXT,TEXT,TEXT,TEXT)
    FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.record_feedback_human_decision_v1(
    UUID,UUID,UUID,UUID,UUID,UUID,TEXT,TEXT,TEXT,TEXT)
    FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.record_feedback_human_decision_v1(
    UUID,UUID,UUID,UUID,UUID,UUID,TEXT,TEXT,TEXT,TEXT)
    TO service_role;

CREATE OR REPLACE FUNCTION public.root_phrase_normalize_transcript_v1(p_text TEXT)
RETURNS TEXT LANGUAGE sql IMMUTABLE SET search_path = public AS $$
    SELECT lower(regexp_replace(btrim(COALESCE(p_text, '')), '[[:space:]]+', ' ', 'g'))
$$;

-- Lock, orange-root and maturity metadata do not change Ideal Text content.
-- Preserve the cold-open content snapshot while still invalidating on any
-- identity, order or wording mutation.
CREATE OR REPLACE FUNCTION public.advance_ideal_text_document_generation_v1()
RETURNS trigger LANGUAGE plpgsql SET search_path=public AS $$
DECLARE changed_arc TEXT;
BEGIN
  IF TG_TABLE_NAME='v2_sessions' THEN
    IF TG_OP='INSERT' THEN
      IF NEW.analysis_state IS DISTINCT FROM 'ready'
         OR COALESCE(NEW.recording_kind,'spoken')<>'spoken'
         OR NEW.paired_session_id IS NOT NULL
         OR NULLIF(trim(NEW.arc_id::text),'') IS NULL
      THEN RETURN NEW; END IF;
    ELSIF TG_OP='UPDATE' THEN
      IF NEW.analysis_state IS DISTINCT FROM 'ready'
         OR OLD.analysis_state IS NOT DISTINCT FROM 'ready'
         OR COALESCE(NEW.recording_kind,'spoken')<>'spoken'
         OR NEW.paired_session_id IS NOT NULL
         OR NULLIF(trim(NEW.arc_id::text),'') IS NULL
      THEN RETURN NEW; END IF;
    ELSE RETURN OLD; END IF;
  END IF;
  IF TG_TABLE_NAME='user_arc_ideal_notes' THEN
    IF TG_OP='INSERT' AND NEW.user_text IS NULL THEN RETURN NEW; END IF;
    IF TG_OP='UPDATE'
       AND NEW.user_text IS NOT DISTINCT FROM OLD.user_text
       AND NEW.user_text_version IS NOT DISTINCT FROM OLD.user_text_version
    THEN RETURN NEW; END IF;
    IF TG_OP='DELETE' AND OLD.user_text IS NULL THEN RETURN OLD; END IF;
  END IF;
  IF TG_TABLE_NAME='ideal_text_part' AND TG_OP='UPDATE'
     AND NEW.id IS NOT DISTINCT FROM OLD.id
     AND NEW.arc_id IS NOT DISTINCT FROM OLD.arc_id
     AND NEW.user_id IS NOT DISTINCT FROM OLD.user_id
     AND NEW.ord IS NOT DISTINCT FROM OLD.ord
     AND NEW.text IS NOT DISTINCT FROM OLD.text
  THEN RETURN NEW; END IF;
  changed_arc:=CASE WHEN TG_OP='DELETE' THEN OLD.arc_id ELSE NEW.arc_id END;
  INSERT INTO public.ideal_text_document_generations(
    arc_id,generation,updated_at)
  VALUES(changed_arc,1,clock_timestamp())
  ON CONFLICT (arc_id) DO UPDATE
    SET generation=ideal_text_document_generations.generation+1,
        updated_at=clock_timestamp();
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS ideal_text_part_advances_document_generation
  ON public.ideal_text_part;
CREATE TRIGGER ideal_text_part_advances_document_generation
AFTER INSERT OR UPDATE OR DELETE ON public.ideal_text_part
FOR EACH ROW EXECUTE FUNCTION public.advance_ideal_text_document_generation_v1();

-- Reused by creation, replay, qualification and activation.  An immutable
-- ledger row is evidence, not continuing authority: current source/deletion
-- state is checked again at every service boundary.
CREATE OR REPLACE FUNCTION public.require_synthetic_root_content_live_v1(
    p_content_version_id UUID
) RETURNS public.root_phrase_content_versions
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE content public.root_phrase_content_versions;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'ROOT_CONTENT_REQUIRES_READ_COMMITTED';
    END IF;
    SELECT * INTO STRICT content FROM public.root_phrase_content_versions
     WHERE id = p_content_version_id;
    PERFORM public.require_exercise_assignment_authority_v1(
        content.authorization_check_id, content.acquisition_principal_id);
    IF NOT EXISTS (
        SELECT 1
          FROM public.feedback_v3_memberships membership
          JOIN public.feedback_v3_membership_items item
            ON item.membership_id = membership.id
           AND item.candidate_id = content.feedback_candidate_id
          JOIN public.feedback_candidates candidate
            ON candidate.id = item.candidate_id
           AND candidate.evidence_span_id = item.evidence_span_id
          JOIN public.evidence_spans evidence
            ON evidence.id = item.evidence_span_id
          JOIN public.v2_sessions take_row
            ON take_row.id = membership.take_id
          JOIN public.snippets snippet
            ON snippet.id = item.snippet_id
           AND snippet.session_id = take_row.id
           AND snippet.recording_id = take_row.recording_1_id
           AND snippet.recording_id = evidence.recording_id
           AND snippet.start_offset_ms = evidence.start_ms
           AND snippet.duration_ms = evidence.end_ms - evidence.start_ms
          JOIN public.processing_recording_attempts attempt
            ON attempt.id = take_row.id
           AND attempt.recording_id = take_row.recording_1_id
           AND attempt.project_id = membership.project_id
           AND attempt.acquisition_principal_id = membership.acquisition_principal_id
           AND attempt.status NOT IN ('cancelled', 'purged')
          JOIN public.processing_audio_objects object_row
            ON object_row.recording_attempt_id = attempt.id
           AND object_row.acquisition_principal_id = membership.acquisition_principal_id
           AND object_row.deleted_at IS NULL
          JOIN public.ideal_text_document_heads document_head
            ON document_head.snapshot_id = content.document_snapshot_id
         WHERE membership.id = content.feedback_membership_id
           AND membership.project_id = content.project_id
           AND membership.acquisition_principal_id = content.acquisition_principal_id
           AND membership.document_snapshot_id = content.document_snapshot_id
           AND item.selected AND item.eligibility = 'eligible'
           AND item.source_ideal_part_id = content.source_ideal_part_id
           AND item.slide_index = content.slide_index
           AND item.block_key = content.block_key
           AND evidence.take_id = take_row.id
           AND evidence.project_id = membership.project_id
           AND evidence.owner_principal_id = membership.acquisition_principal_id
           AND evidence.start_ms >= 0 AND evidence.end_ms > evidence.start_ms
           AND NULLIF(candidate.generated_output->>'quote', '') IS NOT NULL
           AND NULLIF(evidence.exact_text, '') IS NOT NULL
           AND candidate.generated_output->>'quote' = evidence.exact_text
           AND (candidate.feedback_family <> 'rewrite_clarity'
                OR (NULLIF(candidate.generated_output->>'proposed_text', '') IS NOT NULL
                    AND NULLIF(evidence.replacement_text, '') IS NOT NULL
                    AND candidate.generated_output->>'proposed_text' =
                        evidence.replacement_text))
           AND (
               (content.text_origin = 'unchanged_manager'
                AND content.phrase_text = candidate.generated_output->>'quote'
                AND content.phrase_text = evidence.exact_text
                AND (evidence.start_char IS NULL
                     OR evidence.start_char = content.phrase_start)
                AND (evidence.end_char IS NULL
                     OR evidence.end_char = content.phrase_end))
               OR
               (content.text_origin = 'accepted_rewrite'
                AND content.phrase_text = candidate.generated_output->>'proposed_text'
                AND content.phrase_text = evidence.replacement_text
                AND EXISTS (
                    SELECT 1 FROM public.correction_decisions decision
                     WHERE decision.id = content.source_correction_decision_id
                       AND decision.evidence_span_id = evidence.id
                       AND decision.rater_id = document_head.actor_id::UUID
                       AND decision.value = 'accept_proposed'
                       AND decision.candidate_id = candidate.id
                       AND decision.feedback_membership_id = membership.id
                       AND decision.feedback_exposure_id IS NOT NULL
                       AND decision.candidate_output_contract_version =
                           'feedback-candidate-output-v1'
                       AND decision.candidate_output_sha256 =
                           public.feedback_candidate_output_sha256_v1(candidate.id)
                       AND NOT EXISTS (
                           SELECT 1
                             FROM public.correction_decisions later_decision
                            WHERE later_decision.supersedes_id = decision.id)))
               OR
               (content.text_origin = 'manual_edit'
                AND content.phrase_start = 0
                AND content.phrase_end = length(content.paragraph_text)
                AND content.phrase_text = content.paragraph_text)
           )
           AND (content.text_origin = 'unchanged_manager' OR EXISTS (
               SELECT 1 FROM public.ideal_text_part_revision revision
                WHERE revision.id = content.source_part_revision_id
                  AND revision.arc_id = document_head.arc_id
                  AND revision.user_id = document_head.actor_id
                  AND revision.part_id = content.source_ideal_part_id
                  AND revision.text = content.paragraph_text
                  AND revision.action = 'user_edit'
                  AND (content.text_origin <> 'accepted_rewrite'
                       OR revision.take_session_id = membership.take_id)
           ))
    ) OR EXISTS (
        SELECT 1 FROM public.data_purge_requests purge
         WHERE purge.acquisition_principal_id = content.acquisition_principal_id
           AND purge.state <> 'done'
    ) THEN
        RAISE EXCEPTION 'ROOT_CONTENT_SOURCE_NOT_LIVE';
    END IF;
    RETURN content;
END;
$$;

DROP FUNCTION IF EXISTS public.register_synthetic_root_content_version_v1(
    UUID,UUID,UUID,TEXT,INTEGER,INTEGER,TEXT,TEXT
);
CREATE OR REPLACE FUNCTION public.register_synthetic_root_content_version_v1(
    p_feedback_membership_id UUID,
    p_feedback_candidate_id UUID,
    p_source_ideal_part_id UUID,
    p_authorization_check_id UUID,
    p_phrase_text TEXT,
    p_phrase_start INTEGER,
    p_phrase_end INTEGER,
    p_text_origin TEXT,
    p_idempotency_key TEXT
) RETURNS public.root_phrase_content_versions
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE membership public.feedback_v3_memberships;
    feedback_item public.feedback_v3_membership_items;
    candidate public.feedback_candidates;
    evidence public.evidence_spans;
    snapshot public.ideal_text_document_snapshots;
    part JSONB; piece JSONB; paragraph_text TEXT; version_hash TEXT;
    part_revision public.ideal_text_part_revision;
    correction public.correction_decisions;
    owner_user_id UUID;
    expected_phrase TEXT;
    part_version_kind TEXT;
    existing public.root_phrase_content_versions;
BEGIN
    SELECT * INTO STRICT membership FROM public.feedback_v3_memberships
     WHERE id = p_feedback_membership_id;
    SELECT * INTO STRICT feedback_item FROM public.feedback_v3_membership_items
     WHERE membership_id = membership.id AND candidate_id = p_feedback_candidate_id
       AND source_ideal_part_id = p_source_ideal_part_id AND selected;
    SELECT * INTO STRICT candidate FROM public.feedback_candidates
     WHERE id = feedback_item.candidate_id
       AND evidence_span_id = feedback_item.evidence_span_id;
    SELECT * INTO STRICT evidence FROM public.evidence_spans
     WHERE id = feedback_item.evidence_span_id
       AND owner_principal_id = membership.acquisition_principal_id
       AND project_id = membership.project_id
       AND take_id = membership.take_id;
    IF NULLIF(candidate.generated_output->>'quote', '') IS NULL
       OR NULLIF(evidence.exact_text, '') IS NULL
       OR candidate.generated_output->>'quote' IS DISTINCT FROM evidence.exact_text
       OR (candidate.feedback_family = 'rewrite_clarity'
           AND (NULLIF(candidate.generated_output->>'proposed_text', '') IS NULL
                OR NULLIF(evidence.replacement_text, '') IS NULL
                OR candidate.generated_output->>'proposed_text'
                   IS DISTINCT FROM evidence.replacement_text))
    THEN RAISE EXCEPTION 'ROOT_MANAGER_EVIDENCE_MISMATCH'; END IF;
    SELECT * INTO STRICT snapshot FROM public.ideal_text_document_snapshots
     WHERE id = membership.document_snapshot_id;
    SELECT user_id INTO STRICT owner_user_id FROM public.owner_principals
     WHERE id = membership.acquisition_principal_id;
    PERFORM public.require_exercise_assignment_authority_v1(
        p_authorization_check_id, membership.acquisition_principal_id);
    SELECT value INTO part FROM jsonb_array_elements(snapshot.payload->'parts') value
     WHERE value->>'id' = p_source_ideal_part_id::TEXT LIMIT 1;
    SELECT value INTO piece FROM jsonb_array_elements(snapshot.payload->'pieces') value
     WHERE value->>'part_id' = p_source_ideal_part_id::TEXT LIMIT 1;
    paragraph_text := part->>'text';
    SELECT * INTO part_revision FROM public.ideal_text_part_revision revision
     WHERE revision.arc_id = snapshot.arc_id
       AND revision.user_id = snapshot.actor_id
       AND revision.part_id = p_source_ideal_part_id
       AND revision.text = paragraph_text
       AND revision.created_at <= snapshot.created_at
       AND (p_text_origin = 'unchanged_manager'
            OR (revision.action = 'user_edit'
                AND (p_text_origin <> 'accepted_rewrite'
                     OR revision.take_session_id = membership.take_id)))
     ORDER BY revision.created_at DESC, revision.id DESC LIMIT 1;
    part_version_kind := CASE WHEN part_revision.id IS NULL
        THEN 'canonical_snapshot_baseline_v1'
        ELSE 'existing_part_revision_v1' END;
    IF p_text_origin = 'accepted_rewrite' THEN
        expected_phrase := candidate.generated_output->>'proposed_text';
        -- Share the canonical decision writer's lock.  This freezes the
        -- current decision leaf and its exact candidate/output association.
        PERFORM pg_advisory_xact_lock(hashtextextended(
            'canonical-correction:' || evidence.id::TEXT || ':' ||
            owner_user_id::TEXT, 0));
        SELECT decision.* INTO correction
          FROM public.correction_decisions decision
         WHERE decision.evidence_span_id = evidence.id
           AND decision.rater_id = owner_user_id
           AND decision.value = 'accept_proposed'
           AND decision.candidate_id = candidate.id
           AND decision.feedback_membership_id = membership.id
           AND decision.feedback_exposure_id IS NOT NULL
           AND decision.candidate_output_contract_version =
               'feedback-candidate-output-v1'
           AND decision.candidate_output_sha256 =
               public.feedback_candidate_output_sha256_v1(candidate.id)
           AND decision.created_at >= membership.frozen_at
           AND NOT EXISTS (
               SELECT 1
                 FROM public.correction_decisions later_decision
                WHERE later_decision.supersedes_id = decision.id)
         ORDER BY decision.created_at DESC, decision.id DESC LIMIT 1;
    ELSIF p_text_origin = 'unchanged_manager' THEN
        expected_phrase := candidate.generated_output->>'quote';
    ELSE
        expected_phrase := paragraph_text;
    END IF;
    IF part IS NULL OR piece IS NULL OR p_text_origin NOT IN (
        'unchanged_manager', 'accepted_rewrite', 'manual_edit')
       OR p_phrase_start < 0 OR p_phrase_end <= p_phrase_start
       OR p_phrase_end > length(paragraph_text)
       OR substring(paragraph_text FROM p_phrase_start + 1
                    FOR p_phrase_end - p_phrase_start) IS DISTINCT FROM p_phrase_text
       OR feedback_item.slide_index <> (piece->>'slide_index')::INTEGER
       OR NULLIF(expected_phrase, '') IS NULL
       OR p_phrase_text IS DISTINCT FROM expected_phrase
       OR (p_text_origin = 'manual_edit'
           AND (p_phrase_start <> 0 OR p_phrase_end <> length(paragraph_text)))
       OR (p_text_origin IN ('accepted_rewrite', 'manual_edit')
           AND (part_revision.id IS NULL OR part_revision.action <> 'user_edit'))
       OR (p_text_origin = 'accepted_rewrite' AND correction.id IS NULL)
       OR (evidence.start_char IS NOT NULL
           AND p_text_origin = 'unchanged_manager'
           AND evidence.start_char <> p_phrase_start)
       OR (evidence.end_char IS NOT NULL
           AND p_text_origin = 'unchanged_manager'
           AND evidence.end_char <> p_phrase_end)
    THEN RAISE EXCEPTION 'ROOT_CONTENT_VERSION_INVALID'; END IF;
    IF NOT EXISTS (SELECT 1 FROM public.ideal_text_document_heads head
                    WHERE head.snapshot_id = snapshot.id)
    THEN RAISE EXCEPTION 'ROOT_CONTENT_VERSION_STALE'; END IF;
    version_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'acquisition_principal_id', membership.acquisition_principal_id,
        'project_id', membership.project_id, 'feedback_membership_id', membership.id,
        'feedback_candidate_id', feedback_item.candidate_id,
        'feedback_candidate_output_sha256',
            public.feedback_candidate_output_sha256_v1(candidate.id),
        'feedback_candidate_output_contract_version',
            'feedback-candidate-output-v1',
        'source_feedback_exposure_id', correction.feedback_exposure_id,
        'authorization_check_id', p_authorization_check_id,
        'document_snapshot_id', snapshot.id,
        'document_snapshot_sha256', snapshot.payload_sha256,
        'source_ideal_part_id', p_source_ideal_part_id,
        'source_part_revision_id', part_revision.id,
        'source_correction_decision_id', correction.id,
        'source_part_version_kind', part_version_kind,
        'slide_index', feedback_item.slide_index, 'block_key', feedback_item.block_key,
        'paragraph_text', paragraph_text, 'phrase_text', p_phrase_text,
        'phrase_start', p_phrase_start, 'phrase_end', p_phrase_end,
        'text_origin', p_text_origin,
        'transcript_normalization_version', 'root-transcript-normalization-v1',
        'content_version_kind', 'canonical_snapshot_part_v1'));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'root-content-version:' || p_idempotency_key, 0));
    PERFORM public.require_exercise_assignment_authority_v1(
        p_authorization_check_id, membership.acquisition_principal_id);
    IF NOT EXISTS (SELECT 1 FROM public.ideal_text_document_heads head
                    WHERE head.snapshot_id = snapshot.id)
    THEN RAISE EXCEPTION 'ROOT_CONTENT_VERSION_STALE'; END IF;
    SELECT * INTO existing FROM public.root_phrase_content_versions
     WHERE idempotency_key = p_idempotency_key;
    IF existing.id IS NOT NULL THEN
        IF existing.content_version_sha256 <> version_hash THEN
            RAISE EXCEPTION 'ROOT_CONTENT_VERSION_REPLAY_CONFLICT'; END IF;
        PERFORM public.require_synthetic_root_content_live_v1(existing.id);
        RETURN existing;
    END IF;
    INSERT INTO public.root_phrase_content_versions (
        acquisition_principal_id, project_id, feedback_membership_id,
        feedback_candidate_id, authorization_check_id, document_snapshot_id,
        source_ideal_part_id, source_part_revision_id,
        source_correction_decision_id, source_part_version_kind,
        slide_index, block_key, paragraph_text, paragraph_text_sha256,
        phrase_text, phrase_start, phrase_end, transcript_normalization_version,
        text_origin,
        content_version_kind, content_version_sha256, idempotency_key
    ) VALUES (
        membership.acquisition_principal_id, membership.project_id, membership.id,
        feedback_item.candidate_id, p_authorization_check_id, snapshot.id,
        p_source_ideal_part_id, part_revision.id, correction.id, part_version_kind,
        feedback_item.slide_index, feedback_item.block_key, paragraph_text,
        public.exercise_json_sha256_v1(to_jsonb(paragraph_text)), p_phrase_text,
        p_phrase_start, p_phrase_end, 'root-transcript-normalization-v1', p_text_origin,
        'canonical_snapshot_part_v1', version_hash, p_idempotency_key
    ) RETURNING * INTO existing;
    PERFORM public.require_synthetic_root_content_live_v1(existing.id);
    RETURN existing;
END;
$$;

CREATE OR REPLACE FUNCTION public.freeze_synthetic_root_semantic_input_v1(
    p_content_version_id UUID,
    p_idempotency_key TEXT
) RETURNS public.root_phrase_semantic_input_snapshots
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE content public.root_phrase_content_versions;
    project_row public.projects;
    snapshot public.ideal_text_document_snapshots;
    goal_snapshot JSONB; slide_snapshot JSONB;
    goal_hash TEXT; slide_hash TEXT; snapshot_hash TEXT;
    existing public.root_phrase_semantic_input_snapshots;
BEGIN
    SELECT * INTO content FROM public.require_synthetic_root_content_live_v1(
        p_content_version_id);
    SELECT * INTO STRICT project_row FROM public.projects
     WHERE id = content.project_id
       AND owner_principal_id = content.acquisition_principal_id
     FOR SHARE;
    SELECT * INTO STRICT snapshot FROM public.ideal_text_document_snapshots
     WHERE id = content.document_snapshot_id
       AND project_id = project_row.id
       AND acquisition_principal_id = content.acquisition_principal_id;
    goal_snapshot := jsonb_build_object(
        'project_id', project_row.id,
        'project_setup', COALESCE(project_row.setup, '{}'::jsonb));
    SELECT jsonb_build_object(
        'document_snapshot_id', snapshot.id,
        'document_snapshot_sha256', snapshot.payload_sha256,
        'slide_index', content.slide_index,
        'slide_title', snapshot.payload->'slide_titles'->content.slide_index,
        'paragraphs', COALESCE(jsonb_agg(jsonb_build_object(
            'id', part->>'id', 'text', part->>'text') ORDER BY ordinal)
            FILTER (WHERE part IS NOT NULL), '[]'::jsonb))
      INTO slide_snapshot
      FROM jsonb_array_elements(snapshot.payload->'parts')
           WITH ORDINALITY AS p(part, ordinal)
      JOIN LATERAL (
          SELECT value
            FROM jsonb_array_elements(snapshot.payload->'pieces') value
           WHERE value->>'part_id' = part->>'id'
             AND (value->>'slide_index')::INTEGER = content.slide_index
           LIMIT 1
      ) piece ON true;
    goal_hash := public.exercise_json_sha256_v1(goal_snapshot);
    slide_hash := public.exercise_json_sha256_v1(slide_snapshot);
    snapshot_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'content_version_id', content.id,
        'content_version_sha256', content.content_version_sha256,
        'project_goal_sha256', goal_hash,
        'slide_context_sha256', slide_hash,
        'snapshot_schema_version', 'root-semantic-input-v1'));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'root-semantic-input:' || p_idempotency_key, 0));
    PERFORM public.require_synthetic_root_content_live_v1(content.id);
    SELECT * INTO existing FROM public.root_phrase_semantic_input_snapshots
     WHERE idempotency_key = p_idempotency_key;
    IF existing.id IS NOT NULL THEN
        IF existing.content_version_id <> content.id
           OR existing.input_snapshot_sha256 <> snapshot_hash
        THEN RAISE EXCEPTION 'ROOT_SEMANTIC_INPUT_REPLAY_CONFLICT'; END IF;
        RETURN existing;
    END IF;
    INSERT INTO public.root_phrase_semantic_input_snapshots (
        content_version_id, acquisition_principal_id, project_id,
        document_snapshot_id, project_goal_snapshot, slide_context_snapshot,
        project_goal_sha256, slide_context_sha256, input_snapshot_sha256,
        snapshot_schema_version, idempotency_key
    ) VALUES (
        content.id, content.acquisition_principal_id, content.project_id,
        content.document_snapshot_id, goal_snapshot, slide_snapshot,
        goal_hash, slide_hash, snapshot_hash, 'root-semantic-input-v1',
        p_idempotency_key
    ) RETURNING * INTO existing;
    RETURN existing;
END;
$$;

DROP FUNCTION IF EXISTS public.record_synthetic_root_semantic_result_v1(
    UUID,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
);
CREATE OR REPLACE FUNCTION public.record_synthetic_root_semantic_result_v1(
    p_content_version_id UUID,
    p_semantic_input_snapshot_id UUID,
    p_result TEXT,
    p_reason_code TEXT,
    p_prompt_version TEXT,
    p_model_version TEXT,
    p_code_version TEXT,
    p_idempotency_key TEXT
) RETURNS public.root_phrase_semantic_results
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE content public.root_phrase_content_versions;
    semantic_input public.root_phrase_semantic_input_snapshots;
    result_hash TEXT; input_hash TEXT; existing public.root_phrase_semantic_results;
BEGIN
    SELECT * INTO content FROM public.require_synthetic_root_content_live_v1(
        p_content_version_id);
    SELECT * INTO STRICT semantic_input
      FROM public.root_phrase_semantic_input_snapshots
     WHERE id = p_semantic_input_snapshot_id
       AND content_version_id = content.id
       AND acquisition_principal_id = content.acquisition_principal_id
       AND project_id = content.project_id
       AND document_snapshot_id = content.document_snapshot_id;
    IF p_result NOT IN ('aligned','uncertain','not_aligned','unavailable')
       OR COALESCE(btrim(p_reason_code), '') = ''
       OR COALESCE(btrim(p_prompt_version), '') = ''
       OR COALESCE(btrim(p_model_version), '') = ''
       OR COALESCE(btrim(p_code_version), '') = ''
    THEN RAISE EXCEPTION 'ROOT_SEMANTIC_RESULT_INVALID'; END IF;
    input_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'content_version_sha256', content.content_version_sha256,
        'semantic_input_snapshot_sha256', semantic_input.input_snapshot_sha256));
    result_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'input_sha256', input_hash, 'result', p_result,
        'reason_code', p_reason_code, 'result_origin', 'machine_policy',
        'prompt_version', p_prompt_version,
        'policy_version', 'root-semantic-alignment-v1',
        'model_version', p_model_version, 'code_version', p_code_version));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'root-semantic:' || p_idempotency_key, 0));
    PERFORM public.require_synthetic_root_content_live_v1(content.id);
    SELECT * INTO existing FROM public.root_phrase_semantic_results
     WHERE idempotency_key = p_idempotency_key;
    IF existing.id IS NOT NULL THEN
        IF existing.content_version_id <> content.id
           OR existing.semantic_input_snapshot_id <> semantic_input.id
           OR existing.output_sha256 <> result_hash
        THEN RAISE EXCEPTION 'ROOT_SEMANTIC_RESULT_REPLAY_CONFLICT'; END IF;
        RETURN existing;
    END IF;
    INSERT INTO public.root_phrase_semantic_results (
        content_version_id, semantic_input_snapshot_id,
        acquisition_principal_id, result, reason_code,
        result_origin, project_goal_sha256, slide_context_sha256,
        prompt_version, policy_version, model_version, code_version,
        input_sha256, output_sha256, completed_at, idempotency_key
    ) VALUES (
        content.id, semantic_input.id, content.acquisition_principal_id,
        p_result, p_reason_code, 'machine_policy',
        semantic_input.project_goal_sha256, semantic_input.slide_context_sha256,
        p_prompt_version, 'root-semantic-alignment-v1', p_model_version,
        p_code_version, input_hash, result_hash, clock_timestamp(),
        p_idempotency_key
    ) RETURNING * INTO existing;
    RETURN existing;
END;
$$;

CREATE OR REPLACE FUNCTION public.record_synthetic_root_alignment_action_v1(
    p_content_version_id UUID,
    p_semantic_result_id UUID,
    p_owner_user_id UUID,
    p_action TEXT,
    p_idempotency_key TEXT
) RETURNS public.root_phrase_owner_alignment_actions
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE content public.root_phrase_content_versions;
    semantic public.root_phrase_semantic_results;
    existing public.root_phrase_owner_alignment_actions;
BEGIN
    SELECT * INTO content FROM public.require_synthetic_root_content_live_v1(
        p_content_version_id);
    SELECT * INTO STRICT semantic FROM public.root_phrase_semantic_results
     WHERE id = p_semantic_result_id AND content_version_id = content.id
       AND acquisition_principal_id = content.acquisition_principal_id;
    IF semantic.result <> 'uncertain'
       OR p_action NOT IN ('root_alignment_confirm','root_alignment_reject')
       OR NOT EXISTS (SELECT 1 FROM public.owner_principals owner
                       WHERE owner.id = content.acquisition_principal_id
                         AND owner.user_id = p_owner_user_id)
    THEN RAISE EXCEPTION 'ROOT_ALIGNMENT_ACTION_INVALID'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'root-alignment-action:' || p_idempotency_key, 0));
    PERFORM public.require_synthetic_root_content_live_v1(content.id);
    INSERT INTO public.root_phrase_owner_alignment_actions (
        content_version_id, semantic_result_id, acquisition_principal_id,
        owner_user_id, action, idempotency_key
    ) VALUES (content.id, semantic.id, content.acquisition_principal_id,
              p_owner_user_id, p_action, p_idempotency_key)
    ON CONFLICT (idempotency_key) DO NOTHING;
    SELECT * INTO STRICT existing FROM public.root_phrase_owner_alignment_actions
     WHERE idempotency_key = p_idempotency_key;
    IF existing.content_version_id <> content.id OR existing.semantic_result_id <> semantic.id
       OR existing.owner_user_id <> p_owner_user_id OR existing.action <> p_action
    THEN RAISE EXCEPTION 'ROOT_ALIGNMENT_ACTION_REPLAY_CONFLICT'; END IF;
    RETURN existing;
END;
$$;

CREATE OR REPLACE FUNCTION public.evaluate_synthetic_root_qualification_v1(
    p_content_version_id UUID,
    p_semantic_result_id UUID,
    p_owner_alignment_action_id UUID,
    p_confidence_response_id UUID,
    p_practice_selection_revision_id UUID,
    p_qualification_path TEXT,
    p_idempotency_key TEXT
) RETURNS public.root_phrase_qualification_revisions
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE content public.root_phrase_content_versions;
    semantic public.root_phrase_semantic_results;
    membership public.feedback_v3_memberships;
    feedback_item public.feedback_v3_membership_items;
    owner_action public.root_phrase_owner_alignment_actions;
    response public.feedback_v3_owner_responses;
    selection public.exercise_practice_selection_revisions;
    attempt public.exercise_practice_attempts;
    practice public.exercise_practice_sessions;
    offer public.exercise_service_offers;
    routing TEXT; evidence_hash TEXT;
    existing public.root_phrase_qualification_revisions;
BEGIN
    SELECT * INTO content FROM public.require_synthetic_root_content_live_v1(
        p_content_version_id);
    SELECT * INTO STRICT semantic FROM public.root_phrase_semantic_results
     WHERE id = p_semantic_result_id AND content_version_id = content.id;
    SELECT * INTO STRICT membership FROM public.feedback_v3_memberships
     WHERE id = content.feedback_membership_id;
    SELECT * INTO STRICT feedback_item FROM public.feedback_v3_membership_items
     WHERE membership_id = membership.id AND candidate_id = content.feedback_candidate_id;
    IF p_qualification_path NOT IN (
        'unchanged_confident_voice','accepted_rewrite','manual_edit','strong_formulation')
    THEN RAISE EXCEPTION 'ROOT_QUALIFICATION_PATH_INVALID'; END IF;
    IF (p_qualification_path IN ('unchanged_confident_voice','strong_formulation')
            AND (content.text_origin <> 'unchanged_manager'
                 OR p_practice_selection_revision_id IS NOT NULL))
       OR (p_qualification_path = 'accepted_rewrite'
            AND content.text_origin <> 'accepted_rewrite')
       OR (p_qualification_path = 'manual_edit'
            AND content.text_origin <> 'manual_edit')
    THEN RAISE EXCEPTION 'ROOT_QUALIFICATION_ORIGIN_INVALID'; END IF;
    IF NOT EXISTS (SELECT 1 FROM public.ideal_text_document_heads head
                    WHERE head.snapshot_id = content.document_snapshot_id) THEN
        routing := 'stale_text_revision';
    ELSIF EXISTS (SELECT 1 FROM public.root_phrase_block_heads head
        WHERE head.project_id = content.project_id AND head.slide_index = content.slide_index
          AND head.block_key = content.block_key AND head.active_root_action_id IS NOT NULL) THEN
        routing := 'blocked_existing_block_root';
    ELSIF semantic.result = 'not_aligned' THEN routing := 'blocked_semantic_mismatch';
    ELSIF semantic.result = 'unavailable' THEN routing := 'blocked_semantic_unavailable';
    ELSIF semantic.result = 'uncertain' THEN
        SELECT * INTO owner_action FROM public.root_phrase_owner_alignment_actions
         WHERE id = p_owner_alignment_action_id AND content_version_id = content.id
           AND semantic_result_id = semantic.id;
        IF owner_action.action IS DISTINCT FROM 'root_alignment_confirm' THEN
            routing := 'pending_owner_alignment_confirmation';
        END IF;
    END IF;
    IF routing IS NULL AND p_qualification_path IN (
        'unchanged_confident_voice','strong_formulation') THEN
        SELECT * INTO response FROM public.feedback_v3_owner_responses
         WHERE id = p_confidence_response_id AND membership_id = membership.id
           AND candidate_id = feedback_item.candidate_id;
        IF feedback_item.feedback_family <> 'confident_voice'
           OR response.response IS DISTINCT FROM 'confident_yes' THEN
            routing := 'blocked_confidence_response';
        ELSE routing := 'eligible_direct'; END IF;
    ELSIF routing IS NULL THEN
        IF p_practice_selection_revision_id IS NULL THEN routing := 'pending_recording';
        ELSE
            SELECT * INTO selection FROM public.exercise_practice_selection_revisions
             WHERE id = p_practice_selection_revision_id
               AND acquisition_principal_id = content.acquisition_principal_id;
            SELECT * INTO attempt FROM public.exercise_practice_attempts
             WHERE id = selection.selected_attempt_id
               AND acquisition_principal_id = content.acquisition_principal_id
               AND public.root_phrase_normalize_transcript_v1(exact_passage) =
                   public.root_phrase_normalize_transcript_v1(content.phrase_text)
               AND public.root_phrase_normalize_transcript_v1(transcript_text) =
                   public.root_phrase_normalize_transcript_v1(content.phrase_text);
            SELECT * INTO practice FROM public.exercise_practice_sessions
             WHERE id = selection.session_id
               AND acquisition_principal_id = content.acquisition_principal_id;
            SELECT offer_row.* INTO offer
              FROM public.exercise_service_offers offer_row
             WHERE offer_row.id = practice.source_offer_id
               AND offer_row.acquisition_principal_id =
                   content.acquisition_principal_id
               AND offer_row.project_id = content.project_id
               AND offer_row.feedback_membership_id =
                   content.feedback_membership_id
               AND offer_row.source_take_id = membership.take_id
               AND offer_row.source_audio_lineage_id =
                   practice.source_audio_lineage_id
               AND EXISTS (
                   SELECT 1 FROM public.feedback_v3_membership_items offer_item
                    WHERE offer_item.membership_id=
                              offer_row.feedback_membership_id
                      AND offer_item.candidate_id=
                              offer_row.feedback_candidate_id
                      AND offer_item.feedback_family='confident_voice'
                      AND offer_item.selected
                      AND offer_item.slide_index=content.slide_index
                      AND offer_item.block_key=content.block_key);
            IF selection.selection_state <> 'selected_first_valid'
               OR selection.baseline_revision <> practice.baseline_revision
               OR attempt.id IS NULL OR attempt.session_id <> practice.id
               OR offer.id IS NULL
               OR practice.exact_passage_sha256 <>
                  public.exercise_json_sha256_v1(to_jsonb(practice.exact_passage))
               OR attempt.exact_audio_sha256 !~ '^[0-9a-f]{64}$'
               OR attempt.transcript_sha256 !~ '^[0-9a-f]{64}$'
            THEN routing := 'blocked_audio_or_transcript';
            ELSE
                PERFORM public.require_practice_source_live_v1(
                    practice.id, practice.acquisition_principal_id);
                IF NOT EXISTS (
                    SELECT 1 FROM public.processing_audio_objects object_row
                     WHERE object_row.id = attempt.processing_audio_object_id
                       AND object_row.acquisition_principal_id =
                           content.acquisition_principal_id
                       AND object_row.exact_bytes_sha256 = attempt.exact_audio_sha256
                       AND object_row.deleted_at IS NULL
                ) THEN routing := 'blocked_audio_or_transcript';
                ELSE routing := 'eligible_after_rerecord'; END IF;
            END IF;
        END IF;
    END IF;
    evidence_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'content_version_id', content.id,
        'content_version_sha256', content.content_version_sha256,
        'semantic_result_id', semantic.id, 'semantic_output_sha256', semantic.output_sha256,
        'owner_alignment_action_id', owner_action.id,
        'confidence_response_id', response.id,
        'practice_session_id', practice.id,
        'source_offer_id', offer.id,
        'practice_selection_revision_id', selection.id,
        'practice_attempt_id', attempt.id,
        'transcript_normalization_version', content.transcript_normalization_version,
        'qualification_path', p_qualification_path, 'routing_state', routing,
        'qualification_policy_version', 'rooting-phrase-qualification-v1'));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'root-qualification:' || p_idempotency_key, 0));
    PERFORM public.require_synthetic_root_content_live_v1(content.id);
    IF practice.id IS NOT NULL THEN
        PERFORM public.require_practice_source_live_v1(
            practice.id, practice.acquisition_principal_id);
        IF NOT EXISTS (
            SELECT 1 FROM public.processing_audio_objects object_row
             WHERE object_row.id = attempt.processing_audio_object_id
               AND object_row.acquisition_principal_id =
                   content.acquisition_principal_id
               AND object_row.exact_bytes_sha256 = attempt.exact_audio_sha256
               AND object_row.deleted_at IS NULL
        ) THEN RAISE EXCEPTION 'ROOT_PRACTICE_AUDIO_NOT_LIVE'; END IF;
    END IF;
    SELECT * INTO existing FROM public.root_phrase_qualification_revisions
     WHERE idempotency_key = p_idempotency_key;
    IF existing.id IS NOT NULL THEN
        IF existing.evidence_sha256 <> evidence_hash THEN
            RAISE EXCEPTION 'ROOT_QUALIFICATION_REPLAY_CONFLICT'; END IF;
        RETURN existing;
    END IF;
    INSERT INTO public.root_phrase_qualification_revisions (
        acquisition_principal_id, content_version_id, semantic_result_id,
        owner_alignment_action_id, confidence_response_id,
        practice_selection_revision_id, practice_attempt_id,
        qualification_path, routing_state, evidence_sha256,
        qualification_policy_version, idempotency_key
    ) VALUES (
        content.acquisition_principal_id, content.id, semantic.id,
        owner_action.id, response.id, selection.id, attempt.id,
        p_qualification_path, routing, evidence_hash,
        'rooting-phrase-qualification-v1', p_idempotency_key
    ) RETURNING * INTO existing;
    RETURN existing;
END;
$$;

CREATE OR REPLACE FUNCTION public.activate_synthetic_root_phrase_v1(
    p_qualification_revision_id UUID,
    p_owner_user_id UUID,
    p_lock_and_root BOOLEAN,
    p_replace_existing BOOLEAN,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE qualification public.root_phrase_qualification_revisions;
    content public.root_phrase_content_versions;
    membership public.feedback_v3_memberships;
    snapshot public.ideal_text_document_snapshots;
    canonical_part public.ideal_text_part;
    practice public.exercise_practice_sessions;
    selection public.exercise_practice_selection_revisions;
    head public.root_phrase_block_heads;
    lock_action public.root_phrase_product_actions;
    root_action public.root_phrase_product_actions;
    action_hash TEXT; revision BIGINT;
BEGIN
    SELECT * INTO STRICT qualification FROM public.root_phrase_qualification_revisions
     WHERE id = p_qualification_revision_id
       AND routing_state IN ('eligible_direct','eligible_after_rerecord');
    SELECT * INTO content FROM public.require_synthetic_root_content_live_v1(
        qualification.content_version_id);
    SELECT * INTO STRICT membership FROM public.feedback_v3_memberships
     WHERE id = content.feedback_membership_id;
    SELECT * INTO STRICT snapshot FROM public.ideal_text_document_snapshots
     WHERE id = content.document_snapshot_id;
    IF NOT EXISTS (SELECT 1 FROM public.owner_principals owner
                    WHERE owner.id = content.acquisition_principal_id
                      AND owner.user_id = p_owner_user_id)
       OR NOT EXISTS (SELECT 1 FROM public.ideal_text_document_heads document_head
                       WHERE document_head.snapshot_id = content.document_snapshot_id)
    THEN RAISE EXCEPTION 'ROOT_ACTIVATION_NOT_CURRENT'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'root-activation:' || p_idempotency_key, 0));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'root-block:' || content.project_id::TEXT || ':' || content.slide_index::TEXT ||
        ':' || content.block_key::TEXT, 0));
    IF content.text_origin = 'accepted_rewrite' THEN
        PERFORM pg_advisory_xact_lock(hashtextextended(
            'canonical-correction:' || decision.evidence_span_id::TEXT || ':' ||
            decision.rater_id::TEXT, 0))
          FROM public.correction_decisions decision
         WHERE decision.id = content.source_correction_decision_id;
    END IF;
    SELECT * INTO content FROM public.require_synthetic_root_content_live_v1(content.id);
    IF qualification.routing_state = 'eligible_after_rerecord' THEN
        SELECT * INTO STRICT selection
          FROM public.exercise_practice_selection_revisions
         WHERE id = qualification.practice_selection_revision_id
           AND selected_attempt_id = qualification.practice_attempt_id
           AND acquisition_principal_id = content.acquisition_principal_id;
        SELECT * INTO practice FROM public.require_practice_source_live_v1(
            selection.session_id, content.acquisition_principal_id);
        IF NOT EXISTS (
            SELECT 1
              FROM public.exercise_practice_attempts attempt
              JOIN public.processing_audio_objects object_row
                ON object_row.id = attempt.processing_audio_object_id
               AND object_row.acquisition_principal_id =
                   qualification.acquisition_principal_id
               AND object_row.exact_bytes_sha256 = attempt.exact_audio_sha256
               AND object_row.deleted_at IS NULL
             WHERE attempt.id = qualification.practice_attempt_id
               AND attempt.session_id = practice.id
               AND selection.selection_state = 'selected_first_valid'
        ) THEN RAISE EXCEPTION 'ROOT_ACTIVATION_PRACTICE_NOT_LIVE'; END IF;
    END IF;
    SELECT * INTO canonical_part FROM public.ideal_text_part part_row
     WHERE part_row.id = content.source_ideal_part_id
       AND part_row.arc_id = snapshot.arc_id
       AND part_row.user_id = snapshot.actor_id
       AND part_row.text = content.paragraph_text
     FOR UPDATE;
    SELECT * INTO content FROM public.require_synthetic_root_content_live_v1(
        content.id);
    IF qualification.routing_state = 'eligible_after_rerecord' THEN
        SELECT * INTO practice FROM public.require_practice_source_live_v1(
            practice.id, content.acquisition_principal_id);
    END IF;
    IF canonical_part.id IS NULL THEN
        RAISE EXCEPTION 'ROOT_CANONICAL_PARAGRAPH_NOT_CURRENT';
    END IF;
    SELECT * INTO root_action FROM public.root_phrase_product_actions
     WHERE idempotency_key = p_idempotency_key || ':root';
    IF root_action.id IS NOT NULL THEN
        action_hash := public.exercise_json_sha256_v1(jsonb_build_object(
            'content_version_id', root_action.content_version_id,
            'qualification_revision_id', root_action.qualification_revision_id,
            'owner_user_id', root_action.owner_user_id,
            'action', root_action.action,
            'supersedes_action_id', root_action.supersedes_action_id,
            'lock_and_root', p_lock_and_root,
            'replace_existing', p_replace_existing));
        IF root_action.content_version_id <> content.id
           OR root_action.qualification_revision_id <> qualification.id
           OR root_action.owner_user_id <> p_owner_user_id
           OR root_action.action_sha256 <> action_hash
        THEN RAISE EXCEPTION 'ROOT_ACTIVATION_REPLAY_CONFLICT'; END IF;
        SELECT * INTO lock_action FROM public.root_phrase_product_actions
         WHERE idempotency_key = p_idempotency_key || ':lock';
        IF p_lock_and_root <> (lock_action.id IS NOT NULL) THEN
            RAISE EXCEPTION 'ROOT_ACTIVATION_REPLAY_CONFLICT'; END IF;
        IF canonical_part.locked_at IS NULL
           OR canonical_part.root_phrase IS DISTINCT FROM content.phrase_text
           OR canonical_part.root_start IS DISTINCT FROM content.phrase_start
           OR canonical_part.root_end IS DISTINCT FROM content.phrase_end
        THEN RAISE EXCEPTION 'ROOT_ACTIVATION_CANONICAL_STATE_CONFLICT'; END IF;
        IF qualification.routing_state = 'eligible_after_rerecord' THEN
            PERFORM public.require_practice_source_live_v1(
                practice.id, content.acquisition_principal_id);
        END IF;
        RETURN jsonb_build_object(
            'lock_action_id', lock_action.id, 'root_action_id', root_action.id,
            'interaction_state_revision', root_action.interaction_state_revision,
            'serves_user', false, 'dataset_eligible', false);
    END IF;
    SELECT * INTO head FROM public.root_phrase_block_heads
     WHERE project_id = content.project_id AND slide_index = content.slide_index
       AND block_key = content.block_key FOR UPDATE;
    IF head.active_root_action_id IS NOT NULL AND NOT p_replace_existing THEN
        RAISE EXCEPTION 'ROOT_BLOCK_ALREADY_ACTIVE'; END IF;
    IF p_lock_and_root THEN
        IF canonical_part.locked_at IS NULL THEN
            UPDATE public.ideal_text_part
               SET locked_at = clock_timestamp(),
                   iteration = iteration + 1,
                   updated_at = clock_timestamp()
             WHERE id = canonical_part.id
               AND arc_id = snapshot.arc_id
               AND user_id = snapshot.actor_id
               AND text = content.paragraph_text;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'ROOT_CANONICAL_LOCK_FAILED';
            END IF;
            INSERT INTO public.ideal_text_part_revision (
                arc_id, user_id, part_id, action, text,
                take_session_id, review_version
            ) VALUES (
                snapshot.arc_id, snapshot.actor_id, canonical_part.id,
                'lock', canonical_part.text, membership.take_id,
                membership.take_index
            );
        END IF;
        action_hash := public.exercise_json_sha256_v1(jsonb_build_object(
            'content_version_id', content.id, 'owner_user_id', p_owner_user_id,
            'action', 'paragraph_lock'));
        INSERT INTO public.root_phrase_product_actions (
            acquisition_principal_id, project_id, content_version_id,
            qualification_revision_id, owner_user_id, action,
            action_sha256, idempotency_key
        ) VALUES (content.acquisition_principal_id, content.project_id, content.id,
            NULL, p_owner_user_id, 'paragraph_lock', action_hash,
            p_idempotency_key || ':lock')
        ON CONFLICT (idempotency_key) DO NOTHING
        RETURNING * INTO lock_action;
        IF lock_action.id IS NULL THEN SELECT * INTO STRICT lock_action
            FROM public.root_phrase_product_actions
            WHERE idempotency_key = p_idempotency_key || ':lock'; END IF;
    ELSIF canonical_part.locked_at IS NULL THEN
        RAISE EXCEPTION 'ROOT_ACTIVATION_REQUIRES_LOCK';
    END IF;
    IF qualification.routing_state = 'eligible_after_rerecord' THEN
        PERFORM public.require_practice_source_live_v1(
            practice.id, content.acquisition_principal_id);
    END IF;
    revision := COALESCE(head.interaction_state_revision, 0) + 1;
    action_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'content_version_id', content.id,
        'qualification_revision_id', qualification.id,
        'owner_user_id', p_owner_user_id,
        'action', CASE WHEN head.active_root_action_id IS NULL
                       THEN 'root_activate' ELSE 'root_replace' END,
        'supersedes_action_id', head.active_root_action_id,
        'lock_and_root', p_lock_and_root,
        'replace_existing', p_replace_existing));
    INSERT INTO public.root_phrase_product_actions (
        acquisition_principal_id, project_id, content_version_id,
        qualification_revision_id, owner_user_id, action,
        supersedes_action_id, interaction_state_revision, action_sha256,
        idempotency_key
    ) VALUES (content.acquisition_principal_id, content.project_id, content.id,
        qualification.id, p_owner_user_id,
        CASE WHEN head.active_root_action_id IS NULL
             THEN 'root_activate' ELSE 'root_replace' END,
        head.active_root_action_id, revision, action_hash,
        p_idempotency_key || ':root')
    RETURNING * INTO root_action;
    INSERT INTO public.root_phrase_block_heads (
        acquisition_principal_id, project_id, slide_index, block_key,
        active_root_action_id, interaction_state_revision
    ) VALUES (content.acquisition_principal_id, content.project_id,
              content.slide_index, content.block_key, root_action.id, revision)
    ON CONFLICT (project_id, slide_index, block_key) DO UPDATE
        SET active_root_action_id = EXCLUDED.active_root_action_id,
            interaction_state_revision = EXCLUDED.interaction_state_revision,
            updated_at = clock_timestamp();
    UPDATE public.ideal_text_part
       SET root_phrase = content.phrase_text,
           root_start = content.phrase_start,
           root_end = content.phrase_end,
           root_selected_at = clock_timestamp(),
           updated_at = clock_timestamp()
     WHERE id = canonical_part.id
       AND arc_id = snapshot.arc_id
       AND user_id = snapshot.actor_id
       AND locked_at IS NOT NULL
       AND text = content.paragraph_text;
    IF NOT FOUND THEN RAISE EXCEPTION 'ROOT_CANONICAL_ROOT_FAILED'; END IF;
    RETURN jsonb_build_object(
        'lock_action_id', lock_action.id, 'root_action_id', root_action.id,
        'interaction_state_revision', revision, 'serves_user', false,
        'dataset_eligible', false);
END;
$$;

CREATE OR REPLACE FUNCTION public.remove_synthetic_root_phrase_v1(
    p_project_id UUID,
    p_slide_index INTEGER,
    p_block_key INTEGER,
    p_expected_active_root_action_id UUID,
    p_owner_user_id UUID,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE head public.root_phrase_block_heads;
    active_action public.root_phrase_product_actions;
    remove_action public.root_phrase_product_actions;
    content public.root_phrase_content_versions;
    snapshot public.ideal_text_document_snapshots;
    canonical_part public.ideal_text_part;
    revision BIGINT; action_hash TEXT;
BEGIN
    IF p_slide_index < 0 OR p_block_key < 0
       OR COALESCE(btrim(p_idempotency_key), '') = ''
    THEN RAISE EXCEPTION 'ROOT_REMOVAL_INVALID'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'root-removal:' || p_idempotency_key, 0));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'root-block:' || p_project_id::TEXT || ':' || p_slide_index::TEXT ||
        ':' || p_block_key::TEXT, 0));
    SELECT * INTO remove_action FROM public.root_phrase_product_actions
     WHERE idempotency_key = p_idempotency_key || ':remove';
    IF remove_action.id IS NOT NULL THEN
        action_hash := public.exercise_json_sha256_v1(jsonb_build_object(
            'project_id', p_project_id, 'slide_index', p_slide_index,
            'block_key', p_block_key,
            'content_version_id', remove_action.content_version_id,
            'owner_user_id', p_owner_user_id,
            'action', 'root_remove',
            'supersedes_action_id', p_expected_active_root_action_id));
        IF remove_action.project_id <> p_project_id
           OR remove_action.owner_user_id <> p_owner_user_id
           OR remove_action.supersedes_action_id <>
              p_expected_active_root_action_id
           OR remove_action.action_sha256 <> action_hash
        THEN RAISE EXCEPTION 'ROOT_REMOVAL_REPLAY_CONFLICT'; END IF;
        RETURN jsonb_build_object(
            'root_remove_action_id', remove_action.id,
            'interaction_state_revision', remove_action.interaction_state_revision,
            'serves_user', false, 'dataset_eligible', false);
    END IF;
    SELECT * INTO STRICT head FROM public.root_phrase_block_heads
     WHERE project_id = p_project_id AND slide_index = p_slide_index
       AND block_key = p_block_key FOR UPDATE;
    IF head.active_root_action_id IS DISTINCT FROM p_expected_active_root_action_id
    THEN RAISE EXCEPTION 'ROOT_REMOVAL_STALE_ACTIVE_ROOT'; END IF;
    SELECT * INTO STRICT active_action FROM public.root_phrase_product_actions
     WHERE id = head.active_root_action_id
       AND acquisition_principal_id = head.acquisition_principal_id
       AND action IN ('root_activate', 'root_replace');
    SELECT * INTO STRICT content FROM public.root_phrase_content_versions
     WHERE id = active_action.content_version_id;
    SELECT * INTO STRICT snapshot FROM public.ideal_text_document_snapshots
     WHERE id = content.document_snapshot_id;
    IF NOT EXISTS (SELECT 1 FROM public.owner_principals owner
                    WHERE owner.id = head.acquisition_principal_id
                      AND owner.user_id = p_owner_user_id)
    THEN RAISE EXCEPTION 'ROOT_REMOVAL_OWNER_INVALID'; END IF;
    SELECT * INTO canonical_part FROM public.ideal_text_part part_row
     WHERE part_row.id = content.source_ideal_part_id
       AND part_row.arc_id = snapshot.arc_id
       AND part_row.user_id = snapshot.actor_id
       AND part_row.text = content.paragraph_text
       AND part_row.locked_at IS NOT NULL
       AND part_row.root_phrase = content.phrase_text
       AND part_row.root_start = content.phrase_start
       AND part_row.root_end = content.phrase_end
     FOR UPDATE;
    IF canonical_part.id IS NULL THEN
        RAISE EXCEPTION 'ROOT_REMOVAL_CANONICAL_STATE_CONFLICT';
    END IF;
    PERFORM public.require_synthetic_root_content_live_v1(content.id);
    revision := head.interaction_state_revision + 1;
    action_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'project_id', p_project_id, 'slide_index', p_slide_index,
        'block_key', p_block_key, 'content_version_id', content.id,
        'owner_user_id', p_owner_user_id, 'action', 'root_remove',
        'supersedes_action_id', active_action.id));
    INSERT INTO public.root_phrase_product_actions(
        acquisition_principal_id, project_id, content_version_id,
        qualification_revision_id, owner_user_id, action,
        supersedes_action_id, interaction_state_revision, action_sha256,
        idempotency_key)
    VALUES(head.acquisition_principal_id, p_project_id, content.id, NULL,
        p_owner_user_id, 'root_remove', active_action.id, revision,
        action_hash, p_idempotency_key || ':remove')
    RETURNING * INTO remove_action;
    UPDATE public.root_phrase_block_heads
       SET active_root_action_id = NULL,
           interaction_state_revision = revision,
           updated_at = clock_timestamp()
     WHERE project_id = p_project_id AND slide_index = p_slide_index
       AND block_key = p_block_key;
    UPDATE public.ideal_text_part
       SET root_phrase = NULL, root_start = NULL, root_end = NULL,
           root_selected_at = NULL, updated_at = clock_timestamp()
     WHERE id = canonical_part.id
       AND arc_id = snapshot.arc_id AND user_id = snapshot.actor_id
       AND root_phrase = content.phrase_text
       AND root_start = content.phrase_start
       AND root_end = content.phrase_end;
    IF NOT FOUND THEN RAISE EXCEPTION 'ROOT_REMOVAL_CANONICAL_CLEAR_FAILED'; END IF;
    RETURN jsonb_build_object(
        'root_remove_action_id', remove_action.id,
        'interaction_state_revision', revision,
        'serves_user', false, 'dataset_eligible', false);
END;
$$;

CREATE OR REPLACE FUNCTION public.get_synthetic_root_core_state_v1(
    p_project_id UUID,
    p_acquisition_principal_id UUID,
    p_document_snapshot_id UUID
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER STABLE SET search_path = public AS $$
DECLARE snapshot public.ideal_text_document_snapshots;
    paragraphs JSONB; slides JSONB; interaction_revision BIGINT;
    full_density BOOLEAN;
BEGIN
    SELECT * INTO STRICT snapshot FROM public.ideal_text_document_snapshots source
     WHERE source.id=p_document_snapshot_id AND source.project_id=p_project_id
       AND source.acquisition_principal_id=p_acquisition_principal_id
       AND EXISTS (SELECT 1 FROM public.ideal_text_document_heads head
                    WHERE head.snapshot_id=source.id);
    SELECT COALESCE(max(head.interaction_state_revision), 0)
      INTO interaction_revision FROM public.root_phrase_block_heads head
     WHERE head.project_id=p_project_id
       AND head.acquisition_principal_id=p_acquisition_principal_id;
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
        'id', part->>'id', 'text', part->>'text',
        'slide_index', (piece->>'slide_index')::INTEGER,
        'locked', EXISTS (
            SELECT 1 FROM public.ideal_text_part canonical_part
           WHERE canonical_part.id=(part->>'id')::UUID
             AND canonical_part.arc_id=snapshot.arc_id
             AND canonical_part.user_id=snapshot.actor_id
             AND canonical_part.text=part->>'text'
             AND canonical_part.locked_at IS NOT NULL),
        'active_root', (
            SELECT jsonb_build_object(
                'phrase_text', content.phrase_text,
                'phrase_start', content.phrase_start,
                'phrase_end', content.phrase_end,
                'block_key', content.block_key)
              FROM public.root_phrase_block_heads head
              JOIN public.root_phrase_product_actions action_row
                ON action_row.id=head.active_root_action_id
              JOIN public.root_phrase_content_versions content
                ON content.id=action_row.content_version_id
             WHERE head.project_id=p_project_id
               AND head.acquisition_principal_id=p_acquisition_principal_id
               AND content.source_ideal_part_id=(part->>'id')::UUID
               AND content.paragraph_text=part->>'text'
             LIMIT 1)
    ) ORDER BY ordinal), '[]'::jsonb)
      INTO paragraphs
      FROM jsonb_array_elements(snapshot.payload->'parts')
           WITH ORDINALITY v(part,ordinal)
      LEFT JOIN LATERAL (
          SELECT value AS piece
            FROM jsonb_array_elements(snapshot.payload->'pieces') value
           WHERE value->>'part_id'=part->>'id' LIMIT 1
      ) mapped ON true;
    WITH slide_ids AS (
        SELECT DISTINCT (piece->>'slide_index')::INTEGER AS slide_index
          FROM jsonb_array_elements(snapshot.payload->'pieces') piece
    ), blocks AS (
        SELECT DISTINCT item.slide_index,item.block_key
          FROM public.feedback_v3_memberships membership
          JOIN public.feedback_v3_membership_items item
            ON item.membership_id=membership.id
         WHERE membership.document_snapshot_id=snapshot.id
           AND membership.acquisition_principal_id=p_acquisition_principal_id
           AND item.feedback_family='confident_voice'
           AND item.eligibility='eligible'
    ), active AS (
        SELECT DISTINCT head.slide_index,head.block_key
          FROM public.root_phrase_block_heads head
          JOIN public.root_phrase_product_actions action_row
            ON action_row.id=head.active_root_action_id
          JOIN public.root_phrase_content_versions content
            ON content.id=action_row.content_version_id
         WHERE head.project_id=p_project_id
           AND head.acquisition_principal_id=p_acquisition_principal_id
           AND EXISTS (
               SELECT 1 FROM jsonb_array_elements(snapshot.payload->'parts') part
                WHERE part->>'id'=content.source_ideal_part_id::TEXT
                  AND part->>'text'=content.paragraph_text)
    ), slide_summary AS (
        SELECT slide_ids.slide_index,
               count(DISTINCT blocks.block_key) AS current_block_count,
               count(DISTINCT active.block_key) AS active_block_count
          FROM slide_ids
          LEFT JOIN blocks ON blocks.slide_index=slide_ids.slide_index
          LEFT JOIN active ON active.slide_index=slide_ids.slide_index
           AND active.block_key=blocks.block_key
         GROUP BY slide_ids.slide_index
    )
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
        'slide_index',slide_summary.slide_index,
        'state',CASE WHEN slide_summary.active_block_count>0
            THEN 'slide_minimum_ready' ELSE 'slide_pending' END,
        'current_block_count',slide_summary.current_block_count,
        'active_block_count',slide_summary.active_block_count
    ) ORDER BY slide_summary.slide_index),'[]'::jsonb)
      INTO slides
      FROM slide_summary;
    WITH blocks AS (
        SELECT DISTINCT item.slide_index,item.block_key
          FROM public.feedback_v3_memberships membership
          JOIN public.feedback_v3_membership_items item
            ON item.membership_id=membership.id
         WHERE membership.document_snapshot_id=snapshot.id
           AND membership.acquisition_principal_id=p_acquisition_principal_id
           AND item.feedback_family='confident_voice'
           AND item.eligibility='eligible'
    ), active AS (
        SELECT DISTINCT head.slide_index,head.block_key
          FROM public.root_phrase_block_heads head
          JOIN public.root_phrase_product_actions action_row
            ON action_row.id=head.active_root_action_id
          JOIN public.root_phrase_content_versions content
            ON content.id=action_row.content_version_id
         WHERE head.project_id=p_project_id
           AND head.acquisition_principal_id=p_acquisition_principal_id
           AND EXISTS (
               SELECT 1 FROM jsonb_array_elements(snapshot.payload->'parts') part
                WHERE part->>'id'=content.source_ideal_part_id::TEXT
                  AND part->>'text'=content.paragraph_text)
    )
    SELECT EXISTS(SELECT 1 FROM blocks)
       AND NOT EXISTS (
           SELECT 1 FROM blocks block_row
            WHERE NOT EXISTS (
                SELECT 1 FROM active active_row
                 WHERE active_row.slide_index=block_row.slide_index
                   AND active_row.block_key=block_row.block_key))
      INTO full_density;
    RETURN jsonb_build_object(
        'content_snapshot_id',snapshot.id,
        'content_snapshot_sha256',snapshot.payload_sha256,
        'interaction_state_revision',interaction_revision,
        'paragraphs',paragraphs,'slides',slides,
        'full_density',COALESCE(full_density,false),
        'serves_user',false);
END;
$$;

DO $$
DECLARE relation_name TEXT;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'root_phrase_content_versions', 'root_phrase_semantic_input_snapshots',
        'root_phrase_semantic_results',
        'root_phrase_owner_alignment_actions',
        'root_phrase_qualification_revisions', 'root_phrase_product_actions',
        'root_phrase_block_heads'
    ] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', relation_name);
        EXECUTE format(
            'REVOKE ALL ON public.%I FROM PUBLIC,anon,authenticated,service_role',
            relation_name);
        EXECUTE format('GRANT SELECT ON public.%I TO service_role', relation_name);
    END LOOP;
    FOREACH relation_name IN ARRAY ARRAY[
        'root_phrase_content_versions', 'root_phrase_semantic_input_snapshots',
        'root_phrase_semantic_results',
        'root_phrase_owner_alignment_actions',
        'root_phrase_qualification_revisions', 'root_phrase_product_actions'
    ] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON public.%I',
            relation_name || '_append_only', relation_name);
        EXECUTE format(
            'CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON public.%I FOR EACH ROW '
            'EXECUTE FUNCTION public.reject_mlc2_immutable_mutation()',
            relation_name || '_append_only', relation_name);
    END LOOP;
END;
$$;

REVOKE ALL ON FUNCTION public.register_synthetic_root_content_version_v1(
    UUID,UUID,UUID,UUID,TEXT,INTEGER,INTEGER,TEXT,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.register_synthetic_root_content_version_v1(
    UUID,UUID,UUID,UUID,TEXT,INTEGER,INTEGER,TEXT,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.root_phrase_normalize_transcript_v1(TEXT)
    FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.require_synthetic_root_content_live_v1(UUID)
    FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.freeze_synthetic_root_semantic_input_v1(UUID,TEXT)
    FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.freeze_synthetic_root_semantic_input_v1(UUID,TEXT)
    TO service_role;
REVOKE ALL ON FUNCTION public.record_synthetic_root_semantic_result_v1(
    UUID,UUID,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.record_synthetic_root_semantic_result_v1(
    UUID,UUID,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.record_synthetic_root_alignment_action_v1(
    UUID,UUID,UUID,TEXT,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.record_synthetic_root_alignment_action_v1(
    UUID,UUID,UUID,TEXT,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.evaluate_synthetic_root_qualification_v1(
    UUID,UUID,UUID,UUID,UUID,TEXT,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.evaluate_synthetic_root_qualification_v1(
    UUID,UUID,UUID,UUID,UUID,TEXT,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.activate_synthetic_root_phrase_v1(
    UUID,UUID,BOOLEAN,BOOLEAN,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.activate_synthetic_root_phrase_v1(
    UUID,UUID,BOOLEAN,BOOLEAN,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.remove_synthetic_root_phrase_v1(
    UUID,INTEGER,INTEGER,UUID,UUID,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.remove_synthetic_root_phrase_v1(
    UUID,INTEGER,INTEGER,UUID,UUID,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.get_synthetic_root_core_state_v1(UUID,UUID,UUID)
    FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.get_synthetic_root_core_state_v1(UUID,UUID,UUID)
    TO service_role;

COMMENT ON TABLE public.root_phrase_qualification_revisions IS
    'Synthetic product-routing eligibility only; never an ML judgment, supervision label, or exposure.';
COMMENT ON TABLE public.root_phrase_owner_alignment_actions IS
    'Owner presentation-routing actions only; excluded from all eight learning surfaces.';

COMMIT;
