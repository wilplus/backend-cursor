-- 0302 · MLC-2 / ED-2.4 canonical learning foundation.
--
-- Additive and dark by default.  This migration creates the authoritative
-- registry, identity/split, consent-snapshot, outbox/envelope, evidence,
-- artifact, blind-review and rendered-exposure foundations.  It does not
-- redirect a product write, import legacy learning data, create a dataset
-- release, train a model or activate a cutover.

BEGIN;

-- ── Immutable contract and semantic registries ────────────────────────────

CREATE OR REPLACE FUNCTION public.reject_mlc2_immutable_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'MLC-2 canonical records are append-only';
END;
$$;

CREATE TABLE IF NOT EXISTS public.ml_contract_epochs (
    learning_contract_version TEXT NOT NULL,
    data_epoch                 INTEGER NOT NULL CHECK (data_epoch > 0),
    specification_version      TEXT NOT NULL,
    dataset_creation_enabled   BOOLEAN NOT NULL DEFAULT false,
    training_enabled           BOOLEAN NOT NULL DEFAULT false,
    promotion_enabled          BOOLEAN NOT NULL DEFAULT false,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by                 TEXT NOT NULL,
    PRIMARY KEY (learning_contract_version, data_epoch),
    CONSTRAINT ml_contract_epoch_safe_defaults CHECK (
        NOT dataset_creation_enabled
        AND NOT training_enabled
        AND NOT promotion_enabled
    )
);

