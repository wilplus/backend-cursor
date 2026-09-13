# MLC-3 Confident Moment Coaching Bundle — Transport Closure Amendment D18

Status: proposed interface amendment; executable work remains blocked pending
independent Product and ML/data acceptance.

## 1. Frozen parents and narrow supersession

D18 binds the exact final documents:

```text
MLC3-CONFIDENT-MOMENT-COACHING-TRANSPORT-CLOSURE-AMENDMENT-D16.md
SHA-256 a24f4e44af99f7b7334428c051cc079a75e506f77cfe34c03e8dc26a63a63176

MLC3-CONFIDENT-MOMENT-COACHING-TRANSPORT-CLOSURE-AMENDMENT-D17.md
SHA-256 45017febb2afd674c6722e42cd25d90be85b8c137ed13b00b8a7a1ff041e961a
```

D17 remains authoritative except where D18 explicitly supersedes:

1. D17 sections 2.3–2.6 for snapshot behavior, replacement coordinates and a
   byte-identical accepted Rephrase;
2. D17 sections 4.1–4.5 and D11 section 4.3 for exact blind-assignment coverage
   and per-attachment coach-authoring authority;
3. D17 section 5's abbreviated lock ordering; and
4. the corresponding regressions and stop conditions.

All other accepted D3/D11/D12/D13/D14/D15/D16/D17 clauses remain in force.
D18 creates no new Manager item, confidence meaning, learning label, assignment
system, dataset release, or serving activation.

## 2. Bundle text update does not advance the Feedback V3 document head

### 2.1 Atomic result and snapshot identity

`apply_confident_moment_bundle_text_update_v1` still changes the one exact
target Ideal Text part, appends exactly one immutable
`ideal_text_part_revision`, and inserts exactly one immutable
`confident_moment_bundle_text_update_bindings` row in a single transaction.

That transaction must **not** publish a new canonical Feedback V3 document
snapshot, advance `ideal_text_document_generations`, replace the current
`ideal_text_document_snapshots` head, or mutate the immutable source snapshot.
The binding's `result_document_snapshot_id` is exactly its
`source_document_snapshot_id`, and both equal the Bundle's frozen snapshot.

The owner Ideal Text part revision is an overlay result bound back to the
frozen Bundle source. It is not a regenerated Feedback V3 input. Consequently,
the update does not invalidate its own Bundle, family response, render receipt,
text-update binding, projection replay, or immediately following root action.
Those operations remain current while the same Feedback V3 snapshot/head is
current and every other authority/deletion/currentness leaf remains live.

Only an ordinary later F1 operation that independently publishes a successor
Feedback V3 document snapshot/head makes the old Bundle and binding unavailable
for new replay/root use. Historical rows remain immutable.

### 2.2 Writer/trigger boundary

The Bundle text-update RPC must use one reviewed writer path that updates the
canonical owner Ideal Text part while suppressing only the Feedback V3
generation/head advance caused by this exact transaction. The suppression is
internal to `apply_confident_moment_bundle_text_update_v1`; no public request,
browser value, direct table write or general user-edit caller may select it.

Every affected document-generation trigger/writer is included in the D11 closed
registry and must prove:

- the suppression is reachable only inside the exact Bundle wrapper;
- it applies only to the one validated target part mutation;
- it cannot suppress an ordinary F1 publication or non-Bundle edit;
- the part revision and binding exist before successful return; and
- transaction rollback restores both the Ideal Text part and every head state.

The binding row stores the same source/result snapshot ID. Any row with unequal
snapshot IDs fails its structural constraint.

### 2.3 Corrected response

The D17 update response remains closed, but the snapshot field has this exact
meaning:

```json
{
  "text_update_contract_version": "confident-moment-bundle-text-update-v1",
  "bundle_id": "uuid",
  "bundle_attachment_id": "uuid",
  "text_update_binding_id": "uuid",
  "correction_decision_id": "uuid",
  "feedback_exposure_id": "uuid",
  "render_receipt_id": "uuid",
  "target_part_id": "uuid",
  "result_part_revision_id": "9007199254740993",
  "result_document_snapshot_id": "uuid",
  "before_part_inventory_sha256": "64-lowercase-hex",
  "after_part_inventory_sha256": "64-lowercase-hex",
  "dataset_eligible": false
}
```

