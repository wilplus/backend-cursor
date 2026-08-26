-- 0294 · canonical feedback and ML data contract.
--
-- Additive only. Existing product tables remain the live read model while
-- these tables receive parity-checked dual writes. Nothing historical is
-- rewritten or deleted by this migration.

BEGIN;

-- ── Immutable source snapshots ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.transcript_versions (
    id                       UUID PRIMARY KEY,
    owner_principal_id       UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    project_id               UUID NOT NULL
        REFERENCES public.projects(id) ON DELETE RESTRICT,
    take_id                  UUID NOT NULL
        REFERENCES public.v2_sessions(id) ON DELETE RESTRICT,
    version                  INTEGER NOT NULL CHECK (version > 0),
    source_kind              TEXT NOT NULL CHECK (source_kind IN (
        'automatic', 'aligned', 'user_corrected', 'coach_corrected'
    )),
    transcript_text          TEXT NOT NULL,
    transcript_hash          TEXT NOT NULL,
    input_hash               TEXT NOT NULL,
    model_version            TEXT NULL,
    prompt_version           TEXT NULL,
    code_commit              TEXT NOT NULL,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (take_id, version),
    UNIQUE (take_id, transcript_hash)
);

CREATE TABLE IF NOT EXISTS public.slides (
    id                       UUID PRIMARY KEY,
    owner_principal_id       UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    project_id               UUID NOT NULL
        REFERENCES public.projects(id) ON DELETE RESTRICT,
    take_id                  UUID NOT NULL
        REFERENCES public.v2_sessions(id) ON DELETE RESTRICT,
    transcript_version_id    UUID NOT NULL
        REFERENCES public.transcript_versions(id) ON DELETE RESTRICT,
    slide_index              INTEGER NOT NULL CHECK (slide_index >= 0),
    title                    TEXT NULL,
    source_payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (transcript_version_id, slide_index),
    UNIQUE (id, transcript_version_id)
);

CREATE TABLE IF NOT EXISTS public.paragraphs (
    id                       UUID PRIMARY KEY,
    owner_principal_id       UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    project_id               UUID NOT NULL
        REFERENCES public.projects(id) ON DELETE RESTRICT,
    take_id                  UUID NOT NULL
        REFERENCES public.v2_sessions(id) ON DELETE RESTRICT,
    transcript_version_id    UUID NOT NULL
        REFERENCES public.transcript_versions(id) ON DELETE RESTRICT,
    slide_id                 UUID NULL REFERENCES public.slides(id)
        ON DELETE RESTRICT,
    paragraph_index          INTEGER NOT NULL CHECK (paragraph_index >= 0),
    source_ideal_part_id     UUID NULL,
    paragraph_text           TEXT NOT NULL,
    start_char               INTEGER NOT NULL CHECK (start_char >= 0),
    end_char                 INTEGER NOT NULL CHECK (end_char > start_char),
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (transcript_version_id, paragraph_index),
    UNIQUE (id, transcript_version_id)
);

