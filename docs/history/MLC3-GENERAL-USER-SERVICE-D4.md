# MLC-3 General-User Service Rollout D4

Status: design proposal for ML/data and Engineering review. No implementation
or activation is authorized by this document.

This revised amendment replaces the founder-only rollout boundary with a
database-authoritative generally available product boundary. It does not alter
Feedback V3, N1 measurement, exercise eligibility, blind review, coach
authoring, practice selection, or catalogue semantics. Dataset creation,
training, evaluation, and promotion remain unavailable.

D2 resolved the four D1 review findings by defining one rollout-aware resolver
and new persisted service modes, complete cohort versioning plus an explicit
founder skip-cohort risk artifact, acquisition-specific speaker identity and
missingness, and executable capacity/backpressure policy.

D3 makes the dual-purpose service authority exact and splits speaker count,
speaker identity, and target-span provenance so acoustic routing cannot operate
on the wrong voice.

D4 additionally requires immutable same-speaker equality across source and
practice clips before any comparison or adequacy evidence can exist.

## 1. Product outcome and non-goals

After activation, any authenticated product user may use the accepted
Feedback V3 -> deterministic exercise -> playback -> re-record -> subjective
comparison loop when every exact service requirement is satisfied.

General availability does not mean anonymous access, automatic consent,
automatic exercise creation, automatic coach access, or pooled-learning
eligibility. A user with missing or withdrawn service authorization, an open
purge, invalid media, stale lineage, or no eligible exercise receives the
existing typed unavailable/no-match outcome.

This amendment creates no score, confidence verdict, effectiveness label,
adequacy label, ninth learning surface, dataset row, training job, evaluation,
or promotion path.

## 2. Versioned rollout policy

Add one append-only rollout-policy ledger with a stable policy identity and
immutable revisions. The closed rollout states are:

- `disabled`
- `explicit_cohort`
- `generally_available`
- `retired`

Exactly one revision may be current. A revision freezes:

- service-contract version and checksum;
- rollout-policy/code version and checksum;
- activation scope and effective time;
- the exact `personalized_exercise_recommendation` and `coach_review` purpose
  versions and the policy version that must authorize both on one receipt;
- approved acoustic-need contract (`rushed_phrase_endings` only);
- language, safety, rights, retention, deletion, and media-policy versions;
- backend and frontend gate contract versions;
- monitor and emergency-disable contract versions;
- activating operator identity and reviewed authorization evidence hash.
- access-resolver version and checksum;
- operation-mode registry version;
- the complete capacity/backpressure policy in section 9.

Changing scope creates a successor revision; no historical revision is
updated. Database activation is an explicit privileged RPC, never a migration
seed or application-start side effect. The release migration seeds only a
`disabled` revision.

The existing `mlc3-first-client-service-v1` remains the content and lifecycle
contract, but its founder-only access resolver is not reused for new rollout
modes. The migration adds one central
`require_mlc3_service_access_v2(acquisition_principal_id,
expected_rollout_revision_id, expected_enrollment_revision_id)` resolver. Every
D2/D3/D5 service wrapper, helper, retry and media-read boundary must call this
resolver after contention. No runtime wrapper may continue to call
`require_mlc3_service_principal_v1` after cutover. Execute permission on the old
resolver is revoked from runtime roles; it remains only for immutable
historical verification.

The closed operation-mode registry becomes:

- `synthetic_dark` for historical and rehearsal-only records;
- `allowlisted_service` for existing first-client records;
- `cohort_service` for exact-cohort rollout records;
- `general_service` for generally available records.

Old rows and hashes are unchanged. Every new cohort/general service row stores
and hashes the exact `rollout_revision_id`, `enrollment_revision_id`, access
resolver version and operation mode. The columns are nullable only for
historical rows whose original contract did not have them. Composite foreign
keys bind the row's acquisition principal to its enrollment and rollout
revision. A row cannot be replayed across rollout modes or revisions.

The V2 resolver distinguishes `explicit_cohort` from `generally_available`.
For a cohort revision it requires exact membership in the frozen cohort set.
For a GA revision it requires current general eligibility under section 3. It
never copies GA users into `mlc3_service_principal_allowlist` and never reports
general access as allowlist provenance.

