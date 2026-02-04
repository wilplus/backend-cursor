# Admin BFF API Routes

Copy each file into your Next.js app as shown below. These routes proxy to the Flask backend at `GET/PUT/POST/DELETE https://BACKEND_URL/v2/admin/...` with the **current user's** Supabase access token. The backend enforces admin via the `admin_users` table.

**Frontend paths:** The frontend calls **`/api/admin/*`** (no `v2`). BFF routes live under **`src/app/api/admin/`** and proxy to backend `/v2/admin/*`.

Use the same `getV2AccessToken` and `getBackendUrl` from your shared auth helper (e.g. `src/app/api/getAuth.ts`). Adjust relative imports if your `getAuth` lives elsewhere.

## File mapping

| This file | Copy to (Next.js) |
|-----------|-------------------|
| `students-route.ts` | `src/app/api/admin/students/route.ts` |
| `students-[id]-route.ts` | `src/app/api/admin/students/[id]/route.ts` |
| `students-[id]-overrides-route.ts` | `src/app/api/admin/students/[id]/overrides/route.ts` |
| `students-[id]-speaker-profile-route.ts` | `src/app/api/admin/students/[id]/speaker-profile/route.ts` |
| `students-[id]-send-assignment-route.ts` | `src/app/api/admin/students/[id]/send-assignment/route.ts` |
| `exercises-route.ts` | `src/app/api/admin/exercises/route.ts` |
| `exercises-[id]-route.ts` | `src/app/api/admin/exercises/[id]/route.ts` |
| `tasks-route.ts` | `src/app/api/admin/tasks/route.ts` (GET + POST) |
| `tasks-[id]-route.ts` | `src/app/api/admin/tasks/[id]/route.ts` (PUT + DELETE) |
| `post-recording-questions-route.ts` | `src/app/api/admin/post-recording-questions/route.ts` (GET + POST) |
| `post-recording-questions-[id]-route.ts` | `src/app/api/admin/post-recording-questions/[id]/route.ts` (PUT + DELETE) |
| `students-[id]-warm-up-tasks-route.ts` | `src/app/api/admin/students/[id]/warm-up-tasks/route.ts` (GET + POST) |
| `students-[id]-warm-up-tasks-[taskId]-route.ts` | `src/app/api/admin/students/[id]/warm-up-tasks/[taskId]/route.ts` (PUT + DELETE) |
| `metric-questions-route.ts` | `src/app/api/admin/metric-questions/route.ts` (GET + POST) |
| `metric-questions-[id]-route.ts` | `src/app/api/admin/metric-questions/[id]/route.ts` (PUT + DELETE) |

Imports: if `getAuth.ts` is at `src/app/api/getAuth.ts`, from `admin/students/route.ts` use `../../getAuth`, from `admin/students/[id]/route.ts` use `../../../getAuth`.
