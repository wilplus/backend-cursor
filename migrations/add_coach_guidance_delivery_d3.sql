-- 0322: MLC-3 Coach Guidance and Exercise Delivery D3.
-- Additive, synthetic-only, non-serving and non-dataset.

BEGIN;

CREATE OR REPLACE FUNCTION public.reject_coach_guidance_d3_mutation_v1()
RETURNS trigger LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
    RAISE EXCEPTION 'COACH_GUIDANCE_D3_APPEND_ONLY';
END;
$$;

CREATE TABLE IF NOT EXISTS public.coach_guidance_review_frames (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    project_id UUID NOT NULL REFERENCES public.projects(id) ON DELETE RESTRICT,
    reviewer_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    batch_policy_version TEXT NOT NULL CHECK (
        batch_policy_version = 'coach-guidance-review-batch-v1'
    ),
    cutoff_at TIMESTAMPTZ NOT NULL,
    eligible_assignment_count INTEGER NOT NULL CHECK (
        eligible_assignment_count >= 0
    ),
    excluded_assignment_count INTEGER NOT NULL CHECK (
        excluded_assignment_count >= 0
    ),
    frame_sha256 TEXT NOT NULL CHECK (frame_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE CHECK (
        length(btrim(idempotency_key)) BETWEEN 1 AND 200
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    UNIQUE (id, acquisition_principal_id, reviewer_principal_id)
);

-- A terminal-only successor is a meaningful immutable inventory: it records
-- that every formerly required assignment is now a typed exclusion.  An
-- actually empty source inventory remains invalid.
ALTER TABLE public.coach_guidance_review_frames
    DROP CONSTRAINT IF EXISTS
        coach_guidance_review_frames_eligible_assignment_count_check;
ALTER TABLE public.coach_guidance_review_frames
    DROP CONSTRAINT IF EXISTS coach_guidance_review_frames_inventory_check;
ALTER TABLE public.coach_guidance_review_frames
    ADD CONSTRAINT coach_guidance_review_frames_inventory_check CHECK (
        eligible_assignment_count >= 0
        AND excluded_assignment_count >= 0
        AND eligible_assignment_count + excluded_assignment_count > 0
    );

CREATE TABLE IF NOT EXISTS public.coach_guidance_review_frame_items (
    frame_id UUID NOT NULL
        REFERENCES public.coach_guidance_review_frames(id) ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL,
    reviewer_principal_id UUID NOT NULL,
    review_assignment_id UUID NOT NULL,
    blind_packet_id UUID NOT NULL
        REFERENCES public.exercise_blind_packets(id) ON DELETE RESTRICT,
    membership_state TEXT NOT NULL CHECK (
        membership_state IN ('required', 'excluded')
    ),
    exclusion_reason TEXT NULL CHECK (
        exclusion_reason IS NULL OR exclusion_reason IN (
            'cancelled_before_cutoff', 'expired_before_cutoff'
        )
    ),
    canonical_position INTEGER NULL CHECK (canonical_position > 0),
    item_sha256 TEXT NOT NULL CHECK (item_sha256 ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (frame_id, review_assignment_id),
    UNIQUE (frame_id, canonical_position),
    FOREIGN KEY (frame_id, acquisition_principal_id, reviewer_principal_id)
        REFERENCES public.coach_guidance_review_frames(
            id, acquisition_principal_id, reviewer_principal_id
        ) ON DELETE RESTRICT,
    FOREIGN KEY (review_assignment_id, reviewer_principal_id)
        REFERENCES public.ml_review_assignments(id, reviewer_principal_id)
        ON DELETE RESTRICT,
    CONSTRAINT coach_guidance_frame_item_state_check CHECK (
        (membership_state = 'required' AND exclusion_reason IS NULL
         AND canonical_position IS NOT NULL)
        OR (membership_state = 'excluded' AND exclusion_reason IS NOT NULL
            AND canonical_position IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS public.coach_guidance_review_batches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    frame_id UUID NOT NULL UNIQUE
        REFERENCES public.coach_guidance_review_frames(id) ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL,
    reviewer_principal_id UUID NOT NULL,
    batch_revision INTEGER NOT NULL DEFAULT 1 CHECK (batch_revision > 0),
    supersedes_batch_id UUID NULL,
    batch_sha256 TEXT NOT NULL CHECK (batch_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    FOREIGN KEY (frame_id, acquisition_principal_id, reviewer_principal_id)
        REFERENCES public.coach_guidance_review_frames(
            id, acquisition_principal_id, reviewer_principal_id
        ) ON DELETE RESTRICT,
    UNIQUE (id, acquisition_principal_id, reviewer_principal_id)
);

ALTER TABLE public.coach_guidance_review_batches
    ADD COLUMN IF NOT EXISTS supersedes_batch_id UUID NULL;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'public.coach_guidance_review_batches'::regclass
           AND conname = 'coach_guidance_batches_supersedes_fk'
    ) THEN
        ALTER TABLE public.coach_guidance_review_batches
            ADD CONSTRAINT coach_guidance_batches_supersedes_fk
            FOREIGN KEY (supersedes_batch_id)
            REFERENCES public.coach_guidance_review_batches(id)
            ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'public.coach_guidance_review_batches'::regclass
           AND conname = 'coach_guidance_batches_supersedes_key'
    ) THEN
        ALTER TABLE public.coach_guidance_review_batches
            ADD CONSTRAINT coach_guidance_batches_supersedes_key
            UNIQUE (supersedes_batch_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'public.coach_guidance_review_batches'::regclass
           AND conname = 'coach_guidance_batches_revision_check'
    ) THEN
        ALTER TABLE public.coach_guidance_review_batches
            ADD CONSTRAINT coach_guidance_batches_revision_check CHECK (
                (batch_revision = 1 AND supersedes_batch_id IS NULL)
                OR (batch_revision > 1 AND supersedes_batch_id IS NOT NULL)
            );
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS public.coach_guidance_reveal_grants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    review_batch_id UUID NOT NULL UNIQUE
        REFERENCES public.coach_guidance_review_batches(id) ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL,
    reviewer_principal_id UUID NOT NULL,
    reveal_policy_version TEXT NOT NULL CHECK (
        reveal_policy_version = 'coach-guidance-post-blind-reveal-v1'
    ),
    judgment_inventory_sha256 TEXT NOT NULL CHECK (
        judgment_inventory_sha256 ~ '^[0-9a-f]{64}$'
    ),
    grant_sha256 TEXT NOT NULL CHECK (grant_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    FOREIGN KEY (review_batch_id, acquisition_principal_id, reviewer_principal_id)
        REFERENCES public.coach_guidance_review_batches(
            id, acquisition_principal_id, reviewer_principal_id
        ) ON DELETE RESTRICT,
    UNIQUE (id, reviewer_principal_id),
    UNIQUE (id, acquisition_principal_id)
);

CREATE TABLE IF NOT EXISTS public.coach_guidance_reveal_grant_judgments (
    reveal_grant_id UUID NOT NULL
        REFERENCES public.coach_guidance_reveal_grants(id) ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL,
    review_assignment_id UUID NOT NULL
        REFERENCES public.ml_review_assignments(id) ON DELETE RESTRICT,
    judgment_id UUID NOT NULL UNIQUE
        REFERENCES public.ml_judgments(id) ON DELETE RESTRICT,
    canonical_position INTEGER NOT NULL CHECK (canonical_position > 0),
    item_sha256 TEXT NOT NULL CHECK (item_sha256 ~ '^[0-9a-f]{64}$'),
    PRIMARY KEY (reveal_grant_id, review_assignment_id),
    UNIQUE (reveal_grant_id, canonical_position),
    UNIQUE (reveal_grant_id, review_assignment_id, judgment_id),
    FOREIGN KEY (reveal_grant_id, acquisition_principal_id)
        REFERENCES public.coach_guidance_reveal_grants(
            id, acquisition_principal_id
        ) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS public.coach_guidance_reveal_accesses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reveal_grant_id UUID NOT NULL,
    acquisition_principal_id UUID NOT NULL,
    reviewer_principal_id UUID NOT NULL,
    review_assignment_id UUID NOT NULL,
    blind_judgment_id UUID NOT NULL
        REFERENCES public.ml_judgments(id) ON DELETE RESTRICT,
    access_purpose TEXT NOT NULL CHECK (
        access_purpose IN ('acoustic_reference', 'guidance_authoring')
    ),
    access_sha256 TEXT NOT NULL CHECK (access_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE,
    accessed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    FOREIGN KEY (reveal_grant_id, reviewer_principal_id)
        REFERENCES public.coach_guidance_reveal_grants(
            id, reviewer_principal_id
        ) ON DELETE RESTRICT,
    FOREIGN KEY (reveal_grant_id, acquisition_principal_id)
        REFERENCES public.coach_guidance_reveal_grants(
            id, acquisition_principal_id
        ) ON DELETE RESTRICT,
    FOREIGN KEY (reveal_grant_id, review_assignment_id)
        REFERENCES public.coach_guidance_reveal_grant_judgments(
            reveal_grant_id, review_assignment_id
        ) ON DELETE RESTRICT,
    FOREIGN KEY (
        reveal_grant_id, review_assignment_id, blind_judgment_id
    ) REFERENCES public.coach_guidance_reveal_grant_judgments(
        reveal_grant_id, review_assignment_id, judgment_id
    ) ON DELETE RESTRICT,
    UNIQUE (id, reviewer_principal_id),
    UNIQUE (id, acquisition_principal_id, reviewer_principal_id)
);

CREATE TABLE IF NOT EXISTS public.coach_guidance_upload_permits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    reviewer_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    reveal_access_id UUID NOT NULL,
    authorization_snapshot_id UUID NOT NULL
        REFERENCES public.processing_authorization_snapshots(id)
        ON DELETE RESTRICT,
    purpose_id TEXT NOT NULL CHECK (purpose_id IN (
        'coach_review', 'personalized_exercise_recommendation'
    )),
    storage_provider TEXT NOT NULL CHECK (storage_provider = 'r2'),
    bucket TEXT NOT NULL CHECK (length(btrim(bucket)) > 0),
    object_key TEXT NOT NULL CHECK (length(btrim(object_key)) > 0),
    intended_exact_bytes_sha256 TEXT NOT NULL CHECK (
        intended_exact_bytes_sha256 ~ '^[0-9a-f]{64}$'
    ),
    intended_byte_size BIGINT NOT NULL CHECK (intended_byte_size > 0),
    content_type TEXT NOT NULL CHECK (content_type LIKE 'video/%'),
    expires_at TIMESTAMPTZ NOT NULL,
    permit_sha256 TEXT NOT NULL CHECK (permit_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    synthetic_only BOOLEAN NOT NULL DEFAULT true CHECK (synthetic_only),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    FOREIGN KEY (reveal_access_id, reviewer_principal_id)
        REFERENCES public.coach_guidance_reveal_accesses(
            id, reviewer_principal_id
        ) ON DELETE RESTRICT,
    UNIQUE (id, acquisition_principal_id)
);

CREATE TABLE IF NOT EXISTS public.coach_guidance_upload_recoveries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    upload_permit_id UUID NOT NULL UNIQUE,
    acquisition_principal_id UUID NOT NULL,
    storage_provider TEXT NOT NULL CHECK (storage_provider = 'r2'),
    bucket TEXT NOT NULL,
    object_key TEXT NOT NULL,
    intended_exact_bytes_sha256 TEXT NOT NULL CHECK (
        intended_exact_bytes_sha256 ~ '^[0-9a-f]{64}$'
    ),
    recovery_sha256 TEXT NOT NULL CHECK (recovery_sha256 ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    synthetic_only BOOLEAN NOT NULL DEFAULT true CHECK (synthetic_only),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    FOREIGN KEY (upload_permit_id, acquisition_principal_id)
        REFERENCES public.coach_guidance_upload_permits(
            id, acquisition_principal_id
        ) ON DELETE RESTRICT,
    UNIQUE (id, acquisition_principal_id)
);

CREATE TABLE IF NOT EXISTS public.coach_guidance_upload_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    upload_recovery_id UUID NOT NULL,
    upload_permit_id UUID NOT NULL
        REFERENCES public.coach_guidance_upload_permits(id)
        ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL,
    event_kind TEXT NOT NULL CHECK (event_kind IN (
        'reserved', 'write_started', 'write_acknowledged',
        'finalized', 'abandoned'
    )),
    media_object_id UUID NULL
        REFERENCES public.exercise_media_objects(id) ON DELETE RESTRICT,
    event_sha256 TEXT NOT NULL CHECK (event_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    synthetic_only BOOLEAN NOT NULL DEFAULT true CHECK (synthetic_only),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    FOREIGN KEY (upload_recovery_id, acquisition_principal_id)
        REFERENCES public.coach_guidance_upload_recoveries(
            id, acquisition_principal_id
        ) ON DELETE RESTRICT,
    CHECK ((event_kind = 'finalized' AND media_object_id IS NOT NULL)
        OR (event_kind <> 'finalized' AND media_object_id IS NULL)),
    UNIQUE (upload_recovery_id, event_kind)
);

CREATE TABLE IF NOT EXISTS public.coach_guidance_media_validity_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    media_object_id UUID NOT NULL
        REFERENCES public.exercise_media_objects(id) ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    previous_event_id UUID NULL UNIQUE
        REFERENCES public.coach_guidance_media_validity_events(id)
        ON DELETE RESTRICT,
    validity_state TEXT NOT NULL CHECK (validity_state IN (
        'active', 'quarantined', 'invalid', 'deleted'
    )),
    reason_code TEXT NOT NULL CHECK (length(btrim(reason_code)) > 0),
    evidence_sha256 TEXT NOT NULL CHECK (evidence_sha256 ~ '^[0-9a-f]{64}$'),
    event_sha256 TEXT NOT NULL CHECK (event_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    synthetic_only BOOLEAN NOT NULL DEFAULT true CHECK (synthetic_only),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    CONSTRAINT coach_guidance_media_validity_identity_key
        UNIQUE (id, media_object_id, acquisition_principal_id),
    CONSTRAINT coach_guidance_media_validity_previous_fk
        FOREIGN KEY (previous_event_id, media_object_id, acquisition_principal_id)
        REFERENCES public.coach_guidance_media_validity_events(
            id, media_object_id, acquisition_principal_id
        ) ON DELETE RESTRICT,
    CHECK ((validity_state = 'active' AND previous_event_id IS NULL)
        OR (validity_state <> 'active' AND previous_event_id IS NOT NULL))
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'public.coach_guidance_media_validity_events'::regclass
           AND conname = 'coach_guidance_media_validity_identity_key'
    ) THEN
        ALTER TABLE public.coach_guidance_media_validity_events
            ADD CONSTRAINT coach_guidance_media_validity_identity_key
            UNIQUE (id, media_object_id, acquisition_principal_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'public.coach_guidance_media_validity_events'::regclass
           AND conname = 'coach_guidance_media_validity_previous_fk'
    ) THEN
        ALTER TABLE public.coach_guidance_media_validity_events
            ADD CONSTRAINT coach_guidance_media_validity_previous_fk
            FOREIGN KEY (
                previous_event_id, media_object_id, acquisition_principal_id
            ) REFERENCES public.coach_guidance_media_validity_events(
                id, media_object_id, acquisition_principal_id
            ) ON DELETE RESTRICT;
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS public.coach_guidance_independent_media_reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    media_object_id UUID NOT NULL UNIQUE
        REFERENCES public.exercise_media_objects(id) ON DELETE RESTRICT,
    upload_permit_id UUID NOT NULL,
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    reviewer_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    contains_user_audio BOOLEAN NOT NULL CHECK (NOT contains_user_audio),
    contains_user_transcript BOOLEAN NOT NULL CHECK (NOT contains_user_transcript),
    contains_user_identity BOOLEAN NOT NULL CHECK (NOT contains_user_identity),
    contains_project_context BOOLEAN NOT NULL CHECK (NOT contains_project_context),
    contains_unique_user_passage BOOLEAN NOT NULL CHECK (
        NOT contains_unique_user_passage
    ),
    language_policy_version TEXT NOT NULL CHECK (
        length(btrim(language_policy_version)) > 0
    ),
    safety_policy_version TEXT NOT NULL CHECK (
        length(btrim(safety_policy_version)) > 0
    ),
    rights_policy_version TEXT NOT NULL CHECK (
        length(btrim(rights_policy_version)) > 0
    ),
    content_review_version TEXT NOT NULL CHECK (
        length(btrim(content_review_version)) > 0
    ),
    review_evidence_sha256 TEXT NOT NULL CHECK (
        review_evidence_sha256 ~ '^[0-9a-f]{64}$'
    ),
    review_sha256 TEXT NOT NULL CHECK (review_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE,
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    synthetic_only BOOLEAN NOT NULL DEFAULT true CHECK (synthetic_only),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    FOREIGN KEY (upload_permit_id, acquisition_principal_id)
        REFERENCES public.coach_guidance_upload_permits(
            id, acquisition_principal_id
        ) ON DELETE RESTRICT,
    UNIQUE (id, media_object_id)
);

CREATE TABLE IF NOT EXISTS public.coach_guidance_media_bindings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    media_object_id UUID NOT NULL
        REFERENCES public.exercise_media_objects(id) ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    authorization_snapshot_id UUID NOT NULL
        REFERENCES public.processing_authorization_snapshots(id)
        ON DELETE RESTRICT,
    purpose_id TEXT NOT NULL CHECK (purpose_id IN (
        'coach_review', 'personalized_exercise_recommendation'
    )),
    provenance_class TEXT NOT NULL CHECK (provenance_class IN (
        'user_scoped', 'independent_clean_media', 'user_source_dependent'
    )),
    source_acquisition_principal_id UUID NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    independent_media_review_id UUID NULL,
    upload_authorization_id UUID NOT NULL
        REFERENCES public.coach_guidance_upload_permits(id)
        ON DELETE RESTRICT,
    language_policy_version TEXT NOT NULL,
    safety_policy_version TEXT NOT NULL,
    rights_policy_version TEXT NOT NULL,
    content_review_version TEXT NOT NULL,
    binding_sha256 TEXT NOT NULL CHECK (binding_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    CONSTRAINT coach_guidance_media_binding_provenance_check CHECK (
        (provenance_class = 'independent_clean_media'
         AND source_acquisition_principal_id IS NULL
         AND independent_media_review_id IS NOT NULL)
        OR (provenance_class <> 'independent_clean_media'
            AND source_acquisition_principal_id IS NOT NULL
            AND independent_media_review_id IS NULL)
    ),
    UNIQUE (id, acquisition_principal_id)
);

ALTER TABLE public.coach_guidance_media_bindings
    ADD COLUMN IF NOT EXISTS independent_media_review_id UUID NULL;
ALTER TABLE public.coach_guidance_media_bindings
    DROP CONSTRAINT IF EXISTS coach_guidance_media_binding_provenance_check;
ALTER TABLE public.coach_guidance_media_bindings
    ADD CONSTRAINT coach_guidance_media_binding_provenance_check CHECK (
        (provenance_class = 'independent_clean_media'
         AND source_acquisition_principal_id IS NULL
         AND independent_media_review_id IS NOT NULL)
        OR (provenance_class <> 'independent_clean_media'
            AND source_acquisition_principal_id IS NOT NULL
            AND independent_media_review_id IS NULL)
    );
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'public.coach_guidance_media_bindings'::regclass
           AND conname = 'coach_guidance_media_binding_independent_review_fk'
    ) THEN
        ALTER TABLE public.coach_guidance_media_bindings
            ADD CONSTRAINT coach_guidance_media_binding_independent_review_fk
            FOREIGN KEY (independent_media_review_id)
            REFERENCES public.coach_guidance_independent_media_reviews(id)
            ON DELETE RESTRICT;
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS public.coach_guidance_attachments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    recipient_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    author_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    review_batch_id UUID NOT NULL,
    reveal_grant_id UUID NOT NULL,
    reveal_access_id UUID NOT NULL,
    blind_judgment_id UUID NOT NULL
        REFERENCES public.ml_judgments(id) ON DELETE RESTRICT,
    review_assignment_id UUID NOT NULL
        REFERENCES public.ml_review_assignments(id) ON DELETE RESTRICT,
    feedback_membership_id UUID NOT NULL,
    feedback_candidate_id UUID NOT NULL,
    attachment_class TEXT NOT NULL CHECK (attachment_class IN (
        'general_product_guidance', 'mlc3_exercise'
    )),
    product_subcategory TEXT NULL CHECK (
        product_subcategory IS NULL OR product_subcategory IN (
            'structure', 'delivery'
        )
    ),
    exercise_offer_id UUID NULL
        REFERENCES public.exercise_service_offers(id) ON DELETE RESTRICT,
    exercise_version_id UUID NULL
        REFERENCES public.exercise_versions(id) ON DELETE RESTRICT,
    need_contract_id UUID NULL
        REFERENCES public.exercise_need_contracts(id) ON DELETE RESTRICT,
    authorization_snapshot_id UUID NOT NULL
        REFERENCES public.processing_authorization_snapshots(id)
        ON DELETE RESTRICT,
    attachment_sha256 TEXT NOT NULL CHECK (
        attachment_sha256 ~ '^[0-9a-f]{64}$'
    ),
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    FOREIGN KEY (review_batch_id, acquisition_principal_id, author_principal_id)
        REFERENCES public.coach_guidance_review_batches(
            id, acquisition_principal_id, reviewer_principal_id
        ) ON DELETE RESTRICT,
    FOREIGN KEY (reveal_grant_id, author_principal_id)
        REFERENCES public.coach_guidance_reveal_grants(
            id, reviewer_principal_id
        ) ON DELETE RESTRICT,
    FOREIGN KEY (reveal_access_id, author_principal_id)
        REFERENCES public.coach_guidance_reveal_accesses(
            id, reviewer_principal_id
        ) ON DELETE RESTRICT,
    FOREIGN KEY (reveal_grant_id, review_assignment_id)
        REFERENCES public.coach_guidance_reveal_grant_judgments(
            reveal_grant_id, review_assignment_id
        ) ON DELETE RESTRICT,
    FOREIGN KEY (feedback_membership_id, feedback_candidate_id)
        REFERENCES public.feedback_v3_membership_items(
            membership_id, candidate_id
        ) ON DELETE RESTRICT,
    FOREIGN KEY (feedback_membership_id, acquisition_principal_id)
        REFERENCES public.feedback_v3_memberships(
            id, acquisition_principal_id
        ) ON DELETE RESTRICT,
    CHECK (recipient_principal_id = acquisition_principal_id),
    CHECK (
        (attachment_class = 'general_product_guidance'
         AND exercise_offer_id IS NULL AND exercise_version_id IS NULL
         AND need_contract_id IS NULL)
        OR (attachment_class = 'mlc3_exercise'
            AND exercise_offer_id IS NOT NULL
            AND need_contract_id IS NOT NULL)
    ),
    UNIQUE (id, acquisition_principal_id)
);

CREATE TABLE IF NOT EXISTS public.coach_guidance_attachment_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attachment_id UUID NOT NULL
        REFERENCES public.coach_guidance_attachments(id) ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL,
    version_number INTEGER NOT NULL CHECK (version_number > 0),
    written_note TEXT NULL CHECK (
        written_note IS NULL OR length(btrim(written_note)) BETWEEN 1 AND 2000
    ),
    media_binding_id UUID NULL
        REFERENCES public.coach_guidance_media_bindings(id) ON DELETE RESTRICT,
    language_policy_version TEXT NOT NULL,
    safety_policy_version TEXT NOT NULL,
    rights_policy_version TEXT NOT NULL,
    content_review_version TEXT NOT NULL,
    version_sha256 TEXT NOT NULL CHECK (version_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    FOREIGN KEY (attachment_id, acquisition_principal_id)
        REFERENCES public.coach_guidance_attachments(
            id, acquisition_principal_id
        ) ON DELETE RESTRICT,
    CHECK (written_note IS NOT NULL OR media_binding_id IS NOT NULL),
    UNIQUE (attachment_id, version_number),
    UNIQUE (id, acquisition_principal_id)
);

CREATE TABLE IF NOT EXISTS public.coach_guidance_lifecycle_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attachment_version_id UUID NOT NULL,
    acquisition_principal_id UUID NOT NULL,
    actor_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    authorization_snapshot_id UUID NOT NULL
        REFERENCES public.processing_authorization_snapshots(id)
        ON DELETE RESTRICT,
    previous_event_id UUID NULL
        REFERENCES public.coach_guidance_lifecycle_events(id)
        ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK (event_kind IN (
        'authored', 'assigned', 'delivered', 'rendered', 'played'
    )),
    event_payload JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (
        jsonb_typeof(event_payload) = 'object'
    ),
    event_sha256 TEXT NOT NULL CHECK (event_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    synthetic_only BOOLEAN NOT NULL DEFAULT true CHECK (synthetic_only),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    FOREIGN KEY (attachment_version_id, acquisition_principal_id)
        REFERENCES public.coach_guidance_attachment_versions(
            id, acquisition_principal_id
        ) ON DELETE RESTRICT,
    UNIQUE (attachment_version_id, event_kind),
    UNIQUE (id, attachment_version_id, event_kind)
);

CREATE TABLE IF NOT EXISTS public.coach_guidance_publications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_attachment_version_id UUID NOT NULL
        REFERENCES public.coach_guidance_attachment_versions(id)
        ON DELETE RESTRICT,
    source_acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    published_exercise_version_id UUID NOT NULL
        REFERENCES public.exercise_versions(id) ON DELETE RESTRICT,
    catalog_snapshot_id UUID NOT NULL
        REFERENCES public.exercise_catalog_snapshots(id) ON DELETE RESTRICT,
    provenance_class TEXT NOT NULL CHECK (provenance_class IN (
        'independent_clean_media', 'user_source_dependent'
    )),
    authorization_snapshot_id UUID NOT NULL
        REFERENCES public.processing_authorization_snapshots(id)
        ON DELETE RESTRICT,
    publication_sha256 TEXT NOT NULL CHECK (
        publication_sha256 ~ '^[0-9a-f]{64}$'
    ),
    idempotency_key TEXT NOT NULL UNIQUE,
    published_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    UNIQUE (published_exercise_version_id, catalog_snapshot_id),
    UNIQUE (id, source_acquisition_principal_id)
);

CREATE TABLE IF NOT EXISTS public.coach_guidance_publication_invalidations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    publication_id UUID NOT NULL UNIQUE
        REFERENCES public.coach_guidance_publications(id) ON DELETE RESTRICT,
    source_acquisition_principal_id UUID NOT NULL,
    reason_code TEXT NOT NULL CHECK (reason_code IN (
        'authority_withdrawn', 'source_deleted', 'retention_expired',
        'source_quarantined'
    )),
    invalidation_sha256 TEXT NOT NULL CHECK (
        invalidation_sha256 ~ '^[0-9a-f]{64}$'
    ),
    invalidated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    FOREIGN KEY (publication_id, source_acquisition_principal_id)
        REFERENCES public.coach_guidance_publications(
            id, source_acquisition_principal_id
        ) ON DELETE RESTRICT
);

CREATE OR REPLACE FUNCTION public.require_coach_guidance_reviewer_access_v1(
    p_reviewer_principal_id UUID
) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public, auth AS $$
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'COACH_GUIDANCE_REQUIRES_READ_COMMITTED';
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM public.owner_principals principal
          JOIN auth.users auth_user ON auth_user.id = principal.user_id
          JOIN public.coach_users coach
            ON lower(coach.email) = lower(auth_user.email)
           AND coach.is_active
         WHERE principal.id = p_reviewer_principal_id
    ) THEN RAISE EXCEPTION 'COACH_GUIDANCE_REVIEWER_ACCESS_REQUIRED'; END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.require_coach_guidance_authority_v1(
    p_authorization_snapshot_id UUID,
    p_acquisition_principal_id UUID,
    p_purpose_id TEXT
) RETURNS public.processing_authorization_snapshots
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    snapshot public.processing_authorization_snapshots;
    wall_now TIMESTAMPTZ := clock_timestamp();