`result_document_snapshot_id` must equal the request's
`expected_document_snapshot_id`, the Bundle snapshot and the binding's source
snapshot. It is not evidence that a new snapshot was created.

## 3. Exact replacement coordinates come only from the Ideal Text locator

### 3.1 Required locator contract

For a Bundle `rewrite_clarity` attachment that may support Update-text, its
exact `evidence_spans.target_locator` must be a closed object:

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

No missing or extra key is allowed. `start` and `end` are zero-based,
end-exclusive Unicode scalar-value positions in the exact frozen served Ideal
Text surface. They are finite non-negative JSON integers, never booleans;
`end > start`. No Unicode normalization, whitespace normalization, HTML
stripping, case folding or punctuation repair occurs during verification.

The database must prove all of the following under the document and part locks:

1. `version` is exactly `ideal-text-target-locator-v1`;
2. `surface` is exactly `ideal_text`;
3. `surface_hash` equals the SHA-256 of the exact frozen snapshot Ideal Text
   UTF-8 bytes;
4. slicing that frozen surface at `[start,end)` yields `exact_text` byte-for-
   byte after UTF-8 encoding;
5. the current exact ordered Ideal Text parts join with the canonical `\n\n`
   separator to the same source surface used by the Bundle;
6. the range lies wholly inside the Bundle target part; and
7. the target part ID is the exact Bundle paragraph ID.

`evidence_spans.start_char` and `evidence_spans.end_char` describe transcript
evidence and are never used, copied or treated as Ideal Text replacement
coordinates.

### 3.2 Deterministic global-to-local conversion

Let each non-empty current part retain its exact stored text. The global start
of part `i` is:

```text
sum(Unicode-scalar length of each preceding part text)
+ 2 for each preceding canonical "\n\n" separator
```

For the unique target part:

```text
local_start = target_locator.start - target_part_global_start
local_end   = target_locator.end   - target_part_global_start
```

The operation requires:

```text
0 <= local_start < local_end <= Unicode-scalar length(target_part.text)
```

PostgreSQL replacement uses its one-based character substring position
`local_start + 1` and length `local_end - local_start`. The preserved prefix is
the exact target-part slice `[0,local_start)` and the preserved suffix is
`[local_end,part_length)`. Only the middle range is replaced with the exact
accepted Rephrase. The final byte-level before/after inventory checks from D17
remain mandatory.

Invalid version, surface/hash, range, exact text, part containment or
global-to-local conversion returns typed
`CONFIDENT_MOMENT_TEXT_TARGET_INVALID` and writes nothing. The implementation
may not search for matching text, choose among repeated strings, use transcript
coordinates, or clamp/repair a range.

The locator object, its canonical hash and the derived local coordinates are
stored in the text-update binding hash and exact replay identity.

## 4. D11 section 4.3: complete distinct-evidence blind batch

This section explicitly replaces D11 section 4.3 for Confident Moment Bundle
coach authority.

### 4.1 Canonical assignment inventory

Before any Bundle coach wording is revealed or authored, the canonical blind
batch must contain one `ml_review_assignment` for every **distinct exact source
audio/evidence identity** required by the selected Bundle subjects and
attachments in that batch revision.

The exact deduplication key is the immutable tuple:

```text
acquisition_principal_id
+ Project + source Take
+ feedback membership
+ evidence_span_id + evidence_hash
+ recording/audio lineage ID + exact audio SHA-256
+ start_ms + end_ms
+ target-speaker binding revision where required
+ blind packet policy/version
```

Two Bundle subjects/attachments with the identical complete tuple share one
assignment. A difference in any tuple member requires a separate assignment.
Text similarity, shared snippet, same Slide, same candidate family, overlapping
interval, same Bundle, or same recording alone never deduplicates evidence.

The inventory includes:

- each `confidence_anchor` subject's exact source audio/evidence;
- each `no_anchor_paragraph_trigger` subject's exact source audio/evidence; and
- each selected sibling attachment whose product wording may be edited and
  whose source audio/evidence identity differs from every assignment already in
  the batch.

No-anchor status does not permit an approximate or unrelated confidence clip.

