-- 0313 · MLC-3-D2 / M3-2 dark exercise catalogue and lineage foundation.
--
-- Additive and inert.  This migration registers the eighth learning surface
-- and creates immutable catalogue, exact-audio, profile, authorization and
-- blind-review foundations.  It does not seed an exercise, activate the
-- personalized-exercise purpose, enqueue a producer, serve feedback, expose
-- a packet, create a dataset, train/evaluate/promote a model, or delete data.

BEGIN;

-- ── Canonical registry amendment ─────────────────────────────────────────

INSERT INTO public.ml_contract_epochs (
    learning_contract_version, data_epoch, specification_version, created_by
) VALUES (
    'MLC-3', 1, 'MLC-3-D2/M3-2', 'founder_authorized_m3_2'
) ON CONFLICT (learning_contract_version, data_epoch) DO NOTHING;

INSERT INTO public.ml_learning_surfaces (id, description, trainable) VALUES (
    'exercise_adequacy_classification',
    'Predict improvement probability among deterministically eligible exercise versions',
    true
) ON CONFLICT (id) DO NOTHING;

INSERT INTO public.ml_learning_surface_aliases (
    alias, learning_surface_id, canonical_writes_allowed, reason
) VALUES
    ('exercise_match', 'exercise_adequacy_classification', true,
     'Explicit product/runtime alias only'),
    ('practice_recommendation', 'exercise_adequacy_classification', true,
     'Explicit product/runtime alias only'),
    ('diagnostic_exercise', 'exercise_adequacy_classification', true,
     'Legacy product name resolved only through the canonical registry')
ON CONFLICT (alias) DO NOTHING;

-- MLC-3 events have their own typed payload and no feedback-family value.
-- No event producer is added in M3-2.
ALTER TABLE public.ml_canonical_events
    DROP CONSTRAINT IF EXISTS ml_canonical_event_payload_type_check;
ALTER TABLE public.ml_canonical_events
    ADD CONSTRAINT ml_canonical_event_payload_type_check CHECK (
        payload_type = CASE learning_surface_id
            WHEN 'confidence_classification' THEN 'confidence_event'
            WHEN 'correction_generation' THEN 'correction_generation_event'
            WHEN 'coach_comment_generation' THEN 'coach_comment_event'
            WHEN 'praise_generation' THEN 'praise_generation_event'
            WHEN 'praise_selection' THEN 'praise_selection_event'
            WHEN 'correction_selection' THEN 'correction_selection_event'
            WHEN 'ideal_text_generation' THEN 'ideal_text_event'
            WHEN 'exercise_adequacy_classification' THEN 'exercise_adequacy_event'
        END
    );

ALTER TABLE public.ml_canonical_events
    DROP CONSTRAINT IF EXISTS ml_canonical_feedback_family_check;
ALTER TABLE public.ml_canonical_events
    ADD CONSTRAINT ml_canonical_feedback_family_check CHECK (
        (learning_surface_id IN (
            'confidence_classification', 'correction_generation',
            'praise_generation', 'praise_selection', 'correction_selection'
        ) AND feedback_family_id IS NOT NULL)
        OR (learning_surface_id IN (
            'coach_comment_generation', 'ideal_text_generation',
            'exercise_adequacy_classification'
        ) AND feedback_family_id IS NULL)
    );

-- ── Immutable exercise catalogue ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.exercise_need_contracts (
    id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    need_code                  TEXT NOT NULL,
    contract_version           INTEGER NOT NULL CHECK (contract_version > 0),
    approval_state             TEXT NOT NULL CHECK (approval_state IN (
        'draft', 'approved', 'rejected'
    )),
    operational_definition     JSONB NOT NULL CHECK (
        jsonb_typeof(operational_definition) = 'object'
    ),
    allowed_feature_names      TEXT[] NOT NULL CHECK (
        cardinality(allowed_feature_names) > 0
    ),
    required_feature_names     TEXT[] NOT NULL CHECK (
        cardinality(required_feature_names) > 0
        AND required_feature_names <@ allowed_feature_names
    ),
    exclusion_reason_codes     TEXT[] NOT NULL CHECK (
        cardinality(exclusion_reason_codes) > 0
    ),
    contraindications          JSONB NOT NULL CHECK (
        jsonb_typeof(contraindications) = 'array'
    ),
    feature_schema_version     TEXT NOT NULL CHECK (
        length(btrim(feature_schema_version)) > 0
    ),
    ml_data_approval_ref       TEXT NULL,
    approval_evidence_sha256   TEXT NULL CHECK (
        approval_evidence_sha256 IS NULL
        OR approval_evidence_sha256 ~ '^[0-9a-f]{64}$'
    ),
    contract_sha256            TEXT NOT NULL CHECK (
        contract_sha256 ~ '^[0-9a-f]{64}$'
    ),
    created_by                 TEXT NOT NULL,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (need_code, contract_version),
    CONSTRAINT exercise_need_approval_evidence_check CHECK (
        (approval_state = 'approved'
         AND length(btrim(COALESCE(ml_data_approval_ref, ''))) > 0
         AND approval_evidence_sha256 IS NOT NULL)
        OR approval_state <> 'approved'
    )
);

CREATE TABLE IF NOT EXISTS public.exercise_media_objects (
    id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    storage_provider           TEXT NOT NULL CHECK (storage_provider = 'r2'),
    bucket                     TEXT NOT NULL CHECK (length(btrim(bucket)) > 0),
    object_key                 TEXT NOT NULL CHECK (length(btrim(object_key)) > 0),
    exact_bytes_sha256         TEXT NOT NULL CHECK (
        exact_bytes_sha256 ~ '^[0-9a-f]{64}$'
    ),
    byte_size                  BIGINT NOT NULL CHECK (byte_size > 0),
    content_type               TEXT NOT NULL CHECK (
        content_type LIKE 'video/%' OR content_type LIKE 'audio/%'
    ),
    verification_method        TEXT NOT NULL CHECK (verification_method IN (
        'read_after_write_sha256', 'trusted_object_checksum_sha256'
    )),
    verified_at                TIMESTAMPTZ NOT NULL,
    content_authority          TEXT NOT NULL CHECK (
        length(btrim(content_authority)) > 0
    ),
    created_by                 TEXT NOT NULL,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (storage_provider, bucket, object_key)
);

CREATE INDEX IF NOT EXISTS exercise_media_content_hash_idx
    ON public.exercise_media_objects (exact_bytes_sha256);

CREATE TABLE IF NOT EXISTS public.exercise_definitions (
    id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    exercise_key               TEXT NOT NULL UNIQUE CHECK (
        exercise_key ~ '^[a-z0-9][a-z0-9_-]{2,119}$'
    ),
    origin_kind                TEXT NOT NULL CHECK (origin_kind IN (
        'willab_library', 'coach_case_specific'
    )),
    author_principal_id        UUID NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    language_code              TEXT NOT NULL CHECK (
        language_code ~ '^[a-z]{2}(-[A-Z]{2})?$'
    ),
    definition_sha256          TEXT NOT NULL CHECK (
        definition_sha256 ~ '^[0-9a-f]{64}$'
    ),
    created_by                 TEXT NOT NULL,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT exercise_definition_author_check CHECK (
        (origin_kind = 'coach_case_specific' AND author_principal_id IS NOT NULL)
        OR (origin_kind = 'willab_library')
    )
);

CREATE TABLE IF NOT EXISTS public.exercise_versions (
    id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    exercise_definition_id     UUID NOT NULL
        REFERENCES public.exercise_definitions(id) ON DELETE RESTRICT,
    version_number             INTEGER NOT NULL CHECK (version_number > 0),
    need_contract_id           UUID NOT NULL
        REFERENCES public.exercise_need_contracts(id) ON DELETE RESTRICT,
    media_object_id            UUID NOT NULL
        REFERENCES public.exercise_media_objects(id) ON DELETE RESTRICT,
    instruction_text           TEXT NOT NULL CHECK (
        length(btrim(instruction_text)) > 0
    ),
    instruction_sha256         TEXT NOT NULL CHECK (
        instruction_sha256 ~ '^[0-9a-f]{64}$'
    ),
    safety_state               TEXT NOT NULL CHECK (safety_state IN (
        'pending_review', 'approved', 'restricted', 'rejected'
    )),
    catalogue_state            TEXT NOT NULL CHECK (catalogue_state IN (
        'draft', 'active', 'inactive', 'retired'
    )),
    version_sha256             TEXT NOT NULL CHECK (
        version_sha256 ~ '^[0-9a-f]{64}$'
    ),
    created_by                 TEXT NOT NULL,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (exercise_definition_id, version_number),
    CONSTRAINT exercise_active_version_review_check CHECK (
        catalogue_state <> 'active' OR safety_state = 'approved'
    )
);

CREATE INDEX IF NOT EXISTS exercise_versions_need_idx
    ON public.exercise_versions (need_contract_id, created_at);
CREATE INDEX IF NOT EXISTS exercise_versions_catalogue_idx
    ON public.exercise_versions (catalogue_state, safety_state, created_at);

