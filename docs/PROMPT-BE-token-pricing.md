# BE handoff — token pricing (Phase 1)

Spec: [docs/PRICING-TOKENS-PLAN.md](PRICING-TOKENS-PLAN.md). Migration:
`migrations/add_token_pricing.sql`. Phase 0 (cost measurement) is already built —
commit `55e075e`, table `llm_usage`. **This is a different ledger. Do not join them.**

Everything ships behind `TOKEN_PRICING_ENABLED` (default **0**), unlike Phase 0's
default-on. Phase 0 only observed; this one can refuse a user's action.

---

## 0. The two things that must not break

**F-1 · The meter fails OPEN on the live loop.** A zero balance must never abort a
recording mid-upload, drop a transcript, or fail analysis. Gate at the **start** of
record; once audio is accepted the pipeline runs to completion and the balance floors
at zero. Precedent already in the codebase — `v2_charge_lab_credits_once` deducts
*softly* and `v2_deduct_session_credits` floors at 0. Keep exactly that behaviour.
A test must assert that a zero-balance user's upload still produces a transcript.

**F-2 · Prices are FLAT and published per action.** Never derived from what the call
actually cost, never varying with how the user performed. A quality-varying price is
an AC-9 score in billing clothes. `llm_usage` informs *our* price list between
releases; it must never be read at charge time. Pin with a test that no pricing module
imports `services.llm_usage` or `services.llm_pricing`.

---

## 1. Stripe: starter and pro become RECURRING

Founder 2026-07-28: everything resets monthly, free tier included. That decision
changes what $5 and $25 *are*.

A "pack" whose remainder is deleted after 30 days is not a pack. Sold as
"buy 50,000 tokens" and then zeroed, it is the shape of a chargeback. Sold as
"$5/month, 50,000 tokens a month", it is an ordinary subscription and reads honestly.

- Create **recurring monthly** Stripe Prices for starter ($5), pro ($25), max ($100).
- `STRIPE_CHECKOUT_PRICE_CREDITS_JSON` maps `price_id → amount` and works unchanged;
  add a parallel `STRIPE_PRICE_TIER_JSON` mapping `price_id → tier` so the webhook
  sets `tier`, not just a balance.
- On `customer.subscription.created|updated`: set `tier`, set `period_start` to the
  Stripe **billing anchor**, grant the tier's tokens, zero `coach_reviews_used`.
- On `customer.subscription.deleted`: set `tier='free'`. Do **not** claw back the
  current period — they paid for it. The downgrade takes effect at the next roll.

## 2. `ensure_period_current(user_id)` — the whole reset

Lazy, in the app, no cron. Called at the top of every balance read and every spend.

```
row = load(user_id)                       # seed to free/12000/now if NULL
elapsed = whole_months_between(row.period_start, now())
if elapsed < 1: return row

new_start = row.period_start + elapsed months     # JUMP, never loop-grant
UPDATE v2_student_details
   SET period_start = new_start,
       token_balance = grant_for(row.tier),        # SET, not +=. No rollover.
       coach_reviews_used = 0
 WHERE user_id = :u AND period_start = :observed   # CAS — one writer wins
```

Then append one `period_grant` row to `token_ledger`. If the CAS matched zero rows
another request already rolled it; re-read and carry on — not an error.

**Three traps.** (a) *Jump, never loop* — a user dormant four months gets one grant,
not four. (b) *SET, never add* — adding is rollover, which the founder explicitly
ruled out, and on Max it would let three quiet months bank 4.5M tokens. (c) The
`period_grant` ledger row must be idempotent per period — key `ref_id` on the period
start (`uq_token_ledger_once_per_ref` enforces it).

## 3. Charging

```
charge(user_id, action, ref_id=None) -> ok | insufficient
```

Prices from a **versioned dict in config**, never computed. `price_version` goes on
every ledger row so a repricing never re-interprets history.

| action | tokens | | action | tokens |
|---|---|---|---|---|
| `take_short` (<2 min) | 1,000 | | `moment_explanation` | 2,500 |
| `take_medium` (2–6) | 3,000 | | `game` (per arc) | 1,500 |
| `take_long` (6–15) | 6,000 | | `insights` (per arc) | 1,000 |
| `reread` | 1,500 | | `chat` | 150 |
| `assembly` | 500 | | **`coach_review`** | **35,000** |

Idempotency: per-arc items (`game`, `insights`, `coach_review`) pass `ref_id=arc_id`
so a re-open never double-charges — the partial unique index makes the second insert
fail, which the caller treats as "already paid", not an error. `chat` passes no
`ref_id` (legitimately repeatable).

## 4. Coach reviews — the second limit

`coach_reviews_used` is checked **independently** of the balance, and the tighter
limit binds. Free 0 · starter 1 · pro 6 · max 10 per period.

A Max user holding 1.5M tokens can still be out of reviews. That is the design, not a
bug: at 15 minutes of the founder's own time each, 1.5M tokens convertible into
reviews would be 43 hours. Reviews beyond the cap are **unavailable**, not
higher-priced — a price ladder on the founder's calendar is noise.

## 5. Record-start band (fail-open)

`GET /v2/tokens/recording-band` → `{max_seconds, action, price}` from the balance:
≥6,000 → 900s · ≥3,000 → 360s · ≥1,000 → 120s · below → `{can_record:false}`.

**Advisory only.** The upload endpoint accepts any duration and charges the band the
audio actually falls into. Never reject an upload for length or balance (F-1).

## 6. Endpoints

| method | path | notes |
|---|---|---|
| GET | `/v2/tokens/balance` | balance, tier, `period_ends_at`, reviews used/allowed |
| GET | `/v2/tokens/prices` | the price table — FE must never hardcode it |
| GET | `/v2/tokens/recording-band` | §5 |
| GET | `/v2/tokens/history` | paged ledger, newest first |

All call `ensure_period_current` first.

## 7. Tests that must exist

1. Zero balance still yields a transcript (F-1).
2. No pricing module imports the cost ledger (F-2).
3. Dormant four months → **one** grant, `period_start` advanced four months.
4. Concurrent reset → one `period_grant` row, not two.
5. Unused tokens do **not** carry across a roll.
6. `coach_reviews_used` does **not** carry across a roll.
7. Re-opening a paid arc does not double-charge.
8. `TOKEN_PRICING_ENABLED=0` → every action free, no ledger rows, no gate.

## 8. Open

- **Proration on mid-period upgrade.** Simplest defensible rule: upgrading sets the
  new tier's full grant immediately and re-anchors `period_start` to now. Slightly
  generous, trivially explainable. Confirm before building.
- **Refunds** are out of scope; Stripe handles money, this ledger handles tokens.
