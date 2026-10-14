-- A coach's answer video is saved (founder 2026-10-14, Railway log:
-- "permission denied for table exercise_coach_requests" on
-- POST .../exercise-request/video).
--
-- 0403 added `answer_video_ref` and the server writes it directly while the
-- request is still open (`set_exercise_coach_request_video`), but the table
-- only ever granted SELECT and DELETE to service_role, so every save failed.
-- This grants UPDATE on that one column only. The guard trigger (0446) still
-- refuses a change once the request is resolved, and every other column
-- stays write-only through its functions. Safe to re-run; nothing is dropped.

GRANT UPDATE (answer_video_ref) ON public.exercise_coach_requests TO service_role;
