# MLC-3 exercise adequacy and Feedback Policy V3 design

Status: **ML/DATA DESIGN ACCEPTED — ARCHITECTURE ONLY — IMPLEMENTATION GATED**

Owner: Artur Willoński

Engineering/ML adviser: Codex (OpenAI)

Design version: `MLC-3-D2`
Date: 2026-08-29

This document is a design and cutover contract. It does not authorize a
migration, runtime write, user-facing activation, dataset release, training,
evaluation, model promotion, or deletion. The existing production Manager and
the existing Phase-1 authorization boundary remain authoritative until the
separate activation gates in this document pass.

## 1. Objective

Deliver one coherent loop:

```text
completed Take
  -> slide-bounded speech blocks closest to 75 words
  -> one relative-best Confident Voice moment per block
  -> immutable user confidence response
  -> deterministic exercise safety/compatibility gate
  -> eligible exercise ranking and assignment
  -> authenticated rendered exposure
  -> same-passage practice recording
  -> separate raw outcome signals
  -> blind coach/peer confidence judgments
  -> later, surface-specific exercise-adequacy learning
```

The product goal is not to declare that every selected clip is objectively
confident. It is to find the **best available delivery inside each local
presentation moment**, use that exact phrase as a possible memory/root cue, and
offer practice matched to the clip's evidenced delivery need.

The live recording -> processing -> Ideal Text -> next-Take loop never waits
for coach review, exercise authoring, dataset work, or model training.

## 2. Founder-locked product policy

### 2.1 Speech blocks

1. Partition each contiguous Slide run independently.
2. Use persisted snippet/Paragraph boundaries; never cut words or fabricate
   transcript boundaries.
3. Choose a deterministic global partition closest to 75 words per block.
4. The normal target range is 60-90 words. An indivisible short or long
   Paragraph remains intact and receives a typed partition exception.
5. Returning to an earlier Slide starts a new run; chronology is never
   reordered merely to balance block sizes.
6. Every block and candidate retains exact Project, Take, recording, Slide,
   Paragraph, snippet, text-span, audio-offset, duration, and audio-object
   lineage.

### 2.2 Feedback budget by Take

This is an explicit future amendment to §4 of
`docs/CANONICAL_PRODUCT_CONTRACT.md`. It supersedes the current exact-three
rule only when Feedback Policy V3 is separately activated.

| Take | Confident Voice | Actionable Improvement | Evidence-backed Praise |
| --- | --- | --- | --- |
| Take 1 | Exactly one relative-best candidate per valid 75-word block | None | None |
| Take 2+ | Exactly one relative-best candidate per valid 75-word block | Zero or one globally highest-ranked item from the weakest defensible verbal/structure fragment | Zero or one globally highest-ranked formulation supported by real textual evidence |

Consequences:

- There is no three-item whole-Take cap under V3.
- Confidence is relative within each block. Rewrite and praise remain absolute
  comparisons across their complete eligible Take-level pools.
- Every selected item is frozen together before exposure. Responding to one
  item never reveals a previously hidden substitute.
- Weak relative confidence uses tentative qualitative language. It is never
  presented as an objective positive verdict.
- Invalid or unusable blocks/candidates remain in the inventory with typed
  exclusions; they are never silently dropped.
- Weak evidence may still produce the best honest rewrite or praise using
  tentative language. When a valid Take contains no evidence that can support
  an honest item, the Manager freezes `no_defensible_candidate` for that lane
  and shows no card. It never manufactures a correction, praise, wording, or
  certainty merely to fill a slot.
- Missing/unusable source material remains a distinct typed exclusion and is
  never collapsed into `no_defensible_candidate`.

### 2.3 Root/orange behavior

1. Confident Voice may propose an exact phrase from the selected Paragraph as
   a potential root; it never styles text automatically.
2. The user first resolves the Feedback, then explicitly locks or leaves the
   Paragraph evolving, then explicitly applies, chooses, or declines the
   orange phrase under the existing versioning contract.
3. Recording and Presentation modes show only phrases whose Paragraph is
   locked and whose orange action was explicitly accepted.
