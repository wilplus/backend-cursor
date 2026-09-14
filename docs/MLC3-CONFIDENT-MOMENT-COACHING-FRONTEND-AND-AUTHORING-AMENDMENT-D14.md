# MLC-3 Confident Moment Coaching Bundle — Frontend and Authoring Amendment D14

**Status:** proposed narrow executable-interface amendment for Product/ML-data
and Engineering review. It authorizes no executable edit, migration numbering,
commit, push, merge, deployment, activation, collection, dataset creation,
training, evaluation, promotion, or serving.

## 1. Bound authority and purpose

D14 is bound to:

- accepted Contract Delta D3 SHA-256
  `59c4bad81e1b0a4917d76ce27f48b9a049ca29ea5ba94ad0829ba9ed5650dc67`;
- accepted Interface Manifest D11 SHA-256
  `ec2d92bed3a0da354b4ecfd0051d68677e83f9f0d40382c9e3d9678c287c49ea`;
- accepted Per-item Currentness Amendment D12 SHA-256
  `0f6a9e9f7068c4881f0bb728033d62ee6ac80c9766dd5eecd14cd6630e7a86ea`;
  and
- accepted Render Identity and Transport Amendment D13 SHA-256
  `23def906f8ad310a65ef40529b14b9230cc87f40544eec2000eae069ea69e21d`.

D14 freezes only the remaining Chunk 4/5 transport and ownership seams. It does
not change the Manager inventory or three-item budget, a Feedback family,
confidence meaning, L1/L2/L3, AC-9, blind judgment, exercise eligibility,
root qualification, dataset eligibility, or any learning surface.

## 2. Per-item presentation and family identity

This section explicitly amends D13 section 6's closed Feedback Language item
row and cross-object invariants. Each object in `feedback_language_items` returned by
`project_confident_moment_bundles_v1` additionally contains exactly:

```json
{
  "feedback_family": "confident_voice|rewrite_clarity|great_formulation",
  "canonical_feedback_presentation_id": "uuid"
}
```

These are required non-null fields on every non-excluded and excluded attachment
because they identify the already-selected Manager item and its prepared
canonical presentation; exclusion does not erase provenance. They join exactly
to that item's attachment membership, attached candidate and evidence span.
They may not be copied from a sibling or inferred from `output_kind`, Comment
purpose, visual treatment, Bundle subject kind, or array position.

`canonical_feedback_presentation_id` is the exact prepared V3 presentation used
by the D13 Bundle-item render boundary. It is not a rendered exposure. It must
equal the attachment's frozen presentation identity, and its canonical family
must equal `feedback_family`. A duplicate presentation across different items,
or a family/presentation/candidate mismatch, is fatal projection invalidity.
Presentation IDs are unique across projection items, and every item's
`feedback_family` equals the canonical family bound to that exact prepared
presentation.

The browser uses `feedback_family` only to dispatch the item's later explicit
answer to the already-reviewed family-specific response boundary. It does not
create a generic Bundle response, translate one family's answer into another,
or treat selection/render as an answer. The response still requires the exact
canonical rendered exposure created for this presentation. Silence, Cancel,
dismissal and timeout remain unanswered.

D13's recursively closed projection schema and response hash include these two
fields. Stable first paint and the full Bundle response come from the same
database projection; no application-side lookup may supplement them.

## 3. Owner root-action HTTP boundary

### 3.1 Public route and caller identity

The sole user HTTP route is:

```http
POST /v2/user/confident-moment-bundles/{bundle_id}/root-actions
```

The exact application caller is:

```text
services/confident_moment_bundle_repository.py::ConfidentMomentBundleRepository.record_root_action
  -> record_confident_moment_bundle_root_action_v1
```

Add one database wrapper:

```text
record_confident_moment_bundle_root_action_v1(
  p_acquisition_principal_id uuid,
  p_bundle_id uuid,
  p_bundle_attachment_id uuid,
  p_action text,
  p_expected_block_head_action_id uuid,
  p_source_feedback_exposure_id uuid,
  p_source_owner_response_id uuid,
  p_source_practice_attempt_id uuid,
  p_source_ideal_text_revision_id bigint,
  p_source_target_speaker_binding_id uuid,
  p_practice_target_speaker_binding_id uuid,
  p_restore_product_action_id uuid,
  p_policy_version text,
  p_idempotency_key text
) -> jsonb
```

The wrapper is `SECURITY DEFINER`, service-role-only, and the only
application-callable root mutation. It loads the exact attachment and derives
Project, Take, Paragraph, block, selected candidate, evidence and current root
content from immutable database lineage. It verifies `bundle_id` against the
attachment before and after contention, applies D11/D12/D13 serializers and
live authority/deletion/currentness checks, then calls
`record_root_phrase_product_action_v2` in the same database transaction.
Browser-supplied principal, Project, Take, Paragraph, block, candidate, evidence,
origin, persistence, qualification, action revision or root content is never
accepted as authority. `record_root_phrase_product_action_v2` becomes
runtime-inaccessible and remains an internal canonical mutation primitive.

### 3.2 Closed request

The path UUID and every UUID use D13's canonical lowercase transport rule. The
request has exactly these keys; nullable fields must be explicit JSON null:

```json
{
  "bundle_attachment_id": "uuid",
  "action": "save_owner_selected_root|lock_current_root|restore_previous_root|unlock_current_root|remove_current_root",
  "expected_block_head_action_id": null,
  "source_feedback_exposure_id": null,
  "source_owner_response_id": null,
  "source_practice_attempt_id": null,
  "source_ideal_text_revision_id": null,
  "source_target_speaker_binding_id": null,
  "practice_target_speaker_binding_id": null,
  "restore_product_action_id": null,
  "policy_version": "rooting-coverage-30-80-100-v1",
  "idempotency_key": "non-empty-string"
}
```

`source_ideal_text_revision_id`, when non-null, is a canonical positive base-10
integer string in HTTP JSON so JavaScript cannot round a PostgreSQL bigint; the
backend alone parses it to bigint. Number, exponent, sign, leading zero, float,
boolean or object rejects.

The closed D6 source matrix remains authoritative:

- `save_owner_selected_root` is the only public action behind **Save the text**.
  Transcript/Ideal-Text selection carries the exact item exposure and owner
  response when that is its source. A re-record selection additionally carries
  the exact practice attempt and both exact active same-speaker bindings. Manual
  text uses its exact Ideal Text revision. The database derives and validates
  every remaining source identity.
- `lock_current_root` is the existing frontend lock action, with every source
  field and restore ID null.
- `restore_previous_root` requires only a non-null
  `restore_product_action_id`; every source field is null. It is available only
  during the current post-Take review and restores a live previous root.
- `unlock_current_root` and `remove_current_root` have every source field and
  restore ID null.
- `activate_automatic_root` has no public browser route. It remains a
  server-owned deterministic coverage operation.
- **Cancel** performs no request and creates no event, action, response,
  dismissal, label or state transition.

Illegal null combinations reject before a write. Exact retry repeats all live
checks and returns the same action. A changed path, attachment, action, head,
source, binding, revision, restore target, policy or idempotency identity is a
replay conflict.

### 3.3 Closed response and projection root state

The wrapper returns exactly:

```json
{
  "root_action_contract_version": "confident-moment-root-action-v1",
  "bundle_id": "uuid",
  "bundle_attachment_id": "uuid",
  "product_action_id": "uuid",
  "active_root_action_id": null,
  "interaction_state_revision": "1",
  "is_orange": false,
  "is_locked": false,
  "can_restore_previous": false,
  "restore_product_action_id": null,
  "dataset_eligible": false
}
```

