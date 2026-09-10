# MLC-3 General-User Service D4 — Production-Shape Release Correction

Status: `RELEASE_RE_REVIEW_REQUESTED`

Design authority: `MLC-3 General-User Service Rollout D4`, SHA-256
`4ee8cc5f1dda8cf5e727fefdaef12a1a96a85d9fcd01c74e8953564026bf1085`.

This packet supersedes release packet
`2999634a29e6fc9868bcc3eb6746f1d6a01224d67afd33f420d5367b0c471bac`
only for the production-shape upload-reservation correction described below.
No serving, collection, dataset, training, evaluation, or promotion gate is
enabled or changed.

## Production failure and rollback

Backend PR #487 merged as production commit
`e05ecb6a3b66461822a535b70a51ce00386dbad5`. Railway pre-deploy stopped at
migration 0326 with:

```text
MLC3_RUNTIME_FUNCTION_MISSING:
public.reserve_exercise_practice_service_upload_v1(
  uuid,uuid,integer,uuid,text,bigint,text,text,text,integer
)
```

The migration runner rolled back migration 0326. Zero earlier migrations were
applied in that run, the prior healthy deployment remained active, and the
frontend release was not merged. A disposable negative control using the
original released SQL reproduced the same failure and then proved:

- `mlc3_service_rollout_revisions` did not exist;
- `reserve_exercise_practice_service_upload_v2(...)` did not exist;
- zero rollout-lineage columns remained.

No partial D4 schema, product record, exposure, dataset, or learning record was
committed.

## Root cause and correction

Numbered migration 0323 defines the authoritative production function as:

```text
reserve_exercise_practice_service_upload_v1(
  uuid,uuid,uuid,text,bigint,text,text,text,integer
)
```

That V1 function already allocates `attempt_index` in the database under its
practice-session and idempotency locks and validates exact replay identity. The
old D4 rehearsal template had manually restored a nonexistent 10-argument
variant, hiding the release mismatch.

Corrected 0326 now:

- requires and rewrites the exact released 9-argument V1 overload;
- never restores or calls the nonexistent 10-argument overload;
- exposes the reviewed 9-argument V2 runtime wrapper;
- delegates allocation and immutable replay validation to authoritative V1;
- revokes runtime access to V1 and grants only V2 to `service_role`;
- registers the exact released V1 overload as forbidden in readiness checks.

The D4 business semantics, same-speaker safeguards, provenance, RLS, deletion,
capacity, product-only exclusions, and disabled learning boundaries are
otherwise unchanged.

## Frozen checksums

```text
4e5663adbed0ffe0396fd5840f1fbc0ca2149ef3697ec429e0adf44d0b0d97c1  migrations/add_mlc3_general_user_service_d4.sql
76680350a380cba0dbeb78c213010bea42ea103a430e700286d937ed1379667b  migrations/add_mlc3_first_client_service_d2.sql
2e16bdbcbf1023504e9109e39c80c8db610bf83afb034af1e162428f8b4d7895  migrations/add_mlc3_founder_canary_security_closure.sql
fc1ef4e61a8ff7ebb375ec0458f964ca8669d9d63e9611ea8612302605fa1c06  migrations/manifest.txt
754e84a1997264e281249730105848ffe292c13fffd2cb8b3f345bf1b8a311c0  scripts/check_mlc3_general_service_readiness.py
be741d6e3494f5c2654e7bba036d266b8f469dcd58cfeda61bb72456e55e61e5  tests/test_mlc3_general_service_readiness.py
1e9261447cf7e0738a36b8ab7a3fb108cd7869abb0e183e5494c94cd25c63e43  tests/test_mlc3_general_user_service_d4.py
c91f72ffa452bb38764db725ba6a569203a507a5892135f0ab7ce53426bdde7b  tests/test_mlc3_general_user_service_d4_postgres.py
5a4330f1f327fc46be8e574b05eba839a09610acd2b0089eecad5f04810cf994  docs/MLC3-GENERAL-USER-SERVICE-D4-RELEASE.md
```

The manifest remains contiguous at 326 migrations (`0001–0326`) and retains
0325 immediately before terminal 0326.

## Verification against the corrected snapshot

- Production-shape 0325 → corrected 0326 apply: passed.
- Corrected 0326 reapply: passed.
- D4 adversarial/concurrency/PostgreSQL suite: **33 passed**.
- Focused D4/readiness/static suite: **49 passed**.
- Backend CI mirror: **5,047 passed, 361 skipped, 113 subtests**.
- Migration runner: **66 passed**; manifest, Ruff and mypy passed.
- Permission probe: released V1 exists but is not executable by
  `service_role`; V2 is executable by `service_role`; the obsolete overload is
  absent.
- RLS probe: all **11/11** D4 tables have RLS and forced RLS.
- Seeded rollout remains `disabled`, `serves_user=false`,
  `dataset_eligible=false`.
- Exact original-SQL negative control failed on the released 9-argument shape
  and left zero partial D4 objects.

## Release re-review request

> **ML/DATA AND ENGINEERING RELEASE RE-REVIEW REQUEST — D4 migration 0326
> production-shape correction**
>
> Review this checksum-pinned correction. Verify the exact released
> 9-argument V1 upload-reservation identity, database-allocated attempt order,
> V2 delegation, obsolete-overload closure, production-shape apply/reapply,
> atomic rollback negative control, permissions, RLS, and unchanged disabled
> product/data/learning gates.
>
> No activation, real collection, dataset creation, training, evaluation, or
> promotion is authorized.
