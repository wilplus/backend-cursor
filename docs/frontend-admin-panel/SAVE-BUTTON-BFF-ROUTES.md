# Save button doesn't persist — add these BFF routes

If clicking **Save** in the admin student profile doesn't persist values (Homework Configuration or Speaker Profile), the frontend is probably **missing the BFF routes** that proxy PUT requests to the backend. The browser sends requests to **your** app (e.g. `/api/admin/students/:id/overrides` and `/api/admin/students/:id/speaker-profile`); if those routes don't exist, you get 404 and nothing is saved.

## 1. Add the two route files

Create these in your **frontend** app (adjust the `getAuth` import path to match your project).

### A) Overrides (Homework Configuration Save)

**File:** `src/app/api/admin/students/[id]/overrides/route.ts`

```ts
import { NextRequest, NextResponse } from "next/server";
import { getV2AccessToken, getBackendUrl } from "../../../../../getAuth";

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const token = await getV2AccessToken();
  if (!token) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const { id } = await params;
  const body = await request.json().catch(() => ({}));
  const backend = getBackendUrl();
  const res = await fetch(`${backend}/v2/admin/students/${id}/overrides`, {
    method: "PUT",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    return NextResponse.json(data, { status: res.status });
  }
  return NextResponse.json(data);
}
```

### B) Speaker profile (Speaker Profile Save)

**File:** `src/app/api/admin/students/[id]/speaker-profile/route.ts`

```ts
import { NextRequest, NextResponse } from "next/server";
import { getV2AccessToken, getBackendUrl } from "../../../../../getAuth";

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const token = await getV2AccessToken();
  if (!token) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const { id } = await params;
  const body = await request.json().catch(() => ({}));
  const backend = getBackendUrl();
  const res = await fetch(`${backend}/v2/admin/students/${id}/speaker-profile`, {
    method: "PUT",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    return NextResponse.json(data, { status: res.status });
  }
  return NextResponse.json(data);
}
```

Reference copies (same content): **`docs/frontend-admin-panel/api-routes/students-[id]-overrides-route.ts`** and **`students-[id]-speaker-profile-route.ts`** in the backend repo.

## 2. Fix the import path

The `getAuth` import path depends on where your auth helper lives. From `src/app/api/admin/students/[id]/overrides/route.ts`, the path `../../../../../getAuth` goes up to `src/app/api/` and loads `getAuth.ts` there. If your file is at `src/lib/getAuth.ts`, use something like `../../../../../../lib/getAuth` (or a path alias like `@/lib/getAuth`).

## 3. Verify in the browser

1. Open DevTools → **Network**.
2. Change a value (e.g. intended emotion prompt or coach notes) and click **Save**.
3. You should see:
   - **PUT** request to **`/api/admin/students/<student-id>/overrides`** (when saving Homework Configuration) or to **`/api/admin/students/<student-id>/speaker-profile`** (when saving Speaker Profile).
   - Status **200** and response `{ "status": "ok" }` if the backend saved successfully.
4. If you see **404** for either URL, the corresponding BFF route file is missing or in the wrong place (path must be **api/admin/students/[id]/overrides** and **api/admin/students/[id]/speaker-profile**, not under **api/v2/**).

## 4. Backend validation (overrides)

The backend expects **assigned_post_question_ids** to be either omitted or **exactly 3** IDs. If you send 0, 1, 2, or 4+, the backend returns 400 and the save fails. Your frontend should only include `assigned_post_question_ids` in the payload when the user has selected exactly 3 questions (the reference does this).

After adding the two BFF routes and fixing the import, Save should persist correctly.

## 5. Warm-up task "Max score" doesn't save

If warm-up **questions** save but changing **Max score** does not persist:

1. **Backend** accepts `max_performance_score` (0–1) on PUT to `/v2/admin/students/:id/warm-up-tasks/:taskId`. The BFF route forwards the full body, so no BFF change is needed.
2. **Frontend** must send `max_performance_score` in the **PUT body** when updating a warm-up task. For example:
   - When the user changes the Max score input, call your update API with `{ max_performance_score: value }` (e.g. on **blur** or with a per-row Save).
   - When saving the Edit modal, include `max_performance_score` in the payload along with `text` (and optionally `order_index`).

Example update payload that persists the score:

```json
{ "text": "How are you doing today?", "max_performance_score": 1 }
```

The reference admin client and student profile page in this repo now include `max_performance_score` in `WarmUpTask`, in `createWarmUpTask` / `updateWarmUpTask` payloads, and an inline Max score input that saves on blur.