CREATE TABLE IF NOT EXISTS public.evidence_spans (
    id                       UUID PRIMARY KEY,
    owner_principal_id       UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    project_id               UUID NOT NULL
        REFERENCES public.projects(id) ON DELETE RESTRICT,
    take_id                  UUID NOT NULL
        REFERENCES public.v2_sessions(id) ON DELETE RESTRICT,
    recording_id             UUID NULL,
    transcript_version_id    UUID NULL
        REFERENCES public.transcript_versions(id) ON DELETE RESTRICT,
    slide_id                 UUID NULL REFERENCES public.slides(id)
        ON DELETE RESTRICT,
    paragraph_id             UUID NULL REFERENCES public.paragraphs(id)
        ON DELETE RESTRICT,
    legacy_piece_id          UUID NULL,
    evidence_kind            TEXT NOT NULL CHECK (evidence_kind IN (
        'audio_interval', 'transcript_span', 'correction_pair',
        'audio_and_transcript'
    )),
    task_type                TEXT NOT NULL CHECK (task_type IN (
        'confidence_classification', 'praise_generation',
        'praise_selection', 'correction_generation',
        'correction_selection', 'paragraph_decision'
    )),
    audio_ref                TEXT NULL,
    start_ms                 INTEGER NULL,
    end_ms                   INTEGER NULL,
    start_char               INTEGER NULL,
    end_char                 INTEGER NULL,
    exact_text               TEXT NULL,
    replacement_text         TEXT NULL,
    target_locator           JSONB NOT NULL DEFAULT '{}'::jsonb,
    technical_metadata       JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_hash            TEXT NOT NULL UNIQUE,
    input_hash               TEXT NOT NULL,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT evidence_audio_interval_check CHECK (
        (start_ms IS NULL AND end_ms IS NULL)
        OR (start_ms IS NOT NULL AND start_ms >= 0
            AND end_ms IS NOT NULL AND end_ms > start_ms)
    ),
    CONSTRAINT evidence_text_interval_check CHECK (
        (start_char IS NULL AND end_char IS NULL AND exact_text IS NULL)
        OR (start_char IS NOT NULL AND start_char >= 0
            AND end_char IS NOT NULL AND end_char > start_char
            AND exact_text IS NOT NULL AND length(exact_text) > 0)
    ),
    CONSTRAINT evidence_kind_payload_check CHECK (
        (evidence_kind = 'audio_interval'
            AND start_ms IS NOT NULL AND end_ms IS NOT NULL)
        OR (evidence_kind = 'transcript_span'
            AND transcript_version_id IS NOT NULL
            AND slide_id IS NOT NULL AND paragraph_id IS NOT NULL
            AND start_char IS NOT NULL AND end_char IS NOT NULL)
        OR (evidence_kind = 'correction_pair'
            AND transcript_version_id IS NOT NULL
            AND slide_id IS NOT NULL AND paragraph_id IS NOT NULL
            AND start_char IS NOT NULL AND end_char IS NOT NULL
            AND replacement_text IS NOT NULL
            AND length(replacement_text) > 0)
        OR (evidence_kind = 'audio_and_transcript'
            AND start_ms IS NOT NULL AND end_ms IS NOT NULL
            AND transcript_version_id IS NOT NULL
            AND slide_id IS NOT NULL AND paragraph_id IS NOT NULL
            AND start_char IS NOT NULL AND end_char IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS public.acoustic_feature_snapshots (
    id                       UUID PRIMARY KEY,
    evidence_span_id         UUID NOT NULL
        REFERENCES public.evidence_spans(id) ON DELETE RESTRICT,
    owner_principal_id       UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    feature_schema_version   TEXT NOT NULL,
    speaker_baseline_version TEXT NOT NULL,
    features                 JSONB NOT NULL,
    input_hash               TEXT NOT NULL,
    code_commit              TEXT NOT NULL,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (evidence_span_id, feature_schema_version,
            speaker_baseline_version, input_hash)
);

-- ── Complete candidate and exposure ledger ─────────────────────────────────

CREATE TABLE IF NOT EXISTS public.candidate_sets (
    id                       UUID PRIMARY KEY,
    owner_principal_id       UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    project_id               UUID NOT NULL
        REFERENCES public.projects(id) ON DELETE RESTRICT,
    take_id                  UUID NOT NULL
        REFERENCES public.v2_sessions(id) ON DELETE RESTRICT,
    taxonomy_version         TEXT NOT NULL,
    selector_version         TEXT NOT NULL,
    manager_rules_version    TEXT NOT NULL,
    threshold_version        TEXT NOT NULL,
    model_version            TEXT NULL,
    prompt_version           TEXT NULL,
    feature_schema_version   TEXT NULL,
    speaker_baseline_version TEXT NULL,
    experiment_assignment    JSONB NOT NULL DEFAULT '{}'::jsonb,
    input_hash               TEXT NOT NULL,
    idempotency_key          TEXT NOT NULL UNIQUE,
    code_commit              TEXT NOT NULL,
    complete                 BOOLEAN NOT NULL DEFAULT true
        CHECK (complete = true),
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (take_id, manager_rules_version, input_hash)
);

CREATE TABLE IF NOT EXISTS public.feedback_candidates (
    id                       UUID PRIMARY KEY,
    candidate_set_id         UUID NOT NULL
        REFERENCES public.candidate_sets(id) ON DELETE RESTRICT,
    evidence_span_id         UUID NOT NULL
        REFERENCES public.evidence_spans(id) ON DELETE RESTRICT,
    feedback_family          TEXT NOT NULL CHECK (feedback_family IN (
        'confident_voice', 'rewrite_clarity', 'great_formulation'
    )),
    lane                     TEXT NOT NULL,
    candidate_key            TEXT NOT NULL,
    candidate_score          DOUBLE PRECISION NULL,
    rank_evidence            JSONB NOT NULL DEFAULT '{}'::jsonb,
    generated_output         JSONB NOT NULL DEFAULT '{}'::jsonb,
    detector_version         TEXT NULL,
    rule_version             TEXT NULL,
    model_version            TEXT NULL,
    prompt_version           TEXT NULL,
    training_eligible        BOOLEAN NOT NULL DEFAULT false,
    ineligibility_reason     TEXT NULL,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (candidate_set_id, candidate_key),
    UNIQUE (id, candidate_set_id)
);

CREATE TABLE IF NOT EXISTS public.feedback_exposures (
    id                       UUID PRIMARY KEY,
    candidate_set_id         UUID NOT NULL
        REFERENCES public.candidate_sets(id) ON DELETE RESTRICT,
    candidate_id             UUID NOT NULL
        REFERENCES public.feedback_candidates(id) ON DELETE RESTRICT,
    feedback_family          TEXT NOT NULL CHECK (feedback_family IN (
        'confident_voice', 'rewrite_clarity', 'great_formulation'
    )),
    lane                     TEXT NOT NULL,
    is_selected              BOOLEAN NOT NULL,
    position_shown           INTEGER NULL CHECK (position_shown > 0),
    shown_at                 TIMESTAMPTZ NULL,
    selector_version         TEXT NOT NULL,
    manager_rules_version    TEXT NOT NULL,
    threshold_version        TEXT NOT NULL,
    model_version            TEXT NULL,
    prompt_version           TEXT NULL,
    experiment_assignment    JSONB NOT NULL DEFAULT '{}'::jsonb,
    input_hash               TEXT NOT NULL,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT feedback_exposure_shown_check CHECK (
        (is_selected AND position_shown IS NOT NULL AND shown_at IS NOT NULL)
        OR (NOT is_selected AND position_shown IS NULL AND shown_at IS NULL)
    ),
    UNIQUE (candidate_set_id, candidate_id)
);

-- ── Append-only machine and generation provenance ──────────────────────────

CREATE TABLE IF NOT EXISTS public.machine_predictions (
    id                       UUID PRIMARY KEY,
    evidence_span_id         UUID NOT NULL
        REFERENCES public.evidence_spans(id) ON DELETE RESTRICT,
    owner_principal_id       UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    project_id               UUID NOT NULL
        REFERENCES public.projects(id) ON DELETE RESTRICT,
    take_id                  UUID NOT NULL
        REFERENCES public.v2_sessions(id) ON DELETE RESTRICT,
    task_type                TEXT NOT NULL,
    surface                  TEXT NOT NULL,
    classification           TEXT NULL,
    score                    DOUBLE PRECISION NULL,
    model_version            TEXT NOT NULL,
    rule_version             TEXT NULL,
    threshold_version        TEXT NULL,
    feature_schema_version   TEXT NULL,
    speaker_baseline_version TEXT NULL,
    prompt_version           TEXT NULL,
    input_hash               TEXT NOT NULL,
    complete_output          JSONB NOT NULL,
    code_commit              TEXT NOT NULL,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (evidence_span_id, task_type, model_version, input_hash)
);

CREATE TABLE IF NOT EXISTS public.generation_runs (
    id                       UUID PRIMARY KEY,
    evidence_span_id         UUID NULL
        REFERENCES public.evidence_spans(id) ON DELETE RESTRICT,
    owner_principal_id       UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    project_id               UUID NOT NULL
        REFERENCES public.projects(id) ON DELETE RESTRICT,
    take_id                  UUID NOT NULL
        REFERENCES public.v2_sessions(id) ON DELETE RESTRICT,
    task_type                TEXT NOT NULL,
    surface                  TEXT NOT NULL,
    model_version            TEXT NOT NULL,
    prompt_version           TEXT NOT NULL,
    input_hash               TEXT NOT NULL,
    complete_output          JSONB NOT NULL,
    code_commit              TEXT NOT NULL,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (task_type, surface, model_version, prompt_version, input_hash)
);

-- ── Typed human judgments. No cross-task label table. ──────────────────────

CREATE TABLE IF NOT EXISTS public.evidence_review_assignments (
    id                  UUID PRIMARY KEY,
    evidence_span_id    UUID NOT NULL REFERENCES public.evidence_spans(id)
        ON DELETE RESTRICT,
    assignee_role       TEXT NOT NULL CHECK (assignee_role IN ('coach','peer')),
    assignee_id         UUID NOT NULL,
    blind_packet_hash   TEXT NOT NULL,
    assignment_reason   TEXT NOT NULL,
    idempotency_key     TEXT NOT NULL UNIQUE,
    assigned_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (evidence_span_id, assignee_role, assignee_id)
);

CREATE TABLE IF NOT EXISTS public.confidence_self_reports (
    id                  UUID PRIMARY KEY,
    evidence_span_id    UUID NOT NULL REFERENCES public.evidence_spans(id)
        ON DELETE RESTRICT,
    task_type           TEXT NOT NULL DEFAULT 'confidence_classification'
        CHECK (task_type = 'confidence_classification'),
    value               TEXT NOT NULL CHECK (value IN (
        'yes', 'in_between', 'no', 'not_sure', 'audio_unclear'
    )),
    rater_role          TEXT NOT NULL DEFAULT 'owner'
        CHECK (rater_role = 'owner'),
    rater_id            UUID NOT NULL,
    taxonomy_version    TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    supersedes_id       UUID NULL
        REFERENCES public.confidence_self_reports(id) ON DELETE RESTRICT,
    idempotency_key     TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS public.confidence_coach_labels (
    id                  UUID PRIMARY KEY,
    evidence_span_id    UUID NOT NULL REFERENCES public.evidence_spans(id)
        ON DELETE RESTRICT,
    task_type           TEXT NOT NULL DEFAULT 'confidence_classification'
        CHECK (task_type = 'confidence_classification'),
    value               TEXT NOT NULL CHECK (value IN (
        'yes', 'in_between', 'no', 'not_sure', 'audio_unclear'
    )),
    rater_role          TEXT NOT NULL DEFAULT 'coach'
        CHECK (rater_role = 'coach'),
    rater_id            UUID NOT NULL,
    taxonomy_version    TEXT NOT NULL,
    blind_packet_hash   TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    supersedes_id       UUID NULL
        REFERENCES public.confidence_coach_labels(id) ON DELETE RESTRICT,
    idempotency_key     TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS public.confidence_peer_labels (
    id                  UUID PRIMARY KEY,
    evidence_span_id    UUID NOT NULL REFERENCES public.evidence_spans(id)
        ON DELETE RESTRICT,
    task_type           TEXT NOT NULL DEFAULT 'confidence_classification'
        CHECK (task_type = 'confidence_classification'),
    value               TEXT NOT NULL CHECK (value IN (
        'yes', 'in_between', 'no', 'not_sure', 'audio_unclear'
    )),
    rater_role          TEXT NOT NULL DEFAULT 'peer'
        CHECK (rater_role = 'peer'),
    rater_id            UUID NOT NULL,
    taxonomy_version    TEXT NOT NULL,
    blind_packet_hash   TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    supersedes_id       UUID NULL
        REFERENCES public.confidence_peer_labels(id) ON DELETE RESTRICT,
    idempotency_key     TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS public.praise_helpfulness (
    id                  UUID PRIMARY KEY,
    evidence_span_id    UUID NOT NULL REFERENCES public.evidence_spans(id)
        ON DELETE RESTRICT,
    task_type           TEXT NOT NULL DEFAULT 'praise_helpfulness'
        CHECK (task_type = 'praise_helpfulness'),
    value               TEXT NOT NULL CHECK (value IN (
        'useful', 'not_useful', 'not_sure'
    )),
    rater_role          TEXT NOT NULL DEFAULT 'owner'
        CHECK (rater_role = 'owner'),
    rater_id            UUID NOT NULL,
    taxonomy_version    TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    supersedes_id       UUID NULL
        REFERENCES public.praise_helpfulness(id) ON DELETE RESTRICT,
    idempotency_key     TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS public.correction_decisions (
    id                  UUID PRIMARY KEY,
    evidence_span_id    UUID NOT NULL REFERENCES public.evidence_spans(id)
        ON DELETE RESTRICT,
    task_type           TEXT NOT NULL DEFAULT 'correction_decision'
        CHECK (task_type = 'correction_decision'),
    value               TEXT NOT NULL CHECK (value IN (
        'accept_proposed', 'keep_original'
    )),
    rater_role          TEXT NOT NULL DEFAULT 'owner'
        CHECK (rater_role = 'owner'),
    rater_id            UUID NOT NULL,
    taxonomy_version    TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    supersedes_id       UUID NULL
        REFERENCES public.correction_decisions(id) ON DELETE RESTRICT,
    idempotency_key     TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS public.paragraph_decisions (
    id                  UUID PRIMARY KEY,
    evidence_span_id    UUID NOT NULL REFERENCES public.evidence_spans(id)
        ON DELETE RESTRICT,
    paragraph_id        UUID NOT NULL REFERENCES public.paragraphs(id)
        ON DELETE RESTRICT,
    task_type           TEXT NOT NULL DEFAULT 'paragraph_versioning'
        CHECK (task_type = 'paragraph_versioning'),
    value               TEXT NOT NULL CHECK (value IN (
        'lock_for_next_take', 'keep_evolving', 'reopen_for_edit'
    )),
    rater_role          TEXT NOT NULL DEFAULT 'owner'
        CHECK (rater_role = 'owner'),
    rater_id            UUID NOT NULL,
    taxonomy_version    TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    supersedes_id       UUID NULL
        REFERENCES public.paragraph_decisions(id) ON DELETE RESTRICT,
    idempotency_key     TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS public.feedback_revisions (
    id                  UUID PRIMARY KEY,
    evidence_span_id    UUID NOT NULL REFERENCES public.evidence_spans(id)
        ON DELETE RESTRICT,
    task_type           TEXT NOT NULL DEFAULT 'feedback_revision'
        CHECK (task_type = 'feedback_revision'),
    value               TEXT NOT NULL,
    rater_role          TEXT NOT NULL CHECK (rater_role IN (
        'owner', 'coach', 'peer'
    )),
    rater_id            UUID NOT NULL,
    taxonomy_version    TEXT NOT NULL,
    revision_payload    JSONB NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    supersedes_id       UUID NULL
        REFERENCES public.feedback_revisions(id) ON DELETE RESTRICT,
    idempotency_key     TEXT NOT NULL UNIQUE
);

CREATE UNIQUE INDEX IF NOT EXISTS confidence_self_report_original_idx
    ON public.confidence_self_reports(evidence_span_id, rater_id)
    WHERE supersedes_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS confidence_coach_original_idx
    ON public.confidence_coach_labels(evidence_span_id, rater_id)
    WHERE supersedes_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS confidence_coach_revision_chain_idx
    ON public.confidence_coach_labels(supersedes_id)
    WHERE supersedes_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS confidence_peer_original_idx
    ON public.confidence_peer_labels(evidence_span_id, rater_id)
    WHERE supersedes_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS praise_helpfulness_original_idx
    ON public.praise_helpfulness(evidence_span_id, rater_id)
    WHERE supersedes_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS correction_decision_original_idx
    ON public.correction_decisions(evidence_span_id, rater_id)
    WHERE supersedes_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS paragraph_decision_original_idx
    ON public.paragraph_decisions(paragraph_id, rater_id)
    WHERE supersedes_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS paragraph_decision_revision_chain_idx
    ON public.paragraph_decisions(supersedes_id)
    WHERE supersedes_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS feedback_revision_chain_idx
    ON public.feedback_revisions(supersedes_id)
    WHERE supersedes_id IS NOT NULL;

-- ── Derived product state with supporting-decision foreign keys ─────────────

CREATE TABLE IF NOT EXISTS public.voice_album_admissions (
    id                        UUID PRIMARY KEY,
    evidence_span_id          UUID NOT NULL
        REFERENCES public.evidence_spans(id) ON DELETE RESTRICT,
    machine_prediction_id     UUID NOT NULL
        REFERENCES public.machine_predictions(id) ON DELETE RESTRICT,
    confidence_self_report_id UUID NOT NULL
        REFERENCES public.confidence_self_reports(id) ON DELETE RESTRICT,
    confidence_coach_label_id UUID NOT NULL
        REFERENCES public.confidence_coach_labels(id) ON DELETE RESTRICT,
    state                     TEXT NOT NULL CHECK (state IN (
        'admitted', 'removed'
    )),
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    supersedes_id             UUID NULL
        REFERENCES public.voice_album_admissions(id) ON DELETE RESTRICT,
    idempotency_key           TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS public.accepted_flagships (
    id                       UUID PRIMARY KEY,
    evidence_span_id         UUID NOT NULL
        REFERENCES public.evidence_spans(id) ON DELETE RESTRICT,
    correction_decision_id   UUID NOT NULL
        REFERENCES public.correction_decisions(id) ON DELETE RESTRICT,
    paragraph_id             UUID NOT NULL REFERENCES public.paragraphs(id)
        ON DELETE RESTRICT,
    exact_text               TEXT NOT NULL CHECK (length(exact_text) > 0),
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    supersedes_id            UUID NULL
        REFERENCES public.accepted_flagships(id) ON DELETE RESTRICT,
    idempotency_key          TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS public.root_phrases (
    id                       UUID PRIMARY KEY,
    paragraph_id             UUID NOT NULL REFERENCES public.paragraphs(id)
        ON DELETE RESTRICT,
    paragraph_decision_id    UUID NOT NULL
        REFERENCES public.paragraph_decisions(id) ON DELETE RESTRICT,
    exact_text               TEXT NOT NULL CHECK (length(exact_text) > 0),
    start_char               INTEGER NOT NULL CHECK (start_char >= 0),
    end_char                 INTEGER NOT NULL CHECK (end_char > start_char),
    state                    TEXT NOT NULL CHECK (state IN ('active', 'removed')),
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    supersedes_id            UUID NULL REFERENCES public.root_phrases(id)
        ON DELETE RESTRICT,
    idempotency_key          TEXT NOT NULL UNIQUE
);

CREATE UNIQUE INDEX IF NOT EXISTS root_phrase_revision_chain_idx
    ON public.root_phrases(supersedes_id)
    WHERE supersedes_id IS NOT NULL;

-- ── Durable per-stage processing provenance ────────────────────────────────

CREATE TABLE IF NOT EXISTS public.processing_stage_runs (
    id                       UUID PRIMARY KEY,
    processing_job_id        UUID NULL
        REFERENCES public.processing_jobs(id) ON DELETE SET NULL,
    owner_principal_id       UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    project_id               UUID NOT NULL
        REFERENCES public.projects(id) ON DELETE RESTRICT,
    take_id                  UUID NOT NULL
        REFERENCES public.v2_sessions(id) ON DELETE RESTRICT,
    stage                    TEXT NOT NULL CHECK (stage IN (
        'upload', 'transcription', 'alignment', 'feature_extraction',
        'candidate_generation', 'manager_selection', 'exposure',
        'human_decisions', 'derived_state'
    )),
    status                   TEXT NOT NULL CHECK (status IN (
        'pending', 'running', 'succeeded', 'failed', 'retryable'
    )),
    attempt_count            INTEGER NOT NULL CHECK (attempt_count > 0),
    input_hash               TEXT NOT NULL,
    output_hash              TEXT NULL,
    idempotency_key          TEXT NOT NULL UNIQUE,
    error                    JSONB NULL,
    started_at               TIMESTAMPTZ NULL,
    completed_at             TIMESTAMPTZ NULL,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT processing_stage_terminal_check CHECK (
        (status IN ('succeeded', 'failed') AND completed_at IS NOT NULL)
        OR status IN ('pending', 'running', 'retryable')
    )
);

-- ── Immutable dataset releases. Live product tables are never a dataset. ──

CREATE TABLE IF NOT EXISTS public.dataset_releases (
    id                       UUID PRIMARY KEY,
    release_identifier       TEXT NOT NULL UNIQUE,
    learning_surface         TEXT NOT NULL CHECK (learning_surface IN (
        'confidence_classification', 'praise_generation',
        'praise_selection', 'correction_generation',
        'correction_selection'
    )),
    source_cutoff_at         TIMESTAMPTZ NOT NULL,
    inclusion_rules          JSONB NOT NULL,
    exclusion_rules          JSONB NOT NULL,
    taxonomy_versions        JSONB NOT NULL,
    feature_versions         JSONB NOT NULL,
    extraction_code_commit   TEXT NOT NULL,
    item_counts              JSONB NOT NULL,
    manifest_checksum        TEXT NOT NULL UNIQUE,
    consent_retention_status JSONB NOT NULL,
    split_strategy_version   TEXT NOT NULL,
    created_by               UUID NOT NULL,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.dataset_split_assignments (
    id                       UUID PRIMARY KEY,
    owner_principal_id       UUID NOT NULL UNIQUE
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    split                    TEXT NOT NULL CHECK (split IN (
        'train', 'validation', 'test'
    )),
    strategy_version         TEXT NOT NULL,
    assignment_hash          TEXT NOT NULL,
    first_release_id         UUID NOT NULL
        REFERENCES public.dataset_releases(id) ON DELETE RESTRICT,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (id, owner_principal_id)
);

CREATE TABLE IF NOT EXISTS public.dataset_release_items (
    id                       UUID PRIMARY KEY,
    release_id               UUID NOT NULL
        REFERENCES public.dataset_releases(id) ON DELETE RESTRICT,
    owner_principal_id       UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    split_assignment_id      UUID NOT NULL,
    evidence_span_id         UUID NOT NULL
        REFERENCES public.evidence_spans(id) ON DELETE RESTRICT,
    learning_surface         TEXT NOT NULL CHECK (learning_surface IN (
        'confidence_classification', 'praise_generation',
        'praise_selection', 'correction_generation',
        'correction_selection'
    )),
    item_payload             JSONB NOT NULL,
    label_provenance         JSONB NOT NULL,
    eligibility_decision     TEXT NOT NULL CHECK (eligibility_decision IN (
        'eligible', 'research_only'
    )),
    item_checksum            TEXT NOT NULL,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT dataset_item_split_owner_fk FOREIGN KEY (
        split_assignment_id, owner_principal_id
    ) REFERENCES public.dataset_split_assignments(id, owner_principal_id)
        ON DELETE RESTRICT,
    UNIQUE (release_id, item_checksum)
);

CREATE TABLE IF NOT EXISTS public.dataset_exclusions (
    id                       UUID PRIMARY KEY,
    release_id               UUID NOT NULL
        REFERENCES public.dataset_releases(id) ON DELETE RESTRICT,
    owner_principal_id       UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    evidence_span_id         UUID NULL
        REFERENCES public.evidence_spans(id) ON DELETE RESTRICT,
    reason_code              TEXT NOT NULL,
    reason_detail            JSONB NOT NULL DEFAULT '{}'::jsonb,
    consent_retention_status JSONB NOT NULL,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (release_id, owner_principal_id, evidence_span_id, reason_code)
);

-- Every new table is service-role-only. The browser anon key gets no policy.
ALTER TABLE public.transcript_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.slides ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.paragraphs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.evidence_spans ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.acoustic_feature_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.candidate_sets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.feedback_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.feedback_exposures ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.machine_predictions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.generation_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.evidence_review_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.confidence_self_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.confidence_coach_labels ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.confidence_peer_labels ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.praise_helpfulness ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.correction_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.paragraph_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.feedback_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.voice_album_admissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.accepted_flagships ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.root_phrases ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.processing_stage_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.dataset_releases ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.dataset_split_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.dataset_release_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.dataset_exclusions ENABLE ROW LEVEL SECURITY;

-- ── Append-only enforcement ─────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.reject_canonical_feedback_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'canonical feedback evidence is append-only';
END;
$$;

DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'transcript_versions', 'slides', 'paragraphs', 'evidence_spans',
        'acoustic_feature_snapshots', 'candidate_sets',
        'feedback_candidates', 'feedback_exposures', 'machine_predictions',
        'generation_runs', 'evidence_review_assignments',
        'confidence_self_reports',
        'confidence_coach_labels', 'confidence_peer_labels',
        'praise_helpfulness', 'correction_decisions',
        'paragraph_decisions', 'feedback_revisions',
        'voice_album_admissions', 'accepted_flagships', 'root_phrases',
        'dataset_releases', 'dataset_split_assignments',
        'dataset_release_items', 'dataset_exclusions'
    ] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS %I_append_only ON public.%I',
                       table_name, table_name);
        EXECUTE format(
            'CREATE TRIGGER %I_append_only BEFORE UPDATE OR DELETE ON public.%I '
            'FOR EACH ROW EXECUTE FUNCTION public.reject_canonical_feedback_mutation()',
            table_name, table_name
        );
    END LOOP;
END;
$$;

-- ── Atomic owner decision against a selected, exposed candidate ─────────────

CREATE OR REPLACE FUNCTION public.record_feedback_exposure_v1(
    p_owner_principal_id UUID,
    p_project_id UUID,
    p_take_id UUID,
    p_bundle JSONB
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    take_row public.v2_sessions%ROWTYPE;
    transcript JSONB;
    versions JSONB;
    selected_keys JSONB;
    candidate_rows JSONB;
    transcript_id UUID;
    v_candidate_set_id UUID;
    slide_row JSONB;
    paragraph_row JSONB;
    candidate_row JSONB;
    evidence JSONB;
    feature_snapshot JSONB;
    prediction JSONB;
    generation JSONB;
    slide_id UUID;
    paragraph_id UUID;
    evidence_id UUID;
    candidate_id UUID;
    family TEXT;
    candidate_key TEXT;
    selected_position INTEGER;
    selected_count INTEGER;
    candidate_count INTEGER;
    stored_hash TEXT;
BEGIN
    IF jsonb_typeof(p_bundle) <> 'object' THEN
        RAISE EXCEPTION 'canonical exposure bundle must be an object';
    END IF;
    transcript := p_bundle -> 'transcript';
    versions := p_bundle -> 'versions';
    selected_keys := p_bundle -> 'selected_keys';
    candidate_rows := p_bundle -> 'candidates';
    IF jsonb_typeof(transcript) <> 'object'
       OR jsonb_typeof(versions) <> 'object'
       OR jsonb_typeof(selected_keys) <> 'array'
       OR jsonb_array_length(selected_keys) <> 3
       OR jsonb_typeof(candidate_rows) <> 'array'
       OR jsonb_array_length(candidate_rows) < 3 THEN
        RAISE EXCEPTION 'canonical exposure bundle is incomplete';
    END IF;
    IF NOT selected_keys @> '[{"feedback_family":"confident_voice"}]'::jsonb
       OR NOT selected_keys @> '[{"feedback_family":"rewrite_clarity"}]'::jsonb
       OR NOT selected_keys @> '[{"feedback_family":"great_formulation"}]'::jsonb THEN
        RAISE EXCEPTION 'canonical exposure requires all three families';
    END IF;
    IF NULLIF(p_bundle ->> 'idempotency_key', '') IS NULL THEN
        RAISE EXCEPTION 'canonical exposure idempotency key is required';
    END IF;
    -- Serialize only identical exposure identities. Concurrent first opens
    -- then collapse into one complete transaction and one replay instead of
    -- letting a unique-index race surface as a false dual-write failure.
    PERFORM pg_advisory_xact_lock(
        hashtextextended(p_bundle ->> 'idempotency_key', 0));

    SELECT * INTO take_row FROM public.v2_sessions
     WHERE id = p_take_id
       AND project_id = p_project_id
       AND owner_principal_id = p_owner_principal_id
       AND COALESCE(recording_kind, 'spoken') = 'spoken'
       AND paired_session_id IS NULL
     FOR SHARE;
    IF take_row.id IS NULL THEN
        RAISE EXCEPTION 'canonical exposure ownership rejected';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.projects project
         WHERE project.id = p_project_id
           AND project.owner_principal_id = p_owner_principal_id
    ) THEN
        RAISE EXCEPTION 'canonical exposure project rejected';
    END IF;

    transcript_id := (transcript ->> 'id')::uuid;
    INSERT INTO public.transcript_versions (
        id, owner_principal_id, project_id, take_id, version, source_kind,
        transcript_text, transcript_hash, input_hash, model_version,
        prompt_version, code_commit
    ) VALUES (
        transcript_id, p_owner_principal_id, p_project_id, p_take_id,
        (transcript ->> 'version')::integer,
        transcript ->> 'source_kind',
        transcript ->> 'text',
        transcript ->> 'transcript_hash',
        transcript ->> 'input_hash',
        NULLIF(transcript ->> 'model_version', ''),
        NULLIF(transcript ->> 'prompt_version', ''),
        p_bundle ->> 'code_commit'
    ) ON CONFLICT (take_id, version) DO NOTHING;
    SELECT row.id, row.transcript_hash INTO transcript_id, stored_hash
      FROM public.transcript_versions row
     WHERE row.take_id = p_take_id
       AND row.version = (transcript ->> 'version')::integer;
    IF transcript_id IS NULL
       OR stored_hash IS DISTINCT FROM transcript ->> 'transcript_hash' THEN
        RAISE EXCEPTION 'transcript version conflicts with immutable history';
    END IF;

    FOR slide_row IN SELECT value FROM jsonb_array_elements(
        COALESCE(transcript -> 'slides', '[]'::jsonb)
    ) LOOP
        INSERT INTO public.slides (
            id, owner_principal_id, project_id, take_id,
            transcript_version_id, slide_index, title, source_payload
        ) VALUES (
            (slide_row ->> 'id')::uuid,
            p_owner_principal_id, p_project_id, p_take_id, transcript_id,
            (slide_row ->> 'slide_index')::integer,
            NULLIF(slide_row ->> 'title', ''),
            COALESCE(slide_row -> 'source_payload', '{}'::jsonb)
        ) ON CONFLICT (transcript_version_id, slide_index) DO NOTHING;
    END LOOP;

    FOR paragraph_row IN SELECT value FROM jsonb_array_elements(
        COALESCE(transcript -> 'paragraphs', '[]'::jsonb)
    ) LOOP
        slide_id := NULL;
        IF NULLIF(paragraph_row ->> 'slide_index', '') IS NOT NULL THEN
            SELECT row.id INTO slide_id FROM public.slides row
             WHERE row.transcript_version_id = transcript_id
               AND row.slide_index =
                   (paragraph_row ->> 'slide_index')::integer;
        END IF;
        INSERT INTO public.paragraphs (
            id, owner_principal_id, project_id, take_id,
            transcript_version_id, slide_id, paragraph_index,
            source_ideal_part_id, paragraph_text, start_char, end_char
        ) VALUES (
            (paragraph_row ->> 'id')::uuid,
            p_owner_principal_id, p_project_id, p_take_id,
            transcript_id, slide_id,
            (paragraph_row ->> 'paragraph_index')::integer,
            NULLIF(paragraph_row ->> 'source_ideal_part_id', '')::uuid,
            paragraph_row ->> 'text',
            (paragraph_row ->> 'start_char')::integer,
            (paragraph_row ->> 'end_char')::integer
        ) ON CONFLICT (transcript_version_id, paragraph_index) DO NOTHING;
    END LOOP;

    SELECT row.id, row.input_hash INTO v_candidate_set_id, stored_hash
      FROM public.candidate_sets row
     WHERE row.idempotency_key = p_bundle ->> 'idempotency_key';
    IF v_candidate_set_id IS NOT NULL THEN
        IF stored_hash IS DISTINCT FROM p_bundle ->> 'input_hash' THEN
            RAISE EXCEPTION 'candidate-set idempotency conflict';
        END IF;
        RETURN jsonb_build_object(
            'candidate_set_id', v_candidate_set_id,
            'replayed', true
        );
    END IF;

    v_candidate_set_id := (p_bundle ->> 'candidate_set_id')::uuid;
    INSERT INTO public.candidate_sets (
        id, owner_principal_id, project_id, take_id, taxonomy_version,
        selector_version, manager_rules_version, threshold_version,
        model_version, prompt_version, feature_schema_version,
        speaker_baseline_version, experiment_assignment, input_hash,
        idempotency_key, code_commit
    ) VALUES (
        v_candidate_set_id, p_owner_principal_id, p_project_id, p_take_id,
        versions ->> 'taxonomy_version',
        versions ->> 'selector_version',
        versions ->> 'manager_rules_version',
        versions ->> 'threshold_version',
        NULLIF(versions ->> 'model_version', ''),
        NULLIF(versions ->> 'prompt_version', ''),
        NULLIF(versions ->> 'feature_schema_version', ''),
        NULLIF(versions ->> 'speaker_baseline_version', ''),
        COALESCE(p_bundle -> 'experiment_assignment', '{}'::jsonb),
        p_bundle ->> 'input_hash',
        p_bundle ->> 'idempotency_key',
        p_bundle ->> 'code_commit'
    );

    FOR candidate_row IN SELECT value FROM jsonb_array_elements(candidate_rows)
    LOOP
        family := candidate_row ->> 'feedback_family';
        candidate_key := candidate_row ->> 'candidate_key';
        evidence := candidate_row -> 'evidence';
        IF family NOT IN (
            'confident_voice', 'rewrite_clarity', 'great_formulation'
        ) OR candidate_key IS NULL OR jsonb_typeof(evidence) <> 'object' THEN
            RAISE EXCEPTION 'invalid canonical feedback candidate';
        END IF;

        slide_id := NULL;
        paragraph_id := NULL;
        IF NULLIF(evidence ->> 'slide_index', '') IS NOT NULL THEN
            SELECT row.id INTO slide_id FROM public.slides row
             WHERE row.transcript_version_id = transcript_id
               AND row.slide_index = (evidence ->> 'slide_index')::integer;
        END IF;
        IF NULLIF(evidence ->> 'paragraph_index', '') IS NOT NULL THEN
            SELECT row.id INTO paragraph_id FROM public.paragraphs row
             WHERE row.transcript_version_id = transcript_id
               AND row.paragraph_index =
                   (evidence ->> 'paragraph_index')::integer;
        END IF;

        evidence_id := (evidence ->> 'id')::uuid;
        INSERT INTO public.evidence_spans (
            id, owner_principal_id, project_id, take_id, recording_id,
            transcript_version_id, slide_id, paragraph_id, legacy_piece_id,
            evidence_kind, task_type, audio_ref, start_ms, end_ms,
            start_char, end_char, exact_text, replacement_text,
            target_locator, technical_metadata, evidence_hash, input_hash
        ) VALUES (
            evidence_id, p_owner_principal_id, p_project_id, p_take_id,
            NULLIF(evidence ->> 'recording_id', '')::uuid,
            CASE WHEN (evidence ->> 'uses_transcript')::boolean
                 THEN transcript_id ELSE NULL END,
            slide_id, paragraph_id,
            NULLIF(evidence ->> 'legacy_piece_id', '')::uuid,
            evidence ->> 'evidence_kind', evidence ->> 'task_type',
            NULLIF(evidence ->> 'audio_ref', ''),
            NULLIF(evidence ->> 'start_ms', '')::integer,
            NULLIF(evidence ->> 'end_ms', '')::integer,
            NULLIF(evidence ->> 'start_char', '')::integer,
            NULLIF(evidence ->> 'end_char', '')::integer,
            NULLIF(evidence ->> 'exact_text', ''),
            NULLIF(evidence ->> 'replacement_text', ''),
            COALESCE(evidence -> 'target_locator', '{}'::jsonb),
            COALESCE(evidence -> 'technical_metadata', '{}'::jsonb),
            evidence ->> 'evidence_hash', evidence ->> 'input_hash'
        ) ON CONFLICT (evidence_hash) DO NOTHING;
        SELECT row.id INTO evidence_id FROM public.evidence_spans row
         WHERE row.evidence_hash = evidence ->> 'evidence_hash'
           AND row.project_id = p_project_id
           AND row.take_id = p_take_id;
        IF evidence_id IS NULL THEN
            RAISE EXCEPTION 'evidence hash crosses a Take boundary';
        END IF;

        candidate_id := (candidate_row ->> 'id')::uuid;
        INSERT INTO public.feedback_candidates (
            id, candidate_set_id, evidence_span_id, feedback_family, lane,
            candidate_key, candidate_score, rank_evidence, generated_output,
            detector_version, rule_version, model_version, prompt_version,
            training_eligible, ineligibility_reason
        ) VALUES (
            candidate_id, v_candidate_set_id, evidence_id, family,
            candidate_row ->> 'lane', candidate_key,
            NULLIF(candidate_row ->> 'candidate_score', '')::double precision,
            COALESCE(candidate_row -> 'rank_evidence', '{}'::jsonb),
            COALESCE(candidate_row -> 'generated_output', '{}'::jsonb),
            NULLIF(candidate_row ->> 'detector_version', ''),
            NULLIF(candidate_row ->> 'rule_version', ''),
            NULLIF(candidate_row ->> 'model_version', ''),
            NULLIF(candidate_row ->> 'prompt_version', ''),
            COALESCE((candidate_row ->> 'training_eligible')::boolean, false),
            NULLIF(candidate_row ->> 'ineligibility_reason', '')
        );

        selected_position := NULL;
        SELECT ordinal::integer INTO selected_position
          FROM jsonb_array_elements(selected_keys) WITH ORDINALITY
               AS selected(value, ordinal)
         WHERE selected.value ->> 'id' = candidate_key
           AND selected.value ->> 'feedback_family' = family
         LIMIT 1;
        INSERT INTO public.feedback_exposures (
            id, candidate_set_id, candidate_id, feedback_family, lane,
            is_selected, position_shown, shown_at, selector_version,
            manager_rules_version, threshold_version, model_version,
            prompt_version, experiment_assignment, input_hash
        ) VALUES (
            (candidate_row ->> 'exposure_id')::uuid,
            v_candidate_set_id, candidate_id, family,
            candidate_row ->> 'lane', selected_position IS NOT NULL,
            selected_position,
            CASE WHEN selected_position IS NOT NULL THEN now() ELSE NULL END,
            versions ->> 'selector_version',
            versions ->> 'manager_rules_version',
            versions ->> 'threshold_version',
            NULLIF(versions ->> 'model_version', ''),
            NULLIF(versions ->> 'prompt_version', ''),
            COALESCE(p_bundle -> 'experiment_assignment', '{}'::jsonb),
            p_bundle ->> 'input_hash'
        );

        feature_snapshot := candidate_row -> 'acoustic_feature_snapshot';
        IF jsonb_typeof(feature_snapshot) = 'object' THEN
            INSERT INTO public.acoustic_feature_snapshots (
                id, evidence_span_id, owner_principal_id,
                feature_schema_version, speaker_baseline_version, features,
                input_hash, code_commit
            ) VALUES (
                (feature_snapshot ->> 'id')::uuid, evidence_id,
                p_owner_principal_id,
                feature_snapshot ->> 'feature_schema_version',
                feature_snapshot ->> 'speaker_baseline_version',
                feature_snapshot -> 'features',
                feature_snapshot ->> 'input_hash',
                p_bundle ->> 'code_commit'
            ) ON CONFLICT DO NOTHING;
        END IF;

        prediction := candidate_row -> 'machine_prediction';
        IF jsonb_typeof(prediction) = 'object' THEN
            INSERT INTO public.machine_predictions (
                id, evidence_span_id, owner_principal_id, project_id, take_id,
                task_type, surface, classification, score, model_version,
                rule_version, threshold_version, feature_schema_version,
                speaker_baseline_version, prompt_version, input_hash,
                complete_output, code_commit
            ) VALUES (
                (prediction ->> 'id')::uuid, evidence_id,
                p_owner_principal_id, p_project_id, p_take_id,
                prediction ->> 'task_type', prediction ->> 'surface',
                NULLIF(prediction ->> 'classification', ''),
                NULLIF(prediction ->> 'score', '')::double precision,
                prediction ->> 'model_version',
                NULLIF(prediction ->> 'rule_version', ''),
                NULLIF(prediction ->> 'threshold_version', ''),
                NULLIF(prediction ->> 'feature_schema_version', ''),
                NULLIF(prediction ->> 'speaker_baseline_version', ''),
                NULLIF(prediction ->> 'prompt_version', ''),
                prediction ->> 'input_hash',
                prediction -> 'complete_output',
                p_bundle ->> 'code_commit'
            ) ON CONFLICT DO NOTHING;
        END IF;
    END LOOP;

    FOR generation IN SELECT value FROM jsonb_array_elements(
        COALESCE(p_bundle -> 'generation_runs', '[]'::jsonb)
    ) LOOP
        INSERT INTO public.generation_runs (
            id, evidence_span_id, owner_principal_id, project_id, take_id,
            task_type, surface, model_version, prompt_version, input_hash,
            complete_output, code_commit
        ) VALUES (
            (generation ->> 'id')::uuid,
            NULLIF(generation ->> 'evidence_span_id', '')::uuid,
            p_owner_principal_id, p_project_id, p_take_id,
            generation ->> 'task_type', generation ->> 'surface',
            generation ->> 'model_version', generation ->> 'prompt_version',
            generation ->> 'input_hash', generation -> 'complete_output',
            p_bundle ->> 'code_commit'
        ) ON CONFLICT DO NOTHING;
    END LOOP;

    SELECT count(*)::integer INTO candidate_count
      FROM public.feedback_candidates candidate
     WHERE candidate.candidate_set_id = v_candidate_set_id;
    SELECT count(*)::integer INTO selected_count
      FROM public.feedback_exposures exposure
     WHERE exposure.candidate_set_id = v_candidate_set_id
       AND exposure.is_selected = true;
    IF candidate_count <> jsonb_array_length(candidate_rows)
       OR selected_count <> 3 THEN
        RAISE EXCEPTION 'canonical exposure ledger is incomplete';
    END IF;

    RETURN jsonb_build_object(
        'candidate_set_id', v_candidate_set_id,
        'candidate_count', candidate_count,
        'selected_count', selected_count,
        'replayed', false
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.record_feedback_human_decision_v1(
    p_project_id UUID,
    p_take_id UUID,
    p_rater_id UUID,
    p_feedback_id TEXT,
    p_feedback_family TEXT,
    p_value TEXT,
    p_taxonomy_version TEXT,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    take_row public.v2_sessions%ROWTYPE;
    owner_id UUID;
    candidate_row public.feedback_candidates%ROWTYPE;
    decision_id UUID := gen_random_uuid();
    existing_id UUID;
    existing_evidence_id UUID;
    existing_rater_id UUID;
    existing_value TEXT;
BEGIN
    SELECT * INTO take_row FROM public.v2_sessions
     WHERE id = p_take_id AND project_id = p_project_id
     FOR SHARE;
    IF take_row.id IS NULL OR take_row.user_id IS DISTINCT FROM p_rater_id THEN
        RAISE EXCEPTION 'feedback decision ownership rejected';
    END IF;
    SELECT id INTO owner_id FROM public.owner_principals
     WHERE id = take_row.owner_principal_id AND user_id = p_rater_id;
    IF owner_id IS NULL THEN
        RAISE EXCEPTION 'feedback decision principal rejected';
    END IF;

    SELECT candidate.* INTO candidate_row
      FROM public.feedback_candidates candidate
      JOIN public.candidate_sets candidate_set
        ON candidate_set.id = candidate.candidate_set_id
      JOIN public.feedback_exposures exposure
        ON exposure.candidate_id = candidate.id
       AND exposure.candidate_set_id = candidate_set.id
     WHERE candidate_set.take_id = p_take_id
       AND candidate.candidate_key = p_feedback_id
       AND candidate.feedback_family = p_feedback_family
       AND exposure.is_selected = true
     ORDER BY exposure.created_at DESC
     LIMIT 1;
    IF candidate_row.id IS NULL THEN
        RAISE EXCEPTION 'feedback decision requires a selected exposure';
    END IF;

    IF p_feedback_family = 'confident_voice' THEN
        IF p_value NOT IN ('yes','in_between','no','not_sure','audio_unclear') THEN
            RAISE EXCEPTION 'invalid confidence self-report';
        END IF;
        SELECT id, evidence_span_id, rater_id, value
          INTO existing_id, existing_evidence_id,
               existing_rater_id, existing_value
          FROM public.confidence_self_reports
         WHERE idempotency_key = p_idempotency_key;
        IF existing_id IS NULL THEN
            INSERT INTO public.confidence_self_reports (
                id, evidence_span_id, value, rater_id,
                taxonomy_version, idempotency_key
            ) VALUES (
                decision_id, candidate_row.evidence_span_id, p_value,
                p_rater_id, p_taxonomy_version, p_idempotency_key
            );
        ELSE
            IF existing_evidence_id IS DISTINCT FROM
               candidate_row.evidence_span_id
               OR existing_rater_id IS DISTINCT FROM p_rater_id
               OR existing_value IS DISTINCT FROM p_value THEN
                RAISE EXCEPTION 'confidence decision idempotency conflict';
            END IF;
            decision_id := existing_id;
        END IF;
    ELSIF p_feedback_family = 'great_formulation' THEN
        IF p_value NOT IN ('useful','not_useful','not_sure') THEN
            RAISE EXCEPTION 'invalid praise response';
        END IF;
        SELECT id, evidence_span_id, rater_id, value
          INTO existing_id, existing_evidence_id,
               existing_rater_id, existing_value
          FROM public.praise_helpfulness
         WHERE idempotency_key = p_idempotency_key;
        IF existing_id IS NULL THEN
            INSERT INTO public.praise_helpfulness (
                id, evidence_span_id, value, rater_id,
                taxonomy_version, idempotency_key
            ) VALUES (
                decision_id, candidate_row.evidence_span_id, p_value,
                p_rater_id, p_taxonomy_version, p_idempotency_key
            );
        ELSE
            IF existing_evidence_id IS DISTINCT FROM
               candidate_row.evidence_span_id
               OR existing_rater_id IS DISTINCT FROM p_rater_id
               OR existing_value IS DISTINCT FROM p_value THEN
                RAISE EXCEPTION 'praise decision idempotency conflict';
            END IF;
            decision_id := existing_id;
        END IF;
    ELSIF p_feedback_family = 'rewrite_clarity' THEN
        IF p_value NOT IN ('accept_proposed','keep_original') THEN
            RAISE EXCEPTION 'invalid correction decision';
        END IF;
        SELECT id, evidence_span_id, rater_id, value
          INTO existing_id, existing_evidence_id,
               existing_rater_id, existing_value
          FROM public.correction_decisions
         WHERE idempotency_key = p_idempotency_key;
        IF existing_id IS NULL THEN
            INSERT INTO public.correction_decisions (
                id, evidence_span_id, value, rater_id,
                taxonomy_version, idempotency_key
            ) VALUES (
                decision_id, candidate_row.evidence_span_id, p_value,
                p_rater_id, p_taxonomy_version, p_idempotency_key
            );
        ELSE
            IF existing_evidence_id IS DISTINCT FROM
               candidate_row.evidence_span_id
               OR existing_rater_id IS DISTINCT FROM p_rater_id
               OR existing_value IS DISTINCT FROM p_value THEN
                RAISE EXCEPTION 'correction decision idempotency conflict';
            END IF;
            decision_id := existing_id;
        END IF;
    ELSE
        RAISE EXCEPTION 'unknown feedback family';
    END IF;

    RETURN jsonb_build_object(
        'decision_id', decision_id,
        'evidence_span_id', candidate_row.evidence_span_id,
        'feedback_family', p_feedback_family,
        'value', p_value
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.record_paragraph_decision_v1(
    p_project_id UUID,
    p_take_id UUID,
    p_rater_id UUID,
    p_source_ideal_part_id UUID,
    p_exact_text TEXT,
    p_value TEXT,
    p_taxonomy_version TEXT,
    p_evidence_id UUID,
    p_evidence_hash TEXT,
    p_input_hash TEXT,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    take_row public.v2_sessions%ROWTYPE;
    paragraph_row public.paragraphs%ROWTYPE;
    evidence_id UUID;
    existing public.paragraph_decisions%ROWTYPE;
    latest public.paragraph_decisions%ROWTYPE;
    latest_root public.root_phrases%ROWTYPE;
    created_id UUID := gen_random_uuid();
BEGIN
    IF p_value NOT IN (
        'lock_for_next_take', 'keep_evolving', 'reopen_for_edit'
    ) OR NULLIF(trim(p_exact_text), '') IS NULL
       OR NULLIF(trim(p_evidence_hash), '') IS NULL
       OR NULLIF(trim(p_input_hash), '') IS NULL
       OR NULLIF(trim(p_idempotency_key), '') IS NULL THEN
        RAISE EXCEPTION 'invalid paragraph decision payload';
    END IF;
    SELECT * INTO take_row FROM public.v2_sessions
     WHERE id = p_take_id AND project_id = p_project_id
     FOR SHARE;
    IF take_row.id IS NULL OR take_row.user_id IS DISTINCT FROM p_rater_id
       OR NOT EXISTS (
           SELECT 1 FROM public.owner_principals owner
            WHERE owner.id = take_row.owner_principal_id
              AND owner.user_id = p_rater_id
       ) THEN
        RAISE EXCEPTION 'paragraph decision ownership rejected';
    END IF;
    SELECT paragraph.* INTO paragraph_row
      FROM public.paragraphs paragraph
      JOIN public.transcript_versions transcript
        ON transcript.id = paragraph.transcript_version_id
     WHERE paragraph.take_id = p_take_id
       AND paragraph.project_id = p_project_id
       AND paragraph.owner_principal_id = take_row.owner_principal_id
       AND paragraph.source_ideal_part_id = p_source_ideal_part_id
     ORDER BY transcript.version DESC, paragraph.created_at DESC
     LIMIT 1;
    IF paragraph_row.id IS NULL
       OR paragraph_row.paragraph_text IS DISTINCT FROM p_exact_text THEN
        RAISE EXCEPTION 'paragraph decision exact text is stale';
    END IF;

    INSERT INTO public.evidence_spans (
        id, owner_principal_id, project_id, take_id,
        transcript_version_id, slide_id, paragraph_id,
        evidence_kind, task_type, start_char, end_char, exact_text,
        target_locator, technical_metadata, evidence_hash, input_hash
    ) VALUES (
        p_evidence_id, take_row.owner_principal_id, p_project_id, p_take_id,
        paragraph_row.transcript_version_id, paragraph_row.slide_id,
        paragraph_row.id, 'transcript_span', 'paragraph_decision',
        paragraph_row.start_char, paragraph_row.end_char,
        paragraph_row.paragraph_text,
        jsonb_build_object(
            'surface', 'ideal_text_part',
            'source_ideal_part_id', p_source_ideal_part_id
        ), '{}'::jsonb, p_evidence_hash, p_input_hash
    ) ON CONFLICT (evidence_hash) DO NOTHING;
    SELECT evidence.id INTO evidence_id
      FROM public.evidence_spans evidence
     WHERE evidence.evidence_hash = p_evidence_hash
       AND evidence.take_id = p_take_id
       AND evidence.paragraph_id = paragraph_row.id;
    IF evidence_id IS NULL THEN
        RAISE EXCEPTION 'paragraph evidence crosses a Take boundary';
    END IF;

    SELECT * INTO existing FROM public.paragraph_decisions row
     WHERE row.idempotency_key = p_idempotency_key;
    IF existing.id IS NOT NULL THEN
        IF existing.evidence_span_id IS DISTINCT FROM evidence_id
           OR existing.paragraph_id IS DISTINCT FROM paragraph_row.id
           OR existing.rater_id IS DISTINCT FROM p_rater_id
           OR existing.value IS DISTINCT FROM p_value THEN
            RAISE EXCEPTION 'paragraph decision idempotency conflict';
        END IF;
        RETURN jsonb_build_object(
            'paragraph_decision_id', existing.id,
            'paragraph_id', existing.paragraph_id,
            'replayed', true
        );
    END IF;
    SELECT row.* INTO latest FROM public.paragraph_decisions row
     WHERE row.paragraph_id = paragraph_row.id
       AND row.rater_id = p_rater_id
     ORDER BY row.created_at DESC, row.id DESC
     LIMIT 1;
    INSERT INTO public.paragraph_decisions (
        id, evidence_span_id, paragraph_id, value, rater_id,
        taxonomy_version, supersedes_id, idempotency_key
    ) VALUES (
        created_id, evidence_id, paragraph_row.id, p_value, p_rater_id,
        p_taxonomy_version, latest.id, p_idempotency_key
    );
    IF p_value <> 'lock_for_next_take' THEN
        SELECT row.* INTO latest_root FROM public.root_phrases row
         WHERE row.paragraph_id = paragraph_row.id
         ORDER BY row.created_at DESC, row.id DESC
         LIMIT 1;
        IF latest_root.id IS NOT NULL AND latest_root.state = 'active' THEN
            INSERT INTO public.root_phrases (
                id, paragraph_id, paragraph_decision_id, exact_text,
                start_char, end_char, state, supersedes_id, idempotency_key
            ) VALUES (
                gen_random_uuid(), paragraph_row.id, created_id,
                latest_root.exact_text, latest_root.start_char,
                latest_root.end_char, 'removed', latest_root.id,
                'root-auto-remove:' || created_id::text || ':' ||
                    latest_root.id::text
            );
        END IF;
    END IF;
    RETURN jsonb_build_object(
        'paragraph_decision_id', created_id,
        'paragraph_id', paragraph_row.id,
        'supersedes_id', latest.id,
        'replayed', false
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.record_root_phrase_skip_v1(
    p_project_id UUID,
    p_take_id UUID,
    p_rater_id UUID,
    p_source_ideal_part_id UUID,
    p_taxonomy_version TEXT,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    take_row public.v2_sessions%ROWTYPE;
    paragraph_row public.paragraphs%ROWTYPE;
    decision_row public.paragraph_decisions%ROWTYPE;
    existing_revision public.feedback_revisions%ROWTYPE;
    latest_revision public.feedback_revisions%ROWTYPE;
    latest_root public.root_phrases%ROWTYPE;
    revision_id UUID := gen_random_uuid();
    removal_id UUID;
BEGIN
    IF NULLIF(trim(p_idempotency_key), '') IS NULL THEN
        RAISE EXCEPTION 'root phrase skip idempotency key is required';
    END IF;
    SELECT * INTO take_row FROM public.v2_sessions
     WHERE id = p_take_id AND project_id = p_project_id
     FOR SHARE;
    IF take_row.id IS NULL OR take_row.user_id IS DISTINCT FROM p_rater_id THEN
        RAISE EXCEPTION 'root phrase skip ownership rejected';
    END IF;
    SELECT paragraph.* INTO paragraph_row
      FROM public.paragraphs paragraph
      JOIN public.transcript_versions transcript
        ON transcript.id = paragraph.transcript_version_id
     WHERE paragraph.take_id = p_take_id
       AND paragraph.source_ideal_part_id = p_source_ideal_part_id
       AND paragraph.owner_principal_id = take_row.owner_principal_id
     ORDER BY transcript.version DESC, paragraph.created_at DESC
     LIMIT 1;
    SELECT row.* INTO decision_row FROM public.paragraph_decisions row
     WHERE row.paragraph_id = paragraph_row.id
       AND row.rater_id = p_rater_id
     ORDER BY row.created_at DESC, row.id DESC
     LIMIT 1;
    IF paragraph_row.id IS NULL OR decision_row.id IS NULL
       OR decision_row.value <> 'lock_for_next_take' THEN
        RAISE EXCEPTION 'root phrase skip requires a current lock decision';
    END IF;
    SELECT row.* INTO existing_revision FROM public.feedback_revisions row
     WHERE row.idempotency_key = p_idempotency_key;
    IF existing_revision.id IS NOT NULL THEN
        IF existing_revision.evidence_span_id IS DISTINCT FROM
           decision_row.evidence_span_id
           OR existing_revision.rater_id IS DISTINCT FROM p_rater_id
           OR existing_revision.value <> 'root_phrase_skipped' THEN
            RAISE EXCEPTION 'root phrase skip idempotency conflict';
        END IF;
        RETURN jsonb_build_object(
            'feedback_revision_id', existing_revision.id,
            'root_phrase_id', NULL,
            'replayed', true
        );
    END IF;
    SELECT row.* INTO latest_revision FROM public.feedback_revisions row
     WHERE row.evidence_span_id = decision_row.evidence_span_id
       AND row.rater_id = p_rater_id
       AND row.value = 'root_phrase_skipped'
     ORDER BY row.created_at DESC, row.id DESC
     LIMIT 1;
    INSERT INTO public.feedback_revisions (
        id, evidence_span_id, value, rater_role, rater_id,
        taxonomy_version, revision_payload, supersedes_id, idempotency_key
    ) VALUES (
        revision_id, decision_row.evidence_span_id, 'root_phrase_skipped',
        'owner', p_rater_id, p_taxonomy_version,
        jsonb_build_object(
            'paragraph_id', paragraph_row.id,
            'source_ideal_part_id', p_source_ideal_part_id
        ), latest_revision.id, p_idempotency_key
    );
    SELECT row.* INTO latest_root FROM public.root_phrases row
     WHERE row.paragraph_id = paragraph_row.id
     ORDER BY row.created_at DESC, row.id DESC
     LIMIT 1;
    IF latest_root.id IS NOT NULL AND latest_root.state = 'active' THEN
        removal_id := gen_random_uuid();
        INSERT INTO public.root_phrases (
            id, paragraph_id, paragraph_decision_id, exact_text,
            start_char, end_char, state, supersedes_id, idempotency_key
        ) VALUES (
            removal_id, paragraph_row.id, decision_row.id,
            latest_root.exact_text, latest_root.start_char,
            latest_root.end_char, 'removed', latest_root.id,
            'root-skip-remove:' || revision_id::text
        );
    END IF;
    RETURN jsonb_build_object(
        'feedback_revision_id', revision_id,
        'root_phrase_id', removal_id,
        'replayed', false
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.record_root_phrase_v1(
    p_project_id UUID,
    p_take_id UUID,
    p_rater_id UUID,
    p_source_ideal_part_id UUID,
    p_exact_text TEXT,
    p_start_char INTEGER,
    p_end_char INTEGER,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    take_row public.v2_sessions%ROWTYPE;
    paragraph_row public.paragraphs%ROWTYPE;
    decision_row public.paragraph_decisions%ROWTYPE;
    existing public.root_phrases%ROWTYPE;
    latest public.root_phrases%ROWTYPE;
    created_id UUID := gen_random_uuid();
BEGIN
    IF NULLIF(trim(p_exact_text), '') IS NULL
       OR p_start_char < 0 OR p_end_char <= p_start_char
       OR NULLIF(trim(p_idempotency_key), '') IS NULL THEN
        RAISE EXCEPTION 'invalid root phrase payload';
    END IF;
    SELECT * INTO take_row FROM public.v2_sessions
     WHERE id = p_take_id AND project_id = p_project_id
     FOR SHARE;
    IF take_row.id IS NULL OR take_row.user_id IS DISTINCT FROM p_rater_id THEN
        RAISE EXCEPTION 'root phrase ownership rejected';
    END IF;
    SELECT paragraph.* INTO paragraph_row
      FROM public.paragraphs paragraph
      JOIN public.transcript_versions transcript
        ON transcript.id = paragraph.transcript_version_id
     WHERE paragraph.take_id = p_take_id
       AND paragraph.source_ideal_part_id = p_source_ideal_part_id
       AND paragraph.owner_principal_id = take_row.owner_principal_id
     ORDER BY transcript.version DESC, paragraph.created_at DESC
     LIMIT 1;
    IF paragraph_row.id IS NULL
       OR p_end_char > length(paragraph_row.paragraph_text)
       OR substring(
           paragraph_row.paragraph_text
           FROM p_start_char + 1 FOR p_end_char - p_start_char
       ) IS DISTINCT FROM p_exact_text THEN
        RAISE EXCEPTION 'root phrase is not an exact paragraph span';
    END IF;
    SELECT row.* INTO decision_row FROM public.paragraph_decisions row
     WHERE row.paragraph_id = paragraph_row.id
       AND row.rater_id = p_rater_id
     ORDER BY row.created_at DESC, row.id DESC
     LIMIT 1;
    IF decision_row.id IS NULL
       OR decision_row.value <> 'lock_for_next_take' THEN
        RAISE EXCEPTION 'root phrase requires a current lock decision';
    END IF;
    SELECT * INTO existing FROM public.root_phrases row
     WHERE row.idempotency_key = p_idempotency_key;
    IF existing.id IS NOT NULL THEN
        IF existing.paragraph_id IS DISTINCT FROM paragraph_row.id
           OR existing.paragraph_decision_id IS DISTINCT FROM decision_row.id
           OR existing.exact_text IS DISTINCT FROM p_exact_text
           OR existing.start_char IS DISTINCT FROM p_start_char
           OR existing.end_char IS DISTINCT FROM p_end_char THEN
            RAISE EXCEPTION 'root phrase idempotency conflict';
        END IF;
        RETURN jsonb_build_object('root_phrase_id', existing.id,
                                  'replayed', true);
    END IF;
    SELECT row.* INTO latest FROM public.root_phrases row
     WHERE row.paragraph_id = paragraph_row.id
     ORDER BY row.created_at DESC, row.id DESC
     LIMIT 1;
    INSERT INTO public.root_phrases (
        id, paragraph_id, paragraph_decision_id, exact_text,
        start_char, end_char, state, supersedes_id, idempotency_key
    ) VALUES (
        created_id, paragraph_row.id, decision_row.id, p_exact_text,
        p_start_char, p_end_char, 'active', latest.id, p_idempotency_key
    );
    RETURN jsonb_build_object('root_phrase_id', created_id,
                              'supersedes_id', latest.id,
                              'replayed', false);
END;
$$;

CREATE OR REPLACE FUNCTION public.record_confidence_coach_judgment_v1(
    p_evidence_span_id UUID,
    p_coach_id UUID,
    p_value TEXT,
    p_taxonomy_version TEXT,
    p_blind_packet_hash TEXT,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    assignment public.evidence_review_assignments%ROWTYPE;
    existing public.confidence_coach_labels%ROWTYPE;
    latest public.confidence_coach_labels%ROWTYPE;
    created_id UUID := gen_random_uuid();
BEGIN
    IF p_value NOT IN ('yes','in_between','no','not_sure','audio_unclear') THEN
        RAISE EXCEPTION 'invalid coach confidence value';
    END IF;
    IF NULLIF(trim(p_blind_packet_hash), '') IS NULL
       OR NULLIF(trim(p_idempotency_key), '') IS NULL THEN
        RAISE EXCEPTION 'blind packet hash and idempotency key are required';
    END IF;
    SELECT row.* INTO assignment
      FROM public.evidence_review_assignments row
      JOIN public.evidence_spans evidence
        ON evidence.id = row.evidence_span_id
     WHERE row.evidence_span_id = p_evidence_span_id
       AND row.assignee_role = 'coach'
       AND row.assignee_id = p_coach_id
       AND row.blind_packet_hash = p_blind_packet_hash
       AND evidence.task_type = 'confidence_classification';
    IF assignment.id IS NULL THEN
        RAISE EXCEPTION 'coach assignment rejected';
    END IF;

    SELECT * INTO existing FROM public.confidence_coach_labels
     WHERE idempotency_key = p_idempotency_key;
    IF existing.id IS NOT NULL THEN
        IF existing.evidence_span_id IS DISTINCT FROM p_evidence_span_id
           OR existing.rater_id IS DISTINCT FROM p_coach_id
           OR existing.value IS DISTINCT FROM p_value THEN
            RAISE EXCEPTION 'coach judgment idempotency conflict';
        END IF;
        RETURN jsonb_build_object(
            'coach_label_id', existing.id,
            'supersedes_id', existing.supersedes_id,
            'replayed', true
        );
    END IF;

    SELECT label.* INTO latest
      FROM public.confidence_coach_labels label
     WHERE label.evidence_span_id = p_evidence_span_id
       AND label.rater_id = p_coach_id
     ORDER BY label.created_at DESC, label.id DESC
     LIMIT 1;
    IF latest.id IS NOT NULL AND latest.value = p_value THEN
        RETURN jsonb_build_object(
            'coach_label_id', latest.id,
            'supersedes_id', latest.supersedes_id,
            'replayed', true
        );
    END IF;

    INSERT INTO public.confidence_coach_labels (
        id, evidence_span_id, value, rater_id, taxonomy_version,
        blind_packet_hash, supersedes_id, idempotency_key
    ) VALUES (
        created_id, p_evidence_span_id, p_value, p_coach_id,
        p_taxonomy_version, p_blind_packet_hash, latest.id,
        p_idempotency_key
    );
    RETURN jsonb_build_object(
        'coach_label_id', created_id,
        'supersedes_id', latest.id,
        'replayed', false
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.assign_confidence_coach_evidence_v1(
    p_take_id UUID,
    p_evidence_span_id UUID,
    p_coach_id UUID,
    p_blind_packet_hash TEXT,
    p_assignment_reason TEXT,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    existing public.evidence_review_assignments%ROWTYPE;
    by_evidence public.evidence_review_assignments%ROWTYPE;
    created_id UUID := gen_random_uuid();
BEGIN
    IF NULLIF(trim(p_blind_packet_hash), '') IS NULL
       OR NULLIF(trim(p_assignment_reason), '') IS NULL
       OR NULLIF(trim(p_idempotency_key), '') IS NULL
       OR NOT EXISTS (
           SELECT 1 FROM public.evidence_spans evidence
            WHERE evidence.id = p_evidence_span_id
              AND evidence.take_id = p_take_id
              AND evidence.task_type = 'confidence_classification'
              AND evidence.start_ms IS NOT NULL
              AND evidence.end_ms IS NOT NULL
       ) THEN
        RAISE EXCEPTION 'invalid blind coach assignment';
    END IF;
    SELECT row.* INTO existing FROM public.evidence_review_assignments row
     WHERE row.idempotency_key = p_idempotency_key;
    IF existing.id IS NOT NULL THEN
        IF existing.evidence_span_id IS DISTINCT FROM p_evidence_span_id
           OR existing.assignee_role <> 'coach'
           OR existing.assignee_id IS DISTINCT FROM p_coach_id
           OR existing.blind_packet_hash IS DISTINCT FROM p_blind_packet_hash
           THEN
            RAISE EXCEPTION 'blind coach assignment idempotency conflict';
        END IF;
        RETURN jsonb_build_object('assignment_id', existing.id,
                                  'replayed', true);
    END IF;
    SELECT row.* INTO by_evidence
      FROM public.evidence_review_assignments row
     WHERE row.evidence_span_id = p_evidence_span_id
       AND row.assignee_role = 'coach'
       AND row.assignee_id = p_coach_id;
    IF by_evidence.id IS NOT NULL THEN
        IF by_evidence.blind_packet_hash IS DISTINCT FROM
           p_blind_packet_hash THEN
            RAISE EXCEPTION 'blind coach packet changed after assignment';
        END IF;
        RETURN jsonb_build_object('assignment_id', by_evidence.id,
                                  'replayed', true);
    END IF;
    INSERT INTO public.evidence_review_assignments (
        id, evidence_span_id, assignee_role, assignee_id,
        blind_packet_hash, assignment_reason, idempotency_key
    ) VALUES (
        created_id, p_evidence_span_id, 'coach', p_coach_id,
        p_blind_packet_hash, p_assignment_reason, p_idempotency_key
    );
    RETURN jsonb_build_object('assignment_id', created_id,
                              'replayed', false);
END;
$$;

CREATE OR REPLACE FUNCTION public.record_confidence_peer_judgment_v1(
    p_evidence_span_id UUID,
    p_peer_id UUID,
    p_value TEXT,
    p_taxonomy_version TEXT,
    p_blind_packet_hash TEXT,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    assignment public.evidence_review_assignments%ROWTYPE;
    existing public.confidence_peer_labels%ROWTYPE;
    created_id UUID := gen_random_uuid();
BEGIN
    IF p_value NOT IN ('yes','in_between','no','not_sure','audio_unclear') THEN
        RAISE EXCEPTION 'invalid peer confidence value';
    END IF;
    SELECT row.* INTO assignment
      FROM public.evidence_review_assignments row
     WHERE row.evidence_span_id = p_evidence_span_id
       AND row.assignee_role = 'peer'
       AND row.assignee_id = p_peer_id
       AND row.blind_packet_hash = p_blind_packet_hash;
    IF assignment.id IS NULL THEN
        RAISE EXCEPTION 'peer assignment rejected';
    END IF;
    SELECT * INTO existing FROM public.confidence_peer_labels
     WHERE idempotency_key = p_idempotency_key;
    IF existing.id IS NOT NULL THEN
        IF existing.evidence_span_id IS DISTINCT FROM p_evidence_span_id
           OR existing.rater_id IS DISTINCT FROM p_peer_id
           OR existing.value IS DISTINCT FROM p_value THEN
            RAISE EXCEPTION 'peer judgment idempotency conflict';
        END IF;
        RETURN jsonb_build_object('peer_label_id', existing.id,
                                  'replayed', true);
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.confidence_peer_labels label
         WHERE label.evidence_span_id = p_evidence_span_id
           AND label.rater_id = p_peer_id
    ) THEN
        RAISE EXCEPTION 'peer judgment is already final';
    END IF;
    INSERT INTO public.confidence_peer_labels (
        id, evidence_span_id, value, rater_id, taxonomy_version,
        blind_packet_hash, idempotency_key
    ) VALUES (
        created_id, p_evidence_span_id, p_value, p_peer_id,
        p_taxonomy_version, p_blind_packet_hash, p_idempotency_key
    );
    RETURN jsonb_build_object('peer_label_id', created_id,
                              'replayed', false);
END;
$$;

-- The blind read is allowlisted at SQL level. It deliberately cannot return
-- transcript text, predictions, owner reports, peer labels or derived state.
CREATE OR REPLACE FUNCTION public.blind_coach_evidence_v1(
    p_take_id UUID,
    p_coach_id UUID
) RETURNS TABLE (
    evidence_span_id UUID,
    audio_ref TEXT,
    start_ms INTEGER,
    end_ms INTEGER,
    technical_metadata JSONB
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT evidence.id, evidence.audio_ref, evidence.start_ms, evidence.end_ms,
           evidence.technical_metadata
      FROM public.evidence_spans evidence
      JOIN public.v2_sessions take_row ON take_row.id = evidence.take_id
     WHERE evidence.take_id = p_take_id
       AND (
           take_row.coach_review_assigned_to = p_coach_id
           OR EXISTS (
               SELECT 1 FROM public.evidence_review_assignments assignment
                WHERE assignment.evidence_span_id = evidence.id
                  AND assignment.assignee_role = 'coach'
                  AND assignment.assignee_id = p_coach_id
           )
       )
       AND evidence.task_type = 'confidence_classification'
       AND evidence.start_ms IS NOT NULL
       AND evidence.end_ms IS NOT NULL
       AND NOT EXISTS (
           SELECT 1 FROM public.confidence_coach_labels label
            WHERE label.evidence_span_id = evidence.id
              AND label.rater_id = p_coach_id
       )
     ORDER BY evidence.start_ms, evidence.id;
$$;

CREATE OR REPLACE FUNCTION public.blind_peer_evidence_v1(
    p_peer_id UUID
) RETURNS TABLE (
    evidence_span_id UUID,
    audio_ref TEXT,
    start_ms INTEGER,
    end_ms INTEGER,
    technical_metadata JSONB
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT evidence.id, evidence.audio_ref, evidence.start_ms, evidence.end_ms,
           evidence.technical_metadata
      FROM public.evidence_review_assignments assignment
      JOIN public.evidence_spans evidence
        ON evidence.id = assignment.evidence_span_id
     WHERE assignment.assignee_role = 'peer'
       AND assignment.assignee_id = p_peer_id
       AND evidence.task_type = 'confidence_classification'
       AND evidence.start_ms IS NOT NULL
       AND evidence.end_ms IS NOT NULL
       AND NOT EXISTS (
           SELECT 1 FROM public.confidence_peer_labels label
            WHERE label.evidence_span_id = evidence.id
              AND label.rater_id = p_peer_id
       )
     ORDER BY assignment.assigned_at, evidence.id;
$$;

-- Comparison is a distinct post-judgment boundary. The caller receives other
-- provenance only after its own immutable coach label exists.
CREATE OR REPLACE FUNCTION public.coach_evidence_comparison_v1(
    p_evidence_span_id UUID,
    p_coach_id UUID
) RETURNS TABLE (
    coach_label_id UUID,
    coach_value TEXT,
    owner_value TEXT,
    machine_value TEXT,
    peer_values JSONB
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT coach.id,
           coach.value,
           owner_report.value,
           machine.classification,
           COALESCE(peer.values, '[]'::jsonb)
      FROM public.confidence_coach_labels coach
      LEFT JOIN LATERAL (
          SELECT report.value
            FROM public.confidence_self_reports report
           WHERE report.evidence_span_id = coach.evidence_span_id
           ORDER BY report.created_at DESC LIMIT 1
      ) owner_report ON true
      LEFT JOIN LATERAL (
          SELECT prediction.classification
            FROM public.machine_predictions prediction
           WHERE prediction.evidence_span_id = coach.evidence_span_id
             AND prediction.task_type = 'confidence_classification'
           ORDER BY prediction.created_at DESC LIMIT 1
      ) machine ON true
      LEFT JOIN LATERAL (
          SELECT jsonb_agg(jsonb_build_object(
              'value', label.value,
              'taxonomy_version', label.taxonomy_version,
              'created_at', label.created_at
          ) ORDER BY label.created_at) AS values
            FROM public.confidence_peer_labels label
           WHERE label.evidence_span_id = coach.evidence_span_id
      ) peer ON true
     WHERE coach.evidence_span_id = p_evidence_span_id
       AND coach.rater_id = p_coach_id
     ORDER BY coach.created_at DESC
     LIMIT 1;
$$;

CREATE OR REPLACE FUNCTION public.create_dataset_release_v1(
    p_manifest JSONB
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_release_id UUID;
    existing public.dataset_releases%ROWTYPE;
    assignment_row JSONB;
    item_row JSONB;
    exclusion_row JSONB;
    stored_assignment public.dataset_split_assignments%ROWTYPE;
    item_count INTEGER;
BEGIN
    IF jsonb_typeof(p_manifest) <> 'object'
       OR jsonb_typeof(p_manifest -> 'split_assignments') <> 'array'
       OR jsonb_typeof(p_manifest -> 'items') <> 'array'
       OR jsonb_typeof(p_manifest -> 'exclusions') <> 'array' THEN
        RAISE EXCEPTION 'dataset release manifest is incomplete';
    END IF;
    SELECT * INTO existing FROM public.dataset_releases
     WHERE release_identifier = p_manifest ->> 'release_identifier';
    IF existing.id IS NOT NULL THEN
        IF existing.manifest_checksum IS DISTINCT FROM
           p_manifest ->> 'manifest_checksum' THEN
            RAISE EXCEPTION 'dataset release identifier conflict';
        END IF;
        RETURN jsonb_build_object('release_id', existing.id,
                                  'replayed', true);
    END IF;

    v_release_id := (p_manifest ->> 'id')::uuid;
    INSERT INTO public.dataset_releases (
        id, release_identifier, learning_surface, source_cutoff_at,
        inclusion_rules,
        exclusion_rules, taxonomy_versions, feature_versions,
        extraction_code_commit, item_counts, manifest_checksum,
        consent_retention_status, split_strategy_version, created_by
    ) VALUES (
        v_release_id, p_manifest ->> 'release_identifier',
        p_manifest ->> 'learning_surface',
        (p_manifest ->> 'source_cutoff_at')::timestamptz,
        p_manifest -> 'inclusion_rules', p_manifest -> 'exclusion_rules',
        p_manifest -> 'taxonomy_versions', p_manifest -> 'feature_versions',
        p_manifest ->> 'extraction_code_commit',
        p_manifest -> 'item_counts', p_manifest ->> 'manifest_checksum',
        p_manifest -> 'consent_retention_status',
        p_manifest ->> 'split_strategy_version',
        (p_manifest ->> 'created_by')::uuid
    );

    FOR assignment_row IN SELECT value FROM jsonb_array_elements(
        p_manifest -> 'split_assignments'
    ) LOOP
        SELECT row.* INTO stored_assignment
          FROM public.dataset_split_assignments row
         WHERE row.owner_principal_id =
               (assignment_row ->> 'owner_principal_id')::uuid;
        IF stored_assignment.id IS NOT NULL THEN
            IF stored_assignment.split IS DISTINCT FROM
               assignment_row ->> 'split'
               OR stored_assignment.strategy_version IS DISTINCT FROM
               assignment_row ->> 'strategy_version' THEN
                RAISE EXCEPTION 'speaker split conflict';
            END IF;
        ELSE
            INSERT INTO public.dataset_split_assignments (
                id, owner_principal_id, split, strategy_version,
                assignment_hash, first_release_id
            ) VALUES (
                (assignment_row ->> 'id')::uuid,
                (assignment_row ->> 'owner_principal_id')::uuid,
                assignment_row ->> 'split',
                assignment_row ->> 'strategy_version',
                assignment_row ->> 'assignment_hash', v_release_id
            );
        END IF;
    END LOOP;

    FOR item_row IN SELECT value FROM jsonb_array_elements(
        p_manifest -> 'items'
    ) LOOP
        IF item_row ->> 'learning_surface' IS DISTINCT FROM
           p_manifest ->> 'learning_surface' THEN
            RAISE EXCEPTION 'dataset release mixes learning surfaces';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM public.evidence_spans evidence
             WHERE evidence.id = (item_row ->> 'evidence_span_id')::uuid
               AND evidence.owner_principal_id =
                   (item_row ->> 'owner_principal_id')::uuid
        ) THEN
            RAISE EXCEPTION 'dataset item evidence ownership mismatch';
        END IF;
        SELECT row.* INTO stored_assignment
          FROM public.dataset_split_assignments row
         WHERE row.owner_principal_id =
               (item_row ->> 'owner_principal_id')::uuid;
        IF stored_assignment.id IS NULL
           OR stored_assignment.split IS DISTINCT FROM item_row ->> 'split' THEN
            RAISE EXCEPTION 'dataset item split is not speaker-stable';
        END IF;
        INSERT INTO public.dataset_release_items (
            id, release_id, owner_principal_id, split_assignment_id,
            evidence_span_id, learning_surface, item_payload,
            label_provenance, eligibility_decision, item_checksum
        ) VALUES (
            (item_row ->> 'id')::uuid, v_release_id,
            (item_row ->> 'owner_principal_id')::uuid,
            stored_assignment.id,
            (item_row ->> 'evidence_span_id')::uuid,
            item_row ->> 'learning_surface', item_row -> 'item_payload',
            item_row -> 'label_provenance',
            item_row ->> 'eligibility_decision',
            item_row ->> 'item_checksum'
        );
    END LOOP;

    FOR exclusion_row IN SELECT value FROM jsonb_array_elements(
        p_manifest -> 'exclusions'
    ) LOOP
        IF NULLIF(exclusion_row ->> 'evidence_span_id', '') IS NOT NULL
           AND NOT EXISTS (
               SELECT 1 FROM public.evidence_spans evidence
                WHERE evidence.id =
                      (exclusion_row ->> 'evidence_span_id')::uuid
                  AND evidence.owner_principal_id =
                      (exclusion_row ->> 'owner_principal_id')::uuid
           ) THEN
            RAISE EXCEPTION 'dataset exclusion evidence ownership mismatch';
        END IF;
        INSERT INTO public.dataset_exclusions (
            id, release_id, owner_principal_id, evidence_span_id,
            reason_code, reason_detail, consent_retention_status
        ) VALUES (
            (exclusion_row ->> 'id')::uuid, v_release_id,
            (exclusion_row ->> 'owner_principal_id')::uuid,
            NULLIF(exclusion_row ->> 'evidence_span_id', '')::uuid,
            exclusion_row ->> 'reason_code',
            COALESCE(exclusion_row -> 'reason_detail', '{}'::jsonb),
            exclusion_row -> 'consent_retention_status'
        );
    END LOOP;

    SELECT count(*)::integer INTO item_count
      FROM public.dataset_release_items item
     WHERE item.release_id = v_release_id;
    IF item_count <> jsonb_array_length(p_manifest -> 'items')
       OR item_count <> (p_manifest -> 'item_counts' ->> 'total')::integer THEN
        RAISE EXCEPTION 'dataset release item count mismatch';
    END IF;
    RETURN jsonb_build_object('release_id', v_release_id,
                              'item_count', item_count,
                              'replayed', false);
END;
$$;

CREATE OR REPLACE FUNCTION public.record_processing_stage_run_v1(
    p_processing_job_id UUID,
    p_owner_principal_id UUID,
    p_project_id UUID,
    p_take_id UUID,
    p_stage TEXT,
    p_status TEXT,
    p_attempt_count INTEGER,
    p_input_hash TEXT,
    p_output_hash TEXT,
    p_idempotency_key TEXT,
    p_error JSONB
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    existing public.processing_stage_runs%ROWTYPE;
    stage_id UUID;
BEGIN
    IF p_stage NOT IN (
        'upload', 'transcription', 'alignment', 'feature_extraction',
        'candidate_generation', 'manager_selection', 'exposure',
        'human_decisions', 'derived_state'
    ) OR p_status NOT IN (
        'pending', 'running', 'succeeded', 'failed', 'retryable'
    ) OR p_attempt_count < 1 OR length(COALESCE(p_input_hash, '')) = 0
       OR length(COALESCE(p_idempotency_key, '')) = 0 THEN
        RAISE EXCEPTION 'invalid processing stage payload';
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM public.v2_sessions take_row
          JOIN public.projects project
            ON project.id = take_row.project_id
         WHERE take_row.id = p_take_id
           AND take_row.project_id = p_project_id
           AND take_row.owner_principal_id = p_owner_principal_id
           AND project.owner_principal_id = p_owner_principal_id
    ) THEN
        RAISE EXCEPTION 'take ownership mismatch';
    END IF;
    IF p_processing_job_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.processing_jobs job
         WHERE job.id = p_processing_job_id
           AND job.session_id = p_take_id
    ) THEN
        RAISE EXCEPTION 'processing job does not belong to take';
    END IF;

    SELECT * INTO existing
      FROM public.processing_stage_runs row
     WHERE row.idempotency_key = p_idempotency_key
     FOR UPDATE;
    IF existing.id IS NULL THEN
        stage_id := gen_random_uuid();
        INSERT INTO public.processing_stage_runs (
            id, processing_job_id, owner_principal_id, project_id, take_id,
            stage, status, attempt_count, input_hash, output_hash,
            idempotency_key, error, started_at, completed_at
        ) VALUES (
            stage_id, p_processing_job_id, p_owner_principal_id, p_project_id,
            p_take_id, p_stage, p_status, p_attempt_count, p_input_hash,
            p_output_hash, p_idempotency_key, p_error,
            CASE WHEN p_status IN ('running', 'succeeded', 'failed')
                 THEN now() ELSE NULL END,
            CASE WHEN p_status IN ('succeeded', 'failed')
                 THEN now() ELSE NULL END
        );
        RETURN jsonb_build_object('stage_run_id', stage_id,
                                  'status', p_status,
                                  'replayed', false);
    END IF;

    IF existing.owner_principal_id IS DISTINCT FROM p_owner_principal_id
       OR existing.project_id IS DISTINCT FROM p_project_id
       OR existing.take_id IS DISTINCT FROM p_take_id
       OR existing.processing_job_id IS DISTINCT FROM p_processing_job_id
       OR existing.stage IS DISTINCT FROM p_stage
       OR existing.attempt_count IS DISTINCT FROM p_attempt_count
       OR existing.input_hash IS DISTINCT FROM p_input_hash THEN
        RAISE EXCEPTION 'processing stage idempotency conflict';
    END IF;
    IF existing.status IN ('succeeded', 'failed') THEN
        IF existing.status IS DISTINCT FROM p_status
           OR existing.output_hash IS DISTINCT FROM p_output_hash THEN
            RAISE EXCEPTION 'terminal processing stage is immutable';
        END IF;
        RETURN jsonb_build_object('stage_run_id', existing.id,
                                  'status', existing.status,
                                  'replayed', true);
    END IF;
    IF existing.status = 'running' AND p_status = 'pending' THEN
        RAISE EXCEPTION 'processing stage cannot move backward';
    END IF;

    UPDATE public.processing_stage_runs
       SET status = p_status,
           output_hash = CASE
               WHEN p_status IN ('succeeded', 'failed') THEN p_output_hash
               ELSE output_hash END,
           error = CASE WHEN p_status IN ('failed', 'retryable')
                        THEN p_error ELSE error END,
           started_at = CASE WHEN p_status = 'running'
                             THEN COALESCE(started_at, now()) ELSE started_at END,
           completed_at = CASE WHEN p_status IN ('succeeded', 'failed')
                               THEN now() ELSE NULL END
     WHERE id = existing.id;
    RETURN jsonb_build_object('stage_run_id', existing.id,
                              'status', p_status,
                              'replayed', false);
END;
$$;

CREATE OR REPLACE FUNCTION public.feedback_data_parity_v1(
    p_take_id UUID
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    legacy_selected_count INTEGER := 0;
    legacy_candidate_count INTEGER := 0;
    legacy_mappable_decision_count INTEGER := 0;
    canonical_selected_count INTEGER := 0;
    canonical_candidate_count INTEGER := 0;
    canonical_decision_count INTEGER := 0;
    canonical_set_id UUID;
BEGIN
    SELECT COALESCE(jsonb_array_length(row.selected_keys), 0)
      INTO legacy_selected_count
      FROM public.ideal_text_feedback_sets row
     WHERE row.take_session_id = p_take_id
     LIMIT 1;
    SELECT COALESCE(jsonb_array_length(row.candidate_set), 0)
      INTO legacy_candidate_count
      FROM public.take_feedback_exposure row
     WHERE row.take_session_id = p_take_id
     LIMIT 1;
    SELECT count(*)::integer INTO legacy_mappable_decision_count
      FROM public.take_feedback_self_report row
     WHERE row.take_session_id = p_take_id
       AND NOT (
           row.feedback_family = 'rewrite_clarity'
           AND row.response = 'edit_myself'
       );

    SELECT row.id INTO canonical_set_id
      FROM public.candidate_sets row
     WHERE row.take_id = p_take_id
     ORDER BY row.created_at DESC, row.id DESC
     LIMIT 1;
    IF canonical_set_id IS NOT NULL THEN
        SELECT count(*)::integer INTO canonical_candidate_count
          FROM public.feedback_candidates row
         WHERE row.candidate_set_id = canonical_set_id;
        SELECT count(*)::integer INTO canonical_selected_count
          FROM public.feedback_exposures row
         WHERE row.candidate_set_id = canonical_set_id
           AND row.is_selected = true;
    END IF;
    SELECT count(*)::integer INTO canonical_decision_count
      FROM (
          SELECT report.id
            FROM public.confidence_self_reports report
            JOIN public.evidence_spans evidence
              ON evidence.id = report.evidence_span_id
           WHERE evidence.take_id = p_take_id
          UNION ALL
          SELECT praise.id
            FROM public.praise_helpfulness praise
            JOIN public.evidence_spans evidence
              ON evidence.id = praise.evidence_span_id
           WHERE evidence.take_id = p_take_id
          UNION ALL
          SELECT correction.id
            FROM public.correction_decisions correction
            JOIN public.evidence_spans evidence
              ON evidence.id = correction.evidence_span_id
           WHERE evidence.take_id = p_take_id
      ) decisions;

    RETURN jsonb_build_object(
        'take_id', p_take_id,
        'mode', 'observation_only',
        'legacy', jsonb_build_object(
            'candidate_count', legacy_candidate_count,
            'selected_count', legacy_selected_count,
            'mappable_decision_count', legacy_mappable_decision_count
        ),
        'canonical', jsonb_build_object(
            'candidate_set_id', canonical_set_id,
            'candidate_count', canonical_candidate_count,
            'selected_count', canonical_selected_count,
            'decision_count', canonical_decision_count
        ),
        'checks', jsonb_build_object(
            'candidate_count_equal',
                canonical_candidate_count = legacy_candidate_count,
            'exact_three_equal',
                legacy_selected_count = 3 AND canonical_selected_count = 3,
            'decisions_covered',
                canonical_decision_count >= legacy_mappable_decision_count
        )
    );
END;
$$;

REVOKE ALL ON FUNCTION public.reject_canonical_feedback_mutation()
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.record_feedback_exposure_v1(
    UUID, UUID, UUID, JSONB
) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.record_feedback_human_decision_v1(
    UUID, UUID, UUID, TEXT, TEXT, TEXT, TEXT, TEXT
) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.record_paragraph_decision_v1(
    UUID, UUID, UUID, UUID, TEXT, TEXT, TEXT, UUID, TEXT, TEXT, TEXT
) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.record_root_phrase_v1(
    UUID, UUID, UUID, UUID, TEXT, INTEGER, INTEGER, TEXT
) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.record_root_phrase_skip_v1(
    UUID, UUID, UUID, UUID, TEXT, TEXT
) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.record_confidence_coach_judgment_v1(
    UUID, UUID, TEXT, TEXT, TEXT, TEXT
) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.assign_confidence_coach_evidence_v1(
    UUID, UUID, UUID, TEXT, TEXT, TEXT
) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.record_confidence_peer_judgment_v1(
    UUID, UUID, TEXT, TEXT, TEXT, TEXT
) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.blind_coach_evidence_v1(UUID, UUID)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.blind_peer_evidence_v1(UUID)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.coach_evidence_comparison_v1(UUID, UUID)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.create_dataset_release_v1(JSONB)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.record_processing_stage_run_v1(
    UUID, UUID, UUID, UUID, TEXT, TEXT, INTEGER, TEXT, TEXT, TEXT, JSONB
) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.feedback_data_parity_v1(UUID)
    FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.record_feedback_human_decision_v1(
    UUID, UUID, UUID, TEXT, TEXT, TEXT, TEXT, TEXT
) TO service_role;
GRANT EXECUTE ON FUNCTION public.record_paragraph_decision_v1(
    UUID, UUID, UUID, UUID, TEXT, TEXT, TEXT, UUID, TEXT, TEXT, TEXT
) TO service_role;
GRANT EXECUTE ON FUNCTION public.record_root_phrase_v1(
    UUID, UUID, UUID, UUID, TEXT, INTEGER, INTEGER, TEXT
) TO service_role;
GRANT EXECUTE ON FUNCTION public.record_root_phrase_skip_v1(
    UUID, UUID, UUID, UUID, TEXT, TEXT
) TO service_role;
GRANT EXECUTE ON FUNCTION public.record_feedback_exposure_v1(
    UUID, UUID, UUID, JSONB
) TO service_role;
GRANT EXECUTE ON FUNCTION public.record_confidence_coach_judgment_v1(
    UUID, UUID, TEXT, TEXT, TEXT, TEXT
) TO service_role;
GRANT EXECUTE ON FUNCTION public.assign_confidence_coach_evidence_v1(
    UUID, UUID, UUID, TEXT, TEXT, TEXT
) TO service_role;
GRANT EXECUTE ON FUNCTION public.record_confidence_peer_judgment_v1(
    UUID, UUID, TEXT, TEXT, TEXT, TEXT
) TO service_role;
GRANT EXECUTE ON FUNCTION public.blind_coach_evidence_v1(UUID, UUID)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.blind_peer_evidence_v1(UUID)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.coach_evidence_comparison_v1(UUID, UUID)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.create_dataset_release_v1(JSONB)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.record_processing_stage_run_v1(
    UUID, UUID, UUID, UUID, TEXT, TEXT, INTEGER, TEXT, TEXT, TEXT, JSONB
) TO service_role;
GRANT EXECUTE ON FUNCTION public.feedback_data_parity_v1(UUID)
    TO service_role;

GRANT ALL ON TABLE public.transcript_versions TO service_role;
GRANT ALL ON TABLE public.slides TO service_role;
GRANT ALL ON TABLE public.paragraphs TO service_role;
GRANT ALL ON TABLE public.evidence_spans TO service_role;
GRANT ALL ON TABLE public.acoustic_feature_snapshots TO service_role;
GRANT ALL ON TABLE public.candidate_sets TO service_role;
GRANT ALL ON TABLE public.feedback_candidates TO service_role;
GRANT ALL ON TABLE public.feedback_exposures TO service_role;
GRANT ALL ON TABLE public.machine_predictions TO service_role;
GRANT ALL ON TABLE public.generation_runs TO service_role;
GRANT ALL ON TABLE public.evidence_review_assignments TO service_role;
GRANT ALL ON TABLE public.confidence_self_reports TO service_role;
GRANT ALL ON TABLE public.confidence_coach_labels TO service_role;
GRANT ALL ON TABLE public.confidence_peer_labels TO service_role;
GRANT ALL ON TABLE public.praise_helpfulness TO service_role;
GRANT ALL ON TABLE public.correction_decisions TO service_role;
GRANT ALL ON TABLE public.paragraph_decisions TO service_role;
GRANT ALL ON TABLE public.feedback_revisions TO service_role;
GRANT ALL ON TABLE public.voice_album_admissions TO service_role;
GRANT ALL ON TABLE public.accepted_flagships TO service_role;
GRANT ALL ON TABLE public.root_phrases TO service_role;
GRANT ALL ON TABLE public.processing_stage_runs TO service_role;
GRANT ALL ON TABLE public.dataset_releases TO service_role;
GRANT ALL ON TABLE public.dataset_split_assignments TO service_role;
GRANT ALL ON TABLE public.dataset_release_items TO service_role;
GRANT ALL ON TABLE public.dataset_exclusions TO service_role;

COMMENT ON TABLE public.feedback_exposures IS
    'One row per available candidate in a selection event; is_selected and position_shown distinguish availability from actual exposure.';
COMMENT ON TABLE public.dataset_releases IS
    'Immutable approved dataset manifest. Training code reads releases, never evolving production tables.';
COMMENT ON FUNCTION public.blind_coach_evidence_v1(UUID, UUID) IS
    'Pre-judgment allowlist: audio evidence and technical metadata only.';

COMMIT;
