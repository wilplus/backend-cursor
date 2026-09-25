-- 0368 · A project row is kept as a tombstone.
--
-- FOUNDER 2026-09-25, decisions log N9 ("tombstone it").
--
-- WHAT WAS BROKEN, SHOWN BY RUNNING IT. tests/test_take_purge_postgres.py runs
-- the real orchestrator against an account with one recorded Take. The purge
-- deleted the Take, then failed on the project row:
--   update or delete on table "projects" violates foreign key constraint
--   "processing_recording_attempts_project_id_fkey"
-- Every accepted recording attempt is retained as evidence (registry:
-- recording_boundary) and points at its project ON DELETE RESTRICT, while the
-- registry deleted the project. So no erasure could finish for anyone who had
-- recorded a Take: every such request ended at `review_required`.
--
-- THE DECISION. Keep the row; wipe what the person wrote into it. The registry
-- files `projects` as a `tombstone` under the deletion-evidence rule, and the
-- orchestrator calls tombstone_phase1_purge_projects_v1 to blank it:
--   display_name -> '' , setup -> {} , presentation_ref -> NULL,
--   tombstoned_at -> now()
-- id, owner_principal_id and the dates stay, which is all the retained
-- evidence needs to point at.
--
-- SCOPE OF THE WIPE. Only projects in THIS request's frozen subject graph:
-- owned by one of its principal_ids, or listed in its project_ids and owned by
-- the requesting principal. The request must be `in_progress` (frozen, not
-- finished). Nothing else can be wiped through it.
--
-- ADDITIVE AND IDEMPOTENT. One nullable column (ADD COLUMN IF NOT EXISTS) and
-- one CREATE OR REPLACE FUNCTION. No existing row changes on boot; no
-- environment variable is read.

ALTER TABLE public.projects
    ADD COLUMN IF NOT EXISTS tombstoned_at TIMESTAMPTZ NULL;

CREATE OR REPLACE FUNCTION public.tombstone_phase1_purge_projects_v1(
    p_purge_request_id UUID
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    req public.data_purge_requests;
    manifest public.data_purge_inventory_manifests;
    principal_values TEXT[];
    project_values TEXT[];
    wiped INTEGER;
    not_blank INTEGER;
BEGIN
    SELECT * INTO req FROM public.data_purge_requests
     WHERE id = p_purge_request_id FOR UPDATE;
    IF req.id IS NULL THEN RAISE EXCEPTION 'PURGE_REQUEST_NOT_FOUND'; END IF;
    IF req.state <> 'in_progress' THEN
        RAISE EXCEPTION 'PURGE_TOMBSTONE_REQUEST_NOT_IN_PROGRESS';
    END IF;
    SELECT * INTO manifest FROM public.data_purge_inventory_manifests
     WHERE purge_request_id = req.id;
    IF manifest.id IS NULL THEN RAISE EXCEPTION 'PURGE_INVENTORY_NOT_SEALED'; END IF;

    SELECT ARRAY(SELECT jsonb_array_elements_text(
                   COALESCE(manifest.subject_graph->'principal_ids', '[]'::jsonb)))
      INTO principal_values;
    SELECT ARRAY(SELECT jsonb_array_elements_text(
                   COALESCE(manifest.subject_graph->'project_ids', '[]'::jsonb)))
      INTO project_values;

    UPDATE public.projects project
       SET display_name = '',
           setup = '{}'::jsonb,
           presentation_ref = NULL,
           tombstoned_at = COALESCE(project.tombstoned_at, now()),
           updated_at = now()
     WHERE project.owner_principal_id::text = ANY(principal_values)
        OR (project.id::text = ANY(project_values)
            AND project.owner_principal_id = req.acquisition_principal_id);
    GET DIAGNOSTICS wiped = ROW_COUNT;

    SELECT count(*) INTO not_blank
      FROM public.projects project
     WHERE (project.owner_principal_id::text = ANY(principal_values)
            OR (project.id::text = ANY(project_values)
                AND project.owner_principal_id = req.acquisition_principal_id))
       AND (project.display_name <> '' OR project.setup <> '{}'::jsonb
            OR project.presentation_ref IS NOT NULL
            OR project.tombstoned_at IS NULL);

    RETURN jsonb_build_object('tombstoned', wiped, 'not_blank', not_blank);
END;
$$;
REVOKE ALL ON FUNCTION public.tombstone_phase1_purge_projects_v1(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.tombstone_phase1_purge_projects_v1(UUID)
    TO service_role;
