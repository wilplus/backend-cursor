# MLC-3 General-User Service Rollout D4 — Disabled Implementation Review

Status: `IMPLEMENTATION_RE_REVIEW_REQUESTED`

Design authority: `MLC-3 General-User Service Rollout D4`, SHA-256
`4ee8cc5f1dda8cf5e727fefdaef12a1a96a85d9fcd01c74e8953564026bf1085`.

This packet freezes a local, unassigned implementation. It does not authorize
migration assignment, commit, push, merge, deployment, activation, real
collection, dataset creation, training, evaluation, or promotion.

## Implemented contract

- One central rollout-aware access resolver distinguishes historical
  `allowlisted_service`, `explicit_cohort`, and `generally_available` records.
  Every new service row freezes the rollout revision, enrollment revision,
  resolver version, operation mode, and canonical rollout identity hash.
- Enrollment and every replay require the exact acquisition principal and the
  same current processing receipt/policy carrying both
  `personalized_exercise_recommendation` and `coach_review`. Optional pooled
  authorization remains separate and never gates service.
- Rollout revisions freeze cohort membership or the reviewed GA risk decision,
  capacity policy, required policy, and activation window. The seed revision is
  disabled and creates no enrollment or service record.
- Each source and practice acquisition has its own explicit self-speaker action,
  immutable pseudonymous speaker identity, count/identity status, target span,
  and binding revision. Email, account ownership, and acoustic similarity never
  assign speaker identity.
- Comparison, owner preference, randomized coach A/B, and later adequacy paths
  require the exact current source and practice target bindings to resolve to
  the same speaker after contention and on replay. Mismatch/unresolved state is
  a typed product exclusion and creates no comparison or learning record.
- Superseded target bindings cannot qualify. Owner pair assignment, judgment
  creation, and exact replay share consistently ordered source/practice
  identity locks and revalidate the exact active binding revisions frozen into
  the pair. A concurrent correction wins cleanly and leaves no partial
  judgment. The historical synthetic coach A/B writers remain inaccessible to
  runtime roles until an equivalent reviewed service wrapper exists.
- The browser cannot assert authoritative passage, attempt index, rollout,
  enrollment, or speaker identity. PostgreSQL allocates practice attempt order
  under lock and the server derives frozen evidence and timing policy.
- Offer, practice, and guidance audio use authenticated same-origin byte
  delivery. Each read resolves current authorization/media state before and
  after the exact R2 read and verifies byte length and SHA-256. No service path
  returns a presigned R2 URL or silently falls back to another provider.
- Capacity/backpressure controls are versioned and serialized. A typed halt
  closes rollout without deleting immutable history.
- The aggregate monitor and SELECT-only readiness report check exact RPC/RLS
  surface, direct-write closure, rollout/enrollment lineage, recovery state,
  capacity, coach/need readiness, security migration 0325, signed deployment
  evidence, signed R2 evidence, alert receipts, and two-pass emergency disable.
- All product actions, speaker-routing actions, measurements, judgments,
  comparisons, delivery events, and media provenance remain separate. No row is
  dataset eligible and no outcome, improvement, confidence-truth, or exercise-
  adequacy label is inferred.

## Exact pinned files

### Backend

