# dev.willpowerlab.com — "user stories · tasks" backlog (SPEC, for review)

Second view in the dev tool, alongside dev-bugs. Bugs feed **GPT-4o**, which turns
each into a **user-story-centered task** (leads with the user-journey fragment it
unlocks), filed under **Theme → Epic → User Story** and prioritized into a single
list — highest at the top, always. You review, reorder, copy to the LLM of your
choice, and click **done** to archive. **No auto-dispatch to coding agents** (parked
— see §9).

> Status: **spec only, nothing built.** This is the review checkpoint.

---

## 0. Decisions locked (founder, 2026-07-24)

| Question | Answer |
|---|---|
| Manual drag vs GPT-4o priority | **Manual pins it** — GPT-4o slots each *new* task; once you drag a task, that position sticks and survives future runs |
| When bugs → tasks | **Immediately on save** (a bug saved → GPT-4o → task appears) |
| "Crucial" ranking | **Fixed theme order, AI ranks within** — themes fixed (T1>T2>T3>T4), GPT-4o orders epic/user-story/task inside each theme |
| Done → archive | **Reversible** — archived tasks can be restored |
| Export | **Whole backlog exportable** — a ZIP (markdown + screenshot files) when a task has images, else plain markdown |

**Scope:** still dev-tooling (not F1). With no auto-execute, it's fence-clean — it never writes code or touches `main`; it only reads bugs and shows a list.

