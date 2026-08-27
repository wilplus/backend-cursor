# Production Data Foundation

Contract versions: Product `PDF-1`, ML/Data `MLC-1`, Engineering `ED-1`

Decision-filter stamp: `ADVANCE-F2`; fences clear; L1/L2/L3 clear.

Scope: collection reliability and future dataset readiness only. No training or model promotion is implemented.

## Canonical relationship map

```text
owner_principals
  └─ projects
      ├─ recording_attempts ── processing_transition_events
      │    └─ takes (successful spoken attempts only; contiguous project ordinal)
      │         ├─ evidence_spans
      │         │    ├─ candidate_sets ── feedback_candidates
      │         │    ├─ generation_runs
      │         │    ├─ machine_predictions
      │         │    ├─ confidence_self_reports
      │         │    ├─ confidence_coach_labels
      │         │    ├─ confidence_peer_labels
      │         │    ├─ praise_helpfulness
      │         │    ├─ correction_decisions
      │         │    └─ feedback_revisions
      │         ├─ learning_surface_presentations
      │         │    └─ learning_surface_exposure_receipts
      │         └─ paragraphs ── paragraph_decisions ── root_phrases
      └─ owner_claim_events (immutable guest → authenticated transfer proof)

dataset_releases (one learning surface only)
  ├─ dataset_split_assignments (stable owner/speaker split)
  ├─ dataset_release_items
  └─ dataset_exclusions
```

`v2_sessions` remains the compatibility read model during parity. A canonical
`recording_attempt` is created once durable audio and verified ownership exist.
Only a successful spoken attempt is promoted to `takes`; failures retain audio,
remain retryable and do not consume a Take ordinal.

## Exposure-to-release data flow

```text
durable audio
→ RecordingAttempt
→ append-only processing transitions
→ successful canonical Take
→ immutable transcript/evidence snapshot
→ complete CandidateSet + generation provenance
→ Manager selects one item in each locked Feedback family
→ actor-specific learning_surface_presentation is prepared
→ exact item visibly paints in an authenticated client
→ post-render ACK creates learning_surface_exposure_receipt
→ optional typed decision event (absence stays unanswered)
→ optional immutable blind coach/peer judgment or later revision
→ explicit eligibility/exclusion review under an authorized consent policy
→ immutable, single-surface dataset release with speaker-disjoint split
```

Preparing, selecting, fetching, preloading, closing, timing out or skipping does
not create a visible exposure or a negative decision. Shadow packets persist as
`evaluation_only`; the API never returns them for rendering and the receipt RPC
rejects them.

## Seven isolated learning surfaces

| Surface | Visible packet | Answer instrument | Release boundary |
|---|---|---|---|
| `confidence_classification` | Exact audio clip; blind packet excludes words and prior judgments | Typed owner/coach/peer confidence event, provenance kept separate | Exact evidence span |
| `correction_generation` | Manager-selected verbal correction plus complete candidate inventory | Typed correction decision | Exact evidence span |
| `coach_comment_generation` | Coach draft after the same coach's immutable blind judgment | Immutable coach revision | Exact evidence span |
| `praise_generation` | Evidence-backed praise plus complete candidate inventory | Typed helpfulness response | Exact evidence span |
| `praise_selection` | Same visible praise; distinct selection dataset | Typed helpfulness response | Exact evidence span |
| `correction_selection` | Same visible correction; distinct selection dataset | Typed correction decision | Exact evidence span |
| `ideal_text_generation` | Exact canonical document visibly rendered | No generic answer is inferred; later explicit document/paragraph events remain separate | Canonical Take + document hash |

The coach-comment surface is intentionally reported as blocked until a generated
draft is actually active in product. The retired prefill path is not revived to
manufacture data.

## Cross-owner and cross-project threat model

| Threat | Enforcement |
|---|---|
| Same project name treated as identity | All canonical reads/writes use UUID owner + project + Take coordinates; names never join data. |
| Retry creates two Takes | Project upload idempotency plus unique attempt key; promotion is idempotent and Take ordinal is unique. |
| Failed attempt looks successful | Terminal states are explicit; Take promotion is the sole successful boundary; Take 1 additionally requires confirmed Ideal Text. |
| Stale client acknowledges another actor's packet | Receipt RPC checks presentation ID, secret ACK token, authenticated actor role/ID and stable render instance. |
| Server fetch counted as exposure | Presentation and receipt are different append-only tables; only post-paint client ACK writes a receipt. |
| Shadow output reaches users | Shadow packets are `evaluation_only`, omitted by mappers and rejected by the ACK RPC. |
| Blind coach receives an answer hint | Packet allowlist contains audio/timing only and SQL rejects prediction, self-report, judgments or transcript keys. |
| Guest claim destroys origin | Atomic transfer retains the guest principal and appends an immutable claim event with source, target and proof hash. |
| Owner response becomes gold label | Machine, owner, blind coach and blind peer tables remain separate; release provenance cannot contain a collapsed generic label. |
| Speaker appears across train/test | Split is a stable hash of canonical owner/speaker identity, not project, Take, clip or name. |

## Honest readiness calculations

`get_seven_surface_readiness_v1()` returns exactly seven aggregate-only rows to
the Research view in CEO. It reports:

- prepared production packets, shadow packets and confirmed render receipts;
- answered/unanswered counts only where a typed answer instrument is defined;
- distinct owners/speakers, projects, Takes and coaches;
- complete version payloads and missing-version counts;
- eligible, research-only and excluded items with exclusion reasons;
- owner-level split-assignment coverage;
- confidence self-report/coach contradictions;
- explicit `not_captured` or `not_defined` states for language, device,
  recording-condition, semantic-duplicate and non-confidence contradiction
  metrics.

An unsupported metric is never displayed as zero. Existing Terms acceptance is
not interpreted as training authorization. A dataset release is authorized only
when its immutable `consent_retention_status.training_authorized` is explicitly
true.

## Legacy paths preserved

- `v2_sessions`: product compatibility read model during canonical dual-write
  parity. Removal would be a separate approved cutover.
- `feedback_exposures.shown_at`: retained for history; documented as a server
  selection timestamp, never render proof.
- Existing raw feedback and confidence tables: retained so product behavior and
  historical reads continue while canonical events build parity.
- Retired coach-comment prefill storage: retained for history/revert safety but
  not treated as a current visible learning surface.
- Uncertain historical rows: retained and excluded; no inferred ownership,
  consent, evidence or version is backfilled.

## Operational blockers

The CEO report exposes these instead of hiding them:

- no authorized ML-training consent/retention release;
- language, device and recording-condition coverage are not yet captured in the
  canonical exposure contract;
- semantic duplicate detection is not yet defined;
- contradiction instruments exist only for Confident Voice today;
- coach-comment generation is blocked while the generated prefill is inactive;
- production migration `0297` through `0301` must apply before canonical writes
  and readiness queries are available.

## Rollback

Disable the new dual-writes and CEO readiness read, then roll application code
back. Preserve append-only audit tables. Do not reverse ownership claims or
delete canonical records. Immediate rollback triggers are ownership leakage,
blindness leakage, locked-text regression, contradictory terminal state or data
integrity failure.
