# Frontend catch-up prompt — Phase 12/13 admin user view + EBCP reset

Hand this entire document to your frontend agent. It is self-contained: it explains why the admin panel currently 404s, what the backend now exposes, the exact BFF (Next.js App Router) routes to drop in, the TypeScript client additions, and the UI work required.

---

## 0. TL;DR for the frontend agent

The backend has shipped two new admin capabilities and one runtime tweak. The admin panel was throwing **404** because the BFF proxy routes did not exist yet.

**Path convention (canonical):** every admin user-scoped route uses the **plural `/v2/admin/users/{user_id}/...`** form. Use this everywhere, no exceptions. The legacy singular `/admin/user/...` alias still exists for back-compat but new code must not use it.

You must:

1. **Add three Next.js BFF routes** under `src/app/api/admin/users/[id]/...` (full code below).
2. **Extend `lib/api/admin-client.ts`** with three typed methods + their response interfaces.
3. **Update the admin user-detail page** (`/admin/users/[id]`) to consume the new multi-session context payload, render the admin-only fields (custom LLM instructions, private notes, queued override question, coach override profile, behavioral profile source badge, baseline state), and add a **"Reset baseline"** danger-zone button.
4. **Optionally** wire a one-shot **"Force assessment this session"** toggle on the interview start screen that sets `force_assessment: true` in the payload to `POST /v2/public/interview/next-question`. This is independent of the persistent reset.

After you ship: every URL the admin clicks for a student under `/admin/users/[id]` must resolve (no 404s), the page must render the multi-session timeline, and the reset button must hit `POST /api/admin/users/<id>/reset-baseline` and show a success toast.

---

## 1. Why the panel was broken (root cause of the 404) and the canonical route map

The Flask backend exposes these endpoints (verified against `routes/v2_routes.py`). Use the **plural** `users` form everywhere — it is the project-wide REST convention:

| Method        | Backend path                                          | Purpose                                                                                                          |
|---------------|-------------------------------------------------------|------------------------------------------------------------------------------------------------------------------|
| GET           | `/v2/admin/users/<user_id>/context`                   | Full longitudinal admin view: user block + ALL their sessions + chat                                             |
| PATCH *(or PUT)* | `/v2/admin/users/<user_id>/context`                | Partial update of `custom_llm_instructions`, `private_admin_notes`, `queued_override_question`, `coach_override_profile`. PATCH and PUT share the same partial-update semantics — use **PATCH** in new code. |
| POST          | `/v2/admin/users/<user_id>/reset-baseline`            | Flip `user_settings.baseline_established=FALSE` (re-arm scripted EBCP)                                           |

The 404 was caused by missing BFF proxies under `/api/admin/users/[id]/...`. Add the routes in §3 and the panel resolves.

> **Note on the legacy singular alias.** The backend still accepts `/v2/admin/user/<id>/context` (singular) for back-compat with older callers. **Do not write new code against it.** All BFF mounts, all client methods, all in-app links — plural only. This keeps URLs predictable and matches every other admin user-scoped route in the API (`/users/<id>/settings`, `/users/<id>/snippets`, `/users/<id>/timeline`, `/users/<id>/reset-baseline`).

---

## 2. Backend contract — exact request/response shapes

### 2.1 `GET /v2/admin/users/<user_id>/context`

Auth: `Authorization: Bearer <admin access_token>` (admin allowlist enforced server-side).

Response 200:

