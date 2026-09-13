# MLC-3 Confident Moment Coaching Bundle — Transport Closure Amendment D16

Status: proposed interface amendment; no executable implementation is authorized
by this document.

## 1. Frozen parents and purpose

This amendment is bound to these exact accepted documents:

| Contract | SHA-256 |
| --- | --- |
| Confident Moment Coaching Contract Delta D3 | `59c4bad81e1b0a4917d76ce27f48b9a049ca29ea5ba94ad0829ba9ed5650dc67` |
| Interface Manifest D11 | `ec2d92bed3a0da354b4ecfd0051d68677e83f9f0d40382c9e3d9678c287c49ea` |
| Currentness Amendment D12 | `0f6a9e9f7068c4881f0bb728033d62ee6ac80c9766dd5eecd14cd6630e7a86ea` |
| Render Identity and Transport Amendment D13 | `23def906f8ad310a65ef40529b14b9230cc87f40544eec2000eae069ea69e21d` |
| Frontend and Authoring Amendment D14 | `507543935fa1906ea7cf3cea2e1d3195ab830cb35262942bec6b2daef27e759d` |
| Feedback Exposure Identity Amendment D15 | `25bddb8673bff3debe7572125c3b64ac40bcda29d8c5f424c75201b5c7970454` |

D16 closes four transport gaps that would otherwise force the browser to infer
or fetch legacy provenance: the family response identity, the owner response
needed by a root action, the exact Ideal Text part revision, and the post-reveal
coach Bundle identity. It also freezes the original corrected passage and
separates coach-update existence from unread state.

D16 does not change the Manager budget, Feedback V3 families, response meaning,
blindness, root qualification, exercise matching, learning surfaces, or dataset
eligibility. All gates remain disabled by default.

## 2. Bundle-bound family response

### 2.1 Existing boundaries and prohibition

The compatibility route
`POST /v2/user/takes/{take_id}/feedback-response` currently requires the legacy
`feedback_id`/`feedback_candidates.candidate_key`. It does not return the exact
canonical response identity required by a later root action. It remains
unchanged for existing non-Bundle callers and is prohibited for Bundle items.

Neither `feedback_id` nor `candidate_key` may be added to the Bundle projection,
first-paint summary, Bundle HTTP request, or browser state. The browser may not
translate an attachment UUID into a legacy key.

### 2.2 Sole Bundle response route and RPC

The sole Bundle family-response route is:

```http
POST /v2/user/confident-moment-bundles/{bundle_id}/attachments/{bundle_attachment_id}/response
```

Its sole application caller is:

```text
services/confident_moment_bundle_repository.py::ConfidentMomentBundleRepository.record_family_response
  -> record_confident_moment_bundle_family_response_v1
```

The exact database wrapper is:

```text
record_confident_moment_bundle_family_response_v1(
  p_acquisition_principal_id uuid,
  p_bundle_id uuid,
  p_bundle_attachment_id uuid,
  p_feedback_exposure_id uuid,
  p_render_receipt_id uuid,
  p_response text,
  p_idempotency_key text
) -> jsonb
```

The request body has exactly:

```json
{
  "feedback_exposure_id": "uuid",
  "render_receipt_id": "uuid",
  "response": "closed-family-value",
  "idempotency_key": "non-empty-string"
}
```

The database derives Project, Take, owner user, membership, candidate, evidence,
family, taxonomy and any compatibility key from the exact Bundle attachment and
D15 render receipt. The browser supplies none of them. Before mutation, after
contention, and on exact replay, the wrapper repeats D11–D15 current membership,
attachment, exposure, render-receipt, document, deletion and D4 service-authority
validation.

The closed public response values remain the existing UI vocabulary:

| Family | Accepted values | Canonical decision mapping |
| --- | --- | --- |
| `confident_voice` | `yes`, `in_between`, `no`, `not_sure`, `audio_unclear` | exact corresponding confidence self-report; the service wrapper maps to its namespaced V3 value internally |
| `rewrite_clarity` | `apply_suggestion`, `keep_wording` | `accept_proposed`, `keep_original` |
| `great_formulation` | `useful`, `not_useful`, `not_sure` | unchanged |

`edit_myself` only opens an editor. It remains local and creates no decision.
Cancel, dismissal, silence and timeout create no request or response.

For `confident_voice`, the wrapper delegates in the same transaction to the
existing exact `record_feedback_v3_service_response_v1` boundary and returns the
created/replayed `feedback_v3_owner_responses.id` and
`feedback_v3_service_response_bindings.id`. For `rewrite_clarity` and
`great_formulation`, it delegates to the exact
`record_feedback_human_decision_v1(uuid,uuid,uuid,uuid,uuid,uuid,text,text,text,text)`
overload and returns its canonical decision ID. These
two families do not fabricate a `feedback_v3_owner_responses` row.

