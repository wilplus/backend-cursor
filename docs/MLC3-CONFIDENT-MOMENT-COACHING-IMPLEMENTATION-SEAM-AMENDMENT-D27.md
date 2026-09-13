# MLC-3 Confident Moment Coaching Bundle — Implementation Seam Amendment D27

Status: proposed narrow canonical-read and durable-delivery-dispatch closure;
executable work remains blocked pending independent Product, ML/data and
Engineering acceptance.

## 1. Bound parents and scope

D27 binds:

```text
MLC3-CONFIDENT-MOMENT-COACHING-TRANSPORT-CLOSURE-AMENDMENT-D25.md
SHA-256 81dfec670fb56584ee5f431a828e5de2aa8d55be29b7e18c43c6c5018aa0c2b0

MLC3-CONFIDENT-MOMENT-COACHING-COACH-CONTEXT-PRINCIPAL-AMENDMENT-D26.md
SHA-256 88328fbb48c0f3d1a799c8c95c0fb279b83fa3fefe6f376d046cf1c1101af6b7
```

D27 adds only two missing application seams:

1. one database-owned Ideal Text core GET projection containing the D22 owner
   edit overlay; and
2. loss-tolerant post-commit dispatch for D14's already-durable coach delivery
   materialization job.

D3/D11–D25 and D26 remain authoritative. D27 does not change Manager
membership, Feedback Language meaning, coach authority, public coach publish
response, exposure, rooting, datasets, learning surfaces or any gate default.

## 2. Canonical Ideal Text core read v2

### 2.1 Exact SQL identity and actor type

Add:

```text
read_ideal_text_document_core_v2(
  p_arc_id text,
  p_actor_id text
) -> jsonb
```

The SQL boundary deliberately retains the released actor type `TEXT`; the
released v1 is `read_ideal_text_document_core_v1(TEXT,TEXT)`. PostgreSQL derives
the authoritative owner/acquisition principal from current Project lineage and
parses/compares actor UUID identity only where that lineage requires it. An
invalid, foreign or ambiguous actor fails closed; browser text never becomes a
principal assertion.

The function is fixed-search-path `SECURITY DEFINER`, executable only by
`service_role`. `PUBLIC`, `anon` and `authenticated` have no execute privilege.
The v1 function retains its historical callers but is not a Bundle owner-edit
read path and must not be called by the current Ideal Text core application
method after this amendment.

### 2.2 Exact database envelope

The original immutable snapshot payload must remain byte-for-byte unchanged,
and `payload_sha256` continues to hash only those original immutable payload
bytes. Dynamic owner state is not inserted into that stored/hash-covered
payload. The exact recursively closed RPC result is:

```json
{
  "ideal_text_core_read_contract_version": "ideal-text-document-core-v2",
  "snapshot": {
    "id": "uuid",
    "arc_id": "arc-id",
    "actor_id": "uuid-as-text",
    "project_id": "uuid",
    "acquisition_principal_id": "uuid",
    "source_generation": 4,
    "payload": {},
    "payload_sha256": "64-lowercase-hex",
    "created_at": "canonical-timestamptz"
  },
  "dynamic_overlay": {
    "owner_edit": {
      "text": "current complete owner text",
      "source_document_version": 4,
      "user_text_revision": "8",
      "user_text_sha256": "64-lowercase-hex",
      "parts": [
        {
          "id": "uuid",
          "ord": 0,
          "text": "exact text",
          "locked": false,
          "current_part_revision_id": null
        }
      ],
      "current_bundle_text_update_binding": null
    },
    "confident_moment_summary": null,
    "confident_moment_summary_status": {
      "state": "disabled|unavailable|available",
      "code": null,
      "retryable": false
    }
  },
  "read_sha256": "64-lowercase-hex"
}
```

The `snapshot` key is the exact released v1 snapshot row with the exact
canonical v1 column set; the illustrative object above must be replaced at
implementation freeze by the mechanically extracted released column registry,
not by `to_jsonb(*)` drift. Unknown or extra keys fail the repository parser.

