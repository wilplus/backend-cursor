# Phase-1 processing authorization runbook

Status: implemented and rehearsed locally; production activation is blocked.

This runbook covers only the required recording/coaching service boundary. It
does not authorize pooled datasets, training, evaluation, promotion,
personalized exercise recommendation, or exercise-adequacy classification.

## Deployment invariant

`PLF1_PROCESSING_AUTHORIZATION_MODE` has two supported values:

- `off` (default): new schema may exist, but no policy is required and the
  established product path remains active.
- `enforce`: every core-service request, recording intake, manual retry and
  provider operation requires current canonical authority.

There is no permissive fallback in `enforce`. Set the same value on web,
worker, and every job/cron service. Verify the value from each service's boot
log. Never activate it before the approved policy below is registered and the
staging rehearsal passes.

## Migration order

1. Apply every migration already in `migrations/manifest.txt` through 0309.
2. Apply `0310 migrations/add_phase1_processing_boundary.sql`.
3. Reapply 0310 in staging to prove idempotency.
4. Keep `migrations/pending/cleanup_retired_sex_data.sql` out of the manifest.
   It is a destructive, separately authorized cleanup requiring a row-count
   preview, retention approval and recovery plan.

Migration 0310 seeds only purpose-registry identifiers. It creates no legal
artifact, policy version, acceptance receipt or processing authority.

## Policy registration and activation

Do not invent legal copy in code or an operator command. Product/legal must
supply the exact approved Terms, Privacy and AI-notice text, versions, object
references, SHA-256 hashes, allowed countries, 18+ wording, authority,
approval reference and approval date.

Register through `register_phase1_policy_v1`. The RPC rejects copy/hash
mismatches, artifact-version conflicts, purpose drift and non-operational
required purposes. Replay must return the same policy without a second admin
event. Activate through `activate_phase1_policy_v1` only after staging review;
activation atomically freezes the cutoff and creates exact-job carryovers for
accepted non-terminal work.

No operator may create an acceptance receipt for a user. Acceptance is a
server-validated `agree_and_continue` action from the durable acquisition
principal. Guest-to-account claim preserves that principal rather than copying
receipts.

## Required staging verification

Run:

```text
psql ... -f tests/integration/phase1_processing_prerequisites.sql
psql ... -f migrations/add_phase1_processing_boundary.sql
psql ... -f migrations/add_phase1_processing_boundary.sql
psql ... -f tests/integration/phase1_processing_rehearsal.sql
```

Verify:

- passive status creates no receipt;
- one explicit action creates one receipt and replay is idempotent;
- pooled-learning eligibility is always false;
- one accepted upload creates exactly one attempt, exact-byte audio object,
  snapshot, job and outbox event;
- provider permits are narrow and append terminal operation events;
- rendered AI exposure requires authenticated client confirmation;
- termination blocks new recording, retry and provider work;
- immutable evidence rejects updates/deletes;
- browser/authenticated roles have no table or RPC bypass;
- orphan uploads are claimed and deleted only by exact provider/bucket/key/hash;
- Phase-2 routes return the centralized disabled response.

## Monitoring and rollback

Alert on failed intake finalization, unresolved principals, provider-permit
denials, stale outbox rows, orphan-cleanup failures, policy/hash mismatch,
carryover expiry and purge requests in `review_required`.

Rollback means set all services to `off` and redeploy the previous application
revision. Do not drop tables, delete receipts, reactivate legacy learning
writes, or run the pending cleanup migration. Queued product jobs remain
observable and retryable under the reviewed recovery decision.

## Deletion limitation

The current orchestrator records the request and inventories canonical SQL and
exact storage targets. It deliberately stops at `review_required` when it
encounters mixed-purpose product tables, unknown retention, coach-delivery
copies, provider artifacts, caches, dataset lineage or trained-model lineage.
This fail-closed state is not completed erasure. Production activation remains
blocked until every target has an approved resolver, retention rule,
idempotent executor, reconciliation monitor and end-to-end staging proof.

## Deletions that complete by themselves (0422, N48.4 Q14 A, Q17 A)

An account deletion (`POST /v2/processing-authorization/terminate`,
`account_deletion`) and a project deletion (`POST
/v2/projects/<id>/deletion-request`) wait seven days. The account is blocked
at once (the status function counts the pending request); the requester may
cancel until `completes_after`; nothing is deleted before it. Then the
completion run starts the purge, runs the orchestrator and marks the request
done on verified evidence. A purge that meets rows no rule decides stops at
`review_required`, deletes nothing past the refusal, and waits for a person:
`GET /v2/admin/deletions` lists it with the targets that stopped it.

Setup (CONFIG-FIRST: the web service first):

1. Web service: `DELETION_COMPLETION_SECRET` (without it the route answers
   503). Leave `PHASE1_PURGE_EXECUTION_ENABLED` unset at first: every run is
   then a dry run that reports what is due and writes nothing.
2. A Railway cron service from this repo: Start Command
   `sh bin/railway-deletion-completion-cron.sh`, schedule `37 * * * *`,
   variables `DELETION_COMPLETION_BACKEND_URL` and `DELETION_COMPLETION_SECRET`.
3. Read a dry run's report (the cron log, or `python
   scripts/run_due_deletions.py` in a shell). When it lists only what should
   go, set `PHASE1_PURGE_EXECUTION_ENABLED=true` on the web service.

Known limit (found by the 0422 rehearsal, not changed by it): the purge
deletes `phase1_processing_jobs`, `phase1_processing_outbox`,
`processing_job_carryovers` and `processing_orphan_objects` rows directly as
service_role, and 0310 revoked DELETE on them. A person with processing jobs
is stopped earlier, at the jobs' events (external_review, N14.3), before
anything is deleted; once a rule decides those events, or for a person with
an orphan-object row and no job, those deletes fail with
InsufficientPrivilege mid-run and the request waits for a person. They need
an executor (a scoped function, or a grant) before that.

## Production gates

Required before activation: Product/legal approval of exact artifacts and
`power_score` classification; DPIA/RoPA and processor/transfer review;
retention schedule; data-rights and breach procedures; complete cross-provider
deletion rehearsal; ML/data, Engineering, security and founder acceptance;
staging evidence; and explicit production deployment authorization.

Even after those reviews, do not describe the application as “fully
compliant.” Report the controls and evidence that were actually verified.