```jsonc
{
  "user": {
    "id": "uuid",
    "email": "string|null",
    "name": "string|null",

    // Free-text admin tools
    "custom_llm_instructions": "string|null",
    "private_admin_notes": "string|null",
    "queued_override_question": "string|null",   // injected as the next bot turn

    // Behavioral classification
    "behavioral_profile": "string|null",         // effective profile (override OR auto)
    "behavioral_profile_auto": "string|null",    // raw AI classification
    "behavioral_profile_source": "auto|admin_override",
    "coach_override_profile": "string|null",     // admin's manual override (null = use auto)

    // Inferred learner profile (derived from coaching attempts)
    "inferred_learner_profile": { /* opaque object */ } "|null",

    // Phase 9 admin override on the inferred learner profile
    "admin_profile_override_active": false,
    "admin_profile_override_set_at": "ISO8601|null"
  },
  "sessions": [    // newest first; ALL sessions, no pagination
    {
      "id": "uuid",
      "created_at": "ISO8601",
      "date": "12 May 2026",                      // pre-formatted display
      "score": "8.5/10" "|null",                  // KPI / 10, one decimal
      "status": "Pending Review|Completed",
      "summary": "KPI 78/100 · Sticky topic: pricing (62%)" "|null",
      "metrics": [
        { "label": "KPI",     "value": "78/100" },
        { "label": "WPM",     "value": "142" },
        { "label": "Fillers", "value": "3" },
        { "label": "Pause",   "value": "240ms" },
        { "label": "Dynamic", "value": "8.4dB" },
        { "label": "Pitch",   "value": "115" },
        { "label": "Energy",  "value": "0.62" },
        { "label": "Sticky topic", "value": "pricing (62%)" }
      ],
      "snippets": [
        {
          "id": "uuid|null",
          "turn_number": 1,
          "range": "0:00 - 0:42",                 // mm:ss - mm:ss
          "wpm": 142,
          "pitch": 115,
          "type": "charisma|stress|unlabeled",
          "status": "raw|saved|published|skipped",
          "admin_comment": "string|null",
          "ai_draft_admin_comment": "string|null",
          "follow_up_question": "string|null",
          "ai_draft_follow_up_question": "string|null",
          "transcript": "string|null",
          "is_skipped": false
        }
      ],
      "chat": [                                    // oldest first
        { "from": "bot",  "text": "Are you good at math?", "turn_number": 1, "snippet_id": "uuid|null" },
        { "from": "user", "text": "Yeah, I aced calc in college...", "turn_number": 1, "snippet_id": "uuid|null" }
      ]
    }
  ]
}
```

### 2.2 `PATCH /v2/admin/users/<user_id>/context`  *(PUT also accepted)*

Body — every field optional, only included keys are written. `null` clears. PATCH and PUT have identical semantics on this endpoint; **use PATCH in new code** to match REST convention for partial updates.

```jsonc
{
  "custom_llm_instructions": "string|null",
  "private_admin_notes": "string|null",
  "queued_override_question": "string|null",
  "coach_override_profile": "Stressor|Charismatic|...|null"
}
```

Response: same shape as `GET` so the page re-renders from one round-trip. Status 200.

### 2.3 `POST /v2/admin/users/<user_id>/reset-baseline`

No body required. Idempotent. Response 200:

```jsonc
{
  "status": "ok",
  "user_id": "uuid",
  "baseline_established": false,
  "baseline_established_at": null
}
```

Errors: `400 INVALID_INPUT` (bad UUID), `500 PERSIST_FAILED` (DB upsert failed), `500 V2_ERROR` (unexpected).

### 2.4 `POST /v2/public/interview/next-question` — `force_assessment` flag (already shipped)

Existing endpoint. New optional payload field: `force_assessment: boolean` (default `false`). When `true`, the user runs the scripted EBCP turns 1-4 *for this one session* even if `baseline_established=TRUE`. **Does not** flip the persistent flag — that is what `reset-baseline` is for.

Use cases:

- One-off: admin wants the next session of a returning user to be a recalibration → flip the toggle on the interview start screen, send `force_assessment: true`.
- Permanent: new microphone, new cohort, suspected acoustic drift → call the reset endpoint, the next session (and all sessions until they graduate again on turn 5) will run scripted EBCP.

Existing payload still accepted:

```jsonc
{
  "turn_number": 1,
  "user_id": "uuid|undefined",
  "previous_turns": [ { "question": "...", "transcript": "..." } ] "|undefined",
  "force_assessment": false
}
```

Response (unchanged): `{ question, tone, turn_number, source }` where `source` is one of `ebcp_llm | ebcp_fallback | llm_bypass_ebcp | llm_bypass_fallback | llm | fallback`.

---

## 3. Drop-in BFF route files (Next.js App Router)

