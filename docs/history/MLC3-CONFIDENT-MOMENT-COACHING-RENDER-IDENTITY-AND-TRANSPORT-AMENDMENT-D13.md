# MLC-3 Confident Moment Coaching Bundle — Render Identity and Transport Amendment D13

**Status:** proposed narrow interface amendment for Product/ML-data and
Engineering review. It authorizes no executable change, migration numbering,
commit, push, merge, deployment, activation, collection, dataset creation,
training, evaluation, promotion, or serving.

## 1. Bound authority and purpose

D13 is bound to:

- accepted Contract Delta D3 SHA-256
  `59c4bad81e1b0a4917d76ce27f48b9a049ca29ea5ba94ad0829ba9ed5650dc67`;
- accepted Interface Manifest D6 SHA-256
  `73514e30005c4b780011f5b6e1631b4c9bb3c3d1f087afea8408bf24df0f15b2`;
- accepted Interface Manifest D11 SHA-256
  `ec2d92bed3a0da354b4ecfd0051d68677e83f9f0d40382c9e3d9678c287c49ea`;
  and
- accepted Per-item Currentness Amendment D12 SHA-256
  `0f6a9e9f7068c4881f0bb728033d62ee6ac80c9766dd5eecd14cd6630e7a86ea`.

D13 closes four application/interface gaps only:

1. both public render paths contain `bundle_id`, but their accepted SQL RPCs do
   not receive or verify it;
2. scalar PostgreSQL `jsonb` responses are currently tolerated as singleton
   arrays by the application adapter;
3. the application response validator is not yet a recursively closed schema
   with complete cross-identity and summary-currentness checks; and
4. the pure clause helper reconstructs normalized text rather than preserving
   the exact canonical transcript byte span.

No Manager item, family, slot, confidence state, response, coach judgment,
root qualification, exercise, label, dataset row, or learning surface changes.
D3/D6/D11/D12 authorization, blindness, serializers, currentness, exposure,
deletion, non-serving, dataset-ineligible and disabled-gate boundaries remain.

## 2. Canonical Bundle identity at both render boundaries

`ConfidentMomentCoachingBundle.bundle_id` is the exact
`bundle_subject_candidate_id`. It is not a display identifier and cannot be
discarded by the route. Both render operations must bind the real path value to
the exact attachment before any exposure write or replay return.

Replace the Bundle-item render RPC with:

```text
ack_confident_moment_bundle_item_render_v2(
  p_acquisition_principal_id uuid,
  p_bundle_id uuid,
  p_bundle_attachment_id uuid,
  p_presentation_id uuid,
  p_render_instance_id uuid,
  p_idempotency_key text
) -> jsonb
```

Replace the D12 coach-update render RPC with:

```text
ack_feedback_language_revision_render_v3(
  p_recipient_principal_id uuid,
  p_bundle_id uuid,
  p_bundle_attachment_id uuid,
  p_revision_id uuid,
  p_revision_delivery_id uuid,
  p_presentation_id uuid,
  p_render_instance_id uuid,
  p_idempotency_key text
) -> jsonb
```

For both functions PostgreSQL loads the exact attachment under the existing
D11 staged serializers and requires:

```text
p_bundle_id = attachment.bundle_subject_candidate_id
attachment.acquisition_principal_id = authenticated/derived principal
attachment.id = p_bundle_attachment_id
attachment membership/Project/Take/document/subject is current and live
```

The coach-update v3 function additionally proves the supplied revision,
delivery and presentation are the complete D12 currentness tuple for that same
attachment. The Bundle-item v2 function proves the supplied presentation is
the attachment's exact pre-existing canonical Feedback presentation. A Bundle
ID that exists for the same principal or Take but belongs to another attachment
is still foreign and fails before an exposure write.

The database derives Bundle identity from the attachment and compares it to the
supplied path identity; the browser does not establish it. The equality is
revalidated after contention and before exact replay return. Reusing an
idempotency key with a changed Bundle, attachment, presentation, revision,
delivery or render instance is a replay conflict.

