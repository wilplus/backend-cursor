# MLC-3 Founder Canary Activation-Readiness Review

Status: checksum-pinned security-closure release preparation; every product
and learning gate is disabled. This packet requests release review of migration
0325 and the already accepted readiness mechanism, not approval to deploy or
activate production.

Backend base: `324430b3b773185dc21793ba77540f769071f5e0`

Frontend base: `724ce3c0c58ccd019180fc1d663effa2b5eeabe9`

Readiness contract: `mlc3-founder-canary-readiness-v1`

## Prepared change

The release already contains the complete D2/D5 product path. This slice adds
a route-independent readiness evaluator, a SELECT-only operator command and an
explicit synthetic R2 write/read/delete rehearsal. It also adds an
aggregate-only five-minute monitor, a pinned-key evidence signer and release
migration 0325 for permission closure. None is imported by a product route.
The readiness command cannot activate a contract,
allowlist a principal, write media, create a service record, or change a
frontend/backend flag. The R2 command requires an exact confirmation phrase,
uses unique fixed-prefix random-byte objects and verifies their deletion.
Security-closure migration 0325 removes service-role access to two
lower-level writers; reviewed exact-identity wrappers remain unchanged.

The evaluator distinguishes `ready_for_activation_review` from activation. It
uses 56 exact `regprocedure` signatures and complete route-call, dependency,
RLS, direct-write, seven-family zero-state, dataset and media-recovery
registries. It requires both `personalized_exercise_recommendation` and
`coach_review` to be operational and present on the same current receipt and
policy. R2 evidence is bound to both exact buckets, endpoint, account hash,
byte hashes, deletion confirmation, manifest version and a 24-hour window. It
also requires the pinned operator signature and a hashed, retained
Cloudflare-authenticated control-plane export proving public access, `r2.dev`
and custom domains are disabled for both buckets.
Railway and Vercel evidence must embed retained normalized authenticated API
exports and carry an Ed25519 signature from the release-operator key whose
public half is pinned in this packet. It must include the exact web, worker and
monitor inventory, exact commits, effective backend/learning controls and the
exact frontend production build flags. The same signed artifact must prove a
received Sentry/operations test alert (including immutable receipt IDs and
hashes) and a two-attempt idempotent emergency-disable rehearsal over the
database contract plus all four product gates. A caller who
merely constructs internally consistent JSON cannot pass verification.

## Pinned files

```text
83532e4ad27de149c39e17ba6b70bdd3455f3e51c57f4bf9cfacff55625cafdf  services/mlc3_founder_canary_readiness.py
555d2b58629fd2607a4862db4f8e628491f628645eb55dfebb9e8ec8eec55ab4  services/mlc3_founder_canary_monitor.py
ded31e5790033c772984d13622fadc49f969f4bf5b276f62be28fb1f277ee916  scripts/check_mlc3_founder_canary_readiness.py
4ef95a449bc75448272ddf23f3b8517369240557cbf12f6246fea63594110b8a  scripts/monitor_mlc3_founder_canary.py
abe9e1c5a11ed994ec967052299da4dfbb8f6e53a63c59e137dbac5f2bd3c556  scripts/rehearse_mlc3_founder_r2.py
dcabfc31cd96d3ebd10004e7d0f5cda6bf14c28df07519cfd8c72e2ed59ff5c8  scripts/sign_mlc3_founder_deployment_attestation.py
c7c896835e7071129ab6d7f6cd4870d3b8c4a61fd697126c46b796bc34814e86  bin/railway-mlc3-founder-canary-monitor.sh
66bc358b7055cf3cd08e1f3e9aea49839cfd81541077e434d6b1b670eb24bced  tests/test_mlc3_founder_canary_readiness.py
0d73f66f4f5e1df57c047dda5a468250b70f5122a85fd134b6abcee6d6d33dc0  tests/test_mlc3_founder_canary_monitor.py
900c06f3fea306a6f3a2abacaf7916f60fa657f8b7e9b2243c3a5e5db23e691e  tests/test_mlc3_founder_canary_readiness_postgres.py
2e16bdbcbf1023504e9109e39c80c8db610bf83afb034af1e162428f8b4d7895  migrations/add_mlc3_founder_canary_security_closure.sql
c854ef8021fd7fdb62d576e91b39abab27e35218c6ae1617522edaa0f9c03ff6  migrations/manifest.txt
76decb2eaf861c660d14a6ad51a22b790b2754d8efed6eccca647ac1fc029d9d  config/mlc3_founder_attestation_public_key.pem
c1833c5cee0c59570e24f7d3102cb0861660a586096a191d4a03f4a2cea0e79a  docs/MLC3-FOUNDER-CANARY-ACTIVATION-READINESS.md
```

Accepted release dependencies were not changed. Their verification pins are:

```text
76680350a380cba0dbeb78c213010bea42ea103a430e700286d937ed1379667b  migrations/add_mlc3_first_client_service_d2.sql
f82ba8b84319fd8798bfcbccaff63be4ae2cdae40fcac6625d685019ad258be2  migrations/add_mlc3_coach_inline_exercise_authoring_d5.sql
d579be497d7dd5910740a234c5d1a5edfb3b290b6fdbabc4d101378432403a38  routes/v2/mlc3_first_client_service.py
573525208d6d8b3f23618606aa14e1ffd9cdae62b2e64a96bd7d7ff3abb98453  routes/v2/mlc3_first_client_coach.py
b04b0456f5b5042daa7d794dbf91f304c4779d2e1aa073448bdf120abdacd230  routes/v2/coach.py
8b0c87fb8f56b0efa7bccd644f6c31229fa7c8f5cdf076339d6461dd84a4425c  routes/v2/coach_guidance_delivery.py
8691b219b2c2edc6d9ba2bc51199781302f38ea5799049f3948dd33c2cc7d9f9  services/mlc3_pilot_storage.py
af0adb6b901820d962f393388b4d642ddabff25a48940fb8f79823b7e26280c2  services/practice_attempt_orchestrator.py
3631db39d6b949cee6420bd846d912ef6409fd04e74a51ec654a75658b99a20f  services/first_client_repository.py
```

