# MLC-2 Foundation Slice 1

Owner: Artur Willoński  
Engineering design: `ED-2.4`  
Learning contract: `MLC-2`, `data_epoch=1`  
Branch: `codex/mlc2-foundation`  
Status: `IMPLEMENTED — AWAITING REVIEW AND MIGRATION REHEARSAL`

## Authorization boundary

Authorized: Foundation Slice 1 implementation and verification.

Not authorized:

- legacy learning-path changes;
- historical import or relabeling;
- dataset release creation;
- training or promotion;
- per-surface cutover;
- deployment or merge-to-production.

## Implemented

- Sole seven-surface registry and explicit/rejected aliases.
- Independent feedback-family, pipeline-stage and product-operation
  vocabularies.
- Canonical speaker/principal binding and deterministic speaker-level
  80/10/10 split assignments.
- Product/legal approval records, required bundled consent purposes,
  Article 6/Article 9 provenance, withdrawals, immutable snapshots and purge
  requests.
- Leased transactional outbox with at-least-once delivery and idempotent,
  atomic canonical finalization.
- Shared MLC-2 event envelope with typed surface payload identity.
- Immutable evidence, semantic artifact, R2 object and checksum-verification
  foundations.
- Blind review assignments, submit-before-reveal control and independently
  provenanced judgments.
- Authenticated post-render exposures; shadow packets cannot acknowledge.
- Paragraph/orange decisions isolated in `ml_product_actions`.
- Aggregate-only foundation health RPC.
- Dark-by-default configuration with dataset, training and promotion hard
  disabled.
- Checked-in conservative legacy dependency inventory and code isolation
  guard.

## Verification

Final local gate:

- Migration manifest: pass, 302 ordered migrations.
- Migration runner: 66 tests passed.
- Ruff `0.15.8`: pass.
- Mypy `2.3.0`: pass across 319 source files.
- Unit tier: 4,795 passed, 9 skipped, 127 subtests passed.
- New focused MLC-2 tests: 27 passed.
- `git diff --check`: pass.
- Live/model evals: not applicable to this dark foundation; not run.

## Required before merge

Because `MIGRATE_ON_BOOT=1` makes a merge equivalent to applying migration
`0302` in production, the following remain mandatory:

1. Independent engineering review of migration `0302` and its RPC grants.
2. Apply/reapply migration rehearsal against an isolated PostgreSQL/Supabase
   schema matching production.
3. Verify all 28 MLC-2 tables have RLS enabled and no anon/authenticated
   policy or function access.
4. Exercise speaker registration, consent grant/withdrawal, snapshot,
   outbox claim/finalize/retry, render ACK and blind reveal RPCs in the
   rehearsal database.
5. Verify the actual Product/legal approval artifact before inserting an
   active consent policy.
6. ML/data acceptance of the implemented foundation.
7. Separate merge/deployment approval.

## Rollback

No product route is connected, so application rollback is disabling the
foundation flag and reverting application code while retaining append-only
rows. Do not down-migrate or delete foundation tables. Queued outbox events
remain intact. Legacy learning writes are untouched by this slice and no
cutover can be rolled back because none occurred.

## Known blocked work

- Every legacy surface audit remains blocked/unknown as recorded in
  `docs/MLC2-LEGACY-DEPENDENCY-AUDIT.md`.
- No active Product/legal approval row or consent policy is seeded.
- No surface-specific typed producer is active.
- No canonical dataset/release/training module exists or is enabled.

> FOUNDATION IMPLEMENTED — MLC-2/ED-2.4 Slice 1 awaits Engineering and ML/data review plus an isolated migration rehearsal. No deployment or cutover has occurred.