These assume `src/app/api/getAuth.ts` exports `getV2AccessToken()` and `getBackendUrl()` exactly as in `docs/homework-bff-routes/getAuth.ts`. If your project keeps them elsewhere, fix the import paths.

### 3.1 `src/app/api/admin/users/[id]/context/route.ts`

```ts
/**
 * BFF: /api/admin/users/[id]/context
 * Proxies to GET/PATCH /v2/admin/users/<id>/context.
 * Backs the multi-session admin view at /admin/users/[id].
 */
import { NextRequest, NextResponse } from "next/server";
import { getV2AccessToken, getBackendUrl } from "@/app/api/getAuth";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const token = await getV2AccessToken();
  if (!token) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const { id } = await params;
  const backend = getBackendUrl();
  const res = await fetch(`${backend}/v2/admin/users/${id}/context`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const token = await getV2AccessToken();
  if (!token) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const { id } = await params;
  const body = await request.json().catch(() => ({}));
  const backend = getBackendUrl();
  const res = await fetch(`${backend}/v2/admin/users/${id}/context`, {
    method: "PATCH",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}
```

### 3.2 `src/app/api/admin/users/[id]/reset-baseline/route.ts`

```ts
/**
 * BFF: /api/admin/users/[id]/reset-baseline
 * Proxies to POST /v2/admin/users/<id>/reset-baseline.
 * Flips user_settings.baseline_established back to FALSE so the user
 * re-runs the scripted EBCP opener on their next session.
 */
import { NextRequest, NextResponse } from "next/server";
import { getV2AccessToken, getBackendUrl } from "@/app/api/getAuth";

export async function POST(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const token = await getV2AccessToken();
  if (!token) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const { id } = await params;
  const backend = getBackendUrl();
  const res = await fetch(
    `${backend}/v2/admin/users/${id}/reset-baseline`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    },
  );
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}
```

### 3.3 (Optional but recommended) verify these adjacent BFF routes exist

These backend routes already exist and are used by the same admin user page. If the panel still 404s after adding the two above, audit these too — every one needs a BFF proxy at the matching `/api/admin/...` path:

- `GET /v2/admin/users/<id>/settings` → `src/app/api/admin/users/[id]/settings/route.ts`
- `POST /v2/admin/users/<id>/settings`
- `GET /v2/admin/users/<id>/snippets` → `src/app/api/admin/users/[id]/snippets/route.ts`
- `GET /v2/admin/users/<id>/timeline` → `src/app/api/admin/users/[id]/timeline/route.ts`

Each follows the exact same forward-the-bearer-token pattern as 3.1/3.2 — copy and adjust path/method.

---

## 4. TypeScript client additions

### 4.1 Append these interfaces to `src/lib/api/admin-client.ts`

```ts
export interface AdminUserContextUser {
  id: string;
  email: string | null;
  name: string | null;
  custom_llm_instructions: string | null;
  private_admin_notes: string | null;
  queued_override_question: string | null;
  behavioral_profile: string | null;
  behavioral_profile_auto: string | null;
  behavioral_profile_source: "auto" | "admin_override";
  coach_override_profile: string | null;
  inferred_learner_profile: Record<string, unknown> | null;
  admin_profile_override_active: boolean;
  admin_profile_override_set_at: string | null;
}

export interface AdminUserContextSnippet {
  id: string | null;
  turn_number: number | null;
  range: string | null;            // "mm:ss - mm:ss"
  wpm: number | null;
  pitch: number | null;
  type: "charisma" | "stress" | "unlabeled";
  status: "raw" | "saved" | "published" | "skipped";
  admin_comment: string | null;
  ai_draft_admin_comment: string | null;
  follow_up_question: string | null;
  ai_draft_follow_up_question: string | null;
  transcript: string | null;
  is_skipped: boolean;
}

export interface AdminUserContextChatTurn {
  from: "bot" | "user";
  text: string;
  turn_number: number | null;
  snippet_id: string | null;
}

export interface AdminUserContextSession {
  id: string | null;
  created_at: string;
  date: string | null;             // "12 May 2026"
  score: string | null;            // "8.5/10"
  status: "Pending Review" | "Completed";
  summary: string | null;
  metrics: Array<{ label: string; value: string }>;
  snippets: AdminUserContextSnippet[];
  chat: AdminUserContextChatTurn[];
}

export interface AdminUserContextPayload {
  user: AdminUserContextUser;
  sessions: AdminUserContextSession[];   // newest first
}

export interface AdminUserContextUpdate {
  custom_llm_instructions?: string | null;
  private_admin_notes?: string | null;
  queued_override_question?: string | null;
  coach_override_profile?: string | null;
}

export interface ResetBaselineResponse {
  status: "ok";
  user_id: string;
  baseline_established: false;
  baseline_established_at: null;
}
```

