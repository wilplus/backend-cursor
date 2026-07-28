# PROMPT — BE: `prior_edit` re-offer + re-apply telemetry (T1 · 1.2)

**For:** the backend agent/dev on `wilplus/backend-cursor`. Run the WILLAB
DECISION FILTER first and emit the verdict block (expected:
`JUSTIFIED-SCAFFOLDING — named unblocker: the in-flight FE add/rearrange
surface`). Ship via branch → PR → CI green → squash-merge.

## Founder decision context (do not re-litigate)

The versioning-engine change ("typed additions/moves bake forward into the
next assembled version") is **PARKED by founder decision 2026-07-28**. The
BE-2 lane semantics stand: rewordings/deletions bake forward via the decision
ledger (rule 4b); pure additions and moves display + are retained but do NOT
re-graft into the next assembly. **Do not** implement insertion-baking, order
overlays, master-document writes, or any change to `decompose_user_edit` /
assembly semantics — that is a founder re-lock, not a task.

The decision metric that may un-park it later is exactly what this task
instruments: how often users re-apply a superseded addition.

## Task (two small, additive changes — nothing else)

### 1. `prior_edit` on the student ideal-text GET

`GET /v2/explore/arc/<arc_id>/ideal-text` (handler
`v2_explore_get_ideal_text`) — add ONE additive response field:

```jsonc
"prior_edit": { "text": "<the superseded edit>", "version": N }   // or absent
```

Rules:
- Present **only** when a user-edit row exists for (arc, caller) whose
  `version` differs from the current served version AND whose text is
  non-empty. (When the edit matches the current version it is already served
  as `text` with `user_edited: true` — `prior_edit` absent.)
- Reuses the existing `db.get_user_ideal_edit(arc_id, request.user_id)` read
  already made by the handler — zero extra queries, owner-keyed (never
  another user's edit, never coach text).
- Absent on any error (best-effort; never breaks the GET). No migration.
- Historical `?version=N` view and the coach GET: **unchanged**.

Purpose: after a new take supersedes an edit, the FE offers one-click
"re-apply your additions" even across a reload / device switch.

### 2. Optional `reapplied` flag on the user-edit PUT (log-only)

`PUT /v2/explore/arc/<arc_id>/ideal-text/user-edit` — accept an optional
body field `"reapplied": true`. Behavior:
- Validated leniently: anything but boolean `true` is ignored.
- When true and the save succeeds, emit ONE structured log line, e.g.
  `ideal_edit.reapplied arc=<id> version=<n> chars=<len>`.
- **Never persisted, never surfaced, no schema change.** This is the
  founder's decision metric for the parked versioning question — a log
  counter is sufficient.

## Fences / constraints

- No writes to canonical `text`/`auto_text`, the master document, or the
  ledger beyond what the endpoint already does. L1 untouched.
- AC-9: `prior_edit` carries the user's own text only — no scores, nothing
  numeric beyond `version`.
- Idempotent, additive, live-loop-safe; both changes degrade to today's
  behavior on any failure.

## Tests (extend `test_user_ideal_edit.py`, same patterns)

- `prior_edit` present with `{text, version}` when a stale non-empty edit
  exists; absent when: no edit · edit at current version (then
  `user_edited: true` and `prior_edit` absent) · empty stale edit.
- Owner-keyed: another user's edit never appears.
- PUT with `reapplied: true` → 200 + log line emitted (assert via
  `assertLogs`); with `reapplied` absent / non-bool → 200, no log, no error.
- Full CI-style suite green before the PR.

## Acceptance

FE can: detect `prior_edit` on the GET → render a one-click re-offer → PUT
the merged text with `reapplied: true` → founder can count re-applies from
logs. Nothing else about the contract moved.
