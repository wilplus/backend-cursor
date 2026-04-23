-- Unified delivery lifecycle for admin_student_send_drafts (Training Studio / copilot send).
-- Idempotent. Run in Supabase SQL Editor.

ALTER TABLE public.admin_student_send_drafts
    ADD COLUMN IF NOT EXISTS delivery_lifecycle TEXT NOT NULL DEFAULT 'idle',
    ADD COLUMN IF NOT EXISTS delivery_failed_step TEXT,
    ADD COLUMN IF NOT EXISTS delivery_email_soft_failed BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS delivery_started_at TIMESTAMPTZ;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'admin_student_send_drafts_delivery_lifecycle_check'
    ) THEN
        ALTER TABLE public.admin_student_send_drafts
            ADD CONSTRAINT admin_student_send_drafts_delivery_lifecycle_check
            CHECK (delivery_lifecycle IN ('idle', 'delivering', 'delivered', 'failed'));
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'admin_student_send_drafts_delivery_failed_step_check'
    ) THEN
        ALTER TABLE public.admin_student_send_drafts
            ADD CONSTRAINT admin_student_send_drafts_delivery_failed_step_check
            CHECK (delivery_failed_step IS NULL OR delivery_failed_step IN ('render', 'email'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_admin_student_send_drafts_delivery_lifecycle
    ON public.admin_student_send_drafts (delivery_lifecycle, updated_at DESC);

-- Backfill from legacy status + pipeline_status (idempotent)
UPDATE public.admin_student_send_drafts
SET
    delivery_lifecycle = CASE
        WHEN lower(coalesce(status, '')) = 'sent' THEN 'delivered'
        WHEN lower(coalesce(pipeline_status, '')) IN ('queued', 'running_tts', 'running_video', 'uploading')
            AND lower(coalesce(status, '')) = 'pending' THEN 'delivering'
        WHEN lower(coalesce(pipeline_status, '')) = 'failed' THEN 'failed'
        ELSE delivery_lifecycle
    END,
    delivery_failed_step = CASE
        WHEN lower(coalesce(pipeline_status, '')) = 'failed' THEN 'render'
        ELSE delivery_failed_step
    END
WHERE lower(coalesce(status, '')) = 'sent'
   OR (
        lower(coalesce(pipeline_status, '')) IN ('queued', 'running_tts', 'running_video', 'uploading')
        AND lower(coalesce(status, '')) = 'pending'
   )
   OR lower(coalesce(pipeline_status, '')) = 'failed';
