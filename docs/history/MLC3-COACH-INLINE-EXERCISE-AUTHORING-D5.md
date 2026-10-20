# MLC-3 Coach Inline Exercise Authoring D5

Status: proposed local implementation contract. No activation is granted.

## Problem

The coach review screen already contains the intended exercise composer below
an exact feedback item. Its current service query only returns items that have
an `exercise_practice_session`. A no-match offer has outcome
`coach_exercise_requested` and cannot create that practice session until an
exercise exists. Consequently, the coach cannot create the first exercise from
the exact feedback moment that requested it.

The completed recorded Take is canonically typed `source_before_exercise`.
It is sufficient for coach prescription but is not an
`exercise_practice_attempt`. The correction is an inline Take-feedback
authoring path. It is not a separate
catalogue panel and it does not relax the blind-review boundary.

## Product flow

1. The existing blind confidence card remains limited to opaque audio playback
   and the five-state judgment. Transcript content, machine feedback, Project
   context and acoustic measurements are absent before judgment. The transcript
   hash remains server-side and transcript content may appear only after the
   reviewer-specific reveal.
2. The server/database freezes the complete canonical blind-review batch. The
   browser cannot select, omit or reorder assignments. The exact Take-feedback
   assignment joins that existing database-derived frame; it is not a separate
   one-item shortcut around batch blindness.
3. The coach submits every required judgment in that exact batch revision. Only
   then does the reviewer-specific reveal grant unlock contextual controls.
4. On the same feedback card, directly below the revealed feedback, show:
   - `Add written guidance`;
   - `Add coaching video`;
   - for a qualifying no-match Confident Voice item, `Create exercise`.
5. `Create exercise` accepts a title, instruction, demonstration video and the
   reviewed compatibility fields allowed by this contract. Saving it attaches
   the exact one-off exercise to this feedback response.
6. If a separately reviewed reusable publication transition succeeds, it also
   creates a new immutable exercise version and complete catalogue snapshot.
   Future matching may then select it. Saving a draft does not silently publish.

The composer stays on the feedback card shown in the user's screenshot. No
separate authoring or catalogue-management screen is introduced.

## Take-feedback review frame

For an offer whose immutable outcome is `coach_exercise_requested`, the
database may create a Take-feedback coach review frame from the user's existing
recorded Take before any after-exercise attempt exists. It freezes:

- exact reviewer and `acquisition_principal_id`;
- Project, Take, recording attempt, recording and audio-object identity;
- exact clip coordinates, transcript hash and audio SHA-256;
- V3 membership, exposure, immutable user response and canonical candidate;
- exercise offer, complete candidate inventory and typed no-match outcome;
- machine-only source-pattern result and approved need-contract identity;
- assignment policy, cutoff, required assignment set and typed exclusions;
- five-state taxonomy and blindness policy versions.

The Take-feedback item contributes exactly one required blind confidence
assignment for the exact Take clip to the complete canonical batch. The batch
may contain other required assignments, and every one must be answered before
reveal. This recording is typed `source_before_exercise`; it is never an
exercise-practice attempt and cannot populate practice, comparison or outcome
records. The system cannot invent an after-exercise assignment or A/B
comparison. If the user later re-records after confirmed exercise playback,
that recording is typed `practice_after_exercise`; the accepted two-clip
review and A/B contracts then apply separately and remain unchanged.

The Take-feedback frame is eligible for inline authoring only when the exact V3
user response, offer and need result permit the service flow. Silence,
`confident_audio_unclear`, foreign/stale membership, missing render exposure,
ineligible need provenance or an active matching exercise fails closed.

## Inline authoring and publication

General guidance may be added to any eligible frozen feedback item after its
blind frame is complete. An MLC-3 exercise may be created only for an exact
Confident Voice item with:

- an approved operational acoustic-need contract;
- machine-only exact-clip need provenance;
- a complete frozen catalogue inventory;
- deterministic typed eligibility for every catalogue version;
- a typed `coach_exercise_requested` no-match result;
- current authorization, retention, quarantine and deletion validity.

The coach may provide:

- exercise title and instruction;
- one private demonstration video;
- language;
- supported confidence-pattern set selected from the server-provided approved
  ordinal vocabulary;
