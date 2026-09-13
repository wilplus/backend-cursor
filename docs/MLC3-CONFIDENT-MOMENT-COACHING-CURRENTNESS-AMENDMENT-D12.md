# MLC-3 Confident Moment Coaching Bundle — Per-item Currentness Amendment D12

**Status:** proposed narrow interface amendment for Product/ML-data and
Engineering review. It authorizes no executable change, migration numbering,
commit, push, merge, deployment, activation, collection, dataset creation,
training, evaluation, promotion, or serving.

## 1. Bound authority and narrow purpose

This amendment is bound to:

- accepted Contract Delta D3 SHA-256
  `59c4bad81e1b0a4917d76ce27f48b9a049ca29ea5ba94ad0829ba9ed5650dc67`;
- accepted Interface Manifest D6 SHA-256
  `73514e30005c4b780011f5b6e1631b4c9bb3c3d1f087afea8408bf24df0f15b2`;
  and
- accepted Interface Manifest D11 SHA-256
  `ec2d92bed3a0da354b4ecfd0051d68677e83f9f0d40382c9e3d9678c287c49ea`.

D12 changes only how Feedback Language wording and coach-update currentness are
represented and acknowledged when one Bundle contains more than one attached
Manager-selected item. D6's singular Bundle-level `coach_update` cannot name
the revision, delivery, presentation and rendered exposure for two different
coach-resolved attachments. Folding several attachments into one revision ID
is therefore prohibited.

D12 does not change candidate inventory, Manager selection or budget, Feedback
family, Bundle anchoring, progressive disclosure, response/learning semantics,
rooting, exercise routing, coach blindness, or the eight accepted learning
surfaces. It does correct the already-required D3 family-to-presentation routing:
a selected `rewrite_clarity` item with an observation but no replacement is an
actionable Comment, not an exclusion. It creates no Manager slot, candidate,
judgment, label, outcome, dataset row, or learning surface.

## 2. Canonical unit of currentness

The canonical user-visible Feedback Language unit is one exact
`confident_moment_bundle_attachments.id`. Each projection contains exactly one
`feedback_language_items[]` entry for every attachment, including machine
fallback and typed exclusion entries. An entry may never carry a revision,
delivery, presentation, exposure, wording, or unread state belonging to another
attachment.

The immutable identity of one entry is:

```text
projection_id
+ bundle_attachment_id
+ feedback_membership_id
+ bundle_subject_candidate_id
+ attached_candidate_id
+ attached_evidence_span_id
+ canonical_position
```

For coach-resolved wording, that identity additionally binds the exact current:

```text
feedback_revision_id
+ feedback_revision_sha256
+ revision_delivery_id
+ delivery_subject_sha256
+ canonical_presentation_id
+ rendered_exposure_id nullable
```

The database derives every identity. Neither browser nor route may choose an
attachment's output kind, comment purpose, wording origin, current revision,
current delivery, presentation, exposure, or unread state.

## 3. Authoritative response shape

`project_confident_moment_bundles_v1` remains the sole projection RPC and the
existing user GET route remains unchanged. The response is additively extended
with `feedback_language_shape_version` and the authoritative per-Bundle
`feedback_language_items` array:

```json
{
  "contract_version": "confident-moment-coaching-bundle-v2",
  "feedback_language_shape_version": "feedback-language-items-v1",
  "bundles": [
    {
      "bundle_id": "uuid",
      "feedback_language_items": [
        {
          "bundle_attachment_id": "uuid",
          "attached_candidate_id": "uuid",
          "canonical_position": 1,
          "resolution_state": "coach_revision",
          "exclusion_reason": null,
          "output": {
            "output_kind": "comment",
            "comment_purpose": "confidence_explanation",
            "text": "Concise wording",
            "origin": "coach"
          },
          "coach_update": {
            "current_revision_id": "uuid",
            "revision_sha256": "64-lowercase-hex",
            "revision_delivery_id": "uuid",
            "delivery_subject_sha256": "64-lowercase-hex",
            "presentation_id": "uuid",
            "rendered_exposure_id": null,
            "unread": true
          }
        },
        {
          "bundle_attachment_id": "uuid",
          "attached_candidate_id": "uuid",
          "canonical_position": 2,
          "resolution_state": "machine_fallback",
          "exclusion_reason": null,
          "output": {
            "output_kind": "rephrase",
            "comment_purpose": null,
            "text": "Exact frozen Manager wording",
            "origin": "machine"
          },
          "coach_update": null
        }
      ],
      "exercise": null,
      "state_revision": 1
    }
  ]
}
```

