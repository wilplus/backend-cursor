# willab token pricing — plan (no code)

Date: 2026-07-27 · Status: **ECONOMICS LOCKED, not built.** No code written.

**✅ Founder-approved 2026-07-27** — the whole shape is now decided:
- Peg **10,000 tokens = $1.00**; tiers **Free 12,000 · $5 = 50,000 · $25 = 300,000 (6×) · $100/mo = 1,500,000 (30×)**
- **Coach reviews capped 0 / 1 / 6 / 10 per tier** — a second counter, deliberately NOT scaled 30× (§5.1)
- **Key-moment explanations 5 credits ($5) → 2,500 tokens ($0.25)** (§2)
- Coach verify + key-moment comment are **ONE 35,000-token item** (one 15-min sitting)
- Take bands **<2 min = 1,000 · 2–6 min = 3,000 · 6–15 min = 6,000**; nothing published above 15 min

**Measured, not assumed (§8.1).** The longest take ever recorded is **5.3 min**; median is **50 s**;
**zero** takes have ever exceeded 6 min. Real cost is **≈$0.018/take** (~2.5× cheaper than first
modelled) and lifetime Whisper spend across the whole corpus is **$2.46**. Machine cost is not a
constraint — §5 (the founder's calendar) is the only real one.

- **EVERY tier renews monthly — free, $5, $25, $100 — and nothing rolls over** (founder 2026-07-28,
  supersedes "packs never expire"). Forces starter/pro to be Stripe SUBSCRIPTIONS, not packs (§9.6)

**Cost reality (§9):** analysis is the only line with a genuine ×7 (**$0.014** median take). Coach
comment writing costs **$0.00 machine** — `COACH_PREFILL_ENABLED` is OFF, the coach types it. Every
unlock costs **$0.00** — verified in the endpoints; they are pure DB reads of already-generated
content, so ×7 cannot apply to any of them. A complete $5 coached arc = **$0.083 machine + 15 founder
minutes** ⇒ **98.3% machine margin.** The founder's calendar is the entire cost structure.

**Still open:** only Phase 0 go/no-go (§7) — per-surface LLM spend remains un-instrumented. Full list §10.

⚠️ **All user-facing pricing copy remains held for founder sign-off** — approving the economics is
not approving the wording.

Replaces the current `credits` model (1 credit = $1, 25 free, only `MOMENTS_UNLOCK_CREDITS=5`
actually charges) with a Manus-style **upfront token grant → meter every action** model.

---

## 0. Decision filter

```
VERDICT:  JUSTIFIED-SCAFFOLDING (founder-directed)
CATEGORY: SCAFFOLDING
WHY:      Metering/monetization changes no per-slide transcription accuracy and no
          best-per-slide ranking. It touches the F1 surfaces only as a gate in front
          of them, which is precisely where it is dangerous:
            · LIVE LOOP — a meter that can abort record→transcribe→coach→read breaks
              the fence. Mitigation §6.1 (fail-open, gate at start not at completion).
            · AC-9 — a per-action price that VARIES with how the user performed is a
              surfaced score by the back door. Mitigation §6.2 (flat published prices).
            · BLIND COACH — the coach-comment unlock sells the coach's WRITTEN comment,
              never the blind labels. Mitigation §6.3.
          No L1/L2/L3 breach: nothing here changes what text is selected or how it ranks.
REDIRECT: This does not advance F1. The nearest F1-advancing work stays (1) word→slide
          bucketing at the two-clocks boundary. Ship pricing as its own gate-routed PR
          series, behind a flag, off the F1 critical path.
```

---

## 1. Every action that costs us model tokens

Measured from the code, not guessed. Model prices used: **gpt-4o-mini $0.15/1M in, $0.60/1M out ·
gpt-4o $2.50/1M in, $10/1M out · whisper-1 $0.006/min.**

### 1a. The per-take pipeline (fires on every recording)

`routes/v2_routes.py:14724 _run_analysis_pipeline` → `services/lab_recording.py:process_lab_recording`.
Sized for a **4-minute spoken take**, LLM budget `WILLAB_PIECE_LLM_BUDGET=16` pieces.

| # | Surface | File | Model | Calls | Est. cost |
|---|---|---|---|---|---|
| 1 | **Whisper transcription** (full take, verbose_json + word timings) | `openai_service.py:245` | whisper-1 | 1 | **$0.0240** |
| 2 | Say It Stronger (per budgeted piece) | `say_it_stronger.py:350` | 4o-mini | 16 | **$0.0122** |
| 3 | Moment / star suggestions | `moment_suggestions.py:92` | 4o-mini | ~8 | $0.0024 |
| 4 | Slide claim extraction | `slide_alignment.py:251` | 4o-mini | 1 | $0.0014 |
| 5 | Slide entailment (claim ledger) | `slide_alignment.py:314` | 4o-mini | 1 | $0.0014 |
| 6 | Snippet stickiness (batched) | `snippet_stickiness.py:173` | 4o-mini | 1–2 | $0.0013 |
| 7 | Structural-device star | `moment_suggestions.py:149` | 4o-mini | ~6 | $0.0009 |
| 8 | Ideal-text compose / polish | `best_presentation.py:196` | 4o-mini | 1 | $0.0008 |
| 9 | Delivery-alignment star | `delivery_alignment.py:130` | 4o-mini | ~6 | $0.0004 |
| 10 | Session cadence bubble | `session_cadence.py:294` | 4o-mini | 1 | $0.0004 |
| 11 | Master-doc chunking (**take 1 only**) | `master_document.py:100` | 4o-mini | 1 | $0.0016 |
| 12 | Coach-note draft (**flag OFF today**) | `coach_comment_drafter.py:136` | 4o-mini | 16 | +$0.010 |
| | | | | **≈ $0.046 / take** |

> ⚠️ **That $0.046 is a 4-minute take, which production data (§8.1) says is above the p99.** The real
> median take is **50 seconds**. Re-sized against actual usage: a median take costs **~$0.014**, a
> 2–6 min take **~$0.039**, and the usage-weighted average is **≈ $0.018/take** — about 2.5× cheaper
> than modelled. Total lifetime Whisper spend across the entire corpus is **$2.46**. The table below
> is kept as the *worst realistic case*; §2 prices off the weighted number.

Two facts that drive the whole design:

- **Whisper is 52% of a take.** It scales *linearly with duration* — a 20-min take is ~$0.14,
  a 45-min talk ~$0.29. Everything else is capped by the 16-piece budget and barely moves.
- **Say-It-Stronger is 27%** and is the only LLM line that would explode without the budget cap
  (a 60-min talk = ~270 pieces).

### 1b. Chat (the Lounge / master-doc RAG)

| Surface | File | Model | Per turn |
|---|---|---|---|
| Master-doc RAG answer (~7.5k-token system prompt + library + life context) | `master_doc_rag.py:1089` | 4o-mini | $0.0017 |
| Intent router | `master_doc_rag.py:854` | 4o-mini | $0.0002 |
| Goal-update intercept | `goal_update.py:109` | 4o-mini | $0.0002 |
| Audit-pointer line | `audit_intent.py:74` | 4o-mini | $0.0001 |
| Rolling conversation summary (every N turns) | `conversation_summary.py:191` | 4o-mini | ~$0.0003 amortized |
| | | | **≈ $0.002 / turn** |

The big cost here is the **inline master document — ~30k chars of string literals in
`master_doc_rag.py` ≈ 7.5k input tokens re-sent on every single turn.** Prompt-caching that
alone would cut chat cost ~50%.

### 1c. Everything else that burns tokens

| Surface | File | Model | Trigger |
|---|---|---|---|
| Snippet re-transcription on window edit | `snippet_transcription.py:58` | whisper-1 | admin/coach edits a piece boundary |
| Baseline summary | `baseline_summary.py:108` | 4o-mini | first-session baseline |
| Snippet drafts | `snippet_drafts.py:165` | 4o-mini | labeling flow |
| Session-level stickiness topics | `stickiness.py:211` | 4o-mini | session metrics |
| Next-session icebreaker | `next_session_icebreaker.py:382` | 4o-mini | end of session |
| Contextual follow-up | interview funnel | 4o-mini | onboarding interview |
| Onboarding opener | `onboarding_opener.py:223` | 4o-mini | signup |
| Coaching intro | `coaching_intro.py` | 4o-mini | post-labeling |
| Life Panel (4 generators) | `life_engine.py:318/464/618/698` | 4o-mini | Life Panel build/refresh |
| Legacy report/homework generators | `openai_service.py:375–1483` | 4o-mini / **4o** | legacy admin/copilot paths |

**Non-user, do not meter:** Community Content Studio (`community_content.py:365`, **gpt-4o**,
~$0.03/run, founder marketing), Dev Tasks (`dev_tasks.py:354`, **gpt-4o**, internal bug triage),
eval graders (`llm_config.SPEC_EVAL_GRADER`, gpt-4o, CI).

### 1d. Zero marginal model cost — verified

These are **fully deterministic** (grep confirms zero `chat_completions` calls):

- **The game** — `services/game_engine.py`
- **Insights payload** — `services/insights_payload.py`
- **The ideal-text report** — `services/ideal_text_report.py`
- Ranking / cross-take selection / power-phrase / challenge-threat — all code
- Key-moment *explanations* at unlock time: the text was **already generated during the take**
  (`moment_suggestions`). Unlocking costs us **$0.00** — today we charge $5 for it.

**The real cost that is not tokens at all: the coach's time.** The coach's key-moment comment and
the ideal-text verify are human labor and will dominate unit economics by 10–50×. §5 treats this
as the load-bearing number.

---

## 2. Every action a user can spend tokens on

The spend menu. Peg: **10,000 willab tokens = $1.00** (1 token = $0.0001).
Machine prices = measured cost **× 7**, rounded to a legible number.

**Revised 2026-07-27 after §8.1.** The original ladder opened at 3,000 for anything ≤6 min. Against a
50-second median that is a ~21× markup, not 7× — so the **<2 min band** was added. The three bands now
land at 7.1× / 6.9× / 7.0×, which is the rule you actually asked for rather than a rounding of it.

| Action | Where | Our cost | ×7 | **Price** |
|---|---|---|---|---|
| **Record a take** <2 min — *68% of all takes* | Lab record | $0.014 | $0.10 | **1,000** |
| **Record a take** 2–6 min | Lab record | $0.039 | $0.27 | **3,000** |
| **Record a take** 6–15 min — *never yet used* | Lab record | $0.10 | $0.70 | **6,000** |
| ~~15–30 min~~ / ~~30–60 min~~ | — | — | — | **not published — see §8** |
| Re-read a take (paired read) | Lab record | ~$0.02 | $0.14 | **1,500** |
| **Text assembly** (ideal-text compose / re-compose) | after each take | $0.001 | $0.007 | **500** |
| **Key-moment explanation** (per moment) | `/unlock-moments` | $0.00 | — | **2,500** ✅ |
| **The game** (per arc, unlimited replays) | `/explore/arc/<id>/game` | $0.00 | — | **1,500** |
| **Insights** (per arc) | `/explore/arc/<id>/feedback` | $0.00 | — | **1,000** |
| **Chat message** | `/v2/chat/query` | $0.002 | $0.014 | **150** |
| Say-It-Stronger card refresh | readout | $0.001 | $0.007 | **500** |
| Piece re-transcription (boundary edit) | coach/admin | $0.003 | $0.02 | **300** |
| Life Panel build / refresh | Life Panel | $0.008 | $0.06 | **800** |
| — **human item** — | | | | |
| **Coach review** (verify pass + key-moment comment — ONE sitting, ~15 min) | `/coach/arc/<id>/verify` + Insights unlock | 15 min founder time | — | **35,000** |

**One human item, not two** (revised 2026-07-27). The verify pass and the key-moment comment are a
single 15-minute sitting, so they are a single SKU. Selling them separately lets someone buy half a
pass and turns one block of the founder's calendar into two line items.

✅ **Key-moment explanations drop from 5 credits ($5) → 2,500 tokens ($0.25) — founder-approved
2026-07-27.** A 20× cut on today's only live paid item, and deliberate: under this model the *coach's*
review carries the price, not a card the pipeline already generated for free during the take.

Three consequences of that decision, none blocking:

- **`MOMENTS_UNLOCK_CREDITS=5` stops being a revenue line.** It becomes a friction-shaped item — cheap
  enough to feel free, priced enough that nobody unlocks all of them reflexively. Revenue expectation
  from it after this change: ~zero. That is the point.
- **No free-grant side-spend risk.** A user cannot unlock explanations without moments, and moments
  only exist after a take (`moment_suggestions.generate_for_session` runs inside the take pipeline).
  So the 12,000 grant cannot be burned on explanations without first spending 3,000 on a take — the
  ordering gate is structural, not a rule we have to enforce.
- **Existing `moment_unlocks` rows stay unlocked, never re-charged.** Anyone who already paid 5 credits
  keeps what they bought; the conversion in §4 (1 credit → 400 tokens) handles their residual balance.
  Volume is de minimis at this stage, so no grandfathering credit is proposed — flag if that's wrong.

**Never metered** (deliberate): viewing your own transcript, replaying audio, editing your own text,
the strong-sides library, the readout itself, sending a take to the coach.

---

## 3. The tiers

✅ **LOCKED — founder-approved 2026-07-27/28** (grant, ratios, coach caps).
**Every tier renews monthly, free included; nothing rolls over** (§9.6).

| Tier | Price | Tokens | $ / 1k | vs $5 | **Coach reviews** |
|---|---|---|---|---|---|
| **Free** (monthly grant) | $0 | **12,000/mo** | — | 0.24× | **0** |
| **Starter** (monthly) | **$5/mo** | **50,000** | $0.100 | 1× | **1** |
| **Pro** (monthly) | **$25/mo** | **300,000** | $0.083 | **6×** | **6** |
| **Max** (monthly) | **$100/mo** | **1,500,000** | $0.067 | **30×** | **10** |

Token ratios are exactly the founder's 1× / 6× / 30×; the per-token discount ladder (0 → 17% → 33%)
falls out of it for free. **The coach-review column deliberately does NOT follow that ladder** — it is
a separate hard allowance protecting the founder's calendar, sized in §5.1. Two independent limits,
and the tighter one binds: you can hold 1.5M tokens and still be out of coach reviews for the month.

### What each tier actually buys

**Free — 12,000.** The complete machine loop, once, with nothing withheld:

```
1 take (3,000) + assembly (500) + game (1,500) + insights (1,000)
+ 1 key-moment explanation (2,500) + ~23 chat turns (3,450)   = 11,950
```

They touch every feature — coach-verified text, insights, the game, chat, assembly — and run dry at
exactly the moment they want *takes 2 and 3 and the coach's read*. That is the intended cliff.
Costs us **~$0.10 per signup.** Dial range if it reads too generous/stingy: 8,000–15,000.

**Starter — $5 / 50,000.** One complete coached presentation, which is the founder's brief:

```
3 takes (9,000) + assembly (500) + game (1,500) + insights (1,000)
+ coach-verified text (12,000) + coach key-moment comment (25,000)
+ ~7 chat turns (1,050)                                        = 50,050
```

**Pro — $25 / 300,000.** ~6 coached presentations, or ~15 machine-only, or one 45-minute keynote
worked hard (4 long takes + heavy chat + the coach twice).

**Max — $100/mo / 1,500,000.** ~30 coached presentations a month. This is a team / agency / heavy
prep tier, and it is where §5's cap matters.

---

## 4. Migration off `credits`

- Current state: `WILLAB_FREE_CREDIT_GRANT=25`, `ARC_UNLOCK_CREDITS=25` (**retired**, `/unlock` → 410),
  `MOMENTS_UNLOCK_CREDITS=5` (the only live charge). Balances are effectively unspent.
- Keep the column, rename the concept. `token_balance` is a NEW additive column beside `credits`;
  the old one stays for at least a release — never drop (standing constraint). `credits` is still
  read by the moments-unlock path until that is cut over.
- `STRIPE_CHECKOUT_PRICE_CREDITS_JSON` already maps `price_id → integer amount` and works unchanged;
  §7 Phase 3 adds `STRIPE_PRICE_TIER_JSON` beside it so the webhook can set the tier.

**The 1-credit → 400-tokens conversion is now MOOT, and `add_token_pricing.sql` deliberately leaves
it commented out.** Once every tier renews monthly (§9.6), the migration seeds every existing user a
full free period — 12,000 tokens — immediately. Also converting their 25 legacy credits would grant
10,000 more on top, i.e. a double grant for the entire user base, for balances that were never spent
in the first place. The seed alone is more generous than the conversion was.

Uncomment the conversion block only if you decide legacy balances should be honoured **in addition
to** the first free period.

---

## 5. Coach economics — 15 min of the founder's own time (answered 2026-07-27)

**This is not a cash cost, so margin is never the problem.** $5 revenue against $0.16 of machine cost
is 96.8% gross margin and it stays that way at every tier. The scarce input is the founder's calendar.
That changes what the pricing has to protect.

### 5.1 The volume ladder was discounting the founder's own labor

At 15 min/arc, the effective hourly rate under the §3 ladder:

| Tier | Coach reviews if tokens spent on them | Founder hours | **$ / hour** |
|---|---|---|---|
| Starter $5 | 1 | 0.25 | **$20.00** |
| Pro $25 | 6 | 1.5 | **$16.67** |
| Max $100/mo | 30 | 7.5 | **$13.33** |

Backwards. The 1× / 6× / 30× discount is correct for machine tokens (97% margin — a discount costs
nothing) and wrong for human time (the only genuinely scarce input). Heavier users should pay **more**
per hour of the founder's time, not less.

**Fix: cap coach reviews per tier, independent of the token balance. ✅ Approved 2026-07-27.**

| Tier | Tokens | **Coach reviews included** | Founder hrs/mo | $ / hour |
|---|---|---|---|---|
| Free | 12,000 | **0** | 0 | — |
| Starter $5 | 50,000 | **1** | 0.25 | $20 |
| Pro $25 | 300,000 | **6** | 1.5 | $16.67 |
| Max $100/mo | 1,500,000 | **10** (not 30) | 2.5 | **$40** |

Implementation note: this is a **second counter, not a token price** — `coach_reviews_used_this_period`
against a per-tier allowance, reset with the billing period on Max and per-pack on Starter/Pro. The
35,000-token charge still applies on top; the cap is what stops 1.5M tokens from being convertible
into 43 hours of the founder's year.

Max keeps the 30× *token* multiplier — it becomes the machine-heavy tier (1.5M tokens ≈ 380 short
takes for someone prepping constantly) with a deliberately modest coach allowance. Reviews beyond the
cap are simply unavailable that month, not priced higher; a price ladder on the founder's own time is
noise the product doesn't need.

### 5.2 The real ceiling is hours, and it is low

| Founder coaching load | Arcs/month | Starter revenue ceiling |
|---|---|---|
| 5 hrs/week | ~87 | ~$435/mo |
| 10 hrs/week | ~173 | ~$865/mo |
| 20 hrs/week (full-time coaching, no building) | ~347 | ~$1,735/mo |

**The coached tier is not the business — it can't be, at 15 min a head.** The machine tiers are the
business, because they scale to zero marginal hours.

### 5.3 …which makes the coach review a data-acquisition line, not a cost line

Every coach review is exactly the corpus L3 calls for — the clone learns the **whole** coach review,
not just breakthrough detection. At $5 for 15 minutes, **the user is paying the founder to produce a
labeled training example.** That reframes the Starter tier: it is not a thin-margin service, it is
funded F2 data collection with a customer attached.

Two consequences:

- **If signups outrun the calendar, the lever is the cap and a queue — not the price.** A waitlist
  ("your review is queued, typically 2 days") beats raising the price, because at this stage the
  labeled example is worth more than the $5.
- The cap exists to protect the calendar, not the margin. Say so internally so it never gets
  "optimized" into a revenue lever.

---

## 6. Fence-safety rules (non-negotiable, these are why this can ship)

**6.1 The meter fails OPEN on the live loop.** A zero balance must never abort a recording mid-upload,
drop a transcript, or fail analysis. Gate at the **start** of record with a clear "this take costs
3,000" confirmation; once audio is accepted the pipeline runs to completion and the balance goes to
zero, never negative-blocking. Precedent already in the codebase: `v2_charge_lab_credits_once` deducts
*softly* and `v2_deduct_session_credits` floors at 0 — keep exactly that behavior.

**6.2 Prices are FLAT and published per action — never vary with how the user performed.** A price
that moves with quality is a surfaced score wearing a billing costume (AC-9). Duration *bands* are
fine — duration is not quality — but they must be coarse, fixed, and shown before the user records,
never computed after. No "this take cost more because…" copy, ever.

**6.3 The coach unlock sells the coach's written comment only.** Never the blind labels, never a
model guess presented as the coach's read (BLIND COACH).

**6.4 The balance is a wallet, not a progress bar.** No streaks, no "you've earned tokens", no
tokens-as-achievement. The moment a balance signals *how well you're doing* rather than *what you
bought*, it is a score.

**6.5 All user-facing pricing copy is held for founder sign-off** — standing rule.

---

## 7. Build order (each its own gate-routed PR, all behind `TOKEN_PRICING_ENABLED`)

**Phase 0 — measure before pricing. Do this first regardless of whether the rest ships.**
`services/llm.py:chat_complete` already logs `prompt_tokens` / `completion_tokens` per surface. Write
those to an `llm_usage` table (`user_id, surface, model, tokens_in, tokens_out, cost_usd, arc_id`) plus
one row per Whisper call. Two weeks of that and every multiplier above becomes measured instead of
estimated.

> ⚠️ **Prerequisite.** Not everything goes through the wrapper. `openai_service.py`, `master_doc_rag.py`,
> `life_engine.py`, `baseline_summary.py`, `snippet_drafts.py`, `coach_comment_drafter.py`,
> `stickiness.py` and `dev_tasks.py` call `client.chat.completions.create` **directly** and would be
> invisible to the meter. Route them through `chat_complete` (or a shared usage recorder) first —
> otherwise Phase 0 silently under-reports by roughly a third of the take pipeline.

**Phase 1 — ledger.** `token_balance` + append-only `token_ledger` (`user_id, delta, action, ref_id,
price_version, created_at`). Price table versioned in `config.py` so a repricing never rewrites history.

**Phase 2 — meter.** Wire the §2 table to the actions, fail-open per §6.1. Read-only "shadow mode"
first: log what *would* have been charged for a week, compare against real spend, then enforce.

**Phase 3 — Stripe.** Three **recurring monthly** prices — starter $5, pro $25, max $100 — since
every tier now renews (§9.6). `STRIPE_CHECKOUT_PRICE_CREDITS_JSON` still maps price → amount; add a
parallel `STRIPE_PRICE_TIER_JSON` mapping price → tier so the webhook sets the tier, not just a
balance. Anchor `period_start` to the Stripe billing date. Details in
[PROMPT-BE-token-pricing.md](PROMPT-BE-token-pricing.md) §1.

**Phase 4 — FE handoff.** Balance chip, price shown *before* each action, top-up sheet, low-balance
nudge. All copy held for sign-off.

**Cheap win, independent of all of the above:** prompt-cache the ~7.5k-token master document in
`master_doc_rag.py` and chat cost halves.

---

## 8. Recording length — ANSWERED FROM PRODUCTION DATA (2026-07-27)

### 8.1 The distribution

Pulled read-only from `recordings.duration` via the Supabase REST API, **whole history, not a
90-day window** (the corpus is small enough that the date filter only threw away signal).

```
recordings.duration — 446 rows (82 null duration)
band             takes     pct    avg_s    max_s   whisper$
a. <2 min          304   68.2%       44      119       1.34
b. 2-6 min          60   13.5%      186      318       1.11
c. 6-10 min          0    0.0%        -        -          -
d. 10-15 min         0    0.0%        -        -          -
e. 15-30 min         0    0.0%        -        -          -
f. 30 min+           0    0.0%        -        -          -

  median 50s (0.8m) · p90 167s (2.8m) · p99 300s (5.0m) · max 318s (5.3m)
  >=10 min: 0 (0.0%)   >=15 min: 0 (0.0%)
  total whisper spend in window: $2.46
```

`v2_sessions.presentation_duration_seconds` confirms it independently on a different table:
366 rows, median 61s, **max 201s**, zero takes at or above 6 minutes.

**The longest take ever recorded is 5.3 minutes.** Not one recording in the entire history reaches
6 minutes, let alone 10 or 30.

### 8.2 What this settles

**The length question is moot.** "Should we delete >10 min takes" has no subject — there are none to
delete. Publishing bands up to 15 min costs nothing because nothing lives up there. Keep the headroom;
it is free.

**The cost model was ~2.5× too pessimistic.** §1a was sized on a 4-minute take, which turns out to sit
above the p99. Re-derived against real usage:

| | median take (50s) | 2–6 min take (avg 186s) | **usage-weighted** |
|---|---|---|---|
| Whisper | $0.005 | $0.019 | |
| Say-It-Stronger (~4 vs ~15 pieces) | $0.004 | $0.014 | |
| Everything else (deck-level, ~flat) | $0.005 | $0.006 | |
| **Total** | **~$0.014** | **~$0.039** | **≈ $0.018 / take** |

Lifetime Whisper spend across the whole corpus: **$2.46.** Machine cost is not a constraint at this
scale and will not become one for a long time. Every economic question here reduces to §5 — the
founder's calendar.

**It broke the ×7 rule, which is why §2 changed.** A flat 3,000 for anything ≤6 min is ~21× the cost
of the take people actually record. The **<2 min band at 1,000 tokens** restores the intended
multiplier (7.1× / 6.9× / 7.0× across the three bands) and stretches the 12,000 free grant from ~4
short takes to ~8.

### 8.3 Correction to the previous recommendation

An earlier draft flagged `WILLAB_PIECE_LLM_BUDGET=16` duration-scaling as the one F1-touching item
worth shipping on its own, on the grounds that a 30-minute take gets LLM layers on only ~12% of its
pieces. **The data says this has never once happened.** At a 50-second median (~4 pieces) and a
5.3-minute maximum (~24 pieces), the budget of 16 delivers full or near-full coverage on every take
ever recorded. The ceiling is real but has never been touched — **de-prioritized**, not deleted. It
becomes live only if the 6–15 min band ever sees traffic.

### 8.4 Recommendation

1. **Publish bands <2 / 2–6 / 6–15 min.** The third is dead weight today and that's fine — it costs
   nothing and it means the first user who tries a conference-length talk isn't blocked.
2. **Do not publish 15–30 or 30–60.** No evidence anyone wants them, and §8.5's coverage ceiling
   would bite there for real.
3. **Still accept over-length uploads.** Fence §6.1 — never drop audio. Charge the top band, floor
   the balance at zero, log it. That log is how this question gets re-answered.
4. **Re-run §8.1 when the corpus is ~10× larger.** The query is in §8.6.

### 8.5 Honest caveat on the sample

446 recordings, largely founder + testers, on a product that presents itself as short-take-oriented.
This proves nobody **has** recorded a long take. It does not prove nobody **would** — there is an
obvious selection effect, and a 60-second median is at least partly the product teaching people what
a take is. That asymmetry is precisely why §8.4 keeps the 6–15 band open rather than hard-capping at
6 minutes: allowing headroom nobody uses is free, while removing headroom someone wanted is a lost
user we would never hear about.

### 8.6 Balance-driven length limits — the safe shape

Your instinct was right and it composes cleanly with the fences:

- The server issues a **recording band at record START** from the balance: ≥6,000 → 15-min recorder,
  ≥3,000 → 6-min, ≥1,000 → 2-min, <1,000 → recorder doesn't arm, offer top-up.
- **The band is advisory on the client; the upload is ALWAYS accepted.** Record 4 minutes on a 2-min
  band and we transcribe it and charge the 2–6 min price. Never abort mid-take, never drop audio
  (§6.1). The limit shapes the recorder UI; it never gates the pipeline.
- **AC-9 clean.** "Your balance covers a 2-minute take" is a wallet fact — it says nothing about how
  well they spoke. Contrast with anything shaped like "this take cost more because…", which is a
  score in billing clothes.

Side effect worth naming: a balance-driven length cap pushes users toward **short, repeated takes** —
exactly F1's best mode (full LLM coverage, three comparable takes to rank across). The pricing quietly
reinforces the product's strongest shape, and per §8.1 that is already what people do unprompted.

To re-run the distribution later, paste into the Supabase SQL Editor:

```sql
SELECT
  CASE
    WHEN duration IS NULL THEN 'unknown'
    WHEN duration <  120  THEN 'a. <2 min'
    WHEN duration <  360  THEN 'b. 2-6 min'
    WHEN duration <  600  THEN 'c. 6-10 min'
    WHEN duration <  900  THEN 'd. 10-15 min'
    WHEN duration < 1800  THEN 'e. 15-30 min'
    ELSE                       'f. 30 min+'
  END                                                AS band,
  COUNT(*)                                           AS takes,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct,
  ROUND(AVG(duration)::numeric, 0)                   AS avg_sec,
  ROUND(MAX(duration)::numeric, 0)                   AS max_sec,
  ROUND((SUM(duration) / 60.0 * 0.006)::numeric, 2)  AS whisper_usd
FROM public.recordings
GROUP BY 1
ORDER BY 1;
```

---

## 9. Real cost vs in-app cost, per action (2026-07-27)

"Real cost" = what we actually pay (OpenAI + founder minutes). "In-app cost" = the token price and
its dollar equivalent at the 10,000 = $1.00 peg.

### 9.1 The three actions asked about

| Action | What actually runs | **Real cost** | **In-app** | Multiple |
|---|---|---|---|---|
| **Analysis** (record a take) | Whisper + 8 LLM surfaces | **$0.014** (median 50 s take) · $0.039 (2–6 min) | 1,000 / 3,000 | **7.1× / 6.9×** |
| **Coach comment writing** | *nothing* — the coach types it | **$0.00 machine** + **~10 of the 15 founder-min** | folded into the 35,000 coach-review item | n/a |
| **Unlock coach-verified moments** | one `INSERT`, one balance decrement | **$0.00** — verified by code read | 2,500 (explanations) / 0 (verified text is free) | **∞** |

### 9.2 Analysis — the only line with a genuine ×7

Splitting the take pipeline into its two halves, because they behave completely differently:

| | median take (50 s) | 2–6 min take (186 s avg) | scaling |
|---|---|---|---|
| **Transcription** (whisper-1 @ $0.006/min) | $0.005 | $0.019 | **linear in duration** |
| **Analysis** (8 LLM surfaces, 4o-mini) | $0.009 | $0.020 | capped by `WILLAB_PIECE_LLM_BUDGET=16` |
| **Total** | **$0.014** | **$0.039** | |

Analysis breaks down as: Say-It-Stronger (~$0.001/piece × pieces) · slide claims + entailment
(~$0.003, per-deck so effectively flat) · stickiness batch ($0.0007) · moment + structural + delivery
stars (~$0.003) · ideal-text compose ($0.0008) · cadence ($0.0004).

The important asymmetry: **transcription grows without limit, analysis does not.** At 5 minutes they
are roughly equal; past ~10 minutes Whisper dominates and analysis flattens out — which is the same
budget ceiling §8.3 describes, seen from the cost side.

### 9.3 Coach comment writing — $0.00 machine, and that is deliberate

`COACH_PREFILL_ENABLED` defaults to **"0"** (`lab_recording.py:246`). The AI-Commentator draft is
**off in production**, so writing a coach comment today costs us **nothing in tokens** — the coach
types it from scratch and the system learns from that (founder 2026-07-14).

If prefill were switched on, `coach_comment_drafter.py` would fire one gpt-4o-mini call per budgeted
piece (`_MAX_TOKENS = 320`, ≤16 pieces) ≈ **+$0.010 per take** — a ~70% increase on median-take
analysis cost, and still economically irrelevant. **The reason to leave it off is corpus purity, not
money**: a pre-filled draft contaminates the very signal L3 wants (what the coach writes *unprompted*).
Do not let a future cost review "optimize" this back on.

So the real cost of a coach comment is **founder minutes** — roughly 10 of the 15 per arc, the other
~5 being the verify pass. Both are inside the single 35,000-token coach-review item; they are not
separately priced because they are not separately performed (§2).

### 9.4 Unlocks cost us exactly nothing — every one of them

Verified by reading the endpoints, not assumed:

- **`POST /v2/arc/<id>/unlock-moments`** (`v2_routes.py:11674`) — `deduct_credits_strict` then
  `insert_moment_unlock`. **Zero LLM calls.** The explanation text was generated during the take by
  `moment_suggestions` and is already sitting in the database.
- **`POST /v2/coach/arc/<id>/verify`** (`v2_routes.py:12437`) — stamps who/when, snapshots the served
  text, fires the notification bubble. **Zero LLM calls.** The student GET then serves the verified
  text **free**, with no payment gate.

**Consequence worth stating plainly: no unlock in this product has a marginal cost, so the ×7 rule
cannot apply to any of them.** Unlock prices are pure value-pricing. That is not a flaw — it is why
key-moment explanations could drop from $5 to $0.25 without touching margin at all (§2), and it is
why the 35,000-token coach review is priced against *the founder's calendar* rather than against any
cost line (§5).

### 9.5 The whole picture, one table

Median take, one complete coached arc (3 takes + everything):

| Line | Real cost | In-app | Notes |
|---|---|---|---|
| 3 × analysis (median takes) | $0.042 | 3,000 | the only real machine cost |
| Text assembly | $0.001 | 500 | fires after every take |
| The game | **$0.00** | 1,500 | `game_engine.py` — fully deterministic |
| Insights | **$0.00** | 1,000 | `insights_payload.py` — fully deterministic |
| Key-moment explanations (say 3) | **$0.00** | 7,500 | generated during the take |
| ~20 chat turns | $0.040 | 3,000 | ~7.5k of the input is the master doc, every turn |
| **Coach review** (verify + comment) | **$0.00 machine · 15 founder-min** | **35,000** | the actual product |
| **Total** | **≈ $0.083 machine + 15 min** | **51,500 ≈ $5.15** | |

**Machine gross margin on a $5 arc: 98.3%.** The founder's 15 minutes is the entire cost structure.
Everything in §5 follows from that one line, and nothing in §1, §8 or this section changes it.

### 9.6 Renewal — EVERYTHING resets monthly (founder 2026-07-28)

**Supersedes the 2026-07-27 "no expiry on packs" decision.** One cycle for every tier,
free included. Nothing rolls over.

| Tier | Tokens / month | Coach reviews / month | Rollover |
|---|---|---|---|
| Free | 12,000 | 0 | none |
| Starter $5 | 50,000 | 1 | none |
| Pro $25 | 300,000 | 6 | none |
| Max $100 | 1,500,000 | 10 | none |

A single reset cycle is much simpler than the two-model version it replaces — one
`period_start` per user, one grant rule, no distinction between "pack" and
"subscription" balances. `migrations/add_token_pricing.sql` is built on that.

**⚠️ The one thing this forces: starter and pro are now SUBSCRIPTIONS, not packs.**
An allowance whose remainder is deleted after 30 days is not a pack. Sold as "buy
50,000 tokens" and then zeroed it is the shape of a chargeback; sold as "$5/month,
50,000 tokens a month" it is an ordinary plan that reads honestly. The Stripe Prices
for starter and pro must be **recurring**, and every surface must say *per month*. If
the founder wants them to stay one-off purchases, then they must NOT reset — the two
cannot both be true.

**The free tier resetting is a real product change, not a detail.** 12,000 tokens
every month forever is a permanently-free user running roughly one take a month, at
~$0.10/month to us — trivially affordable. But it removes the exhaustion cliff the
earlier design leaned on. Conversion pressure now comes from *impatience* and *coach
access*, not from running out permanently: a free user who is happy at one take a
month simply never converts.

That is a defensible trade at this stage and probably the right one — a returning free
user is corpus, and corpus is what F2's clone needs. It should be a chosen trade
rather than a discovered one. If conversion later looks too weak, the lever is the
free grant size (8,000 makes one take feel tight; 12,000 makes it comfortable), not
re-introducing expiry.

**Coach reviews still must not roll over** — the §5.1 reason is unchanged and now
applies uniformly. Three quiet months banking 30 reviews would be 7.5 hours of the
founder's time callable in a single week, which is exactly what the cap exists to
prevent.

**Unused tokens vanish at the roll.** Standard for a subscription, and worth saying
out loud because the earlier draft recommended a one-month carry on Max. That carry is
now dropped: with every tier on the same cycle, a single "nothing rolls over" rule is
easier to explain than a per-tier exception, and the machine capacity it forgoes costs
us ~nothing either way.

**No cron.** The reset is computed lazily on read (`ensure_period_current`), never by
a scheduled job — see the reasoning in `migrations/add_token_pricing.sql`. A monthly
grant cron fails silently and this repo has a standing habit of infrastructure that
was specified and never wired.
---

## 10. Open questions for the founder

1. ~~Coach cost per arc~~ — **answered: 15 min, founder's own time.** §5 rewritten.
2. ~~Key-moment explanations → 2,500 tokens ($0.25)~~ — **approved 2026-07-27.**
3. ~~Coach reviews capped 1 / 6 / 10 by tier~~ — **approved 2026-07-27.**
4. ~~Free grant 12,000~~ — **approved 2026-07-27.**
5. ~~Published length ladder stops at 15 min~~ — **settled by data 2026-07-27** (§8.1: max take ever
   = 5.3 min, zero above 6). Bands <2 / 2–6 / 6–15 published; nothing above.
6. ~~Add a <2 min band~~ — **approved 2026-07-27** at 1,000 tokens; restores the ×7 rule the flat
   3,000 band was breaking (§8.2).
7. ~~Scale `WILLAB_PIECE_LLM_BUDGET` with take duration~~ — **de-prioritized by data** (§8.3). The
   12%-coverage failure mode has never occurred; 16 pieces covers every take ever recorded. Revisit
   only if the 6–15 min band sees traffic.

**Genuinely still open:**

8. ~~Do $5/$25 packs expire?~~ — **superseded 2026-07-28: EVERY tier renews monthly, free included,
   nothing rolls over** (§9.6). Forces starter/pro to be sold as subscriptions rather than packs.
9. ~~Phase 0 go/no-go~~ — **approved and BUILT 2026-07-28**, commit `55e075e`
   (`feat/llm-usage-instrumentation`, unpushed). ⚠️ run `migrations/add_llm_usage.sql`.

**Genuinely still open:**

10. **Confirm starter/pro become recurring Stripe Prices.** The alternative is that they stay one-off
    and do NOT reset — those two cannot both be true (§9.6).
11. **Proration on a mid-period upgrade.** Proposed: full new-tier grant immediately, re-anchor
    `period_start` to now. Slightly generous, trivially explainable.
12. **Phase 1 go/no-go** — the balance itself. Migration written
    (`migrations/add_token_pricing.sql`), handoffs written
    ([BE](PROMPT-BE-token-pricing.md) · [FE](PROMPT-FE-token-pricing.md)), nothing built.
