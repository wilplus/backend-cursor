-- Isolated experiment storage. Media and its progress commit in the same
-- database, so a lost write response cannot orphan a saved answer.
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS public.experiment_baseline_participants (
    volunteer_id text PRIMARY KEY REFERENCES public.experiment_volunteer_keys(volunteer_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS public.experiment_baseline_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    volunteer_id text NOT NULL REFERENCES public.experiment_baseline_participants(volunteer_id) ON DELETE CASCADE,
    request_id uuid NOT NULL,
    mode text NOT NULL CHECK (mode IN ('initial', 'on_demand', 'refresh')),
    protocol_version text NOT NULL,
    consent jsonb NOT NULL CHECK (jsonb_typeof(consent) = 'object'
                                AND consent @> '{"participant":true}'::jsonb),
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    UNIQUE (volunteer_id, request_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS experiment_baseline_one_initial
    ON public.experiment_baseline_runs(volunteer_id) WHERE mode = 'initial';
CREATE UNIQUE INDEX IF NOT EXISTS experiment_baseline_one_open_per_mode
    ON public.experiment_baseline_runs(volunteer_id, mode) WHERE completed_at IS NULL;
CREATE INDEX IF NOT EXISTS experiment_baseline_history
    ON public.experiment_baseline_runs(volunteer_id, mode, created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS public.experiment_baseline_steps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id uuid NOT NULL REFERENCES public.experiment_baseline_runs(id) ON DELETE CASCADE,
    position integer NOT NULL CHECK (position > 0),
    prompt_id text NOT NULL,
    prompt text NOT NULL,
    prompt_sha256 text NOT NULL CHECK (prompt_sha256 ~ '^[0-9a-f]{64}$'),
    intended_valence text CHECK (intended_valence IN ('pleasant', 'unpleasant')),
    intended_energy text NOT NULL CHECK (
        intended_energy IN ('low', 'low_to_medium', 'medium', 'medium_to_high', 'high')),
    partition text NOT NULL CHECK (partition IN ('calibration', 'held_out')),
    audio bytea CHECK (octet_length(audio) BETWEEN 1 AND 4194304),
    audio_sha256 text CHECK (audio_sha256 ~ '^[0-9a-f]{64}$'),
    content_type text CHECK (content_type IN ('audio/webm', 'audio/wav', 'audio/ogg', 'audio/mp4', 'audio/mpeg')),
    captured_at timestamptz,
    felt_valence text CHECK (felt_valence IN ('pleasant', 'unpleasant', 'neutral', 'mixed', 'unsure')),
    felt_energy text CHECK (felt_energy IN ('low', 'low_to_medium', 'medium', 'medium_to_high', 'high', 'unsure')),
    reported_at timestamptz,
    UNIQUE (run_id, position),
    UNIQUE (run_id, prompt_id),
    UNIQUE (run_id, prompt_sha256),
    CHECK ((captured_at IS NULL AND audio IS NULL AND audio_sha256 IS NULL AND content_type IS NULL)
        OR (captured_at IS NOT NULL AND audio IS NOT NULL AND audio_sha256 IS NOT NULL AND content_type IS NOT NULL)),
    CHECK (felt_energy IS NULL OR captured_at IS NOT NULL),
    CHECK ((reported_at IS NULL AND felt_valence IS NULL)
        OR (reported_at IS NOT NULL AND felt_energy IS NOT NULL AND felt_valence IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS public.experiment_baseline_predictions (
    step_id uuid NOT NULL REFERENCES public.experiment_baseline_steps(id) ON DELETE CASCADE,
    model_version text NOT NULL CHECK (char_length(btrim(model_version)) BETWEEN 1 AND 120),
    calibration_step_ids uuid[] NOT NULL CHECK (cardinality(calibration_step_ids) > 0),
    predicted_valence text CHECK (predicted_valence IN ('pleasant', 'unpleasant', 'neutral', 'mixed', 'unsure')),
    predicted_energy text CHECK (predicted_energy IN ('low', 'low_to_medium', 'medium', 'medium_to_high', 'high', 'unsure')),
    predicted_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (step_id, model_version)
);

ALTER TABLE public.experiment_baseline_participants ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.experiment_baseline_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.experiment_baseline_steps ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.experiment_baseline_predictions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.experiment_baseline_participants, public.experiment_baseline_runs, public.experiment_baseline_steps,
    public.experiment_baseline_predictions FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.experiment_baseline_participants TO service_role;
GRANT SELECT, INSERT ON public.experiment_baseline_runs TO service_role;
GRANT UPDATE (completed_at) ON public.experiment_baseline_runs TO service_role;
GRANT SELECT, INSERT ON public.experiment_baseline_steps TO service_role;
GRANT UPDATE (audio, audio_sha256, content_type, captured_at, felt_valence, felt_energy, reported_at)
    ON public.experiment_baseline_steps TO service_role;
GRANT SELECT, INSERT ON public.experiment_baseline_predictions TO service_role;

-- State is computed from the first unfinished answer in the same snapshot as
-- completion. The progress view exposes a state, with neither label nor audio.
CREATE OR REPLACE VIEW public.experiment_baseline_progress WITH (security_invoker = true) AS
SELECT r.id, r.volunteer_id, r.request_id, r.mode, r.protocol_version, r.created_at, r.completed_at,
       s.id AS next_step_id, s.prompt AS next_prompt,
       CASE WHEN s.id IS NULL THEN NULL WHEN s.captured_at IS NULL THEN 'record'
            WHEN s.felt_energy IS NULL THEN 'energy' ELSE 'valence' END AS next_step_state
FROM public.experiment_baseline_runs r
LEFT JOIN LATERAL (
    SELECT id, prompt, captured_at, felt_energy FROM public.experiment_baseline_steps
    WHERE run_id = r.id AND reported_at IS NULL ORDER BY position LIMIT 1
) s ON true;
REVOKE ALL ON public.experiment_baseline_progress FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.experiment_baseline_progress TO service_role;

CREATE OR REPLACE FUNCTION public.start_experiment_baseline(
    p_user_id uuid, p_new_volunteer_id text, p_request_id uuid, p_mode text,
    p_protocol_version text, p_consent jsonb, p_prompts jsonb
) RETURNS uuid LANGUAGE plpgsql SET search_path = '' AS $$
DECLARE
    existing public.experiment_baseline_runs%ROWTYPE;
    run_id uuid;
    p_volunteer_id text;
BEGIN
    -- 0531 locks the entire linked account graph and checks deletion and purge.
    IF NOT public.owner_chat_may_write_v1(p_user_id) THEN
        RAISE EXCEPTION 'PILOT_UNAVAILABLE';
    END IF;
    INSERT INTO public.experiment_volunteer_keys (user_id, volunteer_id) VALUES (p_user_id, p_new_volunteer_id)
    ON CONFLICT (user_id) DO NOTHING;
    SELECT volunteer_id INTO STRICT p_volunteer_id FROM public.experiment_volunteer_keys
    WHERE user_id = p_user_id FOR KEY SHARE;
    -- The participant row serializes new runs with each other and with erasure.
    INSERT INTO public.experiment_baseline_participants (volunteer_id) VALUES (p_volunteer_id)
    ON CONFLICT (volunteer_id) DO UPDATE SET volunteer_id = EXCLUDED.volunteer_id;
    SELECT * INTO existing FROM public.experiment_baseline_runs
    WHERE volunteer_id = p_volunteer_id AND request_id = p_request_id;
    IF FOUND THEN
        IF existing.mode <> p_mode THEN
            RAISE EXCEPTION 'PILOT_REQUEST_CONFLICT';
        END IF;
        RETURN existing.id;
    END IF;
    IF p_mode <> 'initial' AND NOT EXISTS (
        SELECT 1 FROM public.experiment_baseline_runs
        WHERE volunteer_id = p_volunteer_id AND mode = 'initial' AND completed_at IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'PILOT_INITIAL_REQUIRED';
    END IF;
    SELECT id INTO run_id FROM public.experiment_baseline_runs
    WHERE volunteer_id = p_volunteer_id AND mode = p_mode AND (p_mode = 'initial' OR completed_at IS NULL);
    IF FOUND THEN
        IF p_mode = 'initial' THEN
            RETURN run_id;
        END IF;
        RAISE EXCEPTION 'PILOT_RUN_IN_PROGRESS';
    END IF;
    IF jsonb_typeof(p_prompts) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'PILOT_PROTOCOL_UNAVAILABLE';
    END IF;
    IF jsonb_array_length(p_prompts) < 2 THEN
        RAISE EXCEPTION 'PILOT_PROTOCOL_UNAVAILABLE';
    END IF;
    IF p_mode = 'initial' AND (jsonb_array_length(p_prompts) <> 2
        OR (p_prompts->0->>'intended_energy') IS DISTINCT FROM 'low'
        OR (p_prompts->1->>'intended_energy') IS DISTINCT FROM 'high') THEN
        RAISE EXCEPTION 'PILOT_PROTOCOL_UNAVAILABLE';
    END IF;
    INSERT INTO public.experiment_baseline_runs (volunteer_id, request_id, mode, protocol_version, consent)
    VALUES (p_volunteer_id, p_request_id, p_mode, p_protocol_version, p_consent) RETURNING id INTO run_id;
    INSERT INTO public.experiment_baseline_steps
        (run_id, position, prompt_id, prompt, prompt_sha256, intended_valence, intended_energy, partition)
    SELECT run_id, n::integer, item->>'id', item->>'prompt', item->>'prompt_sha256',
           item->>'intended_valence', item->>'intended_energy', item->>'partition'
    FROM jsonb_array_elements(p_prompts) WITH ORDINALITY AS q(item, n);
    RETURN run_id;
END;
$$;

-- The owned run row serializes audio and report writes. Exact repeats are
-- acknowledged even when the next step has already moved on.
CREATE OR REPLACE FUNCTION public.save_experiment_baseline_step(
    p_volunteer_id text, p_run_id uuid, p_step_id uuid,
    p_audio bytea DEFAULT NULL, p_content_type text DEFAULT NULL,
    p_felt_valence text DEFAULT NULL, p_felt_energy text DEFAULT NULL
) RETURNS uuid LANGUAGE plpgsql SET search_path = '' AS $$
DECLARE
    step public.experiment_baseline_steps%ROWTYPE;
    first_missing uuid;
    audio_digest text;
    account uuid;
BEGIN
    IF num_nonnulls(p_audio, p_felt_energy, p_felt_valence) <> 1
        OR (p_audio IS NULL) <> (p_content_type IS NULL) THEN
        RAISE EXCEPTION 'PILOT_INPUT';
    END IF;
    SELECT user_id INTO account FROM public.experiment_volunteer_keys WHERE volunteer_id = p_volunteer_id;
    IF account IS NULL THEN
        RAISE EXCEPTION 'PILOT_NOT_FOUND';
    END IF;
    IF NOT public.owner_chat_may_write_v1(account) THEN
        RAISE EXCEPTION 'PILOT_UNAVAILABLE';
    END IF;
    PERFORM 1 FROM public.experiment_baseline_runs
    WHERE id = p_run_id AND volunteer_id = p_volunteer_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'PILOT_NOT_FOUND';
    END IF;
    SELECT * INTO step FROM public.experiment_baseline_steps WHERE run_id = p_run_id AND id = p_step_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'PILOT_NOT_FOUND';
    END IF;
    IF p_audio IS NOT NULL THEN
        audio_digest := encode(sha256(p_audio), 'hex');
        IF step.captured_at IS NOT NULL THEN
            IF step.audio_sha256 = audio_digest AND step.content_type = p_content_type THEN
                RETURN p_run_id;
            END IF;
            RAISE EXCEPTION 'PILOT_STEP_CONFLICT';
        END IF;
    ELSIF p_felt_energy IS NOT NULL AND step.felt_energy IS NOT NULL THEN
        IF step.felt_energy = p_felt_energy THEN
            RETURN p_run_id;
        END IF;
        RAISE EXCEPTION 'PILOT_STEP_CONFLICT';
    ELSIF p_felt_valence IS NOT NULL AND step.felt_valence IS NOT NULL THEN
        IF step.felt_valence = p_felt_valence THEN
            RETURN p_run_id;
        END IF;
        RAISE EXCEPTION 'PILOT_STEP_CONFLICT';
    END IF;
    SELECT id INTO first_missing FROM public.experiment_baseline_steps
    WHERE run_id = p_run_id AND reported_at IS NULL ORDER BY position LIMIT 1;
    IF first_missing IS DISTINCT FROM p_step_id THEN
        RAISE EXCEPTION 'PILOT_STEP_ORDER';
    END IF;
    IF p_audio IS NOT NULL THEN
        UPDATE public.experiment_baseline_steps
        SET audio = p_audio, audio_sha256 = audio_digest, content_type = p_content_type, captured_at = now()
        WHERE id = p_step_id;
    ELSIF step.captured_at IS NULL THEN
        RAISE EXCEPTION 'PILOT_AUDIO_REQUIRED';
    ELSIF p_felt_energy IS NOT NULL THEN
        UPDATE public.experiment_baseline_steps SET felt_energy = p_felt_energy WHERE id = p_step_id;
    ELSE
        IF step.felt_energy IS NULL THEN
            RAISE EXCEPTION 'PILOT_STEP_ORDER';
        END IF;
        UPDATE public.experiment_baseline_steps
        SET felt_valence = p_felt_valence, reported_at = now()
        WHERE id = p_step_id;
        UPDATE public.experiment_baseline_runs SET completed_at = now()
        WHERE id = p_run_id AND completed_at IS NULL AND NOT EXISTS (
            SELECT 1 FROM public.experiment_baseline_steps WHERE run_id = p_run_id AND reported_at IS NULL
        );
    END IF;
    RETURN p_run_id;
END;
$$;

-- The evaluation projection admits one held-out answer in the same completed
-- run as its calibration sources. Reused media is excluded from calibration
-- even when saved against a different prompt. The view carries no prompt or
-- self-report fields.
CREATE OR REPLACE FUNCTION public.blind_experiment_baseline_audio(
    p_volunteer_id text, p_run_id uuid, p_step_id uuid
) RETURNS TABLE(step_id uuid, target boolean, audio_hex text, content_type text)
LANGUAGE sql STABLE SET search_path = '' AS $$
    SELECT a.id, a.id = h.id, encode(a.audio, 'hex'), a.content_type
    FROM public.experiment_baseline_runs r
    JOIN public.experiment_baseline_steps h ON h.run_id = r.id AND h.id = p_step_id
      AND h.partition = 'held_out' AND h.reported_at IS NOT NULL
    JOIN public.experiment_baseline_steps a ON a.run_id = r.id AND a.reported_at IS NOT NULL
    WHERE r.id = p_run_id AND r.volunteer_id = p_volunteer_id AND r.completed_at IS NOT NULL
      AND (a.id = h.id OR (
          a.partition = 'calibration' AND NOT EXISTS (
              SELECT 1 FROM public.experiment_baseline_steps excluded
              WHERE excluded.run_id = r.id AND excluded.partition = 'held_out'
                AND (excluded.audio_sha256 = a.audio_sha256 OR excluded.prompt_sha256 = a.prompt_sha256)
          )
      ))
    ORDER BY a.position;
$$;

-- Scoring is a separate read. There is no row to score until a prediction
-- for this exact answer and model version has committed.
CREATE OR REPLACE VIEW public.experiment_baseline_scored WITH (security_invoker = true) AS
SELECT r.volunteer_id, r.id AS run_id, s.id AS step_id, p.model_version, p.calibration_step_ids,
       p.predicted_valence, p.predicted_energy, p.predicted_at, s.felt_valence, s.felt_energy,
       s.intended_valence, s.intended_energy, s.prompt_id
FROM public.experiment_baseline_predictions p
JOIN public.experiment_baseline_steps s ON s.id = p.step_id AND s.partition = 'held_out'
JOIN public.experiment_baseline_runs r ON r.id = s.run_id AND r.completed_at IS NOT NULL;
REVOKE ALL ON public.experiment_baseline_scored FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.experiment_baseline_scored TO service_role;

REVOKE ALL ON FUNCTION public.start_experiment_baseline(uuid,text,uuid,text,text,jsonb,jsonb)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.save_experiment_baseline_step(text,uuid,uuid,bytea,text,text,text)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.blind_experiment_baseline_audio(text,uuid,uuid)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.start_experiment_baseline(uuid,text,uuid,text,text,jsonb,jsonb),
    public.save_experiment_baseline_step(text,uuid,uuid,bytea,text,text,text),
    public.blind_experiment_baseline_audio(text,uuid,uuid) TO service_role;

NOTIFY pgrst, 'reload schema';
