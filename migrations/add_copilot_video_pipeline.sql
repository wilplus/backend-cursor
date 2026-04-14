-- Copilot agentic video pipeline schema (idempotent).
-- Adds async pipeline fields to admin_student_send_drafts, references dataset tables,
-- and private storage bucket for generated coach feedback videos.

ALTER TABLE public.admin_student_send_drafts
    ADD COLUMN IF NOT EXISTS script_mode TEXT,
    ADD COLUMN IF NOT EXISTS script_manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS feedback_video_storage_path TEXT,
    ADD COLUMN IF NOT EXISTS pipeline_status TEXT NOT NULL DEFAULT 'idle',
    ADD COLUMN IF NOT EXISTS pipeline_error TEXT,
    ADD COLUMN IF NOT EXISTS pipeline_job_id UUID,
    ADD COLUMN IF NOT EXISTS pipeline_started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS pipeline_finished_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS training_ingested_at TIMESTAMPTZ;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'admin_student_send_drafts_pipeline_status_check'
    ) THEN
        ALTER TABLE public.admin_student_send_drafts
            ADD CONSTRAINT admin_student_send_drafts_pipeline_status_check
            CHECK (
                pipeline_status IN (
                    'idle',
                    'queued',
                    'running_tts',
                    'running_video',
                    'uploading',
                    'sent',
                    'failed'
                )
            );
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'admin_student_send_drafts_script_mode_check'
    ) THEN
        ALTER TABLE public.admin_student_send_drafts
            ADD CONSTRAINT admin_student_send_drafts_script_mode_check
            CHECK (
                script_mode IS NULL
                OR script_mode IN ('ai_only', 'ai_edited', 'full_video_override')
            );
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_admin_student_send_drafts_pipeline_status
    ON public.admin_student_send_drafts (pipeline_status, updated_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_admin_student_send_drafts_pipeline_job_id
    ON public.admin_student_send_drafts (pipeline_job_id)
    WHERE pipeline_job_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.admin_uploaded_reference_videos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_id UUID REFERENCES public.admin_student_send_drafts(id) ON DELETE SET NULL,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL,
    session_id UUID REFERENCES public.v2_sessions(id) ON DELETE SET NULL,
    storage_path TEXT NOT NULL,
    source_video_url TEXT,
    transcript_text TEXT,
    transcription_status TEXT NOT NULL DEFAULT 'pending',
    transcription_error TEXT,
    title TEXT,
    feature_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    tags TEXT[] NOT NULL DEFAULT '{}'::text[],
    is_universal BOOLEAN NOT NULL DEFAULT false,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_by UUID REFERENCES auth.users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.admin_uploaded_reference_videos
    ADD COLUMN IF NOT EXISTS transcription_status TEXT NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS transcription_error TEXT,
    ADD COLUMN IF NOT EXISTS title TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'admin_uploaded_reference_videos_transcription_status_check'
    ) THEN
        ALTER TABLE public.admin_uploaded_reference_videos
            ADD CONSTRAINT admin_uploaded_reference_videos_transcription_status_check
            CHECK (transcription_status IN ('pending', 'processing', 'done', 'failed'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_admin_uploaded_reference_videos_user
    ON public.admin_uploaded_reference_videos (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_admin_uploaded_reference_videos_active
    ON public.admin_uploaded_reference_videos (is_active, created_at DESC);

CREATE TABLE IF NOT EXISTS public.model_training_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    input_count INTEGER NOT NULL DEFAULT 0,
    output_artifact_ref TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'model_training_runs_status_check'
    ) THEN
        ALTER TABLE public.model_training_runs
            ADD CONSTRAINT model_training_runs_status_check
            CHECK (status IN ('queued', 'running', 'completed', 'failed', 'skipped'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_model_training_runs_type_created
    ON public.model_training_runs (run_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_model_training_runs_status
    ON public.model_training_runs (status, updated_at DESC);

-- Private bucket for generated coach feedback videos.
INSERT INTO storage.buckets (id, name, public)
VALUES ('coach_feedback_videos', 'coach_feedback_videos', false)
ON CONFLICT (id) DO NOTHING;