### 4.2 Append these methods to the `adminApi` object

```ts
  // ── Phase 12 / 13 — Admin user multi-session view + EBCP reset ──
  getUserContext: (userId: string) =>
    adminFetch<AdminUserContextPayload>(`/users/${userId}/context`),

  updateUserContext: (userId: string, patch: AdminUserContextUpdate) =>
    adminFetch<AdminUserContextPayload>(`/users/${userId}/context`, {
      method: "PATCH",
      body: patch,
    }),

  resetBaseline: (userId: string) =>
    adminFetch<ResetBaselineResponse>(
      `/users/${userId}/reset-baseline`,
      { method: "POST" },
    ),
```

All three methods sit under the unified `/users/{id}/...` namespace. Use `PATCH` for partial updates of the context (matches REST convention for partial mutations).

---

## 5. UI work on the admin user-detail page

Target route: whichever page renders `/admin/users/[id]` (or `/admin/students/[id]` if that is your current convention — keep one canonical path).

Replace the existing call to `adminApi.getStudentProfile(id)` with `adminApi.getUserContext(id)` for the "user view" (the multi-session timeline). Keep `getStudentProfile` only if you still use the legacy speaker-profile editor — but the new payload already has the fields needed, so you can deprecate that fetch entirely once the new view ships.

### 5.1 Page sections to render (top → bottom)

1. **Header**: name + email + a small badge for `behavioral_profile_source` (`auto` → grey, `admin_override` → orange "Manual"). If `coach_override_profile` is set, show it; otherwise show `behavioral_profile_auto`.
2. **Admin tools card** (editable, debounced PATCH to `updateUserContext`):
   - `custom_llm_instructions` — textarea
   - `private_admin_notes` — textarea
   - `queued_override_question` — single-line input (helper text: "Will be injected as the next bot turn, then cleared")
   - `coach_override_profile` — segmented control (`null` / `Stressor` / `Charismatic` / etc — use whatever profile vocabulary your project already uses; `null` clears the override)
3. **Inferred learner profile card** (read-only): pretty-print `inferred_learner_profile`. If `admin_profile_override_active` is true, show a "Manual override active since {admin_profile_override_set_at}" pill. (The override editor itself lives elsewhere — `POST /v2/admin/users/<id>/learner-profile-override`. Out of scope for this prompt unless you already had a UI for it.)
4. **Danger zone card** — see §5.2.
5. **Sessions accordion** (newest first): one card per `sessions[i]`, header = `date` · `score` · `status` · `summary`. Expand to show `metrics` (chip row), then a chat-thread render of `chat[]`, then the `snippets[]` cards.

### 5.2 The "Reset baseline" danger-zone block

