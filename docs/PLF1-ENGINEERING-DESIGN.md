# ED-PLF-1 — Product/legal onboarding and processing engineering design

**Product contract:** `PLF-1`  
**Status:** ENGINEERING DESIGN READY FOR REVIEW · NO IMPLEMENTATION STARTED  
**Prepared:** 2026-08-29  
**Owner:** Artur Willoński

Decision-filter stamp:

`FILTER: JUSTIFIED-SCAFFOLDING — cat F1-SUPPORT — preserve recording→feedback while closing authorization, lineage, and deletion boundaries; keep datasets, training, and promotion disabled.`

## 1. Scope and non-authorization boundary

This document is a standalone implementation design for the locked product
decision in [`PRODUCT-LEGAL-FLOW-PLF-1.md`](./PRODUCT-LEGAL-FLOW-PLF-1.md).
It defines the dependency cutover, schema, APIs, user/guest flow, provider
boundary, termination/deletion workflow, rollout, rollback, monitoring, and
tests.

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

PLF-1 produces one authoritative processing-authorization boundary for both
accounts and guests:

```text
durable owner principal
  -> approved Terms/notice + 18+ receipt + residence country
  -> immutable purpose-specific authorization event
  -> current-authority check
  -> recording object SHA-256 + recording attempt + authorization snapshot
  -> durable processing job
  -> provider permit
  -> feedback
```

It also produces one termination and deletion boundary:

```text
termination/account deletion
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
does not create a dataset release or start a training job.

## 3. Current-state dependency audit

### 3.1 Competing acceptance sources

| Producer/reader | Current responsibility | Classification | PLF-1 treatment |
| --- | --- | --- | --- |
| Frontend `WelcomeConsent` and `useWillabFlow` | Local first-run button and `localStorage` flag | Product gate with no authoritative server receipt | Retire as an authority; retain only presentation state until PLF-1 cutover |
| `GET/PUT /v2/user/consent` + `user_consents` | Authenticated Terms ledger plus mic/share/email preferences | Mixed-purpose legacy product state | Preserve historical rows; stop using it for recording authority; keep unrelated preferences |
| `GET/PUT /v2/user/sharing-consent` + `user_settings` flags | Chat mic/share/email/Terms flags | Mixed-purpose legacy product state | Remove Terms as an authority; preserve mic/email/peer-sharing preferences |
| `GET/POST/DELETE /v2/user/mlc2-consent` | Founder-only explicit bundled consent and speaker binding | Canonical but founder-only and legally over-specific | Generalize in place into the neutral PLF authorization contract; preserve historical events |
| `ml_product_legal_approvals` | Immutable approved copy/evidence | Reusable canonical foundation | Rename/generalize; keep immutable approval records |
| `ml_consent_*` tables/RPCs | Two consent purposes fixed to Article 6(1)(a) | Reusable structure with incorrect universal semantics | Rename/generalize in place; do not maintain a parallel consent ledger |

There must be exactly one current authority after cutover. Historical ledgers
remain audit evidence, but no legacy row is automatically relabelled as a
PLF-1 acceptance.

### 3.2 Identity and acquisition

| Dependency | Current behavior | PLF-1 treatment |
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
- a pre-existing account principal needs its own current PLF-1 acceptance for
  future recordings unless it already accepted the same active policy; and
- no compliance record is copied or rewritten.

### 3.3 Recording and processing producers

| Path | Current gate | PLF-1 requirement |
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

PLF-1 applies to operations that send user-acquired recording, transcript,
derived voice features, or associated coaching content. These operations must
go through a provider adapter requiring a database-issued processing permit.
Unrelated system/admin generation remains outside PLF-1 but must declare a
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

1. One active PLF policy is authoritative for recording/coaching.
2. A browser-local flag is never authorization.
3. Account and guest principals use the same server contract.
4. No full date of birth is collected; only an over-18 result is retained.
5. Age is never inferred from voice.
6. Country of residence is collected at setup, not before each recording.
7. Gateway location is rechecked only on a versioned risk trigger.
8. No per-recording sole-speaker checkbox exists.
9. The Terms contain the voice-only rule.
10. Each accepted recording references the exact immutable authorization
    snapshot active at acquisition.
11. Current authority is checked again at downstream provider, dataset,
    training, evaluation, and promotion boundaries.
12. Product/legal events, product actions, ML judgments and exposures remain
    separate records.
13. Audio SHA-256 verifies exact bytes; it is not globally unique identity and
    is never treated as a speaker identifier.
14. A provider call carrying PLF user data cannot occur without a typed permit.
15. Termination blocks new processing immediately, even while deletion runs.
16. Dataset creation, training, evaluation and promotion remain disabled.
17. No founder, coach, administrator, migration or script bypass exists.

## 5. Target architecture

```text
                           immutable approval evidence (R2 + SHA-256)
                                           |
                                product_legal_approvals
                                           |
                           processing_authorization_policies
                                           |
                        processing_authorization_policy_purposes
                                           |
