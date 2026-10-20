# MLC-3 Coach Guidance and Exercise Delivery — D3

**Status:** DRAFT FOR ML/DATA DESIGN RE-REVIEW  
**Scope:** local, disabled-gate implementation design only  
**Companions:** `MLC3-EXERCISE-ADEQUACY-DESIGN.md`, accepted MLC-3 N1,
P1/P2, CMP-1, Feedback V3, and RPQ-V1 contracts

This amendment defines how post-judgment acoustic reference data, written
guidance, general coaching videos, and MLC-3 exercises may be attached to an
exact frozen feedback item. It adds no learning surface and authorizes no
runtime activation, real collection, dataset, training, evaluation, or model
promotion.

## 1. Complete blind pass and reveal boundary

A complete blind pass is scoped to one coach and one immutable
`review_batch_id`.

Batch membership is derived exclusively by a database RPC from the canonical
review-assignment frame. The coach and browser submit neither membership nor
ordering. Under a transaction lock, the RPC freezes:

- the canonical `review_assignment_frame_id`;
- batch-policy version and wall-clock cutoff;
- the complete eligible assignment set in canonical policy order;
- every in-scope exclusion with its typed reason;
- the exact required `review_assignment_id` values and their order;
- each assignment's blind-packet ID, schema version, taxonomy version, payload
  hash, exact evidence/clip lineage, and expiry policy;
- the coach ID, creation time, and batch hash covering the frame, policy,
  cutoff, eligible set, exclusions, and order.

Assignments committed after the cutoff cannot enter this batch; they are
derived into a later batch. Reapplication or replay must resolve to the same
canonical frame and hash. The completion RPC recomputes the frozen membership
from the referenced frame and requires one valid judgment for every eligible
required row. A caller cannot omit, add, replace, or reorder an assignment to
obtain a reveal grant. Typed exclusions remain in the frozen inventory but do
not require a fabricated judgment.

The batch completes only when that coach has submitted one immutable judgment
for every required assignment using the five-state taxonomy:

- `yes`;
- `in_between`;
- `no`;
- `not_sure`;
- `audio_unclear`.

Opening or playing a clip, navigating away, skipping, timing out, assignment
expiry, or submitting an empty response never completes an assignment. A
cancelled or superseded assignment changes the batch only through a new
immutable batch revision; it is never silently omitted from the original
batch.

Completion atomically creates a `post_judgment_reveal_grant` containing:

- `review_batch_id` and batch revision/hash;
- coach ID;
- the exact ordered assignment and judgment IDs;
- reveal-policy version, creation time, and grant hash.

Each post-blind read creates an immutable `reveal_access_id` referencing the
grant, coach, exact evidence requested, purpose, and timestamp. The grant is
valid only for its coach. Another coach or peer remains blind until completing
their own frozen batch. No acoustic, machine, user, peer, feedback-context, or
exercise data enters the browser payload before this grant exists.

## 2. Post-blind acoustic reference

After a valid reveal grant, the coach may expand the raw, versioned acoustic
feature projection already bound to the exact clip. The panel is collapsed by
default and presents measurements only. It must not add a confidence verdict,
exercise-effectiveness claim, direction label, threshold interpretation, or
human answer.

The read records the exact extractor run, feature-schema version, audio-object
ID and byte SHA-256, clip offsets, evidence ID, review batch, judgment, reveal
grant, and reveal access.

## 3. Two distinct attachment classes

### 3.1 General product guidance

Any exact frozen feedback membership may receive:

- a versioned written note;
- a versioned general coaching-video attachment; or
- both.

This applies to Confident Voice, rewrite, praise, structure, and delivery
feedback. General guidance is product-only. It is not an MLC-3 exercise, does
not assert an acoustic need, does not enter an exercise candidate inventory,
and creates no ninth learning surface.

Rewrite, praise, structure, or delivery feedback must never be converted into
an acoustic need merely because a coach attaches a video. The attachment keeps
the exact feedback family and product purpose with which it was authored.

### 3.2 MLC-3 exercise

An MLC-3 exercise may attach only when all of the following already exist and
validate:

- an approved, active acoustic-need contract and version;
- the exact eligible source clip and frozen machine/policy need result;
- a complete frozen exercise catalogue/candidate inventory;
- one typed deterministic eligibility outcome for every in-scope exercise
  version;
