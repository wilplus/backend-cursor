# MLC-3 Confident Moment Coaching Bundle — Transport Closure Amendment D20

Status: proposed interface amendment; executable work remains blocked pending
independent Product, ML/data and Engineering acceptance.

## 1. Parent and narrow supersession

D20 binds and narrowly supersedes:

```text
MLC3-CONFIDENT-MOMENT-COACHING-TRANSPORT-CLOSURE-AMENDMENT-D19.md
SHA-256 31ae544c5f80de33102f2f1ec114673d90f1f40ee1492784af4ddb99de7f35d8
```

D19 and its accepted D3/D11–D18 parents remain authoritative except where D20
explicitly replaces:

1. D19's assumption that `user_arc_ideal_notes.user_text` already exists;
2. the transient-only treatment of audio-less coach authorability;
3. the locator producer timing, identity and replay contract;
4. the Bundle owner-edit concurrency-token rule; and
5. the closed Feedback Language item schema's Update-text availability.

D20 preserves D11's complete numeric lock graph, all blindness and provenance
fences, the Manager budget, legacy non-Bundle behavior, non-serving/non-learning
semantics, and every disabled gate.

## 2. Database-derived first-owner bootstrap

### 2.1 Bootstrap is not a browser choice

`apply_confident_moment_bundle_text_update_v1` alone decides whether the exact
owner edit row requires bootstrap. The browser sends no bootstrap boolean,
initial document text, owner row state, user-text version, legacy notebook text,
target part, replacement text or storage-mode value.

After acquiring the applicable D11 10→20→30→40→50→51→52→53 serializers, the
wrapper derives and locks:

- the exact owner, Project, arc and source Take;
- the exact current immutable Feedback V3 snapshot and payload;
- the complete current ordered `ideal_text_part` inventory for `(arc,user)`;
- the exact `user_arc_ideal_notes` row, when present; and
- the Bundle, attachment, decision, locator, exposure and render identities.

The exact locked snapshot Ideal Text payload must equal the current ordered part
join using D19's exact non-empty-part `\n\n` rule. If it does not, bootstrap is
invalid and Update-text is unavailable/fails closed.

### 2.2 Closed bootstrap states

The database derives exactly one of these states:

| State | Requirement | Exact action inside the update transaction |
| --- | --- | --- |
| `existing_owner_edit` | row exists and `user_text` is non-null and byte-equal to the current joined parts | compare-and-swap the existing owner edit |
| `bootstrap_missing_row` | no `(arc_id,user_id)` row exists | INSERT only the row key, legacy `text`, `user_text` and `user_text_version`; required legacy `text` is the exact locked pre-replacement snapshot/part surface, and no browser value or other column is asserted |
| `bootstrap_null_user_text` | row exists and `user_text` is SQL null | UPDATE only `user_text` and `user_text_version`; every legacy/other column remains byte/value-identical |
| `storage_diverged` | non-null `user_text` differs from joined parts, or snapshot/parts do not agree | no request success and no write |

For both bootstrap states, the pre-replacement base is the exact locked snapshot
payload/current part join. The wrapper applies only the D19 exact locator range,
then atomically persists the resulting full document to `user_text`, the exact
resulting target text to `ideal_text_part`, one part revision and one text-update
binding. The browser cannot distinguish the two bootstrap write forms or choose
between them.

On a missing-row INSERT, the released schema's non-null legacy `text` has no
default. The wrapper therefore derives it only from the exact locked,
byte-verified pre-replacement snapshot/part surface. It must never use the
accepted replacement, browser input or an unrelated notebook value for that
column. On a null-`user_text` UPDATE, it must preserve `text`, timestamps not owned by this
operation, and every other column except the exact database-managed update time
if the released schema requires it. It never uses a destructive whole-row
upsert.

### 2.3 Exact owner-edit concurrency token

`user_text_version` is the owner-edit row's compare-and-swap token on this
Bundle path; advancing it does not advance the Feedback V3 document generation,
snapshot or head.

For an existing owner edit with token `N`, the Bundle update requires the exact
locked `N` and writes `N + 1`. For a first bootstrap, the database derives `N`
from the locked current source document version and writes `N + 1`. Overflow,
non-positive or inconsistent version state fails closed.

The response adds:

```json
{
  "result_user_text_version": 2
}
```

as a finite positive JSON integer. It enters the binding and response hashes.
The existing non-Bundle edit route must compare-and-swap this token and the
exact current `user_text` hash before writing. A legacy edit that read `N`
before a Bundle update cannot overwrite the accepted Rephrase after the Bundle
commits at `N + 1`; it receives the existing typed superseded/conflict result.

The owner Ideal Text resolver treats a current live Bundle text-update binding
and its `N + 1` owner-edit token as the visible accepted owner overlay while the
source Feedback V3 snapshot remains current. It does not hide the accepted text
merely because no new Feedback V3 snapshot was published. A later ordinary F1
successor invalidates the old binding under D18 currentness and resolves the new
document normally.

### 2.4 Capability supports INSERT and UPDATE

D19's private database-owned transaction capability adds:

```text
notes_mutation_kind = insert|update
expected_notes_row_present boolean
expected_user_text_sha256 text null
result_user_text_sha256 text
expected_user_text_version integer null
result_user_text_version integer
```

The values are database-derived. For `insert`, the exact OLD notes row is absent
and expected text/version are null. For `update`, the exact OLD row, hash and
version must match. The notes trigger consumes the capability only for that
exact INSERT or UPDATE, exact allowed columns and exact result. A browser,
header, GUC, direct service-role write or ordinary writer cannot request or
spoof either mutation kind.

Both the notes and part trigger consumptions, dual-storage postconditions,
revision, binding and capability deletion remain one transaction. The operation
still publishes/advances no Feedback V3 generation/snapshot/head.

### 2.5 Projection availability

The D13 section 6 Feedback Language item row, as amended through D19, adds one
required non-null boolean on **every** item, including excluded items:

```json
{"update_text_available": false}
```

This is the single authoritative recursively closed schema; missing/extra keys
fail closed. The value is true exactly when:

- the item is non-excluded `rewrite_clarity` with a proposed Rephrase;
- the D20 locator triple is present and valid for the exact current snapshot;
- the target lies wholly inside the exact non-empty target part;
- snapshot payload and ordered parts agree;
- owner storage is one of `existing_owner_edit`, `bootstrap_missing_row` or
  `bootstrap_null_user_text`; and
- every current authority/deletion/render prerequisite for later Update-text is
  satisfiable.

It is false for all-null locator, non-Rephrase family/output, excluded item,
empty target part or non-authorable product state. A malformed present locator
or corrupt/divergent authoritative storage remains typed projection invalidity,
not false. The frontend renders/sends Update-text only when this exact value is
true and never recomputes it.

The field participates in item/projection/summary currentness and response
hashes where that item is represented.

## 3. Durable complete coach-authorability inventory

### 3.1 One immutable inventory per Bundle version/cutoff

Before constructing any blind batch, freeze one immutable authorability
inventory for the exact Bundle version:

```text
confident_moment_coach_authorability_inventories
confident_moment_coach_authorability_items
```

The inventory header contains at least:

```text
id uuid primary key
acquisition_principal_id uuid
project_id uuid
source_take_id uuid
feedback_membership_id uuid
document_snapshot_id uuid
bundle_inventory_sha256 text
cutoff_at timestamptz
cutoff_source_generation bigint
inventory_revision integer
supersedes_inventory_id uuid null
item_count integer
audio_backed_count integer
source_audio_unavailable_count integer
inventory_sha256 text
idempotency_key text unique
created_at timestamptz
serves_user boolean default false check (not serves_user)
dataset_eligible boolean default false check (not dataset_eligible)
```

Each item row represents **every** selected Bundle attachment exactly once in
canonical Bundle/attachment order and contains at least:

```text
inventory_id uuid
bundle_id uuid
bundle_attachment_id uuid
canonical_position integer
evidence_span_id uuid
authorability_status text
audio_identity jsonb null
item_sha256 text
created_at timestamptz
serves_user boolean default false check (not serves_user)
dataset_eligible boolean default false check (not dataset_eligible)
```

`authorability_status` is exactly `audio_backed` or
`source_audio_unavailable`. The closed nullable `audio_identity` is:

```json
{
  "audio_lineage_id": "uuid",
  "media_object_id": "uuid",
  "audio_sha256": "64-lowercase-hex",
  "start_ms": 0,
  "end_ms": 1000,
  "evidence_span_id": "uuid",
  "evidence_hash": "64-lowercase-hex",
  "target_speaker_binding_id": null,
  "review_policy_version": "non-empty-string"
}
```

For `audio_backed`, the object is non-null, recursively closed and fully valid.
For `source_audio_unavailable`, it is exactly SQL/JSON null. Partial audio is
never retained as an authorizable tuple and cannot be borrowed.

Header counts, item order and the complete canonical item array enter
`inventory_sha256`. Exactly one unsuperseded head exists for the Bundle version.
A successor is a new full inventory with `inventory_revision + 1` and exact
`supersedes_inventory_id`; no row is updated or reinterpreted. Fork, duplicate,
missing/extra selected attachment or mismatched count/hash is fatal.

Both tables enable and force RLS, reject UPDATE/DELETE, grant no runtime direct
writes and join deletion traversal. Only the reviewed freezer may insert them.

### 3.2 Relationship to the blind batch

Only `audio_backed` inventory items feed D18's distinct exact evidence/audio
deduplication and `confident_moment_blind_assignment_bindings`. Every
`source_audio_unavailable` item is durably present in the product inventory but
has no assignment binding, is absent from `authorized_targets`, never enters
the judgment denominator and never blocks reveal.

The blind batch/frame stores the exact authorability inventory ID/revision/hash
and cutoff. Its required assignment set must reproduce all and only distinct
audio-backed identities from that frozen inventory.

If every selected attachment is audio-less, the system still freezes the full
authorability header/items and exact hashes, but creates no `ml_review_batch`,
assignment, blind packet, presentation, exposure, judgment, reveal grant or
coach authoring context. This is a durable product inventory with zero review
work, not an empty completed blind batch or a learning signal.

The product projection may return each item's exact
`coach_authoring_exclusion_reason=source_audio_unavailable`, but this status is
not confidence, quality, adequacy, effectiveness or dataset supervision.

## 4. Snapshot-first locator producer contract

### 4.1 Snapshot must be read before evidence construction

The service/canonical orchestration order is exactly:

1. acquire/read the exact current snapshot through
   `read_feedback_v3_candidate_source_snapshot_v1` under D11
   10→20→30→40→52→53;
2. verify the immutable snapshot's canonical Ideal Text payload hash and return
   exact snapshot ID, payload and surface SHA-256;
3. application code verifies that payload equals the exact `served_text`
   byte-for-byte before building any candidate/evidence;
4. pass the exact snapshot ID and surface hash into the evidence producer;
5. build the complete candidate bundle; and
6. persist it through the applicable candidate-set writer, which reacquires the
   same serializers and verifies the same snapshot is still the current head
   and the payload/hash still match before INSERT or exact replay.

The read RPC's transaction ends before application construction, but snapshots
are immutable. Acceptance remains race-safe because the writer repeats the full
head/currentness validation and rejects/retries if the head changed. No bundle
built against a stale snapshot may commit.

The exact read RPC is:

```text
read_feedback_v3_candidate_source_snapshot_v1(
  p_acquisition_principal_id uuid,
  p_project_id uuid,
  p_take_id uuid
) -> jsonb
```

Its exact response is:

```json
{
  "snapshot_contract_version": "feedback-v3-candidate-source-snapshot-v1",
  "document_snapshot_id": "uuid",
  "source_generation": 1,
  "surface": "exact-served-ideal-text",
  "surface_sha256": "64-lowercase-hex"
}
```

It is read-only, service-role-only, fixed-search-path and returns no transcript,
score, judgment or learning value.

### 4.2 Exact producer signature

The sole application producer signature becomes:

```text
services.feedback_data_contract._exact_transcript_evidence(
  *,
  family,
  row,
  document,
  transcript,
  served_text,
  document_snapshot_id,
  document_surface_sha256
) -> evidence | null
```

For a snapshot-bound call, both new values are required, canonical and must
match `served_text`. The producer emits D19's exact
`ideal_text_target_locator_v1`, exact snapshot ID and non-circular locator hash.

For every non-snapshot legacy/synthetic caller, both values are explicitly null
and the new locator triple is all-null. A caller may not provide only one,
invent a snapshot, recover it after construction, or upgrade an old locator by
text equality.