`ack_confident_moment_bundle_item_render_v1` and
`ack_feedback_language_revision_render_v1/v2` are runtime-inaccessible. They
may remain only when a checksum-pinned internal migration dependency requires
them and can never be alternate service paths. The exhaustive SQL function,
proname, overload, grants/revokes, caller and static registries must replace the
old signatures exactly. The closed application tuples become:

```text
services/confident_moment_bundle_repository.py::ConfidentMomentBundleRepository.ack_item_render
  -> ack_confident_moment_bundle_item_render_v2
services/confident_moment_bundle_repository.py::ConfidentMomentBundleRepository.ack_revision_render
  -> ack_feedback_language_revision_render_v3
```

No route, service, worker, operation or dynamic RPC name may call the retired
overloads.

## 3. HTTP and UUID transport identity

The public paths remain:

```http
POST /v2/user/confident-moment-bundles/{bundle_id}/render
POST /v2/user/confident-moment-bundles/{bundle_id}/coach-updates/{revision_id}/render
```

`bundle_id`, `revision_id`, and every UUID request field must be a real JSON or
path string in canonical lowercase hyphenated UUID form. Null, number, boolean,
array, object, bytes, test double, UUID-like object, braces, uppercase or a
non-canonical UUID spelling rejects. Parsing must round-trip to the identical
canonical string; coercing arbitrary objects through `str(...)` is prohibited.
The same rule applies recursively to every UUID returned by PostgreSQL.

Bundle-item request exact keys:

```json
{
  "bundle_attachment_id": "uuid",
  "presentation_id": "uuid",
  "render_instance_id": "uuid",
  "idempotency_key": "non-empty-string"
}
```

Coach-update request exact keys:

```json
{
  "bundle_attachment_id": "uuid",
  "revision_delivery_id": "uuid",
  "presentation_id": "uuid",
  "render_instance_id": "uuid",
  "idempotency_key": "non-empty-string"
}
```

The path supplies `bundle_id` and, for coach updates, `revision_id`; duplicating
either in the body is rejected as an extra field. Missing or extra request keys
reject before repository access.

## 4. Exact scalar-`jsonb` repository transport

Every D11/D12/D13 RPC declared `RETURNS jsonb` returns one PostgreSQL scalar
JSON object. For these RPCs, `execute().data` must be a Python `dict` with
exactly the expected closed keys. A list, including a singleton list whose
first entry is an object, is invalid transport. Null, scalar, tuple, arbitrary
mapping/test double, or an object nested under an unreviewed wrapper is also
invalid. The shared list-first `_rpc_payload` behavior must not be used.

If a deployed PostgREST/client version is ever observed to wrap this exact
scalar result, that transport requires a separately frozen adapter contract and
regression evidence; application code may not guess or silently unwrap it.

The repository passes the canonical path `bundle_id` as `p_bundle_id` for both
replacement RPCs and returns their object unchanged after closed validation.
Routes do not select optional keys from the result and do not rename whichever
ID happens to be present.

## 5. Closed render-receipt responses

The Bundle-item v2 RPC returns exactly:

```json
{
  "render_contract_version": "confident-moment-bundle-item-render-v2",
  "bundle_id": "uuid",
  "bundle_attachment_id": "uuid",
  "presentation_id": "uuid",
  "render_instance_id": "uuid",
  "render_receipt_id": "uuid",
  "feedback_exposure_id": "uuid",
  "dataset_eligible": false
}
```

The coach-update v3 RPC returns exactly:

```json
{
  "render_contract_version": "feedback-language-revision-render-v3",
  "bundle_id": "uuid",
  "bundle_attachment_id": "uuid",
  "current_revision_id": "uuid",
  "revision_delivery_id": "uuid",
  "presentation_id": "uuid",
  "render_instance_id": "uuid",
  "rendered_exposure_id": "uuid",
  "dataset_eligible": false
}
```

Every listed key is required; no extra key is allowed. Each echoed identity
must equal the request/path identity and the exact database-derived row. The
route returns this validated object without omission, synthesis or renaming.
Exact replay returns the byte-equivalent identity object. A missing receipt ID,
wrong ID kind, cross-Bundle echo, `dataset_eligible` other than literal false,
or changed response shape fails closed and is never reported as success.

## 6. Recursively closed projection envelope

