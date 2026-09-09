-- MLC-3 Coach Inline Exercise Authoring D5 — release migration 0324.
-- All rows remain non-serving and
-- non-dataset until a separately reviewed assignment transition exists.

BEGIN;

CREATE OR REPLACE FUNCTION public.reject_coach_inline_mutation_v1()
RETURNS trigger LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
    RAISE EXCEPTION 'COACH_INLINE_EXERCISE_APPEND_ONLY';
END;
$$;

REVOKE ALL ON FUNCTION public.reject_coach_inline_mutation_v1()
    FROM PUBLIC, anon, authenticated, service_role;

-- Composite parent identities let every D5 child prove the same reviewer,
-- assignment, packet, audio lineage and acquisition principal at the database
-- boundary.  Do not rely on a service-layer lookup for these relationships.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'public.exercise_blind_packets'::regclass
           AND conname = 'exercise_blind_packets_id_assignment_lineage_key'
    ) THEN
        ALTER TABLE public.exercise_blind_packets
            ADD CONSTRAINT exercise_blind_packets_id_assignment_lineage_key
            UNIQUE (id, review_assignment_id, audio_lineage_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'public.exercise_audio_lineages'::regclass
           AND conname = 'exercise_audio_lineages_id_principal_key'
    ) THEN
        ALTER TABLE public.exercise_audio_lineages
            ADD CONSTRAINT exercise_audio_lineages_id_principal_key
            UNIQUE (id, acquisition_principal_id);
    END IF;
END;
$$;

-- General post-blind guidance is bound to the canonical review act.  An
-- ordinary frozen batch item may not have a V3 offer membership/candidate;
-- exercise attachments still require both identities.  Existing D3/service
-- writers continue to pass the exact pair and retain their stricter checks.
ALTER TABLE public.coach_guidance_attachments
    ALTER COLUMN feedback_membership_id DROP NOT NULL,
    ALTER COLUMN feedback_candidate_id DROP NOT NULL;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'public.coach_guidance_attachments'::regclass
           AND conname = 'coach_guidance_feedback_identity_class_check'
    ) THEN
        ALTER TABLE public.coach_guidance_attachments
            ADD CONSTRAINT coach_guidance_feedback_identity_class_check CHECK (
                (feedback_membership_id IS NULL) =
                    (feedback_candidate_id IS NULL)
                AND (
                    attachment_class = 'general_product_guidance'
                    OR (feedback_membership_id IS NOT NULL
                        AND feedback_candidate_id IS NOT NULL)
                )
            );
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS public.coach_inline_source_roles (
    review_batch_id UUID NOT NULL
        REFERENCES public.coach_guidance_review_batches(id) ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    reviewer_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    review_assignment_id UUID NOT NULL
        REFERENCES public.ml_review_assignments(id) ON DELETE RESTRICT,
    blind_packet_id UUID NOT NULL,
    audio_lineage_id UUID NOT NULL,
    evidence_role TEXT NOT NULL CHECK (
        evidence_role = 'source_before_exercise'
    ),
    role_sha256 TEXT NOT NULL CHECK (role_sha256 ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    PRIMARY KEY (review_batch_id, review_assignment_id),
    FOREIGN KEY (
        review_batch_id, acquisition_principal_id, reviewer_principal_id
    ) REFERENCES public.coach_guidance_review_batches(
        id, acquisition_principal_id, reviewer_principal_id
    ) ON DELETE RESTRICT,
    FOREIGN KEY (review_assignment_id, reviewer_principal_id)
        REFERENCES public.ml_review_assignments(id, reviewer_principal_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (blind_packet_id, review_assignment_id, audio_lineage_id)
        REFERENCES public.exercise_blind_packets(
            id, review_assignment_id, audio_lineage_id
        ) ON DELETE RESTRICT,
    FOREIGN KEY (audio_lineage_id, acquisition_principal_id)
        REFERENCES public.exercise_audio_lineages(
            id, acquisition_principal_id
        ) ON DELETE RESTRICT,
    UNIQUE (
        review_batch_id, review_assignment_id,
        acquisition_principal_id, reviewer_principal_id
    )
);

CREATE TABLE IF NOT EXISTS public.coach_inline_exercise_drafts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attachment_version_id UUID NOT NULL UNIQUE
        REFERENCES public.coach_guidance_attachment_versions(id)
        ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    author_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    review_batch_id UUID NOT NULL
        REFERENCES public.coach_guidance_review_batches(id) ON DELETE RESTRICT,
    review_assignment_id UUID NOT NULL
        REFERENCES public.ml_review_assignments(id) ON DELETE RESTRICT,
    exercise_offer_id UUID NOT NULL
        REFERENCES public.exercise_service_offers(id) ON DELETE RESTRICT,
    need_contract_id UUID NOT NULL
        REFERENCES public.exercise_need_contracts(id) ON DELETE RESTRICT,
    source_role TEXT NOT NULL CHECK (source_role = 'source_before_exercise'),
    provenance_class TEXT NOT NULL CHECK (
        provenance_class = 'user_source_dependent'
    ),
    title TEXT NOT NULL CHECK (length(btrim(title)) BETWEEN 1 AND 120),
    instruction_text TEXT NOT NULL CHECK (
        length(btrim(instruction_text)) BETWEEN 1 AND 2000
    ),
    language_code TEXT NOT NULL CHECK (
        language_code ~ '^[a-z]{2}(-[A-Z]{2})?$'
    ),
    supported_confidence_patterns TEXT[] NOT NULL CHECK (
        cardinality(supported_confidence_patterns) > 0
        AND supported_confidence_patterns <@ ARRAY[
            'low_confidence_rushing_dominant',
            'near_confident',
            'confident'
        ]::TEXT[]
    ),
    draft_state TEXT NOT NULL DEFAULT 'awaiting_review' CHECK (
        draft_state = 'awaiting_review'
    ),
    contract_version TEXT NOT NULL CHECK (
        contract_version = 'coach-inline-exercise-authoring-d5'
    ),
    draft_sha256 TEXT NOT NULL CHECK (draft_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE CHECK (
        length(btrim(idempotency_key)) BETWEEN 1 AND 200
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    FOREIGN KEY (
        review_batch_id, acquisition_principal_id, author_principal_id
    ) REFERENCES public.coach_guidance_review_batches(
        id, acquisition_principal_id, reviewer_principal_id
    ) ON DELETE RESTRICT,
    FOREIGN KEY (
        review_batch_id, review_assignment_id,
        acquisition_principal_id, author_principal_id
    ) REFERENCES public.coach_inline_source_roles(
        review_batch_id, review_assignment_id,
        acquisition_principal_id, reviewer_principal_id
    ) ON DELETE RESTRICT,
    UNIQUE (id, acquisition_principal_id)
);

CREATE TABLE IF NOT EXISTS public.coach_inline_context_assessments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    reviewer_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    review_assignment_id UUID NOT NULL
        REFERENCES public.ml_review_assignments(id) ON DELETE RESTRICT,
    blind_packet_id UUID NOT NULL,
    audio_lineage_id UUID NOT NULL,
    context_state TEXT NOT NULL CHECK (
        context_state IN ('known', 'unknown', 'verified_none')
    ),
    assessment_revision INTEGER NOT NULL CHECK (assessment_revision > 0),
    supersedes_assessment_id UUID NULL
        REFERENCES public.coach_inline_context_assessments(id)
        ON DELETE RESTRICT,
    history_policy_version TEXT NOT NULL,
    history_cutoff_at TIMESTAMPTZ NOT NULL,
    history_inventory_sha256 TEXT NOT NULL CHECK (
        history_inventory_sha256 ~ '^[0-9a-f]{64}$'
    ),
    assessment_sha256 TEXT NOT NULL CHECK (
        assessment_sha256 ~ '^[0-9a-f]{64}$'
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    UNIQUE (review_assignment_id, reviewer_principal_id, assessment_revision),
    UNIQUE (supersedes_assessment_id),
    FOREIGN KEY (review_assignment_id, reviewer_principal_id)
        REFERENCES public.ml_review_assignments(id, reviewer_principal_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (blind_packet_id, review_assignment_id, audio_lineage_id)
        REFERENCES public.exercise_blind_packets(
            id, review_assignment_id, audio_lineage_id
        ) ON DELETE RESTRICT,
    FOREIGN KEY (audio_lineage_id, acquisition_principal_id)
        REFERENCES public.exercise_audio_lineages(
            id, acquisition_principal_id
        ) ON DELETE RESTRICT,
    UNIQUE (id, acquisition_principal_id)
);

CREATE TABLE IF NOT EXISTS public.coach_inline_exercise_eligibility_reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_id UUID NOT NULL
        REFERENCES public.coach_inline_exercise_drafts(id) ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL,
    reviewed_exercise_version_id UUID NOT NULL
        REFERENCES public.exercise_versions(id) ON DELETE RESTRICT,
    compatibility_profile_id UUID NOT NULL
        REFERENCES public.exercise_n1_version_compatibility_profiles(id)
        ON DELETE RESTRICT,
    content_approval_version TEXT NOT NULL,
    content_approval_sha256 TEXT NOT NULL CHECK (
        content_approval_sha256 ~ '^[0-9a-f]{64}$'
    ),
    safety_approval_version TEXT NOT NULL,
    safety_approval_sha256 TEXT NOT NULL CHECK (
        safety_approval_sha256 ~ '^[0-9a-f]{64}$'
    ),
    rights_approval_version TEXT NOT NULL,
    rights_approval_sha256 TEXT NOT NULL CHECK (
        rights_approval_sha256 ~ '^[0-9a-f]{64}$'
    ),
    fresh_inventory_sha256 TEXT NOT NULL CHECK (
        fresh_inventory_sha256 ~ '^[0-9a-f]{64}$'
    ),
    review_sha256 TEXT NOT NULL CHECK (review_sha256 ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    FOREIGN KEY (draft_id, acquisition_principal_id)
        REFERENCES public.coach_inline_exercise_drafts(
            id, acquisition_principal_id
        ) ON DELETE RESTRICT,
    UNIQUE (draft_id, reviewed_exercise_version_id)
);

-- Create current product-processing authority for one exact post-blind
-- ordinary-guidance act.  The receipt/policy are derived from the source
-- packet's immutable acquisition snapshot; no latest-receipt lookup and no
-- pooled-learning authority are permitted.
CREATE OR REPLACE FUNCTION public.issue_coach_inline_general_authority_v1(
    p_review_batch_id UUID,
    p_reveal_grant_id UUID,
    p_reveal_access_id UUID,
    p_review_assignment_id UUID,
    p_reviewer_principal_id UUID,
    p_idempotency_key TEXT
) RETURNS public.processing_authorization_snapshots
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    principal_id UUID;
    source_receipt_id UUID;
    source_policy_id UUID;
    source_take_id UUID;
    source_recording_id UUID;
    authority_hash TEXT;
    result public.processing_authorization_snapshots;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'COACH_INLINE_REQUIRES_READ_COMMITTED';
    END IF;
    IF COALESCE(btrim(p_idempotency_key), '') = '' THEN
        RAISE EXCEPTION 'COACH_INLINE_GENERAL_AUTHORITY_KEY_REQUIRED';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'coach-inline-general-authority:' || p_review_assignment_id::TEXT, 0
    ));
    SELECT lineage_row.acquisition_principal_id,
           packet_snapshot.receipt_id, packet_snapshot.policy_id,
           lineage_row.take_id, lineage_row.recording_id
      INTO principal_id, source_receipt_id, source_policy_id,
           source_take_id, source_recording_id
      FROM public.coach_guidance_review_batches batch
      JOIN public.coach_guidance_reveal_grants grant_row
        ON grant_row.id = p_reveal_grant_id
       AND grant_row.review_batch_id = batch.id
       AND grant_row.acquisition_principal_id =
           batch.acquisition_principal_id
       AND grant_row.reviewer_principal_id =
           batch.reviewer_principal_id
      JOIN public.coach_guidance_reveal_accesses access_row
        ON access_row.id = p_reveal_access_id
       AND access_row.reveal_grant_id = grant_row.id
       AND access_row.review_assignment_id = p_review_assignment_id
       AND access_row.reviewer_principal_id =
           p_reviewer_principal_id
       AND access_row.access_purpose = 'guidance_authoring'
      JOIN public.coach_inline_source_roles source_role
        ON source_role.review_batch_id = batch.id
       AND source_role.review_assignment_id = p_review_assignment_id
       AND source_role.reviewer_principal_id =
           p_reviewer_principal_id
       AND source_role.evidence_role = 'source_before_exercise'
      JOIN public.exercise_blind_packets packet
        ON packet.id = source_role.blind_packet_id
       AND packet.review_assignment_id = source_role.review_assignment_id
       AND packet.audio_lineage_id = source_role.audio_lineage_id
      JOIN public.exercise_audio_lineages lineage_row
        ON lineage_row.id = packet.audio_lineage_id
       AND lineage_row.acquisition_principal_id =
           batch.acquisition_principal_id
      JOIN public.exercise_authorization_checks source_check
        ON source_check.id = packet.authorization_check_id
       AND source_check.acquisition_principal_id =
           batch.acquisition_principal_id
      JOIN public.processing_authorization_snapshots packet_snapshot
        ON packet_snapshot.id = source_check.authorization_snapshot_id
       AND packet_snapshot.acquisition_principal_id =
           batch.acquisition_principal_id
     WHERE batch.id = p_review_batch_id
       AND batch.reviewer_principal_id = p_reviewer_principal_id;
    PERFORM public.require_coach_guidance_assignment_live_v1(
        p_review_assignment_id, principal_id, 'coach_review'
    );
    PERFORM public.require_coach_guidance_receipt_authority_v1(
        source_receipt_id, principal_id, 'coach_review'
    );
    authority_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'contract_version', 'coach-inline-general-guidance-authority-d5',
        'acquisition_principal_id', principal_id,
        'source_receipt_id', source_receipt_id,
        'source_policy_id', source_policy_id,
        'review_batch_id', p_review_batch_id,
        'reveal_grant_id', p_reveal_grant_id,
        'reveal_access_id', p_reveal_access_id,
        'review_assignment_id', p_review_assignment_id,
        'source_take_id', source_take_id,
        'source_recording_id', source_recording_id,
        'purpose_id', 'coach_review',
        'idempotency_key', p_idempotency_key
    ));
    SELECT * INTO result
      FROM public.processing_authorization_snapshots snapshot_row
     WHERE snapshot_row.acquisition_principal_id = principal_id
       AND snapshot_row.authority_evidence_sha256 = authority_hash;
    IF result.id IS NULL THEN
        INSERT INTO public.processing_authorization_snapshots (
            acquisition_principal_id, receipt_id, policy_id, purpose_id,
            operation_kind, source_take_id, source_recording_id,
            authority_evidence_sha256, pooled_learning_eligible,
            authority_checked_at
        ) VALUES (
            principal_id, source_receipt_id,
            source_policy_id, 'coach_review',
            'coach_inline_general_guidance', source_take_id,
            source_recording_id, authority_hash, false, clock_timestamp()
        ) RETURNING * INTO result;
    END IF;
    PERFORM public.require_coach_guidance_assignment_live_v1(
        p_review_assignment_id, principal_id, 'coach_review'
    );
    PERFORM public.require_coach_guidance_authority_v1(
        result.id, principal_id, 'coach_review'
    );
    RETURN result;