```text
46279942d67670564bc17ab802fe3eb9d972784424837522c58a0ddc5d4abf0c  bin/railway-mlc3-general-service-monitor.sh
142acaa583bb535ac9770e3da067c5b2cf485111bb5bce43f8120a387d0f0eb9  config.py
4ee8cc5f1dda8cf5e727fefdaef12a1a96a85d9fcd01c74e8953564026bf1085  docs/MLC3-GENERAL-USER-SERVICE-D4.md
7106cced39b659e1f41b4d140106dcb3bf8a0a9a97c67df3d4430d7312d6b593  migrations/pending/add_mlc3_general_user_service_d4.sql
6c8bb3f6770a391fe4132aee72bc04ef9c9a4288c35650be2884595e74431c11  routes/phase2_guard.py
54f332c8bb37931e9f4734444efea7034a3bc54c6580b1cce0e1043f32908f29  routes/v2/coach_guidance_delivery.py
f07568c3e3b148eb6a6f29fe2403c2eea787bc3e02543afccc35af7a83f7f7cd  routes/v2/mlc3_first_client_service.py
0434393255812a165c2d9cb757d33c4c1beb09f44fbf5b6d05e0af8155c5d326  scripts/check_mlc3_general_service_readiness.py
508ffd2ebf41e30d9e429e00bc462160e0a6b514f237a5ebb599fbade81ac782  scripts/monitor_mlc3_general_service.py
0506f18007da8305b4d7c11fbd18bd153f134cd87537404c20c9f0a067d5ebb6  services/coach_guidance_delivery.py
eed0317c5f488af6e18e4884a8e9616609f10dca3b971784494a3736710982fc  services/data_purge_registry.py
e0a4b99ba835b0e03d5c63c3c91a73f399dc0853626fccba7da25a7e87fe4b8b  services/first_client_repository.py
35a33ec61949897a7132492e86c792ff9dd9fdc1a50215277a0ec800eba07779  services/mlc3_first_client_feedback.py
38ff6939f76f21c33a2da83955cf1c1ccc67ed3fd3ab6ff41733e89b43b48611  services/mlc3_general_service_monitor.py
56843688660e5ab66ab05650a5d05bebec3ce1612233af3efcce36672083bfa6  services/mlc3_general_service_readiness.py
9096c7a285806cd3ebdd38c054d22820bd545bd8e62cbbc963ff676a7b492645  services/practice_attempt_orchestrator.py
77a48c3d2e9d4c48998d40162c9ad702e6f4147075a7180f97388ee8fb12b06e  tests/test_coach_guidance_delivery_d3.py
f40a96d05af7041bf6edd50887525280d66434c276a9406aea359a498ad1b793  tests/test_mlc3_first_client_feedback.py
6633611d151eb09e69e4cbeef15ebdfab26b10e1566b9df957e8cf007d60defa  tests/test_mlc3_first_client_service_d2.py
c26e597b0f283f8483e927d6239e879929796c5ff344c3344519ce9708f6053c  tests/test_mlc3_founder_canary_readiness.py
de7f4475188ad04981b9aada20badc9be8bc059be4b79cd6b3bfb2cb883ae9f4  tests/test_mlc3_general_service_monitor.py
b9fd140a3065b87cf2e331e80243834f6bd0b2acf39e9899d47285436511a8df  tests/test_mlc3_general_service_readiness.py
4e61edd31fc1b93fceb8ad6b2bed78f18ee5758455333a3b117c6740eaa4b4bd  tests/test_mlc3_general_user_service_d4.py
d2f919734e282b86c0ca64337a6ace7ab32d961f5273a1f4c834e480b797c2d9  tests/test_mlc3_general_user_service_d4_postgres.py
```

### Frontend

```text
cbf1f0fd7504735371cf0576bb342cfaaeb8ff97f4ffd321417a9dceaeb71deb  src/app/api/v2/user/mlc3/[...path]/route.ts
4595efabc4a19f0f6eb7beeb58458ec7d1bed197e72a4f6a1b88000e26502e9c  src/components/willab/Mlc3FirstClientPractice.tsx
4b470db12d9240fb8252c5146ab875edc881f9813e0a93e7e7bad04e8d87fcfe  src/components/willab/confidentVoicePractice.test.ts
3ca1e3a731aac5bfd62566d0f7b60cd1860e92cf0bf4cdd8bc54502c87cdaf0f  src/components/willab/usePracticeFlow.ts
99b6246269ed74200f1aab07f0fd6f8a5cea76e6fa34fd2103fb6ef1b4e4f3a8  src/services/api/coachGuidanceDelivery.test.ts
b48830d7531b03ab3430e08d2d6a175f65125c399f77b58291b52b8d24920357  src/services/api/coachGuidanceDelivery.ts
ae3d8af0219dc6812320e2dc1ee8c24a70475b120060214b497fa63173006d78  src/services/api/mlc3FirstClient.test.ts
3a03717612c6912b554bc090cc67631a4594043c53513c9a7881755e051ee4be  src/services/api/mlc3FirstClient.ts
```

