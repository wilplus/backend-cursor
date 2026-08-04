# Transactions — what is atomic, what is not, what to move next

Founder directive 2026-08-03: *"keep PostgREST for basic CRUD, but move
invariant-critical, multi-step writes into Postgres functions (`.rpc()`) —
eliminate these dangerous half-states so a server crash doesn't permanently
corrupt user data."*

This is the running record of that work. It starts with one path converted and
an honest list of the ones that are not.

## The shape of the problem

`services/db.py` is 15,700 lines and 458 methods, every query a fluent
`.table().select().eq()` chain over PostgREST with the service-role key. That is
a legitimate pattern for CRUD and it is not what needs changing.

What needs changing is that **PostgREST has no transaction across requests**.
Each `.execute()` is its own HTTP call and its own implicit transaction, so any
invariant spanning two of them is enforced by hope. The codebase is candid about
this — `grep -c "Atomic-ish\|Best-effort"` in `db.py` returns dozens — but
candour in a docstring is not a guarantee, and a documented half-state is still
a corrupted balance.

The escape hatch was used **zero** times before this change: no `.rpc()` calls,
no `CREATE FUNCTION` in any of the 130+ migration files.

## What is atomic now

### `token_charge()` — the token charge path ✅

`migrations/add_token_charge_rpc.sql` · `services/token_account.charge`

Chosen first because it is the money path that sits **on the F1 live loop**:
`services/lab_recording.py` charges the take from inside the
record→transcribe pipeline, and that pipeline retries by design.

It was four unsynchronised round trips — probe the ledger, debit the balance,
bump the coach counter, insert the ledger row — which produced three
half-states, all silent:

| # | Failure | Consequence |
|---|---|---|
| A | debit lands, ledger insert does not | The ledger is the idempotency record, so the next pipeline retry charges the same `recording_id` **again**. The balance is also short with nothing to explain it. |
| B | two concurrent charges for one ref | Both pass the probe, both debit. The partial unique index rejects the second *row* and the second *debit* stands — logged at INFO as "expected, not a fault". Balance and ledger disagree permanently. |
| C | debit lands, coach counter does not | A free coach review past a cap that is a fence, not a preference. |

All three are now impossible: one function, one transaction, with a
`SELECT ... FOR UPDATE` on the user's account row held across the probe, the cap
check, the balance check, the debit and the ledger insert. The row lock is what
kills B — the read cannot go stale between the check and the write — and it is
why there is no CAS retry loop anywhere in the function.

Rollout is order-independent. The application detects a missing function
(PostgREST `PGRST202`) and falls back to the legacy path, so *merged on main*
and *run in prod* can happen either way round without an outage. The negative
cache expires after 10 minutes, so applying the migration takes effect **without
a redeploy**.

One direction is deliberately not symmetric: a genuine RPC **error** does *not*
fall back. "The call failed" and "the call committed but the response was lost"
are indistinguishable from the client, so retrying through the legacy path could
replay a charge that already landed — the exact double-debit this removes. A
real failure fails open (fence §6.1: billing never fails a take) and stops.

Proven rather than asserted: `test_token_pricing.ChargeAtomicityTests`
reproduces each half-state on the legacy path, watches it corrupt the balance,
and then shows the atomic path refusing to produce it. The other 66 tests in
that file now run against the atomic path, since that is what production runs.

## What is NOT atomic yet

Ordered by what a failure actually costs. Nothing here is scheduled; this is the
map, not a plan.

1. **`ensure_period_current()` / `_seed()`** — `services/token_account.py`.
   The monthly roll SETs the balance and then writes the `period_grant` ledger
   row separately. A crash between them grants tokens with no record of the
   grant. Contained by the CAS on `period_start` and the ledger's unique index,
   so it cannot double-grant — it can only under-record. The obvious next one,
   and it shares a table with `token_charge` so it is a small addition.

2. **Stripe → credits** — `services/stripe_checkout_credits.py:234`.
   `stripe_checkout_grant_claim()` inserts an idempotency row, then
   `v2_increment_student_credits()` applies the credits, then a failure path
   *deletes* the claim row to allow a retry. A crash between the claim and the
   increment leaves money taken and no credits granted, with the claim row still
   present — so the retry is swallowed as a duplicate. This is real money and it
   is the one a user would actually complain about.

3. **`v2_increment_student_credits` / `v2_deduct_session_credits`** —
   `services/db.py:3121,3138`. Read-modify-write over two HTTP calls with **no**
   CAS: two concurrent charges both read `10`, both write `5`, and five credits
   vanish. `deduct_credits_strict` (line 11705) already does this correctly with
   a compare-and-swap and is the model — but the soft variants are what the
   `v2_charge_*_credits_once` helpers call.

4. **`v2_charge_*_credits_once`** — `services/db.py:3235,3271,3330`. Set the
   charged-at flag, then deduct, then clear the flag if the deduct failed. Three
   calls, and the compensating write can itself fail. Mitigated by flooring at 0
   and by being genuinely soft.

5. **Moments unlock** — `routes/v2_routes.py:11818`. Deduct, insert the unlock
   row, and on failure refund by calling the racy
   `v2_increment_student_credits` — so the compensation can silently lose the
   refund. The token-pricing branch above it already routes through
   `token_charge`; this is the legacy credits branch behind the flag.

6. **`replace_*` "atomic-ish" pairs** — `services/db.py:6626,6738`. DELETE then
   POST, with the half-state logged and a documented "the next GET re-POSTs"
   recovery. Not money; user content.

## Rules for the next one

* **`SECURITY INVOKER`, never `DEFINER`.** DEFINER runs as the owner and
  bypasses RLS for whoever called it — a leaked anon key becomes full write
  access even with grants locked down. The backend is already service-role, so
  INVOKER costs nothing.
* **`REVOKE ALL ... FROM PUBLIC, anon, authenticated`** in the same migration.
  New functions are granted to PUBLIC by default and PostgREST publishes them at
  `/rest/v1/rpc/<name>`. See `docs/RLS-AUDIT.md` § "The second door". CI enforces
  it (`test_migration_security_rules.py`) — and CI is genuinely the only guard:
  `ALTER DEFAULT PRIVILEGES` **cannot** revoke PUBLIC's built-in `EXECUTE` on
  future functions (measured on PG 16.13, four orderings, all ineffective), so
  there is no database-level backstop to fall back on if the REVOKE is
  forgotten.
* **Pin `SET search_path = public, pg_temp`** so a caller cannot shadow `public`
  and have the function resolve to tables they control.
* **Lock the row, don't CAS.** A `FOR UPDATE` at the top removes the retry loop
  and the whole class of check-then-write races along with it.
* **Never `ON CONFLICT DO NOTHING` on a ledger insert.** Swallowing the conflict
  reinstates the debit-with-no-record the function exists to prevent. Let it
  raise; the transaction takes the debit down with it.
* **Keep a fallback until the migration is confirmed live.** "On `main`" is not
  "run in prod" here — migrations are applied by hand.
* **Reproduce the half-state in a test before fixing it.** A guarantee nobody
  has watched fail is a comment.

## Migrations to run

Neither of these is applied yet. Both are idempotent, both run as a single
transaction in the Supabase SQL Editor, and running them together is fine:

```
migrations/add_token_charge_rpc.sql              -- the function + its grants
migrations/lock_down_public_function_grants.sql  -- the backstop sweep + defaults
```

Until they are, the application keeps using the legacy path — no behaviour
change, no outage, and the half-states above remain exactly as they are today.