CREATE TABLE IF NOT EXISTS public.exercise_catalog_snapshots (
    id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    catalog_policy_version     TEXT NOT NULL CHECK (
        length(btrim(catalog_policy_version)) > 0
    ),
    scope_language_code        TEXT NULL CHECK (
        scope_language_code IS NULL
        OR scope_language_code ~ '^[a-z]{2}(-[A-Z]{2})?$'
    ),
    version_cutoff_at          TIMESTAMPTZ NOT NULL,
    version_count              INTEGER NOT NULL CHECK (version_count > 0),
    manifest_sha256            TEXT NOT NULL CHECK (
        manifest_sha256 ~ '^[0-9a-f]{64}$'
    ),
    idempotency_key            TEXT NOT NULL UNIQUE,
    finalized_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by                 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS public.exercise_catalog_snapshot_items (
    catalog_snapshot_id        UUID NOT NULL
        REFERENCES public.exercise_catalog_snapshots(id) ON DELETE RESTRICT,
    exercise_version_id        UUID NOT NULL
        REFERENCES public.exercise_versions(id) ON DELETE RESTRICT,
    exercise_key               TEXT NOT NULL,
    version_number             INTEGER NOT NULL CHECK (version_number > 0),
    catalogue_state            TEXT NOT NULL CHECK (catalogue_state IN (
        'draft', 'active', 'inactive', 'retired'
    )),
    safety_state               TEXT NOT NULL CHECK (safety_state IN (
        'pending_review', 'approved', 'restricted', 'rejected'
    )),
    item_sha256                TEXT NOT NULL CHECK (
        item_sha256 ~ '^[0-9a-f]{64}$'
    ),
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (catalog_snapshot_id, exercise_version_id),
    UNIQUE (catalog_snapshot_id, exercise_key, version_number)
);

-- ── Authorization, stable profile identity, and exact audio lineage ─────

CREATE TABLE IF NOT EXISTS public.exercise_authorization_checks (
    id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id   UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    authorization_snapshot_id  UUID NOT NULL
        REFERENCES public.processing_authorization_snapshots(id)
        ON DELETE RESTRICT,
    purpose_id                 TEXT NOT NULL DEFAULT
        'personalized_exercise_recommendation'
        REFERENCES public.processing_purpose_registry(id) ON DELETE RESTRICT,
    operation_kind             TEXT NOT NULL CHECK (operation_kind IN (
        'profile_identity', 'source_audio_lineage', 'catalog_assignment',
        'blind_review_preparation', 'practice_processing'
    )),
    authorized                 BOOLEAN NOT NULL,
    decision_code              TEXT NOT NULL,
    policy_version             TEXT NULL,
    authority_evidence_sha256  TEXT NOT NULL CHECK (
        authority_evidence_sha256 ~ '^[0-9a-f]{64}$'
    ),
    checked_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    idempotency_key            TEXT NOT NULL UNIQUE,
    CONSTRAINT exercise_authorization_purpose_check CHECK (
        purpose_id = 'personalized_exercise_recommendation'
    ),
    CONSTRAINT exercise_authorization_decision_check CHECK (
        (authorized AND decision_code = 'AUTHORIZED')
        OR (NOT authorized AND decision_code <> 'AUTHORIZED')
    )
);

CREATE INDEX IF NOT EXISTS exercise_authorization_principal_time_idx
    ON public.exercise_authorization_checks (
        acquisition_principal_id, checked_at DESC
    );

CREATE TABLE IF NOT EXISTS public.learning_profiles (
    id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    speaker_id                 UUID NOT NULL UNIQUE
        REFERENCES public.ml_speakers(id) ON DELETE RESTRICT,
    origin_acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    origin_authorization_check_id UUID NOT NULL
        REFERENCES public.exercise_authorization_checks(id) ON DELETE RESTRICT,
    profile_schema_version     TEXT NOT NULL CHECK (
        length(btrim(profile_schema_version)) > 0
    ),
    profile_identity_sha256    TEXT NOT NULL CHECK (
        profile_identity_sha256 ~ '^[0-9a-f]{64}$'
    ),
    idempotency_key            TEXT NOT NULL UNIQUE,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT learning_profile_speaker_principal_fk FOREIGN KEY (
        speaker_id, origin_acquisition_principal_id
    ) REFERENCES public.ml_speaker_principals(
        speaker_id, acquisition_principal_id
    ) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS public.exercise_audio_lineages (
    id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id   UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    speaker_id                 UUID NOT NULL
        REFERENCES public.ml_speakers(id) ON DELETE RESTRICT,
    learning_profile_id        UUID NOT NULL
        REFERENCES public.learning_profiles(id) ON DELETE RESTRICT,
    authorization_check_id     UUID NOT NULL
        REFERENCES public.exercise_authorization_checks(id) ON DELETE RESTRICT,
    processing_audio_object_id UUID NOT NULL
        REFERENCES public.processing_audio_objects(id) ON DELETE RESTRICT,
    project_id                 UUID NOT NULL
        REFERENCES public.projects(id) ON DELETE RESTRICT,
    take_id                    UUID NOT NULL
        REFERENCES public.takes(id) ON DELETE RESTRICT,
    recording_attempt_id       UUID NOT NULL
        REFERENCES public.processing_recording_attempts(id) ON DELETE RESTRICT,
    recording_id               UUID NOT NULL,
    snippet_id                 UUID NOT NULL
        REFERENCES public.snippets(id) ON DELETE RESTRICT,
    start_offset_ms            INTEGER NOT NULL CHECK (start_offset_ms >= 0),
    duration_ms                INTEGER NOT NULL CHECK (duration_ms > 0),
    exact_audio_sha256         TEXT NOT NULL CHECK (
        exact_audio_sha256 ~ '^[0-9a-f]{64}$'
    ),
    object_byte_size           BIGINT NOT NULL CHECK (object_byte_size > 0),
    verification_method        TEXT NOT NULL,
    lineage_schema_version     TEXT NOT NULL CHECK (
        length(btrim(lineage_schema_version)) > 0
    ),
    lineage_sha256             TEXT NOT NULL CHECK (
        lineage_sha256 ~ '^[0-9a-f]{64}$'
    ),
    idempotency_key            TEXT NOT NULL UNIQUE,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (snippet_id, start_offset_ms, duration_ms, exact_audio_sha256),
    CONSTRAINT exercise_audio_speaker_principal_fk FOREIGN KEY (
        speaker_id, acquisition_principal_id
    ) REFERENCES public.ml_speaker_principals(
        speaker_id, acquisition_principal_id
    ) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS exercise_audio_lineage_take_idx
    ON public.exercise_audio_lineages (take_id, snippet_id, created_at);
CREATE INDEX IF NOT EXISTS exercise_audio_lineage_object_idx
    ON public.exercise_audio_lineages (processing_audio_object_id, created_at);

-- ── Blind-review foundation (no packet producer or UI in M3-2) ──────────

CREATE TABLE IF NOT EXISTS public.exercise_blind_packets (
    id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    review_assignment_id       UUID NOT NULL UNIQUE
        REFERENCES public.ml_review_assignments(id) ON DELETE RESTRICT,
    audio_lineage_id           UUID NOT NULL
        REFERENCES public.exercise_audio_lineages(id) ON DELETE RESTRICT,
    reviewer_principal_id      UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    packet_schema_version      TEXT NOT NULL CHECK (
        packet_schema_version = 'confidence-exercise-blind-packet-v1'
    ),
    confidence_taxonomy_version TEXT NOT NULL,
    playback_token_sha256      TEXT NOT NULL CHECK (
        playback_token_sha256 ~ '^[0-9a-f]{64}$'
    ),
    playback_expires_at        TIMESTAMPTZ NOT NULL,
    clip_duration_ms           INTEGER NOT NULL CHECK (clip_duration_ms > 0),
    language_code              TEXT NULL CHECK (
        language_code IS NULL
        OR language_code ~ '^[a-z]{2}(-[A-Z]{2})?$'
    ),
    asr_transcript             TEXT NULL,
    asr_transcript_sha256      TEXT NULL CHECK (
        asr_transcript_sha256 IS NULL
        OR asr_transcript_sha256 ~ '^[0-9a-f]{64}$'
    ),
    visible_payload_sha256     TEXT NOT NULL CHECK (
        visible_payload_sha256 ~ '^[0-9a-f]{64}$'
    ),
    idempotency_key            TEXT NOT NULL UNIQUE,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT exercise_blind_packet_assignment_actor_fk FOREIGN KEY (
        review_assignment_id, reviewer_principal_id
    ) REFERENCES public.ml_review_assignments(
        id, reviewer_principal_id
    ) ON DELETE RESTRICT,
    CONSTRAINT exercise_blind_packet_transcript_check CHECK (
        (asr_transcript IS NULL AND asr_transcript_sha256 IS NULL)
        OR (asr_transcript IS NOT NULL AND asr_transcript_sha256 IS NOT NULL)
    ),
    CONSTRAINT exercise_blind_packet_expiry_check CHECK (
        playback_expires_at > created_at
    )
);

CREATE TABLE IF NOT EXISTS public.exercise_blind_packet_events (
    id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    blind_packet_id            UUID NOT NULL
        REFERENCES public.exercise_blind_packets(id) ON DELETE RESTRICT,
    review_assignment_id       UUID NOT NULL
        REFERENCES public.ml_review_assignments(id) ON DELETE RESTRICT,
    event_kind                 TEXT NOT NULL CHECK (event_kind IN (
        'blind_packet_created', 'blind_packet_accessed',
        'blind_judgment_submitted', 'post_judgment_reveal_granted',
        'post_judgment_reveal_accessed'
    )),
    actor_principal_id         UUID NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    judgment_id                UUID NULL
        REFERENCES public.ml_judgments(id) ON DELETE RESTRICT,
    blindness_policy_version   TEXT NOT NULL,
    idempotency_key            TEXT NOT NULL UNIQUE,
    occurred_at                TIMESTAMPTZ NOT NULL,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (blind_packet_id, event_kind),
    CONSTRAINT exercise_blind_event_judgment_check CHECK (
        (event_kind = 'blind_judgment_submitted' AND judgment_id IS NOT NULL)
        OR (event_kind <> 'blind_judgment_submitted' AND judgment_id IS NULL)
    )
);

-- Even a future SECURITY DEFINER writer cannot record reveal out of order.
CREATE OR REPLACE FUNCTION public.validate_exercise_blind_event_sequence_v1()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
    packet public.exercise_blind_packets;
    assignment public.ml_review_assignments;
    judgment public.ml_judgments;
BEGIN
    SELECT * INTO packet FROM public.exercise_blind_packets
     WHERE id = NEW.blind_packet_id;
    IF packet.id IS NULL
       OR packet.review_assignment_id <> NEW.review_assignment_id THEN
        RAISE EXCEPTION 'EXERCISE_BLIND_PACKET_ASSIGNMENT_MISMATCH';
    END IF;
    IF NEW.event_kind <> 'blind_packet_created' AND NOT EXISTS (
        SELECT 1 FROM public.exercise_blind_packet_events event
         WHERE event.blind_packet_id = NEW.blind_packet_id
           AND event.event_kind = 'blind_packet_created'
    ) THEN
        RAISE EXCEPTION 'EXERCISE_BLIND_PACKET_NOT_CREATED';
    END IF;
    IF NEW.event_kind = 'blind_judgment_submitted' THEN
        SELECT * INTO assignment FROM public.ml_review_assignments
         WHERE id = NEW.review_assignment_id
           AND learning_surface_id = 'confidence_classification';
        SELECT * INTO judgment FROM public.ml_judgments
         WHERE id = NEW.judgment_id
           AND review_assignment_id = NEW.review_assignment_id
           AND learning_surface_id = 'confidence_classification'
           AND evidence_span_id = assignment.evidence_span_id
           AND actor_provenance IN ('blind_coach', 'blind_peer');
        IF assignment.id IS NULL OR judgment.id IS NULL THEN
            RAISE EXCEPTION 'EXERCISE_BLIND_JUDGMENT_EVIDENCE_MISMATCH';
        END IF;
    END IF;
    IF NEW.event_kind IN (
        'post_judgment_reveal_granted', 'post_judgment_reveal_accessed'
    ) AND NOT EXISTS (
        SELECT 1 FROM public.exercise_blind_packet_events event
         WHERE event.blind_packet_id = NEW.blind_packet_id
           AND event.event_kind = 'blind_judgment_submitted'
    ) THEN
        RAISE EXCEPTION 'EXERCISE_BLIND_REVEAL_REQUIRES_JUDGMENT';
    END IF;
    IF NEW.event_kind = 'post_judgment_reveal_accessed' AND NOT EXISTS (
        SELECT 1 FROM public.exercise_blind_packet_events event
         WHERE event.blind_packet_id = NEW.blind_packet_id
           AND event.event_kind = 'post_judgment_reveal_granted'
    ) THEN
        RAISE EXCEPTION 'EXERCISE_BLIND_REVEAL_NOT_GRANTED';
    END IF;
    RETURN NEW;
END;
$$;

-- Bind a blind packet to the exact immutable confidence evidence selected by
-- its assignment.  This trigger is intentionally below the RPC boundary so
-- even a privileged/manual insert cannot pair a valid assignment with another
-- principal, speaker, recording, object or interval.
CREATE OR REPLACE FUNCTION public.validate_exercise_blind_packet_lineage_v1()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
    assignment public.ml_review_assignments;
    evidence public.ml_evidence_spans;
    evidence_object public.ml_object_artifacts;
    lineage public.exercise_audio_lineages;
    processing_object public.processing_audio_objects;
    evidence_start_ms INTEGER;
    evidence_end_ms INTEGER;
BEGIN
    SELECT * INTO assignment FROM public.ml_review_assignments
     WHERE id = NEW.review_assignment_id
       AND reviewer_principal_id = NEW.reviewer_principal_id;
    IF assignment.id IS NULL
       OR assignment.learning_surface_id <> 'confidence_classification' THEN
        RAISE EXCEPTION 'EXERCISE_BLIND_ASSIGNMENT_SURFACE_INVALID';
    END IF;

    SELECT * INTO evidence FROM public.ml_evidence_spans
     WHERE id = assignment.evidence_span_id;
    SELECT * INTO lineage FROM public.exercise_audio_lineages
     WHERE id = NEW.audio_lineage_id;
    IF evidence.id IS NULL OR lineage.id IS NULL THEN
        RAISE EXCEPTION 'EXERCISE_BLIND_PACKET_EVIDENCE_REQUIRED';
    END IF;

    SELECT * INTO evidence_object FROM public.ml_object_artifacts
     WHERE id = evidence.object_artifact_id;
    SELECT * INTO processing_object FROM public.processing_audio_objects
     WHERE id = lineage.processing_audio_object_id;
    IF evidence_object.id IS NULL OR processing_object.id IS NULL THEN
        RAISE EXCEPTION 'EXERCISE_BLIND_PACKET_AUDIO_OBJECT_REQUIRED';
    END IF;

    BEGIN
        evidence_start_ms := (evidence.coordinates ->> 'start_ms')::INTEGER;
        evidence_end_ms := (evidence.coordinates ->> 'end_ms')::INTEGER;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'EXERCISE_BLIND_PACKET_COORDINATES_INVALID';
    END;

    IF evidence.acquisition_principal_id <> lineage.acquisition_principal_id
       OR evidence.speaker_id <> lineage.speaker_id
       OR evidence.project_id <> lineage.project_id
       OR evidence.take_id <> lineage.take_id
       OR evidence.recording_attempt_id <> lineage.recording_attempt_id
       OR evidence_object.acquisition_principal_id
            <> lineage.acquisition_principal_id
       OR evidence_object.speaker_id <> lineage.speaker_id
       OR evidence_object.object_store <> 'cloudflare_r2'
       OR evidence_object.artifact_kind <> 'audio'
       OR evidence_object.bucket <> processing_object.bucket
       OR evidence_object.object_key <> processing_object.object_key
       OR evidence_object.sha256 <> processing_object.exact_bytes_sha256
       OR evidence_object.byte_size <> processing_object.byte_size
       OR evidence_start_ms <> lineage.start_offset_ms
       OR evidence_end_ms - evidence_start_ms <> lineage.duration_ms THEN
        RAISE EXCEPTION 'EXERCISE_BLIND_PACKET_LINEAGE_MISMATCH';
    END IF;

    IF NEW.clip_duration_ms <> lineage.duration_ms THEN
        RAISE EXCEPTION 'EXERCISE_BLIND_PACKET_DURATION_MISMATCH';
    END IF;
    IF NEW.confidence_taxonomy_version <> assignment.taxonomy_version THEN
        RAISE EXCEPTION 'EXERCISE_BLIND_PACKET_TAXONOMY_MISMATCH';
    END IF;
    IF NEW.visible_payload_sha256 <> assignment.blind_packet_sha256 THEN
        RAISE EXCEPTION 'EXERCISE_BLIND_PACKET_PAYLOAD_HASH_MISMATCH';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS exercise_blind_packet_lineage_guard
    ON public.exercise_blind_packets;
CREATE TRIGGER exercise_blind_packet_lineage_guard
    BEFORE INSERT ON public.exercise_blind_packets
    FOR EACH ROW EXECUTE FUNCTION
        public.validate_exercise_blind_packet_lineage_v1();

DROP TRIGGER IF EXISTS exercise_blind_packet_event_sequence
    ON public.exercise_blind_packet_events;
CREATE TRIGGER exercise_blind_packet_event_sequence
    BEFORE INSERT ON public.exercise_blind_packet_events
    FOR EACH ROW EXECUTE FUNCTION
        public.validate_exercise_blind_event_sequence_v1();

-- ── Reviewed write RPCs ──────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.register_exercise_need_contract_v1(
    p_need_code TEXT,
    p_contract_version INTEGER,
    p_approval_state TEXT,
    p_operational_definition JSONB,
    p_allowed_feature_names TEXT[],
    p_required_feature_names TEXT[],
    p_exclusion_reason_codes TEXT[],
    p_contraindications JSONB,
    p_feature_schema_version TEXT,
    p_ml_data_approval_ref TEXT,
    p_approval_evidence_sha256 TEXT,
    p_created_by TEXT
) RETURNS public.exercise_need_contracts
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    contract public.exercise_need_contracts;
    contract_hash TEXT;
BEGIN
    IF btrim(COALESCE(p_need_code, '')) = ''
       OR p_contract_version <= 0
       OR p_approval_state NOT IN ('draft', 'approved', 'rejected')
       OR jsonb_typeof(p_operational_definition) <> 'object'
       OR cardinality(p_allowed_feature_names) = 0
       OR cardinality(p_required_feature_names) = 0
       OR NOT p_required_feature_names <@ p_allowed_feature_names
       OR cardinality(p_exclusion_reason_codes) = 0
       OR jsonb_typeof(p_contraindications) <> 'array'
       OR btrim(COALESCE(p_feature_schema_version, '')) = ''
       OR btrim(COALESCE(p_created_by, '')) = '' THEN
        RAISE EXCEPTION 'EXERCISE_NEED_CONTRACT_INVALID';
    END IF;
    IF p_approval_state = 'approved' AND (
        btrim(COALESCE(p_ml_data_approval_ref, '')) = ''
        OR COALESCE(p_approval_evidence_sha256, '') !~ '^[0-9a-f]{64}$'
    ) THEN
        RAISE EXCEPTION 'EXERCISE_NEED_APPROVAL_REQUIRED';
    END IF;
    contract_hash := encode(extensions.digest(concat_ws(':',
        p_need_code, p_contract_version::text, p_approval_state,
        p_operational_definition::text, p_allowed_feature_names::text,
        p_required_feature_names::text, p_exclusion_reason_codes::text,
        p_contraindications::text, p_feature_schema_version,
        COALESCE(p_ml_data_approval_ref, ''),
        COALESCE(p_approval_evidence_sha256, '')
    ), 'sha256'), 'hex');
    INSERT INTO public.exercise_need_contracts (
        need_code, contract_version, approval_state,
        operational_definition, allowed_feature_names,
        required_feature_names, exclusion_reason_codes, contraindications,
        feature_schema_version, ml_data_approval_ref,
        approval_evidence_sha256, contract_sha256, created_by
    ) VALUES (
        p_need_code, p_contract_version, p_approval_state,
        p_operational_definition, p_allowed_feature_names,
        p_required_feature_names, p_exclusion_reason_codes,
        p_contraindications, p_feature_schema_version,
        NULLIF(p_ml_data_approval_ref, ''),
        NULLIF(lower(p_approval_evidence_sha256), ''), contract_hash,
        p_created_by
    ) ON CONFLICT (need_code, contract_version) DO NOTHING;
    SELECT * INTO contract FROM public.exercise_need_contracts
     WHERE need_code = p_need_code AND contract_version = p_contract_version;
    IF contract.contract_sha256 <> contract_hash THEN
        RAISE EXCEPTION 'EXERCISE_NEED_CONTRACT_IDEMPOTENCY_CONFLICT';
    END IF;
    RETURN contract;
END;
$$;

CREATE OR REPLACE FUNCTION public.register_exercise_media_object_v1(
    p_bucket TEXT,
    p_object_key TEXT,
    p_exact_bytes_sha256 TEXT,
    p_byte_size BIGINT,
    p_content_type TEXT,
    p_verification_method TEXT,
    p_verified_at TIMESTAMPTZ,
    p_content_authority TEXT,
    p_created_by TEXT
) RETURNS public.exercise_media_objects
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE object_row public.exercise_media_objects;
BEGIN
    IF btrim(COALESCE(p_bucket, '')) = ''
       OR btrim(COALESCE(p_object_key, '')) = ''
       OR COALESCE(p_exact_bytes_sha256, '') !~ '^[0-9a-f]{64}$'
       OR p_byte_size <= 0
       OR (p_content_type NOT LIKE 'video/%'
           AND p_content_type NOT LIKE 'audio/%')
       OR p_verification_method NOT IN (
           'read_after_write_sha256', 'trusted_object_checksum_sha256'
       )
       OR p_verified_at IS NULL
       OR btrim(COALESCE(p_content_authority, '')) = ''
       OR btrim(COALESCE(p_created_by, '')) = '' THEN
        RAISE EXCEPTION 'EXERCISE_MEDIA_OBJECT_INVALID';
    END IF;
    INSERT INTO public.exercise_media_objects (
        storage_provider, bucket, object_key, exact_bytes_sha256, byte_size,
        content_type, verification_method, verified_at, content_authority,
        created_by
    ) VALUES (
        'r2', p_bucket, p_object_key, lower(p_exact_bytes_sha256), p_byte_size,
        p_content_type, p_verification_method, p_verified_at,
        p_content_authority, p_created_by
    ) ON CONFLICT (storage_provider, bucket, object_key) DO NOTHING;
    SELECT * INTO object_row FROM public.exercise_media_objects
     WHERE storage_provider = 'r2' AND bucket = p_bucket
       AND object_key = p_object_key;
    IF object_row.exact_bytes_sha256 <> lower(p_exact_bytes_sha256)
       OR object_row.byte_size <> p_byte_size
       OR object_row.content_type <> p_content_type THEN
        RAISE EXCEPTION 'EXERCISE_MEDIA_OBJECT_IDEMPOTENCY_CONFLICT';
    END IF;
    RETURN object_row;
END;
$$;

CREATE OR REPLACE FUNCTION public.register_exercise_version_v1(
    p_exercise_key TEXT,
    p_origin_kind TEXT,
    p_author_principal_id UUID,
    p_language_code TEXT,
    p_version_number INTEGER,
    p_need_contract_id UUID,
    p_media_object_id UUID,
    p_instruction_text TEXT,
    p_safety_state TEXT,
    p_catalogue_state TEXT,
    p_created_by TEXT
) RETURNS public.exercise_versions
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    definition public.exercise_definitions;
    version_row public.exercise_versions;
    need_contract public.exercise_need_contracts;
    media public.exercise_media_objects;
    definition_hash TEXT;
    instruction_hash TEXT;
    version_hash TEXT;
BEGIN
    SELECT * INTO need_contract FROM public.exercise_need_contracts
     WHERE id = p_need_contract_id;
    SELECT * INTO media FROM public.exercise_media_objects
     WHERE id = p_media_object_id;
    IF need_contract.id IS NULL OR media.id IS NULL
       OR p_exercise_key !~ '^[a-z0-9][a-z0-9_-]{2,119}$'
       OR p_origin_kind NOT IN ('willab_library', 'coach_case_specific')
       OR (p_origin_kind = 'coach_case_specific'
           AND p_author_principal_id IS NULL)
       OR p_language_code !~ '^[a-z]{2}(-[A-Z]{2})?$'
       OR p_version_number <= 0
       OR btrim(COALESCE(p_instruction_text, '')) = ''
       OR p_safety_state NOT IN (
           'pending_review', 'approved', 'restricted', 'rejected'
       )
       OR p_catalogue_state NOT IN ('draft', 'active', 'inactive', 'retired')
       OR btrim(COALESCE(p_created_by, '')) = '' THEN
        RAISE EXCEPTION 'EXERCISE_VERSION_INVALID';
    END IF;
    IF p_catalogue_state = 'active' AND (
        p_safety_state <> 'approved' OR need_contract.approval_state <> 'approved'
    ) THEN
        RAISE EXCEPTION 'EXERCISE_ACTIVE_VERSION_REQUIRES_APPROVAL';
    END IF;
    definition_hash := encode(extensions.digest(concat_ws(':',
        p_exercise_key, p_origin_kind,
        COALESCE(p_author_principal_id::text, ''), p_language_code
    ), 'sha256'), 'hex');
    INSERT INTO public.exercise_definitions (
        exercise_key, origin_kind, author_principal_id, language_code,
        definition_sha256, created_by
    ) VALUES (
        p_exercise_key, p_origin_kind, p_author_principal_id, p_language_code,
        definition_hash, p_created_by
    ) ON CONFLICT (exercise_key) DO NOTHING;
    SELECT * INTO definition FROM public.exercise_definitions
     WHERE exercise_key = p_exercise_key;
    IF definition.definition_sha256 <> definition_hash THEN
        RAISE EXCEPTION 'EXERCISE_DEFINITION_IDEMPOTENCY_CONFLICT';
    END IF;
    instruction_hash := encode(
        extensions.digest(convert_to(p_instruction_text, 'UTF8'), 'sha256'),
        'hex'
    );
    version_hash := encode(extensions.digest(concat_ws(':',
        definition.id::text, p_version_number::text, need_contract.id::text,
        media.id::text, media.exact_bytes_sha256, instruction_hash,
        p_safety_state, p_catalogue_state
    ), 'sha256'), 'hex');
    INSERT INTO public.exercise_versions (
        exercise_definition_id, version_number, need_contract_id,
        media_object_id, instruction_text, instruction_sha256,
        safety_state, catalogue_state, version_sha256, created_by
    ) VALUES (
        definition.id, p_version_number, need_contract.id, media.id,
        p_instruction_text, instruction_hash, p_safety_state,
        p_catalogue_state, version_hash, p_created_by
    ) ON CONFLICT (exercise_definition_id, version_number) DO NOTHING;
    SELECT * INTO version_row FROM public.exercise_versions
     WHERE exercise_definition_id = definition.id
       AND version_number = p_version_number;
    IF version_row.version_sha256 <> version_hash THEN
        RAISE EXCEPTION 'EXERCISE_VERSION_IDEMPOTENCY_CONFLICT';
    END IF;
    RETURN version_row;
END;
$$;

CREATE OR REPLACE FUNCTION public.finalize_exercise_catalog_snapshot_v1(
    p_catalog_policy_version TEXT,
    p_scope_language_code TEXT,
    p_version_cutoff_at TIMESTAMPTZ,
    p_idempotency_key TEXT,
    p_created_by TEXT
) RETURNS public.exercise_catalog_snapshots
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    snapshot public.exercise_catalog_snapshots;
    manifest JSONB;
    manifest_hash TEXT;
    item_count INTEGER;
BEGIN
    IF btrim(COALESCE(p_catalog_policy_version, '')) = ''
       OR (p_scope_language_code IS NOT NULL
           AND p_scope_language_code !~ '^[a-z]{2}(-[A-Z]{2})?$')
       OR p_version_cutoff_at IS NULL OR p_version_cutoff_at > now()
       OR btrim(COALESCE(p_idempotency_key, '')) = ''
       OR btrim(COALESCE(p_created_by, '')) = '' THEN
        RAISE EXCEPTION 'EXERCISE_CATALOG_SNAPSHOT_INVALID';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtext(concat_ws(':',
        'exercise-catalog', COALESCE(p_scope_language_code, '*'),
        p_catalog_policy_version, p_version_cutoff_at::text
    )));
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
        'exercise_version_id', version_row.id,
        'exercise_key', definition.exercise_key,
        'version_number', version_row.version_number,
        'version_sha256', version_row.version_sha256,
        'catalogue_state', version_row.catalogue_state,
        'safety_state', version_row.safety_state,
        'need_contract_sha256', need_contract.contract_sha256,
        'media_sha256', media.exact_bytes_sha256
    ) ORDER BY definition.exercise_key, version_row.version_number), '[]'::jsonb),
    count(*)::integer
      INTO manifest, item_count
      FROM public.exercise_versions version_row
      JOIN public.exercise_definitions definition
        ON definition.id = version_row.exercise_definition_id
      JOIN public.exercise_need_contracts need_contract
        ON need_contract.id = version_row.need_contract_id
      JOIN public.exercise_media_objects media
        ON media.id = version_row.media_object_id
     WHERE version_row.created_at <= p_version_cutoff_at
       AND (p_scope_language_code IS NULL
            OR definition.language_code = p_scope_language_code);
    IF item_count = 0 THEN
        RAISE EXCEPTION 'EXERCISE_CATALOG_SCOPE_EMPTY';
    END IF;
    manifest_hash := encode(
        extensions.digest(convert_to(manifest::text, 'UTF8'), 'sha256'), 'hex'
    );
    INSERT INTO public.exercise_catalog_snapshots (
        catalog_policy_version, scope_language_code, version_cutoff_at,
        version_count, manifest_sha256, idempotency_key, created_by
    ) VALUES (
        p_catalog_policy_version, p_scope_language_code, p_version_cutoff_at,
        item_count, manifest_hash, p_idempotency_key, p_created_by
    ) ON CONFLICT (idempotency_key) DO NOTHING;
    SELECT * INTO snapshot FROM public.exercise_catalog_snapshots
     WHERE idempotency_key = p_idempotency_key;
    IF snapshot.catalog_policy_version <> p_catalog_policy_version
       OR snapshot.scope_language_code IS DISTINCT FROM p_scope_language_code
       OR snapshot.version_cutoff_at <> p_version_cutoff_at
       OR snapshot.version_count <> item_count
       OR snapshot.manifest_sha256 <> manifest_hash THEN
        RAISE EXCEPTION 'EXERCISE_CATALOG_IDEMPOTENCY_CONFLICT';
    END IF;
    INSERT INTO public.exercise_catalog_snapshot_items (
        catalog_snapshot_id, exercise_version_id, exercise_key,
        version_number, catalogue_state, safety_state, item_sha256
    )
    SELECT snapshot.id, version_row.id, definition.exercise_key,
           version_row.version_number, version_row.catalogue_state,
           version_row.safety_state,
           encode(extensions.digest(concat_ws(':',
               snapshot.id::text, version_row.id::text,
               version_row.version_sha256, version_row.catalogue_state,
               version_row.safety_state
           ), 'sha256'), 'hex')
      FROM public.exercise_versions version_row
      JOIN public.exercise_definitions definition
        ON definition.id = version_row.exercise_definition_id
     WHERE version_row.created_at <= p_version_cutoff_at
       AND (p_scope_language_code IS NULL
            OR definition.language_code = p_scope_language_code)
    ON CONFLICT (catalog_snapshot_id, exercise_version_id) DO NOTHING;
    IF (SELECT count(*) FROM public.exercise_catalog_snapshot_items item
         WHERE item.catalog_snapshot_id = snapshot.id) <> snapshot.version_count
    THEN
        RAISE EXCEPTION 'EXERCISE_CATALOG_SNAPSHOT_INCOMPLETE';
    END IF;
    RETURN snapshot;