The array is ordered by attachment canonical position, then attached candidate
UUID bytes. `output` is either one exact typed Comment or Rephrase object, or
null for an excluded item. `resolution_state` remains closed to
`coach_revision|machine_fallback|excluded`. Excluded entries carry one typed
`exclusion_reason`, `output=null`, and `coach_update=null`.

### 3.1 Zero-delivery and null semantics

- Zero valid current coach deliveries for an attachment yields its exact frozen
  Manager machine output and `coach_update=null`.
- Exactly one valid current scheduled delivery whose revision is the one valid
  current revision head yields `resolution_state=coach_revision` and a complete
  non-null `coach_update` object.
- A usable coach delivery requires exactly one canonical, non-shadow
  presentation for that exact revision, recipient and learning surface. Zero or
  multiple such presentations is typed fatal projection invalidity; the
  browser is never given an update it cannot acknowledge exactly.
- Before render, `rendered_exposure_id=null` and `unread=true`.
- After the one exact authenticated rendered exposure exists,
  `rendered_exposure_id` is that exposure and `unread=false`.
- Multiple rendered-exposure heads, cross-presentation exposure, multiple
  revision/delivery heads, a fork, stale authority, or broken lineage is typed
  fatal projection invalidity. UUID or timestamp order must not choose a winner.
- An explicit current invalidation remains the D11 typed excluded item and does
  not fall back to machine wording.

Machine fallback and excluded entries never carry revision, delivery,
presentation, exposure, or unread values through hidden parallel fields.

### 3.2 Legacy singular fields

The singular Bundle-level `coach_update`, `comment`, and `rephrase` are retired
and omitted from the v2 response. No deterministic compatibility projection is
possible: D3 permits one Bundle to contain both an actionable Comment from
`rewrite_clarity` without replacement text and a praise Comment from
`great_formulation`; one singular Comment slot must discard a Manager-approved
item. Multiple coach-resolved attachments likewise cannot share one exact
revision/delivery/presentation/exposure identity.

This is therefore an explicit response-version boundary, not a nullable v1
compatibility mode. `contract_version=confident-moment-coaching-bundle-v2` is
mandatory. A client must reject an unknown contract version before rendering;
it may not treat missing v1 singular fields as empty content. New frontend code
renders only `feedback_language_items`. Because all product gates are disabled,
backend and frontend must be released together before any later activation.

## 4. Stable first-paint summary

The existing summary remains intentionally aggregate and contains no revision,
delivery, presentation or exposure identity. For each Bundle:

```text
has_unread_coach_update = EXISTS(
  feedback_language_item where
  resolution_state = coach_revision and coach_update.unread = true
)
```

This is an existential display hint only. Rendering or acknowledging one item
cannot clear the Bundle marker while any other current coach-resolved item is
unread. A Bundle with zero coach-resolved items reports false. The summary and
full Bundle projection must still derive from the same stabilized database
snapshot and retain their separate hashes.

## 5. Independent render acknowledgement

The existing HTTP path remains:

```http
POST /v2/user/confident-moment-bundles/{bundle_id}/coach-updates/{revision_id}/render
```

Its request is narrowed to one exact array item:

```json
{
  "bundle_attachment_id": "uuid",
  "revision_delivery_id": "uuid",
  "presentation_id": "uuid",
  "render_instance_id": "uuid",
  "idempotency_key": "non-empty-string"
}
```

The route derives the authenticated recipient and passes all other identity to
the database. The browser may copy only the IDs returned together in that
item's `coach_update` object; it may not combine IDs from different entries.

Replace the runtime render boundary with:

```text
ack_feedback_language_revision_render_v2(
  p_recipient_principal_id uuid,
  p_bundle_attachment_id uuid,
  p_revision_id uuid,
  p_revision_delivery_id uuid,
  p_presentation_id uuid,
  p_render_instance_id uuid,
  p_idempotency_key text
) -> jsonb
```