END;
$$;

-- Prepare the exact blind assignment used by the visible coach card.  This is
-- intentionally the same ml_review_assignments/exercise_blind_packets pair
-- consumed by the D3 complete-batch grant: the UI never creates a parallel
-- evidence_review_assignment or a second canonical judgment for this act.
CREATE OR REPLACE FUNCTION public.prepare_coach_inline_blind_batch_v1(
    p_project_id UUID,
    p_acquisition_principal_id UUID,
    p_reviewer_principal_id UUID,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    source RECORD;
    evidence public.ml_evidence_spans;
    assignment public.ml_review_assignments;
    packet public.exercise_blind_packets;
    presentation public.ml_presentations;
    batch public.coach_guidance_review_batches;
    authority JSONB;
    auth_check_id UUID;
    assignment_id UUID;
    packet_id UUID;
    playback_reference_id UUID;
    packet_payload JSONB;
    packet_hash TEXT;
    opaque_payload JSONB;
    opaque_hash TEXT;
    item_count INTEGER := 0;
    result_items JSONB := '[]'::JSONB;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'COACH_INLINE_REQUIRES_READ_COMMITTED';
    END IF;
    IF COALESCE(btrim(p_idempotency_key), '') = '' THEN
        RAISE EXCEPTION 'COACH_INLINE_BLIND_BATCH_KEY_REQUIRED';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.projects project
         WHERE project.id = p_project_id
           AND project.owner_principal_id = p_acquisition_principal_id
    ) THEN
        RAISE EXCEPTION 'COACH_INLINE_PROJECT_PRINCIPAL_MISMATCH';
    END IF;
    PERFORM public.require_coach_guidance_reviewer_access_v1(
        p_reviewer_principal_id
    );
    PERFORM pg_advisory_xact_lock(hashtextextended(concat_ws(':',
        'coach-inline-visible-batch', p_project_id::TEXT,
        p_acquisition_principal_id::TEXT,
        p_reviewer_principal_id::TEXT), 0));

    FOR source IN
        SELECT DISTINCT ON (offer.feedback_membership_id,
                            offer.feedback_candidate_id)
               offer.id AS offer_id, offer.source_audio_lineage_id,
               offer.authorization_check_id, offer.feedback_membership_id,
               offer.feedback_candidate_id, offer.outcome,
               lineage.take_id, lineage.recording_id, lineage.snippet_id,
               lineage.duration_ms, lineage.acquisition_principal_id,
               snippet.transcript, 'en'::TEXT AS language_code
          FROM public.exercise_service_offers offer
          JOIN public.exercise_audio_lineages lineage
            ON lineage.id = offer.source_audio_lineage_id
           AND lineage.acquisition_principal_id = p_acquisition_principal_id
           AND lineage.project_id = p_project_id
           AND lineage.take_id = offer.source_take_id
          JOIN public.feedback_v3_membership_items feedback_item
            ON feedback_item.membership_id = offer.feedback_membership_id
           AND feedback_item.candidate_id = offer.feedback_candidate_id
           AND feedback_item.snippet_id = lineage.snippet_id
           AND feedback_item.feedback_family = 'confident_voice'
           AND feedback_item.selected
           AND feedback_item.eligibility = 'eligible'
          JOIN public.snippets snippet
            ON snippet.id = lineage.snippet_id
           AND snippet.session_id = lineage.take_id
           AND snippet.recording_id = lineage.recording_id
           AND snippet.start_offset_ms = lineage.start_offset_ms
           AND snippet.duration_ms = lineage.duration_ms
          JOIN public.v2_sessions take_row
            ON take_row.id = lineage.take_id
           AND take_row.project_id = p_project_id
           AND take_row.owner_principal_id = p_acquisition_principal_id
         WHERE offer.acquisition_principal_id = p_acquisition_principal_id
           AND offer.project_id = p_project_id
           AND offer.operation_mode = 'allowlisted_service'
           AND offer.serves_user AND NOT offer.dataset_eligible
         ORDER BY offer.feedback_membership_id, offer.feedback_candidate_id,
                  offer.prepared_at DESC, offer.id DESC
    LOOP
        PERFORM public.require_exercise_service_current_authority_v1(
            source.authorization_check_id, p_acquisition_principal_id
        );
        IF NOT EXISTS (
            SELECT 1 FROM public.exercise_audio_lineages lineage_row
              JOIN public.processing_audio_objects object_row
                ON object_row.id = lineage_row.processing_audio_object_id
               AND object_row.acquisition_principal_id =
                   lineage_row.acquisition_principal_id
               AND object_row.deleted_at IS NULL
             WHERE lineage_row.id = source.source_audio_lineage_id
               AND lineage_row.acquisition_principal_id =
                   p_acquisition_principal_id
               AND NOT EXISTS (
                   SELECT 1 FROM public.data_purge_requests purge
                    WHERE purge.acquisition_principal_id =
                          p_acquisition_principal_id
                      AND purge.state <> 'done'
               )
        ) THEN RAISE EXCEPTION 'COACH_INLINE_SOURCE_NOT_LIVE'; END IF;
        SELECT evidence_row.* INTO STRICT evidence
          FROM public.ml_evidence_spans evidence_row
         WHERE public.exercise_evidence_matches_audio_v1(
             evidence_row.id, source.source_audio_lineage_id
         );
        authority := public.issue_exercise_service_authority_v1(
            p_acquisition_principal_id, source.take_id, source.recording_id,
            'blind_review_preparation',
            'coach-inline-authority-v1:' || source.offer_id::TEXT || ':' ||
                p_reviewer_principal_id::TEXT
        );
        auth_check_id := (authority->>'authorization_check_id')::UUID;
        assignment_id := gen_random_uuid();
        packet_id := gen_random_uuid();
        playback_reference_id := gen_random_uuid();
        packet_payload := public.build_exercise_blind_visible_payload_v1(
            packet_id, assignment_id,
            'confidence-exercise-blind-packet-v1',
            'confidence-five-state-v1', playback_reference_id,
            source.duration_ms, source.language_code,
            NULLIF(btrim(source.transcript), '')
        );
        packet_hash := public.exercise_json_sha256_v1(packet_payload);

        SELECT assignment_row.* INTO assignment
          FROM public.ml_review_assignments assignment_row
         WHERE assignment_row.idempotency_key =
               'coach-inline-assignment-v1:' || source.offer_id::TEXT || ':' ||
                   p_reviewer_principal_id::TEXT;
        IF assignment.id IS NULL THEN
            INSERT INTO public.ml_review_assignments (
                id, learning_surface_id, evidence_span_id,
                reviewer_principal_id, reviewer_role, blind_packet_sha256,
                taxonomy_version, blindness_policy_version, expires_at,
                idempotency_key
            ) VALUES (
                assignment_id, 'confidence_classification', evidence.id,
                p_reviewer_principal_id, 'coach', packet_hash,
                'confidence-five-state-v1',
                'coach-inline-complete-batch-v1',
                clock_timestamp() + INTERVAL '7 days',
                'coach-inline-assignment-v1:' || source.offer_id::TEXT || ':' ||
                    p_reviewer_principal_id::TEXT
            ) RETURNING * INTO assignment;
            INSERT INTO public.ml_review_assignment_events (
                review_assignment_id, event_kind, actor_principal_id,
                idempotency_key, metadata
            ) VALUES (
                assignment.id, 'assigned', NULL,
                'coach-inline-assigned-v1:' || source.offer_id::TEXT || ':' ||
                    p_reviewer_principal_id::TEXT,
                jsonb_build_object('source_offer_id', source.offer_id,
                    'packet_schema_version',
                    'confidence-exercise-blind-packet-v1')
            );
            packet := public.register_exercise_blind_packet_v1(
                packet_id, assignment.id, source.source_audio_lineage_id,
                auth_check_id, p_reviewer_principal_id,
                'confidence-exercise-blind-packet-v1',
                'confidence-five-state-v1', playback_reference_id,
                clock_timestamp() + INTERVAL '7 days', source.duration_ms,
                source.language_code, NULLIF(btrim(source.transcript), ''),
                'coach-inline-complete-batch-v1',
                'coach-inline-packet-v1:' || source.offer_id::TEXT || ':' ||
                    p_reviewer_principal_id::TEXT
            );
        ELSE
            SELECT packet_row.* INTO STRICT packet
              FROM public.exercise_blind_packets packet_row
             WHERE packet_row.review_assignment_id = assignment.id
               AND packet_row.audio_lineage_id = source.source_audio_lineage_id
               AND packet_row.reviewer_principal_id = p_reviewer_principal_id;
            PERFORM public.require_coach_guidance_assignment_live_v1(
                assignment.id, p_acquisition_principal_id, 'coach_review'
            );
        END IF;

        opaque_payload := jsonb_build_object(
            'review_assignment_id', assignment.id,
            'blind_packet_id', packet.id,
            'playback_reference_id', assignment.id,
            'question', 'Was this voice confident?',
            'allowed_response_ids', jsonb_build_array(
                'rating_yes', 'rating_in_between', 'rating_no',
                'rating_not_sure', 'rating_audio_unclear'
            )
        );
        opaque_hash := public.exercise_json_sha256_v1(opaque_payload);
        SELECT presentation_row.* INTO presentation
          FROM public.ml_presentations presentation_row
         WHERE presentation_row.idempotency_key =
               'coach-inline-presentation-v1:' || source.offer_id::TEXT || ':' ||
                   p_reviewer_principal_id::TEXT;
        IF presentation.id IS NULL THEN
            INSERT INTO public.ml_presentations (
                canonical_event_id, learning_surface_id,
                review_assignment_id, actor_principal_id, actor_role,
                delivery_mode, evaluation_only, visible_payload_sha256,
                idempotency_key
            ) VALUES (
                evidence.canonical_event_id, 'confidence_classification',
                assignment.id, p_reviewer_principal_id, 'coach', 'canary',
                false, opaque_hash,
                'coach-inline-presentation-v1:' || source.offer_id::TEXT || ':' ||
                    p_reviewer_principal_id::TEXT
            ) RETURNING * INTO presentation;
        ELSIF presentation.review_assignment_id <> assignment.id
              OR presentation.actor_principal_id <> p_reviewer_principal_id
              OR presentation.visible_payload_sha256 <> opaque_hash THEN
            RAISE EXCEPTION 'COACH_INLINE_BLIND_PRESENTATION_REPLAY_CONFLICT';
        END IF;
        item_count := item_count + 1;
    END LOOP;
    IF item_count = 0 THEN
        RAISE EXCEPTION 'COACH_INLINE_BATCH_HAS_NO_ASSIGNMENTS';
    END IF;

    SELECT public.exercise_json_sha256_v1(COALESCE(jsonb_agg(
        jsonb_build_object('assignment_id', assignment_row.id,
            'packet_sha256', assignment_row.blind_packet_sha256)
        ORDER BY assignment_row.assigned_at, assignment_row.id
    ), '[]'::JSONB)) INTO opaque_hash
      FROM public.ml_review_assignments assignment_row
      JOIN public.exercise_blind_packets packet_row
        ON packet_row.review_assignment_id = assignment_row.id
      JOIN public.exercise_audio_lineages lineage_row
        ON lineage_row.id = packet_row.audio_lineage_id
       AND lineage_row.acquisition_principal_id = p_acquisition_principal_id
       AND lineage_row.project_id = p_project_id
     WHERE assignment_row.reviewer_principal_id = p_reviewer_principal_id
       AND assignment_row.reviewer_role = 'coach'
       AND assignment_row.learning_surface_id = 'confidence_classification';
    batch := public.freeze_synthetic_coach_guidance_batch_v1(
        p_acquisition_principal_id, p_project_id, p_reviewer_principal_id,
        'coach-inline-visible-batch-v1:' || p_project_id::TEXT || ':' ||
            p_reviewer_principal_id::TEXT || ':' || opaque_hash
    );
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
        'review_batch_id', batch.id,
        'review_assignment_id', frame_item.review_assignment_id,
        'blind_packet_id', frame_item.blind_packet_id,
        'take_id', lineage.take_id,
        'snippet_id', lineage.snippet_id,
        'playback_reference_id', frame_item.review_assignment_id,
        'presentation_id', presentation_row.id,
        'acknowledgement_token', presentation_row.acknowledgement_token,
        'visible_payload_sha256', presentation_row.visible_payload_sha256,
        'canonical_position', frame_item.canonical_position,
        'judgment', judgment.decision
    ) ORDER BY frame_item.canonical_position), '[]'::JSONB)
      INTO result_items
      FROM public.coach_guidance_review_frame_items frame_item
      JOIN public.exercise_blind_packets packet_row
        ON packet_row.id = frame_item.blind_packet_id
       AND packet_row.review_assignment_id = frame_item.review_assignment_id
      JOIN public.exercise_audio_lineages lineage
        ON lineage.id = packet_row.audio_lineage_id
       AND lineage.acquisition_principal_id = p_acquisition_principal_id
       AND lineage.project_id = p_project_id
      JOIN public.ml_presentations presentation_row
        ON presentation_row.review_assignment_id = frame_item.review_assignment_id
       AND presentation_row.actor_principal_id = p_reviewer_principal_id
      LEFT JOIN LATERAL (
          SELECT candidate.decision
            FROM public.ml_judgments candidate
           WHERE candidate.review_assignment_id = frame_item.review_assignment_id
             AND candidate.actor_principal_id = p_reviewer_principal_id
             AND candidate.actor_provenance = 'blind_coach'
             AND NOT EXISTS (SELECT 1 FROM public.ml_judgments later
                 WHERE later.supersedes_id = candidate.id)
           ORDER BY candidate.decided_at DESC, candidate.id DESC LIMIT 1
      ) judgment ON true
     WHERE frame_item.frame_id = batch.frame_id
       AND frame_item.membership_state = 'required';
    RETURN jsonb_build_object(
        'review_batch_id', batch.id, 'items', result_items,
        'operation_mode', 'synthetic_dark', 'synthetic_only', true,
        'serves_user', false, 'dataset_eligible', false
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.ack_coach_inline_blind_render_v1(
    p_review_assignment_id UUID,
    p_blind_packet_id UUID,
    p_presentation_id UUID,
    p_acknowledgement_token UUID,
    p_acquisition_principal_id UUID,
    p_reviewer_principal_id UUID,
    p_render_instance_id UUID,
    p_client_rendered_at TIMESTAMPTZ,
    p_client_version TEXT,
    p_visible_payload_sha256 TEXT,
    p_idempotency_key TEXT
) RETURNS public.ml_rendered_exposures
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE result public.ml_rendered_exposures;
BEGIN
    PERFORM public.require_coach_guidance_assignment_live_v1(
        p_review_assignment_id, p_acquisition_principal_id, 'coach_review'
    );
    IF NOT EXISTS (
        SELECT 1 FROM public.exercise_blind_packets packet
          JOIN public.ml_presentations presentation
            ON presentation.id = p_presentation_id
           AND presentation.review_assignment_id = packet.review_assignment_id
           AND presentation.actor_principal_id = p_reviewer_principal_id
         WHERE packet.id = p_blind_packet_id
           AND packet.review_assignment_id = p_review_assignment_id
           AND packet.reviewer_principal_id = p_reviewer_principal_id
           AND presentation.visible_payload_sha256 = p_visible_payload_sha256
    ) THEN RAISE EXCEPTION 'COACH_INLINE_BLIND_RENDER_IDENTITY_INVALID'; END IF;
    SELECT * INTO STRICT result FROM public.ack_mlc2_rendered_exposure_v1(
        p_presentation_id, p_acknowledgement_token,
        p_reviewer_principal_id, p_render_instance_id,
        p_client_rendered_at, p_client_version,
        p_visible_payload_sha256, p_idempotency_key
    );
    PERFORM public.require_coach_guidance_assignment_live_v1(
        p_review_assignment_id, p_acquisition_principal_id, 'coach_review'
    );
    RETURN result;
END;
$$;

-- The released MLC-2 writer predates D5's exact browser retry contract.  D5
-- replaces it in place so an exact lost-ack retry remains safe even after a
-- reveal, while a new or changed answer can never pass as a replay.  The two
-- advisory identities are acquired in numeric order to prevent cross-key
-- deadlocks and to serialize both same-assignment and same-key races.
CREATE OR REPLACE FUNCTION public.submit_mlc2_confidence_blind_judgment_v1(
    p_review_assignment_id UUID,
    p_reviewer_principal_id UUID,
    p_exposure_id UUID,
    p_decision TEXT,
    p_decided_at TIMESTAMPTZ,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
VOLATILE
SET search_path = public
AS $$
DECLARE
    assignment public.ml_review_assignments%ROWTYPE;
    exposure public.ml_rendered_exposures%ROWTYPE;
    judgment public.ml_judgments%ROWTYPE;
    assignment_judgment public.ml_judgments%ROWTYPE;
    assignment_lock BIGINT;
    idempotency_lock BIGINT;
    provenance TEXT;
BEGIN
    IF p_decision NOT IN (
        'rating_yes', 'rating_in_between', 'rating_no',
        'rating_not_sure', 'rating_audio_unclear'
    ) OR p_decided_at IS NULL
      OR NULLIF(btrim(p_idempotency_key), '') IS NULL THEN
        RAISE EXCEPTION 'invalid blind confidence judgment';
    END IF;

    assignment_lock := hashtextextended(
        'mlc2-blind-judgment-assignment:' || p_review_assignment_id::TEXT, 0
    );
    idempotency_lock := hashtextextended(
        'mlc2-blind-judgment-idempotency:' || p_idempotency_key, 0
    );
    PERFORM pg_advisory_xact_lock(LEAST(assignment_lock, idempotency_lock));
    IF assignment_lock <> idempotency_lock THEN
        PERFORM pg_advisory_xact_lock(
            GREATEST(assignment_lock, idempotency_lock)
        );
    END IF;

    SELECT * INTO assignment
      FROM public.ml_review_assignments row
     WHERE row.id = p_review_assignment_id
       AND row.learning_surface_id = 'confidence_classification'
       AND row.reviewer_principal_id = p_reviewer_principal_id
     FOR SHARE;
    IF assignment.id IS NULL THEN
        RAISE EXCEPTION 'blind judgment assignment rejected';
    END IF;
    provenance := CASE assignment.reviewer_role
        WHEN 'coach' THEN 'blind_coach' ELSE 'blind_peer' END;

    SELECT rendered.* INTO exposure
      FROM public.ml_rendered_exposures rendered
      JOIN public.ml_presentations presentation
        ON presentation.id = rendered.presentation_id
     WHERE rendered.id = p_exposure_id
       AND rendered.actor_principal_id = p_reviewer_principal_id
       AND presentation.review_assignment_id = assignment.id;
    IF exposure.id IS NULL THEN
        RAISE EXCEPTION
            'blind judgment requires authenticated rendered exposure';
    END IF;

    -- Check the exact retry before the reveal state.  This is the only path
    -- allowed after reveal and handles a committed write whose HTTP ACK was
    -- lost.  The immutable artifact identity must match in full.
    SELECT * INTO judgment
      FROM public.ml_judgments row
     WHERE row.idempotency_key = p_idempotency_key;
    IF judgment.id IS NOT NULL THEN
        IF judgment.learning_surface_id <> 'confidence_classification'
          OR judgment.feedback_family_id <> 'confident_voice'
          OR judgment.evidence_span_id <> assignment.evidence_span_id
          OR judgment.review_assignment_id <> assignment.id
          OR judgment.actor_principal_id <> p_reviewer_principal_id
          OR judgment.actor_provenance <> provenance
          OR judgment.exposure_id <> exposure.id
          OR judgment.decision <> p_decision THEN
            RAISE EXCEPTION 'blind judgment idempotency conflict';
        END IF;
        RETURN jsonb_build_object(
            'judgment_id', judgment.id,
            'review_assignment_id', assignment.id,
            'decision', judgment.decision,
            'replayed', true
        );
    END IF;

    -- One immutable judgment represents one review act.  A second key cannot
    -- create a second answer or revise the first one implicitly.
    SELECT * INTO assignment_judgment
      FROM public.ml_judgments row
     WHERE row.review_assignment_id = assignment.id
       AND row.actor_principal_id = p_reviewer_principal_id
       AND row.actor_provenance = provenance
       AND NOT EXISTS (
           SELECT 1 FROM public.ml_judgments later
            WHERE later.supersedes_id = row.id
       )
     ORDER BY row.decided_at DESC, row.id DESC
     LIMIT 1;
    IF assignment_judgment.id IS NOT NULL THEN
        RAISE EXCEPTION 'blind judgment idempotency conflict';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.ml_review_assignment_events event
         WHERE event.review_assignment_id = assignment.id
           AND event.event_kind = 'revealed'
    ) THEN
        RAISE EXCEPTION 'blind judgment assignment rejected';
    END IF;

    INSERT INTO public.ml_judgments (
        learning_surface_id, feedback_family_id, evidence_span_id,
        exposure_id, review_assignment_id, actor_principal_id,
        actor_provenance, decision, training_eligibility,
        idempotency_key, decided_at
    ) VALUES (
        'confidence_classification', 'confident_voice',
        assignment.evidence_span_id, exposure.id, assignment.id,
        p_reviewer_principal_id, provenance, p_decision,
        'potentially_eligible', p_idempotency_key, p_decided_at
    ) RETURNING * INTO judgment;
    INSERT INTO public.ml_review_assignment_events (
        review_assignment_id, event_kind, actor_principal_id,
        idempotency_key
    ) VALUES (
        assignment.id, 'submitted', p_reviewer_principal_id,
        p_idempotency_key || ':submitted'
    );
    RETURN jsonb_build_object(
        'judgment_id', judgment.id,
        'review_assignment_id', assignment.id,
        'decision', judgment.decision,
        'replayed', false
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.submit_coach_inline_blind_judgment_v1(
    p_review_assignment_id UUID,
    p_blind_packet_id UUID,
    p_acquisition_principal_id UUID,
    p_reviewer_principal_id UUID,
    p_exposure_id UUID,
    p_decision TEXT,
    p_decided_at TIMESTAMPTZ,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE result JSONB; judgment_id UUID; existing_event public.exercise_blind_packet_events;
BEGIN
    PERFORM public.require_coach_guidance_assignment_live_v1(
        p_review_assignment_id, p_acquisition_principal_id, 'coach_review'
    );
    IF NOT EXISTS (SELECT 1 FROM public.exercise_blind_packets packet
        WHERE packet.id = p_blind_packet_id
          AND packet.review_assignment_id = p_review_assignment_id
          AND packet.reviewer_principal_id = p_reviewer_principal_id)
    THEN RAISE EXCEPTION 'COACH_INLINE_BLIND_JUDGMENT_IDENTITY_INVALID'; END IF;
    result := public.submit_mlc2_confidence_blind_judgment_v1(
        p_review_assignment_id, p_reviewer_principal_id, p_exposure_id,
        p_decision, p_decided_at, p_idempotency_key
    );
    judgment_id := (result->>'judgment_id')::UUID;
    INSERT INTO public.exercise_blind_packet_events (
        blind_packet_id, review_assignment_id, event_kind,
        actor_principal_id, judgment_id, blindness_policy_version,
        idempotency_key, occurred_at
    ) VALUES (
        p_blind_packet_id, p_review_assignment_id,
        'blind_judgment_submitted', p_reviewer_principal_id, judgment_id,
        'coach-inline-complete-batch-v1',
        p_idempotency_key || ':packet-submitted', p_decided_at
    ) ON CONFLICT (blind_packet_id, event_kind) DO NOTHING;
    SELECT * INTO STRICT existing_event
      FROM public.exercise_blind_packet_events event
     WHERE event.blind_packet_id = p_blind_packet_id
       AND event.event_kind = 'blind_judgment_submitted';
    IF existing_event.review_assignment_id <> p_review_assignment_id
       OR existing_event.actor_principal_id <> p_reviewer_principal_id
       OR existing_event.judgment_id <> judgment_id THEN
        RAISE EXCEPTION 'COACH_INLINE_BLIND_JUDGMENT_REPLAY_CONFLICT';
    END IF;
    PERFORM public.require_coach_guidance_assignment_live_v1(
        p_review_assignment_id, p_acquisition_principal_id, 'coach_review'
    );
    RETURN result || jsonb_build_object('blind_packet_id', p_blind_packet_id);
END;
$$;

CREATE OR REPLACE FUNCTION public.prepare_coach_inline_guidance_context_v1(
    p_project_id UUID,
    p_acquisition_principal_id UUID,
    p_reviewer_principal_id UUID,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    assignment_inventory JSONB;
    inventory_sha256 TEXT;
    batch public.coach_guidance_review_batches;
    grant_row public.coach_guidance_reveal_grants;
    frame public.coach_guidance_review_frames;
    item RECORD;
    access_row public.coach_guidance_reveal_accesses;
    response_binding public.feedback_v3_service_response_bindings;
    items JSONB := '[]'::JSONB;
    role_hash TEXT;
    produced_item_count INTEGER := 0;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'COACH_INLINE_REQUIRES_READ_COMMITTED';
    END IF;
    IF COALESCE(btrim(p_idempotency_key), '') = '' THEN
        RAISE EXCEPTION 'COACH_INLINE_CONTEXT_KEY_REQUIRED';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.projects project
         WHERE project.id = p_project_id
           AND project.owner_principal_id = p_acquisition_principal_id
    ) THEN
        RAISE EXCEPTION 'COACH_INLINE_PROJECT_PRINCIPAL_MISMATCH';
    END IF;
    PERFORM public.require_coach_guidance_reviewer_access_v1(
        p_reviewer_principal_id
    );
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
        'assignment_id', assignment.id,
        'packet_sha256', assignment.blind_packet_sha256,
        'assigned_at', assignment.assigned_at,
        'expires_at', assignment.expires_at,
        'terminal', COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                'kind', event.event_kind, 'at', event.occurred_at
            ) ORDER BY event.occurred_at, event.id)
              FROM public.ml_review_assignment_events event
             WHERE event.review_assignment_id = assignment.id
               AND event.event_kind IN ('cancelled', 'expired')
        ), '[]'::JSONB)
    ) ORDER BY assignment.assigned_at, assignment.id), '[]'::JSONB)
      INTO assignment_inventory
      FROM public.ml_review_assignments assignment
      JOIN public.exercise_blind_packets packet
        ON packet.review_assignment_id = assignment.id
      JOIN public.exercise_audio_lineages lineage
        ON lineage.id = packet.audio_lineage_id
       AND lineage.acquisition_principal_id = p_acquisition_principal_id
       AND lineage.project_id = p_project_id
     WHERE assignment.reviewer_principal_id = p_reviewer_principal_id
       AND assignment.reviewer_role = 'coach'
       AND assignment.learning_surface_id = 'confidence_classification';
    IF jsonb_array_length(assignment_inventory) = 0 THEN
        RAISE EXCEPTION 'COACH_INLINE_BATCH_HAS_NO_ASSIGNMENTS';
    END IF;
    inventory_sha256 := public.exercise_json_sha256_v1(assignment_inventory);
    batch := public.freeze_synthetic_coach_guidance_batch_v1(
        p_acquisition_principal_id, p_project_id, p_reviewer_principal_id,
        p_idempotency_key || ':batch:' || inventory_sha256
    );
    grant_row := public.complete_synthetic_coach_guidance_batch_v1(
        batch.id, p_reviewer_principal_id,
        p_idempotency_key || ':reveal:' || batch.id::TEXT
    );
    SELECT * INTO STRICT frame FROM public.coach_guidance_review_frames
     WHERE id = batch.frame_id;
    FOR item IN
        SELECT frame_item.review_assignment_id, packet.id AS blind_packet_id,
               lineage.id AS audio_lineage_id, lineage.snippet_id,
               packet.asr_transcript AS frozen_transcript,
               packet.asr_transcript_sha256 AS frozen_transcript_sha256,
               offer.id AS offer_id, offer.outcome AS offer_outcome,
               offer.feedback_membership_id, offer.feedback_candidate_id,
               offer.feedback_response_binding_id,
               offer.authorization_check_id,
               candidate_set.need_contract_id,
               source_result.source_pattern,
               source_result.source_pattern_policy_version,
               source_result.ordinal_policy_version,
               source_result.result_sha256,
               observation.features AS source_features,
               observation.detector_version,
               observation.feature_schema_version,
               observation.extractor_version
          FROM public.coach_guidance_review_frame_items frame_item
          JOIN public.exercise_blind_packets packet
            ON packet.id = frame_item.blind_packet_id
           AND packet.review_assignment_id =
               frame_item.review_assignment_id
          JOIN public.exercise_audio_lineages lineage
            ON lineage.id = packet.audio_lineage_id
           AND lineage.acquisition_principal_id =
               p_acquisition_principal_id
           AND lineage.project_id = p_project_id
          JOIN public.snippets snippet
            ON snippet.id = lineage.snippet_id
           AND snippet.session_id = lineage.take_id
           AND snippet.recording_id = lineage.recording_id
           AND snippet.start_offset_ms = lineage.start_offset_ms
           AND snippet.duration_ms = lineage.duration_ms
          LEFT JOIN LATERAL (
              SELECT candidate_offer.*
                FROM public.exercise_service_offers candidate_offer
               WHERE candidate_offer.source_audio_lineage_id = lineage.id
                 AND candidate_offer.acquisition_principal_id =
                     p_acquisition_principal_id
                 AND candidate_offer.project_id = p_project_id
                 AND candidate_offer.operation_mode = 'allowlisted_service'
                 AND candidate_offer.serves_user
                 AND NOT candidate_offer.dataset_eligible
               ORDER BY candidate_offer.prepared_at DESC,
                        candidate_offer.id DESC
               LIMIT 1
          ) offer ON true
          LEFT JOIN public.feedback_v3_membership_items feedback_item
            ON feedback_item.membership_id =
               offer.feedback_membership_id
           AND feedback_item.candidate_id =
               offer.feedback_candidate_id
           AND feedback_item.snippet_id = lineage.snippet_id
           AND feedback_item.feedback_family = 'confident_voice'
           AND feedback_item.selected
           AND feedback_item.eligibility = 'eligible'
          LEFT JOIN public.exercise_n1_pattern_snapshots pattern_snapshot
            ON pattern_snapshot.candidate_set_id =
               offer.n1_candidate_set_id
           AND pattern_snapshot.acquisition_principal_id =
               p_acquisition_principal_id
          LEFT JOIN public.exercise_candidate_sets candidate_set
            ON candidate_set.id = pattern_snapshot.candidate_set_id
           AND candidate_set.acquisition_principal_id =
               p_acquisition_principal_id
          LEFT JOIN public.exercise_n1_source_pattern_results source_result
            ON source_result.id =
               pattern_snapshot.source_pattern_result_id
           AND source_result.acquisition_principal_id =
               p_acquisition_principal_id
           AND source_result.audio_lineage_id = lineage.id
          LEFT JOIN public.learning_profile_observations observation
            ON observation.id = source_result.source_observation_id
           AND observation.audio_lineage_id = lineage.id
           AND observation.acquisition_principal_id =
               p_acquisition_principal_id
         WHERE frame_item.frame_id = frame.id
           AND frame_item.membership_state = 'required'
           AND (
               (packet.asr_transcript IS NULL
                AND packet.asr_transcript_sha256 IS NULL)
               OR (
                   packet.asr_transcript IS NOT NULL
                   AND packet.asr_transcript_sha256 = encode(
                       extensions.digest(
                           convert_to(packet.asr_transcript, 'UTF8'), 'sha256'
                       ), 'hex'
                   )
                   AND packet.visible_payload #>> '{asr_transcript,text}' =
                       packet.asr_transcript
               )
           )
         ORDER BY frame_item.canonical_position
    LOOP
        IF item.offer_id IS NOT NULL THEN
            response_binding :=
                public.require_feedback_v3_service_response_v1(
                    item.feedback_response_binding_id,
                    p_acquisition_principal_id,
                    item.feedback_membership_id,
                    item.feedback_candidate_id,
                    (SELECT binding.feedback_exposure_id
                       FROM public.feedback_v3_service_response_bindings binding
                      WHERE binding.id = item.feedback_response_binding_id)
                );
        ELSE
            response_binding := NULL;
        END IF;
        access_row := public.record_synthetic_guidance_reveal_access_v1(
            grant_row.id, p_reviewer_principal_id,
            item.review_assignment_id, 'guidance_authoring',
            p_idempotency_key || ':access:' ||
                item.review_assignment_id::TEXT
        );
        role_hash := public.exercise_json_sha256_v1(jsonb_build_object(
            'review_batch_id', batch.id,
            'acquisition_principal_id', p_acquisition_principal_id,
            'reviewer_principal_id', p_reviewer_principal_id,
            'review_assignment_id', item.review_assignment_id,
            'blind_packet_id', item.blind_packet_id,
            'audio_lineage_id', item.audio_lineage_id,
            'evidence_role', 'source_before_exercise'
        ));
        INSERT INTO public.coach_inline_source_roles (
            review_batch_id, acquisition_principal_id,
            reviewer_principal_id, review_assignment_id,
            blind_packet_id, audio_lineage_id, evidence_role, role_sha256
        ) VALUES (
            batch.id, p_acquisition_principal_id,
            p_reviewer_principal_id, item.review_assignment_id,
            item.blind_packet_id, item.audio_lineage_id,
            'source_before_exercise', role_hash
        ) ON CONFLICT (review_batch_id, review_assignment_id) DO NOTHING;
        IF NOT EXISTS (
            SELECT 1 FROM public.coach_inline_source_roles role_row
             WHERE role_row.review_batch_id = batch.id
               AND role_row.review_assignment_id =
                   item.review_assignment_id
               AND role_row.blind_packet_id = item.blind_packet_id
               AND role_row.audio_lineage_id = item.audio_lineage_id
               AND role_row.role_sha256 = role_hash
        ) THEN
            RAISE EXCEPTION 'COACH_INLINE_SOURCE_ROLE_REPLAY_CONFLICT';
        END IF;
        items := items || jsonb_build_array(jsonb_build_object(
            'review_batch_id', batch.id,
            'reveal_grant_id', grant_row.id,
            'reveal_access_id', access_row.id,
            'review_assignment_id', item.review_assignment_id,
            'feedback_membership_id', item.feedback_membership_id,
            'feedback_candidate_id', item.feedback_candidate_id,
            'snippet_id', item.snippet_id,
            'feedback_family', 'confident_voice',
            'transcript', item.frozen_transcript,
            'transcript_sha256', item.frozen_transcript_sha256,
            'features', jsonb_build_object(
                'raw_measurements', item.source_features,
                'safeguards', '{}'::JSONB,
                'detector_version', item.detector_version,
                'feature_schema_version', item.feature_schema_version,
                'extractor_version', item.extractor_version
            ),
            'exercise_eligible',
                COALESCE(item.offer_outcome = 'coach_exercise_requested', false),
            'exercise_offer_id', item.offer_id,
            'exercise_version_id', NULL,
            'need_contract_id', item.need_contract_id,
            'authorization_snapshot_id', (
                SELECT check_row.authorization_snapshot_id
                  FROM public.exercise_authorization_checks check_row
                 WHERE check_row.id = item.authorization_check_id
                   AND check_row.acquisition_principal_id =
                       p_acquisition_principal_id
            ),
            'source_role', 'source_before_exercise',
            'source_pattern', item.source_pattern,
            'source_pattern_policy_version',
                item.source_pattern_policy_version,
            'ordinal_policy_version', item.ordinal_policy_version,
            'source_pattern_result_sha256', item.result_sha256
        ));
        produced_item_count := produced_item_count + 1;
    END LOOP;
    IF produced_item_count <> frame.eligible_assignment_count THEN
        RAISE EXCEPTION 'COACH_INLINE_FROZEN_PACKET_INVENTORY_MISMATCH';
    END IF;
    RETURN jsonb_build_object(
        'review_batch_id', batch.id,
        'reveal_grant_id', grant_row.id,
        'batch_complete', true,
        'items', items,
        'operation_mode', 'synthetic_dark',
        'synthetic_only', true,
        'serves_user', false,
        'dataset_eligible', false
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.create_coach_inline_exercise_draft_v1(
    p_attachment_version_id UUID,
    p_reviewer_principal_id UUID,
    p_title TEXT,
    p_instruction_text TEXT,
    p_language_code TEXT,
    p_supported_confidence_patterns TEXT[],
    p_idempotency_key TEXT
) RETURNS public.coach_inline_exercise_drafts
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    version_row public.coach_guidance_attachment_versions;
    attachment public.coach_guidance_attachments;
    offer public.exercise_service_offers;
    binding public.coach_guidance_media_bindings;
    result public.coach_inline_exercise_drafts;
    draft_hash TEXT;
    normalized_patterns TEXT[];
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'COACH_INLINE_REQUIRES_READ_COMMITTED';
    END IF;
    IF length(btrim(COALESCE(p_title, ''))) NOT BETWEEN 1 AND 120
       OR length(btrim(COALESCE(p_instruction_text, '')))
          NOT BETWEEN 1 AND 2000
       OR p_language_code !~ '^[a-z]{2}(-[A-Z]{2})?$'
       OR p_supported_confidence_patterns IS NULL
       OR cardinality(p_supported_confidence_patterns) = 0
       OR NOT p_supported_confidence_patterns <@ ARRAY[
            'low_confidence_rushing_dominant',
            'near_confident',
            'confident'
       ]::TEXT[]
       OR COALESCE(btrim(p_idempotency_key), '') = ''
    THEN
        RAISE EXCEPTION 'COACH_INLINE_DRAFT_INVALID';
    END IF;
    SELECT array_agg(pattern ORDER BY pattern)
      INTO normalized_patterns
      FROM (
          SELECT DISTINCT unnest(p_supported_confidence_patterns) AS pattern
      ) normalized;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'coach-inline-draft:' || p_idempotency_key, 0
    ));
    SELECT * INTO STRICT version_row
      FROM public.coach_guidance_attachment_versions
     WHERE id = p_attachment_version_id
       AND NOT serves_user AND NOT dataset_eligible;
    SELECT * INTO STRICT attachment
      FROM public.coach_guidance_attachments
     WHERE id = version_row.attachment_id
       AND author_principal_id = p_reviewer_principal_id
       AND attachment_class = 'mlc3_exercise'
       AND NOT serves_user AND NOT dataset_eligible;
    SELECT * INTO STRICT offer FROM public.exercise_service_offers
     WHERE id = attachment.exercise_offer_id
       AND acquisition_principal_id =
           attachment.acquisition_principal_id
       AND outcome = 'coach_exercise_requested'
       AND selected_exercise_version_id IS NULL
       AND operation_mode = 'allowlisted_service';
    IF version_row.media_binding_id IS NULL THEN
        RAISE EXCEPTION 'COACH_INLINE_DRAFT_VIDEO_REQUIRED';
    END IF;
    SELECT * INTO STRICT binding FROM public.coach_guidance_media_bindings
     WHERE id = version_row.media_binding_id
       AND acquisition_principal_id =
           attachment.acquisition_principal_id
       AND provenance_class = 'user_source_dependent'
       AND source_acquisition_principal_id =
           attachment.acquisition_principal_id;
    PERFORM public.require_coach_guidance_assignment_live_v1(
        attachment.review_assignment_id,
        attachment.acquisition_principal_id,
        'personalized_exercise_recommendation'
    );
    PERFORM public.require_coach_guidance_media_live_v1(
        binding.id, attachment.acquisition_principal_id
    );
    IF NOT EXISTS (
        SELECT 1 FROM public.coach_inline_source_roles source_role
         WHERE source_role.review_batch_id = attachment.review_batch_id
           AND source_role.review_assignment_id =
               attachment.review_assignment_id
           AND source_role.acquisition_principal_id =
               attachment.acquisition_principal_id
           AND source_role.reviewer_principal_id =
               p_reviewer_principal_id
           AND source_role.evidence_role = 'source_before_exercise'
    ) THEN
        RAISE EXCEPTION 'COACH_INLINE_SOURCE_ROLE_REQUIRED';
    END IF;
    draft_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'attachment_version_id', version_row.id,
        'version_sha256', version_row.version_sha256,
        'acquisition_principal_id', attachment.acquisition_principal_id,
        'author_principal_id', p_reviewer_principal_id,
        'review_batch_id', attachment.review_batch_id,
        'review_assignment_id', attachment.review_assignment_id,
        'exercise_offer_id', offer.id,
        'need_contract_id', attachment.need_contract_id,
        'source_role', 'source_before_exercise',
        'provenance_class', 'user_source_dependent',
        'title', btrim(p_title),
        'instruction_text', btrim(p_instruction_text),
        'language_code', p_language_code,
        'supported_confidence_patterns', normalized_patterns,
        'contract_version', 'coach-inline-exercise-authoring-d5'
    ));
    SELECT * INTO result FROM public.coach_inline_exercise_drafts
     WHERE idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.draft_sha256 <> draft_hash THEN
            RAISE EXCEPTION 'COACH_INLINE_DRAFT_REPLAY_CONFLICT';
        END IF;
        RETURN result;
    END IF;
    INSERT INTO public.coach_inline_exercise_drafts (
        attachment_version_id, acquisition_principal_id,
        author_principal_id, review_batch_id, review_assignment_id,
        exercise_offer_id, need_contract_id, source_role,
        provenance_class, title, instruction_text, language_code,
        supported_confidence_patterns, contract_version,
        draft_sha256, idempotency_key
    ) VALUES (
        version_row.id, attachment.acquisition_principal_id,
        p_reviewer_principal_id, attachment.review_batch_id,
        attachment.review_assignment_id, offer.id,
        attachment.need_contract_id, 'source_before_exercise',
        'user_source_dependent', btrim(p_title),
        btrim(p_instruction_text), p_language_code,
        normalized_patterns,
        'coach-inline-exercise-authoring-d5',
        draft_hash, p_idempotency_key
    ) RETURNING * INTO result;
    RETURN result;
