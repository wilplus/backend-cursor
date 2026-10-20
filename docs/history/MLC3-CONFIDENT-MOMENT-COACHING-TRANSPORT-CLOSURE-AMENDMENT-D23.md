# MLC-3 Confident Moment Coaching Bundle — Transport Closure Amendment D23

Status: proposed final structural-edit, legacy-replay and Bundle-derived-target
closure; executable work remains blocked pending independent Product, ML/data
and Engineering acceptance.

## 1. Parent and narrow supersession

D23 binds and narrowly supersedes:

```text
MLC3-CONFIDENT-MOMENT-COACHING-TRANSPORT-CLOSURE-AMENDMENT-D22.md
SHA-256 9dfaf5f2c01b6cf887f0080fe1e0ca76b7cbfb859e089000aaffcde814170453
```

D22, D21, D20 and their accepted parents remain authoritative except where
D23 replaces:

1. D22's fixed-part-inventory rule with the closed bootstrap and structural
   owner-edit policy below;
2. D22's legacy idempotency identity with a stable desired-operation ledger;
3. the Bundle Update-text browser/RPC shapes so target part and replacement
   text are database-derived; and
4. the canonical Bundle repository method name with `update_text`.

Atomic text/parts/revisions persistence, the owner CAS, migration order, D11's
complete lock graph, exact authorization/deletion checks, blindness, non-
serving/non-dataset semantics and every disabled gate remain unchanged.

## 2. Closed ordinary structural-edit policy

### 2.1 Expected-current inventory is authority

The current ordinary request's `parts` field contains both the exact
expected-current inventory and exact desired inventory:

```json
{
  "expected_parts": [
    {
      "position": 0,
      "part_id": "uuid",
      "text_sha256": "64-lowercase-hex",
      "locked": false,
      "current_part_revision_id": "9223372036854775806"
    }
  ],
  "desired_parts": [
    {
      "position": 0,
      "part_id": "uuid",
      "text": "exact desired text"
    }
  ]
}
```

Both arrays are recursively closed, ordered by consecutive zero-based
`position`, and contain unique UUID part identities. Every bigint is a
canonical positive base-10 JSON string or null where explicitly permitted.
The database rederives the complete current inventory, text hashes, lock state,
root metadata and current revision heads under the D11 locks and requires exact
equality with `expected_parts`. The browser never asserts hidden root metadata.

### 2.2 First-owner `bootstrap_missing_parts`

The database derives `bundle_structural_edit_kind`; the browser cannot choose
it. `bootstrap_missing_parts` is permitted only when:

- the current exact owner/arc part inventory is empty under lock;
- no current or historical part identity exists for that owner/arc/source
  document version;
- the current owner edit is absent under D21's null-triple rule;
- `expected_parts` is exactly empty;
- `desired_parts` is non-empty, uses unique client-minted UUIDs and consecutive
  zero-based positions, and its canonical join equals non-empty desired text;
- every new part begins unlocked, unrooted, unqualified, iteration zero and
  without root/source/selection metadata; and
- current source, authority, deletion and idempotency checks pass.

Each new part receives exactly one immutable revision with action
`owner_part_created`. The client chooses only a collision-free UUID identity;
it cannot choose revision, lock, root, qualification or provenance state.
A UUID already present anywhere in the authoritative part/revision lineage
rejects the entire bootstrap.

### 2.3 Existing unrooted/unlocked structural edits

Against a non-empty exact expected inventory, an ordinary edit may add, remove,
reorder or change text only for parts whose current stored state is both
unlocked and unrooted and which have no active root-block/head dependency.

- **Add:** a new unique UUID may be inserted at any desired position, initially
  unlocked/unrooted with zero iteration and no root metadata; action
  `owner_part_created` is appended.
- **Text update:** an existing eligible part retains its UUID and receives
  action `owner_part_text_updated`.
- **Reorder:** every retained eligible part whose position changes retains its
  UUID and receives action `owner_part_reordered`, unless its text also changes,
  in which case the one revision uses `owner_part_text_updated_and_reordered`.
