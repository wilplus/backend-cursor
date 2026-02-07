# How to implement the three task types in the frontend

Step-by-step guide to switch the admin panel to the new backend routes so the three sections (Warm-up Tasks, Focus tasks, Post-recording questions) use the same mechanism and stop returning 404.

---

## Overview

You will:

1. **BFF (Next.js API routes):** Point existing or new routes to the new backend paths and response keys.
2. **API client:** Call the new paths and read the new response keys (`task_warm_up`, `task_focus`, `post_recording_questions`).
3. **Student profile page:** Use the new keys from the profile (or from dedicated fetches), and stop using `assigned_post_question_ids` for post-recording.

Backend paths (your BFF should proxy to these):

| What              | Old backend path (404)              | New backend path                          |
|-------------------|-------------------------------------|-------------------------------------------|
| Warm-up list      | `.../students/:id/warm-up-tasks`     | `.../students/:id/task-warm-up`            |
| Focus list        | `.../students/:id/focus-tasks`       | `.../students/:id/task-focus`             |
| Post-recording pool | `.../post-recording-questions`     | `.../post-recording-questions-pool`       |
| Post-recording list | (overrides)                        | `.../students/:id/post-recording-questions` |

Response keys: **`task_warm_up`**, **`task_focus`**, **`post_recording_questions`** (and pool: **`task_warm_up_pool`**, **`task_focus_pool`**, **`post_recording_questions_pool`**).

---

## Step 1: BFF — proxy to new backend paths

Your BFF lives under `/api/admin/...` and proxies to the Flask backend. You can either **keep the same frontend URL** and only change the backend URL inside the BFF, or **rename the frontend URL** to match the backend. Below we **rename** so the frontend and backend naming are aligned.

### 1a. Warm-up (per student)

- **Option A — New path:** Create `app/api/admin/students/[id]/task-warm-up/route.ts` and proxy to `${backend}/v2/admin/students/${id}/task-warm-up`. Then add `route.ts` for `task-warm-up/[taskId]` for PUT/DELETE (proxy to same path with `/${taskId}`).
- **Option B — Same path:** In your existing `students/[id]/warm-up-tasks/route.ts`, change the backend URL from `.../warm-up-tasks` to `.../task-warm-up`. The backend will return `{ "task_warm_up": [...] }`, so the frontend will receive that key (you must then use `task_warm_up` in the client, not `warm_up_tasks`).

Use **one** of these. Example for **Option B** (minimal BFF change):

```ts
// In students/[id]/warm-up-tasks/route.ts — change backend path only:
const res = await fetch(`${backend}/v2/admin/students/${id}/task-warm-up`, { ... });
// Backend returns { task_warm_up: [...] }; frontend must read .task_warm_up
```

### 1b. Warm-up pool (if you have it)

If you have a BFF route for the warm-up **pool** (e.g. `/api/admin/warm-up-task-pool`), change the backend URL to:

`${backend}/v2/admin/task-warm-up-pool`

Backend response key is **`task_warm_up_pool`**.

### 1c. Focus (per student)

Create or update BFF so that:

- **GET/PUT/POST** `.../students/[id]/task-focus` → `${backend}/v2/admin/students/${id}/task-focus`
- **PUT/DELETE** `.../students/[id]/task-focus/[taskId]` → same with `/${taskId}`

Response key: **`task_focus`**.

### 1d. Focus pool

- **GET/POST/PUT/DELETE** `/api/admin/task-focus-pool` and `.../task-focus-pool/[poolId]` → `${backend}/v2/admin/task-focus-pool` and `.../task-focus-pool/${poolId}`. Response key: **`task_focus_pool`**.

### 1e. Post-recording pool

In your **pool** route (e.g. `post-recording-questions/route.ts`), change backend URL from:

`${backend}/v2/admin/post-recording-questions`  
to  
`${backend}/v2/admin/post-recording-questions-pool`

Response key: **`post_recording_questions_pool`** (backend no longer returns `questions` for this endpoint).

### 1f. Post-recording per student

Add a **new** BFF route for the per-student list, e.g.:

- **File:** `app/api/admin/students/[id]/post-recording-questions/route.ts`
- **GET** → `${backend}/v2/admin/students/${id}/post-recording-questions` → returns `{ post_recording_questions: [...] }`
- **PUT** (sync) → same URL, body `{ "pool_question_ids": [...] }`
- **POST** (create) → same URL, body `{ "text", "order_index?", "answer_type?" }`

And for one question:

- **File:** `app/api/admin/students/[id]/post-recording-questions/[questionId]/route.ts`
- **PUT** → `${backend}/v2/admin/students/${id}/post-recording-questions/${questionId}`
- **DELETE** → same

---

## Step 2: API client — new paths and response keys

Update your admin API client (e.g. `lib/api/admin-client.ts`) so it calls the new paths and uses the new keys.

### 2a. Types

Add or rename types so they match backend (same shape, names can stay):