END;
$$;

-- Exchange one opaque canonical coach-assignment ID for the exact source clip.
-- The browser never receives the object key or clip coordinates.  The route
-- calls this RPC before and after the R2 read, so a concurrent authority or
-- deletion change fails closed before bytes are returned.
CREATE OR REPLACE FUNCTION public.resolve_coach_inline_blind_audio_read_v1(
    p_evidence_review_assignment_id UUID,
    p_reviewer_user_id UUID,
    p_reviewer_principal_id UUID
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    assignment public.ml_review_assignments%ROWTYPE;
    packet public.exercise_blind_packets%ROWTYPE;
    lineage public.exercise_audio_lineages%ROWTYPE;
    object_row public.processing_audio_objects%ROWTYPE;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'COACH_INLINE_REQUIRES_READ_COMMITTED';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.owner_principals principal
         WHERE principal.id = p_reviewer_principal_id
           AND principal.user_id = p_reviewer_user_id
    ) THEN
        RAISE EXCEPTION 'COACH_INLINE_REVIEWER_IDENTITY_INVALID';
    END IF;
    PERFORM public.require_coach_guidance_reviewer_access_v1(
        p_reviewer_principal_id
    );
    SELECT * INTO STRICT assignment
      FROM public.ml_review_assignments row
     WHERE row.id = p_evidence_review_assignment_id
       AND row.reviewer_role = 'coach'
       AND row.reviewer_principal_id = p_reviewer_principal_id
       AND row.learning_surface_id = 'confidence_classification';
    SELECT * INTO STRICT packet FROM public.exercise_blind_packets row
     WHERE row.review_assignment_id = assignment.id
       AND row.reviewer_principal_id = p_reviewer_principal_id
       AND row.playback_expires_at > clock_timestamp();
    SELECT * INTO STRICT lineage FROM public.exercise_audio_lineages row
     WHERE row.id = packet.audio_lineage_id;
    PERFORM public.require_coach_guidance_assignment_live_v1(
        assignment.id, lineage.acquisition_principal_id, 'coach_review'
    );
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-processing-audio-object:' ||
        lineage.processing_audio_object_id::TEXT, 0
    ));
    -- Repeat every mutable/live lookup after the potentially blocking lock.
    SELECT * INTO STRICT assignment
      FROM public.ml_review_assignments row
     WHERE row.id = p_evidence_review_assignment_id
       AND row.reviewer_role = 'coach'
       AND row.reviewer_principal_id = p_reviewer_principal_id
       AND row.learning_surface_id = 'confidence_classification';
    SELECT * INTO STRICT packet FROM public.exercise_blind_packets row
     WHERE row.review_assignment_id = assignment.id
       AND row.reviewer_principal_id = p_reviewer_principal_id
       AND row.playback_expires_at > clock_timestamp();
    SELECT * INTO STRICT lineage FROM public.exercise_audio_lineages row
     WHERE row.id = packet.audio_lineage_id;
    PERFORM public.require_coach_guidance_assignment_live_v1(
        assignment.id, lineage.acquisition_principal_id, 'coach_review'
    );
    SELECT * INTO STRICT object_row
      FROM public.processing_audio_objects row
     WHERE row.id = lineage.processing_audio_object_id
       AND row.acquisition_principal_id = lineage.acquisition_principal_id
       AND row.recording_attempt_id = lineage.recording_attempt_id
       AND row.exact_bytes_sha256 = lineage.exact_audio_sha256
       AND row.byte_size = lineage.object_byte_size
       AND row.storage_provider = 'r2'
       AND row.deleted_at IS NULL;
    IF EXISTS (
        SELECT 1 FROM public.processing_audio_object_deletion_events event
         WHERE event.audio_object_id = object_row.id
    ) OR EXISTS (
        SELECT 1 FROM public.data_purge_requests purge
         WHERE purge.acquisition_principal_id =
               lineage.acquisition_principal_id
           AND purge.state <> 'done'
    ) THEN
        RAISE EXCEPTION 'COACH_INLINE_BLIND_AUDIO_NOT_LIVE';
    END IF;
    RETURN jsonb_build_object(
        'assignment_id', assignment.id,
        'blind_packet_id', packet.id,
        'bucket', object_row.bucket,
        'object_key', object_row.object_key,
        'exact_bytes_sha256', object_row.exact_bytes_sha256,
        'byte_size', object_row.byte_size,
        'content_type', object_row.content_type,
        'start_offset_ms', lineage.start_offset_ms,
        'duration_ms', lineage.duration_ms
    );
