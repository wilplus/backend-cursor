# MLC-2 Slice 6A — Founder consent and recurring readiness remediation

Owner: Artur Willoński

Engineering design: `ED-2.4`

Learning contract: `MLC-2`, `data_epoch=1`

Status: `IMPLEMENTED LOCALLY — DARK DEPLOYMENT AUTHORIZED`

Founder-canary activation was subsequently deferred. The authoritative future
activation procedure is
[`mlc2-confidence-founder-canary-activation-runbook.md`](mlc2-confidence-founder-canary-activation-runbook.md).
This link is documentation only and grants no runtime authorization.

Decision filter: `ADVANCE-F2`. This slice closes approved identity, consent,
provenance and monitoring gates. It changes no Construct fence, L1–L3 label or
live learning loop.

## Authorization boundary

Authorized: deploy the verified founder acquisition-principal flow, approved
Product/legal consent configuration, founder consent UI, exact-principal
configuration and recurring aggregate readiness monitor.

Not authorized: creating consent for the founder, changing the hard-coded
`dark` cutover mode, activating canonical Confidence writes, stopping the prior
learning writer, creating datasets, training or promoting models.

## Product/legal contract

The immutable approval artifact is
`legal/mlc2-bundled-consent-v1.json`. It binds the exact onboarding copy,
Product/legal approval reference, Terms and Privacy version `1.2`, Article
6(1)(a), the conditional Article 9(2)(a) treatment and an immutable Cloudflare
R2 object key/checksum.

Migration `0306` adds service-role-only configuration and exact-principal
status RPCs. It creates no approval row, policy, principal binding or consent.
Migration `0307` is a data-free production compatibility correction: it makes
the six MLC-2 SHA-256 RPCs resolve `pgcrypto` from Supabase's trusted
`extensions` schema. It activates no writer and changes no product state.
`scripts/configure_mlc2_consent_policy.py` verifies the checked-in artifact,
uploads or byte-verifies the immutable R2 object, reads it back, verifies its
SHA-256, and then registers the approval and one active policy. It never calls
the consent-grant RPC.

Only the authenticated founder account receives the bundled consent gate.
The checkbox starts unselected. A POST must carry the exact policy version and
copy checksum the server returned. Only that affirmative action binds the
verified acquisition principal to a speaker and appends the two-purpose grant.
Declining stores no judgment or consent. Withdrawal appends a new immutable
event, starts the canonical purge process and ends recording/coaching access.

The legal gate does not reuse the old local Welcome transition and therefore
cannot reset an active Lab state. Ordinary users make no consent request, see
no new menu item, and continue through the existing product path.

## Recurring aggregate monitor

Railway must run one dedicated cron service from this repository:

```text
Builder:       Railpack
Start command: sh bin/railway-mlc2-confidence-readiness-cron.sh
Schedule:      */5 * * * *
```

Required service variables:

- `DATABASE_URL`
- `SENTRY_DSN`
- `DATA_FOUNDATION_CANARY_ENABLED=true`
- `MLC2_CONFIDENCE_CANARY_PRINCIPAL_ID=<verified founder principal UUID>`
- `MLC2_CONFIDENCE_MONITORING_ENABLED=true`

The job is read-only and sends only aggregate readiness/blocker evidence to
Sentry. Every unsafe invariant exits non-zero. The cutover mode is not an
environment variable and remains hard-coded `dark`.

## Controlled deployment order

1. Merge and deploy backend source; allow migrations `0306–0307` to apply.
2. Run `scripts/configure_mlc2_consent_policy.py` once in the backend service.
   Verify the R2 read-back checksum and policy result.
3. Deploy frontend source and verify ordinary accounts are unchanged.
4. The founder personally reviews and clicks **Agree and continue**. No
   operator, migration or script may perform this action for them.
5. Resolve the exact acquisition-principal UUID created by that authenticated
   flow and configure it on backend/worker/monitor services.
6. Deploy the recurring monitor, set monitoring enabled, and verify its Sentry
   alert path.
7. Run the production readiness check and preserve the JSON report.

At every step, `MLC2_CONFIDENCE_CUTOVER_MODE` remains `dark`, canonical
Confidence producer receipts remain zero, and datasets/training/promotion
remain disabled.

## Verification evidence

- Complete backend local CI: migration manifest, migration runner, Ruff, Mypy
  and unit tier green (`4904 passed`, `9 skipped`, `127 subtests passed`).
- Frontend test suite, TypeScript check and production build green on Node 22.
- Disposable PostgreSQL rehearsal installed `pgcrypto` in the Supabase
  `extensions` schema, applied migrations `0302–0307`, reapplied `0307`,
  rejected an invalid copy hash, proved byte-identical policy
  idempotency, verified exact-principal pre-grant/grant/withdrawal status,
  verified purge creation and denied browser-role RPC execution. All fixtures
  rolled back.

> SLICE 6A READY FOR AUTHORIZED DARK DEPLOYMENT — no founder consent,
> producer activation, legacy cutover, dataset, training or promotion action
> has occurred.
