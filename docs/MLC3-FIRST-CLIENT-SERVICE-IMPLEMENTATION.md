# MLC-3 First-Client Service D2 — Local Implementation Review Packet

**Scope:** local implementation with every serving and data gate disabled  
**Backend base:** `0a02060c1674bb81bd3c1b254d7ca140c8d9619d`  
**Frontend base:** `b44796e6ae837a01b11301b58fed38d783927840`  
**Accepted design SHA-256:**
`b465b3070e543ed1c3395a1de34dfd21686f6c808d7007bc3944bc28ba662fd8`

The accepted migration is assigned release version `0323` and is included in
the manifest. Assignment does not activate the service: all four serving gates
remain disabled. Dataset creation, training, evaluation and promotion remain
absent.

## Implemented service loop

- Feedback V3 produces a complete service-mode inventory under the locked
  75-word Manager budget. Rendering and the exact immutable five-state owner
  response are separate records.
- An exercise offer binds the exact acquisition principal, Project, Take,
  frozen feedback membership, selected candidate, rendered exposure, response,
  source clip/audio lineage, N1 machine-only source pattern, complete candidate
  inventory, approved need contract, and catalogue snapshot.
- Missing responses and `confident_audio_unclear` fail closed. Other owner
  responses are routing facts only and never affect deterministic eligibility
  or ranking.
- Exact or nearest reviewed eligible exercise matching is deterministic. An
  honest no-match produces `coach_exercise_requested`.
- Assignment, delivery, confirmed rendering, playback, capture, processing and
  preference remain separate immutable events. Delivery is never treated as
  exposure.
- Offer delivery, render and playback events—including exact replays—serialize
  through the offer event key and exact source-audio object, then revalidate a
  freshly derived current authorization check, immutable lineage, recording
  attempt, audio hash and deletion ledger immediately before return or insert.
- Practice capture uses a pre-write R2 permit/recovery row, exact-byte SHA-256,
  read-after-write verification, immutable recording/audio identity, transcript
  and raw acoustic/safeguard measurements. It never derives `improved` or any
  outcome label.
- The first valid attempt is selected deterministically. Invalid, missing and
  unresolved earlier attempts remain recorded. Owner A/B preference remains a
  subjective product response.
- Original and practice clips receive separate blind confidence assignments,
  exact render receipts and independent five-state coach judgments. They do not
  substitute for the randomized A/B preference workflow.
- Post-blind general notes or reviewed videos can attach to any selected frozen
  feedback item. Only the exact qualifying Confident Voice item may receive an
  MLC-3 exercise; rewrite, praise and structure are never converted into
  acoustic needs.
- Guidance media uses exact R2 upload/recovery/verification provenance and a
  fresh database-authorized signed-read resolver. Catalogue publication creates
  a new clean reviewed exercise version and immutable catalogue snapshot.
- Source and practice acquisitions retain separate service and pooled-learning
  provenance. Pooling never gates service, and all produced records remain
  structurally dataset-ineligible.
- Authorization checks stored on offers, sessions and media runs remain
  immutable historical evidence. They are never treated as 24-hour bearer
  permits: every operation and replay derives a fresh current check from the
  exact historical source identity and revalidates the active receipt, policy,
  principal allowlist, service block, retention/deletion state and media leaf
  after contention. Wall-clock check timestamps keep long READ COMMITTED
  transactions fail-closed without expiring an otherwise valid session merely
  because its acquisition check is older than five minutes.
- Source acquisition receipts reuse only the recording attempt's immutable
  acquisition-time service snapshot. A pooled snapshot must predate the exact
  acquisition and share its receipt and policy; later opt-in is non-retroactive.
- The browser supplies neither the authoritative practice passage nor its
  window. PostgreSQL derives the passage from frozen evidence and freezes the
  versioned 24-hour service window.
- Service offer and practice-session writes submit and independently verify
  the authenticated `acquisition_principal_id`.
