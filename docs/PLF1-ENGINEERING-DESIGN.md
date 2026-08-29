# ED-PLF-1.3 — Staged authorization and continuously learning service design

**Product contract:** `PLF staged rollout` (`core_service` → `learning_live`)
**Status:** ENGINEERING DESIGN READY FOR REVIEW · NO IMPLEMENTATION STARTED  
**Prepared:** 2026-08-29  
**Owner:** Artur Willoński

Decision-filter stamp:

`FILTER: JUSTIFIED-SCAFFOLDING — cat F1-SUPPORT — Phase 1 preserves recording→feedback without pooled learning; Phase 2 remains fenced until the bounded learning loop and all external approvals are real.`

## 1. Scope and non-authorization boundary

This document is a standalone implementation design for the proposed staged
rollout. [`PRODUCT-LEGAL-FLOW-PLF-1.1.md`](./PRODUCT-LEGAL-FLOW-PLF-1.1.md)
is retained as historical design evidence but governs neither phase: its
optional pooled-learning control conflicts with this staged contract and it
does not approve the individual-learning-profile purpose. A new exact
Product/legal artifact must supersede PLF-1.1 for Phase 1 and define Phase 2
before either phase can become active.
It defines the dependency cutover, schema, APIs, user/guest flow, provider
boundary, termination/deletion workflow, rollout, rollback, monitoring, and
tests.

ED-PLF-1.3 supersedes ED-PLF-1.2. It preserves the staged contract and adds
historical-purpose compatibility, general policy-cutover carryovers, an exact
`power_score` classification gate, and the universal operational-purpose
invariant. It retains the conditional
`learning_live` phase, one-action re-acceptance for existing users, one-action
onboarding for new users, and explicit coverage of eligible historical and
future recordings. This is a design revision, not a policy activation.

Preparing this design does **not** authorize:

- changing the deployed Terms or Privacy Policy;
- inserting or activating a Product/legal policy;
- collecting a new user acceptance;
- changing a recording or provider route;
- migrating or deleting data;
- enabling MLC-2 or MLC-3 production writers;
- creating a dataset release;
- training, evaluating, or promoting a model; or
- merging or deploying source.

An exact Product/legal artifact remains a hard prerequisite for activation.
The schema is deliberately lawful-basis-neutral: Engineering must store the
basis approved for each purpose and must not decide it in code.

## 2. Outcomes

The design produces one authoritative phase-aware processing boundary for
accounts and guests:

```text
                         unknown/unsafe
                              |
                              v
                           killed

approved Phase 1 policy                 approved Phase 2 policy
         |                                       |
         v                                       v
    core_service  -- reviewed cutover -->   learning_live
         |                                       |
one Agree and continue                  one current Agree and continue
core + individual profile               bounded pooled learning required
pooled eligibility always false         historical + future scope permitted
dataset/training gates off               dataset/training atomically live
                                          evaluation/promotion remain gated
```

In either service phase, an accepted recording follows one product path:

```text
durable owner principal
  -> exact current phase/policy receipt
  -> recording object SHA-256 + recording attempt + authorization snapshot
  -> durable processing job
  -> typed provider permit
  -> recording → transcription → ranking → feedback
```

Refusal, termination, and deletion are separate states:

```text
current-policy refusal/missing acceptance
  -> no new recording or coaching
  -> existing content + legal/data-rights surfaces remain available
  -> no purge request

service termination/account deletion
  -> new work blocked immediately
  -> pending jobs cancelled
  -> complete target inventory frozen
  -> database/R2/provider/dataset lineage traversed
  -> deletable objects erased
  -> shared lineage retained only where independently required
  -> affected releases/models invalidated or quarantined
  -> completion or explicit failure recorded
```

The user never waits for model training. Committing an outbox/provenance event
does not create a dataset release or start a training job. Opening, signing in,
or merely using a legal/data-rights surface never creates acceptance.

## 3. Current-state dependency audit

### 3.1 Competing acceptance sources

| Producer/reader | Current responsibility | Classification | ED-PLF-1.3 treatment |
| --- | --- | --- | --- |
| Frontend `WelcomeConsent` and `useWillabFlow` | Local first-run button and `localStorage` flag | Product gate with no authoritative server receipt | Replace with a server-backed “Agree and continue” action; local state remains presentation-only |
| `GET/PUT /v2/user/consent` + `user_consents` | Authenticated Terms ledger plus mic/share/email preferences | Mixed-purpose legacy product state | Preserve historical rows; stop using it for recording authority; keep unrelated preferences |
| `GET/PUT /v2/user/sharing-consent` + `user_settings` flags | Chat mic/share/email/Terms flags | Mixed-purpose legacy product state | Remove Terms as an authority; preserve mic/email/peer-sharing preferences |
| `GET/POST/DELETE /v2/user/mlc2-consent` | Founder-only bundled acceptance and speaker binding | Canonical but founder-only and legally over-specific | Preserve as historical evidence only; never infer Phase 1 or Phase 2 authority from it |
| `ml_product_legal_approvals` | Immutable approved copy/evidence | Reusable canonical foundation | Rename/generalize; keep immutable approval records |
| `ml_consent_*` tables/RPCs | Two consent purposes fixed to Article 6(1)(a) | Reusable structure with incorrect universal semantics | Rename/generalize in place; do not maintain a parallel consent ledger |

There must be exactly one current service-phase authority after cutover.
`core_service` never grants pooled eligibility. `learning_live` requires the
exact current Phase 2 receipt and the approved bounded pooled purpose.
Historical ledgers remain audit evidence, but no legacy row is relabelled as a
Phase 1 or Phase 2 acceptance.

### 3.2 Identity and acquisition

| Dependency | Current behavior | ED-PLF-1.3 treatment |
| --- | --- | --- |
| `owner_principals` | Durable account or signed guest owner | Reuse unchanged as the identity root |
| `X-Willab-Guest-Owner` | Signed guest capability | Reuse for guest authorization status and acceptance |
| `/v2/projects` | Creates an owner principal if needed | Reuse; project/deck setup may occur before recording authority |
| `/v2/projects/claim` | Claims or aliases a guest graph into an account | Preserve immutable acquisition origin; never copy an acceptance event |
| `ml_speakers` / `ml_speaker_principals` | Canonical speaker identity for learning splits | Reuse; do not add a parallel `canonical_subject_id` graph |

Canonical speaker binding is derived solely from authenticated account/signed-
guest ownership and immutable claim provenance. It never uses acoustic 1:1
verification, 1:N identification, cross-recording voice matching, embeddings
for identity, or a claimed similarity between voices. An unresolved provenance
graph remains unresolved and learning-ineligible; audio cannot resolve it.

When a guest principal is claimed into an account:

- past acquisition records remain tied to the original guest principal;
- existing recordings keep that acquisition provenance;
- the claim event links the graph for access and deletion traversal;
- a pre-existing account principal needs its own exact current-phase service
  acceptance for future recordings unless it already accepted the same active
  policy; and
- no compliance record is copied or rewritten.

### 3.3 Recording and processing producers

| Path | Current gate | ED-PLF-1.3 requirement |
| --- | --- | --- |
| `POST /v2/lab/recordings` | Optional auth plus account/guest ownership | Require current PLF authority before reading/uploading accepted voice data |
| `POST /v2/lab/recordings/:id/retry-processing` | Ownership only | Recheck current authority before retry/provider work |
| `POST /v2/lab/recordings/:id/retry-ideal-text` | Ownership and Take state | Recheck current authority before any provider-backed retry |
| `POST /v2/projects/:project/takes/:take/send-to-coach` | Authenticated ownership | Require coach-review purpose and current authority |
| Sync/daemon analysis | Carries request-independent audio bytes | Carry an immutable authorization snapshot and provider-purpose context |
| Durable `processing_jobs` worker | Reloads audio and processes it | Recheck current authority before object download and before each provider operation |
| Coach queue | Pseudonymous and blind where required | Exclude/cancel work whose current authority ended |
| Dataset-release builders | Separate legacy/canonical tables | Revalidate current authority independently; remain disabled under this design |

An authorization failure is a hard domain stop. It must not be caught by the
current broad transcription exception and converted into an empty transcript.

### 3.4 Provider callers

The repository contains direct or indirect OpenAI calls in recording
transcription, stickiness/scoring, Ideal Text and coaching generation, user
chat, coach draft generation, snippet transcription, reference-video
processing, imports, Life, journal and administrative tools.

The active PLF phase applies to operations that send user-acquired recording, transcript,
derived voice features, or associated coaching content. These operations must
go through a provider adapter requiring a database-issued processing permit.
Unrelated system/admin generation remains outside this boundary but must declare a
different data origin; absence of an origin is rejected.

The checked-in implementation audit must classify every provider caller as:

- `plf_user_data` — permit required;
- `coach_authored_data` — separate coach contract/policy;
- `public_or_operator_content` — no user acquisition authority;
- `mixed` — refactor before cutover; or
- `unknown` — fail closed and block cutover.

### 3.5 Storage and deletion

Current Lab audio is stored before the product rows are fully committed.
`recording_attempts` persists bucket and key but no SHA-256 of the underlying
audio bytes. MLC-2 object rows can store hashes, but general product recording
objects are not comprehensively registered there.

