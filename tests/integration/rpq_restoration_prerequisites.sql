\set ON_ERROR_STOP on
-- Disposable-only additions to the M3 fixtures. Never a production migration.

ALTER TABLE public.v2_sessions
    ADD COLUMN IF NOT EXISTS take_index INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS recording_kind TEXT DEFAULT 'spoken',
    ADD COLUMN IF NOT EXISTS paired_session_id UUID,
    ADD COLUMN IF NOT EXISTS analysis_state TEXT DEFAULT 'ready';
ALTER TABLE public.snippets
    ADD COLUMN IF NOT EXISTS transcript TEXT;
ALTER TABLE public.processing_recording_attempts
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'completed',
    ADD COLUMN IF NOT EXISTS authorization_snapshot_id UUID,
    ADD COLUMN IF NOT EXISTS upload_idempotency_key TEXT,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL
        DEFAULT clock_timestamp();
ALTER TABLE public.processing_audio_objects
    ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;
ALTER TABLE public.processing_authorization_snapshots
    ALTER COLUMN id SET DEFAULT gen_random_uuid(),
    ADD COLUMN IF NOT EXISTS source_take_id UUID,
    ADD COLUMN IF NOT EXISTS source_recording_id UUID,
    ADD COLUMN IF NOT EXISTS operation_kind TEXT,
    ADD COLUMN IF NOT EXISTS authority_evidence_sha256 TEXT UNIQUE,
    ADD COLUMN IF NOT EXISTS pooled_learning_eligible BOOLEAN NOT NULL
        DEFAULT false,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL
        DEFAULT clock_timestamp(),
    ADD COLUMN IF NOT EXISTS authority_checked_at TIMESTAMPTZ NOT NULL
        DEFAULT clock_timestamp();
ALTER TABLE public.processing_authorization_receipts
    ADD COLUMN IF NOT EXISTS accepted_at TIMESTAMPTZ NOT NULL
        DEFAULT clock_timestamp();
ALTER TABLE public.projects
    ADD COLUMN IF NOT EXISTS setup JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE public.evidence_spans (
    id UUID PRIMARY KEY,
    owner_principal_id UUID NOT NULL REFERENCES public.owner_principals(id),
    project_id UUID NOT NULL REFERENCES public.projects(id),
    take_id UUID NOT NULL REFERENCES public.v2_sessions(id),
    recording_id UUID,
    legacy_piece_id UUID,
    evidence_kind TEXT NOT NULL,
    task_type TEXT NOT NULL,
    start_ms INTEGER,
    end_ms INTEGER,
    exact_text TEXT,
    evidence_hash TEXT NOT NULL UNIQUE,
    input_hash TEXT NOT NULL
);
ALTER TABLE public.evidence_spans
    ADD COLUMN IF NOT EXISTS start_char INTEGER,
    ADD COLUMN IF NOT EXISTS end_char INTEGER,
    ADD COLUMN IF NOT EXISTS replacement_text TEXT;
