# Record of Processing Activities (GDPR Article 30)

**Controller:** Artur Willoński, operating as "WillpowerLab"
Poland, European Union · contact@willpowerlab.com
(postal address available to data subjects and to UODO on request)

**Representative (Art 27):** not applicable — the controller is established in the EU.
**Data Protection Officer (Art 37):** none appointed. See §6.

**Version:** 0.1 DRAFT · **Date:** 2026-09-17 · **Status:** awaiting founder adoption
**Produced to:** UODO on request. This is an internal record, not a public document.

---

## Why this record is required

Art 30(5) exempts organisations under 250 employees **unless** processing is
likely to result in risk to rights and freedoms, is **not occasional**, or
includes special-category data.

**The exemption does not apply.** Recording and analysing every take of every
user, continuously, is not occasional. The controller also adopts a cautious
Art 9(2)(a) posture (Privacy §3). Either limb removes the exemption on its own.

A privacy policy does not discharge Art 30. This document does.

---

## 1. Processing activities

> **⚠️ Configuration as at 2026-09-18 — the MLC-3 first-client service is ACTIVE.**
>
> An Art 30 record that does not describe today's configuration is inaccurate
> from today, so the activation is recorded here on the day it happened rather
> than at the next review.
>
> | | |
> |---|---|
> | Service contract `mlc3-first-client-service-v1` | **activated 2026-09-17**, for technical validation |
> | `PLF1_PROCESSING_AUTHORIZATION_MODE` | **not enforcing** |
> | Registered processing policy | **none** |
> | Principals on `mlc3_service_principal_allowlist` | **one** — the founder's own |
>
> **This is not a new category of data subject.** The single allowlisted
> principal is the founder, who is therefore simultaneously the controller and
> the only data subject the activation reaches. The risk in practice is
> negligible.
>
> **It is not an exemption, and must not be recorded as one.** There is no
> "self-processing" carve-out in the GDPR. Art 2(2)(c)'s household exemption
> covers purely personal or household activity, is read narrowly by the CJEU,
> and does not reach a business activity — an unregistered business is still a
> business. Every obligation remains intact on paper; only the practical
> exposure is small.
>
> **What guards it:** nothing automatic yet. The one-principal state is a fact
> about production data, not something CI can see, so it is presently a promise
> rather than a gate. See the note at the end of §4.

### A1 — Account administration and authentication
- **Purposes:** create and maintain accounts, authenticate, secure access
- **Categories of subject:** users; coaches
- **Categories of data:** email, display name, hashed password, IP, device and browser metadata, auth tokens and session metadata
- **Art 6 basis:** 6(1)(b) contract · 6(1)(f) legitimate interests for security
- **Recipients:** Supabase (auth + DB), Railway, Vercel, Sentry, Resend
- **Transfers:** Supabase EU region. Railway / Vercel / Sentry / Resend — SCCs where processed outside the EEA
- **Retention:** until account deletion (A1 account data). Approved schedule, `06-retention-schedule-v1.0`.
- **Security:** Art 32 measures at §5
- **Systems:** `auth.users` (**the user record** — 67 rows, 2026-09-17), `user_consents`, `user_consent_events`, `coach_users`, `user_audits`, `user_settings`
- **Correction, 2026-09-17:** this line previously led with `user_settings` as an account system. It is not the user record and must not be read as a user count: it holds **7 rows against 67 accounts**, because a row is written when a user changes a preference, not when an account is created. `auth.users` is the account register. The distinction was found while reconciling a 7-vs-25 discrepancy in the DPIA and is recorded because the wrong table was briefly being used to size the user base.

