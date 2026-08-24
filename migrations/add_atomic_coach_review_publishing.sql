-- Canonical professional-review delivery boundary.
--
-- Machine processing and coach review are intentionally separate state
-- machines.  Publishing is one immutable revision plus one durable outbox
-- event in the same transaction.  A browser retry replays by either the
-- request idempotency key or the canonical payload hash.

ALTER TABLE IF EXISTS public.v2_sessions
    ADD COLUMN IF NOT EXISTS coach_review_status TEXT NOT NULL
        DEFAULT 'not_requested'
        CHECK (coach_review_status IN (
            'not_requested', 'queued', 'in_review', 'published', 'revised',
            'cancelled', 'failed'
        )),
    ADD COLUMN IF NOT EXISTS coach_review_assigned_to UUID NULL
        REFERENCES auth.users(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS public.coach_review_revisions (
    id                    UUID PRIMARY KEY,
    session_id            UUID NOT NULL REFERENCES public.v2_sessions(id)
                            ON DELETE CASCADE,
    owner_user_id         UUID NOT NULL REFERENCES auth.users(id)
                            ON DELETE CASCADE,
    project_id            UUID NOT NULL REFERENCES public.projects(id)
                            ON DELETE CASCADE,
    revision_number       INTEGER NOT NULL CHECK (revision_number > 0),
    supersedes_revision_id UUID NULL REFERENCES public.coach_review_revisions(id)
                            ON DELETE RESTRICT,
    idempotency_key       TEXT NOT NULL,
    payload_hash          TEXT NOT NULL,
    actor_user_id         UUID NOT NULL REFERENCES auth.users(id)
                            ON DELETE RESTRICT,
    actor_is_admin        BOOLEAN NOT NULL DEFAULT false,
    admin_override_reason TEXT NULL,
    feedback_items        JSONB NOT NULL,
    overall_message       TEXT NULL,
    share_video           BOOLEAN NOT NULL DEFAULT false,
    published_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT coach_review_admin_override_audit CHECK (
        NOT actor_is_admin OR admin_override_reason IS NOT NULL
    ),
    UNIQUE (session_id, revision_number),
    UNIQUE (session_id, idempotency_key),
    UNIQUE (session_id, payload_hash)
);

ALTER TABLE IF EXISTS public.v2_sessions
    ADD COLUMN IF NOT EXISTS coach_review_revision_id UUID NULL
        REFERENCES public.coach_review_revisions(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS public.coach_review_delivery_outbox (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    revision_id    UUID NOT NULL REFERENCES public.coach_review_revisions(id)
                     ON DELETE CASCADE,
    session_id     UUID NOT NULL REFERENCES public.v2_sessions(id)
                     ON DELETE CASCADE,
    event_kind     TEXT NOT NULL DEFAULT 'coach_review_delivery',
    payload        JSONB NOT NULL DEFAULT '{}'::jsonb,
    status         TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'running', 'done', 'failed')),
    attempts       INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    available_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_error     TEXT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at   TIMESTAMPTZ NULL,
    UNIQUE (revision_id, event_kind)
);

CREATE INDEX IF NOT EXISTS coach_review_outbox_pending_idx
    ON public.coach_review_delivery_outbox(status, available_at);
CREATE INDEX IF NOT EXISTS coach_review_assignment_idx
    ON public.v2_sessions(coach_review_status, coach_review_assigned_to,
                          review_requested_at);

-- Backfill the new human-review state without changing machine processing.
UPDATE public.v2_sessions
   SET coach_review_status = CASE
       WHEN results_published_at IS NOT NULL THEN 'published'
       WHEN status = 'pending_admin_review' AND review_opened_at IS NOT NULL
            THEN 'in_review'
       WHEN status = 'pending_admin_review' THEN 'queued'
       ELSE 'not_requested'
   END
 WHERE coach_review_status = 'not_requested';

