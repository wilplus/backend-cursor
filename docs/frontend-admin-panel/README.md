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
- `POST /v2/admin/students/:id/send-assignment` — stub
- `GET/POST/PUT/DELETE /v2/admin/exercises` — exercise CRUD
- `GET /v2/admin/tasks`, `GET /v2/admin/post-recording-questions` — for dropdowns/chips

See `docs/V2-ADMIN-API.md` in the backend repo for full reference.
