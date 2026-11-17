-- the slow model reads use one trip
--
-- Measured from the app (Server-Timing, bff -> backend):
--
--   GET  /v2/chats/setup/models   ~744 ms, almost all of it database
--                                 round trips one after another (public
--                                 models, the versions that say an exam
--                                 passed, the models this host teaches,
--                                 the recipe, the ring).
--   GET  /v2/models/queue         ~1293 ms the same way: every teacher,
--                                 every counted answer and every exam
--                                 case was read just to draw the queue,
--                                 one model at a time for the exam's
--                                 people.
--   PUT  /v2/chats/setup/live     ~2773 ms, one call ~2360 ms. Saving a
--                                 part updated people_profiles and
--                                 PostgREST sent the whole row back,
--                                 including the profile photo (up to
--                                 5 MB). user_id is already the primary
--                                 key, so an index cannot make that call
--                                 shorter; the application now asks for
--                                 user_id only. This function reads the
--                                 ring and the recipe in the same trip
--                                 as the check that used to be two.
--   GET  /v2/models/coach-tasks   5-10 s, and the page asks four times.
--                                 Each task was built as the full sheet
--                                 (audio and all) just to count it, and
--                                 the walk's review queue filtered
--                                 v2_sessions with no matching index.
--
-- WHAT THIS ADDS.
--
--   Partial indexes for the rows those reads actually filter:
--     v2_sessions pending coach review (the walk's first read);
--     the four blind lines, waiting rows only;
--     a model's open examples and its exam cases.
--   Four read functions, each one trip, calling feature_is_on_v1 for
--   the ring so that rule stays where it is. The application still
--   decides what is offered, what waits and what a teacher is sent.
--   Until a database has run this file, the application reads the
--   tables the way it did, which is why a missing function changes
--   nothing.
--
-- Idempotent + additive, per the standing constraint: safe to re-run.
-- Nothing dropped; no env var. CREATE INDEX, not CONCURRENTLY: the
-- runner applies a file as one transaction, which refuses CONCURRENTLY.

-- The walk's queue: pending Lab Takes, newest request first.
CREATE INDEX IF NOT EXISTS v2_sessions_review_queue_idx
    ON public.v2_sessions (review_requested_at DESC)
    WHERE status = 'pending_admin_review'
      AND source = 'audit_upload'
      AND results_published_at IS NULL;

-- A coach's waiting line, not their history. The (coach, week) indexes
-- still serve the weekly cap; these serve "what is unanswered".
CREATE INDEX IF NOT EXISTS error_presence_audit_pending_idx
    ON public.error_presence_audit (coach_id, created_at)
    WHERE answer IS NULL AND cleared_week IS NULL;

CREATE INDEX IF NOT EXISTS coach_block_pick_pending_idx
    ON public.coach_block_pick (coach_id, created_at)
    WHERE answered_at IS NULL AND cleared_week IS NULL;

CREATE INDEX IF NOT EXISTS v4_moment_pick_sheets_pending_idx
    ON public.v4_moment_pick_sheets (rater_id, created_at)
    WHERE answered_at IS NULL AND cleared_week IS NULL;

CREATE INDEX IF NOT EXISTS v4_surer_sheets_pending_idx
    ON public.v4_surer_sheets (rater_id, created_at)
    WHERE answered_at IS NULL AND cleared_week IS NULL;

-- The queue reads a model's examples by whether they are in the exam.
CREATE INDEX IF NOT EXISTS idx_ai_model_examples_model_open
    ON public.ai_model_examples (model_id)
    WHERE NOT in_exam;

CREATE INDEX IF NOT EXISTS idx_ai_model_examples_model_exam
    ON public.ai_model_examples (model_id)
    WHERE in_exam;

-- GET /v2/chats/setup/models, one trip: the ring, what this host's
-- people send, the public models (the same 200 the list took) with the
-- version rows the exam check reads, and the models this host teaches
-- that are not in those 200. "Models you can use" is still decided in
-- services/chat_recipes.py.
CREATE OR REPLACE FUNCTION public.chat_setup_models_bundle_v1(p_user uuid)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    principal uuid;
    builder boolean := false;
    models_on boolean := false;
    send jsonb;
    public_rows jsonb;
    extra_rows jsonb;
    teaching jsonb;
BEGIN
    IF p_user IS NULL THEN
        RETURN jsonb_build_object('builder', false);
    END IF;
    SELECT id INTO principal
      FROM public.owner_principals
     WHERE user_id = p_user
     LIMIT 1;
    IF principal IS NOT NULL THEN
        builder := public.feature_is_on_v1('chat_builder', principal);
        models_on := public.feature_is_on_v1('ai_models', principal);
    END IF;
    IF NOT builder THEN
        RETURN jsonb_build_object('builder', false);
    END IF;

    SELECT CASE
               WHEN p.chat_recipe->>'v' = '2' THEN p.chat_recipe->'send'
               ELSE NULL
           END
      INTO send
      FROM public.people_profiles p
     WHERE p.user_id = p_user;

    -- MATERIALIZED so the 200 public rows are one set: the extras are
    -- whatever this host teaches that is not in that same set.
    WITH public_models AS MATERIALIZED (
        SELECT m.id, m.owner_id, m.owner_name, m.visibility, m.status,
               m.recipe, m.price_units
          FROM public.ai_models m
         WHERE m.visibility = 'public'
         LIMIT 200
    ),
    taught AS (
        SELECT t.model_id
          FROM public.ai_model_teachers t
         WHERE models_on AND t.user_id = p_user
    )
    SELECT COALESCE((
               SELECT jsonb_agg(jsonb_build_object(
                          'id', pm.id,
                          'owner_id', pm.owner_id,
                          'owner_name', pm.owner_name,
                          'visibility', pm.visibility,
                          'status', pm.status,
                          'recipe', pm.recipe,
                          'price_units', pm.price_units,
                          'versions', COALESCE((
                              SELECT jsonb_agg(jsonb_build_object(
                                         'model_id', v.model_id,
                                         'status', v.status,
                                         'exam', v.exam))
                                FROM public.ai_model_versions v
                               WHERE v.model_id = pm.id), '[]'::jsonb)))
                 FROM public_models pm), '[]'::jsonb),
           CASE WHEN models_on
                THEN COALESCE((SELECT jsonb_agg(td.model_id) FROM taught td),
                               '[]'::jsonb)
                ELSE 'null'::jsonb
           END,
           COALESCE((
               SELECT jsonb_agg(jsonb_build_object(
                          'id', m.id,
                          'owner_id', m.owner_id,
                          'owner_name', m.owner_name,
                          'visibility', m.visibility,
                          'status', m.status,
                          'recipe', m.recipe,
                          'price_units', m.price_units,
                          'versions', COALESCE((
                              SELECT jsonb_agg(jsonb_build_object(
                                         'model_id', v.model_id,
                                         'status', v.status,
                                         'exam', v.exam))
                                FROM public.ai_model_versions v
                               WHERE v.model_id = m.id), '[]'::jsonb)))
                 FROM public.ai_models m
                WHERE m.id IN (SELECT td.model_id FROM taught td)
                  AND m.id NOT IN (SELECT pm.id FROM public_models pm)),
               '[]'::jsonb)
      INTO public_rows, teaching, extra_rows
      FROM (SELECT 1) AS _one;

    RETURN jsonb_build_object(
        'builder', true,
        'models_on', models_on,
        'send', send,
        'public', public_rows,
        'extra', extra_rows,
        'teaching', teaching);
END;
$$;

-- PUT /v2/chats/setup/<part>: the ring and the recipe, one trip.
-- The write stays in the application, and it does not read the photo back.
CREATE OR REPLACE FUNCTION public.chat_setup_recipe_v1(p_user uuid)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    principal uuid;
    builder boolean := false;
    recipe jsonb;
BEGIN
    IF p_user IS NULL THEN
        RETURN jsonb_build_object('builder', false);
    END IF;
    SELECT id INTO principal
      FROM public.owner_principals
     WHERE user_id = p_user
     LIMIT 1;
    IF principal IS NOT NULL THEN
        builder := public.feature_is_on_v1('chat_builder', principal);
    END IF;
    IF NOT builder THEN
        RETURN jsonb_build_object('builder', false);
    END IF;
    SELECT p.chat_recipe INTO recipe
      FROM public.people_profiles p
     WHERE p.user_id = p_user
       AND p.chat_recipe->>'v' = '2';
    RETURN jsonb_build_object('builder', true, 'recipe', recipe);
END;
$$;

-- GET /v2/models/queue, one trip: the ring, the models this person
-- teaches, their examples (open ones on a model still being taught, exam
-- cases on any model they teach), their answers and the invites. Who may
-- see a private example, and which examples are sent, stays in
-- services/model_launchpad_store.py.
CREATE OR REPLACE FUNCTION public.model_queue_bundle_v1(p_user uuid)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    principal uuid;
    enabled boolean := false;
    taught jsonb;
    models jsonb;
    examples jsonb;
    answers jsonb;
    invites jsonb;
BEGIN
    IF p_user IS NULL THEN
        RETURN jsonb_build_object('enabled', false);
    END IF;
    SELECT id INTO principal
      FROM public.owner_principals
     WHERE user_id = p_user
     LIMIT 1;
    IF principal IS NOT NULL THEN
        enabled := public.feature_is_on_v1('ai_models', principal);
    END IF;
    IF NOT enabled THEN
        RETURN jsonb_build_object('enabled', false);
    END IF;

    SELECT COALESCE(jsonb_agg(jsonb_build_object(
               'model_id', t.model_id,
               'role', t.role,
               'paused_at', t.paused_at,
               'company_line', t.company_line)), '[]'::jsonb)
      INTO taught
      FROM public.ai_model_teachers t
     WHERE t.user_id = p_user;

    SELECT COALESCE(jsonb_agg(jsonb_build_object(
               'id', m.id,
               'name', m.name,
               'owner_id', m.owner_id,
               'visibility', m.visibility,
               'status', m.status,
               'setup', m.setup)), '[]'::jsonb)
      INTO models
      FROM public.ai_models m
     WHERE m.id IN (
               SELECT t.model_id
                 FROM public.ai_model_teachers t
                WHERE t.user_id = p_user);

    SELECT COALESCE(jsonb_agg(jsonb_build_object(
               'id', e.id,
               'model_id', e.model_id,
               'source', e.source,
               'private', e.private,
               'kind', e.kind,
               'content', e.content,
               'sureness', e.sureness,
               'speaker_id', e.speaker_id,
               'added_by', e.added_by,
               'snippet_id', e.snippet_id,
               'in_exam', e.in_exam)), '[]'::jsonb)
      INTO examples
      FROM public.ai_model_examples e
     WHERE e.model_id IN (
               SELECT t.model_id
                 FROM public.ai_model_teachers t
                WHERE t.user_id = p_user)
       AND (
            e.in_exam
            OR EXISTS (
                SELECT 1
                  FROM public.ai_models m
                 WHERE m.id = e.model_id
                   AND m.status IN ('learning', 'ready')));

    SELECT COALESCE(jsonb_agg(jsonb_build_object(
               'example_id', a.example_id,
               'model_id', a.model_id)), '[]'::jsonb)
      INTO answers
      FROM public.ai_model_answers a
     WHERE a.teacher_id = p_user
       AND a.model_id IN (
               SELECT t.model_id
                 FROM public.ai_model_teachers t
                WHERE t.user_id = p_user);

    SELECT COALESCE(jsonb_agg(jsonb_build_object(
               'id', i.id,
               'model_id', i.model_id,
               'invitee_id', i.invitee_id,
               'status', i.status,
               'created_at', i.created_at)), '[]'::jsonb)
      INTO invites
      FROM public.ai_model_invites i
     WHERE i.model_id IN (
               SELECT t.model_id
                 FROM public.ai_model_teachers t
                WHERE t.user_id = p_user);

    RETURN jsonb_build_object(
        'enabled', true,
        'teachers', taught,
        'models', models,
        'examples', examples,
        'answers', answers,
        'invites', invites);
END;
$$;

-- GET /v2/models/coach-tasks: the waiting rows of the four blind lines,
-- not the sheets. Hear-it is a count (no consent filter). The other three
-- are one take id per waiting sheet; the application still asks which
-- takes may be heard. The moments count stays the walk's own count.
CREATE OR REPLACE FUNCTION public.coach_task_rows_v1(p_coach text)
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT jsonb_build_object(
        'hear', (
            SELECT count(*)
              FROM public.error_presence_audit a
             WHERE a.coach_id = p_coach
               AND a.answer IS NULL
               AND a.cleared_week IS NULL),
        'blocks', COALESCE((
            SELECT jsonb_agg(b.take_session_id)
              FROM public.coach_block_pick b
             WHERE b.coach_id = p_coach
               AND b.answered_at IS NULL
               AND b.cleared_week IS NULL), '[]'::jsonb),
        'picks', COALESCE((
            SELECT jsonb_agg(s.take_session_id::text)
              FROM public.v4_moment_pick_sheets s
             WHERE s.rater_id = p_coach
               AND s.answered_at IS NULL
               AND s.cleared_week IS NULL), '[]'::jsonb),
        'surers', COALESCE((
            SELECT jsonb_agg(s.take_session_id::text)
              FROM public.v4_surer_sheets s
             WHERE s.rater_id = p_coach
               AND s.answered_at IS NULL
               AND s.cleared_week IS NULL), '[]'::jsonb));
$$;

REVOKE ALL ON FUNCTION public.chat_setup_models_bundle_v1(uuid)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.chat_setup_models_bundle_v1(uuid)
    TO service_role;

REVOKE ALL ON FUNCTION public.chat_setup_recipe_v1(uuid)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.chat_setup_recipe_v1(uuid)
    TO service_role;

REVOKE ALL ON FUNCTION public.model_queue_bundle_v1(uuid)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.model_queue_bundle_v1(uuid)
    TO service_role;

REVOKE ALL ON FUNCTION public.coach_task_rows_v1(text)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.coach_task_rows_v1(text)
    TO service_role;
