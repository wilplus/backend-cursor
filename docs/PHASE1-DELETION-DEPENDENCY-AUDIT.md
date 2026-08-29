# Phase-1 deletion dependency audit

Status: implementation evidence only. No production purge, deployment, policy
activation, dataset, training, or model promotion is authorized by this file.

## Authoritative allowlist

`services/data_purge_registry.py` is the checked-in, versioned allowlist. Each
entry fixes a stable dependency code, physical relation, selector, subject
coordinate, disposition, target kind, delete order, and (where applicable)
retention category. At this revision it classifies:

- 170 attributable dependency paths: 64 deletable, 16 retain-only, and 90
  explicit-review paths.
- 49 global/admin/configuration relations that do not belong to the subject.
- 2 reviewed foreign-key cascade relations.
- 25 runtime-selected physical names, including both sides of the snippets
  rename, profile aliases, token/cost ledgers, and the Life Panel tables.

`tests/test_phase1_deletion_completion.py` parses every literal
`client.table(...)` call under `routes/`, `services/`, and `scripts/`. A new
literal relation fails the build until it is classified. Dynamic names are
bound separately through `DYNAMIC_RUNTIME_RELATIONS`; unknown database catalog
relations fail closed through `audit_phase1_purge_catalog_v1`. The test also
parses every migration for newly declared subject-coordinate tables, so an
append-only or historical relation cannot escape merely because current code
accesses it through a generic repository.

## Producer/reader ownership map

| Area | Principal runtime owners | Purge treatment |
| --- | --- | --- |
| Acquisition, processing jobs and provider permits | `routes/v2/lab_recording.py`, `services/analysis_worker.py`, `services/processing_authorization.py` | Cancel/delete queues; retain minimal authorization and processor evidence only under an active rule. |
| Projects, Takes, recordings and snippets | `routes/v2/projects.py`, `routes/v2/user_sessions.py`, `services/db.py`, `services/snippet_tables.py` | Delete exact owner/project/Take graph. The old multi-producer `charisma_snippets` table requires explicit review because a broad delete could remove another producer's rows. |
| Ideal Text, feedback and coach packets | `routes/v2/explore_ideal_text.py`, `routes/v2/coach.py`, `services/take_feedback_manager.py`, `services/db.py` | Delete user content and derived feedback in child-before-parent order. |
| Exact audio bytes | `services/lab_audio_storage.py`, `services/orphan_audio_cleanup.py` | Verify provider/bucket/key and SHA-256 immediately before delete; verify absence; preserve minimal deletion evidence. Shared or legacy-unhashed objects block. |
| OpenAI/provider operations | `services/openai_service.py`, `services/processing_authorization.py` | Resolve only through an immutable Product/legal-reviewed provider contract. Missing or ambiguous contracts block. |
| Billing/cost evidence | `services/token_account.py`, `services/llm_usage.py` | Retain only under an active `financial_evidence` rule; otherwise block. |
| Life Panel | `services/life_store.py`, `services/life_import.py`, `services/life_reminders.py`, `services/life_engine.py` | Its existing hard-delete path must be transactionally integrated before Phase-1 can claim completion; matching rows currently block. |
| Dark MLC-2/V3 lineage | MLC services and shadow-frame writer | Route to the separately reviewed exceptional-purge traversal; never delete or relabel implicitly. |
| CEO/admin/global configuration | CEO/admin services and global content pools | Classified as non-subject; never deleted merely because a subject purge runs. |

The full table-by-table mapping is the typed registry itself; this summary does
not override it.

## Fail-closed invariants

1. Freeze the resolved principal/account/project/Take/recording/snippet graph
   and every target before the first destructive call.
2. PostgreSQL hashes the exact JSONB graph and target array it stores.
3. Any unknown relation, unresolved retention rule, mixed-purpose relation,
   legacy object without exact byte lineage, shared object, or missing provider
   contract prevents all deletion.
   A legacy Take linked only by account, without a matching canonical owner
   principal, is included in the frozen graph and blocks with
   `LEGACY_TAKE_OWNER_PRINCIPAL_UNRESOLVED`; it is never silently omitted.
4. A target cannot be recorded as deleted/not-found while its verified
   remaining count is non-zero.
5. Provider contracts and their activation/retirement facts are immutable and
   writable only through validating RPCs.
6. R2/Supabase deletion hashes bytes immediately before deletion and verifies
   absence afterward. A previously verified deletion is not sent twice.
7. Completion evidence binds resolver version, frozen inventory hash, catalog
   hash, target states, and remaining counts.
8. Operator execution is off unless `PHASE1_PURGE_EXECUTION_ENABLED=true` and
   the exact purge request ID is repeated as confirmation.
9. Immediately before any destructive call, the worker rechecks the frozen
   resolver version, code-owned dependency-manifest hash and live catalog hash.
   A schema or resolver change after freeze requires a new reviewed request.

## Rehearsal evidence

The disposable PostgreSQL rehearsal applies migrations 0310 and 0312, then
proves catalog detection, unknown-target blocking, exact replay, replay
conflict, duplicate-target rejection, remaining-count enforcement, immutable
evidence, RPC-only provider contracts, and finalization. It ends with
`ROLLBACK`.

Python adapter tests use synthetic bytes and fake providers to prove hash-before-
delete, verified absence, missing-contract failure, unknown-inventory preflight,
and the operator kill switch. No external provider or production database is
contacted.

Local evidence recorded on 2026-08-29:

- Migration 0312 applied, reapplied, and passed its transaction-scoped
  PostgreSQL rehearsal in the disposable `plf1_deletion_rehearsal` database.
- The rehearsal proved an exact canonical audio deletion marker is idempotent,
  cannot rewrite the append-only acquisition row, and rejects mismatched object
  coordinates.
- Migration 0311 applied, reapplied, and passed the separate universal-v3
  detector transition rehearsal in `detector_transition_rehearsal`.
- `scripts/local_ci.sh --no-setup` passed migration verification, migration
  runner tests, Ruff, Mypy, and 4,828 unit-tier tests (105 skipped by the
  checked-in CI quarantine/evaluation policy).
- All SQL rehearsals ended in `ROLLBACK`; no production database, provider
  object, or user data was read, changed, or deleted.

## Explicit remaining integrations

- The old multi-producer snippets table needs an exact producer ownership
  predicate before its rows may be automatically deleted.
- The Life Panel's existing hard-delete must be connected transactionally.
- MLC-2/MLC-3 release/model invalidation remains a separate exceptional purge.
- Product/legal must register exact retention and provider contracts; this
  implementation deliberately seeds none.
- Production scheduling/activation and any real purge require separate
  authorization.