owner_principals -- processing_authorization_events -- event_purposes
        |                    |                 |
        |         age/residence receipts      |
        |                    |                 |
        |         location risk assessments   |
        |                    |                 |
        +---- recording attempt acceptance RPC+
                          |       |       |
                  auth snapshot  audio object  processing job
                          |       |       |
                          +--- provider operation/permit
                                      |
                                   feedback

termination event -> data_purge_request -> frozen purge targets
                                            | DB
                                            | R2
                                            | provider operations
                                            | queues
                                            | dataset/release lineage
                                            | evaluations/training/models
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
- `contract_family text not null` — `PLF-1`, optional future families
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
- `pooled_model_improvement`
- `exercise_adequacy_classification`

Optional emotion-state inference is **not** silently added to these purposes.
If Product/legal later permits it, it requires its own purpose, approved copy
and user control.

#### `processing_authorization_policies`

In-place generalization of `ml_consent_policies`:

- `version text primary key`
- `product_legal_approval_id uuid not null`
- `contract_family text not null check (contract_family = 'PLF-1')`
- `acceptance_kind text not null` — value comes from the approved artifact,
  not source code
- `required_for_recording boolean not null`
- `active_from`, `retired_at`
- `jurisdiction_policy_version text not null`
- `age_policy_version text not null`
- `location_risk_policy_version text not null`

At most one policy may be active for a contract family at a time. Activating a
policy requires immutable approval evidence whose copy hash verifies.

#### `processing_authorization_policy_purposes`

One row per policy and purpose:

- `policy_version`
- `purpose_id`
- `required_for_service boolean`
- `legal_basis_code text not null`
- `article_9_basis_code text null`
- `provider_processing_allowed boolean`
- `dataset_release_allowed boolean`
- `training_allowed boolean`
- `evaluation_allowed boolean`
- `promotion_allowed boolean`

These fields describe the scope of the approved legal policy; they are not
runtime activation switches. Their exact values come from the Product/legal
artifact. Independent runtime capability flags for dataset creation, training,
evaluation and promotion remain hard-disabled under this design even if the
approved policy permits those future purposes. Engineering does not derive a
lawful basis or operational authorization from a checkbox.

### 6.2 Immutable acceptance and termination

#### `processing_authorization_events`

In-place generalization of `ml_consent_events`:

- exact `acquisition_principal_id`
- exact policy and approval IDs
- `event_kind`: `accepted`, `terminated`
- accepted copy, Terms, Privacy and AI-notice versions
- `locale`
- `residence_country_code char(2)`
- `adult_confirmed boolean`
- `age_assurance_method`: initially `self_attestation`; later provider result
- source route, client version, occurred/received times
- immutable affirmative action envelope
- idempotency key
- `supersedes_event_id` for termination

Checks enforce that acceptance has `adult_confirmed=true`, a supported
residence country under the referenced policy, and every required purpose.
A termination references the exact accepted event and never deletes it.

#### `processing_authorization_event_purposes`

One immutable row per accepted/terminated purpose containing the exact
approved legal-basis codes. A single checkbox may create several purpose rows;
those rows remain semantically separate.