PostgreSQL derives membership, candidate, subject Bundle, Project, Take,
reviewer, output kind and learning surface from immutable lineage. It requires
all supplied identities to describe the same current attachment item, current
revision head, current scheduled delivery head and canonical presentation.
The load-bearing attachment invariant is the existing unique
`(feedback_membership_id, attached_candidate_id)` constraint on
`confident_moment_bundle_attachments`: after PostgreSQL derives the exact live
membership, the candidate identifies exactly one attachment. The v2 guard must
also accept and verify `p_bundle_attachment_id`; relaxing that uniqueness or
removing the explicit attachment check is a contract change requiring review.
`ack_feedback_language_revision_render_v1` becomes runtime-inaccessible and is
retained only if an existing internal migration/replay dependency requires it;
it cannot be a second user path. Manifest D11's exact caller registry must be
updated so `ConfidentMomentBundleRepository.ack_revision_render` calls v2 only.

The pending migration's independent closed writer registries must be updated in
the same change: exact `expected_functions` signatures, affected proname set,
overload count, grants/revokes, and static caller tuple must name v2 and leave no
runtime v1 path. Fresh apply and reapply must succeed with the updated registry;
missing, extra, obsolete, or overloaded writers fail closed.

One visible item acknowledgement creates or exactly replays one canonical
`ml_rendered_exposures` receipt for that exact presentation. It does not mark
another attachment read, mutate delivery/revision wording authority, create a
response, or update a Bundle-wide read flag. Reusing an idempotency key with a
changed attachment/revision/delivery/presentation/render identity is a conflict.

## 6. Serialization, projection succession and replay

D11's global lock order and staged A3 discovery protocol remain unchanged. The
stabilized inventory hash must include, separately for every attachment, the
exact current revision, delivery, presentation and zero-or-one exposure
identity. There is no Bundle-level folded currentness leaf.

The v2 render RPC acquires the same D11 serializers in the same order for the
derived principal, Project, Take, membership, Bundle subject, candidate,
delivery subject and revision head, followed by the canonical presentation/
exposure writer lock. It revalidates before and after the potentially blocking
exposure write:

- recipient D4 service access and same-receipt service purposes;
- current reviewer access and exact blind assignment/source authority;
- live membership, candidate/output hash, attachment and Bundle subject;
- current unsuperseded revision and scheduled delivery heads;
- exact source retention, deletion, purge and media state; and
- exact presentation payload/surface plus zero-or-one canonical exposure.

If projection wins the locks before render, it may return only the fully
validated pre-render snapshot with that one item unread. The render waits; a
later projection has a different stabilized inventory hash and freezes an
immutable successor with that item read. If render wins first, projection
returns only the post-render snapshot. A discovered identity-set change returns
only `CONFIDENT_MOMENT_PROJECTION_RETRY_REQUIRED`; no mixed response is allowed.

Exact projection replay repeats the full lock/revalidation boundary. Exact
render replay returns the same exposure only while every authority, source,
head and identity leaf remains current. Supersession, invalidation, deletion,
purge, quarantine or authority withdrawal fails closed even for an otherwise
exact idempotency key. Historical projections and exposures remain immutable.

## 7. Frontend implications

- The data model and reducer key each Feedback Language item by
  `bundle_id + bundle_attachment_id + state_revision`, never text, output kind,
  revision ID alone or array position.
- The overlay renders typed output from `feedback_language_items` in canonical
  order while retaining D3's one-highest-priority-unresolved-correction
  progressive disclosure rule.
- Each coach-resolved item's buzz/read affordance comes only from that item's
  `coach_update.unread`. Bundle opening alone acknowledges nothing.
- When an exact coach-updated item becomes authentically visible, the existing
  viewport/two-painted-frame boundary sends that item's exact v2 render request.
  An unmounted or not-visible item creates no exposure.
- Successful acknowledgement updates only the matching item to read. The
  Bundle-level marker remains while any sibling item is unread.
- A 409 projection retry reloads the complete projection. Foreign, stale,
  authority, deletion and source failures remain fatal/fail-closed and are not
  converted to an empty success.
- `exercise=null` continues to mean only “not supplied by this projection.”
- No user-visible score, rank, coach judgment, qualification, reviewer identity
  or internal currentness reason is added.

## 8. Required executable regressions

### 8.1 Response cardinality and lineage

