# MLC-3 Coach Inline Exercise Authoring D5 — Release Review Packet

Status: migration 0324 assigned; release verification with every gate disabled.

Backend base: `15bd963162967aaacc2e6ff89a814b085d9b13ec`

Frontend base: `e0b4ece5583594feb105ade280b8f590c53888c3`

Accepted design SHA-256:
`cc4544d358bea690d99f3e3a4b1d99c944654e4626ffbd7df8193f9f742e1438`

The accepted D5 migration is assigned release version `0324` and is terminal
in the manifest. Assignment changes no runtime state: coach inline authoring,
serving, collection, dataset, training, evaluation and promotion gates remain
disabled.

## Implemented scope

- A completed recorded Take is frozen only as `source_before_exercise`.
- The canonical database-derived coach batch must be complete before the
  reviewer-specific reveal and inline controls become available.
- The legacy confidence queue remains audio-only for the complete blind pass.
  Transcript and machine-derived readout arrive only through the post-batch
  context.
- An exact `coach_exercise_requested` no-match item can create a case-bound,
  `user_source_dependent` exercise draft directly below its feedback card.
- Exercise title, instruction, demonstration video, language and an approved
  ordinal-vocabulary subset are stored with exact feedback, offer, need,
  reviewer, principal, authorization, clip and media lineage.
- R2 upload is preceded by a durable permit/recovery row and followed by exact
  read-after-write SHA-256 verification.
- Draft preview uses authenticated same-origin byte delivery. Database media
  authority is checked before and after the R2 read; no presigned URL escapes.
- Drafts are `awaiting_review`, `serves_user=false` and
  `dataset_eligible=false`. No exercise version, catalogue publication,
  assignment, delivery, exposure, outcome or learning row is created.
- Existing practice-upload orchestration and first-client database wrappers
  were moved into the previously approved lean abstractions without changing
  their accepted behavior.

## ML/data correction delta

- The pre-judgment confidence queue now emits only an opaque, assignment-bound
  `playback_reference_id`. It emits no transcript, object URL/key, recording
  coordinates, feature values, or machine result.
- The same-origin playback endpoint resolves the exact assignment and source
  lineage in PostgreSQL, checks the authenticated coach and the acquisition
  receipt's current `coach_review` authority, serializes on the audio object,
  loads and clips the R2 object server-side, then repeats the complete resolver
  check before returning private, no-store WAV bytes.
- Post-blind transcript content is read only from the immutable
  `exercise_blind_packets.asr_transcript` and is verified against both its
  stored SHA-256 and the packet's frozen visible payload. Mutable
  `snippets.transcript` is not an authoring source.
- Source roles and context assessments are structurally bound to the exact
  assignment, reviewer, blind packet, audio lineage and acquisition principal
  through composite foreign keys. A completed context must reproduce every
  required assignment in the frozen batch.
- Deletion traversal now includes source-role reviewers and exercise-draft
  authors. The append-only trigger helper is executable by no runtime or
  client role.
- The visible coach card and complete-batch gate now use one exact identity:
  `ml_review_assignment` + `exercise_blind_packet` + `ml_presentation` +
  `ml_rendered_exposure` + one immutable `ml_judgment`. The visible path no
  longer creates or answers a parallel `evidence_review_assignment` for this
  review act.
- The server freezes the complete canonical batch before returning opaque
  cards. A card submits its exact assignment, packet, presentation and render
  receipt; stale or foreign identities fail closed. One submitted five-state
  answer is therefore the same answer counted by complete-batch reveal.
- Post-blind context reproduces every required frozen item in canonical order.
  Offer/no-match provenance is optional: ordinary items remain available for
  general written/video guidance, while `exercise_eligible=true` is emitted
  only for the exact `coach_exercise_requested` item. Missing, extra, late or
  foreign items cannot change the frozen batch.
- Visible rendering is now independent from judgment. An intersection-visible
  exact card waits for two painted frames, then records one retry-safe
  `ml_rendered_exposure`; silence therefore remains a shown-but-unanswered
  event. A judgment accepts only the exposure ID already returned for that
  exact assignment/presentation and never creates a render itself.