Historical MLC-2 founder consent rows are preserved as historical
`acceptance_kind=explicit_consent` records. They are not automatically expanded
to the new purposes and do not satisfy PLF-1.

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

### 6.5 Recording authorization snapshots

#### `processing_authorization_snapshots`

In-place generalization of `ml_consent_snapshots`:

- principal, accepted event and policy
- recording attempt, project and eventual Take
- age receipt/state
- residence event and latest required location assessment
- exact purpose-state object
- `captured_at`
- retention state
- canonical snapshot SHA-256

The recording-acceptance RPC creates this snapshot in the same PostgreSQL
transaction as the recording attempt and processing job/outbox record. A
historical snapshot proves acquisition conditions but never overrides a later
termination when current authority is rechecked.

### 6.6 Exact audio-object lineage

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

### 6.7 Provider operations and permits

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
- active, non-terminated PLF policy acceptance;
- purpose authorization;
- required current location assessment;
- object SHA verification;
- absence of an active termination/purge block; and
- the provider/operation allowed by the approved processor configuration.

It creates an operation plus an `authorized` event. In-scope provider adapters
require that operation ID and reject missing, stale or mismatched permits.
Raw OpenAI client access is forbidden from PLF user-data modules by a static
dependency test.

### 6.8 Product-neutral termination and purge

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

### 6.9 Security, immutability and RLS

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
- policy/status reads;
- acceptance and termination;
- current-purpose checks;
- residence/location assessment resolution;
- recording snapshot creation;
- provider-permit issuance; and
- stable public error codes.

Routes and jobs may not recreate these rules.

Public decisions:

- `PLF_POLICY_NOT_CONFIGURED` — 503, recording disabled
- `PLF_ACCEPTANCE_REQUIRED` — 403, show setup gate
- `PLF_POLICY_CHANGED` — 409, show renewed acceptance
- `PLF_ADULT_CONFIRMATION_REQUIRED` — 403
- `PLF_REGION_BLOCKED` — 451 or reviewed product status
- `PLF_LOCATION_REVIEW_REQUIRED` — 403, no provider work
- `PLF_TERMINATED` — 403, legal/self-service surfaces only
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
| `GET /v2/processing-authorization` | Account or signed guest | None | Returns approved public copy, versions and current state |
| `POST /v2/processing-authorization/accept` | Account or signed guest | Atomic acceptance, purpose rows, age/residence receipts, initial location assessment and speaker binding when resolvable | Requires exact copy/policy hash, `adult_confirmed=true`, country and idempotency key |
| `POST /v2/processing-authorization/terminate` | Account or signed guest | Atomic termination and purge request | Immediately blocks new recording/processing |
| `POST /v2/ai-notices/:version/rendered` | Account or signed guest | Render receipt | Authenticated post-paint acknowledgement |
| `POST /v2/lab/recordings` | Account or signed guest | Audio object, attempt, snapshot and job/outbox in one DB transaction after R2 upload | Rejects before provider work without current authority |
| `POST .../retry-processing` | Exact owner | Provider operation only after revalidation | Termination blocks retry |
| `POST .../retry-ideal-text` | Exact owner | Provider operation only after revalidation | No re-upload/re-transcription unless authorized operation needs it |
| `POST .../send-to-coach` | Exact owner | Coach-delivery event | Requires `coach_review` purpose |
| queue worker claim | Service | Provider permit and operation events | Rechecks current authority before download and each provider stage |
| coach queue claim/read | Coach | Existing blind assignment events | Cancelled/terminated items cannot be newly opened |
| future dataset builder | Offline reviewed service | Release/exclusion records only | Independently rechecks current authority and audio hash; remains disabled |

No endpoint accepts an arbitrary principal ID from the browser as authority.

## 9. User and guest flow

### 9.1 New guest

```text
open Willab
  -> bootstrap durable signed guest principal
  -> fetch active PLF policy
  -> show country field + one unchecked acceptance control
  -> acceptance copy includes 18+ confirmation and voice-only Terms
  -> server verifies exact policy/copy and trusted initial country assessment
  -> show first-exposure AI notice
  -> enter Lounge/Lab
  -> no per-recording speaker or country prompt
```