The exact response is:

```json
{
  "family_response_contract_version": "confident-moment-family-response-v1",
  "bundle_id": "uuid",
  "bundle_attachment_id": "uuid",
  "feedback_family": "confident_voice|rewrite_clarity|great_formulation",
  "response": "closed-family-value",
  "decision_id": "uuid",
  "owner_response_id": null,
  "response_binding_id": null,
  "dataset_eligible": false
}
```

For `confident_voice`, `owner_response_id` and `response_binding_id` are non-null
and `decision_id` is the exact confidence self-report ID held by the binding.
For `rewrite_clarity` and `great_formulation`, both nullable IDs are null and
`decision_id` is the exact correction or praise decision. No extra response key
is permitted.

## 3. Root-action source identity

D14 section 3 is amended as follows.

The Bundle family-response result is the only browser source of an
`owner_response_id`. It may be submitted as `source_owner_response_id` only for
the exact confidence attachment, exposure and response from which the selected
transcript phrase derives. The database revalidates the exact response binding.
The browser never fabricates or discovers this ID through a supplemental read.

An accepted Rephrase is not a V3 owner response. `Update the text` records the
exact correction decision through section 2 and the exact Ideal Text part
revision through section 4. A later `Save the text` sends
`source_owner_response_id=null` and the exact `source_ideal_text_revision_id`.
The Bundle root wrapper derives the exact `source_correction_decision_id` from
the Bundle attachment, family decision, exposure and root content lineage.

The internal root primitive must therefore permit this closed accepted-Rephrase
case without pretending that a correction decision is a
`feedback_v3_owner_responses.id`. It must require the content version's exact
non-null `source_correction_decision_id`, the exact same Bundle attachment and
exposure, the exact applied Ideal Text part revision, and `text_origin` equal to
`accepted_rewrite`. A manual owner edit instead requires `text_origin` equal to
`manual_edit` and an exact Ideal Text part revision. These cases remain distinct.

`record_confident_moment_bundle_root_action_v1` remains the only public root
wrapper and derives Project, Take, Paragraph, block, candidate, evidence, root
content and any correction-decision identity. The raw
`record_root_phrase_product_action_v2` primitive becomes inaccessible to every
runtime role.

## 4. Exact Ideal Text part revision

### 4.1 Current boundary is not sufficient

The existing `PUT /v2/explore/arc/{arc_id}/ideal-text/user-edit` returns only a
document version. Its current application persistence writes the document,
replaces parts, and appends `ideal_text_part_revision` rows in separate,
best-effort operations. A `MAX(id)`, timestamp order, or read-latest-after-save
cannot prove which exact edit produced a root and is prohibited.

### 4.2 One authoritative transaction

The existing HTTP route remains the single Ideal Text user-edit boundary. Its
implementation must call exactly one authoritative database transaction:

```text
persist_ideal_text_user_edit_v2(
  p_arc_id text,
  p_owner_user_id uuid,
  p_expected_document_version integer,
  p_text text,
  p_parts jsonb,
  p_reapplied boolean,
  p_idempotency_key text
) -> jsonb
```

Backend authentication derives `p_owner_user_id`; the database derives Project
and acquisition principal from the owned arc and revalidates them after
contention. The transaction validates the exact ordered part set and its join,
writes the full user edit, replaces the exact parts, and appends an immutable
part revision for every changed part. All succeed or all roll back. An audit
append is no longer best-effort on this v2 path.

The HTTP request permits exactly:

```json
{
  "text": "complete-document-text",
  "version": 1,
  "parts": [
    {"id": "uuid", "text": "paragraph-text", "locked": false}
  ],
  "reapplied": false,
  "idempotency_key": "non-empty-string"
}
```

`parts` must be present and non-empty when the request originates from a Bundle
`Update the text` action. The route may preserve its reviewed non-Bundle legacy
behavior in a separately tested compatibility branch, but that branch may not
authorize a Bundle root.

The successful v2 response is exactly:

```json
{
  "ideal_text_user_edit_contract_version": "ideal-text-user-edit-v2",
  "saved": true,
  "arc_id": "arc-id",
  "version": 1,
  "part_revisions": [
    {"part_id": "uuid", "revision_id": "9007199254740993"}
  ]
}
```

`part_revisions` contains exactly the changed parts, sorted by their canonical
part order. Every `revision_id` is a canonical positive base-10 JSON string:
no number, sign, exponent, decimal point or leading zero is accepted. The
Bundle overlay selects a revision only by exact equality between the returned
`part_id` and the Bundle `paragraph_id`; absence or duplication fails closed.
It passes the string unchanged to the D14 root route, whose backend alone parses
it to PostgreSQL `bigint`.

