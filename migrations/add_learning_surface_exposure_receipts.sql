-- 0299 · true visible exposure receipts for seven isolated learning surfaces.
--
-- Candidate selection is not exposure. A presentation freezes what could be
-- rendered; a receipt exists only after the exact authenticated client says
-- that presentation was visibly mounted. There is intentionally no skip,
-- close, timeout, implicit-negative or shadow-acknowledgement write path.

BEGIN;

CREATE TABLE IF NOT EXISTS public.learning_surface_presentations (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_principal_id       UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    project_id               UUID NOT NULL
        REFERENCES public.projects(id) ON DELETE RESTRICT,
    take_id                  UUID NOT NULL
        REFERENCES public.v2_sessions(id) ON DELETE RESTRICT,
    evidence_span_id         UUID NULL
        REFERENCES public.evidence_spans(id) ON DELETE RESTRICT,
    candidate_set_id         UUID NULL
        REFERENCES public.candidate_sets(id) ON DELETE RESTRICT,
    generation_run_id        UUID NULL
        REFERENCES public.generation_runs(id) ON DELETE RESTRICT,
    learning_surface         TEXT NOT NULL CHECK (learning_surface IN (
        'confidence_classification', 'correction_generation',
        'coach_comment_generation', 'praise_generation',
        'praise_selection', 'correction_selection',
        'ideal_text_generation'
    )),
    actor_role               TEXT NOT NULL CHECK (actor_role IN (
        'owner', 'coach', 'peer'
    )),
    actor_id                 UUID NOT NULL,
    complete_candidate_set   JSONB NOT NULL CHECK (
        jsonb_typeof(complete_candidate_set) = 'array'
        AND jsonb_array_length(complete_candidate_set) > 0
    ),
    selected_candidate       JSONB NOT NULL CHECK (
        jsonb_typeof(selected_candidate) = 'object'
    ),
    visible_payload          JSONB NOT NULL CHECK (
        jsonb_typeof(visible_payload) = 'object'
    ),
    versions                 JSONB NOT NULL CHECK (
        jsonb_typeof(versions) = 'object'
    ),
    content_hash             TEXT NOT NULL CHECK (length(content_hash) = 64),
    delivery_mode            TEXT NOT NULL CHECK (delivery_mode IN (
        'production', 'canary', 'shadow'
    )),
    evaluation_only          BOOLEAN NOT NULL,
    acknowledgement_token    UUID NOT NULL DEFAULT gen_random_uuid(),
    idempotency_key          TEXT NOT NULL UNIQUE,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT presentation_mode_check CHECK (
        evaluation_only = (delivery_mode = 'shadow')
    ),
    CONSTRAINT presentation_surface_evidence_check CHECK (
        learning_surface = 'ideal_text_generation'
        OR evidence_span_id IS NOT NULL
    ),
    UNIQUE (id, actor_role, actor_id),
    UNIQUE (id, owner_principal_id, project_id, take_id)
);

CREATE TABLE IF NOT EXISTS public.learning_surface_exposure_receipts (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    presentation_id          UUID NOT NULL,
    owner_principal_id       UUID NOT NULL,
    project_id               UUID NOT NULL,
    take_id                  UUID NOT NULL,
    learning_surface         TEXT NOT NULL CHECK (learning_surface IN (
        'confidence_classification', 'correction_generation',
        'coach_comment_generation', 'praise_generation',
        'praise_selection', 'correction_selection',
        'ideal_text_generation'
    )),
    actor_role               TEXT NOT NULL CHECK (actor_role IN (
        'owner', 'coach', 'peer'
    )),
    actor_id                 UUID NOT NULL,
    render_instance_id       UUID NOT NULL,
    client_rendered_at       TIMESTAMPTZ NULL,
    acknowledged_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    idempotency_key          TEXT NOT NULL UNIQUE,
    CONSTRAINT receipt_presentation_actor_fk FOREIGN KEY (
        presentation_id, actor_role, actor_id
    ) REFERENCES public.learning_surface_presentations(
        id, actor_role, actor_id
    ) ON DELETE RESTRICT,
    CONSTRAINT receipt_presentation_owner_fk FOREIGN KEY (
        presentation_id, owner_principal_id, project_id, take_id
    ) REFERENCES public.learning_surface_presentations(
        id, owner_principal_id, project_id, take_id
    ) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
    UNIQUE (presentation_id, render_instance_id)
);

