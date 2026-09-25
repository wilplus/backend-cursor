-- 0364 · A project deletion can be requested.
--
-- FOUNDER 2026-09-25, decisions log N8 and spec
-- docs/SPEC-training-corpus-and-project-purge.md §6.4 / §7 (P1).
--
-- WHAT A USER NOW HAS. The picker's ⋯ → Delete becomes a REQUEST, not a
-- delete. An operator confirms it within 7 days (legal ceiling: one month,
-- Art 12(3)); until then the project is locked and the user may cancel.
-- Nothing is deleted by anything in this file.
--
-- WHY A TABLE OF ITS OWN, NOT A ROW IN data_purge_requests. A
-- data_purge_requests row is executed by the Phase-1 purge, which today
-- resolves a WHOLE principal. A project request stored there could be run by
-- the operator script as an account-wide purge. Kept here, a project request
-- cannot reach the purge at all. P1-B links a confirmed request to a
-- project-scoped purge through purge_request_id, once the purge can scope to
-- one project.
--
-- STATES.
--   pending    the user asked; the project is locked; the user may cancel
--   cancelled  the user cancelled before an operator confirmed; terminal
--   confirmed  an operator confirmed (P1-B); the purge runs
--   done       the purge finished (P1-B); terminal
-- A request row is never deleted or reused. At most one pending or confirmed
-- request exists per project (partial unique index).
--
-- project_id carries NO foreign key on purpose: the project row is exactly
-- what a confirmed request deletes, and a RESTRICT key here would block it.
-- Ownership is proved at request time against projects.owner_principal_id.
--
-- ADDITIVE AND IDEMPOTENT. CREATE ... IF NOT EXISTS and CREATE OR REPLACE
-- FUNCTION only; no existing table or row changes. No environment variable is
-- read. The application treats a missing table or function as "no request",
-- so an unmigrated database keeps today's behaviour.

CREATE TABLE IF NOT EXISTS public.project_deletion_requests (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id  UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    project_id                UUID NOT NULL,
    state                     TEXT NOT NULL DEFAULT 'pending' CHECK (state IN (
        'pending', 'cancelled', 'confirmed', 'done'
    )),
    requested_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    due_at                    TIMESTAMPTZ NOT NULL,
    cancelled_at              TIMESTAMPTZ NULL,
    confirmed_at              TIMESTAMPTZ NULL,
    confirmed_by              UUID NULL,
    completed_at              TIMESTAMPTZ NULL,
    purge_request_id          UUID NULL
        REFERENCES public.data_purge_requests(id) ON DELETE RESTRICT,
    idempotency_key           TEXT NOT NULL,
    UNIQUE (acquisition_principal_id, idempotency_key),
    CONSTRAINT project_deletion_due_check CHECK (due_at > requested_at),
    CONSTRAINT project_deletion_state_fields_check CHECK (
        (state <> 'cancelled' OR cancelled_at IS NOT NULL)
        AND (state NOT IN ('confirmed', 'done') OR confirmed_at IS NOT NULL)
        AND (state <> 'done' OR completed_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS project_deletion_requests_one_open_idx
    ON public.project_deletion_requests (project_id)
    WHERE state IN ('pending', 'confirmed');
CREATE INDEX IF NOT EXISTS project_deletion_requests_queue_idx
    ON public.project_deletion_requests (state, due_at);
CREATE INDEX IF NOT EXISTS project_deletion_requests_owner_idx
    ON public.project_deletion_requests (acquisition_principal_id);

ALTER TABLE public.project_deletion_requests ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.project_deletion_requests
    FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.project_deletion_requests TO service_role;

-- Request. Idempotent on (principal, idempotency_key); a second open request
-- for the same project returns the open one rather than raising, so a double
-- tap is one request.
CREATE OR REPLACE FUNCTION public.request_project_deletion_v1(
    p_acquisition_principal_id UUID,
    p_project_id UUID,
    p_idempotency_key TEXT
) RETURNS public.project_deletion_requests
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    request public.project_deletion_requests;
BEGIN
    IF COALESCE(btrim(p_idempotency_key), '') = '' THEN
        RAISE EXCEPTION 'PROJECT_DELETION_IDEMPOTENCY_KEY_REQUIRED';
    END IF;

    SELECT * INTO request FROM public.project_deletion_requests
     WHERE acquisition_principal_id = p_acquisition_principal_id
       AND idempotency_key = p_idempotency_key;
    IF request.id IS NOT NULL THEN
        IF request.project_id <> p_project_id THEN
            RAISE EXCEPTION 'IDEMPOTENCY_CONFLICT';
        END IF;
        RETURN request;
    END IF;

    PERFORM 1 FROM public.projects
     WHERE id = p_project_id
       AND owner_principal_id = p_acquisition_principal_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'PROJECT_NOT_FOUND';
    END IF;

    SELECT * INTO request FROM public.project_deletion_requests
     WHERE project_id = p_project_id
       AND state IN ('pending', 'confirmed');
    IF request.id IS NOT NULL THEN
        RETURN request;
    END IF;

    INSERT INTO public.project_deletion_requests (
        acquisition_principal_id, project_id, requested_at, due_at,
        idempotency_key
    ) VALUES (
        p_acquisition_principal_id, p_project_id, now(),
        now() + interval '7 days', p_idempotency_key
    )
    RETURNING * INTO request;
    RETURN request;
END;
$$;

-- Cancel. Only the owner, only while pending. Cancelling an already
-- cancelled request is a no-op that returns it; anything confirmed is final.
CREATE OR REPLACE FUNCTION public.cancel_project_deletion_v1(
    p_acquisition_principal_id UUID,
    p_project_id UUID
) RETURNS public.project_deletion_requests
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    request public.project_deletion_requests;
BEGIN
    SELECT * INTO request FROM public.project_deletion_requests
     WHERE project_id = p_project_id
       AND acquisition_principal_id = p_acquisition_principal_id
       AND state IN ('pending', 'confirmed')
     FOR UPDATE;
    IF request.id IS NULL THEN
        RAISE EXCEPTION 'PROJECT_DELETION_NOT_PENDING';
    END IF;
    IF request.state <> 'pending' THEN
        RAISE EXCEPTION 'PROJECT_DELETION_ALREADY_CONFIRMED';
    END IF;
    UPDATE public.project_deletion_requests
       SET state = 'cancelled', cancelled_at = now()
     WHERE id = request.id
    RETURNING * INTO request;
    RETURN request;
END;
$$;

REVOKE ALL ON FUNCTION public.request_project_deletion_v1(UUID, UUID, TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.request_project_deletion_v1(UUID, UUID, TEXT)
    TO service_role;
REVOKE ALL ON FUNCTION public.cancel_project_deletion_v1(UUID, UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.cancel_project_deletion_v1(UUID, UUID)
    TO service_role;