BEGIN
    IF p_purpose_id NOT IN (
        'coach_review', 'personalized_exercise_recommendation'
    ) THEN RAISE EXCEPTION 'COACH_GUIDANCE_PURPOSE_INVALID'; END IF;
    SELECT * INTO snapshot FROM public.processing_authorization_snapshots s
     WHERE s.id = p_authorization_snapshot_id
       AND s.acquisition_principal_id = p_acquisition_principal_id
       AND s.purpose_id = p_purpose_id;
    IF snapshot.id IS NULL
       OR NOT EXISTS (
           SELECT 1 FROM public.processing_authorization_receipts receipt
            WHERE receipt.id = snapshot.receipt_id
              AND receipt.acquisition_principal_id = p_acquisition_principal_id
              AND receipt.policy_id = snapshot.policy_id
       )
       OR NOT EXISTS (
           SELECT 1 FROM public.processing_policy_versions policy
            WHERE policy.id = snapshot.policy_id AND policy.status = 'active'
              AND policy.activated_at <= wall_now
              AND (policy.retired_at IS NULL OR policy.retired_at > wall_now)
       )
       OR NOT EXISTS (
           SELECT 1 FROM public.processing_purpose_registry purpose
            WHERE purpose.id = p_purpose_id AND purpose.operational
              AND purpose.authorizes_processing
       )
       OR NOT EXISTS (
           SELECT 1 FROM public.processing_policy_purposes policy_purpose
            WHERE policy_purpose.policy_id = snapshot.policy_id
              AND policy_purpose.purpose_id = p_purpose_id
       )
       OR NOT EXISTS (
           SELECT 1 FROM public.processing_authorization_receipt_purposes rp
            WHERE rp.receipt_id = snapshot.receipt_id
              AND rp.purpose_id = p_purpose_id
       )
       OR EXISTS (
           SELECT 1 FROM public.processing_service_blocks block
            WHERE block.acquisition_principal_id = p_acquisition_principal_id
              AND block.effective_at <= wall_now
       )
       OR EXISTS (
           SELECT 1 FROM public.data_purge_requests purge
            WHERE purge.acquisition_principal_id = p_acquisition_principal_id
              AND purge.state <> 'done'
       )
    THEN RAISE EXCEPTION 'COACH_GUIDANCE_CURRENT_AUTHORITY_REQUIRED'; END IF;
    RETURN snapshot;
