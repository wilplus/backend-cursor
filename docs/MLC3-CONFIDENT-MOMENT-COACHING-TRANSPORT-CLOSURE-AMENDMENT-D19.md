# MLC-3 Confident Moment Coaching Bundle — Transport Closure Amendment D19

Status: proposed interface amendment; executable work remains blocked pending
independent Product, ML/data and Engineering acceptance.

## 1. Parent and narrow supersession

D19 binds and narrowly supersedes:

```text
MLC3-CONFIDENT-MOMENT-COACHING-TRANSPORT-CLOSURE-AMENDMENT-D18.md
SHA-256 eb836df41641c7bd252517516d392110e7fc9da3ef9eba3481ae34a3461bda99
```

D18 and its D16/D17 parents remain authoritative except where D19 explicitly
replaces:

1. the target-part-only persistence description with one exact atomic update
   of both `user_arc_ideal_notes.user_text` and `ideal_text_part.text`;
2. the underspecified document-generation suppression with a database-owned,
   transaction-local, exact-operation capability;
3. the assumed `evidence_spans.target_locator` contract with an additive,
   nullable, snapshot-bound locator identity and producer contract;
4. blind-batch treatment of selected attachments that have no exact audio; and
5. any statement implying that legacy `ideal_text_part` is already forced-RLS
   or RPC-only.

D19 preserves the complete D11 numeric lock graph, D12–D18 closed transport,
blindness, Manager budget, deletion/authority checks, non-serving and non-
learning boundaries, and every disabled gate.

## 2. Bundle Update-text atomically changes both canonical owner views

### 2.1 Exact two-row-family transaction

`apply_confident_moment_bundle_text_update_v1` must update, in one PostgreSQL
transaction:

1. the exact owner row's `user_arc_ideal_notes.user_text`; and
2. the exact target row's `ideal_text_part.text`.

In that same transaction it appends exactly one target
`ideal_text_part_revision` and exactly one
`confident_moment_bundle_text_update_bindings` row. It does not advance or
publish a Feedback V3 document generation/snapshot/head, exactly as D18 freezes.

The database derives the current full owner document by joining all current
non-empty `ideal_text_part.text` values in canonical `ord` order using exactly
two bytes/characters, `\n\n`, between adjacent retained parts. Empty parts are
not legal in the frozen Bundle update inventory. No leading or trailing
separator is added.

Before mutation, the exact joined part document must equal
`user_arc_ideal_notes.user_text` byte-for-byte. A null owner edit, missing owner
row, empty part, duplicate order, gap/ambiguity in the authoritative part
inventory, or mismatch returns typed
`CONFIDENT_MOMENT_IDEAL_TEXT_STORAGE_DIVERGED` and writes nothing.

After replacing the one exact locator range in the target part, the database
rebuilds the complete document with the same separator rule and writes that
exact byte string to `user_arc_ideal_notes.user_text`. Postconditions require:

- `user_arc_ideal_notes.user_text` equals the joined resulting parts byte-for-
  byte;
- every non-target part ID, `ord`, text byte, lock value, lock timestamp, root
  field and other metadata is unchanged;
- the target part keeps its ID, `ord`, lock and non-text metadata;
- only the exact target range changes;
- `user_text_version` remains the exact source document version;
- exactly one part revision names the target and resulting target text; and
- exactly one text-update binding names that exact revision.

Failure of any postcondition raises and rolls back both storage representations,
the revision, binding and capability. No best-effort write exists in this path.

### 2.2 No self-invalidating document publication

The transaction does not mutate `ideal_text_document_generations`, create an
`ideal_text_document_snapshots` row, or advance the canonical Feedback V3
document head. The binding's source and result snapshot IDs remain identical to
the Bundle's frozen source snapshot. Exact replay and the immediate root action
remain valid until an ordinary later F1 writer independently publishes a
successor, as D18 requires.

Neither the source snapshot nor its stored payload is mutated. The owner edit
and part revision are an exact overlay bound to that immutable source.

## 3. Spoof-proof transaction-local generation capability