For an active root, `active_root_action_id=product_action_id`; after remove it is
null. `interaction_state_revision` is a canonical positive base-10 integer
string using the same no-sign, no-leading-zero and no-coercion rule as
`source_ideal_text_revision_id`. No extra key is permitted. Echoed identities and the
booleans must match the post-transition database head.

The projection's closed `root` object adds exact nullable
`active_root_action_id`, canonical positive base-10 string
`interaction_state_revision`, and nullable
`restore_product_action_id`. `can_restore_previous` is true exactly when that
restore ID is present and live. The browser neither computes revisions nor
searches root history. On HTTP 409 stale/retry it discards optimistic state and
reloads the entire canonical projection.

## 4. Post-reveal coach Feedback Language authoring

### 4.1 Placement and blindness

Coach authoring is mounted only inside the existing post-reveal feedback area
below the coach's completed blind judgment. Before complete-batch reveal, the
component, request and authoring context do not exist. It never shares state
with, preloads text into, or changes the blind five-state answer. Transcript and
context remain unavailable until the reviewer-specific complete reveal.

The browser never sends reviewer/coach principal, recipient principal, target
Take, anchor candidate, membership, candidate, candidate-output hash, family or
delivery state. Backend authentication derives the reviewer principal; the
database derives all user/source/target identities and verifies current coach
authority, exact blind assignment/judgment, complete reveal, current service
authority, deletion/media state and Bundle lineage after contention.

### 4.2 Atomic endpoint

The sole authoring endpoint is:

```http
POST /v2/coach/confident-moment-bundles/{bundle_id}/attachments/{bundle_attachment_id}/feedback-language
```

Its body has exactly:

```json
{
  "review_batch_id": "uuid",
  "reveal_grant_id": "uuid",
  "reveal_access_id": "uuid",
  "review_assignment_id": "uuid",
  "blind_judgment_id": "uuid",
  "output_kind": "comment|rephrase",
  "comment_purpose": null,
  "revision_text": "non-empty-string",
  "expected_current_revision_id": null,
  "expected_current_delivery_id": null,
  "idempotency_key": "non-empty-string"
}
```

For `comment`, `comment_purpose` is exactly one accepted D3 purpose
(`confidence_explanation`, `actionable_observation`, or `positive_praise`); for
`rephrase` it is null. The purpose must match the exact canonical Feedback
family. Unknown or extra fields reject. The browser cannot choose
current-versus-next Take.

The exact repository caller is:

```text
services/confident_moment_bundle_repository.py::ConfidentMomentBundleRepository.publish_coach_feedback_language
  -> publish_confident_moment_coach_feedback_language_v1
```

The endpoint makes one database call only:

```text
publish_confident_moment_coach_feedback_language_v1(
  p_reviewer_principal_id uuid,
  p_bundle_id uuid,
  p_bundle_attachment_id uuid,
  p_review_batch_id uuid,
  p_reveal_grant_id uuid,
  p_reveal_access_id uuid,
  p_review_assignment_id uuid,
  p_blind_judgment_id uuid,
  p_output_kind text,
  p_comment_purpose text,
  p_revision_text text,
  p_expected_current_revision_id uuid,
  p_expected_current_delivery_id uuid,
  p_idempotency_key text
) -> jsonb
```

This function atomically creates/replays the immutable coach revision and its
delivery successor. Two application RPCs are prohibited because a revision may
not commit without the corresponding current delivery decision.

Under the D11 global lock order it derives exact membership, attached candidate,
candidate output version/hash, acquisition/recipient principal, anchor and
source Take. If the owner's overlay for that source Take is still unresolved,
the delivery targets that exact Take as `scheduled_current_take`. If owner
completion already exists, it resolves the already-created next relevant Take
for the same Project and principal and uses `scheduled_next_take`. If no such
Take exists, it commits the immutable revision with no delivery row; absence is
the routing state, not a fabricated pending delivery. The canonical
later delivery materialization is asynchronous and never runs inside or gates
the F1 Take-promotion transaction. Until then the revision is not projected to
a user, does not buzz, and cannot fall back to a different Take.

