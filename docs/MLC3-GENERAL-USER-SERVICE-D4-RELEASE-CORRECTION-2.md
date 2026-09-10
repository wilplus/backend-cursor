# MLC-3 General-User Service D4 — Offer Resolver-Chain Correction

Status: `RELEASE_RE_REVIEW_REQUESTED`

Design authority: `MLC-3 General-User Service Rollout D4`, SHA-256
`4ee8cc5f1dda8cf5e727fefdaef12a1a96a85d9fcd01c74e8953564026bf1085`.

This packet supersedes correction packet
`72be4057b4294da8442b9b67f03dc0821e67ced0bdee022ddba2780adaed6d54`
only for the exact production offer-resolver chain described below. No
serving, collection, dataset, training, evaluation, or promotion gate is
enabled or changed.

## Second production failure and rollback

Backend PR #488 merged as production commit
`6cec542b933b5f4e7e26a4b1cb38c9a31e330080`. Railway pre-deploy stopped at
migration 0326 with:

```text
MLC3_RUNTIME_RESOLVER_CUTOVER_CONFLICT:
public.record_exercise_offer_service_event_v1(
  uuid,uuid,uuid,text,uuid,text,jsonb,timestamptz,text
)
```

Migration 0326 rolled back atomically. The prior healthy backend remained
active, the frontend release stayed unmerged, and every product/data/learning
gate remained disabled. The exact prior SQL reproduced the failure on a
production-shaped disposable database and left:

- zero of the eleven D4 tables;
- zero rollout-lineage columns on representative runtime tables;
- no `require_mlc3_service_access_v2(...)` function;
- the original offer-live resolver definition intact.

## Root cause and correction

The released offer event writer obtains authority transitively:

```text
record_exercise_offer_service_event_v1
  -> require_exercise_service_offer_live_v1
  -> require_mlc3_service_principal_v1
```

The prior correction incorrectly required the event writer itself to contain a
direct resolver call. The corrected migration now:

- rewrites `require_exercise_service_offer_live_v1(uuid,uuid)` to the reviewed
  rollout-aware `require_mlc3_service_access_v2` boundary;
- retains `record_exercise_offer_service_event_v1(...)` in the exact
  operation-mode cutover registry without fabricating a redundant direct
  resolver call;
- explicitly verifies the complete transitive chain after cutover;
- fails with `MLC3_OFFER_RESOLVER_CHAIN_CONFLICT` if the event bypasses the
  live guard, still calls the historical resolver directly, or if the live
  guard does not use the V2 resolver;
- includes the live guard in the production-complete 40-function
  operation-mode inventory.

The D4 business semantics, same-speaker safeguards, authorization, provenance,
RLS/RPC-only controls, deletion, capacity, product-only exclusions, and
disabled learning boundaries are unchanged.

## Frozen checksums

```text
3ed059ac08c705ddcaa1bfa6adce528ba08126109e44a5d6972cc25dba17ec5c  migrations/add_mlc3_general_user_service_d4.sql
76680350a380cba0dbeb78c213010bea42ea103a430e700286d937ed1379667b  migrations/add_mlc3_first_client_service_d2.sql
2e16bdbcbf1023504e9109e39c80c8db610bf83afb034af1e162428f8b4d7895  migrations/add_mlc3_founder_canary_security_closure.sql
fc1ef4e61a8ff7ebb375ec0458f964ca8669d9d63e9611ea8612302605fa1c06  migrations/manifest.txt
754e84a1997264e281249730105848ffe292c13fffd2cb8b3f345bf1b8a311c0  scripts/check_mlc3_general_service_readiness.py
be741d6e3494f5c2654e7bba036d266b8f469dcd58cfeda61bb72456e55e61e5  tests/test_mlc3_general_service_readiness.py
4ebe8c6ecf81dff61ff74440bfd6e7f9423e835995614acaa757430a12bd9e10  tests/test_mlc3_general_user_service_d4.py
b97e63bfe63d377ba3d0b56128ef0c37b9dacf873791a7bfbf2b1abf1b8837dc  tests/test_mlc3_general_user_service_d4_postgres.py
5a4330f1f327fc46be8e574b05eba839a09610acd2b0089eecad5f04810cf994  docs/MLC3-GENERAL-USER-SERVICE-D4-RELEASE.md
ffaed9ca6d4a6175f360e7796f9f2f16904d073e7efe43fd41501e907ce7344d  docs/MLC3-GENERAL-USER-SERVICE-D4-RELEASE-CORRECTION.md
```

The manifest remains contiguous at 326 migrations (`0001–0326`) with 0325
immediately before terminal 0326.

## Verification against this exact correction

- Production inventory: all **40** operation-mode functions and all **14**
  historical-resolver references were accounted for before cutover.
- Prior-SQL negative control: reproduced the exact second Railway error and
  left zero partial D4 schema.
- Bypassing-event negative control: rejected with
  `MLC3_OFFER_RESOLVER_CHAIN_CONFLICT` and left zero partial D4 schema.
- Production-shaped 0325 → corrected 0326 apply: passed.
- Corrected 0326 reapply: passed.
- D4 adversarial/concurrency/PostgreSQL suite: **34 passed**.
- Focused D4/readiness/static suite: **22 passed**.
- Backend CI mirror: **5,048 passed, 362 skipped, 113 subtests**.
- Migration runner: **66 passed**; manifest, Ruff and mypy passed.
- Frontend remains unmerged; all backend/frontend runtime and learning gates
  remain disabled.

## Release re-review request

> **ML/DATA AND ENGINEERING RELEASE RE-REVIEW REQUEST — D4 migration 0326
> production offer-resolver-chain correction**
>
> Review this checksum-pinned correction. Verify the exact production
> `event -> live guard -> rollout-aware resolver` chain, the complete runtime
> inventories, production-shaped apply/reapply, bypass and prior-SQL negative
> controls, atomic rollback, permissions, RLS, and unchanged disabled
> product/data/learning gates.
>
> No activation, real collection, dataset creation, training, evaluation, or
> promotion is authorized.

```text
VERDICT:  ADVANCE-F2
CATEGORY: F2
WHY:      The correction binds the released offer-event path to the reviewed
          rollout resolver without changing service or learning semantics.
REDIRECT: Complete independent release re-review before any deployment retry;
          keep every gate disabled.
```