### 3.1 Internal capability state

The two existing document-generation triggers on
`user_arc_ideal_notes` and `ideal_text_part` may suppress generation advancement
only when an exact database-owned capability exists for the current transaction.

Add one private operational table:

```text
confident_moment_text_update_capabilities
```

Its row contains exactly:

```text
capability_id uuid primary key
transaction_id bigint
backend_pid integer
operation_name = apply_confident_moment_bundle_text_update_v1
acquisition_principal_id uuid
owner_user_id uuid
project_id uuid
arc_id text
bundle_id uuid
bundle_attachment_id uuid
target_part_id uuid
expected_user_text_sha256 text
result_user_text_sha256 text
expected_part_text_sha256 text
result_part_text_sha256 text
notes_trigger_consumed boolean default false
part_trigger_consumed boolean default false
capability_sha256 text
created_at timestamptz
```

The table is transaction-operational state, not product evidence. It is not
returned or retained after success. It enables and forces RLS and grants no
SELECT/INSERT/UPDATE/DELETE to `PUBLIC`, `anon`, `authenticated` or
`service_role`. Its creator/check/consume/delete helpers are `SECURITY DEFINER`,
fixed-search-path, internal-only functions with no execute grant to runtime
roles. No public RPC accepts a capability ID, operation name, transaction ID,
backend PID or suppression flag.

### 3.2 Creation, consumption and proof

Only `apply_confident_moment_bundle_text_update_v1`, after all D11 serializers
and live-source checks are held, may create one capability. The wrapper derives
all fields from locked database lineage and generates its UUID internally. The
row is bound simultaneously to `txid_current()`, `pg_backend_pid()`, the exact
wrapper name, principal, owner, document, Bundle/attachment, target part and
the exact permitted OLD/NEW hashes for both writes.

Each generation trigger calls the private checker. Suppression occurs only if
one and only one unconsumed capability matches:

- current transaction ID and backend PID;
- exact trigger table and operation;
- exact principal/owner/arc/part identity derivable from OLD and NEW;
- exact allowed OLD and NEW UTF-8 hashes; and
- the expected wrapper operation.

The notes trigger atomically marks only `notes_trigger_consumed=true`; the part
trigger marks only `part_trigger_consumed=true`. Duplicate consumption,
unexpected columns, a second row, wrong order/identity/hash, direct runtime
write or non-Bundle writer does not suppress generation and causes the Bundle
wrapper to fail.

Before return, the wrapper proves both triggers consumed the same capability,
proves the two exact storage postconditions, then deletes the capability inside
the same transaction. Successful commit retains no capability row. Error,
connection loss or rollback rolls back the capability and all data changes.

A transaction-local GUC, request header, browser nonce, caller-provided UUID,
session variable, role name or mere `SECURITY DEFINER` nesting is insufficient
and prohibited as the authority. The capability is database-created and
database-verified from the exact mutation itself.

Ordinary F1 publication, the legacy non-Bundle edit path and direct service-role
table writes cannot create or consume this capability; their generation
triggers retain existing behavior.

## 4. Exact nullable Ideal Text target locator

### 4.1 Additive canonical storage

The legacy `evidence_spans.target_locator JSONB NOT NULL DEFAULT '{}'` remains
historical compatibility data and is not authoritative for D18/D19 replacement.
D19 adds these exact nullable columns to `evidence_spans`:

```text
ideal_text_target_locator_v1 jsonb null
ideal_text_target_snapshot_id uuid null
ideal_text_target_locator_sha256 text null
```

All three are null or all three are non-null. The snapshot ID has an immutable
foreign key to the exact `ideal_text_document_snapshots.id`. The locator hash is
the canonical JSON SHA-256 of the complete locator object plus evidence span ID
and snapshot ID. No default is permitted.

The non-null locator object is recursively closed:

```json
{
  "version": "ideal-text-target-locator-v1",
  "surface": "ideal_text",
  "surface_hash": "64-lowercase-hex",
  "start": 0,
  "end": 17,
  "exact_text": "exact target wording"
}
```

