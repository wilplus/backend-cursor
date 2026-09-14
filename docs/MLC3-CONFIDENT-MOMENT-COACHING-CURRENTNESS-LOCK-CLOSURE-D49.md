# MLC-3 Confident Moment Coaching Bundle — Currentness and Lock Closure D49

Status: proposed corrective amendment. D49 retains accepted Delta D3, Manifest
D11 and D38–D48 except where explicitly replaced below. No product gate,
dataset, learning surface or activation change is introduced.

## 1. Exact owner-decision binding

The Bundle projection must never infer current owner response by scanning the
three historical decision families directly. Add one append-only canonical
`confident_moment_owner_decision_bindings` relation. Each row binds exactly:

- acquisition principal, Project, Take, membership, Bundle subject, Bundle
  attachment, candidate, family, evidence span, canonical feedback
  presentation, and canonical rendered receipt;
- the exact underlying decision identity: confidence response plus service
  binding, correction decision, or praise-helpfulness decision according to a
  mutually exclusive family check;
- the closed interaction response literal and its existing family taxonomy;
- immutable decision hash and idempotency key; and
- `serves_user=false`, `dataset_eligible=false`.

There is at most one binding per exact Bundle attachment. An exact retry returns
that binding after complete current authority/replay validation. A changed
response or changed identity fails closed; it does not silently supersede the
owner's original answer. Existing decisions outside this Bundle path remain
historical and cannot become Bundle owner-decision state.

`record_confident_moment_bundle_family_response_v1` is the sole writer. It must:

1. acquire the existing rollout/principal and Project/Take inventory serializers
   before reading or writing any underlying decision family;
2. acquire a new exact owner-decision serializer at numeric position 95, before
   root position 100 and Feedback Language positions 110–130;
3. revalidate exact membership, candidate, presentation, render receipt,
   authority and deletion state;
4. create/replay the underlying canonical response and exact Bundle binding in
   one transaction; and
5. revalidate authority after contention and on replay.

Serializer literal:

`confident-moment-owner-decision:<membership_uuid>:<candidate_uuid>:<attachment_uuid>`

The projection acquires every derived position-95 key in canonical UTF-8 byte
order **before every position-110, 120 and 130 Feedback Language key** and
before deriving owner decisions. Its stabilized inventory hashes the
exact owner-decision binding rows, not unbound historical decision tables.
`derive_confident_moment_owner_decision_v1` accepts only one exact current
binding for the requested attachment and validates the referenced canonical
row. Foreign praise sharing an evidence span or rater can never qualify.

The response vocabulary and stored mapping are closed as follows:

| family | public interaction literal | stored canonical column/literal |
| --- | --- | --- |
| `confident_voice` | `yes`, `in_between`, `no`, `not_sure`, `audio_unclear` | `feedback_v3_owner_responses.response`: respectively `confident_yes`, `confident_in_between`, `confident_no`, `confident_not_sure`, `confident_audio_unclear` |
| `rewrite_clarity` | `apply_suggestion`, `keep_wording` | `correction_decisions.value`: respectively `accept_proposed`, `keep_original` |
| `great_formulation` | `useful`, `not_useful`, `not_sure` | `praise_helpfulness.value`: unchanged |

The inverse projection strips the confidence namespace and applies the exact
rewrite inverse above. `rewrite_not_sure` from the separate blind-judgment
taxonomy is not a Bundle owner-response state and cannot qualify or be mapped.
The binding stores both literals and does not create a new label or learning
target. The historical family writers invoked internally by the Bundle writer,
including both exact `record_feedback_human_decision_v1` overloads, are added to
the exhaustive D11 writer/caller registry; overload drift fails migration apply.

The new table enables and forces RLS, permits no direct runtime writes, and is
included in deletion traversal and the D11 writer/caller/permission registries.

## 2. Feedback Language item shape v2

The exact item object is named `feedback-language-items-v2` and contains exactly
these thirteen keys, no more and no fewer:

`bundle_attachment_id`, `attached_candidate_id`, `feedback_family`,
`canonical_feedback_exposure_id`, `canonical_position`, `resolution_state`,
`exclusion_reason`, `source_passage`, `update_text_available`,
`coach_authoring_exclusion_reason`, `output`, `coach_update`, `owner_decision`.

`owner_decision` is either null or the exact five-key D40 object:
`feedback_family`, `response`, `decision_id`, `owner_response_id`,
`response_binding_id`. The separately returned family-response mutation result
remains `confident-moment-family-response-v1` with exactly the nine D16 keys:
`family_response_contract_version`, `bundle_id`, `bundle_attachment_id`,
`feedback_family`, `response`, `decision_id`, `owner_response_id`,
`response_binding_id`, `dataset_eligible`. It is a write acknowledgement, not an
alternative projected item shape.

The Bundle contract remains `confident-moment-coaching-bundle-v2`. SQL, Python,
TypeScript and fixtures must reject v1, mixed, missing, extra or reinterpreted
item shapes. This is a version correction only; it does not change Manager
family membership, budget or user semantics.

The exercise-correlation response, which gained the required
`source_target_speaker_binding_id`, is likewise renamed
`confident-moment-exercise-correlation-v2`. Its exact `not_supplied` keys are
`contract_version`, `status`, `bundle_id`, `bundle_attachment_id`, `offer_id`,
`correlation_sha256`, `dataset_eligible`. Its exact `available` keys are those
first five keys plus `feedback_response_binding_id`, `n1_candidate_set_id`,
`authorization_check_id`, `source_acquisition_receipt_id`,
`source_target_speaker_binding_id`, `correlation_sha256`, and
`dataset_eligible`. No other key is permitted; v1 and mixed shapes fail closed
in SQL, Python and fixtures.

## 3. Canonical target-speaker binding resolver

Add one internal, runtime-inaccessible resolver for the exact tuple:

`(acquisition_principal_id, recording_attempt_id, audio_object_id,
 target_kind, clip_id, practice_attempt_id)`.

`target_kind` is a resolver input, not a new stored column. It must equal
`source_clip` iff `clip_id IS NOT NULL AND practice_attempt_id IS NULL`, or
`practice_attempt` iff `practice_attempt_id IS NOT NULL AND clip_id IS NULL`,
matching the table's existing XOR constraint.

The exact internal function is:

`resolve_confident_moment_target_speaker_binding_v1(uuid,uuid,uuid,text,uuid,uuid) RETURNS jsonb`

with arguments in the tuple order above. The exact successful result contains
only `contract_version='confident-moment-target-speaker-binding-v1'`,
`target_kind`, `acquisition_revision_id`, `target_speaker_binding_id`,
`speaker_id`, and `result_sha256`. UUIDs are canonical lowercase strings in the
JSON result. The hash is the canonical JSON SHA-256 over the first five fields
plus the exact principal, attempt, audio-object, audio-SHA and non-null input
discriminator (`clip_id` or `practice_attempt_id`) lineage validated by the
resolver. Any missing, duplicate, stale, superseded, unresolved,
foreign, mismatched or structurally invalid identity raises only
`CONFIDENT_MOMENT_TARGET_SPEAKER_INVALID`; there is no valid-empty result.

Under the existing sorted attempt/audio serializer positions 60/70 it requires:

- the sole latest `mlc3_speaker_acquisition_revisions` row for the exact
  principal and attempt: maximum `revision_number`, no row whose
  `supersedes_revision_id` points to it, and
  `speaker_identity_status='resolved'`;
- exactly one `mlc3_target_speaker_bindings` row selected by the complete input
  identity: principal, recording attempt, audio object, `binding_state='active'`,
  no row whose `supersedes_binding_id` points to it, and `clip_id` equal to the
  exact non-null input when `target_kind='source_clip'` or
  `practice_attempt_id` equal to the exact non-null input when
  `target_kind='practice_attempt'`;
- that selected binding's `acquisition_revision_id` must equal the sole latest
  resolved acquisition revision above; the acquisition revision is a
  currentness check, never a substitute selector for the target-span binding;
- the exact non-null binding `speaker_id` matching the resolved acquisition
  revision's `speaker_id`;