`owner_edit` is exactly the recursively closed D22/D24 string-or-null schema.
Its valid-empty object retains every required key with null/empty values.
`confident_moment_summary` is either the exact D11 stable summary from the same
serialized read or null. Null means only “not supplied because the database
contract is disabled/unavailable” as typed by the adjacent status; it is never
a no-match or learning fact. When available, the summary and owner edit are
derived from the same stabilized identity inventory.

`read_sha256` hashes the exact snapshot identity/hash plus the complete dynamic
overlay. It does not replace or reinterpret `payload_sha256`.

### 2.3 Lock and derivation boundary

The function acquires the complete D11 and D25 locks applicable to rollout,
principal, Project, current document/head/snapshot, owner notes, complete part
inventory/revision heads, current Bundle edit binding and D11 Bundle summary.
It uses D25's non-interleaved complete 100-A→100-B→100-C sets, rederives and
hashes the identity inventory, then builds both dynamic objects. A changed
inventory returns only `CONFIDENT_MOMENT_PROJECTION_RETRY_REQUIRED`; it never
returns a mixed snapshot/owner overlay.

It validates exact owner authority, source document version, notes CAS/hash,
part join/order/locks/revision heads, Bundle binding and deletion/currentness
after contention and immediately before return. A broken owner triple or
binding is typed projection invalidity, not omission. Exact replay repeats the
full lock/currentness boundary.

### 2.4 Application and HTTP seam

The exact production caller becomes:

```text
services/db.py::DatabaseService.get_ideal_text_document_core
  -> read_ideal_text_document_core_v2
```

It makes one RPC call and parses the closed envelope. The core route performs
no supplemental read of `user_arc_ideal_notes`, `ideal_text_part`, revision
heads, Bundle bindings or the Bundle projection. It unwraps `snapshot.payload`
for the existing HTTP surface and adds only:

```text
payload.owner_edit = dynamic_overlay.owner_edit
payload.confident_moment_summary = dynamic_overlay.confident_moment_summary
payload.confident_moment_summary_status =
  dynamic_overlay.confident_moment_summary_status
```

This merge exists only in the HTTP representation. It does not mutate the
stored immutable snapshot, and clients may not claim that the dynamic fields
are covered by `document_snapshot_sha256`; `read_sha256` covers the combined
read. Existing document snapshot ID/hash fields continue to identify only the
immutable snapshot.

`read_ideal_text_document_core_v1(TEXT,TEXT)` is registered as a forbidden
Bundle owner-edit caller. Static tests fail if the current database method or
route performs a v1 call or supplemental direct read.

## 3. Durable coach-delivery dispatch

### 3.1 Publish transaction and trusted raw result

D14 already requires
`publish_confident_moment_coach_feedback_language_v1` to atomically create a
durable `feedback_language_delivery_materialization_jobs` row when no target
delivery exists. That invariant is retained and made operational:

- the revision and job commit or roll back together;
- a direct target delivery creates no materialization job;
- exact publish replay returns the same job identity; and
- job identity is opaque UUID routing state with no comment/rephrase text,
  transcript, audio, media URL or other raw content.

The SQL function's **trusted internal** result may add exactly:

```json
"_materialization_job_id": "uuid-or-null"
```

It is non-null only when this exact publish owns a durable pending job. The
leading-underscore field is registered internal transport and is forbidden on
the public wire.

`ConfidentMomentBundleRepository.publish_coach_feedback_language` validates the
complete raw result, removes the internal key, validates the remaining object
against D14's exact public schema, and returns an internal typed pair:

```text
PublishCoachFeedbackLanguageResult(
  public_payload=<exact D14 response>,
  materialization_job_id=<uuid|null>
)
```

The route may pass only `public_payload` to `jsonify`. Its closed response
denylist rejects `_materialization_job_id`, `job_id`, raw revision text and all
internal dispatch keys. D14's public HTTP status/body remain exact and
unchanged.

### 3.2 Immediate post-commit wake-up

The PostgREST RPC transaction has committed before the repository returns.
Only then, when the internal job ID is non-null, the application calls:

```text
services.confident_moment_delivery_worker.enqueue_confident_moment_delivery
```

The existing deterministic RQ identity remains:

```text
confident-moment-delivery-<job_uuid>
```