**To confirm before I build (I'll assume these unless you say otherwise):**
1. Fixed theme order = **T1 > T2 > T3 > T4** (as listed in the backlog).
2. **1 bug → 1 task** (keeps the track-record 1:1; GPT-4o may occasionally note sub-tasks inside the one task's text).
3. Export = a **markdown file of the active backlog** in priority order (archive excluded unless you want it too).

---

## 1. Two-view app (hamburger)

`static/dev_bugs.html` grows a **hamburger menu** with two views (same page, same `x-dev-key`, same host):
- **dev-bugs** — the existing collector (unchanged).
- **user stories · tasks** — the new backlog (this spec).

Bugs still auto-email on the 3-day cron (your audit trail) — **untouched**.

---

## 2. Data model — `migrations/add_dev_tasks.sql`

```sql
CREATE TABLE IF NOT EXISTS public.dev_tasks (
    id          BIGSERIAL   PRIMARY KEY,
    bug_id      BIGINT      REFERENCES public.dev_bugs(id) ON DELETE SET NULL,
    body        TEXT        NOT NULL DEFAULT '',   -- the user-story-centered task text (what the user sees + copies)
    theme       TEXT,                              -- 'T1'..'T4' (fixed-rank bucket)
    epic        TEXT,                              -- e.g. '1.2 Ideal-Text & Recording UX'
    user_story  TEXT,                              -- the user-journey fragment this task unlocks
    priority    SMALLINT    NOT NULL DEFAULT 2,    -- 1=P1 (high) .. 3=P3, set by GPT-4o within the theme
    order_key   DOUBLE PRECISION NOT NULL,         -- effective sort position; lower = higher on the list
    pinned      BOOLEAN     NOT NULL DEFAULT false, -- true once you manually drag it (GPT-4o won't move it again)
    status      TEXT        NOT NULL DEFAULT 'active', -- 'active' | 'archived'
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at TIMESTAMPTZ,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS dev_tasks_status_order_idx ON public.dev_tasks (status, order_key);
-- guarded CHECKs on status + priority (DO $$ ... pg_constraint ... $$), RLS enabled.
```

---

## 3. GPT-4o transform (`services/dev_tasks.py`) — on bug save

Reuse `services/openai_service.py` (already wired), model `gpt-4o`. On `POST /api/dev-bugs`, after the bug is stored, generate its task:

- **Prompt:** the backlog context (THEMES T1–T4 / EPICS 1.1–4.3) + "write ONE user-story-centered task; lead with the user-journey fragment it makes possible." Returns strict JSON:
  ```json
  { "theme": "T1", "epic": "1.2 …", "user_story": "As a <role>, I want <journey fragment>, so that <payoff>",
    "body": "<the full task the coding agent will act on>", "priority": 1 }
  ```
- Insert a `dev_tasks` row (`status='active'`), compute `order_key` (§4). GPT-4o runs once per task; it is **never** re-invoked to re-rank the whole list.

---

## 4. Prioritization & stability (your main worry)

The list is **deterministically sorted by `order_key` ascending** — it never re-ranks the whole growing list, so it can't drift or "break" as tasks amass.

- **Composite rank for a new task:** `order_key` derived from `(theme_rank, epic_rank, user_story_rank, priority, created_at)` where `theme_rank` is fixed (T1<T2<T3<T4) and the rest come from GPT-4o's classification. The new task lands in its correct slot among the **unpinned** tasks.
- **Manual pin:** when you drag a task, we set `pinned=true` and rewrite its `order_key` to the midpoint of its new neighbors. Pinned tasks hold their spot forever; new GPT-4o tasks slot around them but never displace them.
- Net: top of list = highest priority (T1 / crucial epic / crucial user story / P1), descending as you scroll — stable at 10 or 500 tasks.

---

## 5. Endpoints (`routes/dev_tasks.py`, `x-dev-key` gated)

| Route | Purpose |
|---|---|
| `GET /api/dev-tasks?view=active\|archive` | Active list (by `order_key`) or archive (by `archived_at` desc) |
| `POST /api/dev-tasks/<id>/reorder` `{after_id}` | Drag-reorder → set `pinned`, recompute `order_key` |
| `PATCH /api/dev-tasks/<id>` `{body,…}` | Edit task text |
| `DELETE /api/dev-tasks/<id>` | Delete (⋮ menu) |
| `POST /api/dev-tasks/<id>/done` / `/restore` | Archive ↔ restore (reversible) |
| `GET /api/dev-tasks/export` | Whole active backlog as a download — a **ZIP** (`backlog.md` + `images/task-<id>-<n>.<ext>`) when a task has screenshots, else a plain `.md`. The client names the saved file from `Content-Disposition`. |

(Task creation is implicit — it happens inside the existing `POST /api/dev-bugs`.)

---

## 6. Frontend — the tasks view

- **Flat list, priority order.** Each row: the user-story/task text, a small **date** + **priority** chip (P1/P2/P3), and tiny theme/epic labels. Minimal.
- **Copy all** (top) and **copy one** (per row) → clipboard, **with the screenshots** (see 6b).
- **Drag to reorder** (tap-hold-move on mobile, drag on desktop) → calls `/reorder`.
- **⋮ menu** per row → **Edit** (inline) / **Delete**.
- **Done** button per row → archive (moves it out of active).
- **Archive view** (toggle) → done tasks by date, each with **Restore**.
- **Export** button → downloads the backlog **with the screenshots as files** (see 6b).

---

## 6b. Screenshots in Copy all / Export

A bug's screenshots ride onto its task (`dev_tasks.images`, stored as `data:` URLs).
Both paths carry them, by the only means each channel allows.

**Copy all / copy one → two clipboard flavours.** The clipboard cannot hold "text
plus N attachments", but it can hold several *flavours* of one payload:

| Flavour | Paste target | You get |
|---|---|---|
| `text/html` | Notion, Google Docs, Gmail, Slack | text **+ the screenshots inline** |
| `text/plain` | code editor, most LLM chat inputs | the markdown, with an `(N screenshots attached)` note |

Pasting into a **plain-text** box cannot carry images — that is a clipboard limit,
not a bug; use Export there. The plain flavour deliberately omits the base64 so a
plain-text paste stays sane.

Two things to keep in mind when touching `copyAll`:

- The handler is **not `async`** and `ClipboardItem` is handed **promises**. Safari
  rejects a clipboard write issued after an `await`, so the write must go out inside
  the tap with the fetch still in flight. This is a phone-first tool — an `await`
  before the write breaks Copy all on the iPhone. (`copyRich` is fine for a single
  row: nothing is awaited before it.)
- No `ClipboardItem`, or a refused write, falls back to plain `writeText`; an empty
  backlog reports "Nothing to copy", not "Copy failed".

**Export → a ZIP.** `backlog.md` plus `images/task-<id>-<n>.<ext>`, the markdown
linking each file (`![screenshot 1](images/task-11-1.png)`). Real files, so they
open anywhere and can be dragged straight into an LLM or a ticket — a `.md` with
megabytes of inline base64 renders in almost nothing (GitHub and most editors
refuse `data:` URIs) and can't be opened as an image.

With nothing decodable to bundle it stays a plain `.md`, still self-contained (any
`data:` URI is embedded by `to_markdown`). `http(s)`-hosted images are left as
links rather than fetched, so an export never depends on network egress. An
unreadable image is skipped, not fatal. Image numbering counts what actually made
it in, so a file name and its `screenshot N` label always agree.

---

## 7. Build phases (each its own gate-routed PR)

1. **Data + transform:** `add_dev_tasks.sql`, `services/dev_tasks.py` (GPT-4o on bug save), `order_key`/pin logic, tests.
2. **Endpoints:** `routes/dev_tasks.py` (list/reorder/edit/delete/done/restore/export), register in `app.py`, tests.
3. **Frontend:** hamburger + tasks view (list, copy, drag, ⋮, done, archive, export) in `static/dev_bugs.html`.

Small, contained, testable. Phase 1 is the engine (prioritization + stability); 2 wires it; 3 is the UI.

---

## 8. Out of scope now / untouched
- dev-bugs collector + 3-day email cron — **unchanged** (bugs still logged + emailed as the audit trail).
- A bug becoming a task does **not** remove it from the bug log.

## 9. Parked — auto-dispatch to coding agents (former plan)
The "GPT-4o → dispatch to Claude/Codex in GitHub Actions → PR" pipeline is **parked** at your request; you'll copy tasks and pick your own LLM. If revived later, it slots on top of this (each task already carries the agent-ready `body`). The human-merge fence still applies.
