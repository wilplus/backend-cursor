# Production Data Foundation

Title: Production Data Foundation  
Owner: Artur Willoński  
Problem: Product usage must produce reliable, isolated, reconstructable and uncontaminated signals for seven future learning systems.  
User outcome: Recordings, Ideal Text, Manager feedback and coach review remain reliable while every learning-relevant presentation and decision has exact provenance.  
Scope: Canonical RecordingAttempt-to-Take promotion, durable processing transitions, ownership and guest-claim audit, visible exposure acknowledgements, typed immutable decisions, seven-system readiness calculations, and a read-only CEO workspace.  
Out of scope: Model training, dataset/model promotion controls, product-semantic changes, inferred legacy provenance, compatibility-data deletion, and treating legal acceptance as ML-training permission without an authorized policy.  
Product decision: `PDF-1`  
Affected learning surfaces: Confident Voice classifier; verbal-correction wording; coach-comment drafting; praise wording; praise selection; verbal-correction selection; Ideal Text generation.  
Affected data/events: Recording attempts, successful Takes, processing transitions, ownership claims, candidate sets, visible exposures, typed decisions, coach revisions, consent/retention snapshots, dataset releases and readiness aggregates.  
Affected frontend/backend/database areas: Recording upload/poll/retry, Ideal Text and coach review presentation acknowledgements, canonical persistence services and migrations, CEO admin API and workspace.  
Risks: Cross-owner leakage, false exposure, inferred negative labels, blind-review leakage, duplicate Takes, contradictory terminal states, incomplete provenance, and unapproved eligibility.  
Acceptance criteria: See `ED-1` below.  
Rollback plan: Disable new dual-writes and CEO readiness routes, roll application code back, retain append-only audit records, and immediately roll back on ownership, blindness, locked-text or data-integrity violations.  
Current status: `IN_PROGRESS`

## Product approval

- Status: `APPROVED`
- Approved by: Artur Willoński
- Date: 2026-08-27
- Decision version: `PDF-1`

## ML/data approval

- Status: `APPROVED`
- Approved by: Codex (OpenAI), acting as ML Engineer and CEO adviser
- Date: 2026-08-27
- Contract version: `MLC-1`

## Engineering approval

- Status: `APPROVED`
- Approved by: Señor Engineer
- Date: 2026-08-27
- Design version: `ED-1`

## Deployment approval

- Status: `PENDING`
- Approved by:
- Date:

## MLC-1 — canonical ML/data contract

1. A production exposure exists only after the client confirms that the item rendered visibly. Server delivery alone is not `shown`.
2. Selection freezes the complete eligible candidate set, selected candidate, rank, exact evidence, scores, actor, ownership and all model/prompt/policy/schema versions.
3. Closing, skipping, timing out and not responding remain unanswered. They never produce negative decisions.
4. Shadow output is stored as `evaluation_only`, never rendered and never treated as feedback.
5. Machine predictions, owner self-reports, blind coach judgments, blind peer judgments and later revisions keep separate typed provenance.
6. Coach and peer judgments remain blind until immutable submission.
7. Each of the seven systems owns a distinct learning surface and dataset release. No generic combined label table is allowed.
8. Unclaimed guests, uncertain legacy rows and records missing evidence, ownership, consent/retention state or reproducible versions are excluded with explicit reasons.
9. Speaker-disjoint splits use stable owner/speaker identity, never project, Take, clip or display name.
10. Existing Terms acceptance may be captured as legal evidence but is not silently interpreted as ML-training permission. Affected rows remain ineligible until an authorized consent/retention policy exists.
11. Dataset releases are immutable and surface-specific. Display is not positive; a self-report is not automatically gold truth.
12. The CEO readiness workspace is read-only and has no training or promotion controls.

ML approval statement:

> ML/DATA APPROVED — The signals are interpretable, provenance-safe and correctly eligible or excluded. ML contract version: MLC-1.

## ED-1 — engineering design

### Scope

- Introduce an additive canonical `RecordingAttempt → successful Take` boundary. Failed attempts retain stored recording but never consume a completed Take number.
- Preserve `v2_sessions` as a compatibility model during dual-write parity.
- Add append-only processing transition events beside current job state.
- Harden project-scoped idempotency, stale-client protection, retries and terminal consistency.
- Preserve guest-origin identity through immutable claim events.
- Add exact visible-exposure acknowledgements for owner, coach and peer surfaces.
- Keep candidate inventory distinct from actual rendered exposure.
- Capture Ideal Text and coach-draft exposures through explicit client acknowledgements.
- Preserve typed decisions and blind-review boundaries.
- Extend immutable dataset-release vocabulary to all seven systems.
- Add aggregate-only CEO readiness API and read-only frontend workspace.
- Add adversarial isolation, retry, duplicate, partial-failure, blindness and provenance tests.

### Migration strategy

- Additive migrations only.
- Backfill only provably successful and owned records.
- Mark uncertain history ineligible.
- Preserve new audit tables during application rollback.
- Gate canonical writes and reads until parity is verified.

### Acceptance criteria

- Failed/retried uploads preserve one recording attempt and create at most one successful Take.
- Only successful Takes receive contiguous project-scoped Take ordinals.
- Every processing transition and retry is reconstructable.
- Cross-owner/project reads and mutations fail, including same-named projects.
- Every visibly rendered learning item has one idempotent exposure receipt.
- Close, timeout and skip produce no negative decision.
- Shadow records are evaluation-only and never rendered.
- Blind coach/peer packets reveal no prior prediction or label.
- All seven readiness rows report honest counts, exclusions, versions, coverage, contradictions and blockers.
- Relevant tests and complete local CI pass before review.
- No public deployment occurs before product, data, technical and deployment acceptance.

Engineering approval statement:

> ENGINEERING APPROVED — The design is secure, maintainable, testable and operationally safe. Engineering design version: ED-1.
