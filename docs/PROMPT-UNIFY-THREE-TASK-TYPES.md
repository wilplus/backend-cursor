# One-shot prompt: Unify warm_up, focus, and post_recording_questions

You want **three** features that all use the **same mechanism** as **focus_tasks** (pool + per-student list, add/edit/delete/sync on student profile), and you want to **remove** current warm-up and post-recording code and **reuse** only what already works (focus_tasks pattern). Below: what you need to decide, then the prompt to give so it’s done once without worsening the code.

---

## 1. Goal in one sentence

**Have three “task/question” types — task_warm_up, task_focus, post_recording_questions — each using the same mechanism as focus_tasks (pool table + per-student table, same API shape and UI pattern); remove or replace existing warm-up and post-recording code so there’s one clear pattern everywhere.**

---

## 2. What “same mechanism” means (reference: focus_tasks)

- **DB:** One **pool** table (e.g. `v2_focus_task_pool`) and one **per-student** table (e.g. `v2_focus_tasks` with `user_id`, `text`, `order_index`, `pool_task_id`, `max_performance_score`).
- **Backend:** Same route shape for all three:
  - `GET/POST/PUT/DELETE .../focus-task-pool` and `.../focus-task-pool/<id>`
  - `GET/POST/PUT/DELETE .../students/<id>/focus-tasks` and `.../focus-tasks/<task_id>`
  - `PUT .../students/<id>/focus-tasks` with `{ "pool_task_ids": [...] }` for sync from pool
- **UI:** Same pattern: list on student profile, “+ Add”, “Manage list” (select from pool, Confirm selection), Edit, Delete.

So **task_warm_up** and **post_recording_questions** should have the **same** API shape and UI pattern as focus_tasks, only with different names/tables.

---

## 3. Gaps you should decide (answer these so the prompt is complete)

**A) Naming**

- Backend routes: keep **warm-up-tasks** and **focus-tasks** and **post-recording-questions**, or rename to **task_warm_up**, **task_focus**, **post_recording_questions** (with underscores/slashes as in your API style)?
- Response keys: keep **warm_up_tasks**, **focus_tasks** and for post-recording use **post_recording_questions** (array), or one common key like **items** for all three?

**B) Post-recording and the homework flow**

- Today the **homework flow** (e.g. step 4 “reflective questions”) reads **assigned_post_question_ids** from **v2_student_overrides** and loads questions from **v2_post_recording_questions** by ID.
- If we make post_recording use the **same mechanism** as focus_tasks we have two options:
  - **Option 1 – Per-student table:** Add e.g. `v2_student_post_recording_questions` (like `v2_focus_tasks`). Sync from pool writes into this table. Homework flow then reads from this table (and we can remove `assigned_post_question_ids` from overrides). Bigger migration and flow change.
  - **Option 2 – Keep overrides:** No new per-student table. Admin API still uses “sync” but backend writes **assigned_post_question_ids** into **v2_student_overrides**. Same API shape and UI as focus_tasks, but under the hood post_recording stays “IDs in overrides”. Homework flow unchanged.

Which do you want: **Option 1** (full per-student table for post_recording) or **Option 2** (same API/UI, overrides keep storing IDs)?

**C) Scope**

- **Backend only** (you’ll do frontend yourself), **frontend only** (backend already done), or **both** (backend + frontend in one go)?
- If both: do you have a **single repo** (backend + frontend) or **two repos**? So the prompt can say “in this repo do X” vs “in backend repo do A, in frontend repo do B”.

**D) What to delete**

- For **warm-up:** Remove only the **old** or **duplicate** code (e.g. different route shapes, or legacy tables), and keep one clear warm-up implementation that matches focus_tasks. Confirm: “Delete any legacy/alternate warm-up implementation; keep one warm-up flow that mirrors focus_tasks.”
- For **post_recording:** Same: remove any alternate/legacy implementation and keep either (1) the new per-student table flow or (2) the overrides-based flow, depending on your answer to B.

Answer A–D in a short list (e.g. “A: keep current route names. B: Option 2. C: both, one repo. D: delete legacy warm-up and post-recording, keep one implementation each.”), then paste the **Master prompt** below and your answers so the model can do it in one pass.

---

## 4. Master prompt (paste this + your answers)

Copy everything below into the chat, then add your answers to the “Decisions” section.

---

**Context**

This codebase has (or will have) three “task/question” types used on the admin student profile:

1. **task_warm_up** (warm-up tasks)  
2. **task_focus** (focus tasks)  
3. **post_recording_questions** (post-recording questions)

**Reference implementation:** **focus_tasks** is the one that works and is the pattern to reuse:

- DB: pool table (e.g. `v2_focus_task_pool`) + per-student table (e.g. `v2_focus_tasks`: `user_id`, `text`, `order_index`, `pool_task_id`, `max_performance_score`).
- Backend: `GET/POST/PUT/DELETE` for pool and for `.../students/<id>/focus-tasks` (and by task id); `PUT .../students/<id>/focus-tasks` with body `{ "pool_task_ids": [...] }` for “sync from pool”.
- UI: list on student profile, “+ Add”, “Manage list” (select from pool, Confirm selection), Edit, Delete.

**Goal**

- Make **task_warm_up** and **post_recording_questions** use the **exact same mechanism** (same API shape, same UI pattern, same DB pattern where applicable).
- **Remove** any existing warm-up and post-recording code that doesn’t follow this pattern (legacy routes, duplicate logic, or alternate implementations). Do not leave two ways to do the same thing.
- **Do not worsen** existing behavior: keep focus_tasks working; fix or align warm-up and post_recording so they work the same way.

**Decisions (fill in)**

- **A) Naming:** [ e.g. Keep routes as warm-up-tasks, focus-tasks, post-recording-questions; response keys warm_up_tasks, focus_tasks, post_recording_questions ]
- **B) Post-recording and homework:** [ Option 1 = new per-student table and homework reads from it; Option 2 = keep assigned_post_question_ids in overrides, sync only updates that array; same API/UI as focus_tasks ]
- **C) Scope:** [ Backend only | Frontend only | Both; and: one repo or two? ]
- **D) What to delete:** [ e.g. Delete legacy warm-up and post-recording implementations; keep exactly one implementation per type, mirroring focus_tasks ]

**What to do**

1. **Backend:** For task_warm_up and post_recording_questions, implement (or refactor to) the same mechanism as focus_tasks: same route shape, same request/response shape, same DB pattern (pool + per-student table, or for post_recording Option 2: overrides array). Add migrations only if needed (e.g. new per-student table for post_recording if Option 1). Remove any code that duplicates or conflicts with this (old routes, old tables references, or alternate logic).
2. **Frontend (if in scope):** Three sections on the student profile (Warm-up, Focus, Post-recording), each using the same UI and same API pattern (list, + Add, Manage list / Confirm selection, Edit, Delete). Reuse the same components or copy the working focus_tasks implementation and rename for the other two. Remove any old/alternate UI for warm-up or post-recording.
3. **Docs:** Point to one place that describes the “three task types” pattern (e.g. “All three use the same mechanism as focus_tasks; see focus_tasks for the reference.”). Remove or update docs that describe the old warm-up or post_recording flow.

Do not change the homework flow (e.g. how step 4 gets questions) except if we chose Option 1 for post_recording; then read from the new per-student table instead of overrides.

---

Once you’ve filled in the **Decisions** block and pasted this (and any repo paths or file names), the model can do the refactor in one go without guessing.