- Service-mode storage and playback fail closed unless the exact configured R2
  bucket is available. Playback metadata comes only from database resolvers
  serialized against deletion and media invalidation.
- The N1 extractor records phrase, prefix and final-three-word spans, WER,
  timing, pauses, WPM, syllable/OOV state, ASR uncertainty, dBFS RMS, clipping
  and typed missingness. It derives no rushed, confidence or improvement label.
- First-valid selection accepts only the session's frozen validity contract.
  Only unanswered expired confidence assignments receive immutable successor
  revisions. Submitted judgments remain valid for completion and reveal; an
  answered clip is never silently re-assigned or judged twice.
- Practice transcription now has its own immutable provider-run envelope. An
  authorization permit freezes the exact R2 audio object and byte hash,
  provider/model, prompt, language policy, output schema and request hash
  before the provider call. A separate durable dispatch transition commits
  before bytes leave the service. Finalization rechecks the permit against
  wall-clock time and live authority after all waits. Expiry or revocation
  after dispatch records a sanitized terminal state with no provider output;
  a lost terminal write is closed by an idempotent request/run reconciliation
  path and never causes a second provider dispatch. Only an exact `finalized`
  run can create an attempt or N1 measurement.
- Dispatch and terminalization share the canonical processing-audio-object
  advisory lock with deletion. Both the deletion-event ledger and current
  audio-object leaf are rechecked after contention, so deletion wins without a
  provider call or retained output. Only the exact known authorization
  exceptions map to `revoked_after_dispatch`; unexpected database failures
  escape and are reconciled as typed `outcome_uncommitted` rather than being
  falsely classified as revocation.
- A disabled, retired or otherwise unavailable service contract emits the
  stable `MLC3_SERVICE_CONTRACT_NOT_ACTIVE` authorization error. After provider
  dispatch, that exact closure is truthfully sanitized as
  `revoked_after_dispatch`; unrelated failures remain `outcome_uncommitted`.
- Deletion traversal covers the added service records and media dependencies.
  RLS, append-only state and validating RPC-only writes remain enforced.
- Re-rendering one frozen feedback item creates a distinct immutable render
  receipt while preserving the first canonical `shown_at`; any exact rendered
  receipt may support the subsequent response without overwriting history.
- Practice upload, media-finalization, transcription and attempt creation
  replay from their canonical terminal state. A response lost after verified
  storage or transcription does not rewrite R2 bytes, redispatch the provider,
  or collide with a later recording. PostgreSQL allocates the attempt ordinal
  under a session-scoped lock; the browser never supplies it. The client
  retains the exact blob, timestamps, render identity and idempotency key until
  terminal recovery and blocks a new capture while that submission is open.
- Blind coach assignments expose neither source/practice chronology, evidence
  kind, source offsets nor object-storage paths before judgment. Their order is
  a stable opaque permutation. Playback uses a reviewer-authorized same-origin
  proxy keyed by an opaque playback reference; the backend revalidates the
  object, verifies its exact bytes, normalizes only the assigned span, then
  revalidates the complete assignment/object/clip identity immediately before
  returning the WAV. Authority or deletion changes during the R2 read fail
  closed without returning audio.
- Deletion traversal includes acquisition-subject and approver edges for the
  canary allowlist and every reviewer-owned assignment, render, judgment,
  review-set, reveal-grant and reveal-access record.

## Disabled gates

All four gates remain closed:

1. `mlc3-first-client-service-v1` is seeded with database state `disabled`.
2. Backend `MLC3_PILOT_ENABLED` defaults to false.
3. Backend and database acquisition-principal allowlists are empty.
4. Frontend `NEXT_PUBLIC_MLC3_PILOT_UI_ENABLED` defaults to false and is only a
   presentation gate; it is never trusted as authorization.

Dataset, training, evaluation and promotion operations do not exist in this
service implementation.

## Verification evidence

- Pending migration applied and reapplied cleanly on a disposable populated
  PostgreSQL dependency chain.