## Verification against this snapshot

- D4 PostgreSQL adversarial/concurrency/security suite: **33 passed**. This
  includes latest-superseded rejection, post-pair identity correction, exact
  replay rejection after correction, unchanged-binding idempotent replay, and
  a forced two-connection correction-versus-judgment race with zero partial
  judgments.
- D4 migration apply and reapply: passed on a populated, dependency-complete
  disposable PostgreSQL database.
- Focused backend D2/D3/D4 service, route, readiness and monitor tests:
  **105 passed**.
- Backend full local CI mirror: **5,047 passed, 361 skipped, 113 subtests**.
- Migration runner: **66 passed**. Manifest verification: **325 migrations,
  0001–0325**, with D4 still unassigned under `migrations/pending`.
- Ruff 0.15.8, full mypy and backend diff check: passed.
- Frontend full suite under bundled Node 24: **1,535 passed across 142 files**.
  Focused D4 API/UI tests: **23 passed**.
- Frontend TypeScript, BFF boundary, targeted ESLint, production build and diff
  check: passed. The build emitted only four pre-existing hook warnings.

The locally retained historical D2/D5 PostgreSQL databases were not used as
compatibility evidence because inspection showed they were missing accepted
release dependencies. No passing result is claimed for those incomplete
fixtures; the D4 suite clones its own pinned dependency schema for every test.

## Known limitations and release boundary

- Only the approved deterministic `rushed_phrase_endings` need contract is in
  scope. No learned matching, ranking, effectiveness claim, or additional need
  is introduced.
- The self-speaker copy is currently “Is this your voice in this recording?”,
  “Yes, this is my voice”, and “Not sure or someone else”. Only the affirmative
  action persists identity-routing provenance; the negative action records
  nothing and blocks comparison routing.
- This packet contains no production principal enrollment, cohort or GA rollout
  revision, coach mapping, live R2 evidence, production config attestation, or
  activation evidence.
- All gates default false: backend user serving, coach inline authoring,
  frontend user/coach presentation, dataset creation, training, evaluation and
  promotion. The database rollout seed is disabled.

## ML/data implementation review request

> **ML/DATA IMPLEMENTATION RE-REVIEW REQUEST — MLC-3 General-User Service Rollout D4 same-speaker correction**
>
> Review this checksum-pinned, unassigned, disabled snapshot. Verify the central
> rollout-aware resolver; exact dual-purpose same-receipt/policy authority;
> acquisition-principal isolation; immutable enrollment and rollout lineage;
> separate source/practice self-speaker target bindings; rejection of latest
> superseded bindings; exact current same-speaker revalidation during owner
> assignment, judgment and replay under ordered locks; runtime closure of the
> unguarded synthetic coach A/B writers; non-mutating typed
> exclusions; server-derived practice identity; same-origin R2 byte delivery;
> capacity/backpressure; deletion traversal; exhaustive RLS/RPC-only closure;
> monitoring/readiness evidence; and structural non-serving/non-dataset gates.
>
> Evidence: 33 PostgreSQL tests; migration apply/reapply; backend CI 5,047
> passed; frontend 1,535 passed; TypeScript, production build, BFF, Ruff, mypy,
> manifest and diff checks passed.
>
> No migration assignment, commit, push, merge, deployment, activation, real
> collection, dataset creation, training, evaluation, or promotion is
> authorized.
