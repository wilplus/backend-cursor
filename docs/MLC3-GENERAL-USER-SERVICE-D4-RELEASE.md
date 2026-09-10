# MLC-3 General-User Service Rollout D4 — Release Packet

Status: `RELEASE_REVIEW_REQUESTED`

Design authority: `MLC-3 General-User Service Rollout D4`, SHA-256
`4ee8cc5f1dda8cf5e727fefdaef12a1a96a85d9fcd01c74e8953564026bf1085`.

Accepted implementation packet SHA-256:
`0349b23ea2f0c41edc3d908031120a3cb492dc7b815767eaf83a9d6140e8c085`.

ML/data and Engineering implementation acceptance are recorded for that
packet. This release package assigns the accepted implementation to migration
0326. It authorizes no commit, push, merge, deployment, production migration,
activation, real collection, dataset creation, training, evaluation, or
promotion.

## Assigned migration

| Version | Migration | SHA-256 |
| --- | --- | --- |
| 0326 | `add_mlc3_general_user_service_d4.sql` | `babc3fc6616f95360af654a3ce4a7ff415cae5f95c4261701743238668a95c05` |

Manifest SHA-256:
`fc1ef4e61a8ff7ebb375ec0458f964ca8669d9d63e9611ea8612302605fa1c06`.

The manifest is contiguous through 0326, with migration 0325 retained
immediately before 0326 as the founder-canary lower-level writer closure.

## Release-only changes

- The accepted pending SQL moved to
  `migrations/add_mlc3_general_user_service_d4.sql` and its header now names
  release migration 0326.
- The 11 already enforced RLS declarations are repeated literally so the
  repository release scanner can prove each table enables RLS in its defining
  migration. `FORCE ROW LEVEL SECURITY` remains explicit for every table.
- The founder readiness regression now requires security closure 0325 to
  precede terminal migration 0326, and verifies that both migrations finish
  with PostgREST schema reload before commit.
- D4 tests now resolve the numbered migration path. No runtime, provenance,
  comparison, authorization, product, or learning semantic changed.

## Preserved accepted boundaries

- Latest superseded speaker bindings cannot qualify as same-speaker.
- Owner assignment, new judgment and exact replay revalidate the exact current
  active source/practice binding revisions under ordered attempt locks.
- The shared rollout resolver requires the same current receipt and policy for
  both `personalized_exercise_recommendation` and `coach_review`.
- Acquisition principal, speaker identity, machine measurements, owner routing,
  blind coach judgments, paired preference and product events remain separate.
- Historical synthetic A/B writers remain inaccessible to all runtime roles.
- All 11 D4 tables enforce RLS, forced RLS, RPC-only writes and append-only
  history.
- The seed rollout is `disabled`, `serves_user=false` and
  `dataset_eligible=false`. Backend and frontend gates remain false by default.

## Exact pinned files

### Backend

```text
46279942d67670564bc17ab802fe3eb9d972784424837522c58a0ddc5d4abf0c  bin/railway-mlc3-general-service-monitor.sh
142acaa583bb535ac9770e3da067c5b2cf485111bb5bce43f8120a387d0f0eb9  config.py
4ee8cc5f1dda8cf5e727fefdaef12a1a96a85d9fcd01c74e8953564026bf1085  docs/MLC3-GENERAL-USER-SERVICE-D4.md
0349b23ea2f0c41edc3d908031120a3cb492dc7b815767eaf83a9d6140e8c085  docs/MLC3-GENERAL-USER-SERVICE-D4-IMPLEMENTATION.md
babc3fc6616f95360af654a3ce4a7ff415cae5f95c4261701743238668a95c05  migrations/add_mlc3_general_user_service_d4.sql
fc1ef4e61a8ff7ebb375ec0458f964ca8669d9d63e9611ea8612302605fa1c06  migrations/manifest.txt
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
5fd4fa296ed18a20cbb99f04035376aca5ec7b562a0d91ca523ad559280061e7  tests/test_mlc3_founder_canary_readiness.py
de7f4475188ad04981b9aada20badc9be8bc059be4b79cd6b3bfb2cb883ae9f4  tests/test_mlc3_general_service_monitor.py
b9fd140a3065b87cf2e331e80243834f6bd0b2acf39e9899d47285436511a8df  tests/test_mlc3_general_service_readiness.py
bc5655c6c666cdb3087674366828fee2c8db85c1cd9e8de45237a4ee20d2bcf5  tests/test_mlc3_general_user_service_d4.py
e489e374455b7ef80249ed2c320274a09f2b98e8023e8c07746ce9304b108e9e  tests/test_mlc3_general_user_service_d4_postgres.py
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

## Verification against this release snapshot

- Exact numbered migration 0326 applied and reapplied successfully on a fresh,
  populated, dependency-complete disposable PostgreSQL database.
- D4 PostgreSQL adversarial/concurrency/security suite: **33 passed** against
  the exact post-reapply release database.
- Release migration/security subset: **56 passed**.
- Backend full CI mirror: **5,047 passed, 361 skipped, 113 subtests**.
- Migration runner: **66 passed**. Manifest verification: **326 migrations,
  0001–0326**.
- Ruff 0.15.8, mypy and backend diff check: passed.
- Frontend: **1,535 passed across 142 files** under bundled Node 24. TypeScript,
  BFF boundary, targeted ESLint, production build and diff check: passed. The
  build emitted only four pre-existing hook warnings.
- Read-only database probes: **11/11** D4 tables have RLS and forced RLS;
  rollout state is `disabled,false,false`; synthetic assignment/judgment RPCs
  are not executable by `service_role`; reviewed owner judgment remains
  executable by `service_role`.

## Release review request

> **ML/DATA AND ENGINEERING RELEASE REVIEW REQUEST — MLC-3 General-User Service Rollout D4 migration 0326**
>
> Review this checksum-pinned release package. Verify migration 0326 ordering,
> exact preservation of accepted D4 semantics, explicit RLS and forced-RLS
> coverage, RPC-only permissions, latest-active same-speaker revalidation,
> concurrency rollback, apply/reapply safety, terminal PostgREST reload,
> manifest integrity, and disabled product/data/learning boundaries.
>
> Evidence: exact migration apply/reapply; 33 PostgreSQL tests; 56 focused
> release/security tests; backend CI 5,047 passed; frontend 1,535 passed;
> Ruff, mypy, TypeScript, BFF, ESLint, build, manifest and diff checks passed.
>
> No commit, push, merge, deployment, production migration, activation, real
> collection, dataset creation, training, evaluation, or promotion is
> authorized.