END;
$$;

-- The blind source packet may have been acquired for the exercise overlay,
-- while an ordinary coach-review action is authorized by the independently
-- accepted core-service purpose on the same receipt.  Keep the immutable
-- source snapshot as provenance, but revalidate the requested live purpose
-- against its receipt instead of treating the source snapshot's purpose as a
-- bearer permit for every downstream action.
CREATE OR REPLACE FUNCTION public.require_coach_guidance_receipt_authority_v1(
    p_receipt_id UUID,
    p_acquisition_principal_id UUID,
    p_purpose_id TEXT
) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    wall_now TIMESTAMPTZ := clock_timestamp();
BEGIN
    IF p_purpose_id NOT IN (
        'coach_review', 'personalized_exercise_recommendation'
    ) OR NOT EXISTS (
        SELECT 1
          FROM public.processing_authorization_receipts receipt
          JOIN public.processing_policy_versions policy
            ON policy.id = receipt.policy_id
           AND policy.status = 'active'
           AND policy.activated_at <= wall_now
           AND (policy.retired_at IS NULL OR policy.retired_at > wall_now)
          JOIN public.processing_authorization_receipt_purposes receipt_purpose
            ON receipt_purpose.receipt_id = receipt.id
           AND receipt_purpose.purpose_id = p_purpose_id
          JOIN public.processing_policy_purposes policy_purpose
            ON policy_purpose.policy_id = policy.id
           AND policy_purpose.purpose_id = p_purpose_id
          JOIN public.processing_purpose_registry purpose
            ON purpose.id = p_purpose_id
           AND purpose.operational
           AND purpose.authorizes_processing
         WHERE receipt.id = p_receipt_id
           AND receipt.acquisition_principal_id = p_acquisition_principal_id
    ) OR EXISTS (
        SELECT 1 FROM public.processing_service_blocks block
         WHERE block.acquisition_principal_id = p_acquisition_principal_id
           AND block.effective_at <= wall_now
    ) OR EXISTS (
        SELECT 1 FROM public.data_purge_requests purge
         WHERE purge.acquisition_principal_id = p_acquisition_principal_id
           AND purge.state <> 'done'
    ) THEN
        RAISE EXCEPTION 'COACH_GUIDANCE_CURRENT_AUTHORITY_REQUIRED';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.require_coach_guidance_assignment_live_v1(
    p_review_assignment_id UUID,
    p_acquisition_principal_id UUID,
    p_purpose_id TEXT
) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    auth_snapshot_id UUID;
    source_receipt_id UUID;
    reviewer_principal_id UUID;
    wall_now TIMESTAMPTZ := clock_timestamp();
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'COACH_GUIDANCE_REQUIRES_READ_COMMITTED';
    END IF;
    SELECT auth.authorization_snapshot_id, source_snapshot.receipt_id,
           assignment.reviewer_principal_id
      INTO auth_snapshot_id, source_receipt_id, reviewer_principal_id
      FROM public.ml_review_assignments assignment
      JOIN public.exercise_blind_packets packet
        ON packet.review_assignment_id = assignment.id
      JOIN public.exercise_audio_lineages lineage
        ON lineage.id = packet.audio_lineage_id
       AND lineage.acquisition_principal_id = p_acquisition_principal_id
      JOIN public.exercise_authorization_checks auth
        ON auth.id = packet.authorization_check_id
       AND auth.acquisition_principal_id = p_acquisition_principal_id
      JOIN public.processing_authorization_snapshots source_snapshot
        ON source_snapshot.id = auth.authorization_snapshot_id
       AND source_snapshot.acquisition_principal_id =
           p_acquisition_principal_id
      JOIN public.processing_authorization_receipts source_receipt
        ON source_receipt.id = source_snapshot.receipt_id
       AND source_receipt.acquisition_principal_id =
           p_acquisition_principal_id
       AND source_receipt.policy_id = source_snapshot.policy_id
      JOIN public.processing_audio_objects audio_object
        ON audio_object.id = lineage.processing_audio_object_id
       AND audio_object.acquisition_principal_id = p_acquisition_principal_id
       AND audio_object.deleted_at IS NULL
     WHERE assignment.id = p_review_assignment_id
       AND assignment.learning_surface_id = 'confidence_classification'
       AND assignment.reviewer_role = 'coach'
       AND (assignment.expires_at IS NULL OR assignment.expires_at > wall_now)
       AND NOT EXISTS (
           SELECT 1 FROM public.ml_review_assignment_events terminal_event
            WHERE terminal_event.review_assignment_id = assignment.id
              AND terminal_event.event_kind IN ('cancelled', 'expired')
              AND terminal_event.occurred_at <= wall_now
       )
       AND NOT EXISTS (
           SELECT 1 FROM public.data_purge_requests purge
            WHERE purge.acquisition_principal_id = p_acquisition_principal_id
              AND purge.state <> 'done'
       );
    IF auth_snapshot_id IS NULL THEN
        RAISE EXCEPTION 'COACH_GUIDANCE_SOURCE_NOT_LIVE';
    END IF;
    PERFORM public.require_coach_guidance_reviewer_access_v1(
        reviewer_principal_id
    );
    IF p_purpose_id = 'coach_review' THEN
        PERFORM public.require_coach_guidance_receipt_authority_v1(
            source_receipt_id, p_acquisition_principal_id, p_purpose_id
        );
    ELSE
        PERFORM public.require_coach_guidance_authority_v1(
            auth_snapshot_id, p_acquisition_principal_id, p_purpose_id
        );
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.freeze_synthetic_coach_guidance_batch_v1(
    p_acquisition_principal_id UUID,
    p_project_id UUID,
    p_reviewer_principal_id UUID,
    p_idempotency_key TEXT
) RETURNS public.coach_guidance_review_batches
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    cutoff TIMESTAMPTZ;
    inventory JSONB;
    eligible_count INTEGER;
    excluded_count INTEGER;
    frame_hash TEXT;
    batch_hash TEXT;
    frame public.coach_guidance_review_frames;
    batch public.coach_guidance_review_batches;
    previous_batch public.coach_guidance_review_batches;
    next_revision INTEGER;
BEGIN
    IF length(COALESCE(p_idempotency_key, '')) NOT BETWEEN 1 AND 190 THEN
        RAISE EXCEPTION 'COACH_GUIDANCE_BATCH_INVALID';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(concat_ws(':',
        'coach-guidance-batch', p_acquisition_principal_id::text,
        p_project_id::text, p_reviewer_principal_id::text), 0));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'coach-guidance-idempotency:' || p_idempotency_key, 0));
    PERFORM public.require_coach_guidance_reviewer_access_v1(
        p_reviewer_principal_id
    );
    SELECT * INTO batch FROM public.coach_guidance_review_batches
     WHERE idempotency_key = p_idempotency_key;
    IF batch.id IS NOT NULL THEN
        SELECT * INTO STRICT frame FROM public.coach_guidance_review_frames
         WHERE id = batch.frame_id;
        IF frame.acquisition_principal_id <> p_acquisition_principal_id
           OR frame.project_id <> p_project_id
           OR frame.reviewer_principal_id <> p_reviewer_principal_id
        THEN RAISE EXCEPTION 'COACH_GUIDANCE_BATCH_REPLAY_CONFLICT'; END IF;
        PERFORM public.require_coach_guidance_assignment_live_v1(
            frame_item.review_assignment_id,
            frame_item.acquisition_principal_id,
            'coach_review')
          FROM public.coach_guidance_review_frame_items frame_item
         WHERE frame_item.frame_id = frame.id
           AND frame_item.membership_state = 'required';
        RETURN batch;
    END IF;
    cutoff := clock_timestamp();
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
        'review_assignment_id', source.review_assignment_id,
        'blind_packet_id', source.blind_packet_id,
        'membership_state', source.membership_state,
        'exclusion_reason', source.exclusion_reason,
        'canonical_position', source.canonical_position
    ) ORDER BY source.assigned_at, source.review_assignment_id), '[]'::jsonb),
    count(*) FILTER (WHERE source.membership_state = 'required'),
    count(*) FILTER (WHERE source.membership_state = 'excluded')
    INTO inventory, eligible_count, excluded_count
    FROM (
        SELECT assignment.id AS review_assignment_id,
               packet.id AS blind_packet_id,
               assignment.assigned_at,
               CASE WHEN EXISTS (
                    SELECT 1 FROM public.ml_review_assignment_events event
                     WHERE event.review_assignment_id = assignment.id
                       AND event.event_kind IN ('cancelled', 'expired')
                       AND event.occurred_at <= cutoff
               ) THEN 'excluded'
               WHEN assignment.expires_at IS NOT NULL
                    AND assignment.expires_at <= cutoff THEN 'excluded'
               ELSE 'required' END AS membership_state,
               CASE WHEN EXISTS (
                    SELECT 1 FROM public.ml_review_assignment_events event
                     WHERE event.review_assignment_id = assignment.id
                       AND event.event_kind = 'cancelled'
                       AND event.occurred_at <= cutoff
               ) THEN 'cancelled_before_cutoff'
               WHEN EXISTS (
                    SELECT 1 FROM public.ml_review_assignment_events event
                     WHERE event.review_assignment_id = assignment.id
                       AND event.event_kind = 'expired'
                       AND event.occurred_at <= cutoff
               ) THEN 'expired_before_cutoff'
               WHEN assignment.expires_at IS NOT NULL
                    AND assignment.expires_at <= cutoff
               THEN 'expired_before_cutoff' ELSE NULL END AS exclusion_reason,
               CASE WHEN NOT EXISTS (
                    SELECT 1 FROM public.ml_review_assignment_events event
                     WHERE event.review_assignment_id = assignment.id
                       AND event.event_kind IN ('cancelled', 'expired')
                       AND event.occurred_at <= cutoff
               ) AND (assignment.expires_at IS NULL
                      OR assignment.expires_at > cutoff)
               THEN row_number() OVER (
                    ORDER BY assignment.assigned_at, assignment.id
               ) ELSE NULL END AS canonical_position
          FROM public.ml_review_assignments assignment
          JOIN public.exercise_blind_packets packet
            ON packet.review_assignment_id = assignment.id
          JOIN public.exercise_audio_lineages lineage
            ON lineage.id = packet.audio_lineage_id
         WHERE assignment.learning_surface_id = 'confidence_classification'
           AND assignment.reviewer_principal_id = p_reviewer_principal_id
           AND assignment.reviewer_role = 'coach'
           AND assignment.assigned_at <= cutoff
           AND lineage.acquisition_principal_id = p_acquisition_principal_id
           AND lineage.project_id = p_project_id
    ) source;
    IF COALESCE(eligible_count, 0) + COALESCE(excluded_count, 0) = 0 THEN
        RAISE EXCEPTION 'COACH_GUIDANCE_BATCH_HAS_NO_ASSIGNMENTS';
    END IF;
    PERFORM public.require_coach_guidance_assignment_live_v1(
        (item->>'review_assignment_id')::uuid,
        p_acquisition_principal_id,
        'coach_review')
      FROM jsonb_array_elements(inventory) item
     WHERE item->>'membership_state' = 'required';
    frame_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'acquisition_principal_id', p_acquisition_principal_id,
        'project_id', p_project_id,
        'reviewer_principal_id', p_reviewer_principal_id,
        'batch_policy_version', 'coach-guidance-review-batch-v1',
        'cutoff_at', cutoff,
        'inventory', inventory));
    INSERT INTO public.coach_guidance_review_frames (
        acquisition_principal_id, project_id, reviewer_principal_id,
        batch_policy_version, cutoff_at, eligible_assignment_count,
        excluded_assignment_count, frame_sha256, idempotency_key
    ) VALUES (
        p_acquisition_principal_id, p_project_id, p_reviewer_principal_id,
        'coach-guidance-review-batch-v1', cutoff, eligible_count,
        excluded_count, frame_hash, 'frame:' || p_idempotency_key
    ) RETURNING * INTO frame;
    INSERT INTO public.coach_guidance_review_frame_items (
        frame_id, acquisition_principal_id, reviewer_principal_id,
        review_assignment_id, blind_packet_id, membership_state,
        exclusion_reason, canonical_position, item_sha256
    ) SELECT frame.id, p_acquisition_principal_id, p_reviewer_principal_id,
        (item->>'review_assignment_id')::uuid,
        (item->>'blind_packet_id')::uuid,
        item->>'membership_state', item->>'exclusion_reason',
        (item->>'canonical_position')::integer,
        public.exercise_json_sha256_v1(item)
      FROM jsonb_array_elements(inventory) item;
    SELECT existing_batch.* INTO previous_batch
      FROM public.coach_guidance_review_batches existing_batch
      JOIN public.coach_guidance_review_frames existing_frame
        ON existing_frame.id = existing_batch.frame_id
     WHERE existing_frame.acquisition_principal_id = p_acquisition_principal_id
       AND existing_frame.project_id = p_project_id
       AND existing_frame.reviewer_principal_id = p_reviewer_principal_id
     ORDER BY existing_batch.batch_revision DESC, existing_batch.created_at DESC
     LIMIT 1;
    next_revision := COALESCE(previous_batch.batch_revision, 0) + 1;
    batch_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'frame_id', frame.id, 'frame_sha256', frame.frame_sha256,
        'batch_revision', next_revision,
        'supersedes_batch_id', previous_batch.id));
    INSERT INTO public.coach_guidance_review_batches (
        frame_id, acquisition_principal_id, reviewer_principal_id,
        batch_revision, supersedes_batch_id, batch_sha256, idempotency_key
    ) VALUES (
        frame.id, p_acquisition_principal_id, p_reviewer_principal_id,
        next_revision, previous_batch.id, batch_hash, p_idempotency_key
    ) RETURNING * INTO batch;
    RETURN batch;