- exact principal, attempt, audio SHA/object, target span, and mutually exclusive
  source-clip versus practice-attempt lineage; and
- an immutable result hash.

`speaker_count_status` is independent of identity resolution and is not by
itself a rejection. A `multiple` or `unknown` acquisition is usable here only
because the exact immutable clip/practice target span has its own reviewed,
resolved binding; without that exact binding the resolver fails closed.

Both exercise correlation and the root-practice guard must call this one
resolver. They may not independently restate “latest active resolved.”

## 4. Root/practice lock order

For a practice-derived `save_owner_selected_root`, both new creation and exact
replay must complete the practice guard, offer correlation, exact source and
practice target-binding resolution, and post-contention identity revalidation
before acquiring any position-100 root-block/head/Ideal-Text transition lock.

After position 100 is acquired, the operation may acquire no position 10–95
serializer. Any rederivation that would introduce a previously undiscovered
offer, catalogue, media, attempt, audio, or binding identity is correlation
drift and fails closed before acquiring the new key. Every derived key set is
sorted in the frozen global order. Two-connection practice/root and
correlation/binding races must be deadlock-free in both commit orders.

D48 binding fields and the practice guard apply only when
`source_practice_attempt_id` is non-null. Automatic roots, transcript/manual
owner selections, wording-accepted selections, lock, unlock, restore and remove
must not invoke exercise correlation or require speaker-binding IDs.

## 5. Playback timeout truthfulness

The dedicated 500 ms HTTP transport deadline and 500 ms local authorization
window are no-byte client deadlines; they are not represented as cancellation
of an already-running PostgreSQL statement. Remove any claim that an in-function
`set_config('statement_timeout',...)` arms its own invocation.

The three source-playback RPCs must remain bounded in structure: only
non-waiting advisory acquisition, `NOWAIT` row locks, exact indexed identities,
no external I/O, no unbounded inventory loops, and no R2 read while database
locks are held. A client timeout always discards state and emits no bytes.
Residual PostgreSQL execution after client give-up is explicitly bounded by the
deployed database/PostgREST statement-timeout configuration and must be attested
before activation. The accepted local disabled implementation may not claim a
specific server-cancellation latency without that production-bound evidence.

Phase 3 remains stateless and creates no durable emit receipt. Only D45 §2's
stateless/no-durable-receipt clause remains authoritative. Its wall-clock expiry
comparison is superseded by D46's request-local monotonic window; D43's
cross-TTL completion language and D40's 10 MiB cap are also superseded by the
later accepted amendments. Activation attestation must record the deployed
database/PostgREST statement timeout and prove the client's total bounded retry
window exceeds it.

## 6. Required regressions

- owner response versus projection in both commit orders;
- exact owner-response replay and changed-response rejection;
- foreign praise with the same evidence span/rater cannot bind;
- decision change yields a typed retry/new projection, never a hash collision;
- v2 item shape accepts only the frozen exact object and rejects v1/mixed shape;
- v2 exercise-correlation shape accepts its exact closed keys and rejects v1 or
  mixed shape;
- writer/caller registry and permission closure for the binding table/function;
- exact registry and REVOKE closure for
  `record_confident_moment_bundle_family_response_v1`,
  `derive_confident_moment_owner_decision_v1`, and
  `resolve_confident_moment_target_speaker_binding_v1`;
- every non-null `owner_decision.feedback_family` equals its containing item's
  `feedback_family` in SQL, Python and TypeScript validation;
- canonical speaker resolver ambiguity, supersession, unresolved identity,
  cross-principal and exact replay cases;
- practice/root and correlation/binding races in both commit orders, proving no
  lower-position acquisition occurs after position 100;
- non-practice root actions never call correlation or require binding IDs;
- source-playback SQL contains only the bounded non-waiting operation classes;
  client timeout emits no bytes and does not claim database cancellation; and
- zero fabricated confidence, improvement, adequacy, outcome, dataset, training
  or ninth-surface row.

All gates remain literal default-disabled. The migration remains unnumbered and
unmanifested. No commit, push, merge, deployment, activation, collection,
dataset creation, training, evaluation or promotion is authorized.