### 2.1 Exact cohort mechanics and progression

An `explicit_cohort` revision freezes one immutable cohort set containing:

- the ordered unique acquisition-principal IDs;
- membership-set SHA-256 and member count;
- maximum member count and activation window;
- per-member addition evidence and operator identity;
- the capacity policy and exit criteria used to evaluate the phase.

Membership is server/database derived from that frozen set. A browser cannot
add, omit, reorder, or substitute a principal. Adding or removing a member
creates a new set and rollout revision; there is no automatic expansion.
Concurrent activation and membership changes serialize on the rollout-policy
identity.

The normal production sequence is a reviewed 5--20 principal cohort followed
by a successor `generally_available` revision only after the cohort's signed
operational evidence satisfies its frozen exit criteria: no authorization,
cross-principal, deletion, hash, or resurrection breach; recovery backlog
within policy; alerts and emergency disable proven; and coach capacity within
policy. These are operational criteria, not exercise-quality judgments.

On 2026-09-09 Product explicitly directed that, because there are currently no
users, the first active revision should be generally available rather than an
explicit cohort. D4 treats that as a requested risk decision, not an
engineering default. Skipping the cohort is permitted only if a separately
reviewed and signed immutable `founder_skip_cohort_v1` decision is supplied to
the activation RPC. It must identify this design checksum, the exact production
deployment, the initial capacity policy, the absent-cohort reason, the founder
identity and timestamp. Missing or mismatched risk evidence fails closed. This
document and the founder statement do not themselves activate the service.

## 3. Exact authenticated principal eligibility and enrollment

The server resolves the authenticated account to exactly one canonical
`acquisition_principal_id`. Email, user ID, coach identity, linked accounts,
speaker profile, and learning profile are not rollout identities.

Under `generally_available`, the exact principal may enter the service only
when all of these are true at the serialization point:

1. the service contract and current rollout revision are active;
2. the account-to-principal binding is current and unambiguous;
3. `personalized_exercise_recommendation` and `coach_review` are both currently
   operational and authorize processing;
4. both exact purpose links exist on the same current authorization receipt
   under the exact accepted policy, and that receipt belongs to the principal;
5. no service block, quarantine, retention stop, withdrawal, or unresolved
   purge applies;
6. the backend master gate is enabled.

Create an append-only principal-enrollment ledger. The first successful
service entry creates one immutable enrollment revision containing the exact
principal, account binding, rollout revision, current service-authorization
receipt/policy, both exact purpose-link identities, eligibility result,
idempotency identity, and canonical hash.
Enrollment is product access provenance only. It is not consent for a prior
recording and is never dataset eligibility.

Enrollment does not retroactively authorize any recording. Every offer,
playback, upload, practice attempt, comparison, coach review, or guidance
operation must continue to prove the exact acquisition-time authorization of
the source or practice recording independently and recheck current authority
after contention. Source and practice acquisitions never borrow one another's
authorization.

An enrollment successor records withdrawal, service blocking, or operator
revocation. Re-enrollment after a later valid authorization creates another
revision and cannot revive invalid historical operations.

### 3.1 Speaker count, identity, and target span remain separate

Access identity and speaker identity are different facts. Every source and
practice acquisition binds one immutable speaker-provenance record containing
two independent closed states:

- `speaker_count_status`: `single`, `multiple`, or `unknown`;
- `speaker_identity_status`: `resolved` or `unresolved`.

`speaker_id` is non-null exactly when identity status is `resolved`. The record
also freezes the acquisition, recording attempt, audio object/hash, count and
identity policy versions, evidence source, acquisition principal, and binding
hash. Count does not prove identity, and identity does not prove that the
entire recording contains only one speaker.

Confident Voice, N1 extraction, exercise matching, practice comparison, and
speaker-relative processing require one exact target speaker for the exact
source span. The frozen target provenance contains canonical `speaker_id`,
clip/segment identity, audio hash, start/duration, transcript span/hash,
segmentation policy/run version, and reviewer or self-speaker assertion
identity. A `multiple` or `unknown` recording may enter those paths only when a
reviewed immutable segmentation resolves the exact span to one target speaker.
Otherwise it fails closed with a typed non-routable outcome. Non-speaker-
dependent product paths may still operate when their own policy permits.