Enqueue is best-effort wake-up only. Enqueue failure cannot change or roll back
the successful coach publish response and cannot delete/close the durable job.
The due-job sweep below is the mandatory recovery path.

### 3.3 Due-job scanner RPC

Add:

```text
claim_due_feedback_language_delivery_jobs_v1(
  p_worker_id text,
  p_limit integer,
  p_lease_seconds integer
) -> jsonb
```

It is fixed-search-path `SECURITY DEFINER`, service-role-only, and registered in
the exhaustive signature/overload/grant/caller/lock inventories. Under D11
locks it claims at most `LEAST(GREATEST(p_limit,1),100)` exact pending or
expired-lease jobs. Lease seconds are bounded to 15–300. It uses deterministic
oldest-due-time then UUID order and an atomic skip-locked/lease transition so
concurrent sweepers cannot own the same active lease.

Its recursively closed response contains only:

```json
{
  "delivery_job_claim_contract_version": "feedback-language-delivery-claim-v1",
  "jobs": [
    {"job_id": "uuid"}
  ],
  "has_more": false,
  "dataset_eligible": false
}
```

No principal, Take, candidate, wording, transcript, audio or media field may be
returned. The database derives attempts/due/lease state but keeps it internal.
Expired enqueue leases are retryable up to the frozen D14 bounded attempt/age
policy; exhaustion becomes an aggregate-alertable typed terminal lifecycle
event, never a fabricated delivery.

The exact scanner caller is:

```text
services/confident_moment_delivery_worker.py::sweep_due_confident_moment_deliveries
  -> claim_due_feedback_language_delivery_jobs_v1
```

### 3.4 Worker sweep seam

Add:

```text
services.confident_moment_delivery_worker.sweep_due_confident_moment_deliveries(
  *, worker_id: str, limit: int = 25, lease_seconds: int = 60
) -> dict[str, int]
```

It validates the closed scanner response and enqueues each opaque job ID
through `enqueue_confident_moment_delivery`. A failed enqueue leaves the lease
to expire and be reclaimed. A successful enqueue uses the exact deterministic
RQ ID, so duplicate immediate/sweep wake-ups converge.

The scheduled production path is exactly:

```text
bin/railway-worker.sh
  -> worker.py::main
  -> services.pipeline_jobs.run_sweep_loop
  -> services.confident_moment_delivery_worker.
       sweep_due_confident_moment_deliveries
```

The existing single leased queue sweep chain invokes this bounded sweep once
per configured pipeline sweep interval; it does not create a thread, second
unleased loop or new Railway process. Worker boot also performs one bounded
sweep after Redis/DB readiness and before RQ blocking. Both paths are inert
unless the exact Confident Moment Bundle gate and database rollout contract are
enabled. Scanner or enqueue failure is logged/aggregated and does not stop the
general worker sweep chain.

The materializer remains exactly:

```text
services/confident_moment_delivery_worker.py::
  materialize_confident_moment_delivery
  -> materialize_feedback_language_delivery_job_v1(uuid,text)
```

It accepts only an opaque job UUID and deterministic operation key
`materialize:<job_uuid>`, revalidates current revision/delivery/authority under
D11 locks, creates at most one delivery, and records one immutable completed or
closed-stale lifecycle. Duplicate RQ execution, lease expiry and scanner replay
are idempotent. No raw content is placed in Redis/RQ job arguments, logs,
metrics, Sentry tags or scanner results.

## 4. Exact registry additions

Freeze:

```text
read RPC:
read_ideal_text_document_core_v2(text,text)

read caller:
services/db.py::DatabaseService.get_ideal_text_document_core
  -> read_ideal_text_document_core_v2

publish caller:
services/confident_moment_bundle_repository.py::
  ConfidentMomentBundleRepository.publish_coach_feedback_language
  -> publish_confident_moment_coach_feedback_language_v1

scanner RPC:
claim_due_feedback_language_delivery_jobs_v1(text,integer,integer)

scanner caller:
services/confident_moment_delivery_worker.py::
  sweep_due_confident_moment_deliveries
  -> claim_due_feedback_language_delivery_jobs_v1

materializer caller:
services/confident_moment_delivery_worker.py::
  materialize_confident_moment_delivery
  -> materialize_feedback_language_delivery_job_v1
```