1. One Bundle with a coach Comment and a different coach Rephrase returns two
   ordered items, each carrying only its own revision, delivery, presentation,
   exposure and unread state.
2. Repeat with both revisions authored by the same coach and by two different
   currently authorized coaches; identity remains attachment-scoped.
3. Reverse attachment order and output kinds; no first/last fold changes either
   item's values.
4. Mix coach-updated, machine-fallback and explicitly invalidated attachments in
   every order; no leaf leaks and exactly one projection item exists per
   attachment.
5. A `rewrite_clarity` attachment with an observation and no replacement is an
   `actionable_observation` Comment item, not `machine_output_invalid`; in the same Bundle a
   `great_formulation` praise Comment is also present and independently
   addressable.
6. Cross-bind A's revision with B's delivery/presentation/exposure at the table,
   RPC and HTTP boundaries; all fail atomically.
7. Zero valid delivery returns machine wording plus `coach_update=null`.
   Explicit invalidation returns exclusion, not machine fallback.
8. Zero/multiple canonical presentations, multiple exposure heads, forked
   revision/delivery chains, foreign reviewer/source lineage and stale output
   hashes fail the whole projection with no payload.
9. The response hash changes when any one item's currentness leaf changes and
   exact unchanged replay returns byte-identical Bundle and summary objects.

### 8.2 Independent visibility and summary

1. Two unread coach items produce `has_unread_coach_update=true`.
2. Rendering A creates exactly one exposure for A, leaves B without exposure,
   and the successor projection reports A read, B unread and summary true.
3. Rendering B then reports both read and summary false. Reversing render order
   yields the equivalent per-item result.
4. Visible A plus unmounted B creates one exposure only. Silence, dismissal,
   skip and timeout create no exposure or response for B.
5. Exact render retry reuses the same exposure. Missing, foreign, stale or
   cross-item identities fail with no second exposure.
6. A machine-only sibling never inherits an unread flag, presentation or
   exposure from a coach-updated item.

### 8.3 Concurrency and invalidation

1. Force both commit orders for projection versus render of A while B is
   unread; only complete pre-render or post-render snapshots may return.
2. Force both commit orders for A render versus A revision supersession,
   delivery supersession/invalidation, reviewer-access withdrawal, recipient
   authority withdrawal, source deletion/purge and media invalidation. The
   invalidation-winning order creates no exposure; the render-winning order may
   create only the fully validated historical exposure before the writer
   proceeds.
3. Concurrent renders of A and B are deadlock-free, create one exact exposure
   per item and never exchange idempotency or payload hashes.
4. Identity change between staged discovery and fine-lock acquisition produces
   the one typed retry and no mixed/newly discovered unlocked item.

### 8.4 Security and learning fences

- Only `service_role` may execute v2 through the reviewed repository route;
  `PUBLIC`, `anon` and `authenticated` cannot execute it. V1 is inaccessible to
  all runtime roles.
- No runtime role receives direct read/write privileges on canonical projection,
  delivery, revision, presentation or exposure tables; forced RLS and RPC-only
  writes remain.
- Static caller extraction contains exactly the updated repository-method-to-v2
  tuple and no v1 runtime caller or direct `.table(...)` Bundle read.
- The pending migration's exact function/proname/overload registry matches v2;
  fresh apply and reapply pass, while missing/extra/obsolete overload controls
  fail closed.
- Projection/render create no response, Manager item, root, exercise, practice,
  comparison, adequacy, judgment, dataset, training or learning-surface row.
- `serves_user=false`, `dataset_eligible=false`, all bundle/root/PAM and learning
  gates, and the unnumbered/unmanifested migration state remain unchanged.

## 9. Decision filter

```text
VERDICT:  ADVANCE-F2 FOR INTERFACE REVIEW
CATEGORY: F2
WHY:      D12 replaces an ambiguous Bundle-wide currentness fold with exact
          attachment-scoped wording and render provenance while preserving the
          accepted Manager, exposure, blindness and learning boundaries.
REDIRECT: Obtain Product/ML-data and Engineering interface acceptance, update
          the executable manifest/caller registry, then correct Chunk 2B and
          Chunk 3 locally behind disabled gates.
```

`FILTER: ADVANCE-F2 — cat F2 — fences clear — locks clear at the proposed
interface level — redirect: accept and re-freeze before executable edits.`
