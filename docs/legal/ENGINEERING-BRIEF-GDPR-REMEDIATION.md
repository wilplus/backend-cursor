# Engineering brief — GDPR remediation

**Hand this to the engineer verbatim.** Origin: `docs/legal/DPIA-2026-09-17.md`.
Five work packages, ordered. WP0 is a 10-minute query that rescales everything else.

```
FILTER: JUSTIFIED-SCAFFOLDING — cat {SCAFFOLDING} — fences {clear: no surfaced
copy changed in code; copy held separately for founder sign-off} — locks {clear:
L1/L2/L3 untouched} — redirect: named unblocker of in-flight L-1/L-3/L-4/L-5/L-9.
Lawfulness of the recording path is a live-loop risk (R2 carve-out), not a refactor.
```

**House rules:** branch off `origin/main`; PR → CI green → squash-merge.
`MIGRATE_ON_BOOT=1` in prod, so **merging a migration runs it**. Migrations
idempotent (`IF NOT EXISTS`). CONFIG-FIRST: any env var a migration depends on is
set on **every** Railway service (web, worker, cron) **before** merge, verified
from the **boot log**, not the dashboard. Gate is `scripts/local_ci.sh`.

---

## WP0 — Answer three questions before writing code ⏱ 10 min 🔴

Every severity score in the DPIA assumes the active user base is very small. Confirm it.

```sql
-- 1. How many real users, and how many accepted the bundled consent?
SELECT COUNT(*) AS total_users FROM user_settings;

-- `terms_version`, NOT `consent_policy_version`. user_consents holds
-- id, user_id, terms_accepted_at, terms_version, ip_address, user_agent,
-- created_at, organization_id (add_user_consents_table.sql:13-22,
-- add_foundation_discriminators.sql:105-111). `consent_policy_version` is an
-- MLC-2 foundation column (add_mlc2_foundation.sql:231) and naming it here
-- fails with "column does not exist" before returning a row.
--
-- terms_accepted_at and created_at are separate columns and may disagree;
-- both are reported so a discrepancy is visible rather than averaged away.
SELECT terms_version, COUNT(*) AS acceptances, COUNT(DISTINCT user_id) AS users,
       MIN(terms_accepted_at) AS first_accepted,
       MAX(terms_accepted_at) AS last_accepted,
       MIN(created_at) AS first_row, MAX(created_at) AS last_row
FROM user_consents GROUP BY 1 ORDER BY 2 DESC;

-- 2. How much audio is actually retained, and how far back?
SELECT COUNT(*) AS takes, MIN(created_at) AS oldest
FROM coaching_attempts;

-- 3. How many users have a voice_confidence value persisted?
SELECT COUNT(DISTINCT user_id) FROM intervention_decisions;
```

```bash
# 4. Is the inference actually running in prod? Boot log, NOT the dashboard.
#    Unset => ON: `os.getenv("VOICE_CONFIDENCE_ENABLED") or "1"` in enabled(),
#    services/voice_confidence.py:256 (def at :252). The RANKING flag is the
#    other one and defaults OFF: ranking_enabled(), :248 (def at :243).
railway logs --service web    | grep -i VOICE_CONFIDENCE
railway logs --service worker | grep -i VOICE_CONFIDENCE
```

**Report all four back before starting WP1.** If total_users is in the low tens,
this is pre-launch hygiene. If it is in the thousands, the sequencing changes and
counsel should be told immediately.

---

## WP1 — Split the consent 🔴 ~1-2 days

Closes DPIA RISK-1 and backlog L-1. **The highest-exposure item.** The current
bundled consent is assessed as invalid under Art 4(11)/7(4) + Recital 43; if it is
invalid it fails for *both* purposes, including the recording itself, for which
Privacy v1.2 §3 expressly declined Art 6(1)(b).

**Spec:** `legal/mlc2-split-consent-v2.json` (drafted; DRAFT status, do not activate
until founder adopts and copy v1.3 ships).

1. **Migration** — `add_model_improvement_consent.sql`, idempotent:
   - `user_settings.model_improvement_consent BOOLEAN NOT NULL DEFAULT FALSE`
   - `user_settings.model_improvement_consent_at TIMESTAMPTZ NULL`
   - **Default FALSE is the whole point.** Nobody is opted in by a migration.
   - Existing `user_consents` rows for `mlc2-bundled-consent-v1` stay as an audit
     record. They do **not** migrate into the new flag — that consent is assessed
     as never validly given for training.

2. **Filter every training/corpus/dataset read path** on the flag. Start from
   `services/training_import.py`, `services/confidence_dataset.py`,
   `services/ml_finetuning_export.py`, `services/annotation_export.py`, and any
   `training_labels` reader. **A missed path is the bug that matters here** — an
   Art 21 objection has to be honourable inside Art 12(3)'s one month, and today
   it is a manual hunt.

3. **Re-base recording/coaching on Art 6(1)(b).** The consent record for the
   coaching grant becomes an acknowledgement, not a permission.

