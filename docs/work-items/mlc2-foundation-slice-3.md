# MLC-2 Foundation Slice 3 — Confidence Audit and Dark Contracts

Owner: Artur Willoński

Engineering design: `ED-2.4`

Learning contract: `MLC-2`, `data_epoch=1`

Branch: `codex/mlc2-foundation`
Status: `IMPLEMENTED LOCALLY — AWAITING ML/DATA + ENGINEERING REVIEW`

Decision-filter stamp:

`FILTER: ADVANCE-F2 — cat F2 — fences clear — locks clear — redirect: preserve the recording loop and keep canonical producers and legacy cutover disabled.`

## Authorization boundary

Authorized and completed:

- Complete Confidence Classification producer/reader/route/job/UI dependency
  audit.
- Typed, additive, dark runtime contracts.
- Atomic immutable confidence sampling-frame finalization.
- Static, unit and disposable PostgreSQL verification.

Still not authorized and not performed:

- Product producer activation or any route/worker import.
- Legacy learning-path cutover, dual learning-provenance writes or deletion.
- Historical import or relabeling.
- Dataset creation, training, evaluation promotion or model promotion.
- Merge, push, staging change or deployment.

## Dependency-audit result

`docs/MLC2-CONFIDENCE-DEPENDENCY-AUDIT.md` maps the live analysis worker,
acoustic classifier, exact-three Manager, take feedback, user self-report,
blind coach queue/judgment, revealed professional controls, practice flow,
Voice Album quorum, corpus/export readers and frontend/BFF consumers.

The audit classifies the legacy stores as product-state, mixed-purpose or
learning-only.  Current product-state writers remain untouched.  Legacy
training/export stores are explicitly prohibited as MLC-2 inputs.  Unknown
dependencies fail closed.

## Dark implementation

Migration `0303` adds six append-only, RLS-protected tables:

- `ml_model_runs`
- `ml_classification_runs`
- `ml_machine_predictions`
- `ml_selection_runs`
- `ml_candidate_sets`
- `ml_candidates`

`finalize_mlc2_confidence_frame_v1` atomically persists:

- the canonical event and acquisition-bound consent snapshot;
- provider-neutral classifier execution;
- exact non-empty R2 audio evidence and feature/detector/threshold versions;
- machine outputs kept separate from human judgments;
- a deterministic policy run linked to its classifier predictions;
- fixed 20% exploration, RNG algorithm/seed/draws and policy versions;
- every eligible and excluded candidate, reason, score when available, rank,
  sampling probability, selection reason and selected row;
- an immutable, server-computed pool hash.

At-least-once replays return the same frame only when both the canonical
envelope and complete manifest match.  A conflicting replay fails.  A late
candidate error rolls back the canonical event, evidence, runs, predictions,
candidate frame and outbox completion together.

`services/mlc2_confidence.py` validates the typed contract before the RPC.
`Config.MLC2_CONFIDENCE_CANONICAL_WRITES_ENABLED` is hard-coded `False` and is
not an environment switch.  Static tests prove no live product module imports
the dark service.

## Verification evidence

Disposable PostgreSQL 16 rehearsal on 2026-08-27:

- Created a local-only database using the checked-in minimal prerequisite
  shape; migrations `0001..0301` were baselined.
- Applied `0302` and final `0303` normally from a clean database.
- Reapplied `0303` directly without error.
- Finalized one complete pool containing one eligible selected candidate and
  one excluded candidate.
- Verified provider/model, feature, threshold, policy, RNG, exact evidence and
  immutable-hash lineage.
- Verified effectively-once replay.
- Verified a late invalid candidate leaves no canonical event, model run,
  candidate set or completed outbox state.
- Verified `anon`/`authenticated` cannot read the new tables, `service_role`
  has SELECT but no direct INSERT, and all new rows are append-only.
- All rehearsal fixtures ended in `ROLLBACK`; the local cluster was stopped.

Repository gates:

- Migration manifest and runner: pass, 303 ordered migrations.
- Focused Slice 3 contract suite: pass.
- Ruff `0.15.8`: pass.
- Mypy `2.3.0`: pass.
- Full unit tier: 4,818 passed, 9 skipped, 127 subtests passed.
- Live/model evals: not applicable to a disconnected dark contract; not run.

## Review and next gate

ML/data review should verify the audit classification, exact evidence,
classifier/selection separation, deterministic-policy-only confidence
selection, 20% exploration provenance, immutable frame and consent boundary.

Engineering review should verify migration `0303`, its SECURITY DEFINER RPC,
RLS/grants, append-only enforcement, idempotency and transactional rollback.

Acceptance of Slice 3 still does not authorize activation or cutover.  The
next implementation slice must be separately defined and authorized.

> CONFIDENCE DARK CONTRACTS READY — Slice 3 is locally complete. No live
> producer, legacy path, dataset, model or production behavior changed.
