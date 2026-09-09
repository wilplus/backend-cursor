# MLC-3 First-Client Service D2

Status: revised service-mode amendment for ML/data and Engineering design review.

This amendment connects the already accepted Feedback V3, N1 proximity,
practice P1/P2 and Coach Guidance D3 foundations into one first-client product
loop. It does not create a dataset, outcome label, training job, evaluation or
model-promotion path.

## 1. Product outcome and scope

For an authenticated user whose exact acquisition principal is allowlisted,
and an already rendered and answered Manager-selected Confident Voice item:

1. The server freezes a fresh, service-mode exercise offer from the exact V3
   membership, candidate, rendered exposure, immutable user response and exact
   N1 source-pattern result.
2. If at least one exercise is deterministically eligible, the closest reviewed
   exercise is shown. If none is eligible, the product shows the honest
   `coach_exercise_requested` state.
3. Rendering and video playback are recorded as separate immutable events.
4. The user may record the exact displayed passage. The audio is stored through
   a durable pre-write R2 recovery boundary and read-after-write SHA-256 check.
5. The first valid attempt is the immutable comparison attempt. Missing,
   invalid and unresolved earlier attempts remain explicit.
6. The user may answer only the subjective comparison question: “Does this
   sound better to you than the original?”
7. A coach completes separate blind five-state confidence assignments for the
   original source clip and first-valid practice clip before any context,
   measurements or authoring controls for those clips are revealed.
8. After reveal, the coach may attach a written note or reviewed video to the
   exact feedback item. MLC-3 exercise attachment is permitted only for the
   approved need and complete deterministic inventory.
9. A reusable exercise enters the catalogue only as a new independently
   reviewed version and a new immutable catalogue snapshot. A one-off draft is
   never mutated into reusable content.

General guidance remains product-only. The only initial acoustic need is the
approved `rushed_phrase_endings` contract. Feedback families and learning
surfaces are not extended.

## 2. One canonical persistence model

The released tables remain the canonical records. No parallel “pilot” offer,
practice, attachment or exposure tables may be introduced.

Add `operation_mode` to service-capable rows with the closed values:

- `synthetic_dark`
- `allowlisted_service`

Existing rows are backfilled as `synthetic_dark`. Existing hashes remain valid
under their historical contract versions. Every new service-mode hash includes
`operation_mode`, the service-contract version and all pre-existing immutable
identity fields.

The existing `synthetic_only` columns remain historical evidence. New
service-mode rows require `synthetic_only=false`. `dataset_eligible=false`
remains a structural constraint for every mode. `serves_user` is true only for
the service records that can actually affect the recipient:

- fresh offer and practice session;
- delivery, confirmed render and playback events;
- the delivered attachment version.

Preparation, upload recovery, media verification, coach authoring and catalogue
review records are product provenance and remain `serves_user=false`.

## 3. Activation and authorization

Four independent gates are required:

1. The exact service contract/version is active in the database.
2. `MLC3_PILOT_ENABLED=true` is present on every relevant backend service.
3. The exact `acquisition_principal_id` is in the configured pilot allowlist.
4. The frontend presentation flag is enabled.

The authenticated account is resolved to its canonical acquisition principal
by the server. That exact principal—not a user ID, email, linked account or
learning-profile identity—is submitted to and independently verified by the
database against the allowlist. Guest-to-account linkage does not expand the
canary to other historical acquisition principals.

The frontend flag controls presentation only and is never trusted as
authorization. Direct API calls still require the active database contract,
the backend master gate and the exact acquisition-principal allowlist. The
database gate is authoritative; frontend or backend configuration alone cannot
authorize a service write.

Every operation revalidates after contention:

- current required-service authorization for its exact purpose;
- policy/receipt consistency;
- principal, Project, Take, recording-attempt, object and clip lineage;
- retention, quarantine and authoritative deletion/purge state;
- coach role or recipient ownership;
- exact current media leaf state.