### A2 — Voice recording and storage
- **Purposes:** capture the user's spoken take for transcription, playback, analysis and coaching
- **Categories of subject:** users; incidentally, third parties audible in a recording
- **Categories of data:** raw audio (voice), capture timestamps, device metadata, slide/session correlation
- **Art 6 basis:** currently 6(1)(a). **⚠️ Under remediation — to be re-based on 6(1)(b), see DPIA RISK-1.** 9(2)(a) as cautious overlay for incidental special-category content
- **Recipients:** Cloudflare R2 (object storage), OpenAI (transcription/analysis), Railway/worker
- **Transfers:** Cloudflare — DPA and SCCs. OpenAI — United States, DPA and SCCs, zero-retention API terms (**unverified, DPIA RISK-8**)
- **Retention:** **12 months after last use of the recording** (founder-approved schedule, 2026-09-17; supersedes the life-of-account position first recorded here). Rules seeded by a pending migration; the purge job that enforces them is not yet built — DPIA RISK-5 M5.1.
- **Systems:** R2 buckets; `coaching_attempts`, `reflection_clips`, `rejected_takes`
- **Storage location, verified 2026-09-17:** all four Cloudflare R2 buckets — `coach-feedback-videos`, `user-interview-audio`, `willab-journal`, `willab-lab-audio` — report **Eastern Europe (EEUR)** in the Cloudflare console. Recorded as verified rather than assumed: the jurisdiction was an open item in `VENDOR_DPA_REGISTER.md`, and that item closes with the console as its evidence. **There is no undisclosed international transfer of recordings.**
- **Access control, 2026-09-18 — see DPIA RISK-11.** Recordings were served over permanent, unauthenticated public URLs from at least 2026-05-08. They are now served over short-lived signed URLs, and stored public URLs are re-signed on read. **Residual:** the buckets remain publicly readable, so URLs issued before that date stay valid; closing that needs the private-bucket migration (DPIA M11.4, undated, founder decision).

### A3 — Transcription and per-slide segmentation
- **Purposes:** produce an accurate transcript segmented 1:1 per slide
- **Categories of data:** transcripts, word timings, slide boundaries, user transcript edits
- **Art 6 basis:** as A2
- **Recipients:** OpenAI developer API; Supabase
- **Transfers:** OpenAI — US, SCCs, ZDR terms
- **Retention:** until account deletion
- **Systems:** `user_transcript_edits`, `read_alignments`, `candidate_windows`

### A4 — Delivery-signal inference ("what we infer from your voice")
- **Purposes:** locate a take on a delivery spectrum to select evidence for coaching feedback and Ideal Text assembly
- **Categories of subject:** users
- **Categories of data:** acoustic measurements (`f0_mean`, `f0_sd`, `dynamic_db`, `pause_ratio`, `wpm`, `f0_mid_end_delta`, intensity envelope); the `voice_confidence` composite, z-scored against the speaker's own baseline; `power_score`
- **Art 6 basis:** 6(1)(a). **⚠️ Published as "opt-in and off by default"; the code defaults on — DPIA RISK-2**
- **Recipients:** internal only. Not surfaced to users (AC-9 fence). Not on the coach packet (BLIND COACH fence)
- **Transfers:** none — computed in-process from metrics already held
- **Retention:** until account deletion
- **⚠️ AI Act note:** the controller adopts, **pending counsel's determination**, the conservative working assumption that these are biometric data under AI Act Art 3(34) — whose text omits GDPR Art 4(14)'s unique-identification limb, though Recital 14 directs that it be read in light of it. Whether the composite is an emotion recognition system under Art 3(39) is **open and contested**; both readings are set out in `legal/phase1-2026.1/02-power-score-classification-v1.0` §7, and the determination belongs there. This record states the working assumption, not a conclusion. See also `AI-ACT-SCOPING-MEMO.md`
- **Systems:** `services/voice_confidence.py`, `services/acoustic_baseline.py`, `services/part_acoustics.py`, `intervention_decisions`

### A5 — Coaching feedback generation and Ideal Text
- **Purposes:** generate evidence-backed feedback and maintain the canonical Ideal Text
- **Categories of data:** transcripts, derived measurements, feedback candidates and decisions, Ideal Text versions
- **Art 6 basis:** 6(1)(b) contract (the service itself)
- **Recipients:** OpenAI developer API; Supabase
- **Retention:** until account deletion
- **Systems:** `intervention_decisions`, `coaching_attempt_annotations`, `best_presentation_edits`