The existing `ml_purge_requests`/`ml_purge_events` schema creates an audit
request but no complete operational worker was found that cancels jobs,
deletes provider/R2 objects, traverses dataset lineage, or proves completion.
Individual session and Life-data deletion paths do not constitute account-wide
PLF deletion.

## 4. Locked invariants

1. Exactly one runtime phase is authoritative: `core_service`,
   `learning_live`, or `killed`; unknown values resolve to `killed`.
2. Opening the app, signing in, inactivity, a preselected state, and
   browser-local flags are never acceptance.
3. One explicit “Agree and continue” action creates one immutable receipt for
   the exact current phase and policy.
4. Account and guest principals use the same server contract.
5. No full date of birth is collected; only an over-18 result is retained.
6. Age, sex, and gender are never inferred from voice; sex/gender is not
   collected by this flow.
7. Country of residence is collected at setup, not before each recording.
8. Gateway location is rechecked only on a versioned risk trigger.
9. No per-recording sole-speaker checkbox exists; the Terms contain the
   voice-only rule.
10. `core_service` permits recording, transcription, coaching, and the
    individual learning profile but makes pooled eligibility false.
11. `learning_live` requires the exact current Phase 2 receipt before new
    recording/coaching and may cover eligible existing and future recordings.
12. Historical coverage is explicit, inventory-backed, and never inferred
    from storage, a prior service receipt, or a legacy consent row.
13. Each accepted recording references the exact immutable authorization
    snapshot active at acquisition.
14. Current authority is checked again at provider, coach, dataset, training,
    evaluation, and promotion boundaries.
15. Product/legal events, product actions, ML judgments and exposures remain
    separate records.
16. Audio SHA-256 verifies exact bytes; it is not globally unique identity and
    is never treated as a speaker identifier or voiceprint.
17. Canonical speaker identity is bound only through account/guest provenance;
    acoustic verification, identification and voice matching are prohibited.
18. A provider call carrying PLF user data cannot occur without a typed permit.
19. Refusal or missing current acceptance blocks new service but does not
    delete existing content or create a purge request.
20. Termination blocks new processing immediately and starts cancellation and
    purge; deletion is a separately attributable request where applicable.
21. Release eligibility is recomputed from source evidence; it is never
    inherited from a policy-purpose field or acquisition snapshot.
22. Dataset creation, training, evaluation, and promotion use independent
    default-off controls. Dataset/training require separate prior approval and
    are enabled atomically with `learning_live`; evaluation/promotion remain
    independently gated afterward.
23. Feedback never waits for a training run.
24. Phase 1 retention follows only the approved core-service schedule; it is
    never extended merely because a future learning phase is contemplated.
25. No founder, coach, administrator, migration, worker, or script bypass
    exists.
26. A purpose may be registered before implementation, but an active policy
    cannot mark it required or authorize its processing until the real
    capability is operational, reviewed, monitored, and connected to
    retention, deletion and data-rights controls.
27. Phase 1 recordings require a positive, applicable, immutable GDPR Article
    6(4) further-processing assessment before Phase 2 historical coverage can
    finalize or release eligibility can become true. Phase 2 Terms alone never
    imply compatibility.
28. Every material policy-version activation—not only a phase change—must
    atomically freeze and reconcile exact non-terminal accepted product jobs,
    create narrow completion carryovers, and activate the new policy.
29. L1, L2 and L3 remain unchanged. `power_score` remains the internal blended
    L2 ranker and is never surfaced as a score, number, band or verdict under
    AC-9.
30. No phase or material policy may activate until an immutable Product/legal
    and technical classification covers the exact deployed `power_score`
    pipeline and configuration. A founder label does not establish its legal
    conclusion.

## 5. Target architecture

```text
approved evidence -> phase policy -> purpose rows
                          |
owner principal -> explicit acceptance event -> current phase authority
      |                         |                         |
      |               age/residence/notices              |
      |                         |                         |
      +------ recording acceptance RPC -----------------+
                        |         |         |
                   snapshot  audio+SHA  processing job
                        |         |         |
                        +---- provider permit ----> feedback

Phase 2 existing-user acceptance
  -> applicable Article 6(4) assessment/resolution
  -> historical coverage cutoff
  -> complete historical inventory
       ├─ verified eligible candidate
       └─ typed exclusion
  -> immutable inventory hash

canonical events -> surface eligibility -> dataset release
  -> training/calibration -> evaluation -> promotion -> assigned serving model

core_service + armed(dataset, training) + approvals
  -> one atomic transition
       ├─ learning_live
       ├─ dataset enabled
       ├─ training enabled
       └─ frozen prior-policy in-flight completion inventory

every material policy activation
  -> validate operational purposes + exact power_score classification
  -> freeze cutoff + reconcile old-policy product jobs
  -> create narrow carryovers + activate new policy atomically

refusal/missing receipt -> new service blocked; content/legal access retained
termination/deletion -> frozen purge targets -> DB/R2/provider/queues/ML lineage
```

## 6. Canonical schema design

Physical names may be adjusted during migration review, but responsibilities
must remain separate.

### 6.1 Product/legal approval and purposes

#### `product_legal_approvals`

In-place generalization of `ml_product_legal_approvals`.

Required columns:

- `id uuid primary key`
- `approval_reference text unique not null`
- `contract_family text not null` — `PLF`
- `rollout_phase text not null` — `core_service` or `learning_live`
- `approved_copy_sha256 char(64) not null`
- `onboarding_copy text not null`
- `terms_version text not null`
- `privacy_policy_version text not null`
- `ai_notice_version text not null`
- `approving_authority text not null`
- `approved_at timestamptz not null`
- `jurisdictions text[] not null`
- `evidence_object_key text not null`
- `evidence_sha256 char(64) not null`
- `recorded_at timestamptz not null default now()`

The table is append-only. Hashes verify copy and evidence but are not legal
signatures.

#### `processing_purposes`

Authoritative purpose registry:

- `core_recording_voice_processing`
- `coach_review`
- `individual_learning_profile`
- `personalized_exercise_recommendation`
- `pooled_model_improvement`

`exercise_adequacy_classification` is an MLC-3 learning-surface identifier,
not a legal/product processing purpose. It may appear in ML provenance only;
it must never appear in authorization copy or be inferred from the
personalized-recommendation purpose.

Optional emotion-state inference is **not** silently added to these purposes.
If Product/legal later permits it, it requires its own purpose, approved copy
and user control.

#### `processing_purpose_capability_versions`

The purpose registry is vocabulary, not proof that a feature exists. Each
purpose version therefore has a separately reviewed operational record:

- purpose and capability version
- state: `registry_only`, `operational`, `suspended`, `retired`
- implementation/deployment hash and owner
- processing entry points and provider/storage dependencies
- monitoring/alert contract reference
- retention schedule, deletion resolver and data-rights handler references
- Product, Product/legal, Engineering, security and processor review evidence
- activated/retired timestamps and immutable evidence hash

An active policy-purpose row must reference an exact `operational` capability
version. Policy activation verifies every reference transactionally. A
registry-only, suspended, retired, missing or mismatched capability can appear
in documentation and future design but cannot be `required_for_service`,
authorize collection/provider work, extend retention, or support historical
reuse.

`personalized_exercise_recommendation` remains `registry_only` until its real
feature and controls exist. `exercise_adequacy_classification` remains an
MLC-3 provenance identifier, not a processing purpose. Neither can justify
current collection, required acceptance or future reuse before activation.
This rule applies identically to every future purpose.

#### `processing_authorization_policies`

In-place generalization of `ml_consent_policies`:

- `version text primary key`
- `product_legal_approval_id uuid not null`
- `contract_family text not null check (contract_family = 'PLF')`
- `rollout_phase text not null check (rollout_phase in
  ('core_service', 'learning_live'))`
- `acceptance_kind text not null` — value comes from the approved artifact,
  not source code
- `required_for_recording boolean not null`
- `active_from`, `retired_at`
- `jurisdiction_policy_version text not null`
- `age_policy_version text not null`
- `location_risk_policy_version text not null`
- exact approved `power_score_classification_id`

At most one policy may be active for the runtime phase. Activating a policy
requires immutable approval evidence whose copy hash verifies. A
`learning_live` policy is invalid unless `pooled_model_improvement` is present
as required for service under the exact approved artifact. A `core_service`
policy cannot confer pooled eligibility.

#### `processing_runtime_transitions`

Append-only transitions provide the authoritative state machine:

- `id uuid primary key`
- `from_phase`, `to_phase`: `core_service`, `learning_live`, `killed`
- exact policy and Product/legal approval IDs when entering a service phase
- Engineering, Product/legal, ML/data and founder approval references
- transition reason, actor, deployment version and timestamp
- idempotency key and immutable transition hash

`current_processing_runtime_state_v1` resolves the latest valid transition.
Missing, malformed, contradictory, or unknown state resolves to `killed`.
No environment variable or frontend value can independently activate a phase.
Recording acceptance and every material policy-activation RPC serialize on one
dedicated runtime-guard row: acceptance takes the reviewed shared lock before
resolving the policy; activation takes the exclusive lock before freezing
carryovers and changing policy/state. An accepted job therefore cannot appear
between a carryover inventory and any material cutover.

#### `processing_policy_activations`

Every material policy version change has one append-only activation record:

- `id uuid primary key`
- exact prior/new policy versions and runtime phase(s)
- server cutoff timestamp and material-change reason
- applicable `power_score` classification artifact
- exact operational-purpose capability versions
- Product/legal, Engineering, security, ML/data and founder approval references
- activation status, deployment version, idempotency key and immutable hash

`activate_processing_policy_v1` obtains the exclusive runtime lock, validates
the new policy and every classification/capability dependency, freezes and
reconciles the carryover inventory, then appends the activation as one database
transaction. For the Phase 1→2 change,
`transition_to_learning_live_v1` wraps this contract and atomically appends the
runtime transition plus dataset/training enable events. A same-phase material
Terms, purpose, provider, retention, model-use or signal-classification change
uses the same activation contract.

#### `processing_operational_capability_events`

Operational learning gates are a separate append-only state machine:

- `capability`: `dataset_release`, `training`, `evaluation`, `promotion`
- `state`: `disabled`, `armed`, `enabled`, `killed`
- exact surface scope and environment
- activation and retirement timestamps
- Product/legal, ML/data, Engineering, security and founder approval references
- deployment/config version, actor, reason and idempotency key
- immutable event hash

The latest valid event resolves each capability; missing, malformed or unknown
state is `disabled`. A policy row cannot enable a capability. `armed` means the
implementation, approvals and production configuration are ready but the
operation is still forbidden. Phase 1 rejects all four even if a malformed or
incorrect event says enabled.

Dataset release and training must be separately approved and `armed` while the
runtime remains `core_service`. The reviewed
`transition_to_learning_live_v1` RPC verifies the exact Phase 2 policy, all
transition approvals, an operational bounded learning pipeline, and both
armed capabilities; in one database transaction it appends the
`learning_live` transition and the two `enabled` capability events. Any failed
check rolls back the entire transition. Evaluation and promotion remain
separately disabled/armed/enabled later and are not implied by Phase 2.

#### `processing_policy_cutover_carryovers`

Every material policy-activation transaction freezes the exact non-terminal
product-feedback jobs accepted under its prior policy before the cutoff:

- policy activation, optional phase transition, processing-job, recording,
  attempt and authorization-snapshot IDs
- acquisition principal and exact prior phase/policy
- accepted-before cutoff and frozen job state
- allowlisted remaining product stages
- state: `pending`, `running`, `completed`, `failed`, `cancelled`
- terminal reason/time and immutable carryover hash

`processing_policy_cutover_carryover_events` stores append-only claims,
retries, stage completion, cancellation and terminal outcomes; validated RPCs
derive the current state. Retry events reference the same durable product job
and never create a second scope.

A carryover is not a new acceptance. It permits only the already-promised
recording→transcription→ranking→Ideal Text/feedback pipeline for that exact
job. It cannot authorize another recording, a manual retry created after the
cutoff, new coach delivery, dataset inclusion, training, evaluation or
promotion. Termination, deletion, retention expiry or a safety quarantine
still cancels it. Provider permits accept a current active-policy receipt
**or** this narrow carryover for the exact prior policy. Policy activation cannot commit
unless its carryover inventory reconciles with every eligible non-terminal job,
so no accepted recording is silently stranded. A job rejected before the old
policy cutoff or created afterward is never carried over.

#### `processing_authorization_policy_purposes`

One row per policy and purpose:

- `policy_version`
- `purpose_id`
- `required_for_service boolean`
- `legal_basis_code text not null`
- `article_9_basis_code text null`
- `provider_processing_allowed boolean`
- `authorization_control`: `required_service`, `separate_consent`
- exact `purpose_capability_version` foreign key

The row records the approved legal scope and control type only. It contains no
`dataset_release_allowed`, `training_allowed`, `evaluation_allowed`, or
`promotion_allowed` booleans. Eligibility and operational activation are
independent decisions. This design revision activates none of them; later
runtime activation can occur only through the capability contract and staged
approval sequence, never through policy wording.

### 6.2 Immutable service acceptance, refusal, and termination

#### `processing_authorization_events`

In-place generalization of `ml_consent_events`:

- exact `acquisition_principal_id`
- exact policy and approval IDs
- `event_kind`: `service_accepted`, `service_refused`, `service_terminated`,
  `purpose_granted`, `purpose_withdrawn`
- exact `rollout_phase`
- `coverage_scope`: `future_only` or `existing_and_future`
- `historical_coverage_cutoff_at null` in Phase 1 and fixed to the server
  acceptance time for every Phase 2 receipt (a new user's inventory is simply
  empty)
- `purpose_id null` for service events and required only for separately
  authorized purpose events
- accepted copy, Terms, Privacy and AI-notice versions
- `locale`
- `residence_country_code char(2)`
- `adult_confirmed boolean`
- `age_assurance_method`: initially `self_attestation`; later provider result
- source route, client version, occurred/received times
- immutable affirmative action envelope
- idempotency key
- `supersedes_event_id` for renewed acceptance, termination, or a separately
  authorized purpose withdrawal

Checks enforce that service acceptance has `adult_confirmed=true`, a supported
residence country under the referenced policy, and every required service
purpose. Phase 1 acceptance must use `future_only` and cannot authorize pooled
learning. Phase 2 acceptance must use `existing_and_future`, match the exact
active Phase 2 policy, and prominently presented copy must cover eligible
stored and future recordings. Service termination references the exact current
acceptance and never deletes it. `service_refused` records only an explicit
“Not now” action; it grants nothing and creates no purge request.

Passive entry, authentication, page rendering, and inactivity never call the
acceptance RPC. If Product/legal assigns consent to a purpose, only the
separate `purpose_granted`/`purpose_withdrawn` contract may represent it; the
mandatory service button cannot synthesize that consent.

#### `processing_authorization_event_purposes`

One immutable row per required service purpose or separately authorized
purpose containing the exact approved legal-basis codes. In Phase 1, the
service action creates only core-service purpose rows and pooled eligibility
is false. In Phase 2, the single service action creates every purpose row that
the exact counsel-approved contractual policy marks required, including the
bounded pooled-model purpose. Engineering never assigns those basis codes.

Historical MLC-2 founder consent rows are preserved as historical
`acceptance_kind=explicit_consent` records. They are not automatically expanded
or interpreted as Phase 1 or Phase 2 service authority.

### 6.3 Residence and risk-triggered location assessment

#### `principal_residence_events`

- principal, country code, policy version
- `declared` or `changed`
- occurred time, source, locale and idempotency
- immutable `supersedes_id`

#### `principal_location_assessments`

- principal and residence-event ID
- trusted gateway country code
- `trigger`: `initial_setup`, `residence_change`, `account_recovery`,
  `authentication_risk`, `gateway_country_change`, `policy_change`,
  `manual_security_review`
- trigger evidence hash, source/provider version and policy version
- decision: `allowed`, `blocked`, `review_required`, `unavailable`
- observed time, expiry/recheck time and idempotency key

No raw IP address is stored here. Security logs may retain IP data only under
their separately approved retention schedule.

Trusted gateway country must originate from a server-controlled edge or a
signed BFF assertion. Browser-supplied country headers are never trusted.

### 6.4 First-exposure AI notice

#### `product_ai_notice_versions`

Approved copy, scope/classification, effective dates and copy SHA-256.

#### `product_ai_notice_presentations`

Prepared notice for an exact principal and version. Preparation is not proof
that the user saw it.

#### `product_ai_notice_receipts`

Authenticated post-render acknowledgement referencing the presentation,
principal, payload hash, client version and render timestamp. It is a product
transparency receipt, never a consent, exposure label or ML judgment.

Every conversational AI surface also renders a persistent, non-dismissible
AI identification label. Emotion-recognition processing has no fallback to
this general notice: it remains disabled until its own approved disclosure,
authority and technical classification are configured.

### 6.5 `power_score` technical and Product/legal classification

#### `processing_signal_classifications`

The active ranking signal requires one named immutable classification artifact
whose `signal_id` is `power_score`:

- artifact/version ID, status: `draft`, `approved`, `conflict`, `rejected`,
  `expired`
- exact repository commit, deployment version and configuration hash
- hashes/versions for `power_phrase_ranking`, every upstream producer and its
  feature schema, weights, thresholds, flags and baselines
- complete inputs and acoustic measurements
- functional purpose and prohibited purposes
- output schema/range and every downstream consumer/use
- `performs_biometric_identification boolean` with technical proof; approval
  under the founder contract requires `false`
- `performs_sex_or_gender_inference boolean` with technical proof; approval
  under the founder contract requires `false`
- separate findings for emotion, intention, mental-state, stress,
  threat/challenge and health inference under the applicable definitions
- GDPR and AI Act conclusions, jurisdiction scope and required controls
- founder-intent statement kept separate from the legal conclusion
- technical reviewer, Product/legal approving authority and timestamps
- evidence object key, SHA-256 and immutable artifact hash

The currently implemented blend must be documented exactly. At the time of
this design audit, `power_score` combines the one-sided professional-coach
veto, transcript/content activation, slide stickiness and—when enabled—the
`voice-confidence-v2` machine term. The latter reads `f0_sd`, `dynamic_db`,
`f0_mean`, `wpm`, pause ratio/duration, terminal f0 contour and intensity
envelope relative to the speaker's baseline. Its code also contains declared-
sex routing and acoustic fallback sex inference from baseline f0.

