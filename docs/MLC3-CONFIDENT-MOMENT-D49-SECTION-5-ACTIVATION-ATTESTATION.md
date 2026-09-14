# D49 §5 — activation attestation (taken 2026-09-14)

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
