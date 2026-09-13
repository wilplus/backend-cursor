# MLC-3 Confident Moment Coaching Bundle — Transport Closure Amendment D21

Status: proposed final CAS amendment; executable work remains blocked pending
independent Product, ML/data and Engineering acceptance.

## 1. Parent and narrow supersession

D21 binds and narrowly supersedes:

```text
MLC3-CONFIDENT-MOMENT-COACHING-TRANSPORT-CLOSURE-AMENDMENT-D20.md
SHA-256 336afdae0d5c2f4f2b1e2b3cdece2f5e6f302f2aee8fe097cffb3d9daa49286a
```

D20 and its D3/D11–D19 parents remain authoritative except where D21 replaces
the owner-edit concurrency rule and direct `user_text` application writer.

`user_text_version` and owner-edit revision are two different facts and must
never again share one field:

- `user_text_version` remains exclusively the exact source Ideal Text document
  version against which the owner edit was made; and
- new `user_text_revision BIGINT` is exclusively the database-managed
  compare-and-swap revision of the owner-edit row.

D21 does not advance Feedback V3 generation/snapshot/head and preserves every
blindness, Manager-budget, authorization, deletion, RLS, non-learning and
disabled-gate boundary accepted through D20.

## 2. Exact owner-edit schema and invariants

Add to `user_arc_ideal_notes`:

```text
user_text_revision bigint null
```

The closed state is:

| Owner edit state | `user_text` | `user_text_version` | `user_text_revision` |
| --- | --- | --- | --- |
| no current edit | null | null | null |
| current edit | non-null | positive source document version | positive bigint CAS revision |

Partial states are invalid. `user_text_revision` is database allocated and may
never be supplied as a desired value by a browser or application caller.

For a first genuine owner edit, expected revision is null and the database
writes result revision `1`. For every subsequent successful edit, the caller
must name exact current revision `N` and the database writes `N + 1`. Overflow,
zero, negative, skipped revision, duplicate result revision or changed current
row fails closed.

The Bundle text-update binding and D19 private capability add exact fields:

```text
source_document_version integer
previous_user_text_revision bigint null
result_user_text_revision bigint
previous_user_text_sha256 text null
result_user_text_sha256 text
```

For first write, previous revision/hash are null and result revision is `1`.
For subsequent write, previous revision is `N`, result is `N+1`, and both hashes
are exact lowercase SHA-256. These values enter the immutable binding,
capability, idempotency and response hashes.

`user_text_version` is written to the exact current source document version and
does not increment during a Bundle edit against that same source. The Bundle
result may advance `user_text_revision`; it must not change
`user_text_version`, Feedback V3 generation, snapshot or head.

## 3. Canonical CAS writer for the user-text lane

### 3.1 Direct whole-row upsert is retired for this lane

The current application method `DatabaseService.upsert_user_ideal_edit` performs
a service-role whole-row PostgREST upsert. It is no longer allowed to mutate
`user_text`, `user_text_version` or `user_text_revision` after D21 applies.

The exact replacement caller is:

```text
services/db.py::DatabaseService.compare_and_set_user_ideal_edit
  -> compare_and_set_user_ideal_edit_v1
```

No route, service, worker or script may directly insert/update those three
columns. The legacy notebook writer may continue changing only
`user_arc_ideal_notes.text` and its already-owned notebook metadata.

### 3.2 Registered RPC

```text
compare_and_set_user_ideal_edit_v1(
  p_owner_user_id uuid,
  p_arc_id text,
  p_source_document_version integer,
  p_expected_user_text_revision bigint,
  p_expected_user_text_sha256 text,
  p_desired_user_text text,
  p_desired_parts_lineage jsonb,
  p_idempotency_key text
) -> jsonb
```

The two expected CAS inputs are nullable in SQL only for the exact first-write
or explicitly permitted initial compatibility state. The desired revision is
never an input.

The RPC is `SECURITY DEFINER`, fixed-search-path and executable only by
`service_role`. `PUBLIC`, `anon` and `authenticated` have no execution. It is
added to the exact signature, proname/overload, permission, caller and D11 lock
registries. The retired direct method/call tuple must disappear from production
code.

### 3.3 Exact HTTP request and bigint transport

The existing non-Bundle route remains:

```http
PUT /v2/explore/arc/{arc_id}/ideal-text/user-edit
```

The current client request becomes recursively closed:

```json
{
  "text": "complete desired owner text",
  "version": 4,
  "parts": [
    {"id": "uuid", "text": "exact part text", "locked": false}
  ],
  "expected_user_text_revision": "7",
  "expected_user_text_sha256": "64-lowercase-hex",
  "idempotency_key": "non-empty-string",
  "reapplied": false
}
```

`version` is the exact positive source document version. It is not a CAS
revision. `expected_user_text_revision` is null or a canonical positive base-10
JSON string. Number, sign, exponent, decimal, leading zero, boolean or object
rejects. `expected_user_text_sha256` is null exactly when the expected current
owner edit is absent; otherwise it is lowercase SHA-256.

`parts` remains the exact complete ordered client-held part lineage. The backend
validates its existing closed part shape and canonical join, then passes a
server-canonical `p_desired_parts_lineage` containing exact part IDs/order/text
hashes/locks and the joined-text hash. The database rederives current Project,
principal, source document/head and stored part/owner state under locks; browser
parts never become authority without exact equality/currentness validation.

### 3.4 Exact RPC rules

Under D11 10→20→30 and applicable 40→50→51→52→53 serializers, followed by
canonical part/row validation at 140, the RPC:

1. derives the exact acquisition principal/Project/source document from the
   owned arc and source version;
2. validates current service/deletion authority and exact current document
   version/head;
3. validates the complete desired text/parts join and lineage;
4. locks the exact `(arc_id,owner_user_id)` notes row, or proves it absent;
5. compares both expected revision and expected text hash to current state;
6. allocates result revision `1` or `N+1`;
7. INSERTs only key + required legacy `text` + `user_text`,
   `user_text_version` and `user_text_revision` for a first row; because the
   released legacy column is non-null with no default, its value is the exact
   locked pre-edit source surface and is never browser supplied; or UPDATEs
   only those three owner-edit lane columns plus exact
   database-owned timestamp on an existing row;
8. preserves every notebook/other column; and
9. repeats authority, source-version and exact result checks before return.

Expected `(null,null)` is valid only when no current owner edit exists. Any
combination `(null,hash)` or `(revision,null)` rejects. If a current edit exists,
both exact non-null expected values are required unless section 5's bounded old-
client compatibility applies.

An existing row with `user_text=null`, `user_text_version=null` and
`user_text_revision=null` is the same first-write state as an absent row. The
RPC UPDATEs only the three lane columns and preserves legacy `text`/other
columns. A row with any partial state is corrupt and fails closed.

Exact idempotent replay returns the original result only after revalidating its
source version, current result revision/hash, desired text/parts lineage and
authority. Same key with changed expected/current/desired identity conflicts.

### 3.5 Exact response

```json
{
  "ideal_text_user_edit_contract_version": "ideal-text-user-edit-cas-v1",
  "saved": true,
  "arc_id": "arc-id",
  "source_document_version": 4,
  "previous_user_text_revision": "7",
  "result_user_text_revision": "8",
  "result_user_text_sha256": "64-lowercase-hex",
  "desired_parts_lineage_sha256": "64-lowercase-hex",
  "dataset_eligible": false
}
```

`previous_user_text_revision` is null on first write and otherwise a bigint
string. `result_user_text_revision` is always a canonical positive bigint
string. No extra key is permitted.

## 4. BEFORE guard and database-owned capabilities

Add this exact trigger identity:

```text
user_arc_ideal_notes_user_text_cas_guard
  -> guard_user_ideal_edit_cas_v1()
```

It is a `BEFORE INSERT OR UPDATE` trigger on `user_arc_ideal_notes`. It examines
only whether `user_text`, `user_text_version` or `user_text_revision` would be
created or changed.

Such a change is allowed only when the current transaction holds one exact
unconsumed database-created capability for either:

```text
apply_confident_moment_bundle_text_update_v1
compare_and_set_user_ideal_edit_v1
```

The capability is bound to current transaction ID, backend PID, exact wrapper,
principal, owner, Project, arc, source document version, expected row absence or
exact prior revision/hash, exact desired hash/parts lineage, and exact result
revision. The trigger derives OLD/NEW state itself, matches all fields, and
atomically consumes the notes-guard permission once.

