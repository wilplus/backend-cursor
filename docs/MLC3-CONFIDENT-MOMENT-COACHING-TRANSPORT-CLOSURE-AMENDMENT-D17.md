# MLC-3 Confident Moment Coaching Bundle — Transport Closure Amendment D17

Status: proposed interface amendment; executable work remains blocked pending
independent Product and ML/data acceptance.

## 1. Parent and narrow supersession

D17 is bound to and narrowly supersedes the final D16 document:

```text
MLC3-CONFIDENT-MOMENT-COACHING-TRANSPORT-CLOSURE-AMENDMENT-D16.md
SHA-256 a24f4e44af99f7b7334428c051cc079a75e506f77cfe34c03e8dc26a63a63176
```

D16 remains authoritative except where D17 explicitly replaces:

1. D16 sections 3–4 for a Bundle-origin `Update the text` and its later root;
2. D16 section 5's one-assignment/one-attachment coach-authoring rule; and
3. the associated D16 request, response, persistence and regression clauses.

D17 does not amend the D3 Manager budget, Feedback V3 families, user-response
meaning, blindness, root qualification, exercise matching, dataset eligibility,
learning-surface registry, or any disabled gate.

## 2. Bundle text update is one exact bound transaction

### 2.1 Sole Bundle update route

A Bundle-origin **Update the text** does not use the compatibility branch of the
general Ideal Text edit route. It uses this sole Bundle adapter:

```http
POST /v2/user/confident-moment-bundles/{bundle_id}/attachments/{bundle_attachment_id}/update-text
```

The sole application caller is:

```text
services/confident_moment_bundle_repository.py::ConfidentMomentBundleRepository.update_text
  -> apply_confident_moment_bundle_text_update_v1
```

This is an adapter into the canonical Ideal Text store, not a second document
lane. It changes the same owner Ideal Text and creates the same canonical
`ideal_text_part_revision` identity. The existing non-Bundle
`PUT /v2/explore/arc/{arc_id}/ideal-text/user-edit` route and its behavior remain
unchanged and cannot produce a Bundle text-update binding.

### 2.2 Exact request

The Bundle update body is recursively closed and has exactly:

```json
{
  "correction_decision_id": "uuid",
  "feedback_exposure_id": "uuid",
  "render_receipt_id": "uuid",
  "expected_document_snapshot_id": "uuid",
  "expected_document_version": 1,
  "expected_part_inventory": [
    {
      "part_id": "uuid",
      "text_sha256": "64-lowercase-hex",
      "locked": false
    }
  ],
  "idempotency_key": "non-empty-string"
}
```

`expected_part_inventory` is the complete exact current ordered part-ID
inventory seen by the user. Array position is canonical order. It must contain
every current part exactly once. UUIDs must be canonical lowercase strings,
hashes must be lowercase SHA-256, booleans are literal booleans, and no extra
top-level or nested key is accepted.

The client does not send replacement text, whole-document text, target part ID,
part revision ID, Project, Take, owner, membership, candidate, family,
correction output, lock timestamp, or order number. The database derives all of
them from the exact Bundle, attachment, decision, exposure, render receipt and
current Ideal Text lineage. This prevents the browser from applying wording
other than the exact accepted Rephrase.

### 2.3 Exact RPC

```text
apply_confident_moment_bundle_text_update_v1(
  p_acquisition_principal_id uuid,
  p_bundle_id uuid,
  p_bundle_attachment_id uuid,
  p_correction_decision_id uuid,
  p_feedback_exposure_id uuid,
  p_render_receipt_id uuid,
  p_expected_document_snapshot_id uuid,
  p_expected_document_version integer,
  p_expected_part_inventory jsonb,
  p_idempotency_key text
) -> jsonb
```

The function is `SECURITY DEFINER`, has a fixed `search_path`, and is executable
only by `service_role`. It:

1. validates the exact acquisition principal and D4 service authority;
2. loads the exact Bundle and `rewrite_clarity` attachment;
3. proves the attachment belongs to the exact current Project, source Take,
   membership and document snapshot;
4. proves `correction_decision_id` is `accept_proposed` by this owner for the
   attachment's exact candidate, evidence, output hash and exposure;