4. A Slide with no accepted orange phrase shows no generated fallback before
   Take 3.
5. After Take 3, the Manager may propose at most one root for an uncovered
   Slide. The user must still explicitly lock/apply it; no automatic styling is
   allowed.
6. Editing, unlocking, or accepting an overlapping rewrite clears stale root
   metadata under the existing revision rules.

### 2.4 Confidence responses

The original clip retains the approved five-state immutable self-report:

- `confident_yes`
- `confident_in_between`
- `confident_no`
- `confident_not_sure`
- `confident_audio_unclear`

`confident_audio_unclear` blocks exercise matching for that clip because the
acoustic evidence is not dependable. The other four states do not become
machine truth and do not override deterministic eligibility. They remain
separate routing/evaluation evidence.

## 3. Operational definitions

### 3.1 Relative-best Confident Voice moment

The eligible exact clip in one 75-word block with the highest comparable
current-version Confidence Classification score after deterministic quality
and lineage gates. It means **best available within that block**, not
objectively confident and not better than the speaker's other Slides or Takes.

Tie-breaking order is frozen and reproducible:

1. exact-lineage eligibility;
2. current compatible detector/features present;
3. highest speaker-relative score inside the block;
4. spoken order;
5. stable candidate identifier.

Scores, ranks, thresholds, and machine verdicts never enter user payloads.

### 3.2 Acoustic need

A versioned, evidence-backed description of a modifiable delivery property in
an exact clip that an exercise is designed to address. It is derived only from
approved acoustic measurements and quality evidence. It is not an emotion,
intention, diagnosis, personality trait, identity attribute, health claim, or
speaker-identification embedding.

Examples of permissible narrow properties include word compression, rushed
ending, insufficient audible separation, or unstable pause placement, but each
property must have its own approved feature schema and operational definition
before it may participate in matching.

### 3.3 Deterministic exercise eligibility

Whether one versioned exercise may safely and coherently be offered for one
versioned acoustic need under its language, media, safety, contraindication,
repetition, authority, and delivery constraints. Eligibility is a deterministic
product-policy decision. It is not a learned target, adequacy class, human
label, or positive outcome.

### 3.4 Learned exercise adequacy

Among exercises that have already passed the deterministic gate, the predicted
probability that exposure will produce improvement on the one predeclared
primary endpoint and horizon.

Learned exercise adequacy is initially one learning surface:

```text
exercise_adequacy_classification
```

It may produce a score used only to rank an already eligible exercise pool. It
may never override the gate, learn the gate's eligibility decision as its
label, or treat an exclusion as a negative adequacy outcome. A separate
trainable ranking surface is not created initially.

### 3.5 Outcome horizons and activation gate

The product stores raw observations without deriving a training class until a
versioned label specification is approved.

Raw horizons are separated:

- `same_session_same_passage`: a valid attempt captured in the same opened
  practice flow;
- `delayed_same_passage`: a valid attempt after the original practice session;
- `next_take_transfer`: a materially comparable future-Take clip linked by
  Project/Slide/Paragraph lineage.

The first MLC-3 label specification must choose exactly one primary endpoint
and time horizon. It must also freeze:

- the baseline/original observation;
- which of up to three attempts supplies the endpoint;
- validity and alignment requirements;
- missing, `no_attempt`, dropout, and censoring treatment;
- the minimum follow-up window;
- primary metric, estimand, evaluation cohort, and decision thresholds;
- repeated-exposure and carryover handling;
- offline evaluation and promotion criteria.

It must not merge horizons or use "exercise shown" as success. Until this
specification is approved, every outcome remains evaluation-only raw evidence,
serving may use only the deterministic top eligible exercise, and user-facing
80/20 exploration is structurally disabled. Dark schema, catalog, candidate
inventory, and non-exposure calculations may be implemented earlier.

## 4. Selection and exposure policy

### 4.1 Complete candidate pool

Every assignment freezes:

- one complete in-scope exercise-catalog snapshot and its scope rule;
- one candidate row for every exercise version in that snapshot, including
  active, inactive, retired, unavailable, and otherwise excluded versions;
