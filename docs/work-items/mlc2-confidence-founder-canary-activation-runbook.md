# MLC-2 Confidence founder-canary activation runbook

Owner: Artur Willoński

Engineering design: `ED-2.4`

Learning contract: `MLC-2`, `data_epoch=1`

Status: **DEFERRED BY FOUNDER — DO NOT ACTIVATE**

This document preserves the exact decision and execution boundary for a future
founder-only Confidence Classification production canary. It is a runbook, not
an authorization. Reading, approving, merging or deploying this document must
not change runtime behavior.

Until the activation approvals in this document are supplied:

- `MLC2_CONFIDENCE_CUTOVER_MODE` remains hard-coded as `dark`;
- canonical Confidence producer writes remain disabled;
- the prior Confidence learning/provenance writer remains enabled;
- dataset release creation, training and model promotion remain disabled; and
- no operator may reinterpret a general deployment approval as canary
  activation approval.

## 1. Plain-language purpose

A canary is a deliberately small use of a new production path before wider
use. This canary is restricted to the exact acquisition principal belonging to
the founder. It does not expose the path to ordinary signed-in users or guests.

Dark mode proves that the schema, worker boundary, consent gate, monitor and
deployment are installed without receiving real Confidence events. It cannot
prove the final production hand-off:

```text
founder recording
  -> successful canonical Take
  -> transactional outbox event
  -> idempotent Confidence producer
  -> classifier prediction
  -> deterministic-policy selection run
  -> immutable candidate/sampling frame
  -> answer-free blind packet
```

The founder canary exists to prove this hand-off with tightly bounded real
production data while retaining a small blast radius.

## 2. The irreversible boundary

The Confidence writer state is one code-reviewed tri-state decision:

| Mode | Canonical Confidence writes | Prior learning write | Meaning |
| --- | --- | --- | --- |
| `dark` | off | on | Current pre-cutover state |
| `founder_canary` | on | off | Exact founder principal only |
| `killed` | off | off | Incident stop |
| invalid | off | off | Fail closed as killed |

Activation is not a temporary switch that may later return to `dark`.

Changing to `founder_canary` permanently retires the prior Confidence learning
writer. If the canary fails, the only permitted rollback state is `killed`.
That stops both learning writers but does not stop recording, transcription,
Ideal Text generation or ordinary feedback product state.

This rule prevents an incident rollback from silently resurrecting the old
learning path and contaminating provenance. It also means the activation
decision must be treated as a real cutover, even though the canonical producer
is initially founder-only.

## 3. Production state when activation was deferred

Read-only production verification on 2026-08-28 established:

- the bundled Product/legal consent policy is configured and valid;
- the founder personally granted both required purposes;
- the grant is bound to a canonical speaker;
- the exact founder acquisition principal is configured;
- the aggregate monitor and Sentry sink are configured;
- recurring `mlc2-confidence-readiness` runs succeed;
- the live report returns `ready=true` with no blockers;
- `canonical_writes_enabled=false`;
- `prior_learning_writes_enabled=true`;
- dataset creation, training and promotion are disabled; and
- the only warning is `no_runtime_canary_receipt_expected_while_dark`, which
  is correct before activation.

This is historical evidence, not a permanent waiver. Every live prerequisite
must be rechecked immediately before a future activation.

## 4. What activation changes—and what it does not

### It changes

- the reviewed code constant from `dark` to `founder_canary`;
- successful spoken Takes belonging to the exact founder principal may append
  canonical Confidence outbox/provenance records;
- the prior Confidence learning/provenance append becomes unavailable; and
- the canonical worker may create classifier, selection, candidate-frame and
  blind-packet provenance for eligible founder Takes.

### It does not change

- the user's recording, processing, Ideal Text or feedback experience;
- product-state writes needed by the current application;
- paragraph locks or orange-anchor state;
- the exact-three feedback policy;
- consent for any other principal;
- dataset eligibility or release membership;
- model training or promotion; or
- access for ordinary users and guests.

The same user action may continue to update existing product-state tables and
append a canonical ML event through the transactional outbox. It must not
write learning/provenance data to both the prior and canonical stores.

## 5. Decisions the founder must make at the future activation window

### Decision A — activate now or remain dark

The founder must explicitly accept that this is the permanent retirement
point for the prior Confidence learning writer. Remaining dark is safe and has
no effect on the product.

### Decision B — canary observation boundary

Choose exactly one reviewed boundary:

1. **One-Take canary (recommended):** admit one new successful founder spoken
   Take, then perform the complete evidence review before another Take; or
2. **Time-boxed canary:** admit founder Takes during a precisely stated time
   window and maximum receipt count.

If the chosen boundary must be technically guaranteed, Engineering must add a
database/producer-enforced receipt cap before activation. A UI instruction or
an operator remembering to stop is not an enforceable limit. This cap is not
part of the currently deployed dark implementation and requires separate
review.

### Decision C — successful exit

If the canary passes, keep `founder_canary` active only for the exact founder
principal while the evidence receives ML/data and Engineering acceptance.
Wider activation is a separate slice and authorization.

### Decision D — failed exit

