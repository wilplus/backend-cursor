-- a_coach_hears_when_nothing_fits.sql gave the backend's service_role only
-- SELECT and DELETE on exercise_coach_requests. Three later writes are direct
-- UPDATEs of that table from services/db.py, and each was refused with
-- "permission denied":
--
--   * the video a coach adds to an answer not yet given (0403,
--     set_exercise_coach_request_video): the file was stored, the coach saw
--     "Could not keep the video.";
--   * the model's first draft for the coach's answer (0402, 0459,
--     set_exercise_coach_request_draft): logged and lost, so no draft/final
--     pair could be formed;
--   * the speaker's side of the request once they judged (0408,
--     set_exercise_coach_request_answer_kind): logged and lost.
--
-- Give the backend exactly those columns, nothing else. What was requested
-- stays unwritable, and the resolution, the share and the answer's words
-- stay with the SECURITY DEFINER functions. The guard trigger
-- (guard_exercise_coach_request_update_v2, 0446) still refuses a direct
-- change of the video once the answer is given; that change goes through
-- resolve_exercise_coach_request_v3 as before.
--
-- Additive and safe to re-run. No env var.
GRANT UPDATE (
    answer_video_ref,
    draft_surface, draft_text, draft_model_version, draft_prompt, drafted_at,
    answer_kind, answered_at
) ON public.exercise_coach_requests TO service_role;