- **Remove:** before the row is removed, append an immutable tombstone revision
  `owner_part_removed` containing its final exact text, prior revision/head,
  prior position and owner-edit operation. The tombstone becomes the terminal
  head for that part identity and the UUID can never be reused.

Extend the closed `ideal_text_part_revision.action` constraint only with those
five exact action values. The immutable revision schema/head lineage must retain
the previous part revision, owner-edit revision, previous/result positions and
operation identity needed to distinguish creation, content change, reorder and
removal. A structural operation produces at most one new revision per affected
part and one exact terminal head per identity.

### 2.4 Rooted/locked preservation boundary

The ordinary CAS cannot change a part's lock state. Lock/unlock remains solely
the canonical root-state transition at D11 lock position 100.

An existing locked, rooted, qualified or active-root-dependent part must retain
the same identity, position and byte-identical text. Removing, reordering or
editing any such affected part fails the whole operation with
`IDEAL_TEXT_PART_REQUIRES_UNLOCK`; it never silently carries stale root
coordinates/metadata and never clears a root as a side effect. Adding or
editing an unrelated eligible part is permitted only when it leaves every
protected part byte-identical at the same position; inserting before a
protected part therefore counts as a prohibited reorder of that protected
part.

No `locked` desired value is accepted. The expected boolean is currentness
evidence only. Rooting, locking and qualification are never inferred from an
ordinary edit.

## 3. Atomic persistence and returned revisions

`compare_and_set_user_ideal_edit_v1` remains D22's sole atomic ordinary writer.
It commits the notes text/CAS state, the complete resulting part inventory and
all required immutable part revisions/tombstones as one unit. Any structural,
revision, head, unique-slot, authorization or replay failure rolls all of them
back.

Its response retains D22 and returns `part_revisions` in deterministic order:
resulting part position first, then removed parts in their prior position,
then UUID byte order as a final tie-break:

```json
{
  "part_revisions": [
    {
      "part_id": "uuid",
      "revision_id": "9223372036854775806",
      "action": "owner_part_text_updated",
      "previous_position": 1,
      "result_position": 1
    }
  ]
}
```

For `owner_part_created`, previous position is null. For
`owner_part_removed`, result position is null. Other actions require both.
The response array is recursively closed and is the only ordinary-edit source
for an exact current manual-root revision. Removed/tombstone revisions can
never source a root action.

## 4. Stable legacy no-key operation identity

### 4.1 Immutable operation ledger

Add one forced-RLS, RPC-only, append-only CAS operation ledger. The canonical
legacy operation key is the SHA-256 of:

```text
namespace = legacy-ideal-text-user-edit-v2
owner acquisition principal
owner user identity
arc identity
source document version
canonical desired user_text bytes/hash
canonical complete desired part inventory/hash
```

It intentionally excludes current/expected owner revision and current text
hash. Therefore retrying the same old request after its first successful result
finds the same immutable operation instead of being reinterpreted as a new edit.
The ledger stores the exact precondition revision/hash, result revision/hash,
part revision array, canonical result hash and created time.

### 4.2 Replay and intervening edit

On an exact legacy-key hit, the RPC revalidates authority/source/deletion and
loads the current owner text, revision and complete part heads under the same
locks:

- if they still equal the stored result exactly, return the original exact
  response without a write;
- if any intervening ordinary, Bundle or root/part operation changed the stored
  result state, return `IDEAL_TEXT_LEGACY_REPLAY_CONFLICT` with zero writes; and
- never apply the old desired state as a new `N+1` edit.

Two different desired text/part documents necessarily have different operation
keys. Concurrent duplicate legacy requests serialize to one operation/result.
The browser may not provide or override the derived legacy key.

D22's old-client parts rules remain: present parts must define the exact desired
inventory under this D23 matrix; omitted parts may succeed only when the
database derives one exact current full inventory whose join already equals the
desired text. Otherwise `IDEAL_TEXT_PARTS_REFRESH_REQUIRED` performs no write.

## 5. Bundle Update-text is wholly database-derived

### 5.1 Browser request

The Bundle Update-text request is recursively closed and contains neither
`target_part_id` nor replacement text:

```json
{
  "bundle_id": "uuid",
  "attachment_id": "uuid",
  "correction_decision_id": "uuid",
  "feedback_exposure_id": "uuid",
  "render_receipt_id": "uuid",
  "source_document_snapshot_id": "uuid",
  "source_document_version": 4,
  "expected_current_part_revision_id": "9223372036854775805",
  "expected_user_text_revision": "7",
  "expected_user_text_sha256": "64-lowercase-hex",
  "expected_part_inventory": [
    {
      "position": 0,
      "part_id": "uuid",
      "text_sha256": "64-lowercase-hex",
      "locked": false
    }
  ],
  "idempotency_key": "non-empty-string"
}
```

Every inventory object and array is closed, complete and canonically ordered.
It is only an optimistic-currentness assertion: the database rederives the
actual inventory, lock/root metadata and heads. Unknown keys—including
`target_part_id`, `accepted_replacement_text`, `replacement_text` or any
equivalent browser wording/locator assertion—fail before an RPC call.

### 5.2 Exact RPC and repository caller

The sole Bundle writer is:

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
  p_expected_current_part_revision_id bigint,
  p_expected_user_text_revision bigint,
  p_expected_user_text_sha256 text,
  p_expected_part_inventory jsonb,
  p_idempotency_key text
) -> jsonb
```

D23 explicitly supersedes the D22 repository tuple. The exact caller is:

```text
services/confident_moment_bundle_repository.py::
  ConfidentMomentBundleRepository.update_text
  -> apply_confident_moment_bundle_text_update_v1
```

`ConfidentMomentBundleRepository.apply_text_update` is not a production caller
and must be absent. D16 `persist_ideal_text_user_edit_v2` remains superseded.

### 5.3 Derivation and authorization

Under the complete D11/D20 lock boundary, the database derives:

1. the exact current Bundle and attachment;
2. the exact exposed/rendered correction decision authorized by that
   attachment and user;
3. the canonical accepted replacement bytes from the immutable correction
   decision/output revision; and
4. the exact target part and byte range solely from D18–D20's frozen
   snapshot-bound `target_locator`.

It proves the locator is present, exact, inside one target part and bound to
the supplied source snapshot/version. It compares the derived target part's
current revision to `p_expected_current_part_revision_id` and compares the
complete database part inventory to `p_expected_part_inventory`. It then
performs D20/D21's atomic dual-storage range replacement and immutable binding.

The result continues to return the database-derived `target_part_id`, accepted
replacement hash/decision identity, result part revision, previous/result owner
revision/hash and source snapshot/version. The browser cannot cause a different
part or different wording to be persisted, even if it tampers with local
display text.

## 6. Migration and registry closure

D22's order remains mandatory: add and validate/initialize
`user_text_revision` before installing the BEFORE guard; create wrappers and
private capability; install guard last; run closure checks; reload PostgREST;
commit atomically. D23 additionally alters the part-revision action/head schema
and creates the immutable legacy CAS operation ledger before either public
writer is replaced. Apply/reapply preserves initialized rows and creates no
duplicate operations or revisions.

Freeze these exact identities:

```text
ordinary RPC:
compare_and_set_user_ideal_edit_v1(uuid,text,integer,bigint,text,text,jsonb,text)

Bundle RPC:
apply_confident_moment_bundle_text_update_v1(
  uuid,uuid,uuid,uuid,uuid,uuid,uuid,integer,bigint,bigint,text,jsonb,text
)

ordinary caller:
services/db.py::DatabaseService.compare_and_set_user_ideal_edit
  -> compare_and_set_user_ideal_edit_v1

Bundle caller:
services/confident_moment_bundle_repository.py::
  ConfidentMomentBundleRepository.update_text
  -> apply_confident_moment_bundle_text_update_v1
