# Debug: Both warm-up and focus tasks not showing (BFF, JWT, status)

If **both warm-up and focus tasks aren’t showing in the student flow even though they exist in the admin panel**, the most likely causes are:

1. The student-flow request hits a **BFF route that strips fields** (`warm_up_task` / `focus_task` never reaches the browser).
2. The backend resolves the **wrong `user_id` from the JWT** (e.g. after changing “Flask backend Supabase JWT verification”), so it queries tasks for a different UUID → returns none.
3. The backend doesn’t return `focus_task` on the endpoints the frontend uses, or only returns it when `session.status` is the focus step.

You can pinpoint it quickly with the steps below.

---

## 1) Prove whether the backend is returning warm_up_task / focus_task

On the warm-up or focus screen, in **DevTools → Network**, find the request the UI uses. Usually one of:

- **GET /api/homework/session/status** (BFF)
- **POST /api/homework/session/start** (BFF)
- Or the same paths on the backend: **/v2/homework/session/status**, **/v2/homework/session/start**

Open **Response** and check:

- **`session.status`**
- **`warm_up_task`** (top-level)
- **`focus_task`** (top-level) if present — focus task is often returned in **GET /session/&lt;id&gt;/task-block** or in the **recording-1** response, not in status/start; see §3.
- **`session.user_id`** (if included) or anything that identifies the user

**Paste that JSON here** (plus the request URL) and you can be told the exact fix (BFF vs backend vs session logic).

See **docs/DEBUG-WARM-UP-TASK-LOADING.md** for step-by-step “How to get the response”.

---

## 2) Check the “wrong user_id from JWT” hypothesis (very likely)

If you recently changed JWT verification, the backend may be using the wrong claim for `user_id`.

### DB reality check (Supabase SQL)

Using the **student UUID you see in admin** (e.g. from `auth.users`), run:

```sql
select count(*) as warmups
from public.v2_warm_up_tasks
where user_id = '<STUDENT_UUID>';

select count(*) as focuses
from public.v2_focus_tasks
where user_id = '<STUDENT_UUID>';
```

If **both counts are > 0** but the backend still returns “no task”, the backend is probably querying with a **different `user_id`** than `<STUDENT_UUID>`.

### Backend-side fix pattern

Use the Supabase JWT standard: **user id is in the `sub` claim** (UUID string).

Your auth code should set:

```python
user_id = decoded_jwt["sub"]
```

(not email, not `user_metadata`, not a different field). In this repo, **auth.py** already uses `payload.get("sub")` and attaches it as `request.user_id`. If you overrode or duplicated auth elsewhere, ensure that path also uses `sub`.

**Quick check:** Log the `user_id` your student endpoints use and compare it to the admin student id. If they differ, fix the JWT → `user_id` mapping in Flask (or the layer that sets `request.user_id`).

---

## 3) Focus task may only appear on the focus step

Even if focus tasks are configured, you may not see one if:

- The active session **`status`** is still **`"warm_up"`**, and your endpoint only attaches **`focus_task`** when status is **`task_block`** (or similar).

So check **`session.status`** in the status/start response:

- If it’s **`warm_up`**, you should expect only **warm_up_task** to be present on **GET /session/status** and **POST /session/start**. The **focus task** is returned later: in **POST /session/&lt;id&gt;/recording-1** (inside **`task_block.focus_task`**) and in **GET /session/&lt;id&gt;/task-block** when **`session.status === "task_block"`**.

If you **are** on the focus step (status `task_block`) and the request is **GET /session/&lt;id&gt;/task-block** and you still see no focus task, then the issue is backend (no task selected) or BFF stripping that response.

---

## 4) If you’re using a BFF (/api/…), ensure it forwards the whole payload

A very common bug is the BFF returning only part of the backend response and dropping **`warm_up_task`** / **`focus_task`**.

**Bad:**

```ts
return NextResponse.json(data.session)
```

**Good:**

```ts
return NextResponse.json(data)
```

So the client receives the same shape as the backend: **`{ session, warm_up_task?, ... }`**, not just `session`. Check every BFF route that proxies **session/status** and **session/start** (and **task-block** if the frontend uses it for the focus step).

---

## What to paste so you can get the exact fix

Paste **one** Network response JSON from the student flow request you’re using:

- **URL:** e.g. `GET https://app.example.com/api/homework/session/status` or `POST .../session/start`
- **Response body:** full JSON (especially **`session.status`**, **`warm_up_task`**, **`focus_task`** if present, and any user/session id)

Also say whether you’re on the **warm-up step** or the **focus step** when you expect the focus task.

With that, you can tell precisely whether you need to:

- Fix **JWT → user_id** mapping in Flask (most likely if both tasks are missing and DB has rows for the student), or  
- Fix **BFF passthrough** (return full `data`, not just `data.session`), or  
- Adjust **backend** to include **`focus_task`** on the correct status/endpoint (e.g. task-block when status is `task_block`).