END;
$$;

CREATE OR REPLACE FUNCTION public.record_exercise_authorization_check_v1(
    p_acquisition_principal_id UUID,
    p_authorization_snapshot_id UUID,
    p_operation_kind TEXT,
    p_idempotency_key TEXT
) RETURNS public.exercise_authorization_checks
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    snapshot public.processing_authorization_snapshots;
    receipt public.processing_authorization_receipts;
    policy public.processing_policy_versions;
    purpose public.processing_purpose_registry;
    result public.exercise_authorization_checks;
    allowed BOOLEAN := false;
    decision TEXT;
    evidence_hash TEXT;
BEGIN
    IF p_operation_kind NOT IN (
        'profile_identity', 'source_audio_lineage', 'catalog_assignment',
        'blind_review_preparation', 'practice_processing'
    ) OR btrim(COALESCE(p_idempotency_key, '')) = '' THEN
        RAISE EXCEPTION 'EXERCISE_AUTHORIZATION_CHECK_INVALID';
    END IF;
    SELECT * INTO snapshot FROM public.processing_authorization_snapshots
     WHERE id = p_authorization_snapshot_id
       AND acquisition_principal_id = p_acquisition_principal_id;
    SELECT * INTO purpose FROM public.processing_purpose_registry
     WHERE id = 'personalized_exercise_recommendation';
    IF snapshot.id IS NULL THEN
        decision := 'AUTHORIZATION_SNAPSHOT_MISSING';
    ELSIF snapshot.purpose_id <> 'personalized_exercise_recommendation' THEN
        decision := 'AUTHORIZATION_PURPOSE_MISMATCH';
    ELSIF NOT COALESCE(purpose.operational, false)
          OR NOT COALESCE(purpose.authorizes_processing, false) THEN
        decision := 'EXERCISE_PURPOSE_INACTIVE';
    ELSE
        SELECT * INTO receipt FROM public.processing_authorization_receipts
         WHERE id = snapshot.receipt_id
           AND acquisition_principal_id = p_acquisition_principal_id;
        SELECT * INTO policy FROM public.processing_policy_versions
         WHERE id = snapshot.policy_id AND status = 'active'
           AND activated_at <= now()
           AND (retired_at IS NULL OR retired_at > now());
        IF receipt.id IS NULL OR policy.id IS NULL THEN
            decision := 'CURRENT_AUTHORITY_INACTIVE';
        ELSIF NOT EXISTS (
            SELECT 1 FROM public.processing_authorization_receipt_purposes rp
             WHERE rp.receipt_id = receipt.id
               AND rp.purpose_id = 'personalized_exercise_recommendation'
        ) OR NOT EXISTS (
            SELECT 1 FROM public.processing_policy_purposes pp
             WHERE pp.policy_id = policy.id
               AND pp.purpose_id = 'personalized_exercise_recommendation'
        ) THEN
            decision := 'EXERCISE_PURPOSE_NOT_ACCEPTED';
        ELSIF EXISTS (
            SELECT 1 FROM public.processing_service_blocks block
             WHERE block.acquisition_principal_id = p_acquisition_principal_id
               AND block.effective_at <= now()
        ) THEN
            decision := 'PROCESSING_SERVICE_BLOCKED';
        ELSE
            allowed := true;
            decision := 'AUTHORIZED';
        END IF;
    END IF;
    evidence_hash := encode(extensions.digest(concat_ws(':',
        p_acquisition_principal_id::text,
        p_authorization_snapshot_id::text, p_operation_kind,
        COALESCE(policy.version, ''), decision, now()::date::text
    ), 'sha256'), 'hex');
    INSERT INTO public.exercise_authorization_checks (
        acquisition_principal_id, authorization_snapshot_id, purpose_id,
        operation_kind, authorized, decision_code, policy_version,
        authority_evidence_sha256, idempotency_key
    ) VALUES (
        p_acquisition_principal_id, p_authorization_snapshot_id,
        'personalized_exercise_recommendation', p_operation_kind,
        allowed, decision, policy.version, evidence_hash, p_idempotency_key
    ) ON CONFLICT (idempotency_key) DO NOTHING;
    SELECT * INTO result FROM public.exercise_authorization_checks
     WHERE idempotency_key = p_idempotency_key;
    IF result.acquisition_principal_id <> p_acquisition_principal_id
       OR result.authorization_snapshot_id <> p_authorization_snapshot_id
       OR result.operation_kind <> p_operation_kind
       OR result.authorized <> allowed OR result.decision_code <> decision THEN
        RAISE EXCEPTION 'EXERCISE_AUTHORIZATION_IDEMPOTENCY_CONFLICT';
    END IF;
    RETURN result;
