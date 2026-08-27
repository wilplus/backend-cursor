# MLC-2 Foundation Slice 2 — Database Rehearsal and Hardening

Owner: Artur Willoński
Engineering design: `ED-2.4`
Learning contract: `MLC-2`, `data_epoch=1`
Branch: `codex/mlc2-foundation`
Status: `IMPLEMENTED LOCALLY — AWAITING REVIEW`

Decision-filter stamp:

`FILTER: ADVANCE-F2 — cat F2 — fences clear — locks clear — redirect: keep every learning path dark until its dependency audit and ML/data review pass.`

## Authorization boundary

Authorized:

- Isolated migration apply/reapply rehearsal.
- Foundation SQL correction discovered by that rehearsal.
- Repeatable RPC, RLS, grant, idempotency, blindness and exposure checks.

Still not authorized:

- Production or staging database changes.
- Legacy learning-path changes or dual learning writes.
- Historical import/relabeling.
- Dataset creation, training or promotion.
- Per-surface cutover, merge or deployment.

## Result

The first true PostgreSQL apply found an extra closing parenthesis in the
`ml_judgments` definition. PostgreSQL rolled back the whole migration. The
defect was removed, after which migration `0302` applied and reapplied
successfully against PostgreSQL 16.

`tests/integration/mlc2_foundation_rehearsal.sql` now exercises the sensitive
foundation behavior with transaction-scoped fixtures:

- stable speaker/principal registration and split assignment;
- documented bundled consent and acquisition-bound snapshot;
- at-least-once outbox claim/fail/retry behavior;
- effectively-once canonical finalization;
- rejection of shadow render acknowledgements;
- authenticated production render acknowledgement;
- rejection of blind reveal before submission;
- successful reveal after immutable submission;
- exactly seven learning surfaces;
- RLS on all 29 MLC-2 tables;
- no `anon`/`authenticated` table grants;
- no direct service-role writes and no public MLC-2 RPC execution;
- append-only canonical-event enforcement.

The rehearsal uses a disposable local PostgreSQL cluster and never connects to
Supabase, Railway, staging or production. All scenario fixtures end in
`ROLLBACK`.

## Next gate

Engineering and ML/data review must accept the corrected migration and
rehearsal evidence. After that, the next implementation slice is the complete
Confidence Classification dependency audit plus typed, dark runtime contracts.
That later slice may not activate a producer or stop any legacy learning write
without its own ML/data review and explicit cutover authorization.

> FOUNDATION HARDENED — Slice 2 is locally complete. No production state,
> dataset, model, legacy path or user-facing behavior changed.