If any stop condition is met, deploy the pre-reviewed `killed` state. Never
return to `dark`. Preserve append-only rows and queued outbox events for audit;
do not delete, rewrite or silently redirect them.

## 6. Preconditions that must all pass again

Do not propose activation unless every item below has fresh evidence:

1. Latest production source is identified by immutable commit.
2. The founder consent endpoint reports `configured=true`, `granted=true` and
   `speaker_bound=true` for the authenticated founder.
3. The active consent policy, approved copy checksum, Terms version and Privacy
   version match the approved immutable legal artifact.
4. The exact configured `acquisition_principal_id` matches the founder's
   Project owner principal. Email alone is insufficient.
5. Founder-only scope tests reject ordinary authenticated accounts, guests,
   missing principals and mismatched principals.
6. The pre-activation aggregate report is `ready=true`, has no blocker codes,
   and reports every zero invariant at zero.
7. `DATA_FOUNDATION_CANARY_ENABLED=true` and the foundation producer boundary
   is healthy.
8. Sentry delivery is tested, not merely configured.
9. Dataset creation, training and promotion are false in both code and
   production evidence.
10. There are no pending or failed Confidence outbox events.
11. Product smoke tests pass for founder, ordinary signed-in and guest paths.
12. A reviewed `killed` deployment is prepared before activation.
13. An operator and the founder are available for the complete observation
    window.

### Monitoring implementation gate

The currently deployed readiness evaluator intentionally treats every mode
other than `dark` as blocked. It proves readiness; it is not sufficient as the
sole post-activation monitor.

Before activation, Engineering must deliver and review an activation-aware
aggregate canary monitor (or a separately typed canary-observation mode) that:

- expects `founder_canary` rather than reporting activation itself as an
  incident;
- still alerts on every non-founder receipt/event;
- checks outbox, receipt, candidate-frame and blind-packet lineage;
- checks duplicate/idempotency violations;
- confirms prior learning writes remain disabled;
- confirms dataset, training and promotion remain disabled;
- emits aggregate IDs/counts and reason codes only; and
- never emits audio, transcript, candidate text, blind answers or user
  labels.

The existing dark-readiness monitor remains useful before activation. During
the live canary, the activation-aware check must run before the Take,
immediately after processing and at least once per minute through the agreed
observation window.

## 7. Required approvals

The following approvals are independent. Readiness acceptance documents
evidence but changes no runtime state. The final activation authorization is
the only approval that permits the code change and deployment.

### ML/data readiness acceptance

> **ML/DATA CANARY READINESS ACCEPTED — MLC-2 Confidence.** The current founder
> consent, exact acquisition principal, speaker binding, monitoring, blindness,
> idempotency, zero-invariant and disabled-downstream evidence satisfy MLC-2
> and ED-2.4 for the stated canary boundary. This acceptance does not itself
> authorize deployment or runtime activation.

### Engineering readiness acceptance

> **ENGINEERING CANARY READINESS ACCEPTED — MLC-2 Confidence.** The founder-only
> scope, atomic writer cutover, activation-aware monitoring, product isolation,
> enforceable canary boundary and pre-reviewed `killed` path are secure,
> maintainable, testable and operationally ready. This acceptance does not
> itself authorize deployment or runtime activation.

### Founder activation authorization

For the recommended one-Take boundary:

> **FOUNDER CONFIDENCE CANARY ACTIVATION AUTHORIZED.** Change the reviewed
> Confidence cutover from `dark` to `founder_canary` and deploy it for Artur
> Willoński's exact acquisition principal only. Admit at most one new successful
> spoken Take under the approved canary boundary, then stop and verify the full
> evidence pack before permitting another. Atomically disable the prior
> Confidence learning writer. Preserve all product-state behavior. Keep dataset
> creation, training, promotion and wider rollout disabled. On any failed
> invariant, deploy `killed`; never return to `dark`.

The authorization must identify the activation commit, planned production
window and selected observation boundary. A generic “push to prod,” “go,” or
deployment approval is insufficient.

## 8. Engineering execution sequence

1. Record the latest production commit and fresh dark-readiness JSON report.
2. Complete any approved receipt-cap and activation-monitor work.
3. Run the Confidence dependency audit checks and the complete focused test
   matrix.
4. Prepare two reviewed changes:
   - activation: `dark` -> `founder_canary`;
   - incident stop: `founder_canary` -> `killed`.
5. Confirm the activation change does not make the cutover mode an environment
   variable. Railway must not provide an unreviewed activation switch.
6. Obtain all three approvals above against exact commits and evidence.
7. Deploy backend, worker and activation-aware monitor from the same reviewed
   source lineage.
8. Do not run a database reset, historical relabel, dataset build, training job
   or model promotion.
9. Immediately verify the resolved writer state:
   - mode is `founder_canary`;
   - canonical Confidence writes are enabled;
   - prior Confidence learning writes are disabled;
   - founder identity and principal scope are exact;
   - non-founder canonical counts remain zero.
10. If the initial activation check is green, ask the founder to create the one
    agreed new spoken Take.
