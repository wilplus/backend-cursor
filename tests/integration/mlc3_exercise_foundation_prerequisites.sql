\set ON_ERROR_STOP on

-- Disposable-only representation of objects deployed before migration 0313.
-- This is not an application migration and must never run in production.

CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        CREATE ROLE anon NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        CREATE ROLE authenticated NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        CREATE ROLE service_role NOLOGIN BYPASSRLS;
    END IF;
END;
$$;
ALTER ROLE service_role BYPASSRLS;

CREATE SCHEMA IF NOT EXISTS auth;
CREATE TABLE public.users_fixture (id UUID PRIMARY KEY);
CREATE TABLE public.owner_principals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID UNIQUE,
    guest_secret_hash TEXT UNIQUE
);
CREATE TABLE public.projects (
    id UUID PRIMARY KEY,
    owner_principal_id UUID NOT NULL REFERENCES public.owner_principals(id),
    display_name TEXT DEFAULT 'fixture'
);
CREATE TABLE public.v2_sessions (
    id UUID PRIMARY KEY,
    user_id UUID,
    owner_principal_id UUID,
    project_id UUID,
    arc_id UUID,
    recording_1_id UUID
);
CREATE TABLE public.recording_attempts (
    id UUID PRIMARY KEY,
    owner_principal_id UUID NOT NULL REFERENCES public.owner_principals(id),
    project_id UUID NOT NULL REFERENCES public.projects(id)
);
CREATE TABLE public.takes (
    id UUID PRIMARY KEY,
    recording_attempt_id UUID NOT NULL REFERENCES public.recording_attempts(id),
    owner_principal_id UUID NOT NULL REFERENCES public.owner_principals(id),
    project_id UUID NOT NULL REFERENCES public.projects(id)
);
CREATE TABLE public.snippets (
    id UUID PRIMARY KEY,
    session_id UUID,
    recording_id UUID,
    start_offset_ms INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL
);
CREATE TABLE public.owner_claim_events (
    source_owner_principal_id UUID NOT NULL,
    target_owner_principal_id UUID NOT NULL,
    claimed_user_id UUID
);
CREATE TABLE public.recordings (
    id UUID PRIMARY KEY,
    session_v2_id UUID,
    session_id UUID
);

CREATE TABLE public.processing_purpose_registry (
    id TEXT PRIMARY KEY,
    operational BOOLEAN NOT NULL DEFAULT false,
    authorizes_processing BOOLEAN NOT NULL DEFAULT false
);
INSERT INTO public.processing_purpose_registry (
    id, operational, authorizes_processing
) VALUES ('personalized_exercise_recommendation', false, false);

CREATE TABLE public.processing_policy_versions (
    id UUID PRIMARY KEY,
    version TEXT NOT NULL,
    status TEXT NOT NULL,
    activated_at TIMESTAMPTZ,
    retired_at TIMESTAMPTZ
);
CREATE TABLE public.processing_policy_purposes (
    policy_id UUID NOT NULL REFERENCES public.processing_policy_versions(id),
    purpose_id TEXT NOT NULL REFERENCES public.processing_purpose_registry(id),
    PRIMARY KEY (policy_id, purpose_id)
);
CREATE TABLE public.processing_authorization_receipts (
    id UUID PRIMARY KEY,
    acquisition_principal_id UUID NOT NULL REFERENCES public.owner_principals(id),
    policy_id UUID NOT NULL REFERENCES public.processing_policy_versions(id)
);
CREATE TABLE public.processing_authorization_receipt_purposes (
    receipt_id UUID NOT NULL REFERENCES public.processing_authorization_receipts(id),
    purpose_id TEXT NOT NULL REFERENCES public.processing_purpose_registry(id),
    PRIMARY KEY (receipt_id, purpose_id)
);
CREATE TABLE public.processing_service_blocks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL REFERENCES public.owner_principals(id),
    effective_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE public.processing_authorization_snapshots (
    id UUID PRIMARY KEY,
    acquisition_principal_id UUID NOT NULL REFERENCES public.owner_principals(id),
    receipt_id UUID NOT NULL REFERENCES public.processing_authorization_receipts(id),
    policy_id UUID NOT NULL REFERENCES public.processing_policy_versions(id),
    purpose_id TEXT NOT NULL REFERENCES public.processing_purpose_registry(id)
);
CREATE TABLE public.processing_recording_attempts (
    id UUID PRIMARY KEY,
    acquisition_principal_id UUID NOT NULL REFERENCES public.owner_principals(id),
    project_id UUID NOT NULL REFERENCES public.projects(id),
    recording_id UUID NOT NULL
);
CREATE TABLE public.processing_audio_objects (
    id UUID PRIMARY KEY,
    acquisition_principal_id UUID NOT NULL REFERENCES public.owner_principals(id),
    recording_attempt_id UUID NOT NULL REFERENCES public.processing_recording_attempts(id),
    storage_provider TEXT NOT NULL,
    bucket TEXT NOT NULL,
    object_key TEXT NOT NULL,
    byte_size BIGINT NOT NULL,
    content_type TEXT NOT NULL,
    exact_bytes_sha256 TEXT NOT NULL,
    verification_method TEXT NOT NULL,
    deleted_at TIMESTAMPTZ
);
CREATE TABLE public.processing_orphan_objects (
    id UUID PRIMARY KEY,
    acquisition_principal_id UUID NOT NULL,
    storage_provider TEXT NOT NULL,
    bucket TEXT NOT NULL,
    object_key TEXT NOT NULL,
    exact_bytes_sha256 TEXT NOT NULL
);
CREATE TABLE public.processing_provider_permits (
    id UUID PRIMARY KEY,
    acquisition_principal_id UUID NOT NULL,
    provider TEXT NOT NULL,
    operation_kind TEXT NOT NULL
);
CREATE TABLE public.processing_provider_operations (
    id UUID PRIMARY KEY,
    permit_id UUID NOT NULL REFERENCES public.processing_provider_permits(id),
    provider_operation_ref TEXT
);
CREATE TABLE public.phase1_processing_jobs (
    id UUID PRIMARY KEY,
    acquisition_principal_id UUID NOT NULL
);

