# D49 §5 — activation attestation (taken 2026-09-14, remediated and re-taken 2026-09-15)

> **STATUS: PASS.** The first reading (2026-09-14) FAILED at 8 s against a ~1 s
> client window. A PostgREST `db-pre-request` hook now bounds the three
> Confident Moment RPC paths to 500 ms, verified in production on 2026-09-15.
> The original FAIL reading is kept below unedited — it is the evidence the
> remediation answers. The re-take is in
> "[Re-take — 2026-09-15](#re-take--2026-09-15-pass)".

D49 §5 requires, before activation:

> Residual PostgreSQL execution after client give-up is explicitly bounded by
> the deployed database/PostgREST statement-timeout configuration and must be
> attested before activation. […] Activation attestation must record the
> deployed database/PostgREST statement timeout and prove the client's total
> bounded retry window exceeds it.

## VERDICT: **FAIL**

| field | value |
| --- | --- |
| effective `statement_timeout` on the RPC path | **8 s** |
| effective `lock_timeout` | **8 s** |
| effective `idle_in_transaction_session_timeout` | not set at role or database level |
| other role settings | `session_preload_libraries=safeupdate` |
| client bounded retry window | **1.00 s** correlation / **1.06 s** playback |
| required relation | server bound **<** client window |
| observed relation | server bound is **8×** the client window |
| verdict | **FAIL — activation is blocked** |
| taken by / date | artur@willonski.com, 2026-09-14 |
| database / project | willpowerlab, `main` (production). No credentials recorded. |

## How the 8 s was established

Read from `pg_db_role_setting`, which is catalog state and independent of the
session that reads it:

| role | `statement_timeout` |
| --- | --- |
| `anon` | 3 s |
| `authenticated` | 8 s |
| **`authenticator`** | **8 s** (with `lock_timeout=8s`) |
| `service_role` | *no setting* |
| database level | *no setting* (only `app.settings.jwt_exp=3600`) |

`service_role` carrying no setting does **not** mean the RPC path is unbounded,
and it does not mean it escapes 8 s. PostgREST logs in as `authenticator` and
then `SET ROLE`s to the JWT role. Executed on PostgreSQL 16:

```
at login as the login role (8s):          8s
after SET ROLE to a role with no setting: 8s
after SET ROLE to a role set to 200ms:    8s
```

**`SET ROLE` does not re-apply per-role `statement_timeout`.** The session keeps
the login role's value for its whole life. The effective bound on every
Confident Moment RPC is therefore `authenticator`'s 8 s.

> **⚠️ CORRECTION (2026-09-15) — the 8 s figure is right; this explanation of it
> was wrong.** Measured through PostgREST in production, the effective timeout
> tracks the **JWT role**, not the login role: `anon` reports **3 s**, which is
> `anon`'s own `pg_db_role_setting` value, not `authenticator`'s 8 s. So
> PostgREST applies the impersonated role's settings per request; it does not
> merely `SET ROLE` and inherit. The `SET ROLE` experiment above is a true
> result about raw PostgreSQL and a false model of this deployment.
>
> The recorded 8 s survives for a different reason than the one given: the
> Confident Moment RPCs are called as **`service_role`**, which carries no
> `statement_timeout` of its own, and `service_role` measured through PostgREST
> reports **8 s**. Both readings are in the re-take section below.
>
> This also softens the retraction further down. Giving the three RPCs a
> dedicated role with `ALTER ROLE … SET statement_timeout` is **not** inert as
> claimed — PostgREST would apply it. It remains the wrong remedy for a
> different reason: the calls arrive as `service_role`, so binding a dedicated
> role would mean issuing and plumbing a separate JWT for three RPCs. The
> pre-request hook needs no key changes and scopes by path.

## Why this is not a formality

A client timeout is a give-up, not a cancellation. Because phase-3
reacquisition is non-waiting, a backend statement that outlives the client's
give-up keeps holding the serializers it already acquired, and the client's own
bounded retries then fail against its own orphan. With an 8 s server bound and a
~1 s client window, a 409'd owner exhausts both attempts in about a second while
the orphaned transaction holds its serializers for up to eight — a dead-end
retry, landing on a real user.

## Remedy — what works, and what does not

**Retracted:** an earlier draft of this procedure proposed giving the three RPCs
a dedicated role with `ALTER ROLE <role> SET statement_timeout = '500ms'`. That
**cannot work**, for the reason established above: PostgREST reaches the role by
`SET ROLE`, which never re-reads per-role settings. The proposal was wrong and
is withdrawn.

Executed comparison, PostgreSQL 16, against a 2 s function body under an 8 s
session:

| mechanism | result |
| --- | --- |
| `SET ROLE` to a role with a tighter `statement_timeout` | **no effect** — stays 8 s |
| `ALTER FUNCTION f() SET statement_timeout='200ms'` | **no effect** — 2003.657 ms (control: 2003.444 ms) |
| in-function `set_config('statement_timeout', …, true)` on its own invocation | **no effect** — 1008 ms under a 200 ms setting |
| `SET LOCAL statement_timeout` in an earlier statement of the same transaction | **works** — cancelled at 200.610 ms |
| PostgREST `db-pre-request` hook, scoped by `request.path` | **works** — 501.633 ms on a matching path; 2003.558 ms elsewhere, untouched |

