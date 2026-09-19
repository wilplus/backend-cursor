# MLC-3 general availability — activation runbook

Founder decision, 2026-09-20: **"All generally available."**

This is the procedure for moving `mlc3_service_rollout_revisions` from its
seeded `disabled` state to `generally_available`. It is written from
`_activate_ga` in `tests/test_mlc3_general_user_service_d4_postgres.py`,
which performs exactly this sequence against a rehearsal cluster and is
green in the `d4` lane — the steps below are the production translation of
a path that already executes, not a first draft.

---

## What this unblocks, and what it does not

It does **not** unblock bookmarks. #574 decoupled those: Feedback serves
whether or not this rollout is active, because the bookmark is F1 and the
audit lineage is F2 (R12). If bookmarks are missing, this is not the cause
and this runbook is not the fix.

What it unblocks:

| | |
|---|---|
| Confident Voice **lineage** | an owner answer becomes a canonical MLC-3 judgment instead of only a self-report |
| **Exercise** context | `prepare_feedback_v3_service_context` stops returning nothing |
| Coach review + Album | the paths that need a frozen membership |

## What it opens

`generally_available` serves the MLC-3 service to **every principal** —
there is no per-principal gate above it (`principal_is_allowlisted` is
`runtime_is_enabled() and principal_id`). The two purposes it requires
operational are `personalized_exercise_recommendation` and `coach_review`.

The `explicit_cohort` state exists in the schema and is honoured by the
resolvers, but **D4 ships no function that writes it** — GA is the only
forward path the released code provides. Skipping the cohort step is an
anticipated decision, which is why the risk decision's `decision_kind` is
literally `founder_skip_cohort_v1` and why it demands a written
`absent_cohort_reason`. Put the real reason there; it is the record.

> This is a consent and disclosure decision, not an engineering one. The
> counsel position on people other than the founder recording is the
> founder's to hold. Nothing in this document substitutes for it.

---

## Before you start

**Connection.** Both functions are `REVOKE ALL … FROM PUBLIC, anon,
authenticated, service_role`. They are unreachable from the app, from the
Supabase client, and from the service key. Run them over a **direct psql
connection as the database owner**. If a call returns "permission denied",
the connection is wrong, not the arguments.

**Isolation.** `register_mlc3_general_rollout_v2` refuses unless
`transaction_isolation` is `read committed` (psql's default — do not set
`SERIALIZABLE` in the session).

**Readiness report** (SELECT-only, safe to run any time):

```bash
python3 scripts/check_mlc3_general_service_readiness.py \
  --deployment-attestation <path to your signed attestation> \
  --r2-manifest <path to the R2 smoke manifest> \
  --backend-commit <40-char sha> \
  --frontend-commit <40-char sha>
```

The attestation must verify against
`config/mlc3_founder_attestation_public_key.pem` under the trusted issuer
and key id. Only the founder can produce it.

---

## Step 1 — the service contract must be active

```sql
SELECT contract_version, state, active_from, retired_at
  FROM mlc3_service_contracts
 WHERE contract_version = 'mlc3-first-client-service-v1';
```

`state` must be `active`, `active_from` in the past, `retired_at` NULL.

## Step 2 — both purposes operational

`register_mlc3_general_rollout_v2` raises `MLC3_GA_POLICY_NOT_OPERATIONAL`
unless the policy you name carries **both** purposes, each `operational`
and `authorizes_processing` in the registry. A policy that merely
references them is not enough. **This is the step most likely to stop a
production run.**

```sql
SELECT p.id AS policy_id, r.id AS purpose_id,
       r.operational, r.authorizes_processing
  FROM processing_policy_versions p
  LEFT JOIN processing_policy_purposes pp ON pp.policy_id = p.id
  LEFT JOIN processing_purpose_registry r ON r.id = pp.purpose_id
 WHERE p.status = 'active'
   AND p.activated_at <= clock_timestamp()
   AND (p.retired_at IS NULL OR p.retired_at > clock_timestamp())
   AND r.id IN ('personalized_exercise_recommendation', 'coach_review');
```

