# MLC-3 Confident Moment Coaching Bundle — Feedback Exposure Identity Amendment D15

**Status:** proposed narrow correction for Product/ML-data and Engineering
interface review. It authorizes no implementation, numbering, commit, push,
merge, deployment, activation, collection, dataset, training, evaluation,
promotion, or serving.

## 1. Bound scope

D15 binds accepted D3, D11, D12, D13 SHA-256
`23def906f8ad310a65ef40529b14b9230cc87f40544eec2000eae069ea69e21d`,
and accepted D14 content. It corrects one semantic naming conflict discovered by
executable integration: for a Feedback V3 Manager item, the prepared canonical
render identity is `feedback_exposures.id`. It is not `ml_presentations.id`.
The current Bundle-item wrapper echoes this same UUID as both `presentation_id`
and `feedback_exposure_id`, while D13 correctly rejects arbitrary identity
aliasing. A database exposure can therefore commit while HTTP reports failure.

## 2. Exact replacement boundary

D15 explicitly amends accepted D13 section 2 (Bundle-item RPC identity and
signature), section 3 (exact Bundle-item request keys), and section 5 (the
closed Bundle-item receipt schema).  In each of those clauses,
`feedback_exposure_id` supersedes the misnamed `presentation_id`; the shapes
below are the single authoritative closed schemas for this path.

Replace only the Bundle-item render RPC with:

```text
ack_confident_moment_bundle_item_render_v3(
  p_acquisition_principal_id uuid,
  p_bundle_id uuid,
  p_bundle_attachment_id uuid,
  p_feedback_exposure_id uuid,
  p_render_instance_id uuid,
  p_idempotency_key text
) -> jsonb
```

The exact body keys are:

```json
{
  "bundle_attachment_id": "uuid",
  "feedback_exposure_id": "uuid",
  "render_instance_id": "uuid",
  "idempotency_key": "non-empty-string"
}
```

The exact response is:

```json
{
  "render_contract_version": "confident-moment-bundle-item-render-v3",
  "bundle_id": "uuid",
  "bundle_attachment_id": "uuid",
  "feedback_exposure_id": "uuid",
  "render_instance_id": "uuid",
  "render_receipt_id": "uuid",
  "dataset_eligible": false
}
```

`render_receipt_id` and `feedback_exposure_id` are distinct typed identities and
must differ. No `presentation_id` exists in this request or response. The
browser copies `feedback_exposure_id` from the same attachment projection item;
the database proves it is the attachment's exact selected Manager exposure and
derives Project, Take, membership, family, candidate and owner.

The application caller becomes exactly:

```text
services/confident_moment_bundle_repository.py::ConfidentMomentBundleRepository.ack_item_render
  -> ack_confident_moment_bundle_item_render_v3
```

The v1 and v2 Bundle-item wrappers are dropped or inaccessible to all runtime
roles and removed from caller/signature/proname registries. The coach-update render v3 is
unchanged because it genuinely uses `ml_presentations.id` and
`ml_rendered_exposures.id` as distinct identities.

## 3. Projection amendment

D15 amends D13 section 6 and D14 section 2. Every Feedback Language attachment,
including an excluded item, carries exact non-null:

```json
{
  "feedback_family": "confident_voice|rewrite_clarity|great_formulation",
  "canonical_feedback_exposure_id": "uuid"
}
```

The old proposed `canonical_feedback_presentation_id` item key is removed.
Exposure IDs are globally unique across projection items and must join the
attachment's exact membership, candidate, family, selected position and frozen
content identity. The subject's historical
`canonical_feedback_presentation_id` field may remain only as the existing
frozen attachment/subject field whose value is explicitly documented as the
same Feedback V3 exposure identity; application code may not treat it as an ML
presentation or use it for a sibling item.

The item's explicit family and exposure ID are included in item/projection and
response hashes. They give the existing family response boundary its exact
`candidate_id + membership_id + feedback_exposure_id + family` inputs without
supplemental reads or inference.

## 4. Replay and atomicity

Bundle-item v3 follows the complete D11/D12/D13 lock and validation boundary on
new render and exact replay. Before replay return and after a potentially
blocking canonical render write it must re-run the canonical live membership,
current document/snapshot, attachment, selected exposure, source deletion/purge
and D4 service-authority checks. Superseded document head, stale membership,
deleted/purged source, foreign Bundle or changed identity rejects atomically.

Coach-update render v3 exact lost-ack replay must also require the stored
exposure's exact `idempotency_key` to equal the request key. Same presentation
and render instance under a changed key is `FEEDBACK_LANGUAGE_REPLAY_CONFLICT`,
never success.

Application response validation happens before HTTP success. No permitted
database result can commit and then fail merely because two aliases name one
identity; D15 removes the alias.

## 5. Required regressions

1. A real Bundle-item render returns distinct render-receipt and Feedback V3
   exposure IDs and passes the exact route/repository validator.
2. Every attachment in a genuine multi-item/multi-Bundle projection carries its
   own exact family/exposure; sibling swaps and duplicates reject.
3. The exposure then binds the existing exact family response; opening,
   dismissal, silence and timeout create no response.
4. New render and exact replay reject successor document head, stale membership,
   deletion/purge, authority withdrawal and cross-Bundle identity in both race
   orders, with zero partial receipt on the invalidation-winning order.
5. Item-render changed idempotency identity conflicts. Coach-render same
   presentation/render instance with a changed key also conflicts.
6. Fresh apply/reapply proves v3 signatures/grants/callers and v1/v2
   retirement. The registry/static regression treats this section's explicit
   amendment of D13 sections 2, 3, and 5 as the sole closed Bundle-item request
   and receipt contract; an old `presentation_id` key must fail.
   RLS/RPC-only, deletion traversal, AC-9, Manager budget, blindness,
   `serves_user=false`, `dataset_eligible=false` and all disabled gates remain.

## 6. Decision filter

```text
VERDICT:  ADVANCE-F2 FOR INTERFACE REVIEW
CATEGORY: F2
WHY:      D15 names the canonical Feedback V3 exposure once, allowing every
          attachment to render and answer without identity aliasing or reads.
REDIRECT: Accept the correction, then update SQL/application/tests locally and
          re-run combined Chunk 2B/3 implementation review.
```