END;
$$;

-- An immutable check is evidence of one decision, not permanent authority.
-- Every consuming RPC revalidates the live purpose, policy and block state;
-- a check also expires quickly so it cannot be replayed as a bearer permit.
CREATE OR REPLACE FUNCTION public.require_current_exercise_authorization_v1(
    p_authorization_check_id UUID,
    p_acquisition_principal_id UUID,
    p_operation_kind TEXT
) RETURNS public.exercise_authorization_checks
LANGUAGE plpgsql SECURITY DEFINER STABLE SET search_path = public
AS $$
DECLARE
    auth public.exercise_authorization_checks;
    snapshot public.processing_authorization_snapshots;
BEGIN
    SELECT * INTO auth FROM public.exercise_authorization_checks
     WHERE id = p_authorization_check_id
       AND acquisition_principal_id = p_acquisition_principal_id
       AND operation_kind = p_operation_kind AND authorized
       AND checked_at >= now() - interval '5 minutes';
    IF auth.id IS NULL THEN
        RAISE EXCEPTION 'EXERCISE_CURRENT_AUTHORIZATION_REQUIRED';
    END IF;
    SELECT * INTO snapshot FROM public.processing_authorization_snapshots
     WHERE id = auth.authorization_snapshot_id
       AND acquisition_principal_id = p_acquisition_principal_id
       AND purpose_id = 'personalized_exercise_recommendation';
    IF snapshot.id IS NULL
       OR NOT EXISTS (
           SELECT 1 FROM public.processing_purpose_registry purpose
            WHERE purpose.id = 'personalized_exercise_recommendation'
              AND purpose.operational AND purpose.authorizes_processing
       )
       OR NOT EXISTS (
           SELECT 1 FROM public.processing_policy_versions policy
            WHERE policy.id = snapshot.policy_id AND policy.status = 'active'
              AND policy.activated_at <= now()
              AND (policy.retired_at IS NULL OR policy.retired_at > now())
       )
       OR NOT EXISTS (
           SELECT 1 FROM public.processing_authorization_receipt_purposes rp
            WHERE rp.receipt_id = snapshot.receipt_id
              AND rp.purpose_id = 'personalized_exercise_recommendation'
       )
       OR EXISTS (
           SELECT 1 FROM public.processing_service_blocks block
            WHERE block.acquisition_principal_id = p_acquisition_principal_id
              AND block.effective_at <= now()
       ) THEN
        RAISE EXCEPTION 'EXERCISE_CURRENT_AUTHORIZATION_REVOKED';
    END IF;
    RETURN auth;