When no target Take exists, the atomic coach RPC stores the revision together
with one immutable, forced-RLS, RPC-only
`feedback_language_delivery_materialization_jobs` row. The job is product
routing state with `serves_user=false` and `dataset_eligible=false`; it is not a
delivery, exposure, label or learning event. This table explicitly extends
D11 section 5's forced-RLS, append-only, RPC-only table registry. The exact
internal worker RPC is
`materialize_feedback_language_delivery_job_v1(uuid,text)`. Its only production
caller is
`services/confident_moment_delivery_worker.py::materialize_confident_moment_delivery`.
Both are added to the exhaustive signature/proname/overload, grant/revoke and
AST caller registries. The worker RPC derives the complete identity set, follows
D11 order and holds the exact delivery-subject serializer at 120 and
revision-head serializer at 130 before revalidating the still-current revision,
new Take and absence of a current delivery.

The canonical Take writer remains unchanged and never acquires an F2 lock. It
may enqueue or wake the worker only after its Take transaction commits; enqueue
failure cannot change its returned success. The worker uses a fixed reviewed
finite lock timeout and one bounded attempt, leaving the durable job retryable
on contention or any typed authority/currentness failure. The existing worker
supervisor retries with a bounded schedule and the aggregate monitor reports
age/count only. No raw content enters the job or monitor. Exact worker replay
creates one delivery and marks the job completed through an immutable lifecycle
event; a stale revision is closed without delivery. Neither path can abort,
delay indefinitely or roll back record → process → Ideal Text → next Take.
The exact driver is
`services.confident_moment_delivery_worker.enqueue_confident_moment_delivery`
through `services.job_queue.enqueue`; Railway's existing
`bin/railway-worker.sh -> worker.py -> RQ` entrypoint executes the registered
materializer. The aggregate general-service monitor owns only job count/age and
typed failure-state alerts; it never calls the mutation RPC.

Expected revision and delivery heads are exact nullable concurrency inputs.
Both null is valid only when neither chain exists. A stale expected head, fork,
foreign context, unavailable target, or changed authority fails the entire
transaction. Exact replay revalidates every leaf and returns the original pair;
changed text or context with the same key conflicts.

The response is exactly:

```json
{
  "coach_feedback_language_contract_version": "confident-moment-coach-feedback-language-v1",
  "bundle_id": "uuid",
  "bundle_attachment_id": "uuid",
  "revision_id": "uuid",
  "revision_sha256": "lowercase-sha256",
  "delivery_id": "uuid-or-null",
  "delivery_state": "scheduled_current_take|scheduled_next_take|null",
  "target_take_id": null,
  "dataset_eligible": false
}
```

`delivery_id`, `delivery_state`, and `target_take_id` are all non-null for a
scheduled delivery or all null when no next Take exists. Every key is present,
no extra key is allowed, and the backend passes the validated object through
unchanged. Existing `record_feedback_language_coach_revision_v2`
and `transition_feedback_language_delivery_v2` become internal-only for this
flow and are absent from application callers.

## 5. Frontend ownership and state machine

### 5.1 Shared-file seams

`TranscriptReviewDeck.tsx` owns only Bundle marker placement and opening the
Bundle overlay from the database first-paint summary. It must not fetch Bundle
details per marker, infer attachment/family/root/exercise state, synthesize an
unread flag, or mutate Ideal Text directly.

`DeckLockMark.tsx` is a pure presentation component. It receives distinct
booleans:

```text
hasCoachUpdate := any exact current coach_update exists for this Bundle
hasUnreadCoachUpdate := any such update has unread=true
```

`hasCoachUpdate` controls whether the update affordance remains available after
reading. `hasUnreadCoachUpdate` alone controls buzzing. Reading one item clears
only that item's successor projection unread state; the Bundle keeps buzzing
while any sibling remains unread. A marker with a read coach update remains
openable but does not buzz. The existing orange/root visual is controlled only
by `is_orange`, never by either update boolean.