- exactly one terminal eligibility state (`eligible` or `excluded`) and a
  typed reason for every candidate;
- deterministic need/compatibility features;
- model scores and ranks when a model exists;
- deterministic fallback ranks when no approved model exists;
- selected exercise/version;
- selection mode and every candidate's selection probability;
- RNG seed/draw/algorithm and 80/20 policy version when randomized, or an
  explicit `not_randomized` reason when deterministic;
- complete pool hash;
- detector, feature, rule, code, exercise-catalog, and model versions;
- exact clip/block/Take/recording lineage.

### 4.2 Gate before rank

The deterministic gate runs before any model ranking. It excludes at least:

- inactive, retired, missing, or checksum-invalid media;
- incompatible language or delivery format;
- unsupported or missing need evidence;
- contraindicated/safety-incompatible exercises;
- missing current processing authority;
- unreliable or `audio_unclear` source clips;
- missing exact audio-object SHA-256;
- a previously assigned identical exercise version for the same learning
  profile and need, unless a coach explicitly records a repeat rationale;
- exercises whose versioned eligibility contract cannot be reproduced.

The model may rank only the surviving pool. When no exercise survives, the
system creates a coach exercise request; it never invents a weak exercise or
bypasses safety.

### 4.3 As-of feature snapshot

Every selection freezes an immutable feature snapshot at `assignment_at`.
Only observations with `observed_at < assignment_at` and already committed
before the assignment transaction may enter it. The snapshot records:

- `feature_snapshot_id`, schema version, content hash, and creation time;
- maximum included source-event sequence and observation timestamp;
- exact speaker-baseline version and its contributing observation IDs;
- exact learning-profile observation IDs;
- prior exercise assignments/exposures available at that instant;
- excluded late/future event counts by typed reason.

Later practice attempts, future Takes, outcomes, coach/peer judgments, revised
baselines, or profile updates may append new observations but can never mutate
or backfill the historical snapshot. Dataset builders reconstruct the as-of
join and reject any example containing a post-assignment source event. One
canonical speaker remains in one split across every release and surface.

### 4.4 80/20 exposure

The 80/20 rule is an exposure policy, not a dataset split:

- The immutable randomization unit is one `exercise_assignment_id` for the
  exact `(speaker_id, source_clip_id, block_id, need_contract_version,
  exposure_policy_version)` tuple.
- A database-enforced idempotency key creates that assignment once. Refresh,
  polling, retry, worker replay, or redelivery returns the same assignment and
  never redraws.
- The assignment freezes RNG algorithm/version, protected seed, seed
  commitment, draw, and every candidate's probability before selection.
- With two or more eligible exercises, the top-ranked candidate has
  probability exactly 0.80. The remaining 0.20 is distributed across every
  other eligible candidate by predeclared normalized exploration weights.
  All candidate probabilities, including the top candidate, are stored and
  sum to 1.0 within deterministic numeric tolerance.
- With one eligible exercise, its probability is 1.0 and the assignment is
  `deterministic_singleton`, not exploration evidence.
- The versioned exposure policy declares a minimum non-zero exploration
  probability. An otherwise valid observation below that floor remains
  product/evaluation evidence but receives
  `causal_evaluation_excluded=insufficient_assignment_probability`.
- The first assignment for one `(speaker_id, need_contract_version)` is the
  initial causal cohort. Repeated observations are separately marked and are
  not pooled into that cohort. Prior exposure and any approved repeat rationale
  are frozen in the as-of snapshot so carryover is explicit.
- An identical exercise version previously exposed for the same profile/need
  is excluded unless an immutable coach repeat rationale exists. That repeated
  assignment remains a separate unit with its own probabilities and cannot
  borrow the first assignment's outcome.
- `no_attempt`, abandonment, expiration, and loss to follow-up are
  missing/censored outcomes under the predeclared label specification. They
  are never negative adequacy labels.
- exploration changes only which eligible exercise is selected, never its
  content, the user's answer, or the blind packet.

