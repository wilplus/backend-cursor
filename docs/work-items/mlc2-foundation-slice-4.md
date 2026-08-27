# MLC-2 Foundation Slice 4 — Dark Confidence Producer Integration

Owner: Artur Willoński

Engineering design: `ED-2.4`

Learning contract: `MLC-2`, `data_epoch=1`

Branch: `codex/mlc2-foundation`

Status: `IMPLEMENTED LOCALLY — AWAITING ML/DATA + ENGINEERING REVIEW`

## Authorization boundary

Authorized: dark Confidence Classification producer integration, blind-packet
contracts, monitoring and cutover rehearsal.

Not authorized and not performed: producer activation, legacy cutover,
dataset creation, training, promotion, merge, push or deployment.

## Delivered boundary

- Migration `0304` adds an immutable producer receipt and an immutable blind
  packet record.
- Future enabled promotion commits the successful Take and typed outbox event
  atomically. At-least-once worker delivery produces effectively-once canonical
  results through the Slice 3 finalizer.
- The worker claim is surface and event-type filtered.
- Blind packets are constructed server-side from exact selected audio evidence
  and the five-state taxonomy. They carry no answer or selection hints.
- Blind judgments require a rendered-exposure ACK; comparison reveal requires
  the immutable judgment.
- Monitoring names pending/failed producer work and impossible lineage gaps.
- One hard-disabled code flag selects the canonical producer branch and
  disables the old learning shadow branch. Product read models remain intact.

## Activation state

`Config.MLC2_CONFIDENCE_CANONICAL_WRITES_ENABLED = False`.

The dark worker has no RQ registration or sweeper import. The migration seeds
no consent approval, dataset release, training run, model assignment, cutover
event or promotion record.

## Verification evidence

Disposable PostgreSQL 16 rehearsal on 2026-08-27:

- Loaded the production-coordinate prerequisites and the existing `0297` Take
  lifecycle, then applied `0302`, `0303` and `0304`.
- Reapplied the final `0304` migration without error.
- Proved missing consent rolls back Take promotion, producer receipt and outbox
  together.
- Proved successful producer replay creates exactly one Take, receipt and
  outbox event.
- Proved the confidence worker lease cannot claim a praise event.
- Finalized a complete confidence frame through the Slice 3 atomic finalizer.
- Created an answer-free five-state blind packet, acknowledged a rendered
  exposure, rejected reveal before judgment, stored an immutable blind coach
  judgment, and revealed only afterward.
- Verified monitoring invariants, append-only enforcement and browser-role
  read denial.
- Rolled back every rehearsal fixture and stopped the local cluster.

Repository gates:

- Migration manifest and runner: pass, 304 ordered migrations.
- Focused Slice 4 contracts: 36 passed.
- Ruff `0.15.8`: pass.
- Mypy `2.3.0`: pass.
- Full unit tier: 4,849 passed, 9 skipped, 127 subtests passed.
- Live/model evals: not applicable to a dark, disconnected producer; not run.

> CONFIDENCE PRODUCER INTEGRATION READY — Slice 4 is locally complete. The
> cutover flag is still disabled. No producer, legacy cutover, dataset, model,
> merge or deployment was activated.
