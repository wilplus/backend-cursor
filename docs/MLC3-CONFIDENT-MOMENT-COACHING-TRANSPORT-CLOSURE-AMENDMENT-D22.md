# MLC-3 Confident Moment Coaching Bundle — Transport Closure Amendment D22

Status: proposed final owner-edit persistence and transport closure; executable
work remains blocked pending independent Product, ML/data and Engineering
acceptance.

## 1. Parent and scope of supersession

D22 binds and narrowly supersedes:

```text
MLC3-CONFIDENT-MOMENT-COACHING-TRANSPORT-CLOSURE-AMENDMENT-D21.md
SHA-256 5848f263b6e7678a4ff8bb63c19bd1c4664f373cc95971a5c0c36e436c1c8b3b
```

D21, D20 and their accepted D3/D11–D19 parents remain authoritative except
where D22 replaces:

1. ordinary owner-edit persistence with one atomic text-and-parts CAS;
2. D16's `persist_ideal_text_user_edit_v2` boundary;
3. the recursively closed Ideal Text read and Bundle Update-text wire shapes;
4. compatibility behavior for the exact legacy request shapes; and
5. the migration order for the new owner-edit revision and guard.

The invariant remains exact: `user_text_version` is only the source Ideal Text
document version. `user_text_revision BIGINT` is only the database-owned owner-
edit CAS revision. Neither value advances the Feedback V3 generation, document
snapshot or document head.

## 2. One atomic ordinary owner-edit document transaction

### 2.1 Closed write unit

`compare_and_set_user_ideal_edit_v1` persists, in one database transaction:

- the exact complete desired `user_arc_ideal_notes.user_text`;
- the exact current source version in `user_text_version`;
- the database-allocated `user_text_revision`;
- the exact complete ordered `ideal_text_part` inventory for that owner/arc;
- one immutable `ideal_text_part_revision` for every part whose text or
  permitted owner-controlled lock state changed; and
- the exact idempotency/replay result and part-revision inventory.

Failure of any text, part, revision, authority, version, lock, hash or replay
check rolls back all of them. The route must not call
`replace_ideal_text_parts` after the RPC, and there is no best-effort parts
write. A successful response means both representations were committed and
agree byte-for-byte under the canonical join rule.

### 2.2 Exact part preservation and mutation rules

The database locks and loads the full current ordered part inventory. The
desired inventory must contain every current part exactly once, in exactly the
same order and with the same stable part IDs. It may not add, remove, duplicate,
reorder or replace an ID.

For each part:

- its desired text is exact UTF-8 text after the already-frozen request
  sanitization; the database performs no semantic rewrite;
- immutable root/source/provenance fields are preserved byte-identically;
- an omitted legacy `locked` member preserves the current lock state;
- an explicit `locked` member may make only the already-authorized owner lock
  transition; it cannot alter root provenance or manufacture qualification;
- unchanged text and lock state create no new part revision;
- every changed part creates exactly one immutable
  `ideal_text_part_revision`, bound to the source document version, previous
  part revision/head, resulting part state, owner-edit revision and operation;
  and
- all non-target metadata and all unchanged parts remain byte-identical.

The canonical join of the resulting ordered part texts must equal the complete
desired `user_text`. Empty separators follow the accepted D19/D20 rule. A
whole-text/parts disagreement fails before mutation.

### 2.3 D16 writer is superseded

D22 explicitly supersedes D16's `persist_ideal_text_user_edit_v2`. There is one
ordinary owner-edit writer only:

```text
services/db.py::DatabaseService.compare_and_set_user_ideal_edit
  -> compare_and_set_user_ideal_edit_v1
```

No application-side second part write is allowed. Existing post-success
telemetry, phrase-decision capture, variant capture and publication may execute
only after the atomic RPC commits; they remain non-authoritative best-effort
consumers and may not change the committed CAS result or fabricate a part
revision.

## 3. Exact ordinary-edit RPC

### 3.1 Signature

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