```ts
// Same shape as before; use for all three “task” types if you want one type
export interface TaskItem {
  id: string;
  user_id?: string;
  text: string;
  order_index: number;
  max_performance_score?: number;
  created_at?: string;
}

export interface PostRecordingQuestionItem {
  id: string;
  user_id?: string;
  pool_question_id?: string | null;
  text: string;
  order_index: number;
  answer_type: string;
  code?: string | null;
  created_at?: string;
}
```

### 2b. Student profile type

Ensure the profile type includes the three arrays returned by the backend:

```ts
export interface StudentProfile {
  user_id: string;
  email: string | null;
  overrides: { ... };
  speaker_profile: { ... };
  task_warm_up: TaskItem[];        // was warm_up_tasks
  task_focus: TaskItem[];          // add
  post_recording_questions: PostRecordingQuestionItem[];  // was from overrides
  sessions: ...;
  // ...
}
```

(If your backend returns these on `GET /v2/admin/students/:id`, your BFF just forwards that; then the frontend profile type must have these fields.)

### 2c. API methods — warm-up

Switch to the new path and key. Example if you **kept** BFF path `/students/:id/warm-up-tasks` but backend now returns `task_warm_up`:

```ts
getTaskWarmUp: (userId: string) =>
  adminFetch<{ task_warm_up: TaskItem[] }>(`/students/${userId}/task-warm-up`).then((r) => r.task_warm_up),
```

If you kept the old BFF path and only changed the backend URL in the BFF, then the backend response is already `task_warm_up`, so the BFF returns that. Then either:

- Change the frontend path to `/students/${userId}/task-warm-up` and add the BFF route for it, and use `.task_warm_up`, or  
- Keep frontend path `/students/${userId}/warm-up-tasks` and in the client read the **key** that the BFF returns. Since the BFF proxies and returns the backend body as-is, the client will get `task_warm_up`. So change the client to:

```ts
getTaskWarmUp: (userId: string) =>
  adminFetch<{ task_warm_up: TaskItem[] }>(`/students/${userId}/warm-up-tasks`).then((r) => r.task_warm_up),
```

(Only if your BFF still listens at `warm-up-tasks` and proxies to backend `task-warm-up`.) And add sync:

```ts
syncTaskWarmUp: (userId: string, poolTaskIds: string[]) =>
  adminFetch<{ task_warm_up: TaskItem[] }>(`/students/${userId}/task-warm-up`, {
    method: "PUT",
    body: { pool_task_ids: poolTaskIds },
  }).then((r) => r.task_warm_up),
```

Use **`task-warm-up`** in the path if your BFF has that route; otherwise use the path your BFF actually exposes.

### 2d. API methods — focus

Add (or rename from focus-tasks):

```ts
getTaskFocus: (userId: string) =>
  adminFetch<{ task_focus: TaskItem[] }>(`/students/${userId}/task-focus`).then((r) => r.task_focus),

syncTaskFocus: (userId: string, poolTaskIds: string[]) =>
  adminFetch<{ task_focus: TaskItem[] }>(`/students/${userId}/task-focus`, {
    method: "PUT",
    body: { pool_task_ids: poolTaskIds },
  }).then((r) => r.task_focus),

createTaskFocus: (userId: string, data: { text: string; order_index?: number; max_performance_score?: number }) =>
  adminFetch<{ task_focus: TaskItem }>(`/students/${userId}/task-focus`, { method: "POST", body: data }),

updateTaskFocus: (userId: string, taskId: string, data: Partial<TaskItem>) =>
  adminFetch<{ task_focus: TaskItem }>(`/students/${userId}/task-focus/${taskId}`, { method: "PUT", body: data }),

deleteTaskFocus: (userId: string, taskId: string) =>
  adminFetch<{ status: string }>(`/students/${userId}/task-focus/${taskId}`, { method: "DELETE" }),
```

And for the **pool**:

```ts
getTaskFocusPool: () =>
  adminFetch<{ task_focus_pool: TaskItem[] }>("/task-focus-pool").then((r) => r.task_focus_pool),
```

### 2e. API methods — post-recording

**Pool** (list/create/update/delete) — path and key:

```ts
getPostRecordingQuestionsPool: () =>
  adminFetch<{ post_recording_questions_pool: PostRecordingQuestionItem[] }>("/post-recording-questions-pool")
    .then((r) => r.post_recording_questions_pool),
```

**Per student** (list, sync, create, update, delete):