- one deterministic selected eligible exercise or a typed no-match result;
- current service authorization, safety, language, rights, retention, and
  deletion checks.

Human judgments and product actions cannot create or substitute the machine
need result. A feedback family with no approved need remains eligible only for
general product guidance.

## 4. Authoring and immutable lineage

Authoring can begin only after the authoring coach has a valid reveal grant for
the exact batch and judgment. Every attachment freezes:

- coach ID;
- `review_batch_id`, exact blind judgment ID, reveal-grant ID, and
  reveal-access ID;
- Feedback V3 membership/revision, canonical candidate ID, candidate-set ID,
  candidate output version and SHA-256;
- evidence-span ID, exact snippet/clip, Take, recording attempt, recording,
  Project/arc, Paragraph and Slide lineage;
- recipient acquisition principal;
- immutable note revision, or exercise/general-video draft and version;
- applicable need-contract version for an MLC-3 exercise, otherwise an
  explicit `general_product_guidance` classification;
- language-policy, safety-policy, rights-policy, content-review, and authoring
  contract versions;
- private media-object ID, content type, byte length, byte SHA-256, upload
  authorization/permit, and storage-provider receipt;
- authoring timestamp, idempotency identity, and complete row hash.

Caller-supplied URLs, text, candidate keys, or hashes never establish lineage.
Database RPCs resolve and validate the canonical parents, revalidate live
authorization and deletion state after contention, and fail atomically.

## 5. Assignment, delivery, rendering, and playback

The lifecycle contains separate immutable events:

```text
authored → assigned → delivered → rendered → played
```

- `authored`: a specific note or media/exercise draft version exists.
- `assigned`: that exact version is assigned to one recipient and feedback
  item.
- `delivered`: the server included the assignment in an authenticated user
  response. This is not exposure.
- `rendered`: the authenticated client confirms that the exact assignment and
  version was visibly rendered. Only this event is a rendered exposure.
- `played`: the authenticated client confirms playback of the exact media
  version. It remains distinct from rendering and practice completion.

Every event references its immediate predecessor plus the recipient principal,
feedback membership/candidate, attachment version, media object where
applicable, policy/code version, idempotency identity, and timestamp. A retry
returns the same immutable event. It never advances a later state implicitly.

### 5.1 Continuing live authority

Historical acquisition snapshots, completed blind batches, judgments, reveal
grants, and earlier lifecycle events prove prior state only. They never provide
continuing authority.

Immediately after every potentially blocking lock and before commit or replay
return, each of these boundaries independently rechecks current wall-clock
state:

- upload finalization and upload replay;
- assignment;
- delivery;
- rendering confirmation;
- playback confirmation;
- reusable publication.

Every check must validate current service authority, coach access, recipient
access, retention state, quarantine state, canonical purge/deletion ledger,
media-object validity, and unresolved provider-write state. Exercise operations
also revalidate the exact need, safety, rights, language, catalogue, and
eligibility versions required for that operation. Revocation, access loss,
retention expiry, quarantine, purge, deleted media, or unknown state fails
closed. An idempotent replay may return historical evidence only when current
authority still permits that exact operation; otherwise it rejects without
creating or advancing state.

## 6. One-off drafts and reusable catalogue publication

A case-specific coach exercise remains a user-scoped immutable draft/version.
It may be assigned to that user after the explicit coach action and applicable
checks. It never becomes reusable by mutation.

Reusable publication requires a separate content/safety/rights review and one
explicit provenance class:

- `independent_clean_media`: the published version uses independently
  registered and reviewed media containing no user audio, transcript, identity,
  Project context, or uniquely identifying passage; or
- `user_source_dependent`: the published version retains an immutable
  dependency on the exact user-scoped source and its current authority.

A successful publication creates:

1. a new reviewed reusable `exercise_version`;
2. independently registered reviewed media lineage;
3. a new immutable catalogue snapshot containing that version.

The source draft remains unchanged and linked as provenance. Publication is
not evidence that the exercise is adequate or effective.

Publication may never sever user provenance while continuing to treat derived
content as valid. An `independent_clean_media` version proves its independent
media and content review before publication and does not derive its payload
from user material. A `user_source_dependent` version remains linked to the
source; withdrawal, deletion, retention expiry, or loss of source authority
logically invalidates that exercise version, removes it from future catalogue
snapshots, and blocks new assignment, delivery, rendering, and playback.