CREATE TABLE public.candidate_sets (
    id UUID PRIMARY KEY,
    owner_principal_id UUID NOT NULL REFERENCES public.owner_principals(id),
    project_id UUID NOT NULL REFERENCES public.projects(id),
    take_id UUID NOT NULL REFERENCES public.v2_sessions(id),
    taxonomy_version TEXT NOT NULL,
    selector_version TEXT NOT NULL,
    manager_rules_version TEXT NOT NULL,
    threshold_version TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    code_commit TEXT NOT NULL,
    complete BOOLEAN NOT NULL DEFAULT true
);
CREATE TABLE public.feedback_candidates (
    id UUID PRIMARY KEY,
    candidate_set_id UUID NOT NULL REFERENCES public.candidate_sets(id),
    evidence_span_id UUID NOT NULL REFERENCES public.evidence_spans(id),
    feedback_family TEXT NOT NULL,
    lane TEXT NOT NULL,
    candidate_key TEXT NOT NULL,
    rank_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    generated_output JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE(candidate_set_id,candidate_key)
);
CREATE TABLE public.feedback_exposures (
    id UUID PRIMARY KEY,
    candidate_set_id UUID NOT NULL REFERENCES public.candidate_sets(id),
    candidate_id UUID NOT NULL REFERENCES public.feedback_candidates(id),
    feedback_family TEXT NOT NULL CHECK (feedback_family IN (
        'confident_voice', 'rewrite_clarity', 'great_formulation'
    )),
    lane TEXT NOT NULL,
    is_selected BOOLEAN NOT NULL,
    position_shown INTEGER,
    shown_at TIMESTAMPTZ,
    selector_version TEXT NOT NULL,
    manager_rules_version TEXT NOT NULL,
    threshold_version TEXT NOT NULL,
    model_version TEXT,
    prompt_version TEXT,
    experiment_assignment JSONB NOT NULL DEFAULT '{}'::jsonb,
    input_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK (
        (is_selected AND position_shown IS NOT NULL AND shown_at IS NOT NULL)
        OR (NOT is_selected AND position_shown IS NULL AND shown_at IS NULL)
    ),
    UNIQUE (candidate_set_id, candidate_id)
);
CREATE TABLE public.confidence_self_reports (
    id UUID PRIMARY KEY,
    evidence_span_id UUID NOT NULL REFERENCES public.evidence_spans(id),
    task_type TEXT NOT NULL DEFAULT 'confidence_classification'
        CHECK (task_type = 'confidence_classification'),
    value TEXT NOT NULL CHECK (value IN (
        'yes', 'in_between', 'no', 'not_sure', 'audio_unclear'
    )),
    rater_role TEXT NOT NULL DEFAULT 'owner' CHECK (rater_role = 'owner'),
    rater_id UUID NOT NULL,
    taxonomy_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    supersedes_id UUID REFERENCES public.confidence_self_reports(id),
    idempotency_key TEXT NOT NULL UNIQUE
);
CREATE TABLE public.processing_audio_object_deletion_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    audio_object_id UUID NOT NULL UNIQUE
        REFERENCES public.processing_audio_objects(id) ON DELETE RESTRICT,
    purge_request_id UUID NOT NULL
        REFERENCES public.data_purge_requests(id) ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    storage_provider TEXT NOT NULL,
    bucket TEXT NOT NULL,
    object_key TEXT NOT NULL,
    exact_bytes_sha256 TEXT NOT NULL,
    evidence_sha256 TEXT NOT NULL,
    verified_deleted_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE public.ideal_text_document_generations (
    arc_id TEXT PRIMARY KEY,
    generation BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE public.ideal_text_document_snapshots (
    id UUID PRIMARY KEY,
    arc_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    acquisition_principal_id UUID NOT NULL REFERENCES public.owner_principals(id),
    project_id UUID NOT NULL REFERENCES public.projects(id),
    source_take_session_id UUID NOT NULL REFERENCES public.v2_sessions(id),
    version INTEGER NOT NULL,
    source_generation BIGINT NOT NULL,
    source_fingerprint_sha256 TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    payload JSONB NOT NULL,
    enrichment_seed JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE public.ideal_text_document_heads (
    arc_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    snapshot_id UUID NOT NULL REFERENCES public.ideal_text_document_snapshots(id),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(arc_id,actor_id)
);
CREATE TABLE public.ideal_text_part_revision (
    id BIGSERIAL PRIMARY KEY,
    arc_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    part_id UUID NOT NULL,
    action TEXT NOT NULL,
    text TEXT NOT NULL,
    root_phrase TEXT,
    take_session_id UUID,
    review_version INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE public.ideal_text_part (
    id UUID PRIMARY KEY,
    arc_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    ord INTEGER NOT NULL,
    text TEXT NOT NULL,
    locked_at TIMESTAMPTZ,
    iteration INTEGER NOT NULL DEFAULT 0,
    root_phrase TEXT,
    root_start INTEGER,
    root_end INTEGER,
    root_selected_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (arc_id, user_id, ord)
);
CREATE TABLE public.correction_decisions (
    id UUID PRIMARY KEY,
    evidence_span_id UUID NOT NULL REFERENCES public.evidence_spans(id),
    value TEXT NOT NULL,
    rater_id UUID NOT NULL,
    taxonomy_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    supersedes_id UUID NULL REFERENCES public.correction_decisions(id),
    idempotency_key TEXT NOT NULL UNIQUE
);
CREATE UNIQUE INDEX correction_decision_original_idx
    ON public.correction_decisions(evidence_span_id, rater_id)
    WHERE supersedes_id IS NULL;
CREATE UNIQUE INDEX correction_decision_revision_chain_idx
    ON public.correction_decisions(supersedes_id)
    WHERE supersedes_id IS NOT NULL;