You need two rows for one `policy_id`, both `true`/`true`. That
`policy_id` is the `p_required_policy_id` in step 4.

## Step 3 — record the risk decision

```sql
SELECT * FROM register_mlc3_activation_risk_decision_v1(
  '4ee8cc5f1dda8cf5e727fefdaef12a1a96a85d9fcd01c74e8953564026bf1085',
  '<production backend commit, exactly 40 hex chars>',
  '<production frontend commit, exactly 40 hex chars>',
  '<why the cohort step is being skipped — a real sentence>',
  '<capacity policy sha256 — see below>',
  '<founder user_id from owner_principals>',
  clock_timestamp(),
  '<signature identity>',
  '<evidence sha256, 64 hex chars>'
);
```

The capacity hash must be computed from the **same** JSON you pass in step
4, or step 4 finds no accepted decision:

```sql
SELECT exercise_json_sha256_v1('<capacity policy json>'::jsonb);
```

The default capacity policy is in the D4 seed row; reuse it unless you
mean to change it.

`p_founder_user_id` must match an `owner_principals` row with
`guest_secret_hash IS NULL`, else `MLC3_GA_FOUNDER_IDENTITY_INVALID`.

**Re-running step 3 with the same `evidence_sha256` is safe** — it returns
the existing decision. Re-running it with the same evidence but *different
facts* raises `MLC3_GA_RISK_DECISION_REPLAY_CONFLICT`, deliberately.

## Step 4 — activate

```sql
SELECT * FROM register_mlc3_general_rollout_v2(
  '<policy_id from step 2>',
  '<risk decision id from step 3>',
  '<capacity policy json>'::jsonb,
  '<policy_versions json>'::jsonb,
  '<founder user_id>',
  clock_timestamp(),
  '<authorization evidence sha256, 64 hex chars>'
);
```

`p_policy_versions` replaces the seed's six `review-required` entries. Put
the real reviewed versions there — that object is the record of what was
reviewed for language, safety, rights, retention, deletion and media.

## Step 5 — verify

```sql
SELECT revision_number, rollout_state, cohort_set_id, effective_at
  FROM mlc3_service_rollout_revisions
 ORDER BY revision_number DESC LIMIT 1;
```

Expect `generally_available`, `cohort_set_id` NULL (GA carries no cohort
by construction), `effective_at` in the past.

Then record a take and read the backend log:

- `first_client: serving without lineage` — should now be **absent**
- `v3 stood down` — should be **absent**
- `MLC-3 rollout enrollment failed` — should be **absent**

---

## Rollback

```sql
SELECT * FROM halt_mlc3_service_rollout_v1('<reason>', '<evidence sha256>');
```

This writes a new `halted` revision. Serving stops immediately; nothing is
deleted. `halted` is also a valid predecessor for a later activation, so a
halt does not burn the path.

## Known refusals

| exception | meaning |
|---|---|
| `MLC3_GA_RISK_DECISION_INVALID` | a format rule in step 3: design sha wrong, a commit not 40 hex, a hash not 64 hex, an empty reason or identity, or `decided_at` in the future |
| `MLC3_GA_FOUNDER_IDENTITY_INVALID` | `p_founder_user_id` is not a non-guest owner principal |
| `MLC3_GA_RISK_DECISION_REPLAY_CONFLICT` | same evidence sha, different facts |
| `MLC3_GA_ACTIVATION_REQUEST_INVALID` | the newest revision is not `disabled`/`halted` (already activated?), or a malformed argument in step 4 |
| `MLC3_GA_POLICY_NOT_OPERATIONAL` | step 2 not satisfied |
| `MLC3_SERVICE_REQUIRES_READ_COMMITTED` | the session isolation level was changed |
| `no rows returned by SELECT INTO STRICT` | the risk decision id does not match an accepted `founder_skip_cohort_v1` row whose capacity hash equals step 4's |
