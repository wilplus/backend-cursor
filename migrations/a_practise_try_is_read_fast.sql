-- 0450 · A practise try is read fast (V4 Phase 1, B1.4; build plan D-ML-9;
-- ledger B1.4; founder O5 "under 5 s for 9 in 10 attempts, never block",
-- V7 A "the phone's clock").
--
-- WHY. In Phase 2 the walk decides after each practise try whether the
-- speaker reached the bar (S x partial W >= the bar, B1.4b). That read must
-- arrive within 5 seconds of Stop for 9 tries in 10, measured on the
-- phone's clock (V7 A: it includes the upload the speaker waits through),
-- with the server's times stored beside it because phone clocks drift. A
-- read that is late or fails never blocks: the walk treats the try as "not
-- reached yet" and the late read is still stored (O5). Phase 1 measures
-- this dark: the read is taken and timed on every try, and nothing the
-- speaker sees changes.
--
-- THE READ ('willfidence-v1-machine-fast'), per try. S = the try's own
-- universal-v3 sound read stretched to 0..1 (V4 A; the upload route already
-- reads it). The fast W = the mean of the try's filler and hedging signals
-- (S-B1 A, V5 B), the two word signals that can be read within the budget;
-- slide fit and holding together need the Take's point check and the
-- language-model call, which a few seconds do not allow. The app sends S,
-- filler and hedging; the database computes W and S*W. A try whose read
-- failed keeps a row with outcome 'failed' and no values.
--
-- THE TIMES. The server stamps when the try arrived and when its read was
-- ready. The phone later sends, once, when the speaker pressed Stop and
-- when the answer reached the phone, both on its own clock; their
-- difference is the phone's wait. Late = that wait over 5 000 ms; a read
-- that failed is late by definition. Without the phone's times the server's
-- own wait stands in, marked as such (services/v4_practice_read.py).
--
-- WHAT. One table and two writers:
--   v4_practice_reads                one row per try: the read, its
--                                    outcome, the server's and the phone's
--                                    times. FK to the try (ON DELETE
--                                    CASCADE: it goes with the try).
--   record_v4_practice_read_v1       the read and the server's times,
--                                    once per try; the try's practice,
--                                    Take and owner are read by the
--                                    database, never trusted from the app.
--   record_v4_practice_timing_v1     the phone's two times, once, only for
--                                    the try's own owner; a wait outside
--                                    0..600 000 ms is refused.
--
-- WHAT DOES NOT CHANGE. The try, its comparison, the practise check and
-- every served answer. No route returns any value of this table (AC-9).
--
-- Idempotent: IF NOT EXISTS, CREATE OR REPLACE; no row written on its own;
-- locks only the new table. Rollback (forward): drop the two functions and
-- the table; nothing depends on them.

BEGIN;

CREATE TABLE IF NOT EXISTS public.v4_practice_reads (
    attempt_id          uuid        PRIMARY KEY
                        REFERENCES public.confident_voice_practice_attempt(id)
                        ON DELETE CASCADE,
    practice_id         uuid        NOT NULL,
    take_session_id     uuid        NOT NULL,
    owner_user_id       uuid        NOT NULL,
    read_version        text        NOT NULL,
    outcome             text        NOT NULL,
    s                   numeric     NULL,
    filler              numeric     NULL,
    hedging             numeric     NULL,
    w                   numeric     NULL,
    willfident          numeric     NULL,
    server_received_at  timestamptz NOT NULL,
    server_read_at      timestamptz NOT NULL,
    phone_stopped_ms    bigint      NULL,
    phone_shown_ms      bigint      NULL,
    phone_wait_ms       integer     NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT v4_practice_reads_version CHECK (
        read_version = 'willfidence-v1-machine-fast'),
    CONSTRAINT v4_practice_reads_outcome CHECK (outcome IN ('read', 'failed')),
    CONSTRAINT v4_practice_reads_ranges CHECK (
        (s IS NULL OR s BETWEEN 0 AND 1)
        AND (filler IS NULL OR filler BETWEEN 0 AND 1)
        AND (hedging IS NULL OR hedging BETWEEN 0 AND 1)),
    CONSTRAINT v4_practice_reads_failed_is_empty CHECK (
        outcome = 'read'
        OR (s IS NULL AND filler IS NULL AND hedging IS NULL)),
    CONSTRAINT v4_practice_reads_w CHECK (
        w IS NOT DISTINCT FROM CASE
            WHEN filler IS NOT NULL AND hedging IS NOT NULL
                THEN (filler + hedging) / 2
            ELSE COALESCE(filler, hedging) END
        AND willfident IS NOT DISTINCT FROM s * w),
    CONSTRAINT v4_practice_reads_server_order CHECK (
        server_read_at >= server_received_at),
    CONSTRAINT v4_practice_reads_phone CHECK (
        (phone_stopped_ms IS NULL) = (phone_shown_ms IS NULL)
        AND (phone_wait_ms IS NULL) = (phone_shown_ms IS NULL)
        AND (phone_wait_ms IS NULL
             OR (phone_wait_ms = phone_shown_ms - phone_stopped_ms
                 AND phone_wait_ms BETWEEN 0 AND 600000)))
);