All unresolved-identity material and all multiple/unknown-speaker material
without an exact reviewed target segment remain structurally excluded from
future speaker-disjoint datasets.

### 3.2 First-user pseudonymous speaker creation

A new genuine user obtains a stable pseudonymous canonical `speaker_id` only
through an explicit immutable self-speaker operation bound to one exact
recording acquisition. The operation records the user's affirmative product
action that the target recording/span contains their own voice, the exact
principal, authorization receipt/policy, recording attempt, audio/hash, target
span, accepted self-speaker policy version, idempotency identity, and canonical
hash. Final user-facing copy requires founder sign-off before implementation.

The server creates a random pseudonymous UUID and a principal-speaker binding
revision only after that explicit action. It never derives speaker identity
from email, account ownership, name, device, transcript, pitch, acoustic
similarity, coach judgment, or enrollment. Silence, refusal, uncertainty,
imported third-party audio, or a multi-speaker span leaves identity unresolved.
Linking one speaker across acquisition principals requires a separate reviewed
identity-link operation; it is never automatic.

### 3.3 Same-speaker comparison boundary

Before creating a practice comparison, pair assignment, owner preference,
coach randomized A/B review, or any future exercise-adequacy evidence, the
database proves through the two immutable target-span bindings that
`source_target_speaker_id = practice_target_speaker_id`. It locks and
revalidates both speaker-binding revisions, both exact target spans, their
current non-superseded status, and equality after every potentially blocking
operation and on replay.

Missing, superseded, unresolved, conflicting, or differently resolved speaker
identity produces the typed exclusion
`speaker_identity_mismatch_or_unresolved`. That exclusion creates no pair,
preference, comparison, effectiveness supervision, or adequacy record. It is
product eligibility provenance only.

A later identity revision never edits or reinterprets an existing frozen pair.
After explicit identity review, it may authorize a new versioned eligibility
and pair revision whose hash includes both new binding revisions. Historical
pairs and exclusions remain immutable.

Every later source or practice acquisition requires its own explicit
self-speaker/target-span assertion or reviewed target-speaker segmentation
before it may bind the stable pseudonymous `speaker_id`. Account ownership,
prior enrollment, or an earlier recording cannot assign a speaker to the new
acquisition. The self-speaker action is identity and routing provenance used
for exact grouping and split safety; it is never confidence, improvement,
preference, adequacy, or effectiveness supervision.

## 4. HTTP and frontend gates

Replace the configured principal-list authorization with these independent
boundaries:

1. active database service contract;
2. active database rollout policy;
3. `MLC3_SERVICE_ENABLED=true` on every relevant backend process;
4. exact database principal eligibility and enrollment;
5. `NEXT_PUBLIC_MLC3_SERVICE_UI_ENABLED=true` in the exact production frontend
   build.

The frontend flag is presentation-only. A direct API call must still pass the
backend and database boundaries. The legacy `MLC3_PILOT_ENABLED`,
`MLC3_PILOT_PRINCIPAL_IDS`, and `NEXT_PUBLIC_MLC3_PILOT_UI_ENABLED` settings
cannot authorize the general-user path after cutover; leaving them set must not
expand access.

Coach inline authoring remains separately controlled by
`MLC3_COACH_INLINE_AUTHORING_ENABLED` and the exact canonical coach mapping.
General-user rollout never turns a user into a coach or gives one user access
to another user's audio.

Every runtime service returns a typed unavailable response when configuration
is absent, inconsistent, or stale. No endpoint falls back to the founder
allowlist or a route-local consent check.

## 5. Exact acquisition and signal boundaries

All previously accepted first-client invariants remain mandatory:

- offers require the exact frozen V3 membership, candidate, rendered exposure,
  immutable owner response, evidence span, audio lineage, N1 source-pattern
  result, complete inventory, need contract, and catalogue snapshot;