5. proves the D15 render receipt belongs to that same attachment, exposure,
   principal and visible render;
6. acquires the D11 serializer order for rollout/principal, Project/Take,
   document inventory, attachment, exposure/render, decision and part heads;
7. under those locks revalidates every identity and the complete ordered part
   inventory before any write;
8. derives the target part and exact source-passage coordinates solely from
   the Bundle attachment/evidence lineage, and derives the replacement solely
   from the accepted exact Rephrase output;
9. replaces only that exact source passage inside the target part in the
   canonical owner Ideal Text;
10. appends exactly one immutable `ideal_text_part_revision` for that target;
11. publishes the corresponding exact document generation/snapshot; and
12. persists exactly one immutable text-update binding from the source facts to
    that resulting revision and snapshot in the same transaction.

Any failure rolls back the document, part revision, snapshot and binding.

### 2.4 Exact single-part mutation rule

The database recomputes the current ordered inventory as canonical JSON over:

```text
array position + part_id + UTF-8 text SHA-256 + exact locked boolean
```

It must equal `p_expected_part_inventory` byte-for-byte after canonical JSON
serialization. The target Bundle paragraph must appear exactly once.

The resulting inventory must satisfy all of the following:

- its length is unchanged;
- every part ID is unchanged and remains at the same array position;
- every non-target part's text bytes and text hash are unchanged;
- every byte of the target part outside the exact frozen source-passage range
  is unchanged, and only that range becomes the exact accepted Rephrase;
- every part's lock state and lock timestamp are unchanged;
- no part is added or removed;
- no part is reordered;
- no ID is replaced or re-minted; and
- no lock, unlock, root or coverage transition occurs.

Exactly one new target `ideal_text_part_revision` is allowed. If the accepted
text is byte-identical to the current target, the request fails with typed
`CONFIDENT_MOMENT_TEXT_UPDATE_NO_CHANGE`; it does not create a revision or
binding.

### 2.5 Immutable binding table

Add one append-only canonical table:

```text
confident_moment_bundle_text_update_bindings
```

Each row contains at least these exact immutable identities:

```text
id uuid primary key
acquisition_principal_id uuid
project_id uuid
source_take_id uuid
bundle_id uuid
bundle_attachment_id uuid
feedback_membership_id uuid
feedback_candidate_id uuid
correction_decision_id uuid
feedback_exposure_id uuid
render_receipt_id uuid
source_document_snapshot_id uuid
target_part_id uuid
result_part_revision_id bigint
result_document_snapshot_id uuid
before_part_inventory_sha256 text
after_part_inventory_sha256 text
binding_sha256 text
idempotency_key text unique
created_at timestamptz
serves_user boolean default false check (not serves_user)
dataset_eligible boolean default false check (not dataset_eligible)
```

Exact composite foreign keys must bind the Bundle/attachment, membership/
candidate, candidate/exposure, exposure/render receipt, correction decision,
source snapshot/target part, and resulting part revision/snapshot. The table
enables and forces RLS. `PUBLIC`, `anon`, `authenticated` and `service_role`
have no direct INSERT/UPDATE/DELETE. UPDATE and DELETE are rejected by the
canonical append-only trigger. Reads occur only inside reviewed wrappers.

The table and every source/result edge are added to deletion traversal. Source
deletion, retention loss, authority withdrawal, invalidated render/decision,
document supersession or target revision invalidates the binding for new root
use without mutating history.

### 2.6 Exact response

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

`result_part_revision_id` is a canonical positive base-10 JSON string. A JSON
number, sign, exponent, decimal point or leading zero rejects at the HTTP
boundary. No extra response key is permitted.

Exact replay repeats all live checks and returns the same binding/revision/
snapshot. A changed path, attachment, decision, exposure, render receipt,
snapshot, document version, inventory or idempotency identity conflicts.

## 3. Root action binds the text update

D17 adds one exact nullable key to the D14 root-action request:

```json
{
  "bundle_attachment_id": "uuid",
  "action": "save_owner_selected_root|lock_current_root|restore_previous_root|unlock_current_root|remove_current_root",
  "expected_block_head_action_id": null,
  "source_feedback_exposure_id": null,
  "source_owner_response_id": null,
  "source_practice_attempt_id": null,
  "source_ideal_text_revision_id": null,
  "source_text_update_binding_id": null,
  "source_target_speaker_binding_id": null,
  "practice_target_speaker_binding_id": null,
  "restore_product_action_id": null,
  "policy_version": "rooting-coverage-30-80-100-v1",
  "idempotency_key": "non-empty-string"
}
```

The corresponding public wrapper adds:

```text
p_source_text_update_binding_id uuid
```

to `record_confident_moment_bundle_root_action_v1`. The internal canonical root
action and immutable product-action row retain that binding as an exact foreign
key and include it in the action hash.

The closed source matrix is amended only as follows:

| Source | `source_ideal_text_revision_id` | `source_text_update_binding_id` | Rule |
| --- | --- | --- | --- |
| accepted Rephrase | required | required | both identify the same binding result; database derives the exact `source_correction_decision_id` |
| manual Ideal Text edit | required | null | revision must come from the preserved non-Bundle edit lineage; no correction decision is inferred |
| transcript response | as already frozen | null | exact owner response/exposure rules remain |
| re-record selection | as already frozen | null | exact practice/same-speaker rules remain |
| lock, restore, unlock, remove | null | null | every source field follows D14/D16 |

For an accepted Rephrase, the browser copies only the binding ID and resulting
part revision ID from section 2.6. The root wrapper loads the binding and derives
the correction decision; the browser never sends a correction decision to the
root route. It revalidates that the binding is live, belongs to this Bundle and
attachment, targets this paragraph, and produces this exact current part
revision. Missing, foreign, stale or mismatched binding/revision fails before
the root write.

`source_text_update_binding_id` is forbidden for manual edits and every other
source/action combination. A correction decision UUID may never occupy
`source_owner_response_id`.

## 4. One revealed source assignment, closed same-Bundle authoring set

### 4.1 Scope of authority

One exact independently blind, revealed confidence-review assignment authorizes
post-reveal product wording for a closed set of selected attachments in the
same immutable Bundle. Its five-state judgment remains a judgment only of the
exact reviewed audio clip; it does not become a judgment of the Bundle subject
or a sibling attachment.

The database derives the source authority from the exact tuple:

```text
review batch + reveal grant + reveal access + review assignment
+ derived blind judgment + reviewer + acquisition principal
+ source review packet/audio/evidence + Bundle + membership + source Take
+ document snapshot
```

For a `confidence_anchor` Bundle, the source review evidence must be the exact
confidence subject/anchor evidence. For a `no_anchor_paragraph_trigger` Bundle,
it must be the exact correction subject's source audio/evidence; absence of an
orange confidence anchor does not remove post-reveal wording authoring. In both
cases the blind assignment remains a confidence-review act and is never
reclassified as a correction or praise judgment. The authorized target set is
derived only from immutable
`confident_moment_bundle_attachments` rows for that same Bundle, membership,
source Take, Project, acquisition principal and document snapshot. The caller
cannot add a target. No join by snippet, Slide, text, timing, position or visual
proximity is permitted.

### 4.2 Closed family/output matrix

The exact target attachment's family determines the only legal product wording:

| Target family | `output_kind` | `comment_purpose` |
| --- | --- | --- |
| `confident_voice` | `comment` | `confidence_explanation` |
| `rewrite_clarity` | `rephrase` | null |
| `rewrite_clarity` whose frozen machine output is an observation rather than a proposed replacement | `comment` | `actionable_observation` |
| `great_formulation` | `comment` | `positive_praise` |

No other pair is legal. The attachment must remain selected, current and
non-excluded. The output type cannot be chosen independently of the frozen
target candidate output form.

### 4.3 Immutable source-lineage binding

Every coach Feedback Language revision created through this scope has one
immutable source-lineage row, stored in an append-only forced-RLS table:

```text
confident_moment_coach_wording_authority_bindings
```

The row binds at least:

```text
feedback_revision_id
review_batch_id
reveal_grant_id
reveal_access_id
review_assignment_id
blind_judgment_id
reviewer_principal_id
acquisition_principal_id
bundle_id
source_review_attachment_id
source_review_candidate_id
source_review_evidence_span_id
target_bundle_attachment_id
target_feedback_candidate_id
target_feedback_family
authority_scope = same_bundle_post_reveal_product_wording_v1
binding_sha256
created_at
serves_user = false
dataset_eligible = false
```

The row's exact composite foreign keys preserve Bundle membership, source
assignment/judgment and target attachment lineage. It is created atomically
with the revision and any delivery/materialization job. The revision is product
wording authored after reveal; the source blind judgment remains attached only
as authoring authority provenance.

The sibling target does **not** inherit the source candidate's confidence
decision, rating, evidence role, qualification or learning meaning. This path
creates no new assignment or judgment, does not copy the judgment value into
the target revision, and creates no confidence, correction-quality, praise-
quality, adequacy, effectiveness, preference or training label. It adds no
learning surface.

### 4.4 Coach context response

After complete-batch reveal, each exact source review item may add:

```json
{
  "bundle_authoring_context": {
    "bundle_id": "uuid",
    "source_review_attachment_id": "uuid",
    "authorized_targets": [
      {
        "bundle_attachment_id": "uuid",
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
    ]
  }
}
```

`authorized_targets` is complete, deduplicated and ordered by the Bundle's
canonical attachment position. For Comment targets,
`allowed_comment_purpose` is the exact family-matrix value; for Rephrase it is
null. Expected heads are exact nullable currentness inputs, not suggestions.

Before complete-batch reveal the entire object is absent. The response never
contains `blind_judgment_id`; the authoring RPC derives it from reveal access as
D16 requires.

### 4.5 Atomic coach-authoring RPC

The D16 public coach request and
`publish_confident_moment_coach_feedback_language_v1` signature remain. The
database now accepts a target attachment from the section 4.4 authorized set,
rather than requiring the blind assignment itself to name that target.

Before the write, after contention, and on replay it revalidates:

- the exact reviewer and current coach authority;
- complete-batch reveal and the derived exact blind judgment;
- the source confidence-review assignment/packet/audio/evidence remains live;
- the source attachment is the exact Bundle confidence subject/anchor or the
  exact no-anchor correction subject under section 4.1;
- the target remains an exact current same-Bundle attachment;
- the family/output matrix;
- Project, Take, membership, document, deletion, purge, retention and media
  currentness; and
- exact revision and delivery heads.

Changed membership, source assignment, Bundle, target set, family, reviewer,
reveal or currentness rejects the entire revision/delivery transaction. Exact
replay returns the same revision, delivery/job and authority binding.

## 5. Locks, deletion, permissions and idempotency

Both new binding families join the D11 exhaustive lock and writer registries.
The exact order is:

1. rollout policy and acquisition principal;
2. Project and Take inventory;
3. document/snapshot and ordered part inventory;
4. Bundle and attachment inventory;
5. source exposure/render/decision or coach reveal/assignment/judgment;
6. target part or target attachment;
7. part-revision or coach-revision head;
8. delivery/materialization head; and
9. immutable binding insertion.

All identity sets are derived under the coarse serializers, hashed, fine-locked
in canonical UUID/numeric order, rederived and compared before mutation. A
changed set returns the existing typed retry condition; no newly discovered
unlocked leaf may be followed.

Every writer that can change the ordered part inventory, Bundle membership,
decision/render validity, source assignment/reveal, reviewer authority,
revision/delivery head, deletion, purge, retention or media state must share the
same serializers and global order. The caller/signature/trigger registry is
closed and mechanically checked.

The two new binding tables enable and force RLS, reject UPDATE/DELETE, and grant
no runtime direct writes. Only the exact public service-role wrappers may create
them. All source and result edges join deletion traversal. Exact replay repeats
current authority, deletion and leaf validation before returning the original
result; a changed identity with the same key is a conflict.

## 6. Required regressions

### 6.1 Bundle text update

1. Exact accepted Rephrase + attachment + decision + D15 exposure/render +
   current inventory changes one target paragraph and returns one revision and
   one binding.
2. Missing, foreign, sibling, stale or changed decision/exposure/render rejects
   with zero document, revision, snapshot or binding writes.