### 9.2 Existing account

The same screen and server contract apply. A legacy Terms row or localStorage
flag does not silently satisfy PLF-1. Existing projects and completed content
are preserved. Until the user accepts, only sign-in, Terms/Privacy, data-rights
and termination/deletion surfaces remain available.

### 9.3 Guest signup

The guest owner claim runs as it does today. Acquisition events remain on the
guest principal and are linked through claim provenance. If the target account
principal lacks the same current PLF policy acceptance, it must accept before
making a future recording. Existing accepted guest recordings remain traceable
to their original receipt.

### 9.4 Policy change

When the active policy version changes materially, status returns
`PLF_POLICY_CHANGED`; the user reviews and accepts the new exact copy before
new processing. Historical acceptances remain immutable.

### 9.5 Termination

The account page uses “End recording and coaching” or approved equivalent,
not “withdraw mandatory consent while continuing normally.” After immutable
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

PLF-1 changes queue eligibility only:

- new coach delivery requires active `coach_review` authority;
- termination revokes unopened assignments and cancels pending deliveries;
- an already-submitted blind judgment remains immutable audit evidence but is
  excluded/erased according to the purge and retention decision;
- the coach never sees Terms, age, country, legal-basis or purge details; and
- a generic “item no longer available” response prevents identity/status
  leakage.

Exercise matching remains MLC-3 work and is not implemented by PLF-1.

## 11. Termination and deletion traversal

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
tables and purge links exist. PLF-1 must not fabricate successful model purge
evidence.

## 12. Migration and cutover plan

Migration numbers are proposed sequencing only; implementation review owns
the final manifest entries.

### Slice A — neutral authorization schema (`0310` proposed)

- Rename/generalize the existing canonical approval/consent tables in place.
- Add purpose registry and policy-purpose rows.
- Preserve historical founder events exactly.
- Add age/residence/location and AI-notice tables.
- Add service-only RPC contracts and RLS.
- Seed no PLF policy and create no user acceptance.

### Slice B — audio and recording boundary (`0311` proposed)

- Add `recording_audio_objects` and exact SHA-256 columns/constraints.
- Add one atomic recording-acceptance RPC.
- Add orphan-object inventory/sweeper contract.
- Keep the existing live route unchanged behind the cutover mode.

### Slice C — provider permits (`0312` proposed)

- Add provider operation/event tables and permit RPC.
- Refactor in-scope provider calls behind `AuthorizedProviderAdapter`.
- Complete and check in the provider dependency classification.
- Run in read-only rehearsal; no product activation.

### Slice D — termination and purge (`0313` proposed)

- Generalize purge tables and add target inventory.
- Implement cancellation/deletion adapters for PostgreSQL, R2, OpenAI and
  queues.
- Run inventory-only rehearsals against synthetic principals.
- Keep destructive production execution disabled.

### Slice E — status, UI and readiness (`0314` proposed)

- Add aggregate-only readiness RPC and alerts.
- Implement account/guest onboarding, AI notice and termination UI.
- Replace local Welcome authority and founder-only gate.
- Update exact approved Terms/Privacy copy only after Product/legal evidence is
  configured.

### Atomic cutover mode

One backend-controlled mode selects the whole authorization writer boundary:

- `legacy` — current behavior; PLF schema dark
- `plf1` — PLF authoritative; legacy Terms writes disabled/read-only
- `killed` — no new recording/provider work

Unknown values resolve to `killed`. No mode writes the same acceptance to both
legacy and PLF stores. After the first PLF production acceptance, rollback is
to `killed`, never to `legacy`, because legacy recording would acquire new data
without the current PLF contract.

Frontend state is presentation only. The backend mode and current status are
authoritative.

### Data treatment at cutover

- Preserve projects, recordings, Takes, transcripts, Ideal Text, locks,
  orange anchors, coach judgments, invoices and product history.
- Preserve historical acceptance and consent records unchanged.
- Do not import or reinterpret historical records as PLF-1.
- Require the active PLF acceptance before the next new recording or retry
  that invokes processing.