### 4.3 Exhaustive candidate-set writers and callers

Exactly these candidate-set writers can persist Feedback V3 candidate evidence:

```text
record_feedback_exposure_v1(uuid,uuid,uuid,jsonb)
record_feedback_v3_service_candidate_set_v1(uuid,uuid,uuid,jsonb)
```

Their exact production application callers are:

```text
services/db.py::DatabaseService.record_canonical_feedback_exposure
  -> record_feedback_exposure_v1

services/first_client_repository.py::FirstClientRepository.record_feedback_v3_service_candidate_set
  -> record_feedback_v3_service_candidate_set_v1
```

The service orchestrator
`services/mlc3_first_client_feedback.py::prepare_first_client_feedback` must
read/verify the snapshot **before** `build_feedback_exposure_bundle`; the current
post-persistence snapshot lookup is prohibited. Any other production caller of
either writer or producer is an unregistered-writer/caller failure.

`record_feedback_v3_service_candidate_set_v1` requires the exact non-null
snapshot-bound locator triple for every eligible service rewrite target.
`record_feedback_exposure_v1` preserves non-snapshot compatibility by requiring
the explicit all-null triple unless its caller has independently adopted the
same snapshot-first contract.

### 4.4 Exact replay and non-circular identity

The locator hash is exactly the canonical JSON SHA-256 over:

```json
{
  "document_snapshot_id": "uuid",
  "locator": {
    "version": "ideal-text-target-locator-v1",
    "surface": "ideal_text",
    "surface_hash": "64-lowercase-hex",
    "start": 0,
    "end": 17,
    "exact_text": "exact target wording"
  }
}
```

It excludes `evidence_span_id` and `evidence_hash`, so no circular hash exists.
The evidence identity then includes the exact snapshot ID and this completed
locator hash before deriving `evidence_hash`/stable evidence ID.

On `ON CONFLICT`, both candidate-set writers reload and compare the complete
stored locator triple, snapshot ID, locator hash, evidence hash and candidate
identity. A stored old/all-null locator cannot replay a newly non-null request;
a non-null locator cannot replay as null; a foreign snapshot, changed locator,
old hash formula, or changed surface fails with the writer's exact replay-
conflict error. No UPDATE/backfill occurs during replay.

The locator/snapshot remains serialized at D19's exact 52→53 discovery,
applicable 60→70, 90 and final 140 row-validation positions.

## 5. D11 lock order and permissions

D11 section 2 remains the sole full order from 10 through 140. D20 does not
renumber or omit any position. Snapshot read/persist uses 10→20→30→40→52→53;
audio validity adds 60→70; Bundle/assignment uses 90; root uses 100; coach
wording preserves 110→120→130; current rows validate at 140.

The owner bootstrap notes row and ordered part inventory are discovered under
52/53. The database-owned INSERT/UPDATE capability is created only after all
applicable serializers and final identity comparison. Authorability inventory
freezing uses the same Bundle/evidence/audio serializers as its future batch.

All new durable inventory/binding tables enable and force RLS, are append-only,
RPC-only and deletion-connected. The transient capability table retains D19's
forced-RLS/no-runtime-access consume-and-delete contract. D19's accurate legacy
fact remains: `ideal_text_part` and `user_arc_ideal_notes` have RLS enabled but
are not currently forced-RLS/RPC-only; their legacy compatibility writes remain.

## 6. Required regressions

### 6.1 Bootstrap and concurrency

1. Missing notes row and null `user_text` independently bootstrap from the exact
   locked snapshot/parts, update only allowed note columns, and atomically
   produce dual storage, one revision and one binding.
2. Missing-row bootstrap stores the exact locked pre-replacement snapshot/part
   surface in required legacy `text`; null-text bootstrap preserves a non-empty
   legacy `text` and every unrelated column byte/value-identically.
3. Browser bootstrap fields/whole-document text are rejected as extra keys.
4. Capability validates exact notes INSERT versus UPDATE and both trigger
   consumptions; cross-kind, wrong OLD row/hash/version and direct-write spoof
   fail without suppression.
5. Bundle update reads owner token `N`, commits `N+1`, leaves Feedback V3
   generation/snapshot/head unchanged and remains visibly current.