User-facing 80/20 assignments cannot begin until the endpoint/evaluation
contract in §3.5 and this exposure-policy version are both approved. Before
then, serving—if separately authorized—selects the deterministic top eligible
exercise and records no randomized comparison.

No exposure exists until the authenticated client confirms that the assigned
exercise rendered. Delivery, polling, opening the Ideal Text, or server-side
selection is not exposure.

## 5. User workflow

1. Processing completes and opens the Project's Ideal Text immediately.
2. All frozen V3 Feedback items are attached to their exact Slides and
   Paragraphs. They do not appear through sequential replacement.
3. The user answers each Confident Voice item using the five-state taxonomy.
4. For any response except `confident_audio_unclear`, the system may create one
   exercise assignment for that exact clip after eligibility/ranking.
5. The assignment identifies the exercise already assigned so the user does
   not unknowingly repeat it. A replay is visible as the same assignment, not a
   new exposure or a new recommendation.
6. If no exercise exists, a post-blind coach request is queued. The next Take
   remains available; the user never waits for the coach.
7. A user may open the exercise, watch the exact versioned video, and record up
   to three same-passage attempts.
8. Each attempt is a separate Recording Attempt, not a presentation Take.
9. The app compares only valid, aligned attempts with the original exact clip.
   It returns qualitative copy and never exposes acoustic scores.
10. The user may keep one attempt and answer the approved practice-confidence
    self-report. Keeping does not admit it to Voice Album.
11. The assigned exercise and completed attempts remain visible in the
    Project so later recommendations can avoid accidental repetition.

Surface copy remains subject to founder sign-off. This design approves
semantics and identifiers, not final prose.

## 6. Coach and peer workflow

### 6.1 Blindness boundary

The initial packet schema is
`confidence-exercise-blind-packet-v1`. Its exact allowlist is:

- opaque `blind_packet_id`;
- opaque `review_assignment_id`;
- `packet_schema_version`;
- `confidence_taxonomy_version`;
- one assignment-scoped, expiring `playback_token` for the exact clip;
- `clip_duration_ms`;
- `language_code` when known;
- optional exact-passage ASR transcript, identified as machine transcription;
- the five allowed response identifiers and `audio_unclear` control.

No other field may enter the blind payload. In particular it excludes Project,
Take, recording, speaker, principal and coach-author identities; machine
predictions/scores/ranks; the user's response; acoustic measurements or need
labels; exercise catalogue/candidates/assignment; selection or exploration
metadata; prior or concurrent ratings; orange/lock state; practice attempts;
and outcomes. Internal lineage remains server-side and is referenced through
the opaque assignment only.

The packet schema, exact payload, and SHA-256 hash freeze at creation. These
are separate immutable events with actor, timestamp, packet/assignment ID, and
policy version:

1. `blind_packet_created`;
2. `blind_packet_accessed`;
3. `blind_judgment_submitted`;
4. `post_judgment_reveal_granted`;
5. `post_judgment_reveal_accessed`.

The database cannot grant or record a reveal before the same assignment has an
immutable submitted judgment. Access without submission remains unanswered;
it never becomes a label. Only after submission may the separate
post-judgment view reveal comparison/provenance and permit exercise selection
or authoring.

### 6.2 Multiple judgments and authorship

- More than one blind coach or peer judgment may reference the same exact clip.
- Each assignment/judgment remains separately attributable and immutable.
- The coach who later authors an exercise is not excluded from the confidence
  quorum, provided their blind judgment was submitted before reveal/authoring.
- Coach/peer judgments evaluate confidence only. They do not silently become
  exercise-effectiveness labels.
- A later reconsideration is a new judgment linked by `supersedes_id`; the
  original remains unchanged.

### 6.3 Exercise authoring

After blind submission, a coach may:

1. choose an existing eligible exercise;
2. record a case-specific exercise for the exact request; or
3. state that no safe/adequate exercise is presently available.

A case-specific exercise is versioned and may be shared with that user after
an explicit coach action. It is not automatically admitted to the reusable
pool. Reusable-pool promotion requires a separate content/safety review and a
new immutable catalog version.

## 7. Canonical data architecture

