-- Canonical MVP ownership boundary.
--
-- New application code speaks Project / Take / FeedbackItem. Historical
-- arc/session/snippet names remain only as persistence coordinates until a
-- later mechanical database rename. New guest data is never ownerless.

CREATE TABLE IF NOT EXISTS public.owner_principals (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID UNIQUE NULL REFERENCES auth.users(id)
                      ON DELETE CASCADE,
    guest_secret_hash TEXT UNIQUE NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    claimed_at        TIMESTAMPTZ NULL,
    CONSTRAINT owner_principal_identity_check CHECK (
        (user_id IS NOT NULL AND guest_secret_hash IS NULL)
        OR (user_id IS NULL AND guest_secret_hash IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS public.projects (
    id                 UUID PRIMARY KEY,
    owner_principal_id UUID NOT NULL REFERENCES public.owner_principals(id)
                       ON DELETE CASCADE,
    display_name       TEXT NOT NULL,
    setup              JSONB NOT NULL DEFAULT '{}'::jsonb,
    presentation_ref   TEXT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Duplicate display names are deliberately valid. Identity is owner + UUID.
CREATE INDEX IF NOT EXISTS projects_owner_created_idx
    ON public.projects (owner_principal_id, created_at DESC);

ALTER TABLE IF EXISTS public.v2_sessions
    ADD COLUMN IF NOT EXISTS owner_principal_id UUID NULL
        REFERENCES public.owner_principals(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS project_id UUID NULL
        REFERENCES public.projects(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS coach_overall_message TEXT NULL,
    ADD COLUMN IF NOT EXISTS review_requested_at TIMESTAMPTZ NULL;

-- New rejected-take metrics use verified ownership coordinates. Historical
-- columns remain untouched so an existing observability record is never
-- destroyed by this migration.
ALTER TABLE IF EXISTS public.rejected_takes
    ADD COLUMN IF NOT EXISTS owner_principal_id UUID NULL
        REFERENCES public.owner_principals(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS project_id UUID NULL
        REFERENCES public.projects(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS v2_sessions_owner_principal_idx
    ON public.v2_sessions (owner_principal_id, created_at DESC);
CREATE INDEX IF NOT EXISTS v2_sessions_project_take_idx
    ON public.v2_sessions (project_id, take_index);
CREATE UNIQUE INDEX IF NOT EXISTS v2_sessions_project_take_unique_idx
    ON public.v2_sessions (project_id, take_index)
    WHERE project_id IS NOT NULL AND take_index IS NOT NULL;

-- Retry identity is project-scoped. The old global index made the same opaque
-- key in two unrelated projects collide even though their ownership graphs
-- are independent.
DROP INDEX IF EXISTS public.idx_v2_sessions_upload_key;
CREATE UNIQUE INDEX IF NOT EXISTS v2_sessions_project_upload_unique_idx
    ON public.v2_sessions (project_id, upload_idempotency_key)
    WHERE project_id IS NOT NULL AND upload_idempotency_key IS NOT NULL;

-- The compatibility feedback store receives the same strict ownership
-- coordinates for every newly generated item.
ALTER TABLE IF EXISTS public.moment_suggestions
    ADD COLUMN IF NOT EXISTS owner_principal_id UUID NULL
        REFERENCES public.owner_principals(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS project_id UUID NULL
        REFERENCES public.projects(id) ON DELETE CASCADE;

ALTER TABLE IF EXISTS public.coach_snippet_drafts
    ADD COLUMN IF NOT EXISTS feedback_family TEXT NULL
        CHECK (feedback_family IN (
            'confident_voice', 'great_formulation', 'rewrite_for_clarity'
        )),
    ADD COLUMN IF NOT EXISTS review_state TEXT NULL
        CHECK (review_state IN (
            'reviewed', 'refined', 'material_correction', 'not_confirmed'
        )),
    ADD COLUMN IF NOT EXISTS evidence_locator JSONB NULL;

-- Atomic guest claim. Child entities retain one immutable principal foreign
-- key; changing the principal binding transfers the complete graph in one row
-- lock rather than performing a fallible multi-table fan-out update.
CREATE OR REPLACE FUNCTION public.claim_guest_owner(
    p_owner_principal_id UUID,
    p_guest_secret_hash TEXT,
    p_user_id UUID
) RETURNS public.owner_principals
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    claimed public.owner_principals;
    existing public.owner_principals;
BEGIN
    SELECT * INTO claimed
      FROM public.owner_principals
     WHERE id = p_owner_principal_id
       AND user_id IS NULL
       AND guest_secret_hash = p_guest_secret_hash
     FOR UPDATE;

    IF claimed.id IS NULL THEN
        RAISE EXCEPTION 'guest owner claim rejected';
    END IF;

    SELECT * INTO existing
      FROM public.owner_principals
     WHERE user_id = p_user_id
     FOR UPDATE;

    IF existing.id IS NOT NULL THEN
        UPDATE public.projects
           SET owner_principal_id = existing.id,
               updated_at = now()
         WHERE owner_principal_id = claimed.id;
        UPDATE public.v2_sessions
           SET owner_principal_id = existing.id,
               user_id = p_user_id
         WHERE owner_principal_id = claimed.id;
        UPDATE public.recording_1
           SET user_id = p_user_id
         WHERE session_v2_id IN (
             SELECT id FROM public.v2_sessions
              WHERE owner_principal_id = existing.id
                AND user_id = p_user_id
         );
        UPDATE public.charisma_snippets
           SET user_id = p_user_id
         WHERE session_id IN (
             SELECT id FROM public.v2_sessions
              WHERE owner_principal_id = existing.id
                AND user_id = p_user_id
         );
        UPDATE public.moment_suggestions
           SET owner_principal_id = existing.id
         WHERE owner_principal_id = claimed.id;
        DELETE FROM public.owner_principals WHERE id = claimed.id;
        RETURN existing;
    END IF;

    UPDATE public.owner_principals
       SET user_id = p_user_id,
           guest_secret_hash = NULL,
           claimed_at = now()
     WHERE id = claimed.id
    RETURNING * INTO claimed;
    UPDATE public.v2_sessions
       SET user_id = p_user_id
     WHERE owner_principal_id = claimed.id;
    UPDATE public.recording_1
       SET user_id = p_user_id
     WHERE session_v2_id IN (
         SELECT id FROM public.v2_sessions
          WHERE owner_principal_id = claimed.id
            AND user_id = p_user_id
     );
    UPDATE public.charisma_snippets
       SET user_id = p_user_id
     WHERE session_id IN (
         SELECT id FROM public.v2_sessions
          WHERE owner_principal_id = claimed.id
            AND user_id = p_user_id
     );
    RETURN claimed;
END;
$$;

REVOKE ALL ON FUNCTION public.claim_guest_owner(UUID, TEXT, UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.claim_guest_owner(UUID, TEXT, UUID)
    TO service_role;

-- Allocate the next Take ordinal while holding the Project row lock. This
-- makes two simultaneous uploads deterministic instead of relying on a
-- read-max-then-write race in application code.
CREATE OR REPLACE FUNCTION public.bind_project_take(
    p_take_id UUID,
    p_project_id UUID,
    p_owner_principal_id UUID
) RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    next_index INTEGER;
    bound_id UUID;
BEGIN
    PERFORM 1
      FROM public.projects
     WHERE id = p_project_id
       AND owner_principal_id = p_owner_principal_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'project ownership rejected';
    END IF;

    SELECT COALESCE(MAX(take_index), 0) + 1
      INTO next_index
      FROM public.v2_sessions
     WHERE project_id = p_project_id;

    UPDATE public.v2_sessions
       SET project_id = p_project_id,
           arc_id = p_project_id,
           owner_principal_id = p_owner_principal_id,
           take_index = next_index
     WHERE id = p_take_id
       AND (project_id IS NULL OR project_id = p_project_id)
    RETURNING id INTO bound_id;

    IF bound_id IS NULL THEN
        RAISE EXCEPTION 'take bind rejected';
    END IF;
    RETURN next_index;
END;
$$;

REVOKE ALL ON FUNCTION public.bind_project_take(UUID, UUID, UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.bind_project_take(UUID, UUID, UUID)
    TO service_role;

-- A read/practice recording is evidence attached to an existing spoken Take;
-- it inherits that Take's project coordinate but never reserves an ordinal.
CREATE OR REPLACE FUNCTION public.bind_project_recording_variant(
    p_variant_id UUID,
    p_project_id UUID,
    p_owner_principal_id UUID,
    p_paired_take_id UUID
) RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    paired_index INTEGER;
    bound_id UUID;
BEGIN
    PERFORM 1
      FROM public.projects
     WHERE id = p_project_id
       AND owner_principal_id = p_owner_principal_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'project ownership rejected';
    END IF;

    SELECT take_index INTO paired_index
      FROM public.v2_sessions
     WHERE id = p_paired_take_id
       AND project_id = p_project_id
       AND owner_principal_id = p_owner_principal_id
       AND COALESCE(recording_kind, 'spoken') = 'spoken';
    IF paired_index IS NULL THEN
        RAISE EXCEPTION 'paired take rejected';
    END IF;

    UPDATE public.v2_sessions
       SET project_id = p_project_id,
           arc_id = p_project_id,
           owner_principal_id = p_owner_principal_id,
           take_index = NULL,
           recording_kind = 'read',
           paired_session_id = p_paired_take_id
     WHERE id = p_variant_id
       AND project_id IS NULL
    RETURNING id INTO bound_id;

    IF bound_id IS NULL THEN
        RAISE EXCEPTION 'recording variant bind rejected';
    END IF;
    RETURN paired_index;
END;
$$;

REVOKE ALL ON FUNCTION public.bind_project_recording_variant(
    UUID, UUID, UUID, UUID
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.bind_project_recording_variant(
    UUID, UUID, UUID, UUID
) TO service_role;

ALTER TABLE public.owner_principals ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.projects ENABLE ROW LEVEL SECURITY;
GRANT ALL ON TABLE public.owner_principals TO service_role;
GRANT ALL ON TABLE public.projects TO service_role;

COMMENT ON TABLE public.owner_principals IS
    'Immutable owner identity shared by authenticated and pre-signup projects.';
COMMENT ON TABLE public.projects IS
    'Canonical project identity; display names are intentionally non-unique.';
COMMENT ON COLUMN public.v2_sessions.coach_overall_message IS
    'Optional take-level coach summary. Paragraph feedback is stored only as exact-evidence FeedbackItems.';
COMMENT ON COLUMN public.v2_sessions.review_requested_at IS
    'Canonical time at which this Take entered asynchronous coach review.';