6. A legacy edit that read `N` before Bundle commit rejects after `N+1`; it
   cannot overwrite the accepted Rephrase. Exact Bundle replay returns `N+1`.
7. Projection availability is true for each valid bootstrap state, false for
   honest unavailable state, and typed invalid for malformed/diverged state.

### 6.2 Durable authorability inventory

1. Every selected attachment appears exactly once in frozen canonical order
   with one of the two statuses and the correct nullable tuple.
2. Missing/extra/duplicate/reordered item, partial audio tuple, wrong counts,
   wrong cutoff/hash and forked successor reject.
3. Mixed audio-backed/audio-less inventory creates assignments only for the
   distinct audio-backed set; audio-less items never block reveal or appear in
   authorized targets.
4. All-audio-less Bundle freezes the durable product inventory but creates no
   review batch/assignment/reveal/context.
5. Inventory replay returns the same rows/hash; a changed source creates only a
   full immutable successor under reviewed policy and never mutates history.
6. Borrowing a sibling audio/assignment/access for an unavailable item rejects
   with zero authoring writes and no learning label.

### 6.3 Producer order and replay

1. Static call-order tests prove snapshot read precedes bundle/evidence build
   and no post-persistence lookup is used as locator provenance.
2. Snapshot payload/served-text mismatch rejects before candidate build.
3. A head change between read/build and writer commit fails closed/retry with
   zero candidate/evidence rows.
4. Exact producer arguments emit the golden locator/snapshot/hash; one-null and
   foreign inputs reject; explicit non-snapshot calls emit all-null triple.
5. Both exact candidate writer signatures and caller tuples are mechanically
   exhaustive; added/renamed/overloaded callers fail.
6. ON CONFLICT rejects null→non-null, non-null→null, old-hash, foreign-snapshot,
   changed-surface and changed-locator replay without UPDATE.
7. Golden identity test proves locator hash excludes evidence ID/hash and the
   completed locator hash enters evidence identity exactly once.

### 6.4 Closed frontend schema

1. Every confidence, rewrite, praise and excluded item contains exactly one
   boolean `update_text_available`.
2. Only an eligible valid-locator/bootstrap-ready Rephrase returns true.
3. Missing, extra, non-boolean or frontend-derived availability rejects; closed
   schema and response hashes change deterministically.

All D11–D19 apply/reapply, atomic rollback, lock graph, deadlock, grant/revoke,
RLS, deletion, exact transport, bigint-string, blindness and zero-fabricated-
learning tests remain mandatory.

## 7. Gates and stop conditions

Every Bundle, rooting, PAM, serving, collection, dataset, training, evaluation
and promotion gate retains its exact disabled default. Durable D20 provenance
remains structurally `serves_user=false` and `dataset_eligible=false`.

Stop and request ML/data interface review if implementation would:

- ask the browser whether/how to bootstrap or accept browser initial document
  text/version/owner-row state;
- derive missing-row legacy `user_arc_ideal_notes.text` from anything except
  the exact locked pre-replacement snapshot/part surface, or overwrite the
  existing legacy value or unrelated columns during null-text bootstrap;
- fail to advance/check the owner-edit concurrency token or allow a stale legacy
  writer to overwrite a Bundle update;
- hide an otherwise-current accepted Bundle edit merely because Feedback V3
  snapshot/head did not advance;
- treat authorability as an ephemeral filter instead of freezing every selected
  attachment/status/cutoff/order/hash;
- create an empty review batch for an all-audio-less inventory;
- build evidence before reading/verifying the immutable snapshot, or fetch the
  snapshot only after candidate persistence;
- allow an old/null/foreign locator to replay a new exact locator;
- include evidence ID/hash in locator hash and create a circular identity;
- omit or let frontend infer `update_text_available`;
- weaken D11's full order, D19's capability/dual-storage/locator/audio-less/RLS
  boundaries, any blindness/Manager/deletion/non-learning fence, or any disabled
  gate; or
- number, commit, push, merge, deploy, activate or collect without separate
  authorization.

`VERDICT: D20 PROPOSED FOR PRODUCT, ML/DATA AND ENGINEERING REVIEW; EXECUTABLE WORK BLOCKED`