For the Bundle wrapper, D19's two generation-trigger consumption flags remain;
the exact Bundle capability therefore proves the BEFORE CAS guard, notes
generation trigger and target-part generation trigger all observed the same
operation. Only the Bundle capability suppresses Feedback V3 generation. The
ordinary CAS RPC capability authorizes the BEFORE guard but preserves the
released ordinary generation-trigger behavior.

The guard/helper/capability functions have no runtime execute grant. The
capability table has forced RLS and no runtime direct access. A GUC, role,
header, browser value, session value, whole-row upsert or direct service-role
table request cannot satisfy the guard.

An INSERT or UPDATE that changes only legacy notebook `text` and its separately
owned metadata, while leaving all three user-text lane columns identical/null,
remains compatible and needs no user-text capability.

## 5. Initial compatibility and old clients

### 5.1 Existing-row initialization

At migration apply, existing rows are classified under one locked, checksum-
pinned compatibility operation:

- all-null owner-edit triple remains all null;
- every structurally valid non-null `user_text` + positive
  `user_text_version` receives `user_text_revision=1`; and
- a partial/invalid owner-edit state blocks migration rather than being guessed.

The initialization changes no `user_text`, `user_text_version`, legacy `text`,
part, document generation/snapshot/head or learning row. Apply/reapply verifies
the same result exactly.

### 5.2 Old request without token/hash

An old client omitting both expected CAS fields may use a bounded compatibility
branch only when all of these are true under the same locks:

- no current/live `confident_moment_bundle_text_update_bindings` exists for the
  owner/arc/source document;
- no current Bundle-bound owner edit has been served;
- the request's source document version is exactly current;
- the current owner edit state is structurally valid;
- the desired text/parts lineage passes all existing validation; and
- no concurrent owner edit crosses the locked operation.

The database derives the current revision/hash internally, executes one CAS and
returns the new token/hash. This branch preserves initial rollout compatibility;
it is not available after a current Bundle binding/edit exists.

Once a current Bundle binding exists, an old request missing either expected
field fails with typed `IDEAL_TEXT_CAS_REQUIRED`. It may refetch the current
Ideal Text response, which now carries exact revision/hash, and resubmit through
the current contract. It may never overwrite or silently supersede the Bundle
edit.

Supplying only one expected field always rejects, before and after Bundle use.
An old client's whole-row direct upsert is rejected by the BEFORE guard.

## 6. Bundle Update-text correction

D20 section 2 is corrected as follows:

- `user_text_version` remains exactly the source document version;
- `user_text_revision` is null before first owner edit, then `1`, then exact
  `N+1` for each owner edit;
- the Bundle request/repository uses the exact current revision/hash from the
  owner Ideal Text response in addition to D20's decision/render/snapshot/
  inventory identities;
- D20 bootstrap writes source version plus result owner revision `1`;
- D19/D20 capability and immutable Bundle binding store previous/result owner
  revisions and hashes; and
- the Bundle response transports previous/result revisions as bigint strings.

The Bundle wrapper still atomically updates `user_text` and one exact part range,
creates one part revision and binding, suppresses its two generation advances,
and publishes no Feedback V3 snapshot/head.

The owner Ideal Text resolver retains the source-version rule:

```text
user_text_version must equal the current source document version
```

When a current live Bundle binding exists, it additionally requires the notes
row's exact `user_text_revision` and hash to equal the binding result. Thus the
accepted Rephrase remains visible and root-current without pretending its owner
revision is a document version. A later F1 source-version successor naturally
supersedes it under the existing rule.

## 7. Registered identities and lock order

Add to the exhaustive registries:

```text
compare_and_set_user_ideal_edit_v1(uuid,text,integer,bigint,text,text,jsonb,text)

services/db.py::DatabaseService.compare_and_set_user_ideal_edit
  -> compare_and_set_user_ideal_edit_v1

user_arc_ideal_notes_user_text_cas_guard
  -> guard_user_ideal_edit_cas_v1()
```

The old production tuple
`DatabaseService.upsert_user_ideal_edit -> direct table upsert` is forbidden for
the three owner-edit columns. AST/static checks fail on any `.table("user_arc_ideal_notes")`
INSERT/UPDATE/upsert that can set them outside approved migration/test code.

