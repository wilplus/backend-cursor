# Rehearsal tier — recipes for the three pending lanes

Date: 2026-09-14. Every result below was produced by execution on a disposable
PostgreSQL 16.13 cluster built by `scripts/rehearsal_tier.sh --build-only`,
python 3.12.3, `requirements.txt` + pytest 9.1.1.

| Lane | `docs/REHEARSAL-TIER.md` best known | This document | Status |
| --- | --- | --- | --- |
| `test_mlc3_founder_canary_readiness_postgres.py` | 8/9 | **9/9** | **closed** |
| `test_mlc3_general_user_service_d4_postgres.py` | 24/34 | **34/34** | **closed** |
| `test_mlc3_coach_inline_authoring_d5_postgres.py` | 11/12 | 11/12 | one open assertion, now located |

## Shared mechanics

A checkpoint is the checked-in recipe `tests/integration/confident_moment_rehearsal.sh`
stopped after a named migration:

```bash
awk -v stop="add_mlc3_founder_canary_security_closure.sql" \
    '{print} ($1=="hard" && index($0,stop)>0){print "exit 0"}' \
    tests/integration/confident_moment_rehearsal.sh > tests/integration/_ckpt.sh
bash tests/integration/_ckpt.sh released willab_confident_moment_ckpt0325
```

Three mechanics cost time to discover; they are not optional:

1. **Export `CONFIDENT_MOMENT_PGHOST` / `_PGPORT` / `_PGUSER`.** The builder sets
   `PGHOST` itself, defaulting to `127.0.0.1`. Against the socket-only rehearsal
   cluster every connection then fails and the script reports
   `(database already exists; reusing)` followed by `FAILED add_coach_users_table.sql`
   — a misleading message for "cannot connect".
2. **The copy must live in `tests/integration/`.** The builder does
   `cd "$(dirname "$0")/../.."`; a copy in `/tmp` cd's to `/`.
3. **The builder refuses database names outside `willab_confident_moment_*`.**
   Build under that prefix, then `CREATE DATABASE <lane> TEMPLATE <checkpoint>`
   using the name each suite's fixture guard demands.

Two relaxations are shared by the D4 and D5 lanes:

```sql
ALTER TABLE public.ml_judgments ALTER COLUMN id SET DEFAULT gen_random_uuid();
```

```sql
-- generate, then run, the DISABLE statements (109 triggers in these lanes)
SELECT 'ALTER TABLE '||t.tgrelid::regclass||' DISABLE TRIGGER '||quote_ident(t.tgname)||';'
  FROM pg_trigger t JOIN pg_proc p ON p.oid=t.tgfoid
 WHERE NOT t.tgisinternal
   AND p.proname IN ('reject_mlc2_immutable_mutation',
                     'reject_phase1_immutable_mutation');
```

**Why disabling the append-only guards does not hollow out these suites:**
neither suite contains the strings `append-only`, `append_only` or `immutable`
— they assert nothing about immutability, so the guards are pure obstacles to
their fixture helpers, which were written against the narrow schema. The guards
themselves are exercised elsewhere. The repo already uses exactly this technique
in `_age_authorization_checks` (`tests/test_mlc3_first_client_service_postgres.py:77`).

## Lane 1 — founder canary readiness → 9/9

Checkpoint: **`released` lane, stopped after `add_mlc3_founder_canary_security_closure.sql`**
(0325; 27 migrations). Clone to `willab_d3_canary`; DSN `MLC3_CANARY_READINESS_REHEARSAL_DSN`.

One seed step, no relaxations:

```sql
UPDATE public.processing_purpose_registry
   SET operational=true, authorizes_processing=true,
       capability_version='rehearsal-capability-v1',
       reviewed_at=now(),
       retention_control_version='rehearsal-retention-v1',
       deletion_control_version='rehearsal-deletion-v1',
       rights_control_version='rehearsal-rights-v1'
 WHERE id IN ('personalized_exercise_recommendation','coach_review');
```

