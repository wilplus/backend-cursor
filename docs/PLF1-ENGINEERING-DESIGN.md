# ED-PLF-1.2 — Staged authorization and continuously learning service design

**Product contract:** `PLF staged rollout` (`core_service` → `learning_live`)
**Status:** ENGINEERING DESIGN READY FOR REVIEW · NO IMPLEMENTATION STARTED  
**Prepared:** 2026-08-29  
**Owner:** Artur Willoński

Decision-filter stamp:

`FILTER: JUSTIFIED-SCAFFOLDING — cat F1-SUPPORT — Phase 1 preserves recording→feedback without pooled learning; Phase 2 remains fenced until the bounded learning loop and all external approvals are real.`

## 1. Scope and non-authorization boundary

This document is a standalone implementation design for the locked staged
rollout. [`PRODUCT-LEGAL-FLOW-PLF-1.1.md`](./PRODUCT-LEGAL-FLOW-PLF-1.1.md)
governs Phase 1. Phase 2 requires a new exact Product/legal artifact before it
can become active.
It defines the dependency cutover, schema, APIs, user/guest flow, provider
boundary, termination/deletion workflow, rollout, rollback, monitoring, and
tests.

ED-PLF-1.2 supersedes ED-PLF-1.1. It adds the conditional
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
dataset/training gates off               separate gates still required
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

| Producer/reader | Current responsibility | Classification | ED-PLF-1.2 treatment |
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

| Dependency | Current behavior | ED-PLF-1.2 treatment |
| --- | --- | --- |
| `owner_principals` | Durable account or signed guest owner | Reuse unchanged as the identity root |
| `X-Willab-Guest-Owner` | Signed guest capability | Reuse for guest authorization status and acceptance |
| `/v2/projects` | Creates an owner principal if needed | Reuse; project/deck setup may occur before recording authority |
| `/v2/projects/claim` | Claims or aliases a guest graph into an account | Preserve immutable acquisition origin; never copy an acceptance event |
| `ml_speakers` / `ml_speaker_principals` | Canonical speaker identity for learning splits | Reuse; do not add a parallel `canonical_subject_id` graph |

When a guest principal is claimed into an account:

- past acquisition records remain tied to the original guest principal;
- existing recordings keep that acquisition provenance;
- the claim event links the graph for access and deletion traversal;
- a pre-existing account principal needs its own exact current-phase service
  acceptance for future recordings unless it already accepted the same active
  policy; and
- no compliance record is copied or rewritten.

### 3.3 Recording and processing producers

| Path | Current gate | ED-PLF-1.2 requirement |
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
17. A provider call carrying PLF user data cannot occur without a typed permit.
18. Refusal or missing current acceptance blocks new service but does not
    delete existing content or create a purge request.
19. Termination blocks new processing immediately and starts cancellation and
    purge; deletion is a separately attributable request where applicable.
20. Release eligibility is recomputed from source evidence; it is never
    inherited from a policy-purpose field or acquisition snapshot.
21. Dataset creation, training, evaluation, and promotion remain independently
    default-off and require separate authorization even in `learning_live`.
22. Feedback never waits for a training run.
23. Phase 1 retention follows only the approved core-service schedule; it is
    never extended merely because a future learning phase is contemplated.
24. No founder, coach, administrator, migration, worker, or script bypass
    exists.

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
  -> historical coverage cutoff
  -> complete historical inventory
       ├─ verified eligible candidate
       └─ typed exclusion
  -> immutable inventory hash

canonical events -> surface eligibility -> dataset release
  -> training/calibration -> evaluation -> promotion -> assigned serving model

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

#### `processing_operational_capability_events`

Operational learning gates are a separate append-only state machine:

- `capability`: `dataset_release`, `training`, `evaluation`, `promotion`
- `state`: `disabled`, `enabled`, `killed`
- exact surface scope and environment
- activation and retirement timestamps
- Product/legal, ML/data, Engineering, security and founder approval references
- deployment/config version, actor, reason and idempotency key
- immutable event hash

The latest valid event resolves each capability; missing, malformed or unknown
state is `disabled`. A policy row cannot enable a capability. Phase 1 rejects
all four even if a bad capability event says enabled. Phase 2 merely makes
separate activation possible; it never implies it.

#### `processing_authorization_policy_purposes`

One row per policy and purpose:

- `policy_version`
- `purpose_id`
- `required_for_service boolean`
- `legal_basis_code text not null`
- `article_9_basis_code text null`
- `provider_processing_allowed boolean`
- `authorization_control`: `required_service`, `separate_consent`

The row records the approved legal scope and control type only. It contains no
`dataset_release_allowed`, `training_allowed`, `evaluation_allowed`, or
`promotion_allowed` booleans. Eligibility and operational activation are
independent decisions. Dataset creation, training, evaluation, and promotion
remain hard-disabled under this design regardless of policy wording.

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

### 6.5 Recording authorization snapshots

#### `processing_authorization_snapshots`

In-place generalization of `ml_consent_snapshots`:

- principal, accepted event and policy
- exact runtime phase at acquisition
- recording attempt, project and eventual Take
- age receipt/state
- residence event and latest required location assessment
- exact required-service purpose-state object
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

### 6.6 Historical recording coverage

Phase 2 acceptance may cover eligible recordings already stored, but an
acceptance event alone does not make any historical object eligible. Coverage
requires a complete, immutable inventory.

#### `processing_historical_coverage_sets`

- `id uuid primary key`
- exact Phase 2 acceptance event, policy and Product/legal approval
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
`orphaned_recording`, and `not_lawfully_retained`.

The Phase 2 acceptance transaction records the cutoff and commits quickly.
An asynchronous worker then enumerates the complete principal graph. Every
discovered recording becomes either a candidate or a typed exclusion. The set
is finalized atomically only when counts reconcile and its deterministic hash
verifies. Until then every historical item is learning-ineligible. Recordings
created after the cutoff use their Phase 2 acquisition snapshots, preventing
gaps and double inclusion.

### 6.7 Release-time learning eligibility

#### `ml_release_eligibility_decisions`

One append-only decision per prospective surface-specific release item and
eligibility evaluation attempt:

- exact dataset release and `learning_surface`;
- evidence span, recording object, Take, clip and candidate coordinates;
- exact `acquisition_principal_id` and canonical `speaker_id`;
- original service acquisition snapshot;
- current Phase 2 service acceptance and active policy;
- historical coverage set/item when the recording predates the acceptance
  cutoff, or a Phase 2 acquisition snapshot for future recordings;
- retention, deletion and purge state observed at evaluation;
- stored audio hash and independently recomputed audio-object SHA-256;
- applicable MLC-2 or MLC-3 contract/epoch/schema versions;
- `eligible boolean` and typed inclusion/exclusion reason;
- evaluated time, evaluator code version and immutable decision hash.

The release builder recomputes this decision immediately before including an
item. It does not read eligibility from a policy-purpose boolean, an
acquisition snapshot, an inventory disposition or a prior decision. Phase 1
recordings are always excluded unless a finalized Phase 2 historical-coverage
item proves every required condition. A dataset retry recomputes eligibility.
Training creation/retry, evaluation and promotion independently revalidate
the current Phase 2 acceptance, release validity and operational capability.
Refusal, policy retirement, termination, expiry, deletion or quarantine makes
future use ineligible immediately. An immutable published release is
invalidated and replaced through reviewed lineage rather than silently edited.

### 6.8 Exact audio-object lineage

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

### 6.9 Provider operations and permits

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
- active current-phase service acceptance for product feedback;
- purpose-specific current authority;
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
dependency test.

### 6.10 Refusal, termination, deletion, and purge

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

#### `data_purge_requests`

- exact acquisition principal
- canonical speaker when resolved; nullable only before resolution
- triggering termination event
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

### 6.11 Security, immutability and RLS

- Partial unique indexes enforce one active policy per phase and one finalized
  coverage set per acceptance/cutoff.
- Authorization status uses `(acquisition_principal_id, rollout_phase,
  occurred_at desc)`; historical inventory uses `(coverage_set_id,
  recording_id)` unique plus state/reason indexes; release checks use
  `(dataset_release_id, learning_surface, evidence_span_id, evaluated_at desc)`.
- Audio locators are unique within their store/bucket/key coordinates, while
  content hashes are deliberately non-unique.
- Foreign keys prohibit cross-principal recording/snapshot/coverage lineage;
  deferred constraints are allowed only inside the reviewed atomic RPC.
- Canonical approval, authorization, snapshot, notice receipt, object
  coordinates and purge event rows are append-only.
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
- current-purpose checks;
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

### 7.2 `DataPurgeOrchestrator`