- The enabled queue projects the canonical frame items directly in database
  order and keys browser state by `review_assignment_id`. It never builds a
  snippet-keyed dictionary. Two assignments may therefore share one snippet
  while retaining separate cards, exposures, judgments and completion state.
- Ordinary items in a mixed revealed batch retain their exact review-assignment
  identity without fabricated V3 offer IDs. The frontend accepts nullable
  offer-specific membership/candidate IDs only when `exercise_eligible=false`;
  exercise-eligible items still require both. Composer keys remain the exact
  `review_assignment_id`, so a valid mixed batch mounts in canonical order.
- Blind judgment submission now serializes the assignment and idempotency key
  in a stable lock order. Concurrent exact retries produce one immutable
  winner and one exact replay. After reveal, only the already-stored exact
  assignment/exposure/decision/key tuple may replay; a new key or changed
  answer fails closed.
- Ordinary frozen items now have an executable assignment-bound general-
  guidance writer. It accepts nullable V3 membership/candidate identity only
  for `general_product_guidance`, and instead freezes the exact batch, reveal,
  judgment, assignment, blind packet and audio lineage in the attachment hash.
  Exercise attachments and drafts continue to require both exact V3 IDs.
- The ordinary-guidance write issues a current `coach_review` authorization
  snapshot only at submission time. Its receipt and policy are derived from
  the source packet's immutable acquisition snapshot—never a latest-receipt
  lookup—and its hash includes the exact review act. This does not authorize
  historical pooling or any learning use.
- Ordinary private video uses the established durable pre-write recovery,
  R2-only exact-byte verification and media-validity locks under the
  `coach_review` purpose. Note/video replay is exact; foreign batch/reveal/
  assignment identity and revocation fail closed without creating exercise,
  practice, outcome, judgment, catalogue or dataset records.
- Ordinary video replay repeats current reviewer and assignment authority
  checks after the potentially blocking media-validity lock. Revocation during
  contention therefore rejects rather than returning historical authorization.
- An exercise attachment with either exact feedback identity missing is
  rejected by the HTTP boundary before authorization, permit creation or any
  storage write. Nullable feedback identity remains exclusive to assignment-
  bound `general_product_guidance`.

## Intentionally not implemented or activated

- The independently approved N1 compatibility/content/safety/rights review
  that converts a draft into an immutable exercise version.
- A fresh post-authoring deterministic candidate inventory and assignment.
- User delivery, playback, re-record collection or successor practice review
  for the new draft.
- Reusable independent publication.
- Dataset creation, training, evaluation or promotion.

Those are separate transitions. This packet requests acceptance only of the
disabled inline bootstrap and exact draft/media lineage.

## Verification

- Corrective PostgreSQL rejection/reapply suite: **12 passed** against a
  disposable local database containing the accepted D3 foundation and the
  released canonical coach-assignment prerequisite.
- The real migration runner applied terminal migration **0324** to a clean
  disposable database reconstructed from the accepted 0323 prerequisite
  shape; direct reapply then completed cleanly. Populated-database reapply also
  completed cleanly.
- The PostgreSQL suite includes the complete no-match path with no practice
  session: freeze one mixed batch, render and answer each opaque card once,
  reveal both in canonical order, and expose exercise eligibility only for the
  no-match item. It also asserts that no practice or outcome row is created.
- It also proves visible-without-answer persistence, exact render replay,
  foreign-exposure rejection, and two required assignments sharing one
  snippet: completing only one keeps reveal closed and completing both opens
  the canonical ordered context. A forced two-connection judgment race proves
  one winner/one replay, and a post-reveal test proves only the exact lost-ACK
  request can replay.
- The suite additionally executes ordinary-item note and private-video
  persistence, exact replay, foreign-identity rejection and post-revocation
  rejection while proving that no practice, measurement or draft row is
  fabricated.
- Backend focused contract/refactor suite: **54 passed**.
- Backend migration/security release suite: **45 passed**. Migration-runner
  unit suite: **66 passed**.
- Backend full local CI: **4,989 passed, 319 skipped, 113 subtests passed**.
- Migration manifest verification passed; migration 0324 is terminal and
  assigned without changing any disabled gate.