`start/end` retain D18's zero-based, end-exclusive Unicode scalar-value
semantics. No extra/missing key, null member, normalization or repaired value is
accepted. The object's `surface_hash` must equal the exact frozen snapshot
Ideal Text UTF-8 hash, and the stored snapshot ID must equal the Bundle/
membership snapshot used to select the candidate.

An exact all-null triple means `ideal_text_target_locator_unavailable`; it is
not malformed data and creates no Update-text request. A partially null triple,
`{}`, unknown version, invalid shape/hash/range/text or foreign snapshot is
present-but-malformed and returns typed
`CONFIDENT_MOMENT_TEXT_TARGET_INVALID`. It may not be treated as absence.

### 4.2 Sole producer and persistence

The sole application producer is the existing canonical evidence builder:

```text
services/feedback_data_contract.py::_exact_transcript_evidence
```

For an exact Ideal Text rewrite target, it emits the closed locator using the
already-served immutable Ideal Text surface and its exact snapshot identity.
The canonical candidate-set freeze writer validates and persists the three
columns atomically with the evidence span. Browser data is never accepted as a
locator.

Every synthetic/service candidate-set writer that can persist such evidence is
included in the closed writer/caller registry and must call the same database
validator. After persistence the locator triple is immutable; correction is a
new evidence/candidate revision, never UPDATE.

Bundle preparation copies no coordinates. It retains the evidence span and
snapshot foreign keys; Update-text loads the authoritative locator directly
under locks. Projection exposes only:

```json
{"update_text_available": true}
```

for an exact current non-null valid locator, or `false` for the all-null state.
It never exposes locator coordinates to the browser. Malformed present locator
fails projection with the typed error rather than returning false.

### 4.3 Snapshot, separator and lock position

Locator verification uses the exact immutable Feedback V3 snapshot surface.
The current ordered non-empty part inventory must join with exactly `\n\n`
between adjacent parts and equal the current owner `user_text` before mutation.
An empty part is not silently dropped for locator arithmetic: its presence makes
the Bundle update inventory invalid and Update-text unavailable until resolved
through the ordinary non-Bundle edit path. There is no alternate separator or
paragraph splitter.

The D11 order remains complete. Locator/snapshot identity is discovered and
serialized under 52 then 53. Applicable speaker/audio validity still locks 60
then 70. Bundle/evidence identity locks at 90, and the immutable locator/evidence
rows receive their final canonical row-lock validation at 140. No 140 row lock
may be acquired before applicable 60/70/90/100/110/120/130 serializers.

## 5. Audio-less selected attachments

### 5.1 Exact product-only exclusion

A selected Bundle subject or attachment is coach-authorable only if it has a
complete exact blind-review audio identity:

```text
recording/audio lineage ID + live media/object identity + audio SHA-256
+ finite start_ms/end_ms with end_ms > start_ms
+ exact evidence span and evidence hash
+ target-speaker binding revision where the review policy requires it
```

If any required audio member is absent, the item is typed
`coach_authoring_exclusion_reason=source_audio_unavailable`.

That exclusion is product-routing state only. The item:

- remains a selected Manager/Bundle attachment with its existing user-facing
  machine Feedback Language where otherwise valid;
- is not added to the blind assignment inventory;
- has no `confident_moment_blind_assignment_bindings` row;
- is absent from coach `authorized_targets`;
- creates no assignment, packet, presentation, exposure or judgment;
- does not count as a required blind-batch assignment;
- never blocks complete-batch reveal for the audio-backed required set; and
- creates no quality, confidence, missingness, adequacy or learning label.

No assignment, audio, judgment or reveal access may be borrowed from another
Bundle subject/attachment, even when the two share a Bundle, family, Slide,
text, snippet or visual position. A later version with its own exact audio may
enter a later frozen batch; it never retrofits the historical audio-less item.

### 5.2 Mixed inventory and complete reveal

The D18 distinct-evidence rule applies only to audio-backed items. The canonical
batch freezes one assignment per distinct complete audio/evidence tuple among
those items, deduplicating only exact tuple equality.

