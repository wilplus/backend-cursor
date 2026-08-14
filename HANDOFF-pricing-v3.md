# HANDOFF — pricing v3 cutover (2026-08-14/15)

Status at handoff: **backend #440 merged and deployed; verification incomplete.**
Written for the next agent. Everything below is verified fact unless marked ❓.

---

## 1. What shipped

| PR | Repo | State |
|---|---|---|
| #298 | frontend | merged — four billing-surface defects |
| #299 | frontend | merged — out-of-tokens top-up card in the Lounge |
| #440 | backend | merged `bacabb7`, deployed, **unverified in the browser** |

### The ladder now sold

| key | display | $/mo | tokens | coach reviews |
|---|---|---|---|---|
| `free` | Free | 0 | 12,000 | 0 |
| `practice` | Practice | 12 | 150,000 | 0 |
| `coached` | **Coaching** | 39 | 150,000 | 3 |
| `intensive` | Intensive | 89 | 400,000 | 8 |

`starter`/`pro`/`max` are retired: absent from `SOLD_TIERS` (cannot be bought,
render no card) but still present in `TIERS` so a live subscriber's renewal
webhook resolves to something. **Not a grandfathering scheme** — no aliases, no
legacy cards, no special entitlement rules. Founder: if no legacy subscribers
remain, those three entries can be deleted outright (one line).

⚠️ **Display name ≠ tier key.** The founder rejected "Coached" as a label; the
Stripe product is named **Coaching**. The internal key stays `coached`
everywhere (tier table, migration, tests, Stripe metadata). Renaming the key is
a migration; renaming the label is a text edit. Do not "fix" the mismatch.

---

## 2. Stripe — done

Three recurring monthly USD Prices created and verified (`recurring`,
`interval: month`, `interval_count: 1`, `active: true`):

| price id | tier | $ |
|---|---|---|
| `price_1U4TyHCOBPOlZhfkAnj8ygFa` | practice | 12 |
| `price_1U4U1bCOBPOlZhfk53PXBNnx` | coached | 39 |
| `price_1U4U2fCOBPOlZhfkiOKnxYBg` | intensive | 89 |

`STRIPE_PRICE_TIER_JSON` was machine-merged (roundtrip-validated, 6 entries) and
set on **web** and **worker**. Boot logs clean — no `invalid JSON`, no
`must be an object`, no `unknown tier`. All six keys confirmed resolvable
against `TIERS` on the merged parser.

**Cron was correctly skipped.** The tier map is imported only by
`routes/internal_webhooks.py` and `routes/token_routes.py` — both web. Neither
the worker nor any of the four cron services (`annotation-export`, `devbugs`,
`drift`, `life-reminders`) reads it. Worker was set anyway as cheap insurance.
An earlier instruction to set it on "all three services" was a reflex
application of the CONFIG-FIRST rule, corrected after checking the importers.

---

## 3. ⛔ THE OPEN ITEM — pick up here

**The pricing page was last seen rendering the OLD ladder** (starter $5 / pro
$25 / max $100), after the merge.

What is established:
- Merge `bacabb7` committed **2026-08-14 23:14 UTC**
- Railway deployment `48b09bc4` went Active **2026-08-15 01:14 GMT+2 = 23:14 UTC**
- Same minute ⇒ the active deployment **is** the merge. Backend is on v3.
- `48b09bc4` is a Railway **deployment ID**, not a git SHA — it does not resolve
  in the repo. Do not try to `git log` it.

So the stale cards are ❓ most likely a client-side read: either the page was
loaded before the deploy finished, or the prices cache added in #298.

**Next action, in order:**

1. Hard-refresh the pricing page. Expect Free / Practice $12 / Coaching $39 /
   Intensive $89.
2. If still old: DevTools → Network → `prices` → Response → read
   `price_version`.
   - `2026-08-14-v3` → backend fine, **frontend misrenders** — real bug, dig in
     the FE.
   - `2026-08-01-v2` → something is serving old code despite an Active deploy.
3. Confirm migration `0274_add_pricing_v3_tiers.sql` applied — search the web
   service's **Deploy Logs** for `0274`. (Searching for `price_version` there is
   pointless; it is a response field, never logged.)
4. **Live purchase test.** Stripe test mode does not exercise the live webhook
   path, which is exactly where the tier map matters. Put a real card through on
   Practice and confirm the wallet reflects the grant.

Note: a sandboxed agent cannot curl the live site from this environment
(connection blocked, status 000). Steps 1–2 require the founder's browser.

Also unverified: the free-tier token count is **12,000 in both v2 and v3**, so
that line on the page is *not* a signal of which version is live. It was
initially misread as one.

---

## 4. Also open, not blocking

- **Token top-up products are recurring.** `1,500,000 tokens` / `300,000
  tokens` / `50,000 tokens` are all *Per month* subscriptions in the Stripe
  catalogue. The #299 bubble sells a **one-off** pack. ❓ If the bubble points at
  these price IDs, a user tapping a chip subscribes to monthly token delivery
  instead of buying once. **Verify which price IDs the bubble is wired to before
  it sees real traffic.** This is the highest-value unchecked item.
- **Archive the retired Stripe Prices** (old starter/pro/max) once §3 passes.
  Stops a stale link or old Payment Link opening a subscription on a retired
  tier; existing subscriptions keep renewing untouched.
- **Stripe account: "Action required — provide information to keep payouts
  enabled."** Payouts are held until cleared, regardless of product config.
- **Tax decision.** Products use the *Electronically Supplied Services* preset.
  ❓ Whether `Include tax in price` was set is unconfirmed. It must be identical
  across all three tiers or they price inconsistently at Checkout. At 23% PL
  VAT, exclusive means a $12 headline charges $14.76; inclusive means $12 in,
  ~$9.76 kept.
- **Stripe product descriptions deliberately omit token counts** (except
  Intensive's relative "larger allowance"), because a static Checkout string
  goes stale the moment a grant is tuned. Exact numbers live on the pricing
  page, which reads live. ❓ Confirm which wording was actually pasted for
  Practice — Intensive must match.

---

## 5. Constraints that shaped this work

- **CONFIG-FIRST** — env var on every service that *reads* it, before the merge,
  verified from **boot logs** not the Railway UI.
- **`MIGRATE_ON_BOOT=1`** — merging a migration runs it in prod at next
  container start, before the app process boots.
- **Actions is out of minutes** (runner-allocation outage: no job starts, no
  logs, 404 on download). Per the standing founder ruling, #440 merged on
  `scripts/local_ci.sh` evidence — **GREEN at `a99dac0`, 4,533 passed** — with
  the override documented in the squash commit. Do not "fix" the red X.
- **Deploy order** — frontend #298's dynamic tier ladder had to be live *before*
  #440, or the pricing page renders zero cards. It was.
- **AC-9 holds throughout**: no price is derived from user output; token counts
  are quantities of a purchased good, not scores or verdicts.

---

## 6. Environment note

This handoff was written from an isolated git worktree
(`.claude/worktrees/pricing-v3-verify`, branch `worktree-pricing-v3-verify`) to
avoid colliding with another agent working in the shared checkout. Nothing was
committed or pushed from it. The worktree can be removed once this file is
placed wherever it belongs.