This creates an explicit unresolved conflict with the founder requirement that
the classified pipeline confirm no sex/gender inference. It may also affect the
legal analysis of whether the “confident/doubtful” spectrum infers emotion,
intention, mental state, stress or challenge. Engineering does not decide
those questions by renaming the signal. The retired challenge/threat inputs
must remain absent from the live blend and the artifact must prove that no
legacy caller reintroduces them.

No policy or phase activates unless the artifact is `approved`, applies to the
exact deployed code/configuration and contains no unresolved required finding.
Any code, feature, weight, flag, baseline or downstream-use change expires the
match and fails closed pending a new artifact. This gate does not remove or
alter `power_score`, L1, L2 or L3.

AC-9 remains absolute: the numeric score, inputs, bands, cue values, model
judgments and classification artifact are never serialized to a user-facing
payload. Users receive only the resulting product selection and separately
approved qualitative feedback.

### 6.6 Recording authorization snapshots

#### `processing_authorization_snapshots`

In-place generalization of `ml_consent_snapshots`:

- principal, accepted event and policy
- exact runtime phase at acquisition
- recording attempt, project and eventual Take
- age receipt/state
- residence event and latest required location assessment
- exact required-service purpose-state object and operational-capability
  versions
- exact active `power_score` classification artifact/hash
- `pooled_learning_eligible_at_acquisition` (always false in `core_service`;
  true in `learning_live` only when the exact Phase 2 receipt applies)
- `captured_at`
- retention state
- canonical snapshot SHA-256

The recording-acceptance RPC creates this snapshot in the same PostgreSQL
transaction as the recording attempt and processing job/outbox record. A
historical snapshot proves acquisition conditions but never overrides a later
refusal, policy retirement, service termination, retention expiry or deletion
when current authority is rechecked.

### 6.7 Historical further-processing compatibility

#### `processing_further_use_assessments`

One immutable GDPR Article 6(4) assessment covers an exact historical-reuse
scope:

- `id uuid primary key`
- original Phase 1 policy and purpose versions
- proposed Phase 2 policy and `pooled_model_improvement` purpose version
- applicable jurisdiction set and assessment-policy version
- typed compatibility factors and written rationale
- outcome: `compatible`, `incompatible`,
  `separate_authorization_required`
- approving authority, approval reference and approved timestamp
- evidence object key, SHA-256 and immutable assessment hash
- effective/retired timestamps and optional `supersedes_id`

The factors preserve the exact Product/legal analysis; Engineering neither
scores them nor derives the outcome. The assessment is applicable only when
the original/proposed purposes, policies, jurisdictions, implementation scope
and evidence hashes match the recording and planned release.

`compatible` is a positive assessment. Missing, stale, mismatched,
`incompatible` or unresolved assessments are negative for historical reuse.
`separate_authorization_required` is not permission by itself and never adds a
checkbox automatically.

#### `processing_further_use_authority_resolutions`

If Product/legal separately approves a mechanism for an assessment whose
outcome is `separate_authorization_required`, an immutable resolution links:

- the assessment and exact historical recording/principal scope
- the independently approved mechanism and legal artifact
- its exact authorization event/evidence, where applicable
- approving authority, timestamp and evidence hash
- status: `satisfied`, `revoked`, `expired`

Only `compatible`, or `separate_authorization_required` plus a current
`satisfied` resolution, is a positive applicable result. Engineering cannot
invent the mechanism, reinterpret Phase 2 Terms, or present another control
without separate approval.

### 6.8 Historical recording coverage

Phase 2 acceptance may cover eligible recordings already stored, but an
acceptance event alone does not make any historical object eligible. Coverage
requires a complete, immutable inventory.

#### `processing_historical_coverage_sets`

- `id uuid primary key`
- exact Phase 2 acceptance event, policy and Product/legal approval
- exact applicable further-processing assessment scope/hash
- acquisition-principal graph root and immutable graph version
- `coverage_cutoff_at` captured by the acceptance transaction
- state: `inventorying`, `finalized`, `failed`, `superseded`
- expected, inventoried, candidate and excluded counts
- inventory code/schema version
- finalized inventory hash and timestamp
- lease/retry metadata and idempotency key

#### `processing_historical_coverage_items`

One row for every recording discovered at or before the cutoff:

- coverage set, recording, attempt, Take and exact audio-object IDs
- original acquisition principal and original authorization snapshot
- applicable further-processing assessment and, where required, authority-
  resolution ID
- ownership-resolution evidence and principal-graph version
- stored hash plus independently recomputed object SHA-256
- original collection, current retention, expiry, deletion, quarantine and
  legal-hold states
- disposition: `candidate` or `excluded`
- one typed exclusion reason where excluded
- immutable item hash and inventory timestamp

Required exclusion reasons include `unresolved_owner`, `missing_audio_object`,
`missing_original_snapshot`, `hash_unverified`, `hash_mismatch`,
`retention_expired`, `deletion_pending`, `quarantined`,
`legal_hold_blocks_training`, `unknown_or_third_party_provenance`,
`orphaned_recording`, `not_lawfully_retained`,
`further_processing_assessment_missing`,
`further_processing_assessment_inapplicable`,
`further_processing_incompatible`, and
`separate_authorization_required`.

The Phase 2 acceptance transaction records the cutoff and commits quickly.
An asynchronous worker then enumerates the complete principal graph. Every
discovered recording becomes either a candidate or a typed exclusion. The set
is finalized atomically only when counts reconcile and its deterministic hash
verifies, and every candidate has a positive applicable further-processing
result. Until then every historical item is learning-ineligible. Recordings
created after the cutoff use their Phase 2 acquisition snapshots, preventing
gaps and double inclusion.

### 6.9 Release-time learning eligibility

#### `ml_release_eligibility_decisions`

One append-only decision per prospective surface-specific release item and
eligibility evaluation attempt:

- exact dataset release and `learning_surface`;
- evidence span, recording object, Take, clip and candidate coordinates;
- exact `acquisition_principal_id` and canonical `speaker_id`;
- original service acquisition snapshot;
- current Phase 2 service acceptance and active policy;
- exact operational `pooled_model_improvement` capability version;
- historical coverage set/item when the recording predates the acceptance
  cutoff, or a Phase 2 acquisition snapshot for future recordings;
- positive applicable Article 6(4) assessment/result for every historical
  recording;
- retention, deletion and purge state observed at evaluation;
- stored audio hash and independently recomputed audio-object SHA-256;
- applicable MLC-2 or MLC-3 contract/epoch/schema versions;
- `eligible boolean` and typed inclusion/exclusion reason;
- evaluated time, evaluator code version and immutable decision hash.

The release builder recomputes this decision immediately before including an
item. It does not read eligibility from a policy-purpose boolean, an
acquisition snapshot, an inventory disposition or a prior decision. Phase 1
recordings are always excluded unless a finalized Phase 2 historical-coverage
item and positive applicable further-processing result prove every required
condition. Phase 2 Terms alone never supply that result. A dataset retry
recomputes eligibility.
Training creation/retry, evaluation and promotion independently revalidate
the current Phase 2 acceptance, release validity and operational capability.
Refusal, policy retirement, termination, expiry, deletion or quarantine makes
future use ineligible immediately. An immutable published release is
invalidated and replaced through reviewed lineage rather than silently edited.

### 6.10 Exact audio-object lineage

#### `recording_audio_objects`

- `id uuid primary key`
- exact principal, project, recording attempt and recording IDs
- object store, bucket and immutable key
- content type and byte size
- `sha256 char(64)` of the uploaded bytes
- hash method/version
- upload verification status/time
- created time
- unique object locator and unique recording-attempt relationship

SHA-256 is not globally unique. Two people may submit identical bytes. Record
identity comes from provenance coordinates; the hash verifies content.

The web process computes SHA-256 before upload. The worker downloads the object
and verifies the bytes before provider use. Dataset construction, if separately
authorized later, must independently download/recompute the hash rather than
trusting the stored value.

R2 and PostgreSQL cannot commit in one distributed transaction. Therefore:

1. upload bytes under a new immutable object key;
2. verify upload success and retain the computed hash;
3. call one PostgreSQL acceptance RPC that commits the object registry,
   recording attempt, authorization snapshot and processing job/outbox;
4. if the database transaction fails, append the key to an orphan-cleanup
   queue; and
5. the sweeper deletes only unreferenced staged objects after a safety window.

The route never dispatches processing until step 3 succeeds.

### 6.11 Provider operations and permits

#### `processing_provider_operations`

Operational row containing immutable identity/lineage coordinates and a
mutable current status changed only through validated RPCs:

- principal, authorization snapshot, recording object, attempt and Take
- purpose ID
- provider, adapter version and operation kind
- external request/object reference where available
- current status and timestamps
- idempotency key

#### `processing_provider_operation_events`

Append-only lifecycle: `authorized`, `queued`, `started`, `completed`,
`failed`, `cancel_requested`, `cancelled`, `retention_confirmed`.

#### Provider permit contract

`issue_processing_provider_permit_v1` revalidates:

- exact ownership and acquisition principal;
- active current-policy service acceptance for product feedback, or an exact
  non-terminal policy-cutover carryover for the original allowlisted product
  job;
- purpose-specific current authority;
- exact operational purpose capability and approved `power_score`
  classification/configuration match;
- `learning_live`, current Phase 2 acceptance, fresh release eligibility and
  the corresponding default-off capability for any dataset, training,
  evaluation or promotion provider operation;