The SQL signature retains nullable CAS/hash/idempotency parameters because the
closed first-write and legacy compatibility branches are database-derived.
The browser never supplies a desired owner revision or part revision.

The exact recursively closed response is:

```json
{
  "ideal_text_user_edit_contract_version": "ideal-text-user-edit-cas-v2",
  "saved": true,
  "arc_id": "arc-id",
  "source_document_version": 4,
  "previous_user_text_revision": "7",
  "result_user_text_revision": "8",
  "result_user_text_sha256": "64-lowercase-hex",
  "desired_parts_lineage_sha256": "64-lowercase-hex",
  "part_revisions": [
    {"part_id": "uuid", "revision_id": "9223372036854775806"}
  ],
  "dataset_eligible": false
}
```

`previous_user_text_revision` is `null` only for a genuine first write.
`part_revisions` is in canonical part order and contains exactly the changed
parts; `revision_id` is a canonical positive base-10 JSON string. An unchanged
exact replay returns the original identical array and hashes. This array is the
only ordinary-edit source from which the frontend may obtain the exact part
revision needed by a later manual/current-part root action.

### 3.2 Transaction behavior

Under D11's complete numeric lock order, the RPC derives principal, Project,
source document and current parts; validates live dual-purpose authority,
deletion and exact source head; stabilizes the current full part inventory;
locks the notes row and every part/head in canonical order; checks both owner
revision and owner-text hash; allocates revision `1` or exact `N+1`; applies the
closed part mutation; inserts immutable changed-part revisions; changes the
three owner-edit lane columns; revalidates the complete resulting join,
authority, source head and result hashes; stores the immutable replay result;
and returns only after commit eligibility is proven.

An idempotency key cannot replay different expected state, text, parts, source
version or principal. An exact replay repeats currentness checks and returns
the exact stored result. A current-state conflict returns only the canonical
typed `IDEAL_TEXT_USER_EDIT_CONFLICT` and performs zero writes.

## 4. Exact HTTP request contracts and legacy compatibility

### 4.1 Current CAS request

`PUT /v2/explore/arc/{arc_id}/ideal-text/user-edit` accepts this recursively
closed current shape:

```json
{
  "text": "complete non-empty desired owner text",
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

The exact required current keys are `text`, `version`, `parts`,
`expected_user_text_revision`, `expected_user_text_sha256` and
`idempotency_key`. `reapplied` is optional and accepted only when exactly
boolean `true` or `false`; only exact `true` emits the existing telemetry.
Unknown keys fail closed for a current CAS client.

Owner text must remain non-empty after the frozen sanitization. D22 chooses
safe rejection of empty text with `IDEAL_TEXT_EMPTY_EDIT_REJECTED`; empty text
does not clear the edit and never creates the all-null triple. Clearing an
owner edit, if later desired, requires a separate reviewed immutable operation.

`expected_user_text_revision` is `null` only when the current edit is absent;
otherwise it is a canonical positive decimal JSON string. A JSON number,
leading sign/zero, fraction, exponent, boolean or object rejects.
`expected_user_text_sha256` is `null` exactly with absent current edit;
otherwise it is exact lowercase SHA-256. One null and one non-null always
rejects.

### 4.2 Exact frozen old-client shapes

The only legacy request keys are:

```text
required: text, version
optional: parts, reapplied
forbidden/absent: expected_user_text_revision,
                  expected_user_text_sha256,
                  idempotency_key
