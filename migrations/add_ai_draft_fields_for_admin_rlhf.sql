-- =============================================================================
-- Admin RLHF draft provenance fields
-- =============================================================================
-- Adds optional AI draft columns so admin edits can be exported as pairs:
-- - v2_sessions.ai_draft_grade / ai_draft_comment
-- - admin_student_send_drafts.ai_suggested_task_text / ai_draft_message / ai_draft_video_script
-- Idempotent and safe to run multiple times.
-- =============================================================================

BEGIN;

ALTER TABLE IF EXISTS public.v2_sessions
  ADD COLUMN IF NOT EXISTS ai_draft_grade INTEGER;

ALTER TABLE IF EXISTS public.v2_sessions
  ADD COLUMN IF NOT EXISTS ai_draft_comment TEXT;

ALTER TABLE IF EXISTS public.admin_student_send_drafts
  ADD COLUMN IF NOT EXISTS ai_suggested_task_text TEXT;

ALTER TABLE IF EXISTS public.admin_student_send_drafts
  ADD COLUMN IF NOT EXISTS ai_draft_message TEXT;

ALTER TABLE IF EXISTS public.admin_student_send_drafts
  ADD COLUMN IF NOT EXISTS ai_draft_video_script TEXT;

COMMENT ON COLUMN public.v2_sessions.ai_draft_grade IS
  'AI-suggested admin grade (1-10) for RLHF comparison against report_grade.';

COMMENT ON COLUMN public.v2_sessions.ai_draft_comment IS
  'AI-suggested admin report comment for RLHF comparison against report_comment.';

COMMENT ON COLUMN public.admin_student_send_drafts.ai_suggested_task_text IS
  'Original AI task suggestion saved before coach edits/swaps.';

COMMENT ON COLUMN public.admin_student_send_drafts.ai_draft_message IS
  'Original AI draft homework/email message for coach review.';

COMMENT ON COLUMN public.admin_student_send_drafts.ai_draft_video_script IS
  'Original AI draft video script for coach review.';

NOTIFY pgrst, 'reload schema';

COMMIT;