MLC-3 extends the existing canonical MLC-2 ledger; it does not create a
parallel identity, consent, exposure, review, object, or split system.

### 7.1 Registry amendment

Add one canonical learning surface:

```text
exercise_adequacy_classification
```

The existing seven MLC-2 surfaces remain unchanged. Product aliases such as
`exercise_match`, `practice_recommendation`, or `diagnostic_exercise` resolve
through the registry and may never create another dataset or model assignment.

### 7.2 New typed tables

| Table | Responsibility |
| --- | --- |
| `exercise_definitions` | Immutable logical exercise identity, owner/author, language, safety status, and lifecycle |
| `exercise_versions` | Immutable instruction/media/need-contract version and checksums |
| `exercise_need_contracts` | Versioned admissible acoustic properties, required features, exclusions, and contraindications |
| `exercise_catalog_snapshots` | Immutable in-scope universe and one row/hash for every included exercise version, regardless of lifecycle state |
| `exercise_candidate_sets` | Frozen complete eligible/excluded pool, policy/model/RNG versions and pool hash |
| `exercise_candidates` | One row per considered exercise version with eligibility, reason, probability, score and rank |
| `exercise_selection_feature_snapshots` | Immutable assignment-time learning-profile, baseline, prior-exposure and source-event as-of features |
| `exercise_assignments` | Exact selected Feedback/clip/block/exercise version and assignment state |
| `exercise_randomization_assignments` | Stable assignment unit, idempotency key, probabilities, RNG seed/draw, causal eligibility and repeat/carryover state |
| `exercise_requests` | No-match post-blind request and later coach resolution |
| `exercise_practice_sessions` | Exact original clip, assigned exercise snapshot and non-Take practice lifecycle |
| `exercise_practice_attempts` | Exact attempt audio/transcript/alignment/features with immutable object SHA-256 |
| `exercise_outcome_events` | Separate raw machine, user, blind-coach, and blind-peer observations by horizon |
| `learning_profiles` | Stable pseudonymous profile identity linked to canonical `speaker_id` |
| `learning_profile_observations` | Versioned need observations; never a universal judgment about the person |
| `exercise_blind_packet_events` | Versioned packet creation/access, judgment submission and post-judgment reveal audit events |

### 7.3 Reused canonical tables

- `ml_learning_surfaces` and aliases;
- `ml_model_runs`, classification runs, and provider-neutral assignments;
- `ml_evidence_spans` and exact audio/object artifacts;
- `ml_candidate_sets`/selection lineage where the shared contract applies;
- `ml_review_assignments` and immutable judgments;
- rendered `ml_exposures`;
- acquisition-principal, speaker, consent/authorization, retention, and purge
  lineage;
- speaker-disjoint split assignments;
- R2 object artifacts and checksums;
- dataset release, exclusion, training, evaluation, and promotion lineage.

The implementation design may normalize shared candidate-set fields instead
of duplicating them, but exercise-specific constraints must remain typed and
must not turn the canonical ledger into a generic JSON label table.

### 7.4 Required foreign-key lineage

Every assignment and outcome resolves:

```text
acquisition_principal
  -> canonical speaker
  -> Project
  -> Take
  -> Recording Attempt
  -> audio object + SHA-256
  -> Slide run
  -> 75-word block
  -> exact snippet/clip interval
  -> frozen Feedback candidate and rendered exposure
  -> frozen exercise candidate set
  -> selected exercise version and rendered exposure
  -> practice session
  -> practice attempt audio object + SHA-256
  -> separate raw outcomes and human judgments
```

No URL, filename, transcript text, display name, or content hash alone is an
identity key. Hashes verify bytes; provenance coordinates identify records.

## 8. Signal and label boundaries

Keep these records separate:

- machine confidence prediction;
- relative block selection;
- owner confidence self-report;
- blind coach confidence judgment;
- blind peer confidence judgment;
- deterministic exercise eligibility result (product policy only, never an
  adequacy label);
- learned adequacy prediction among already-eligible exercises;
- exercise selection/exposure;
- practice attempt comparison;
- owner practice self-report;
- coach/peer practice confidence judgment;
- professional exercise authoring/share action.