END;
$$;

CREATE OR REPLACE FUNCTION public.complete_synthetic_coach_guidance_batch_v1(
    p_review_batch_id UUID,
    p_reviewer_principal_id UUID,
    p_idempotency_key TEXT
) RETURNS public.coach_guidance_reveal_grants
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    batch public.coach_guidance_review_batches;
    frame public.coach_guidance_review_frames;
    inventory JSONB;
    inventory_hash TEXT;
    grant_hash TEXT;
    result public.coach_guidance_reveal_grants;
    item RECORD;
BEGIN
    IF length(COALESCE(p_idempotency_key, '')) NOT BETWEEN 1 AND 200 THEN
        RAISE EXCEPTION 'COACH_GUIDANCE_REVEAL_INVALID';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'coach-guidance-complete:' || p_review_batch_id::text, 0));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'coach-guidance-idempotency:' || p_idempotency_key, 0));
    SELECT * INTO STRICT batch FROM public.coach_guidance_review_batches
     WHERE id = p_review_batch_id
       AND reviewer_principal_id = p_reviewer_principal_id FOR UPDATE;
    SELECT * INTO STRICT frame FROM public.coach_guidance_review_frames
     WHERE id = batch.frame_id FOR SHARE;
    PERFORM public.require_coach_guidance_assignment_live_v1(
        frame_item.review_assignment_id,
        frame_item.acquisition_principal_id,
        'coach_review'
    )
      FROM public.coach_guidance_review_frame_items frame_item
     WHERE frame_item.frame_id = frame.id
       AND frame_item.membership_state = 'required';
    IF EXISTS (
        SELECT 1 FROM public.coach_guidance_review_frame_items frame_item
         WHERE frame_item.frame_id = frame.id
           AND frame_item.membership_state = 'required'
           AND NOT EXISTS (
               SELECT 1
                 FROM public.ml_judgments judgment
                 JOIN public.exercise_blind_packet_events event
                   ON event.judgment_id = judgment.id
                  AND event.event_kind = 'blind_judgment_submitted'
                WHERE judgment.review_assignment_id =
                      frame_item.review_assignment_id
                  AND judgment.actor_principal_id = p_reviewer_principal_id
                  AND judgment.actor_provenance = 'blind_coach'
                  AND judgment.decision IN (
                      'rating_yes', 'rating_in_between', 'rating_no',
                      'rating_not_sure', 'rating_audio_unclear'
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM public.ml_judgments later
                       WHERE later.supersedes_id = judgment.id
                  )
           )
    ) THEN RAISE EXCEPTION 'COACH_GUIDANCE_BATCH_INCOMPLETE'; END IF;
    SELECT jsonb_agg(jsonb_build_object(
        'review_assignment_id', frame_item.review_assignment_id,
        'judgment_id', judgment.id,
        'canonical_position', frame_item.canonical_position
    ) ORDER BY frame_item.canonical_position)
    INTO inventory
      FROM public.coach_guidance_review_frame_items frame_item
      JOIN LATERAL (
          SELECT candidate.id
            FROM public.ml_judgments candidate
            JOIN public.exercise_blind_packet_events event
              ON event.blind_packet_id = frame_item.blind_packet_id
             AND event.review_assignment_id = frame_item.review_assignment_id
             AND event.judgment_id = candidate.id
             AND event.event_kind = 'blind_judgment_submitted'
           WHERE candidate.review_assignment_id =
                 frame_item.review_assignment_id
             AND candidate.actor_principal_id = p_reviewer_principal_id
             AND candidate.actor_provenance = 'blind_coach'
             AND candidate.decision IN (
                 'rating_yes', 'rating_in_between', 'rating_no',
                 'rating_not_sure', 'rating_audio_unclear'
             )
             AND NOT EXISTS (
                 SELECT 1 FROM public.ml_judgments later
                  WHERE later.supersedes_id = candidate.id
             )
           ORDER BY candidate.decided_at DESC, candidate.id DESC LIMIT 1
      ) judgment ON true
     WHERE frame_item.frame_id = frame.id
       AND frame_item.membership_state = 'required';
    inventory_hash := public.exercise_json_sha256_v1(inventory);
    grant_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'review_batch_id', batch.id, 'batch_sha256', batch.batch_sha256,
        'reviewer_principal_id', p_reviewer_principal_id,
        'reveal_policy_version', 'coach-guidance-post-blind-reveal-v1',
        'judgment_inventory_sha256', inventory_hash));
    SELECT * INTO result FROM public.coach_guidance_reveal_grants
     WHERE idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.review_batch_id <> batch.id
           OR result.reviewer_principal_id <> p_reviewer_principal_id
           OR result.grant_sha256 <> grant_hash
        THEN RAISE EXCEPTION 'COACH_GUIDANCE_REVEAL_REPLAY_CONFLICT'; END IF;
        RETURN result;
    END IF;
    INSERT INTO public.coach_guidance_reveal_grants (
        review_batch_id, acquisition_principal_id, reviewer_principal_id,
        reveal_policy_version, judgment_inventory_sha256, grant_sha256,
        idempotency_key
    ) VALUES (
        batch.id, batch.acquisition_principal_id, p_reviewer_principal_id,
        'coach-guidance-post-blind-reveal-v1', inventory_hash, grant_hash,
        p_idempotency_key
    ) RETURNING * INTO result;
    FOR item IN SELECT value FROM jsonb_array_elements(inventory) LOOP
        INSERT INTO public.coach_guidance_reveal_grant_judgments (
            reveal_grant_id, acquisition_principal_id,
            review_assignment_id, judgment_id,
            canonical_position, item_sha256
        ) VALUES (
            result.id, batch.acquisition_principal_id,
            (item.value->>'review_assignment_id')::uuid,
            (item.value->>'judgment_id')::uuid,
            (item.value->>'canonical_position')::integer,
            public.exercise_json_sha256_v1(item.value)
        );
    END LOOP;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.record_synthetic_guidance_reveal_access_v1(
    p_reveal_grant_id UUID,
    p_reviewer_principal_id UUID,
    p_review_assignment_id UUID,
    p_access_purpose TEXT,
    p_idempotency_key TEXT
) RETURNS public.coach_guidance_reveal_accesses
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    result public.coach_guidance_reveal_accesses;
    access_hash TEXT;
    judgment_id UUID;
    grant_record public.coach_guidance_reveal_grants;
