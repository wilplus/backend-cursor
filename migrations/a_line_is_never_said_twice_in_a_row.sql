-- 0438 · a signed line is never said twice in a row (build plan D-FW-3;
-- docs/SIGNED-line-bank-2026-10-06.md "Rotation"; founder lock
-- 2026-10-06, the Feedback walk, "Line bank"; decisions log N54).
--
-- WHY. The signed bank says: "within one bank the app never shows the same
-- line twice in a row. A 'later' line shows only from Take 2 on, with the
-- real Take number, and only when it is true." Never twice in a row needs
-- a memory of the line last shown, per speaker and per bank, that survives
-- a reload, a new Take and another device.
--
-- WHAT. One table, line_bank_memory: per (user_id, bank) the index of the
-- line last shown (-1 when it was the bank's "later" line, NULL before the
-- first) and the index of
-- the last ordinary line, so the rotation continues past a later line. One
-- function, pick_line_bank_line_v1, decides and records in one call
-- under the row's lock, so two concurrent picks cannot both see the same
-- "last" and say the same line:
--   * p_later_true (the caller has proved the later line is true: Take 2
--     on, the cue measurably weaker then) and the last line shown was not
--     already that later line -> -1, the later line;
--   * otherwise the next ordinary line after the last ordinary one,
--     (last + 1) mod p_size, starting at 0. With p_size >= 2 this is never
--     the index shown just before.
-- The bank's lines live in code (services/line_bank.py, byte-identical to
-- the signed file); this table holds indexes only: no text, no score, no
-- number but an index into a signed bank (AC-9).
--
-- PRIVATE. RLS on with no policy; the browser roles hold nothing on the
-- table or the function; the app calls the function with the service key.
-- Purged with the account (services/data_purge_registry.py,
-- line_bank_memory by user_id).
--
-- Additive; idempotent; no env var; no lock on an existing table.
-- Rollback (a new forward migration): drop the function and the table.

BEGIN;

CREATE TABLE IF NOT EXISTS public.line_bank_memory (
    user_id          text        NOT NULL,
    bank             text        NOT NULL,
    last_index       integer     NULL,
    last_plain_index integer     NULL,
    shown_at         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT line_bank_memory_pkey PRIMARY KEY (user_id, bank),
    CONSTRAINT line_bank_memory_bank_shape CHECK (bank ~ '^[A-Za-z0-9]{2,8}$'),
    CONSTRAINT line_bank_memory_last_index_range CHECK (
        last_index IS NULL OR last_index >= -1),
    CONSTRAINT line_bank_memory_plain_index_range CHECK (
        last_plain_index IS NULL OR last_plain_index >= 0)
);
ALTER TABLE public.line_bank_memory ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.line_bank_memory IS
    'The signed line last shown per speaker and bank (0438, D-FW-3): '
    'last_index is its index in the bank, -1 for the bank''s later line, '
    'NULL before the first; '
    'last_plain_index is the last ordinary line, from which the rotation '
    'continues. Indexes only, never text or a score. Purged with the account.';

CREATE OR REPLACE FUNCTION public.pick_line_bank_line_v1(
    p_user_id text, p_bank text, p_size integer, p_later_true boolean
) RETURNS integer
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
    v_last  integer;
    v_plain integer;
    v_next  integer;
BEGIN
    IF p_user_id IS NULL OR btrim(p_user_id) = '' THEN
        RAISE EXCEPTION 'LINE_BANK_USER_REQUIRED';
    END IF;
    IF p_size IS NULL OR p_size < 1 THEN
        RAISE EXCEPTION 'LINE_BANK_SIZE_INVALID';
    END IF;
    -- The first line of a speaker's bank: make the row exist so it can be
    -- locked. A concurrent first pick finds it through the conflict.
    INSERT INTO public.line_bank_memory (user_id, bank, last_index, last_plain_index)
    VALUES (p_user_id, p_bank, NULL, NULL)
    ON CONFLICT (user_id, bank) DO NOTHING;
    SELECT last_index, last_plain_index INTO v_last, v_plain
      FROM public.line_bank_memory
     WHERE user_id = p_user_id AND bank = p_bank
       FOR UPDATE;
    IF p_later_true AND v_last IS DISTINCT FROM -1 THEN
        v_next := -1;
    ELSE
        v_next := (COALESCE(v_plain, -1) + 1) % p_size;
        v_plain := v_next;
    END IF;
    UPDATE public.line_bank_memory
       SET last_index = v_next, last_plain_index = v_plain, shown_at = now()
     WHERE user_id = p_user_id AND bank = p_bank;
    RETURN v_next;
END;
$$;

DO $$
DECLARE
    v_role text;
BEGIN
    REVOKE ALL ON TABLE public.line_bank_memory FROM PUBLIC;
    REVOKE ALL ON FUNCTION public.pick_line_bank_line_v1(text, text, integer, boolean) FROM PUBLIC;
    FOREACH v_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
            EXECUTE format('REVOKE ALL ON TABLE public.line_bank_memory FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON FUNCTION public.pick_line_bank_line_v1(text, text, integer, boolean) FROM %I', v_role);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT EXECUTE ON FUNCTION public.pick_line_bank_line_v1(text, text, integer, boolean) TO service_role;
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.line_bank_memory TO service_role;
    END IF;
END $$;

COMMIT;