- required current location assessment;
- object SHA verification;
- absence of an active termination/purge block; and
- the provider/operation allowed by the approved processor configuration.

It creates an operation plus an `authorized` event. In-scope provider adapters
require that operation ID and reject missing, stale or mismatched permits.
Raw OpenAI client access is forbidden from PLF user-data modules by a static
dependency test. Carryover permits are tagged `product_completion_only` and
are structurally rejected by coach, dataset, training, evaluation and promotion
callers.

### 6.12 Refusal, termination, deletion, and purge

An explicit refusal of the current Phase 2 policy—or simply not accepting it—
is not termination or deletion. It blocks new recording, coaching and learning
use, while preserving access to existing content, export, deletion and legal
surfaces under the prior retention policy. It creates no purge request.

Whole-service termination or account deletion uses the purge path below. If
an exact approved policy later uses a separate consent for any purpose, its
purpose-specific withdrawal is recorded independently and enforced according
to that artifact; Engineering must not infer such a control from this staged
contract.

Generalize `ml_purge_requests`/`ml_purge_events` in place so product and ML
deletion share one orchestrator.

#### `data_purge_triggers`

One append-only attributable trigger normalizes the originating action:

- `id uuid primary key`
- `trigger_kind`: `service_termination`, `account_deletion`,
  `third_party_audio_report`, `retention_expiry`, `lawful_deletion_order`
- exact principal and actor
- typed source table/event ID and source-event hash
- linked service-termination event when one exists
- occurred/received times and idempotency key

Account deletion is independently representable. Its transaction appends the
account-deletion domain event and purge trigger; if service is active, it also
appends a distinct linked service-termination event. Neither event impersonates
the other, and both retain their own timestamp and provenance.

#### `data_purge_requests`

- exact acquisition principal
- canonical speaker when resolved; nullable only before resolution
- `purge_trigger_id uuid not null` referencing the attributable trigger above
- reason: `contract_termination`, `account_deletion`, `third_party_audio`,
  `retention_expiry`, `lawful_deletion`
- requested time/actor
- current state: `requested`, `inventorying`, `cancelling`, `deleting`,
  `review_required`, `completed`, `failed`
- lease/retry fields and idempotency key

#### `data_purge_targets`

The frozen traversal inventory:

- purge request
- target kind and source system
- database entity/object/provider operation/release/model coordinate
- action: cancel, delete, invalidate, quarantine, retain-shared,
  retain-legal
- reason and governing retention rule
- target checksum where applicable
- state, attempts and completion evidence

#### `data_purge_events`

Append-only lifecycle and target outcomes. Ordinary code cannot update or
delete purge evidence.

The purge resolver registry is an explicit allowlist. An unknown table,
provider, bucket, release link or artifact type changes the request to
`review_required`; it never reports success.

### 6.13 Security, immutability and RLS

- Partial unique indexes enforce one active policy per phase and one finalized
  coverage set per acceptance/cutoff.
- Purpose capabilities are unique by `(purpose_id, capability_version)`;
  signal classifications by `(signal_id, artifact_version)` and exact code/
  configuration hash; policy carryovers by `(policy_activation_id,
  processing_job_id)`.
- Further-use assessment lookup is indexed by original/proposed policy,
  jurisdiction scope hash, outcome and effective/retired times; evidence and
  assessment hashes are unique immutable verifiers, not mutable decisions.
- Authorization status uses `(acquisition_principal_id, rollout_phase,
  occurred_at desc)`; historical inventory uses `(coverage_set_id,
  recording_id)` unique plus state/reason indexes; release checks use
  `(dataset_release_id, learning_surface, evidence_span_id, evaluated_at desc)`.
- Audio locators are unique within their store/bucket/key coordinates, while
  content hashes are deliberately non-unique.
- Foreign keys prohibit cross-principal recording/snapshot/coverage lineage;
  deferred constraints are allowed only inside the reviewed atomic RPC.
- Canonical approval, purpose-capability version, signal classification,
  further-use assessment/resolution, policy activation, authorization,
  snapshot, notice receipt, object coordinates and purge event rows are
  append-only. Carryover lifecycle changes append events through RPCs; their
  identity/scope is immutable.
- Browser roles receive no direct table write access.
- Service role receives read access where possible; mutations use reviewed
  `SECURITY DEFINER` RPCs with fixed `search_path` and explicit grants.
- User/guest routes resolve exact ownership before calling an RPC.
- Coach/admin roles cannot create acceptance, change residence/age, issue a
  provider permit for another purpose, or mark purge completion.
- Read APIs expose approved copy and state, never internal identity hashes,
  legal evidence object keys, raw IPs or purge target locators.
- Logs and monitoring contain IDs, policy versions, reason codes and counts,
  not audio, transcripts or blind packets.

## 7. Application services

### 7.1 `ProcessingAuthorizationService`

One reusable backend service owns:

- principal resolution for account and signed guest;
- authoritative runtime-phase and policy/status reads;
- exact current-phase acceptance, explicit refusal and termination;
- historical-coverage cutoff creation and inventory status;
- separately approved purpose grant/withdrawal only where the Product/legal
  artifact requires it;
- current-purpose and exact operational-capability checks;
- exact applicable `power_score` classification resolution;
- residence/location assessment resolution;
- recording snapshot creation;
- provider-permit issuance; and
- stable public error codes.

Routes and jobs may not recreate these rules.

Public decisions:

- `PLF_POLICY_NOT_CONFIGURED` — 503, recording disabled
- `PLF_PHASE_KILLED` — 503, all new recording/coaching disabled
- `PLF_ACCEPTANCE_REQUIRED` — 403, show setup gate
- `PLF_PHASE2_REACCEPTANCE_REQUIRED` — 409, show the prominent stored-and-
  future-recordings Phase 2 screen
- `PLF_POLICY_CHANGED` — 409, show renewed current-phase acceptance
- `PLF_ADULT_CONFIRMATION_REQUIRED` — 403
- `PLF_REGION_BLOCKED` — 451 or reviewed product status
- `PLF_LOCATION_REVIEW_REQUIRED` — 403, no provider work
- `PLF_TERMINATED` — 403, legal/self-service surfaces only
- `PLF_LEARNING_NOT_AUTHORIZED` — current phase/receipt or release evidence
  does not authorize this learning operation
- `PLF_PROVIDER_NOT_AUTHORIZED` — 503, fail closed
- `PLF_PURPOSE_NOT_OPERATIONAL` — 503, registry entry cannot authorize work
- `PLF_SIGNAL_CLASSIFICATION_REQUIRED` — 503, exact `power_score` pipeline is
  missing, mismatched, expired or unresolved
- `PLF_HISTORICAL_REUSE_NOT_APPROVED` — typed historical exclusion, never a
  fallback to Phase 2 Terms

### 7.2 `PolicyActivationService`

The only service allowed to activate a material policy version:

- resolves materiality and takes the exclusive runtime lock;
- validates Product/legal evidence, every required purpose capability and the
  exact `power_score` classification;
- freezes the server cutoff and reconciles all eligible non-terminal jobs;
- creates narrow policy-cutover carryovers; and
- activates the policy, plus any reviewed phase/capability events, in one
  transaction.

It cannot alter the ranking algorithm, legal conclusions or user receipts.

### 7.3 `DataPurgeOrchestrator`

One durable worker owns cancellation, inventory, deletion, invalidation and
completion. It uses leases, idempotent target actions, exponential retry and a
dead-letter/review state. A web request only creates the termination/purge
request; it never attempts a long synchronous purge.

### 7.4 `AuthorizedProviderAdapter`

All in-scope transcription and generation calls use a provider-neutral adapter
that requires a `ProviderProcessingPermit`. A direct OpenAI client is an
implementation error for a PLF user-data origin.

## 8. Endpoint and event contract

| Endpoint/event | Auth | Canonical write | Behavior |
| --- | --- | --- | --- |
| `POST /v2/processing-authorization/bootstrap` | Optional auth or signed guest | Creates/reuses `owner_principal` only | Returns principal capability and current policy status |
| `GET /v2/processing-authorization` | Account or signed guest | None | Returns exact phase, approved public copy/versions, current receipt state, allowed surfaces and historical-inventory status |
| `POST /v2/processing-authorization/accept-service` | Account or signed guest | Atomic service acceptance, required-purpose rows, age/residence receipts, initial location assessment and speaker binding when resolvable | One explicit button; Phase 1 is future-only/core, Phase 2 is existing-and-future and captures a cutoff |
| `POST /v2/processing-authorization/refuse-current-policy` | Account or signed guest | Immutable explicit refusal | Blocks new service without termination or purge; omission remains no response, not refusal |
| `POST /v2/processing-authorization/terminate-service` | Account or signed guest | Atomic service termination and purge request | Immediately blocks all new recording/processing |
| historical coverage inventory job | Reviewed service | Complete item inventory and atomic finalized set | Every pre-cutoff recording is candidate or typed exclusion; candidates require positive applicable further-use result; no dataset side effect |
| `activate_processing_policy_v1` reviewed RPC | Deployment service with exact approvals | Policy activation plus complete prior-policy carryover inventory in one transaction | Used for every material policy version change; fails if purpose capabilities or signal classification do not match |
| `transition_to_learning_live_v1` reviewed RPC | Deployment service with exact approvals | Wraps policy activation, phase transition and dataset/training enable events in one transaction | Fails closed unless the bounded pipeline is operational and both capabilities are armed |
| `POST /v2/ai-notices/:version/rendered` | Account or signed guest | Render receipt | Authenticated post-paint acknowledgement |
| `POST /v2/lab/recordings` | Account or signed guest | Audio object, attempt, snapshot and job/outbox in one DB transaction after R2 upload | Rejects before provider work without current authority |
| `POST .../retry-processing` | Exact owner | Provider operation only after revalidation | Termination blocks retry |
| `POST .../retry-ideal-text` | Exact owner | Provider operation only after revalidation | No re-upload/re-transcription unless authorized operation needs it |
| `POST .../send-to-coach` | Exact owner | Coach-delivery event | Requires `coach_review` purpose |
| queue worker claim | Service | Provider permit and operation events | Rechecks current authority or exact policy-cutover carryover before download and each provider stage |
| coach queue claim/read | Coach | Existing blind assignment events | Cancelled/terminated items cannot be newly opened |
| future dataset builder | Offline reviewed service | Release/exclusion records plus `ml_release_eligibility_decisions` | Recomputes acquisition, current Phase 2 authority, historical/future coverage, Article 6(4)/separate-authority result, principal/speaker, retention/deletion, audio hash and surface-contract eligibility; remains disabled |

