# MLC-3 Confident Moment Coaching Bundle — Transport Closure Amendment D25

Status: proposed final within-position-100 lock-order closure; executable work
remains blocked pending independent Product, ML/data and Engineering acceptance.

## 1. Parent and sole supersession

D25 binds and narrowly supersedes:

```text
MLC3-CONFIDENT-MOMENT-COACHING-TRANSPORT-CLOSURE-AMENDMENT-D24.md
SHA-256 54014be98f58ccf50420710c0959aaae67ba90dfda6c46e260037a09afdcd5a0
```

D24 and all accepted parents remain authoritative. D25 changes only the
within-position-100 acquisition order. It does not add a global lock position,
change any lock identity, alter revision-head semantics, or weaken atomicity,
authorization, deletion, blindness, RLS, non-learning or disabled-gate rules.

## 2. Exact within-position-100 order

After all applicable D11 positions below 100 have been acquired, an operation
must derive its complete applicable position-100 lock inventory under the
already-held coarse inventory serializers. It then acquires **all** locks in
the following three phases. A phase must finish before the next begins.

### 2.1 Phase 100-A — all root-block serializers

Acquire every applicable:

```text
root-block:<project_uuid>:<slide_index>:<block_key>
```

Sort its canonical tuple by:

1. Project UUID raw bytes ascending;
2. Slide integer ascending; and
3. exact normalized block-key UTF-8 bytes ascending.

Duplicate tuples collapse to one lock. No ideal-root-transition or part-head
lock may be acquired until the complete applicable root-block set is held.

### 2.2 Phase 100-B — all Ideal Text root-transition serializers

Acquire every applicable existing transition lock:

```text
ideal-root-transition:<p_idempotency_key>
```

The existing exact identity remains the validated canonical transition
`p_idempotency_key`; D25 does not reinterpret or broaden it. For an operation
that can invoke more than one canonical transition, derive the complete set
before locking, deduplicate it, and sort by the exact normalized idempotency-key
UTF-8 bytes ascending. The stored/advisory lock string must use those exact
bytes.

No part-revision-head lock may be acquired until the complete applicable
transition set is held. An internal transition helper called by a higher-level
writer must recognize that its required earlier root-block locks are already
held; it may not acquire a new root-block lock after entering phase 100-B.

### 2.3 Phase 100-C — all part-revision-head serializers

Acquire every applicable D24 lock:

```text
ideal-text-part-revision-head:<arc_id>:<owner_user_id>:<part_id>
```

Sort its canonical tuple by:

1. exact arc identifier UTF-8 bytes ascending;
2. authoritative owner UUID raw bytes ascending; and
3. part UUID raw bytes ascending.

Duplicate tuples collapse to one lock. Only after the complete part-head set is
held may the operation select latest revision IDs, lock rows, append revisions,
change parts/root metadata, or remove/recreate part rows.

### 2.4 Closed non-interleaving rule

The only legal position-100 sequence is:

```text
ALL 100-A root-block locks
  -> ALL 100-B ideal-root-transition locks
  -> ALL 100-C ideal-text-part-revision-head locks
```

Locks from different phases may never be interleaved. A writer may omit a
phase only when the mechanically derived applicable set for that phase is
empty. It may not acquire one part's three locks and then move to another part,
nor discover and acquire an earlier-phase lock after acquiring a later-phase
lock. If rederivation under the acquired sets changes any applicable identity,
the operation returns the accepted typed retry/stale result and performs no
mutation; it does not extend the set in place.

Within each phase, the exact sort above is mandatory across the complete set,
including multi-Project/shared-object operations. Browser order, desired part
order, database physical order, discovery order and hash-table order never
control lock order.

## 3. Writer and reader closure

Every ordinary CAS, Bundle Update-text, root/lock transition, deletion, purge,
retention, maintenance and migration writer that reads or changes any affected
root block, Ideal Text root transition, part, part head or part revision must:

1. derive every applicable 100-A/100-B/100-C identity from authoritative
   immutable lineage under D11's earlier coarse locks;
2. acquire the complete sets in D25 order;
3. rederive and hash the complete three-phase identity inventory;
4. fail typed retry/stale with zero writes on a mismatch; and
5. retain every acquired lock through final currentness revalidation and the
   transaction boundary.

This includes `compare_and_set_user_ideal_edit_v1`,
`apply_confident_moment_bundle_text_update_v1`,
`transition_ideal_text_root_state_v1`, its retained higher-level root adapters,
all registered part/root deletion paths and every maintenance writer. A writer
that cannot obey all phases is retired from runtime reachability or protected
by a writer-shared trigger that rejects the mutation.