`pooled_model_improvement` is never required for offering, playback, recording,
coach review or feedback. The source recording and practice recording each
retain their own immutable acquisition-time required-service authorization
snapshot and their own acquisition-specific pooled-authorization state. The
states cannot be copied between recordings, inherited from a current account
setting or collapsed into the practice session.

Missing pooled authorization stores an explicit future-release exclusion for
that acquisition without blocking service. A later opt-in cannot retroactively
authorize either earlier recording. Every future dataset release must recheck
the applicable acquisition snapshot, acquisition-time pooled state and current
pooled authority independently for both source and practice audio.

## 4. Fresh offer and deterministic matching

A service offer may be created only from:

- one current immutable Feedback V3 membership and selected Confident Voice
  candidate;
- the exact rendered V3 exposure shown to this acquisition principal;
- the exact immutable user response bound to that membership, candidate and
  exposure;
- the exact audio lineage and evidence span;
- one immutable, pre-assignment, machine/policy N1 source-pattern result;
- one complete candidate inventory;
- one approved need contract and catalogue snapshot.

Human judgments and product actions cannot supply `source_pattern`.

An offer is allowed only after one response from the approved closed set:
`confident_yes`, `confident_in_between`, `confident_no` or
`confident_not_sure`. The response is product routing provenance only and does
not influence exercise eligibility or ranking. Silence, a missing response,
`confident_audio_unclear`, a foreign exposure, a superseded response or a stale
membership blocks offer creation with a typed outcome. Reading or opening a
card is not a response.

The deterministic order is:

1. safety and need compatibility;
2. recognized ordinal pattern distance;
3. frozen base deterministic rank;
4. frozen editorial priority, descending;
5. exercise-version UUID.

Every catalogue version is retained as eligible or typed-excluded. Exact match
is preferred; otherwise the nearest reviewed eligible exercise is selected.
Missing or unrecognized source patterns fail closed. This rank is a product
heuristic, not adequacy classification and not a label.

## 5. Media and practice recording

### Coach video

Before any R2 write, the database creates an immutable upload permit and
recovery record containing principal, reveal access, purpose, bucket, object
key, content type, byte length, expected byte SHA-256 and expiry. The worker
then records `write_started`, writes R2, reads the object back, recomputes length
and SHA-256, and records `write_acknowledged` and `finalized`.

An acknowledgement-lost or interrupted write remains unresolved and discoverable
by reconciliation and deletion traversal. It is never treated as absent.

### Practice audio

Practice audio uses the same ordering with the practice session, attempt index
and recipient principal in the immutable permit identity. It is private user
media. It must not reuse a presentation upload permit or a coach-video permit.

Provider-backed signed reads revalidate current authority and deletion state;
raw permanent public URLs are not persisted for new service-mode media.

The microphone route stores raw measurements and safeguards only. It must not
call the legacy hard-coded `improved` calculation or write machine outcome
labels.

## 6. Events and exposure

Offer/practice events remain distinct:

`assignment_prepared → delivery_prepared → render_confirmed → playback_started → playback_completed`

Guidance events remain distinct:

`authored → assigned → delivered → rendered → played`

Delivery is not exposure. Only an authenticated render confirmation for the
exact recipient and frozen content identity creates rendered exposure. Playback
never backfills a missing render event. Retries replay the exact immutable event
or fail with a typed conflict.

No dark assignment or dark event is converted into a service event. A fresh
service assignment is required.

## 7. Raw evidence and subjective judgments

The collection contract stores:

- exact original and practice audio-object identities and SHA-256 values;
- separate acquisition-time service and pooled-authorization snapshots for
  the original and practice recordings;
- exact transcripts, transcript versions and hashes;
- capture timing and recording conditions;
- versioned raw N1 measurements and safeguards;
- explicit validity, missingness and invalidity reasons;
- immutable first-valid selection revision;
- user before/after preference;
- independent coach blind confidence judgment for the original source clip;
- independent coach blind confidence judgment for the first-valid practice
  clip;