- Ruff 0.15.8 (the CI-pinned version), mypy and diff checks passed.
- Frontend correction-focused suites cover independent visible render,
  no-click silence, exact exposure reuse, retry identity, absent-exposure
  rejection, unmounted-card behavior and same-snippet assignment isolation.
- Frontend full suite under the bundled Node 24 runtime: **1,531 passed across
  142 files**.
- Frontend TypeScript, BFF and full Next.js production-build checks passed.
- The self-contained corpus browser rehearsal passed after its synthetic queue
  was updated to exercise the opaque same-origin playback reference used by
  the accepted D5 runtime contract.

## Pinned checksums

### Backend

```text
3d7cb6c59efd1a956a79d54103722390ffe6b4434a8ea742fd2a9806dd0b91eb  .env.example
d7fd6ffb1f06e46ffa7ca2c54af0a643c9f9fe9bdce374953031680a3cd54425  config.py
b04b0456f5b5042daa7d794dbf91f304c4779d2e1aa073448bdf120abdacd230  routes/v2/coach.py
8b0c87fb8f56b0efa7bccd644f6c31229fa7c8f5cdf076339d6461dd84a4425c  routes/v2/coach_guidance_delivery.py
4f6aa86f5cfe00c8b464a1fc291ab17d64ad6793c1ee49c247ecc2f1d35376d3  routes/v2/explore_ideal_text.py
573525208d6d8b3f23618606aa14e1ffd9cdae62b2e64a96bd7d7ff3abb98453  routes/v2/mlc3_first_client_coach.py
d579be497d7dd5910740a234c5d1a5edfb3b290b6fdbabc4d101378432403a38  routes/v2/mlc3_first_client_service.py
50daae82f8f98f12dc844aca8858863027d07e0bc6e1a51a8ff1869dadd37d53  services/coach_guidance_delivery.py
d7c5b5106f4f64b4c2a93f016308e0a7abeaf23e0bf63ac029501d895cb430ec  services/data_purge_registry.py
4266ec54679052870169aefaa3cce8f84c3e8f315b2b51b510883b799e097b5e  services/db.py
3631db39d6b949cee6420bd846d912ef6409fd04e74a51ec654a75658b99a20f  services/first_client_repository.py
af0adb6b901820d962f393388b4d642ddabff25a48940fb8f79823b7e26280c2  services/practice_attempt_orchestrator.py
d1a9b20f32cbb0d046f159a594e65733bf95ffed0e866a6fcd3ad01212abfb34  tests/test_first_client_refactor.py
e1dd981e5cb4227155607ea78656fd8e66369844207dc61900c8ad1701d501f7  tests/test_mlc3_coach_inline_authoring_d5.py
b5be16d49bb4bd46d069a0d04f980d584aec94ca310dd976bfbf2cc8e189240f  tests/test_mlc3_coach_inline_authoring_d5_postgres.py
e75f4cca01905cd348ef515575607c659998de9aa8dbf4c2f8b5cf34970fa24f  tests/test_coach_guidance_delivery_d3_postgres.py
8a8d0f64b6091668cf85ae203d2d7147e68e069ad3417d7fd704f8e5f6c5b369  tests/test_mlc3_first_client_service_d2.py
cc4544d358bea690d99f3e3a4b1d99c944654e4626ffbd7df8193f9f742e1438  docs/MLC3-COACH-INLINE-EXERCISE-AUTHORING-D5.md
f82ba8b84319fd8798bfcbccaff63be4ae2cdae40fcac6625d685019ad258be2  migrations/add_mlc3_coach_inline_exercise_authoring_d5.sql
769f05f21a28469d2a4c9f3f95b6e76253c912c5a3bbaa872c923d86f38ae27d  migrations/manifest.txt
```

### Frontend

