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

## 1. Get the numbers from the BE, always

`GET /v2/tokens/prices` is the source of truth. **Do not hardcode any token price in
the frontend** — they will be repriced once Phase 0's measurements land (that is the
entire point of Phase 0), and a hardcoded 3,000 becomes a lie silently.

`GET /v2/tokens/balance` returns:

```json
{ "balance": 41500, "tier": "starter", "period_ends_at": "2026-08-28T09:00:00Z",
  "coach_reviews": { "used": 0, "allowed": 1 } }
```

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
