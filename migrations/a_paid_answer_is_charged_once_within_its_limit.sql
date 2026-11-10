-- a_paid_answer_is_charged_once_within_its_limit (a paid answer is charged
-- once however often it is retried, and a key's monthly limit cannot be
-- passed by two answers at once; founder, the Claude Code chat, 10 November
-- 2026: N615 item 3, N620 step 4; the stories PIPE-07 and PIPE-08 of
-- docs/design/the-blank-setup-2026-11-10/stories.json; and the examples
-- sweep's turn, so every model is reached).
--
-- Builds on a_business_can_buy_a_model_s_answers (0521). The rules live in
-- services/model_api_store.py; this table and this function only hold and
-- take what it asks for.
--
--   ai_model_charges   One row per answer a key asked for, written BEFORE
--                      the model is asked: the key, what the answer costs
--                      (0 for a test key's free answer), the caller's
--                      Idempotency-Key and a SHA-256 of the question when
--                      the caller sent one, and its stage: reserved (the
--                      model is being asked), answered, or released (no
--                      answer came; what was taken was given back). Its id
--                      is the call's id: the token charge's ref and, once
--                      answered, the ai_model_calls row's id. ``reply`` is
--                      the answer given, kept ONLY for a call that sent an
--                      Idempotency-Key, so a retry gets the same answer and
--                      is charged nothing; it and the key are cleared after
--                      24 hours, the next time that key asks.
--   ai_model_answer_reserve(key, units, idempotency_key, request_hash)
--                      The check and the take in one transaction, under a
--                      row lock on the key (SELECT ... FOR UPDATE), so two
--                      answers arriving together at a key's limit are
--                      served one after the other and only one passes
--                      (PIPE-08). A retry with the same Idempotency-Key gets
--                      the first answer back, or "in flight" while the first
--                      is still being asked, and nothing new is reserved
--                      (PIPE-07). Answers what it did: reserved, replay,
--                      in_flight, mismatch (same key, another question),
--                      limit, or no_key (unknown or revoked).
--                      SECURITY INVOKER: it runs with the caller's rights;
--                      only service_role may execute it.
--   ai_models (1 column)  examples_gathered_at: when the periodic sweep last
--                      gathered a model's examples from Takes, so each run
--                      takes the models it reached longest ago and every
--                      model is reached over successive runs.
--
-- What a month has spent is counted, inside the function, as the charges
-- not released this month plus the answers of this month that came before
-- this migration (ai_model_calls rows with no charge row). An answered
-- charge and its call row share an id, so nothing is counted twice.
--
-- Read and written by the backend (service role) only; nothing for anon or
-- authenticated. RLS on, no policies, like the neighbouring model tables. No
-- environment variable needed. No new ring row: everything here sits behind
-- the ring row ai_models (0516). Account erasure: a charge goes with its key
-- (ON DELETE CASCADE), and services/data_purge_registry.py already deletes a
-- person's keys.
--
-- Idempotent and additive: CREATE ... IF NOT EXISTS, ADD COLUMN IF NOT
-- EXISTS, constraints added only when missing, CREATE OR REPLACE for the
-- function; nothing is dropped and no existing row is written, rewritten or
-- removed. One transaction.
--
-- Rollback (a new forward migration): leave the table, the column and the
-- function; the code that calls the function can be reverted on its own.

BEGIN;

CREATE TABLE IF NOT EXISTS public.ai_model_charges (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    key_id           UUID        NOT NULL REFERENCES public.ai_model_api_keys(id) ON DELETE CASCADE,
    units            INTEGER     NOT NULL DEFAULT 0,
    idempotency_key  TEXT        NULL,
    request_hash     TEXT        NULL,
    status           TEXT        NOT NULL DEFAULT 'reserved',
    reply            JSONB       NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    settled_at       TIMESTAMPTZ NULL
);

ALTER TABLE public.ai_models ADD COLUMN IF NOT EXISTS examples_gathered_at TIMESTAMPTZ NULL;

-- Each CHECK is added NOT VALID (no scan under the ACCESS EXCLUSIVE lock),
-- then validated (a scan under SHARE UPDATE EXCLUSIVE). VALIDATE on an
-- already valid constraint is a no-op, so a second run is safe. The table is
-- new and empty on the first run.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ai_model_charges_units'
                      AND conrelid = 'public.ai_model_charges'::regclass) THEN
        ALTER TABLE public.ai_model_charges
            ADD CONSTRAINT ai_model_charges_units CHECK (units >= 0) NOT VALID;
    END IF;
    ALTER TABLE public.ai_model_charges VALIDATE CONSTRAINT ai_model_charges_units;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ai_model_charges_status'
                      AND conrelid = 'public.ai_model_charges'::regclass) THEN
        ALTER TABLE public.ai_model_charges
            ADD CONSTRAINT ai_model_charges_status
            CHECK (status IN ('reserved', 'answered', 'released')) NOT VALID;
    END IF;
    ALTER TABLE public.ai_model_charges VALIDATE CONSTRAINT ai_model_charges_status;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ai_model_charges_key_shape'
                      AND conrelid = 'public.ai_model_charges'::regclass) THEN
        ALTER TABLE public.ai_model_charges
            ADD CONSTRAINT ai_model_charges_key_shape
            CHECK (idempotency_key IS NULL OR idempotency_key ~ '^[!-~]{1,255}$') NOT VALID;
    END IF;
    ALTER TABLE public.ai_model_charges VALIDATE CONSTRAINT ai_model_charges_key_shape;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ai_model_charges_hash_shape'
                      AND conrelid = 'public.ai_model_charges'::regclass) THEN
        ALTER TABLE public.ai_model_charges
            ADD CONSTRAINT ai_model_charges_hash_shape
            CHECK (request_hash IS NULL OR request_hash ~ '^[0-9a-f]{64}$') NOT VALID;
    END IF;
    ALTER TABLE public.ai_model_charges VALIDATE CONSTRAINT ai_model_charges_hash_shape;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ai_model_charges_reply_kept'
                      AND conrelid = 'public.ai_model_charges'::regclass) THEN
        ALTER TABLE public.ai_model_charges
            ADD CONSTRAINT ai_model_charges_reply_kept
            CHECK (reply IS NULL OR (status = 'answered' AND idempotency_key IS NOT NULL
                                     AND jsonb_typeof(reply) = 'object')) NOT VALID;
    END IF;
    ALTER TABLE public.ai_model_charges VALIDATE CONSTRAINT ai_model_charges_reply_kept;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ai_model_charges_settled'
                      AND conrelid = 'public.ai_model_charges'::regclass) THEN
        ALTER TABLE public.ai_model_charges
            ADD CONSTRAINT ai_model_charges_settled
            CHECK (status = 'reserved' OR settled_at IS NOT NULL) NOT VALID;
    END IF;
    ALTER TABLE public.ai_model_charges VALIDATE CONSTRAINT ai_model_charges_settled;
