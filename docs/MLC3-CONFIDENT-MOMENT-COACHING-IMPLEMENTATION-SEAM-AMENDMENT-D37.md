# MLC-3 Confident Moment Coaching Bundle — Scanner Identity Amendment D37

Status: proposed exact scanner-identity closure; executable work remains
blocked pending independent ML/data and Engineering confirmation.

## 1. Parent and sole correction

D37 binds and narrowly supersedes D36, SHA-256
`06bfb0502b55a27c9c59c5833e2f3c885fd251e975e5424ce22ccc1176fadf66`.
All D36/D35 and accepted-parent behavior remains unchanged except that the
scanner rename, exact signature and retirement boundary are now explicit.

## 2. Exact current scanner

The sole current scanner is:

```text
public.scan_due_feedback_language_delivery_jobs_v1(
  uuid,text,integer,integer,integer
)
```

Its named arguments are, in order:

```text
p_run_id uuid
p_worker_id_sha256 text
p_limit integer — must equal literal 3
p_lease_seconds integer
p_server_budget_ms integer
```

It implements D36's one index-only LIMIT-3 identity window followed by at
most those three ordered exact-primary-key NOWAIT attempts. The application
caller is exactly:

```text
services/confident_moment_delivery_worker.py::
  sweep_due_confident_moment_deliveries
  -> scan_due_feedback_language_delivery_jobs_v1(uuid,text,integer,integer,integer)
```

No other production caller is permitted.

## 3. Retired scanner

D35 intentionally renames and supersedes:

```text
public.claim_due_feedback_language_delivery_jobs_v1(
  uuid,text,integer,integer,integer
)
```

The migration drops that exact overload after installing and verifying the
new scanner. It must not recreate, call, delegate to or retain a grant on the
retired overload. Apply/reapply and the static caller/RPC registry require
`to_regprocedure(...) is null` for the retired signature and exact
service-role-only EXECUTE on the current signature. `PUBLIC`, `anon` and
`authenticated` cannot execute either identity.

Tests reject a lingering retired function/grant, a three- or four-argument
overload, a different argument order, any unregistered caller, or any current
scanner that does not implement D36's fixed window. Negative failure rolls the
rename/permission change back atomically.

No product meaning, response, lock, authorization, deletion, monitoring,
dataset, learning-surface or disabled-gate contract changes.

`VERDICT: D37 PROPOSED FOR ML/DATA AND ENGINEERING CONFIRMATION; EXECUTABLE WORK BLOCKED`