No endpoint accepts an arbitrary principal ID from the browser as authority.

## 9. User and guest flow

### 9.1 New guest

```text
open Willab
  -> bootstrap durable signed guest principal
  -> fetch exact active phase and PLF policy
  -> show country field + one “Agree and continue” action
  -> Phase 1 copy: core recording/coaching + individual profile
  -> Phase 2 copy: complete continuously learning service
  -> copy includes 18+ confirmation and voice-only Terms
  -> server verifies exact policy/copy and trusted initial country assessment
  -> server stores one exact phase receipt
  -> show first-exposure AI notice
  -> enter Lounge/Lab
  -> no per-recording speaker or country prompt
```

### 9.2 Existing account

In Phase 1, the same one-action screen and server contract apply. A legacy
Terms row or localStorage flag does not silently satisfy the current policy.

On transition to Phase 2, every existing user must re-accept once before a new
recording or new coaching. The screen prominently states—outside the full
Terms—that eligible recordings already stored and future recordings may be
used for Willab's bounded pooled speech-coaching models. The server action
captures the historical cutoff and starts the inventory only against an
applicable further-processing assessment. Before acceptance,
historical recordings remain excluded from shared datasets/training. Before
inventory finalization, they remain excluded even after acceptance.

If the applicable Article 6(4) outcome is missing, incompatible or unresolved,
the affected stored recording receives a typed exclusion. Phase 2 acceptance
does not override that result and the product does not invent a second
checkbox. Product/legal may later approve a separate mechanism; until its
immutable resolution is satisfied, the recording stays excluded. Recordings
created after acceptance use their Phase 2 snapshots and do not use the
historical-compatibility route.

If the user does not accept, existing projects and completed content remain
viewable and exportable, and deletion plus Terms/Privacy/data-rights surfaces
remain available. New recording and coaching are blocked. No purge starts.

### 9.3 Guest signup

The guest owner claim runs as it does today. Acquisition events remain on the
guest principal and are linked through claim provenance. If the target account
principal lacks the same current phase/policy receipt, it must accept before a
future recording. Existing guest recordings remain traceable to their original
receipt and may be historical candidates only through a finalized Phase 2
inventory covering their exact principal graph. Claiming never copies or
fabricates acceptance.

### 9.4 Policy change

When the active policy version changes materially, status returns
`PLF_POLICY_CHANGED`; the user reviews and accepts the new exact copy before
new processing. Historical acceptances remain immutable.

### 9.5 Refusal and missing acceptance

An explicit “Not now” may record refusal; closing the screen or timing out is
only no response. Either state blocks new service under the current policy.
Neither state deletes data, starts a purge, or is presented as account
termination. Existing content and data-rights controls remain accessible.

### 9.6 Service termination and deletion

The account page uses “End recording and coaching” or approved equivalent and
keeps it visually and semantically separate from refusing updated Terms.
Account deletion is also separately attributable. After immutable
confirmation:

- all new recording and coaching requests fail closed;
- active jobs receive cancellation requests;
- the legal/self-service area remains available;
- deletion progress is visible as requested/in progress/review required/done;
- the user is not told deletion completed until every required target has a
  recorded terminal outcome.

### 9.7 Recording already processing during a material policy cutover

The user is not asked to repeat a recording that the prior policy already
accepted. The frozen carryover lets that exact job finish its normal feedback
pipeline even if the user has not yet accepted the new policy. It does not
unlock another Take, a new manual retry, new coaching or any learning use. The
next new recording/coaching request shows the current-policy acceptance screen.
If the user terminates or deletes the account—or retention expires or the item
is quarantined—the carryover is cancelled like every other product job.

## 10. Coach flow

The blind-review sequence does not change:

```text
blind packet -> immutable coach judgment -> reveal context
```

The current PLF phase changes queue eligibility only:

- new coach delivery requires active `coach_review` authority;
- termination revokes unopened assignments and cancels pending deliveries;
- an already-submitted blind judgment remains immutable audit evidence but is
  excluded/erased according to the purge and retention decision;
- the coach never sees Terms, age, country, legal-basis or purge details; and
- a generic “item no longer available” response prevents identity/status
  leakage.

`personalized_exercise_recommendation` is registry-only and cannot appear in an
active policy until exercise matching and all operational controls exist.
Exercise matching remains MLC-3 work and is not implemented by this design.
The technical `exercise_adequacy_classification` surface appears only in MLC-3
provenance.

## 11. Service termination and deletion traversal

Order is safety-critical:

1. append termination and purge request atomically;
2. make current authorization false immediately;
3. cancel pending web/worker/provider/dataset/training jobs;
4. freeze the complete purge target inventory;
5. invalidate user-facing and learning eligibility;
6. remove source audio/transcripts/derived artifacts from product databases
   under FK-aware handlers;
7. delete unshared R2 objects and record read-after-delete verification;
8. cancel/delete provider objects where the provider exposes such an API, or
   record the verified DPA/retention outcome where no remote object exists;
9. remove or invalidate dataset release items and their manifests;
10. invalidate evaluations, training runs, adapters and assignments that
    depended on affected items;
11. quarantine completed models for retraining/unlearning review rather than
    claiming model weights were erased automatically;
12. retain only allowlisted legal/security/billing evidence under an explicit
    retention rule; and
13. mark complete only when no unknown or failed target remains.

Before shared R2 deletion, the worker checks every unaffected reference. Shared
objects required by valid lineage are retained with an
`object_retained_shared` event while the affected lineage is invalidated.

Current code lacks complete training/evaluation/model-lineage tables. Dataset,
training and promotion must therefore remain disabled until those canonical
tables and purge links exist. This design must not fabricate successful model
purge evidence.

## 12. Migration and controlled-cutover plan

Migration numbers are sequencing placeholders only. Each slice is additive,
rehearsed against a production-like backup, and separately reviewed.

| Slice | Dark deliverable | Gate before activation |
| --- | --- | --- |
| A | Phase-neutral registry, purpose-capability versions, further-use assessments/resolutions, `power_score` classifications, policy activations/carryovers, events and RLS/RPCs | Engineering + Product/legal + ML/data schema review |
| B | Account/guest status, one-action acceptance/refusal/termination APIs and dark UI; registry-only purposes remain unavailable | Exact-copy Product/legal + Engineering review |
| C | Audio-object SHA-256, atomic recording boundary and orphan sweeper | Engineering + ML/data lineage review |
| D | Provider permits and complete provider dependency refactor | Security/Engineering + processor review |
| E | Historical-coverage sets/items and inventory-only worker | ML/data + Product/legal eligibility review |
| F | Purge inventory and synthetic deletion execution | Product/legal + Engineering deletion acceptance |
| G | Phase 1 readiness monitor, exact implemented `power_score` classification and founder rehearsal | Product/legal + Security + Engineering; classification conflict must be resolved |
| H | Separately authorized `core_service` policy activation with generic cutover-carryover reconciliation | Explicit deployment authorization |
| I | Bounded dataset/training infrastructure, general cutover inventory, end-to-end production rehearsal and separately approved `armed` dataset/training capabilities while Phase 1 still blocks execution | MLC-2/MLC-3 + Product/legal + security + processor + production reviews |
| J | Phase 2 exact policy, Article 6(4) assessment/resolution, re-acceptance UI and historical inventory rehearsal | Product/legal + ML/data + Engineering acceptance |
| K | Atomic `learning_live` transition, dataset/training unlock and frozen prior-policy carryover inventory | Explicit founder deployment authorization; all-or-nothing transaction |
| L | Evaluation and promotion capabilities | Each capability separately reviewed and authorized; no implied activation |

No migration seeds a policy, creates a user receipt, reinterprets historical
data, enables a learning capability or changes the live route.

### Authoritative runtime transitions

The only runtime states are:

- `core_service` — current Phase 1 policy is authoritative;
- `learning_live` — current Phase 2 policy is authoritative; and
- `killed` — no new recording, coaching or provider processing.

Unknown, missing or contradictory state resolves to `killed`. State changes
occur only through the reviewed append-only transition contract. Environment
variables and frontend values may request a deployment configuration but
cannot independently activate a phase.