```

An old client may omit `parts`. It may omit `reapplied`; if present,
`reapplied` must be exact boolean and only `true` has telemetry meaning.
Unknown keys reject. A request containing any but not all three CAS-era keys is
neither current nor legacy and rejects.

For an accepted legacy request, the server derives a deterministic idempotency
identity from the exact authenticated owner, arc, current source document
version, expected current owner revision/hash, desired text hash and complete
desired part-lineage hash. It is namespaced `legacy-ideal-text-user-edit-v1`.
The client cannot override it.

If `parts` is present, it is validated as the exact complete desired inventory.
If absent, the database may derive the desired full part inventory only when:

1. the current locked part inventory is unique and structurally valid;
2. the desired `text` is byte-identical to the canonical join of that inventory;
3. no part text, order, ID or lock change is required; and
4. all source/currentness checks pass.

Therefore a legacy no-parts request can replay/save only an already matching
part document. It cannot distribute changed whole text across parts. If desired
text differs, return `IDEAL_TEXT_PARTS_REFRESH_REQUIRED` with zero writes.

D21's bounded old-client CAS compatibility remains: omission of token/hash is
accepted only before a current Bundle binding/edit exists for this exact owner,
arc and source version, while the locked transaction can derive the exact
current revision/hash. Once a current Bundle binding exists, a legacy request
returns `IDEAL_TEXT_CAS_REQUIRED`. A stale ordinary edit racing a Bundle update
uses the same locks: exactly one commits; the loser returns the canonical
conflict/refresh error and performs zero partial text or part writes.

## 5. Recursively closed Ideal Text read transport

The canonical Ideal Text GET that supplies the editor must include this exact
closed owner-edit object whenever its enclosing response permits the edit lane:

```json
{
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
        "current_part_revision_id": "9223372036854775806"
      }
    ],
    "current_bundle_text_update_binding": {
      "binding_id": "uuid",
      "bundle_id": "uuid",
      "attachment_id": "uuid",
      "source_document_version": 4,
      "result_user_text_revision": "8",
      "result_user_text_sha256": "64-lowercase-hex",
      "result_part_revision_id": "9223372036854775806"
    }
  }
}
```

The exact valid-empty state is:

```json
{
  "owner_edit": {
    "text": null,
    "source_document_version": null,
    "user_text_revision": null,
    "user_text_sha256": null,
    "parts": [],
    "current_bundle_text_update_binding": null
  }
}
```

All listed object keys are always present. All bigint identities/revisions are
canonical decimal JSON strings or null. No numeric bigint transport is legal.
The database/read repository must derive the text hash from the exact returned
bytes and prove that source version, current revision, complete parts join and
current Bundle binding agree under the D11 locks. A stale/foreign/broken
binding or partial triple is typed projection invalidity, not omission.

The enclosing frontend mapper is recursively closed: unknown keys at the
owner-edit, part or Bundle-binding level fail its contract parser. It must not
supplement the response with direct part/table reads.

## 6. Exact Bundle Update-text CAS transport

The accepted D20 Bundle Update-text request is extended—not replaced—with:

```json
{
  "bundle_id": "uuid",
  "attachment_id": "uuid",
  "correction_decision_id": "uuid",
  "feedback_exposure_id": "uuid",
  "render_receipt_id": "uuid",
  "source_document_snapshot_id": "uuid",
  "source_document_version": 4,
  "target_part_id": "uuid",
  "expected_current_part_revision_id": "9223372036854775805",
  "expected_user_text_revision": "7",
  "expected_user_text_sha256": "64-lowercase-hex",
  "accepted_replacement_text": "non-empty exact replacement",
  "expected_ordered_part_ids": ["uuid"],
  "idempotency_key": "non-empty-string"
}
```

For a D20 first-owner bootstrap, both expected owner CAS values are null; for
every current edit, both are non-null and exact. Partial nulls reject. Bigints
are JSON strings. The backend route and
`ConfidentMomentBundleRepository.apply_text_update` pass these values exactly;
they never derive them from stale component state, coerce them to JavaScript
numbers or invent a result revision.

The exact SQL signature is:

```text
apply_confident_moment_bundle_text_update_v1(
  p_owner_user_id uuid,
  p_bundle_id uuid,
  p_attachment_id uuid,
  p_correction_decision_id uuid,
  p_feedback_exposure_id uuid,
  p_render_receipt_id uuid,
  p_source_document_snapshot_id uuid,
  p_source_document_version integer,
  p_target_part_id uuid,
  p_expected_current_part_revision_id bigint,
  p_expected_user_text_revision bigint,
  p_expected_user_text_sha256 text,
  p_accepted_replacement_text text,
  p_expected_ordered_part_ids uuid[],
  p_idempotency_key text
) -> jsonb
```

Its closed response retains D20/D21 provenance and adds exact bigint-string
transport:

```json
{
  "bundle_text_update_contract_version": "bundle-text-update-v1",
  "binding_id": "uuid",
  "source_document_snapshot_id": "uuid",
  "source_document_version": 4,
  "previous_user_text_revision": "7",
  "result_user_text_revision": "8",
  "previous_user_text_sha256": "64-lowercase-hex",
  "result_user_text_sha256": "64-lowercase-hex",
  "target_part_id": "uuid",
  "result_part_revision_id": "9223372036854775806",
  "dataset_eligible": false
}
```

First bootstrap returns null previous revision/hash. Repository and route map
the response without dropping or renaming fields. The resulting exact part
revision is the only accepted source for an `accepted_rewrite` root action.

## 7. Migration order, guards and apply/reapply

The unnumbered pending migration must execute in this order:

1. add `user_text_revision bigint null` without installing its guard;
2. acquire the frozen owner/arc and part inventory locks;
3. validate every existing row: all-null owner triple, or non-empty
   `user_text` + positive source `user_text_version`; any partial/invalid state
   aborts the whole migration;
4. initialize every valid existing edit to `user_text_revision=1` without
   changing text, source version, parts, IDs, order, locks, notebook columns,
   document snapshot/head or timestamps except a migration-owned audit fact;
5. create the CAS RPC and Bundle wrapper/capability changes;
6. create the private guard helper and then the exact `BEFORE INSERT OR UPDATE`
   `user_arc_ideal_notes_user_text_cas_guard`; and
7. run signature, trigger, caller, permission, invariant and PostgREST-reload
   closure checks before commit.

On reapply, initialization changes nothing and the installed guard remains
active. Reapply cannot require bypassing the guard through a public mechanism.
Any failure rolls back the column, initialization, functions, triggers,
revisions and registry changes atomically.

The D21 private transaction-local capability is expanded to bind the complete
desired part inventory/hash and exact changed-part revision result. The BEFORE
guard still rejects every direct change to `user_text`, `user_text_version` or
`user_text_revision`; only the Bundle wrapper or CAS RPC can issue and consume
the exact private capability. The legacy notebook `text`-only lane remains
compatible when all three owner fields are byte-identically unchanged.

## 8. Registry and lock closure

Add/freeze these exact identities:

```text
RPC:
compare_and_set_user_ideal_edit_v1(uuid,text,integer,bigint,text,text,jsonb,text)