CREATE INDEX IF NOT EXISTS learning_presentations_surface_time_idx
    ON public.learning_surface_presentations(
        learning_surface, created_at, id
    );
CREATE INDEX IF NOT EXISTS learning_presentations_take_actor_idx
    ON public.learning_surface_presentations(
        take_id, actor_role, actor_id, created_at
    );
CREATE INDEX IF NOT EXISTS learning_receipts_surface_time_idx
    ON public.learning_surface_exposure_receipts(
        learning_surface, acknowledged_at, id
    );

ALTER TABLE public.learning_surface_presentations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.learning_surface_exposure_receipts
    ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.learning_surface_presentations
    FROM anon, authenticated;
REVOKE ALL ON TABLE public.learning_surface_exposure_receipts
    FROM anon, authenticated;
GRANT ALL ON TABLE public.learning_surface_presentations TO service_role;
GRANT ALL ON TABLE public.learning_surface_exposure_receipts TO service_role;

DROP TRIGGER IF EXISTS learning_surface_presentations_append_only
    ON public.learning_surface_presentations;
CREATE TRIGGER learning_surface_presentations_append_only
    BEFORE UPDATE OR DELETE ON public.learning_surface_presentations
    FOR EACH ROW EXECUTE FUNCTION public.reject_canonical_feedback_mutation();
DROP TRIGGER IF EXISTS learning_surface_exposure_receipts_append_only
    ON public.learning_surface_exposure_receipts;
CREATE TRIGGER learning_surface_exposure_receipts_append_only
    BEFORE UPDATE OR DELETE ON public.learning_surface_exposure_receipts
    FOR EACH ROW EXECUTE FUNCTION public.reject_canonical_feedback_mutation();

-- Future guest claims automatically include these tables without rewriting
-- the already-applied 0298 claim RPC. Transaction-local claim settings and
-- the immutable event are re-verified by the append-only trigger itself.
CREATE OR REPLACE FUNCTION public.transfer_learning_surfaces_on_owner_claim()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.owner_principal_id IS DISTINCT FROM NEW.owner_principal_id
       AND current_setting('willab.owner_claim_source', true) =
           OLD.owner_principal_id::text
       AND current_setting('willab.owner_claim_target', true) =
           NEW.owner_principal_id::text THEN
        UPDATE public.learning_surface_presentations
           SET owner_principal_id = NEW.owner_principal_id
         WHERE project_id = NEW.id
           AND owner_principal_id = OLD.owner_principal_id;
        UPDATE public.learning_surface_exposure_receipts
           SET owner_principal_id = NEW.owner_principal_id
         WHERE project_id = NEW.id
           AND owner_principal_id = OLD.owner_principal_id;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS projects_transfer_learning_surfaces_on_claim
    ON public.projects;
CREATE TRIGGER projects_transfer_learning_surfaces_on_claim
    AFTER UPDATE OF owner_principal_id ON public.projects
    FOR EACH ROW EXECUTE FUNCTION
        public.transfer_learning_surfaces_on_owner_claim();

REVOKE ALL ON FUNCTION public.transfer_learning_surfaces_on_owner_claim()
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.transfer_learning_surfaces_on_owner_claim()
    TO service_role;

