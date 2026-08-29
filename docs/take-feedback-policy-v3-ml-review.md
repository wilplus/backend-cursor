# Take Feedback Policy v3 — ML/data review packet

Status: implemented dark, disabled by default. This document requests design
and implementation review only. It does not request activation, dataset
creation, training, or promotion.

## Runtime boundary

- Current policy ID: `take-feedback-policy-v3-universal-dark-v3`.
- Frame schema: `take-feedback-policy-v3-frame-v3`.
- Migration 0309 and `take-feedback-policy-v3-dark-v2` remain immutable
  historical contracts; migration 0311 adds the universal-v3 write boundary.
- Activation requires both `TAKE_FEEDBACK_POLICY_V3_MODE=dark` and an exact
  match with `TAKE_FEEDBACK_POLICY_V3_FOUNDER_PRINCIPAL_ID`.
- The current v2 Manager remains the only serving path.
- A dark computation is not delivery and not exposure.
- The immutable shadow table structurally forces `rendered_exposure_id=NULL`
  and `dataset_eligible=FALSE`.

## Candidate inventory

Every current-Take document piece enters a slide-bounded inventory or a typed
exclusion. Clip eligibility requires the Take's immutable recording ID plus an
exact matching snippet ID, Take ID, recording ID, non-negative start offset and
positive duration in both the document and persisted snippet. A URL or generic
audio reference is availability only and is never eligibility evidence. The
canonical coordinates receive their own SHA-256 identity. No transcript or
generated wording is stored in the shadow frame.

Within each contiguous slide run, a deterministic global partition chooses
snippet-boundary blocks closest to 75 words. The normal range is 60–90 words;
an indivisible long or short snippet remains intact rather than altering speech.

For every block, all exact-lineage audio candidates are retained. Selection is
lexicographic and reproducible:

1. Exact clip lineage eligibility.
2. Comparable, current-version stamped acoustic score present.
3. Highest speaker-relative `voice-confidence-universal-v3` score.
4. Spoken order and candidate ID as stable tie-breakers.

No retired personality, psychological, or sex-routed construct participates
in ranking. A stamped `voice-confidence-v2` candidate remains in the frozen
inventory as `excluded/incompatible_detector_version` until the exact clip is
recomputed. It is never silently converted into an unmeasured candidate.

The winner is the best delivery *relative to that block*. No absolute positive
threshold is required. A non-positive or unmeasured winner carries tentative
language and must never be represented as an objectively confident moment.

Take 1 selects confidence candidates only. Take 2 and later additionally retain
the complete current-Take rewrite and praise pools, selecting one global
absolute-quality winner from each. Invalid rewrite and praise rows are not
dropped: their identity, input position, known provenance, and typed exclusion
reason remain frozen. Slide diversity is not allowed to outrank materially
stronger evidence.

## Reproducibility boundary

Every frame freezes the policy/frame versions, confidence detector version,
acoustic-feature schema version, suggestion-generator contract and observed
producer versions, Manager rules and evidence-schema versions, and a SHA-256 of
all four source modules that can affect the result. The deployment commit is
also stored when the runtime provides it. Versionless verbal candidates remain
in the inventory but are excluded from selection.

The service role has read-only table access. The current write boundary is the
new validating `record_take_feedback_policy_v3_shadow_v3` security-definer RPC,
which independently verifies Take ownership, recording identity, exact snippet
interval lineage, universal-v3 version metadata, typed incompatibility, and
dark non-exposure/non-dataset invariants. The old v2 RPC is not modified.

## Exposure and blindness

- Server computation, storage, polling, and delivery are not exposure.
- A future exposure exists only after authenticated client render confirmation.
- Machine score/version, detector tier, cue keys, selection reason, and all
  other human answers remain absent from a blind review packet until the
  independent judgment is immutably submitted.
- Shadow frames are evaluation evidence only and are rejected by dataset
  builders until a separately approved contract says otherwise.

## Review questions

ML/data should explicitly accept or reject:

1. The 75-word, 60–90 normal block definition and exact-snippet cut boundary.
2. The lexicographic relative-confidence definition, including the explicit
   difference between a genuinely missing measurement and an incompatible v2
   measurement, and between "best available" and "confident".
3. The completeness and reason codes of the candidate/exclusion inventory.
4. The Take 1 versus Take 2+ lane policy.
5. The non-exposure semantics and blind-field denylist.
6. The fact that these frames are non-training, non-dataset product-policy
   evidence until a future, separately approved release contract exists.

Requested verdict:

> ML/DATA REVIEWED — `take-feedback-policy-v3-universal-dark-v3` candidate inventory,
> relative-confidence definition, exposure semantics, and leakage controls are
> accepted for founder-only dark comparison. This does not authorize serving,
> datasets, training, or promotion.

## Version-transition verification

- Migration 0309 was left unchanged and continues to own only its historical
  v2 RPC/contract.
- Migration 0311 adds the universal-v3-only RPC and an immutable reconciliation
  ledger keyed by exact Take, recording, snippet, interval, candidate and clip
  identity. The historical v2 RPC remains defined for audit but service-role
  execution is revoked after the transition.
- The PostgreSQL rehearsal writes one historical v2 frame with two exact clips
  and one current v3 frame that recomputes only one. It verifies exact replay,
  rejects changed replay, rejects eligible v2 input, rejects falsified lineage
  on an excluded v2 clip, and proves that the unrecomputed clip remains only
  `incompatible_detector_version`.
- Unit tests prove that a v2 measurement becomes
  `excluded/incompatible_detector_version`, never an unmeasured ranked item.
