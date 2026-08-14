# HANDOFF — WillpowerLab, 2026-08-14

The state-of-the-world for a maintainer picking this project up cold.
This is the SYSTEM-LEVEL handoff (both repos); the frontend half lives in
`frontend-cursor/docs/HANDOFF.md`. It is an index — it points into the
canonical docs rather than duplicating them.

**Before any work: read [`CLAUDE.md`](../CLAUDE.md).** It is the operating
doctrine — the north star (F1/F2), the locked choices (L1–L3), the fences
(AC-9, CONSTRUCT, BLIND COACH, LIVE LOOP, NORTH-STAR LOCK), and the
WILLAB DECISION FILTER that gates every task. `AGENTS.md` at the repo
root is a pointer to it for non-Claude agent harnesses. The frontend repo
carries an identical filter copy on purpose — divergence is itself drift.

## The product in one paragraph

**F1 (the MVP, deterministic):** voice → perfect per-slide transcript
(every word bucketed to the slide on screen when it was spoken) → across
takes, rank + select the best version of each slide (verbatim take +
light continuity polish, blended `power_score` ranking) → the user's best
speech. **F2 (the overlay):** find where the voice sounds ASSURED — the
`confidence` construct (SPEC §17, `conf-q-v1`) — rated blind by humans,
shadow-learned toward the coach-clone. Everything else is scaffolding.
Full construct registry: `docs/SPEC.md` §17. Decisions newer than SPEC:
`docs/SPEC-DECISIONS-LOG.md`. The charisma construct was **retired by
founder re-lock 2026-08-13** — never reintroduce it; a CI probe and
`_CONSTRUCT_RE` guard the copy.

## Repos, runtime, deploy

- **backend-cursor** — Flask + Supabase (Postgres, RLS) on **Railway**.
  Processes: web (`bin/railway-web.sh`), worker
  (`bin/railway-worker.sh`), and cron services (annotation-export,
  devbugs, drift, life-reminders — `bin/railway-*-cron.sh`,
  `Dockerfile.*-cron`, `Procfile`).
- **⚠️ `MIGRATE_ON_BOOT=1` on the web service: merging a migration IS
  running it in prod at the next container start.** Manifest:
  `migrations/manifest.txt` (contiguous numbering, currently through
  0272; house gates: idempotent SQL, RLS on every new public table).
  Read `docs/MIGRATIONS.md` and the CONFIG-FIRST rule in `CLAUDE.md`
  before touching any of it. Railway env vars are per-service — a writer
  service missing a variable fails silently; verify from boot logs, not
  the UI.
- **frontend-cursor** — Next.js (App Router) at willpowerlab.com. The
  browser reaches the backend ONLY through the BFF routes
  (`src/app/api/v2/*`); backend secrets (e.g.
  `PIPELINE_JOBS_SWEEP_SECRET`) never reach the client. Hosting is
  configured outside the repo — confirm platform access at handoff.
- **Audio**: Cloudflare R2 + Worker; `services/audio_ref_resolver.py` is
  the one home for turning stored refs into playable URLs.
- **Errors**: Sentry (`sentry_sdk`) across routes. **Secrets/staging**:
  `docs/OPS-SECRETS-AND-STAGING.md`. **Engine map** (which service does
  what): `docs/ENGINE-MAP.md`. **Queues/pipeline runbook**:
  `docs/OPS-PIPELINE-QUEUE-RUNBOOK.md`.
- **dev.willpowerlab.com is deliberately ISOLATED** from production
  jobs, workers, Redis, cron schedules, and sweep secrets (founder
  standing rule). Keep it that way.

## How to ship

Branch off freshly-fetched `origin/main` → PR → CI green → squash-merge.
Never break the live record→transcribe→coach→read loop; never auto-drop
tables/columns.

**The GitHub Actions caveat (standing since 2026-08-11):** this repo is
private and its CI minutes come from the account allowance. When the
allowance runs out mid-month, every run fails at RUNNER ALLOCATION — two
red X's in 2–3 s, `runner_id: 0`, logs 404 because the job never
started. That is a billing stop, not a code failure; re-running cannot
help. Founder ruling: **do not upgrade** — merge on local evidence and
document the override in the squash commit. The evidence is
`scripts/local_ci.sh` (rebuilds the `checks` job: python 3.12 venv,
pinned ruff/mypy, the job's steps in order; `test_local_ci_mirror.py`
fails if script and workflow drift). An ad-hoc `pytest && ruff && mypy`
is NOT the gate. Suite size at handoff: **4,476 passing** in the gate
tier.