END;
$$;

CREATE OR REPLACE FUNCTION public.ensure_learning_profile_v1(
    p_speaker_id UUID,
    p_acquisition_principal_id UUID,
    p_authorization_check_id UUID,
    p_profile_schema_version TEXT,
    p_idempotency_key TEXT
) RETURNS public.learning_profiles
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    auth public.exercise_authorization_checks;
    profile public.learning_profiles;
    identity_hash TEXT;
BEGIN
    SELECT * INTO auth FROM public.require_current_exercise_authorization_v1(
        p_authorization_check_id, p_acquisition_principal_id,
        'profile_identity'
    );
    IF auth.id IS NULL
       OR NOT EXISTS (
           SELECT 1 FROM public.ml_speaker_principals binding
            WHERE binding.speaker_id = p_speaker_id
              AND binding.acquisition_principal_id = p_acquisition_principal_id
       ) OR btrim(COALESCE(p_profile_schema_version, '')) = ''
       OR btrim(COALESCE(p_idempotency_key, '')) = '' THEN
        RAISE EXCEPTION 'LEARNING_PROFILE_IDENTITY_INVALID';
    END IF;
    identity_hash := encode(extensions.digest(concat_ws(':',
        p_speaker_id::text, p_profile_schema_version,
        'exercise-learning-profile'
    ), 'sha256'), 'hex');
    INSERT INTO public.learning_profiles (
        speaker_id, origin_acquisition_principal_id,
        origin_authorization_check_id, profile_schema_version,
        profile_identity_sha256, idempotency_key
    ) VALUES (
        p_speaker_id, p_acquisition_principal_id, auth.id,
        p_profile_schema_version, identity_hash, p_idempotency_key
    ) ON CONFLICT (speaker_id) DO NOTHING;
    SELECT * INTO profile FROM public.learning_profiles
     WHERE speaker_id = p_speaker_id;
    IF profile.profile_schema_version <> p_profile_schema_version
       OR profile.profile_identity_sha256 <> identity_hash THEN
        RAISE EXCEPTION 'LEARNING_PROFILE_IDEMPOTENCY_CONFLICT';
    END IF;
    PERFORM public.assign_ml_speaker_split_v1(p_speaker_id);
    RETURN profile;