CREATE TABLE public.ml_contract_epochs (
    learning_contract_version TEXT NOT NULL,
    data_epoch INTEGER NOT NULL,
    specification_version TEXT NOT NULL,
    dataset_creation_enabled BOOLEAN NOT NULL DEFAULT false,
    training_enabled BOOLEAN NOT NULL DEFAULT false,
    promotion_enabled BOOLEAN NOT NULL DEFAULT false,
    created_by TEXT NOT NULL,
    PRIMARY KEY (learning_contract_version, data_epoch)
);
CREATE TABLE public.ml_learning_surfaces (
    id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    trainable BOOLEAN NOT NULL DEFAULT true
);
INSERT INTO public.ml_learning_surfaces (id, description) VALUES
    ('confidence_classification', 'fixture'),
    ('correction_generation', 'fixture'),
    ('coach_comment_generation', 'fixture'),
    ('praise_generation', 'fixture'),
    ('praise_selection', 'fixture'),
    ('correction_selection', 'fixture'),
    ('ideal_text_generation', 'fixture');
CREATE TABLE public.ml_learning_surface_aliases (
    alias TEXT PRIMARY KEY,
    learning_surface_id TEXT REFERENCES public.ml_learning_surfaces(id),
    canonical_writes_allowed BOOLEAN NOT NULL,
    reason TEXT NOT NULL
);
CREATE TABLE public.ml_feedback_families (id TEXT PRIMARY KEY);
INSERT INTO public.ml_feedback_families (id) VALUES
    ('confident_voice'), ('great_formulation'), ('rewrite_clarity');
CREATE TABLE public.ml_canonical_events (
    id UUID PRIMARY KEY,
    learning_surface_id TEXT NOT NULL REFERENCES public.ml_learning_surfaces(id),
    feedback_family_id TEXT REFERENCES public.ml_feedback_families(id),
    payload_type TEXT NOT NULL,
    CONSTRAINT ml_canonical_event_payload_type_check CHECK (length(payload_type) > 0),
    CONSTRAINT ml_canonical_feedback_family_check CHECK (true)
);
CREATE TABLE public.ml_speakers (
    id UUID PRIMARY KEY
);
CREATE TABLE public.ml_speaker_principals (
    speaker_id UUID NOT NULL REFERENCES public.ml_speakers(id),
    acquisition_principal_id UUID NOT NULL REFERENCES public.owner_principals(id),
    PRIMARY KEY (speaker_id, acquisition_principal_id),
    UNIQUE (acquisition_principal_id)
);
CREATE TABLE public.ml_speaker_split_assignments (
    speaker_id UUID PRIMARY KEY REFERENCES public.ml_speakers(id)
);
CREATE OR REPLACE FUNCTION public.assign_ml_speaker_split_v1(
    p_speaker_id UUID,
    p_split_policy_version TEXT DEFAULT 'speaker-sha256-80-10-10-v1'
) RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO public.ml_speaker_split_assignments (speaker_id)
    VALUES (p_speaker_id) ON CONFLICT DO NOTHING;