END;
$$;

-- Private preview only. The caller must invoke this immediately before and
-- immediately after reading R2 bytes; both calls serialize with media
-- invalidation and revalidate current authority. No signed URL escapes this
-- boundary.
CREATE OR REPLACE FUNCTION public.resolve_coach_inline_media_read_v1(
    p_draft_id UUID,
    p_reviewer_principal_id UUID
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    draft public.coach_inline_exercise_drafts%ROWTYPE;
    version_row public.coach_guidance_attachment_versions%ROWTYPE;
    binding public.coach_guidance_media_bindings%ROWTYPE;
    media public.exercise_media_objects%ROWTYPE;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'COACH_INLINE_REQUIRES_READ_COMMITTED';
    END IF;
    PERFORM public.require_coach_guidance_reviewer_access_v1(
        p_reviewer_principal_id
    );
    SELECT * INTO STRICT draft
      FROM public.coach_inline_exercise_drafts
     WHERE id = p_draft_id
       AND author_principal_id = p_reviewer_principal_id
       AND draft_state = 'awaiting_review'
       AND NOT serves_user AND NOT dataset_eligible;
    SELECT * INTO STRICT version_row
      FROM public.coach_guidance_attachment_versions
     WHERE id = draft.attachment_version_id
       AND media_binding_id IS NOT NULL
       AND NOT serves_user AND NOT dataset_eligible;
    SELECT * INTO STRICT binding
      FROM public.coach_guidance_media_bindings
     WHERE id = version_row.media_binding_id
       AND acquisition_principal_id = draft.acquisition_principal_id
       AND provenance_class = 'user_source_dependent';
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'coach-guidance-media-validity:' || binding.media_object_id::TEXT, 0
    ));
    PERFORM public.require_coach_guidance_assignment_live_v1(
        draft.review_assignment_id,
        draft.acquisition_principal_id,
        'personalized_exercise_recommendation'
    );
    PERFORM public.require_coach_guidance_authority_v1(
        binding.authorization_snapshot_id,
        draft.acquisition_principal_id,
        'personalized_exercise_recommendation'
    );
    PERFORM public.require_coach_guidance_media_live_v1(
        binding.id, draft.acquisition_principal_id
    );
    SELECT * INTO STRICT media
      FROM public.exercise_media_objects
     WHERE id = binding.media_object_id
       AND storage_provider = 'r2'
       AND exact_bytes_sha256 ~ '^[0-9a-f]{64}$'
       AND byte_size > 0
       AND content_type LIKE 'video/%';
    RETURN jsonb_build_object(
        'draft_id', draft.id,
        'media_binding_id', binding.id,
        'media_object_id', media.id,
        'bucket', media.bucket,
        'object_key', media.object_key,
        'exact_bytes_sha256', media.exact_bytes_sha256,
        'byte_size', media.byte_size,
        'content_type', media.content_type,
        'serves_user', false,
        'dataset_eligible', false
    );
