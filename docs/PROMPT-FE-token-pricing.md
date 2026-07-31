# FE handoff — token pricing (Phase 1)

Spec: [docs/PRICING-TOKENS-PLAN.md](PRICING-TOKENS-PLAN.md). BE contract:
[docs/PROMPT-BE-token-pricing.md](PROMPT-BE-token-pricing.md).

Everything here is behind `TOKEN_PRICING_ENABLED`. When it is off the BE reports every
action as free — the FE should then render **no balance UI at all**, not a zeroed one.

---

## 0. Two rules that override any design instinct

**The balance is a wallet, not a progress bar.** No streaks, no "you've earned", no
badge for spending little, no comparison to other users, no "efficiency". The moment
a number signals *how well you're doing* rather than *what you bought*, it is a
performance score and it breaks AC-9 — the hard fence this product is built around.
A monthly reset makes this tempting ("you used 80% of your month!"). Don't.

**Never explain a price with quality.** "This take costs 3,000" is fine. "This take
cost more because it ran long" is borderline — say it only as a duration band chosen
*before* recording. "This take cost more because…" anything about their delivery is
forbidden. Prices are flat and published; they never vary with performance.

**All copy in this feature is held for founder sign-off.** Ship the mechanics; leave
the words as placeholders and flag them.

---

## 1. The shipped contract

BE is live on `feat/token-pricing-be` (commit `ce729b2`). All four endpoints are
authed, read-only, and **none of them charge** — charging happens at the action being
paid for, so polling a balance can never cost the user anything.

**Flag off** (`TOKEN_PRICING_ENABLED=0`, the current state) every endpoint answers
`200 {"enabled": false}`. Deliberately not a 404: you need one probe that separates
"pricing is off, render no wallet UI at all" from "the backend is broken", and a 404
can't carry that difference. Check `enabled` first, always.

```jsonc
// GET /v2/tokens/balance
{ "enabled": true, "available": true,
  "balance": 41500, "tier": "starter",
  "period_start": "2026-07-28T09:00:00+00:00",
  "period_ends_at": "2026-08-28T09:00:00+00:00",
  "coach_reviews": { "used": 0, "allowed": 1, "remaining": 1 } }

// GET /v2/tokens/prices  — THE source of truth
{ "enabled": true, "price_version": "2026-07-28-v1",
  "actions": { "take_short": 1000, "take_medium": 3000, "take_long": 6000,
               "reread": 1500, "assembly": 500, "moment_explanation": 2500,
               "game": 1500, "insights": 1000, "chat": 150,
               "coach_review": 35000 },
  "bands":   [ { "max_seconds": 120, "action": "take_short",  "price": 1000 },
               { "max_seconds": 360, "action": "take_medium", "price": 3000 },
               { "max_seconds": 900, "action": "take_long",   "price": 6000 } ],
  "tiers":   { "free":    { "tokens_per_month": 12000,   "coach_reviews_per_month": 0,  "usd_per_month": 0 },
               "starter": { "tokens_per_month": 50000,   "coach_reviews_per_month": 1,  "usd_per_month": 5 },
               "pro":     { "tokens_per_month": 300000,  "coach_reviews_per_month": 6,  "usd_per_month": 25 },
               "max":     { "tokens_per_month": 1500000, "coach_reviews_per_month": 10, "usd_per_month": 100 } } }

// GET /v2/tokens/recording-band
{ "enabled": true, "can_record": true, "balance": 41500,
  "period_ends_at": "…", "max_seconds": 900, "action": "take_long", "price": 6000 }
// out of tokens:
{ "enabled": true, "can_record": false, "balance": 200, "period_ends_at": "…" }

// GET /v2/tokens/history?limit=50&before_id=123
{ "enabled": true, "next_before_id": 88,
  "entries": [ { "id": 91, "delta": -1000, "balance_after": 41500,
                 "action": "take_short", "ref_id": "rec_…", "tier": "starter",
                 "created_at": "…" } ] }
```

**`available: false`** on the balance endpoint means the account could not be read.
Treat it as "unknown", NOT as zero — render the previous value or nothing, and keep
every action enabled. Showing zero would hide the record button over a failed lookup.

**Never hardcode a price.** They get repriced once the cost measurements land — that
is the whole point of Phase 0 — and `price_version` is there so you can tell when a
cached list is stale.

### Buying a tier — `POST /v2/tokens/checkout`

```jsonc
// → {"tier": "pro"}            (optional: success_url, cancel_url)
// 200
{ "checkout_url": "https://checkout.stripe.com/…", "checkout_session_id": "cs_live_…", "tier": "pro" }
// 400 {"code":"INVALID_TIER"} · 500 {"code":"MISCONFIGURED"} · 502 · 503
```

Redirect the browser to `checkout_url`. **Do not use a Stripe Payment Link** —
`client_reference_id` never reaches the Subscription, so renewals would arrive
unattributable and grant nothing from month two. This endpoint writes the user id
onto the subscription itself, which is the only copy renewals carry.

