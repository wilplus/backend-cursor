# BE → FE: the legacy credits are settled. The balance has two halves now.

**Date:** 2026-08-01 · **Answers:** decision 5 of the 2026-07-31 FE handoff
**Founder decision:** honour at 1,600 tokens/credit, above the free 25, as non-expiring tokens.

---

## The short version

Your instinct to **hide the credits row while pricing is on** was right, and it can now come
down for good: the credits are converted, not hidden. What replaces it is one new fact about
the balance you already render.

**`balance` has not changed meaning.** It is still "what you can spend right now", so nothing
you have shipped needs to change to keep working. What is new is that part of it may not expire.

```jsonc
// GET /v2/tokens/balance
{
  "balance": 700000,          // total spendable — unchanged meaning
  "monthly_balance": 12000,   // resets at period_ends_at
  "bonus_balance": 688000,    // honoured legacy credits — NEVER resets
  "period_ends_at": "2026-08-31T...",
  ...
}
```

## The one thing you must not do

**Do not render `period_ends_at` against `balance`.** It applies to `monthly_balance` alone.

A user with 700,000 tokens shown under "renews 31 August" reads as *"688,000 of these disappear
in three weeks"* — which is false, and is exactly the kind of thing someone acts on. If you show
a renewal date at all, show it against the monthly half.

Suggested shape, not prescriptive:

> **700,000 tokens** — 12,000 this month, renewing 31 August, plus 688,000 that don't expire.

When `bonus_balance` is `0` — which is the case for almost everyone, see below — collapse it and
render exactly what you render today. No new empty state.

## Who actually has one

Almost nobody, by design. The conversion pays on credits **above the free 25**, and every
account was seeded 25 free (plus a 2026-07-13 bump that lifted everyone to at least 25). So:

| holder | bonus |
|---|---|
| a normal account (25 credits) | **0** — renders exactly as today |
| the founder (455 credits) | 688,000 |
| anyone who topped up beyond the free grant | `(credits − 25) × 1600` |

The floor exists because nothing in the schema separates a *purchased* credit from a *granted*
one — the Stripe grants table stores only a session id, with no user and no amount. Without the
floor, every account that ever signed up would have received 40,000 non-expiring tokens, 3.3×
the entire free monthly tier, whether or not it ever paid. So treat `bonus_balance > 0` as the
rare case and make sure the common path is untouched.

## Spending order, in case you ever surface it

**Monthly allowance first, bonus second.** The expiring money is always spent before the
permanent money — the other order would quietly burn someone's honoured credits while their
monthly allowance evaporated unused at the roll.

You should not need to explain this. If you ever do, that sentence is the whole rule.

## Fences

Nothing here changes what you were already holding:

- **No performance framing.** `bonus_balance` is a quantity someone owns, not a measure of how
  they are doing. Do not derive a "you've used X%" from the split — that is the AC-9 fence, and
  a two-part balance makes it more tempting, not less.
- **Never gate a recording.** Unchanged: `charge()` still fails open, and the bonus only ever
  makes a balance larger, never smaller.
- **Monthly plans, never packs.** The bonus is a one-time honouring of a retired currency, not a
  purchasable top-up. There is no way to buy more of it and there should be no copy implying
  there is.

## What the ledger shows

One row per converted user, `action: "legacy_credit_conversion"`, positive delta. It appears in
`/v2/tokens/history` like any other movement, so the honouring is visible to the user rather
than a number that silently appeared.

## Ops

`migrations/add_legacy_credit_conversion.sql` — run by hand, and it contains a **preview query
that grants nothing**; run that first to see the real totals. Until it runs, `bonus_balance`
reads `0` for everyone and the wallet behaves exactly as it does today, so a deploy landing
first degrades rather than breaks.