Never infer:

- shown = helpful;
- opened = attempted;
- skipped/timeout = rejection;
- `confident_yes` = exercise success;
- coach confidence Yes = exercise effectiveness;
- orange applied = confidence/praise truth;
- an authored exercise = a positive adequacy label;
- the best attempt = objective improvement without the approved endpoint;
- one need observation = a permanent user trait.
- eligible/excluded = improved/not improved.

Practice user self-report remains non-blind and potentially
training-eligible under a future label contract. Coach/peer practice ratings
remain independently blind. Existing revealed professional `yes/no/refine`
controls remain evaluation-only.

Exercise outcomes never train `confidence_classification`. Confidence data and
exercise-adequacy data receive separate releases and evaluation reports.

## 9. Authorization, retention, and deletion

`personalized_exercise_recommendation` is the product processing purpose.
`exercise_adequacy_classification` is the technical learning-surface ID; it
must never appear as authorization copy or independently justify collection.

Before user-facing assignment, Product/legal must activate the real
`personalized_exercise_recommendation` capability and connect it to monitoring,
retention, deletion, data-rights, provider, and policy controls under PLF.

Every clip keeps its immutable acquisition snapshot, while current authority
is rechecked before provider upload, exercise processing, dataset release,
training/retry, evaluation, and promotion. Termination, deletion, retention
expiry, quarantine, or purpose withdrawal cancels pending exercise work and
traverses assignments, attempts, R2 objects, releases, runs, adapters, and
model assignments through the canonical purge graph.

No MLC-3 dataset may be created until exact source and attempt audio-object
SHA-256 values are independently verified or recomputed at release time.

## 10. Legacy exercise cutover

The current `diagnostic_exercise`, `confident_voice_practice`,
`confident_voice_practice_attempt`, and related routes are mixed product/eval
state. They are not MLC-3 training data.

Required audit classifications:

- exercise media/content that can be copied into a reviewed immutable MLC-3
  catalog version;
- current user-visible assignments/attempts that must remain readable;
- legacy matching, ranking, labels, and revealed professional decisions that
  remain excluded from canonical datasets;
- unknown dependencies that fail closed.

Cutover rules:

1. Preserve existing user-visible product state.
2. Do not import or relabel historical matching/outcome rows for training.
3. One atomic per-surface flag enables canonical exercise writes while
   disabling new legacy matching/evaluation writes.
4. Rollback may disable the new writer/serving path but never reactivate legacy
   learning writes.
5. The old one-exercise-per-Take limit and hard-coded
   `hear-every-word-v1` matcher do not constrain MLC-3.
6. Existing exercises enter the new pool only through explicit reviewed
   version creation with media checksum and safety/need contracts.

## 11. Incremental implementation slices

### Slice M3-1 — standalone contract and dependency audit

- approve this document;
- amend the canonical product contract and decision filter for the V3 budget;
- produce checked-in producer/reader/route/job/UI/table mapping;
- classify every legacy exercise dependency;
- no schema or runtime changes.

Delivered audit:
[`MLC3-EXERCISE-DEPENDENCY-AUDIT.md`](MLC3-EXERCISE-DEPENDENCY-AUDIT.md).

Gate: Founder/Product + ML/data approval.

### Slice M3-2 — dark catalog and lineage foundation

- registry amendment;
- typed immutable exercise/need/version tables;
- exact object SHA-256 lineage;
- learning-profile identity;
- review/authorization/RLS/RPC contracts;
- no producer activation.

Gate: ML/data + Engineering implementation review and PostgreSQL rehearsal.

### Slice M3-3 — dark assignment frames

- complete eligible/excluded exercise inventory;
- deterministic gate;
- deterministic fallback ranker;
- dark 80/20 probability/RNG provenance with no rendered exposure;
- immutable assignment-time as-of feature snapshot;
- post-blind no-match exercise requests;
- `serves_user=false`, `dataset_eligible=false` structurally enforced.

Gate: founder-only dark comparison approval.

### Slice M3-4 — practice and coach dark workflow