- silence and `confident_audio_unclear` cannot create an offer;
- the source Take remains `source_before_exercise`;
- a practice attempt exists only after confirmed exercise playback;
- first-valid selection retains unresolved earlier attempts;
- original confidence judgment, practice confidence judgment, owner A/B
  preference, and coach randomized A/B preference remain separate;
- delivery, rendered exposure, playback, and capture remain distinct events;
- the legacy hard-coded `improved` calculation remains excluded;
- historical dark assignments are never converted into service assignments.

Every `cohort_service` or `general_service` row remains
`dataset_eligible=false`. Product responses, coach notes, measurements,
practice attempts, preferences, exposures, and catalogue decisions do not
become labels merely because the service is generally available. Every such
row proves its exact rollout/enrollment revision through the central resolver;
no wrapper may stamp these modes from a session variable alone.

The central resolver, enrollment, every source/practice acquisition check,
every exact replay, and every post-contention revalidation require
`personalized_exercise_recommendation` and `coach_review` to be operational,
processing-authorizing, and linked on the same current receipt and exact policy.
No cached enrollment or historical receipt supplies continuing authority.

## 6. Service authorization versus pooled authorization

Required service authorization gates the product. Optional
`pooled_model_improvement` authorization never gates product access, R2
playback, practice, coach guidance, or deletion.

For this service, “required service authorization” always means both exact
purpose IDs—`personalized_exercise_recommendation` and `coach_review`—on one
current receipt and exact accepted policy. A receipt containing only one
purpose, two purposes split across receipts/policies, or a non-operational or
non-processing-authorizing registry entry fails closed. The optional pooled
purpose cannot substitute for either required purpose.

Each original and practice acquisition freezes its own acquisition-time
service snapshot, speaker-status record, and acquisition-time pooled state. A
later pooled opt-in is non-retroactive. Withdrawal or deletion is checked
independently for each acquisition.

No generally available record is dataset eligible. A future immutable dataset
release still requires a separately reviewed surface-specific label contract,
speaker-disjoint split, exact source and practice pooled authorization,
current withdrawal/deletion checks, hashes, and provenance. Training,
evaluation, and promotion remain independently disabled.

## 7. Media, deletion, and recovery

The accepted R2 permit and recovery order remains unchanged:

`durable permit/recovery -> write_started -> R2 write -> exact read-back hash -> acknowledgement -> finalization`

Service mode fails closed when R2 is unavailable; it never stores bytes through
a fallback provider while claiming R2. Authenticated same-origin reads retain
their authoritative before/after checks. Every potentially blocking media
operation locks the shared validity identity and rechecks the fresh leaf state.

Principal enrollment, rollout revisions, and access decisions join the
deletion registry. Withdrawing one user invalidates their user-scoped links and
future access without deleting shared independently clean media that still has
valid references or a legal hold. User-source-dependent catalogue content is
logically invalidated when its source authority disappears.

No retry, late acknowledgement, delayed worker, stale transaction, or
concurrent enrollment can resurrect a withdrawn or purged principal.

## 8. Monitoring

Replace founder-specific monitoring with an aggregate general-service monitor.
It must cover the exact active rollout revision and report only aggregate or
opaque operational identities—never transcript text, audio, coach answers, or
user-facing classifier values.

The monitor checks at least:

- active enrollment count and enrollment/revocation failures;
- for cohort mode, the exact frozen member count/hash and zero active foreign
  enrollments; for GA, zero active service rows without a matching enrollment;
- resolved, unresolved and multi-speaker acquisition counts without exposing
  speaker or principal identity;
- cross-principal rejection count;
- unresolved practice and coach-media recovery states;
- stale permits, deletion fences, quarantines, and purge conflicts;
- offer, render, playback, practice, review, and guidance typed failures;
- assignments that cannot reach completion because of missing exact identity;
- every section 9 capacity counter, window, backpressure state and automatic
  halt transition;
- database, web, worker, monitor, and frontend gate/config consistency;
- any non-zero `dataset_eligible` row in the registered service families.

Operational alert thresholds and windows are versioned and reviewed as
reliability policy. They are not acoustic measurements or user-facing quality
scores.