One durable worker owns cancellation, inventory, deletion, invalidation and
completion. It uses leases, idempotent target actions, exponential retry and a
dead-letter/review state. A web request only creates the termination/purge
request; it never attempts a long synchronous purge.

### 7.3 `AuthorizedProviderAdapter`

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
| historical coverage inventory job | Reviewed service | Complete item inventory and atomic finalized set | Every pre-cutoff recording is candidate or typed exclusion; no dataset side effect |
| `POST /v2/ai-notices/:version/rendered` | Account or signed guest | Render receipt | Authenticated post-paint acknowledgement |
| `POST /v2/lab/recordings` | Account or signed guest | Audio object, attempt, snapshot and job/outbox in one DB transaction after R2 upload | Rejects before provider work without current authority |
| `POST .../retry-processing` | Exact owner | Provider operation only after revalidation | Termination blocks retry |
| `POST .../retry-ideal-text` | Exact owner | Provider operation only after revalidation | No re-upload/re-transcription unless authorized operation needs it |
| `POST .../send-to-coach` | Exact owner | Coach-delivery event | Requires `coach_review` purpose |
| queue worker claim | Service | Provider permit and operation events | Rechecks current authority before download and each provider stage |
| coach queue claim/read | Coach | Existing blind assignment events | Cancelled/terminated items cannot be newly opened |
| future dataset builder | Offline reviewed service | Release/exclusion records plus `ml_release_eligibility_decisions` | Recomputes acquisition, current Phase 2 authority, historical/future coverage, principal/speaker, retention/deletion, audio hash and surface-contract eligibility; remains disabled |

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
captures the historical cutoff and starts the inventory. Before acceptance,
historical recordings remain excluded from shared datasets/training. Before
inventory finalization, they remain excluded even after acceptance.

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

The `personalized_exercise_recommendation` product purpose may be represented
by an approved policy, but exercise matching remains MLC-3 work and is not implemented by
this design. The technical `exercise_adequacy_classification` surface appears
only in MLC-3 provenance.

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
| A | Phase-neutral registry, approvals, events, runtime transitions, RLS/RPCs | Engineering + Product/legal schema review |
| B | Account/guest status, one-action acceptance/refusal/termination APIs and dark UI | Exact-copy Product/legal + Engineering review |
| C | Audio-object SHA-256, atomic recording boundary and orphan sweeper | Engineering + ML/data lineage review |
| D | Provider permits and complete provider dependency refactor | Security/Engineering + processor review |
| E | Historical-coverage sets/items and inventory-only worker | ML/data + Product/legal eligibility review |
| F | Purge inventory and synthetic deletion execution | Product/legal + Engineering deletion acceptance |
| G | Phase 1 readiness monitor and founder rehearsal | Product/legal + Security + Engineering |
| H | Separately authorized `core_service` production transition | Explicit deployment authorization |
| I | Bounded dataset/training/evaluation/promotion infrastructure and rehearsals, still default-off | MLC-2/MLC-3 + security + processor + production reviews |
| J | Phase 2 exact policy, re-acceptance UI and historical inventory rehearsal | Product/legal + ML/data + Engineering acceptance |
| K | Separately authorized `learning_live` production transition | Explicit founder deployment authorization |
| L | Dataset, training, evaluation and promotion capabilities | Each capability separately authorized; no bundled activation |

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
- Deleted, expired, orphaned, quarantined, legally blocked and unknown-
  provenance recordings remain typed exclusions.

## 13. Rollback and kill behavior

Before phase activation, dark services/UI can be removed while additive schema
remains inert. After either service phase has accepted a production receipt,
rollback is only to `killed`, never to legacy authority:

1. append a reviewed transition to `killed`;
2. stop new recording, coach delivery and provider work;
3. keep receipts, objects, snapshots, coverage sets and queued events
   immutable;
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
- Phase 1 snapshots or release decisions marked pooled-eligible (must be zero);
- Phase 2 recording/coaching attempts without the current receipt;
- historical coverage sets by state/age and count mismatches;
- historical items treated eligible before atomic finalization (must be zero);
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

### Acceptance, state and identity

- opening, authentication, rendering, timeout and passive use never accept;
- one explicit button produces one immutable, idempotent receipt with exact
  phase, policy/copy hashes, principal, timestamp, locale and client version;
- wrong principal, stale copy, stale phase and idempotency collision fail;
- account and signed guest contracts behave identically;
- guest claim preserves original acquisition provenance and never copies a
  receipt;