- First-client PostgreSQL security/contract and executable service-flow suite:
  **73 passed**, including current-authority refresh across the 24-hour service
  window, termination, policy-retirement and source-deletion rejection,
  offer-event creation/replay revocation and deletion races,
  concurrent server-side attempt allocation, opaque
  media resolution, repeated render receipts, terminal practice replay,
  permit expiry, contention, post-dispatch revocation
  for provider success/error, lost-terminal-write reconciliation, deletion
  before dispatch, deletion during finalization and unexpected database-fault
  provenance, plus explicit denial of every internal trigger and serialization
  helper to runtime roles.
- Combined First-Client, static-contract and migration-security release suite:
  **118 passed**.
- D3 media/concurrency compatibility suite: **14 passed**.
- M3-3/N1 provenance compatibility suites: **91 passed**.
- Focused backend service, media and deletion tests: **62 passed**.
- Exact backend local-CI mirror: **4,969 passed, 307 skipped, 113 subtests**;
  migration verification, Ruff and mypy passed.
- Frontend Vitest: **1,517 passed**. TypeScript and the BFF boundary check
  passed under Node 22.
- Backend and frontend `git diff --check` passed.

No live R2 object, production database, real user record or deployed service
was touched. Provider behavior is covered with local synthetic adapters; a
separate live-R2 rehearsal remains required before activation.

## Checksum pins

### Backend