BEGIN
    IF length(COALESCE(p_idempotency_key, '')) NOT BETWEEN 1 AND 200
       OR p_access_purpose NOT IN ('acoustic_reference', 'guidance_authoring')
       OR NOT EXISTS (
           SELECT 1 FROM public.coach_guidance_reveal_grant_judgments item
            JOIN public.coach_guidance_reveal_grants grant_row
              ON grant_row.id = item.reveal_grant_id
           WHERE item.reveal_grant_id = p_reveal_grant_id
             AND item.review_assignment_id = p_review_assignment_id
             AND grant_row.reviewer_principal_id = p_reviewer_principal_id
       ) THEN RAISE EXCEPTION 'COACH_GUIDANCE_REVEAL_ACCESS_INVALID'; END IF;
    SELECT * INTO STRICT grant_record
      FROM public.coach_guidance_reveal_grants
     WHERE id = p_reveal_grant_id
       AND reviewer_principal_id = p_reviewer_principal_id;
    SELECT item.judgment_id INTO STRICT judgment_id
      FROM public.coach_guidance_reveal_grant_judgments item
      JOIN public.coach_guidance_reveal_grants grant_row
        ON grant_row.id = item.reveal_grant_id
     WHERE item.reveal_grant_id = p_reveal_grant_id
       AND item.review_assignment_id = p_review_assignment_id
       AND grant_row.reviewer_principal_id = p_reviewer_principal_id;
    access_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'reveal_grant_id', p_reveal_grant_id,
        'reviewer_principal_id', p_reviewer_principal_id,
        'review_assignment_id', p_review_assignment_id,
        'blind_judgment_id', judgment_id,
        'access_purpose', p_access_purpose));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'coach-guidance-idempotency:' || p_idempotency_key, 0));
    PERFORM public.require_coach_guidance_assignment_live_v1(
        p_review_assignment_id, grant_record.acquisition_principal_id,
        'coach_review'
    );
    SELECT * INTO result FROM public.coach_guidance_reveal_accesses
     WHERE idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.reveal_grant_id <> p_reveal_grant_id
           OR result.review_assignment_id <> p_review_assignment_id
           OR result.blind_judgment_id <> judgment_id
           OR result.access_purpose <> p_access_purpose
           OR result.access_sha256 <> access_hash
        THEN RAISE EXCEPTION 'COACH_GUIDANCE_REVEAL_ACCESS_REPLAY_CONFLICT'; END IF;
        RETURN result;
    END IF;
    INSERT INTO public.coach_guidance_reveal_accesses (
        reveal_grant_id, acquisition_principal_id,
        reviewer_principal_id, review_assignment_id,
        blind_judgment_id,
        access_purpose, access_sha256, idempotency_key
    ) VALUES (
        p_reveal_grant_id, grant_record.acquisition_principal_id,
        p_reviewer_principal_id,
        p_review_assignment_id, judgment_id, p_access_purpose, access_hash,
        p_idempotency_key
    ) RETURNING * INTO result;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.record_synthetic_coach_guidance_media_validity_v1(
    p_media_object_id UUID,
    p_acquisition_principal_id UUID,
    p_validity_state TEXT,
    p_reason_code TEXT,
    p_evidence_sha256 TEXT,
    p_idempotency_key TEXT
) RETURNS public.coach_guidance_media_validity_events
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    previous_event public.coach_guidance_media_validity_events;
    result public.coach_guidance_media_validity_events;
    event_hash TEXT;
    permit public.coach_guidance_upload_permits;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'COACH_GUIDANCE_REQUIRES_READ_COMMITTED';
    END IF;
    IF p_validity_state NOT IN ('active', 'quarantined', 'invalid', 'deleted')
       OR COALESCE(btrim(p_reason_code), '') = ''
       OR p_evidence_sha256 !~ '^[0-9a-f]{64}$'
       OR length(COALESCE(p_idempotency_key, '')) NOT BETWEEN 1 AND 200
    THEN RAISE EXCEPTION 'COACH_GUIDANCE_MEDIA_VALIDITY_INVALID'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'coach-guidance-media-validity:' || p_media_object_id::text, 0));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'coach-guidance-idempotency:' || p_idempotency_key, 0));
    SELECT * INTO previous_event
      FROM public.coach_guidance_media_validity_events event_row
     WHERE event_row.media_object_id = p_media_object_id
     ORDER BY event_row.occurred_at DESC, event_row.id DESC LIMIT 1;
    IF p_validity_state = 'active' THEN
        SELECT permit_row.* INTO permit
          FROM public.coach_guidance_upload_permits permit_row
          JOIN public.coach_guidance_upload_events upload_event
            ON upload_event.upload_permit_id = permit_row.id
           AND upload_event.event_kind = 'finalized'
           AND upload_event.media_object_id = p_media_object_id
         WHERE permit_row.acquisition_principal_id = p_acquisition_principal_id;
        IF permit.id IS NULL THEN
            RAISE EXCEPTION 'COACH_GUIDANCE_MEDIA_INITIAL_STATE_INVALID';
        END IF;
        PERFORM public.require_coach_guidance_reviewer_access_v1(
            permit.reviewer_principal_id
        );
        PERFORM public.require_coach_guidance_authority_v1(
            permit.authorization_snapshot_id,
            permit.acquisition_principal_id,
            permit.purpose_id
        );
    END IF;
    event_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'media_object_id', p_media_object_id,
        'acquisition_principal_id', p_acquisition_principal_id,
        'previous_event_id', previous_event.id,
        'validity_state', p_validity_state,
        'reason_code', p_reason_code,
        'evidence_sha256', p_evidence_sha256));
    SELECT * INTO result
      FROM public.coach_guidance_media_validity_events
     WHERE idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.event_sha256 <> event_hash THEN
            RAISE EXCEPTION 'COACH_GUIDANCE_MEDIA_VALIDITY_REPLAY_CONFLICT';
        END IF;
        RETURN result;
    END IF;
    IF previous_event.id IS NULL THEN
        IF p_validity_state <> 'active' THEN
            RAISE EXCEPTION 'COACH_GUIDANCE_MEDIA_INITIAL_STATE_INVALID';
        END IF;
    ELSIF p_validity_state = 'active'
       OR previous_event.validity_state = 'deleted' THEN
        RAISE EXCEPTION 'COACH_GUIDANCE_MEDIA_VALIDITY_TRANSITION_INVALID';
    END IF;
    INSERT INTO public.coach_guidance_media_validity_events (
        media_object_id, acquisition_principal_id, previous_event_id,
        validity_state, reason_code, evidence_sha256, event_sha256,
        idempotency_key
    ) VALUES (
        p_media_object_id, p_acquisition_principal_id, previous_event.id,
        p_validity_state, p_reason_code, p_evidence_sha256, event_hash,
        p_idempotency_key
    ) RETURNING * INTO result;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.require_coach_guidance_media_object_live_v1(
    p_media_object_id UUID,
    p_acquisition_principal_id UUID
) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'COACH_GUIDANCE_REQUIRES_READ_COMMITTED';
    END IF;
    -- Every consumer serializes with the validity writer.  Because this is a
    -- transaction-scoped lock, a successful leaf-state check remains true
    -- until the consuming transaction commits.
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'coach-guidance-media-validity:' || p_media_object_id::text, 0));
    IF NOT EXISTS (
        SELECT 1
          FROM public.exercise_media_objects media
          JOIN LATERAL (
              SELECT validity.validity_state
                FROM public.coach_guidance_media_validity_events validity
               WHERE validity.media_object_id = media.id
                 AND validity.acquisition_principal_id =
                     p_acquisition_principal_id
               ORDER BY validity.occurred_at DESC, validity.id DESC LIMIT 1
          ) current_validity ON current_validity.validity_state = 'active'
         WHERE media.id = p_media_object_id
           AND media.exact_bytes_sha256 ~ '^[0-9a-f]{64}$'
           AND media.byte_size > 0
    ) THEN RAISE EXCEPTION 'COACH_GUIDANCE_MEDIA_NOT_LIVE'; END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.require_coach_guidance_media_live_v1(
    p_media_binding_id UUID,
    p_acquisition_principal_id UUID
) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    binding public.coach_guidance_media_bindings;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'COACH_GUIDANCE_REQUIRES_READ_COMMITTED';
    END IF;
    SELECT * INTO binding FROM public.coach_guidance_media_bindings
     WHERE id = p_media_binding_id
       AND acquisition_principal_id = p_acquisition_principal_id;
    IF binding.id IS NULL THEN
        RAISE EXCEPTION 'COACH_GUIDANCE_MEDIA_NOT_LIVE';
    END IF;
    PERFORM public.require_coach_guidance_media_object_live_v1(
        binding.media_object_id, binding.acquisition_principal_id
    );
    IF NOT EXISTS (
        SELECT 1
          FROM public.exercise_media_objects media
          JOIN public.coach_guidance_upload_events upload_event
            ON upload_event.upload_permit_id = binding.upload_authorization_id
           AND upload_event.event_kind = 'finalized'
           AND upload_event.media_object_id = media.id
         WHERE media.id = binding.media_object_id
           AND media.exact_bytes_sha256 ~ '^[0-9a-f]{64}$'
           AND media.byte_size > 0
    ) OR EXISTS (
        SELECT 1 FROM public.data_purge_requests purge
         WHERE purge.acquisition_principal_id IN (
             binding.acquisition_principal_id,
             binding.source_acquisition_principal_id
         ) AND purge.state <> 'done'
    ) THEN RAISE EXCEPTION 'COACH_GUIDANCE_MEDIA_NOT_LIVE'; END IF;
    PERFORM public.require_coach_guidance_authority_v1(
        binding.authorization_snapshot_id,
        binding.acquisition_principal_id,
        binding.purpose_id
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.register_synthetic_independent_media_review_v1(
    p_media_object_id UUID,
    p_reviewer_principal_id UUID,
    p_contains_user_audio BOOLEAN,
    p_contains_user_transcript BOOLEAN,
    p_contains_user_identity BOOLEAN,
    p_contains_project_context BOOLEAN,
    p_contains_unique_user_passage BOOLEAN,
    p_language_policy_version TEXT,
    p_safety_policy_version TEXT,
    p_rights_policy_version TEXT,
    p_content_review_version TEXT,
    p_review_evidence_sha256 TEXT,
    p_idempotency_key TEXT
) RETURNS public.coach_guidance_independent_media_reviews
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    permit public.coach_guidance_upload_permits;
    media public.exercise_media_objects;
    review_hash TEXT;
    result public.coach_guidance_independent_media_reviews;
BEGIN
    IF COALESCE(p_contains_user_audio, true)
       OR COALESCE(p_contains_user_transcript, true)
       OR COALESCE(p_contains_user_identity, true)
       OR COALESCE(p_contains_project_context, true)
       OR COALESCE(p_contains_unique_user_passage, true)
       OR COALESCE(btrim(p_language_policy_version), '') = ''
       OR COALESCE(btrim(p_safety_policy_version), '') = ''
       OR COALESCE(btrim(p_rights_policy_version), '') = ''
       OR COALESCE(btrim(p_content_review_version), '') = ''
       OR p_review_evidence_sha256 !~ '^[0-9a-f]{64}$'
       OR length(COALESCE(p_idempotency_key, '')) NOT BETWEEN 1 AND 200
    THEN RAISE EXCEPTION 'COACH_GUIDANCE_INDEPENDENT_REVIEW_INVALID'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'coach-guidance-independent-review:' || p_media_object_id::text, 0));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'coach-guidance-idempotency:' || p_idempotency_key, 0));
    PERFORM public.require_coach_guidance_reviewer_access_v1(
        p_reviewer_principal_id
    );
    SELECT media_row.* INTO STRICT media
      FROM public.exercise_media_objects media_row
     WHERE media_row.id = p_media_object_id;
    SELECT permit_row.* INTO STRICT permit
      FROM public.coach_guidance_upload_permits permit_row
     JOIN public.coach_guidance_upload_events upload_event
        ON upload_event.upload_permit_id = permit_row.id
       AND upload_event.event_kind = 'finalized'
       AND upload_event.media_object_id = p_media_object_id
     WHERE permit_row.reviewer_principal_id = p_reviewer_principal_id;
    PERFORM public.require_coach_guidance_media_object_live_v1(
        p_media_object_id, permit.acquisition_principal_id
    );
    PERFORM public.require_coach_guidance_authority_v1(
        permit.authorization_snapshot_id,
        permit.acquisition_principal_id,
        permit.purpose_id
    );
    IF NOT EXISTS (
        SELECT 1
          FROM public.coach_guidance_media_validity_events validity
         WHERE validity.media_object_id = p_media_object_id
           AND validity.acquisition_principal_id = permit.acquisition_principal_id
           AND validity.validity_state = 'active'
           AND NOT EXISTS (
               SELECT 1
                 FROM public.coach_guidance_media_validity_events later
                WHERE later.previous_event_id = validity.id
           )
    ) THEN RAISE EXCEPTION 'COACH_GUIDANCE_MEDIA_NOT_LIVE'; END IF;
    review_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'media_object_id', media.id,
        'exact_bytes_sha256', media.exact_bytes_sha256,
        'byte_size', media.byte_size,
        'upload_permit_id', permit.id,
        'acquisition_principal_id', permit.acquisition_principal_id,
        'reviewer_principal_id', p_reviewer_principal_id,
        'contains_user_audio', false,
        'contains_user_transcript', false,
        'contains_user_identity', false,
        'contains_project_context', false,
        'contains_unique_user_passage', false,
        'language_policy_version', p_language_policy_version,
        'safety_policy_version', p_safety_policy_version,
        'rights_policy_version', p_rights_policy_version,
        'content_review_version', p_content_review_version,
        'review_evidence_sha256', p_review_evidence_sha256));
    SELECT * INTO result
      FROM public.coach_guidance_independent_media_reviews
     WHERE idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.review_sha256 <> review_hash THEN
            RAISE EXCEPTION 'COACH_GUIDANCE_INDEPENDENT_REVIEW_REPLAY_CONFLICT';
        END IF;
        RETURN result;
    END IF;
    INSERT INTO public.coach_guidance_independent_media_reviews (
        media_object_id, upload_permit_id, acquisition_principal_id,
        reviewer_principal_id, contains_user_audio,
        contains_user_transcript, contains_user_identity,
        contains_project_context, contains_unique_user_passage,
        language_policy_version, safety_policy_version,
        rights_policy_version, content_review_version,
        review_evidence_sha256, review_sha256, idempotency_key
    ) VALUES (
        media.id, permit.id, permit.acquisition_principal_id,
        p_reviewer_principal_id, false, false, false, false, false,
        p_language_policy_version, p_safety_policy_version,
        p_rights_policy_version, p_content_review_version,
        p_review_evidence_sha256, review_hash, p_idempotency_key
    ) RETURNING * INTO result;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.reserve_synthetic_coach_guidance_upload_v1(
    p_reveal_access_id UUID,
    p_reviewer_principal_id UUID,
    p_authorization_snapshot_id UUID,
    p_purpose_id TEXT,
    p_bucket TEXT,
    p_object_key TEXT,
    p_intended_exact_bytes_sha256 TEXT,
    p_intended_byte_size BIGINT,
    p_content_type TEXT,
    p_expires_at TIMESTAMPTZ,
    p_idempotency_key TEXT
) RETURNS public.coach_guidance_upload_permits
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    access_row public.coach_guidance_reveal_accesses;
    grant_row public.coach_guidance_reveal_grants;
    permit_hash TEXT;
    recovery_hash TEXT;
    result public.coach_guidance_upload_permits;
    recovery public.coach_guidance_upload_recoveries;
BEGIN
    IF p_purpose_id NOT IN (
        'coach_review', 'personalized_exercise_recommendation'
    ) OR COALESCE(btrim(p_bucket), '') = ''
       OR COALESCE(btrim(p_object_key), '') = ''
       OR p_intended_exact_bytes_sha256 !~ '^[0-9a-f]{64}$'
       OR p_intended_byte_size <= 0 OR p_content_type NOT LIKE 'video/%'
       OR p_expires_at <= clock_timestamp()
       OR length(COALESCE(p_idempotency_key, '')) NOT BETWEEN 1 AND 170
    THEN RAISE EXCEPTION 'COACH_GUIDANCE_UPLOAD_INVALID'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'coach-guidance-upload:' || p_idempotency_key, 0));
    SELECT * INTO STRICT access_row FROM public.coach_guidance_reveal_accesses
     WHERE id = p_reveal_access_id
       AND reviewer_principal_id = p_reviewer_principal_id
       AND access_purpose = 'guidance_authoring';
    SELECT * INTO STRICT grant_row FROM public.coach_guidance_reveal_grants
     WHERE id = access_row.reveal_grant_id
       AND reviewer_principal_id = p_reviewer_principal_id;
    PERFORM public.require_coach_guidance_assignment_live_v1(
        access_row.review_assignment_id, grant_row.acquisition_principal_id,
        p_purpose_id);
    PERFORM public.require_coach_guidance_authority_v1(
        p_authorization_snapshot_id, grant_row.acquisition_principal_id,
        p_purpose_id);
    permit_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'reveal_access_id', p_reveal_access_id,
        'reviewer_principal_id', p_reviewer_principal_id,
        'acquisition_principal_id', grant_row.acquisition_principal_id,
        'authorization_snapshot_id', p_authorization_snapshot_id,
        'purpose_id', p_purpose_id, 'storage_provider', 'r2',
        'bucket', p_bucket, 'object_key', p_object_key,
        'intended_exact_bytes_sha256', p_intended_exact_bytes_sha256,
        'intended_byte_size', p_intended_byte_size,
        'content_type', p_content_type, 'expires_at', p_expires_at));
    SELECT * INTO result FROM public.coach_guidance_upload_permits
     WHERE idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.permit_sha256 <> permit_hash OR NOT EXISTS (
            SELECT 1 FROM public.coach_guidance_upload_recoveries existing
             WHERE existing.upload_permit_id = result.id
        ) THEN RAISE EXCEPTION 'COACH_GUIDANCE_UPLOAD_REPLAY_CONFLICT'; END IF;
        RETURN result;
    END IF;
    INSERT INTO public.coach_guidance_upload_permits (
        acquisition_principal_id, reviewer_principal_id, reveal_access_id,
        authorization_snapshot_id, purpose_id, storage_provider, bucket,
        object_key, intended_exact_bytes_sha256, intended_byte_size,
        content_type, expires_at, permit_sha256, idempotency_key
    ) VALUES (
        grant_row.acquisition_principal_id, p_reviewer_principal_id,
        p_reveal_access_id, p_authorization_snapshot_id, p_purpose_id,
        'r2', p_bucket, p_object_key, p_intended_exact_bytes_sha256,
        p_intended_byte_size, p_content_type, p_expires_at, permit_hash,
        p_idempotency_key
    ) RETURNING * INTO result;
    recovery_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'upload_permit_id', result.id,
        'acquisition_principal_id', result.acquisition_principal_id,
        'storage_provider', result.storage_provider, 'bucket', result.bucket,
        'object_key', result.object_key,
        'intended_exact_bytes_sha256', result.intended_exact_bytes_sha256));
    INSERT INTO public.coach_guidance_upload_recoveries (
        upload_permit_id, acquisition_principal_id, storage_provider, bucket,
        object_key, intended_exact_bytes_sha256, recovery_sha256
    ) VALUES (
        result.id, result.acquisition_principal_id, result.storage_provider,
        result.bucket, result.object_key, result.intended_exact_bytes_sha256,
        recovery_hash
    ) RETURNING * INTO recovery;
    INSERT INTO public.coach_guidance_upload_events (
        upload_recovery_id, upload_permit_id, acquisition_principal_id,
        event_kind, event_sha256, idempotency_key
    ) VALUES (
        recovery.id, result.id, result.acquisition_principal_id, 'reserved',
        public.exercise_json_sha256_v1(jsonb_build_object(
            'upload_recovery_id', recovery.id, 'event_kind', 'reserved',
            'recovery_sha256', recovery.recovery_sha256)),
        'event:reserved:' || p_idempotency_key
    );
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.record_synthetic_coach_guidance_upload_event_v1(
    p_upload_permit_id UUID,
    p_reviewer_principal_id UUID,
    p_event_kind TEXT,
    p_media_object_id UUID,
    p_idempotency_key TEXT
) RETURNS public.coach_guidance_upload_events
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    permit public.coach_guidance_upload_permits;
    recovery public.coach_guidance_upload_recoveries;
    access_row public.coach_guidance_reveal_accesses;
    required_previous TEXT;
    event_hash TEXT;
    result public.coach_guidance_upload_events;