- independent coach randomized A/B preference when that workflow is enabled.

These remain separate facts. The system does not derive `improved`, causal
effectiveness, confidence truth, adequacy class or training eligibility.

The two confidence judgments are separate canonical review assignments. Each
is bound to its own exact recording attempt, audio object, byte SHA-256, clip
coordinates, evidence span and five-state judgment. The source judgment cannot
answer the practice assignment and the practice judgment cannot be copied back
to the source. Neither confidence judgment may substitute for, imply or be
joined as the answer to the separately randomized A/B preference assignment.
The A/B assignment retains its own frozen order, context history and immutable
judgment.

## 8. Coach authoring and catalogue growth

The review batch is derived by the database from the canonical coach assignment
frame at a frozen cutoff. The browser cannot choose, omit or reorder required
assignments. Only all required `blind_coach` five-state judgments unlock that
reviewer’s reveal grant.

After reveal:

- any frozen feedback item may receive product-only written guidance or a
  reviewed coaching video;
- only a qualifying Confident Voice item may receive an MLC-3 exercise;
- structure, praise or rewrite feedback cannot be declared an acoustic need;
- acoustic measurements are visible only through an explicit post-judgment
  reveal control.

Publication requires either independently registered clean media containing no
user audio/transcript/identity/project context/unique passage, or an immutable
user-source dependency that is logically invalidated when source authority is
lost. Physical retention is evaluated separately for unaffected references and
legal holds.

## 9. Deletion and reconciliation

Deletion traversal covers offers, sessions, attempts, upload permits,
recoveries, media objects, event chains, comparison responses, attachments,
publications and invalidations by acquisition principal.

Deletion wins over creation and replay. Every storage or lifecycle operation
uses read-committed isolation or a separately proven serialization strategy,
locks the exact media/deletion identity, and revalidates after waits. Late R2
writes remain registered for reconciliation. Shared media is physically deleted
only when no valid reference or legal hold remains.

## 10. Rollout

The implementation sequence is:

1. additive migration and code deployed with every gate off;
2. production migration rehearsal and live R2 synthetic-object rehearsal;
3. ML/data implementation review;
4. Engineering release review;
5. exact founder acquisition principal allowlisted;
6. founder canary with datasets/training/evaluation/promotion still off;
7. evidence review and explicit expansion to named first clients.

Rollback closes the database service contract and backend/frontend gates. It
does not delete immutable audit records or reinterpret already confirmed
exposures.

## 11. Required verification

- service mode cannot be reached through any synthetic RPC;
- synthetic rows remain byte-for-byte replayable;
- current authorization and deletion fail during every contention window;
- cross-principal, cross-Take, cross-recording, cross-clip and stale-membership
  inputs fail closed;
- complete eligible/excluded inventories and deterministic nearest matching;
- exact idempotency under two-connection races;
- acknowledgement-lost, late-write, corrupt-read and no-resurrection media
  tests for coach video and practice audio;
- first-valid attempt with unresolved earlier-attempt blocking;
- no automatic outcome or label writes;
- coach batch omission and wrong-provenance rejection;
- rendered exposure requires exact recipient confirmation;
- catalogue publication creates a new version/snapshot and preserves withdrawal
  dependencies;
- RLS, RPC-only writes, append-only behavior and deletion registry coverage;
- fresh apply/reapply, populated reapply and rollback rehearsals;
- backend, frontend, BFF and browser end-to-end tests with all production gates
  off by default.

```text
VERDICT:  ADVANCE-F2
CATEGORY: F2
WHY:      Completes the approved exact-clip exercise and coach-review loop
          without converting product evidence into labels or learning access.
REDIRECT: Review this service-mode amendment, then implement it behind four
          independent gates before any founder or first-client activation.
```
