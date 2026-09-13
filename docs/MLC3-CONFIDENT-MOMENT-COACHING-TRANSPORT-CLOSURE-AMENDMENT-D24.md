# MLC-3 Confident Moment Coaching Bundle — Transport Closure Amendment D24

Status: proposed final legacy-part revision-head closure; executable work
remains blocked pending independent Product, ML/data and Engineering acceptance.

## 1. Parent and narrow supersession

D24 binds and narrowly supersedes:

```text
MLC3-CONFIDENT-MOMENT-COACHING-TRANSPORT-CLOSURE-AMENDMENT-D23.md
SHA-256 2107d43ca16db72f97bb38ed385591cf36d876eea65cc10eab296a8e05760336
```

D23 and all of its accepted parents remain authoritative except where D24
clarifies legacy parts with no revision, freezes the executable part-revision
head rule, and pins the exact revision-schema extension. D23's atomic
text/parts persistence, structural-edit matrix, stable legacy operation ledger,
database-derived Bundle target/wording, D11 lock order, permissions, gates and
non-learning boundaries remain unchanged.

## 2. Existing parts may have no revision

An `ideal_text_part` created by the released legacy path may legitimately have
no row in `ideal_text_part_revision`. Absence is an explicit current state; it
is not projection corruption and must not make the Ideal Text unreadable.

### 2.1 Read and expected-current wire shapes

The D22 Ideal Text GET field is exactly:

```json
"current_part_revision_id": null
```

or a canonical positive base-10 bigint JSON string. `null` means that, under
the complete lock boundary, no revision exists for that exact owner/arc/part.
It never means that the application omitted a lookup.

The D23 ordinary-edit `expected_parts` item retains
`current_part_revision_id`, now explicitly nullable. The D23 Bundle
`expected_part_inventory` item adds:

```json
"current_part_revision_id": null
```

with the same string-or-null contract. Consequently
`p_expected_current_part_revision_id bigint` in the Bundle RPC is nullable and
must agree with the same target part's inventory member. A non-null expected
head when none exists, null when one exists, or disagreement between the scalar
and inventory rejects before mutation.

For every null assertion, PostgreSQL must prove no revision row exists after
acquiring the writer-shared head serializer in section 3. An application-side
null, missing field, failed read or empty list cannot substitute. The fields are
required even when their value is null.

### 2.2 First mutation of a legacy part

The first valid ordinary text/reorder/remove mutation or canonical root/lock
transition of a legacy no-revision part creates its first immutable revision.
Its `previous_revision_id` is null. The action and remaining conditional fields
must describe the real operation; no synthetic migration/backfill revision is
invented.

Concurrent attempts to create a first revision serialize on the same exact
head lock. One may append against null; the other must rederive the now-non-null
head and either operate against it under its own valid current request or fail
stale. Two sibling first revisions are impossible.

## 3. One executable part-revision head rule

### 3.1 No mutable head table

There is no new mutable part-revision head table. For an exact
`(arc_id, owner_user_id, part_id)`, the current head is:

```sql
SELECT id
FROM public.ideal_text_part_revision
WHERE arc_id = :arc_id
  AND user_id = :owner_user_id_text
  AND part_id = :part_id
ORDER BY id DESC
LIMIT 1;
```

The owner identity comparison follows the released column type exactly, while
the authoritative UUID owner is derived through immutable Project/principal
lineage. The highest `id` is authoritative only after the shared serializer
below is held. Zero rows means the exact null-head state.

### 3.2 Writer-shared serializer at lock position 100

After acquiring all applicable D11 coarse locks and before reading or changing
a part/revision, every reader or writer acquires, in sorted bytewise part-ID
order, the transaction-scoped advisory lock:

```text
ideal-text-part-revision-head:<arc_id>:<owner_user_id>:<part_id>
```

This is the canonical position-100 Ideal Text part/root serializer. It does not
add a second position or relax D11's complete numeric order. After acquiring
it, the operation selects the latest revision by descending ID, locks that row
when present, and rederives the latest ID before append/return. If discovery
changed, the accepted typed retry/stale path applies; it may not follow a newly
discovered unlocked part.

