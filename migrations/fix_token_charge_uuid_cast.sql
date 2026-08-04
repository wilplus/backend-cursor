-- URGENT: token_charge has never run. Fixes a runtime type error in 0241.
--
-- ─────────────────────────────────────────────────────────────────────────
-- WHAT HAPPENED
-- ─────────────────────────────────────────────────────────────────────────
-- migrations/add_token_charge_rpc.sql (0241, #328) compares the account row on
--
--     WHERE user_id = p_user_id      -- uuid column = text parameter
--
-- `public.v2_student_details.user_id` is UUID (add_v2_student_details.sql) and
-- PostgREST hands every JSON string in as TEXT. Postgres has NO `uuid = text`
-- operator, so that raises
--
--     ERROR:  operator does not exist: uuid = text     (SQLSTATE 42883)
--
-- plpgsql resolves SQL inside a function body at FIRST EXECUTION, not at
-- CREATE, so the migration applied cleanly and reported success. The very
-- first call fails, and every call since has failed the same way.
--
-- ─────────────────────────────────────────────────────────────────────────
-- WHY NOBODY NOTICED — the part worth learning from
-- ─────────────────────────────────────────────────────────────────────────
-- services/token_account._rpc_not_found() treats SQLSTATE 42883 as "the
-- function is not installed", because that is also the code PostgREST returns
-- for a genuinely missing function. So the chain was:
--
--     token_charge raises 42883
--       -> read as "not installed"
--       -> negative-cached for 10 minutes
--       -> silently falls back to the legacy four-round-trip path
--       -> logs INFO "not installed — using the legacy non-atomic path"
--
-- Nothing broke, no money moved wrongly, and charging kept working — on the
-- OLD path. The entire #328 atomicity fix has been inert in production since
-- the migration ran, while the logs said "not installed" about a function that
-- was installed and broken. A fallback that cannot tell "absent" from "broken"
-- converts a loud failure into a silent one.
--
-- Two things change as a result:
--   * this migration fixes the cast;
--   * services/token_account._rpc_not_found() is narrowed so a bare 42883 from
--     INSIDE a function is no longer read as "not installed" — it must also
--     name the function. A genuine in-function error now fails loudly instead
--     of quietly downgrading.
--
-- The test fixture is fixed too: test_token_pricing.py's double declared
-- user_id as TEXT, which is why a live-Postgres verification of #328 passed
-- against a schema production does not have.
--
-- ─────────────────────────────────────────────────────────────────────────
-- THE FIX
-- ─────────────────────────────────────────────────────────────────────────
-- Cast once, guarded, at the top; use the uuid for every v2_student_details
-- access. public.token_ledger.user_id is TEXT (add_token_pricing.sql), so the
-- ledger insert deliberately keeps the original text value — the two tables
-- genuinely disagree on the type and both are load-bearing.
--
-- The guard matters: a bare `p_user_id::uuid` on a non-UUID id would raise
-- invalid_text_representation and abort a recording's charge. It degrades to
-- reason='no_user' with ok=true instead, which fails OPEN per fence §6.1.
--
-- Idempotent (CREATE OR REPLACE). Nothing else in 0241 changes: same
-- signature, same grants, same semantics. Body below is derived from 0241
-- verbatim apart from the cast.
--
-- Rollback: re-run migrations/add_token_charge_rpc.sql (restores the broken
-- version — there is no reason to want this).

CREATE OR REPLACE FUNCTION public.token_charge(
    p_user_id       text,
    p_action        text,
    p_price         bigint,
    p_ref_id        text    DEFAULT NULL,
    p_tier          text    DEFAULT NULL,
    p_price_version text    DEFAULT NULL,
    p_coach_action  boolean DEFAULT false,
    p_coach_allowed integer DEFAULT 0
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY INVOKER
-- Pinned so a caller cannot shadow `public` with a temp schema and have this
-- function resolve `token_ledger` to a table they control.
SET search_path = public, pg_temp
AS $fn$
DECLARE
    v_row          jsonb;
    v_price        bigint  := GREATEST(COALESCE(p_price, 0), 0);
    v_monthly      bigint;
    v_bonus        bigint;
    v_balance      bigint;
    v_reviews      integer;
    v_allowed      integer := GREATEST(COALESCE(p_coach_allowed, 0), 0);
    v_from_monthly bigint;
    v_from_bonus   bigint;
    v_new_balance  bigint;
    v_sets         text[]  := ARRAY[]::text[];
    v_uid          uuid;
BEGIN
    IF p_user_id IS NULL OR btrim(p_user_id) = '' OR p_action IS NULL THEN
        RETURN jsonb_build_object('ok', true, 'charged', 0, 'balance', 0,
                                  'reason', 'no_user');
    END IF;

    -- (1) THE LOCK. Everything below — the idempotency probe, the cap check,
    -- the balance check, the debit, the ledger insert — runs while this one
    -- user's row is held, so two concurrent charges for the same user
    -- SERIALIZE instead of interleaving. This is what kills half-state B, and
    -- it is also why no CAS retry loop appears anywhere in this function: the
    -- read cannot go stale between the check and the write.
    --
    -- Scoped to a single row keyed by user_id, so contention is per-user and
    -- one user's charge never blocks another's.
    BEGIN
        v_uid := p_user_id::uuid;
    EXCEPTION WHEN invalid_text_representation THEN
        RETURN jsonb_build_object('ok', true, 'charged', 0, 'balance', 0,
                                  'reason', 'no_user');
    END;

    PERFORM 1
       FROM public.v2_student_details
      WHERE user_id = v_uid
        FOR UPDATE;

    IF NOT FOUND THEN
        -- No account row. The caller seeds via ensure_period_current() before
        -- reaching this, so this is the "cannot read the account" case, and
        -- fence §6.1 says FAIL OPEN — never fail a recording over a billing
        -- lookup. ok=true, charged=0: the action proceeds, unmetered.
        RETURN jsonb_build_object('ok', true, 'charged', 0, 'balance', 0,
                                  'reason', 'account_unavailable');
    END IF;

    -- Read as JSONB, not into typed columns: bonus_balance may not exist on a
    -- database where add_legacy_credit_conversion.sql has not been run, and
    -- `->> 'missing_key'` yields NULL where a static column reference would
    -- raise and take every charge down with it.
    SELECT to_jsonb(d) INTO v_row
      FROM public.v2_student_details d
     WHERE d.user_id = v_uid;

    v_monthly := GREATEST(COALESCE((v_row->>'token_balance')::bigint, 0), 0);
    v_bonus   := GREATEST(COALESCE((v_row->>'bonus_balance')::bigint, 0), 0);
    v_reviews := GREATEST(COALESCE((v_row->>'coach_reviews_used')::integer, 0), 0);
    v_balance := v_monthly + v_bonus;

    -- (2) Idempotency — now UNDER the lock, which is the whole fix for B.
    -- Same contract as before: an already-paid ref is ok/charged=0, never an
    -- error. Rows with a NULL ref_id (chat) are legitimately repeatable and
    -- skip this entirely.
    IF p_ref_id IS NOT NULL THEN
        PERFORM 1
           FROM public.token_ledger
          WHERE user_id = p_user_id
            AND action  = p_action
            AND ref_id  = p_ref_id
          LIMIT 1;
        IF FOUND THEN
            RETURN jsonb_build_object('ok', true, 'charged', 0,
                                      'balance', v_balance,
                                      'reason', 'already_charged');
        END IF;
    END IF;

    -- (3) The coach cap: a SECOND limit binding independently of the balance.
    -- A Max user with 1.4M tokens can still be out of reviews, and cannot buy
    -- past it. Checked before the debit so a capped call costs nothing.
    IF p_coach_action AND v_reviews >= v_allowed THEN
        RETURN jsonb_build_object('ok', false, 'charged', 0,
                                  'balance', v_balance,
                                  'reason', 'coach_cap_reached');
    END IF;

    -- (4) Can they cover it? Zero-priced actions always pass.
    IF v_price > 0 AND v_balance < v_price THEN
        RETURN jsonb_build_object('ok', false, 'charged', 0,
                                  'balance', v_balance,
                                  'reason', 'insufficient');
    END IF;

    -- (5) Debit: MONTHLY ALLOWANCE FIRST, then the non-expiring bonus. The
    -- order is load-bearing — the monthly allowance is deleted at the next
    -- period roll and the bonus (honoured legacy credits) is not, so spending
    -- bonus first would burn the permanent balance while the expiring one
    -- evaporated unused. Expiring money goes first, always.
    v_from_monthly := LEAST(v_price, v_monthly);
    v_from_bonus   := v_price - v_from_monthly;
    v_new_balance  := v_balance - v_price;

    v_sets := array_append(v_sets,
        format('token_balance = %L::bigint', v_monthly - v_from_monthly));

    -- Written ONLY when some of it is actually spent, so a database without
    -- add_legacy_credit_conversion.sql never sees this column named. Dynamic
    -- for the same reason: plpgsql resolves static SQL on first execution and
    -- would fail there, dynamic SQL only when this branch runs — and it cannot
    -- run pre-migration (bonus is 0, so step 4 already returned).
    IF v_from_bonus > 0 THEN
        v_sets := array_append(v_sets,
            format('bonus_balance = %L::bigint', v_bonus - v_from_bonus));
    END IF;

    -- Half-state C: the coach counter moves in the SAME statement as the
    -- debit, not a second CAS that could fail on its own.
    IF p_coach_action THEN
        v_sets := array_append(v_sets,
            format('coach_reviews_used = %L::integer', v_reviews + 1));
    END IF;

    EXECUTE format('UPDATE public.v2_student_details SET %s WHERE user_id = $1',
                   array_to_string(v_sets, ', '))
      USING v_uid;

    -- (6) The audit row, in the SAME transaction as the debit. That is the
    -- entire point of this function: if this INSERT raises — unique violation,
    -- disk, a dropped connection — the UPDATE above rolls back WITH it and the
    -- user is not charged. Half-state A cannot exist here. Deliberately NOT
    -- `ON CONFLICT DO NOTHING`: swallowing a conflict would reinstate exactly
    -- the debit-without-a-record this function was written to remove.
    INSERT INTO public.token_ledger
        (user_id, delta, balance_after, action, ref_id, price_version, tier)
    VALUES (p_user_id, -v_price, v_new_balance, p_action, p_ref_id,
            p_price_version, p_tier);

    RETURN jsonb_build_object('ok', true, 'charged', v_price,
                              'balance', v_new_balance, 'reason', '');
END;
$fn$;


COMMENT ON FUNCTION public.token_charge(
    text, text, bigint, text, text, text, boolean, integer) IS
    'Atomic token charge: idempotency probe, coach cap, balance check, debit '
    '(monthly before bonus), coach counter and ledger row in ONE transaction '
    'under a per-user row lock. Casts the text user_id to uuid — see '
    'fix_token_charge_uuid_cast.sql. SECURITY INVOKER; service_role only.';

-- Grants are re-asserted: CREATE OR REPLACE preserves them, but re-running is
-- free and this file must be safe to apply on a database that somehow never
-- got 0241's REVOKE block.
REVOKE ALL ON FUNCTION public.token_charge(
    text, text, bigint, text, text, text, boolean, integer) FROM PUBLIC;

DO $$
DECLARE
    r     text;
    v_sig text := 'public.token_charge(text, text, bigint, text, text, '
                  'text, boolean, integer)';
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON FUNCTION %s FROM %I', v_sig, r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role', v_sig);
    END IF;
END $$;

-- ── VERIFY (run this; it is the whole point) ─────────────────────────────
--
-- The grants query alone would NOT have caught the original bug — the
-- function existed and was correctly locked down; it just could not run. The
-- only check that catches this is CALLING it:
--
--   SELECT public.token_charge(
--       (SELECT user_id::text FROM public.v2_student_details LIMIT 1),
--       'chat', 0, NULL, 'free', 'verify', false, 0);
--
-- Expect a jsonb object with "ok": true. An ERROR mentioning "operator does
-- not exist" means this migration has not been applied.