4. **Two independent UI controls** (FE). Neither pre-ticked. Refusing model
   improvement must not block, degrade, delay or re-prompt. Withdrawal in
   Account → Data & consent must be the same number of clicks as granting (Art 7(3)).

5. **Test** that a user with `model_improvement_consent = FALSE` appears in **zero**
   training/export paths. Make this a real test, not a smoke test.

---

## WP2 — Account deletion + data export 🔴 ~2-3 days

Closes DPIA RISK-4, backlog L-3/L-4, **and is a hard dependency of WP3.**

Note: `/v2/processing-authorization/data-export` exports **authorisation
evidence**, not the subject's personal data. It does **not** discharge Art 15 or 20.
Do not extend it — build alongside.

- `GET /v2/account/export` → structured machine-readable archive (Art 15 + 20):
  account, takes, transcripts, Ideal Text versions, derived measurements, ratings
  given, consent history. JSON, plus audio either inline or as signed URLs.
- `DELETE /v2/account` → hard delete across **~69 tables plus R2 objects**.
  - Must include R2. Orphaned audio after a deletion request is the worst outcome.
  - Preserve what law requires (billing → Polish accounting/tax) and say so in the
    response.
  - Anonymise rather than delete where a row is load-bearing for another subject's
    data — peer ratings *given* by this user are also data about the rater, but
    they are attached to someone else's extract. Sever the link; keep the judgement.
  - **Log every deletion** with timestamp, scope and outcome. Art 5(2) accountability.
- Both behind re-authentication. Deletion is irreversible; confirm explicitly.

---

## WP3 — Retention purge job 🟠 ~1 day, after WP2

Closes DPIA RISK-5 / backlog L-5.

**Founder decision 2026-09-17: raw audio is retained for the life of the account
and purged on closure.** Advice was a fixed 90-day maximum; the founder elected
otherwise and the residual risk is recorded at DPIA RISK-5.

This means **WP2 is the retention policy.** Without deletion there is no limit at
all, only an intention. So:
- Purge is triggered by account closure, and must cover **R2 objects as well as rows**.
- Add a reconciliation cron: find R2 objects with no live owning row and purge them.
  Orphans are how "we deleted it" becomes false.
- Separately, give the retired demographic-routing rows a documented deletion date
  (DPIA RISK-9) — that is a previewed, separately-authorised retention operation,
  not an automatic migration side effect.

---

## WP4 — Technical B2C fence 🟠 ~half day

Closes DPIA RISK-3 / M3.2. **Raised in priority: the founder has confirmed live
inbound B2B interest.**

AI Act Art 5(1)(f) prohibits emotion recognition in workplace and education
contexts. Terms §7 bans it contractually. **A contract term is not a technical
control**, and if the system is in scope (counsel memo Q1), the contract alone
probably does not discharge Art 5.

- No team plans, no seat purchasing, no multi-user billing, no employer dashboard,
  no org-level admin. If any of these exist even in draft, disable them.
- Audit the coach-assigns-homework flow (`docs/backend-assignment-email-template.html`,
  the homework card architecture). **A coach assigning practice to a learner could
  engage the *education* limb.** Report what you find — do not redesign it yet.
- Add an assertion/test that no code path creates a user account owned by another
  account.

**Do not implement any AI Act *compliance* machinery beyond this fence until
counsel answers.** Building a high-risk conformity apparatus we may not need is
the expensive wrong move.

---

## WP5 — Sub-processor verification 🟡 ~2 hrs, founder-led

Not code. Closes DPIA RISK-8 / backlog L-6. Privacy §9 asserts DPA + transfer
safeguard for eight sub-processors; none verified. Download and file each DPA
(Supabase, Railway, Vercel, Cloudflare, OpenAI, Stripe, Sentry, Resend — all
publish click-through DPAs). **Then confirm OpenAI zero data retention in writing:
ZDR is not a default, it requires an approved per-organisation application.** If it
is not in force, Privacy §5 is false and standard abuse-monitoring retention
applies to every transcript and every piece of audio sent.

**A sub-processor list cannot be audited from the repo** — Vercel was missing from
the first draft because the tree never names its own host. Read the Vercel and
Supabase dashboards, DNS, and the Railway per-service variables.

---

## Explicitly out of scope

- **Do not** change `services/voice_confidence.py` semantics, remove the
  speaker-relative baseline, or rename the construct. Those are live options in the
  counsel memo (Q4) and F1-CORE surface area. **They wait for the opinion.**
- **Do not** edit `src/app/privacy/page.tsx` or `src/app/terms/page.tsx` (frontend-cursor). Copy is fenced under
  LIVE LOOP; the amendments are drafted at
  `docs/legal/COPY-AMENDMENT-PROPOSAL-v1.3.md` awaiting founder sign-off.
- **Do not** activate `mlc2-split-consent-v2.json`. It is DRAFT by design.

## Order

**WP0 → WP1 → WP2 → WP3 → WP4**, with WP5 in parallel by the founder.
WP1 is the bleeding one. WP2 blocks WP3. WP4 can move earlier if the B2B
conversation gets concrete.