- practice sessions/attempts and exact-byte lineage;
- blind review packet and reveal boundary;
- case-specific authoring and explicit share contract;
- raw outcome horizons;
- no user exposure.

Gate: ML/data + Engineering + coach-workflow review.

### Slice M3-5 — frontend behind disabled flags

- per-block frozen Feedback presentation;
- five-state answer;
- assigned-exercise history;
- practice recorder;
- post-render exposure acknowledgments;
- founder-approved copy;
- no activation.

Gate: Product/UI acceptance and accessibility/mobile tests.

### Slice M3-6 — founder canary

- activate V3 Manager + exercise assignment only for the exact founder
  principal;
- keep legacy users on the current serving Manager;
- assign only the deterministic top eligible exercise unless the separately
  approved endpoint/evaluation and 80/20 policy contracts are active;
- compare completeness, block distribution, no-feedback failures, assignment
  eligibility, and live-loop latency;
- datasets/training/promotion stay disabled.

Gate: ML/data + Engineering + Product/legal + production acceptance.

### Slice M3-7 — controlled serving cutover

- atomically enable V3 serving/canonical exercise writes and disable new
  legacy matching/evaluation writes;
- preserve readable legacy product state;
- monitor feedback completeness, exposure confirmation, exercise failures,
  latency, and rollback invariants.
- keep randomized 80/20 exposure independently disabled until its predeclared
  endpoint, missing-data, evaluation, and assignment contracts are approved.

Gate: explicit founder deployment authorization.

Dataset creation, training, evaluation, and promotion remain separately gated
after working product serving is proven.

## 12. Verification matrix

### Feedback policy

- deterministic slide-bounded 60-90/75-word partition;
- one and only one selected confidence candidate per valid block;
- Take 1 contains no rewrite/praise;
- Take 2+ contains at most one global weakest actionable item and at most one
  global strongest evidence-backed praise; an honest empty lane freezes
  `no_defensible_candidate` without creating a card;
- complete candidate/exclusion inventory and frozen whole set;
- no machine numbers in user payloads;
- no item replacement after any response;
- exact audio and Paragraph lineage for every selected clip.

### Exercise selection

- gate always precedes ranking;
- model cannot select an excluded exercise;
- no-match creates a request, not invented content;
- complete pool/probability/RNG/version/hash reproducibility;
- 80/20 is exposure policy, never speaker/dataset split;
- one immutable randomization unit survives refresh/retry without redraw;
- every eligible candidate, including the top candidate, has a stored
  probability and the probabilities sum to one;
- sub-floor probabilities receive typed causal-evaluation exclusion;
- assignment-time feature/baseline/profile snapshots reject every
  post-assignment observation;
- `no_attempt`, dropout, expiry, and loss to follow-up are missing/censored,
  never negative;
- repeated exercise excluded unless explicit reviewed repeat rationale;
- client render required for exposure;
- replay is idempotent and not a new assignment/exposure.

### Blindness and provenance

- blind packet matches the exact `confidence-exercise-blind-packet-v1`
  allowlist and contains none of the denied machine/user/selection fields;
- packet create/access, judgment submit, reveal grant and reveal access are
  separate immutable events;
- reveal impossible before immutable judgment submission;
- multiple coach/peer assignments remain separate;
- author may join confidence quorum only when judgment predates reveal;
- coach confidence never becomes exercise-effectiveness truth;
- owner, machine, coach, peer, authoring, and product actions remain separate.

### Practice and live loop

- practice attempt is not a Take;
- invalid/misaligned/audio-unclear attempt excluded with typed reason;
- maximum three attempts per practice session;
- no score or metric in the owner payload;
- next Take remains available throughout coach/exercise work;
- Ideal Text and locks/orange roots never mutate from exercise activity;
- Voice Album admission still requires exact-attempt Machine + User + Coach Yes.

### Security, authorization, and deletion

- RLS and RPC-only writes for canonical tables;
- acquisition-principal and speaker ownership enforced in database;
- current purpose authority checked before every external or learning boundary;
- object hashes recomputed for releases;
- termination/deletion cancels pending assignments/requests/provider jobs;
- purge traversal reaches source/attempt objects and later release/model links;
- datasets, training, evaluation, and promotion default off and cannot be
  enabled by a serving flag.