## 5. Post-reveal coach Bundle context

### 5.1 Sole Bundle-aware context wrapper

When the Bundle gate is enabled, the existing post-reveal route
`GET /v2/coach/guidance/batches/{arc_id}` must make one database call to:

```text
project_confident_moment_coach_authoring_context_v1(
  p_project_id uuid,
  p_acquisition_principal_id uuid,
  p_reviewer_principal_id uuid,
  p_idempotency_key text
) -> jsonb
```

The wrapper invokes and validates the existing
`prepare_coach_inline_guidance_context_v1` result, then joins each revealed item
to exactly one current Bundle attachment using the database-owned Project,
acquisition principal, source Take, membership and candidate lineage. It never
joins by snippet, text, Slide, timing, visual position or array index.

Each Bundle-authorable item additively returns this exact object:

```json
{
  "bundle_context": {
    "bundle_id": "uuid",
    "bundle_attachment_id": "uuid",
    "source_passage": {
      "evidence_span_id": "uuid",
      "text": "exact selected passage",
      "text_sha256": "64-lowercase-hex"
    }
  }
}
```

The surrounding D5 item retains its exact `review_batch_id`, `reveal_grant_id`,
`reveal_access_id` and `review_assignment_id`. Zero Bundle attachments means the
Bundle authoring control is absent for that item. More than one exact match is
typed `CONFIDENT_MOMENT_BUNDLE_ATTACHMENT_AMBIGUOUS` and fails the Bundle
authoring context; the database never chooses one.

### 5.2 Blind judgment is derived, not transported

D14 section 4.2 is amended to remove `blind_judgment_id` from the
public HTTP body and from the public RPC signature. The body is exactly:

```json
{
  "review_batch_id": "uuid",
  "reveal_grant_id": "uuid",
  "reveal_access_id": "uuid",
  "review_assignment_id": "uuid",
  "output_kind": "comment|rephrase",
  "comment_purpose": null,
  "revision_text": "non-empty-string",
  "expected_current_revision_id": null,
  "expected_current_delivery_id": null,
  "idempotency_key": "non-empty-string"
}
```

The revised atomic wrapper is:

```text
publish_confident_moment_coach_feedback_language_v1(
  p_reviewer_principal_id uuid,
  p_bundle_id uuid,
  p_bundle_attachment_id uuid,
  p_review_batch_id uuid,
  p_reveal_grant_id uuid,
  p_reveal_access_id uuid,
  p_review_assignment_id uuid,
  p_output_kind text,
  p_comment_purpose text,
  p_revision_text text,
  p_expected_current_revision_id uuid,
  p_expected_current_delivery_id uuid,
  p_idempotency_key text
) -> jsonb
```

It derives `blind_judgment_id` from the exact reveal-access, reveal-grant,
reviewer and assignment tuple, then revalidates the matching immutable
`ml_judgments` row, complete-batch reveal, source and current reviewer authority
before and after contention. It supplies the derived judgment only to the
internal revision writer. A browser-provided judgment ID is rejected as an
extra key. The accepted D14 atomic revision/delivery response is unchanged.

## 6. Original selected passage

This section explicitly amends the closed Feedback Language item row in D13
section 6, as previously amended by D14 section 2 and D15 section 3. It adds
`source_passage` as one required non-null key on every item; this D16 schema is
the single authoritative recursive closed-item schema and unknown or missing
keys still fail closed.

Every Bundle Feedback Language item, excluded or non-excluded, adds:

```json
{
  "source_passage": {
    "evidence_span_id": "uuid",
    "text": "exact selected passage",
    "text_sha256": "64-lowercase-hex"
  }
}
```

The database derives the text only from the attached candidate's exact
`evidence_spans.exact_text` and hashes the canonical UTF-8 bytes. The evidence
ID must equal the attachment candidate's evidence and must not be copied from a
sibling. The passage is not reconstructed from generated output, a transcript
search, offsets supplied by the browser, or text equality.

The object participates in the item hash, projection response hash and
stabilized currentness inventory. Missing text, a changed hash, foreign evidence
or invalid source is typed projection invalidity; there is no null or guessed
fallback. The owner may receive only their selected passage. The coach may
receive it only in the complete post-reveal context from section 5. This is
product context, not a confidence label or dataset release.

## 7. Coach-update existence and unread state

The D13 summary-item closed schema adds one required boolean:

```json
{
  "bundle_id": "uuid",
  "paragraph_id": "uuid",
  "slide_index": 0,
  "block_key": 0,
  "marker_present": true,
  "is_orange": false,
  "is_locked": false,
  "has_coach_update": false,
  "has_unread_coach_update": false,
  "state_revision": 1
}
```