END;
$$;

-- Ordinary written/video guidance has no exercise-offer identity.  Bind it
-- directly to the exact immutable batch, reveal, assignment, blind packet and
-- source-audio lineage.  This remains product-only and cannot create an
-- exercise draft, practice/outcome row or learning record.
CREATE OR REPLACE FUNCTION public.create_coach_inline_general_guidance_v1(
    p_review_batch_id UUID,
    p_reveal_grant_id UUID,
    p_reveal_access_id UUID,
    p_review_assignment_id UUID,
    p_reviewer_principal_id UUID,
    p_authorization_snapshot_id UUID,
    p_product_subcategory TEXT,
    p_written_note TEXT,
    p_media_binding_id UUID,
    p_language_policy_version TEXT,
    p_safety_policy_version TEXT,
    p_rights_policy_version TEXT,
    p_content_review_version TEXT,
    p_idempotency_key TEXT
) RETURNS public.coach_guidance_attachment_versions
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    batch public.coach_guidance_review_batches;
    grant_row public.coach_guidance_reveal_grants;
    access_row public.coach_guidance_reveal_accesses;
    source_role public.coach_inline_source_roles;
    binding public.coach_guidance_media_bindings;
    attachment public.coach_guidance_attachments;
    result public.coach_guidance_attachment_versions;
    attachment_hash TEXT;
    version_hash TEXT;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'COACH_INLINE_REQUIRES_READ_COMMITTED';
    END IF;
    IF COALESCE(btrim(p_idempotency_key), '') = ''
       OR (p_product_subcategory IS NOT NULL
           AND p_product_subcategory NOT IN ('structure', 'delivery'))
       OR (NULLIF(btrim(COALESCE(p_written_note, '')), '') IS NULL
           AND p_media_binding_id IS NULL)
       OR COALESCE(btrim(p_language_policy_version), '') = ''
       OR COALESCE(btrim(p_safety_policy_version), '') = ''
       OR COALESCE(btrim(p_rights_policy_version), '') = ''
       OR COALESCE(btrim(p_content_review_version), '') = ''
    THEN
        RAISE EXCEPTION 'COACH_INLINE_GENERAL_GUIDANCE_INVALID';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'coach-inline-general-guidance:' || p_idempotency_key, 0
    ));
    SELECT * INTO STRICT batch
      FROM public.coach_guidance_review_batches row
     WHERE row.id = p_review_batch_id
       AND row.reviewer_principal_id = p_reviewer_principal_id;
    SELECT * INTO STRICT grant_row
      FROM public.coach_guidance_reveal_grants row
     WHERE row.id = p_reveal_grant_id
       AND row.review_batch_id = batch.id
       AND row.acquisition_principal_id = batch.acquisition_principal_id
       AND row.reviewer_principal_id = p_reviewer_principal_id;
    SELECT * INTO STRICT access_row
      FROM public.coach_guidance_reveal_accesses row
     WHERE row.id = p_reveal_access_id
       AND row.reveal_grant_id = grant_row.id
       AND row.review_assignment_id = p_review_assignment_id
       AND row.reviewer_principal_id = p_reviewer_principal_id
       AND row.access_purpose = 'guidance_authoring';
    IF NOT EXISTS (
        SELECT 1
          FROM public.coach_guidance_reveal_grant_judgments judgment
          JOIN public.coach_guidance_review_frame_items frame_item
            ON frame_item.frame_id = batch.frame_id
           AND frame_item.review_assignment_id =
               judgment.review_assignment_id
           AND frame_item.blind_packet_id = (
               SELECT role_row.blind_packet_id
                 FROM public.coach_inline_source_roles role_row
                WHERE role_row.review_batch_id = batch.id
                  AND role_row.review_assignment_id =
                      p_review_assignment_id
           )
           AND frame_item.membership_state = 'required'
         WHERE judgment.reveal_grant_id = grant_row.id
           AND judgment.review_assignment_id = p_review_assignment_id
           AND judgment.judgment_id = access_row.blind_judgment_id
    ) THEN
        RAISE EXCEPTION 'COACH_INLINE_GENERAL_REVIEW_IDENTITY_INVALID';
    END IF;
    SELECT role_row.* INTO STRICT source_role
      FROM public.coach_inline_source_roles role_row
      JOIN public.exercise_blind_packets packet
        ON packet.id = role_row.blind_packet_id
       AND packet.review_assignment_id = role_row.review_assignment_id
       AND packet.audio_lineage_id = role_row.audio_lineage_id
      JOIN public.exercise_audio_lineages lineage
        ON lineage.id = packet.audio_lineage_id
       AND lineage.acquisition_principal_id =
           role_row.acquisition_principal_id
      JOIN public.exercise_authorization_checks auth
        ON auth.id = packet.authorization_check_id
       AND auth.acquisition_principal_id =
           role_row.acquisition_principal_id
      JOIN public.processing_authorization_snapshots source_snapshot
        ON source_snapshot.id = auth.authorization_snapshot_id
       AND source_snapshot.acquisition_principal_id =
           role_row.acquisition_principal_id
      JOIN public.processing_authorization_snapshots action_snapshot
        ON action_snapshot.id = p_authorization_snapshot_id
       AND action_snapshot.acquisition_principal_id =
           role_row.acquisition_principal_id
       AND action_snapshot.receipt_id = source_snapshot.receipt_id
       AND action_snapshot.policy_id = source_snapshot.policy_id
       AND action_snapshot.purpose_id = 'coach_review'
       AND action_snapshot.operation_kind =
           'coach_inline_general_guidance'
       AND action_snapshot.source_take_id = lineage.take_id
       AND action_snapshot.source_recording_id = lineage.recording_id
     WHERE role_row.review_batch_id = batch.id
       AND role_row.review_assignment_id = p_review_assignment_id
       AND role_row.acquisition_principal_id =
           batch.acquisition_principal_id
       AND role_row.reviewer_principal_id = p_reviewer_principal_id
       AND role_row.evidence_role = 'source_before_exercise';
    PERFORM public.require_coach_guidance_assignment_live_v1(
        p_review_assignment_id,
        batch.acquisition_principal_id,
        'coach_review'
    );
    PERFORM public.require_coach_guidance_authority_v1(
        p_authorization_snapshot_id,
        batch.acquisition_principal_id,
        'coach_review'
    );
    IF p_media_binding_id IS NOT NULL THEN
        SELECT * INTO STRICT binding
          FROM public.coach_guidance_media_bindings row
         WHERE row.id = p_media_binding_id
           AND row.acquisition_principal_id =
               batch.acquisition_principal_id
           AND row.authorization_snapshot_id =
               p_authorization_snapshot_id
           AND row.purpose_id = 'coach_review'
           AND row.provenance_class = 'user_scoped'
           AND row.source_acquisition_principal_id =
               batch.acquisition_principal_id;
        PERFORM public.require_coach_guidance_media_live_v1(
            binding.id, batch.acquisition_principal_id
        );
        -- Media validation may wait on its validity lock.  Revalidate the
        -- exact review act and current authority after that wait.
        PERFORM public.require_coach_guidance_assignment_live_v1(
            p_review_assignment_id,
            batch.acquisition_principal_id,
            'coach_review'
        );
        PERFORM public.require_coach_guidance_authority_v1(
            p_authorization_snapshot_id,
            batch.acquisition_principal_id,
            'coach_review'
        );
    END IF;
    attachment_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'contract_version', 'coach-inline-general-guidance-d5',
        'review_batch_id', batch.id,
        'reveal_grant_id', grant_row.id,
        'reveal_access_id', access_row.id,
        'blind_judgment_id', access_row.blind_judgment_id,
        'review_assignment_id', p_review_assignment_id,
        'blind_packet_id', source_role.blind_packet_id,
        'audio_lineage_id', source_role.audio_lineage_id,
        'feedback_membership_id', NULL,
        'feedback_candidate_id', NULL,
        'attachment_class', 'general_product_guidance',
        'product_subcategory', p_product_subcategory
    ));
    version_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'attachment_sha256', attachment_hash,
        'written_note', NULLIF(btrim(COALESCE(p_written_note, '')), ''),
        'media_binding_id', p_media_binding_id,
        'language_policy_version', p_language_policy_version,
        'safety_policy_version', p_safety_policy_version,
        'rights_policy_version', p_rights_policy_version,
        'content_review_version', p_content_review_version
    ));
    SELECT version_row.* INTO result
      FROM public.coach_guidance_attachment_versions version_row
      JOIN public.coach_guidance_attachments attachment_row
        ON attachment_row.id = version_row.attachment_id
     WHERE attachment_row.idempotency_key =
           'inline-general:' || p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.version_sha256 <> version_hash THEN
            RAISE EXCEPTION 'COACH_INLINE_GENERAL_REPLAY_CONFLICT';
        END IF;
        IF result.media_binding_id IS NOT NULL THEN
            PERFORM public.require_coach_guidance_media_live_v1(
                result.media_binding_id, batch.acquisition_principal_id
            );
            -- The media-validity lock above may have blocked.  Replay must
            -- recheck the exact assignment and reviewer access after that
            -- wait, just like first creation.
            PERFORM public.require_coach_guidance_assignment_live_v1(
                p_review_assignment_id,
                batch.acquisition_principal_id,
                'coach_review'
            );
            PERFORM public.require_coach_guidance_authority_v1(
                p_authorization_snapshot_id,
                batch.acquisition_principal_id,
                'coach_review'
            );
        END IF;
        RETURN result;
    END IF;
    INSERT INTO public.coach_guidance_attachments (
        acquisition_principal_id, recipient_principal_id,
        author_principal_id, review_batch_id, reveal_grant_id,
        reveal_access_id, blind_judgment_id, review_assignment_id,
        feedback_membership_id, feedback_candidate_id,
        attachment_class, product_subcategory, exercise_offer_id,
        exercise_version_id, need_contract_id,
        authorization_snapshot_id, attachment_sha256, idempotency_key
    ) VALUES (
        batch.acquisition_principal_id,
        batch.acquisition_principal_id,
        p_reviewer_principal_id, batch.id, grant_row.id,
        access_row.id, access_row.blind_judgment_id,
        p_review_assignment_id, NULL, NULL,
        'general_product_guidance', p_product_subcategory,
        NULL, NULL, NULL, p_authorization_snapshot_id,
        attachment_hash, 'inline-general:' || p_idempotency_key
    ) RETURNING * INTO attachment;
    INSERT INTO public.coach_guidance_attachment_versions (
        attachment_id, acquisition_principal_id, version_number,
        written_note, media_binding_id, language_policy_version,
        safety_policy_version, rights_policy_version,
        content_review_version, version_sha256, idempotency_key
    ) VALUES (
        attachment.id, attachment.acquisition_principal_id, 1,
        NULLIF(btrim(COALESCE(p_written_note, '')), ''),
        p_media_binding_id, p_language_policy_version,
        p_safety_policy_version, p_rights_policy_version,
        p_content_review_version, version_hash,
        'inline-general-version:' || p_idempotency_key
    ) RETURNING * INTO result;
    INSERT INTO public.coach_guidance_lifecycle_events (
        attachment_version_id, acquisition_principal_id,
        actor_principal_id, authorization_snapshot_id,
        event_kind, event_payload, event_sha256, idempotency_key
    ) VALUES (
        result.id, attachment.acquisition_principal_id,
        p_reviewer_principal_id, p_authorization_snapshot_id,
        'authored', jsonb_build_object(
            'contract_version', 'coach-inline-general-guidance-d5',
            'review_batch_id', batch.id,
            'review_assignment_id', p_review_assignment_id,
            'blind_packet_id', source_role.blind_packet_id,
            'audio_lineage_id', source_role.audio_lineage_id
        ), public.exercise_json_sha256_v1(jsonb_build_object(
            'attachment_version_id', result.id,
            'event_kind', 'authored',
            'version_sha256', result.version_sha256
        )), 'inline-general-event:' || p_idempotency_key
    );
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.create_coach_inline_exercise_attachment_v1(
    p_reveal_access_id UUID,
    p_reviewer_principal_id UUID,
    p_feedback_membership_id UUID,
    p_feedback_candidate_id UUID,
    p_authorization_snapshot_id UUID,
    p_written_note TEXT,
    p_media_binding_id UUID,
    p_exercise_offer_id UUID,
    p_need_contract_id UUID,
    p_language_policy_version TEXT,
    p_safety_policy_version TEXT,
    p_rights_policy_version TEXT,
    p_content_review_version TEXT,
    p_idempotency_key TEXT
) RETURNS public.coach_guidance_attachment_versions
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    access_row public.coach_guidance_reveal_accesses;
    grant_row public.coach_guidance_reveal_grants;
    offer public.exercise_service_offers;
    binding public.coach_guidance_media_bindings;
    attachment public.coach_guidance_attachments;
    result public.coach_guidance_attachment_versions;
    attachment_hash TEXT;
    version_hash TEXT;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'COACH_INLINE_REQUIRES_READ_COMMITTED';
    END IF;
    IF COALESCE(btrim(p_idempotency_key), '') = ''
       OR COALESCE(btrim(p_language_policy_version), '') = ''
       OR COALESCE(btrim(p_safety_policy_version), '') = ''
       OR COALESCE(btrim(p_rights_policy_version), '') = ''
       OR COALESCE(btrim(p_content_review_version), '') = ''
       OR p_media_binding_id IS NULL
    THEN
        RAISE EXCEPTION 'COACH_INLINE_ATTACHMENT_INVALID';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'coach-inline-attachment:' || p_idempotency_key, 0
    ));
    SELECT * INTO STRICT access_row
      FROM public.coach_guidance_reveal_accesses
     WHERE id = p_reveal_access_id
       AND reviewer_principal_id = p_reviewer_principal_id
       AND access_purpose = 'guidance_authoring';
    SELECT * INTO STRICT grant_row
      FROM public.coach_guidance_reveal_grants
     WHERE id = access_row.reveal_grant_id
       AND acquisition_principal_id = access_row.acquisition_principal_id
       AND reviewer_principal_id = p_reviewer_principal_id;
    IF NOT EXISTS (
        SELECT 1 FROM public.coach_guidance_reveal_grant_judgments item
         WHERE item.reveal_grant_id = grant_row.id
           AND item.review_assignment_id =
               access_row.review_assignment_id
           AND item.judgment_id = access_row.blind_judgment_id
    ) OR NOT EXISTS (
        SELECT 1 FROM public.coach_inline_source_roles source_role
         WHERE source_role.review_batch_id = grant_row.review_batch_id
           AND source_role.review_assignment_id =
               access_row.review_assignment_id
           AND source_role.acquisition_principal_id =
               grant_row.acquisition_principal_id
           AND source_role.reviewer_principal_id =
               p_reviewer_principal_id
           AND source_role.evidence_role = 'source_before_exercise'
    ) THEN
        RAISE EXCEPTION 'COACH_INLINE_REVEAL_LINEAGE_INVALID';
    END IF;
    SELECT * INTO STRICT offer FROM public.exercise_service_offers
     WHERE id = p_exercise_offer_id
       AND acquisition_principal_id =
           grant_row.acquisition_principal_id
       AND feedback_membership_id = p_feedback_membership_id
       AND feedback_candidate_id = p_feedback_candidate_id
       AND outcome = 'coach_exercise_requested'
       AND selected_exercise_version_id IS NULL
       AND operation_mode = 'allowlisted_service'
       AND serves_user AND NOT dataset_eligible;
    IF offer.authorization_check_id IS NULL
       OR NOT EXISTS (
          SELECT 1 FROM public.exercise_authorization_checks check_row
           WHERE check_row.id = offer.authorization_check_id
             AND check_row.acquisition_principal_id =
                 offer.acquisition_principal_id
             AND check_row.authorization_snapshot_id =
                 p_authorization_snapshot_id
       )
       OR NOT EXISTS (
          SELECT 1
            FROM public.feedback_v3_membership_items feedback_item
            JOIN public.feedback_v3_memberships membership
              ON membership.id = feedback_item.membership_id
             AND membership.acquisition_principal_id =
                 feedback_item.acquisition_principal_id
            JOIN public.exercise_blind_packets packet
              ON packet.review_assignment_id =
                 access_row.review_assignment_id
            JOIN public.exercise_audio_lineages lineage
              ON lineage.id = packet.audio_lineage_id
             AND lineage.acquisition_principal_id =
                 membership.acquisition_principal_id
             AND lineage.project_id = membership.project_id
             AND lineage.snippet_id = feedback_item.snippet_id
           WHERE feedback_item.membership_id =
                 p_feedback_membership_id
             AND feedback_item.candidate_id =
                 p_feedback_candidate_id
             AND feedback_item.feedback_family = 'confident_voice'
             AND feedback_item.selected
             AND feedback_item.eligibility = 'eligible'
             AND membership.acquisition_principal_id =
                 grant_row.acquisition_principal_id
             AND membership.project_id = offer.project_id
       )
    THEN
        RAISE EXCEPTION 'COACH_INLINE_FEEDBACK_LINEAGE_INVALID';
    END IF;
    IF offer.n1_candidate_set_id IS NULL OR NOT EXISTS (
        SELECT 1
          FROM public.exercise_n1_pattern_snapshots pattern_snapshot
          JOIN public.exercise_candidate_sets candidate_set
            ON candidate_set.id = pattern_snapshot.candidate_set_id
           AND candidate_set.acquisition_principal_id =
               pattern_snapshot.acquisition_principal_id
          JOIN public.exercise_need_contracts need
            ON need.id = candidate_set.need_contract_id
         WHERE pattern_snapshot.candidate_set_id =
               offer.n1_candidate_set_id
           AND pattern_snapshot.acquisition_principal_id =
               offer.acquisition_principal_id
           AND candidate_set.need_contract_id = p_need_contract_id
           AND need.approval_state = 'approved'
    ) THEN
        RAISE EXCEPTION 'COACH_INLINE_NEED_LINEAGE_INVALID';
    END IF;
    PERFORM public.require_coach_guidance_assignment_live_v1(
        access_row.review_assignment_id,
        grant_row.acquisition_principal_id,
        'personalized_exercise_recommendation'
    );
    PERFORM public.require_coach_guidance_authority_v1(
        p_authorization_snapshot_id,
        grant_row.acquisition_principal_id,
        'personalized_exercise_recommendation'
    );
    SELECT * INTO STRICT binding
      FROM public.coach_guidance_media_bindings
     WHERE id = p_media_binding_id
       AND acquisition_principal_id =
           grant_row.acquisition_principal_id
       AND purpose_id = 'personalized_exercise_recommendation'
       AND provenance_class = 'user_source_dependent'
       AND source_acquisition_principal_id =
           grant_row.acquisition_principal_id
       AND authorization_snapshot_id =
           p_authorization_snapshot_id;
    PERFORM public.require_coach_guidance_media_live_v1(
        binding.id, grant_row.acquisition_principal_id
    );
    attachment_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'review_batch_id', grant_row.review_batch_id,
        'reveal_grant_id', grant_row.id,
        'reveal_access_id', access_row.id,
        'blind_judgment_id', access_row.blind_judgment_id,
        'review_assignment_id', access_row.review_assignment_id,
        'feedback_membership_id', p_feedback_membership_id,
        'feedback_candidate_id', p_feedback_candidate_id,
        'attachment_class', 'mlc3_exercise',
        'exercise_offer_id', offer.id,
        'need_contract_id', p_need_contract_id,
        'source_role', 'source_before_exercise'
    ));
    version_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'attachment_sha256', attachment_hash,
        'written_note', NULLIF(btrim(COALESCE(p_written_note, '')), ''),
        'media_binding_id', binding.id,
        'language_policy_version', p_language_policy_version,
        'safety_policy_version', p_safety_policy_version,
        'rights_policy_version', p_rights_policy_version,
        'content_review_version', p_content_review_version
    ));
    SELECT version_row.* INTO result
      FROM public.coach_guidance_attachment_versions version_row
      JOIN public.coach_guidance_attachments attachment_row
        ON attachment_row.id = version_row.attachment_id
     WHERE attachment_row.idempotency_key =
           'inline-attachment:' || p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.version_sha256 <> version_hash THEN
            RAISE EXCEPTION 'COACH_INLINE_ATTACHMENT_REPLAY_CONFLICT';
        END IF;
        RETURN result;
    END IF;
    INSERT INTO public.coach_guidance_attachments (
        acquisition_principal_id, recipient_principal_id,
        author_principal_id, review_batch_id, reveal_grant_id,
        reveal_access_id, blind_judgment_id, review_assignment_id,
        feedback_membership_id, feedback_candidate_id,
        attachment_class, product_subcategory, exercise_offer_id,
        exercise_version_id, need_contract_id,
        authorization_snapshot_id, attachment_sha256, idempotency_key
    ) VALUES (
        grant_row.acquisition_principal_id,
        grant_row.acquisition_principal_id,
        p_reviewer_principal_id, grant_row.review_batch_id,
        grant_row.id, access_row.id, access_row.blind_judgment_id,
        access_row.review_assignment_id, p_feedback_membership_id,
        p_feedback_candidate_id, 'mlc3_exercise', NULL, offer.id,
        NULL, p_need_contract_id, p_authorization_snapshot_id,
        attachment_hash, 'inline-attachment:' || p_idempotency_key
    ) RETURNING * INTO attachment;
    INSERT INTO public.coach_guidance_attachment_versions (
        attachment_id, acquisition_principal_id, version_number,
        written_note, media_binding_id, language_policy_version,
        safety_policy_version, rights_policy_version,
        content_review_version, version_sha256, idempotency_key
    ) VALUES (
        attachment.id, attachment.acquisition_principal_id, 1,
        NULLIF(btrim(COALESCE(p_written_note, '')), ''), binding.id,
        p_language_policy_version, p_safety_policy_version,
        p_rights_policy_version, p_content_review_version,
        version_hash, 'inline-version:' || p_idempotency_key
    ) RETURNING * INTO result;
    INSERT INTO public.coach_guidance_lifecycle_events (
        attachment_version_id, acquisition_principal_id,
        actor_principal_id, authorization_snapshot_id,
        event_kind, event_payload, event_sha256, idempotency_key
    ) VALUES (
        result.id, attachment.acquisition_principal_id,
        p_reviewer_principal_id, p_authorization_snapshot_id,
        'authored',
        jsonb_build_object(
            'source_role', 'source_before_exercise',
            'review_assignment_id', access_row.review_assignment_id
        ),
        public.exercise_json_sha256_v1(jsonb_build_object(
            'attachment_version_id', result.id,
            'event_kind', 'authored',
            'version_sha256', result.version_sha256
        )),
        'inline-event:authored:' || p_idempotency_key
    );
    RETURN result;