## 7. Signal, supervision, and dataset boundary

Notes, videos, acoustic measurements, authoring actions, assignment, delivery,
rendering, and playback are product evidence. They are not labels and remain
structurally dataset-ineligible.

Future use requires all of the following in addition to an independently
authorized dataset release:

- a named existing learning surface;
- a surface-specific, versioned supervision/label contract;
- exact authorization and acquisition-snapshot checks;
- current withdrawal, retention, deletion, and quarantine checks;
- exact immutable provenance and byte-hash verification;
- applicable leakage controls and speaker-disjoint release rules.

A coach note with no corresponding frozen machine draft/output remains
ineligible for generation SFT under MLC-2. General guidance never enters
`exercise_adequacy_classification`. Confidence judgments remain on
`confidence_classification`; exercise evidence remains isolated from all seven
MLC-2 systems.

## 8. Deletion and shared-media references

Deletion inventory records user-scoped links separately from reusable shared
objects.

- Termination or deletion removes/quarantines the recipient assignment,
  delivery/render/playback events as applicable, user-scoped draft linkage,
  and private user-scoped media under the approved retention procedure.
- A reusable media object is not deleted while another valid catalogue version,
  active assignment, retention exception, or legal hold references it.
- User-source linkage is never removed from a `user_source_dependent` version.
  Loss of source authority invalidates that lineage even if physical bytes must
  remain temporarily for unaffected references or a legal hold.
- An `independent_clean_media` version may remain valid after deletion of an
  unrelated user-scoped draft only because its media and content provenance
  were independently registered and reviewed and contain none of that user's
  protected material.
- Physical object retention is separate from logical validity. A shared object
  is deleted only when its complete reference graph reaches zero and no hold
  remains; retained bytes do not authorize use through an invalidated lineage.
- Ambiguous ownership, unresolved provider writes, or incomplete reference
  traversal fails closed and blocks deletion completion.

## 9. Disabled-gate implementation boundary

The first implementation may add schemas, RPCs, synthetic adapters, and UI
fixtures behind hard-disabled gates. It must preserve:

- RPC-only writes, explicit RLS, append-only records, and immutable replay;
- synthetic media only until live R2 permits receive separate verification;
- `serves_user=false` and `dataset_eligible=false` structural constraints;
- no production migration, live authoring, delivery, rendering, playback,
  collection, dataset creation, training, evaluation, or promotion.

## 10. Acceptance tests required before implementation acceptance

- incomplete/missing/expired/skipped five-state assignments cannot create a
  reveal grant;
- browser-supplied membership/order is rejected, the batch inventory equals the
  canonical frame at its cutoff, and omitting one required assignment cannot
  unlock reveal;
- assignments committed after the cutoff enter a later batch;
- one coach's completed batch cannot reveal data to another reviewer;
- exact batch/judgment/reveal identity survives retry and contention;
- general guidance cannot populate an acoustic need or exercise inventory;
- MLC-3 attachment rejects missing/foreign need, clip, candidate inventory,
  eligibility, authorization, safety, language, or rights lineage;
- delivery without render confirmation creates no rendered exposure;
- render and playback retries remain exact and separate;
- revocation, access loss, retention expiry, quarantine, purge, or media
  invalidation during contention rejects upload finalization/replay, assignment,
  delivery, rendering, playback, and publication without partial events;
- same-key cross-recipient or cross-version replay fails closed;
- publishing creates a new exercise version and catalogue snapshot without
  mutating the one-off draft;
- clean reusable publication rejects any user audio, transcript, identity,
  Project context, or uniquely identifying passage; user-dependent publication
  retains its immutable source dependency and is logically invalidated when
  that source authority ends;
- deletion removes user-scoped links without deleting valid shared media and
  blocks completion on unresolved references;
- no attachment or lifecycle event becomes a judgment, label, dataset row, or
  ninth learning surface.

```text
VERDICT:  ADVANCE-F2
CATEGORY: F2
WHY:      The amendment makes blindness, guidance/exercise separation,
          rendered exposure, continuing authority, reusable-media withdrawal,
          and future supervision eligibility explicit.
REDIRECT: Obtain ML/data design acceptance before disabled-gate implementation.
```