END;
$$;

CREATE OR REPLACE FUNCTION public.register_exercise_audio_lineage_v1(
    p_acquisition_principal_id UUID,
    p_speaker_id UUID,
    p_learning_profile_id UUID,
    p_authorization_check_id UUID,
    p_processing_audio_object_id UUID,
    p_project_id UUID,
    p_take_id UUID,
    p_recording_attempt_id UUID,
    p_recording_id UUID,
    p_snippet_id UUID,
    p_start_offset_ms INTEGER,
    p_duration_ms INTEGER,
    p_lineage_schema_version TEXT,
    p_idempotency_key TEXT
) RETURNS public.exercise_audio_lineages
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    auth public.exercise_authorization_checks;
    profile public.learning_profiles;
    object_row public.processing_audio_objects;
    attempt public.processing_recording_attempts;
    take_row public.takes;
    snippet public.snippets;
    lineage public.exercise_audio_lineages;
    lineage_hash TEXT;
BEGIN
    SELECT * INTO auth FROM public.require_current_exercise_authorization_v1(
        p_authorization_check_id, p_acquisition_principal_id,
        'source_audio_lineage'
    );
    SELECT * INTO profile FROM public.learning_profiles
     WHERE id = p_learning_profile_id AND speaker_id = p_speaker_id;
    SELECT * INTO object_row FROM public.processing_audio_objects
     WHERE id = p_processing_audio_object_id
       AND acquisition_principal_id = p_acquisition_principal_id
       AND recording_attempt_id = p_recording_attempt_id
       AND storage_provider = 'r2' AND deleted_at IS NULL;
    SELECT * INTO attempt FROM public.processing_recording_attempts
     WHERE id = p_recording_attempt_id
       AND acquisition_principal_id = p_acquisition_principal_id
       AND project_id = p_project_id AND recording_id = p_recording_id;
    SELECT * INTO take_row FROM public.takes
     WHERE id = p_take_id AND recording_attempt_id = p_recording_attempt_id
       AND owner_principal_id = p_acquisition_principal_id
       AND project_id = p_project_id;
    SELECT * INTO snippet FROM public.snippets
     WHERE id = p_snippet_id AND session_id = p_take_id
       AND recording_id = p_recording_id;
    IF auth.id IS NULL OR profile.id IS NULL OR object_row.id IS NULL
       OR attempt.id IS NULL OR take_row.id IS NULL OR snippet.id IS NULL
       OR p_start_offset_ms < 0 OR p_duration_ms <= 0
       OR btrim(COALESCE(p_lineage_schema_version, '')) = ''
       OR btrim(COALESCE(p_idempotency_key, '')) = '' THEN
        RAISE EXCEPTION 'EXERCISE_AUDIO_LINEAGE_INVALID';
    END IF;
    IF snippet.start_offset_ms IS DISTINCT FROM p_start_offset_ms
       OR snippet.duration_ms IS DISTINCT FROM p_duration_ms THEN
        RAISE EXCEPTION 'EXERCISE_AUDIO_LINEAGE_SNIPPET_INTERVAL_MISMATCH';
    END IF;
    lineage_hash := encode(extensions.digest(concat_ws(':',
        p_acquisition_principal_id::text, p_speaker_id::text,
        profile.id::text, auth.id::text, object_row.id::text,
        p_project_id::text, p_take_id::text, p_recording_attempt_id::text,
        p_recording_id::text, p_snippet_id::text,
        p_start_offset_ms::text, p_duration_ms::text,
        object_row.exact_bytes_sha256, object_row.byte_size::text,
        object_row.verification_method, p_lineage_schema_version
    ), 'sha256'), 'hex');
    INSERT INTO public.exercise_audio_lineages (
        acquisition_principal_id, speaker_id, learning_profile_id,
        authorization_check_id, processing_audio_object_id, project_id,
        take_id, recording_attempt_id, recording_id, snippet_id,
        start_offset_ms, duration_ms, exact_audio_sha256, object_byte_size,
        verification_method, lineage_schema_version, lineage_sha256,
        idempotency_key
    ) VALUES (
        p_acquisition_principal_id, p_speaker_id, profile.id, auth.id,
        object_row.id, p_project_id, p_take_id, p_recording_attempt_id,
        p_recording_id, p_snippet_id, p_start_offset_ms, p_duration_ms,
        object_row.exact_bytes_sha256, object_row.byte_size,
        object_row.verification_method, p_lineage_schema_version,
        lineage_hash, p_idempotency_key
    ) ON CONFLICT (idempotency_key) DO NOTHING;
    SELECT * INTO lineage FROM public.exercise_audio_lineages
     WHERE idempotency_key = p_idempotency_key;
    IF lineage.lineage_sha256 <> lineage_hash THEN
        RAISE EXCEPTION 'EXERCISE_AUDIO_LINEAGE_IDEMPOTENCY_CONFLICT';
    END IF;
    RETURN lineage;
END;
$$;

CREATE OR REPLACE FUNCTION public.register_exercise_blind_packet_v1(
    p_review_assignment_id UUID,
    p_audio_lineage_id UUID,
    p_reviewer_principal_id UUID,
    p_packet_schema_version TEXT,
    p_confidence_taxonomy_version TEXT,
    p_playback_token_sha256 TEXT,
    p_playback_expires_at TIMESTAMPTZ,
    p_clip_duration_ms INTEGER,
    p_language_code TEXT,
    p_asr_transcript TEXT,
    p_asr_transcript_sha256 TEXT,
    p_visible_payload_sha256 TEXT,
    p_blindness_policy_version TEXT,
    p_idempotency_key TEXT
) RETURNS public.exercise_blind_packets
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    packet public.exercise_blind_packets;
BEGIN
    IF p_packet_schema_version <> 'confidence-exercise-blind-packet-v1'
       OR COALESCE(p_playback_token_sha256, '') !~ '^[0-9a-f]{64}$'
       OR p_playback_expires_at <= now()
       OR p_clip_duration_ms <= 0
       OR COALESCE(p_visible_payload_sha256, '') !~ '^[0-9a-f]{64}$'
       OR btrim(COALESCE(p_confidence_taxonomy_version, '')) = ''
       OR btrim(COALESCE(p_blindness_policy_version, '')) = ''
       OR btrim(COALESCE(p_idempotency_key, '')) = '' THEN
        RAISE EXCEPTION 'EXERCISE_BLIND_PACKET_INVALID';
    END IF;

    SELECT * INTO packet FROM public.exercise_blind_packets
     WHERE idempotency_key = p_idempotency_key;
    IF packet.id IS NOT NULL THEN
        IF packet.review_assignment_id <> p_review_assignment_id
           OR packet.audio_lineage_id <> p_audio_lineage_id
           OR packet.reviewer_principal_id <> p_reviewer_principal_id
           OR packet.packet_schema_version <> p_packet_schema_version
           OR packet.confidence_taxonomy_version
                <> p_confidence_taxonomy_version
           OR packet.playback_token_sha256 <> p_playback_token_sha256
           OR packet.playback_expires_at <> p_playback_expires_at
           OR packet.clip_duration_ms <> p_clip_duration_ms
           OR packet.language_code IS DISTINCT FROM p_language_code
           OR packet.asr_transcript IS DISTINCT FROM p_asr_transcript
           OR packet.asr_transcript_sha256
                IS DISTINCT FROM p_asr_transcript_sha256
           OR packet.visible_payload_sha256 <> p_visible_payload_sha256 THEN
            RAISE EXCEPTION 'EXERCISE_BLIND_PACKET_IDEMPOTENCY_CONFLICT';
        END IF;
        RETURN packet;
    END IF;

    INSERT INTO public.exercise_blind_packets (
        review_assignment_id, audio_lineage_id, reviewer_principal_id,
        packet_schema_version, confidence_taxonomy_version,
        playback_token_sha256, playback_expires_at, clip_duration_ms,
        language_code, asr_transcript, asr_transcript_sha256,
        visible_payload_sha256, idempotency_key
    ) VALUES (
        p_review_assignment_id, p_audio_lineage_id,
        p_reviewer_principal_id, p_packet_schema_version,
        p_confidence_taxonomy_version, lower(p_playback_token_sha256),
        p_playback_expires_at, p_clip_duration_ms, p_language_code,
        p_asr_transcript, lower(p_asr_transcript_sha256),
        lower(p_visible_payload_sha256), p_idempotency_key
    ) RETURNING * INTO packet;

    INSERT INTO public.exercise_blind_packet_events (
        blind_packet_id, review_assignment_id, event_kind,
        actor_principal_id, blindness_policy_version, idempotency_key,
        occurred_at
    ) VALUES (
        packet.id, packet.review_assignment_id, 'blind_packet_created', NULL,
        p_blindness_policy_version, p_idempotency_key || ':created', now()
    );
    RETURN packet;
END;
$$;

CREATE OR REPLACE FUNCTION public.get_mlc3_exercise_foundation_health_v1()
RETURNS JSONB
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = public
AS $$
SELECT jsonb_build_object(
    'learning_contract_version', 'MLC-3',
    'data_epoch', 1,
    'learning_surface', 'exercise_adequacy_classification',
    'catalogue_foundation', 'dark',
    'producer_integration', false,
    'serves_user', false,
    'dataset_creation_enabled', false,
    'training_enabled', false,
    'evaluation_enabled', false,
    'promotion_enabled', false,
    'personalized_exercise_purpose_operational', COALESCE((
        SELECT operational AND authorizes_processing
          FROM public.processing_purpose_registry
         WHERE id = 'personalized_exercise_recommendation'
    ), false),
    'need_contract_count', (SELECT count(*) FROM public.exercise_need_contracts),
    'exercise_version_count', (SELECT count(*) FROM public.exercise_versions),
    'catalog_snapshot_count', (SELECT count(*) FROM public.exercise_catalog_snapshots),
    'audio_lineage_count', (SELECT count(*) FROM public.exercise_audio_lineages),
    'learning_profile_count', (SELECT count(*) FROM public.learning_profiles),
    'blind_packet_count', (SELECT count(*) FROM public.exercise_blind_packets)
);
$$;