END;
$$;
CREATE TABLE public.ml_object_artifacts (
    id UUID PRIMARY KEY,
    acquisition_principal_id UUID NOT NULL REFERENCES public.owner_principals(id),
    speaker_id UUID NOT NULL REFERENCES public.ml_speakers(id),
    object_store TEXT NOT NULL,
    bucket TEXT NOT NULL,
    object_key TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    byte_size BIGINT NOT NULL,
    content_type TEXT NOT NULL,
    artifact_kind TEXT NOT NULL
);
CREATE TABLE public.ml_evidence_spans (
    id UUID PRIMARY KEY,
    acquisition_principal_id UUID NOT NULL REFERENCES public.owner_principals(id),
    speaker_id UUID NOT NULL REFERENCES public.ml_speakers(id),
    project_id UUID NOT NULL REFERENCES public.projects(id),
    recording_attempt_id UUID NOT NULL,
    take_id UUID NOT NULL REFERENCES public.takes(id),
    object_artifact_id UUID REFERENCES public.ml_object_artifacts(id),
    coordinates JSONB NOT NULL
);
CREATE TABLE public.ml_review_assignments (
    id UUID PRIMARY KEY,
    learning_surface_id TEXT NOT NULL REFERENCES public.ml_learning_surfaces(id),
    evidence_span_id UUID NOT NULL REFERENCES public.ml_evidence_spans(id),
    reviewer_principal_id UUID NOT NULL REFERENCES public.owner_principals(id),
    blind_packet_sha256 TEXT NOT NULL,
    taxonomy_version TEXT NOT NULL,
    UNIQUE (id, reviewer_principal_id)
);
CREATE TABLE public.ml_judgments (
    id UUID PRIMARY KEY,
    review_assignment_id UUID REFERENCES public.ml_review_assignments(id),
    learning_surface_id TEXT NOT NULL REFERENCES public.ml_learning_surfaces(id),
    evidence_span_id UUID NOT NULL REFERENCES public.ml_evidence_spans(id),
    actor_provenance TEXT NOT NULL
);
CREATE OR REPLACE FUNCTION public.reject_mlc2_immutable_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'MLC canonical records are append-only'; END;
$$;
CREATE TABLE public.confident_voice_practice (
    id UUID PRIMARY KEY,
    owner_user_id UUID NOT NULL,
    take_session_id UUID NOT NULL
);
CREATE TABLE public.confident_voice_practice_attempt (
    id UUID PRIMARY KEY,
    practice_id UUID NOT NULL REFERENCES public.confident_voice_practice(id)
);
CREATE TABLE public.voice_album_practice (
    arc_id UUID NOT NULL,
    practice_attempt_id UUID NOT NULL REFERENCES public.confident_voice_practice_attempt(id),
    PRIMARY KEY (arc_id, practice_attempt_id)
);

CREATE TABLE public.data_purge_requests (
    id UUID PRIMARY KEY,
    acquisition_principal_id UUID NOT NULL REFERENCES public.owner_principals(id),
    state TEXT NOT NULL
);
CREATE TABLE public.data_purge_inventory_manifests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    purge_request_id UUID NOT NULL UNIQUE REFERENCES public.data_purge_requests(id),
    resolver_version TEXT NOT NULL,
    dependency_manifest_sha256 TEXT NOT NULL,
    subject_graph JSONB NOT NULL,
    subject_graph_sha256 TEXT NOT NULL,
    target_manifest_sha256 TEXT NOT NULL,
    catalog_sha256 TEXT NOT NULL,
    catalog_unknown_relations TEXT[] NOT NULL DEFAULT '{}'::text[]
);
CREATE TABLE public.data_purge_targets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    purge_request_id UUID NOT NULL REFERENCES public.data_purge_requests(id),
    target_kind TEXT NOT NULL,
    target_ref TEXT NOT NULL,
    resolver_version TEXT NOT NULL,
    state TEXT NOT NULL,
    initial_match_count INTEGER NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (purge_request_id, target_kind, target_ref)
);

CREATE OR REPLACE FUNCTION public.resolve_phase1_purge_subject_graph_v1(
    p_acquisition_principal_id UUID
) RETURNS JSONB LANGUAGE sql STABLE AS $$
SELECT jsonb_build_object(
    'principal_ids', jsonb_build_array(p_acquisition_principal_id::text),
    'user_ids', COALESCE((
        SELECT jsonb_agg(user_id::text) FROM public.owner_principals
         WHERE id = p_acquisition_principal_id AND user_id IS NOT NULL
    ), '[]'::jsonb),
    'project_ids', COALESCE((
        SELECT jsonb_agg(id::text) FROM public.projects
         WHERE owner_principal_id = p_acquisition_principal_id
    ), '[]'::jsonb),
    'take_ids', COALESCE((
        SELECT jsonb_agg(id::text) FROM public.v2_sessions
         WHERE owner_principal_id = p_acquisition_principal_id
    ), '[]'::jsonb),
    'recording_ids', '[]'::jsonb, 'snippet_ids', '[]'::jsonb,
    'permit_ids', '[]'::jsonb, 'job_ids', '[]'::jsonb,
    'unresolved_legacy_take_ids', '[]'::jsonb
)
$$;