The application validator may reject malformed transport but may not enrich,
select, fold, reorder or reinterpret the database projection. Unknown keys are
rejected at every object depth, not only through a sensitive-name denylist.

The complete allowed object keys are:

| Object | Exact keys |
| --- | --- |
| envelope | `bundle_projection`, `confident_moment_summary` |
| bundle projection v2 | `contract_version`, `feedback_language_shape_version`, `project_id`, `take_id`, `document_snapshot_id`, `feedback_membership_id`, `bundles`, `coverage`, `response_sha256` |
| Bundle | `bundle_id`, `bundle_subject_kind`, `slide_index`, `block_key`, `paragraph_id`, `subject`, `confidence_anchor`, `feedback_language_items`, `exercise`, `root`, `state_revision` |
| subject | `candidate_id`, `evidence_span_id`, `canonical_feedback_presentation_id` |
| confidence anchor | `candidate_id`, `evidence_span_id`, `playback_reference_id` |
| Feedback Language item | `bundle_attachment_id`, `attached_candidate_id`, `canonical_position`, `resolution_state`, `exclusion_reason`, `output`, `coach_update` |
| typed output | `output_kind`, `comment_purpose`, `text`, `origin` |
| per-item coach update | `current_revision_id`, `revision_sha256`, `revision_delivery_id`, `delivery_subject_sha256`, `presentation_id`, `rendered_exposure_id`, `unread` |
| root | `is_orange`, `is_locked`, `can_restore_previous` |
| coverage | `target_slide_count`, `achieved_slide_count`, `target_met` |
| first-paint summary | `contract_version`, `document_snapshot_id`, `items`, `summary_sha256` |
| summary item | `bundle_id`, `paragraph_id`, `slide_index`, `block_key`, `marker_present`, `is_orange`, `is_locked`, `has_unread_coach_update`, `state_revision` |

`confidence_anchor` is either null or the exact closed object.
`output`/`coach_update` nullability follows D12. `exercise` is exactly null and
has no no-match meaning. UUID fields obey section 3; hashes are exactly 64
lowercase hexadecimal characters; indices/revisions/counts are non-negative
integers where defined and never booleans; state and purpose strings come only
from the existing closed vocabularies; `playback_reference_id` is a non-empty
opaque string and is not interpreted as a UUID or storage URL.

The following cross-object invariants are mandatory:

1. `subject.candidate_id == bundle.bundle_id`; a `confidence_anchor` subject
   has matching anchor candidate/evidence IDs, while a no-anchor subject has
   `confidence_anchor=null`.
2. Bundle IDs are unique and use canonical database order. Attachment IDs and
   attached candidate IDs are globally unique in the projection. Attachment
   canonical positions are unique and strictly increasing within each
   Bundle's `feedback_language_items` array. No cross-Bundle monotonic order is
   asserted: Bundle order and each Bundle's item order use their separately
   frozen database keys.
3. Coach revision, delivery, presentation and rendered-exposure IDs are each
   unique across items. They occur only together under that one item's
   `coach_update`; machine and excluded items carry none.
4. `unread` is true exactly when the current coach item has no rendered
   exposure. A read item has one exact exposure. Zero-delivery machine fallback
   and exclusions have `coach_update=null`.
5. `output.origin=coach` exactly for `resolution_state=coach_revision` and
   `output.origin=machine` exactly for `machine_fallback`. Exclusion has both
   `output=null` and one non-empty typed reason.
6. Comment has one recognized non-null purpose; Rephrase has purpose null.
7. Summary item cardinality, order and Bundle IDs equal the Bundle array.
   Paragraph, Slide, block, root display booleans and state revision equal the
   corresponding Bundle values. `marker_present` is literal true.
8. For each Bundle, `has_unread_coach_update` equals the existential OR of
   `coach_update.unread` over its own Feedback Language items. It may never be
   copied from another Bundle or cleared after only one of several items is
   rendered.
9. Projection and summary document snapshot IDs match. The application accepts
   the server hashes only after all structural/coherence checks; it does not
   recalculate them using a different JSON canonicalization.