END;
$$;

DROP TRIGGER IF EXISTS coach_inline_source_roles_append_only
    ON public.coach_inline_source_roles;
CREATE TRIGGER coach_inline_source_roles_append_only
BEFORE UPDATE OR DELETE ON public.coach_inline_source_roles
FOR EACH ROW EXECUTE FUNCTION public.reject_coach_inline_mutation_v1();
DROP TRIGGER IF EXISTS coach_inline_exercise_drafts_append_only
    ON public.coach_inline_exercise_drafts;
CREATE TRIGGER coach_inline_exercise_drafts_append_only
BEFORE UPDATE OR DELETE ON public.coach_inline_exercise_drafts
FOR EACH ROW EXECUTE FUNCTION public.reject_coach_inline_mutation_v1();
DROP TRIGGER IF EXISTS coach_inline_context_assessments_append_only
    ON public.coach_inline_context_assessments;
CREATE TRIGGER coach_inline_context_assessments_append_only
BEFORE UPDATE OR DELETE ON public.coach_inline_context_assessments
FOR EACH ROW EXECUTE FUNCTION public.reject_coach_inline_mutation_v1();
DROP TRIGGER IF EXISTS coach_inline_eligibility_reviews_append_only
    ON public.coach_inline_exercise_eligibility_reviews;