END
$$;

-- Plain CREATE INDEX, not CONCURRENTLY, for 0474's and 0483's reason: the
-- runner sends a file as one transaction block, where CONCURRENTLY is
-- refused. ai_model_charges is new and empty on the first run, so each build
-- is instant.

-- PIPE-07's backstop: one live charge per (key, Idempotency-Key). A released
-- charge (no answer came) frees its key, so the caller's retry is a new try.
CREATE UNIQUE INDEX IF NOT EXISTS ai_model_charges_idempotency_once
    ON public.ai_model_charges (key_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL AND status <> 'released';
-- PIPE-08's month: a key's charges since the first of the month.
CREATE INDEX IF NOT EXISTS idx_ai_model_charges_key_month
    ON public.ai_model_charges (key_id, created_at);

CREATE OR REPLACE FUNCTION public.ai_model_answer_reserve(
    p_key_id          UUID,
    p_units           INTEGER,
    p_idempotency_key TEXT DEFAULT NULL,
    p_request_hash    TEXT DEFAULT NULL)
RETURNS TABLE (outcome TEXT, charge_id UUID, reply JSONB)
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_limit  BIGINT;
    v_month  TIMESTAMPTZ := date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
    v_spent  BIGINT;
    v_found  RECORD;
    v_id     UUID;
BEGIN
    IF p_units IS NULL OR p_units < 0 THEN
        RAISE EXCEPTION 'ai_model_answer_reserve: units must be 0 or more' USING ERRCODE = '22023';
    END IF;

    -- The key's row lock: every reserve for this key waits here for the one
    -- before it to commit, so the month's sum below is never stale.
    SELECT k.monthly_limit_units INTO v_limit
      FROM public.ai_model_api_keys k
     WHERE k.id = p_key_id AND k.revoked_at IS NULL
       FOR UPDATE;
    IF NOT FOUND THEN
        RETURN QUERY SELECT 'no_key'::TEXT, NULL::UUID, NULL::JSONB;
        RETURN;
    END IF;

    IF p_idempotency_key IS NOT NULL THEN
        -- A key's replies are kept 24 hours, then let go. Only this key's
        -- rows that still hold an Idempotency-Key older than 24 hours are
        -- touched. Lazy on purpose: a background sweep of keys that never
        -- ask again is out of scope (the founder's review of 0523).
        UPDATE public.ai_model_charges c
           SET idempotency_key = NULL, request_hash = NULL, reply = NULL
         WHERE c.key_id = p_key_id
           AND c.idempotency_key IS NOT NULL
           AND c.created_at < now() - INTERVAL '24 hours';

        SELECT c.id, c.status, c.reply, c.request_hash INTO v_found
          FROM public.ai_model_charges c
         WHERE c.key_id = p_key_id
           AND c.idempotency_key = p_idempotency_key
           AND c.status <> 'released'
         LIMIT 1
           FOR UPDATE;
        IF FOUND THEN
            IF v_found.request_hash IS DISTINCT FROM p_request_hash THEN
                RETURN QUERY SELECT 'mismatch'::TEXT, v_found.id, NULL::JSONB;
            ELSIF v_found.status = 'answered' THEN
                RETURN QUERY SELECT 'replay'::TEXT, v_found.id, v_found.reply;
            ELSE
                RETURN QUERY SELECT 'in_flight'::TEXT, v_found.id, NULL::JSONB;
            END IF;
            RETURN;
        END IF;
    END IF;

    IF v_limit IS NOT NULL AND p_units > 0 THEN
        SELECT COALESCE((SELECT sum(c.units) FROM public.ai_model_charges c
                          WHERE c.key_id = p_key_id AND c.created_at >= v_month
                            AND c.status <> 'released'), 0)
             + COALESCE((SELECT sum(a.price_units) FROM public.ai_model_calls a
                          WHERE a.key_id = p_key_id AND a.created_at >= v_month
                            AND NOT EXISTS (SELECT 1 FROM public.ai_model_charges c
                                             WHERE c.id = a.id)), 0)
          INTO v_spent;
        IF v_spent + p_units > v_limit THEN
            RETURN QUERY SELECT 'limit'::TEXT, NULL::UUID, NULL::JSONB;
            RETURN;
        END IF;
    END IF;

    -- A second guard (the founder's review of 0523): the key row's lock above
    -- already serialises every reserve for one key, so this handler should
    -- never run; if two charges ever race for one (key, Idempotency-Key),
    -- the unique index refuses the second and it answers as a retry does.
    BEGIN
        INSERT INTO public.ai_model_charges (key_id, units, idempotency_key, request_hash)
        VALUES (p_key_id, p_units, p_idempotency_key, p_request_hash)
        RETURNING id INTO v_id;
    EXCEPTION WHEN unique_violation THEN
        SELECT c.id, c.status, c.reply, c.request_hash INTO v_found
          FROM public.ai_model_charges c
         WHERE c.key_id = p_key_id
           AND c.idempotency_key = p_idempotency_key
           AND c.status <> 'released'
         LIMIT 1
           FOR UPDATE;
        IF NOT FOUND THEN
            RAISE;
        END IF;
        IF v_found.request_hash IS DISTINCT FROM p_request_hash THEN
            RETURN QUERY SELECT 'mismatch'::TEXT, v_found.id, NULL::JSONB;
        ELSIF v_found.status = 'answered' THEN
            RETURN QUERY SELECT 'replay'::TEXT, v_found.id, v_found.reply;
        ELSE
            RETURN QUERY SELECT 'in_flight'::TEXT, v_found.id, NULL::JSONB;
        END IF;
        RETURN;
    END;
    RETURN QUERY SELECT 'reserved'::TEXT, v_id, NULL::JSONB;
END
$$;

REVOKE ALL ON FUNCTION public.ai_model_answer_reserve(UUID, INTEGER, TEXT, TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ai_model_answer_reserve(UUID, INTEGER, TEXT, TEXT) TO service_role;

ALTER TABLE public.ai_model_charges ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.ai_model_charges FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.ai_model_charges TO service_role;

COMMIT;