`ConfidentMomentCoachingBundle.tsx` owns overlay sequencing and local render
instances. For each actually visible item it ACKs the exact item presentation
after the reviewed visibility boundary; a coach-update render is a separate ACK
of its exact revision/delivery/presentation. Opening the Bundle alone ACKs
nothing. Remount/retry reuses the exact render instance/idempotency identity.

The overlay sequence remains D3:

```text
playback + family response
  -> concise Comment
  -> optional Rephrase: [Update the text] [Cancel]
  -> separately correlated exercise, if supplied by canonical MLC-3 service
  -> optional re-record
  -> [Save the text] [Cancel]
```

`Update the text` uses the existing reviewed Ideal Text change boundary; it is
not a root action. `Save the text` is the owner root action in section 3.
`Cancel` is always local/no-write as frozen above. Root restoration is shown
only in current post-Take review as **Restore previous version** and disappears
after leaving that review.

Coach components own only post-reveal Comment/Rephrase editing and submission.
They do not edit `TranscriptReviewDeck.tsx`, `DeckLockMark.tsx`, the blind answer
component, or canonical exercise composer behavior. Integrator-owned adapters
mount the new components at these seams; delegated chunks do not concurrently
edit the same shared host files.

### 5.2 Stable events

Closed frontend events are:

```text
SUMMARY_RECEIVED
BUNDLE_OPENED
ITEM_VISIBLE
ITEM_RENDER_ACKED
FAMILY_RESPONSE_SUBMITTED
UPDATE_TEXT
TEXT_UPDATE_CONFIRMED
EXERCISE_CORRELATED
EXERCISE_PLAYBACK_CONFIRMED
RERECORD_COMPLETED
SAVE_TEXT
ROOT_ACTION_CONFIRMED
RESTORE_PREVIOUS
UNLOCK_ROOT
REMOVE_ROOT
COACH_UPDATE_VISIBLE
COACH_UPDATE_RENDER_ACKED
CANCEL
PROJECTION_RETRY_REQUIRED
```

No event name itself is persisted as a label. Database receipts/actions remain
the authority. `PROJECTION_RETRY_REQUIRED` and any stale root head cause a full
projection reload, not local reconciliation.

## 6. Exercise correlation remains separate

The Bundle projection returns `exercise: null` exactly as D11–D13 require. This
means only “not supplied by this projection.” It is never mapped to no-match,
ineligibility, absence, helped/not-helped, or a learning signal.

Exercise offer/assignment/media is fetched only through the already-reviewed
canonical `/v2/user/mlc3/*` service route. The client may show an exercise in a
Bundle only when that response carries the exact same acquisition principal,
Project, Take, feedback membership, source candidate/evidence or review
assignment lineage required by the existing MLC-3 contract. Correlation is an
exact identity join, not matching by Slide, snippet, text, timing, array index,
need name or visual proximity. Missing or conflicting correlation shows no
exercise section in this overlay, but is not recorded or reported as no-match.

Playback, re-record and practice evidence continue exclusively through the
canonical MLC-3 route. Bundle code does not create an exercise offer,
assignment, catalogue entry, media URL, playback, practice attempt, comparison,
adequacy or outcome row.

## 7. Gates and permissions

All new backend routes fail closed before auth, database or storage access when
`CONFIDENT_MOMENT_BUNDLE_V1_ENABLED=false`. Root actions additionally require
`ROOTING_COVERAGE_V1_ENABLED=false` to be changed by a separate activation.
Frontend Bundle and coach-authoring presentation gates have literal absent/off
defaults. No gate aliases, environment fallbacks or broad MLC-3 flag may enable
them.