BEGIN
    IF p_event_kind NOT IN (
        'write_started', 'write_acknowledged', 'finalized', 'abandoned'
    ) OR length(COALESCE(p_idempotency_key, '')) NOT BETWEEN 1 AND 200
       OR (p_event_kind = 'finalized') <> (p_media_object_id IS NOT NULL)
    THEN RAISE EXCEPTION 'COACH_GUIDANCE_UPLOAD_EVENT_INVALID'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'coach-guidance-upload-permit:' || p_upload_permit_id::text, 0));
    SELECT * INTO STRICT permit FROM public.coach_guidance_upload_permits
     WHERE id = p_upload_permit_id
       AND reviewer_principal_id = p_reviewer_principal_id;
    SELECT * INTO STRICT recovery FROM public.coach_guidance_upload_recoveries
     WHERE upload_permit_id = permit.id
       AND acquisition_principal_id = permit.acquisition_principal_id;
    SELECT * INTO STRICT access_row FROM public.coach_guidance_reveal_accesses
     WHERE id = permit.reveal_access_id
       AND reviewer_principal_id = p_reviewer_principal_id;
    IF p_event_kind <> 'abandoned' THEN
        IF permit.expires_at <= clock_timestamp() THEN
            RAISE EXCEPTION 'COACH_GUIDANCE_UPLOAD_PERMIT_EXPIRED';
        END IF;
        PERFORM public.require_coach_guidance_assignment_live_v1(
            access_row.review_assignment_id, permit.acquisition_principal_id,
            permit.purpose_id);
        PERFORM public.require_coach_guidance_authority_v1(
            permit.authorization_snapshot_id,
            permit.acquisition_principal_id, permit.purpose_id);
    END IF;
    required_previous := CASE p_event_kind
        WHEN 'write_started' THEN 'reserved'
        WHEN 'write_acknowledged' THEN 'write_started'
        WHEN 'finalized' THEN 'write_acknowledged'
        WHEN 'abandoned' THEN 'reserved' END;
    event_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'upload_recovery_id', recovery.id, 'upload_permit_id', permit.id,
        'event_kind', p_event_kind, 'media_object_id', p_media_object_id));
    SELECT * INTO result FROM public.coach_guidance_upload_events
     WHERE idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.event_sha256 <> event_hash THEN
            RAISE EXCEPTION 'COACH_GUIDANCE_UPLOAD_EVENT_REPLAY_CONFLICT';
        END IF;
        IF p_event_kind = 'finalized' THEN
            PERFORM public.require_coach_guidance_media_object_live_v1(
                result.media_object_id, result.acquisition_principal_id
            );
        END IF;
        RETURN result;
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.coach_guidance_upload_events terminal_event
         WHERE terminal_event.upload_recovery_id = recovery.id
           AND terminal_event.event_kind IN ('finalized', 'abandoned')
    ) THEN RAISE EXCEPTION 'COACH_GUIDANCE_UPLOAD_ALREADY_TERMINAL'; END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.coach_guidance_upload_events prior
         WHERE prior.upload_recovery_id = recovery.id
           AND prior.event_kind = required_previous
    ) THEN RAISE EXCEPTION 'COACH_GUIDANCE_UPLOAD_EVENT_OUT_OF_ORDER'; END IF;
    IF p_event_kind = 'finalized' AND NOT EXISTS (
        SELECT 1 FROM public.exercise_media_objects media
         WHERE media.id = p_media_object_id
           AND media.storage_provider = permit.storage_provider
           AND media.bucket = permit.bucket
           AND media.object_key = permit.object_key
           AND media.exact_bytes_sha256 = permit.intended_exact_bytes_sha256
           AND media.byte_size = permit.intended_byte_size
           AND media.content_type = permit.content_type
    ) THEN RAISE EXCEPTION 'COACH_GUIDANCE_UPLOAD_MEDIA_MISMATCH'; END IF;
    INSERT INTO public.coach_guidance_upload_events (
        upload_recovery_id, upload_permit_id, acquisition_principal_id,
        event_kind, media_object_id, event_sha256, idempotency_key
    ) VALUES (
        recovery.id, permit.id, permit.acquisition_principal_id,
        p_event_kind, p_media_object_id, event_hash, p_idempotency_key
    ) RETURNING * INTO result;
    IF p_event_kind = 'finalized' THEN
        PERFORM public.record_synthetic_coach_guidance_media_validity_v1(
            p_media_object_id,
            permit.acquisition_principal_id,
            'active',
            'upload_finalized',
            event_hash,
            'media-validity:' || p_idempotency_key
        );
    END IF;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.register_synthetic_coach_guidance_media_v1(
    p_media_object_id UUID,
    p_acquisition_principal_id UUID,
    p_authorization_snapshot_id UUID,
    p_purpose_id TEXT,
    p_provenance_class TEXT,
    p_source_acquisition_principal_id UUID,
    p_independent_media_review_id UUID,
    p_upload_authorization_id UUID,
    p_language_policy_version TEXT,
    p_safety_policy_version TEXT,
    p_rights_policy_version TEXT,
    p_content_review_version TEXT,
    p_idempotency_key TEXT
) RETURNS public.coach_guidance_media_bindings
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    binding_hash TEXT;
    result public.coach_guidance_media_bindings;
BEGIN
    IF p_purpose_id NOT IN (
        'coach_review', 'personalized_exercise_recommendation'
    ) OR p_provenance_class NOT IN (
        'user_scoped', 'independent_clean_media', 'user_source_dependent'
    ) OR length(COALESCE(p_idempotency_key, '')) NOT BETWEEN 1 AND 200
       OR p_upload_authorization_id IS NULL
       OR COALESCE(btrim(p_language_policy_version), '') = ''
       OR COALESCE(btrim(p_safety_policy_version), '') = ''
       OR COALESCE(btrim(p_rights_policy_version), '') = ''
       OR COALESCE(btrim(p_content_review_version), '') = ''
       OR (p_provenance_class = 'independent_clean_media'
           AND (p_source_acquisition_principal_id IS NOT NULL
                OR p_independent_media_review_id IS NULL))
       OR (p_provenance_class <> 'independent_clean_media'
           AND p_source_acquisition_principal_id IS DISTINCT FROM
               p_acquisition_principal_id)
       OR (p_provenance_class <> 'independent_clean_media'
           AND p_independent_media_review_id IS NOT NULL)
    THEN RAISE EXCEPTION 'COACH_GUIDANCE_MEDIA_INVALID'; END IF;
    PERFORM public.require_coach_guidance_authority_v1(
        p_authorization_snapshot_id, p_acquisition_principal_id,
        p_purpose_id
    );
    IF NOT EXISTS (
        SELECT 1
          FROM public.coach_guidance_upload_permits permit
          JOIN public.coach_guidance_upload_events upload_event
            ON upload_event.upload_permit_id = permit.id
           AND upload_event.event_kind = 'finalized'
           AND upload_event.media_object_id = p_media_object_id
         WHERE permit.id = p_upload_authorization_id
           AND permit.acquisition_principal_id =
               p_acquisition_principal_id
           AND permit.authorization_snapshot_id =
               p_authorization_snapshot_id
           AND permit.purpose_id = p_purpose_id
           AND permit.expires_at > clock_timestamp()
    ) THEN RAISE EXCEPTION 'COACH_GUIDANCE_UPLOAD_NOT_FINALIZED'; END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.exercise_media_objects media
         WHERE media.id = p_media_object_id
           AND media.storage_provider = 'r2'
           AND media.exact_bytes_sha256 ~ '^[0-9a-f]{64}$'
           AND media.byte_size > 0
           AND media.content_type LIKE 'video/%'
    ) THEN RAISE EXCEPTION 'COACH_GUIDANCE_MEDIA_NOT_VERIFIED'; END IF;
    binding_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'media_object_id', p_media_object_id,
        'acquisition_principal_id', p_acquisition_principal_id,
        'authorization_snapshot_id', p_authorization_snapshot_id,
        'purpose_id', p_purpose_id,
        'provenance_class', p_provenance_class,
        'source_acquisition_principal_id', p_source_acquisition_principal_id,
        'independent_media_review_id', p_independent_media_review_id,
        'upload_authorization_id', p_upload_authorization_id,
        'language_policy_version', p_language_policy_version,
        'safety_policy_version', p_safety_policy_version,
        'rights_policy_version', p_rights_policy_version,
        'content_review_version', p_content_review_version));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'coach-guidance-media:' || p_idempotency_key, 0));
    PERFORM public.require_coach_guidance_media_object_live_v1(
        p_media_object_id, p_acquisition_principal_id
    );
    PERFORM public.require_coach_guidance_authority_v1(
        p_authorization_snapshot_id, p_acquisition_principal_id,
        p_purpose_id
    );
    IF NOT EXISTS (
        SELECT 1
          FROM public.coach_guidance_upload_permits permit
          JOIN public.coach_guidance_upload_events upload_event
            ON upload_event.upload_permit_id = permit.id
           AND upload_event.event_kind = 'finalized'
           AND upload_event.media_object_id = p_media_object_id
          JOIN public.exercise_media_objects media
            ON media.id = upload_event.media_object_id
           AND media.storage_provider = permit.storage_provider
           AND media.bucket = permit.bucket
           AND media.object_key = permit.object_key
           AND media.exact_bytes_sha256 =
               permit.intended_exact_bytes_sha256
           AND media.byte_size = permit.intended_byte_size
           AND media.content_type = permit.content_type
         WHERE permit.id = p_upload_authorization_id
           AND permit.acquisition_principal_id =
               p_acquisition_principal_id
           AND permit.authorization_snapshot_id =
               p_authorization_snapshot_id
           AND permit.purpose_id = p_purpose_id
           AND permit.expires_at > clock_timestamp()
           AND EXISTS (
               SELECT 1
                 FROM public.coach_guidance_media_validity_events validity
                WHERE validity.media_object_id = p_media_object_id
                  AND validity.acquisition_principal_id =
                      p_acquisition_principal_id
                  AND validity.validity_state = 'active'
                  AND NOT EXISTS (
                      SELECT 1
                        FROM public.coach_guidance_media_validity_events later
                       WHERE later.previous_event_id = validity.id
                  )
           )
    ) THEN RAISE EXCEPTION 'COACH_GUIDANCE_UPLOAD_NOT_FINALIZED'; END IF;
    IF p_provenance_class = 'independent_clean_media' AND NOT EXISTS (
        SELECT 1
          FROM public.coach_guidance_independent_media_reviews review
         WHERE review.id = p_independent_media_review_id
           AND review.media_object_id = p_media_object_id
           AND review.acquisition_principal_id = p_acquisition_principal_id
           AND review.language_policy_version = p_language_policy_version
           AND review.safety_policy_version = p_safety_policy_version
           AND review.rights_policy_version = p_rights_policy_version
           AND review.content_review_version = p_content_review_version
    ) THEN RAISE EXCEPTION 'COACH_GUIDANCE_INDEPENDENT_REVIEW_REQUIRED'; END IF;
    SELECT * INTO result FROM public.coach_guidance_media_bindings
     WHERE idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.binding_sha256 <> binding_hash THEN
            RAISE EXCEPTION 'COACH_GUIDANCE_MEDIA_REPLAY_CONFLICT';
        END IF;
        RETURN result;
    END IF;
    INSERT INTO public.coach_guidance_media_bindings (
        media_object_id, acquisition_principal_id,
        authorization_snapshot_id, purpose_id, provenance_class,
        source_acquisition_principal_id, independent_media_review_id,
        upload_authorization_id,
        language_policy_version, safety_policy_version,
        rights_policy_version, content_review_version, binding_sha256,
        idempotency_key
    ) VALUES (
        p_media_object_id, p_acquisition_principal_id,
        p_authorization_snapshot_id, p_purpose_id, p_provenance_class,
        p_source_acquisition_principal_id, p_independent_media_review_id,
        p_upload_authorization_id,
        p_language_policy_version, p_safety_policy_version,
        p_rights_policy_version, p_content_review_version, binding_hash,
        p_idempotency_key
    ) RETURNING * INTO result;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.create_synthetic_coach_guidance_attachment_v1(
    p_reveal_grant_id UUID,
    p_reveal_access_id UUID,
    p_reviewer_principal_id UUID,
    p_review_assignment_id UUID,
    p_feedback_membership_id UUID,
    p_feedback_candidate_id UUID,
    p_authorization_snapshot_id UUID,
    p_attachment_class TEXT,
    p_product_subcategory TEXT,
    p_exercise_offer_id UUID,
    p_exercise_version_id UUID,
    p_need_contract_id UUID,
    p_written_note TEXT,
    p_media_binding_id UUID,
    p_language_policy_version TEXT,
    p_safety_policy_version TEXT,
    p_rights_policy_version TEXT,
    p_content_review_version TEXT,
    p_idempotency_key TEXT
) RETURNS public.coach_guidance_attachment_versions
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    grant_row public.coach_guidance_reveal_grants;
    feedback_item public.feedback_v3_membership_items;
    membership public.feedback_v3_memberships;
    judgment_id UUID;
    offer public.exercise_service_offers;
    attachment_hash TEXT;
    version_hash TEXT;
    attachment public.coach_guidance_attachments;
    result public.coach_guidance_attachment_versions;