CREATE OR REPLACE FUNCTION public.claim_coach_review_v1(
    p_session_id UUID,
    p_actor_user_id UUID,
    p_actor_is_admin BOOLEAN DEFAULT false
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    s public.v2_sessions;
BEGIN
    SELECT * INTO s FROM public.v2_sessions WHERE id = p_session_id FOR UPDATE;
    IF s.id IS NULL THEN
        RAISE EXCEPTION 'take not found';
    END IF;
    IF s.user_id IS NULL THEN
        RAISE EXCEPTION 'unclaimed guest cannot enter coach review';
    END IF;
    IF s.coach_review_assigned_to IS NULL THEN
        UPDATE public.v2_sessions
           SET coach_review_assigned_to = p_actor_user_id,
               coach_review_status = CASE
                   WHEN coach_review_status = 'queued' THEN 'in_review'
                   ELSE coach_review_status
               END,
               review_opened_at = COALESCE(review_opened_at, now())
         WHERE id = p_session_id;
        RETURN jsonb_build_object('assigned_to', p_actor_user_id,
                                  'claimed', true);
    END IF;
    IF s.coach_review_assigned_to <> p_actor_user_id AND NOT p_actor_is_admin THEN
        RAISE EXCEPTION 'review assigned to another coach';
    END IF;
    RETURN jsonb_build_object('assigned_to', s.coach_review_assigned_to,
                              'claimed', false);
END;
$$;

CREATE OR REPLACE FUNCTION public.publish_coach_review_revision_v1(
    p_revision_id UUID,
    p_session_id UUID,
    p_owner_user_id UUID,
    p_project_id UUID,
    p_actor_user_id UUID,
    p_actor_is_admin BOOLEAN,
    p_admin_override_reason TEXT,
    p_idempotency_key TEXT,
    p_payload_hash TEXT,
    p_feedback_items JSONB,
    p_overall_message TEXT,
    p_share_video BOOLEAN,
    p_delivery_payload JSONB
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    s public.v2_sessions;
    prior public.coach_review_revisions;
    created public.coach_review_revisions;
    next_number INTEGER;
    outbox_id UUID;
    override_used BOOLEAN;
BEGIN
    SELECT * INTO s FROM public.v2_sessions WHERE id = p_session_id FOR UPDATE;
    IF s.id IS NULL THEN RAISE EXCEPTION 'take not found'; END IF;
    IF s.user_id IS NULL THEN RAISE EXCEPTION 'unclaimed guest cannot publish'; END IF;
    IF s.user_id <> p_owner_user_id THEN RAISE EXCEPTION 'owner mismatch'; END IF;
    IF COALESCE(s.project_id, s.arc_id) <> p_project_id THEN
        RAISE EXCEPTION 'project mismatch';
    END IF;
    IF jsonb_typeof(p_feedback_items) <> 'array' THEN
        RAISE EXCEPTION 'feedback_items must be an array';
    END IF;

    SELECT * INTO prior
      FROM public.coach_review_revisions
     WHERE session_id = p_session_id
       AND (idempotency_key = p_idempotency_key OR payload_hash = p_payload_hash)
     ORDER BY published_at DESC LIMIT 1;
    IF prior.id IS NOT NULL THEN
        RETURN jsonb_build_object(
            'revision_id', prior.id,
            'revision_number', prior.revision_number,
            'published_at', prior.published_at,
            'replayed', true
        );
    END IF;

    override_used := s.coach_review_assigned_to IS NOT NULL
                     AND s.coach_review_assigned_to <> p_actor_user_id;
    IF override_used AND NOT p_actor_is_admin THEN
        RAISE EXCEPTION 'review assigned to another coach';
    END IF;
    IF override_used AND NULLIF(trim(p_admin_override_reason), '') IS NULL THEN
        RAISE EXCEPTION 'admin override reason required';
    END IF;

    SELECT COALESCE(MAX(revision_number), 0) + 1 INTO next_number
      FROM public.coach_review_revisions WHERE session_id = p_session_id;

    INSERT INTO public.coach_review_revisions (
        id, session_id, owner_user_id, project_id, revision_number,
        supersedes_revision_id, idempotency_key, payload_hash,
        actor_user_id, actor_is_admin, admin_override_reason,
        feedback_items, overall_message, share_video
    ) VALUES (
        p_revision_id, p_session_id, p_owner_user_id, p_project_id, next_number,
        s.coach_review_revision_id, p_idempotency_key, p_payload_hash,
        p_actor_user_id, override_used,
        CASE WHEN override_used THEN trim(p_admin_override_reason) ELSE NULL END,
        p_feedback_items, NULLIF(trim(p_overall_message), ''), p_share_video
    ) RETURNING * INTO created;

    UPDATE public.v2_sessions
       SET coach_review_revision_id = created.id,
           coach_review_status = CASE WHEN next_number = 1
                                      THEN 'published' ELSE 'revised' END,
           coach_overall_message = created.overall_message,
           results_published_at = created.published_at
     WHERE id = p_session_id;

    INSERT INTO public.coach_review_delivery_outbox(
        revision_id, session_id, payload
    ) VALUES (
        created.id, p_session_id,
        COALESCE(p_delivery_payload, '{}'::jsonb)
        || jsonb_build_object('owner_user_id', p_owner_user_id,
                              'project_id', p_project_id)
    ) RETURNING id INTO outbox_id;

    RETURN jsonb_build_object(
        'revision_id', created.id,
        'revision_number', created.revision_number,
        'published_at', created.published_at,
        'replayed', false,
        'outbox_id', outbox_id
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.refund_coach_review_credit_v1(
    p_user_id TEXT,
    p_session_id TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
    current_balance BIGINT;
BEGIN
    PERFORM 1 FROM public.v2_student_details
     WHERE user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('ok', false, 'reason', 'account_unavailable');
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.token_ledger
         WHERE user_id = p_user_id
           AND action = 'coach_feedback'
           AND ref_id = p_session_id
    ) THEN
        RETURN jsonb_build_object('ok', true, 'reason', 'not_charged');
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.token_ledger
         WHERE user_id = p_user_id
           AND action = 'coach_feedback_refund'
           AND ref_id = p_session_id
    ) THEN
        RETURN jsonb_build_object('ok', true, 'reason', 'already_refunded');
    END IF;

    UPDATE public.v2_student_details
       SET coach_reviews_used = GREATEST(COALESCE(coach_reviews_used, 0) - 1, 0)
     WHERE user_id = p_user_id
     RETURNING COALESCE(token_balance, 0) INTO current_balance;
    INSERT INTO public.token_ledger(
        user_id, delta, balance_after, action, ref_id
    ) VALUES (
        p_user_id, 0, current_balance, 'coach_feedback_refund', p_session_id
    );
    RETURN jsonb_build_object('ok', true, 'reason', 'refunded');
END;
$$;

-- Arc publishing is one transaction too: a later invalid take rolls back
-- every earlier revision and outbox row from the same request.
CREATE OR REPLACE FUNCTION public.publish_coach_review_batch_v1(
    p_reviews JSONB
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    item JSONB;
    published JSONB;
    results JSONB := '[]'::jsonb;
BEGIN
    IF jsonb_typeof(p_reviews) <> 'array'
       OR jsonb_array_length(p_reviews) = 0 THEN
        RAISE EXCEPTION 'at least one review is required';
    END IF;
    FOR item IN SELECT value FROM jsonb_array_elements(p_reviews)
    LOOP
        published := public.publish_coach_review_revision_v1(
            (item->>'revision_id')::uuid,
            (item->>'session_id')::uuid,
            (item->>'owner_user_id')::uuid,
            (item->>'project_id')::uuid,
            (item->>'actor_user_id')::uuid,
            COALESCE((item->>'actor_is_admin')::boolean, false),
            item->>'admin_override_reason',
            item->>'idempotency_key',
            item->>'payload_hash',
            item->'feedback_items',
            item->>'overall_message',
            COALESCE((item->>'share_video')::boolean, false),
            COALESCE(item->'delivery_payload', '{}'::jsonb)
        );
        results := results || jsonb_build_array(published);
    END LOOP;
    RETURN results;
END;
$$;

REVOKE ALL ON FUNCTION public.claim_coach_review_v1(UUID, UUID, BOOLEAN)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_coach_review_v1(UUID, UUID, BOOLEAN)
    TO service_role;
REVOKE ALL ON FUNCTION public.publish_coach_review_revision_v1(
    UUID, UUID, UUID, UUID, UUID, BOOLEAN, TEXT, TEXT, TEXT, JSONB, TEXT,
    BOOLEAN, JSONB
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.publish_coach_review_revision_v1(
    UUID, UUID, UUID, UUID, UUID, BOOLEAN, TEXT, TEXT, TEXT, JSONB, TEXT,
    BOOLEAN, JSONB
) TO service_role;
REVOKE ALL ON FUNCTION public.publish_coach_review_batch_v1(JSONB)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.publish_coach_review_batch_v1(JSONB)
    TO service_role;
REVOKE ALL ON FUNCTION public.refund_coach_review_credit_v1(TEXT, TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.refund_coach_review_credit_v1(TEXT, TEXT)
    TO service_role;

ALTER TABLE public.coach_review_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.coach_review_delivery_outbox ENABLE ROW LEVEL SECURITY;
GRANT ALL ON TABLE public.coach_review_revisions TO service_role;
GRANT ALL ON TABLE public.coach_review_delivery_outbox TO service_role;

COMMENT ON TABLE public.coach_review_revisions IS
    'Immutable complete professional-review snapshots; one revision per publish.';
COMMENT ON TABLE public.coach_review_delivery_outbox IS
    'Retryable post-publish effects. Core review visibility never depends on these jobs.';