Also freeze the `pipeline_jobs.run_sweep_loop` call edge to the bounded sweep
and `worker.py::main` boot-sweep call. The application AST test rejects v1 core
read use by the current method, supplemental owner/part/Bundle core-route
reads, missing/extra scanner/materializer callers, and any public serialization
of the internal publish job key.

## 5. Required executable regressions

Implementation review must add, while retaining every D20–D26 regression:

1. v2 core read returns the exact immutable v1 snapshot unchanged plus the
   exact current D22/D24 owner overlay under one transaction;
2. valid-empty owner state contains every null/empty key; bigint revisions are
   strings; legacy null part heads remain distinguishable from failed reads;
3. a concurrent ordinary/Bundle edit, root/part change, document successor or
   deletion in both commit orders returns one fully old or fully new valid
   result/typed retry—never a mixed overlay;
4. `payload_sha256` still verifies the original immutable payload and
   `read_sha256` changes with a dynamic owner update;
5. wrong actor text, foreign owner, stale Bundle binding and partial owner
   triple fail closed;
6. core route makes exactly one database call, performs no supplemental notes,
   parts, revision, principal or Bundle projection read, and emits the exact
   merged HTTP schema without claiming dynamic fields are snapshot-hashed;
7. application v1 read and unknown/extra RPC envelope fields fail static/runtime
   closure;
8. coach publish with no target Take atomically commits exactly one revision
   and one durable pending job; direct-delivery branch creates no job;
9. repository extracts one internal job UUID, route response remains byte-for-
   byte D14-compatible, and internal/raw-content keys are denied publicly;
10. immediate enqueue runs only after successful RPC return/commit; rollback
    enqueues nothing; enqueue failure still returns publish success and leaves
    the exact pending job;
11. scanner returns only bounded opaque IDs in due-time/UUID order; concurrent
    scanners cannot claim one live lease; invalid bounds/worker ID fail closed;
12. lease expiry after enqueue failure permits a later scan; deterministic RQ
    ID collapses immediate/sweep duplicate wake-ups;
13. boot and recurring worker seams each invoke the bounded scanner under the
    enabled gate, remain inert under disabled gates, and scanner failure does
    not kill the sweep chain;
14. duplicate materializers, scanner replay and worker restart create exactly
    one delivery/completed event; stale revision closes without delivery;
15. job/scanner/RQ/log/metric/Sentry payloads contain no wording, transcript,
    audio, media or principal content; and
16. publish, scan and materialize revalidate authority/deletion/currentness and
    create no exposure, response, confidence, adequacy, dataset, training or
    learning-surface record.

## 6. Gates and stop conditions

All new SQL executes service-role-only; internal result/job/lease state is not
browser authority. Existing forced-RLS/RPC-only job/lifecycle constraints and
D11/D25 locks remain mandatory.

All Bundle, rooting, PAM, serving, collection, dataset, training, evaluation
and promotion gates retain literal disabled defaults. Jobs and lifecycle events
remain `serves_user=false` and `dataset_eligible=false`.

Stop and request review if implementation would:

- supplement the canonical core route from notes/parts/Bundle table reads;
- mutate the immutable snapshot payload or claim owner state is covered by its
  historical `payload_sha256`;
- change the public D14 coach publish body or expose a job/internal/raw-content
  field;
- enqueue before the publish transaction commits or treat Redis/RQ as the
  durable job source;
- omit the due-job scanner, use an unbounded scan, create an unleased recurring
  loop, or pass anything but an opaque job ID to RQ;
- make enqueue failure reverse a successful coach revision;
- let duplicate/restarted workers create multiple deliveries;
- weaken D11/D25 locks, exact authority/deletion/currentness, blindness, RLS,
  non-serving or non-learning boundaries;
- change a disabled gate; or
- number, commit, push, merge, deploy, activate or collect without separate
  authorization.

`VERDICT: D27 PROPOSED FOR PRODUCT, ML/DATA AND ENGINEERING REVIEW; EXECUTABLE WORK BLOCKED`
