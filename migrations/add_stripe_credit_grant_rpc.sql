-- Atomic Stripe credit grant — the money-IN path, in one transaction.
--
-- Second transactional write path, after token_charge (#328). Founder
-- 2026-08-04: "do the stripe credits path next." Ranked first in
-- docs/DB-TRANSACTIONS.md § "What is NOT atomic yet" by what a failure costs,
-- because this is the one a user actually complains about — they paid.
--
-- ─────────────────────────────────────────────────────────────────────────
-- THE HALF-STATES THIS CLOSES
-- ─────────────────────────────────────────────────────────────────────────
-- services/stripe_checkout_credits.py was three unsynchronised round trips:
--
--     1. INSERT stripe_checkout_credit_grants   -- "claim" this session
--     2. read credits; write credits + N        -- the actual grant
--     3. DELETE the claim row, if step 2 failed -- compensation
--
--   A. MONEY TAKEN, NO CREDITS, RETRY SWALLOWED. Step 1 lands, the process
--      dies before step 2. The claim row now exists, so every Stripe retry —
--      and every manual student claim — takes the `if not claimed` branch and
--      returns 200 with duplicate=true, delta_applied=0. The user paid, got
--      nothing, and the system reports success. Permanently, and silently.
--      This is the worst failure available on this path.
--
--   B. LOST GRANT. Step 2 was read-modify-write over two HTTP calls with NO
--      compare-and-swap (unlike deduct_credits_strict, which has one). Two
--      concurrent grants both read credits=10 and both write 10+N, so one
--      payment evaporates. Not hypothetical: the Stripe webhook and the
--      student's own claim endpoint both call this, and a student clicking
--      "I paid" while the webhook lands is exactly that race.
--
--   C. COMPENSATION FAILS TOO. Step 3 is itself a network call with no
--      retry. If it fails, the state is identical to A.
--
-- One function = one transaction. The claim and the grant commit together or
-- not at all, so a crash leaves NOTHING — and the next Stripe retry re-grants
-- correctly, because the claim rolled back with it. That is the whole point:
-- the claim row stops meaning "someone started granting" and starts meaning
-- "the credits are in the balance".
--
-- ─────────────────────────────────────────────────────────────────────────
-- NO ROW LOCK, DELIBERATELY — unlike token_charge
-- ─────────────────────────────────────────────────────────────────────────
-- token_charge needs SELECT ... FOR UPDATE because it must READ the balance,
-- decide against it (sufficient? cap reached?), and only then write. This
-- function never decides against the balance — it adds a fixed amount — so
-- the whole grant is one `INSERT ... ON CONFLICT DO UPDATE SET credits =
-- credits + N` statement, which Postgres already makes atomic at row level.
-- A lock would be slower and buy nothing. Read-modify-write in the client was
-- the bug; a single self-referencing UPDATE is the fix.
--
-- Grants are additive and floor at 0, matching v2_increment_student_credits
-- exactly (negative deltas are allowed for corrections and cannot go below 0).
--
-- ─────────────────────────────────────────────────────────────────────────
-- SECURITY
-- ─────────────────────────────────────────────────────────────────────────
-- PostgREST publishes every public function at /rest/v1/rpc/<name> and
-- Postgres grants EXECUTE to PUBLIC by default, so an unrevoked function here
-- would let anyone with the browser bundle's anon key mint themselves credits.
-- SECURITY INVOKER (never DEFINER — that bypasses RLS for the CALLER), pinned
-- search_path, EXECUTE revoked from PUBLIC/anon/authenticated.
-- See docs/RLS-AUDIT.md § "The second door". CI enforces this
-- (test_migration_security_rules.py).
--
-- Idempotent: CREATE OR REPLACE + additive ALTERs. Backward compatible — the
-- application falls back to the legacy three-call path when the function is
-- absent (PGRST202), so merged-on-main and run-in-prod can happen either way
-- round. See services/stripe_checkout_credits.py.
--
-- Rollback (manual, never automatic):
--   DROP FUNCTION IF EXISTS public.stripe_checkout_grant_credits(text, text, integer, integer);
--   DROP FUNCTION IF EXISTS public.credits_increment(text, integer, integer);
--   (the two columns below are additive and safe to leave)

-- ── 1. Make the claim row a RECORD, not just a lock ──────────────────────
--
-- It previously held only the session id, so it could say "this session was
-- claimed" but never "…and here is who got how much". Now that the claim and
-- the grant commit together, these columns are a true audit trail: a row here
-- means those credits are in that balance.

ALTER TABLE public.stripe_checkout_credit_grants
    ADD COLUMN IF NOT EXISTS user_id         text,
    ADD COLUMN IF NOT EXISTS credits_granted integer;

COMMENT ON COLUMN public.stripe_checkout_credit_grants.user_id IS
    'Who was credited. NULL on rows written before add_stripe_credit_grant_rpc.sql.';
COMMENT ON COLUMN public.stripe_checkout_credit_grants.credits_granted IS
    'How many credits this session added. NULL on pre-RPC rows — and on those, '
    'the row only proves the grant was ATTEMPTED, not that it landed.';

-- ── 2. The atomic grant ──────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.stripe_checkout_grant_credits(
    p_checkout_session_id text,
    p_user_id             text,
    p_credits             integer,
    p_free_grant          integer DEFAULT 0
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $fn$
DECLARE
    v_claimed int;
    v_new     bigint;
    v_current bigint;
    v_uid     uuid;
BEGIN
    IF p_checkout_session_id IS NULL OR btrim(p_checkout_session_id) = ''
       OR p_user_id IS NULL OR btrim(p_user_id) = ''
       OR p_credits IS NULL THEN
        RETURN jsonb_build_object('ok', false, 'granted', false,
                                  'duplicate', false, 'credits', 0, 'delta', 0,
                                  'reason', 'invalid_input');
    END IF;

    -- ⚠️ v2_student_details.user_id is UUID (add_v2_student_details.sql), and
    -- PostgREST hands every JSON string in as TEXT. `uuid_col = text_param`
    -- has NO operator in Postgres and raises 42883 at RUNTIME — CREATE
    -- succeeds, the first call fails. That is exactly how token_charge
    -- (0241) shipped broken and sat inert in production behind a fallback
    -- that read the error as "function not installed"; see
    -- fix_token_charge_uuid_cast.sql. Cast ONCE, explicitly, here.
    --
    -- The cast is guarded rather than bare: a non-UUID user_id must degrade to
    -- "no such user", not abort a paid checkout with invalid_text_representation.
    BEGIN
        v_uid := p_user_id::uuid;
    EXCEPTION WHEN invalid_text_representation THEN
        RETURN jsonb_build_object('ok', false, 'granted', false,
                                  'duplicate', false, 'credits', 0, 'delta', 0,
                                  'reason', 'invalid_user_id');
    END;

    -- (1) Claim. ON CONFLICT DO NOTHING rather than a SELECT-then-INSERT: two
    -- concurrent calls for the same session both reach here, one inserts, the
    -- other BLOCKS on the unique index until the first commits and then sees
    -- the conflict. No window between checking and claiming.
    INSERT INTO public.stripe_checkout_credit_grants
        (checkout_session_id, user_id, credits_granted)
    VALUES (p_checkout_session_id, p_user_id, p_credits)
    ON CONFLICT (checkout_session_id) DO NOTHING;

    GET DIAGNOSTICS v_claimed = ROW_COUNT;

    IF v_claimed = 0 THEN
        -- Already granted. Report the CURRENT balance so the caller can still
        -- show the user their credits; grant nothing.
        SELECT credits INTO v_current
          FROM public.v2_student_details
         WHERE user_id = v_uid;
        RETURN jsonb_build_object(
            'ok', true, 'granted', false, 'duplicate', true,
            'credits', COALESCE(v_current, GREATEST(COALESCE(p_free_grant, 0), 0)),
            'delta', 0, 'reason', 'already_granted');
    END IF;

    -- (2) The grant itself, in ONE statement. `credits + N` reads and writes
    -- inside a single row-level-atomic UPDATE, so there is no window for a
    -- concurrent grant to overwrite — which is half-state B. Seeds from
    -- p_free_grant when the user has no credits value yet, matching
    -- v2_increment_student_credits's fallback so a first-ever purchase does
    -- not silently drop the free grant.
    --
    -- If this raises, the claim above rolls back with it: no claim row, so
    -- the next Stripe retry grants correctly instead of being swallowed.
    INSERT INTO public.v2_student_details (user_id, credits, updated_at)
    VALUES (v_uid,
            GREATEST(COALESCE(p_free_grant, 0) + p_credits, 0),
            now())
    ON CONFLICT (user_id) DO UPDATE
       SET credits = GREATEST(
               COALESCE(public.v2_student_details.credits,
                        GREATEST(COALESCE(p_free_grant, 0), 0)) + p_credits, 0),
           updated_at = now()
    RETURNING credits INTO v_new;

    RETURN jsonb_build_object('ok', true, 'granted', true, 'duplicate', false,
                              'credits', v_new, 'delta', p_credits,
                              'reason', '');
END;
$fn$;

COMMENT ON FUNCTION public.stripe_checkout_grant_credits(
    text, text, integer, integer) IS
    'Atomic Stripe credit grant: claims the checkout session and applies the '
    'credits in ONE transaction, so a crash can no longer take a payment and '
    'grant nothing while making every retry report "duplicate". Replaces the '
    'three-round-trip path in services/stripe_checkout_credits.py. '
    'SECURITY INVOKER; service_role only.';

-- ── 3. The shared primitive the other two callers need ───────────────────
--
-- routes/internal_webhooks.py (admin adjustment) and routes/v2/arcs.py (the
-- moments-unlock REFUND) both call v2_increment_student_credits, which is the
-- same read-modify-write with the same lost-update race. A dropped refund is
-- money too, so the same single-statement fix applies. Deliberately separate
-- from the Stripe function: no checkout session, no claim, nothing to
-- idempotency-guard — this one is repeatable by design.

CREATE OR REPLACE FUNCTION public.credits_increment(
    p_user_id    text,
    p_delta      integer,
    p_free_grant integer DEFAULT 0
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $fn$
DECLARE
    v_new bigint;
    v_uid uuid;
BEGIN
    IF p_user_id IS NULL OR btrim(p_user_id) = '' OR p_delta IS NULL THEN
        RETURN jsonb_build_object('ok', false, 'credits', 0,
                                  'reason', 'invalid_input');
    END IF;

    -- See the note in stripe_checkout_grant_credits: user_id is UUID, the
    -- caller sends TEXT, and uuid = text raises 42883 at runtime.
    BEGIN
        v_uid := p_user_id::uuid;
    EXCEPTION WHEN invalid_text_representation THEN
        RETURN jsonb_build_object('ok', false, 'credits', 0,
                                  'reason', 'invalid_user_id');
    END;

    INSERT INTO public.v2_student_details (user_id, credits, updated_at)
    VALUES (v_uid,
            GREATEST(COALESCE(p_free_grant, 0) + p_delta, 0),
            now())
    ON CONFLICT (user_id) DO UPDATE
       SET credits = GREATEST(
               COALESCE(public.v2_student_details.credits,
                        GREATEST(COALESCE(p_free_grant, 0), 0)) + p_delta, 0),
           updated_at = now()
    RETURNING credits INTO v_new;

    RETURN jsonb_build_object('ok', true, 'credits', v_new, 'reason', '');
END;
$fn$;

COMMENT ON FUNCTION public.credits_increment(text, integer, integer) IS
    'Atomic credit increment (floors at 0). Replaces the read-modify-write in '
    'services/db.v2_increment_student_credits, which could lose a concurrent '
    'grant or refund. SECURITY INVOKER; service_role only.';

-- ── 4. GRANTS — the door ─────────────────────────────────────────────────
--
-- Default EXECUTE on a new function goes to PUBLIC, and PostgREST publishes it.
-- Without this block, anyone holding the anon key could mint credits.
-- Roles are guarded: anon / authenticated / service_role exist on Supabase but
-- not on a bare Postgres, and a missing role must not abort the migration.

REVOKE ALL ON FUNCTION public.stripe_checkout_grant_credits(
    text, text, integer, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.credits_increment(
    text, integer, integer) FROM PUBLIC;

DO $$
DECLARE
    r     text;
    sig   text;
    sigs  text[] := ARRAY[
        'public.stripe_checkout_grant_credits(text, text, integer, integer)',
        'public.credits_increment(text, integer, integer)'
    ];
BEGIN
    FOREACH sig IN ARRAY sigs LOOP
        FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                EXECUTE format('REVOKE ALL ON FUNCTION %s FROM %I', sig, r);
                RAISE NOTICE '% : EXECUTE revoked from %', sig, r;
            END IF;
        END LOOP;

        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
            EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role', sig);
            RAISE NOTICE '% : EXECUTE granted to service_role', sig;
        END IF;
    END LOOP;
END $$;

-- ── VERIFY (read-only; run after) ────────────────────────────────────────
--
--   SELECT p.proname,
--          has_function_privilege('anon',          p.oid, 'EXECUTE') AS anon,
--          has_function_privilege('authenticated', p.oid, 'EXECUTE') AS authed,
--          has_function_privilege('service_role',  p.oid, 'EXECUTE') AS svc
--     FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
--    WHERE n.nspname = 'public'
--      AND p.proname IN ('stripe_checkout_grant_credits', 'credits_increment');
--
-- anon and authed must both be false; svc true. scripts/rls_guard.py checks
-- this on every deploy from now on.