- explicit clean-media and rights attestation.

These coach inputs describe a draft; they do not approve its technical
eligibility. Before assignment, the server resolves an immutable, independently
approved N1 compatibility profile for the exact draft/version. The profile
freezes its ID, version, hash, supported-pattern vocabulary and finite supported
and preferred ratio bounds. The same draft/version must also have separately
approved immutable content, safety and rights evidence with IDs, versions and
hashes. A coach attestation alone cannot satisfy any of those approvals.

The browser cannot supply or override numerical thresholds, need identity,
safety approval, catalogue state, version number, hashes, storage identity,
policy versions or the no-match decision.

The original no-match candidate inventory remains immutable and cannot
authorize an exercise created after that inventory was frozen. Before the new
draft/version may be assigned or delivered, the server freezes a fresh
deterministic eligibility inventory containing that exact immutable exercise
version. It re-evaluates need, language, safety, rights, media validity, N1
compatibility-profile ID/version/hash, exact content/safety/rights approval
identities and current authorization, and records one typed eligibility or
exclusion result for every in-scope version. Only a newly selected eligible
version may proceed to assignment. The earlier no-match inventory is preserved
unchanged as historical provenance.

A one-off draft is user/source-linked. Reusable publication is a separate
atomic transition. Review cannot reclassify a case-derived draft as
`independent_clean_media`. If its wording, passage, video or exercise design
was copied or materially derived from the case, it remains
`user_source_dependent` and retains the exact source lineage and invalidation
rules. Independent publication requires a separately authored artifact and
independently reviewed media containing no user audio, transcript, identity,
Project context, uniquely identifying passage or other case-derived material,
plus exact content, rights, safety and N1 compatibility approvals.
Publication creates a new immutable `exercise_version` and complete catalogue
snapshot; it never mutates the one-off draft into shared content.

## Media and continuing authority

The upload lifecycle remains:

`reserved -> write_started -> write_acknowledged -> verified -> attached`

Before R2 writes, durable recovery identity is persisted. Finalization binds
the exact byte SHA-256, byte length, MIME type, object key and provider receipt.
Lost acknowledgements remain reconcilable. Playback uses authenticated,
same-origin byte delivery; the browser never receives a direct R2 or presigned
object URL. The backend acquires the authoritative media-validity lock, checks
coach/recipient authority, retention, quarantine and deletion state, reads the
bounded object bytes from R2, rechecks the same current leaf state after the
read, and only then returns the bytes with private/no-store headers. If either
check fails, no bytes are returned. This avoids claiming immediate revocation
for a URL that has already escaped the authorization boundary.

Creation, replay, upload finalization, attachment, private playback,
assignment, delivery, render, play and publication revalidate current coach
and recipient authority, exact acquisition principal, retention, quarantine,
purge/deletion state and media validity after contention. Historical reveal or
authorization evidence is never a continuing bearer permit.

## Event and learning boundaries

Keep immutable events separate:

`authored -> assigned -> delivered -> rendered -> played`

Delivery is not exposure. Only authenticated client render confirmation creates
rendered exposure.

The source judgment remains `confidence_classification`. Exercise authoring,
notes, media, matching, delivery and playback are product provenance only.
They are not exercise-effectiveness labels, outcome labels or dataset rows and
create no ninth learning surface. Any future exercise-adequacy dataset requires
its own reviewed supervision and release contract.

## Later review after contextual reveal

The coach who authored the exercise has already received contextual reveal for
the source Take. When a `practice_after_exercise` recording later exists, the
system must not create a duplicate source judgment or describe that coach as
context-naive.

For the same coach, a successor review frame reuses the exact immutable
`source_before_exercise` assignment and judgment, carries forward
`prior_context=known`, and adds one exact assignment for the new practice
recording. That practice judgment may remain blind to machine and user answers,
but it must never be represented or counted as independently context-naive.
Only the new practice clip is judged in that successor frame.

Alternatively, the practice clip may be assigned to another eligible reviewer.
That reviewer is `prior_context=unknown` by default. The database may set
`prior_context=verified_none` only after a canonical cross-session access-history
check finds no prior access to the related acquisition principal, speaker,
recording, audio object or byte hash, any overlapping clip coordinates, or
related comparison context. Missing, incomplete or unavailable access history
remains `prior_context=unknown`; absence of one exact reveal record is never
proof of blindness.