### Compatibility and rollback

- no legacy training/provenance dual writes;
- historical product state remains readable;
- unknown dependency blocks cutover;
- disabled/dark/serving modes are fail closed;
- rollback never reactivates legacy learning writes;
- migration apply/reapply and rejection rehearsals pass PostgreSQL 16.

## 13. Review gates and remaining decisions

ML/data must explicitly approve before implementation:

1. the relative-best operational definition;
2. the V3 feedback budget replacing exact-three;
3. the acoustic-need construct and allowed feature contracts;
4. deterministic eligibility versus learned adequacy separation;
5. complete catalog/candidate/exclusion and 80/20 assignment semantics;
6. immutable assignment-time feature snapshots and temporal-leakage controls;
7. exact clip/block/exercise/attempt lineage;
8. versioned blind-packet allowlist and post-judgment reveal boundary;
9. separation of raw outcome horizons;
10. the label/evaluation contract required before randomized exposure;
11. speaker-disjoint release/evaluation rules;
12. legacy non-import and cutover boundaries.

Before user-facing activation, the project additionally requires:

- canonical product-contract amendment;
- exact founder-approved surface copy;
- Product/legal activation of `personalized_exercise_recommendation` and the
  applicable authorization/AI notice;
- processor, retention, deletion, and data-rights verification;
- Engineering/security review;
- founder-only production rehearsal and explicit deployment authorization.

Before any dataset/training/evaluation/promotion, the project separately
requires an approved endpoint/time-horizon label specification, independently
verified audio-object hashes, immutable surface-specific release, and explicit
ML/data, Product/legal, Engineering/security, production, and founder approval.

## 14. D1 -> D2 revision summary

1. Separated deterministic exercise eligibility from learned adequacy;
   eligibility can neither be a label nor be overridden by a model.
2. Blocked user-facing 80/20 exploration until a primary endpoint, horizon,
   attempt rule, missing-data treatment, estimand, and evaluation plan are
   predeclared and approved.
3. Defined the immutable assignment unit, idempotent seeded draw, complete
   probability vector, causal-probability floor, repeated exposure/carryover,
   and censored no-attempt/dropout behavior.
4. Added immutable assignment-time as-of feature snapshots and explicit
   post-assignment leakage rejection while preserving speaker-disjoint splits.
5. Replaced the contradictory active-only pool with a complete in-scope
   catalog snapshot whose every version is eligible or typed-excluded.
6. Added `no_defensible_candidate` for honest empty rewrite/praise lanes on a
   valid Take.
7. Replaced open-ended blind context with
   `confidence-exercise-blind-packet-v1` and five separate immutable packet,
   judgment, and reveal events.
8. Split the Decision Filter into F1-CORE Feedback Policy V3 and F2 exercise
   adequacy verdicts.

## 15. Decision filters

```yaml
VERDICT:  ADVANCE-F1
CATEGORY: F1-CORE
WHY:      The 75-word policy directly sharpens Manager evidence arbitration;
          it changes the frozen Feedback set while preserving exact evidence,
          non-invention, and user-controlled Ideal Text.
REDIRECT: Approve the V3 feedback-budget amendment, then update the canonical
          product contract before serving it.
```

```yaml
VERDICT:  ADVANCE-F2
CATEGORY: F2
WHY:      Exercise adequacy connects exact confidence evidence to
          provenance-safe practice, blind review, and isolated learning
          without exposing scores or blocking the live loop.
REDIRECT: Approve MLC-3-D2, then implement the dark catalog/lineage foundation
          before any serving, dataset, training, evaluation, or promotion.
```

> **ML/DATA DESIGN ACCEPTED — `MLC-3-D2`. Architecture is approved; acoustic
> need feature contracts, an outcome-label specification, 80/20 activation,
> implementation, migration, runtime activation, dataset creation, training,
> evaluation, promotion, deployment, and production deletion remain separately
> unauthorized.**