```

The D21 notes guard/capability binds the exact expected and resulting complete
part inventories, structural action/revision set and operation-ledger identity
in addition to its owner revision/hash fields. It cannot authorize a lock/root
change. Runtime roles have no direct ledger, notes-owner-lane or revision
writes. The owner-edit route may not call a direct part writer; separately
registered non-owner F1/core-snapshot part writers keep their existing reviewed
compatibility boundary and are not silently revoked by D23. D11's full numeric
lock order remains authoritative; lock transitions
retain position 100 and cannot be folded into the CAS position.

## 7. Required executable regressions

Implementation review must add, while retaining every D20–D22 regression:

1. empty-current-inventory first write accepts one valid non-empty consecutive
   UUID inventory, initializes every part unlocked/unrooted, and creates one
   `owner_part_created` revision per part;
2. bootstrap rejects empty desired parts, duplicate/used UUID, nonconsecutive
   position, root/lock/iteration/source metadata, joined-text mismatch and any
   concurrent inventory appearance, with zero partial writes;
3. existing unlocked/unrooted inventory permits add, remove, reorder and text
   change; exact resulting heads/actions/positions and one-revision-per-part
   rules hold;
4. removing a part creates a terminal immutable tombstone and its UUID cannot
   be reused or source a root;
5. changing/removing/reordering any locked, rooted, qualified or active-head
   part returns `IDEAL_TEXT_PART_REQUIRES_UNLOCK`; unchanged protected parts
   survive byte-identically; CAS cannot change lock state;
6. expected-current inventory wrong hash/order/ID/lock/revision rejects before
   mutation; simultaneous root transition versus CAS follows D11 order without
   deadlock and one stale side rejects;
7. identical legacy retries before and after the first commit derive the same
   ledger key and return one exact stored result; the key is independent of the
   now-current revision;
8. a later ordinary/Bundle/part operation followed by the old legacy retry
   returns `IDEAL_TEXT_LEGACY_REPLAY_CONFLICT`, never overwrites and never
   allocates another revision;
9. concurrent duplicate legacy requests create exactly one operation and one
   set of text/part revisions;
10. Bundle route rejects any target-part or replacement-text key before calling
    the repository; repository `update_text` passes only the closed fields;
11. database derives exact target part/range and exact replacement bytes from
    attachment/decision/locator, persists them, and returns their identities;
12. a locally altered displayed suggestion cannot alter the stored wording;
    foreign decision, attachment, locator, exposure, rendered receipt,
    snapshot, part revision or inventory rejects with zero writes;
13. AST/caller registry accepts only repository `update_text`, rejects
    `apply_text_update`, D16's writer and direct supplemental writes;
14. migration apply/reapply proves revision-action alteration and ledger
    creation occur in safe order and any negative control leaves zero partial
    D23 schema/data; and
15. structural edits, Bundle edits and their exact replays create no confidence,
    judgment, adequacy, dataset, training or new learning-surface record.

## 8. Permissions, gates and stop conditions

Both public writers remain fixed-search-path `SECURITY DEFINER`, executable
only by `service_role`; `PUBLIC`, `anon` and `authenticated` have no execution.
The legacy ledger, part revisions and capability helpers are forced-RLS/RPC-
only or internal-only as applicable. All Bundle, rooting, PAM, serving,
collection, dataset, training, evaluation and promotion gates retain literal
disabled defaults. Every new record remains `serves_user=false` and
`dataset_eligible=false`.

Stop and request review if implementation would:

- forbid all structural editing despite a valid unlocked/unrooted inventory,
  or allow structural change to a protected part;
- let ordinary CAS lock/unlock, retain stale root coordinates after text
  change, or bypass lock position 100;
- include current revision/hash in a legacy operation key, or replay an old
  desired state after an intervening edit;
- accept Bundle replacement wording, target part, locator coordinates or
  subject kind from the browser;
- use any Bundle repository method other than `update_text`;
- split notes/parts/revisions across transactions or tolerate partial success;
- change `user_text_version` into an edit counter, transport bigint as JSON
  number, weaken the owner revision+hash CAS, or reorder D11 locks;
- weaken D20–D22 authority, deletion, blindness, currentness, RLS, non-serving
  or non-learning boundaries;
- change a disabled gate; or
- number, commit, push, merge, deploy, activate or collect without separate
  authorization.

`VERDICT: D23 PROPOSED FOR PRODUCT, ML/DATA AND ENGINEERING REVIEW; EXECUTABLE WORK BLOCKED`
