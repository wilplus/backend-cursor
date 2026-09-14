# BE → FE: the plans are sellable. Answers, and two bugs you did not ask about.

**Date:** 2026-07-31 · **Answers:** FE handoff "the plans are published, priced, and unsellable"
**Status:** built, tested, on `claude/plan-checkout-endpoints-z1f08m`. One migration to run.

---

## The short version

1. **Subscription checkout already exists** — `POST /v2/tokens/checkout`, `mode="subscription"`.
   It landed in #302 under a title about foreign Stripe events, which is why your grep for
   `mode="subscription"` came back empty: you checked before it merged. Nothing lives outside
   the app. **Take the honest note down.**
2. **`plan` is now on `/v2/tokens/balance`** — `managed`, `status`, `cancel_at_period_end`,
   `current_period_end`, `manage_available`. That is the upgrade-vs-manage signal you asked for.
3. **Downgrade above the new cap: the balance is kept, untouched, for the period they paid for.**
   Nothing is ever truncated mid-period. Copy sentence at §3.
4. Two real bugs were sitting on this path. Both are fixed and pinned by test. §6.

---

## 1. Start a plan change — `POST /v2/tokens/checkout`

Your proposed `/v2/tokens/subscribe` is the same endpoint under a different name; the built one
is `/v2/tokens/checkout`. Shape differs slightly from your proposal — redirect to `checkout_url`:

```jsonc
// POST /v2/tokens/checkout   { "tier": "starter"|"pro"|"max",
//                              "success_url"?, "cancel_url"? }
// 200
{ "checkout_url": "https://checkout.stripe.com/c/pay/...",
  "checkout_session_id": "cs_live_...",
  "tier": "pro" }
```

Errors, all with a `code` you can branch on:

| status | code | what to render |
|---|---|---|
| 400 | `INVALID_TIER` | not purchasable (includes `free` — it is the default state, not a product) |
| 409 | `ALREADY_ON_TIER` | they are already on it. Say so calmly, do nothing |
| 409 | `MANAGE_EXISTING` | they have a **different** live subscription → send them to the portal |
| 500 | `MISCONFIGURED` | no Stripe price mapped to that tier. Ours to fix, not theirs |
| 502 | `STRIPE_API_ERROR` | Stripe was unreachable. Retryable |
| 503 | `DISABLED` | Stripe not configured in this environment |

`MANAGE_EXISTING` is the one worth handling properly. Stripe will happily open a **second**
subscription for someone who already has one and bill both, monthly, until a human notices.
A Starter → Pro move is a *switch*, and a switch happens in the portal.

**Not gated on `TOKEN_PRICING_ENABLED`.** The flag governs whether we charge for actions; it must
never be the reason someone cannot pay us, or cannot cancel.

## 2. Manage an existing plan — `POST /v2/tokens/portal`

```jsonc
// POST /v2/tokens/portal   { "return_url"? }
// 200
{ "portal_url": "https://billing.stripe.com/p/session/..." }
// 404 { "code": "NO_SUBSCRIPTION" }   ← nothing to manage; render upgrade instead
```

Cancellation, tier switching and card changes all live in there, so neither side has to build
them. Everything done in the portal comes back to us as a subscription webhook.

### Why `manage_url` is *not* a field on `/v2/tokens/balance`

You asked for it inline. It cannot go there, for two reasons that both bite in production:

- **Portal sessions expire.** A URL minted into a balance payload you render once and keep is a
  dead link by the time anyone clicks it.
- **It would put a synchronous Stripe call inside the most-read endpoint in the wallet.** A
  Stripe blip would then read to the user as *"your balance is unavailable"*. The balance path
  goes to real lengths to stay readable when things around it fail; spending that on a
  convenience is a bad trade.

So the balance carries a **boolean** you render the button from, and the URL is minted on the
click — the same shape checkout already uses.