Complete-batch reveal requires immutable judgments for every required
audio-backed assignment and no others. Audio-less exclusions are frozen in the
Bundle coach-context inventory so omission is explicit and reproducible, but
they are not assignments and do not enter the judgment denominator.

If every selected Bundle item is audio-less, there is no Bundle coach-authoring
batch/context. This is honest absence of coach authoring, not a completed empty
review or a no-match learning signal.

The post-reveal context includes only audio-backed authorized targets. It may
include an aggregate product-only count of audio-less exclusions, but never raw
content or a fabricated assignment identity.

## 6. Accurate legacy RLS boundary

At the frozen base, `ideal_text_part` has RLS **enabled** by
`migrations/add_ideal_text_parts.sql`, but it does not have `FORCE ROW LEVEL
SECURITY`. The legacy application writes it directly through the service-role
PostgREST table client. `user_arc_ideal_notes` likewise has RLS enabled with no
user policy, is not forced-RLS, and is written through the service-role
compatibility path. D19 must not claim that either legacy table is already
forced-RLS, append-only or RPC-only.

D19 preserves the non-Bundle compatibility writer. It does not revoke the
legacy service-role privileges in this scope. Security of Bundle Update-text is
instead established by:

- the sole exact Bundle RPC;
- the database-owned capability, which legacy/direct writers cannot create;
- exact principal/document/part/decision/exposure/render validation;
- the complete D11 lock graph; and
- forced-RLS, append-only, no-direct-write controls on every new immutable
  Bundle binding table.

The future removal of legacy direct writes or conversion of these two shared
tables to forced RLS is a separate migration/review and cannot be silently
folded into D19.

## 7. Lock graph, permissions, deletion and replay

D11 section 2 remains the sole full numeric order. D18's explicit preservation
of 10–140, including all applicable 60/70/100 positions and 110 then 120 then
130, remains unchanged. D19 adds no new numeric position.

The notes row, ordered part inventory and private capability are discovered
under 52/53 and validated at 140. Locator evidence follows 52/53, applicable
60/70, 90 and final 140 validation. Audio-less classification is derived before
the assignment set is frozen; audio-backed assignment bindings follow the D18
batch locks and exact evidence/audio leaf locks.

Every affected canonical writer/trigger/worker is in the exhaustive signature,
caller and lock-graph registries. Identity sets are derived under coarse locks,
hashed, fine-locked in canonical order, rederived and compared. A changed set
returns only the reviewed retry error before mutation.

New immutable binding tables enable and force RLS, deny direct runtime writes,
reject UPDATE/DELETE and join deletion traversal. The private transient
capability table also enables/forces RLS and grants no runtime access, but is
not append-only because the exact wrapper must consume and delete its
transaction-local row before success.

Exact replay repeats current authority, document/part consistency, locator,
decision/render, deletion/media and snapshot-head validation. A later ordinary
F1 snapshot, changed locator/inventory, invalid audio, different exclusion set
or changed identity under the same idempotency key conflicts or fails closed.

## 8. Required regressions

### 8.1 Dual storage and capability

1. A valid update changes one exact range in both `user_text` and target part,
   produces byte-identical joined storage, one revision and one binding, with no
   document generation/snapshot/head change.
2. Pre-existing mismatch between `user_text` and joined parts rejects before a
   write; forced postcondition failure rolls back all four result families.
3. Every non-target byte, ID, order, lock, root and metadata field is unchanged.
4. Both generation triggers consume the same exact capability once; missing,
   duplicate, wrong-table, wrong-hash, wrong-principal, wrong-document,
   wrong-part, wrong-transaction and wrong-backend capabilities reject.
5. Browser/GUC/header/caller UUID spoof attempts and direct service-role writes
   cannot suppress generation. Ordinary F1 and legacy non-Bundle edits retain
   their prior generation behavior.
6. Successful commit retains zero capability rows; rollback and connection loss
   retain zero rows and no partial edit.

### 8.2 Locator

1. Exact nullable all-null locator makes `update_text_available=false` and the
   frontend sends no request.
