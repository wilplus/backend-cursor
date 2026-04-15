-- Progress tracking for async admin reference video uploads (storage + DB + optional Whisper).
-- Backend uses service role; RLS optional per your project policy.

CREATE TABLE IF NOT EXISTS public.copilot_reference_upload_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_by UUID REFERENCES auth.users (id) ON DELETE SET NULL,
    student_user_id UUID NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    stage TEXT NOT NULL DEFAULT 'queued',
    percent INTEGER NOT NULL DEFAULT 0,
    message TEXT,
    reference_video_id UUID REFERENCES public.admin_uploaded_reference_videos (id) ON DELETE SET NULL,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT copilot_reference_upload_jobs_percent_check CHECK (
        percent >= 0
        AND percent <= 100
    )
);

CREATE INDEX IF NOT EXISTS idx_copilot_ref_upload_jobs_created
ON public.copilot_reference_upload_jobs (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_copilot_ref_upload_jobs_student
ON public.copilot_reference_upload_jobs (student_user_id, created_at DESC);
