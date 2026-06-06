-- willab coach video (B.3): a per-session coach-recorded feedback video.
--
-- POST /v2/admin/sessions/<id>/video stores the file via coach_video_storage
-- (same bucket/transport as the funnel afterwards-video + feedback videos —
-- no new infra) and persists the resulting public URL here. The publish
-- contract folds coach_video_ref into insights_payload so it ships to the user
-- alongside the insights. Re-upload overwrites (deterministic storage key).
ALTER TABLE v2_sessions ADD COLUMN IF NOT EXISTS coach_video_ref text;