INSERT INTO public.ml_contract_epochs (
    learning_contract_version, data_epoch, specification_version, created_by
) VALUES ('MLC-2', 1, 'ED-2.4', 'founder_approved_ed_2_4')
ON CONFLICT (learning_contract_version, data_epoch) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.ml_learning_surfaces (
    id                         TEXT PRIMARY KEY,
    description                TEXT NOT NULL,
    trainable                  BOOLEAN NOT NULL DEFAULT true,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO public.ml_learning_surfaces (id, description) VALUES
    ('confidence_classification', 'Confidence prediction and classifier-score ranking'),
    ('correction_generation', 'Evidence-backed verbal or structure rewrite generation'),
    ('coach_comment_generation', 'Machine draft to immutable coach final comment'),
    ('praise_generation', 'Evidence-backed praise wording generation'),
    ('praise_selection', 'Selection among admissible praise candidates'),
    ('correction_selection', 'Selection among admissible correction candidates'),
    ('ideal_text_generation', 'Canonical Ideal Text generation and version lineage')
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.ml_learning_surface_aliases (
    alias                      TEXT PRIMARY KEY,
    learning_surface_id       TEXT NULL
        REFERENCES public.ml_learning_surfaces(id) ON DELETE RESTRICT,
    canonical_writes_allowed  BOOLEAN NOT NULL DEFAULT true,
    reason                    TEXT NOT NULL,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ml_alias_resolution_check CHECK (
        (canonical_writes_allowed AND learning_surface_id IS NOT NULL)
        OR (NOT canonical_writes_allowed)
    )
);

INSERT INTO public.ml_learning_surface_aliases (
    alias, learning_surface_id, canonical_writes_allowed, reason
) VALUES
    ('say_it_stronger', 'correction_generation', true,
     'Explicit product/runtime alias only'),
    ('coach_comment_draft', 'coach_comment_generation', true,
     'Explicit product/runtime alias only'),
    ('ideal_text', 'ideal_text_generation', true,
     'Explicit product/runtime alias only'),
    ('moment_suggestion', NULL, false,
     'Ambiguous legacy vocabulary; rejected for canonical writes')
ON CONFLICT (alias) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.ml_feedback_families (
    id          TEXT PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO public.ml_feedback_families (id) VALUES
    ('confident_voice'), ('great_formulation'), ('rewrite_clarity')
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.ml_pipeline_stages (
    id          TEXT PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO public.ml_pipeline_stages (id) VALUES
    ('classify'), ('generate'), ('select')
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.ml_product_operations (
    id          TEXT PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO public.ml_product_operations (id) VALUES
    ('replace'), ('lock'), ('unlock'), ('style_orange'),
    ('remove_orange'), ('none')
ON CONFLICT (id) DO NOTHING;

-- ── Canonical speaker identity and stable split assignment ────────────────

CREATE TABLE IF NOT EXISTS public.ml_speakers (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    identity_version    TEXT NOT NULL,
    identity_hash       TEXT NOT NULL UNIQUE CHECK (length(identity_hash) = 64),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS public.ml_speaker_principals (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    speaker_id               UUID NOT NULL
        REFERENCES public.ml_speakers(id) ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    binding_kind             TEXT NOT NULL CHECK (binding_kind IN (
        'initial', 'guest_claim', 'verified_account_link', 'manual_review'
    )),
    binding_proof_hash       TEXT NOT NULL CHECK (length(binding_proof_hash) = 64),
    bound_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    bound_by                 TEXT NOT NULL,
    UNIQUE (acquisition_principal_id),
    UNIQUE (speaker_id, acquisition_principal_id)
);

CREATE TABLE IF NOT EXISTS public.ml_split_policies (
    version                 TEXT PRIMARY KEY,
    train_percent           INTEGER NOT NULL,
    validation_percent      INTEGER NOT NULL,
    test_percent            INTEGER NOT NULL,
    hash_algorithm          TEXT NOT NULL,
    salt_version            TEXT NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ml_split_percentages_check CHECK (
        train_percent >= 0 AND validation_percent >= 0 AND test_percent >= 0
        AND train_percent + validation_percent + test_percent = 100
    )
);

INSERT INTO public.ml_split_policies (
    version, train_percent, validation_percent, test_percent,
    hash_algorithm, salt_version
) VALUES (
    'speaker-sha256-80-10-10-v1', 80, 10, 10, 'sha256', 'mlc2-split-v1'
) ON CONFLICT (version) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.ml_speaker_split_assignments (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    speaker_id          UUID NOT NULL
        REFERENCES public.ml_speakers(id) ON DELETE RESTRICT,
    split_policy_version TEXT NOT NULL
        REFERENCES public.ml_split_policies(version) ON DELETE RESTRICT,
    split               TEXT NOT NULL CHECK (split IN (
        'train', 'validation', 'test'
    )),
    assignment_hash     TEXT NOT NULL CHECK (length(assignment_hash) = 64),
    assigned_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (speaker_id, split_policy_version),
    UNIQUE (id, speaker_id, split_policy_version)
);

CREATE OR REPLACE FUNCTION public.assign_ml_speaker_split_v1(
    p_speaker_id UUID,
    p_split_policy_version TEXT DEFAULT 'speaker-sha256-80-10-10-v1'
) RETURNS public.ml_speaker_split_assignments
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    policy public.ml_split_policies;
    assignment public.ml_speaker_split_assignments;
    hash_value TEXT;
    bucket INTEGER;
    selected_split TEXT;
BEGIN
    SELECT * INTO policy
      FROM public.ml_split_policies
     WHERE version = p_split_policy_version;
    IF policy.version IS NULL THEN
        RAISE EXCEPTION 'unknown ML split policy';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.ml_speakers WHERE id = p_speaker_id) THEN
        RAISE EXCEPTION 'unresolved ML speaker';
    END IF;

    hash_value := encode(digest(
        p_speaker_id::text || ':' || policy.salt_version, 'sha256'
    ), 'hex');
    bucket := (('x' || substr(hash_value, 1, 8))::bit(32)::bigint % 100)::integer;
    selected_split := CASE
        WHEN bucket < policy.train_percent THEN 'train'
        WHEN bucket < policy.train_percent + policy.validation_percent
            THEN 'validation'
        ELSE 'test'
    END;

    INSERT INTO public.ml_speaker_split_assignments (
        speaker_id, split_policy_version, split, assignment_hash
    ) VALUES (
        p_speaker_id, p_split_policy_version, selected_split, hash_value
    ) ON CONFLICT (speaker_id, split_policy_version) DO NOTHING;

    SELECT * INTO assignment
      FROM public.ml_speaker_split_assignments
     WHERE speaker_id = p_speaker_id
       AND split_policy_version = p_split_policy_version;
    RETURN assignment;
END;
$$;

-- ── Product/legal approval, authorization and immutable snapshots ─────────

CREATE TABLE IF NOT EXISTS public.ml_product_legal_approvals (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    approval_reference       TEXT NOT NULL UNIQUE,
    approved_copy_sha256     TEXT NOT NULL CHECK (length(approved_copy_sha256) = 64),
    onboarding_copy          TEXT NOT NULL,
    consent_policy_version   TEXT NOT NULL,
    terms_version            TEXT NOT NULL,
    privacy_policy_version   TEXT NOT NULL,
    approving_authority      TEXT NOT NULL,
    approved_at              TIMESTAMPTZ NOT NULL,
    jurisdictions            TEXT[] NOT NULL CHECK (cardinality(jurisdictions) > 0),
    article_6_basis          TEXT NOT NULL CHECK (article_6_basis = '6(1)(a)'),
    article_9_treatment      TEXT NOT NULL CHECK (article_9_treatment IN (
        'not_applicable', '9(2)(a)_when_special_category'
    )),
    evidence_object_key      TEXT NOT NULL,
    evidence_sha256          TEXT NOT NULL CHECK (length(evidence_sha256) = 64),
    recorded_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.ml_consent_policies (
    version                    TEXT PRIMARY KEY,
    product_legal_approval_id  UUID NOT NULL
        REFERENCES public.ml_product_legal_approvals(id) ON DELETE RESTRICT,
    required_for_service       BOOLEAN NOT NULL CHECK (required_for_service),
    bundled_ui                 BOOLEAN NOT NULL CHECK (bundled_ui),
    active_from                TIMESTAMPTZ NOT NULL,
    retired_at                 TIMESTAMPTZ NULL,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ml_consent_policy_dates_check CHECK (
        retired_at IS NULL OR retired_at > active_from
    )
);

CREATE TABLE IF NOT EXISTS public.ml_consent_events (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    consent_policy_version   TEXT NOT NULL
        REFERENCES public.ml_consent_policies(version) ON DELETE RESTRICT,
    product_legal_approval_id UUID NOT NULL
        REFERENCES public.ml_product_legal_approvals(id) ON DELETE RESTRICT,
    accepted_copy_sha256     TEXT NOT NULL CHECK (length(accepted_copy_sha256) = 64),
    event_kind               TEXT NOT NULL CHECK (event_kind IN (
        'grant', 'withdraw'
    )),
    jurisdiction             TEXT NOT NULL,
    terms_version            TEXT NOT NULL,
    privacy_policy_version   TEXT NOT NULL,
    source_route             TEXT NOT NULL,
    client_version           TEXT NOT NULL,
    affirmative_action       JSONB NOT NULL CHECK (
        jsonb_typeof(affirmative_action) = 'object'
    ),
    occurred_at              TIMESTAMPTZ NOT NULL,
    received_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    idempotency_key          TEXT NOT NULL UNIQUE,
    supersedes_event_id      UUID NULL
        REFERENCES public.ml_consent_events(id) ON DELETE RESTRICT,
    CONSTRAINT ml_consent_withdrawal_lineage_check CHECK (
        (event_kind = 'grant' AND supersedes_event_id IS NULL)
        OR (event_kind = 'withdraw' AND supersedes_event_id IS NOT NULL)
    ),
    UNIQUE (id, acquisition_principal_id, consent_policy_version)
);

CREATE TABLE IF NOT EXISTS public.ml_consent_event_purposes (
    consent_event_id         UUID NOT NULL
        REFERENCES public.ml_consent_events(id) ON DELETE RESTRICT,
    purpose                  TEXT NOT NULL CHECK (purpose IN (
        'personalized_coaching', 'pooled_model_improvement'
    )),
    article_6_basis          TEXT NOT NULL CHECK (article_6_basis = '6(1)(a)'),
    article_9_basis          TEXT NULL CHECK (
        article_9_basis IS NULL OR article_9_basis = '9(2)(a)'
    ),
    PRIMARY KEY (consent_event_id, purpose)
);

CREATE TABLE IF NOT EXISTS public.ml_consent_snapshots (
    id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id   UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    grant_event_id             UUID NOT NULL
        REFERENCES public.ml_consent_events(id) ON DELETE RESTRICT,
    consent_policy_version     TEXT NOT NULL
        REFERENCES public.ml_consent_policies(version) ON DELETE RESTRICT,
    recording_attempt_id       UUID NULL
        REFERENCES public.recording_attempts(id) ON DELETE RESTRICT,
    take_id                    UUID NULL
        REFERENCES public.takes(id) ON DELETE RESTRICT,
    project_id                 UUID NULL
        REFERENCES public.projects(id) ON DELETE RESTRICT,
    captured_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    purpose_state              JSONB NOT NULL CHECK (
        jsonb_typeof(purpose_state) = 'object'
        AND purpose_state ? 'personalized_coaching'
        AND purpose_state ? 'pooled_model_improvement'
    ),
    retention_state            TEXT NOT NULL CHECK (retention_state IN (
        'eligible', 'withdrawn', 'expired', 'legal_hold', 'purge_pending'
    )),
    snapshot_sha256             TEXT NOT NULL CHECK (length(snapshot_sha256) = 64),
    UNIQUE (snapshot_sha256),
    UNIQUE (id, acquisition_principal_id),
    CONSTRAINT ml_consent_snapshot_grant_fk FOREIGN KEY (
        grant_event_id, acquisition_principal_id, consent_policy_version
    ) REFERENCES public.ml_consent_events(
        id, acquisition_principal_id, consent_policy_version
    ) ON DELETE RESTRICT,
    CONSTRAINT ml_consent_snapshot_lineage_check CHECK (
        recording_attempt_id IS NOT NULL OR take_id IS NOT NULL
    )
);

-- ── Transactional outbox and canonical event envelope ────────────────────

CREATE TABLE IF NOT EXISTS public.ml_outbox_events (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key          TEXT NOT NULL UNIQUE,
    event_type               TEXT NOT NULL,
    learning_surface_id      TEXT NOT NULL
        REFERENCES public.ml_learning_surfaces(id) ON DELETE RESTRICT,
    aggregate_type           TEXT NOT NULL,
    aggregate_id             UUID NOT NULL,
    payload                  JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    occurred_at              TIMESTAMPTZ NOT NULL,
    available_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    attempt_count            INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    processing_started_at    TIMESTAMPTZ NULL,
    locked_by                TEXT NULL,
    lease_expires_at         TIMESTAMPTZ NULL,
    processed_at             TIMESTAMPTZ NULL,
    last_error_code          TEXT NULL,
    last_error_at            TIMESTAMPTZ NULL,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ml_outbox_state_check CHECK (
        (processed_at IS NULL OR last_error_code IS NULL)
        AND ((locked_by IS NULL AND lease_expires_at IS NULL)
             OR (locked_by IS NOT NULL AND lease_expires_at IS NOT NULL))
    )
);

CREATE INDEX IF NOT EXISTS ml_outbox_available_idx
    ON public.ml_outbox_events (available_at, created_at)
    WHERE processed_at IS NULL;
CREATE INDEX IF NOT EXISTS ml_outbox_failed_idx
    ON public.ml_outbox_events (last_error_at DESC)
    WHERE processed_at IS NULL AND last_error_code IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.ml_canonical_events (
    id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id                   UUID NOT NULL UNIQUE,
    idempotency_key            TEXT NOT NULL UNIQUE,
    source_outbox_event_id     UUID NOT NULL UNIQUE
        REFERENCES public.ml_outbox_events(id) ON DELETE RESTRICT,
    learning_contract_version TEXT NOT NULL,
    data_epoch                 INTEGER NOT NULL,
    learning_surface_id        TEXT NOT NULL
        REFERENCES public.ml_learning_surfaces(id) ON DELETE RESTRICT,
    pipeline_stage_id          TEXT NOT NULL
        REFERENCES public.ml_pipeline_stages(id) ON DELETE RESTRICT,
    feedback_family_id         TEXT NULL
        REFERENCES public.ml_feedback_families(id) ON DELETE RESTRICT,
    acquisition_principal_id   UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    speaker_id                 UUID NOT NULL
        REFERENCES public.ml_speakers(id) ON DELETE RESTRICT,
    consent_snapshot_id        UUID NOT NULL
        REFERENCES public.ml_consent_snapshots(id) ON DELETE RESTRICT,
    project_id                 UUID NULL
        REFERENCES public.projects(id) ON DELETE RESTRICT,
    recording_attempt_id       UUID NULL
        REFERENCES public.recording_attempts(id) ON DELETE RESTRICT,
    take_id                    UUID NULL
        REFERENCES public.takes(id) ON DELETE RESTRICT,
    clip_id                    UUID NULL,
    evidence_locator           JSONB NOT NULL CHECK (
        jsonb_typeof(evidence_locator) = 'object'
    ),
    execution_version          JSONB NOT NULL CHECK (
        jsonb_typeof(execution_version) = 'object'
    ),
    payload_type               TEXT NOT NULL,
    payload                    JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    source_event_id            TEXT NOT NULL,
    occurred_at                TIMESTAMPTZ NOT NULL,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ml_canonical_event_epoch_fk FOREIGN KEY (
        learning_contract_version, data_epoch
    ) REFERENCES public.ml_contract_epochs(
        learning_contract_version, data_epoch
    ) ON DELETE RESTRICT,
    CONSTRAINT ml_canonical_event_speaker_principal_fk FOREIGN KEY (
        speaker_id, acquisition_principal_id
    ) REFERENCES public.ml_speaker_principals(
        speaker_id, acquisition_principal_id
    ) ON DELETE RESTRICT,
    CONSTRAINT ml_canonical_event_consent_principal_fk FOREIGN KEY (
        consent_snapshot_id, acquisition_principal_id
    ) REFERENCES public.ml_consent_snapshots(
        id, acquisition_principal_id
    ) ON DELETE RESTRICT,
    CONSTRAINT ml_canonical_event_payload_type_check CHECK (
        payload_type = CASE learning_surface_id
            WHEN 'confidence_classification' THEN 'confidence_event'
            WHEN 'correction_generation' THEN 'correction_generation_event'
            WHEN 'coach_comment_generation' THEN 'coach_comment_event'
            WHEN 'praise_generation' THEN 'praise_generation_event'
            WHEN 'praise_selection' THEN 'praise_selection_event'
            WHEN 'correction_selection' THEN 'correction_selection_event'
            WHEN 'ideal_text_generation' THEN 'ideal_text_event'
        END
    ),
    CONSTRAINT ml_canonical_feedback_family_check CHECK (
        (learning_surface_id IN (
            'confidence_classification', 'correction_generation',
            'praise_generation', 'praise_selection', 'correction_selection'
        ) AND feedback_family_id IS NOT NULL)
        OR (learning_surface_id IN (
            'coach_comment_generation', 'ideal_text_generation'
        ) AND feedback_family_id IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS ml_canonical_events_surface_time_idx
    ON public.ml_canonical_events (learning_surface_id, occurred_at, id);
CREATE INDEX IF NOT EXISTS ml_canonical_events_speaker_time_idx
    ON public.ml_canonical_events (speaker_id, occurred_at, id);
CREATE INDEX IF NOT EXISTS ml_canonical_events_take_idx
    ON public.ml_canonical_events (take_id, learning_surface_id)
    WHERE take_id IS NOT NULL;

-- ── Evidence and immutable semantic / object artifacts ───────────────────

CREATE TABLE IF NOT EXISTS public.ml_object_artifacts (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    speaker_id               UUID NOT NULL
        REFERENCES public.ml_speakers(id) ON DELETE RESTRICT,
    consent_snapshot_id      UUID NOT NULL
        REFERENCES public.ml_consent_snapshots(id) ON DELETE RESTRICT,
    object_store             TEXT NOT NULL CHECK (object_store = 'cloudflare_r2'),
    bucket                   TEXT NOT NULL,
    object_key               TEXT NOT NULL UNIQUE,
    sha256                   TEXT NOT NULL CHECK (length(sha256) = 64),
    byte_size                BIGINT NOT NULL CHECK (byte_size >= 0),
    content_type             TEXT NOT NULL,
    artifact_kind            TEXT NOT NULL CHECK (artifact_kind IN (
        'audio', 'dataset_manifest', 'dataset_file', 'evaluation_report',
        'model_metadata', 'model_artifact', 'adapter', 'other'
    )),
    retention_status         TEXT NOT NULL CHECK (retention_status IN (
        'eligible', 'legal_hold', 'purge_pending', 'invalidated'
    )),
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by               TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ml_object_artifacts_content_hash_idx
    ON public.ml_object_artifacts (sha256);

CREATE TABLE IF NOT EXISTS public.ml_object_verifications (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    object_artifact_id  UUID NOT NULL
        REFERENCES public.ml_object_artifacts(id) ON DELETE RESTRICT,
    observed_sha256     TEXT NOT NULL CHECK (length(observed_sha256) = 64),
    observed_byte_size  BIGINT NOT NULL CHECK (observed_byte_size >= 0),
    verified            BOOLEAN NOT NULL,
    verification_method TEXT NOT NULL,
    verified_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    verifier_version    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS public.ml_evidence_spans (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_event_id       UUID NOT NULL
        REFERENCES public.ml_canonical_events(id) ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    speaker_id               UUID NOT NULL
        REFERENCES public.ml_speakers(id) ON DELETE RESTRICT,
    project_id               UUID NOT NULL
        REFERENCES public.projects(id) ON DELETE RESTRICT,
    recording_attempt_id     UUID NOT NULL
        REFERENCES public.recording_attempts(id) ON DELETE RESTRICT,
    take_id                  UUID NOT NULL
        REFERENCES public.takes(id) ON DELETE RESTRICT,
    object_artifact_id       UUID NULL
        REFERENCES public.ml_object_artifacts(id) ON DELETE RESTRICT,
    modality                 TEXT NOT NULL CHECK (modality IN (
        'audio', 'text', 'audio_text'
    )),
    coordinates              JSONB NOT NULL CHECK (jsonb_typeof(coordinates) = 'object'),
    content_sha256           TEXT NOT NULL CHECK (length(content_sha256) = 64),
    evidence_schema_version  TEXT NOT NULL,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ml_evidence_speaker_take_idx
    ON public.ml_evidence_spans (speaker_id, take_id, created_at);
CREATE INDEX IF NOT EXISTS ml_evidence_content_hash_idx
    ON public.ml_evidence_spans (content_sha256);

CREATE TABLE IF NOT EXISTS public.ml_semantic_artifacts (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_event_id    UUID NOT NULL
        REFERENCES public.ml_canonical_events(id) ON DELETE RESTRICT,
    learning_surface_id   TEXT NOT NULL
        REFERENCES public.ml_learning_surfaces(id) ON DELETE RESTRICT,
    pipeline_stage_id     TEXT NOT NULL
        REFERENCES public.ml_pipeline_stages(id) ON DELETE RESTRICT,
    feedback_family_id    TEXT NULL
        REFERENCES public.ml_feedback_families(id) ON DELETE RESTRICT,
    evidence_span_id      UUID NULL
        REFERENCES public.ml_evidence_spans(id) ON DELETE RESTRICT,
    artifact_type         TEXT NOT NULL CHECK (artifact_type IN (
        'generated_rewrite', 'generated_praise', 'coach_comment_draft',
        'coach_comment_final', 'ideal_text_version'
    )),
    semantic_version      TEXT NOT NULL,
    content               JSONB NOT NULL CHECK (jsonb_typeof(content) = 'object'),
    content_sha256        TEXT NOT NULL CHECK (length(content_sha256) = 64),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ml_semantic_artifact_family_check CHECK (
        (learning_surface_id IN (
            'confidence_classification', 'correction_generation',
            'praise_generation', 'praise_selection', 'correction_selection'
        ) AND feedback_family_id IS NOT NULL)
        OR (learning_surface_id IN (
            'coach_comment_generation', 'ideal_text_generation'
        ) AND feedback_family_id IS NULL)
    ),
    CONSTRAINT ml_semantic_artifact_surface_type_check CHECK (
        pipeline_stage_id = 'generate'
        AND (
            (learning_surface_id = 'correction_generation'
             AND artifact_type = 'generated_rewrite')
            OR (learning_surface_id = 'praise_generation'
                AND artifact_type = 'generated_praise')
            OR (learning_surface_id = 'coach_comment_generation'
                AND artifact_type IN (
                    'coach_comment_draft', 'coach_comment_final'
                ))
            OR (learning_surface_id = 'ideal_text_generation'
                AND artifact_type = 'ideal_text_version')
        )
    )
);

CREATE INDEX IF NOT EXISTS ml_semantic_artifact_hash_idx
    ON public.ml_semantic_artifacts (content_sha256);

-- ── Blind review assignments, judgments and product-only actions ─────────

CREATE TABLE IF NOT EXISTS public.ml_review_assignments (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    learning_surface_id      TEXT NOT NULL
        REFERENCES public.ml_learning_surfaces(id) ON DELETE RESTRICT,
    evidence_span_id         UUID NOT NULL
        REFERENCES public.ml_evidence_spans(id) ON DELETE RESTRICT,
    reviewer_principal_id    UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    reviewer_role            TEXT NOT NULL CHECK (reviewer_role IN (
        'coach', 'peer'
    )),
    blind_packet_sha256      TEXT NOT NULL CHECK (length(blind_packet_sha256) = 64),
    taxonomy_version         TEXT NOT NULL,
    blindness_policy_version TEXT NOT NULL,
    assigned_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at               TIMESTAMPTZ NULL,
    idempotency_key          TEXT NOT NULL UNIQUE,
    CONSTRAINT ml_review_assignment_expiry_check CHECK (
        expires_at IS NULL OR expires_at > assigned_at
    ),
    UNIQUE (id, reviewer_principal_id)
);

CREATE TABLE IF NOT EXISTS public.ml_review_assignment_events (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    review_assignment_id     UUID NOT NULL
        REFERENCES public.ml_review_assignments(id) ON DELETE RESTRICT,
    event_kind               TEXT NOT NULL CHECK (event_kind IN (
        'assigned', 'opened', 'submitted', 'revealed', 'expired', 'cancelled'
    )),
    occurred_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_principal_id       UUID NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    idempotency_key          TEXT NOT NULL UNIQUE,
    metadata                 JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (
        jsonb_typeof(metadata) = 'object'
    ),
    UNIQUE (review_assignment_id, event_kind)
);

CREATE TABLE IF NOT EXISTS public.ml_presentations (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_event_id       UUID NOT NULL
        REFERENCES public.ml_canonical_events(id) ON DELETE RESTRICT,
    learning_surface_id      TEXT NOT NULL
        REFERENCES public.ml_learning_surfaces(id) ON DELETE RESTRICT,
    artifact_id              UUID NULL
        REFERENCES public.ml_semantic_artifacts(id) ON DELETE RESTRICT,
    review_assignment_id     UUID NULL
        REFERENCES public.ml_review_assignments(id) ON DELETE RESTRICT,
    actor_principal_id       UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    actor_role               TEXT NOT NULL CHECK (actor_role IN (
        'owner', 'coach', 'peer'
    )),
    delivery_mode            TEXT NOT NULL CHECK (delivery_mode IN (
        'production', 'canary', 'shadow'
    )),
    evaluation_only          BOOLEAN NOT NULL,
    visible_payload_sha256   TEXT NOT NULL CHECK (length(visible_payload_sha256) = 64),
    acknowledgement_token    UUID NOT NULL DEFAULT gen_random_uuid(),
    idempotency_key          TEXT NOT NULL UNIQUE,
    prepared_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ml_presentation_shadow_check CHECK (
        delivery_mode <> 'shadow' OR evaluation_only
    ),
    CONSTRAINT ml_presentation_review_actor_fk FOREIGN KEY (
        review_assignment_id, actor_principal_id
    ) REFERENCES public.ml_review_assignments(
        id, reviewer_principal_id
    ) ON DELETE RESTRICT,
    UNIQUE (id, actor_principal_id, visible_payload_sha256)
);

CREATE TABLE IF NOT EXISTS public.ml_rendered_exposures (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    presentation_id          UUID NOT NULL
        REFERENCES public.ml_presentations(id) ON DELETE RESTRICT,
    actor_principal_id       UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    render_instance_id       UUID NOT NULL,
    client_rendered_at       TIMESTAMPTZ NOT NULL,
    authenticated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    client_version           TEXT NOT NULL,
    payload_sha256           TEXT NOT NULL CHECK (length(payload_sha256) = 64),
    idempotency_key          TEXT NOT NULL UNIQUE,
    UNIQUE (id, actor_principal_id),
    CONSTRAINT ml_rendered_exposure_presentation_fk FOREIGN KEY (
        presentation_id, actor_principal_id, payload_sha256
    ) REFERENCES public.ml_presentations(
        id, actor_principal_id, visible_payload_sha256
    ) ON DELETE RESTRICT,
    UNIQUE (presentation_id, render_instance_id)
);

CREATE TABLE IF NOT EXISTS public.ml_judgments (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    learning_surface_id      TEXT NOT NULL
        REFERENCES public.ml_learning_surfaces(id) ON DELETE RESTRICT,
    feedback_family_id       TEXT NOT NULL
        REFERENCES public.ml_feedback_families(id) ON DELETE RESTRICT,
    evidence_span_id         UUID NOT NULL
        REFERENCES public.ml_evidence_spans(id) ON DELETE RESTRICT,
    artifact_id              UUID NULL
        REFERENCES public.ml_semantic_artifacts(id) ON DELETE RESTRICT,
    exposure_id              UUID NOT NULL
        REFERENCES public.ml_rendered_exposures(id) ON DELETE RESTRICT,
    review_assignment_id     UUID NULL
        REFERENCES public.ml_review_assignments(id) ON DELETE RESTRICT,
    actor_principal_id       UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    actor_provenance         TEXT NOT NULL CHECK (actor_provenance IN (
        'user_self_report', 'blind_coach', 'blind_peer',
        'professional_evaluation'
    )),
    decision                 TEXT NOT NULL CHECK (decision IN (
        'confident_yes', 'confident_in_between', 'confident_no',
        'confident_not_sure', 'confident_audio_unclear',
        'rewrite_accept', 'rewrite_reject', 'rewrite_not_sure',
        'praise_useful', 'praise_not_useful', 'praise_not_sure',
        'rating_yes', 'rating_in_between', 'rating_no',
        'rating_not_sure', 'rating_audio_unclear',
        'professional_yes', 'professional_no', 'professional_refine'
    )),
    training_eligibility     TEXT NOT NULL CHECK (training_eligibility IN (
        'potentially_eligible', 'evaluation_only'
    )),
    supersedes_id            UUID NULL
        REFERENCES public.ml_judgments(id) ON DELETE RESTRICT,
    idempotency_key          TEXT NOT NULL UNIQUE,
    decided_at               TIMESTAMPTZ NOT NULL,
    recorded_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ml_judgment_provenance_check CHECK (
        (actor_provenance = 'user_self_report'
         AND decision LIKE 'confident_%'
         AND review_assignment_id IS NULL
         AND exposure_id IS NOT NULL)
        OR (actor_provenance IN ('blind_coach', 'blind_peer')
            AND decision LIKE 'rating_%'
            AND review_assignment_id IS NOT NULL
            AND exposure_id IS NOT NULL)
        OR (actor_provenance = 'professional_evaluation'
            AND decision LIKE 'professional_%'
            AND training_eligibility = 'evaluation_only'
            AND review_assignment_id IS NULL
            AND exposure_id IS NOT NULL)
        OR (actor_provenance = 'user_self_report'
            AND (decision LIKE 'rewrite_%' OR decision LIKE 'praise_%')
            AND exposure_id IS NOT NULL)
    ),
    CONSTRAINT ml_judgment_family_namespace_check CHECK (
        (decision LIKE 'confident_%' AND feedback_family_id = 'confident_voice')
        OR (decision LIKE 'rating_%' AND feedback_family_id = 'confident_voice')
        OR (decision LIKE 'professional_%' AND feedback_family_id = 'confident_voice')
        OR (decision LIKE 'rewrite_%' AND feedback_family_id = 'rewrite_clarity')
        OR (decision LIKE 'praise_%' AND feedback_family_id = 'great_formulation')
    ),
    CONSTRAINT ml_judgment_surface_namespace_check CHECK (
        (feedback_family_id = 'confident_voice'
         AND learning_surface_id = 'confidence_classification')
        OR (feedback_family_id = 'rewrite_clarity'
            AND learning_surface_id IN (
                'correction_generation', 'correction_selection'
            ))
        OR (feedback_family_id = 'great_formulation'
            AND learning_surface_id IN (
                'praise_generation', 'praise_selection'
            ))
    ),
    CONSTRAINT ml_judgment_review_actor_fk FOREIGN KEY (
        review_assignment_id, actor_principal_id
    ) REFERENCES public.ml_review_assignments(
        id, reviewer_principal_id
    ) ON DELETE RESTRICT,
    CONSTRAINT ml_judgment_exposure_actor_fk FOREIGN KEY (
        exposure_id, actor_principal_id
    ) REFERENCES public.ml_rendered_exposures(
        id, actor_principal_id
    ) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS public.ml_product_actions (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_event_id       UUID NOT NULL
        REFERENCES public.ml_canonical_events(id) ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    speaker_id               UUID NOT NULL
        REFERENCES public.ml_speakers(id) ON DELETE RESTRICT,
    product_operation_id     TEXT NOT NULL
        REFERENCES public.ml_product_operations(id) ON DELETE RESTRICT,
    decision                 TEXT NOT NULL CHECK (decision IN (
        'paragraph_lock', 'paragraph_leave_unlocked', 'paragraph_unlock',
        'orange_apply', 'orange_decline', 'orange_remove'
    )),
    paragraph_id             UUID NULL
        REFERENCES public.paragraphs(id) ON DELETE RESTRICT,
    artifact_id              UUID NULL
        REFERENCES public.ml_semantic_artifacts(id) ON DELETE RESTRICT,
    context                  JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (
        jsonb_typeof(context) = 'object'
    ),
    idempotency_key          TEXT NOT NULL UNIQUE,
    acted_at                 TIMESTAMPTZ NOT NULL,
    recorded_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ml_product_action_operation_check CHECK (
        (decision = 'paragraph_lock' AND product_operation_id = 'lock')
        OR (decision = 'paragraph_leave_unlocked' AND product_operation_id = 'none')
        OR (decision = 'paragraph_unlock' AND product_operation_id = 'unlock')
        OR (decision = 'orange_apply' AND product_operation_id = 'style_orange')
        OR (decision = 'orange_decline' AND product_operation_id = 'none')
        OR (decision = 'orange_remove' AND product_operation_id = 'remove_orange')
    )
);

CREATE TABLE IF NOT EXISTS public.ml_purge_requests (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    speaker_id               UUID NOT NULL
        REFERENCES public.ml_speakers(id) ON DELETE RESTRICT,
    withdrawal_event_id      UUID NULL
        REFERENCES public.ml_consent_events(id) ON DELETE RESTRICT,
    reason                   TEXT NOT NULL CHECK (reason IN (
        'consent_withdrawal', 'retention_expiry', 'lawful_deletion'
    )),
    requested_at             TIMESTAMPTZ NOT NULL,
    requested_by             TEXT NOT NULL,
    idempotency_key          TEXT NOT NULL UNIQUE,
    CONSTRAINT ml_purge_speaker_principal_fk FOREIGN KEY (
        speaker_id, acquisition_principal_id
    ) REFERENCES public.ml_speaker_principals(
        speaker_id, acquisition_principal_id
    ) ON DELETE RESTRICT,
    CONSTRAINT ml_purge_withdrawal_reason_check CHECK (
        (reason = 'consent_withdrawal' AND withdrawal_event_id IS NOT NULL)
        OR (reason <> 'consent_withdrawal')
    )
);

CREATE TABLE IF NOT EXISTS public.ml_purge_events (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    purge_request_id    UUID NOT NULL
        REFERENCES public.ml_purge_requests(id) ON DELETE RESTRICT,
    event_kind          TEXT NOT NULL CHECK (event_kind IN (
        'requested', 'traversal_started', 'lineage_invalidated',
        'object_retained_shared', 'object_deleted', 'completed', 'failed'
    )),
    entity_type         TEXT NULL,
    entity_id           UUID NULL,
    detail              JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (
        jsonb_typeof(detail) = 'object'
    ),
    occurred_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    idempotency_key     TEXT NOT NULL UNIQUE
);

-- ── Foundation write contracts ────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.register_ml_speaker_principal_v1(
    p_acquisition_principal_id UUID,
    p_identity_hash TEXT,
    p_identity_version TEXT,
    p_binding_kind TEXT,
    p_binding_proof_hash TEXT,
    p_bound_by TEXT,
    p_split_policy_version TEXT DEFAULT 'speaker-sha256-80-10-10-v1'
) RETURNS public.ml_speaker_principals
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    speaker public.ml_speakers;
    binding public.ml_speaker_principals;
BEGIN
    IF length(p_identity_hash) <> 64 OR length(p_binding_proof_hash) <> 64 THEN
        RAISE EXCEPTION 'identity and binding proof hashes must be SHA-256';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.owner_principals
         WHERE id = p_acquisition_principal_id
    ) THEN
        RAISE EXCEPTION 'unknown acquisition principal';
    END IF;

    SELECT * INTO binding
      FROM public.ml_speaker_principals
     WHERE acquisition_principal_id = p_acquisition_principal_id;
    IF binding.id IS NOT NULL THEN
        SELECT * INTO speaker FROM public.ml_speakers
         WHERE id = binding.speaker_id;
        IF speaker.identity_hash <> p_identity_hash THEN
            RAISE EXCEPTION 'principal is already bound to another speaker identity';
        END IF;
        RETURN binding;
    END IF;

    INSERT INTO public.ml_speakers (
        identity_version, identity_hash, created_by
    ) VALUES (p_identity_version, p_identity_hash, p_bound_by)
    ON CONFLICT (identity_hash) DO NOTHING;

    SELECT * INTO speaker FROM public.ml_speakers
     WHERE identity_hash = p_identity_hash;

    INSERT INTO public.ml_speaker_principals (
        speaker_id, acquisition_principal_id, binding_kind,
        binding_proof_hash, bound_by
    ) VALUES (
        speaker.id, p_acquisition_principal_id, p_binding_kind,
        p_binding_proof_hash, p_bound_by
    )
    RETURNING * INTO binding;

    PERFORM public.assign_ml_speaker_split_v1(
        speaker.id, p_split_policy_version
    );
    RETURN binding;
END;
$$;

CREATE OR REPLACE FUNCTION public.record_mlc2_consent_grant_v1(
    p_acquisition_principal_id UUID,
    p_consent_policy_version TEXT,
    p_jurisdiction TEXT,
    p_terms_version TEXT,
    p_privacy_policy_version TEXT,
    p_source_route TEXT,
    p_client_version TEXT,
    p_affirmative_action JSONB,
    p_occurred_at TIMESTAMPTZ,
    p_article_9_applies BOOLEAN,
    p_idempotency_key TEXT
) RETURNS public.ml_consent_events
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    policy public.ml_consent_policies;
    approval public.ml_product_legal_approvals;
    consent_event public.ml_consent_events;
BEGIN
    SELECT * INTO policy FROM public.ml_consent_policies
     WHERE version = p_consent_policy_version
       AND active_from <= p_occurred_at
       AND (retired_at IS NULL OR retired_at > p_occurred_at);
    IF policy.version IS NULL THEN
        RAISE EXCEPTION 'consent policy is not approved and active';
    END IF;
    SELECT * INTO approval FROM public.ml_product_legal_approvals
     WHERE id = policy.product_legal_approval_id;
    IF approval.id IS NULL
       OR p_terms_version <> approval.terms_version
       OR p_privacy_policy_version <> approval.privacy_policy_version
       OR p_affirmative_action ->> 'copy_sha256'
          IS DISTINCT FROM approval.approved_copy_sha256 THEN
        RAISE EXCEPTION 'consent does not match documented Product/legal approval';
    END IF;
    IF jsonb_typeof(p_affirmative_action) <> 'object'
       OR p_affirmative_action ->> 'accepted' IS DISTINCT FROM 'true' THEN
        RAISE EXCEPTION 'explicit affirmative consent is required';
    END IF;

    INSERT INTO public.ml_consent_events (
        acquisition_principal_id, consent_policy_version,
        product_legal_approval_id, accepted_copy_sha256, event_kind,
        jurisdiction, terms_version, privacy_policy_version, source_route,
        client_version, affirmative_action, occurred_at, idempotency_key
    ) VALUES (
        p_acquisition_principal_id, p_consent_policy_version, approval.id,
        approval.approved_copy_sha256, 'grant',
        p_jurisdiction, p_terms_version, p_privacy_policy_version,
        p_source_route, p_client_version, p_affirmative_action,
        p_occurred_at, p_idempotency_key
    ) ON CONFLICT (idempotency_key) DO NOTHING;

    SELECT * INTO consent_event FROM public.ml_consent_events
     WHERE idempotency_key = p_idempotency_key;
    IF consent_event.acquisition_principal_id <> p_acquisition_principal_id
       OR consent_event.event_kind <> 'grant' THEN
        RAISE EXCEPTION 'consent idempotency collision';
    END IF;

    INSERT INTO public.ml_consent_event_purposes (
        consent_event_id, purpose, article_6_basis, article_9_basis
    ) VALUES
        (consent_event.id, 'personalized_coaching', '6(1)(a)',
         CASE WHEN p_article_9_applies THEN '9(2)(a)' ELSE NULL END),
        (consent_event.id, 'pooled_model_improvement', '6(1)(a)',
         CASE WHEN p_article_9_applies THEN '9(2)(a)' ELSE NULL END)
    ON CONFLICT (consent_event_id, purpose) DO NOTHING;
    IF (SELECT count(*) FROM public.ml_consent_event_purposes purpose
         WHERE purpose.consent_event_id = consent_event.id
           AND purpose.article_6_basis = '6(1)(a)'
           AND purpose.article_9_basis IS NOT DISTINCT FROM CASE
               WHEN p_article_9_applies THEN '9(2)(a)' ELSE NULL
           END) <> 2 THEN
        RAISE EXCEPTION 'consent purpose idempotency collision';
    END IF;
    RETURN consent_event;
END;
$$;

CREATE OR REPLACE FUNCTION public.record_mlc2_consent_withdrawal_v1(
    p_acquisition_principal_id UUID,
    p_grant_event_id UUID,
    p_source_route TEXT,
    p_client_version TEXT,
    p_affirmative_action JSONB,
    p_occurred_at TIMESTAMPTZ,
    p_idempotency_key TEXT
) RETURNS public.ml_consent_events
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    grant_event public.ml_consent_events;
    withdrawal public.ml_consent_events;
    purge_request public.ml_purge_requests;
BEGIN
    SELECT * INTO grant_event FROM public.ml_consent_events
     WHERE id = p_grant_event_id
       AND acquisition_principal_id = p_acquisition_principal_id
       AND event_kind = 'grant';
    IF grant_event.id IS NULL THEN
        RAISE EXCEPTION 'matching consent grant not found';
    END IF;
    IF p_occurred_at < grant_event.occurred_at THEN
        RAISE EXCEPTION 'withdrawal cannot precede grant';
    END IF;

    INSERT INTO public.ml_consent_events (
        acquisition_principal_id, consent_policy_version,
        product_legal_approval_id, accepted_copy_sha256, event_kind,
        jurisdiction, terms_version, privacy_policy_version, source_route,
        client_version, affirmative_action, occurred_at, idempotency_key,
        supersedes_event_id
    ) VALUES (
        p_acquisition_principal_id, grant_event.consent_policy_version,
        grant_event.product_legal_approval_id,
        grant_event.accepted_copy_sha256,
        'withdraw', grant_event.jurisdiction, grant_event.terms_version,
        grant_event.privacy_policy_version, p_source_route, p_client_version,
        p_affirmative_action, p_occurred_at, p_idempotency_key,
        grant_event.id
    ) ON CONFLICT (idempotency_key) DO NOTHING;

    SELECT * INTO withdrawal FROM public.ml_consent_events
     WHERE idempotency_key = p_idempotency_key;
    IF withdrawal.supersedes_event_id IS DISTINCT FROM grant_event.id THEN
        RAISE EXCEPTION 'consent withdrawal idempotency collision';
    END IF;

    INSERT INTO public.ml_consent_event_purposes (
        consent_event_id, purpose, article_6_basis, article_9_basis
    )
    SELECT withdrawal.id, purpose, article_6_basis, article_9_basis
      FROM public.ml_consent_event_purposes
     WHERE consent_event_id = grant_event.id
    ON CONFLICT (consent_event_id, purpose) DO NOTHING;

    INSERT INTO public.ml_purge_requests (
        acquisition_principal_id, speaker_id, withdrawal_event_id, reason,
        requested_at, requested_by, idempotency_key
    )
    SELECT p_acquisition_principal_id, binding.speaker_id, withdrawal.id,
           'consent_withdrawal', p_occurred_at,
           'record_mlc2_consent_withdrawal_v1',
           p_idempotency_key || ':purge'
      FROM public.ml_speaker_principals binding
     WHERE binding.acquisition_principal_id = p_acquisition_principal_id
    ON CONFLICT (idempotency_key) DO NOTHING;

    SELECT * INTO purge_request FROM public.ml_purge_requests
     WHERE idempotency_key = p_idempotency_key || ':purge';
    IF purge_request.id IS NOT NULL THEN
        INSERT INTO public.ml_purge_events (
            purge_request_id, event_kind, detail, occurred_at, idempotency_key
        ) VALUES (
            purge_request.id, 'requested', jsonb_build_object(
                'trigger', 'consent_withdrawal',
                'withdrawal_event_id', withdrawal.id
            ), p_occurred_at, p_idempotency_key || ':purge:requested'
        ) ON CONFLICT (idempotency_key) DO NOTHING;
    END IF;
    RETURN withdrawal;
END;
$$;

CREATE OR REPLACE FUNCTION public.create_mlc2_consent_snapshot_v1(
    p_acquisition_principal_id UUID,
    p_recording_attempt_id UUID,
    p_take_id UUID,
    p_project_id UUID
) RETURNS public.ml_consent_snapshots
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    grant_event public.ml_consent_events;
    state JSONB;
    fingerprint TEXT;
    snapshot public.ml_consent_snapshots;
BEGIN
    IF p_recording_attempt_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.recording_attempts attempt
         WHERE attempt.id = p_recording_attempt_id
           AND attempt.owner_principal_id = p_acquisition_principal_id
           AND (p_project_id IS NULL OR attempt.project_id = p_project_id)
    ) THEN
        RAISE EXCEPTION 'recording attempt does not belong to acquisition principal';
    END IF;
    IF p_take_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.takes take_row
         WHERE take_row.id = p_take_id
           AND take_row.owner_principal_id = p_acquisition_principal_id
           AND (p_project_id IS NULL OR take_row.project_id = p_project_id)
    ) THEN
        RAISE EXCEPTION 'Take does not belong to acquisition principal';
    END IF;

    SELECT event.* INTO grant_event
      FROM public.ml_consent_events event
     WHERE event.acquisition_principal_id = p_acquisition_principal_id
       AND event.event_kind = 'grant'
       AND NOT EXISTS (
           SELECT 1 FROM public.ml_consent_events withdrawal
            WHERE withdrawal.supersedes_event_id = event.id
              AND withdrawal.event_kind = 'withdraw'
              AND withdrawal.occurred_at <= now()
       )
       AND (SELECT count(*) FROM public.ml_consent_event_purposes purpose
             WHERE purpose.consent_event_id = event.id
               AND purpose.purpose IN (
                   'personalized_coaching', 'pooled_model_improvement'
               )) = 2
     ORDER BY event.occurred_at DESC, event.id DESC
     LIMIT 1;
    IF grant_event.id IS NULL THEN
        RAISE EXCEPTION 'no active bundled MLC-2 consent grant';
    END IF;

    SELECT jsonb_object_agg(purpose, jsonb_build_object(
        'authorized', true,
        'article_6_basis', article_6_basis,
        'article_9_basis', article_9_basis
    )) INTO state
      FROM public.ml_consent_event_purposes
     WHERE consent_event_id = grant_event.id;

    fingerprint := encode(digest(concat_ws(':',
        grant_event.id::text,
        p_acquisition_principal_id::text,
        COALESCE(p_recording_attempt_id::text, ''),
        COALESCE(p_take_id::text, ''),
        COALESCE(p_project_id::text, ''),
        state::text
    ), 'sha256'), 'hex');

    INSERT INTO public.ml_consent_snapshots (
        acquisition_principal_id, grant_event_id, consent_policy_version,
        recording_attempt_id, take_id, project_id, purpose_state,
        retention_state, snapshot_sha256
    ) VALUES (
        p_acquisition_principal_id, grant_event.id,
        grant_event.consent_policy_version, p_recording_attempt_id,
        p_take_id, p_project_id, state, 'eligible', fingerprint
    ) ON CONFLICT (snapshot_sha256) DO NOTHING;

    SELECT * INTO snapshot FROM public.ml_consent_snapshots
     WHERE snapshot_sha256 = fingerprint;
    RETURN snapshot;
END;
$$;

CREATE OR REPLACE FUNCTION public.enqueue_mlc2_outbox_event_v1(
    p_idempotency_key TEXT,
    p_event_type TEXT,
    p_learning_surface_id TEXT,
    p_aggregate_type TEXT,
    p_aggregate_id UUID,
    p_payload JSONB,
    p_occurred_at TIMESTAMPTZ
) RETURNS public.ml_outbox_events
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    outbox_event public.ml_outbox_events;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.ml_learning_surfaces
         WHERE id = p_learning_surface_id
    ) THEN
        RAISE EXCEPTION 'canonical learning surface is required';
    END IF;
    IF p_learning_surface_id = 'moment_suggestion' THEN
        RAISE EXCEPTION 'moment_suggestion is invalid for canonical writes';
    END IF;
    IF jsonb_typeof(p_payload) <> 'object' THEN
        RAISE EXCEPTION 'typed outbox payload must be an object';
    END IF;

    INSERT INTO public.ml_outbox_events (
        idempotency_key, event_type, learning_surface_id, aggregate_type,
        aggregate_id, payload, occurred_at
    ) VALUES (
        p_idempotency_key, p_event_type, p_learning_surface_id,
        p_aggregate_type, p_aggregate_id, p_payload, p_occurred_at
    ) ON CONFLICT (idempotency_key) DO NOTHING;

    SELECT * INTO outbox_event FROM public.ml_outbox_events
     WHERE idempotency_key = p_idempotency_key;
    IF outbox_event.learning_surface_id <> p_learning_surface_id
       OR outbox_event.aggregate_id <> p_aggregate_id THEN
        RAISE EXCEPTION 'outbox idempotency collision';
    END IF;
    RETURN outbox_event;
END;
$$;

CREATE OR REPLACE FUNCTION public.claim_mlc2_outbox_events_v1(
    p_worker_id TEXT,
    p_limit INTEGER DEFAULT 25,
    p_lease_seconds INTEGER DEFAULT 60
) RETURNS SETOF public.ml_outbox_events
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    IF p_limit < 1 OR p_limit > 100 OR p_lease_seconds < 10 THEN
        RAISE EXCEPTION 'invalid outbox claim bounds';
    END IF;
    RETURN QUERY
    WITH claimable AS (
        SELECT id FROM public.ml_outbox_events
         WHERE processed_at IS NULL
           AND available_at <= now()
           AND (lease_expires_at IS NULL OR lease_expires_at <= now())
         ORDER BY available_at, created_at, id
         FOR UPDATE SKIP LOCKED
         LIMIT p_limit
    )
    UPDATE public.ml_outbox_events event
       SET locked_by = p_worker_id,
           lease_expires_at = now() + make_interval(secs => p_lease_seconds),
           processing_started_at = now(),
           attempt_count = event.attempt_count + 1,
           last_error_code = NULL,
           last_error_at = NULL
      FROM claimable
     WHERE event.id = claimable.id
    RETURNING event.*;
END;
$$;

CREATE OR REPLACE FUNCTION public.finalize_mlc2_outbox_event_v1(
    p_outbox_event_id UUID,
    p_worker_id TEXT,
    p_canonical_event JSONB
) RETURNS public.ml_canonical_events
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    outbox_event public.ml_outbox_events;
    canonical_event public.ml_canonical_events;
BEGIN
    SELECT * INTO outbox_event FROM public.ml_outbox_events
     WHERE id = p_outbox_event_id
     FOR UPDATE;
    IF outbox_event.id IS NULL THEN
        RAISE EXCEPTION 'outbox event not found';
    END IF;
    IF outbox_event.processed_at IS NOT NULL THEN
        SELECT * INTO canonical_event FROM public.ml_canonical_events
         WHERE source_outbox_event_id = outbox_event.id;
        RETURN canonical_event;
    END IF;
    IF outbox_event.locked_by IS DISTINCT FROM p_worker_id
       OR outbox_event.lease_expires_at <= now() THEN
        RAISE EXCEPTION 'outbox lease is not held by worker';
    END IF;
    IF p_canonical_event ->> 'idempotency_key'
       IS DISTINCT FROM outbox_event.idempotency_key
       OR p_canonical_event ->> 'learning_surface_id'
          IS DISTINCT FROM outbox_event.learning_surface_id THEN
        RAISE EXCEPTION 'canonical event does not match outbox source';
    END IF;

    INSERT INTO public.ml_canonical_events (
        event_id, idempotency_key, source_outbox_event_id,
        learning_contract_version, data_epoch, learning_surface_id,
        pipeline_stage_id, feedback_family_id,
        acquisition_principal_id, speaker_id, consent_snapshot_id,
        project_id, recording_attempt_id, take_id, clip_id,
        evidence_locator, execution_version, payload_type, payload,
        source_event_id, occurred_at
    ) VALUES (
        (p_canonical_event ->> 'event_id')::uuid,
        p_canonical_event ->> 'idempotency_key', outbox_event.id,
        p_canonical_event ->> 'learning_contract_version',
        (p_canonical_event ->> 'data_epoch')::integer,
        p_canonical_event ->> 'learning_surface_id',
        p_canonical_event ->> 'pipeline_stage_id',
        NULLIF(p_canonical_event ->> 'feedback_family_id', ''),
        (p_canonical_event ->> 'acquisition_principal_id')::uuid,
        (p_canonical_event ->> 'speaker_id')::uuid,
        (p_canonical_event ->> 'consent_snapshot_id')::uuid,
        NULLIF(p_canonical_event ->> 'project_id', '')::uuid,
        NULLIF(p_canonical_event ->> 'recording_attempt_id', '')::uuid,
        NULLIF(p_canonical_event ->> 'take_id', '')::uuid,
        NULLIF(p_canonical_event ->> 'clip_id', '')::uuid,
        COALESCE(p_canonical_event -> 'evidence_locator', '{}'::jsonb),
        p_canonical_event -> 'execution_version',
        p_canonical_event ->> 'payload_type',
        p_canonical_event -> 'payload',
        p_canonical_event ->> 'source_event_id',
        (p_canonical_event ->> 'occurred_at')::timestamptz
    ) ON CONFLICT (source_outbox_event_id) DO NOTHING;

    SELECT * INTO canonical_event FROM public.ml_canonical_events
     WHERE source_outbox_event_id = outbox_event.id;
    IF canonical_event.id IS NULL THEN
        RAISE EXCEPTION 'canonical event finalization failed';
    END IF;

    UPDATE public.ml_outbox_events
       SET processed_at = now(), locked_by = NULL, lease_expires_at = NULL,
           last_error_code = NULL, last_error_at = NULL
     WHERE id = outbox_event.id;
    RETURN canonical_event;
END;
$$;

CREATE OR REPLACE FUNCTION public.fail_mlc2_outbox_event_v1(
    p_outbox_event_id UUID,
    p_worker_id TEXT,
    p_error_code TEXT,
    p_retry_after_seconds INTEGER DEFAULT 30
) RETURNS public.ml_outbox_events
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    outbox_event public.ml_outbox_events;
BEGIN
    UPDATE public.ml_outbox_events
       SET locked_by = NULL,
           lease_expires_at = NULL,
           last_error_code = p_error_code,
           last_error_at = now(),
           available_at = now() + make_interval(
               secs => GREATEST(p_retry_after_seconds, 1)
           )
     WHERE id = p_outbox_event_id
       AND processed_at IS NULL
       AND locked_by = p_worker_id
    RETURNING * INTO outbox_event;
    IF outbox_event.id IS NULL THEN
        RAISE EXCEPTION 'outbox failure lease is not held by worker';
    END IF;
    RETURN outbox_event;
END;
$$;

CREATE OR REPLACE FUNCTION public.ack_mlc2_rendered_exposure_v1(
    p_presentation_id UUID,
    p_acknowledgement_token UUID,
    p_actor_principal_id UUID,
    p_render_instance_id UUID,
    p_client_rendered_at TIMESTAMPTZ,
    p_client_version TEXT,
    p_payload_sha256 TEXT,
    p_idempotency_key TEXT
) RETURNS public.ml_rendered_exposures
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    presentation public.ml_presentations;
    exposure public.ml_rendered_exposures;
BEGIN
    SELECT * INTO presentation FROM public.ml_presentations
     WHERE id = p_presentation_id
       AND acknowledgement_token = p_acknowledgement_token
       AND actor_principal_id = p_actor_principal_id
       AND visible_payload_sha256 = p_payload_sha256;
    IF presentation.id IS NULL OR presentation.delivery_mode = 'shadow' THEN
        RAISE EXCEPTION 'render acknowledgement rejected';
    END IF;

    INSERT INTO public.ml_rendered_exposures (
        presentation_id, actor_principal_id, render_instance_id,
        client_rendered_at, client_version, payload_sha256, idempotency_key
    ) VALUES (
        p_presentation_id, p_actor_principal_id, p_render_instance_id,
        p_client_rendered_at, p_client_version, p_payload_sha256,
        p_idempotency_key
    ) ON CONFLICT (presentation_id, render_instance_id) DO NOTHING;

    SELECT * INTO exposure FROM public.ml_rendered_exposures
     WHERE presentation_id = p_presentation_id
       AND render_instance_id = p_render_instance_id;
    IF exposure.actor_principal_id <> p_actor_principal_id
       OR exposure.payload_sha256 <> p_payload_sha256 THEN
        RAISE EXCEPTION 'render acknowledgement idempotency collision';
    END IF;
    RETURN exposure;
END;
$$;

CREATE OR REPLACE FUNCTION public.reveal_ml_review_assignment_v1(
    p_review_assignment_id UUID,
    p_actor_principal_id UUID,
    p_idempotency_key TEXT
) RETURNS public.ml_review_assignment_events
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    reveal_event public.ml_review_assignment_events;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.ml_review_assignments assignment
         WHERE assignment.id = p_review_assignment_id
           AND assignment.reviewer_principal_id = p_actor_principal_id
    ) OR NOT EXISTS (
        SELECT 1 FROM public.ml_review_assignment_events event
         WHERE event.review_assignment_id = p_review_assignment_id
           AND event.event_kind = 'submitted'
    ) THEN
        RAISE EXCEPTION 'blind review may be revealed only after submission';
    END IF;

    INSERT INTO public.ml_review_assignment_events (
        review_assignment_id, event_kind, actor_principal_id,
        idempotency_key
    ) VALUES (
        p_review_assignment_id, 'revealed', p_actor_principal_id,
        p_idempotency_key
    ) ON CONFLICT (review_assignment_id, event_kind) DO NOTHING;

    SELECT * INTO reveal_event FROM public.ml_review_assignment_events
     WHERE review_assignment_id = p_review_assignment_id
       AND event_kind = 'revealed';
    RETURN reveal_event;
END;
$$;

-- ── Immutability, access control and health reporting ─────────────────────

-- Keep these statements explicit.  Besides being easier to audit, the
-- repository security gate deliberately refuses to infer RLS from dynamic
-- EXECUTE strings.
ALTER TABLE public.ml_contract_epochs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_learning_surfaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_learning_surface_aliases ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_feedback_families ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_pipeline_stages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_product_operations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_speakers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_speaker_principals ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_split_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_speaker_split_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_product_legal_approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_consent_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_consent_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_consent_event_purposes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_consent_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_canonical_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_object_artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_object_verifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_evidence_spans ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_semantic_artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_review_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_review_assignment_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_presentations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_rendered_exposures ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_judgments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_product_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_purge_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_purge_events ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON FUNCTION public.reject_mlc2_immutable_mutation() FROM PUBLIC;

DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'ml_contract_epochs', 'ml_learning_surfaces',
        'ml_learning_surface_aliases', 'ml_feedback_families',
        'ml_pipeline_stages', 'ml_product_operations', 'ml_speakers',
        'ml_speaker_principals', 'ml_split_policies',
        'ml_speaker_split_assignments', 'ml_product_legal_approvals',
        'ml_consent_policies', 'ml_consent_events',
        'ml_consent_event_purposes', 'ml_consent_snapshots',
        'ml_canonical_events', 'ml_object_artifacts',
        'ml_object_verifications', 'ml_evidence_spans',
        'ml_semantic_artifacts', 'ml_review_assignments',
        'ml_review_assignment_events', 'ml_presentations',
        'ml_rendered_exposures', 'ml_judgments', 'ml_product_actions',
        'ml_purge_requests', 'ml_purge_events'
    ] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('REVOKE ALL ON TABLE public.%I FROM anon, authenticated', table_name);
        -- Runtime writes must use reviewed SECURITY DEFINER contracts.  A
        -- service client may inspect foundation rows but cannot bypass the
        -- idempotency, identity, consent or blindness checks with a direct
        -- table insert.
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

ALTER TABLE public.ml_outbox_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.ml_outbox_events FROM anon, authenticated;
GRANT SELECT ON TABLE public.ml_outbox_events TO service_role;

REVOKE ALL ON FUNCTION public.assign_ml_speaker_split_v1(UUID, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.assign_ml_speaker_split_v1(UUID, TEXT)
    TO service_role;
REVOKE ALL ON FUNCTION public.register_ml_speaker_principal_v1(
    UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.register_ml_speaker_principal_v1(
    UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.record_mlc2_consent_grant_v1(
    UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, TIMESTAMPTZ,
    BOOLEAN, TEXT
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.record_mlc2_consent_grant_v1(
    UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, TIMESTAMPTZ,
    BOOLEAN, TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.record_mlc2_consent_withdrawal_v1(
    UUID, UUID, TEXT, TEXT, JSONB, TIMESTAMPTZ, TEXT
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.record_mlc2_consent_withdrawal_v1(
    UUID, UUID, TEXT, TEXT, JSONB, TIMESTAMPTZ, TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.create_mlc2_consent_snapshot_v1(
    UUID, UUID, UUID, UUID
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.create_mlc2_consent_snapshot_v1(
    UUID, UUID, UUID, UUID
) TO service_role;
REVOKE ALL ON FUNCTION public.enqueue_mlc2_outbox_event_v1(
    TEXT, TEXT, TEXT, TEXT, UUID, JSONB, TIMESTAMPTZ
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.enqueue_mlc2_outbox_event_v1(
    TEXT, TEXT, TEXT, TEXT, UUID, JSONB, TIMESTAMPTZ
) TO service_role;
REVOKE ALL ON FUNCTION public.claim_mlc2_outbox_events_v1(
    TEXT, INTEGER, INTEGER
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.claim_mlc2_outbox_events_v1(
    TEXT, INTEGER, INTEGER
) TO service_role;
REVOKE ALL ON FUNCTION public.finalize_mlc2_outbox_event_v1(
    UUID, TEXT, JSONB
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.finalize_mlc2_outbox_event_v1(
    UUID, TEXT, JSONB
) TO service_role;
REVOKE ALL ON FUNCTION public.fail_mlc2_outbox_event_v1(
    UUID, TEXT, TEXT, INTEGER
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.fail_mlc2_outbox_event_v1(
    UUID, TEXT, TEXT, INTEGER
) TO service_role;
REVOKE ALL ON FUNCTION public.ack_mlc2_rendered_exposure_v1(
    UUID, UUID, UUID, UUID, TIMESTAMPTZ, TEXT, TEXT, TEXT
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.ack_mlc2_rendered_exposure_v1(
    UUID, UUID, UUID, UUID, TIMESTAMPTZ, TEXT, TEXT, TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.reveal_ml_review_assignment_v1(
    UUID, UUID, TEXT
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.reveal_ml_review_assignment_v1(
    UUID, UUID, TEXT
) TO service_role;

CREATE OR REPLACE FUNCTION public.get_mlc2_foundation_health_v1()
RETURNS JSONB
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = public
AS $$
SELECT jsonb_build_object(
    'learning_contract_version', 'MLC-2',
    'data_epoch', 1,
    'generated_at', now(),
    'learning_surface_count', (SELECT count(*) FROM ml_learning_surfaces),
    'pending_outbox_count', (
        SELECT count(*) FROM ml_outbox_events WHERE processed_at IS NULL
    ),
    'failed_outbox_count', (
        SELECT count(*) FROM ml_outbox_events
         WHERE processed_at IS NULL AND last_error_code IS NOT NULL
    ),
    'oldest_pending_outbox_at', (
        SELECT min(created_at) FROM ml_outbox_events WHERE processed_at IS NULL
    ),
    'unresolved_principal_count', (
        SELECT count(*) FROM owner_principals p
         WHERE NOT EXISTS (
             SELECT 1 FROM ml_speaker_principals sp
              WHERE sp.acquisition_principal_id = p.id
         )
    ),
    'unverified_object_count', (
        SELECT count(*) FROM ml_object_artifacts object
         WHERE NOT EXISTS (
             SELECT 1 FROM ml_object_verifications verification
              WHERE verification.object_artifact_id = object.id
                AND verification.verified
                AND verification.observed_sha256 = object.sha256
                AND verification.observed_byte_size = object.byte_size
         )
    ),
    'pending_purge_count', (
        SELECT count(*) FROM ml_purge_requests request
         WHERE NOT EXISTS (
             SELECT 1 FROM ml_purge_events event
              WHERE event.purge_request_id = request.id
                AND event.event_kind = 'completed'
         )
    ),
    'dataset_creation_enabled', false,
    'training_enabled', false,
    'promotion_enabled', false
);
$$;

REVOKE ALL ON FUNCTION public.get_mlc2_foundation_health_v1() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.get_mlc2_foundation_health_v1()
    TO service_role;

COMMENT ON TABLE public.ml_contract_epochs IS
    'Authoritative MLC-2 contract epoch; foundation ships with dataset, training and promotion disabled.';
COMMENT ON TABLE public.ml_learning_surfaces IS
    'Sole authoritative registry for exactly seven canonical learning systems.';
COMMENT ON TABLE public.ml_outbox_events IS
    'Transactional outbox: at-least-once delivery and effectively-once canonical results through idempotency.';
COMMENT ON TABLE public.ml_canonical_events IS
    'Immutable shared envelope; typed surface payloads remain isolated by learning_surface_id and payload_type.';
COMMENT ON TABLE public.ml_rendered_exposures IS
    'Authenticated post-render receipts. Delivery, opening, skipping, timeout and silence are not judgments.';
COMMENT ON TABLE public.ml_product_actions IS
    'Product mutations only. Paragraph/orange actions never enter judgments or supervision.';
COMMENT ON TABLE public.ml_purge_events IS
    'Audited exceptional purge traversal; shared objects are retained while unaffected valid lineage still references them.';

NOTIFY pgrst, 'reload schema';

COMMIT;