D11's complete order remains authoritative. The CAS path uses 10→20→30,
applicable 40→50→51, then 52→53, followed by the exact notes/part/current rows at
140. Bundle Update-text retains every D18–D20 applicable 60/70/90/100/110
position. Coach wording retains 110→120→130. D21 adds no numeric position.

## 8. Required regressions

### 8.1 Schema and transport

1. `user_text_version` always equals its exact source document version and does
   not increment for an edit against the same source.
2. First owner edit writes revision `1`; exact current `N` writes `N+1`; null,
   partial, skipped, overflow and changed-current states reject.
3. Revisions above `2^53` round-trip only as canonical JSON strings; JSON numbers
   and malformed strings reject.
4. Bundle capability/binding and CAS response contain exact source version,
   previous/result revision and hashes.

### 8.2 CAS and direct-write closure

1. Exact revision+hash CAS succeeds once and exact replay returns the same row;
   stale revision, stale hash, changed desired text/parts or reused key rejects.
2. A missing-row first write derives required legacy `text` only from the exact
   locked pre-edit source surface; a null-edit-row first write preserves its
   existing legacy `text`; both preserve every unrelated column.
3. Whole-row/direct service-role INSERT, UPDATE and upsert of any owner-edit
   column are rejected by the BEFORE guard with no partial change.
4. Bundle and CAS capabilities independently authorize only their exact OLD/NEW
   row; cross-wrapper, wrong transaction/backend/principal/document/hash/
   revision, duplicate consumption and GUC/header spoof reject.
5. Text-only legacy notebook INSERT/UPDATE remains compatible and cannot mutate
   the owner-edit triple.

### 8.3 Old-client race

1. Before any Bundle binding, a valid old request omitting both expected fields
   may execute the bounded locked compatibility CAS and receives new token/hash.
2. Supplying only one expected field always rejects.
3. Client A reads revision `N`; Bundle update commits `N+1`; A's current CAS at
   `N` rejects and the accepted Rephrase remains stored/visible.
4. The same race through an old no-token client fails with
   `IDEAL_TEXT_CAS_REQUIRED` once the Bundle binding exists.
5. An old direct PostgREST upsert after Bundle commit is rejected by the trigger.
6. Ordinary later F1 source-version successor supersedes the edit without
   rewriting owner revision/binding history.

### 8.4 Registries and unchanged fences

Exact signature/caller/trigger extraction rejects missing, extra, renamed or
overloaded writers. Apply/reapply validates safe initialization and rejects
partial legacy state. D11–D20 lock, deadlock, atomic rollback, RLS, deletion,
locator, authorability, closed-schema and zero-fabricated-learning tests remain
mandatory.

## 9. Permissions, gates and stop conditions

The new RPC is service-role-only; the guard and capability helpers are internal-
only. D19's factual legacy RLS statement remains: the shared notes/part tables
are RLS-enabled but not yet forced-RLS/RPC-only. D21 closes only the three owner-
edit columns with the BEFORE guard; it does not falsely claim broader table
closure or break the notebook text lane.

Every Bundle, rooting, PAM, serving, collection, dataset, training, evaluation
and promotion gate retains its exact disabled default. Durable provenance stays
`serves_user=false` and `dataset_eligible=false`.

Stop and request ML/data interface review if implementation would:

- increment or reinterpret `user_text_version` as an owner-edit counter;
- derive source document version from `user_text_revision` or vice versa;
- accept a browser-chosen desired/result revision;
- compare only revision or only hash when a current edit exists;
- permit a direct whole-row upsert to mutate any owner-edit column;
- use a public/GUC/role/header capability or let CAS suppress ordinary document
  generation;
- let an old no-token/hash client overwrite a current Bundle-bound edit;
- hide a current Bundle edit despite matching source version and exact live
  binding revision/hash;
- alter D11's full order or any D20 bootstrap/dual-storage/locator/
  authorability/RLS/blindness/non-learning boundary;
- change a disabled gate; or
- number, commit, push, merge, deploy, activate or collect without separate
  authorization.

`VERDICT: D21 PROPOSED FOR PRODUCT, ML/DATA AND ENGINEERING REVIEW; EXECUTABLE WORK BLOCKED`