The complete-batch blindness rule remains absolute: every required assignment
in the frozen batch revision must have one independently rendered, immutable
blind-coach judgment before reveal. One unanswered required assignment keeps
all Bundle transcript, wording and authoring context hidden.

### 4.2 Assignment-to-Bundle binding table

Add one immutable, append-only, forced-RLS, RPC-only table:

```text
confident_moment_blind_assignment_bindings
```

Each row binds at least:

```text
id uuid primary key
review_batch_id uuid
review_assignment_id uuid
blind_packet_id uuid
audio_lineage_id uuid
audio_sha256 text
evidence_span_id uuid
evidence_hash text
acquisition_principal_id uuid
project_id uuid
source_take_id uuid
feedback_membership_id uuid
bundle_id uuid
bundle_attachment_id uuid
binding_role text
assignment_identity_sha256 text
binding_sha256 text
created_at timestamptz
serves_user boolean default false check (not serves_user)
dataset_eligible boolean default false check (not dataset_eligible)
```

`binding_role` is exactly `bundle_subject` or `bundle_attachment`. Composite
foreign keys bind the batch/assignment/packet/audio/evidence and exact Bundle/
attachment/membership/Take lineage. One assignment may have multiple binding
rows only when every row has the identical complete deduplication tuple.
Every selected subject/attachment requiring coach wording must have exactly one
binding row in the frozen batch revision.

The database derives and freezes this mapping when it freezes the canonical
batch. It does not create a parallel assignment or judgment system. Existing
`ml_review_assignments`, blind packets, presentations, rendered exposures,
`ml_judgments`, complete-batch reveal and reveal access remain the only review
chain.

`PUBLIC`, `anon`, `authenticated` and `service_role` have no direct table
writes. Only the reviewed batch-freeze wrapper may insert rows. UPDATE and
DELETE are rejected. The table and every source edge join deletion traversal.

### 4.3 Per-attachment authoring authority

Post-reveal coach authoring for a Bundle attachment requires the exact
`confident_moment_blind_assignment_bindings` row for that attachment and the
exact revealed assignment/judgment named by that row. The atomic coach RPC
derives `blind_judgment_id`; the browser never sends it.

The source judgment means only the blind coach's confidence answer for that
exact assignment audio/evidence. It authorizes post-reveal product wording for
the bound attachment under the D17 family/output matrix, but it does not become
a confidence, correction-quality, praise-quality, adequacy, effectiveness or
training label for that attachment. The attachment never inherits another
assignment's evidence or judgment meaning.

Where two sibling attachments have different evidence identities, each must
use its own assignment/binding/judgment. Where their exact complete identities
match, they may share the one assignment but retain separate Bundle-attachment
binding rows and separately authored wording revisions.

The coach context returns, for every authorized target, its exact
`review_assignment_id`, `reveal_access_id` and Bundle attachment identity. It
does not expose the judgment ID or value. The authoring request must echo the
target's assignment/access identities; the database proves they equal its
binding. A source assignment bound only to attachment A cannot authorize B.

The D17 family/output matrix and immutable
`confident_moment_coach_wording_authority_bindings` remain, but each authority
row now points to the exact assignment-binding row for its target. The former
assumption that one source assignment authorizes every same-Bundle sibling is
removed.

### 4.4 Closed coach context adjustment

Each item in `authorized_targets` adds its exact assignment identities:

```json
{
  "bundle_attachment_id": "uuid",
  "review_assignment_id": "uuid",
  "reveal_access_id": "uuid",
  "feedback_family": "confident_voice|rewrite_clarity|great_formulation",
  "allowed_output_kind": "comment|rephrase",
  "allowed_comment_purpose": null,
  "source_passage": {
    "evidence_span_id": "uuid",
    "text": "exact selected passage",
    "text_sha256": "64-lowercase-hex"
  },
  "expected_current_revision_id": null,
  "expected_current_delivery_id": null
}
```

Targets remain in canonical Bundle attachment order. The complete context is
absent before complete-batch reveal. The browser cannot substitute assignment
or access identities between targets.

## 5. Lock order: D11 governs; D18 only adds serializers

D17 section 5's prose list is not a replacement or renumbering of the global
lock graph. D11 section 2 remains the full authoritative numeric order:

```text
10 rollout policy
20 acquisition principal
30 Project inventory
40 Take inventory
50 membership inventory
51 current membership
52 document head
53 document snapshot
60 speaker attempt
70 processing audio object
90 Bundle subject
100 root block
110 Feedback Language candidate/reviewer
120 Feedback Language delivery subject
130 Feedback Language revision head
140 exact current validity/head row locks
```

All existing positions, including every applicable 60, 70 and 100 serializer,
must be acquired. Coach revision/delivery operations preserve **110 before 120
before 130** exactly. D18 does not compress, reorder or omit any D11 position.

D18 adds the following fine serializers within the existing graph:

| Position | Addition |
| ---: | --- |
| 53 | exact ordered Ideal Text part-inventory identity under the already-held document snapshot serializer |
| 90 | exact Bundle attachment and blind-assignment-binding sets, sorted by UUID bytes, under the Bundle subject serializer |
| 110 | exact text-update decision/exposure/render tuple and exact per-target assignment-authority binding |
| 140 | target part revision, text-update binding, assignment-binding and coach-authority-binding rows in canonical row-lock order |

For root creation the applicable order still includes 100. For source/practice
or audio validity it still includes 60 then 70 before 90/100. For coach wording
it includes 110 then 120 then 130, followed by 140. Every reader, batch freezer,
text writer, root writer, coach writer, deletion/purge writer and validity writer
uses the same applicable order.

Identity sets are derived under coarse locks, canonically hashed, fine-locked,
rederived and compared exactly as D11/A3 require. A changed set produces only
the existing typed retry; it may not follow a newly discovered unlocked leaf.

## 6. Byte-identical accepted Rephrase

If the exact accepted Rephrase is byte-identical to the current target range,
`apply_confident_moment_bundle_text_update_v1` returns the typed no-change
result and creates **no** Ideal Text edit, part revision, document generation,
snapshot or `confident_moment_bundle_text_update_bindings` row.

No revision may be fabricated merely to let the user save a root.

The user may still root the unchanged current wording only through an explicit
owner selection using the manual/current-part path, and only when an exact live
current `ideal_text_part_revision.id` already exists for that same target part,
text bytes, owner, Project and current document lineage. In that case:

- the UI leaves the text unchanged;
- it explains no technical state and treats Update as already reflected;
- **Save the text** remains an explicit separate user action;
- the root request uses that existing revision as
  `source_ideal_text_revision_id`;
- `source_text_update_binding_id` is null; and
- the database records the root as explicit owner-selected current wording,
  not accepted-Rephrase update provenance.

If no exact live current part revision already exists, **Save the text** is not
shown or is disabled for this no-change branch. Cancel remains available and
writes nothing. The browser may not create a revision, silently save, fall back
to transcript provenance, or use document version as a part revision.

The D17 accepted-Rephrase root path continues to require both the non-null
text-update binding and its exact resulting part revision whenever actual text
changed.

## 7. Required regressions

### 7.1 Snapshot and self-currentness

1. A successful Bundle text update changes one target part, creates one part
   revision and one binding, while document-generation and Feedback V3 snapshot
   head remain byte-identical.
2. Binding source/result snapshot IDs are equal by constraint.
3. Exact update replay and immediate root use remain valid after the update.
4. An ordinary later F1 successor snapshot makes old update replay/root use fail
   closed without mutating history.
5. Rollback leaves part, revision, binding, generation and snapshot head wholly
   unchanged.
6. The internal suppression cannot be selected by a browser, service-role table
   write, non-Bundle edit or ordinary F1 writer.

### 7.2 Locator and one-part replacement

1. Golden fixtures cover ASCII, multi-byte Unicode, combining characters,
   repeated target text and separators before the target part.
2. Global-to-local conversion changes exactly the locator range wholly inside
   the exact target part.
3. Transcript `start_char/end_char` deliberately differ from the Ideal Text
   locator and are ignored.
4. Missing/wrong locator version, surface, surface hash, range, exact text,
   target part or cross-part range rejects with zero writes.
5. No text search, occurrence choice, normalization, clamp or repair is used.
6. Non-target IDs, text bytes, order and locks remain identical; add/remove/
   reorder/remint/lock-change attempts reject.

### 7.3 Distinct-evidence blind inventory