### A6 — Self-reported pre-take state
- **Purposes:** preserve the user's own answer to a pre-recording check-in
- **Categories of data:** `named_emotion` — one key from a closed vocabulary (*calm, curious, excited, determined, confident, nervous, tense, overwhelmed, doubtful, tired, unsure*)
- **Art 6 basis:** 6(1)(a)
- **Recipients:** the reviewing coach (founder decision: it is the user's own self-report, not a machine guess)
- **Note:** stored verbatim as a validated self-report. Not converted to a psychological state, score, direction or training label. **Not an inference and therefore not in AI Act scope**
- **Retention:** until account deletion
- **Systems:** take `intake_context`, `recording_feelings`

### A7 — Human coach review
- **Purposes:** asynchronous review and correction of machine feedback; calibration
- **Categories of subject:** users (reviewed); coaches (their labels are data about them)
- **Categories of data:** audio, transcripts, coach corrections, coach labels, adjudications
- **Art 6 basis:** 6(1)(a) for the user's data; 6(1)(b)/6(1)(f) for the coach relationship
- **Recipients:** the coach. Where the coach is not the operator, an Art 28 processor or a separate controller — **DPA to be verified, DPIA RISK-6**
- **Retention:** until account deletion; labels retained for calibration
- **Systems:** `training_labels`, `recording_reviews`, `recording_review_annotations`, `coach_snippet_drafts`, `coach_best_presentation_edits`

### A8 — Blind peer rating and community sharing
- **Purposes:** obtain blind perceptual judgements on shared extracts; calibrate analysis; assess rater reliability
- **Categories of subject:** sharing users; rating users
- **Categories of data:** shared audio extracts (presented without name); perceptual judgements; rater reliability metrics; latency
- **Art 6 basis:** 6(1)(a) — opt-in per recording, revocable (**revocation published but unbuilt, backlog L-2**)
- **Recipients:** **other users of the service.** The only route by which personal data reaches other data subjects
- **Note:** a voice is inherently identifiable to anyone who knows the speaker. Disclosed as such in Privacy §7
- **Retention:** extracts while sharing is active; ratings retained in aggregate after withdrawal
- **Systems:** `snippet_peer_labels`, `charisma_snippets` (legacy naming), `content_exposures`

### A9 — Model improvement and training
- **Purposes:** evaluate, train and improve WillpowerLab's own analysis and feedback models
- **Categories of data:** recordings, transcripts, derived measurements, ratings, coach corrections
- **Art 6 basis:** 6(1)(a). **⚠️ Currently bundled with coaching and mandatory — assessed as invalid, DPIA RISK-1**
- **Recipients:** internal. **Not** provided to third parties for training their own models. OpenAI API inputs not used for foundation-model training under ZDR terms (**unverified**)
- **Retention:** n/a — **this activity does not run.** `pooled_model_improvement` is a phase-2 purpose and the database refuses to register any policy carrying one (`PHASE2_PURPOSE_FORBIDDEN`). The v2.0 copy removes the claim that contributions are irreversible, because there are no contributions.
- **Systems:** `training_labels`, `model_versions`, `shadow_predictions`, `confidence_dataset`

### A10 — Payments and billing
- **Purposes:** process payments, manage plans and the token allowance, meet accounting obligations
- **Categories of data:** transaction status, card last four, billing country, subscription status. **Full card data never reaches the controller**
- **Art 6 basis:** 6(1)(b) contract · 6(1)(c) Polish accounting and tax law
- **Recipients:** Stripe
- **Transfers:** SCCs
- **Retention:** n/a — **this activity is built but NOT YET RUNNING.** Corrected 2026-09-18; it previously read "does not run", which was an assertion with no evidence behind it and was wrong about the intent.
- **Systems:** `arc_purchases`, token wallet tables

> **⚠️ 2026-09-18 — corrected, with the evidence this entry previously lacked.**
>
> **Freemium is the intended model** (founder, 2026-09-17): free is generous,
> continued use ultimately requires payment. So this activity is *planned and
> implemented*, not absent. An Art 30 record must not describe a processing
> activity as non-existent when it is built and scheduled — "does not run" and
> "is not running yet" are different statements to a supervisory authority.
>
> **How the absence of processing was established, rather than asserted:**
>
> | | |
> |---|---|
> | Charges taken, ever | **Zero** — verified in the Stripe dashboard, 2026-09-17 |
> | Payment code | Implemented: credits checkout, tier checkout, arc checkout, webhook |
> | `STRIPE_SECRET_KEY` in production | **Present on the backend service** until 2026-09-18 — so checkout was live and reachable |
> | Removed from all services | *[[FOUNDER: date, once verified absent from each boot log]]* |
>
> **The key being present is the material fact.** Every payment surface gates
> on it (`stripe_checkout_credits.py:74`, `tier_checkout.py:94` and `:206`,
> `arc_checkout.py:53` and `:117`, `internal_webhooks.py:105`), each returning
> `503 DISABLED` without it. Its presence means a user *could* have been
> charged, even though none was. That is what makes "does not run" the wrong
> description and "no charges have been taken" the right one.
>
> **Order of operations, founder-stated and now enforced in CI.** Paid launches
> on a Terms amendment, not a config change: re-version the Terms, obtain
> sign-off, register the policy, *then* set the key.
> `tests/test_payment_copy_contract.py` fails if payment config is present
> while the Terms in force still tell users we do not take payment.
>
> **`token_ledger` and `llm_usage`** remain internal model-cost records, not
> billing. They sit under `financial_evidence`, and their disposition is still
> the open question in document 06 §3 — which is unchanged by this correction,
> because zero charges means there are still no accounting records to retain.

### A11 — Service operation, security and diagnostics
- **Purposes:** operate, secure, debug and improve reliability
- **Categories of data:** usage logs, feature events, timestamps, error and diagnostic data, IP
- **Art 6 basis:** 6(1)(f) legitimate interests. **LIA to be recorded — gap**
- **Recipients:** Sentry, Railway, Vercel, Supabase
- **Retention:** security and technical logs, **90 days** (founder-approved schedule). Sub-processor-side retention still to be pinned per vendor — see `07-vendor-actions`.
- **Systems:** `user_audits`, `session_metrics`, `pipeline_health`, Sentry

### A12 — Transactional email
- **Purposes:** account, service and assignment notifications
- **Categories of data:** email address, message metadata
- **Art 6 basis:** 6(1)(b) · 6(1)(a) for anything marketing
- **Recipients:** Resend
- **Retention:** per Resend defaults
- **Systems:** `emails/`, `life_reminder_log`

### A13 — Retired: demographic routing and challenge/threat labels
- **Status:** ⛔ **Retired as executable behaviour (2026-08-29). No new writes.**
- **Historical data:** sex-routing fields and coach challenge/threat rows in `training_labels`
- **Current purpose:** audit only
- **Art 6 basis:** 6(1)(f) — integrity of the historical corpus record
- **⚠️ Gap:** no deletion date set. Audit-only is a legitimate purpose only if documented with an end date. **DPIA RISK-9 / M9.1**
- **Note:** inferring sex from pitch would have been biometric categorisation — AI Act Annex III(1)(b), high-risk. Not an Art 5(1)(g) prohibited category (biological sex is not among those listed). Retirement was correct

---

## 2. Sub-processors and recipients (Art 30(1)(d), (e))

| Recipient | Role | Activities | Location | Safeguard | Verified? |
|---|---|---|---|---|---|
| Supabase | Processor | DB, auth, storage | EU region | DPA | ⛔ L-6 |
| Railway | Processor | Backend hosting | DPA + SCCs | SCCs | ⛔ L-6 |
| Vercel | Processor | Web hosting | DPA + SCCs | SCCs | ⛔ L-6 |
| Cloudflare R2 | Processor | Audio/video object storage | DPA + SCCs | SCCs | ⛔ L-6 |
| OpenAI | Processor | Transcription and analysis | United States | DPA + SCCs + **ZDR** | ⛔ **ZDR is not a default — verify** |
| Stripe | Processor / independent controller | Payments | DPA + SCCs | SCCs | ⛔ L-6 |
| Sentry | Processor | Error monitoring | DPA + SCCs | SCCs | ⛔ L-6 |
| Resend | Processor | Transactional email | DPA + SCCs | SCCs | ⛔ L-6 |
| Coaches (non-operator) | Processor | Human review | EU presumed | Written DPA | ⛔ **Verify before access** |

**⛔ Every row is asserted in Privacy §9 and unverified. An unsigned DPA makes the
published policy false.** Closing L-6 closes this table.

**A sub-processor list cannot be audited from the repository alone** — Vercel was
absent from the first draft because the tree never names its own host. The next
pass must read the Vercel and Supabase dashboards, DNS, and the Railway
per-service variables.

---

## 3. Retention (Art 30(1)(f))

| Category | Period | Enforced? |
|---|---|---|
| Voice (audio) | **Life of account; purged on closure** (founder decision 2026-09-17) | ⛔ **No purge job exists** |
| Transcripts, Ideal Text, coaching notes | Life of account | ⛔ No deletion route |
| Derived measurements | Life of account | ⛔ |
| Shared extracts | While sharing active | ⛔ Revocation unbuilt (L-2) |
| Ratings, coach labels | Retained for calibration; aggregate contributions not reversed | Disclosed |
| Account data | Life of account, then deletion/anonymisation | ⛔ No deletion route |
| Billing | Per Polish accounting/tax law | Stripe |
| Usage/diagnostic | Sub-processor defaults | ⛔ Not pinned |
| Retired demographic rows | **No end date set** | ⛔ RISK-9 |

**Every "enforced" cell is a gap.** Art 5(1)(e) and Art 5(2) accountability both
require the record to be true, not aspirational.

---

## 4. Data subject rights readiness

| Right | Route | Status |
|---|---|---|
| Access (15) | Manual, ~69 tables + R2 | ⛔ No export route |
| Rectification (16) | Manual | Partial — transcript edits are self-service |
| Erasure (17) | Manual | ⛔ **No deletion route** |
| Restriction (18) | Manual | ⛔ |
| Portability (20) | Manual | ⛔ No structured export |
| Object (21) | Manual, by email | Partial |
| Withdraw consent (7(3)) | Data & consent surface | Partial — no model-improvement flag (L-1) |

`/v2/processing-authorization/data-export` returns **authorisation evidence**, not
the subject's personal data. **It does not discharge Art 15 or Art 20.**

> **⚠️ 2026-09-18 — erasure is NON-FUNCTIONAL, and this is a present fact, not a risk.**
>
> The purge orchestrator exists but currently deletes **nothing, for anyone**.
>
> `resolve_targets` is all-or-nothing by design — *"Unknown inventory means
> zero deletion"*, `services/data_purge.py:808`. Any dependency that cannot
> resolve a retention rule aborts the whole run rather than deleting part of an
> account, which is the correct behaviour: a half-deleted account is worse than
> an undeleted one, because the subject is told it is done.
>
> Five `retention_category` values exist in the registry. Four are seeded by
> `migrations/the_retention_schedule_is_loaded.sql`. The fifth,
> `financial_evidence`, is deliberately unseeded pending document 06 §3, so its
> two dependencies land on `RETENTION_RULE_UNRESOLVED` and every purge aborts.
>
> **Operational consequence, stated so it is not discovered during a request:**
> if an Art 17 erasure request arrives before that rule exists, it **cannot** be
> fulfilled by the orchestrator and must be escalated to manual handling inside
> the Art 12(3) one-month deadline. Seeding the four rules is necessary and not
> sufficient — the purge starts working when counsel answers §3, not when that
> migration merges.

> **On the one-principal allowlist (see the banner at §1).** "Only the founder
> is allowlisted" is currently a statement about production data, which no test
> in this repository can observe. It is therefore a promise, not a control. The
> options for converting it into one are: a check in a production monitor
> script, or a database constraint that refuses a second principal while no
> policy is registered. The second fails closed and is the stronger of the two;
> it is a behaviour change and needs founder authorisation before it ships.

---

## 5. Security measures (Art 30(1)(g), Art 32)

- Managed EU-region database with provider-level encryption at rest
- TLS in transit throughout
- Passwords stored hashed; JWT-based authentication
- Object storage under access-controlled keys, not public buckets
- Per-service secret management; secrets not committed
- Row-level ownership checks on project and recording access
- Gate-routed merges; CI checks (`scripts/local_ci.sh`) before production
- Audit trail of consent grants and withdrawals (`user_consents`, `user_consent_events`)
- Structured logging with derivation outputs rather than raw user notes for LLM paths

**Gaps:** no formal breach-response runbook (Arts 33/34); no documented backup
and restore test; no periodic access review for coach accounts.

---

## 6. Data Protection Officer

None appointed. Art 37(1)(b) requires one where core activities consist of
processing requiring **regular and systematic monitoring of data subjects on a
large scale**; 37(1)(c) where core activities are large-scale Art 9 processing.

Recording and analysing every take is regular and systematic monitoring. The
conclusion rests entirely on **"large scale"**, which at the current user count is
not met (WP243 factors: number of subjects, volume, duration, geography).

**This conclusion is a function of scale and will flip as the service grows. It
must be revisited at each review, and specifically before any B2B deployment.**

---

## 7. Review

Reviewed alongside the DPIA, and on: adoption of the split consent; any new
sub-processor; any new processing activity; any change to retention; first B2B
use; material growth in user numbers.

---

*Prepared as counsel-support. Requires founder adoption. Not legal advice.*