`required_operational_purpose_count`
(`scripts/check_mlc3_founder_canary_readiness.py:322`) counts exactly those two
ids `WHERE operational AND authorizes_processing`. The lane seeds all six
purposes false, so `test_disabled_required_purpose_fails_canonical_authority_readiness`
— which disables `coach_review` and expects the count to be 1 — can never move
off 0. The five extra columns are not decoration: CHECK
`processing_purpose_operational_invariant` requires `capability_version`,
`reviewed_at`, `retention_control_version`, `deletion_control_version` and
`rights_control_version` to be non-null whenever `authorizes_processing` is
true. Setting only the two booleans is rejected.

**Correction to `docs/REHEARSAL-TIER.md`.** That table attributes this failure to
the narrow lane dropping `processing_one_active_policy_idx`. That index is
present in the released lane and is not the cause; the purpose rows are.

**Do not run this lane on the full released chain (through 0326/0327).** It
reports 7/9 there, and the second failure is not a fixture problem:

- 0323 creates `reserve_exercise_practice_service_upload_v1(...)` and grants
  `EXECUTE` to `service_role`.
- 0326 supersedes it with `_v2`, grants `_v2` to `service_role`, and
  `REVOKE ALL ON FUNCTION ...upload_v1(...) FROM PUBLIC, anon, authenticated, service_role`.
  `_v2` calls `_v1` internally (`add_mlc3_general_user_service_d4.sql:2428`).
- `scripts/check_mlc3_founder_canary_readiness.py:90` still lists **v1** in
  `_REQUIRED_RPC_SIGNATURES`.

So from 0326 onward `missing_service_rpc_grant_count` is permanently 1 and
`test_missing_service_execute_and_client_execute_both_block` sees 2 where it
expects 1. The deliberate revocation is correct; the required-RPC list is stale
with respect to it. **That is a separate decision, not a lane recipe** — it
means the deployed canary readiness audit reports one false missing grant.

## Lane 2 — general-user service D4 → 34/34

Checkpoint: **`narrow` lane, stopped after `add_mlc3_general_user_service_d4.sql`**
(0326; 25 migrations). Clone to `willab_ga_template`; DSN
`MLC3_GENERAL_USER_REHEARSAL_DSN`. Apply both shared relaxations. Nothing else.

## Lane 3 — coach inline authoring D5 → 11/12

Checkpoint: **`narrow` lane, stopped after `add_mlc3_coach_inline_exercise_authoring_d5.sql`**
(0324; 23 migrations). Clone to `willab_d3_d5`; DSN `COACH_GUIDANCE_REHEARSAL_DSN`.
Apply both shared relaxations.

@0324 is the right checkpoint, confirmed by execution: the same suite on the
@0326 lane scores **5/12**, so it is not simply "further is better".

The `released` chain is the wrong lane for D5 for a different reason — its
shared fixture helpers were written against the narrow schema and fail on
production-shaped NOT NULL columns they never supply
(`projects.display_name`, then `v2_sessions.arc_id` / `user_id` / `take_index`,
and `v2_sessions.recording_1_id` has a real FK the helper does not satisfy).
Papering over those with defaults would make the lane less production-shaped,
not more.

**The one open failure is no longer a fixture error.** Setup now completes; the
suite fails on a real assertion:

```
test_no_match_and_ordinary_items_share_one_complete_visible_batch
tests/test_mlc3_coach_inline_authoring_d5_postgres.py:782
assert len(visible["items"]) == 2   # got 1
```

`prepare_coach_inline_blind_batch_v1` returns one item where the test expects
two — the exact no-match item plus the ordinary one. This is a behavioural
question about what belongs in a blind batch at this checkpoint, not a missing
column or a trigger. It is the last thing between this lane and 12/12.

This differs from the documented 11/12, which failed inside fixture setup on
`reject_mlc2_immutable_mutation`. Same count, different and much later failure.