CREATE TRIGGER coach_inline_eligibility_reviews_append_only
BEFORE UPDATE OR DELETE ON public.coach_inline_exercise_eligibility_reviews
FOR EACH ROW EXECUTE FUNCTION public.reject_coach_inline_mutation_v1();

ALTER TABLE public.coach_inline_source_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.coach_inline_exercise_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.coach_inline_context_assessments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.coach_inline_exercise_eligibility_reviews
    ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.coach_inline_source_roles FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.coach_inline_exercise_drafts FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.coach_inline_context_assessments FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.coach_inline_exercise_eligibility_reviews
    FROM PUBLIC, anon, authenticated;
GRANT SELECT ON TABLE public.coach_inline_source_roles TO service_role;
GRANT SELECT ON TABLE public.coach_inline_exercise_drafts TO service_role;
GRANT SELECT ON TABLE public.coach_inline_context_assessments TO service_role;
GRANT SELECT ON TABLE public.coach_inline_exercise_eligibility_reviews
    TO service_role;

REVOKE ALL ON FUNCTION public.prepare_coach_inline_guidance_context_v1(
    UUID, UUID, UUID, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.prepare_coach_inline_guidance_context_v1(
    UUID, UUID, UUID, TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.issue_coach_inline_general_authority_v1(
    UUID, UUID, UUID, UUID, UUID, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.issue_coach_inline_general_authority_v1(
    UUID, UUID, UUID, UUID, UUID, TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.prepare_coach_inline_blind_batch_v1(
    UUID, UUID, UUID, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.prepare_coach_inline_blind_batch_v1(
    UUID, UUID, UUID, TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.ack_coach_inline_blind_render_v1(
    UUID, UUID, UUID, UUID, UUID, UUID, UUID, TIMESTAMPTZ, TEXT, TEXT, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ack_coach_inline_blind_render_v1(
    UUID, UUID, UUID, UUID, UUID, UUID, UUID, TIMESTAMPTZ, TEXT, TEXT, TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.submit_mlc2_confidence_blind_judgment_v1(
    UUID, UUID, UUID, TEXT, TIMESTAMPTZ, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.submit_mlc2_confidence_blind_judgment_v1(
    UUID, UUID, UUID, TEXT, TIMESTAMPTZ, TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.submit_coach_inline_blind_judgment_v1(
    UUID, UUID, UUID, UUID, UUID, TEXT, TIMESTAMPTZ, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.submit_coach_inline_blind_judgment_v1(
    UUID, UUID, UUID, UUID, UUID, TEXT, TIMESTAMPTZ, TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.create_coach_inline_exercise_draft_v1(
    UUID, UUID, TEXT, TEXT, TEXT, TEXT[], TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.create_coach_inline_exercise_draft_v1(
    UUID, UUID, TEXT, TEXT, TEXT, TEXT[], TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.create_coach_inline_general_guidance_v1(
    UUID, UUID, UUID, UUID, UUID, UUID, TEXT, TEXT, UUID,
    TEXT, TEXT, TEXT, TEXT, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.create_coach_inline_general_guidance_v1(
    UUID, UUID, UUID, UUID, UUID, UUID, TEXT, TEXT, UUID,
    TEXT, TEXT, TEXT, TEXT, TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.create_coach_inline_exercise_attachment_v1(
    UUID, UUID, UUID, UUID, UUID, TEXT, UUID, UUID, UUID,
    TEXT, TEXT, TEXT, TEXT, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.create_coach_inline_exercise_attachment_v1(
    UUID, UUID, UUID, UUID, UUID, TEXT, UUID, UUID, UUID,
    TEXT, TEXT, TEXT, TEXT, TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.resolve_coach_inline_blind_audio_read_v1(
    UUID, UUID, UUID
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.resolve_coach_inline_blind_audio_read_v1(
    UUID, UUID, UUID
) TO service_role;
REVOKE ALL ON FUNCTION public.resolve_coach_inline_media_read_v1(
    UUID, UUID
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.resolve_coach_inline_media_read_v1(
    UUID, UUID
) TO service_role;

NOTIFY pgrst, 'reload schema';
COMMIT;