```ts
getPostRecordingQuestions: (userId: string) =>
  adminFetch<{ post_recording_questions: PostRecordingQuestionItem[] }>(
    `/students/${userId}/post-recording-questions`
  ).then((r) => r.post_recording_questions),

syncPostRecordingQuestions: (userId: string, poolQuestionIds: string[]) =>
  adminFetch<{ post_recording_questions: PostRecordingQuestionItem[] }>(
    `/students/${userId}/post-recording-questions`,
    { method: "PUT", body: { pool_question_ids: poolQuestionIds } }
  ).then((r) => r.post_recording_questions),

createPostRecordingQuestion: (userId: string, data: { text: string; order_index?: number; answer_type?: string }) =>
  adminFetch<{ post_recording_question: PostRecordingQuestionItem }>(
    `/students/${userId}/post-recording-questions`,
    { method: "POST", body: data }
  ),

updatePostRecordingQuestion: (userId: string, questionId: string, data: Partial<PostRecordingQuestionItem>) =>
  adminFetch<{ post_recording_question: PostRecordingQuestionItem }>(
    `/students/${userId}/post-recording-questions/${questionId}`,
    { method: "PUT", body: data }
  ),

deletePostRecordingQuestion: (userId: string, questionId: string) =>
  adminFetch<{ status: string }>(
    `/students/${userId}/post-recording-questions/${questionId}`,
    { method: "DELETE" }
  ),
```

Remove or stop using any method that fetches the pool from `/post-recording-questions` and expects `questions`. Use **`/post-recording-questions-pool`** and **`post_recording_questions_pool`** for the pool.

---

## Step 3: Student profile page — use new keys and endpoints

### 3a. Data from profile

When you load the student profile (`getStudentProfile(id)`), the backend now returns **`task_warm_up`**, **`task_focus`**, and **`post_recording_questions`**. So you can:

- Set state from `profile.task_warm_up`, `profile.task_focus`, `profile.post_recording_questions` instead of separate GETs for warm-up/focus, and instead of `overrides.assigned_post_question_ids` for post-recording.

Example after loading profile:

```ts
if (profileRes.status === "fulfilled") {
  const p = profileRes.value;
  setProfile(p);
  setWarmUpTasks(p.task_warm_up ?? []);
  setFocusTasks(p.task_focus ?? []);
  setPostRecordingQuestions(p.post_recording_questions ?? []);
}
```

(Use your actual state setter names.)

### 3b. When you still need fresh lists

If you prefer to refetch after add/edit/delete, call the new per-student endpoints:

- After create/update/delete/sync warm-up: `adminApi.getTaskWarmUp(id)` or refetch profile.
- Same for focus: `adminApi.getTaskFocus(id)`.
- Same for post-recording: `adminApi.getPostRecordingQuestions(id)`.

### 3c. Stop using overrides for post-recording

- Remove reading **`overrides.assigned_post_question_ids`** for the “Post-recording questions” section.
- Remove any “Save” that writes **`assigned_post_question_ids`** for that section. Assigning post-recording questions is done only via the per-student endpoints (sync or create/update/delete).

You can keep saving other overrides (e.g. `assigned_next_task_ids`) with your existing `putOverrides`; just don’t send or rely on `assigned_post_question_ids` for the post-recording UI.

### 3d. “Manage list” / Confirm selection

- **Warm-up:** On confirm, call `syncTaskWarmUp(userId, selectedPoolTaskIds)`.
- **Focus:** On confirm, call `syncTaskFocus(userId, selectedPoolTaskIds)`.
- **Post-recording:** On confirm, call `syncPostRecordingQuestions(userId, selectedPoolQuestionIds)`.

Body keys: **`pool_task_ids`** for warm-up and focus, **`pool_question_ids`** for post-recording (your API client should send those as in the snippets above).

---

## Step 4: Warm-up and focus pool (if used)

If you have UI to manage the **global pool** (e.g. add/edit/delete warm-up or focus tasks in the pool):

- Warm-up pool: path **`/task-warm-up-pool`**, response **`task_warm_up_pool`** (and single item **`task_warm_up`**).
- Focus pool: path **`/task-focus-pool`**, response **`task_focus_pool`** (and single item **`task_focus`**).

Add BFF routes that proxy to `${backend}/v2/admin/task-warm-up-pool` and `.../task-focus-pool`, and in the client use the paths and keys above.

---

## Checklist

- [ ] BFF: warm-up per student → backend `.../task-warm-up` (and optional `task-warm-up-pool`).
- [ ] BFF: focus per student (and optional pool) → backend `.../task-focus` and `.../task-focus-pool`.
- [ ] BFF: post-recording pool → backend `.../post-recording-questions-pool`.
- [ ] BFF: post-recording per student → new route `.../students/[id]/post-recording-questions` (and `.../[questionId]`).
- [ ] API client: use response keys **`task_warm_up`**, **`task_focus`**, **`post_recording_questions`** (and pool keys).
- [ ] Profile type: **`task_warm_up`**, **`task_focus`**, **`post_recording_questions`**.
- [ ] Student page: fill the three sections from profile or from the new GET endpoints; do not use **`assigned_post_question_ids`** for post-recording.
- [ ] Sync/Confirm: **`pool_task_ids`** for warm-up/focus, **`pool_question_ids`** for post-recording.

After this, the three sections use the same mechanism and the 404s for warm-up, focus, and post-recording should be gone. For full API details (all methods and bodies), see **`FRONTEND-PROMPT-THREE-TASK-TYPES.md`**.
