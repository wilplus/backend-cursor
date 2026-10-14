-- a_coach_hears_when_nothing_fits.sql gave the backend's service_role only
-- SELECT and DELETE on exercise_coach_requests. 0471 gave back the answer
-- video (Railway log, 2026-10-14: "permission denied for table
-- exercise_coach_requests"). Two more writes are direct UPDATEs of that
-- table from services/db.py and are refused the same way, logged and lost:
--
--   * the model's first draft for the coach's answer (0402, 0459,
--     set_exercise_coach_request_draft), so no draft/final pair is formed;
--   * the speaker's side of the request once they judged (0408,
--     set_exercise_coach_request_answer_kind).
--
-- Give the backend exactly those columns, nothing else. What was requested
-- stays unwritable, and the resolution, the share and the answer's words
-- stay with the SECURITY DEFINER functions (the 0446 guard is unchanged).
--
-- Additive and safe to re-run. No env var.
GRANT UPDATE (
    draft_surface, draft_text, draft_model_version, draft_prompt, drafted_at,
    answer_kind, answered_at
) ON public.exercise_coach_requests TO service_role;