Frontend release dependencies are unchanged:

```text
f18d2e661dcacc297072a47ac3d3d75b5b8996671b8168e50481e98dfed980ff  src/services/api/mlc3FirstClient.ts
e69e0a624a9dc0670df57d31d7bbdf41bece03be96ecb8b797fd3857da6032fd  src/services/api/coachGuidanceDelivery.ts
ef50ee4adc504b33f5a6146992d69fb5f1a682dac3842d3faca465f2695ce8f5  src/services/api/stateRatings.ts
f20b9a2b5601843a715ce482d447847d6d15415804586404b1e7fe4211c5c3cb  src/components/willab/Mlc3FirstClientPractice.tsx
9d7b565e870663084e7abf39c1d0f5e5bcfd700456258beb16cbd1aed039bcf8  src/components/willab/CoachGuidanceComposer.tsx
d97966e449480cdc8ebcd0099360a9adc4bcaea801075e57f06d53eef733b08f  src/components/willab/CoachInlineBlindExposureBoundary.tsx
56bd0440ae1624b12f18c13f1739816f3136ba72926fe5b8362751cef4ecfeb1  src/components/willab/usePracticeFlow.ts
d147ee7381007082356091d76b35869ffe5441057755298f0abf6a00435ac2cb  src/components/willab/CoachInlineBlindExposureBoundary.test.tsx
```

## Executable evidence

- D2 PostgreSQL rehearsal on an isolated disabled clone: **73 passed**.
- D5 PostgreSQL rehearsal on a separate isolated disabled clone: **12 passed**.
- Focused backend route/service/readiness/monitor suite: **107 passed**.
- Readiness and monitor contract suite after release numbering: **33 passed**.
- Adversarial readiness PostgreSQL suite: **9 passed** against the numbered
  release snapshot. Exact-overload,
  service/client execution grants, direct table writes, RLS, internal helpers
  (including both newly closed lower-level writers), and disabled-purpose
  probes all fail closed.
- Migration 0325 applied and reapplied on the disposable populated database;
  both lower-level `service_role` EXECUTE checks returned false after each run.
- Exact local CI mirror: **5,022 passed, 328 skipped, 113 subtests passed**;
  migration runner, Ruff and mypy all passed.
- Migration manifest verification: **325 migrations, 0001–0325; OK**.
- Frontend focused D2/D5/render/practice suite under Node 24: **25 passed**.
- Frontend complete suite: **1,531 passed**.
- TypeScript, BFF, Ruff, mypy and diff checks passed. Frontend lint completed
  with four pre-existing hook warnings and no errors.
- The aggregate readiness SQL compiled and executed against a
  dependency-complete disposable schema. Synthetic unknown identities failed
  closed with typed blockers.
- The recurring aggregate monitor SQL compiled against the same schema without
  reading audio, transcript or passage content. Its external alert path was
  not invoked locally; a received production rehearsal receipt remains an
  explicit activation blocker.

The broad backend command must target `tests/`: repository-root collection
also imports the standalone manual `test_sentry.py`, which intentionally exits
when `SENTRY_DSN` is absent. The supported test directory completed cleanly.

## Remaining operational evidence (activation blockers, not code defects)

The following evidence is deliberately not guessed or copied from browser
state:

1. the founder's exact production `acquisition_principal_id`;
2. the exact production coach email/principal mapping;
3. a fresh synthetic write/read/SHA-256/delete manifest for both exact private
   production R2 buckets;
4. a fresh, release-operator-signed Railway/Vercel API-derived deployment
   attestation covering the exact web, worker and monitor inventory and the
   exact frontend build;
5. a verified synthetic Sentry/operations alert from the registered aggregate
   monitor covering D2/D5 failures and unresolved media recovery;
6. an idempotent emergency-disable rehearsal verifying the database contract,
   both backend gates and both frontend gates disabled;
7. the SELECT-only readiness report against production while all gates remain
   disabled.
8. independent release review, production deployment and verification of
   security-closure migration 0325, including absence of service-role
   execution on both lower-level writers.

Until these eight items are supplied and reviewed, the canary is **not ready to
activate**. No user recording or case material is needed for the R2 rehearsal.

## Required review conclusions

ML/data should verify that the checker cannot reinterpret product evidence as
labels or dataset eligibility, that pooled authorization remains independent,
and that the exact principal/authorization/deletion boundary is fail-closed.

Engineering should verify migration 0325 ordering, exact signature revocation,
apply/reapply and terminal PostgREST reload; SELECT-only behavior, exact
schema/RLS/RPC checks, configuration and R2 prerequisites, deterministic exit
status; and that the operator must perform a separately authorized four-gate
activation after both reviews.

No commit, push, deployment, production mutation, gate activation, real
collection, dataset creation, training, evaluation or promotion is authorized
by this packet.