Every public RPC, internal helper, trigger and worker path capable of inserting
`ideal_text_part_revision`, changing `ideal_text_part`, changing its root/lock
metadata, or removing/recreating a part must use this exact serializer and
order. This includes the ordinary CAS, Bundle Update-text wrapper,
`transition_ideal_text_root_state_v1`, every retained legacy root adapter and
any maintenance/deletion writer. A path that cannot be rewritten to the shared
serializer is retired from runtime reachability or guarded by a BEFORE trigger
that rejects its mutation. A direct service-role insert into the revision table
or part mutation remains prohibited.

The signature/caller/trigger registry and lock-graph audit must mechanically
enumerate all such writers. An unknown writer blocks implementation.

### 3.3 Removed part terminality

`owner_part_removed` must be the latest revision when its transaction commits
and is permanently terminal for that UUID. Under the head serializer:

- the physical/current part row must be absent after removal;
- no subsequent revision action may reference that part ID;
- no part row with that UUID may be inserted again; and
- exact replay returns the stored tombstone rather than appending another.

The guard checks both current parts and all revision history, so deletion of a
current row cannot make its identity reusable.

## 4. Exact `ideal_text_part_revision` extension

The pending migration adds these nullable columns:

```sql
previous_revision_id      bigint null
  REFERENCES public.ideal_text_part_revision(id) ON DELETE RESTRICT,
owner_edit_revision       bigint null,
previous_position         integer null,
result_position           integer null,
owner_edit_operation_id   uuid null
  REFERENCES public.ideal_text_user_edit_cas_operations(id)
  ON DELETE RESTRICT,
revision_contract_version text null
```

`owner_edit_revision` is the exact resulting `user_text_revision` of the
ordinary/Bundle owner-edit operation. The referenced
`ideal_text_user_edit_cas_operations` ledger is D23's immutable, forced-RLS,
RPC-only operation ledger and has UUID primary key `id`. Bundle operations also
receive a ledger operation row so the same FK is never a polymorphic or
unverified text reference.

### 4.1 Complete action vocabulary

Retain all six released actions unchanged:

```text
user_edit
lock
unlock
keep_evolving
root_set
root_skipped
```

Add exactly D23's five actions:

```text
owner_part_created
owner_part_text_updated
owner_part_reordered
owner_part_text_updated_and_reordered
owner_part_removed
```

No other value is legal.

### 4.2 New-action constraints

Every five-action D23 row requires:

- `revision_contract_version = 'ideal-text-part-revision-v2'`;
- `owner_edit_revision > 0`;
- non-null `owner_edit_operation_id` resolving to the same owner/arc/source
  operation;
- `previous_revision_id` equal to the exact locked prior head, or null only
  when the locked prior head is absent; and
- identity/text/position fields matching the exact before/result part state.

The per-action matrix is:

| Action | Previous position | Result position | Additional invariant |
| --- | --- | --- | --- |
| `owner_part_created` | null | non-negative | prior head absent; UUID never used |
| `owner_part_text_updated` | non-negative | same value | exact text changes |
| `owner_part_reordered` | non-negative | different non-negative | text byte-identical |
| `owner_part_text_updated_and_reordered` | non-negative | different non-negative | exact text changes |
| `owner_part_removed` | non-negative | null | terminal tombstone; final text retained |

All non-null positions must fit the complete consecutive result/previous
inventory as applicable. An action that does not match its actual before/after
state rejects the whole transaction.

### 4.3 Historical and mixed lineage

All pre-D24 rows and retained six-action legacy writers keep the five new
columns null unless a separately accepted contract already populated an exact
compatible field. The migration does not rewrite history or manufacture
parentage. These historical/legacy actions never appear in a D23 owner-edit
operation's `part_revisions` response.

A new D23 action may follow a historical six-action head: it records that
head's ID in `previous_revision_id` and supplies all new v2 fields. A legacy
part with no history uses null. Once a v2 owner-edit action exists for a part,
all later owner-edit structural actions use v2 and chain exactly; a retained
canonical root transition may append its accepted legacy action only while
holding the same head serializer, after which the next v2 row points to that
actual latest legacy-action ID. Thus mixed history has one linear latest-ID
chain without reinterpreting old facts.

## 5. Bundle and ordinary exactness updates

The ordinary and Bundle routes/repositories transport required nullable
revision heads without coercion. JavaScript/Python may not convert bigint
strings to floating-point numbers. The database-derived Bundle target remains
the only target: its nullable scalar expected revision is merely exact stale-
state evidence and must match its inventory entry.