BEGIN
    IF length(COALESCE(p_idempotency_key, '')) NOT BETWEEN 1 AND 180
       OR p_attachment_class NOT IN (
           'general_product_guidance', 'mlc3_exercise'
       )
       OR (p_product_subcategory IS NOT NULL
           AND p_product_subcategory NOT IN ('structure', 'delivery'))
       OR (NULLIF(btrim(COALESCE(p_written_note, '')), '') IS NULL
           AND p_media_binding_id IS NULL)
       OR COALESCE(btrim(p_language_policy_version), '') = ''
       OR COALESCE(btrim(p_safety_policy_version), '') = ''
       OR COALESCE(btrim(p_rights_policy_version), '') = ''
       OR COALESCE(btrim(p_content_review_version), '') = ''
    THEN RAISE EXCEPTION 'COACH_GUIDANCE_ATTACHMENT_INVALID'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'coach-guidance-attachment:' || p_idempotency_key, 0));
    SELECT * INTO STRICT grant_row
      FROM public.coach_guidance_reveal_grants
     WHERE id = p_reveal_grant_id
       AND reviewer_principal_id = p_reviewer_principal_id;
    SELECT item.judgment_id INTO STRICT judgment_id
      FROM public.coach_guidance_reveal_grant_judgments item
      JOIN public.coach_guidance_reveal_accesses access_row
        ON access_row.id = p_reveal_access_id
       AND access_row.reveal_grant_id = item.reveal_grant_id
       AND access_row.review_assignment_id = item.review_assignment_id
       AND access_row.reviewer_principal_id = p_reviewer_principal_id
       AND access_row.access_purpose = 'guidance_authoring'
     WHERE item.reveal_grant_id = p_reveal_grant_id
       AND item.review_assignment_id = p_review_assignment_id;
    PERFORM public.require_coach_guidance_assignment_live_v1(
        p_review_assignment_id, grant_row.acquisition_principal_id,
        CASE WHEN p_attachment_class = 'mlc3_exercise'
             THEN 'personalized_exercise_recommendation'
             ELSE 'coach_review' END);
    SELECT * INTO STRICT membership FROM public.feedback_v3_memberships
     WHERE id = p_feedback_membership_id
       AND acquisition_principal_id = grant_row.acquisition_principal_id;
    SELECT * INTO STRICT feedback_item
      FROM public.feedback_v3_membership_items
     WHERE membership_id = p_feedback_membership_id
       AND candidate_id = p_feedback_candidate_id
       AND acquisition_principal_id = grant_row.acquisition_principal_id
       AND selected;
    IF membership.project_id <> (
        SELECT frame.project_id
          FROM public.coach_guidance_review_batches batch
          JOIN public.coach_guidance_review_frames frame
            ON frame.id = batch.frame_id
         WHERE batch.id = grant_row.review_batch_id
    ) OR NOT EXISTS (
        SELECT 1
          FROM public.exercise_blind_packets packet
          JOIN public.exercise_audio_lineages lineage
            ON lineage.id = packet.audio_lineage_id
         WHERE packet.review_assignment_id = p_review_assignment_id
           AND lineage.acquisition_principal_id =
               grant_row.acquisition_principal_id
           AND lineage.project_id = membership.project_id
           AND lineage.snippet_id = feedback_item.snippet_id
    ) THEN RAISE EXCEPTION 'COACH_GUIDANCE_FEEDBACK_LINEAGE_MISMATCH'; END IF;
    IF p_attachment_class = 'general_product_guidance' THEN
        IF p_exercise_offer_id IS NOT NULL OR p_exercise_version_id IS NOT NULL
           OR p_need_contract_id IS NOT NULL THEN
            RAISE EXCEPTION 'COACH_GUIDANCE_GENERAL_EXERCISE_FIELDS_FORBIDDEN';
        END IF;
        PERFORM public.require_coach_guidance_authority_v1(
            p_authorization_snapshot_id, grant_row.acquisition_principal_id,
            'coach_review');
    ELSE
        IF p_product_subcategory IS NOT NULL
           OR feedback_item.feedback_family <> 'confident_voice'
           OR p_exercise_offer_id IS NULL OR p_need_contract_id IS NULL THEN
            RAISE EXCEPTION 'COACH_GUIDANCE_MLC3_EXERCISE_INELIGIBLE';
        END IF;
        SELECT * INTO STRICT offer FROM public.exercise_service_offers
         WHERE id = p_exercise_offer_id
           AND acquisition_principal_id = grant_row.acquisition_principal_id
           AND feedback_membership_id = p_feedback_membership_id
           AND feedback_candidate_id = p_feedback_candidate_id;
        IF NOT EXISTS (
            SELECT 1
              FROM public.exercise_candidate_sets candidate_set
              JOIN public.exercise_need_contracts need
                ON need.id = candidate_set.need_contract_id
             WHERE candidate_set.id = offer.n1_candidate_set_id
               AND candidate_set.acquisition_principal_id =
                   grant_row.acquisition_principal_id
               AND candidate_set.need_contract_id = p_need_contract_id
               AND need.approval_state = 'approved'
        ) THEN RAISE EXCEPTION 'COACH_GUIDANCE_MLC3_NEED_MISMATCH'; END IF;
        IF offer.outcome = 'synthetic_matched' AND (
            p_exercise_version_id IS DISTINCT FROM
                offer.selected_exercise_version_id
            OR NOT EXISTS (
                SELECT 1 FROM public.exercise_versions version_row
                 WHERE version_row.id = p_exercise_version_id
                   AND version_row.need_contract_id = p_need_contract_id
                   AND version_row.safety_state = 'approved'
            )
        ) OR offer.outcome = 'synthetic_no_match'
             AND p_exercise_version_id IS NOT NULL THEN
            RAISE EXCEPTION 'COACH_GUIDANCE_MLC3_EXERCISE_INELIGIBLE';
        END IF;
        PERFORM public.require_coach_guidance_authority_v1(
            p_authorization_snapshot_id, grant_row.acquisition_principal_id,
            'personalized_exercise_recommendation');
    END IF;
    IF p_media_binding_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
          FROM public.coach_guidance_media_bindings binding
          JOIN public.exercise_media_objects media
            ON media.id = binding.media_object_id
          JOIN public.coach_guidance_upload_events upload_event
            ON upload_event.upload_permit_id = binding.upload_authorization_id
           AND upload_event.media_object_id = binding.media_object_id
           AND upload_event.event_kind = 'finalized'
         WHERE binding.id = p_media_binding_id
           AND binding.acquisition_principal_id =
               grant_row.acquisition_principal_id
           AND binding.purpose_id = CASE
               WHEN p_attachment_class = 'mlc3_exercise'
               THEN 'personalized_exercise_recommendation'
               ELSE 'coach_review' END
           AND (binding.provenance_class = 'independent_clean_media'
                OR binding.source_acquisition_principal_id =
                   grant_row.acquisition_principal_id)
           AND media.exact_bytes_sha256 ~ '^[0-9a-f]{64}$'
           AND media.byte_size > 0
    ) THEN RAISE EXCEPTION 'COACH_GUIDANCE_MEDIA_NOT_LIVE'; END IF;
    PERFORM public.require_coach_guidance_authority_v1(
        binding.authorization_snapshot_id,
        binding.acquisition_principal_id,
        binding.purpose_id
    )
      FROM public.coach_guidance_media_bindings binding
     WHERE binding.id = p_media_binding_id;
    IF p_media_binding_id IS NOT NULL THEN
        PERFORM public.require_coach_guidance_media_live_v1(
            p_media_binding_id, grant_row.acquisition_principal_id
        );
    END IF;
    attachment_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'review_batch_id', grant_row.review_batch_id,
        'reveal_grant_id', p_reveal_grant_id,
        'reveal_access_id', p_reveal_access_id,
        'blind_judgment_id', judgment_id,
        'review_assignment_id', p_review_assignment_id,
        'feedback_membership_id', p_feedback_membership_id,
        'feedback_candidate_id', p_feedback_candidate_id,
        'attachment_class', p_attachment_class,
        'product_subcategory', p_product_subcategory,
        'exercise_offer_id', p_exercise_offer_id,
        'exercise_version_id', p_exercise_version_id,
        'need_contract_id', p_need_contract_id));
    version_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'attachment_sha256', attachment_hash,
        'written_note', NULLIF(btrim(COALESCE(p_written_note, '')), ''),
        'media_binding_id', p_media_binding_id,
        'language_policy_version', p_language_policy_version,
        'safety_policy_version', p_safety_policy_version,
        'rights_policy_version', p_rights_policy_version,
        'content_review_version', p_content_review_version));
    SELECT version_row.* INTO result
      FROM public.coach_guidance_attachment_versions version_row
      JOIN public.coach_guidance_attachments attachment_row
        ON attachment_row.id = version_row.attachment_id
     WHERE attachment_row.idempotency_key = 'attachment:' || p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.version_sha256 <> version_hash THEN
            RAISE EXCEPTION 'COACH_GUIDANCE_ATTACHMENT_REPLAY_CONFLICT';
        END IF;
        RETURN result;
    END IF;
    INSERT INTO public.coach_guidance_attachments (
        acquisition_principal_id, recipient_principal_id,
        author_principal_id, review_batch_id, reveal_grant_id,
        reveal_access_id, blind_judgment_id, review_assignment_id,
        feedback_membership_id, feedback_candidate_id, attachment_class,
        product_subcategory, exercise_offer_id, exercise_version_id,
        need_contract_id, authorization_snapshot_id, attachment_sha256,
        idempotency_key
    ) VALUES (
        grant_row.acquisition_principal_id,
        grant_row.acquisition_principal_id, p_reviewer_principal_id,
        grant_row.review_batch_id, p_reveal_grant_id, p_reveal_access_id,
        judgment_id, p_review_assignment_id, p_feedback_membership_id,
        p_feedback_candidate_id, p_attachment_class,
        p_product_subcategory, p_exercise_offer_id, p_exercise_version_id,
        p_need_contract_id, p_authorization_snapshot_id, attachment_hash,
        'attachment:' || p_idempotency_key
    ) RETURNING * INTO attachment;
    INSERT INTO public.coach_guidance_attachment_versions (
        attachment_id, acquisition_principal_id, version_number,
        written_note, media_binding_id, language_policy_version,
        safety_policy_version, rights_policy_version,
        content_review_version, version_sha256, idempotency_key
    ) VALUES (
        attachment.id, attachment.acquisition_principal_id, 1,
        NULLIF(btrim(COALESCE(p_written_note, '')), ''), p_media_binding_id,
        p_language_policy_version, p_safety_policy_version,
        p_rights_policy_version, p_content_review_version, version_hash,
        'version:' || p_idempotency_key
    ) RETURNING * INTO result;
    INSERT INTO public.coach_guidance_lifecycle_events (
        attachment_version_id, acquisition_principal_id,
        actor_principal_id, authorization_snapshot_id, event_kind,
        event_payload, event_sha256, idempotency_key
    ) VALUES (
        result.id, attachment.acquisition_principal_id,
        p_reviewer_principal_id, p_authorization_snapshot_id, 'authored',
        jsonb_build_object('review_assignment_id', p_review_assignment_id),
        public.exercise_json_sha256_v1(jsonb_build_object(
            'attachment_version_id', result.id, 'event_kind', 'authored',
            'version_sha256', result.version_sha256)),
        'event:authored:' || p_idempotency_key
    );
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.record_synthetic_coach_guidance_event_v1(
    p_attachment_version_id UUID,
    p_actor_principal_id UUID,
    p_event_kind TEXT,
    p_event_payload JSONB,
    p_idempotency_key TEXT
) RETURNS public.coach_guidance_lifecycle_events
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    attachment public.coach_guidance_attachments;
    version_row public.coach_guidance_attachment_versions;
    required_previous TEXT;
    event_hash TEXT;
    result public.coach_guidance_lifecycle_events;
BEGIN
    IF p_event_kind NOT IN ('assigned', 'delivered', 'rendered', 'played')
       OR jsonb_typeof(COALESCE(p_event_payload, '{}'::jsonb)) <> 'object'
       OR length(COALESCE(p_idempotency_key, '')) NOT BETWEEN 1 AND 200
    THEN RAISE EXCEPTION 'COACH_GUIDANCE_EVENT_INVALID'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'coach-guidance-event:' || p_attachment_version_id::text, 0));
    SELECT * INTO STRICT version_row
      FROM public.coach_guidance_attachment_versions
     WHERE id = p_attachment_version_id;
    SELECT * INTO STRICT attachment FROM public.coach_guidance_attachments
     WHERE id = version_row.attachment_id;
    PERFORM public.require_coach_guidance_assignment_live_v1(
        attachment.review_assignment_id, attachment.acquisition_principal_id,
        CASE WHEN attachment.attachment_class = 'mlc3_exercise'
             THEN 'personalized_exercise_recommendation'
             ELSE 'coach_review' END);
    PERFORM public.require_coach_guidance_authority_v1(
        attachment.authorization_snapshot_id,
        attachment.acquisition_principal_id,
        CASE WHEN attachment.attachment_class = 'mlc3_exercise'
             THEN 'personalized_exercise_recommendation'
             ELSE 'coach_review' END);
    IF version_row.media_binding_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.coach_guidance_media_bindings binding
        JOIN public.exercise_media_objects media
          ON media.id = binding.media_object_id
        JOIN public.coach_guidance_upload_events upload_event
          ON upload_event.upload_permit_id = binding.upload_authorization_id
         AND upload_event.media_object_id = binding.media_object_id
         AND upload_event.event_kind = 'finalized'
         WHERE binding.id = version_row.media_binding_id
           AND media.exact_bytes_sha256 ~ '^[0-9a-f]{64}$'
           AND media.byte_size > 0
    ) THEN RAISE EXCEPTION 'COACH_GUIDANCE_MEDIA_NOT_LIVE'; END IF;
    PERFORM public.require_coach_guidance_authority_v1(
        binding.authorization_snapshot_id,
        binding.acquisition_principal_id,
        binding.purpose_id
    )
      FROM public.coach_guidance_media_bindings binding
     WHERE binding.id = version_row.media_binding_id;
    IF version_row.media_binding_id IS NOT NULL THEN
        PERFORM public.require_coach_guidance_media_live_v1(
            version_row.media_binding_id,
            attachment.acquisition_principal_id
        );
    END IF;
    IF p_event_kind IN ('assigned', 'delivered')
       AND p_actor_principal_id <> attachment.author_principal_id
       OR p_event_kind IN ('rendered', 'played')
       AND p_actor_principal_id <> attachment.recipient_principal_id
    THEN RAISE EXCEPTION 'COACH_GUIDANCE_EVENT_ACTOR_INVALID'; END IF;
    required_previous := CASE p_event_kind
        WHEN 'assigned' THEN 'authored'
        WHEN 'delivered' THEN 'assigned'
        WHEN 'rendered' THEN 'delivered'
        WHEN 'played' THEN 'rendered' END;
    IF NOT EXISTS (
        SELECT 1 FROM public.coach_guidance_lifecycle_events prior
         WHERE prior.attachment_version_id = p_attachment_version_id
           AND prior.event_kind = required_previous
    ) THEN RAISE EXCEPTION 'COACH_GUIDANCE_EVENT_OUT_OF_ORDER'; END IF;
    event_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'attachment_version_id', p_attachment_version_id,
        'actor_principal_id', p_actor_principal_id,
        'event_kind', p_event_kind,
        'event_payload', COALESCE(p_event_payload, '{}'::jsonb),
        'authorization_snapshot_id', attachment.authorization_snapshot_id));
    SELECT * INTO result FROM public.coach_guidance_lifecycle_events
     WHERE idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.event_sha256 <> event_hash THEN
            RAISE EXCEPTION 'COACH_GUIDANCE_EVENT_REPLAY_CONFLICT';
        END IF;
        RETURN result;
    END IF;
    INSERT INTO public.coach_guidance_lifecycle_events (
        attachment_version_id, acquisition_principal_id,
        actor_principal_id, authorization_snapshot_id, previous_event_id,
        event_kind, event_payload, event_sha256, idempotency_key
    ) VALUES (
        p_attachment_version_id, attachment.acquisition_principal_id,
        p_actor_principal_id, attachment.authorization_snapshot_id,
        (SELECT id FROM public.coach_guidance_lifecycle_events
          WHERE attachment_version_id = p_attachment_version_id
            AND event_kind = required_previous),
        p_event_kind, COALESCE(p_event_payload, '{}'::jsonb), event_hash,
        p_idempotency_key
    ) RETURNING * INTO result;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.publish_synthetic_coach_exercise_v1(
    p_source_attachment_version_id UUID,
    p_published_exercise_version_id UUID,
    p_catalog_snapshot_id UUID,
    p_authorization_snapshot_id UUID,
    p_idempotency_key TEXT
) RETURNS public.coach_guidance_publications
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    attachment public.coach_guidance_attachments;
    version_row public.coach_guidance_attachment_versions;
    binding public.coach_guidance_media_bindings;
    publication_class TEXT;
    publication_hash TEXT;
    result public.coach_guidance_publications;
