# MLC-2 Slice 6 — Founder-only Confidence canary readiness

Owner: Artur Willoński

Engineering design: `ED-2.4`

Learning contract: `MLC-2`, `data_epoch=1`

Status: `EVIDENCE PREPARED LOCALLY — CANARY DISABLED`

## Authorization boundary

Authorized: prepare and verify founder-only Confidence canary readiness
evidence.

Not authorized and not performed: runtime activation, legacy cutover, dataset
creation, training, model promotion, merge, push or deployment.

This slice does not claim that production is ready. It creates the controls and
read-only proof needed for ML/data and Engineering to make that decision after
deployment is separately authorized.

## Atomic cutover contract

The former Boolean could not distinguish a pre-cutover dark state from an
incident kill after cutover. One reviewed mode now chooses both writer
boundaries:

| Mode | Canonical Confidence writes | Prior learning write | Meaning |
| --- | --- | --- | --- |
| `dark` | off | on | Current pre-cutover product behavior |
| `founder_canary` | on | off | Future separately authorized founder lane |
| `killed` | off | off | Incident stop; legacy learning cannot resume |
| invalid | off | off | Malformed configuration fails fully closed |

The mode remains hard-coded `dark`. It is not an environment toggle. A future
activation or kill requires an explicit reviewed code change and deployment.
Rollback from `founder_canary` is always to `killed`, never to `dark`.

## Founder scope

Canonical Attempt registration requires all of the following:

- authenticated user;
- token email exactly `artur@willonski.com`;
- configured administrator email exactly `artur@willonski.com`;
- approved canary email exactly `artur@willonski.com`;
- exact configured `acquisition_principal_id` matching the Project owner.

Email is not sufficient provenance. A missing or mismatched principal fails
closed into the ordinary product path. Guests and other users cannot register
a canonical canary Attempt.

## Six readiness gates

### 1. Product/legal consent configuration

The service-role-only readiness RPC requires exactly one active bundled policy
linked to an immutable Product/legal approval with Article 6(1)(a), the
approved Article 9 treatment, approval reference, approved-copy checksum and
evidence-object checksum. The founder principal must have a current grant for
both `personalized_coaching` and `pooled_model_improvement`.

Local proof: PostgreSQL rehearsal passes with a transaction-scoped legal
approval, policy and founder grant. Production proof is still required; this
slice does not seed or change production consent.

### 2. Founder-only enforcement

Route tests prove that only the exact authenticated founder email and exact
Project acquisition principal qualify. Missing principal configuration,
administrator-email drift, guest use, ordinary accounts and a disabled
foundation scope all fail closed.

Production proof still requires the exact founder principal to be configured
and the aggregate monitor to report no non-founder receipt or canonical event.

### 3. Monitoring and alerts

`get_mlc2_confidence_canary_readiness_v1` returns aggregate counts only. It is
`STABLE`, `SECURITY DEFINER`, and executable only by `service_role`. It exposes
no audio, transcript, blind packet or human answer.

The read-only operator command is:

```sh
python scripts/check_mlc2_confidence_canary_readiness.py --json --alert
```

It fails closed and exits non-zero for missing consent, scope drift,
non-founder activity, outbox failures, lineage gaps, blindness violations or
enabled downstream capabilities. When Sentry is configured, `--alert` sends
only the aggregate report and blocker codes.

Required future operating cadence:

- run once immediately before any activation proposal;
- run at least every minute during a founder canary;
- alert on every non-zero exit and every non-zero invariant;
- keep the operator check independent of product request handling;
- stop the canary before investigating content-level evidence.

The monitor and schedule are not deployed by this slice. Monitoring remains
configured off locally and is therefore a deliberate readiness blocker.

### 4. Rollback and kill switch

Unit tests prove `founder_canary -> killed` disables canonical and prior
learning writes together. Invalid modes behave like `killed`. No migration
rollback or data deletion is part of incident response; queued canonical
outbox work remains durable for explicit later handling.

The production kill procedure requires a separately reviewed change of the
hard-coded mode to `killed`, deployment, and verification that both writer
decisions are false. Returning to `dark` after activation is prohibited.

### 5. Atomic prevention of legacy learning writes

The same cutover decision controls both writers. `founder_canary` cannot run
the prior learning exposure write; `killed` cannot run either. Focused tests
prove the canonical Take/outbox promotion remains one transaction and the
prior writer cannot be resurrected by rollback.

This does not delete or migrate product-state tables. It only controls the
specific legacy learning/provenance append identified in the approved
Confidence dependency audit.

### 6. No impact on normal user feedback

Exact-three feedback selection and product rendering happen before the prior
learning-writer condition. The condition surrounds only the provenance append.
Non-founder recordings do not claim the canonical Attempt contract and retain
the normal recording, processing and feedback path. Route and dispatch tests
cover authenticated non-founders and guests.

## Aggregate readiness invariants

Activation review must see all of these at zero:

- non-founder producer receipts;
- non-founder canonical Confidence events;
- pending and failed Confidence outbox events;
- producer receipts without their outbox event;
- processed producer events without a finalized candidate frame;
- blind assignments without an answer-free packet;
- revealed blind assignments without an immutable judgment.

While the mode is `dark`, founder producer receipts must also remain zero. Any
receipt is evidence of unauthorized runtime activation.

Dataset creation, training and promotion must be reported false in both code
and database evidence.

## Verification evidence

Focused repository checks on 2026-08-27:

- founder scope, atomic cutover, legacy isolation, migration, monitor and
  rehearsal contracts: 55 passed;
- Ruff on all changed Python: passed;
- changed-file whitespace validation: passed.

Disposable PostgreSQL 16.15 rehearsal on 2026-08-27:

- loaded production-coordinate prerequisites and the existing `0297` Take
  lifecycle;
- applied migrations `0302`, `0303`, `0304` and `0305`;
- reapplied `0305` successfully;
- recorded a transaction-scoped bundled founder consent grant;
- verified the aggregate readiness contract and disabled downstream flags;
- verified `anon` and `authenticated` cannot execute the readiness RPC;
- rolled back every fixture and stopped the temporary cluster.

Full repository gate on Python 3.12 with the repository-pinned tools:

- migration manifest: 305 ordered migrations (`0001` through `0305`), pass;
- migration runner: 66 passed;
- Ruff `0.15.8`: pass;
- Mypy `2.3.0`: pass across 325 source files;
- unit tier: 4,887 passed, 9 skipped, 127 subtests passed;
- live/model evals: not applicable to a dark, aggregate-only readiness slice;
  not run.

## Current activation blockers

The founder canary is **not ready to activate** until a separately authorized
deployment and production verification prove:

1. the authoritative Product/legal policy and founder grant are live;
2. the exact founder acquisition principal is configured;
3. migration `0305` and the aggregate monitor are deployed;
4. monitoring is scheduled and its Sentry alert path is verified;
5. a production read returns every invariant at zero;
6. ML/data and Engineering accept this Slice 6 evidence;
7. the user separately authorizes runtime activation and legacy cutover.

> CONFIDENCE CANARY READINESS EVIDENCE PREPARED — Slice 6 awaits ML/data and
> Engineering review. The canary remains disabled.