- unknown/missing/contradictory runtime state is killed;
- no browser/admin/founder/coach/script direct-write bypass exists.

### Phase 1

- one action permits recording, transcription, coaching and individual profile;
- it creates no pooled-learning authority or eligibility;
- every Phase 1 release candidate is excluded unless later covered by a valid
  finalized Phase 2 historical item;
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
- only lawfully collected/retained, exact-owner, hash-verified, non-deleted,
  non-expired, non-quarantined and legally available items may become
  candidates;
- orphaned, unknown/third-party provenance and unverifiable objects stay
  excluded;
- a changed policy requires a new exact receipt.

### Learning-boundary races

- release creation/retry independently recomputes current Phase 2 authority,
  principal/speaker lineage, coverage, retention/deletion and object hash;
- training creation/retry rechecks current authority and release validity;
- evaluation and promotion recheck independently;
- refusal, policy retirement or termination racing any worker fails closed;
- prior snapshots/inventory/eligibility decisions cannot override current
  authority;
- stored hashes are not trusted labels; release construction recomputes bytes;
- each default-off capability blocks its operation even in `learning_live`;
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
- deletion is separately attributable;
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
5. historical inventory reconciliation and exclusion-reason report;
6. migration preview and before/after counts for every allowlisted table;
7. proof passive and legacy paths cannot authorize new work;
8. proof release/training code cannot read legacy authority;
9. rollback/kill-switch and alert-path rehearsal; and
10. Product/legal, Engineering, ML/data, security and processor evidence
    required for that slice.

Unknown dependencies fail closed. Each mixed-purpose dependency has a named
migration owner and must pass ML/data review before its learning path changes.

## 17. Remaining externally owned approvals

Phase 1 activation requires:

1. exact Phase 1 Terms/Privacy/AI-notice copy and hashes;
2. exact lawful-basis and any Article 9 code per purpose;
3. jurisdiction/18+ policy and risk-trigger handling;
4. processor inventory, DPAs/transfers and deletion/retention capabilities;
5. approved retention schedule and legal/security/billing exceptions;
6. DPIA/security review and AI Act classification/disclosure decision; and
7. Product, Product/legal, Engineering, security and production deployment
   approval.

Phase 2 additionally requires:

1. a real, bounded, operating pooled-learning pipeline with documented benefit,
   cadence, scope and non-generic purpose;
2. exact prominent existing-and-future-recordings copy and legal opinion;
3. completed lineage, historical inventory, release, training, evaluation,
   promotion, deletion and model-quarantine controls;
4. approved MLC-2/MLC-3 label/release/evaluation contracts;
5. processor/security assessment for every new transfer and training system;
6. re-acceptance, refusal and rollback rehearsal; and
7. separate Product/legal, ML/data, Engineering, security and founder
   activation approvals.

Dataset creation, training, evaluation and promotion each remain separately
unauthorized until their own operational review. Engineering must not guess
any external artifact or legal code.

## 18. Revision summary and decision filter

ED-PLF-1.2 changes ED-PLF-1.1 by:

- replacing the optional pooled-learning checkbox model with honest Phase 1
  core service and conditional Phase 2 continuously learning service;
- requiring one explicit current-policy action in either phase;
- requiring existing-user Phase 2 re-acceptance with prominent coverage of
  eligible stored and future recordings;
- introducing complete immutable historical coverage sets and typed exclusions;
- separating refusal/no response from termination and deletion;
- making runtime phase transitions authoritative and defaulting unknown to
  killed;
- keeping dataset, training, evaluation and promotion as independent default-
  off capabilities; and
- requiring rollback to killed, never legacy authorization.

```yaml
VERDICT: JUSTIFIED-SCAFFOLDING
CATEGORY: F1-SUPPORT
WHY: The design separates a truthful core-service phase from a conditional learning-live phase and prevents passive, retroactive or unverifiable learning eligibility.
REDIRECT: Implement only after the phase-specific approvals; activate learning_live only when the bounded learning loop and all lineage, deletion, processor, legal, ML/data, security and production gates are real.
```

> ENGINEERING DESIGN READY — ED-PLF-1.2 awaits Product/legal, Engineering,
> ML/data, security, processor and production review. No implementation,
> migration, data deletion, deployment, dataset creation, training, evaluation,
> promotion or runtime activation has started.