| SHA-256 | File |
|---|---|
| `b465b3070e543ed1c3395a1de34dfd21686f6c808d7007bc3944bc28ba662fd8` | `docs/MLC3-FIRST-CLIENT-SERVICE-D2.md` |
| `04421ff833172df4c350dbe6f3a8048be8b0af9070e89f59ab6beb5908fc7b37` | `migrations/manifest.txt` |
| `76680350a380cba0dbeb78c213010bea42ea103a430e700286d937ed1379667b` | `migrations/add_mlc3_first_client_service_d2.sql` |
| `ffa9fc09f4baa1032e644fa36ec4777780e0cccad1ca8a986927d3123ea9dcf8` | `config.py` |
| `0a17592a70400505b30bd485f64c9dc40c87020b7f5cd3a687c38c98952c521a` | `routes/phase2_guard.py` |
| `01053069084627511157a596182da37dab6cdde91a9b373d8a49e83135fed3ad` | `routes/v2/coach_guidance_delivery.py` |
| `d64ad2b53934860b74cc97591adf1bfafac04b29c93b88a30a744b3a840c7189` | `routes/v2/explore_ideal_text.py` |
| `a83556ab290318c1143800130020d64cbab2dae118214e9894d11f46804644c8` | `routes/v2/mlc3_first_client_coach.py` |
| `a1dff8fa166858c7f38cf2f9f169ae54959af11632b1318c2261393ad015ad73` | `routes/v2/mlc3_first_client_service.py` |
| `c3643335e6f596cfa2b79f96a66f2e60b07d0e1b0ecf9e022fff29bf0ebdae4f` | `routes/v2/user_sessions.py` |
| `da45bec48bc30e5b48ba556588df72000318d7dc1a80cb4e788f2b66a4dc335d` | `routes/v2_routes.py` |
| `56779d557c2e665076e4319545ac9f202247d77a8063eb51498ab565b6eae178` | `services/coach_guidance_delivery.py` |
| `086fe2992b045c4e6217a9e3a79217b44fd1b8deb5db8467fdac51e5b6396089` | `services/coach_video_storage.py` |
| `3694741a4fb339a235f942184dbf283d4d8993f6530ef9b5cea466d36e7a3fe6` | `services/confident_voice_practice.py` |
| `2974ee7e2b63207517e821b4e1a6b9d4d744233d5e5cc877620c3df9bbed684b` | `services/data_purge_registry.py` |
| `7f5b9e6aac3b2ea2b5fe085b0e214b666a86bdf4647e794947a5441bc9f8348c` | `services/blind_review_media.py` |
| `880cdf5d6a5fcefe457f985d55d1b310aa53104a6de8e4201fc4a626cadfb56a` | `services/db.py` |
| `a533d1540845b05cf20af457f55af48b9966e83b97ee331f73703b9e2c53fd0c` | `services/feedback_data_contract.py` |
| `6e3b9d40d0d9beb2a13a9d931e152740904e32257419d218eb0f86926fdf91cb` | `services/mlc3_first_client_feedback.py` |
| `8691b219b2c2edc6d9ba2bc51199781302f38ea5799049f3948dd33c2cc7d9f9` | `services/mlc3_pilot_storage.py` |
| `ea41cbcdd625739fdcc93cbbcadbd804758758a2cc9e7789c29754ce137cf226` | `services/rushed_phrase_endings_n1.py` |
| `75ac700cd744d9ea3c58827f80ba442d1b7c81b80066e679f48dd4bde0d44ae2` | `services/snippet_transcription.py` |
| `cb59868da79f8f4ad19450b8b9223e18fd10a3af46e30572629df6f60d46c2d9` | `services/take_feedback_policy_v3.py` |
| `9ff2a1169cdb028d40588100eb9f42add87035e89771a109548e02d34d641061` | `services/take_feedback_policy_v3_service.py` |
| `ec45bdd5345720b7a3a573fbd07eeb74bdf49c8cb73b2f2478d7ddbe96c0eaaf` | `services/user_media_storage.py` |
| `3a18f393a6820f0d0a8ef92625eb27deee7499f5dfa3d6ecc5f4ad6be84a10ce` | `test_confident_voice_practice.py` |
| `469056b1ebda7ce24e93e68e35ec794094b4c3ce8bb31bb3f0d2ff78f582a04f` | `tests/test_coach_guidance_delivery_d3.py` |
| `06f32a661360e61d146470fc77ef79def0fc53de1724370101a4e174c53b56f7` | `tests/test_feedback_data_contract.py` |
| `bb9b32f2f4336dad2d9554cfea406ec3bee038dba0220d1dd84d70825d3ff0f3` | `tests/test_mlc3_first_client_feedback.py` |
| `6ff66c01164b6931b29c19e1d8fc09bbc53451c1ba3a197f6148217f11205c9f` | `tests/integration/rpq_restoration_prerequisites.sql` |
| `be6cf2fec96ddc4922e12a35478ba3170f3d35ad1085297287dbe0002c135d56` | `tests/test_blind_review_media.py` |
| `9c7489a1297db7c12d54018d8fbc16f82766e9126aa517362057e2c0ac3bf817` | `tests/test_mlc3_first_client_service_d2.py` |
| `74bcee05bd44eae3ef7e13c5fae77eb6b12ec73ffdde39c10aed98115e080074` | `tests/test_mlc3_first_client_service_postgres.py` |
| `a4c1d30e9dabb96d0abd516a9aa6dd9d109b7aa9c45ef5296ff96d87e9cc6c58` | `tests/test_mlc3_pilot_storage.py` |
| `6b9af15abe30611efb6fa31a5ef9ad681aa0816326e7c3c19dcea7c039f5cb40` | `tests/test_phase1_deletion_completion.py` |
| `023bc1adb96a5ab460d903d5f00ace6f5515f8c78a093ccc797151f4d667d7d4` | `tests/test_rushed_phrase_endings_n1.py` |
| `1c514ea6bbe9b7718b2485f3fed474873b5f47f1c62045b708f5bb2cbac6a514` | `tests/test_snippet_transcription.py` |

### Frontend

