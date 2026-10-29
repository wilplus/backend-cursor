# WillpowerLab: start here

A speaker records a Take. The app turns it into a transcript, one paragraph per slide, the **Ideal Text**,
and gives evidence-backed feedback after every Take. Then they record the next Take. That loop is the product.
This repo is the backend (Flask, Railway, Supabase). The frontend is
[`wilplus/frontend-cursor`](https://github.com/wilplus/frontend-cursor) (Next.js, Vercel).

This page lists every doc in both repos, with one label each (founder, 21 October 2026, N106):

- **In force**: the rules. Read them in the order below (N95).
- **Reference**: how something works today. Where it differs from the rules, the rules win.
- **History**: kept as written, because the rules still cite it. Not edited.
- **Archive**: out of date, and nothing needs it. It moves to an archive folder later.

Each doc also says its label in a line under its title, except the docs that must stay byte for byte:
the legal pack (a test checks its citations), the signed texts, files that live beside code, and files
already in an archive or history folder.

## 0. Strategy now

The founder's direction in one place (N129, N178). Where a rule below says more, the rule wins.

- **The loop is the product.** Record a Take, get the Ideal Text and evidence-backed feedback, record the next Take.
- **The plan serves the loop.** Every speaker is diagnosed and gets a plan up to their deadline (N136). The plan
  chooses what each Feedback walk practises (N129). When the plan and the loop compete, the loop wins: before any
  Take but the first, the only thing shown is the feelings check, with a Skip (N178).
- **Second priority**, never slowing the loop: coach review, Confident Voice and practice.
- **Built:** the loop and the Feedback walk, the coach panel, and the tempo step for the speakers a ring lets in.
  **Decided and held:** the plan's diagnosis, practice days, calls and reminders; the founder holds their build (N147).
- **Next builds:** not named yet (N178).

## 1. The rules (In force)

For coding agents, first: [`CLAUDE.md`](CLAUDE.md) (and [`AGENTS.md`](AGENTS.md)). Then, in N95's order:

1. [The decisions log](docs/SPEC-DECISIONS-LOG.md): the founder's dated decisions, newest last.
2. [The product contract](docs/CANONICAL_PRODUCT_CONTRACT.md): the numbered clauses.
3. [The locked screens](docs/LOCKS.md), and [the founder lock for the coach panel and the learning machine](docs/FOUNDER-LOCK-coach-panel-2026-10.md) (L1 to L9).
4. The rules page of each locked screen, in the frontend repo, which count for their screens:
   - [The Feedback walk and the chat](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md)
   - [The coach panel](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/coach-panel.md)
   - [The Ideal Text page and its helper words](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/ideal-text.md)
   - [The recording screens](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/recording-screens.md)
   - [The consent screens and the Data & consent page](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/consent-screens.md)
   - [The AI version of your voice in practice](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/ai-voice-practice.md)
   - [The plan: from the first questions to the deadline](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md), the one page for the diagnosis and the plan (N129 to N178), a rules page, locked once its first part is built (N178) · Founder-Approved: the Claude Code chat, 26 October 2026, "Okay", to the plan having its own flow page (N160)
   - [The principles: the Sunday note and life goals](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/principles.md), a ring 6 feature apart from the speaking coach (N182) · Founder-Approved: the Claude Code chat, 26 October 2026, "Own page, ring 6", to the principles having their own flow page (N182)
   - [Customer requests: a client's customer asks, the answerer replies with a Take](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/customer-requests.md), the widget on a client's site, the answer as a Take, the customer's chat and booking, and what the client's model learns (N223 to N229); its prototypes, as HTML and PDF, in [`docs/design/customer-requests-2026-10-28/`](docs/design/customer-requests-2026-10-28/) · Founder-Approved: the Claude Code chat, 28 October 2026, "Approve as drafted", to the page (N229)
5. [Learning and the label quorum](docs/LEARNING-AND-QUORUM.md): what the app learns from and how a label settles.
6. [The signed line bank](docs/SIGNED-line-bank-2026-10-06.md): the signed words a speaker may see.

The frontend has its own short [`README.md`](https://github.com/wilplus/frontend-cursor/blob/main/README.md) that points here.

## 2. How it works today (Reference)

### Backend

**How the system works**

- [The durable pipeline queue — architecture, Railway rollout, FE handoff](docs/ASYNC-PIPELINE-QUEUE.md) · `backend` `docs/ASYNC-PIPELINE-QUEUE.md`
- [Transactions — what is atomic, what is not, what to move next](docs/DB-TRANSACTIONS.md) · `backend` `docs/DB-TRANSACTIONS.md`
- [dev-bugs — internal bug collector (setup & ops)](docs/DEV-BUGS-SETUP.md) · `backend` `docs/DEV-BUGS-SETUP.md`
- [dev.willpowerlab.com — "user stories · tasks" backlog (SPEC, for review)](docs/DEV-TASKS-PIPELINE-SETUP.md) · `backend` `docs/DEV-TASKS-PIPELINE-SETUP.md`
- [Journal (blog) + CMS — BE setup](docs/JOURNAL-SETUP.md) · `backend` `docs/JOURNAL-SETUP.md`
- [Migrations — how schema changes reach a database](docs/MIGRATIONS.md) · `backend` `docs/MIGRATIONS.md`
- [OPS — feature flags and what is waiting on a release decision](docs/OPS-FLAGS-AND-RELEASES.md) · `backend` `docs/OPS-FLAGS-AND-RELEASES.md`
- [Ops runbook — the recording pipeline queue](docs/OPS-PIPELINE-QUEUE-RUNBOOK.md) · `backend` `docs/OPS-PIPELINE-QUEUE-RUNBOOK.md`
- [Ops runbook — secrets, staging, storage split, Sentry](docs/OPS-SECRETS-AND-STAGING.md) · `backend` `docs/OPS-SECRETS-AND-STAGING.md`
- [Load-time finding — chat + ideal text (ticket 7, 2026-07-26)](docs/PERF-chat-and-ideal-text.md) · `backend` `docs/PERF-chat-and-ideal-text.md`
- [Phase-1 processing authorization runbook](docs/PHASE1-PROCESSING-RUNBOOK.md) · `backend` `docs/PHASE1-PROCESSING-RUNBOOK.md`
- [Private buckets (DPIA RISK-11, mitigation M11.4)](docs/PRIVATE-BUCKETS-M11.4.md) · `backend` `docs/PRIVATE-BUCKETS-M11.4.md`
- [Rehearsal tier — recipes for the three pending lanes](docs/REHEARSAL-TIER-PENDING-LANE-RECIPES.md) · `backend` `docs/REHEARSAL-TIER-PENDING-LANE-RECIPES.md`
- [The rehearsal tier — PostgreSQL-bound tests, run against a disposable cluster](docs/REHEARSAL-TIER.md) · `backend` `docs/REHEARSAL-TIER.md`
- [Migrations](migrations/README.md) · `backend` `migrations/README.md`
- [migrations/pending — written, reviewed, NOT in the manifest yet](migrations/pending/README.md) · `backend` `migrations/pending/README.md`

**Specs and designs**

- [The AI version of your voice — how it works](docs/AI-VOICE-PRACTICE.md) · `backend` `docs/AI-VOICE-PRACTICE.md`
- [WIL-70 · Speaker/coach disagreement as a learning signal (design note, 2026-10-18)](docs/DESIGN-WIL-70-disagreement-signal-2026-10-18.md) · `backend` `docs/DESIGN-WIL-70-disagreement-signal-2026-10-18.md`
- [Canonical Feedback Data Contract — Migration Map](docs/FEEDBACK_DATA_CONTRACT_MIGRATION_MAP.md) · `backend` `docs/FEEDBACK_DATA_CONTRACT_MIGRATION_MAP.md`
- [Ideal Text cold-open implementation](docs/IDEAL-TEXT-COLD-OPEN-IMPLEMENTATION.md) · `backend` `docs/IDEAL-TEXT-COLD-OPEN-IMPLEMENTATION.md`
- [The learning doors — how each one opens (founder 2026-09-30, L1 to L9)](docs/LEARNING-DOORS.md) · `backend` `docs/LEARNING-DOORS.md`
- [ED-PLF-1.3 — Staged authorization and continuously learning service design](docs/PLF1-ENGINEERING-DESIGN.md) · `backend` `docs/PLF1-ENGINEERING-DESIGN.md`
- [WIL-74 principles: feedback, goals and notifications (founder, 2026-10-20)](docs/PRINCIPLES-WIL-74-feedback-goals.md) · `backend` `docs/PRINCIPLES-WIL-74-feedback-goals.md`
- [Rate limits + the JSON error contract](docs/RATE-LIMITS-AND-ERROR-CONTRACT.md) · `backend` `docs/RATE-LIMITS-AND-ERROR-CONTRACT.md`
- [RPQ-V1 dependency restoration and local implementation review packet](docs/ROOTING-PHRASE-QUALIFICATION-V1-IMPLEMENTATION.md) · `backend` `docs/ROOTING-PHRASE-QUALIFICATION-V1-IMPLEMENTATION.md`
- [Rooting Phrase Qualification V1 — Release Packet](docs/ROOTING-PHRASE-QUALIFICATION-V1-RELEASE.md) · `backend` `docs/ROOTING-PHRASE-QUALIFICATION-V1-RELEASE.md`
- [Speaker memory: how Will learns about each speaker](docs/SPEAKER-MEMORY.md) · `backend` `docs/SPEAKER-MEMORY.md`
- [Appendix A — Verbal Computations for Misalignment and Mis-Emphasis](docs/SPEC-APPENDIX-A-verbal-computations.md) · `backend` `docs/SPEC-APPENDIX-A-verbal-computations.md`
- [Appendix B — Feedback Progression: Novice to Expert](docs/SPEC-APPENDIX-B-progression.md) · `backend` `docs/SPEC-APPENDIX-B-progression.md`
- [Appendix C — Intervention Contract: Finding → Intervention → Presentation](docs/SPEC-APPENDIX-C-intervention-contract.md) · `backend` `docs/SPEC-APPENDIX-C-intervention-contract.md`
- [Appendix D — Fire-Up Benchmarks and Trigger Functions](docs/SPEC-APPENDIX-D-benchmarks.md) · `backend` `docs/SPEC-APPENDIX-D-benchmarks.md`
- [Appendix E — Research Findings and Required Amendments](docs/SPEC-APPENDIX-E-research.md) · `backend` `docs/SPEC-APPENDIX-E-research.md`
- [Appendix F — Measurement Windows](docs/SPEC-APPENDIX-F-windows.md) · `backend` `docs/SPEC-APPENDIX-F-windows.md`
- [Appendix G — Silent Population Telemetry](docs/SPEC-APPENDIX-G-telemetry.md) · `backend` `docs/SPEC-APPENDIX-G-telemetry.md`
- [Appendix H — Manager Engine Parameters](docs/SPEC-APPENDIX-H-manager.md) · `backend` `docs/SPEC-APPENDIX-H-manager.md`
- [SPEC — Immutable source data and provenance](docs/SPEC-immutable-provenance.md) · `backend` `docs/SPEC-immutable-provenance.md`
- [SPEC — Parts, Locking, and the Two Intervention Layers](docs/SPEC-parts-locking-and-layers.md) · `backend` `docs/SPEC-parts-locking-and-layers.md`
- [SPEC — Pipeline queue admin panel (Task IV)](docs/SPEC-pipeline-admin-panel.md) · `backend` `docs/SPEC-pipeline-admin-panel.md`
- [SPEC — Training corpus, training consent and project-scoped purge](docs/SPEC-training-corpus-and-project-purge.md) · `backend` `docs/SPEC-training-corpus-and-project-purge.md`
- [Speech Coaching System — Canonical Specification](docs/SPEC.md) · `backend` `docs/SPEC.md`
- [Vocal-emotion acoustics — what we can measure, and where it stops](docs/VOCAL-EMOTION-ACOUSTICS.md) · `backend` `docs/VOCAL-EMOTION-ACOUSTICS.md`
- [The check-in learning contract](docs/life-checkin-learning-contract.md) · `backend` `docs/life-checkin-learning-contract.md`
- [WILLAB DECISION FILTER](docs/willab_decision_filter.md) · `backend` `docs/willab_decision_filter.md`
- [The golden set for `scripts/measure_transcripts.py` (D-ML-1)](scripts/measure_transcripts.md) · `backend` `scripts/measure_transcripts.md`

**The MLC-2 and MLC-3 programme**

- [MLC-3 exercise adequacy and Feedback Policy V3 design](docs/MLC3-EXERCISE-ADEQUACY-DESIGN.md) · `backend` `docs/MLC3-EXERCISE-ADEQUACY-DESIGN.md`

**Plans and backlogs**

- [Will's learning plan (founder, 2026-10-20)](docs/WILL-LEARNING-PLAN.md) · `backend` `docs/WILL-LEARNING-PLAN.md`
- [Production Data Foundation](docs/work-items/production-data-foundation.md) · `backend` `docs/work-items/production-data-foundation.md`

**Other**

- [P5 — switching training on: the packet for counsel and the founder](docs/P5-TRAINING-ACTIVATION-PACKET.md) · `backend` `docs/P5-TRAINING-ACTIVATION-PACKET.md`
- [WillLab Community — Content & Growth Strategy](docs/WillLab_Community_Content_Strategy.md) · `backend` `docs/WillLab_Community_Content_Strategy.md`
- [Coach surface namespace — `/v2/coach/*` is canonical (delta)](docs/coach-namespace-delta.md) · `backend` `docs/coach-namespace-delta.md`

**Legal and privacy**

- [Marking AI-generated output — mechanism proposal (Article 50(2))](docs/AI-CONTENT-MARKING-PROPOSAL.md) · `backend` `docs/AI-CONTENT-MARKING-PROPOSAL.md`
- [Bundled-era erasure (F4)](docs/BUNDLED-ERA-ERASURE.md) · `backend` `docs/BUNDLED-ERA-ERASURE.md`
- [Product/legal onboarding and processing flow — PLF-1.1](docs/PRODUCT-LEGAL-FLOW-PLF-1.1.md) · `backend` `docs/PRODUCT-LEGAL-FLOW-PLF-1.1.md`
- [Vendor / sub-processor register (Art. 28 + Art. 30 support)](docs/VENDOR_DPA_REGISTER.md) · `backend` `docs/VENDOR_DPA_REGISTER.md`
- [Vendor processor paperwork](docs/compliance/dpa/README.md) · `backend` `docs/compliance/dpa/README.md`

### Frontend

**How the system works**

- [willab upload proxy (Cloudflare Worker)](https://github.com/wilplus/frontend-cursor/blob/main/cloudflare/upload-proxy/README.md) · `frontend` `cloudflare/upload-proxy/README.md`
- [Life Panel — source artifacts still outside the repo](https://github.com/wilplus/frontend-cursor/blob/main/docs/life-panel-sources/README.md) · `frontend` `docs/life-panel-sources/README.md`

**Specs and designs**

- [WIL-74 principles (founder, 2026-10-20)](https://github.com/wilplus/frontend-cursor/blob/main/docs/PRINCIPLES-WIL-74.md) · `frontend` `docs/PRINCIPLES-WIL-74.md`
- [Confidence recognizer — FE pointer](https://github.com/wilplus/frontend-cursor/blob/main/docs/SPEC-confidence-recognizer.md) · `frontend` `docs/SPEC-confidence-recognizer.md`
- [The Life Panel — implementation document](https://github.com/wilplus/frontend-cursor/blob/main/docs/life-panel-spec.md) · `frontend` `docs/life-panel-spec.md`

**Plans and backlogs**

- [Life Panel FE — what shipped, what it assumes, what is still open](https://github.com/wilplus/frontend-cursor/blob/main/docs/life-panel-fe-status.md) · `frontend` `docs/life-panel-fe-status.md`

### The legal pack

Counsel's documents keep their own indexes: [`legal/phase1-2026.1/README.md`](legal/phase1-2026.1/README.md)
and [`docs/legal/README.md`](docs/legal/README.md). Every file in them is Reference and stays byte for byte.

<details><summary>All 56 files of the legal pack</summary>

- [Memorandum to Counsel](docs/legal/AI-ACT-SCOPING-MEMO.md) · `backend` `docs/legal/AI-ACT-SCOPING-MEMO.md`
- [Why the accepted terms version has been stuck at 1.0 since July](docs/legal/CONSENT-VERSION-INVESTIGATION.md) · `backend` `docs/legal/CONSENT-VERSION-INVESTIGATION.md`
- [Proposed copy amendments — Privacy v1.3 / Terms v1.3](docs/legal/COPY-AMENDMENT-PROPOSAL-v1.3.md) · `backend` `docs/legal/COPY-AMENDMENT-PROPOSAL-v1.3.md`
- [Data Protection Impact Assessment](docs/legal/DPIA-2026-09-17.md) · `backend` `docs/legal/DPIA-2026-09-17.md`
- [DPIA addendum — every learning lane under the training yes (Privacy 3.5) — SIGNED by the founder 2026-10-08](docs/legal/DPIA-ADDENDUM-2026-10-08-all-learning-SIGNED.md) · `backend` `docs/legal/DPIA-ADDENDUM-2026-10-08-all-learning-SIGNED.md`
- [Emails to send](docs/legal/EMAILS-TO-SEND.md) · `backend` `docs/legal/EMAILS-TO-SEND.md`
- [Engineering brief — GDPR remediation](docs/legal/ENGINEERING-BRIEF-GDPR-REMEDIATION.md) · `backend` `docs/legal/ENGINEERING-BRIEF-GDPR-REMEDIATION.md`
- [Processor contact log — OpenAI settings-change history](docs/legal/PROCESSOR-CONTACT-LOG.md) · `backend` `docs/legal/PROCESSOR-CONTACT-LOG.md`
- [Legal compliance artefacts](docs/legal/README.md) · `backend` `docs/legal/README.md`
- [Record of Processing Activities — addendum: the learning lanes (Privacy 3.5) — SIGNED by the founder 2026-10-08](docs/legal/ROPA-ADDENDUM-2026-10-08-all-learning-SIGNED.md) · `backend` `docs/legal/ROPA-ADDENDUM-2026-10-08-all-learning-SIGNED.md`
- [Record of Processing Activities (GDPR Article 30)](docs/legal/ROPA-ART30.md) · `backend` `docs/legal/ROPA-ART30.md`
- [Result: the acceptance window DID split across the 2026-06-06 rebrand](docs/legal/queries/acceptance-window-split-RESULTS.md) · `backend` `docs/legal/queries/acceptance-window-split-RESULTS.md`
- [Product legal approval — WillpowerLab Phase-1 recording and coaching service](legal/phase1-2026.1/01-product-legal-approval-v1.0-DRAFT.md) · `backend` `legal/phase1-2026.1/01-product-legal-approval-v1.0-DRAFT.md`
- [`power_score` — classification under Regulation (EU) 2024/1689 (AI Act)](legal/phase1-2026.1/02-power-score-classification-v1.0-DRAFT.md) · `backend` `legal/phase1-2026.1/02-power-score-classification-v1.0-DRAFT.md`
- [`power_score` — classification under Regulation (EU) 2024/1689 (AI Act)](legal/phase1-2026.1/02-power-score-classification-v1.1-DRAFT.md) · `backend` `legal/phase1-2026.1/02-power-score-classification-v1.1-DRAFT.md`
- [Document 02, version 1.2 — note for the learned detector (detector training) — SIGNED by the founder 2026-10-08](legal/phase1-2026.1/02-power-score-classification-v1.2-NOTE-SIGNED-2026-10-08.md) · `backend` `legal/phase1-2026.1/02-power-score-classification-v1.2-NOTE-SIGNED-2026-10-08.md`
- [Document 02, version 1.3 — note for the Willfidence reading a coach and the founder see — SIGNED by the founder 2026-10-27](legal/phase1-2026.1/02-power-score-classification-v1.3-NOTE-SIGNED-2026-10-27.md) · `backend` `legal/phase1-2026.1/02-power-score-classification-v1.3-NOTE-SIGNED-2026-10-27.md` · Founder-Approved: the sign-off page and the Claude Code chat, 27 October 2026, "I sign as drafted, question 1 A, question 2 A" (N208)
- [`power_score` — classification under Regulation (EU) 2024/1689 (AI Act) — version 1.2, SIGNED by the founder 2026-10-08](legal/phase1-2026.1/02-power-score-classification-v1.2-SIGNED-2026-10-08.md) · `backend` `legal/phase1-2026.1/02-power-score-classification-v1.2-SIGNED-2026-10-08.md`
- [Article 50 transparency assessment — WillpowerLab](legal/phase1-2026.1/03-article-50-assessment-v1.0-DRAFT.md) · `backend` `legal/phase1-2026.1/03-article-50-assessment-v1.0-DRAFT.md`
- [Article 50 transparency assessment — WillpowerLab](legal/phase1-2026.1/03-article-50-assessment-v1.1-DRAFT.md) · `backend` `legal/phase1-2026.1/03-article-50-assessment-v1.1-DRAFT.md`
- [Policy `phase1-2026.1` — registration settings](legal/phase1-2026.1/04-policy-registration-DRAFT.md) · `backend` `legal/phase1-2026.1/04-policy-registration-DRAFT.md`
- [Brief to US counsel — WillpowerLab](legal/phase1-2026.1/05-us-counsel-brief-DRAFT.md) · `backend` `legal/phase1-2026.1/05-us-counsel-brief-DRAFT.md`
- [Retention and destruction schedule — WillpowerLab Phase-1](legal/phase1-2026.1/06-retention-schedule-v1.0-DRAFT.md) · `backend` `legal/phase1-2026.1/06-retention-schedule-v1.0-DRAFT.md`
- [Vendor actions — who to contact, for what, with the text](legal/phase1-2026.1/07-vendor-actions-DRAFT.md) · `backend` `legal/phase1-2026.1/07-vendor-actions-DRAFT.md`
- [Reconciling the two legal packs](legal/phase1-2026.1/08-RECONCILIATION.md) · `backend` `legal/phase1-2026.1/08-RECONCILIATION.md`
- [WillpowerLab — instruction pack for Polish/EU counsel](legal/phase1-2026.1/09-counsel-cover-note.md) · `backend` `legal/phase1-2026.1/09-counsel-cover-note.md`
- [Privacy Policy 3.1 → 3.2 — the training changes (DRAFT for counsel)](legal/phase1-2026.1/10-training-policy-changes-DRAFT.md) · `backend` `legal/phase1-2026.1/10-training-policy-changes-DRAFT.md`
- [Retention schedule v1.1 — the training rows (DRAFT: counsel checks, founder signs)](legal/phase1-2026.1/11-retention-schedule-v1.1-training-DRAFT.md) · `backend` `legal/phase1-2026.1/11-retention-schedule-v1.1-training-DRAFT.md`
- [Terms of Service 3.1 → 3.2 — the training licence (DRAFT for counsel)](legal/phase1-2026.1/12-terms-training-licence-DRAFT.md) · `backend` `legal/phase1-2026.1/12-terms-training-licence-DRAFT.md`
- [The training switch wording — SIGNED by the founder 2026-10-01](legal/phase1-2026.1/13-training-consent-wording-SIGNED-2026-10-01.md) · `backend` `legal/phase1-2026.1/13-training-consent-wording-SIGNED-2026-10-01.md`
- [Founder determinations of 2 October 2026 — eight answers, one record each](legal/phase1-2026.1/14-founder-determinations-2026-10-02/README.md) · `backend` `legal/phase1-2026.1/14-founder-determinations-2026-10-02/README.md`
- [Determination Q1 — Gate 6a · the coach's blind check of the detector · lawful basis](legal/phase1-2026.1/14-founder-determinations-2026-10-02/q1.md) · `backend` `legal/phase1-2026.1/14-founder-determinations-2026-10-02/q1.md`
- [Determination Q2 — Gate 6a · how long the coach's blind answers are kept](legal/phase1-2026.1/14-founder-determinations-2026-10-02/q2.md) · `backend` `legal/phase1-2026.1/14-founder-determinations-2026-10-02/q2.md`
- [Determination Q3 — Phases 4 and 5 · C1 · another user hearing a clip](legal/phase1-2026.1/14-founder-determinations-2026-10-02/q3.md) · `backend` `legal/phase1-2026.1/14-founder-determinations-2026-10-02/q3.md`
- [Determination Q4 — Phases 4 and 5 · C2 · where the switch is written down](legal/phase1-2026.1/14-founder-determinations-2026-10-02/q4.md) · `backend` `legal/phase1-2026.1/14-founder-determinations-2026-10-02/q4.md`
- [Determination Q5 — Phases 4 and 5 · C3 · the listener's answer as personal data](legal/phase1-2026.1/14-founder-determinations-2026-10-02/q5.md) · `backend` `legal/phase1-2026.1/14-founder-determinations-2026-10-02/q5.md`
- [Determination Q6 — Gate 6d · the employer and school fact](legal/phase1-2026.1/14-founder-determinations-2026-10-02/q6.md) · `backend` `legal/phase1-2026.1/14-founder-determinations-2026-10-02/q6.md`
- [Determination Q7 — Gate 6d · is the mistake-spotter an emotion recognition system](legal/phase1-2026.1/14-founder-determinations-2026-10-02/q7.md) · `backend` `legal/phase1-2026.1/14-founder-determinations-2026-10-02/q7.md`
- [Determination Q8 — Door 2 · question 2 · the coach's sentences about a speaker's passage](legal/phase1-2026.1/14-founder-determinations-2026-10-02/q8.md) · `backend` `legal/phase1-2026.1/14-founder-determinations-2026-10-02/q8.md`
- [The coach's blind check of the detector — privacy line, balancing test, retention row — SIGNED by the founder 2026-10-02](legal/phase1-2026.1/15-coach-blind-check-privacy-line-and-balancing-test-SIGNED-2026-10-02.md) · `backend` `legal/phase1-2026.1/15-coach-blind-check-privacy-line-and-balancing-test-SIGNED-2026-10-02.md`
- [The share switch — Terms and Privacy wording for the next policy version — SIGNED by the founder 2026-10-02](legal/phase1-2026.1/16-share-switch-wording-SIGNED-2026-10-02.md) · `backend` `legal/phase1-2026.1/16-share-switch-wording-SIGNED-2026-10-02.md`
- [Door 2 stays shut for the two coach-word surfaces — the record](legal/phase1-2026.1/17-door-2-coach-word-surfaces-shut-2026-10-02.md) · `backend` `legal/phase1-2026.1/17-door-2-coach-word-surfaces-shut-2026-10-02.md`
- [Retention schedule v1.2 — the blind-check row and the lending rows (for the founder's signature)](legal/phase1-2026.1/18-retention-schedule-v1.2-blind-check-and-lending-DRAFT.md) · `backend` `legal/phase1-2026.1/18-retention-schedule-v1.2-blind-check-and-lending-DRAFT.md`
- [Retention schedule v1.3 — the financial-records row (for the founder's signature)](legal/phase1-2026.1/19-retention-schedule-v1.3-financial-records-DRAFT.md) · `backend` `legal/phase1-2026.1/19-retention-schedule-v1.3-financial-records-DRAFT.md`
- [Retention schedule v1.4 — product records and job evidence (for the founder's signature)](legal/phase1-2026.1/20-retention-schedule-v1.4-product-records-and-job-evidence-DRAFT.md) · `backend` `legal/phase1-2026.1/20-retention-schedule-v1.4-product-records-and-job-evidence-DRAFT.md`
- [Questions for counsel — October 2026](legal/phase1-2026.1/21-counsel-questions-2026-10.md) · `backend` `legal/phase1-2026.1/21-counsel-questions-2026-10.md`
- [Privacy Policy 3.5 and Terms of Service 3.5: every learning pipe, under the training yes — SIGNED by the founder 2026-10-08](legal/phase1-2026.1/22-privacy-terms-3.5-all-learning-SIGNED-2026-10-08.md) · `backend` `legal/phase1-2026.1/22-privacy-terms-3.5-all-learning-SIGNED-2026-10-08.md`
- [The training switch wording, version 2 — SIGNED by the founder 2026-10-08](legal/phase1-2026.1/23-training-consent-wording-v2-SIGNED-2026-10-08.md) · `backend` `legal/phase1-2026.1/23-training-consent-wording-v2-SIGNED-2026-10-08.md`
- [Retention rows for the learning lanes (Privacy 3.5) — SIGNED by the founder 2026-10-08](legal/phase1-2026.1/24-retention-rows-learning-lanes-SIGNED-2026-10-08.md) · `backend` `legal/phase1-2026.1/24-retention-rows-learning-lanes-SIGNED-2026-10-08.md`
- [Privacy Policy 3.6, Terms of Service 3.6, AI notice 3.2: what shipped since 3.5 — SIGNED by the founder 2026-10-15](legal/phase1-2026.1/25-privacy-terms-3.6-new-features-SIGNED-2026-10-15.md) · `backend` `legal/phase1-2026.1/25-privacy-terms-3.6-new-features-SIGNED-2026-10-15.md`
- [The training switch wording, version 3 — SIGNED by the founder 2026-10-15](legal/phase1-2026.1/26-training-consent-wording-v3-SIGNED-2026-10-15.md) · `backend` `legal/phase1-2026.1/26-training-consent-wording-v3-SIGNED-2026-10-15.md`
- [The training switch wording, version 4 — SIGNED by the founder 2026-10-15](legal/phase1-2026.1/27-training-consent-wording-v4-SIGNED-2026-10-15.md) · `backend` `legal/phase1-2026.1/27-training-consent-wording-v4-SIGNED-2026-10-15.md`
- [28 · Privacy 3.7: what Will is given (APPROVED 2026-10-15)](legal/phase1-2026.1/28-privacy-3.7-will-context-APPROVED-2026-10-15.md) · `backend` `legal/phase1-2026.1/28-privacy-3.7-will-context-APPROVED-2026-10-15.md`
- [29 · Terms 3.7 and Privacy 3.8: tokens bought once, the coach's answer free, and what was already live (SIGNED 2026-10-27)](legal/phase1-2026.1/29-terms-3.7-privacy-3.8-tokens-and-what-is-live-SIGNED-2026-10-27.md) · `backend` `legal/phase1-2026.1/29-terms-3.7-privacy-3.8-tokens-and-what-is-live-SIGNED-2026-10-27.md` · Founder-Approved: the sign-off page and the Claude Code chat, 27 October 2026, "I sign as drafted, question 1 A, question 2 A" (N208)
- [30 · Terms 3.8 and Privacy 3.9: the plan's personal answers, "How do you feel?" and WhatsApp sign-in (SIGNED 2026-10-27)](legal/phase1-2026.1/30-terms-3.8-privacy-3.9-the-plan-feelings-and-whatsapp-sign-in-SIGNED-2026-10-27.md) · `backend` `legal/phase1-2026.1/30-terms-3.8-privacy-3.9-the-plan-feelings-and-whatsapp-sign-in-SIGNED-2026-10-27.md` · Founder-Approved: the sign-off page and the Claude Code chat, 27 October 2026, "I sign as drafted, question 1 A, question 2 A" (N217)
- [Phase-1 processing policy `phase1-2026.1` — drafting pack](legal/phase1-2026.1/README.md) · `backend` `legal/phase1-2026.1/README.md`
- [Signing sheet — the 3.5 pack, 8 October 2026 — SIGNED by the founder 2026-10-08](legal/phase1-2026.1/SIGN-3.5-2026-10-08.md) · `backend` `legal/phase1-2026.1/SIGN-3.5-2026-10-08.md`
- [Signed artifacts — what exists, and its fingerprint](legal/phase1-2026.1/SIGNED-ARTIFACTS.md) · `backend` `legal/phase1-2026.1/SIGNED-ARTIFACTS.md`
- [The published Terms and Privacy sequence, recovered from git](legal/phase1-2026.1/accepted-versions/README.md) · `backend` `legal/phase1-2026.1/accepted-versions/README.md`

</details>

## 3. History

Kept as written, because the rules still cite them.

<details><summary>The MLC-2 and MLC-3 programme (1 file)</summary>

- [The MLC-2 and MLC-3 programme](docs/history/MLC-PROGRAMME.md) · `backend` `docs/history/MLC-PROGRAMME.md`

</details>

<details><summary>Audits (10 files)</summary>

- [Phase-1 deletion dependency audit](docs/PHASE1-DELETION-DEPENDENCY-AUDIT.md) · `backend` `docs/PHASE1-DELETION-DEPENDENCY-AUDIT.md`
- [RLS audit — public-schema tables without row level security](docs/RLS-AUDIT.md) · `backend` `docs/RLS-AUDIT.md`
- [Founder queue (from LEDGER.md)](docs/audit/FOUNDER-QUEUE.md) · `backend` `docs/audit/FOUNDER-QUEUE.md`
- [Audit ledger](docs/audit/LEDGER.md) · `backend` `docs/audit/LEDGER.md`
- [Founder answers, Navigation Panel, 6 October 2026 (second export, 13:10 UTC)](docs/audit/PANEL-ANSWERS-2026-10-06-b.md) · `backend` `docs/audit/PANEL-ANSWERS-2026-10-06-b.md`
- [How audit work runs (founder-approved 6 October 2026)](docs/audit/WORKFLOW.md) · `backend` `docs/audit/WORKFLOW.md`
- [Build plan of 7 Oct 2026](docs/audit/build/BUILD-PLAN-2026-10-07.md) · `backend` `docs/audit/build/BUILD-PLAN-2026-10-07.md`
- [Measurement reports](docs/audit/measure/README.md) · `backend` `docs/audit/measure/README.md`
- [ML provenance audit, 2026-09-22 (read-only; no code changed)](docs/audits/2026-09-22-ml-provenance/README.md) · `backend` `docs/audits/2026-09-22-ml-provenance/README.md`
- [Job 1 — critical review of the Willab ML provenance audit](docs/audits/2026-09-22-ml-provenance/job1_review.md) · `backend` `docs/audits/2026-09-22-ml-provenance/job1_review.md`

</details>

<details><summary>Earlier rule pages, indexes and records (15 files)</summary>

- [VERSIONING_SPEC.md — how the ideal text evolved (the retired master-document model)](docs/VERSIONING_SPEC.md) · `backend` `docs/VERSIONING_SPEC.md`
- [Concept — per-user exercise effectiveness (Linear WIL-29)](docs/CONCEPT-per-user-exercise-effectiveness-2026-10-18.md) · `backend` `docs/CONCEPT-per-user-exercise-effectiveness-2026-10-18.md`
- [Founder lock — the AI version of your voice in practice (2026-10-12)](docs/FOUNDER-LOCK-ai-voice-practice-2026-10-12.md) · `backend` `docs/FOUNDER-LOCK-ai-voice-practice-2026-10-12.md`
- [Founder lock · the consent screens (7 October 2026)](docs/FOUNDER-LOCK-consent-screens-2026-10-07.md) · `backend` `docs/FOUNDER-LOCK-consent-screens-2026-10-07.md`
- [Founder lock — the Feedback walk, its look and its motion (2026-10-06)](docs/FOUNDER-LOCK-feedback-walk-2026-10-06.md) · `backend` `docs/FOUNDER-LOCK-feedback-walk-2026-10-06.md`
- [Founder lock — helper words, the paragraph overlay and the practise loop (2026-09-30)](docs/FOUNDER-LOCK-helper-words-2026-09-30.md) · `backend` `docs/FOUNDER-LOCK-helper-words-2026-09-30.md`
- [Founder lock · the recording screens (7 October 2026)](docs/FOUNDER-LOCK-recording-screens-2026-10-07.md) · `backend` `docs/FOUNDER-LOCK-recording-screens-2026-10-07.md`
- [exercise-human-delayed-v1 — the delayed blind human measure (signed by the founder 2026-10-02)](docs/MEASURE-exercise-human-delayed-v1.md) · `backend` `docs/MEASURE-exercise-human-delayed-v1.md`
- [willab token pricing — plan (no code)](docs/PRICING-TOKENS-PLAN.md) · `backend` `docs/PRICING-TOKENS-PLAN.md`
- [Product/legal onboarding and processing flow — PLF-1](docs/PRODUCT-LEGAL-FLOW-PLF-1.md) · `backend` `docs/PRODUCT-LEGAL-FLOW-PLF-1.md`
- [Session log — 2026-08-13/14/15 · the confidence unification, pricing v3, and the publish rescue](docs/SESSION-2026-08-14-confidence-unification.md) · `backend` `docs/SESSION-2026-08-14-confidence-unification.md`
- [Sign: nine praise lines and three rewrite moves (October 2026)](docs/SIGN-praise-lines-and-rewrite-moves-2026-10.md) · `backend` `docs/SIGN-praise-lines-and-rewrite-moves-2026-10.md`
- [CLAUDE.md — willab backend](docs/history/CLAUDE-2026-10-11.md) · `backend` `docs/history/CLAUDE-2026-10-11.md`
- [HANDOFF — frontend (willab), 2026-08-14](https://github.com/wilplus/frontend-cursor/blob/main/docs/HANDOFF.md) · `frontend` `docs/HANDOFF.md`
- [WillpowerLab — frontend (willab)](https://github.com/wilplus/frontend-cursor/blob/main/docs/history/CLAUDE-2026-10-11.md) · `frontend` `docs/history/CLAUDE-2026-10-11.md`

</details>

<details><summary>Plans and specs that later rules replaced (docs audit, 2026-10-26; 6 files)</summary>

- [willab backlog — status as of 2026-07-23](docs/BACKLOG.md) · `backend` `docs/BACKLOG.md`
- [Product-manager backlog — recurring processes and deferred unlocks](docs/PRODUCT-MANAGER-BACKLOG.md) · `backend` `docs/PRODUCT-MANAGER-BACKLOG.md`
- [Pipeline work ledger](docs/PIPELINE_WORK_LEDGER.md) · `backend` `docs/PIPELINE_WORK_LEDGER.md`
- [The coach panel redesign · build plan P2 to P7](docs/COACH-PANEL-BUILD-PLAN-P2-P7.md) · `backend` `docs/COACH-PANEL-BUILD-PLAN-P2-P7.md`
- [Ideal-text flow — how the app talks to the user between takes](https://github.com/wilplus/frontend-cursor/blob/main/docs/ideal-text-flow-communication.md) · `frontend` `docs/ideal-text-flow-communication.md`
- [Designer brief — Wave 5 (October 2026)](https://github.com/wilplus/frontend-cursor/blob/main/docs/DESIGNER-BRIEF-wave5-2026-10.md) · `frontend` `docs/DESIGNER-BRIEF-wave5-2026-10.md`

</details>

## 4. Archive

Out of date, but code, tests or the legal pack still name them, so they stay in the folders for now (N107).

<details><summary>Prompts written for coding agents (8 files)</summary>

- [BE prompt — The Life Panel](docs/PROMPT-BE-life-panel.md) · `backend` `docs/PROMPT-BE-life-panel.md`
- [BE handoff — token pricing (Phase 1)](docs/PROMPT-BE-token-pricing.md) · `backend` `docs/PROMPT-BE-token-pricing.md`
- [PROMPT — build the drift layer (execute now)](docs/PROMPT-drift-layer.md) · `backend` `docs/PROMPT-drift-layer.md`
- [The Life Panel — implementation document](docs/PROMPT-life-panel.md) · `backend` `docs/PROMPT-life-panel.md`
- [Prompt registry & golden evals](docs/prompt_evals.md) · `backend` `docs/prompt_evals.md`
- [WillLab community — content model](services/prompts/community_content_strategy.md) · `backend` `services/prompts/community_content_strategy.md`
- [willab - willpower lab 🎙️ — App description (single source of truth)](https://github.com/wilplus/frontend-cursor/blob/main/.taskmaster/docs/APP_DESCRIPTION.md) · `frontend` `.taskmaster/docs/APP_DESCRIPTION.md`
- [Task Master docs (willab - willpower lab 🎙️)](https://github.com/wilplus/frontend-cursor/blob/main/.taskmaster/docs/README.md) · `frontend` `.taskmaster/docs/README.md`

</details>

<details><summary>Session handoffs (1 file)</summary>

- [Handoffs — dated messages between the two repos (backend copy)](docs/handoffs/README.md) · `backend` `docs/handoffs/README.md`

</details>

<details><summary>Specs that describe retired features (docs audit, 2026-10-26; 4 files)</summary>

- [SPEC — The lock-in loop, offers, and the coach panel](docs/SPEC-lockin-loop-and-coach-panel.md) · `backend` `docs/SPEC-lockin-loop-and-coach-panel.md`
- [SPEC — the in-thread top-up card (Lounge)](https://github.com/wilplus/frontend-cursor/blob/main/docs/SPEC-lounge-topup-card.md) · `frontend` `docs/SPEC-lounge-topup-card.md`
- [The two coach feedback lanes](https://github.com/wilplus/frontend-cursor/blob/main/docs/COACH-FEEDBACK-LANES.md) · `frontend` `docs/COACH-FEEDBACK-LANES.md`
- [Coach review flow — judgement first, one action per screen](https://github.com/wilplus/frontend-cursor/blob/main/docs/coach-review-flow/SPEC.md) · `frontend` `docs/coach-review-flow/SPEC.md`

</details>

## 5. Left main

On 21 October 2026, 183 docs left `main` (N107): the ones labelled Archive that nothing names, the MLC
chain (now one page, [`docs/history/MLC-PROGRAMME.md`](docs/history/MLC-PROGRAMME.md)) and the History nothing
cites. Git keeps every one. Browse them at the last commit that had them:
[backend `docs/`](https://github.com/wilplus/backend-cursor/tree/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs) and
[frontend `docs/`](https://github.com/wilplus/frontend-cursor/tree/501da43874460770310b24fafc664c4f5e606114/docs).

<details><summary>The 183 docs, each at its last version</summary>

- [Claude Handoff — Confident Moment Coaching Bundle](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/CLAUDE-HANDOFF-CONFIDENT-MOMENT-2026-09-11.md) · `backend` `docs/CLAUDE-HANDOFF-CONFIDENT-MOMENT-2026-09-11.md`
- [MLC-3 Coach Guidance and Exercise Delivery — D3](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/MLC3-COACH-GUIDANCE-DELIVERY-D3.md) · `backend` `docs/MLC3-COACH-GUIDANCE-DELIVERY-D3.md`
- [MLC-3 Coach Guidance and Exercise Delivery D3 — Release Preparation Packet](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/MLC3-COACH-GUIDANCE-DELIVERY-IMPLEMENTATION.md) · `backend` `docs/MLC3-COACH-GUIDANCE-DELIVERY-IMPLEMENTATION.md`
- [MLC-3 Coach Inline Exercise Authoring D5](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/MLC3-COACH-INLINE-EXERCISE-AUTHORING-D5.md) · `backend` `docs/MLC3-COACH-INLINE-EXERCISE-AUTHORING-D5.md`
- [MLC-3 Coach Inline Exercise Authoring D5 — Release Review Packet](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/MLC3-COACH-INLINE-EXERCISE-AUTHORING-IMPLEMENTATION.md) · `backend` `docs/MLC3-COACH-INLINE-EXERCISE-AUTHORING-IMPLEMENTATION.md`
- [MLC-3 Confident Moment Coaching Bundle — Chunk 2B implementation review D4](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/MLC3-CONFIDENT-MOMENT-CHUNK2B-IMPLEMENTATION-REVIEW-D4.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-CHUNK2B-IMPLEMENTATION-REVIEW-D4.md`
- [MLC-3 Confident Moment Coaching Bundle — Chunk 2B implementation review D5](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/MLC3-CONFIDENT-MOMENT-CHUNK2B-IMPLEMENTATION-REVIEW-D5.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-CHUNK2B-IMPLEMENTATION-REVIEW-D5.md`
- [MLC-3 Confident Moment Coaching Bundle — Founder Contract Delta D3](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/MLC3-CONFIDENT-MOMENT-COACHING-CONTRACT-DELTA-D3.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-CONTRACT-DELTA-D3.md`
- [MLC-3 Confident Moment Coaching Bundle — Per-item Currentness Amendment D12](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/MLC3-CONFIDENT-MOMENT-COACHING-CURRENTNESS-AMENDMENT-D12.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-CURRENTNESS-AMENDMENT-D12.md`
- [MLC-3 Confident Moment Coaching Bundle — Interface Manifest D6](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/MLC3-CONFIDENT-MOMENT-COACHING-INTERFACE-MANIFEST-D6.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-INTERFACE-MANIFEST-D6.md`
- [MLC-3 Confident Moment Point 7 — frontend base-commit errata](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/MLC3-CONFIDENT-MOMENT-POINT7-FRONTEND-BASE-COMMIT-ERRATA.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-POINT7-FRONTEND-BASE-COMMIT-ERRATA.md`
- [MLC-3 Confident Moment Coaching Bundle — Point 7 Implementation Evidence](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/MLC3-CONFIDENT-MOMENT-POINT7-IMPLEMENTATION-EVIDENCE.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-POINT7-IMPLEMENTATION-EVIDENCE.md`
- [MLC-3 exercise dependency audit](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/MLC3-EXERCISE-DEPENDENCY-AUDIT.md) · `backend` `docs/MLC3-EXERCISE-DEPENDENCY-AUDIT.md`
- [MLC-3 First-Client Service D2 — Local Implementation Review Packet](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/MLC3-FIRST-CLIENT-SERVICE-IMPLEMENTATION.md) · `backend` `docs/MLC3-FIRST-CLIENT-SERVICE-IMPLEMENTATION.md`
- [MLC-3 Founder Canary Activation Readiness](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/MLC3-FOUNDER-CANARY-ACTIVATION-READINESS.md) · `backend` `docs/MLC3-FOUNDER-CANARY-ACTIVATION-READINESS.md`
- [MLC-3 Founder Canary Activation-Readiness Review](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/MLC3-FOUNDER-CANARY-ACTIVATION-REVIEW.md) · `backend` `docs/MLC3-FOUNDER-CANARY-ACTIVATION-REVIEW.md`
- [MLC-3 general availability — activation runbook](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/MLC3-GA-ACTIVATION-RUNBOOK.md) · `backend` `docs/MLC3-GA-ACTIVATION-RUNBOOK.md`
- [MLC-3 General-User Service Rollout D4 — Disabled Implementation Review](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/MLC3-GENERAL-USER-SERVICE-D4-IMPLEMENTATION.md) · `backend` `docs/MLC3-GENERAL-USER-SERVICE-D4-IMPLEMENTATION.md`
- [MLC-3 General-User Service D4 — Offer Resolver-Chain Correction](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/MLC3-GENERAL-USER-SERVICE-D4-RELEASE-CORRECTION-2.md) · `backend` `docs/MLC3-GENERAL-USER-SERVICE-D4-RELEASE-CORRECTION-2.md`
- [MLC-3 General-User Service D4 — Production-Shape Release Correction](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/MLC3-GENERAL-USER-SERVICE-D4-RELEASE-CORRECTION.md) · `backend` `docs/MLC3-GENERAL-USER-SERVICE-D4-RELEASE-CORRECTION.md`
- [MLC-3 General-User Service Rollout D4 — Release Packet](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/MLC3-GENERAL-USER-SERVICE-D4-RELEASE.md) · `backend` `docs/MLC3-GENERAL-USER-SERVICE-D4-RELEASE.md`
- [M3-3 dark assignment frames — implementation review](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/MLC3-M3-3-IMPLEMENTATION-REVIEW.md) · `backend` `docs/MLC3-M3-3-IMPLEMENTATION-REVIEW.md`
- [MLC-3 N1 Proximity Foundation — Corrective Review Packet](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/MLC3-N1-PROXIMITY-CORRECTION-REVIEW.md) · `backend` `docs/MLC3-N1-PROXIMITY-CORRECTION-REVIEW.md`
- [BE prompt — the 2026-07-27 backlog wave](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/PROMPT-BE-2026-07-27-backlog-wave.md) · `backend` `docs/PROMPT-BE-2026-07-27-backlog-wave.md`
- [PROMPT — BE: `prior_edit` re-offer + re-apply telemetry (T1 · 1.2)](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/PROMPT-BE-prior-edit-2026-07-28.md) · `backend` `docs/PROMPT-BE-prior-edit-2026-07-28.md`
- [FE handoff — founder items 2026-07-17 (paste into a fresh Claude session in `frontend-cursor`)](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/PROMPT-FE-2026-07-17.md) · `backend` `docs/PROMPT-FE-2026-07-17.md`
- [FE handoff — the full versioning + recording wave (2026-07-23)](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/PROMPT-FE-2026-07-23-consolidated.md) · `backend` `docs/PROMPT-FE-2026-07-23-consolidated.md`
- [FE prompt — the 2026-07-27 backlog wave](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/PROMPT-FE-2026-07-27-backlog-wave.md) · `backend` `docs/PROMPT-FE-2026-07-27-backlog-wave.md`
- [BE answers — the corpus index: labelled badge, archive, and your open questions](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/PROMPT-FE-2026-07-30-corpus-index.md) · `backend` `docs/PROMPT-FE-2026-07-30-corpus-index.md`
- [FE HANDOFF — Community Content Studio (one button in the CMS)](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/PROMPT-FE-community-content-studio.md) · `backend` `docs/PROMPT-FE-community-content-studio.md`
- [Frontend brief: exercise routing, steps 1–3 (2026-09-28)](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/PROMPT-FE-exercise-routing-2026-09-28.md) · `backend` `docs/PROMPT-FE-exercise-routing-2026-09-28.md`
- [FE prompt — The Key-Moments Game (Engine 5)](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/PROMPT-FE-game.md) · `backend` `docs/PROMPT-FE-game.md`
- [PROMPT — FE: add & rearrange text in the ideal-text area while recording (T1 · 1.2)](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/PROMPT-FE-ideal-text-add-rearrange-2026-07-28.md) · `backend` `docs/PROMPT-FE-ideal-text-add-rearrange-2026-07-28.md`
- [FE handoff — generated Journal cover images (paste into a fresh Claude session in `frontend-cursor`)](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/PROMPT-FE-journal-cover-images.md) · `backend` `docs/PROMPT-FE-journal-cover-images.md`
- [FE prompt — The Life Panel](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/PROMPT-FE-life-panel.md) · `backend` `docs/PROMPT-FE-life-panel.md`
- [FE handoff — polish as suggestions, Approve all, re-read mic (paste into `frontend-cursor`)](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/PROMPT-FE-polish-suggestions-2026-07-18.md) · `backend` `docs/PROMPT-FE-polish-suggestions-2026-07-18.md`
- [FE handoff — the speaker-sex field](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/PROMPT-FE-speaker-sex.md) · `backend` `docs/PROMPT-FE-speaker-sex.md`
- [FE prompt — Coach Star Verdict](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/PROMPT-FE-star-verdict.md) · `backend` `docs/PROMPT-FE-star-verdict.md`
- [FE prompt — Training corpus, rev 2 (answers to your handoff)](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/PROMPT-FE-training-corpus-rev2.md) · `backend` `docs/PROMPT-FE-training-corpus-rev2.md`
- [FE prompt — Training corpus, rev 3: answering §7 (the empty Polish import)](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/PROMPT-FE-training-corpus-rev3.md) · `backend` `docs/PROMPT-FE-training-corpus-rev3.md`
- [FE prompt — Training corpus, rev 4: answering your §9](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/PROMPT-FE-training-corpus-rev4.md) · `backend` `docs/PROMPT-FE-training-corpus-rev4.md`
- [FE prompt — Training corpus: audio import + confidence labelling](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/PROMPT-FE-training-corpus.md) · `backend` `docs/PROMPT-FE-training-corpus.md`
- [PROMPT — Community Content Studio (one button in the CMS → 3 community posts)](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/PROMPT-community-content-studio.md) · `backend` `docs/PROMPT-community-content-studio.md`
- [Ledger splitter brief (read-only; text only, no code reading needed)](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/audit/build/SPLIT_BRIEF.md) · `backend` `docs/audit/build/SPLIT_BRIEF.md`
- [V4 Phase 1 · one row per pull request](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/audit/build/V4-PHASE1-ROWS.md) · `backend` `docs/audit/build/V4-PHASE1-ROWS.md`
- [Audit questions — decisions needed before cleanup — 2026-09-13](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/audits/2026-09-13-audit-questions.md) · `backend` `docs/audits/2026-09-13-audit-questions.md`
- [Engineering audit prompt — tests, complexity, abstractions, glue code](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/audits/2026-09-13-engineering-audit-prompt.md) · `backend` `docs/audits/2026-09-13-engineering-audit-prompt.md`
- [Engineering audit — backend (`backend-cursor`) — 2026-09-13](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/audits/2026-09-13-engineering-audit.md) · `backend` `docs/audits/2026-09-13-engineering-audit.md`
- [Audit decisions — founder answers to the 2026-09-13 questions — 2026-09-14](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/audits/2026-09-14-audit-decisions.md) · `backend` `docs/audits/2026-09-14-audit-decisions.md`
- [Proposal — a rehearsal lane seeded from a production-shaped dump](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/audits/2026-09-14-proposal-production-shaped-rehearsal-lane.md) · `backend` `docs/audits/2026-09-14-proposal-production-shaped-rehearsal-lane.md`
- [Prompt for the senior engineer — keep the ML code aligned with the locked architecture](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/audits/2026-09-22-ml-provenance/engineer_prompt.md) · `backend` `docs/audits/2026-09-22-ml-provenance/engineer_prompt.md`
- [Prompts for the five jobs](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/audits/2026-09-22-ml-provenance/job_prompts.md) · `backend` `docs/audits/2026-09-22-ml-provenance/job_prompts.md`
- [willab — FE ↔ BE Compatibility Audit (Lounge & Coach UX batch)](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/be-compat-audit.md) · `backend` `docs/be-compat-audit.md`
- [Backend prompt: Flow-step overrides (skip metric questions / skip post questions)](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/cursor-prompts/BACKEND_FLOW_STEPS_OVERRIDES.md) · `backend` `docs/cursor-prompts/BACKEND_FLOW_STEPS_OVERRIDES.md`
- [Prompt for Claude — continue Confident Moment Chunk 2B](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/cursor-prompts/CLAUDE-CONTINUE-CONFIDENT-MOMENT-CHUNK2B.md) · `backend` `docs/cursor-prompts/CLAUDE-CONTINUE-CONFIDENT-MOMENT-CHUNK2B.md`
- [PARKED — Lounge intent-router + persona polish](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/cursor-prompts/PARKED-intent-router-and-lounge-persona.md) · `backend` `docs/cursor-prompts/PARKED-intent-router-and-lounge-persona.md`
- [BE → FE: the legacy credits are settled. The balance has two halves now.](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/handoffs/BE-ANSWER-legacy-credits-2026-08-01.md) · `backend` `docs/handoffs/BE-ANSWER-legacy-credits-2026-08-01.md`
- [BE → FE: the plans are sellable. Answers, and two bugs you did not ask about.](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/handoffs/BE-ANSWER-plan-checkout-2026-07-31.md) · `backend` `docs/handoffs/BE-ANSWER-plan-checkout-2026-07-31.md`
- [BE answer — stress lane deleted, peer-review validation loop wired](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/handoffs/BE-ANSWER-stress-lane-deletion-2026-08-03.md) · `backend` `docs/handoffs/BE-ANSWER-stress-lane-deletion-2026-08-03.md`
- [BE → FE handoff — add & rearrange text in the ideal-text area while recording (T1 · 1.2)](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/handoffs/BE-HANDOFF-ideal-text-add-rearrange.md) · `backend` `docs/handoffs/BE-HANDOFF-ideal-text-add-rearrange.md`
- [BE → FE handoff — slide linkage on the ideal-text GET (answers FE PR #222)](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/handoffs/BE-HANDOFF-ideal-text-slide-linkage.md) · `backend` `docs/handoffs/BE-HANDOFF-ideal-text-slide-linkage.md`
- [BE handoff — Session-1 completion gate (≥1 charisma + ≥1 stress + ≥60s)](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/handoffs/BE-HANDOFF-tab-session1-completion-gate.md) · `backend` `docs/handoffs/BE-HANDOFF-tab-session1-completion-gate.md`
- [BE handoff — split the comment sinks (user-visible vs. pipeline-only)](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/handoffs/BE-HANDOFF-tab1-comment-sink-split.md) · `backend` `docs/handoffs/BE-HANDOFF-tab1-comment-sink-split.md`
- [BE handoff — Tab 1: >5-word-change save gate (anti-lazy-admin)](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/handoffs/BE-HANDOFF-tab1-edit-gate.md) · `backend` `docs/handoffs/BE-HANDOFF-tab1-edit-gate.md`
- [BE handoff — Admin Tab 1: snippet list re-rank + transcript hiding](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/handoffs/BE-HANDOFF-tab1-snippet-rerank.md) · `backend` `docs/handoffs/BE-HANDOFF-tab1-snippet-rerank.md`
- [BE handoff — Admin Tab 3: private admin notes panel](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/handoffs/BE-HANDOFF-tab3-private-admin-notes.md) · `backend` `docs/handoffs/BE-HANDOFF-tab3-private-admin-notes.md`
- [BE handoff — Task 7: "4h human-at-heart" CTA + post-signup confirmation](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/handoffs/BE-HANDOFF-task7-signup-cta-human-at-heart.md) · `backend` `docs/handoffs/BE-HANDOFF-task7-signup-cta-human-at-heart.md`
- [BE handoff — Task 8: data-sharing consent modal at session 2](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/handoffs/BE-HANDOFF-task8-sharing-consent-modal.md) · `backend` `docs/handoffs/BE-HANDOFF-task8-sharing-consent-modal.md`
- [BE handoff — Task 9: admin Tab 4 (Files) Next.js page](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/handoffs/BE-HANDOFF-task9-files-tab-ui.md) · `backend` `docs/handoffs/BE-HANDOFF-task9-files-tab-ui.md`
- [DEBUG HANDOFF — 2026-08-10 evening session](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/handoffs/DEBUG-HANDOFF-2026-08-10.md) · `backend` `docs/handoffs/DEBUG-HANDOFF-2026-08-10.md`
- [FE handoff — the backlog wave (2026-07-27)](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/handoffs/FE-HANDOFF-2026-07-27-backlog-wave.md) · `backend` `docs/handoffs/FE-HANDOFF-2026-07-27-backlog-wave.md`
- [FE handoff — the Life Panel document dock, answered (2026-07-31)](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/handoffs/FE-HANDOFF-2026-07-31-life-panel-doc-dock.md) · `backend` `docs/handoffs/FE-HANDOFF-2026-07-31-life-panel-doc-dock.md`
- [FE handoff — one BFF idiom + lab upload defenses (2026-08-03)](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/handoffs/FE-HANDOFF-2026-08-03-bff-and-upload-defenses.md) · `backend` `docs/handoffs/FE-HANDOFF-2026-08-03-bff-and-upload-defenses.md`
- [FE handoff — the monthly + quarterly reviews (piece 5, 2026-08-03)](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/handoffs/FE-HANDOFF-2026-08-03-life-period-reviews.md) · `backend` `docs/handoffs/FE-HANDOFF-2026-08-03-life-period-reviews.md`
- [FE handoff — the block variant PICKER, revisions & restore (2026-08-03)](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/handoffs/FE-HANDOFF-2026-08-03-variant-picker.md) · `backend` `docs/handoffs/FE-HANDOFF-2026-08-03-variant-picker.md`
- [FE handoff — wins → proposed principles (piece 6, 2026-08-03)](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/handoffs/FE-HANDOFF-2026-08-03-wins-derive.md) · `backend` `docs/handoffs/FE-HANDOFF-2026-08-03-wins-derive.md`
- [FE handoff — coaching chat STEP 2 becomes the peer-review flag](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/handoffs/FE-HANDOFF-2026-08-04-step2-peer-review.md) · `backend` `docs/handoffs/FE-HANDOFF-2026-08-04-step2-peer-review.md`
- [Take Feedback Policy v3 — ML/data review packet](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/take-feedback-policy-v3-ml-review.md) · `backend` `docs/take-feedback-policy-v3-ml-review.md`
- [willab BE → FE handoff — last-pass before test & clear](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/willab_be_handoff_fe_lastpass.md) · `backend` `docs/willab_be_handoff_fe_lastpass.md`
- [MLC-2 Confidence founder-canary activation runbook](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/work-items/mlc2-confidence-founder-canary-activation-runbook.md) · `backend` `docs/work-items/mlc2-confidence-founder-canary-activation-runbook.md`
- [MLC-2 Slice 6 — Founder-only Confidence canary readiness](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/work-items/mlc2-confidence-slice-6-readiness.md) · `backend` `docs/work-items/mlc2-confidence-slice-6-readiness.md`
- [MLC-2 Slice 6A — Founder consent and recurring readiness remediation](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/work-items/mlc2-confidence-slice-6a-readiness-remediation.md) · `backend` `docs/work-items/mlc2-confidence-slice-6a-readiness-remediation.md`
- [MLC-2 Foundation Slice 1](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/work-items/mlc2-foundation-slice-1.md) · `backend` `docs/work-items/mlc2-foundation-slice-1.md`
- [MLC-2 Foundation Slice 2 — Database Rehearsal and Hardening](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/work-items/mlc2-foundation-slice-2.md) · `backend` `docs/work-items/mlc2-foundation-slice-2.md`
- [MLC-2 Foundation Slice 3 — Confidence Audit and Dark Contracts](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/work-items/mlc2-foundation-slice-3.md) · `backend` `docs/work-items/mlc2-foundation-slice-3.md`
- [MLC-2 Foundation Slice 4 — Dark Confidence Producer Integration](https://github.com/wilplus/backend-cursor/blob/ca58853e58fe7f0b6c3f2b212317f795de69f420/docs/work-items/mlc2-foundation-slice-4.md) · `backend` `docs/work-items/mlc2-foundation-slice-4.md`
- [Admin notification when a lesson is complete](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/ADMIN_LESSON_COMPLETE_NOTIFICATION.md) · `frontend` `docs/ADMIN_LESSON_COMPLETE_NOTIFICATION.md`
- [Admin Recording Import MVP](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/ADMIN_RECORDING_IMPORT_MVP.md) · `frontend` `docs/ADMIN_RECORDING_IMPORT_MVP.md`
- [Willab Admin Redesign Implementation](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/ADMIN_REDESIGN_IMPLEMENTATION.md) · `frontend` `docs/ADMIN_REDESIGN_IMPLEMENTATION.md`
- [Backend guide: student homework without post-recording questions](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/BACKEND_WITHOUT_POST_RECORDING_QUESTIONS.md) · `frontend` `docs/BACKEND_WITHOUT_POST_RECORDING_QUESTIONS.md`
- [Debug plan: which of the 3 metric-step failure points is failing](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/DEBUG-METRIC-STEP-PLAN.md) · `frontend` `docs/DEBUG-METRIC-STEP-PLAN.md`
- [Domain migration: `willonski.com` → `willpowerlab.com`](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/DOMAIN_MIGRATION_willpowerlab.md) · `frontend` `docs/DOMAIN_MIGRATION_willpowerlab.md`
- [BE handoff — Training corpus (FE side is live on `main`)](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/HANDOFF-BE-2026-07-28-training-corpus.md) · `frontend` `docs/HANDOFF-BE-2026-07-28-training-corpus.md`
- [BE handoff — Voice-game + star verdict (FE side is live on `main`)](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/HANDOFF-BE-2026-07-28-voice-game.md) · `frontend` `docs/HANDOFF-BE-2026-07-28-voice-game.md`
- [BE handoff — the `language` field: already shipped, and that was the problem](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/HANDOFF-BE-2026-07-29-corpus-language.md) · `frontend` `docs/HANDOFF-BE-2026-07-29-corpus-language.md`
- [BE handoff — Training corpus, FE answer to rev 3](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/HANDOFF-BE-2026-07-29-corpus-rev3.md) · `frontend` `docs/HANDOFF-BE-2026-07-29-corpus-rev3.md`
- [BE handoff — confident voice as the labelling engine, star video, and the deletion that is BLOCKED](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/HANDOFF-BE-2026-07-30-confident-voice-and-star-video.md) · `frontend` `docs/HANDOFF-BE-2026-07-30-confident-voice-and-star-video.md`
- [BE handoff — `direction_label` is about to lose its only writer, and that breaks L2](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/HANDOFF-BE-2026-07-30-direction-label.md) · `frontend` `docs/HANDOFF-BE-2026-07-30-direction-label.md`
- [FE → BE — block variant picker: one anchoring assumption to confirm before the flag flips](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/HANDOFF-BE-2026-08-03-block-variants-anchoring.md) · `frontend` `docs/HANDOFF-BE-2026-08-03-block-variants-anchoring.md`
- [BE handoff — delete the stress lane, wire the peer-review validation loop](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/HANDOFF-BE-2026-08-03-stress-lane-deletion-and-peer-review.md) · `frontend` `docs/HANDOFF-BE-2026-08-03-stress-lane-deletion-and-peer-review.md`
- [HANDOFF — willab pricing & billing surfaces (frontend)](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/HANDOFF-FE-2026-08-13-pricing-and-billing.md) · `frontend` `docs/HANDOFF-FE-2026-08-13-pricing-and-billing.md`
- [Handoff — Voice Game Bubble + Beta Badge](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/HANDOFF-game-bubble-and-beta-badge.md) · `frontend` `docs/HANDOFF-game-bubble-and-beta-badge.md`
- [HomeworkFlowCard — Architecture Reference](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/HOMEWORK_FLOW_CARD_ARCHITECTURE.md) · `frontend` `docs/HOMEWORK_FLOW_CARD_ARCHITECTURE.md`
- [ML 1.0 labeling guide](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/ML_LABELING_1_0.md) · `frontend` `docs/ML_LABELING_1_0.md`
- [Panel-State Matrix — `/chat` surface (v1)](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/PANEL-STATE-MATRIX.md) · `frontend` `docs/PANEL-STATE-MATRIX.md`
- [Recording Data Points](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/RECORDING_DATA_POINTS.md) · `frontend` `docs/RECORDING_DATA_POINTS.md`
- [Sniper ratings & baseline — backend directions](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/SNIPER_RATINGS_BACKEND.md) · `frontend` `docs/SNIPER_RATINGS_BACKEND.md`
- [Sniper (Strength/Pace Dartboard) — Settings History](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/SNIPER_SETTINGS_HISTORY.md) · `frontend` `docs/SNIPER_SETTINGS_HISTORY.md`
- [Frontend styling guidelines](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/STYLING_GUIDELINES.md) · `frontend` `docs/STYLING_GUIDELINES.md`
- [Timer countdown fix checklist](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/TIMER_COUNTDOWN_FIX_CHECKLIST.md) · `frontend` `docs/TIMER_COUNTDOWN_FIX_CHECKLIST.md`
- [What’s in place & edge cases](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/WHATS_IN_PLACE_AND_EDGE_CASES.md) · `frontend` `docs/WHATS_IN_PLACE_AND_EDGE_CASES.md`
- [Admin Dashboard Implementation Summary](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/ADMIN_DASHBOARD_IMPLEMENTATION.md) · `frontend` `docs/archive/ADMIN_DASHBOARD_IMPLEMENTATION.md`
- [Admin Feedback Flow: Storing & Using Admin Comments](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/ADMIN_FEEDBACK_FLOW.md) · `frontend` `docs/archive/ADMIN_FEEDBACK_FLOW.md`
- [API JSON request/response spec — current vs v1 (theme + 1 preQ + 3 command options)](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/API_JSON_SPEC_CURRENT_AND_V1.md) · `frontend` `docs/archive/API_JSON_SPEC_CURRENT_AND_V1.md`
- [Backend: Use Admin Feedback in AI Analysis](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/BACKEND_ADMIN_FEEDBACK_USAGE.md) · `frontend` `docs/archive/BACKEND_ADMIN_FEEDBACK_USAGE.md`
- [Backend Development vs Production Workflow](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/BACKEND_DEV_PROD_WORKFLOW.md) · `frontend` `docs/archive/BACKEND_DEV_PROD_WORKFLOW.md`
- [Backend Email Link Fix: Production URL Issue](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/BACKEND_EMAIL_LINK_FIX.md) · `frontend` `docs/archive/BACKEND_EMAIL_LINK_FIX.md`
- [Backend Prompt: Admin Email with Correct Feedback Link](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/BACKEND_EMAIL_LINK_PROMPT.md) · `frontend` `docs/archive/BACKEND_EMAIL_LINK_PROMPT.md`
- [Backend Fix: Enable Real OpenAI Analysis (Remove Mock Data)](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/BACKEND_ENABLE_REAL_OPENAI.md) · `frontend` `docs/archive/BACKEND_ENABLE_REAL_OPENAI.md`
- [Backend Environment Variables: Update Checklist](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/BACKEND_ENV_UPDATE_CHECKLIST.md) · `frontend` `docs/archive/BACKEND_ENV_UPDATE_CHECKLIST.md`
- [Fix Mock Data in Your Backend](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/BACKEND_FIX_MOCK_DATA.md) · `frontend` `docs/archive/BACKEND_FIX_MOCK_DATA.md`
- [Backend Implementation: Post-Recording Questions & Performance Scoring](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/BACKEND_POST_QUESTIONS_SCORING.md) · `frontend` `docs/archive/BACKEND_POST_QUESTIONS_SCORING.md`
- [Backend Fix: Questionnaire Flow Integration](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/BACKEND_QUESTIONNAIRE_FLOW_FIX.md) · `frontend` `docs/archive/BACKEND_QUESTIONNAIRE_FLOW_FIX.md`
- [Backend Integration: Pre-Recording Questionnaire](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/BACKEND_QUESTIONNAIRE_INTEGRATION.md) · `frontend` `docs/archive/BACKEND_QUESTIONNAIRE_INTEGRATION.md`
- [Backend Implementation Prompt: Questionnaire Flow](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/BACKEND_QUESTIONNAIRE_PROMPT.md) · `frontend` `docs/archive/BACKEND_QUESTIONNAIRE_PROMPT.md`
- [Backend Checklist: Why Old Recordings Aren't Showing](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/BACKEND_RECORDINGS_CHECKLIST.md) · `frontend` `docs/archive/BACKEND_RECORDINGS_CHECKLIST.md`
- [Backend Implementation: Solo-Relevant Scoring System](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/BACKEND_SOLO_RELEVANT_SCORING.md) · `frontend` `docs/archive/BACKEND_SOLO_RELEVANT_SCORING.md`
- [Backend Updates After Vercel Deployment](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/BACKEND_UPDATE_AFTER_VERCEL.md) · `frontend` `docs/archive/BACKEND_UPDATE_AFTER_VERCEL.md`
- [Clean Git History: Remove Large Files](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/CLEAN_GIT_HISTORY.md) · `frontend` `docs/archive/CLEAN_GIT_HISTORY.md`
- [Development vs Production: OpenAI Analysis & Email Flow](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/DEVELOPMENT_VS_PRODUCTION_GUIDE.md) · `frontend` `docs/archive/DEVELOPMENT_VS_PRODUCTION_GUIDE.md`
- [Final Implementation Checklist](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/FINAL_IMPLEMENTATION_CHECKLIST.md) · `frontend` `docs/archive/FINAL_IMPLEMENTATION_CHECKLIST.md`
- [Fix: Remove node_modules from Git](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/FIX_GIT_NODE_MODULES.md) · `frontend` `docs/archive/FIX_GIT_NODE_MODULES.md`
- [Fix: App Won't Host on Localhost](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/FIX_LOCALHOST_ISSUE.md) · `frontend` `docs/archive/FIX_LOCALHOST_ISSUE.md`
- [Flask Backend Setup for Supabase JWT Verification](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/FLASK_BACKEND_SETUP.md) · `frontend` `docs/archive/FLASK_BACKEND_SETUP.md`
- [Frontend: Email Link Debugging Guide](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/FRONTEND_EMAIL_LINK_DEBUG.md) · `frontend` `docs/archive/FRONTEND_EMAIL_LINK_DEBUG.md`
- [Frontend: Email Link Setup Complete ✅](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/FRONTEND_EMAIL_LINK_SETUP.md) · `frontend` `docs/archive/FRONTEND_EMAIL_LINK_SETUP.md`
- [Frontend Implementation Summary](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/FRONTEND_IMPLEMENTATION_SUMMARY.md) · `frontend` `docs/archive/FRONTEND_IMPLEMENTATION_SUMMARY.md`
- [Frontend: Redirect Fix for Email Links](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/FRONTEND_REDIRECT_FIX.md) · `frontend` `docs/archive/FRONTEND_REDIRECT_FIX.md`
- [Frontend UUID Verification: Post-Questions](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/FRONTEND_UUID_VERIFICATION.md) · `frontend` `docs/archive/FRONTEND_UUID_VERIFICATION.md`
- [How to See Real OpenAI Analysis (Not Mock Data)](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/HOW_TO_SEE_REAL_ANALYSIS.md) · `frontend` `docs/archive/HOW_TO_SEE_REAL_ANALYSIS.md`
- [Implementation Summary: Questionnaire Flow](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/IMPLEMENTATION_SUMMARY.md) · `frontend` `docs/archive/IMPLEMENTATION_SUMMARY.md`
- [Password Reset Troubleshooting Guide](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/PASSWORD_RESET_TROUBLESHOOTING.md) · `frontend` `docs/archive/PASSWORD_RESET_TROUBLESHOOTING.md`
- [Post-Recording Questions Implementation Summary](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/POST_QUESTIONS_IMPLEMENTATION_SUMMARY.md) · `frontend` `docs/archive/POST_QUESTIONS_IMPLEMENTATION_SUMMARY.md`
- [Quick Guide: Test Real OpenAI (No Mock Data)](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/QUICK_TEST_REAL_OPENAI.md) · `frontend` `docs/archive/QUICK_TEST_REAL_OPENAI.md`
- [Post Recording Questions Table Schema Verification](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/SCHEMA_VERIFICATION.md) · `frontend` `docs/archive/SCHEMA_VERIFICATION.md`
- [Prompt: Debug "Session expired" on Next.js + Supabase + Flask BFF](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/SESSION_EXPIRED_DEBUG_PROMPT.md) · `frontend` `docs/archive/SESSION_EXPIRED_DEBUG_PROMPT.md`
- [Solo-Relevant Implementation Summary](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/SOLO_RELEVANT_IMPLEMENTATION_SUMMARY.md) · `frontend` `docs/archive/SOLO_RELEVANT_IMPLEMENTATION_SUMMARY.md`
- [Troubleshooting 502 Errors: Backend Not Responding](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/TROUBLESHOOTING_502_ERRORS.md) · `frontend` `docs/archive/TROUBLESHOOTING_502_ERRORS.md`
- [Troubleshoot: Git Push Taking Too Long or Failing](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/TROUBLESHOOT_GIT_PUSH.md) · `frontend` `docs/archive/TROUBLESHOOT_GIT_PUSH.md`
- [Vercel Build Fixes](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/VERCEL_BUILD_FIX.md) · `frontend` `docs/archive/VERCEL_BUILD_FIX.md`
- [Vercel Configuration Settings](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/VERCEL_CONFIGURATION.md) · `frontend` `docs/archive/VERCEL_CONFIGURATION.md`
- [Vercel Deployment Guide](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/VERCEL_DEPLOYMENT_GUIDE.md) · `frontend` `docs/archive/VERCEL_DEPLOYMENT_GUIDE.md`
- [Vercel Setup: Step-by-Step Guide](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/VERCEL_SETUP_STEP_BY_STEP.md) · `frontend` `docs/archive/VERCEL_SETUP_STEP_BY_STEP.md`
- [Recordings Table Column Mapping](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/archive/supabase-recordings-table-mapping.md) · `frontend` `docs/archive/supabase-recordings-table-mapping.md`
- [Engineering audit — frontend (`frontend-cursor`) — 2026-09-13](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/audits/2026-09-13-engineering-audit.md) · `frontend` `docs/audits/2026-09-13-engineering-audit.md`
- [Backend: Coach message after homework (no video on homework flow)](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/backend-reference/coach_message_after_homework.md) · `frontend` `docs/backend-reference/coach_message_after_homework.md`
- [Backend: Tutor countdown timer for first-time completers](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/backend-reference/tutor_feedback_deadline_first_lesson.md) · `frontend` `docs/backend-reference/tutor_feedback_deadline_first_lesson.md`
- [Copilot Draft Contract](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/copilot-draft-contract.md) · `frontend` `docs/copilot-draft-contract.md`
- [Backend: Return `assigned_exercises` so step 0 shows the assigned exercise](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/cursor-prompts/BACKEND_ASSIGNED_EXERCISES_STEP0.md) · `frontend` `docs/cursor-prompts/BACKEND_ASSIGNED_EXERCISES_STEP0.md`
- [Backend: Assignment Email (POST send-assignment)](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/cursor-prompts/BACKEND_ASSIGNMENT_EMAIL.md) · `frontend` `docs/cursor-prompts/BACKEND_ASSIGNMENT_EMAIL.md`
- [Backend: Persist and honor “flow steps” overrides (skip step 2 / step 4)](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/cursor-prompts/BACKEND_FLOW_STEPS_OVERRIDES.md) · `frontend` `docs/cursor-prompts/BACKEND_FLOW_STEPS_OVERRIDES.md`
- [Backend Cursor Prompt: willab (willpower lab) — Five Bug Fixes](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/cursor-prompts/BACKEND_PROMPT.md) · `frontend` `docs/cursor-prompts/BACKEND_PROMPT.md`
- [Frontend prompt: Homework flow – admin overrides and “report generating” state](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/cursor-prompts/FRONTEND_HOMEWORK_FLOW_PROMPT.md) · `frontend` `docs/cursor-prompts/FRONTEND_HOMEWORK_FLOW_PROMPT.md`
- [Frontend Cursor prompt: willab bugfixes (production-ready)](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/cursor-prompts/FRONTEND_PROMPT.md) · `frontend` `docs/cursor-prompts/FRONTEND_PROMPT.md`
- [BUILD PROMPT — wire the billing portal (manage / switch / cancel a plan)](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/cursor-prompts/PROMPT-FE-billing-portal.md) · `frontend` `docs/cursor-prompts/PROMPT-FE-billing-portal.md`
- [BUILD PROMPT — draw the cover from a description, let Enter walk the lane, and stop refusing real video](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/cursor-prompts/PROMPT-FE-cover-draw-and-enter.md) · `frontend` `docs/cursor-prompts/PROMPT-FE-cover-draw-and-enter.md`
- [BUILD PROMPT — the in-thread top-up card (Lounge)](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/cursor-prompts/PROMPT-FE-lounge-topup-card.md) · `frontend` `docs/cursor-prompts/PROMPT-FE-lounge-topup-card.md`
- [Handoff — Voice Game Bubble + Beta Badge](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/handoff-voice-game-bubble-and-beta.md) · `frontend` `docs/handoff-voice-game-bubble-and-beta.md`
- [Backlog implementation — real repos (frontend-cursor / backend-cursor)](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/handoffs/BACKLOG-IMPLEMENTATION-REPORT.md) · `frontend` `docs/handoffs/BACKLOG-IMPLEMENTATION-REPORT.md`
- [BE handoff: connect the breakthrough moment + coach breakthrough video](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/handoffs/backend-handoff-breakthrough-video.md) · `frontend` `docs/handoffs/backend-handoff-breakthrough-video.md`
- [BE handoff: coach publish floor + presentation_ref nullability](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/handoffs/backend-handoff-coach-publish-and-slide-refs.md) · `frontend` `docs/handoffs/backend-handoff-coach-publish-and-slide-refs.md`
- [BE handoff: stale tasks served as current, and where the Dalio ranking lives](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/handoffs/backend-handoff-life-goal-priority.md) · `frontend` `docs/handoffs/backend-handoff-life-goal-priority.md`
- [BE handoff: the Life Panel document dock (kind-aware drafting)](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/handoffs/backend-handoff-life-panel-document-dock.md) · `frontend` `docs/handoffs/backend-handoff-life-panel-document-dock.md`
- [Backend summary: Default warm-up question](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/handoffs/backend-summary-default-warmup.md) · `frontend` `docs/handoffs/backend-summary-default-warmup.md`
- [Chat bot audit — BE + FE prompts](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/handoffs/chat-bot-audit-handoffs.md) · `frontend` `docs/handoffs/chat-bot-audit-handoffs.md`
- [Handoff — CSP `style-src` hardening, after the 2026-08-04 outage](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/handoffs/handoff-csp-style-src.md) · `frontend` `docs/handoffs/handoff-csp-style-src.md`
- [Handoff — The Life Panel (FE)](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/handoffs/handoff-life-panel.md) · `frontend` `docs/handoffs/handoff-life-panel.md`
- [Handoff — readout per-slide, take cadence copy, best-presentation cleanup](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/handoffs/handoff-readout-and-takes.md) · `frontend` `docs/handoffs/handoff-readout-and-takes.md`
- [BE PROMPT — Journal (blog) content + media API](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/journal-be-prompt.md) · `frontend` `docs/journal-be-prompt.md`
- [FE PROMPT — Public Journal (blog) + admin CMS](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/journal-fe-prompt.md) · `frontend` `docs/journal-fe-prompt.md`
- [FE prompt — The Life Panel](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/life-panel-fe-prompt.md) · `frontend` `docs/life-panel-fe-prompt.md`
- [willab — FE Clearing Map](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/willab_clearing_map_fe.md) · `frontend` `docs/willab_clearing_map_fe.md`
- [willab — Design Decisions (Developer Reference)](https://github.com/wilplus/frontend-cursor/blob/501da43874460770310b24fafc664c4f5e606114/docs/willab_design_decisions_beta.md) · `frontend` `docs/willab_design_decisions_beta.md`

</details>

On the same day, after N111, 64 more left: the docs only code comments named. Each comment now
links to the doc's last version, as below.

<details><summary>The 64 docs of N111, each at its last version</summary>

- [PHASE A0 — Findings](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/PHASE-A0-FINDINGS.md) · `backend` `PHASE-A0-FINDINGS.md`
- [BE handoff — push the analysis-state flip (kill the FE's 2s status polling)](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/BE-HANDOFF-analysis-state-push.md) · `backend` `docs/BE-HANDOFF-analysis-state-push.md`
- [Claude Handoff — Confident Moment Coaching Bundle point 7](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/CLAUDE-HANDOFF-CONFIDENT-MOMENT-POINT7-2026-09-12.md) · `backend` `docs/CLAUDE-HANDOFF-CONFIDENT-MOMENT-POINT7-2026-09-12.md`
- [The willab engine map — what runs where, and how it all connects](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/ENGINE-MAP.md) · `backend` `docs/ENGINE-MAP.md`
- [Founder lock · the coach panel, redrawn (6 October 2026)](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/FOUNDER-LOCK-coach-panel-redesign-2026-10-06.md) · `backend` `docs/FOUNDER-LOCK-coach-panel-redesign-2026-10-06.md`
- [Founder lock — moment and feedback, one chat with a lens (2026-10-12)](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/FOUNDER-LOCK-moment-feedback-chat-2026-10-12.md) · `backend` `docs/FOUNDER-LOCK-moment-feedback-chat-2026-10-12.md`
- [HANDOFF — WillpowerLab, 2026-08-14](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/HANDOFF.md) · `backend` `docs/HANDOFF.md`
- [LEARNING-TRACE — the developer window into the learning lanes](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/LEARNING-TRACE.md) · `backend` `docs/LEARNING-TRACE.md`
- [MLC-2 Confidence Classification Dependency Audit](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC2-CONFIDENCE-DEPENDENCY-AUDIT.md) · `backend` `docs/MLC2-CONFIDENCE-DEPENDENCY-AUDIT.md`
- [MLC-2 Foundation Slice 1](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC2-FOUNDATION.md) · `backend` `docs/MLC2-FOUNDATION.md`
- [MLC-2 Legacy Dependency Audit](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC2-LEGACY-DEPENDENCY-AUDIT.md) · `backend` `docs/MLC2-LEGACY-DEPENDENCY-AUDIT.md`
- [MLC-3 Confident Moment Coaching Bundle — Coach Context Principal Amendment D26](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-COACH-CONTEXT-PRINCIPAL-AMENDMENT-D26.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-COACH-CONTEXT-PRINCIPAL-AMENDMENT-D26.md`
- [MLC-3 Confident Moment Coaching Bundle — Currentness and Lock Closure D49](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-CURRENTNESS-LOCK-CLOSURE-D49.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-CURRENTNESS-LOCK-CLOSURE-D49.md`
- [MLC-3 Confident Moment Coaching Bundle — Feedback Exposure Identity Amendment D15](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-FEEDBACK-EXPOSURE-IDENTITY-AMENDMENT-D15.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-FEEDBACK-EXPOSURE-IDENTITY-AMENDMENT-D15.md`
- [MLC-3 Confident Moment Coaching Bundle — Frontend and Authoring Amendment D14](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-FRONTEND-AND-AUTHORING-AMENDMENT-D14.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-FRONTEND-AND-AUTHORING-AMENDMENT-D14.md`
- [MLC-3 Confident Moment Coaching Bundle — Implementation Seam Amendment D27](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-IMPLEMENTATION-SEAM-AMENDMENT-D27.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-IMPLEMENTATION-SEAM-AMENDMENT-D27.md`
- [MLC-3 Confident Moment Coaching Bundle — Implementation Seam Amendment D28](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-IMPLEMENTATION-SEAM-AMENDMENT-D28.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-IMPLEMENTATION-SEAM-AMENDMENT-D28.md`
- [MLC-3 Confident Moment Coaching Bundle — Implementation Seam Amendment D29](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-IMPLEMENTATION-SEAM-AMENDMENT-D29.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-IMPLEMENTATION-SEAM-AMENDMENT-D29.md`
- [MLC-3 Confident Moment Coaching Bundle — Implementation Seam Amendment D30](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-IMPLEMENTATION-SEAM-AMENDMENT-D30.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-IMPLEMENTATION-SEAM-AMENDMENT-D30.md`
- [MLC-3 Confident Moment Coaching Bundle — Implementation Seam Amendment D31](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-IMPLEMENTATION-SEAM-AMENDMENT-D31.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-IMPLEMENTATION-SEAM-AMENDMENT-D31.md`
- [MLC-3 Confident Moment Coaching Bundle — Implementation Seam Amendment D32](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-IMPLEMENTATION-SEAM-AMENDMENT-D32.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-IMPLEMENTATION-SEAM-AMENDMENT-D32.md`
- [MLC-3 Confident Moment Coaching Bundle — Implementation Seam Amendment D33](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-IMPLEMENTATION-SEAM-AMENDMENT-D33.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-IMPLEMENTATION-SEAM-AMENDMENT-D33.md`
- [MLC-3 Confident Moment Coaching Bundle — Implementation Seam Amendment D34](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-IMPLEMENTATION-SEAM-AMENDMENT-D34.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-IMPLEMENTATION-SEAM-AMENDMENT-D34.md`
- [MLC-3 Confident Moment Coaching Bundle — Implementation Seam Amendment D35](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-IMPLEMENTATION-SEAM-AMENDMENT-D35.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-IMPLEMENTATION-SEAM-AMENDMENT-D35.md`
- [MLC-3 Confident Moment Coaching Bundle — Implementation Seam Amendment D36](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-IMPLEMENTATION-SEAM-AMENDMENT-D36.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-IMPLEMENTATION-SEAM-AMENDMENT-D36.md`
- [MLC-3 Confident Moment Coaching Bundle — Scanner Identity Amendment D37](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-IMPLEMENTATION-SEAM-AMENDMENT-D37.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-IMPLEMENTATION-SEAM-AMENDMENT-D37.md`
- [MLC-3 Confident Moment Coaching Bundle — Interface Manifest D11](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-INTERFACE-MANIFEST-D11.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-INTERFACE-MANIFEST-D11.md`
- [MLC-3 Confident Moment Coaching Bundle — Render Identity and Transport Amendment D13](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-RENDER-IDENTITY-AND-TRANSPORT-AMENDMENT-D13.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-RENDER-IDENTITY-AND-TRANSPORT-AMENDMENT-D13.md`
- [MLC-3 Confident Moment Coaching Bundle — Transport Closure Amendment D16](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-TRANSPORT-CLOSURE-AMENDMENT-D16.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-TRANSPORT-CLOSURE-AMENDMENT-D16.md`
- [MLC-3 Confident Moment Coaching Bundle — Transport Closure Amendment D17](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-TRANSPORT-CLOSURE-AMENDMENT-D17.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-TRANSPORT-CLOSURE-AMENDMENT-D17.md`
- [MLC-3 Confident Moment Coaching Bundle — Transport Closure Amendment D18](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-TRANSPORT-CLOSURE-AMENDMENT-D18.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-TRANSPORT-CLOSURE-AMENDMENT-D18.md`
- [MLC-3 Confident Moment Coaching Bundle — Transport Closure Amendment D19](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-TRANSPORT-CLOSURE-AMENDMENT-D19.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-TRANSPORT-CLOSURE-AMENDMENT-D19.md`
- [MLC-3 Confident Moment Coaching Bundle — Transport Closure Amendment D20](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-TRANSPORT-CLOSURE-AMENDMENT-D20.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-TRANSPORT-CLOSURE-AMENDMENT-D20.md`
- [MLC-3 Confident Moment Coaching Bundle — Transport Closure Amendment D21](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-TRANSPORT-CLOSURE-AMENDMENT-D21.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-TRANSPORT-CLOSURE-AMENDMENT-D21.md`
- [MLC-3 Confident Moment Coaching Bundle — Transport Closure Amendment D22](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-TRANSPORT-CLOSURE-AMENDMENT-D22.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-TRANSPORT-CLOSURE-AMENDMENT-D22.md`
- [MLC-3 Confident Moment Coaching Bundle — Transport Closure Amendment D23](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-TRANSPORT-CLOSURE-AMENDMENT-D23.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-TRANSPORT-CLOSURE-AMENDMENT-D23.md`
- [MLC-3 Confident Moment Coaching Bundle — Transport Closure Amendment D24](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-TRANSPORT-CLOSURE-AMENDMENT-D24.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-TRANSPORT-CLOSURE-AMENDMENT-D24.md`
- [MLC-3 Confident Moment Coaching Bundle — Transport Closure Amendment D25](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-TRANSPORT-CLOSURE-AMENDMENT-D25.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-TRANSPORT-CLOSURE-AMENDMENT-D25.md`
- [MLC-3 Confident Moment Coaching Bundle — User Media Correlation Amendment D38](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-USER-MEDIA-CORRELATION-AMENDMENT-D38.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-USER-MEDIA-CORRELATION-AMENDMENT-D38.md`
- [MLC-3 Confident Moment Coaching Bundle — User Media Correlation Amendment D39](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-USER-MEDIA-CORRELATION-AMENDMENT-D39.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-USER-MEDIA-CORRELATION-AMENDMENT-D39.md`
- [MLC-3 Confident Moment Coaching Bundle — User Media Correlation Amendment D40](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-USER-MEDIA-CORRELATION-AMENDMENT-D40.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-USER-MEDIA-CORRELATION-AMENDMENT-D40.md`
- [MLC-3 Confident Moment Coaching Bundle — User Media Correlation Amendment D41](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-USER-MEDIA-CORRELATION-AMENDMENT-D41.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-USER-MEDIA-CORRELATION-AMENDMENT-D41.md`
- [MLC-3 Confident Moment Coaching Bundle — User Media Correlation Amendment D42](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-USER-MEDIA-CORRELATION-AMENDMENT-D42.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-USER-MEDIA-CORRELATION-AMENDMENT-D42.md`
- [MLC-3 Confident Moment Coaching Bundle — User Media Correlation Amendment D43](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-USER-MEDIA-CORRELATION-AMENDMENT-D43.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-USER-MEDIA-CORRELATION-AMENDMENT-D43.md`
- [MLC-3 Confident Moment Coaching Bundle — User Media Correlation Amendment D44](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-USER-MEDIA-CORRELATION-AMENDMENT-D44.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-USER-MEDIA-CORRELATION-AMENDMENT-D44.md`
- [MLC-3 Confident Moment Coaching Bundle — User Media Correlation Amendment D45](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-USER-MEDIA-CORRELATION-AMENDMENT-D45.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-USER-MEDIA-CORRELATION-AMENDMENT-D45.md`
- [MLC-3 Confident Moment Coaching Bundle — User Media Correlation Amendment D46](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-USER-MEDIA-CORRELATION-AMENDMENT-D46.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-USER-MEDIA-CORRELATION-AMENDMENT-D46.md`
- [MLC-3 Confident Moment Coaching Bundle — Exercise Source Speaker Amendment D47](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-USER-MEDIA-CORRELATION-AMENDMENT-D47.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-USER-MEDIA-CORRELATION-AMENDMENT-D47.md`
- [MLC-3 Confident Moment Coaching Bundle — Speaker-Binding Authorization D48](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-COACHING-USER-MEDIA-CORRELATION-AMENDMENT-D48.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-COACHING-USER-MEDIA-CORRELATION-AMENDMENT-D48.md`
- [D49 §5 — activation attestation (taken 2026-09-14, remediated and re-taken 2026-09-15)](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-CONFIDENT-MOMENT-D49-SECTION-5-ACTIVATION-ATTESTATION.md) · `backend` `docs/MLC3-CONFIDENT-MOMENT-D49-SECTION-5-ACTIVATION-ATTESTATION.md`
- [MLC-3 First-Client Service D2](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-FIRST-CLIENT-SERVICE-D2.md) · `backend` `docs/MLC3-FIRST-CLIENT-SERVICE-D2.md`
- [MLC-3 General-User Service Rollout D4](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC3-GENERAL-USER-SERVICE-D4.md) · `backend` `docs/MLC3-GENERAL-USER-SERVICE-D4.md`
- [Production Data Foundation](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/PRODUCTION-DATA-FOUNDATION.md) · `backend` `docs/PRODUCTION-DATA-FOUNDATION.md`
- [FE HANDOFF — measure the recorder clock offset (F1)](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/PROMPT-FE-audio-clock-offset.md) · `backend` `docs/PROMPT-FE-audio-clock-offset.md`
- [FE handoff — token pricing (Phase 1)](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/PROMPT-FE-token-pricing.md) · `backend` `docs/PROMPT-FE-token-pricing.md`
- [PROMPT — IRT, CAT and DIF (deferred; do not execute until a trigger fires)](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/PROMPT-irt-dif-deferred.md) · `backend` `docs/PROMPT-irt-dif-deferred.md`
- [Founder answers, Navigation Panel, 6 October 2026 (fourth export, 19:28 UTC)](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/audit/PANEL-ANSWERS-2026-10-06-c.md) · `backend` `docs/audit/PANEL-ANSWERS-2026-10-06-c.md`
- [Founder answers, Navigation Panel, 6 October 2026 (fifth export, 20:03 UTC)](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/audit/PANEL-ANSWERS-2026-10-06-d.md) · `backend` `docs/audit/PANEL-ANSWERS-2026-10-06-d.md`
- [Founder answers, Navigation Panel, 6 October 2026 (export of 07:59 UTC, verbatim)](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/audit/PANEL-ANSWERS-2026-10-06.md) · `backend` `docs/audit/PANEL-ANSWERS-2026-10-06.md`
- [V4 decision record and Developer brief (verbatim from https://claude.ai/artifact/UXiVaBvGLRTg83kjmHKY6E, founder-signed 2026-10-05/06)](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/audit/build/V4_BRIEF.md) · `backend` `docs/audit/build/V4_BRIEF.md`
- [Frontend — what to know (short contract)](https://github.com/wilplus/frontend-cursor/blob/43e02d2e434a5fe5be31e5646b99be6a4fd85217/docs/FRONTEND-WHAT-TO-KNOW.md) · `frontend` `docs/FRONTEND-WHAT-TO-KNOW.md`
- [BE handoff — plan management: one route still missing (the billing portal)](https://github.com/wilplus/frontend-cursor/blob/43e02d2e434a5fe5be31e5646b99be6a4fd85217/docs/HANDOFF-BE-2026-07-31-token-subscriptions.md) · `frontend` `docs/HANDOFF-BE-2026-07-31-token-subscriptions.md`
- [Backend reference: Assignment email](https://github.com/wilplus/frontend-cursor/blob/43e02d2e434a5fe5be31e5646b99be6a4fd85217/docs/backend-reference/README.md) · `frontend` `docs/backend-reference/README.md`
- [Handoffs — dated messages between the two repos (frontend copy)](https://github.com/wilplus/frontend-cursor/blob/43e02d2e434a5fe5be31e5646b99be6a4fd85217/docs/handoffs/README.md) · `frontend` `docs/handoffs/README.md`

</details>

## 6. Home docs for the code

Every part of the code has one home doc (founder, 21 October 2026, N107 and N111). A session that changes
code writes what changed into the code's home doc, or into the pull request, never into a new file. "No
page" means no doc describes that part: the code and its comments do, and a rule about it goes into the
decisions log. The frontend's table is in its own [`README.md`](https://github.com/wilplus/frontend-cursor/blob/main/README.md).

- A pattern ending in `/` covers its whole folder; `*` stands for any part of one name; anything else is
  one file. When two rows match, the more exact pattern wins.
- Docs, tests, the legal pack and the repo's own settings files are not listed.
- New code in a folder or name group below is covered already. Anything else needs a row here, in the
  same pull request. `scripts/doc_guard.py` refuses code that no row covers, a pattern that matches nothing, and a home
  doc that is History or Archive.

<!-- code-homes:start -->
| Part of the code | Files | Home doc |
|---|---|---|
| Recording a Take and the processing pipeline | `services/lab_*`, `services/recording_*`, `services/create_take.py`, `services/take_lifecycle.py`, `services/take_rebuild.py`, `services/take_repository.py`, `services/take_analysis_state.py`, `services/take_review.py`, `services/analysis_worker.py`, `services/job_queue.py`, `services/pipeline_*`, `services/processing_stages.py`, `services/processing_progress.py`, `services/scheduler_keeper.py`, `services/parallel.py`, `services/degradation.py`, `services/session_*`, `services/speaker_split.py`, `services/realtime_notify.py`, `services/min_content_gate.py`, `services/ffmpeg_audio_extract.py`, `services/webm_remux.py`, `services/snippet_*`, `services/upload_guard.py`, `routes/jobs.py`, `routes/recordings.py`, `routes/v2/lab_recording.py`, `worker.py`, `bin/railway-worker.sh`, `run_cleanup_*.py`, `services/candidate_capture.py`, `scripts/backfill_snippet_*`, `scripts/backfill_piece_slide_lineage.py`, `scripts/backfill_sniper_metrics.py`, `scripts/backfill_trial_session_publish.py`, `scripts/cleanup_corrupt_stress_snippets.py`, `scripts/sql/repair_delete_cleared_take_links.sql`, `scripts/sql/voice_pipeline_student_snippet_coverage.sql` | [`docs/ASYNC-PIPELINE-QUEUE.md`](docs/ASYNC-PIPELINE-QUEUE.md) |
| The pipeline's admin panel | `services/pipeline_health.py` | [`docs/SPEC-pipeline-admin-panel.md`](docs/SPEC-pipeline-admin-panel.md) |
| The recording screens | `services/recording_roots.py` | [frontend `docs/flows/recording-screens.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/recording-screens.md) |
| The transcript and the Ideal Text | `services/ideal_*`, `services/paragraph_history.py`, `services/slide_*`, `services/transcript_*`, `services/tracked_changes.py`, `services/accepted_rewrite.py`, `services/rewrite_*`, `services/say_it_stronger.py`, `services/swap_*`, `services/protected_phrases.py`, `services/presentation_change_intent.py`, `services/prior_take_*`, `services/text_flags.py`, `services/deck_parser.py`, `services/context_document.py`, `services/master_doc*`, `services/strategy_export.py`, `services/suggestion_*`, `services/take_comparison.py`, `services/cross_take_selection.py`, `services/intake_context.py`, `services/prompts/master_document.py`, `services/prompts/slide_alignment.py`, `services/prompts/swap_continuity.py`, `services/prompts/say_it_stronger.py`, `services/prompts/best_presentation.py`, `routes/v2/explore_ideal_text.py`, `routes/v2/canonical_publish.py` | [`docs/CANONICAL_PRODUCT_CONTRACT.md`](docs/CANONICAL_PRODUCT_CONTRACT.md), clauses 8 to 14, and the frontend's [`docs/flows/ideal-text.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/ideal-text.md) |
| Parts, locking and the two intervention layers | `services/dimension_registry.py`, `services/ideal_decision_ledger.py` | [`docs/SPEC-parts-locking-and-layers.md`](docs/SPEC-parts-locking-and-layers.md) |
| The Ideal Text page's helper words | `services/slide_helper_words.py` | [frontend `docs/flows/ideal-text.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/ideal-text.md) |
| The Feedback walk, the chat with Will and the Lounge | `services/feedback_*`, `services/take_feedback_*`, `services/take_summary.py`, `services/after_take.py`, `services/after_practice.py`, `services/chat_*`, `services/will_*`, `services/willfidence.py`, `services/moment_*`, `services/key_moments.py`, `services/judgement_follow_up.py`, `services/owner_feedback_answers.py`, `services/readout_*`, `services/playback_copy.py`, `services/journey_messages.py`, `services/next_session_icebreaker.py`, `services/directive_suggestions.py`, `services/undermining.py`, `services/feelings.py`, `services/named_emotion.py`, `services/line_bank.py`, `services/line_rotation.py`, `services/lounge_*`, `services/person_asks.py`, `services/v4_*`, `services/rewrite_gate.py`, `services/tempo_stretch.py`, `services/prompts/tempo_topic.py`, `services/prompts/moment_suggestions.py`, `services/prompts/v4_take_tags.py`, `routes/v2/line_bank.py`, `routes/v2/lounge.py`, `services/dad_jokes.py`, `services/bold_voices.py`, `services/product_discovery.py`, `scripts/v4_*` | [frontend `docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md) |
| Feedback, goals and notifications principles | `services/goal_*`, `services/feedback_digest.py` | [`docs/PRINCIPLES-WIL-74-feedback-goals.md`](docs/PRINCIPLES-WIL-74-feedback-goals.md) |
| The canonical feedback data contract | `services/feedback_data_contract.py` | [`docs/FEEDBACK_DATA_CONTRACT_MIGRATION_MAP.md`](docs/FEEDBACK_DATA_CONTRACT_MIGRATION_MAP.md) |
| Speaker memory: what Will learns about each speaker | `services/speaker_memory.py`, `services/speaker_lookup.py` | [`docs/SPEAKER-MEMORY.md`](docs/SPEAKER-MEMORY.md) |
| The feedback engine: measures and cues | `services/voice_confidence.py`, `services/power_phrase_ranking.py`, `services/snippet_stickiness.py`, `services/snippet_salience.py`, `services/metrics_v2.py`, `services/recording_feedback_scoring.py`, `services/recording_piece_analysis.py`, `services/delivery_*`, `services/prompts/snippet_stickiness.py`, `services/prompts/delivery_alignment.py`, `services/session_metrics.py`, `services/auto_comment.py`, `scripts/backfill_voice_confidence.py` | [`docs/SPEC.md`](docs/SPEC.md) |
| The feedback engine's manager | `services/manager_engine.py` | [`docs/SPEC-APPENDIX-H-manager.md`](docs/SPEC-APPENDIX-H-manager.md) |
| Interventions | `services/intervention_*` | [`docs/SPEC-APPENDIX-C-intervention-contract.md`](docs/SPEC-APPENDIX-C-intervention-contract.md) |
| Measurement windows | `services/rate_windows.py` | [`docs/SPEC-APPENDIX-F-windows.md`](docs/SPEC-APPENDIX-F-windows.md) |
| Verbal measures | `services/verbal_*`, `scripts/verbal_cue_shadow_report.py` | [`docs/SPEC-APPENDIX-A-verbal-computations.md`](docs/SPEC-APPENDIX-A-verbal-computations.md) |
| Acoustics: what the voice can tell us | `services/acoustic_*`, `services/part_acoustics.py`, `services/audio_metrics.py` | [`docs/VOCAL-EMOTION-ACOUSTICS.md`](docs/VOCAL-EMOTION-ACOUSTICS.md) |
| The coach panel | `services/coach_*`, `services/v4_coach_sheets.py`, `services/speaking_error_library.py`, `services/corpus_*`, `services/confidence_chain_*`, `services/prompts/coach_answer_drafts.py`, `services/prompts/coach_comment_drafter.py`, `services/prompts/coach_word_drafts.py`, `routes/v2/coach*`, `routes/v2/coaching.py`, `routes/v2/confidence_chain_coach.py`, `static/coach-avatar.png`, `scripts/report_public_coach_answer_videos.py` | [frontend `docs/flows/coach-panel.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/coach-panel.md) |
| Labels, learning and training | `services/label_quorum.py`, `services/research_*`, `services/confidence_labels.py`, `services/confidence_dataset.py`, `services/confidence_review_policy.py`, `services/clip_answer_counts.py`, `services/state_ratings.py`, `services/golden_*`, `services/training_*`, `services/model_*`, `services/detector_*`, `services/dataset_releases.py`, `services/pair_*`, `services/feedback_pairs.py`, `services/learning_*`, `services/lend_your_ear.py`, `services/communities.py`, `services/rater_languages.py`, `services/annotation_export.py`, `services/error_presence_audit.py`, `services/drift_*`, `services/runtime_model_gate.py`, `services/ml_surface_contracts.py`, `services/mlc2_*`, `services/moment_confidence.py`, `services/professional_confidence.py`, `services/reasonable_confidence.py`, `services/coach_word_pairs.py`, `services/coach_take_word.py`, `services/coach_block_pick.py`, `services/corpus_split.py`, `services/star_verdicts.py`, `routes/v2/research.py`, `routes/v2/communities.py`, `routes/v2/learning_*`, `routes/v2/training_consent.py`, `routes/v2/mlc2_consent.py`, `routes/drift_webhook.py`, `routes/learning_weekly_webhook.py`, `bin/railway-drift-cron.sh`, `bin/railway-learning-weekly-cron.sh`, `exports/`, `static/snippet_labeler.html`, `scripts/configure_mlc2_consent_policy.py`, `scripts/corpus_base_rates.py`, `scripts/export_annotation_events.py`, `scripts/export_confidence_validation.py`, `scripts/import_training_audio.py`, `scripts/promote_pair_surface.py`, `scripts/smoke_rlhf_capture.py`, `scripts/voxpopuli_speeches.py`, `scripts/record_blind_check_objection.sql`, `scripts/sql/drift_audit.sql` | [`docs/LEARNING-AND-QUORUM.md`](docs/LEARNING-AND-QUORUM.md) |
| Training corpus and project purge | `services/training_corpus.py`, `services/data_purge*`, `services/project_deletion.py` | [`docs/SPEC-training-corpus-and-project-purge.md`](docs/SPEC-training-corpus-and-project-purge.md) |
| How an exercise is chosen | `services/confident_voice_practice.py` | [`docs/CANONICAL_PRODUCT_CONTRACT.md`](docs/CANONICAL_PRODUCT_CONTRACT.md) (35g-1) |
| Exercises and practice | `services/exercise_*`, `services/practice_*`, `services/diagnostic_exercise_catalogue.py`, `services/voice_album*`, `services/confident_moment_*`, `routes/v2/coach_exercises.py`, `routes/v2/confident_moment_bundles.py`, `services/delayed_measure.py`, `services/mlc3_first_client_feedback.py`, `services/first_client_repository.py`, `config/mlc3_founder_attestation_public_key.pem`, `scripts/erase_practice_without_the_tick.py` | [`docs/MLC3-EXERCISE-ADEQUACY-DESIGN.md`](docs/MLC3-EXERCISE-ADEQUACY-DESIGN.md) |
| The AI version of the speaker's voice | `services/ai_voice_*`, `services/elevenlabs_client.py`, `services/authorized_voice_provider.py`, `routes/v2/ai_voice.py`, `scripts/ai_voice_smoke.py` | [`docs/AI-VOICE-PRACTICE.md`](docs/AI-VOICE-PRACTICE.md) |
| Rooting phrases | `services/rooting_phrase*`, `routes/v2/rooting_phrase_qualification.py` | [`docs/ROOTING-PHRASE-QUALIFICATION-V1-IMPLEMENTATION.md`](docs/ROOTING-PHRASE-QUALIFICATION-V1-IMPLEMENTATION.md) |
| Processing authorization: every recording and provider call | `services/processing_authorization.py`, `services/processing_purposes.py`, `services/authorized_provider.py`, `services/refusal.py`, `services/audit_intent.py`, `services/user_audit.py`, `routes/v2/processing_authorization.py`, `routes/phase2_guard.py`, `services/speaker_authority.py`, `scripts/phase1_*` | [`docs/PHASE1-PROCESSING-RUNBOOK.md`](docs/PHASE1-PROCESSING-RUNBOOK.md) |
| Deleting an account and its data | `services/account_deletion.py`, `services/deletion_completion.py`, `services/provider_deletion.py`, `services/retention_cleaner.py`, `services/orphan_audio_cleanup.py`, `services/object_verification.py`, `routes/deletion_completion_webhook.py`, `routes/retention_cleaner_webhook.py`, `bin/railway-deletion-completion-cron.sh`, `bin/railway-retention-cleaner-cron.sh`, `scripts/retention_*`, `scripts/run_due_deletions.py`, `scripts/run_phase1_data_purge.py` | [`docs/PHASE1-PROCESSING-RUNBOOK.md`](docs/PHASE1-PROCESSING-RUNBOOK.md) |
| Bundled-era erasure | `services/bundled_era_storage.py`, `scripts/bundled_era_erasure_storage.py` | [`docs/BUNDLED-ERA-ERASURE.md`](docs/BUNDLED-ERA-ERASURE.md) |
| Private storage buckets | `services/audio_storage.py`, `services/user_media_storage.py`, `services/r2_client.py`, `services/audio_ref_resolver.py`, `services/user_content_keys.py`, `services/tutor_video_url.py` | [`docs/PRIVATE-BUCKETS-M11.4.md`](docs/PRIVATE-BUCKETS-M11.4.md) |
| Immutable source data and provenance | `services/provenance*` | [`docs/SPEC-immutable-provenance.md`](docs/SPEC-immutable-provenance.md) |
| Rate limits and the error contract | `services/rate_limits.py`, `services/request_context.py`, `utils/errors.py` | [`docs/RATE-LIMITS-AND-ERROR-CONTRACT.md`](docs/RATE-LIMITS-AND-ERROR-CONTRACT.md) |
| Database transactions | `services/db.py`, `services/db_transport.py`, `services/table_repository.py` | [`docs/DB-TRANSACTIONS.md`](docs/DB-TRANSACTIONS.md) |
| Secrets, staging and monitoring | `services/secrets.py`, `services/logging_setup.py`, `services/f1_observability.py` | [`docs/OPS-SECRETS-AND-STAGING.md`](docs/OPS-SECRETS-AND-STAGING.md) |
| Feature flags and releases | `services/gate_flags.py`, `services/rings.py`, `routes/v2/rings.py` | [`docs/OPS-FLAGS-AND-RELEASES.md`](docs/OPS-FLAGS-AND-RELEASES.md) |
| Migrations | `migrations/`, `run_migration.py`, `bin/railway-migrate.sh`, `scripts/migrate.py` | [`docs/MIGRATIONS.md`](docs/MIGRATIONS.md) |
| The journal (blog) and its CMS | `services/journal*`, `routes/journal.py`, `routes/internal_webhooks.py` | [`docs/JOURNAL-SETUP.md`](docs/JOURNAL-SETUP.md) |
| Dev bugs | `services/dev_bugs.py`, `routes/dev_bugs.py`, `static/dev_bugs.html`, `static/dev_bugs_icons/`, `bin/railway-devbugs-cron.sh`, `Dockerfile.devbugs-cron`, `scripts/gen_dev_bugs_icons.mjs`, `scripts/send_dev_bugs.py` | [`docs/DEV-BUGS-SETUP.md`](docs/DEV-BUGS-SETUP.md) |
| Dev tasks (dev.willpowerlab.com) | `services/dev_tasks.py`, `routes/dev_tasks.py`, `scripts/backfill_dev_task_images.py`, `scripts/stories_csv.py` | [`docs/DEV-TASKS-PIPELINE-SETUP.md`](docs/DEV-TASKS-PIPELINE-SETUP.md) |
| The Life Panel | `services/life_*`, `routes/life_routes.py`, `routes/life_reminders_webhook.py`, `bin/railway-life-reminders-cron.sh`, `Dockerfile.life-reminders-cron`, `scripts/generate_life_daily_cards.py` | [`docs/life-checkin-learning-contract.md`](docs/life-checkin-learning-contract.md) |
| The plan: the questions, the plan card, the practice days, the level in the walk, the deadline and the coach's side | `services/plan.py`, `services/plan_flow.py`, `services/plan_walk.py`, `services/plan_consent.py`, `services/plan_coach.py`, `routes/v2/plan.py`, `routes/v2/coach_plans.py` | [frontend `docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md) |
| Will's learning plan and voice notebook | `services/voice_notebook.py`, `services/sunday_note.py`, `routes/v2/voice_notebook.py`, `services/life_goals.py`, `routes/v2/life_goals.py`, `services/in_control.py`, `services/sales_framing.py`, `services/your_why.py`, `routes/v2/your_why.py`, `services/strengths.py`, `routes/v2/strengths.py` | [`docs/WILL-LEARNING-PLAN.md`](docs/WILL-LEARNING-PLAN.md) |
| The golden set for transcripts | `scripts/measure_transcripts.py` | [`scripts/measure_transcripts.md`](scripts/measure_transcripts.md) |
| The rehearsal tier (tests against a real database) | `scripts/rehearsal_*` | [`docs/REHEARSAL-TIER.md`](docs/REHEARSAL-TIER.md) |
| Community content from journal posts | `services/community_content.py` | [`docs/WillLab_Community_Content_Strategy.md`](docs/WillLab_Community_Content_Strategy.md) |
| Accounts, sign-in and projects | `auth.py`, `get_token.py`, `routes/auth.py`, `routes/user.py`, `routes/v2/auth_alias.py`, `routes/v2/user_account.py`, `routes/v2/account_security.py`, `services/account_security.py`, `routes/v2/signup_count.py`, `services/signup_count.py`, `routes/v2/login_code.py`, `services/login_code.py`, `routes/v2/user_sessions.py`, `routes/v2/projects.py`, `routes/v2/guest_owner.py`, `services/user_profile.py`, `services/speaker_identity.py`, `services/project_archive.py`, `services/project_ownership.py`, `services/project_repository.py`, `services/domains.py`, `services/canonical_product.py` | No page |
| Tokens, prices and payments | `services/token_*`, `routes/token_routes.py`, `routes/v2/admin_tokens.py`, `services/plan_promotions.py`, `services/booking.py`, `routes/v2/booking.py`, `scripts/legacy_commerce_check.sql` | No page |
| Arcs (audits and explore sessions) | `services/arc_*`, `services/explore_arc.py`, `services/user_trainings.py`, `routes/v2/arcs.py`, `scripts/mint_arc_invite_codes.py` | No page |
| Email and WhatsApp messages | `services/email_*`, `services/assignment_email.py`, `services/unsubscribe_tokens.py`, `services/whatsapp_notify.py`, `services/coach_feedback_notice.py`, `services/homework_digest.py`, `routes/v2/user_whatsapp.py`, `routes/v2/whatsapp_webhook.py` | No page |
| Model and provider calls (OpenAI, prompts, costs) | `services/llm*`, `services/openai_service.py`, `services/prompts/__init__.py`, `services/prompts/pending.py`, `services/prompts/registry.py`, `services/prompts/prompts.lock.json`, `scripts/llm_usage_report.py` | No page |
| The admin console | `services/admin_*`, `routes/admin.py`, `routes/v2/admin.py`, `routes/v2/people.py` | No page |
| The CEO panel and the founder's roadmap | `services/ceo*`, `routes/v2/ceo*`, `services/roadmap.py`, `routes/v2/roadmap_admin.py`, `config/roadmap.json` | No page |
| Running the server: app, settings, deploy and shared helpers | `app.py`, `config.py`, `gunicorn_conf.py`, `Procfile`, `bin/railway-web.sh`, `requirements.txt`, `runtime.txt`, `apt.txt`, `mise.toml`, `nixpacks.toml`, `railpack.json`, `mypy.ini`, `ruff.toml`, `utils/__init__.py`, `utils/ids.py`, `utils/metrics.py`, `services/__init__.py`, `services/utils.py`, `services/warm_connections.py`, `routes/__init__.py`, `routes/v2/__init__.py`, `routes/v2/blueprint.py`, `routes/v2/common.py` | No page |
| The checks a pull request must pass | `scripts/local_ci.sh`, `scripts/doc_guard.py`, `scripts/complexity_*`, `scripts/except_ratchet*`, `scripts/coverage_floor*`, `scripts/ledger_check.py`, `scripts/rls_guard.py`, `scripts/jwt_secret_check.py`, `scripts/sentry_smoke.py`, `scripts/manual_smoke.py`, `scripts/boot_switch_report.py`, `scripts/phase_a0_diagnostics.py`, `scripts/render_doc_pdf.py` | No page |
<!-- code-homes:end -->

## Keeping this page right

- A new doc needs the founder's OK (N107). Its line on this page says `Founder-Approved: <where and when the
  founder said yes>`, and it gets its label line under its title, in the same pull request.
- A label that changes changes in both places. A change to a rule is a decisions-log entry first (N95).
- The labels were set on 21 October 2026 (N106) and the docs converged the same day (N107).
- Don't start a new doc: write into the code's home doc (§6) or this page. `scripts/doc_guard.py` refuses code
  without a home doc, a doc this page doesn't list, and a new doc without the founder's OK (N111).