**Data mutations are not migrations.** Anything that edits rows the
founder owns (e.g. `admin_users`) is run by the founder in the Supabase
console, never smuggled through `MIGRATE_ON_BOOT`.

## Current state (2026-08-14)

- **Open PRs: ZERO in both repos.** #389 (label-quorum ledger) was
  closed unmerged 2026-08-14 with full rationale in its closing comment;
  its branch `claude/voice-game-quorum-rules-96w9hw` is intact.
- Tier 3 is closed: **Voice Album** (three-way entry rule, mirror
  semantics, presentation-order read), **Confident Voice** (deterministic
  founder-signed card, 0-cost, feeds the album), coach tagging, and the
  admin/legacy cleanup (admin access = artur@willonski.com only;
  `/admin/tokens` is the sole admin page; the legacy credits route and
  four dead credit helpers are deleted).
- The §11 chunk-grain system (cap-at-builder, nested scroll, screen
  grain, optimistic lock, binary deck upload) and all three §12
  integrity rules (anchor-first compose, clean-serve fold parity,
  intent-keyed ledger) are shipped — see
  `docs/SPEC-parts-locking-and-layers.md`.
- Game queue voice-source order shipped (own voice → consented app
  users → YouTube corpus, `services/game_engine.py`).
- **In flight (the founder's own action): the end-to-end production
  reality test** — record → capped chunks → Confident Voice card → user
  lock → coach publish → album entry. A strict build freeze holds until
  that report, except work the founder explicitly orders.

## Parked work (spec exists; build not ordered — with preconditions)

1. **The Verbal lane** — fully specced as `lexical-dilution-v1` in
   `docs/SPEC.md` §17 (text-only weak-phrasing detector, one LLM rewrite
   call, founder-signed card copy, inside the ≤3 budget, token-priced).
   **Build explicitly waits for the founder's production reality test.**
   The entry pins its fences: never feeds confidence (D19), versioned
   immutable lexicon, ratio never surfaces.
2. **§12.2 follow-on** — move accent/bold markers fully out of served
   text into metadata (the serve boundary is currently clean via the
   fold; the metadata migration is the durable form).
3. **PR #389 substance** (strict 2-human quorum resolver, self-report
   stamping, machine-proposal-beside-answer). Revival preconditions are
   in its closing comment: renumber the migration, re-point
   charisma→confidence, rebase onto the shipped queue order, and get the
   founder's ruling on the IDK mapping.
4. **Game-queue multi-source ingestion** — the consent surface and
   corpus attachment that make the three-class queue order load-bearing
   beyond own-voice arcs. Product context exists; not a build order.
5. **FE**: §11.5/§11.6 modal auto-open + smart re-triggering policy;
   e2e `continue-on-error` flip (see the FE HANDOFF).

## Standing data-safety rules (founder — non-negotiable)

- **Filler/detector data is versioned and immutable.** Detections feed
  cross-database comparisons; lexicons, thresholds, labels, and
  historical calculations are never silently overwritten — a change is a
  new version, and backfills validate on a copy first.
- Coach labels stay blind (BLIND COACH); no scores/verdicts/numbers ever
  surface to users (AC-9); user-facing copy ships only with founder
  sign-off (LIVE LOOP).
- `admin_users` changes: founder console only.

## Billing & pricing (as-built, audited 2026-08-14)

**Tokens are the only currency; subscriptions are the only purchase.**
The legacy credits system is retired (the old $25 "unlock the audit"
Lounge bubble and the `arc_checkout` chat chip are deleted; the chat has
NO pricing surface by design). There is **no token top-up product** —
the only buy is a monthly Stripe subscription.

- **Tiers** — `services/token_prices.py` (single source of truth):
  free 12,000 tokens / $0 · starter 50,000 / $5 · pro 300,000 / $25 ·
  max 1,500,000 / $100 per month. Balance is SET at the monthly roll
  (no rollover, lazy reset in `token_account.py::ensure_period_current`
  — no cron); admin grants land in `bonus_balance`, which never
  expires. Spend order: monthly first, then bonus.
- **Live charge points** (`PRICE_VERSION = "2026-08-01-v2"`; machine
  prices = measured cost × 7): takes 1,000/3,000/6,000 by length ·
  reread 1,500 · moment_explanation 2,500 (**the only hard 402 in the
  product**) · insights 1,000 · game 1,500 · chat 150 (charged, not
  shown, by design) · coach_feedback 35,000 at publish. All charges are
  SOFT except moment_explanation: balance floors at zero, actions never
  break. Recording is never blocked (`/v2/tokens/recording-band` is
  advisory; unreadable balance fails OPEN). Per-arc idempotency via the
  `token_ledger` unique index — re-opens are free.
