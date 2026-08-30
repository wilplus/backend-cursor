\set ON_ERROR_STOP on
-- Disposable-only narrow copies of pre-0314 dependencies. Not a migration.
-- 0313 prerequisites cover ownership/policy/review/object tables. These add
-- the actual column names/types used from 0303/0309/MLC-2 judgments.
\ir mlc3_exercise_foundation_prerequisites.sql
CREATE TABLE public.ml_model_runs (
    id UUID PRIMARY KEY, learning_surface_id TEXT NOT NULL,
    status TEXT NOT NULL, completed_at TIMESTAMPTZ NOT NULL,
    code_version TEXT NOT NULL
);
CREATE TABLE public.ml_classification_runs (
    model_run_id UUID PRIMARY KEY REFERENCES public.ml_model_runs(id),
    detector_version TEXT NOT NULL, feature_schema_version TEXT NOT NULL,
    feature_extractor_version TEXT NOT NULL
);
CREATE TABLE public.ml_machine_predictions (
    id UUID PRIMARY KEY,
    classification_run_id UUID NOT NULL REFERENCES public.ml_classification_runs(model_run_id),
    evidence_span_id UUID NOT NULL REFERENCES public.ml_evidence_spans(id),
    output_schema_version TEXT NOT NULL, raw_output JSONB NOT NULL
);
ALTER TABLE public.ml_judgments ADD COLUMN actor_principal_id UUID REFERENCES public.owner_principals(id);
ALTER TABLE public.ml_judgments ADD COLUMN decision TEXT;
CREATE TABLE public.take_feedback_policy_v3_shadow_frames (
    take_session_id UUID NOT NULL REFERENCES public.v2_sessions(id),
    recording_id UUID NOT NULL, policy_version TEXT NOT NULL,
    acquisition_principal_id UUID NOT NULL REFERENCES public.owner_principals(id),
    frame JSONB NOT NULL, frame_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (take_session_id,policy_version)
);