```text
35734151fc25ff627eb150addc929b555cc15007cd8b02f36e1feda830a056f3  .env.example
a58d859a0a904d373aaba10e248ba8a7eed3121aa1e9fc5a2ab9ff11f688b9fb  .env.local.example
b7aca4b499beb8a9a39bbca69ac745561bba011a784dea9864e313d70b1877f3  src/app/api/v2/coach/guidance/attachments/route.ts
26cb8ad618ae54223e208edf8d616dd5f1bf8de8eb0d90ee79d6d0159d0ea2e3  src/app/api/v2/coach/mlc3/[...path]/route.ts
5bff7e1821acd74492c2b155e32db4eb63a86c89cefd80a0fd3d5c143baac5cb  src/app/coach/corpus/page.client.tsx
7a07bed54e516b8816bcae607dcb70a94b52576cfcf3e310b92dd5ea8193facf  src/app/dev/corpus/page.tsx
16a6052b39b1e5053acc6a6fa2baab35d02fac54c41b5dfb3fadc368977f7fcb  src/app/api/v2/coach/guidance/exercise-drafts/route.ts
fdaa7f27b8652229d7eb66fb15261dfa276eb34ab8f883042eb4672e0bae8356  src/app/api/v2/coach/guidance/exercise-drafts/[draftId]/playback/route.ts
9d7b565e870663084e7abf39c1d0f5e5bcfd700456258beb16cbd1aed039bcf8  src/components/willab/CoachGuidanceComposer.tsx
d97966e449480cdc8ebcd0099360a9adc4bcaea801075e57f06d53eef733b08f  src/components/willab/CoachInlineBlindExposureBoundary.tsx
d147ee7381007082356091d76b35869ffe5441057755298f0abf6a00435ac2cb  src/components/willab/CoachInlineBlindExposureBoundary.test.tsx
2574932ad119f67ebc8ba7df509362eb3d08808064ba943f41b8b4d7c8e4e2b5  src/components/willab/CoachStarVerdictOverlay.tsx
f20b9a2b5601843a715ce482d447847d6d15415804586404b1e7fe4211c5c3cb  src/components/willab/Mlc3FirstClientPractice.tsx
1d3eee16cf3955455e919ddcca631cdf824ce696b317a096c154926491d00c5b  src/components/willab/blindLabelingIsBlind.test.ts
d5dc6a88a21623de3bc080fa07ca32b79b6b680ac9d908db3238224adcf4ac1e  src/components/willab/confidentVoicePractice.test.ts
56bd0440ae1624b12f18c13f1739816f3136ba72926fe5b8362751cef4ecfeb1  src/components/willab/usePracticeFlow.ts
329931db19f734cb3d915ac6ddc484842c53f01af4fafe69f270941ffb8bb962  src/services/api/coachGuidanceDelivery.test.ts
e69e0a624a9dc0670df57d31d7bbdf41bece03be96ecb8b797fd3857da6032fd  src/services/api/coachGuidanceDelivery.ts
ef50ee4adc504b33f5a6146992d69fb5f1a682dac3842d3faca465f2695ce8f5  src/services/api/stateRatings.ts
ef9d707c3e1f5deadf6033f91314e8d0122438c29a0679c362118f36461c0697  src/services/api/stateRatings.inline.test.ts
ce036ab16c01feca3447567944cc2aafc339bade3ccaec4b70ee4b983c566962  src/services/api/trainingCorpus.test.ts
3664e302bec4ab2bfac9e5716dffc04dea17ab9f7012e105b0e3e33d7a2e032a  src/services/api/trainingCorpus.ts
```

## Requested release review

ML/data should verify complete-batch blindness, `source_before_exercise`
typing, exact response/no-match/source-pattern lineage, case-dependent media,
product-only semantics, deletion coverage and disabled learning boundaries.

ML/data and Engineering should verify the accepted semantics are unchanged;
migration 0324 is terminal and manifest-pinned; PostgreSQL apply/reapply,
adversarial rejection, upload recovery, exact replay, R2-only transport,
pre/post-read authorization, RLS/RPC permissions, deletion traversal, frontend
BFF forwarding and all default-disabled gates remain intact.

```text
VERDICT:  ADVANCE-F2
CATEGORY: F2
WHY:      Removes the first-exercise bootstrap deadlock without treating the
          completed Take as practice or creating serving/learning authority.
REDIRECT: Obtain independent release-package acceptance; do not push, deploy,
          migrate production or enable any runtime/data/learning gate.
```