The two public wrappers and the internal worker RPC are executable only by
`service_role` through their exact registered callers; all underlying
mutation primitives and every table remain inaccessible to `PUBLIC`, `anon`,
`authenticated`, and direct `service_role` writes. RLS is enabled and forced.
Every new and existing row remains `serves_user=false` and
`dataset_eligible=false` in disabled scope. No dataset release, training,
evaluation, promotion or learned serving path is added.

## 8. Required implementation regressions

### 8.1 Projection and response identity

1. Every attachment returns its own exact family and prepared presentation;
   swapped sibling, duplicate, missing or mismatched identities reject.
2. Item render uses that exact presentation and later family response requires
   its exact rendered exposure; preparation/open/dismissal creates no response.
3. First-paint and full projection hashes include both fields and remain one
   database snapshot.

### 8.2 Root actions

1. Test every legal D6 source-matrix row and every illegal null/cross-source
   combination through the exact HTTP route and wrapper RPC.
2. Cross-Bundle, foreign attachment, principal, Project/Take/Paragraph/block,
   stale head, stale Ideal Text revision, stale practice/binding, deletion,
   authority withdrawal and changed replay fail atomically with no partial root
   or Ideal Text action.
3. Exact replay returns one action/head. Concurrent save/lock/restore/remove has
   one valid winner and follows the global lock order without deadlock.
4. Cancel produces zero HTTP call and zero database row. Automatic activation
   is absent from the user route.
5. Both bigint strings (`source_ideal_text_revision_id` and
   `interaction_state_revision`) round-trip exactly, including values above
   JavaScript's safe integer range; unsafe numeric/coercive inputs reject.

### 8.3 Coach authoring and delivery

1. Before incomplete batch reveal, no component/context/request exists and the
   RPC rejects. Exact post-reveal authoring creates one revision and one current
   delivery decision atomically.
2. Reviewer identity is derived from authenticated coach mapping; supplying or
   spoofing coach/user/target/candidate identity is impossible at HTTP.
3. Comment/Rephrase/purpose matrix, expected heads, exact retry and changed
   replay are enforced. Revision failure creates no delivery; delivery failure
   creates no revision.
4. Owner unresolved versus completed routes deterministically to current,
   existing next, or one durable materialization job. Fresh apply/reapply
   verifies the updated exhaustive writer/caller registry. Take promotion
   succeeds unchanged when materialization is stale, unauthorized, deleted,
   purged, contended or unavailable. A held 120/130 lock cannot block it.
   Bounded worker retry materializes the still-current revision once and creates
   no second delivery; concurrent worker versus coach transition has one current
   head and no deadlock.
5. Reviewer/recipient authority withdrawal, deletion/purge, candidate-output
   change, reveal revocation and contention fail closed with no partial pair.
6. Coach update existence and unread are distinct in mixed sibling order;
   rendering changes only unread and never wording authority.

### 8.4 Frontend and exercise separation

1. Viewport/render regressions prove invisible/unmounted items create no ACK;
   visible retry is idempotent; item and coach-update receipts never cross-bind.
2. `TranscriptReviewDeck` consumes only first-paint markers;
   `DeckLockMark` renders all combinations of orange/locked/update/unread without
   conflating them.
3. Update, Save, Cancel and restore labels/actions follow section 5 exactly.
4. `exercise=null` triggers no no-match UI/event. Only an exact canonical MLC-3
   correlation can render exercise media; foreign or absent correlation cannot.
5. Static caller extraction matches the closed new RPC tuples and proves no
   direct table, retired RPC, supplemental projection or dynamic RPC access.

## 9. Stop conditions

Implementation stops for re-review if the existing Ideal Text update boundary
cannot return the exact revision needed by Save, if the bounded asynchronous
delivery worker/job cannot preserve the F1 live loop under contention/failure,
or if the existing MLC-3 response lacks sufficient immutable identities for
exact exercise correlation. Engineering must not fill any of those gaps with
client inference, timestamps, text matching, a second response/exposure system,
or a best-effort write.
