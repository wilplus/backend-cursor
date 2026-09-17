# Why the accepted terms version has been stuck at 1.0 since July

**Investigation only. No behaviour was changed** — bumping the version or
"fixing" the prompt would mass-trigger re-acceptance across 67 accounts against
copy that is still unsigned, which is a live-loop event.

Production, 2026-09-17: 67 accounts · 26 with a consent row · `terms_version`
is `'1.0'` and nothing else · first 2026-05-08, last 2026-07-16.

---

## The finding, in one line

**The re-prompt cannot fire, because nothing in the frontend asks for it.**

The backend computes the signal correctly. It has no consumer.

## (b) Does an out-of-date user get re-prompted? — **No**

Traced end to end:

1. `routes/v2/user_account.py:211` calls `db.get_user_consent_state(user_id,
   current_terms_version=config.CURRENT_TERMS_VERSION)`.
2. `services/db.py::get_user_consent_state` queries `user_consents` filtered
   `.eq("terms_version", current_terms_version)`. A user whose stored row says
   `1.0` does not match `1.2`, so `terms_row` is `None` and `terms_consent`
   comes back **`False`** — which is correct, and is exactly the signal a
   re-prompt would need.
3. Its docstring says *"Frontend reads this to skip the 'ask anything'
   prompt."*
4. **The frontend does not read it.** There is no caller of `/v2/user/consent`
   anywhere in `src/`, and no reference to `terms_consent` or
   `terms_version_current`. The only consent surfaces are the separate MLC-2
   flow (`mlc2Consent.ts`) and the Phase-1 client added this week, neither of
   which touches `user_consents`.

So the mechanism is not broken in the sense of computing the wrong answer. It
computes the right answer and nobody listens. **That distinction matters for
the fix:** there is no bug to repair in `get_user_consent_state`; there is a
surface that was never built.

## (c) Two sources of truth — and they feed different paths

| | Value | Reads env? | Used by |
|---|---|---|---|
| `routes/auth.py:17` | `CURRENT_TERMS_VERSION = "1.2"` | **No — hardcoded** | **Signup.** Written to `user_consents.terms_version` (line 139) and to `user_metadata` (line 111) |
| `config.py:218` | `os.getenv("CURRENT_TERMS_VERSION", "1.2")` | Yes | **The status check** at `user_account.py:211` |

They agree today only because both literals read `1.2`. If the environment
variable were ever set to anything else, **a user who signs up is written at the
hardcoded value and then immediately evaluated against a different one** — newly
registered and already non-consenting, with no surface to tell them. The env
var's own comment says it exists so "behavior shifts without a redeploy", which
is precisely the case where the two diverge.

This is worth collapsing to one source before either value is next changed. It
is not the cause of the stuck version.

## (a) and (d) — not answerable from the repository

- **(a)** Whether `CURRENT_TERMS_VERSION` is actually `1.2` on each service
  requires the boot log of web, worker and every cron service. It is
  env-overridable per service. **Note:** the value is read at import time into a
  module-level constant, and nothing logs it at boot, so a grep will return
  nothing whether it is set or not. Absence of a log line is not evidence of
  absence of an override.
- **(d)** Whether anyone has signed up since 16 July needs the database:

  ```sql
  SELECT COUNT(*) AS signed_up_since_last_consent
    FROM auth.users u
   WHERE u.created_at > '2026-07-16'
     AND NOT EXISTS (SELECT 1 FROM user_consents c WHERE c.user_id = u.id);
  ```

  The answer changes what this is. **Rows returned** → users have been created
  with no consent record at all, and the gap is live. **Zero** → the mechanism
  is untested rather than broken, which is a smaller problem with a different
  fix. Either way the 41-account gap between 67 accounts and 26 consent rows
  needs its own explanation.

## What this does NOT establish

That v1.0 is the accepted text. **It is not** — see
`legal/phase1-2026.1/accepted-versions/README.md`. Every acceptance predates the
v1.0 commit; the document those 26 people agreed to is the 2026-05-07 text,
which its own source marks as placeholder copy.

## Recommended order, when a fix is authorised

1. Answer (a) and (d) first. A fix aimed at the wrong one of those two is worse
   than no fix.
2. Collapse the two `CURRENT_TERMS_VERSION` definitions to one.
3. Only then decide whether to build a re-prompt surface — and against which
   copy, since nothing published since May has founder sign-off.

**Do not backfill consent rows.** A consent record created by us rather than by
a user is worse than a missing one.