Not gated on `TOKEN_PRICING_ENABLED` — the flag controls whether we *charge for
actions*; it must never stop someone paying us. Someone can subscribe while the
flag is off and their tokens simply sit unspent.

Tiers are `starter` · `pro` · `max`. `free` is not purchasable — it is the default
state, granted by the monthly roll.

### Charging responses you'll actually hit

`POST /v2/arc/<arc_id>/unlock-moments` now answers in tokens when the flag is on:

```jsonc
// 200
{ "unlocked": true, "arc_id": "…", "tokens_remaining": 39000 }
// 402
{ "code": "INSUFFICIENT_TOKENS", "required": 2500, "current": 300,
  "reason": "insufficient" }
```

`reason` is either `insufficient` (→ offer top-up **or** the renewal date) or
`coach_cap_reached` (→ offer **upgrade**, never top-up; see §5). Branch on it — they
need different actions, and getting it wrong sends someone to buy tokens that cannot
fix their problem.

Everything else — takes, chat, game, insights — charges **silently and fail-open**.
They never return a payment error, so you never need to handle one. Takes in
particular are charged *after* transcription at the band the audio actually landed
in, so an over-length or over-budget recording still produces a transcript.

## 2. The balance chip

Persistent, low-emphasis, in the header. Shows the number and — because everything
now resets monthly — **when it renews**: "41,500 · renews 28 Aug".

The renewal date is load-bearing copy, not decoration. Without it a user who watches
their balance fall has no idea it comes back, which reads as a countdown to being
locked out. With it, a low balance is "wait or top up", not "you are running out".

Tap → the wallet sheet (§4).

## 3. Price shown BEFORE the action, never after

Every metered action shows its cost on the trigger, before it fires:

- Record button: the band and its price, from `/v2/tokens/recording-band`
  (`{max_seconds, price}`). The recorder caps at `max_seconds`.
- Game / Insights / a key-moment explanation / the coach review: price on the button.
- Chat: **do not** price each message in the UI. 150 tokens is noise next to a 35,000
  coach review, and a per-keystroke price turns conversation into a taxi meter.
  It still charges; it just isn't surfaced per message.

**The recorder cap is advisory.** If a recording overruns, the BE accepts it anyway
and charges the higher band — never block or discard a recording client-side for
balance or length. Losing someone's take is worse than any billing inaccuracy.

## 4. Wallet sheet

Balance · tier · renewal date · coach reviews used/allowed · the price list
(from the BE) · ledger history from `/v2/tokens/history` (action, when, delta) ·
upgrade.

## 4b. ⚠️ Coach review has no trigger yet — do not build a button for it

The BE has the price (35,000) and the per-tier cap, but **no endpoint charges it**.
Today every take auto-sends to the coach; there is no "request a review" action, and
putting the existing auto-send behind a paywall is a product change awaiting founder
sign-off rather than an implementation detail.

So: show the allowance in the wallet (§5) because it is real and it resets, but do
**not** ship a "Request coach review" button until the trigger exists. Wiring one now
would 404.

## 5. Coach reviews are a separate counter

Show as "1 of 1 used this month", never converted to tokens. When exhausted, the
coach-review button is **unavailable with a renewal date**, not "buy more" — the cap
protects the founder's calendar and cannot be bought past.

This is the one place two limits can disagree: a Max user with 1.4M tokens and 10/10
reviews used sees plenty of balance and no review. Say why plainly ("your coach
reviews renew 28 Aug"), or it reads as a bug.

## 6. Low and empty

- **Low** (< ~2 takes): quiet chip state. No modal, no interstitial.
- **Empty**: the record button offers upgrade *or* the renewal date. Both, always —
  with a monthly reset, waiting is a legitimate choice and hiding it is a dark
  pattern.
- **Never** a full-screen block on a surface the user already paid for. Viewing your
  own transcript, replaying audio, editing your own text, and the strong-sides
  library are all unmetered and must stay reachable at zero balance.

## 7. Tiers

Free 12,000 · Starter $5 50,000 · Pro $25 300,000 · Max $100 1.5M — **all per month,
all resetting.** Coach reviews 0 / 1 / 6 / 10.

Present all four as monthly plans. Not "packs", not "credits", not "one-time" — the
allowance resets and the copy has to match, or the first reset feels like theft.

## 8. Checklist

- [ ] No token price hardcoded in the FE
- [ ] Renewal date wherever a balance appears
- [ ] Price on the trigger, before the action
- [ ] Recorder cap advisory; overruns still upload
- [ ] Coach reviews shown as a count, never as tokens, never purchasable past the cap
- [ ] Unmetered surfaces reachable at zero balance
- [ ] No streaks / efficiency / comparative framing anywhere (AC-9)
- [ ] Flag OFF → no balance UI at all
- [ ] All copy marked placeholder pending founder sign-off
