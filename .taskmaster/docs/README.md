# Taskmaster — only source of truth

**APP_DESCRIPTION.md** in this folder is the **only** source of truth for the Homework / Speaking Coach app. All behavior, contracts, and implementation guidance live here. No other description or how-to docs; only `.taskmaster/docs/` and code (`migrations/`, `docs/homework-bff-routes/`) remain.

## Index

| File | Purpose |
|------|---------|
| **APP_DESCRIPTION.md** | Full app spec: flow, status, APIs, scoring, wheel, storage, DB, what’s missing. Read this first. |
| **schema.sql** | Single DB schema file; update in place only. Run in Supabase SQL Editor. |
| **AUDIT-AND-BFF-GLOW.md** | Frontend audit checklist (status→step, mapping, refetch, recording contract), BFF rationale, glow removal. **§4** = copy-paste prompt to run in the frontend repo for a line-level punch-list. |
| **WHEEL-USE-BFF-URL.md** | Wheel = client-side only (AnalyserNode, real-time loudness/pace). No glow, no recording-metrics-chunk. |

**BFF reference:** `docs/homework-bff-routes/` — start, status, recording-upload-url, recording-1, recording-2, metric-answers, questions, post-answers, task-block, warm-up-task. Copy into frontend app; no recording-metrics-chunk (no glow).