At each surface cutover, canonical authorization writes activate atomically as
legacy authorization writes become non-authoritative/read-only. There is no
learning-provenance dual write. Product state needed by the live app may remain
in mixed legacy tables until migrated, but those tables cannot authorize a
dataset, training run or provider operation.

Every material policy activation first verifies that each required purpose is
operational and that the exact deployed `power_score` classification is
approved and hash-matched. It then freezes the cutoff, reconciles all eligible
non-terminal prior-policy product jobs, creates their carryovers and activates
the new policy in the same transaction. This applies within a phase as well as
between phases.

`learning_live` cannot exist while dataset release or training remains merely
disabled/armed. Those two capabilities are pre-approved and armed under Phase
1, then enabled by the same PostgreSQL transaction that changes the phase.
Evaluation and promotion remain later independent gates. The same transition
also satisfies the universal policy-cutover contract before new Phase 2
acceptance is required.

### Data treatment at cutover

- Preserve projects, recordings, Takes, transcripts, Ideal Text, locks,
  orange anchors, coach judgments, invoices and product history.
- Preserve all historical acceptance/consent evidence unchanged.
- Never relabel a legacy row as Phase 1 or Phase 2 acceptance.
- Never fabricate a historical hash. An object is excluded until a verified
  download recomputes its SHA-256.
- Phase 1 recordings remain pooled-ineligible.
- Phase 2 existing-user acceptance creates a cutoff and inventory; it does
  not immediately make stored recordings eligible.
- Historical items remain excluded without a positive applicable Article 6(4)
  result or a separately approved and satisfied authority resolution.
- Deleted, expired, orphaned, quarantined, legally blocked and unknown-
  provenance recordings remain typed exclusions.

## 13. Rollback and kill behavior

Before phase activation, dark services/UI can be removed while additive schema
remains inert. After either service phase has accepted a production receipt,
rollback is only to `killed`, never to legacy authority:

1. append a reviewed transition to `killed`;
2. stop new recording, coach delivery and provider work;
3. keep receipts, objects, snapshots, coverage sets and queued events
   immutable, including further-use assessments, signal classifications,
   policy activations and carryovers;
4. keep cancellation/purge and transactional-outbox retries operational;
5. repair forward or deploy the last compatible phase-aware build; and
6. reactivate a service phase only through a new reviewed transition.

Database rollback is forward-only and cannot delete authorization, notice,
inventory or deletion evidence. A Phase 2 incident does not fall back to Phase
1 without a new Product/legal policy and explicit transition because doing so
would silently change the accepted service.

## 14. Monitoring and audit signals

Aggregate-only readiness and production metrics include:

- current runtime phase, transition age and exact active-policy count;
- unknown/contradictory state (must be zero and resolves killed);
- passive/page-render acceptance attempts (must be zero);
- approval-copy/evidence hash verification failures;
- active policy-purpose rows whose capability is not exact and operational
  (must be zero), including any registry-only exercise purpose;
- active policy without an approved hash-matched `power_score` classification
  (must be zero and resolves killed);
- `power_score`, confidence values/bands, cue values or classification fields
  observed on user-facing payloads (must be zero under AC-9);
- signal-classification code/config drift and expired/conflict artifacts;
- Phase 1 snapshots or release decisions marked pooled-eligible (must be zero);
- `learning_live` without dataset and training both enabled by the same
  transition transaction (must be zero);
- dataset/training execution while merely `armed` or while in Phase 1 (zero);
- dataset-builder/training-worker heartbeat, queue age and last successful
  bounded cycle against the approved cadence while `learning_live`;
- Phase 2 recording/coaching attempts without the current receipt;
- non-terminal pre-cutover prior-policy jobs missing a carryover row for any
  material policy activation (zero);
- carryover permits used by a different job or non-product operation (zero);
- historical coverage sets by state/age and count mismatches;
- historical items treated eligible before atomic finalization (must be zero);
- historical candidates/releases without a positive applicable further-use
  result (must be zero), grouped by typed assessment exclusion;
- coverage cutoff gaps or double-inventoried recordings (must be zero);
- new recordings without snapshots or verified audio-object hashes (zero);
- provider operations without valid permits or after termination (zero);
- release items without a fresh independently recomputed eligibility decision
  and SHA-256 (zero whenever release creation is separately enabled);
- legacy authority writes after cutover (zero);
- refusal events that created purge work (zero);
- purge requests by state/age, unknown targets and delete verification failures;
- dataset, training, evaluation and promotion capabilities and unexpected job
  counts (all zero until their separate activation).

Alerts use opaque IDs, phase/policy versions, counts and reason codes—never
audio, transcripts, blind packets or legal evidence contents.

## 15. Test and verification matrix

### Schema and policy constraints

- purpose capabilities, signal classifications, further-use assessments/
  resolutions, policy activations and carryover scopes are immutable;
- only validated RPCs append lifecycle events or resolve current state;
- active policy-purpose FKs require exact operational capability versions;
- policy activation rejects missing/mismatched classification, purpose,
  approval, monitoring, retention, deletion or rights references;
- historical coverage finalization rejects a candidate without a positive
  applicable further-use result;
- content/evidence hashes verify bytes but never substitute for legal or human
  decisions;
- browser, coach, admin and ordinary service paths have no direct write bypass.

### Acceptance, state and identity

- opening, authentication, rendering, timeout and passive use never accept;
- one explicit button produces one immutable, idempotent receipt with exact
  phase, policy/copy hashes, principal, timestamp, locale and client version;
- wrong principal, stale copy, stale phase and idempotency collision fail;
- account and signed guest contracts behave identically;
- guest claim preserves original acquisition provenance and never copies a
  receipt;
- speaker binding is reproduced solely from account/guest ownership and claim
  events; acoustic features, embeddings and similarity APIs are never read;
- static dependency tests reject acoustic/embedding imports from the identity-
  binding path;
- unknown/missing/contradictory runtime state is killed;
- no browser/admin/founder/coach/script direct-write bypass exists.

### Phase 1

- one action permits recording, transcription, coaching and individual profile;
- it creates no pooled-learning authority or eligibility;
- every Phase 1 release candidate is excluded unless later covered by a valid
  finalized Phase 2 historical item with a positive applicable further-use
  result;
- dataset/training/evaluation/promotion capabilities remain false;
- the recording→transcription→ranking→feedback loop is unchanged and does not
  wait for training.

### Phase 2 and historical recordings

- a new user accepts the complete current service with one action;
- an existing user must accept the exact Phase 2 policy before new recording
  or coaching;
- the rendered screen and submitted hash prominently cover eligible stored and
  future recordings;
- a refusal/no response blocks new service but retains view/export/delete and
  legal surfaces and creates no purge;
- the acceptance transaction freezes one cutoff;
- every pre-cutoff recording is inventoried exactly once as candidate or typed
  exclusion; post-cutoff recordings use Phase 2 snapshots;
- no historical item is eligible before re-acceptance and atomic inventory
  finalization;
- every historical candidate resolves the exact original/proposed purposes,
  policies and jurisdiction to an immutable Article 6(4) assessment;
- missing, stale, mismatched, unresolved and incompatible assessments create
  typed exclusions and cannot be overridden by Phase 2 Terms;
- `separate_authorization_required` remains excluded until an independently
  approved mechanism has a current satisfied resolution; no UI control is
  synthesized automatically;
- only lawfully collected/retained, exact-owner, hash-verified, non-deleted,
  non-expired, non-quarantined and legally available items may become
  candidates;
- orphaned, unknown/third-party provenance and unverifiable objects stay
  excluded;
- future recordings acquired under Phase 2 use their acquisition snapshots and
  never masquerade as historical compatibility candidates;
- a changed policy requires a new exact receipt.

### Operational-purpose and `power_score` gates

- a purpose may be registered as `registry_only` without affecting users;
- policy activation fails if any required purpose is not exact and
  `operational`, or lacks monitoring, retention, deletion or rights handlers;
- `personalized_exercise_recommendation` cannot enter an active policy before
  its feature exists; `exercise_adequacy_classification` is rejected as a
  policy purpose;
- the exact deployed code/configuration/feature manifest hashes to the approved
  `power_score` classification artifact;
- missing, draft, conflict, rejected, expired or mismatched classification
  blocks every phase/policy activation;
- validation detects the current acoustic sex-routing implementation and does
  not permit a false “no sex/gender inference” confirmation;
- retired challenge/threat inputs cannot reach the current ranker and any
  reintroduced runtime path expires classification;
- L1/L2/L3 regression fixtures and `power_score` ordering remain unchanged;
- user payload schemas and serialized responses contain no `power_score`,
  numeric confidence, band, cue value or classification conclusion.

### Atomic policy activation and in-flight completion

- dataset release and training can be approved/armed under Phase 1 but cannot
  execute there;
- `learning_live` transition fails unless both are armed and all exact
  approvals/configuration verify;
- phase change plus dataset/training enablement is one all-or-nothing database
  transaction;
- every same-phase material policy change uses the same locked activation and
  carryover contract;
- a simulated failure at each append leaves the phase and capabilities
  unchanged;
- every eligible non-terminal prior-policy job at the cutoff receives exactly
  one carryover and reconciliation counts/hash match;
- concurrent recording acceptance either commits under the prior policy before
  the locked cutoff and enters the inventory, or resolves the new policy
  afterward; it cannot fall between them;