- Never backfill a fabricated audio hash. Existing objects may be hashed by an
  explicit verified download job; until verified, they are excluded from new
  learning eligibility.

## 13. Rollback

### Before PLF activation

Disable dark services/UI and revert application code. Additive/renamed schema
remains inert; immutable rehearsal rows remain marked non-production.

### After PLF activation

- set mode to `killed`;
- stop new recording and provider work;
- keep accepted receipts, objects, snapshots and queued events immutable;
- repair forward or deploy the last PLF-compatible application;
- never fall back to localStorage, `user_consents`, `user_settings.terms`, or
  founder-only consent as recording authority; and
- keep purge jobs retryable.

Database down-migrations must not delete immutable authorization/deletion
evidence. Recovery is forward-only.

## 14. Monitoring and alerts

Aggregate-only readiness metrics:

- active PLF policy count (must equal one before enforcement);
- approved-copy/evidence hash verification failures;
- recording attempts without an authorization snapshot (must be zero in
  `plf1` mode);
- audio objects missing SHA verification (must be zero for new attempts);
- provider operations without a valid permit (must be zero);
- provider operations started after termination (must be zero);
- risk assessments in `review_required`/`unavailable`;
- terminated principals with active processing jobs;
- purge requests by state and oldest age;
- unknown/failed purge targets;
- R2 delete verification failures;
- legacy Terms writes after cutover (must be zero);
- MLC-2/MLC-3 dataset, training and promotion flags (must remain false).

Alerts route to Sentry/operations using reason codes and opaque IDs only.

## 15. Test and verification matrix

### Schema and security

- approval, policy, acceptance, snapshots, notices and purge evidence are
  append-only;
- purpose and legal-basis rows match the exact approved policy;
- no browser role has direct write access;
- service RPCs reject wrong principal, stale copy, stale policy and
  idempotency collisions;
- unknown mode is killed;
- no direct PLF-table write bypass exists.

### Identity

- new authenticated principal accepts once;
- new guest principal accepts once with the signed capability;
- another guest token cannot read/write the receipt;
- signup preserving the same principal preserves receipt identity;
- claim into a pre-existing account preserves guest acquisition provenance
  without copying it;
- deletion traversal covers every claimed/aliased principal for the subject;
- unresolved speaker identity never becomes learning-eligible.

### Onboarding

- checkbox/control begins inactive;
- exact policy and copy hash are required;
- `adult_confirmed=false` fails and no date of birth is stored;
- unsupported residence country fails under the active policy;
- supported country creates the correct immutable receipt;
- no per-recording sole-speaker control exists;
- AI notice receipt is created only after authenticated render confirmation;
- material policy change forces renewed acceptance.

### Location

- no check runs on an ordinary unchanged session;
- every versioned risk trigger creates an assessment;
- browser-spoofed country headers are rejected;
- signed/trusted gateway country is accepted;
- blocked/review-required decisions prevent new recording/provider work;
- no raw IP enters PLF location tables.

### Recording atomicity and audio

- no current authority: object is not processed and no job is dispatched;
- R2 upload failure: no DB attempt/snapshot/job;
- DB acceptance failure after upload: object enters orphan cleanup only;
- acceptance succeeds: object, attempt, snapshot and job/outbox share exact
  principal/project coordinates;
- hash is computed from exact input bytes;
- one-byte change changes SHA-256;
- identical bytes from two principals produce distinct object records;
- worker read-back mismatch fails before provider upload;
- retries reuse the exact object and independently recheck authority.

### Provider boundary

- every in-scope call requires a valid permit;
- permit purpose/provider/object mismatch fails;
- termination between job enqueue and worker claim prevents provider upload;
- termination between stages prevents the next provider operation;
- authorization exceptions propagate as terminal domain states and are never
  converted to empty transcripts;
- static test rejects direct OpenAI client use in PLF user-data modules;
- admin/founder scripts cannot mint permits without exact provenance.

### Coach

- authorized item reaches the blind queue;
- blind payload remains free of machine/user answers;
- terminated unopened assignment cannot be claimed;
- generic unavailability response leaks no termination reason;
- prior immutable blind judgment is not overwritten.