2. A complete valid locator is persisted only by the exact producer, bound to
   the exact snapshot, and yields `update_text_available=true`.
3. Partial null, `{}`, extra/missing key, wrong version/surface/hash/range/text/
   snapshot and cross-part range produce the typed error with zero writes.
4. Transcript `start_char/end_char` deliberately differ and are ignored.
5. Unicode, combining characters, repeated strings, multi-part offsets and
   canonical `\n\n` separators have golden results. Empty parts fail closed and
   are never silently omitted from arithmetic.
6. Producer, candidate-freeze, projection and Update-text use the same locator
   validator/hash; no browser coordinate or text search enters the path.

### 8.3 Audio-less/mixed batches

1. A mixed Bundle with one audio-backed and one audio-less selected attachment
   freezes one required assignment, one binding for the audio-backed item, and
   an explicit product-only exclusion for the other.
2. Judgment of the one required assignment opens reveal; the audio-less item
   never blocks it and is absent from `authorized_targets`.
3. Attempting to author the audio-less attachment with the sibling assignment,
   judgment, audio or access fails with zero revision/delivery/binding writes.
4. Two audio-backed siblings with differing evidence still require two exact
   assignments as D18 freezes; exact identical tuples deduplicate to one.
5. All-audio-less inventory produces no coach-authoring batch/context and no
   fabricated empty completion.
6. A later audio-backed version does not mutate or reinterpret the historical
   exclusion.

### 8.4 Security and compatibility

1. Schema tests assert the factual legacy state: RLS enabled but not forced on
   `ideal_text_part` and `user_arc_ideal_notes` unless a separately reviewed
   later migration changes it; new Bundle binding tables are forced-RLS.
2. The legacy non-Bundle edit path remains behaviorally compatible and cannot
   create/use a Bundle capability or binding.
3. D11 full lock-order, deadlock, apply/reapply, atomic negative rollback,
   grants, caller registry, deletion traversal, closed JSON and idempotency
   suites remain green.
4. No response, confidence, judgment, qualification, improvement, adequacy,
   outcome, dataset, training, evaluation, promotion or ninth learning-surface
   row is fabricated.

## 9. Gates and stop conditions

`CONFIDENT_MOMENT_BUNDLE_V1_ENABLED`, `ROOTING_COVERAGE_V1_ENABLED`, all PAM,
serving, collection, dataset, training, evaluation and promotion gates retain
their exact disabled defaults. All durable D19 product provenance remains
`serves_user=false` and `dataset_eligible=false`.

Stop and request ML/data interface review if implementation would:

- update only the part or only `user_arc_ideal_notes.user_text`;
- allow those two storage representations to diverge before or after success;
- suppress a generation trigger through a GUC, browser/request value, role
  check, caller-provided capability or any identity not bound to the exact
  transaction, backend, wrapper, principal, document, part and OLD/NEW hashes;
- publish/advance a Feedback V3 snapshot/head or self-invalidate the update;
- use legacy `target_locator`, transcript offsets, text search, normalization or
  repaired coordinates instead of the exact nullable snapshot-bound locator;
- treat a malformed present locator as absent, or send Update-text when the
  locator is absent;
- silently drop an empty part or use a separator other than exact `\n\n`;
- require an audio-less attachment in the blind batch, let it block reveal, or
  borrow another attachment's audio/assignment/judgment;
- infer a label or quality meaning from audio absence;
- claim legacy `ideal_text_part`/`user_arc_ideal_notes` are currently forced-RLS
  or RPC-only, or revoke their compatibility writes without separate review;
- omit any applicable D11 lock position or alter 110→120→130;
- weaken D3/D11–D18 blindness, Manager budget, authority, deletion, RLS on new
  tables, non-serving, non-learning or disabled-gate boundaries; or
- number, commit, push, merge, deploy, activate or collect without separate
  authorization.

`VERDICT: D19 PROPOSED FOR PRODUCT, ML/DATA AND ENGINEERING REVIEW; EXECUTABLE WORK BLOCKED`
