-- 0460 · A CEO task may be in progress (founder 2026-10-09: "a new lane in
-- progress" on the CEO Tasks screen).
--
-- WHY. The CEO Tasks screen shows three lanes, Active, Done and Archive,
-- read from `ceo_tasks.status` (0286). The founder asked for a fourth,
-- In progress, between Active and Done. This is the founder's own admin
-- task board: no speaker data, no learning door, nothing a speaker sees.
--
-- WHAT.
--   1. The status CHECK on `ceo_tasks` widens from
--      ('active', 'done', 'archived') to also hold 'in_progress'. No row
--      changes: every existing task keeps its status.
--   2. `ceo_complete_task` (0286), the one writer of 'done', completes a
--      task that is active OR in progress. Same body as 0286 otherwise; its
--      grants are restated at the end (service_role only, as in 0286).
--
-- SAFE TWICE. The CHECK is dropped and re-added under the same name, and
-- the function is replaced, so applying this file again changes nothing.

ALTER TABLE public.ceo_tasks
    DROP CONSTRAINT IF EXISTS ceo_tasks_status_check;
ALTER TABLE public.ceo_tasks
    ADD CONSTRAINT ceo_tasks_status_check
    CHECK (status IN ('active', 'in_progress', 'done', 'archived'));

CREATE OR REPLACE FUNCTION public.ceo_complete_task(
    p_task_id UUID,
    p_admin_user_id UUID
) RETURNS TABLE (
    out_task_id UUID,
    out_project_key TEXT,
    out_feature_id UUID
)
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
    v_task_id UUID;
    v_project_key TEXT;
    v_feature_id UUID;
    v_title TEXT;
BEGIN
    UPDATE public.ceo_tasks
       SET status = 'done',
           done_at = now(),
           archived_at = NULL,
           updated_at = now()
     WHERE id = p_task_id
       AND status IN ('active', 'in_progress')
    RETURNING id, project_key, feature_id, title
         INTO v_task_id, v_project_key, v_feature_id, v_title;

    IF v_task_id IS NULL THEN
        RETURN;
    END IF;

    INSERT INTO public.ceo_timeline_events (
        project_key, feature_id, event_type, entity_type, entity_id,
        summary, created_by
    ) VALUES (
        v_project_key, v_feature_id, 'task_completed', 'task', v_task_id,
        v_title, p_admin_user_id
    );

    INSERT INTO public.ceo_reevaluation_requests (
        project_key, feature_id, trigger_type, trigger_id, created_by
    ) VALUES (
        v_project_key, v_feature_id, 'task_completed', v_task_id,
        p_admin_user_id
    ) ON CONFLICT (trigger_type, trigger_id) DO NOTHING;

    RETURN QUERY SELECT v_task_id, v_project_key, v_feature_id;
END;
$$;

-- Restated so the grants never depend on CREATE OR REPLACE keeping them.
REVOKE ALL ON FUNCTION public.ceo_complete_task(UUID, UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ceo_complete_task(UUID, UUID)
    TO service_role;