### Termination and deletion

- termination immediately blocks recording/retry/coach delivery;
- duplicate termination is idempotent;
- pending queue/provider operations receive cancellation;
- target inventory is complete and immutable;
- unknown dependency produces `review_required`, never success;
- unshared R2 object is deleted and read-after-delete verified;
- shared object is retained while affected lineage is invalidated;
- provider with no deletion API records its contractually verified retention
  outcome rather than a fake delete;
- datasets/releases containing the subject are invalidated;
- affected models are quarantined and cannot be promoted;
- allowlisted legal/billing/security evidence is retained with reason/expiry;
- completion requires every target terminal.

### Migration and regression

- migrations apply from a production-like schema and reapply safely;
- historical founder consent remains byte-for-byte auditable;
- no historical acceptance is relabelled PLF-1;
- project, Take, transcript, Ideal Text, lock and orange state counts are
  unchanged;
- current recording→processing→Ideal Text flow passes under PLF acceptance;
- guests remain able to record after accepting;
- signed-in users and guests receive identical processing behavior;
- viewing/exporting/deleting data remains available after termination;
- dataset/training/promotion remain hard-disabled.

### Performance and failure

- authorization status read is indexed and bounded;
- recording acceptance adds no provider round trip;
- SHA calculation streams or uses the already-loaded upload without a second
  browser upload;
- location checks do not run every session;
- purge work never runs in the request process;
- provider/storage outages fail closed with a durable retryable state.

## 16. Required checked-in audit artifacts

Before each implementation cutover, Engineering must provide:

1. producer/reader/route/job/UI map for all acceptance sources;
2. provider-caller classification with no `mixed` or `unknown` row;
3. storage bucket/key and deletion-adapter inventory;
4. database product/learning/mixed/unknown classification;
5. before/after row counts for any data-changing migration;
6. proof legacy acceptance paths cannot authorize recording after cutover;
7. proof datasets/releases cannot read an inactive authorization; and
8. Product/legal, Engineering and ML/data review evidence appropriate to the
   affected slice.

Unknown dependencies fail closed.

## 17. Implementation slices and gates

| Slice | Deliverable | Review before next slice |
| --- | --- | --- |
| 1 | Neutral schema, purpose registry, RLS/RPCs, no active policy | Engineering + Product/legal schema review |
| 2 | Account/guest authorization APIs and dark UI | Product/legal exact-copy review + Engineering |
| 3 | Audio object SHA and atomic recording boundary, dark | Engineering + ML/data lineage review |
| 4 | Provider permits and complete dependency refactor, dark | Security/Engineering + processor review |
| 5 | Termination/purge inventory and synthetic execution | Product/legal + Engineering deletion acceptance |
| 6 | Readiness monitor and controlled founder rehearsal | Product/legal + ML/data + Engineering |
| 7 | Separately authorized production cutover | Explicit deployment authorization |

MLC-3 exercise matching begins only after the PLF foundation required by its
data acquisition, authorization, audio lineage and deletion contracts is
accepted. MLC-3 still requires its own design and ML/data approval.

## 18. Unresolved approval inputs

The design is implementable, but activation requires these externally owned
answers/artifacts:

1. exact approved PLF onboarding/Terms/Privacy/AI-notice copy and hashes;
2. exact lawful-basis code per purpose, including Article 9 treatment;
3. approved jurisdiction-policy artifact and handling of travel/risk mismatch;
4. documented AI Act classification for confidence and learning-profile
   processing;
5. processor inventory, DPA/transfer references and deletion/retention
   capability per provider;
6. approved retention schedule, including legal/security/billing exceptions;
7. persistent AI badge product decision (the first-exposure notice itself is
   retained); and
8. whether self-attested 18+ is the launch method or an external over-18-only
   provider is required in any jurisdiction.

None of these may be guessed by Engineering.

> ENGINEERING DESIGN READY — ED-PLF-1 awaits Product/legal, Engineering, and
> ML/data review. No implementation, migration, data deletion, deployment,
> dataset creation, training, evaluation, promotion, or runtime activation has
> started.