Bundle RPC:
apply_confident_moment_bundle_text_update_v1(
  uuid,uuid,uuid,uuid,uuid,uuid,uuid,integer,uuid,bigint,bigint,text,text,uuid[],text
)

application caller:
services/db.py::DatabaseService.compare_and_set_user_ideal_edit
  -> compare_and_set_user_ideal_edit_v1

Bundle caller:
services/confident_moment_bundle_repository.py::
  ConfidentMomentBundleRepository.apply_text_update
  -> apply_confident_moment_bundle_text_update_v1

trigger:
public.user_arc_ideal_notes::user_arc_ideal_notes_user_text_cas_guard
  -> guard_user_ideal_edit_cas_v1()
```

`DatabaseService.upsert_user_ideal_edit` and application-side
`replace_ideal_text_parts` after an owner-edit RPC are forbidden production
callers. The AST/static registry test must reject direct PostgREST writes to the
three owner columns and any two-step text/part persistence path.

D11's entire numeric global order remains authoritative. D22 adds no alternate
order. Both ordinary CAS and Bundle Update-text acquire the identical
principal/Project/document/notes/part serializers and row locks in the same
order. D20's relevant 60/70/90/100/110 positions and the accepted coach
110→120→130 order remain unchanged. A forced stale ordinary-edit-versus-Bundle
race in both start orders must complete without deadlock and with exactly one
atomic winner.

## 9. Required executable regressions

Implementation review must execute at least:

1. first ordinary edit atomically writes text, complete parts, owner revision
   `1`, and one revision for each changed part;
2. subsequent `N→N+1`, bigint beyond JavaScript safe range as JSON string, and
   exact replay return the same changed-part revision inventory;
3. a forced part-revision failure rolls back notes text/revision and every part;
4. omission/add/remove/reorder/duplicate/foreign part ID, wrong joined text,
   forbidden root metadata change and stale part head all reject with zero
   writes;
5. unchanged parts create no part revisions; each changed part creates exactly
   one and preserves all other metadata;
6. route performs no post-RPC `replace_ideal_text_parts` call;
7. current GET returns the exact recursive keys, bigint strings, hash, source
   version, full parts and current Bundle binding; valid-empty returns every
   key with the frozen null/empty values; unknown/malformed fields reject;
8. current ordinary request rejects missing/extra/partial CAS keys, numeric
   bigint, wrong hash, stale revision, empty text and changed idempotency replay;
9. exact legacy key-set parsing; present parts work atomically; absent parts
   succeed only for byte-identical derivable inventory; changed no-parts text
   returns `IDEAL_TEXT_PARTS_REFRESH_REQUIRED`;
10. deterministic server-derived legacy idempotency exactly replays and cannot
    cross owner, arc, version, text or part inventory;
11. bounded no-token/hash compatibility before a Bundle binding, rejection
    after a current Bundle binding, and rejection of any partial CAS-era shape;
12. Bundle first bootstrap null/null→revision `1`; later exact CAS; wrong/stale
    token or hash; exact response and binding previous/result revisions/hashes;
13. Bundle route/repository pass both CAS fields and bigint strings exactly;
14. stale ordinary edit versus Bundle update in both commit orders: one full
    text-and-parts result commits, loser writes nothing, no mixed document and
    no deadlock;
15. migration apply/reapply proves add→validate/initialize→guard ordering,
    existing edit initialization to `1`, all-null preservation, invalid partial
    rollback and no public bypass window;
16. direct service-role INSERT/UPDATE/upsert of any owner lane field fails;
    cross-wrapper/replayed/spoofed capability fails; notebook text-only write
    remains compatible; and
17. every D20/D21 bootstrap, dual-storage, locator, coach-authorability,
    blindness, deletion, authorization, RLS/RPC-only, exact replay and
    structural non-learning regression remains green.

No test may treat a successful text write with failed parts as acceptable.

## 10. Permissions, gates and stop conditions

Both registered public RPCs are `SECURITY DEFINER`, fixed-search-path and
executable only by `service_role`. `PUBLIC`, `anon` and `authenticated` have no
execution. Private capability/guard helpers remain inaccessible to every
runtime role. D19/D20's accurate legacy-table RLS statement remains: the
historical table posture is not silently relabeled forced-RLS; this amendment
closes only the three owner fields through the trigger and registered RPCs.

Every Bundle, rooting, PAM, serving, collection, dataset, training, evaluation
and promotion gate retains its exact disabled default. All new facts remain
`serves_user=false` and `dataset_eligible=false`.

Stop and request review if implementation would:

- persist owner text and parts in separate transactions or tolerate a failed
  part write;
- retain or reintroduce D16 `persist_ideal_text_user_edit_v2`;
- let the browser choose any desired/result owner or part revision;
- reinterpret/increment `user_text_version` as an edit counter;
- transport bigint identities as JSON numbers;
- accept empty owner text as an implicit clear;
- infer a changed legacy no-parts document by distributing text across parts;
- let an old/no-token client overwrite a current Bundle-bound edit;
- omit current CAS/hash/source/binding facts from the canonical GET;
- allow a direct owner-lane upsert or public capability;
- change D11's lock order or weaken any D20/D21 provenance, blindness,
  authorization, deletion, non-serving or non-learning boundary;
- change a disabled gate; or
- number, commit, push, merge, deploy, activate or collect without separate
  authorization.

`VERDICT: D22 PROPOSED FOR PRODUCT, ML/DATA AND ENGINEERING REVIEW; EXECUTABLE WORK BLOCKED`