11. Observe product processing and canonical processing separately. Product
    success must not be inferred from canonical ML success, or vice versa.
12. Freeze further canary input at the agreed boundary and assemble the
    evidence pack.

## 9. One-Take verification checklist

### User-visible product checks

- Recording upload and processing complete normally.
- Ideal Text remains loadable.
- The Take produces the intended feedback set and no duplicate UI cards.
- Paragraph locks, orange anchors and versioning behave normally.
- No internal ML/provenance identifiers or errors appear in the UI.

### Canonical lifecycle checks

- Exactly one successful RecordingAttempt is promoted to exactly one Take.
- `attempt_count` describes processing attempts and does not create extra
  Takes.
- Product mutation and outbox insertion share the approved transaction.
- The outbox event is processed at least once with effectively-once canonical
  results through idempotency.
- Exactly one producer receipt exists for the event.
- No receipt exists without its originating outbox event.
- No processed event lacks its finalized candidate frame.
- The prior Confidence learning append did not run.

### Confidence provenance checks

- The classifier run, model/provider/version and prediction lineage exist.
- The confidence selection run is
  `execution_kind=deterministic_policy`, not an eighth learning system.
- The selection run references the underlying classifier predictions.
- The complete eligible pool and every excluded candidate with reason code are
  frozen atomically.
- Scores, ranks, thresholds, 20% exploration decision, selection
  probabilities, RNG provenance, policy versions and immutable pool hash are
  present.
- Project, Take, recording, clip, evidence-span, speaker and acquisition
  principal lineage is complete.
- Machine prediction, user self-report, blind coach judgment and blind peer
  judgment remain separate records.

### Blindness checks

- Every blind assignment references an exact answer-free packet and immutable
  packet hash.
- The packet reveals no machine score, selection reason, exploration status,
  user answer or other rater answer.
- No reveal occurs before an immutable independent judgment.
- A later reconsideration creates a new judgment with `supersedes_id`; it
  never edits the original.

### Isolation checks

- Non-founder producer receipts remain zero.
- Non-founder canonical Confidence events remain zero.
- Ordinary signed-in and guest feedback remains operational.
- Dataset releases, training runs and promotion records remain disabled.
- Logs and alerts contain aggregate evidence only.

## 10. Stop conditions

Any one of the following stops the canary immediately:

- a non-founder canonical receipt or event;
- canonical and prior Confidence learning writers both writing;
- missing, invalid or withdrawn founder consent;
- founder principal mismatch;
- duplicate canonical result for one idempotency key;
- outbox/receipt/candidate-frame lineage gap;
- blind packet leakage or premature reveal;
- product recording, processing, Ideal Text or feedback regression;
- dataset, training or promotion capability becoming enabled;
- monitor or alert-path failure; or
- breach of the approved Take/time/receipt boundary.

Incident response:

1. Stop new founder canary input.
2. Deploy the reviewed `killed` state.
3. Confirm canonical and prior learning writers are both false.
4. Preserve queued events and append-only evidence.
5. Do not delete, relabel, backfill or return to `dark`.
6. Record the incident and obtain new ML/data and Engineering review before any
   later restart proposal.

## 11. Evidence pack and acceptance after the Take

The operator must retain:

- activation and deployed commit IDs;
- all three approval texts and timestamps;
- pre-activation dark-readiness report;
- post-activation writer-state report;
- canary monitor reports through the observation window;
- aggregate before/after counts;
- exact Take/Attempt/outbox/receipt/frame/assignment identifiers;
- idempotency and lineage verification results;
- blindness verification result;
- product smoke-test result for founder, ordinary user and guest;
- confirmation that prior learning writes did not run;
- confirmation that dataset, training and promotion remained disabled; and
- pass, `killed`, or unresolved final disposition.

After the evidence exists, obtain separate ML/data and Engineering
implementation acceptance. Those acceptances may keep the founder canary
running; they do not authorize ordinary-user expansion, datasets, training or
promotion.

## 12. Explicitly out of scope

This runbook does not authorize:

- activation now;
- any non-founder canonical Confidence producer;
- historical import, relabeling or backfill;
- dual-writing learning provenance;
- dataset creation;
- training or evaluation release creation;
- model training, adapter creation or model promotion;
- changing the other six learning surfaces; or
- replacing explicit approvals with an environment-variable toggle.

## 13. Future execution prompt

Use this only after Sections 5–7 have been decided and accepted:

> Execute the approved MLC-2 Confidence founder-canary runbook. Re-run every
> precondition against current production and stop on any blocker. Implement
> and verify the approved canary boundary and activation-aware aggregate
> monitor. Prepare reviewed `founder_canary` and `killed` changes. Obtain the
> recorded ML/data, Engineering and founder activation approvals against exact
> commits. Deploy only the exact founder principal path, admit only the agreed
> canary input, verify the complete product, provenance, blindness,
> idempotency and isolation evidence pack, and report the final disposition.
> Keep wider rollout, datasets, training and promotion disabled. Never return
> to `dark` after activation.

> **DEFERRED — The MLC-2 Confidence founder canary remains dark until the
> explicit future activation procedure above is completed.**