One fact explains the whole table: a statement timeout only arms for statements
that **begin** after it is set. Anything that changes it once the statement is
already running — a function-level `SET`, an in-body `set_config` — is too late
for that statement.

### The remedy to deploy

A `db-pre-request` hook runs as a separate, earlier statement in the same
transaction, so its setting arms the statement that follows, and it can scope
itself by request path so no other API traffic is tightened:

```sql
-- ⚠️ DO NOT COPY THIS PATTERN. It matches NONE of the real RPC names, which
-- begin resolve_/authorize_, not confident_moment. Deployed as written it
-- would fire on nothing and leave the 8 s bound in place, silently. The
-- literal path list that was actually deployed is in the re-take section.
CREATE FUNCTION public.pre_request() RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  IF current_setting('request.path', true) LIKE '/rpc/confident_moment%' THEN
    PERFORM set_config('statement_timeout', '500ms', true);
  END IF;
END $$;
```

Verified above: 501.633 ms on a matching path, and a non-matching path ran its
full 2003.558 ms unaffected. The alternative D49 §5 allows — raising the client
bound past 8 s — is cheaper to ship but makes the owner wait out the orphan
instead of removing it, which is not what §5 asks for.

## Scope

This attestation is an **activation** prerequisite, not a merge prerequisite.
Taking the reading activates nothing, and this document authorizes nothing. As
of this reading, activation is **blocked** until the server bound is brought
under the client window and the attestation is retaken.

The probe function used for the reading
(`public.zz_attest_effective_timeouts_v1`) is attestation-only. It must never
enter `migrations/` and must be dropped once the reading is taken.

---

# Re-take — 2026-09-15: **PASS**

## VERDICT: **PASS — activation is no longer blocked by D49 §5**

| field | value |
| --- | --- |
| effective `statement_timeout`, the three Confident Moment RPC paths | **500 ms** |
| effective `statement_timeout`, every other path (`service_role`) | 8 s |
| effective `statement_timeout`, every other path (`anon`) | 3 s |
| client bounded retry window | **1.00 s** correlation / **1.06 s** playback |
| required relation | server bound **<** client window |
| observed relation | 500 ms is **half** the client window |
| verdict | **PASS** |
| taken by / date | artur@willonski.com, 2026-09-15 |
| database / project | willpowerlab, `main` (production). No credentials recorded. |

## What was deployed

A PostgREST `db-pre-request` hook, bound to the login role so it is applied at
connection time, tightening `statement_timeout` for three request paths only:

```sql
CREATE OR REPLACE FUNCTION public.willab_pre_request() RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
  IF current_setting('request.path', true) IN (
       '/rpc/resolve_confident_moment_source_playback_authority_v1',
       '/rpc/authorize_confident_moment_source_playback_emit_v1',
       '/rpc/resolve_confident_moment_exercise_offer_v1') THEN
    PERFORM set_config('statement_timeout', '500ms', true);
  END IF;
END $$;

GRANT EXECUTE ON FUNCTION public.willab_pre_request()
  TO authenticator, service_role, anon, authenticated;

ALTER ROLE authenticator SET pgrst.db_pre_request = 'public.willab_pre_request';
NOTIFY pgrst, 'reload config';
```

500 ms is not arbitrary: it is the client's own `DATABASE_PHASE_BUDGET_SECONDS`.
A database phase that legitimately needed longer would already have been
abandoned by the client, so the server is bounded to exactly the budget the
client allows.

## Production evidence (executed through PostgREST, not psql)

A temporary probe, `public.zz_attest_effective_timeouts_v1()`, returning
`current_setting('statement_timeout')` and `current_user`, called over the real
API. It was **dropped after the reading** and never entered `migrations/`.

| # | condition | result |
| --- | --- | --- |
| 1 | probe path **in** the hook's list, called as `anon` | `{"role":"anon","statement_timeout":"500ms"}` |
| 2 | probe path **removed** from the list, called as `anon` | `{"role":"anon","statement_timeout":"3s"}` |
| 3 | probe path **not** in the list, called as `service_role` | `{"role":"service_role","statement_timeout":"8s"}` |

All three returned HTTP 200.

Reading 1 proves the hook **fires** on a matched path in production. Reading 2
is the same function, the same call, the same key, differing only in whether its
path is listed — so it proves the hook is **scoped** and leaves the rest of the
API untouched. Reading 3 records the unhooked baseline for the role the backend
actually uses, and is what keeps the original FAIL reading's 8 s figure standing.

Reading 2 also produced the correction recorded above: `3 s` is `anon`'s own
role setting, which the login-role inheritance model would not have predicted.

## Residual risk

The hook matches the three paths by **exact literal**. A rename, re-version or
re-route of any of

- `resolve_confident_moment_source_playback_authority_v1`
- `authorize_confident_moment_source_playback_emit_v1`
- `resolve_confident_moment_exercise_offer_v1`

silently removes that path from the bound and restores 8 s **with nothing
failing**. This is the one way this attestation goes stale without notice. A
drift test pinning these three names is the mitigation and is tracked
separately; until it exists, treat a rename of any of the three as requiring a
re-take of this attestation.

## Scope

Taking this reading activates nothing, and this document authorizes nothing.
D49 §5 is satisfied; activation remains a separate, explicit founder decision.