```jsonc
// added to GET /v2/tokens/balance
"plan": {
  "tier": "pro",
  "managed": true,                 // live Stripe subscription → show "manage"
                                   // false → show "upgrade" (today's behaviour)
  "status": "active",              // active | trialing | past_due | canceled | ...
  "cancel_at_period_end": false,
  "current_period_end": "2026-08-31T00:00:00+00:00",  // the date they lose it
  "manage_available": true         // POST /v2/tokens/portal will open something
}
```

Two details worth reading:

- **`past_due` counts as `managed`.** The card failed, the subscription still exists, and the
  portal is exactly where it gets fixed. Showing "upgrade" to that user would sell them a second
  subscription to solve a billing problem.
- **`managed: false` with `manage_available: true`** = they cancelled and it has lapsed. They can
  still reach their invoices; they are not on a plan.

Before `migrations/add_subscription_state.sql` runs, `plan` reads `managed: false` for everyone
and the balance is otherwise unaffected — i.e. exactly today's upgrade-only behaviour, never a
broken wallet.

---

## 3. Your decisions, answered

### 1. Mid-period upgrade → the new allowance lands **immediately**, in full

Not pro-rated. Starter with 5,000 left who upgrades to Pro has 300,000 within a webhook of
paying. Slightly generous, and the reason to prefer it is exactly your reason for asking:
you have to say it *before* checkout, and "your new monthly tokens are available right away"
is a sentence that stays true. Stripe still pro-rates the *money*; only the tokens are simple.

The renewal date re-anchors to the Stripe billing date, so the card charge and the token
re-grant land on the same day. That was already true and it is why `period_ends_at` is
trustworthy.

### 2. Downgrade → takes effect at the next renewal. **The balance above the new cap is kept.**

> **Max with 1.4M tokens drops to Starter (50k): what happens to the 1.35M?**
> **Nothing. They keep it until the period they already paid for ends.**

Never truncated mid-period, in any direction. The smaller grant lands by itself at the next
roll, and that is not a special rule invented for downgrades — it is the rule the whole model
already runs on for everybody: *nothing rolls over, every period SETS the new allowance.*

That is what makes it defensible. The user is not being punished for downgrading; they are
hitting the same monthly reset that a user who never touched their plan hits. Copy you can hold:

> You'll stay on Max until 31 August, with the tokens you have. From 1 September you're on
> Starter, with 50,000 tokens a month.

The same rule covers **cancellation** (decision 3): the tier drops to free, the balance is
untouched, and the free grant arrives at the next roll. `plan.current_period_end` is the date to
show. This is the behaviour the code always *claimed* — see §6.

### 4. Coach reviews on a tier change → the used-count **carries**; it resets only when the period rolls

An upgrade may raise the cap; it may not refund reviews already taken. One used on Starter
becomes **1 of 6** on Pro, not 0 of 6. `coach_reviews` on the balance already gives you
`{used, allowed, remaining}` and `allowed` moves with the tier, so nothing changes for you.

Anything else makes upgrade-and-downgrade an unlimited coach-review loop, and the cap exists to
protect the founder's calendar rather than the margin.

### 5. Legacy credits → founder's call, and **the rate written in the plan is wrong by about 4×**

Not implemented; this one is real money and it is not the backend's to decide. But the arithmetic
should be on the table before anyone picks a number, because the two available anchors disagree
badly:

| basis | rate | founder's 455 credits become |
|---|---|---|
| `PRICING-TOKENS-PLAN.md` §4, as written | 400 tokens / credit | 182,000 tokens |
| **what a credit actually bought** | **~1,600 tokens / credit** | **728,000 tokens** |

The second row is derived from this product's own prices: an arc unlock cost `ARC_UNLOCK_CREDITS`
= 25 credits, and the same four deliverables priced in tokens come to 40,000
(`insights` 1,000 + `game` 1,500 + `moment_explanation` 2,500 + `coach_review` 35,000). So
25 credits ≙ 40,000 tokens. The 400:1 rate in the plan quietly writes off three quarters of what
people paid for, at a $1-per-credit peg they were sold on.

