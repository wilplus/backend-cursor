-- 0449 · The machine reads willfidence (V4 Phase 1, B1.3; build plan
-- D-ML-8; ledger B1.3; founder S-B1 A "the four word signals", S-B1b A
-- "the moment roles", Q-B1 A, QG8 A, V4 A, V5 B, V6 A, W1, W2, H3).
--
-- WHY. V4 ranks moments by how far each is from willfident (P2) and learns
-- from whether that rises by the next Take (P5); both need a stored,
-- versioned read per moment. Phase 1 has only the machine's votes:
-- S is the machine's sound read alone, W the partial W from the four signed
-- word signals (H3). Internal only (AC-9); every input in its own column
-- (L3). Definitions: SPEC §17 willfidence-v1-machine; services/willfidence.py.
--
-- WHAT. Per moment (one block of the Take's dark frame), the database
-- computes S from the clips' universal-v3 reads, stretched (mean + 1) / 2
-- (V4 A); W = the mean of the word signals the app sends (filler, hedging,
-- slide fit, holding together); the four boxes; spread always NULL (V6 A);
-- random = in 0447's draw. No S or no W: unrateable, kept with its reason,
-- left out of averages (W2). The Take's line: mean S*W over its rated random
-- moments (W1); 'audio_problem' over 30% unrateable, else 'not_enough_data'
-- under 10 rated, else 'measured' (W2). v4_speaker_willfidence_v1: the same
-- rule over all of a speaker's random moments (QG8 A).
--
-- WHAT DOES NOT CHANGE. The frame, its writer, the draw and every served
-- path. Written from a queued job, never on the request path (LIVE LOOP).
--
-- Idempotent: IF NOT EXISTS, CREATE OR REPLACE; no row written on its own;
-- locks only the new tables. Rollback (forward): drop the two functions and
-- the two tables; nothing depends on them.

BEGIN;

CREATE TABLE IF NOT EXISTS public.v4_willfidence_reads (
    take_session_id          uuid        NOT NULL,
    policy_version           text        NOT NULL,
    read_version             text        NOT NULL,
    block_id                 text        NOT NULL,
    slide_index              integer     NULL,
    is_random                boolean     NOT NULL,
    sound_clips              integer     NOT NULL,
    s                        numeric     NULL,
    filler                   numeric     NULL,
    hedging                  numeric     NULL,
    slide_fit                numeric     NULL,
    holding_together         numeric     NULL,
    word_signals             integer     NOT NULL,
    w                        numeric     NULL,
    willfident               numeric     NULL,
    hollow                   numeric     NULL,
    hidden                   numeric     NULL,
    lost                     numeric     NULL,
    judge_spread             numeric     NULL,
    role                     text        NULL,
    roles_version            text        NOT NULL,
    holding_together_version text        NOT NULL,
    unrateable_reason        text        NULL,
    acquisition_principal_id uuid        NOT NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (take_session_id, policy_version, read_version, block_id),
    CONSTRAINT v4_willfidence_reads_frame_fk
        FOREIGN KEY (take_session_id, policy_version)
        REFERENCES public.take_feedback_policy_v3_shadow_frames
            (take_session_id, policy_version)
        ON DELETE CASCADE,
    CONSTRAINT v4_willfidence_reads_versions CHECK (
        read_version = 'willfidence-v1-machine'
        AND policy_version = 'take-feedback-policy-v3-universal-dark-v3'
        AND roles_version = 'v4-moment-roles-v1'
        AND holding_together_version = 'v4-holding-together-v1'),
    CONSTRAINT v4_willfidence_reads_ranges CHECK (
        (s IS NULL OR s BETWEEN 0 AND 1)
        AND (filler IS NULL OR filler BETWEEN 0 AND 1)
        AND (hedging IS NULL OR hedging BETWEEN 0 AND 1)
        AND (slide_fit IS NULL OR slide_fit IN (0, 0.5, 1))
        AND (holding_together IS NULL OR holding_together IN (0, 0.5, 1))
        AND (w IS NULL OR w BETWEEN 0 AND 1)),
    CONSTRAINT v4_willfidence_reads_sound CHECK (
        sound_clips >= 0 AND (s IS NULL) = (sound_clips = 0)),
    CONSTRAINT v4_willfidence_reads_words CHECK (
        word_signals = (filler IS NOT NULL)::int + (hedging IS NOT NULL)::int
                     + (slide_fit IS NOT NULL)::int
                     + (holding_together IS NOT NULL)::int
        AND (w IS NULL) = (word_signals = 0)),
    CONSTRAINT v4_willfidence_reads_boxes CHECK (
        (s IS NULL OR w IS NULL)
            = (willfident IS NULL AND hollow IS NULL
               AND hidden IS NULL AND lost IS NULL)
        AND (willfident IS NULL OR (
            willfident = s * w AND hollow = s * (1 - w)
            AND hidden = (1 - s) * w AND lost = (1 - s) * (1 - w)))),
    CONSTRAINT v4_willfidence_reads_spread CHECK (judge_spread IS NULL),
    CONSTRAINT v4_willfidence_reads_role CHECK (
        role IS NULL OR role IN ('opening', 'main_point', 'close',
                                 'evidence', 'transition', 'aside')),
    CONSTRAINT v4_willfidence_reads_unrateable CHECK (
        unrateable_reason IS NOT DISTINCT FROM CASE
            WHEN s IS NULL THEN 'no_sound_read'
            WHEN w IS NULL THEN 'no_word_signal'
        END)
);

ALTER TABLE public.v4_willfidence_reads ENABLE ROW LEVEL SECURITY;
CREATE INDEX IF NOT EXISTS v4_willfidence_reads_principal_idx
    ON public.v4_willfidence_reads (acquisition_principal_id);

CREATE TABLE IF NOT EXISTS public.v4_willfidence_takes (
    take_session_id          uuid        NOT NULL,
    policy_version           text        NOT NULL,
    read_version             text        NOT NULL,
    moments                  integer     NOT NULL,
    random_moments           integer     NOT NULL,
    rated_random_moments     integer     NOT NULL,
    willfidence              numeric     NULL,
    status                   text        NOT NULL,
    acquisition_principal_id uuid        NOT NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (take_session_id, policy_version, read_version),
    CONSTRAINT v4_willfidence_takes_frame_fk
        FOREIGN KEY (take_session_id, policy_version)
        REFERENCES public.take_feedback_policy_v3_shadow_frames
            (take_session_id, policy_version)
        ON DELETE CASCADE,
    CONSTRAINT v4_willfidence_takes_version CHECK (
        read_version = 'willfidence-v1-machine'
        AND policy_version = 'take-feedback-policy-v3-universal-dark-v3'),
    CONSTRAINT v4_willfidence_takes_counts CHECK (
        moments >= 1 AND random_moments BETWEEN 1 AND moments
        AND rated_random_moments BETWEEN 0 AND random_moments),
    CONSTRAINT v4_willfidence_takes_value CHECK (
        (willfidence IS NULL) = (rated_random_moments = 0)
        AND (willfidence IS NULL OR willfidence BETWEEN 0 AND 1)),
    CONSTRAINT v4_willfidence_takes_status CHECK (
        status = CASE
            WHEN (random_moments - rated_random_moments) * 10
                 > random_moments * 3 THEN 'audio_problem'
            WHEN rated_random_moments < 10 THEN 'not_enough_data'
            ELSE 'measured'
        END)
);

ALTER TABLE public.v4_willfidence_takes ENABLE ROW LEVEL SECURITY;
CREATE INDEX IF NOT EXISTS v4_willfidence_takes_principal_idx
    ON public.v4_willfidence_takes (acquisition_principal_id);

COMMENT ON TABLE public.v4_willfidence_reads IS
    'V4 B1.3 (0449): willfidence-v1-machine per moment (frame block): S from '
    'the clips'' universal-v3 sound reads stretched to 0..1, the four signed '
    'word signals, partial W, the four boxes, spread empty (V6 A), the '
    'signed role. Every input in its own column (L3). Written only by '
    'record_v4_willfidence_reads_v1. Internal: never in a payload (AC-9).';
COMMENT ON TABLE public.v4_willfidence_takes IS
    'V4 B1.3 (0449, QG8 A): a Take''s willfidence, the mean of S*W over its '
    'rated random moments (W1), with the W2 status. Internal (AC-9).';

CREATE OR REPLACE FUNCTION public.record_v4_willfidence_reads_v1(
    p_take_session_id uuid,
    p_reads jsonb
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    v_policy  constant text := 'take-feedback-policy-v3-universal-dark-v3';
    v_read    constant text := 'willfidence-v1-machine';
    v_frame   public.take_feedback_policy_v3_shadow_frames%ROWTYPE;
    v_n       integer;
    v_random  integer;
    v_rated   integer;
    v_mean    numeric;
    v_status  text;
BEGIN
    IF p_take_session_id IS NULL OR jsonb_typeof(p_reads) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'V4_WILLFIDENCE_INPUT_INVALID';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtext('v4-willfidence:' || p_take_session_id::text));

    IF EXISTS (SELECT 1 FROM public.v4_willfidence_takes
                WHERE take_session_id = p_take_session_id
                  AND read_version = v_read) THEN
        RETURN jsonb_build_object('outcome', 'stored', 'read_version', v_read);
    END IF;

    SELECT * INTO v_frame
      FROM public.take_feedback_policy_v3_shadow_frames
     WHERE take_session_id = p_take_session_id AND policy_version = v_policy;
    IF v_frame.take_session_id IS NULL THEN
        RETURN jsonb_build_object('outcome', 'no_frame');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.v4_random_moments
                    WHERE take_session_id = p_take_session_id
                      AND policy_version = v_policy) THEN
        RETURN jsonb_build_object('outcome', 'no_draw');
    END IF;
    IF jsonb_typeof(v_frame.frame -> 'blocks') IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'V4_WILLFIDENCE_FRAME_INVALID';
    END IF;

    -- Every read: an object naming a block, its signals in their ranges and
    -- types, its role from the signed list. Checked before anything is cast.
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(p_reads) r
         WHERE jsonb_typeof(r) IS DISTINCT FROM 'object'
            OR jsonb_typeof(r -> 'block_id') IS DISTINCT FROM 'string'
            OR EXISTS (
                SELECT 1 FROM unnest(ARRAY['filler', 'hedging', 'slide_fit',
                                           'holding_together']) AS k(key)
                 WHERE jsonb_typeof(r -> k.key) IS NOT NULL
                   AND jsonb_typeof(r -> k.key) NOT IN ('number', 'null'))
            OR (jsonb_typeof(r -> 'role') IS NOT NULL
                AND jsonb_typeof(r -> 'role') NOT IN ('string', 'null'))
    ) THEN
        RAISE EXCEPTION 'V4_WILLFIDENCE_READS_INVALID';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(p_reads) r
         WHERE NOT ((r ->> 'filler') IS NULL
                    OR (r ->> 'filler')::numeric BETWEEN 0 AND 1)
            OR NOT ((r ->> 'hedging') IS NULL
                    OR (r ->> 'hedging')::numeric BETWEEN 0 AND 1)
            OR NOT ((r ->> 'slide_fit') IS NULL
                    OR (r ->> 'slide_fit')::numeric IN (0, 0.5, 1))
            OR NOT ((r ->> 'holding_together') IS NULL
                    OR (r ->> 'holding_together')::numeric IN (0, 0.5, 1))
            OR NOT ((r ->> 'role') IS NULL
                    OR (r ->> 'role') IN ('opening', 'main_point', 'close',
                                          'evidence', 'transition', 'aside'))
    ) THEN
        RAISE EXCEPTION 'V4_WILLFIDENCE_READS_INVALID';
    END IF;

    -- The reads are the frame's moments exactly: each block once, nothing
    -- else.
    IF EXISTS (
        WITH frame_blocks AS (
            SELECT block ->> 'block_id' AS block_id, 1 AS f, 0 AS r
              FROM jsonb_array_elements(v_frame.frame -> 'blocks') block
            UNION ALL
            SELECT r ->> 'block_id', 0, 1 FROM jsonb_array_elements(p_reads) r
        )
        SELECT 1 FROM frame_blocks GROUP BY block_id
        HAVING sum(f) <> 1 OR sum(r) <> 1
    ) THEN
        RAISE EXCEPTION 'V4_WILLFIDENCE_READS_DO_NOT_MATCH_THE_FRAME';
    END IF;

    INSERT INTO public.v4_willfidence_reads (
        take_session_id, policy_version, read_version, block_id, slide_index,
        is_random, sound_clips, s, filler, hedging, slide_fit,
        holding_together, word_signals, w, willfident, hollow, hidden, lost,
        judge_spread, role, roles_version, holding_together_version,
        unrateable_reason, acquisition_principal_id
    )
    SELECT p_take_session_id, v_policy, v_read, m.block_id, m.slide_index,
           m.is_random, m.sound_clips, m.s, m.filler, m.hedging, m.slide_fit,
           m.holding_together, m.word_signals, m.w,
           m.s * m.w, m.s * (1 - m.w), (1 - m.s) * m.w,
           (1 - m.s) * (1 - m.w),
           NULL, m.role, 'v4-moment-roles-v1', 'v4-holding-together-v1',
           CASE WHEN m.s IS NULL THEN 'no_sound_read'
                WHEN m.w IS NULL THEN 'no_word_signal' END,
           v_frame.acquisition_principal_id
      FROM (
          SELECT b.block_id, b.slide_index, b.is_random, b.sound_clips,
                 b.s, b.filler, b.hedging, b.slide_fit, b.holding_together,
                 b.role, b.word_signals,
                 CASE WHEN b.word_signals > 0 THEN
                     (COALESCE(b.filler, 0) + COALESCE(b.hedging, 0)
                      + COALESCE(b.slide_fit, 0)
                      + COALESCE(b.holding_together, 0)) / b.word_signals
                 END AS w
            FROM (
                SELECT block ->> 'block_id' AS block_id,
                       CASE WHEN jsonb_typeof(block -> 'slide_index') = 'number'
                            THEN (block ->> 'slide_index')::numeric::integer
                       END AS slide_index,
                       EXISTS (SELECT 1 FROM public.v4_random_moments d
                                WHERE d.take_session_id = p_take_session_id
                                  AND d.policy_version = v_policy
                                  AND d.block_id = block ->> 'block_id')
                           AS is_random,
                       sound.clips AS sound_clips,
                       CASE WHEN sound.clips > 0
                            THEN (sound.mean + 1) / 2 END AS s,
                       (r ->> 'filler')::numeric AS filler,
                       (r ->> 'hedging')::numeric AS hedging,
                       (r ->> 'slide_fit')::numeric AS slide_fit,
                       (r ->> 'holding_together')::numeric AS holding_together,
                       r ->> 'role' AS role,
                       (r ->> 'filler' IS NOT NULL)::int
                       + (r ->> 'hedging' IS NOT NULL)::int
                       + (r ->> 'slide_fit' IS NOT NULL)::int
                       + (r ->> 'holding_together' IS NOT NULL)::int
                           AS word_signals
                  FROM jsonb_array_elements(v_frame.frame -> 'blocks') block
                  JOIN jsonb_array_elements(p_reads) r
                    ON r ->> 'block_id' = block ->> 'block_id'
                 CROSS JOIN LATERAL (
                     -- The moment's clips, as the frame lists them, that
                     -- belong to this Take and carry a universal-v3 read.
                     SELECT count(*)::int AS clips,
                            avg((snippet.metrics #>>
                                 '{voice_confidence,score}')::numeric) AS mean
                       FROM jsonb_array_elements_text(CASE
                                WHEN jsonb_typeof(block -> 'snippet_ids') = 'array'
                                THEN block -> 'snippet_ids'
                                ELSE '[]'::jsonb END) clip(id)
                       JOIN public.snippets snippet
                         ON snippet.id::text = clip.id
                        AND snippet.session_id = p_take_session_id
                      WHERE snippet.metrics #>> '{voice_confidence,version}'
                            = 'voice-confidence-universal-v3'
                        AND jsonb_typeof(snippet.metrics #>
                            '{voice_confidence,score}') = 'number'
                        AND (snippet.metrics #>> '{voice_confidence,score}')
                            ::numeric BETWEEN -1 AND 1
                 ) sound
            ) b
      ) m;

    SELECT count(*), count(*) FILTER (WHERE s IS NOT NULL AND w IS NOT NULL),
           avg(s * w) FILTER (WHERE s IS NOT NULL AND w IS NOT NULL)
      INTO v_random, v_rated, v_mean
      FROM public.v4_willfidence_reads
     WHERE take_session_id = p_take_session_id AND read_version = v_read
       AND is_random;
    v_n := jsonb_array_length(v_frame.frame -> 'blocks');
    v_status := CASE
        WHEN (v_random - v_rated) * 10 > v_random * 3 THEN 'audio_problem'
        WHEN v_rated < 10 THEN 'not_enough_data'
        ELSE 'measured' END;

    INSERT INTO public.v4_willfidence_takes (
        take_session_id, policy_version, read_version, moments,
        random_moments, rated_random_moments, willfidence, status,
        acquisition_principal_id
    ) VALUES (
        p_take_session_id, v_policy, v_read, v_n, v_random, v_rated, v_mean,
        v_status, v_frame.acquisition_principal_id
    );

    RETURN jsonb_build_object(
        'outcome', 'read', 'read_version', v_read, 'moments', v_n,
        'random_moments', v_random, 'rated_random_moments', v_rated,
        'status', v_status);
END;
$$;

CREATE OR REPLACE FUNCTION public.v4_speaker_willfidence_v1(
    p_acquisition_principal_id uuid
) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public
AS $$
    SELECT jsonb_build_object(
        'read_version', 'willfidence-v1-machine',
        'random_moments', count(*),
        'rated_random_moments', count(*) FILTER (WHERE s IS NOT NULL
                                                   AND w IS NOT NULL),
        'willfidence', avg(s * w) FILTER (WHERE s IS NOT NULL
                                            AND w IS NOT NULL),
        'status', CASE
            WHEN count(*) = 0 THEN 'not_enough_data'
            WHEN (count(*) - count(*) FILTER (WHERE s IS NOT NULL
                                                AND w IS NOT NULL)) * 10
                 > count(*) * 3 THEN 'audio_problem'
            WHEN count(*) FILTER (WHERE s IS NOT NULL AND w IS NOT NULL) < 10
                 THEN 'not_enough_data'
            ELSE 'measured' END)
      FROM public.v4_willfidence_reads
     WHERE acquisition_principal_id = p_acquisition_principal_id
       AND read_version = 'willfidence-v1-machine'
       AND is_random;
$$;

-- ── The door ───────────────────────────────────────────────────────────────
REVOKE ALL ON TABLE public.v4_willfidence_reads FROM PUBLIC;
REVOKE ALL ON TABLE public.v4_willfidence_takes FROM PUBLIC;
REVOKE ALL ON FUNCTION public.record_v4_willfidence_reads_v1(uuid, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.v4_speaker_willfidence_v1(uuid) FROM PUBLIC;
DO $$
DECLARE
    v_role text;
BEGIN
    FOREACH v_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
            EXECUTE format('REVOKE ALL ON TABLE public.v4_willfidence_reads FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON TABLE public.v4_willfidence_takes FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON FUNCTION public.record_v4_willfidence_reads_v1(uuid, jsonb) FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON FUNCTION public.v4_speaker_willfidence_v1(uuid) FROM %I', v_role);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        REVOKE ALL ON TABLE public.v4_willfidence_reads FROM service_role;
        REVOKE ALL ON TABLE public.v4_willfidence_takes FROM service_role;
        GRANT SELECT, DELETE ON TABLE public.v4_willfidence_reads TO service_role;
        GRANT SELECT, DELETE ON TABLE public.v4_willfidence_takes TO service_role;
        GRANT EXECUTE ON FUNCTION public.record_v4_willfidence_reads_v1(uuid, jsonb) TO service_role;
        GRANT EXECUTE ON FUNCTION public.v4_speaker_willfidence_v1(uuid) TO service_role;
    END IF;
END $$;

COMMIT;
