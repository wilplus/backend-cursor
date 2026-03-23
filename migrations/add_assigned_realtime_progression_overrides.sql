-- Coach-controlled progression targets for the next assignment.
-- These values are stored in admin overrides and applied only when the coach sends homework.

ALTER TABLE v2_student_overrides
  ADD COLUMN IF NOT EXISTS assigned_realtime_level INT NULL,
  ADD COLUMN IF NOT EXISTS assigned_realtime_step INT NULL;

COMMENT ON COLUMN v2_student_overrides.assigned_realtime_level IS 'Coach-assigned unlocked realtime level to apply when the next homework email is sent.';
COMMENT ON COLUMN v2_student_overrides.assigned_realtime_step IS 'Coach-assigned unlocked realtime step to apply when the next homework email is sent.';