-- ── Deletion traversal repair (versioned; 0312/v3 remains unchanged) ─────

-- V2 extends, rather than mutates, the deployed subject graph.  New purge
-- inventories can therefore address the real legacy practice coordinates
-- and the M3-2 lineage tables.  A pre-existing v3 inventory fails closed and
-- must be reviewed rather than silently changing meaning during a purge.
CREATE OR REPLACE FUNCTION public.resolve_phase1_purge_subject_graph_v2(
    p_acquisition_principal_id UUID
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER STABLE SET search_path = public
AS $$
DECLARE
    base_graph JSONB;
    principal_values TEXT[];
    user_values TEXT[];
    take_values TEXT[];
    speaker_values TEXT[];
    practice_values TEXT[];
    practice_attempt_values TEXT[];
    exercise_audio_lineage_values TEXT[];
    exercise_blind_packet_values TEXT[];
BEGIN
    base_graph := public.resolve_phase1_purge_subject_graph_v1(
        p_acquisition_principal_id
    );
    SELECT ARRAY(SELECT jsonb_array_elements_text(base_graph->'principal_ids'))
      INTO principal_values;
    SELECT ARRAY(SELECT jsonb_array_elements_text(base_graph->'user_ids'))
      INTO user_values;
    SELECT ARRAY(SELECT jsonb_array_elements_text(base_graph->'take_ids'))
      INTO take_values;

    SELECT COALESCE(array_agg(value ORDER BY value), '{}'::text[])
      INTO speaker_values
      FROM (
          SELECT DISTINCT binding.speaker_id::text AS value
            FROM public.ml_speaker_principals binding
           WHERE binding.acquisition_principal_id::text = ANY(principal_values)
      ) rows;

    SELECT COALESCE(array_agg(value ORDER BY value), '{}'::text[])
      INTO practice_values
      FROM (
          SELECT DISTINCT practice.id::text AS value
            FROM public.confident_voice_practice practice
           WHERE practice.owner_user_id::text = ANY(user_values)
              OR practice.take_session_id::text = ANY(take_values)
      ) rows;

    SELECT COALESCE(array_agg(value ORDER BY value), '{}'::text[])
      INTO practice_attempt_values
      FROM (
          SELECT DISTINCT attempt.id::text AS value
            FROM public.confident_voice_practice_attempt attempt
           WHERE attempt.practice_id::text = ANY(practice_values)
      ) rows;

    SELECT COALESCE(array_agg(value ORDER BY value), '{}'::text[])
      INTO exercise_audio_lineage_values
      FROM (
          SELECT DISTINCT lineage.id::text AS value
            FROM public.exercise_audio_lineages lineage
           WHERE lineage.acquisition_principal_id::text = ANY(principal_values)
              OR lineage.speaker_id::text = ANY(speaker_values)
      ) rows;

    SELECT COALESCE(array_agg(value ORDER BY value), '{}'::text[])
      INTO exercise_blind_packet_values
      FROM (
          SELECT DISTINCT packet.id::text AS value
            FROM public.exercise_blind_packets packet
           WHERE packet.audio_lineage_id::text =
                 ANY(exercise_audio_lineage_values)
      ) rows;

    RETURN base_graph || jsonb_build_object(
        'speaker_ids', to_jsonb(speaker_values),
        'practice_ids', to_jsonb(practice_values),
        'practice_attempt_ids', to_jsonb(practice_attempt_values),
        'exercise_audio_lineage_ids', to_jsonb(exercise_audio_lineage_values),
        'exercise_blind_packet_ids', to_jsonb(exercise_blind_packet_values)
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.freeze_phase1_purge_inventory_v4(
    p_purge_request_id UUID,
    p_resolver_version TEXT,
    p_dependency_manifest_sha256 TEXT,
    p_subject_graph JSONB,
    p_targets JSONB,
    p_catalog_sha256 TEXT,
    p_catalog_unknown_relations TEXT[]
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE req public.data_purge_requests; existing public.data_purge_inventory_manifests;
        item JSONB; kind TEXT; ref TEXT; item_state TEXT; unknown_count INTEGER;
        computed_subject_graph_sha256 TEXT; computed_target_manifest_sha256 TEXT;
        expected_subject_graph JSONB; item_metadata JSONB; locator_key TEXT;
BEGIN
    SELECT * INTO req FROM public.data_purge_requests
     WHERE id = p_purge_request_id FOR UPDATE;
    IF req.id IS NULL THEN RAISE EXCEPTION 'PURGE_REQUEST_NOT_FOUND'; END IF;
    IF req.state = 'done' THEN RAISE EXCEPTION 'PURGE_ALREADY_FINALIZED'; END IF;
    IF jsonb_typeof(p_subject_graph) <> 'object'
       OR jsonb_typeof(p_targets) <> 'array'
       OR jsonb_array_length(p_targets) = 0
    THEN RAISE EXCEPTION 'PURGE_MANIFEST_INVALID'; END IF;
    IF p_resolver_version <> 'phase1-purge-resolver-v4' THEN
        RAISE EXCEPTION 'PURGE_RESOLVER_VERSION_INVALID';
    END IF;
    expected_subject_graph := public.resolve_phase1_purge_subject_graph_v2(
        req.acquisition_principal_id
    );
    IF p_subject_graph IS DISTINCT FROM expected_subject_graph THEN
        RAISE EXCEPTION 'PURGE_SUBJECT_GRAPH_MISMATCH';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(p_targets) candidate
         GROUP BY COALESCE(candidate->>'target_kind', 'unknown'),
                  COALESCE(NULLIF(candidate->>'target_ref', ''), 'unresolved')
        HAVING count(*) > 1
    ) THEN RAISE EXCEPTION 'PURGE_MANIFEST_DUPLICATE_TARGET'; END IF;
    IF p_dependency_manifest_sha256 !~ '^[0-9a-f]{64}$'
       OR p_catalog_sha256 !~ '^[0-9a-f]{64}$'
    THEN RAISE EXCEPTION 'PURGE_MANIFEST_HASH_INVALID'; END IF;

    computed_subject_graph_sha256 := encode(
        extensions.digest(p_subject_graph::text, 'sha256'), 'hex'
    );
    computed_target_manifest_sha256 := encode(
        extensions.digest(p_targets::text, 'sha256'), 'hex'
    );

    SELECT * INTO existing FROM public.data_purge_inventory_manifests
     WHERE purge_request_id = p_purge_request_id;
    IF existing.id IS NOT NULL THEN
        IF existing.resolver_version <> p_resolver_version
           OR existing.dependency_manifest_sha256 <>
              lower(p_dependency_manifest_sha256)
           OR existing.subject_graph_sha256 <> computed_subject_graph_sha256
           OR existing.target_manifest_sha256 <>
              computed_target_manifest_sha256
           OR existing.catalog_sha256 <> lower(p_catalog_sha256)
           OR existing.catalog_unknown_relations <>
              COALESCE(p_catalog_unknown_relations, '{}'::text[])
        THEN RAISE EXCEPTION 'PURGE_INVENTORY_REPLAY_CONFLICT'; END IF;
    ELSE
        INSERT INTO public.data_purge_inventory_manifests (
            purge_request_id, resolver_version, dependency_manifest_sha256,
            subject_graph, subject_graph_sha256, target_manifest_sha256,
            catalog_sha256, catalog_unknown_relations
        ) VALUES (
            p_purge_request_id, p_resolver_version,
            lower(p_dependency_manifest_sha256), p_subject_graph,
            computed_subject_graph_sha256, computed_target_manifest_sha256,
            lower(p_catalog_sha256),
            COALESCE(p_catalog_unknown_relations, '{}'::text[])
        );
    END IF;

    FOR item IN SELECT value FROM jsonb_array_elements(p_targets) LOOP
        kind := COALESCE(item->>'target_kind', 'unknown');
        ref := COALESCE(NULLIF(item->>'target_ref', ''), 'unresolved');
        item_metadata := COALESCE(item->'metadata', '{}'::jsonb);
        IF kind NOT IN (
            'database_row', 'r2_object', 'supabase_object', 'transcript',
            'derived_feedback', 'processing_queue', 'provider_operation',
            'coach_packet', 'cache', 'dataset_lineage', 'model_lineage'
        ) THEN kind := 'unknown'; END IF;
        IF kind <> 'unknown' AND ref LIKE 'dependency:%' THEN
            locator_key := CASE item_metadata->>'locator_kind'
                WHEN 'principal' THEN 'principal_ids'
                WHEN 'user' THEN 'user_ids'
                WHEN 'project' THEN 'project_ids'
                WHEN 'take' THEN 'take_ids'
                WHEN 'recording' THEN 'recording_ids'
                WHEN 'snippet' THEN 'snippet_ids'
                WHEN 'permit' THEN 'permit_ids'
                WHEN 'job' THEN 'job_ids'
                WHEN 'speaker' THEN 'speaker_ids'
                WHEN 'practice' THEN 'practice_ids'
                WHEN 'practice_attempt' THEN 'practice_attempt_ids'
                WHEN 'exercise_audio_lineage' THEN 'exercise_audio_lineage_ids'
                WHEN 'exercise_blind_packet' THEN 'exercise_blind_packet_ids'
                ELSE NULL END;
            IF locator_key IS NULL
               OR length(COALESCE(item_metadata->>'dependency_code', '')) = 0
               OR ref <> ('dependency:' || (item_metadata->>'dependency_code'))
               OR length(COALESCE(item_metadata->>'relation', '')) = 0
               OR length(COALESCE(item_metadata->>'selector_column', '')) = 0
               OR jsonb_typeof(item_metadata->'locator_values') <> 'array'
               OR item_metadata->'locator_values' IS DISTINCT FROM
                  p_subject_graph->locator_key
            THEN RAISE EXCEPTION 'PURGE_DEPENDENCY_TARGET_GRAPH_MISMATCH'; END IF;
        ELSIF kind IN ('r2_object', 'supabase_object') THEN
            IF item_metadata->>'source_relation' = 'processing_audio_objects' THEN
                IF NOT EXISTS (
                    SELECT 1 FROM public.processing_audio_objects object_row
                     WHERE object_row.id =
                           (item_metadata->>'source_id')::uuid
                       AND object_row.acquisition_principal_id =
                           req.acquisition_principal_id
                       AND object_row.storage_provider = item_metadata->>'provider'
                       AND object_row.bucket = item_metadata->>'bucket'
                       AND object_row.object_key = item_metadata->>'key'
                       AND object_row.exact_bytes_sha256 =
                           lower(item_metadata->>'sha256')
                ) THEN RAISE EXCEPTION 'PURGE_STORAGE_TARGET_GRAPH_MISMATCH'; END IF;
            ELSIF item_metadata->>'source_relation' =
                  'processing_orphan_objects' THEN
                IF NOT EXISTS (
                    SELECT 1 FROM public.processing_orphan_objects object_row
                     WHERE object_row.id =
                           (item_metadata->>'source_id')::uuid
                       AND object_row.acquisition_principal_id =
                           req.acquisition_principal_id
                       AND object_row.storage_provider = item_metadata->>'provider'
                       AND object_row.bucket = item_metadata->>'bucket'
                       AND object_row.object_key = item_metadata->>'key'
                       AND object_row.exact_bytes_sha256 =
                           lower(item_metadata->>'sha256')
                ) THEN RAISE EXCEPTION 'PURGE_STORAGE_TARGET_GRAPH_MISMATCH'; END IF;
            ELSE
                RAISE EXCEPTION 'PURGE_STORAGE_TARGET_SOURCE_INVALID';
            END IF;
            IF (kind = 'r2_object') IS DISTINCT FROM
               (item_metadata->>'provider' = 'r2')
            THEN RAISE EXCEPTION 'PURGE_STORAGE_TARGET_KIND_MISMATCH'; END IF;
        ELSIF kind = 'provider_operation' THEN
            IF NOT EXISTS (
                SELECT 1
                  FROM public.processing_provider_operations operation
                  JOIN public.processing_provider_permits permit
                    ON permit.id = operation.permit_id
                 WHERE operation.id =
                       (item_metadata->>'provider_operation_id')::uuid
                   AND permit.acquisition_principal_id =
                       req.acquisition_principal_id
                   AND permit.provider = item_metadata->>'provider'
                   AND permit.operation_kind = item_metadata->>'operation_kind'
                   AND operation.provider_operation_ref IS NOT DISTINCT FROM
                       item_metadata->>'provider_operation_ref'
            ) THEN RAISE EXCEPTION 'PURGE_PROVIDER_TARGET_GRAPH_MISMATCH'; END IF;
        ELSIF kind <> 'unknown' THEN
            RAISE EXCEPTION 'PURGE_TARGET_SOURCE_INVALID';
        END IF;
        item_state := CASE WHEN kind = 'unknown' THEN 'unknown' ELSE 'pending' END;
        INSERT INTO public.data_purge_targets (
            purge_request_id, target_kind, target_ref, resolver_version,
            state, initial_match_count, metadata
        ) VALUES (
            p_purge_request_id, kind, ref, p_resolver_version, item_state,
            GREATEST(0, COALESCE((item->>'initial_match_count')::integer, 0)),
            item_metadata
        ) ON CONFLICT (purge_request_id, target_kind, target_ref) DO NOTHING;
    END LOOP;
    FOREACH ref IN ARRAY COALESCE(p_catalog_unknown_relations, '{}'::text[]) LOOP
        INSERT INTO public.data_purge_targets (
            purge_request_id, target_kind, target_ref, resolver_version,
            state, metadata
        ) VALUES (
            p_purge_request_id, 'unknown', 'catalog:' || ref,
            p_resolver_version, 'unknown',
            jsonb_build_object('reason_code', 'UNCLASSIFIED_SUBJECT_RELATION')
        ) ON CONFLICT (purge_request_id, target_kind, target_ref) DO NOTHING;
    END LOOP;
    SELECT count(*) INTO unknown_count FROM public.data_purge_targets
     WHERE purge_request_id = p_purge_request_id AND state = 'unknown';
    UPDATE public.data_purge_requests
       SET state = CASE WHEN unknown_count > 0
                        THEN 'review_required' ELSE 'in_progress' END
     WHERE id = p_purge_request_id;
    RETURN jsonb_build_object(
        'purge_request_id', p_purge_request_id,
        'state', CASE WHEN unknown_count > 0
                      THEN 'review_required' ELSE 'in_progress' END,
        'unknown_target_count', unknown_count,
        'inventory_sha256', computed_target_manifest_sha256
    );
END;
$$;

REVOKE ALL ON FUNCTION public.resolve_phase1_purge_subject_graph_v2(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.resolve_phase1_purge_subject_graph_v2(UUID)
    TO service_role;
REVOKE ALL ON FUNCTION public.freeze_phase1_purge_inventory_v4(
    UUID,TEXT,TEXT,JSONB,JSONB,TEXT,TEXT[]
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.freeze_phase1_purge_inventory_v4(
    UUID,TEXT,TEXT,JSONB,JSONB,TEXT,TEXT[]
) TO service_role;

-- ── RLS, append-only enforcement, and RPC-only writes ───────────────────

DO $$
DECLARE table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'exercise_need_contracts', 'exercise_media_objects',
        'exercise_definitions', 'exercise_versions',
        'exercise_catalog_snapshots', 'exercise_catalog_snapshot_items',
        'exercise_authorization_checks', 'learning_profiles',
        'exercise_audio_lineages', 'exercise_blind_packets',
        'exercise_blind_packet_events'
    ] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format(
            'REVOKE ALL ON TABLE public.%I FROM anon, authenticated, service_role',
            table_name
        );
        EXECUTE format('GRANT SELECT ON TABLE public.%I TO service_role', table_name);
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON public.%I',
                       table_name || '_append_only', table_name);
        EXECUTE format(
            'CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON public.%I '
            'FOR EACH ROW EXECUTE FUNCTION public.reject_mlc2_immutable_mutation()',
            table_name || '_append_only', table_name
        );
    END LOOP;
END;
$$;

REVOKE ALL ON FUNCTION public.validate_exercise_blind_event_sequence_v1()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.validate_exercise_blind_packet_lineage_v1()
    FROM PUBLIC, anon, authenticated, service_role;

REVOKE ALL ON FUNCTION public.register_exercise_need_contract_v1(
    TEXT,INTEGER,TEXT,JSONB,TEXT[],TEXT[],TEXT[],JSONB,TEXT,TEXT,TEXT,TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.register_exercise_need_contract_v1(
    TEXT,INTEGER,TEXT,JSONB,TEXT[],TEXT[],TEXT[],JSONB,TEXT,TEXT,TEXT,TEXT
) TO service_role;

REVOKE ALL ON FUNCTION public.register_exercise_media_object_v1(
    TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TIMESTAMPTZ,TEXT,TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.register_exercise_media_object_v1(
    TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TIMESTAMPTZ,TEXT,TEXT
) TO service_role;

REVOKE ALL ON FUNCTION public.register_exercise_version_v1(
    TEXT,TEXT,UUID,TEXT,INTEGER,UUID,UUID,TEXT,TEXT,TEXT,TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.register_exercise_version_v1(
    TEXT,TEXT,UUID,TEXT,INTEGER,UUID,UUID,TEXT,TEXT,TEXT,TEXT
) TO service_role;

REVOKE ALL ON FUNCTION public.finalize_exercise_catalog_snapshot_v1(
    TEXT,TEXT,TIMESTAMPTZ,TEXT,TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.finalize_exercise_catalog_snapshot_v1(
    TEXT,TEXT,TIMESTAMPTZ,TEXT,TEXT
) TO service_role;

REVOKE ALL ON FUNCTION public.record_exercise_authorization_check_v1(
    UUID,UUID,TEXT,TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_exercise_authorization_check_v1(
    UUID,UUID,TEXT,TEXT
) TO service_role;

REVOKE ALL ON FUNCTION public.require_current_exercise_authorization_v1(
    UUID,UUID,TEXT
) FROM PUBLIC, anon, authenticated, service_role;

REVOKE ALL ON FUNCTION public.ensure_learning_profile_v1(
    UUID,UUID,UUID,TEXT,TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ensure_learning_profile_v1(
    UUID,UUID,UUID,TEXT,TEXT
) TO service_role;

REVOKE ALL ON FUNCTION public.register_exercise_audio_lineage_v1(
    UUID,UUID,UUID,UUID,UUID,UUID,UUID,UUID,UUID,UUID,
    INTEGER,INTEGER,TEXT,TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.register_exercise_audio_lineage_v1(
    UUID,UUID,UUID,UUID,UUID,UUID,UUID,UUID,UUID,UUID,
    INTEGER,INTEGER,TEXT,TEXT
) TO service_role;

REVOKE ALL ON FUNCTION public.register_exercise_blind_packet_v1(
    UUID,UUID,UUID,TEXT,TEXT,TEXT,TIMESTAMPTZ,INTEGER,TEXT,TEXT,TEXT,
    TEXT,TEXT,TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.register_exercise_blind_packet_v1(
    UUID,UUID,UUID,TEXT,TEXT,TEXT,TIMESTAMPTZ,INTEGER,TEXT,TEXT,TEXT,
    TEXT,TEXT,TEXT
) TO service_role;

REVOKE ALL ON FUNCTION public.get_mlc3_exercise_foundation_health_v1()
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_mlc3_exercise_foundation_health_v1()
    TO service_role;

COMMENT ON TABLE public.exercise_need_contracts IS
    'Immutable acoustic-need feature contracts. No contract is seeded or approved by M3-2.';
COMMENT ON TABLE public.exercise_catalog_snapshots IS
    'Server-computed complete catalogue universe as of one immutable cutoff; this is not an exposure or candidate assignment.';
COMMENT ON TABLE public.exercise_audio_lineages IS
    'Exact clip coordinates bound to the verified bytes SHA-256 of one R2 recording object.';
COMMENT ON TABLE public.learning_profiles IS
    'Stable pseudonymous profile identity only; it contains no trait, diagnosis, label, or biometric identity inference.';
COMMENT ON TABLE public.exercise_blind_packets IS
    'Typed RPC-only storage for the exact confidence-exercise-blind-packet-v1 allowlist. M3-2 creates no runtime packet producer or user/coach route.';

COMMIT;
