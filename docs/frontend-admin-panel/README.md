# Admin Panel — Frontend Deliverables

Copy these into your **Next.js** app so the admin panel matches the design spec (orange primary, SectionCard, Student Profile, Exercises).

## Design tokens (Tailwind)

Add to your `tailwind.config` or `globals.css` so the admin area uses the spec palette:

```css
/* In your admin layout or a scoped file, or extend Tailwind theme */
.admin-panel {
  --primary: 24 95% 53%;
  --background: 0 0% 99%;
  --foreground: 220 20% 10%;
  --card: 0 0% 100%;
  --muted: 220 14% 96%;
  --muted-foreground: 220 10% 46%;
  --accent: 24 100% 97%;
  --accent-foreground: 24 95% 40%;
  --border: 220 13% 91%;
  --destructive: 0 84% 60%;
}
```

If you use shadcn/ui, you can override the CSS variables for the admin route only, or set these as your global theme.

## File mapping (where to copy)

| Deliverable | Copy to (in your Next.js repo) |
|-------------|--------------------------------|
| `components/admin/SectionCard.tsx` | `src/components/admin/SectionCard.tsx` |
| `components/admin/AdminShell.tsx` | `src/components/admin/AdminShell.tsx` |
| `app/admin/layout.tsx` | `src/app/admin/layout.tsx` (or `(admin)` group) |
| `app/admin/students/page.tsx` | `src/app/admin/students/page.tsx` |
| `app/admin/students/[id]/page.tsx` | `src/app/admin/students/[id]/page.tsx` |
| `app/admin/exercises/page.tsx` | `src/app/admin/exercises/page.tsx` |
| `app/admin/questions/page.tsx` | `src/app/admin/questions/page.tsx` |
| `app/admin/metrics/page.tsx` | `src/app/admin/metrics/page.tsx` |
| `lib/api/admin-client.ts` | `src/lib/api/admin-client.ts` |

## BFF (API routes)

Your Next.js app must proxy admin requests to the Flask backend with the **admin user’s** Supabase token. Add API routes under `src/app/api/v2/admin/` that:

- Read the session (e.g. `getServerSession` or cookies) and get `access_token`.
- Call `GET/PUT/POST/DELETE https://YOUR_BACKEND_URL/v2/admin/...` with `Authorization: Bearer <token>`.
- Return the backend response (or 401/403 if not admin).

**Copy the example route handlers** from `api-routes/` in this folder — see `api-routes/README.md` for the full file mapping. Each file proxies one or more backend endpoints. Reuse the same `getV2AccessToken` and `getBackendUrl` from your existing v2 BFF (`src/app/api/v2/getAuth.ts`); admin routes use the same token (backend enforces admin via `admin_users` table).

## Dependencies

- `lucide-react` for icons (Users, BookOpen, ChevronLeft, FileText, etc.)
- `sonner` for toasts (or your toast library)
- UI primitives: Button, Card, Input, Textarea, Label, Badge, Dialog, AlertDialog (shadcn/ui or equivalent)

## Animation

Add to `globals.css` or your Tailwind config:

```css
@keyframes fade-in {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}
.animate-fade-in { animation: fade-in 0.2s ease-out; }
```

## Backend endpoints used

- `GET /v2/admin/students` — list students
- `GET /v2/admin/students/:id` — profile (email, overrides, speaker_profile, sessions with previews)
- `PUT /v2/admin/students/:id/overrides` — homework config (exercises/tasks/questions + prompt overrides)
- `PUT /v2/admin/students/:id/speaker-profile` — speaker profile fields
- `POST /v2/admin/students/:id/send-assignment` — send homework email to student (Resend)
- `GET/POST/PUT/DELETE /v2/admin/exercises` — exercise CRUD
- `GET/POST/PUT/DELETE /v2/admin/post-recording-questions` — question pool CRUD (admin Questions page)
- `GET /v2/admin/tasks`, `GET /v2/admin/post-recording-questions` — for dropdowns/chips
- **Homework flow:** `GET/POST/PUT/DELETE /v2/admin/students/:id/warm-up-tasks` (and `/:taskId`); `GET/POST/PUT/DELETE /v2/admin/metric-questions` — see `docs/FLOW-HOMEWORK-V2.md`

See `docs/V2-ADMIN-API.md` in the backend repo for full reference.

## Troubleshooting

**Students page shows HTTP 404**  
The Students page fetches `GET /api/v2/admin/students` (your Next.js BFF). A 404 means that route is missing or not reachable.

1. **Add the BFF route**  
   Copy `api-routes/students-route.ts` to **`src/app/api/v2/admin/students/route.ts`** in your frontend repo. See `api-routes/README.md` for the full file mapping.

2. **Auth helper**  
   The route imports `getV2AccessToken` and `getBackendUrl` from `../../getAuth`. Ensure **`src/app/api/v2/getAuth.ts`** exists (same as your v2 flow BFF) and returns the Supabase access token and backend base URL.

3. **Backend URL**  
   Set **`NEXT_PUBLIC_BACKEND_URL`** (or **`BACKEND_URL`**) in `.env.local` to your Flask backend (e.g. `https://your-backend.up.railway.app` or `http://localhost:5000`). The BFF proxies to `{BACKEND_URL}/v2/admin/students`.

4. **Backend running**  
   The Flask backend must expose **`GET /v2/admin/students`**. This repo already defines that route; ensure the backend is running and reachable at the URL you set above.

**Debug checklist (when “everything is in place” but something fails)**

1. **Verify backend admin route**  
   Call **`GET {BACKEND_URL}/v2/admin/health`** with `Authorization: Bearer <your_supabase_access_token>`.  
   - **200** → Backend admin prefix is reachable and your token is valid + admin.  
   - **401** → Token missing or invalid.  
   - **403** → Token valid but user not in `admin_users` (add email to `admin_users` in Supabase).  
   - **404** → Wrong base URL or backend not mounted at `/v2` (check `BACKEND_URL` and Flask blueprint).

2. **Verify BFF proxy**  
   In the browser Network tab, when you open the Students page you should see a request to **`/api/v2/admin/students`** (or **`/api/v2/admin/tasks`**, etc.).  
   - If that request is **404** → The corresponding BFF route is missing in the frontend (add the file from `api-routes/` as in `api-routes/README.md`).  
   - If it’s **401/403** → Backend returned that; check token and `admin_users`.  
   - If it’s **500** → Backend threw; check backend logs (and Sentry if configured).

3. **Empty students list**  
   **`GET /v2/admin/students`** returns **`{ "students": [], "limit", "offset" }`** when there are no rows in `v2_sessions`. That’s **200**, not 404. If you expect students, ensure at least one v2 session exists (e.g. a user has started the v2 flow once).

4. **404 for /tasks when opening a student profile**  
   The student profile page fetches **exercises**, **tasks**, and **post-recording questions** in parallel. If the **tasks** BFF route is missing, you get **404 for /tasks** in the console. **Fix:** add **`src/app/api/v2/admin/tasks/route.ts`** (copy from `api-routes/tasks-route.ts`). The student profile page is now resilient: if tasks (or exercises/questions) fail to load, it still shows the profile with an empty list for that section instead of failing the whole page.