For the exact Bundle:

```text
has_coach_update = EXISTS(current valid attachment coach_update)
has_unread_coach_update = EXISTS(current valid attachment coach_update
                                 whose rendered_exposure_id is null)
```

`has_unread_coach_update=true` implies `has_coach_update=true`. After every
current coach update is rendered, existence remains true while unread becomes
false. Mixed attachments use existential OR independently for both fields.
Both values derive from the same D11–D15 serialized projection, enter the
summary hash, and are passed through without frontend recomputation.

## 8. Permissions, gates and fences

All new wrappers are `SECURITY DEFINER`, use a fixed `search_path`, and are
executable only by `service_role`. `PUBLIC`, `anon` and `authenticated` receive
no execution. Internal canonical writers remain inaccessible except to their
reviewed wrapper. No new direct table grant is added; affected canonical tables
remain forced-RLS and RPC-only.

The exact existing disabled defaults remain authoritative, including
`CONFIDENT_MOMENT_BUNDLE_V1_ENABLED=false`,
`ROOTING_COVERAGE_V1_ENABLED=false`, every PAM gate false, and every collection,
dataset-release, training, evaluation and promotion gate false. All rows created
under this work remain structurally `dataset_eligible=false`; transport success
does not change serving or learning eligibility.

No new Manager item, family, response meaning, exposure system, coach judgment,
root qualification, exercise record, practice outcome, learning label, dataset
row or ninth learning surface is created.

## 9. Required executable regressions

Implementation review must include:

1. Bundle projection and requests contain no `feedback_id` or `candidate_key`.
2. Each family's closed vocabulary maps to exactly the existing canonical
   decision; unknown, foreign-family and `edit_myself` mutation attempts reject.
3. Missing, foreign, stale or sibling D15 exposure/render receipt rejects with
   zero response. Exact confidence replay returns one owner response and one
   service binding; rewrite/praise return one decision and null V3 IDs.
4. Cross-principal, cross-Bundle, cross-attachment and changed-idempotency replay
   reject without partial compatibility or canonical decisions.
5. A root action accepts only the exact response/decision/revision source matrix;
   a correction-decision UUID can never occupy `source_owner_response_id`.
6. Ideal Text edit, parts and all part revisions commit atomically or all roll
   back. Exact replay returns the same revision IDs. Concurrent/stale versions,
   missing/duplicate target part, malformed parts and bigint values greater than
   `2^53` are covered. JSON number coercion rejects.
7. Before complete-batch reveal, Bundle coach context and authoring are absent.
   After reveal, exactly matched attachments appear once in canonical order.
   Foreign, ambiguous and stale Bundle lineage fails closed.
8. Browser-supplied `blind_judgment_id` rejects. Derived judgment mismatch,
   reviewer revocation, assignment invalidation and source deletion reject in
   both race orders with no revision or delivery. Exact unchanged replay returns
   the original atomic pair.
9. Original passage exact text/hash succeeds; sibling swap, changed text/hash,
   missing evidence and pre-reveal coach access reject.
10. Summary covers no update, unread update, read update and mixed attachments.
    Unread always implies existence; rendering changes unread only.
11. Recursive closed-schema validation includes the required D16
    `source_passage` key on the D13 section 6 item row as amended by D14
    section 2 and D15 section 3. Response-hash, grant/revoke, RLS, direct-write,
    deletion traversal, caller-registry, apply/reapply and atomic-negative-
    rollback tests remain green.
12. No judgment, qualification, improvement, adequacy, outcome, exercise,
    dataset, training, evaluation, promotion or new learning-surface row is
    fabricated.

## 10. Stop conditions

Stop implementation and request ML/data interface review if any proposed code:

- exposes or asks the browser to infer `feedback_candidates.candidate_key`;
- fabricates a V3 owner-response ID from a correction, praise or other decision;
- uses document version, timestamp, `MAX(id)` or a post-write latest-row query as
  Ideal Text revision provenance;
- cannot make the Bundle-origin Ideal Text edit and its part revision atomic;
- exposes or accepts `blind_judgment_id` merely to complete D14 authoring;
- cannot join the post-reveal source to exactly one Bundle attachment;
- reconstructs the original passage by text matching or generated output;
- derives either summary coach-update flag in the browser;
- weakens D11–D15 locks, currentness, blindness, RLS/RPC-only, deletion,
  authorization, AC-9, Manager-budget, non-serving or non-learning boundaries;
  or
- numbers a migration, commits, pushes, deploys, activates collection, or
  changes a dataset/training/evaluation/promotion gate without separate approval.

`VERDICT: D16 PROPOSED FOR ML/DATA INTERFACE REVIEW; EXECUTABLE WORK BLOCKED`