BEGIN
    IF length(COALESCE(p_idempotency_key, '')) NOT BETWEEN 1 AND 200 THEN
        RAISE EXCEPTION 'COACH_GUIDANCE_PUBLICATION_INVALID';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'coach-guidance-publication:' || p_idempotency_key, 0));
    SELECT * INTO STRICT version_row
      FROM public.coach_guidance_attachment_versions
     WHERE id = p_source_attachment_version_id;
    SELECT * INTO STRICT attachment FROM public.coach_guidance_attachments
     WHERE id = version_row.attachment_id
       AND attachment_class = 'mlc3_exercise';
    SELECT * INTO STRICT binding FROM public.coach_guidance_media_bindings
     WHERE id = version_row.media_binding_id;
    PERFORM public.require_coach_guidance_assignment_live_v1(
        attachment.review_assignment_id, attachment.acquisition_principal_id,
        'personalized_exercise_recommendation');
    PERFORM public.require_coach_guidance_authority_v1(
        p_authorization_snapshot_id, attachment.acquisition_principal_id,
        'personalized_exercise_recommendation');
    PERFORM public.require_coach_guidance_authority_v1(
        binding.authorization_snapshot_id, binding.acquisition_principal_id,
        binding.purpose_id);
    PERFORM public.require_coach_guidance_media_live_v1(
        binding.id, attachment.acquisition_principal_id
    );
    IF NOT EXISTS (
        SELECT 1
          FROM public.coach_guidance_upload_events upload_event
          JOIN public.exercise_media_objects media
            ON media.id = upload_event.media_object_id
         WHERE upload_event.upload_permit_id = binding.upload_authorization_id
           AND upload_event.event_kind = 'finalized'
           AND upload_event.media_object_id = binding.media_object_id
           AND media.exact_bytes_sha256 ~ '^[0-9a-f]{64}$'
           AND media.byte_size > 0
    ) THEN RAISE EXCEPTION 'COACH_GUIDANCE_MEDIA_NOT_LIVE'; END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM public.exercise_versions exercise_version
          JOIN public.exercise_catalog_snapshot_items catalog_item
            ON catalog_item.exercise_version_id = exercise_version.id
         WHERE exercise_version.id = p_published_exercise_version_id
           AND exercise_version.id IS DISTINCT FROM
               attachment.exercise_version_id
           AND exercise_version.need_contract_id = attachment.need_contract_id
           AND exercise_version.media_object_id = binding.media_object_id
           AND exercise_version.safety_state = 'approved'
           AND exercise_version.catalogue_state = 'active'
           AND catalog_item.catalog_snapshot_id = p_catalog_snapshot_id
    ) THEN RAISE EXCEPTION 'COACH_GUIDANCE_PUBLICATION_VERSION_INVALID'; END IF;
    publication_class := CASE binding.provenance_class
        WHEN 'independent_clean_media' THEN 'independent_clean_media'
        ELSE 'user_source_dependent' END;
    IF publication_class = 'user_source_dependent'
       AND binding.source_acquisition_principal_id IS DISTINCT FROM
           attachment.acquisition_principal_id
    THEN RAISE EXCEPTION 'COACH_GUIDANCE_PUBLICATION_SOURCE_MISMATCH'; END IF;
    publication_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'source_attachment_version_id', p_source_attachment_version_id,
        'source_acquisition_principal_id', attachment.acquisition_principal_id,
        'published_exercise_version_id', p_published_exercise_version_id,
        'catalog_snapshot_id', p_catalog_snapshot_id,
        'provenance_class', publication_class,
        'authorization_snapshot_id', p_authorization_snapshot_id));
    SELECT * INTO result FROM public.coach_guidance_publications
     WHERE idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.publication_sha256 <> publication_hash THEN
            RAISE EXCEPTION 'COACH_GUIDANCE_PUBLICATION_REPLAY_CONFLICT';
        END IF;
        RETURN result;
    END IF;
    INSERT INTO public.coach_guidance_publications (
        source_attachment_version_id, source_acquisition_principal_id,
        published_exercise_version_id, catalog_snapshot_id,
        provenance_class, authorization_snapshot_id, publication_sha256,
        idempotency_key
    ) VALUES (
        p_source_attachment_version_id, attachment.acquisition_principal_id,
        p_published_exercise_version_id, p_catalog_snapshot_id,
        publication_class, p_authorization_snapshot_id, publication_hash,
        p_idempotency_key
    ) RETURNING * INTO result;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.invalidate_synthetic_coach_publication_v1(
    p_publication_id UUID,
    p_source_acquisition_principal_id UUID,
    p_reason_code TEXT,
    p_idempotency_key TEXT
) RETURNS public.coach_guidance_publication_invalidations
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    invalidation_hash TEXT;
    result public.coach_guidance_publication_invalidations;
BEGIN
    IF p_reason_code NOT IN (
        'authority_withdrawn', 'source_deleted', 'retention_expired',
        'source_quarantined'
    ) OR length(COALESCE(p_idempotency_key, '')) NOT BETWEEN 1 AND 200 THEN
        RAISE EXCEPTION 'COACH_GUIDANCE_INVALIDATION_INVALID';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'coach-guidance-invalidation:' || p_publication_id::text, 0));
    IF NOT EXISTS (
        SELECT 1 FROM public.coach_guidance_publications publication
         WHERE publication.id = p_publication_id
           AND publication.source_acquisition_principal_id =
               p_source_acquisition_principal_id
           AND publication.provenance_class = 'user_source_dependent'
    ) THEN RAISE EXCEPTION 'COACH_GUIDANCE_INVALIDATION_SOURCE_MISMATCH'; END IF;
    invalidation_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'publication_id', p_publication_id,
        'source_acquisition_principal_id', p_source_acquisition_principal_id,
        'reason_code', p_reason_code));
    SELECT * INTO result
      FROM public.coach_guidance_publication_invalidations
     WHERE publication_id = p_publication_id;
    IF result.id IS NOT NULL THEN
        IF result.invalidation_sha256 <> invalidation_hash THEN
            RAISE EXCEPTION 'COACH_GUIDANCE_INVALIDATION_REPLAY_CONFLICT';
        END IF;
        RETURN result;
    END IF;
    INSERT INTO public.coach_guidance_publication_invalidations (
        publication_id, source_acquisition_principal_id, reason_code,
        invalidation_sha256
    ) VALUES (
        p_publication_id, p_source_acquisition_principal_id, p_reason_code,
        invalidation_hash
    ) RETURNING * INTO result;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.reject_coach_guidance_runtime_event_v1()
RETURNS trigger LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
    IF NEW.serves_user OR NEW.dataset_eligible OR NOT NEW.synthetic_only THEN
        RAISE EXCEPTION 'COACH_GUIDANCE_D3_RUNTIME_DISABLED';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS coach_guidance_runtime_event_guard
    ON public.coach_guidance_lifecycle_events;
CREATE TRIGGER coach_guidance_runtime_event_guard
BEFORE INSERT ON public.coach_guidance_lifecycle_events
FOR EACH ROW EXECUTE FUNCTION public.reject_coach_guidance_runtime_event_v1();

-- Keep these declarations explicit: the release security scanner verifies that
-- every newly created public table enables RLS in the migration that creates it.
ALTER TABLE public.coach_guidance_review_frames ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.coach_guidance_review_frame_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.coach_guidance_review_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.coach_guidance_reveal_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.coach_guidance_reveal_grant_judgments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.coach_guidance_reveal_accesses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.coach_guidance_upload_permits ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.coach_guidance_upload_recoveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.coach_guidance_upload_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.coach_guidance_media_validity_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.coach_guidance_independent_media_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.coach_guidance_media_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.coach_guidance_attachments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.coach_guidance_attachment_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.coach_guidance_lifecycle_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.coach_guidance_publications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.coach_guidance_publication_invalidations ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE relation_name TEXT;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'coach_guidance_review_frames',
        'coach_guidance_review_frame_items',
        'coach_guidance_review_batches',
        'coach_guidance_reveal_grants',
        'coach_guidance_reveal_grant_judgments',
        'coach_guidance_reveal_accesses',
        'coach_guidance_upload_permits',
        'coach_guidance_upload_recoveries',
        'coach_guidance_upload_events',
        'coach_guidance_media_validity_events',
        'coach_guidance_independent_media_reviews',
        'coach_guidance_media_bindings',
        'coach_guidance_attachments',
        'coach_guidance_attachment_versions',
        'coach_guidance_lifecycle_events',
        'coach_guidance_publications',
        'coach_guidance_publication_invalidations'
    ] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',
                       relation_name);
        EXECUTE format('REVOKE ALL ON TABLE public.%I FROM PUBLIC, anon, authenticated',
                       relation_name);
        EXECUTE format('REVOKE ALL ON TABLE public.%I FROM service_role',
                       relation_name);
        EXECUTE format('GRANT SELECT ON TABLE public.%I TO service_role',
                       relation_name);
        EXECUTE format(
            'DROP TRIGGER IF EXISTS %I ON public.%I',
            relation_name || '_append_only', relation_name
        );
        EXECUTE format(
            'CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON public.%I '
            'FOR EACH ROW EXECUTE FUNCTION public.reject_coach_guidance_d3_mutation_v1()',
            relation_name || '_append_only', relation_name
        );
    END LOOP;
END;
$$;

REVOKE ALL ON FUNCTION public.reject_coach_guidance_d3_mutation_v1()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.require_coach_guidance_reviewer_access_v1(UUID)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.require_coach_guidance_authority_v1(UUID,UUID,TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.require_coach_guidance_authority_v1(UUID,UUID,TEXT)
    TO service_role;
REVOKE ALL ON FUNCTION public.require_coach_guidance_receipt_authority_v1(UUID,UUID,TEXT)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.require_coach_guidance_assignment_live_v1(UUID,UUID,TEXT)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.freeze_synthetic_coach_guidance_batch_v1(UUID,UUID,UUID,TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.freeze_synthetic_coach_guidance_batch_v1(UUID,UUID,UUID,TEXT)
    TO service_role;
REVOKE ALL ON FUNCTION public.complete_synthetic_coach_guidance_batch_v1(UUID,UUID,TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.complete_synthetic_coach_guidance_batch_v1(UUID,UUID,TEXT)
    TO service_role;
REVOKE ALL ON FUNCTION public.record_synthetic_guidance_reveal_access_v1(UUID,UUID,UUID,TEXT,TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_synthetic_guidance_reveal_access_v1(UUID,UUID,UUID,TEXT,TEXT)
    TO service_role;
REVOKE ALL ON FUNCTION public.record_synthetic_coach_guidance_media_validity_v1(UUID,UUID,TEXT,TEXT,TEXT,TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_synthetic_coach_guidance_media_validity_v1(UUID,UUID,TEXT,TEXT,TEXT,TEXT)
    TO service_role;
REVOKE ALL ON FUNCTION public.require_coach_guidance_media_object_live_v1(UUID,UUID)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.require_coach_guidance_media_live_v1(UUID,UUID)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.register_synthetic_independent_media_review_v1(UUID,UUID,BOOLEAN,BOOLEAN,BOOLEAN,BOOLEAN,BOOLEAN,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.register_synthetic_independent_media_review_v1(UUID,UUID,BOOLEAN,BOOLEAN,BOOLEAN,BOOLEAN,BOOLEAN,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT)
    TO service_role;
REVOKE ALL ON FUNCTION public.reserve_synthetic_coach_guidance_upload_v1(UUID,UUID,UUID,TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TIMESTAMPTZ,TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.reserve_synthetic_coach_guidance_upload_v1(UUID,UUID,UUID,TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TIMESTAMPTZ,TEXT)
    TO service_role;
REVOKE ALL ON FUNCTION public.record_synthetic_coach_guidance_upload_event_v1(UUID,UUID,TEXT,UUID,TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_synthetic_coach_guidance_upload_event_v1(UUID,UUID,TEXT,UUID,TEXT)
    TO service_role;
REVOKE ALL ON FUNCTION public.register_synthetic_coach_guidance_media_v1(UUID,UUID,UUID,TEXT,TEXT,UUID,UUID,UUID,TEXT,TEXT,TEXT,TEXT,TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.register_synthetic_coach_guidance_media_v1(UUID,UUID,UUID,TEXT,TEXT,UUID,UUID,UUID,TEXT,TEXT,TEXT,TEXT,TEXT)
    TO service_role;
REVOKE ALL ON FUNCTION public.create_synthetic_coach_guidance_attachment_v1(UUID,UUID,UUID,UUID,UUID,UUID,UUID,TEXT,TEXT,UUID,UUID,UUID,TEXT,UUID,TEXT,TEXT,TEXT,TEXT,TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.create_synthetic_coach_guidance_attachment_v1(UUID,UUID,UUID,UUID,UUID,UUID,UUID,TEXT,TEXT,UUID,UUID,UUID,TEXT,UUID,TEXT,TEXT,TEXT,TEXT,TEXT)
    TO service_role;
REVOKE ALL ON FUNCTION public.record_synthetic_coach_guidance_event_v1(UUID,UUID,TEXT,JSONB,TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_synthetic_coach_guidance_event_v1(UUID,UUID,TEXT,JSONB,TEXT)
    TO service_role;
REVOKE ALL ON FUNCTION public.publish_synthetic_coach_exercise_v1(UUID,UUID,UUID,UUID,TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.publish_synthetic_coach_exercise_v1(UUID,UUID,UUID,UUID,TEXT)
    TO service_role;
REVOKE ALL ON FUNCTION public.invalidate_synthetic_coach_publication_v1(UUID,UUID,TEXT,TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.invalidate_synthetic_coach_publication_v1(UUID,UUID,TEXT,TEXT)
    TO service_role;
REVOKE ALL ON FUNCTION public.reject_coach_guidance_runtime_event_v1()
    FROM PUBLIC, anon, authenticated, service_role;

NOTIFY pgrst, 'reload schema';
COMMIT;