Operations touching the same part are mutually exclusive at 100-C regardless
of whether they edit text, append the first/latest revision, root, lock,
remove, delete or maintain it. Root-affecting operations also share the exact
100-A block and 100-B transition locks where applicable. D25 therefore does
not rely on row locks alone for a missing revision row or concurrently removed
part.

Read projections that must prove root/part currentness use the same applicable
phases and ordering. A read-only lookalike lock remains prohibited.

## 4. Registry and lock-graph wording

D24's singular “position-100 serializer” registry language is superseded by a
closed plural registry. For every affected public RPC, internal helper,
trigger, application/worker/operations caller and maintenance path, record:

- exact function signature or trigger identity;
- the complete derivation rule for each applicable 100-A, 100-B and 100-C set;
- exact lock string template for every non-empty phase;
- exact canonical tuple and comparator;
- explicit `100-A -> 100-B -> 100-C` phase order;
- whether an empty phase is valid for that operation;
- post-lock identity-set rehash/current-leaf checks; and
- rewrite, shared-helper, trigger-guard or retirement disposition.

Static SQL/body inspection plus an executable lock-graph audit must fail on a
missing writer, singular-first-part locking, phase interleaving, wrong tuple
sort, late earlier-phase discovery, a different serializer string, or a call
edge that causes a callee to acquire an earlier phase after the caller has
entered a later one.

The shared internal lock helper may accept only server-derived typed arrays. It
must canonicalize, deduplicate and sort all three complete sets before taking
the first position-100 lock. It is inaccessible to `PUBLIC`, `anon`,
`authenticated` and `service_role` and cannot be satisfied or ordered by a
browser payload.

## 5. Required executable regressions

Retain every D20–D24 regression and add:

1. a multi-part ordinary CAS whose desired order is the reverse of UUID order
   acquires all 100-C locks by the frozen tuple, not browser/part order;
2. a multi-block/root operation derives all blocks first and acquires complete
   100-A, then complete 100-B, then complete 100-C sets;
3. crossed two-connection operations touching parts A+B and B+A complete
   without deadlock; one exact serialized result or typed stale loser is
   produced with no mixed document;
4. crossed root transition and multi-part CAS in both start orders share the
   same part exclusion and complete without deadlock or sibling heads;
5. crossed Bundle Update-text and root/lock transition in both start orders
   cannot combine old root state with new text or return a mixed projection;
6. deletion/maintenance touching multiple rooted parts follows the same three
   phases and cannot race a CAS into UUID reuse, post-tombstone revision or
   partial deletion;
7. rederivation that introduces a new earlier-phase block/transition/part
   returns typed retry/stale and acquires no late lock;
8. an explicit negative-control function using `100-C -> 100-A`, interleaving
   A/B/C per part, sorting by desired position, or locking only the first part
   fails the registry/lock-sequence audit;
9. audit captures the exact ordered lock trace for every registered affected
   writer and proves no call edge reverses phases; and
10. legacy null-head first-revision races and terminal tombstone tests remain
    green under the new complete-set acquisition.

Concurrency tests must use bounded waits and inspect both commit orders. A
timeout/deadlock is failure, not an acceptable retry result.

## 6. Permissions, gates and stop conditions

D24 permissions remain unchanged. Shared lock helpers remain internal; no
runtime role gains table writes or helper execution. All Bundle, rooting, PAM,
serving, collection, dataset, training, evaluation and promotion gates retain
literal disabled defaults. Every new record remains `serves_user=false` and
`dataset_eligible=false`.

Stop and request review if implementation would:

- interleave 100-A, 100-B and 100-C or acquire them in another phase order;
- lock per discovered part rather than deriving and sorting each complete set;
- sort by browser order, display position, locale text order or discovery order;
- acquire a newly discovered earlier-phase lock after entering a later phase;
- let a callee reverse the phase already established by its caller;
- omit any CAS, Bundle, root/lock, deletion or maintenance writer from the
  plural registry and executable lock trace;
- weaken D24 latest-ID/null-head/tombstone, D23 structural-edit/legacy replay,
  D22 atomicity, D11 global order, authority, deletion, blindness, RLS or
  non-learning boundaries;
- change a disabled gate; or
- number, commit, push, merge, deploy, activate or collect without separate
  authorization.

`VERDICT: D25 PROPOSED FOR PRODUCT, ML/DATA AND ENGINEERING REVIEW; EXECUTABLE WORK BLOCKED`