- the exact carryover finishes only its already-accepted product-feedback
  stages without a new-policy receipt;
- carryover cannot authorize a new recording, post-cutoff manual retry, coach
  delivery, dataset, training, evaluation or promotion;
- termination, deletion, retention expiry or quarantine cancels carryover
  immediately, including when racing a provider-stage claim;
- retrying a failed carryover is limited to the original durable job's existing
  retry semantics; no user/manual retry creates another carryover;
- terminal prior-policy jobs and jobs accepted after the cutoff receive no
  carryover;
- Phase 2 acceptance and feedback remain independent of training-run duration.

### Learning-boundary races

- release creation/retry independently recomputes current Phase 2 authority,
  principal/speaker lineage, coverage, applicable further-use result,
  retention/deletion and object hash;
- training creation/retry rechecks current authority and release validity;
- evaluation and promotion recheck independently;
- refusal, policy retirement or termination racing any worker fails closed;
- prior snapshots/inventory/eligibility decisions cannot override current
  authority;
- stored hashes are not trusted labels; release construction recomputes bytes;
- each capability blocks its operation unless its exact state is `enabled`;
  `learning_live` alone is never sufficient;
- feedback delivery never waits for a dataset or training run.

### Recording, provider and coach boundaries

- no authority means no dispatched job/provider upload;
- upload/DB partial failure uses only the orphan-cleanup path;
- exact bytes, object, attempt, snapshot, principal and Take coordinates agree;
- worker hash mismatch fails before provider use;
- every in-scope provider call requires a matching fresh permit;
- authorization errors never degrade to an empty transcript;
- direct provider-client imports from PLF user-data modules fail static tests;
- coach packets remain blind and reveal no policy/identity detail;
- new delivery requires current authority; immutable prior judgments are not
  overwritten.

### Transparency, refusal, termination and deletion

- conversational AI remains persistently identified;
- first-exposure notice is evidenced only by authenticated render confirmation;
- no emotion processing occurs without its separately approved disclosure and
  authority;
- refusal/no response is distinct from termination and deletion;
- termination immediately blocks new work and atomically creates purge work;
- account deletion has its own immutable domain event and purge trigger; when
  it also terminates service the two events remain distinctly linked;
- complete target inventory, shared-object reference checks, provider outcomes,
  release invalidation and model quarantine are proven;
- unknown dependency yields `review_required`, never success.

### Migration, regression, performance and security

- migrations apply/reapply against production-like schema;
- product row counts/state remain unchanged unless explicitly allowlisted;
- historical founder records remain byte-for-byte auditable and confer no new
  authority;
- no legacy table can authorize a canonical dataset/training operation;
- status reads are indexed/bounded; acceptance adds no provider round trip;
- hash calculation avoids a second browser upload; purge is never request-
  synchronous;
- signed-in and guest feedback behavior remains equivalent;
- provider/storage outages fail closed with durable retry state.

## 16. Required checked-in audit artifacts

Before each cutover, Engineering must provide:

1. producer/reader/route/job/UI map for every acceptance and refusal source;
2. product-state, learning-only, mixed-purpose or unknown table classification;
3. provider-caller classification with no unresolved `mixed` or `unknown` row;
4. bucket/key, hash and deletion-adapter inventory;
5. purpose registry-to-operational-capability matrix with retention, deletion,
   rights and monitoring links;
6. exact `power_score` input/producer/config/downstream manifest and approved
   classification hash;
7. Article 6(4) assessment/resolution applicability report plus historical
   inventory reconciliation and typed exclusions;
8. every material policy-cutover reconciliation/carryover report;
9. migration preview and before/after counts for every allowlisted table;
10. proof passive and legacy paths cannot authorize new work;
11. proof release/training code cannot read legacy authority;
12. rollback/kill-switch and alert-path rehearsal; and
13. Product/legal, Engineering, ML/data, security and processor evidence
    required for that slice.

Unknown dependencies fail closed. Each mixed-purpose dependency has a named
migration owner and must pass ML/data review before its learning path changes.

## 17. Remaining externally owned approvals

Before either phase can activate:

1. a new Product/legal artifact expressly superseding PLF-1.1 for Phase 1 and
   defining Phase 2, with exact Terms/Privacy/AI-notice copy and hashes;
2. exact lawful-basis and any Article 9 code for every active purpose;
3. a reviewed purpose-capability matrix proving each active required purpose
   is operational and connected to monitoring, retention, deletion and
   data-rights controls;
4. the exact `power_score` technical manifest and Product/legal classification,
   including resolution of the present acoustic sex-routing and confidence-
   spectrum questions, or a separate founder north-star decision;
5. jurisdiction/18+ policy and risk-trigger handling;
6. processor inventory, DPAs/transfers and deletion/retention capabilities;
7. approved retention schedule and legal/security/billing exceptions;
8. DPIA/security review and applicable AI/emotion/biometric classification and
   disclosure decision;
9. updated GDPR Article 30 record of processing activities covering purposes,
   data categories, recipients/transfers, retention and security measures;
10. complete data-subject-rights operating procedure, including access,
    export, correction, objection/restriction where applicable and deletion;
11. tested security-incident and GDPR personal-data-breach procedure;
12. documented AI Act provider/deployer role determination and obligations;
13. documented Article 50(2) machine-readable output-marking applicability and
    implementation decision; and
14. Product, Product/legal, Engineering, ML/data, security and production
    approval for the exact phase/policy activation.

Phase 2 additionally requires:

1. a real, bounded, operating pooled-learning pipeline with documented benefit,
   cadence, scope and non-generic purpose;
2. exact prominent existing-and-future-recordings copy and a written
   contractual-necessity opinion establishing objective necessity rather than
   relying on Terms wording alone;
3. an immutable, jurisdiction-applicable Article 6(4) assessment for Phase 1
   historical reuse and separately approved mechanisms/resolutions wherever
   compatibility is not positive;
4. completed lineage, historical inventory, release, training, evaluation,
   promotion, deletion and model-quarantine controls;
5. approved MLC-2/MLC-3 label/release/evaluation contracts;
6. processor/security assessment for every new transfer and training system;
7. re-acceptance, refusal, general policy-cutover carryover and rollback
   rehearsal; and
8. separate Product/legal, ML/data, Engineering, security and founder
   activation approvals.

Dataset creation, training, evaluation and promotion each remain separately
unauthorized until their own operational review. Engineering must not guess
any external artifact or legal code.

## 18. Unresolved conflict requiring an external decision

Founder intent classifies `power_score` as internal speaking-delivery/ranking,
not emotion, intention, health, identity, sex or gender inference. The current
source audit cannot yet support the required “no sex/gender inference” finding:
`voice-confidence-v2`, which can feed `power_score`, contains declared-sex
weight routing and default-on acoustic fallback sex inference from baseline
f0. It also emits a “confident/doubtful” spectrum that Product/legal must
classify under the applicable GDPR and AI Act definitions.

The retired challenge/threat inputs are absent from the current
`power_score` API and must remain absent. The repository still contains
historical challenge/threat corpus vocabulary and retired artifacts; the exact
classification must prove they are non-executing for the deployed pipeline or
classify any surviving operation. An active challenge/threat inference path is
an additional explicit emotion/intention conflict, not a compatibility alias.

No code or L1/L2/L3 rule changes in this design. The conflicts must be resolved
by an exact Product/legal classification of the deployed pipeline or by a
separate founder north-star decision about the conflicting upstream behavior.
Until then, policy/phase activation fails closed. Engineering must neither
remove the term nor approve the legal conclusion itself.

## 19. ED-PLF-1.2 → ED-PLF-1.3 summary and decision filter

ED-PLF-1.3 preserves every ED-PLF-1.2 correction and adds:

- immutable Article 6(4) assessments and separately approved authority
  resolutions before any Phase 1 historical recording can qualify for Phase 2;
- typed exclusion when compatibility is negative, unresolved or inapplicable,
  without inferring permission or inventing a checkbox;
- one general atomic carryover contract for every material policy-version
  change, not only the Phase 1→2 transition;
- a hash-bound technical/Product-legal classification for the exact deployed
  `power_score` pipeline, with AC-9 and L1/L2/L3 preserved;
- explicit recording of the current sex-routing/confidence-spectrum conflict;
- a universal operational-purpose gate, keeping personalized exercises
  registry-only and exercise adequacy in MLC-3 provenance until implemented;
- corresponding migration, monitoring, race, cancellation, reconciliation,
  release and regression controls.

It also preserves: PLF-1.1 as historical only; atomic Phase 2 dataset/training
activation; independent account-deletion attribution; provenance-only speaker
binding; RoPA, data-rights and breach procedures; AI provider/deployer and
Article 50(2) reviews; and rollback to killed rather than legacy authority.

```yaml
VERDICT: JUSTIFIED-SCAFFOLDING
CATEGORY: F1-SUPPORT
WHY: These controls make the authorization architecture safe for the live F1 processing loop and prevent unsupported historical reuse.
REDIRECT: Complete Product/legal review, then request separate authorization for implementation. No production activation is authorized.
```

> ENGINEERING DESIGN READY — ED-PLF-1.3 awaits Product/legal, Engineering,
> ML/data, security, processor and production review. No implementation,
> migration, data deletion, deployment, dataset creation, training, evaluation,
> promotion or runtime activation has started.