The immutable assignment and judgment provenance records the context state and
the exact access-history policy/version/hash used to derive it. Future
evaluation or release filtering may distinguish `known`, `unknown` and
`verified_none`; no downstream process may silently treat `unknown` as blind.

The assignment freezes the access-history cutoff and inventory hash used for
its context assessment. Context is not trusted only from assignment time. In
the judgment transaction, under the same ordered reviewer/evidence history
locks used by reveal access, the database reruns the canonical history check
through a submission cutoff before accepting the answer. If relevant access
occurred after assignment, the stale context token is rejected and the system
creates a new immutable assignment/context revision; it never overwrites the
earlier assessment or attaches the answer to it. Missing or incomplete history
at submission remains `prior_context=unknown`.

Serialization makes both race orders explicit: a related reveal/access that
commits first is visible to submission revalidation and prevents stale
`verified_none`; a judgment that commits first retains its valid submission
cutoff and any later reveal is recorded only as later context. Neither order
retroactively rewrites an immutable judgment.

The randomized A/B preference assignment remains a separate workflow with its
own frozen order and known/unknown-context provenance. Neither path claims that
the earlier source judgment was newly blinded.

## UI and gates

The inline composer appears only after the server reports the exact source
review frame complete and returns a valid reveal-access identity. It renders
inside the same coach feedback card, below the feedback content and judgment.

The card visibly distinguishes:

- `Draft exercise - not yet sent`;
- `Sent to this user`;
- `Reusable version awaiting review`;
- `Active in exercise catalogue`.

Coach authoring, user serving, collection and reusable publication remain
separate backend/database gates. Frontend flags are presentation only. Every
gate defaults off. Enabling coach authoring alone cannot serve the exercise to
a user.

## Deletion

Deletion traversal covers the Take-feedback batch item, assignments,
judgments, reveal grants/access, draft revisions, upload permits, recovery
rows, media validity, attachments, lifecycle events, publication reviews and
catalogue dependencies. User-source-linked reusable content is logically
invalidated if source authority is lost. Physical shared-media deletion remains
reference- and legal-hold-aware.

## Verification

- A `coach_exercise_requested` offer uses the exact recorded-Take blind
  assignment inside the complete canonical batch and never fabricates an
  after-exercise attempt.
- The pre-judgment response contains no transcript text, machine feedback,
  Project context or measurements.
- The inline composer is absent before the complete canonical blind pass and
  present below the exact card after reveal.
- Omitting a required blind judgment cannot unlock it.
- Wrong reviewer, principal, V3 response, candidate, offer, need result, clip,
  inventory or no-match identity fails closed.
- An existing eligible matched exercise does not open new-exercise authoring.
- A coach can save one exact one-off exercise with note/video and private replay.
- The saved draft cannot be assigned from the historical no-match inventory;
  a fresh complete deterministic inventory must select it as eligible.
- A case-derived draft cannot be reclassified as independent through review.
- Playback is authenticated same-origin byte delivery and rejects when authority
  or media validity changes before or during the R2 read.
- A reviewer cannot submit with stale `verified_none` after related context is
  revealed; both submission-before-reveal and reveal-before-submission races
  preserve the correct immutable cutoff and context revision.
- Upload loss, retry, revocation, quarantine, deletion and media invalidation
  fail closed without orphaning untracked bytes.
- Draft creation does not create an active catalogue version or user exposure.
- Reusable publication fails without exact independent-media, content, rights,
  safety and N1 compatibility approvals.
- Publishing creates a new version and complete catalogue snapshot.
- A later after-exercise re-recording uses the existing original/attempt blind
  review and A/B flow; the Take judgment never substitutes for those later
  judgments.
- Serving, collection, datasets, training, evaluation and promotion remain off.

```text
VERDICT:  ADVANCE-F2
CATEGORY: F2
WHY:      Removes the first-exercise deadlock inside the existing feedback flow
          while preserving blindness, exact lineage and learning isolation.
REDIRECT: Review D5, then implement the inline Take-feedback frame and composer
          behind disabled gates. Activation remains separate.
```
