# Admin BFF API Routes

Copy each file into your Next.js app as shown below. These routes proxy to the Flask backend at `GET/PUT/POST/DELETE https://BACKEND_URL/v2/admin/...` with the **current user's** Supabase access token. The backend enforces admin via the `admin_users` table.

Use the same `getV2AccessToken` and `getBackendUrl` from your existing v2 BFF (`src/app/api/v2/getAuth.ts`). Adjust relative imports if your `getAuth` lives elsewhere.

## File mapping

| This file | Copy to (Next.js) |
|-----------|-------------------|
| `students-route.ts` | `src/app/api/v2/admin/students/route.ts` |
| `students-[id]-route.ts` | `src/app/api/v2/admin/students/[id]/route.ts` |
| `students-[id]-overrides-route.ts` | `src/app/api/v2/admin/students/[id]/overrides/route.ts` |
| `students-[id]-speaker-profile-route.ts` | `src/app/api/v2/admin/students/[id]/speaker-profile/route.ts` |
| `students-[id]-send-assignment-route.ts` | `src/app/api/v2/admin/students/[id]/send-assignment/route.ts` |
| `exercises-route.ts` | `src/app/api/v2/admin/exercises/route.ts` |
| `exercises-[id]-route.ts` | `src/app/api/v2/admin/exercises/[id]/route.ts` |
| `tasks-route.ts` | `src/app/api/v2/admin/tasks/route.ts` |
| `post-recording-questions-route.ts` | `src/app/api/v2/admin/post-recording-questions/route.ts` (GET + POST) |
| `post-recording-questions-[id]-route.ts` | `src/app/api/v2/admin/post-recording-questions/[id]/route.ts` (PUT + DELETE) |

Imports assume `getAuth.ts` is at `src/app/api/v2/getAuth.ts` (so from `admin/students/route.ts` use `../../getAuth`, from `admin/students/[id]/route.ts` use `../../../getAuth`).
