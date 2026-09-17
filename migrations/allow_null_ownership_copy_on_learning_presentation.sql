-- 0337 — a NULL ownership COPY must not veto a proven owner.
--
-- PRODUCTION, 2026-09-17. The founder turned the v3 feedback policy on and
-- got no feedback at all. The backend log, on every read of the deck:
--
--   WARNING services.db: learning presentation write failed
--   take=d27c46b0-... surface=ideal_text_generation: {'code': 'P0001',
--   'message': 'learning presentation ownership rejected'}
--
-- repeated for `confidence_classification` too, several times a second.
--
-- WHY IT SUDDENLY MATTERED. This rejection has been in the log for weeks and
-- was harmless: the v2 serving path records the exposure receipt
-- best-effort, logs the failure and serves the feedback anyway. The v3
-- service path is FAIL-CLOSED by design — it refuses to serve a candidate
-- whose receipt did not persist — so the same warning became a total outage
-- of the feedback surface the moment v3 was switched on. The switch did not
-- break anything; it stopped tolerating something that was already broken.
--
-- WHAT IS ACTUALLY WRONG. The guard proves ownership THREE times:
--
--   public.projects.owner_principal_id       — canonical, per project
--   public.takes.owner_principal_id          — canonical, per take
--   public.v2_sessions.owner_principal_id    — a denormalised COPY
--
-- The third is nullable and is null on the overwhelming majority of rows
-- (348 of 367 when this was last counted). `NULL = p_owner_principal_id` is
-- NULL, not TRUE, so the whole EXISTS fails and a take whose project AND
-- canonical take row both name the caller as owner is refused as not theirs.
--
-- THE FIX IS THE SMALLEST ONE THAT IS STILL TRUE. A NULL copy means "not
-- recorded", never "not yours", so it stops being a veto. Every other
-- condition is untouched:
--
--   · `projects.owner_principal_id = p_owner_principal_id` — unchanged;
--   · `takes.owner_principal_id = p_owner_principal_id` — unchanged;
--   · a copy that is PRESENT and DISAGREES is still refused, which is the
--     only case where the copy carries information the canonical tables do
--     not already carry.
--
-- So the authorization boundary is exactly where it was: two canonical
-- tables must independently name the caller as the owner of this take and
-- this project. What is gone is a nullable cache being able to overrule
-- them both by being empty.
--
-- Backfilling the copy instead was the alternative and is worse: it writes
-- to 348 historical rows to satisfy a check that already has two better
-- sources, and it would have to be re-run for every row written before the
-- writer that populates it. Fixing the check fixes every row at once,
-- including the ones nobody has thought about yet.
--
-- Idempotent: CREATE OR REPLACE FUNCTION, and the body is otherwise
-- byte-identical to the one 0301 installed.

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
           -- 0337: a NULL denormalised copy is "not recorded", never "not
           -- yours". Ownership is still proven twice above, on the canonical
           -- tables. A copy that disagrees is still refused.
           AND (take_row.owner_principal_id IS NULL
                OR take_row.owner_principal_id = p_owner_principal_id)
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

-- THE EXECUTE GRANT, RESTATED (test_migration_security_rules enforces this,
-- and it is right to). `CREATE OR REPLACE FUNCTION` preserves the privileges
-- an existing function already has, so on THIS database the lines below are a
-- no-op. They are not redundant: a database built by replaying migrations in
-- order would otherwise reach the replacement above with no revoke of its own,
-- and a SECURITY DEFINER function that anon or authenticated may execute is a
-- browser-reachable path into the owner's data. Every migration that creates
-- or replaces a function states its own grants, so no function's exposure
-- depends on a different file having run first.
REVOKE ALL ON FUNCTION public.create_learning_surface_presentation_v1(
    UUID, UUID, UUID, UUID, UUID, UUID, TEXT, TEXT, UUID,
    JSONB, JSONB, JSONB, JSONB, TEXT, TEXT, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.create_learning_surface_presentation_v1(
    UUID, UUID, UUID, UUID, UUID, UUID, TEXT, TEXT, UUID,
    JSONB, JSONB, JSONB, JSONB, TEXT, TEXT, TEXT
) TO service_role;