| SHA-256 | File |
|---|---|
| `97534fd0a45c2d8dae9be86df7d85625421c25f366f4a37350d1d6ce192f9617` | `src/app/api/v2/coach/mlc3/[...path]/route.ts` |
| `a53f8b8a9cbd617493e4feb15139d9e494ccc9a94f51a604abcc136ae7b1cd33` | `src/app/api/v2/user/mlc3/[...path]/route.ts` |
| `261416f2700071922a8f115b9214bbe097b9fe275bff9e8d5ae94458d8e26cc4` | `src/components/willab/CoachConfidencePracticeReview.tsx` |
| `4bd22897ec29bbcd7fa8a5554647fc2cfa6c51db57d533465f1775b25d336248` | `src/components/willab/CoachGuidanceComposer.tsx` |
| `53eb26da9c86416dd9fd092c6c646917e42b1170be11b7159ccf9b0e8cecba2d` | `src/components/willab/CoachStarVerdictOverlay.tsx` |
| `bc82c703f6c89fb6c3d802ac4d01823f79b89af44393eca06b83295b705ad604` | `src/components/willab/ConfidentVoicePractice.tsx` |
| `164a8190757d9668e09e9bdae8618e28d4607617ae21624332042cf76a0a1a62` | `src/components/willab/DeckChunkModal.tsx` |
| `3aef078f6ae26da8d05749cb05c47bc7c954f3927ea38daca88e29e8c05ab89c` | `src/components/results/MediaPlayer.tsx` |
| `a9027405bb2f03cd191aa9aeead2a23f4d73b37add41eb9faad7145b5233fdb3` | `src/components/willab/FirstClientCoachBlindReview.tsx` |
| `366cfccbceea656987961b97fc5b975c5fd0a2836ef6d085ddc8de78d934bbab` | `src/components/willab/Mlc3FirstClientPractice.tsx` |
| `18c17c4bbf7621f93959243ad2b14fd0f0c319eebdc8a28e946482f032777324` | `src/components/willab/confidentVoicePractice.test.ts` |
| `6b06be211c5e35c63a56071295df7ef37ad396be6f492db3aee3b0a9183cfb3b` | `src/services/api/coachGuidanceDelivery.test.ts` |
| `f78d984e8a2e5f80b70f66061a53a4f23765ff16d4c8ad565dec896dcd0caed4` | `src/services/api/coachGuidanceDelivery.ts` |
| `3e82bbf6b81bd1e184f576e38994ad6d3a91ee869113a21cacfde8b3d73d659a` | `src/services/api/idealText.ts` |
| `f3b0d6ab0f3a1a02f2b14f935033345b4cf1b1250944c0c81e6952c8c8e1e18b` | `src/services/api/mlc3FirstClient.test.ts` |
| `f18d2e661dcacc297072a47ac3d3d75b5b8996671b8168e50481e98dfed980ff` | `src/services/api/mlc3FirstClient.ts` |

## Review requests

> **ML/DATA AND ENGINEERING IMPLEMENTATION RE-REVIEW REQUEST — current
> authorization across the 24-hour practice window**
>
> Review the checksum-pinned correction. Verify authorization IDs frozen on
> offers, sessions, uploads and provider runs remain immutable historical
> evidence while every operation and replay derives a new current check from
> the exact historical source identity. Verify wall-clock freshness after
> contention, valid operation after the original check is older than five
> minutes, and fail-closed termination, policy retirement and source deletion.
> Verify offer delivery/render/playback event creation and exact replay use the
> same fresh authorization and exact source-audio/deletion boundary before
> returning or inserting, including revocation and deletion during event-lock
> contention with no partial event.
> Verify service-window expiry, acquisition-specific provenance, RLS/RPC-only
> permissions, atomic rollback and all four disabled gates remain unchanged.
> Evidence: 73 First-Client PostgreSQL tests; full backend CI 4,969 passed,
> 307 skipped and 113 subtests; Ruff, mypy, migration verification and
> apply/reapply passed. No migration assignment, push, deployment, activation,
> collection, datasets, training, evaluation or promotion is authorized.