## 9. Versioned capacity and backpressure

Every active rollout revision freezes the following numeric operational
limits. The proposed initial general-user policy is deliberately conservative:

- at most 20 enrollment transactions concurrently and 50 new enrollments per
  rolling hour;
- at most 10 media uploads concurrently across the service and 2 per
  acquisition principal;
- at most 500 outstanding required blind-review assignments across the
  rollout and 100 assigned to one coach;
- maximum oldest required coach-queue age of 72 hours before new exercise
  authoring is paused;
- at most 10 GiB of newly written service media per rolling 24 hours;
- at most 25 unresolved upload/recovery records, with no unresolved recovery
  older than 15 minutes.

The values, units, windows, count queries and policy checksum are persisted in
the rollout revision. A deployment cannot override them through environment
variables alone. Changing a limit requires a successor disabled rollout
revision and review.

The central resolver and exact operation RPC enforce the applicable limit at a
database serialization point before reserving work. The closed typed
backpressure outcomes are:

- `MLC3_ENROLLMENT_CAPACITY_REACHED`;
- `MLC3_UPLOAD_CAPACITY_REACHED`;
- `MLC3_COACH_QUEUE_BACKPRESSURE`;
- `MLC3_MEDIA_BUDGET_REACHED`;
- `MLC3_RECOVERY_BACKLOG_BLOCKED`;
- `MLC3_ROLLOUT_HALTED`.

Backpressure records are product operations evidence only. They are never
quality judgments or ML labels. Capacity exhaustion cannot bypass blindness,
reuse stale authorization, fabricate an exercise, or break the asynchronous
record -> process -> Ideal Text -> next-Take loop.

The monitor may invoke one reviewed, SECURITY DEFINER halt-only RPC when any
of these automatic-stop conditions occurs:

- any confirmed cross-principal access or identity mismatch;
- any authorization, deletion, or purge bypass;
- any R2 byte/hash mismatch or deleted-object resurrection;
- unresolved recovery count/age above the frozen hard limit;
- missing or inconsistent database, web, worker, monitor, or frontend gate
  attestation.

The monitor RPC can only transition the current revision from active to
`halted`/disabled. It cannot activate, enroll a principal, expand a cohort, or
change a capacity value. Queue age, upload concurrency, media budget, and
review saturation create scoped backpressure first; they halt the whole
rollout only if the frozen policy explicitly marks that threshold as a hard
stop.

## 10. Emergency disable and rollback

The emergency procedure targets one exact five-part surface:

1. database rollout policy;
2. database service contract;
3. backend user-service gate on every web/worker/monitor process;
4. backend coach-inline gate on every relevant process;
5. frontend user and coach presentation gates for the exact production build.

Database disable is authoritative and immediate even while a frontend build is
cached. In-flight requests revalidate after contention and fail closed. Two
sequential disable attempts must be idempotent, preserve the same target set,
end fully disabled, and retain signed operation receipts. Rollback never
deletes historical product records.

## 11. Release and activation sequence

1. Implement the migration, runtime boundary, repository layer, frontend
   presentation gate, monitor, readiness checker, and emergency-disable
   tooling locally with all gates disabled.
2. Run independent ML/data and Engineering implementation review.
3. Assign a migration number and run release review.
4. Deploy the accepted code and disabled migration.
5. Produce fresh production R2, Railway, Vercel, Sentry, permission, RLS,
   zero-learning-state, and two-pass emergency-disable evidence.
6. Run the SELECT-only production readiness report while still disabled.
7. Complete the normal cohort phase and its exit review, or present the exact
   separately reviewed `founder_skip_cohort_v1` risk artifact. Then obtain
   explicit general-user activation acceptance and founder authorization.
8. Activate database authority first, backend gates second, and frontend
   presentation last. Verify each boundary between steps.

No migration, deploy, or environment-variable change may itself activate the
service. Failure at any step returns the system to the fully disabled state.

## 12. Required implementation regressions

At minimum, prove:

- an authenticated, currently authorized principal can enroll exactly once;
- an anonymous, ambiguous, withdrawn, blocked, quarantined, or purging
  principal cannot enroll or use the service;