CREATE OR REPLACE FUNCTION public.create_learning_surface_presentation_v1(
    p_owner_principal_id UUID,
    p_project_id UUID,
    p_take_id UUID,
    p_evidence_span_id UUID,
    p_candidate_set_id UUID,
    p_generation_run_id UUID,
    p_learning_surface TEXT,
    p_actor_role TEXT,
    p_actor_id UUID,
    p_complete_candidate_set JSONB,
    p_selected_candidate JSONB,
    p_visible_payload JSONB,
    p_versions JSONB,
    p_content_hash TEXT,
    p_delivery_mode TEXT,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    existing public.learning_surface_presentations%ROWTYPE;
    created public.learning_surface_presentations%ROWTYPE;
    is_evaluation BOOLEAN := p_delivery_mode = 'shadow';
BEGIN
    IF p_learning_surface NOT IN (
        'confidence_classification', 'correction_generation',
        'coach_comment_generation', 'praise_generation',
        'praise_selection', 'correction_selection',
        'ideal_text_generation'
    ) OR p_actor_role NOT IN ('owner', 'coach', 'peer')
      OR p_delivery_mode NOT IN ('production', 'canary', 'shadow')
      OR jsonb_typeof(p_complete_candidate_set) <> 'array'
      OR jsonb_array_length(p_complete_candidate_set) = 0
      OR jsonb_typeof(p_selected_candidate) <> 'object'
      OR jsonb_typeof(p_visible_payload) <> 'object'
      OR jsonb_typeof(p_versions) <> 'object'
      OR length(COALESCE(p_content_hash, '')) <> 64
      OR NULLIF(trim(p_idempotency_key), '') IS NULL THEN
        RAISE EXCEPTION 'learning presentation payload is incomplete';
    END IF;
    IF p_learning_surface <> 'ideal_text_generation'
       AND p_evidence_span_id IS NULL THEN
        RAISE EXCEPTION 'learning presentation requires exact evidence';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.v2_sessions take_row
        JOIN public.takes canonical_take ON canonical_take.id = take_row.id
          AND canonical_take.project_id = p_project_id
          AND canonical_take.owner_principal_id = p_owner_principal_id
        JOIN public.projects project ON project.id = p_project_id
         WHERE take_row.id = p_take_id
           AND take_row.project_id = p_project_id
           AND take_row.owner_principal_id = p_owner_principal_id
           AND project.owner_principal_id = p_owner_principal_id
    ) THEN
        RAISE EXCEPTION 'learning presentation ownership rejected';
    END IF;
    IF p_evidence_span_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.evidence_spans evidence
         WHERE evidence.id = p_evidence_span_id
           AND evidence.owner_principal_id = p_owner_principal_id
           AND evidence.project_id = p_project_id
           AND evidence.take_id = p_take_id
    ) THEN
        RAISE EXCEPTION 'learning presentation evidence rejected';
    END IF;
    IF p_candidate_set_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.candidate_sets candidate_set
         WHERE candidate_set.id = p_candidate_set_id
           AND candidate_set.owner_principal_id = p_owner_principal_id
           AND candidate_set.project_id = p_project_id
           AND candidate_set.take_id = p_take_id
    ) THEN
        RAISE EXCEPTION 'learning presentation candidate set rejected';
    END IF;
    IF p_generation_run_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.generation_runs generation
         WHERE generation.id = p_generation_run_id
           AND generation.owner_principal_id = p_owner_principal_id
           AND generation.project_id = p_project_id
           AND generation.take_id = p_take_id
    ) THEN
        RAISE EXCEPTION 'learning presentation generation rejected';
    END IF;

    IF p_actor_role = 'owner' THEN
        IF NOT EXISTS (
            SELECT 1 FROM public.owner_principals owner
            JOIN public.v2_sessions take_row ON take_row.id = p_take_id
             WHERE owner.id = p_owner_principal_id
               AND owner.user_id = p_actor_id
               AND take_row.user_id = p_actor_id
        ) THEN
            RAISE EXCEPTION 'learning presentation owner actor rejected';
        END IF;
    ELSE
        IF p_evidence_span_id IS NULL OR NOT EXISTS (
            SELECT 1 FROM public.evidence_review_assignments assignment
             WHERE assignment.evidence_span_id = p_evidence_span_id
               AND assignment.assignee_role = p_actor_role
               AND assignment.assignee_id = p_actor_id
        ) THEN
            RAISE EXCEPTION 'learning presentation reviewer actor rejected';
        END IF;
        IF p_learning_surface = 'coach_comment_generation'
           AND (p_actor_role <> 'coach' OR NOT EXISTS (
               SELECT 1 FROM public.confidence_coach_labels label
                WHERE label.evidence_span_id = p_evidence_span_id
                  AND label.rater_id = p_actor_id
           )) THEN
            RAISE EXCEPTION 'coach draft requires an immutable blind judgment';
        END IF;
        IF p_learning_surface = 'confidence_classification'
           AND (
               p_visible_payload ? 'machine_prediction'
               OR p_visible_payload ? 'user_self_report'
               OR p_visible_payload ? 'coach_judgment'
               OR p_visible_payload ? 'peer_judgment'
               OR p_visible_payload ? 'exact_text'
               OR p_visible_payload ? 'transcript_text'
           ) THEN
            RAISE EXCEPTION 'blind confidence packet leaks prior context';
        END IF;
    END IF;

    SELECT * INTO existing
      FROM public.learning_surface_presentations row
     WHERE row.idempotency_key = p_idempotency_key;
    IF existing.id IS NOT NULL THEN
        IF existing.owner_principal_id IS DISTINCT FROM p_owner_principal_id
           OR existing.project_id IS DISTINCT FROM p_project_id
           OR existing.take_id IS DISTINCT FROM p_take_id
           OR existing.learning_surface IS DISTINCT FROM p_learning_surface
           OR existing.actor_role IS DISTINCT FROM p_actor_role
           OR existing.actor_id IS DISTINCT FROM p_actor_id
           OR existing.content_hash IS DISTINCT FROM p_content_hash
           OR existing.delivery_mode IS DISTINCT FROM p_delivery_mode THEN
            RAISE EXCEPTION 'learning presentation idempotency conflict';
        END IF;
        RETURN jsonb_build_object(
            'presentation_id', existing.id,
            'learning_surface', existing.learning_surface,
            'acknowledgement_token', existing.acknowledgement_token,
            'evaluation_only', existing.evaluation_only,
            'replayed', true
        );
    END IF;

    INSERT INTO public.learning_surface_presentations (
        owner_principal_id, project_id, take_id, evidence_span_id,
        candidate_set_id, generation_run_id, learning_surface,
        actor_role, actor_id, complete_candidate_set, selected_candidate,
        visible_payload, versions, content_hash, delivery_mode,
        evaluation_only, idempotency_key
    ) VALUES (
        p_owner_principal_id, p_project_id, p_take_id, p_evidence_span_id,
        p_candidate_set_id, p_generation_run_id, p_learning_surface,
        p_actor_role, p_actor_id, p_complete_candidate_set,
        p_selected_candidate, p_visible_payload, p_versions,
        p_content_hash, p_delivery_mode, is_evaluation, p_idempotency_key
    ) RETURNING * INTO created;
    RETURN jsonb_build_object(
        'presentation_id', created.id,
        'learning_surface', created.learning_surface,
        'acknowledgement_token', created.acknowledgement_token,
        'evaluation_only', created.evaluation_only,
        'replayed', false
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.ack_learning_surface_exposure_v1(
    p_presentation_id UUID,
    p_acknowledgement_token UUID,
    p_actor_role TEXT,
    p_actor_id UUID,
    p_render_instance_id UUID,
    p_client_rendered_at TIMESTAMPTZ,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    presentation public.learning_surface_presentations%ROWTYPE;
    existing public.learning_surface_exposure_receipts%ROWTYPE;
    receipt public.learning_surface_exposure_receipts%ROWTYPE;
BEGIN
    IF p_actor_role NOT IN ('owner', 'coach', 'peer')
       OR NULLIF(trim(p_idempotency_key), '') IS NULL THEN
        RAISE EXCEPTION 'exposure acknowledgement payload is incomplete';
    END IF;
    SELECT * INTO presentation
      FROM public.learning_surface_presentations row
     WHERE row.id = p_presentation_id
     FOR SHARE;
    IF presentation.id IS NULL
       OR presentation.acknowledgement_token IS DISTINCT FROM
          p_acknowledgement_token
       OR presentation.actor_role IS DISTINCT FROM p_actor_role
       OR presentation.actor_id IS DISTINCT FROM p_actor_id THEN
        RAISE EXCEPTION 'exposure acknowledgement actor rejected';
    END IF;
    IF presentation.evaluation_only
       OR presentation.delivery_mode = 'shadow' THEN
        RAISE EXCEPTION 'shadow presentation cannot be rendered';
    END IF;

    SELECT * INTO existing
      FROM public.learning_surface_exposure_receipts row
     WHERE row.idempotency_key = p_idempotency_key;
    IF existing.id IS NOT NULL THEN
        IF existing.presentation_id IS DISTINCT FROM p_presentation_id
           OR existing.actor_role IS DISTINCT FROM p_actor_role
           OR existing.actor_id IS DISTINCT FROM p_actor_id
           OR existing.render_instance_id IS DISTINCT FROM
              p_render_instance_id THEN
            RAISE EXCEPTION 'exposure acknowledgement idempotency conflict';
        END IF;
        RETURN jsonb_build_object(
            'exposure_receipt_id', existing.id,
            'learning_surface', existing.learning_surface,
            'acknowledged_at', existing.acknowledged_at,
            'replayed', true
        );
    END IF;

    INSERT INTO public.learning_surface_exposure_receipts (
        presentation_id, owner_principal_id, project_id, take_id,
        learning_surface, actor_role, actor_id, render_instance_id,
        client_rendered_at, idempotency_key
    ) VALUES (
        presentation.id, presentation.owner_principal_id,
        presentation.project_id, presentation.take_id,
        presentation.learning_surface, presentation.actor_role,
        presentation.actor_id, p_render_instance_id,
        p_client_rendered_at, p_idempotency_key
    ) RETURNING * INTO receipt;
    RETURN jsonb_build_object(
        'exposure_receipt_id', receipt.id,
        'learning_surface', receipt.learning_surface,
        'acknowledged_at', receipt.acknowledged_at,
        'replayed', false
    );
END;
$$;

REVOKE ALL ON FUNCTION public.create_learning_surface_presentation_v1(
    UUID, UUID, UUID, UUID, UUID, UUID, TEXT, TEXT, UUID,
    JSONB, JSONB, JSONB, JSONB, TEXT, TEXT, TEXT
) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.ack_learning_surface_exposure_v1(
    UUID, UUID, TEXT, UUID, UUID, TIMESTAMPTZ, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.create_learning_surface_presentation_v1(
    UUID, UUID, UUID, UUID, UUID, UUID, TEXT, TEXT, UUID,
    JSONB, JSONB, JSONB, JSONB, TEXT, TEXT, TEXT
) TO service_role;
GRANT EXECUTE ON FUNCTION public.ack_learning_surface_exposure_v1(
    UUID, UUID, TEXT, UUID, UUID, TIMESTAMPTZ, TEXT
) TO service_role;

COMMENT ON TABLE public.feedback_exposures IS
    'Manager selection inventory retained for parity. shown_at is a legacy server-selection timestamp and is not proof that a client rendered the item.';
COMMENT ON TABLE public.learning_surface_presentations IS
    'Immutable, actor-specific packet prepared for one of seven isolated learning surfaces; server preparation alone is not exposure.';
COMMENT ON TABLE public.learning_surface_exposure_receipts IS
    'True visible exposure receipts created only by an authenticated post-render acknowledgement. Absence is unanswered, never negative.';

COMMIT;