**Recommendation: honour them at arc-equivalence (1,600:1), once, as a one-time ledger credit.**
It is the only rate the product's own price list supports, it is auditable (one `admin_adjust`
row per user), and it is a defensible answer if anyone ever asks why their balance changed.

Two implementation notes for whoever runs it: the conversion in
`migrations/add_token_pricing.sql` §4 is **deliberately not run** — the Phase 1 seed already
gave everyone a full free period, so running it as-is double-grants — and it should write ledger
rows rather than bump `token_balance` directly, so the credit is visible in the history you
already render. **Your decision to hide the credits row while pricing is on stays right until
this is settled.** Hidden is not resolved, but a balance that buys nothing should not sit next
to one that buys everything.

---

## 4. Your fences — held, and where

| your fence | where it is enforced |
|---|---|
| No performance framing near billing | `plan` carries dates and what-was-bought only. Pinned by `test_balance_carries_plan_and_no_usage_framing`, which fails the build if a key like `percent_used` or `streak` ever appears |
| Monthly plans, never packs | All three tiers are recurring Stripe Prices; `prices` serves `tokens_per_month` / `usd_per_month`. Unchanged |
| Never gate a recording on billing | Untouched. No pre-flight check was added anywhere on the record path; `charge()` still fails open and floors at zero |
| Coach reviews stay a count and unpurchasable | Strengthened — see §6, this was leaking |
| Prices stay served | `price_version` unchanged (`2026-07-28-v1`). No number in the price table moved |

---

## 5. What to run before this is live

```
migrations/add_subscription_state.sql     # additive, idempotent, safe to re-run
```

Five nullable columns on `v2_student_details` plus two indexes. Nothing else changes. Until it
runs, `plan.managed` is `false` for everyone and the wallet behaves exactly as it does today —
the columns are read in their own best-effort query precisely so a deploy that lands first
degrades instead of breaking.

No new environment variables. `STRIPE_PRICE_TIER_JSON` must map all three tiers, which it already
does; the same map serves checkout and the webhook, so a price we can sell is always a price we
can recognise on renewal.

---

## 6. Two bugs found on this path, both worse than the missing endpoint

Neither was in your handoff. Both were live.

**A cancelling user was losing tokens they had paid for.** `set_tier` wrote
`token_balance = grant_for(tier)` unconditionally, so `customer.subscription.deleted` set a Pro
user with 250,000 tokens left to 12,000 on the spot — directly under a comment reading
*"No claw-back: they paid for this period."* The test named
`test_cancellation_drops_to_free_without_clawback_of_the_paid_period` asserted only the tier
string and never the balance, so it passed throughout. It now asserts the balance.

**The coach-review cap could be cleared for free.** `set_tier` also wrote
`coach_reviews_used = 0` on every subscription event — and `customer.subscription.updated` fires
for card changes, cancel-toggles and metadata edits, not just renewals. So anyone could reset
the founder's calendar cap, mid-period, by toggling something in the billing portal. The same
path re-granted a full month of tokens for updating a card.

The fix in both cases is that **the billing anchor decides, not the event**:

| what moved | what happens |
|---|---|
| the billing anchor (a genuine new period) | SET the grant, zero the coach counter — same as the monthly roll |
| the tier only (mid-period change) | balance = `max(current, new grant)`, coach counter **carries** |
| neither (card update, cancel-toggle) | **nothing moves at all** |

The `max()` is what makes upgrades immediate and downgrades harmless in one line, and it is why
§3's answers are the same answer wearing two hats.

One sharp edge worth naming, because it nearly re-opened the fence: anchors are compared with a
60-second tolerance, not `==`. Stripe sends whole seconds, we store microseconds, and both round
trip through ISO text — exact equality reported "different period" for two anchors that are the
same instant, which meant re-grant and reset. Periods are a month apart, so the tolerance cannot
mask a real renewal, and ambiguity now fails toward granting nothing.
