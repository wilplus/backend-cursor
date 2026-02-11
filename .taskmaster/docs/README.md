# Taskmaster — only source of truth

**APP_DESCRIPTION.md** in this folder is the **only** source of truth for the Homework / Speaking Coach app. All behavior, contracts, and implementation guidance live here. No other description or how-to docs; only `.taskmaster/docs/` and code (`migrations/`, `docs/homework-bff-routes/`) remain.

## Index

| File | Purpose |
|------|---------|
| **APP_DESCRIPTION.md** | Full app spec: flow, status, APIs, scoring, wheel, storage, DB, what’s missing. Read this first. |
| **FLOW-AND-CHANGES.md** | What changed (post-answers recovery, finish without post-questions, 409 hint, recording-2 tolerance, no-op BFF chunk) and explicit backend flow. |
| **schema.sql** | V2-only DB schema (recordings, admin_users, v2_*). Single source of truth; run in Supabase SQL Editor. |
| **AUDIT-AND-BFF-GLOW.md** | Frontend audit checklist (status→step, mapping, refetch, recording contract), BFF rationale, glow removal. **§4** = copy-paste prompt to run in the frontend repo for a line-level punch-list. |
| **WHEEL-USE-BFF-URL.md** | Wheel = client-side only (AnalyserNode, real-time loudness/pace). No glow, no recording-metrics-chunk. |
| **SCHEMA-V1-DROP-OPTIONAL.sql** | Migration for existing DBs: drop v1 tables (run after backup). New installs use schema.sql only. |

**BFF reference:** `docs/homework-bff-routes/` — start, status, recording-upload-url, recording-1, recording-2, metric-answers, questions, post-answers, task-block, warm-up-task. Copy into frontend app; backend has no recording-metrics-chunk; BFF may add no-op 204 route for legacy clients (see FLOW-AND-CHANGES.md).