> **ML/DATA IMPLEMENTATION RE-REVIEW REQUEST — authoritative practice identity
> and opaque coach playback correction**
>
> Verify PostgreSQL allocates exact attempt ordinals under a session lock and
> exact replay returns the frozen ordinal; the browser supplies no ordinal and
> retains the exact pending blob/timestamps/render/idempotency identity until a
> terminal response is recovered; and pre-judgment coach playback exposes only
> an opaque same-origin reference whose authorized backend resolver verifies
> exact bytes, normalizes the assigned span, then revalidates the complete
> identity after the R2 wait and immediately before returning WAV. Verify a
> deletion/authority change during the read returns no audio. Verify storage
> keys, offsets, evidence kind and chronology are absent from the complete
> serialized pre-judgment response. Preserve all previously accepted render,
> deletion, authorization, RLS/RPC-only and disabled-gate boundaries. No
> migration assignment, push, deployment, activation, collection, datasets,
> training, evaluation or promotion is authorized.

> **ML/DATA IMPLEMENTATION RE-REVIEW REQUEST — MLC-3 First-Client Service D2 corrections, disabled local scope**
>
> Review the checksum-pinned corrective implementation. Verify the executable
> render → response → offer → practice chain; exact authenticated acquisition
> principal binding; acquisition-time rather than later reconstructed pooling;
> server-derived passage and window; strict R2 transport; authoritative
> deletion-serialized playback resolution; exact N1 spans, measurements,
> uncertainty and missingness; the authorized immutable transcription-run
> envelope; one frozen validity contract; per-assignment expiry renewal that
> preserves submitted judgments without duplication; atomic rollback; and all
> four disabled gates. No
> migration assignment, deployment, activation, real collection, datasets,
> training, evaluation or promotion is authorized.

> **ML/DATA IMPLEMENTATION RE-REVIEW REQUEST — transcription permit and
> dispatched-run terminal correction**
>
> Review this checksum-pinned snapshot. Verify authorize → dispatch → terminal
> state transitions; wall-clock permit validation after contention; sanitized
> expiry/revocation outcomes with no provider response; exact request/run
> reconciliation after a lost terminal write; no second provider dispatch on
> replay; canonical audio-object locking across deletion, dispatch and
> finalization; deletion-event and live-leaf revalidation after contention;
> exact authorization-error classification; unexpected-fault reconciliation;
> explicit inactive-service-contract classification;
> finalized-only attempt/measurement admission; permissions, RLS, deletion
> attribution, migration apply/reapply, and unchanged blind-expiry behavior.
> No migration assignment, deployment, activation, collection, datasets,
> training, evaluation or promotion is authorized.

> **ENGINEERING IMPLEMENTATION REVIEW REQUEST — MLC-3 First-Client Service D2, disabled local scope**
>
> Review the same checksum-pinned snapshot. Verify migration apply/reapply,
> transactional and concurrency boundaries, exact-principal authorization,
> idempotent replay, R2 pre-write recovery, signed reads, event ordering,
> RLS/RPC permissions, deletion safety, frontend presentation-only gating,
> fail-closed API behavior and rollback safety. No migration assignment, push,
> deployment or activation is authorized.

> **ML/DATA AND ENGINEERING RELEASE RE-REVIEW REQUEST — MLC-3 First-Client
> Service D2 migration 0323**
>
> Review the checksum-pinned numbered release package. Verify the accepted
> semantics are unchanged; migration 0323 is terminal and manifest-pinned;
> all internal trigger/serialization helpers explicitly revoke PostgreSQL's
> default PUBLIC execute privilege; public service writers remain service-role
> only; apply/reapply, exact-current-authority regressions, deletion races and
> all four disabled gates pass. Evidence: 73 PostgreSQL, 34 static-contract and
> 11 migration-security tests (118 combined); exact backend CI and frontend
> release suites reported above. No serving, collection, dataset, training,
> evaluation or promotion gate is authorized for activation by this release.

```text
VERDICT:  ADVANCE-F2
CATEGORY: F2
WHY:      Connects exact Manager feedback to provenance-safe exercise practice
          and coach catalogue growth without creating labels or learning access.
REDIRECT: Obtain release-package acceptance, then ship migration 0323 with all
          four gates disabled.
```