```tsx
import { useState } from "react";
import { adminApi } from "@/lib/api/admin-client";
import { toast } from "sonner";

function ResetBaselineButton({ userId, onDone }: { userId: string; onDone?: () => void }) {
  const [busy, setBusy] = useState(false);

  async function handleClick() {
    if (!window.confirm(
      "Reset this user's EBCP baseline?\n\n" +
      "Their NEXT session will start with the scripted opener " +
      "(\"Are you good at math?\" + 3 follow-ups) before handing off " +
      "to the LLM on turn 5.\n\n" +
      "Use this for: new microphone, new cohort, suspected acoustic drift."
    )) return;

    setBusy(true);
    try {
      const r = await adminApi.resetBaseline(userId);
      toast.success(
        `Baseline reset — next session will run scripted EBCP. ` +
        `(baseline_established=${r.baseline_established})`
      );
      onDone?.();
    } catch (e) {
      toast.error(`Reset failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-xl border border-destructive/40 bg-destructive/5 p-4">
      <h3 className="text-sm font-semibold text-destructive">Danger zone</h3>
      <p className="mt-1 text-sm text-muted-foreground">
        Force this user back into the scripted EBCP opener on their next
        session. Permanent until they graduate again on turn 5.
      </p>
      <button
        type="button"
        onClick={handleClick}
        disabled={busy}
        className="mt-3 rounded-md border border-destructive bg-destructive px-3 py-2 text-sm font-medium text-destructive-foreground hover:opacity-90 disabled:opacity-50"
      >
        {busy ? "Resetting…" : "Reset EBCP baseline"}
      </button>
    </div>
  );
}
```

After a successful reset, optionally re-fetch `getUserContext(userId)` so any "Phase 13 status" indicator you render in the user block stays in sync. (The current backend payload does **not** echo `baseline_established` on the user block — if you want that visible, file a follow-up to add it; until then, a toast confirming the reset is enough.)

### 5.3 Optional: one-shot "Force assessment" toggle on the interview start screen

This is **client-only** UI; no new BFF needed. Wherever the interview flow calls `POST /api/public/interview/next-question`, add a checkbox to the admin's preview/test screen ("Force scripted EBCP for this session") that, when checked, includes `force_assessment: true` in the request body. Do not surface this to end users — it is a coach-side debugging aid.

---

## 6. Acceptance criteria

The frontend agent is done when **all** of these are true:

- [ ] Visiting `/admin/users/<some_real_user_id>` no longer 404s and renders the page.
- [ ] The user card shows `email`, `name`, `behavioral_profile`, `behavioral_profile_source` badge.
- [ ] Editing `custom_llm_instructions`, `private_admin_notes`, `queued_override_question`, or `coach_override_profile` issues a `PATCH` to `/api/admin/users/<id>/context` and the new value persists across a page reload.
- [ ] The sessions accordion renders **all** of the user's sessions (newest first), each expandable to show metrics + chat + snippets.
- [ ] Clicking "Reset EBCP baseline" issues `POST /api/admin/users/<id>/reset-baseline`, returns 200, shows a success toast, and the next session that user records starts with the scripted EBCP opener (`source: "ebcp_llm"` or `"ebcp_fallback"` in the next-question response). Clicking it again on an already-reset user is harmless (idempotent 200).
- [ ] DevTools network tab shows **zero** 404s on the admin user page.

If any single endpoint still 404s, the most likely cause is the BFF route file is missing — every backend route in §1 needs a matching `src/app/api/admin/users/[id]/...` proxy.

---

## 7. Out of scope (do not change)

- The legacy `/v2/admin/students/<id>` endpoint and its frontend `getStudentProfile` consumers — that is a different (older) shape. The new view supplements, it does not replace, until you've migrated every caller.
- The interview LLM behavior itself (Phase 13 routing logic lives entirely server-side).
- The `force_assessment` plumbing through the public interview start flow if your end-user app does not currently expose this — leave it for a later coach-tools pass.

---

## 8. References (file paths in the backend repo for the agent to inspect)

- Backend route: `routes/v2_routes.py:776` — `v2_admin_user_context`, registered for **both** `/admin/user/<id>/context` and `/admin/users/<id>/context` with methods `GET, PUT, PATCH`. Use plural in new code.
- Backend route: `routes/v2_routes.py:881` — `v2_admin_reset_baseline` (POST only).
- Backend smart EBCP routing: `routes/v2_routes.py:10096` (`v2_public_interview_next_question`, `force_assessment` flag at line 10115).
- DB helpers: `services/db.py:7048` (`get_baseline_established`), `services/db.py:7075` (`mark_baseline_established`), `services/db.py:7104` (`reset_baseline_established`).
- Existing BFF auth helper to copy: `docs/homework-bff-routes/getAuth.ts`.
- Existing BFF route to mirror as a stylistic template: `docs/frontend-admin-panel/api-routes/students-[id]-overrides-route.ts`.
- Existing admin client to extend: `docs/frontend-admin-panel/lib/api/admin-client.ts`.