Valid empty projection semantics remain explicit: `bundles=[]`, summary
`items=[]`, zero coverage counts, `target_met=false`, and valid hashes. Missing
arrays, missing summary, partial objects and broad-exception fallback to empty
are prohibited.

`coverage` is internal product-routing and diagnostic state. Although it is
transported in the closed envelope, neither backend nor frontend may render its
counts, ratio, target, `target_met` verdict, progress meter, badge, ranking or
any equivalent user-facing assessment. It cannot become a Manager item,
confidence signal, qualification, feedback label or learning target. This is
the explicit AC-9 boundary for the coverage object.

## 7. Serialization, replay and failure mapping

D11's global numeric lock order and staged identity discovery/re-hash protocol
remain authoritative. The replacement render functions use the exact same
writer-shared principal, Project, Take, membership, document, Bundle subject,
candidate, revision/delivery and canonical presentation/exposure serializers
as projection and invalidation writers. They revalidate Bundle equality and all
existing recipient/reviewer/source/deletion/media/current-head leaves before
and after the potentially blocking exposure write and before replay return.

If an identity set changes during discovery, only
`CONFIDENT_MOMENT_PROJECTION_RETRY_REQUIRED` maps to HTTP 409. Malformed HTTP or
database response shape maps to the existing exact-identity/projection-invalid
client error and creates no write. Foreign Bundle, authority, stale revision,
deletion, source and media failures remain typed fail-closed errors; no broad
exception may convert them into empty or successful output.

## 8. Exact-clause preservation and authority

If the Chunk 3 exact-clause helper remains, it must never reconstruct returned
text with token joining, whitespace collapse, trimming, punctuation removal, or
Unicode normalization. One clause is a contiguous slice of the canonical
transcript's strict UTF-8 bytes:

```text
raw_span = transcript_utf8[start_byte:end_byte]
span_sha256 = lowercase_sha256(raw_span)
text = strict_utf8_decode(raw_span)
```

`start_byte` is the first byte of the first included canonical token.
`end_byte` is exclusive and follows the exact terminating `.`, `?`, `!`, `;`
or `:` byte, or the last included token at the evidence boundary. All bytes
between those boundaries—including repeated spaces, tabs and line breaks—are
preserved. Whitespace outside the first/last token is not included. Invalid
UTF-8, non-token-aligned boundaries, empty spans or a hash mismatch is a typed
unusable-source exclusion.

Normalized word tokens may be used only to count 5–20 words and resolve the
already accepted deterministic ordering. They do not become the stored/display
text and are not hashed in place of the raw span. Golden tests must distinguish
one space from two spaces, tabs, newlines, composed/decomposed Unicode and
punctuation adjacency.

The pure application helper is preview/test policy only. In every enabled
write or projection path PostgreSQL remains the authority: it derives the exact
canonical transcript, token/boundary identity, raw span and hash under the
current locks. Browser- or Python-supplied clause text, offsets, word count,
eligibility or hash can never authorize a root or coverage decision.

## 9. Frontend and repository implications

- Routes must parse and forward the real `bundle_id`; deleting or ignoring the
  path parameter is prohibited.
- Repository methods accept `bundle_id`, call only the replacement exact RPC,
  require scalar-object transport, validate the closed receipt, and return it
  unchanged.
- Projection validation enforces section 6 recursively before either Bundle
  response or first-paint summary is exposed. No optional enrichment/direct
  table read is permitted.
- Frontend render requests copy Bundle, attachment and currentness identities
  from the same validated projection item. Cross-item or cross-Bundle mixing is
  impossible in reducer keys and request construction.
- D12 per-item visibility/two-painted-frame acknowledgement remains: an
  unmounted or invisible item creates no exposure. Summary unread remains an
  existential hint only.
- Unknown projection or render contract versions fail closed. Backend and
  frontend are released together while all gates remain disabled.

## 10. Required executable regressions

### 10.1 Cross-Bundle render identity

1. Two Bundles in the same membership each contain an attachment. Use Bundle
   A's path with A's attachment: one exact receipt succeeds. Use Bundle B's
   path with A's attachment/presentation: both render RPCs reject with zero new
   exposure.