- **Wallet/ledger**: `services/token_account.py` (accounts on
  `v2_student_details`, audit trail in `token_ledger`, atomic charge
  RPC with legacy fallback). Master flag `TOKEN_PRICING_ENABLED` — ON
  in prod (web + worker) since 2026-08-12.
- **Purchase flow**: hamburger → Tokens → `/dashboard/pricing` →
  `POST /v2/tokens/checkout` → Stripe subscription checkout → webhook
  `/v2/internal/stripe/webhook` → `set_tier` (price→tier mapping is
  env-only: `STRIPE_PRICE_TIER_JSON`; no price IDs in code). Downgrades
  never claw back.
- **Admin**: `/admin/tokens` (FE, AdminGate) + `routes/v2/admin_tokens.py`
  — lookup by email, bonus grants (±, ceiling 10M, required ref_id). No
  tier changes or refunds from there.

**Known gaps (found in the 2026-08-14 audit — reported, deliberately
not changed during the freeze):**

1. Five priced actions are never charged anywhere (`assembly`,
   `say_it_stronger`, `piece_retranscribe`, `life_panel`,
   `coach_review`) yet all render in the wallet's "What things cost"
   list. In particular `coach_review` 35,000 is the sole member of
   `COACH_ACTIONS`, so the per-tier coach-review allowance (0/1/6/30)
   is never consumed by anything.
2. `POST /v2/tokens/portal` (Stripe billing portal) exists on the BE
   but has no FE caller — the wallet tells users to email support; the
   FE comment claiming the route doesn't exist is stale.
3. Two live 402 bodies (`MOMENTS_LOCKED` in `routes/v2/arcs.py` and
   `routes/v2/explore_ideal_text.py`) and the 410 unlock tombstone
   still say `price_credits: 5` / "5 credits" while the real charge is
   2,500 tokens. No FE reads those fields today, but the copy is wrong.
4. `GET /v2/session/status` still seeds 25 legacy credits to any
   untouched account (`v2_ensure_credits_initialized`) and returns a
   `credits` field + `audit_price`; the credits column and 12
   credits-era migrations remain by the never-auto-drop rule. The
   Stripe credits webhook arm self-disables while
   `STRIPE_CHECKOUT_PRICE_CREDITS_JSON` is unset — do not set it.
5. Migration comment drift: `add_token_pricing.sql` documents max-tier
   coach reviews as 10; code says 30 (inert while gap 1 stands).
6. Legacy credit conversion (`max(0, credits − 25) × 1,600` into
   bonus_balance, stamp `legacy-credits-1600-v1`) remains available.

Historical plan docs (intent — the code above is the truth):
`docs/PRICING-TOKENS-PLAN.md`, `docs/PROMPT-BE-token-pricing.md`,
`docs/PROMPT-FE-token-pricing.md`.

## LLM providers (relevant to any tooling/provider migration)

**The product already runs entirely on OpenAI.** Transcription is
Whisper (`model="whisper-1"`, `services/openai_service.py`); generation
is `gpt-4o-mini` (default) / `gpt-4o` (graders, judges) via
`services/llm_config.py`; the only pinned SDK is `openai` in
`requirements.txt`. There is no Anthropic/other-provider code path in
the product. Internal LLM cost attribution (`services/llm_pricing.py`,
`services/llm_usage.py`) is deliberately never read at charge time —
user prices are flat published numbers (a cost-derived price would vary
with user performance, which is an AC-9 score in billing clothes).

## Maintainer quick-start checklist

- [ ] Access secured: GitHub (both repos), Railway (all services + env
      vars), Supabase (DB + SQL console), Cloudflare (R2 + Worker),
      Sentry, FE hosting/domain, LLM provider keys.
- [ ] Read: `CLAUDE.md` (both repos) → this doc → `docs/MIGRATIONS.md` →
      `docs/ENGINE-MAP.md` → the OPS runbooks.
- [ ] Run `scripts/local_ci.sh` to GREEN locally before any merge.
- [ ] Before trusting a red CI X: check whether Actions minutes are
      exhausted (runner-allocation failure pattern above).
- [ ] Never merge a migration without the CONFIG-FIRST check.