D23's atomic persistence remains unchanged: changing a legacy part with no
head creates the first exact changed-part revision in the same transaction as
the owner text/parts/CAS result. A failure or race rolls back all state.

An old legacy desired operation replayed after any intervening edit returns
`IDEAL_TEXT_LEGACY_REPLAY_CONFLICT`. The product response requires the client
to refetch the closed Ideal Text GET and explicitly resubmit the intended edit
using the current revision, hash and full expected/desired inventory. The
server never silently rebases or reapplies the old desired state.

## 6. Migration order and apply/reapply

D22/D23's migration order remains mandatory, with this exact placement:

1. create the immutable CAS operation ledger;
2. add the nullable part-revision columns and extend the action constraint;
3. add their conditional integrity constraints and terminal-ID guards;
4. add/replace shared position-100 serializer helpers and rewrite/guard every
   registered affected writer;
5. add and initialize `user_text_revision` as D22 requires;
6. create ordinary/Bundle wrappers and private capabilities;
7. install owner-lane and part/revision BEFORE guards only after initialization;
8. run registry, permissions, invariant and lock-graph closure; and
9. reload PostgREST and commit.

Apply/reapply never backfills synthetic part revisions, never duplicates a
ledger/revision/tombstone, and preserves every old action row byte-identically.
Any missing writer classification, invalid partial new row, terminal UUID reuse
or negative control rolls the complete migration back.

## 7. Required executable regressions

Retain every D20–D23 regression and add:

1. GET returns a legacy existing part with required
   `current_part_revision_id=null`; ordinary and Bundle expected inventories
   accept exact null only after proving no row exists;
2. wrong null/non-null, missing revision field and scalar/inventory mismatch
   reject with zero writes;
3. first text change, reorder, removal and canonical root/lock transition from
   a no-revision legacy part each create exactly one correct first revision;
4. forced two-connection first-revision races in both start orders produce one
   linear head chain or one success plus typed stale failure—never sibling
   first heads, duplicates, partial text or deadlock;
5. latest-ID derivation sees retained six-action history, null history and mixed
   legacy→v2→legacy→v2 history correctly under the serializer;
6. every affected writer is mechanically registered and uses the exact
   position-100 lock string/order; an unregistered/direct writer and a writer
   using a different lock fail closure;
7. every old action remains accepted with its historical null extension fields
   and is excluded from D23 operation responses;
8. every new action satisfies its exact parent, operation, owner revision,
   contract version and position matrix; each malformed combination rolls back;
9. removal commits one latest terminal tombstone; exact replay returns it;
   UUID reuse, later revision, concurrent recreate and root sourcing all fail;
10. interrupted apply and reapply preserve old histories, create no synthetic
    revision and expose no interval in which an unguarded writer can fork the
    chain; and
11. after an intervening edit, a legacy replay returns conflict; a fresh GET
    followed by an explicit current-CAS resubmission succeeds as a new operation
    without mutating either historical result.

## 8. Permissions, gates and stop conditions

All D23 permissions remain: public writers are fixed-search-path
`SECURITY DEFINER` and executable only by `service_role`; revision/operation
tables are forced-RLS and RPC-only; private serializers/capabilities are not
runtime-executable. Existing historical rows remain evidence, not labels.

All Bundle, rooting, PAM, serving, collection, dataset, training, evaluation
and promotion gates retain literal disabled defaults. Every new record remains
`serves_user=false` and `dataset_eligible=false`.

Stop and request review if implementation would:

- require a synthetic revision for a released part with no revision;
- treat a missing/failed revision lookup as proven null;
- introduce a mutable head table or select latest ID without the shared lock;
- permit any affected writer to bypass the exact position-100 serializer;
- rewrite historical action rows or include them in a new operation response;
- omit any pinned revision column/FK/conditional action invariant;
- append after `owner_part_removed`, reuse its UUID or create sibling heads;
- silently rebase a conflicting legacy replay instead of requiring refetch and
  explicit current-CAS resubmission;
- weaken D23 atomicity, database-derived Bundle target, owner CAS, D11 order,
  authority, deletion, blindness, RLS or non-learning boundaries;
- change a disabled gate; or
- number, commit, push, merge, deploy, activate or collect without separate
  authorization.

`VERDICT: D24 PROPOSED FOR PRODUCT, ML/DATA AND ENGINEERING REVIEW; EXECUTABLE WORK BLOCKED`