2. Repeat cross-binding with same principal/Project/Take and with foreign
   principal, membership, Take, document and candidate identities.
3. Coach render cross-binds every pair among Bundle, attachment, revision,
   delivery and presentation; each fails atomically before exposure.
4. Exact unchanged replay returns the same receipt object. Changed Bundle ID or
   other identity under the same idempotency key is a conflict.
5. Both commit orders for Bundle/attachment invalidation or replacement versus
   render return either the fully validated old receipt before the writer or a
   typed failure with no exposure; never a cross-Bundle receipt.

### 10.2 Transport and closed responses

1. Scalar JSON object succeeds. Singleton list, empty list, multi-item list,
   null, scalar, tuple, arbitrary mapping/test double and nested wrapper reject.
2. Missing or extra request/response key rejects. Every non-string UUID value,
   uppercase/non-canonical spelling and mismatched response echo rejects.
3. Bundle-item response requires both exact `render_receipt_id` and
   `feedback_exposure_id`; coach response requires exact
   `rendered_exposure_id`. Missing, swapped, duplicated or wrong-kind IDs fail.
4. Recursive unknown keys fail at every envelope/object/array depth, including
   innocuous-looking non-denylisted keys.
5. Duplicate Bundle, attachment, candidate, revision, delivery, presentation,
   or exposure identity rejects. Duplicate/non-monotonic canonical positions
   reject within one Bundle; a genuine multi-Bundle fixture proves separately
   ordered Bundles may reuse/interleave positions without a false global-order
   failure.
6. Exercise non-null, malformed output/currentness nullability, cross-item
   currentness, summary order/cardinality/root mismatch, and an incorrect
   summary existential unread flag reject.
7. Valid empty response succeeds; malformed/fatal database response never
   becomes empty success. Only the typed retry maps to HTTP 409.

### 10.3 Clause golden fixtures

1. Returned `text` is byte-for-byte the canonical raw slice and its SHA-256 is
   over exactly those bytes.
2. Fixtures distinguish single/double spaces, tabs, CRLF/LF, line breaks,
   composed/decomposed Unicode, attached/separate punctuation and evidence-end
   termination without rewriting.
3. Invalid UTF-8/boundary/hash cases exclude and create no root, coverage,
   response or learning row.
4. Attempts to supply authoritative text/hash/count from route or browser are
   rejected; enabled-state DB derivation remains authoritative.

### 10.4 Registry, security and learning fences

- Fresh apply/reapply matches exact replacement signatures, pronames, overload
  counts, grants/revokes and AST caller tuples. Missing/extra/retired runtime
  writers and direct `.table(...)` Bundle reads fail closed.
- Replacement RPCs are executable only by `service_role` through reviewed
  repository routes; `PUBLIC`, `anon`, and `authenticated` cannot execute them.
  Retired v1/v2 overloads are inaccessible to every runtime role.
- RLS/forced RLS, RPC-only writes, deletion traversal, exact authority and all
  D11/D12 concurrency/replay regressions remain green.
- Render/projection/extraction create no extra Manager item, response, root
  qualification, exercise, practice, comparison, adequacy, judgment, dataset,
  training, evaluation, promotion or learning-surface row.
- AC-9 tests prove `coverage` counts, ratios, target state and target verdict
  are never rendered or transformed into user-visible text, progress, badges,
  ranks or scores, while the validated object may remain internal to routing.
- `serves_user=false`, `dataset_eligible=false`, the unnumbered/unmanifested
  migration, and all bundle/root/PAM/data/learning gates remain unchanged.

## 11. Decision filter

```text
VERDICT:  ADVANCE-F2 FOR INTERFACE REVIEW
CATEGORY: F2
WHY:      D13 makes both public path identities authoritative database-bound,
          closes scalar transport and projection schemas, and preserves exact
          transcript bytes without expanding Product or learning semantics.
REDIRECT: Obtain Product/ML-data and Engineering interface acceptance, then
          update the executable manifest and correct Chunks 2B/3 locally behind
          disabled gates before combined implementation review.
```

`FILTER: ADVANCE-F2 — cat F2 — fences clear — locks clear at the proposed
interface level — redirect: accept and re-freeze before executable edits.`
