-- willab — the FIRST transactional write path: token_charge().
--
-- Founder directive 2026-08-03: "move invariant-critical, multi-step writes
-- into Postgres functions (.rpc()) — eliminate the half-states so a server
-- crash doesn't permanently corrupt user data."
--
-- This is that change, applied to the money path that sits ON the F1 live loop
-- (services/lab_recording.py charges the take from inside the record→transcribe
-- pipeline). It is the first `.rpc()` in this repo; before it there were zero.
--
-- ─────────────────────────────────────────────────────────────────────────
-- THE HALF-STATES THIS CLOSES
-- ─────────────────────────────────────────────────────────────────────────
-- services/token_account.charge() was FOUR unsynchronised HTTP round trips:
--
--     1. SELECT token_ledger        -- "was this ref already charged?"
--     2. UPDATE v2_student_details  -- debit (CAS on the balance)
--     3. UPDATE v2_student_details  -- coach counter (separate CAS)
--     4. INSERT token_ledger        -- the audit row
--
-- Three ways that corrupts a balance, all of them silent:
--
--   A. DEBIT WITHOUT A LEDGER ROW. Step 2 lands, the process dies (or the
--      insert throws) before step 4. The ledger is documented as the truth and
--      the balance as a cache — so the cache is now short and nothing can
--      prove why. Worse, step 1 reads the LEDGER: with no row written, the
--      next retry of the same recording_id charges AGAIN. The pipeline retries
--      by design ("a retried pipeline run re-uses recording_id and the ledger's
--      unique index absorbs it") — that absorption only works if the row landed.
--
--   B. TOCTOU DOUBLE-DEBIT. Two concurrent requests for one user both pass
--      step 1 ("not charged"), both reach step 2, and both win their CAS in
--      sequence. Step 4 then fires twice: the partial unique index rejects the
--      second row, and token_account logs it at INFO as "expected, not a
--      fault". Net result — debited twice, recorded once, permanently
--      irreconcilable.
--
--   C. FREE COACH REVIEW. Step 2 lands, step 3 fails. The tokens are gone and
--      coach_reviews_used never moved, so the founder's calendar cap — a fence,
--      not a preference — silently gains a slot.
--
-- One function = one transaction = one outcome. The debit and the ledger row
-- commit together or not at all, and the row lock in step (1) below makes B
-- impossible rather than merely unlikely.
--
-- ─────────────────────────────────────────────────────────────────────────
-- ⚠️ SECURITY — WHY THE GRANTS AT THE BOTTOM ARE NOT OPTIONAL
-- ─────────────────────────────────────────────────────────────────────────
-- PostgREST exposes EVERY function in the exposed schema at
--
--     POST https://<project>.supabase.co/rest/v1/rpc/<name>
--          apikey: <anon key lifted from the browser bundle>
--
-- and Postgres grants EXECUTE on a newly created function to PUBLIC by
-- DEFAULT. Supabase additionally hands anon/authenticated default privileges
-- on functions in `public`. So a function created with no further thought is
-- callable by any visitor who opens the site's JS — and this one MOVES MONEY.
--
-- RLS does not help here. RLS is table-level; the 2026-07-25 sweep
-- (docs/RLS-AUDIT.md) closed the table door and says NOTHING about functions.
-- Adding `.rpc()` to this codebase opens a second door of exactly the shape
-- that incident documented. The REVOKE block at the bottom is the door.
--
-- SECURITY INVOKER, deliberately, not DEFINER. DEFINER would run as the owner
-- and bypass RLS on v2_student_details / token_ledger for whoever called it —
-- turning a leaked anon key into full write access even WITH the revokes in
-- place. The backend already connects as service_role (which bypasses RLS on
-- its own), so INVOKER costs nothing and removes the escalation entirely.
--
-- ─────────────────────────────────────────────────────────────────────────
-- IDEMPOTENT + BACKWARD COMPATIBLE
-- ─────────────────────────────────────────────────────────────────────────
-- CREATE OR REPLACE — re-running is a no-op. The application detects whether
-- this function exists and falls back to the legacy four-call path when it
-- does not (PGRST202 from PostgREST), so "merged on main" and "run in prod"
-- can happen in either order without an outage. See services/token_account.py.
--
-- bonus_balance (migrations/add_legacy_credit_conversion.sql) may not exist
-- yet. The account row is read as JSONB so a missing column reads as 0 rather
-- than raising, and the only statement that WRITES bonus_balance is dynamic —
-- plpgsql does not resolve dynamic SQL at definition time, so a database
-- without that migration can still create and run this function. That branch
-- is unreachable there anyway: bonus is 0, so the balance check returns
-- 'insufficient' before it.
--
-- Run: Supabase → SQL Editor → paste → Run (executes as a single transaction).
-- Rollback (manual, never automatic):
--     DROP FUNCTION IF EXISTS public.token_charge(
--         text, text, bigint, text, text, text, boolean, integer);

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
    PERFORM 1
       FROM public.v2_student_details
      WHERE user_id = p_user_id
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
     WHERE d.user_id = p_user_id;

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
      USING p_user_id;

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
    'under a per-user row lock. Replaces the four-round-trip Python path in '
    'services/token_account.charge(). SECURITY INVOKER; service_role only — '
    'see the REVOKE block in migrations/add_token_charge_rpc.sql.';

-- ── GRANTS — the door ────────────────────────────────────────────────────
--
-- Default EXECUTE on a new function goes to PUBLIC, and PostgREST publishes it
-- at /rest/v1/rpc/token_charge. Without this block, anyone holding the anon key
-- from the browser bundle could set any user's balance to anything.
--
-- Roles are guarded: anon / authenticated / service_role exist on Supabase but
-- not on a bare Postgres, and a missing role must not abort the migration.

REVOKE ALL ON FUNCTION public.token_charge(
    text, text, bigint, text, text, text, boolean, integer) FROM PUBLIC;

DO $$
DECLARE
    r        text;
    v_sig    text := 'public.token_charge(text, text, bigint, text, text, '
                     'text, boolean, integer)';
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON FUNCTION %s FROM %I', v_sig, r);
            RAISE NOTICE 'token_charge: EXECUTE revoked from %', r;
        END IF;
    END LOOP;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role', v_sig);
        RAISE NOTICE 'token_charge: EXECUTE granted to service_role';
    ELSE
        RAISE NOTICE 'token_charge: no service_role on this database — the '
                     'owner retains EXECUTE, nothing else was granted';
    END IF;
END $$;

-- ── VERIFY (read-only; run after) ────────────────────────────────────────
--
-- Should list service_role and nothing else for anon/authenticated:
--
--   SELECT p.proname,
--          has_function_privilege('anon',          p.oid, 'EXECUTE') AS anon,
--          has_function_privilege('authenticated', p.oid, 'EXECUTE') AS authed,
--          has_function_privilege('service_role',  p.oid, 'EXECUTE') AS svc
--     FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
--    WHERE n.nspname = 'public' AND p.proname = 'token_charge';
--
-- And the end-to-end check, which must return 401/404 rather than a balance:
--
--   curl -X POST "https://<project>.supabase.co/rest/v1/rpc/token_charge" \
--        -H "apikey: <ANON key>" -H "Authorization: Bearer <ANON key>" \
--        -H "Content-Type: application/json" \
--        -d '{"p_user_id":"<any>","p_action":"chat","p_price":0}'