ALTER TABLE public.v4_practice_reads ENABLE ROW LEVEL SECURITY;
CREATE INDEX IF NOT EXISTS v4_practice_reads_take_idx
    ON public.v4_practice_reads (take_session_id);

COMMENT ON TABLE public.v4_practice_reads IS
    'V4 B1.4 (0450): the fast willfidence read of each practise try (S, '
    'filler, hedging, W, S*W) with the server''s and the phone''s times '
    '(O5, V7 A). Late or failed reads are stored and count as "not reached '
    'yet". Internal: never in a payload (AC-9).';

CREATE OR REPLACE FUNCTION public.record_v4_practice_read_v1(
    p_attempt_id uuid,
    p_outcome text,
    p_s numeric,
    p_filler numeric,
    p_hedging numeric,
    p_server_received_at timestamptz,
    p_server_read_at timestamptz
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    v_practice public.confident_voice_practice%ROWTYPE;
    v_w numeric;
    v_count integer;
BEGIN
    IF p_attempt_id IS NULL OR p_outcome IS NULL
       OR p_server_received_at IS NULL OR p_server_read_at IS NULL THEN
        RAISE EXCEPTION 'V4_PRACTICE_READ_INPUT_INVALID';
    END IF;
    SELECT practice.* INTO v_practice
      FROM public.confident_voice_practice_attempt attempt
      JOIN public.confident_voice_practice practice
        ON practice.id = attempt.practice_id
     WHERE attempt.id = p_attempt_id;
    IF v_practice.id IS NULL THEN
        RETURN jsonb_build_object('outcome', 'no_attempt');
    END IF;
    v_w := CASE
        WHEN p_filler IS NOT NULL AND p_hedging IS NOT NULL
            THEN (p_filler + p_hedging) / 2
        ELSE COALESCE(p_filler, p_hedging) END;
    INSERT INTO public.v4_practice_reads (
        attempt_id, practice_id, take_session_id, owner_user_id,
        read_version, outcome, s, filler, hedging, w, willfident,
        server_received_at, server_read_at
    ) VALUES (
        p_attempt_id, v_practice.id, v_practice.take_session_id,
        v_practice.owner_user_id, 'willfidence-v1-machine-fast', p_outcome,
        p_s, p_filler, p_hedging, v_w, p_s * v_w,
        p_server_received_at, p_server_read_at
    ) ON CONFLICT (attempt_id) DO NOTHING;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN jsonb_build_object(
        'outcome', CASE WHEN v_count = 1 THEN 'stored' ELSE 'already' END);
END;
$$;

CREATE OR REPLACE FUNCTION public.record_v4_practice_timing_v1(
    p_attempt_id uuid,
    p_owner_user_id uuid,
    p_phone_stopped_ms bigint,
    p_phone_shown_ms bigint
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    v_count integer;
BEGIN
    IF p_attempt_id IS NULL OR p_owner_user_id IS NULL
       OR p_phone_stopped_ms IS NULL OR p_phone_shown_ms IS NULL
       OR p_phone_shown_ms - p_phone_stopped_ms NOT BETWEEN 0 AND 600000 THEN
        RAISE EXCEPTION 'V4_PRACTICE_TIMING_INVALID';
    END IF;
    UPDATE public.v4_practice_reads
       SET phone_stopped_ms = p_phone_stopped_ms,
           phone_shown_ms = p_phone_shown_ms,
           phone_wait_ms = (p_phone_shown_ms - p_phone_stopped_ms)::integer
     WHERE attempt_id = p_attempt_id
       AND owner_user_id = p_owner_user_id
       AND phone_shown_ms IS NULL;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN jsonb_build_object(
        'outcome', CASE WHEN v_count = 1 THEN 'stored' ELSE 'unchanged' END);
END;
$$;

-- ── The door ───────────────────────────────────────────────────────────────
REVOKE ALL ON TABLE public.v4_practice_reads FROM PUBLIC;
REVOKE ALL ON FUNCTION public.record_v4_practice_read_v1(
    uuid, text, numeric, numeric, numeric, timestamptz, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.record_v4_practice_timing_v1(
    uuid, uuid, bigint, bigint) FROM PUBLIC;
DO $$
DECLARE
    v_role text;
BEGIN
    FOREACH v_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
            EXECUTE format('REVOKE ALL ON TABLE public.v4_practice_reads FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON FUNCTION public.record_v4_practice_read_v1(uuid, text, numeric, numeric, numeric, timestamptz, timestamptz) FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON FUNCTION public.record_v4_practice_timing_v1(uuid, uuid, bigint, bigint) FROM %I', v_role);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        REVOKE ALL ON TABLE public.v4_practice_reads FROM service_role;
        GRANT SELECT, DELETE ON TABLE public.v4_practice_reads TO service_role;
        GRANT EXECUTE ON FUNCTION public.record_v4_practice_read_v1(uuid, text, numeric, numeric, numeric, timestamptz, timestamptz) TO service_role;
        GRANT EXECUTE ON FUNCTION public.record_v4_practice_timing_v1(uuid, uuid, bigint, bigint) TO service_role;
    END IF;
END $$;

COMMIT;