3. Missing, extra, duplicate, reordered or replaced part IDs reject.
4. Any non-target text-byte change, target substitution other than the exact
   accepted Rephrase, or any lock change rejects.
5. Add/remove/reorder/id-remint and byte-identical no-op reject.
6. Exact replay returns the same bigint-string revision and binding; changed
   inventory or identity with the same key conflicts.
7. Two-connection races cover document/head replacement, part inventory change,
   decision invalidation, render invalidation, deletion and authority withdrawal
   in both commit orders, with atomic rollback.
8. The legacy non-Bundle user-edit branch remains byte-for-byte behaviorally
   compatible and cannot create a Bundle text-update binding.

### 6.2 Root binding

1. Accepted Rephrase requires matching non-null part revision and text-update
   binding; the database derives the correction decision.
2. Missing, foreign, stale, deleted or mismatched binding/revision rejects with
   zero root/product-action write.
3. Manual edit accepts a live exact part revision only with null binding.
4. Binding is rejected for transcript, practice, lock, restore, unlock and
   remove combinations.
5. A correction-decision UUID in `source_owner_response_id` rejects.

### 6.3 Same-Bundle coach authoring

1. One revealed source confidence-review assignment returns the complete exact
   same-Bundle target set in canonical order and no foreign Bundle attachment.
2. Before reveal, incomplete batch, stale access or withdrawn reviewer authority
   yields no authoring context.
3. Each legal family/output/purpose pair succeeds; every cross-family pair
   rejects before a revision or delivery.
4. Source and target may be distinct attachments, but both must retain the exact
   immutable Bundle/membership/Take/snapshot lineage.
5. Foreign Bundle, sibling membership, changed target set, invalidated source,
   deleted evidence and stale revision/delivery heads reject in both race orders.
6. Exact replay creates one revision, one authority binding and at most one
   current delivery/job.
7. No new assignment/judgment is created; the sibling target receives no copied
   judgment value, confidence state, qualification, label or learning row.
8. A no-anchor Bundle can use authoring only from the exact revealed assignment
   bound to its correction-subject audio/evidence; a foreign or approximate
   confidence review cannot authorize it.

### 6.4 Structural/security controls

Apply/reapply, atomic negative rollback, forced RLS, no direct runtime writes,
exact grants, append-only rejection, deletion traversal, lock-graph/caller
registry, response denylist, bigint-string and recursively closed JSON tests are
mandatory. No fabricated response, root qualification, practice, comparison,
adequacy, outcome, dataset, training, evaluation, promotion or ninth learning-
surface record is permitted.

## 7. Gates and learning fences

`CONFIDENT_MOMENT_BUNDLE_V1_ENABLED`, `ROOTING_COVERAGE_V1_ENABLED`, every PAM
gate and every collection/dataset/training/evaluation/promotion gate retain
their exact disabled defaults. Both new binding tables are structurally
`serves_user=false` and `dataset_eligible=false`. These records are product
provenance only and are not dataset membership or model supervision.

No migration numbering, manifest assignment, commit, push, merge, deployment,
activation or real collection is authorized by D17.

## 8. Stop conditions

Stop implementation and request ML/data interface review if any code would:

- let Bundle Update-text use the unbound legacy edit branch;
- accept replacement text, target part, candidate, family or correction meaning
  from the browser instead of exact immutable lineage;
- mutate more than one part or alter any non-target ID, text, order or lock;
- create a part revision without the same-transaction text-update binding;
- permit accepted-Rephrase root save without the exact binding and revision;
- infer a correction decision from text equality or put it in an owner-response
  field;
- let one blind confidence assignment authorize a different Bundle, membership,
  Take, snapshot or an attachment outside the closed target set;
- copy the source confidence judgment/value/label onto a sibling target;
- create a new assignment, judgment, learning label or surface for wording;
- expose `blind_judgment_id` to the browser;
- weaken D11–D16 blindness, currentness, authorization, deletion, RLS/RPC-only,
  Manager-budget, non-serving or non-learning boundaries; or
- change any gate or release state without a separate approval.

`VERDICT: D17 PROPOSED FOR PRODUCT AND ML/DATA INTERFACE REVIEW; EXECUTABLE WORK BLOCKED`