- two concurrent first requests create one immutable enrollment and one exact
  replay;
- stale and foreign account/principal/rollout identities fail closed;
- later opt-in does not authorize earlier source or practice acquisitions;
- source and practice acquisition snapshots cannot substitute for each other;
- either required service purpose missing, split across receipts/policies,
  non-operational, or non-processing-authorizing blocks enrollment and every
  acquisition/replay boundary; pooled permission cannot substitute;
- direct API calls cannot bypass the database rollout policy;
- legacy pilot variables and allowlist rows cannot authorize general access;
- `allowlisted_service`, `cohort_service`, and `general_service` rows cannot be
  replayed or relabelled across modes or rollout/enrollment revisions;
- every D2/D3/D5 runtime wrapper uses the central V2 resolver, while the old
  resolver is inaccessible to runtime roles for new writes;
- exact cohort membership, order, count, hash, capacity ceiling and revision
  are immutable; automatic membership expansion fails;
- GA cannot be the first active revision without the exact separately reviewed
  founder risk-decision artifact;
- enrollment cannot create or infer a speaker identity;
- speaker count and speaker identity cannot substitute for each other;
- Confident Voice/exercise routing rejects an unresolved target speaker and a
  multiple/unknown-speaker recording without exact reviewed target
  segmentation;
- the explicit self-speaker operation alone can create a first pseudonymous
  `speaker_id`, exact replay is idempotent, and foreign/stale/uncertain
  assertions fail closed;
- different resolved source/practice speakers, unresolved practice identity,
  stale or superseded bindings, and contention-time identity changes create
  only `speaker_identity_mismatch_or_unresolved` and no pair or supervision;
- exact same-speaker source/practice replay returns the same frozen pair, while
  a later reviewed speaker correction can create only a new versioned
  eligibility/pair revision;
- unresolved identity and unsegmented multiple/unknown-speaker acquisitions
  are structurally future-dataset ineligible;
- one user cannot read, render, answer, upload, replay, delete, or review
  another user's objects through any D2/D5 route;
- coach access requires its separate current role and exact assignment;
- withdrawal/deletion during enrollment, offer, playback, upload, finalization,
  retry, review, guidance, and publication fails without partial records;
- unresolved media remains discoverable and blocks false deletion completion;
- no service operation writes a dataset, label, training, evaluation, or
  promotion record;
- every registered service table retains RLS and no direct client write grant;
- every capacity limit is enforced under contention, emits only its typed
  backpressure outcome, and leaves no partial reservation or media record;
- each automatic-stop invariant moves the rollout to halted while the monitor
  cannot open or broaden a rollout;
- emergency disable is immediate and idempotent under concurrent traffic;
- migration apply/reapply and populated-database rehearsal are clean;
- disabled backend or frontend configuration remains fail closed.

## 13. Known limitation

General availability may create more coach-review work than the initial coach
group can complete. Coach review is asynchronous and must never block the
record -> process -> Ideal Text -> next-Take loop. The product must preserve an
honest pending or no-exercise state when review or exercise capacity is absent.

## Review request

> **ML/DATA DESIGN RE-REVIEW REQUEST — MLC-3 General-User Service Rollout D4**
>
> Review the checksum-pinned design that replaces founder-only rollout with a
> database-authoritative generally available service. Verify exact canonical
> principal enrollment, the central rollout-aware access resolver, explicit
> operation-mode lineage, exact cohort mechanics and the separately recorded
> founder skip-cohort risk decision, non-retroactive acquisition authorization,
> separate speaker identity/missingness, independent pooled authorization,
> complete D2/D5 signal separation, R2/deletion safety, versioned capacity and
> automatic backpressure/halt, exact dual-purpose same-receipt authority,
> separate speaker-count/identity/target-span provenance, explicit pseudonymous
> first-speaker creation, immutable same-speaker source/practice equality,
> idempotent emergency disable, and structural exclusion from datasets and
> learning.
>
> This is design review only. No implementation, deployment, activation, real
> collection, dataset creation, training, evaluation, or promotion is
> authorized.