1. Two selected same-Bundle siblings with the exact same complete source
   evidence/audio tuple create one assignment and two assignment-binding rows.
2. Two selected same-Bundle siblings with **different** evidence spans or audio
   lineage create two assignments; one judgment cannot authorize both.
3. Different evidence in one shared snippet still requires distinct assignments.
4. A no-anchor correction subject receives its own exact assignment/binding.
5. Incomplete judgment of any required distinct assignment keeps all reveal and
   authoring closed.
6. After complete reveal, each attachment authoring request succeeds only with
   its exact assignment/access binding. Cross-target substitution rejects.
7. Batch retry reproduces the exact deduplicated set/order/hash; late/extra/
   omitted/foreign bindings reject.
8. No parallel review assignment, judgment, exposure or reveal system is
   created, and sibling output inherits no confidence judgment or label.

### 7.4 Lock graph and contention

1. Static and database audits prove the complete D11 numeric graph, not D17's
   abbreviated list, on every affected reader/writer/trigger/worker.
2. Required operations preserve 60→70→90→100 and 110→120→130 ordering where
   applicable.
3. Two-connection tests cover update versus F1 snapshot successor, batch freeze
   versus Bundle/evidence change, per-target coach write versus assignment/
   reveal invalidation, root versus text binding, and deletion/purge in both
   commit orders without deadlock or mixed state.

### 7.5 Byte-identical Rephrase

1. Byte-identical accepted text creates zero edit/revision/binding/snapshot row.
2. With an already-live exact matching part revision, Save appears only as an
   explicit second action and records manual/current-part owner selection with
   null text-update binding.
3. Without such a revision, Save is absent/disabled and no request/write occurs.
4. A stale, foreign, text-mismatched or document-version value cannot substitute
   for the exact part revision.

All D16/D17 forced-RLS, append-only, exact grant, caller-registry, deletion,
atomic rollback, recursively closed JSON, bigint-string, disabled-gate and zero-
fabricated-learning regressions remain mandatory.

## 8. Permissions, deletion and learning fences

`confident_moment_bundle_text_update_bindings`,
`confident_moment_blind_assignment_bindings` and
`confident_moment_coach_wording_authority_bindings` are append-only, enable and
force RLS, and have no direct runtime writes. Only reviewed `SECURITY DEFINER`,
fixed-search-path wrappers are executable by `service_role`; `PUBLIC`, `anon`
and `authenticated` receive no execution.

Every source and result identity joins deletion traversal and current authority,
retention, purge and media validation. Physical deletion invalidates new use
without rewriting immutable history.

`CONFIDENT_MOMENT_BUNDLE_V1_ENABLED`, `ROOTING_COVERAGE_V1_ENABLED`, every PAM
gate and every serving/collection/dataset/training/evaluation/promotion gate
retain their exact disabled defaults. All new bindings remain structurally
`serves_user=false` and `dataset_eligible=false`.

## 9. Stop conditions

Stop and request ML/data interface review if implementation would:

- publish or advance a Feedback V3 document snapshot/head from Bundle
  Update-text, or invalidate that operation with its own write;
- mutate an immutable source snapshot;
- use transcript offsets, text search, normalization or browser coordinates in
  place of the exact versioned Ideal Text locator;
- replace a range crossing part boundaries or alter a non-target part/lock;
- freeze fewer or more than one assignment per distinct complete evidence/audio
  identity;
- omit no-anchor subjects or differently evidenced sibling attachments from the
  required blind batch;
- let one attachment use another attachment's assignment/access when their
  evidence differs;
- transfer a blind confidence judgment's meaning to sibling wording or create a
  new assignment/judgment/learning surface;
- use D17's abbreviated lock prose instead of every applicable D11 numeric
  position, or change 110→120→130;
- fabricate a part revision/binding for byte-identical text;
- make Save available in the no-change branch without an existing exact live
  current part revision and an explicit owner action;
- weaken any accepted blindness, authority, deletion, RLS/RPC-only, Manager-
  budget, non-serving, dataset or disabled-gate boundary; or
- number, commit, push, merge, deploy, activate or collect without separate
  authorization.

`VERDICT: D18 PROPOSED FOR PRODUCT AND ML/DATA INTERFACE REVIEW; EXECUTABLE WORK BLOCKED`
