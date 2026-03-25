# What the frontend should know (homework flow)

Short reference for the frontend team. Backend contract and behavior that affects the UI.

---

## Paths and auth

- **BFF:** Call **`/api/homework/*`** (not `/api/homework/...` without `session`). Backend is **`/v2/homework/*`**. Example: **`POST /api/homework/session/start`** and **`GET /api/homework/session/status`** — the word **`session`** is required in the path.
- **Auth:** Send **`Authorization: Bearer <supabase_access_token>`** on every request. After login, use `supabase.auth.setSession({ access_token, refresh_token })` so backend and frontend stay in sync.

---

## Step 0 (no active session)

- **`GET /api/homework/session/status`** returns **`video_shown`**: `0` | `1`. **`0`** = hide coach assignment video (waiting UX); **`1`** = allow showing **`tutor_video_url`** when present. See **`docs/VIDEO_SHOWN-CONTRACT.md`**.
- Same response includes **`can_start_homework`**: when **`false`**, **do not** call **`POST .../session/start`** on page load (or right after leaving the report). Wait until **`true`** (coach sent assignment / feedback). If you auto-call start when there is no active session, the waiting screen will flash and jump straight to the recording step. **`POST start`** returns **409** `SESSION_START_BLOCKED` while waiting.
- Same endpoint returns **`assigned_exercises`**: `[ { id, title, video_url, description } ]`.
- **Display:** Show each exercise below the “Start homework” button. If **`video_url`** is present, show the video (link or embed, e.g. Vimeo). If **`description`** is present, show it (e.g. above or beside the video). The backend now provides a **default intro video** for first-time users when the DB has none, so `video_url` can be present even for the default “0-intro” exercise — don’t show “No video for this exercise” when `video_url` is in the response.
- There is **no countdown timer on step 0** anymore.

---

## Report screen

- **`GET /api/homework/session/<sessionId>/report`** returns (among other fields) **`report_cta`** (string). Use it as the **main CTA at the end of the report**, e.g. **“Send the homework to the coach!”**.
- **After the CTA:** Call **`POST /api/homework/session/<sessionId>/leave-report`** (BFF → **`POST /v2/homework/session/<id>/leave-report`**). When that returns **success or 404**, **sign out** and redirect to **`/logged-out`** with a sign-in CTA. The CTA **does not** send the user back to step 0 / a waiting dashboard state (`/dashboard?homeworkState=waiting`). Backend does not need changes for this UI-only behavior.

> **Note for backend:** Frontend behavior changed: the report CTA no longer returns the user to the step 0 waiting screen. It still sends **`leave-report`**, then logs the user out and redirects to **`/logged-out`** with a sign-in CTA.

- When the user **does** open homework while signed in (e.g. after signing in again), use **`GET /api/homework/session/status`** as the source for waiting / video / `can_start_homework`. **Replace** step‑0 state from the status JSON — do **not** shallow-merge stale report state. Clear report **sessionStorage/localStorage** keys when appropriate. Reference helper: **`docs/homework-bff-routes/homeworkApplyStep0State.ts`**.
- Report payload also includes: `report_text`, `scores`, `final_recording`, `performance_history`, optional `recording` (transcript, fillers, `audio_url`), `context_short`, `coach_insight`, `admin_grade`, and `report_comment`. When the session is still generating, backend returns **409** with `REPORT_NOT_READY` — poll until 200.
- When the session becomes `completed`, show the reviewing/report screen and hide any tutor video block. The video is only for step 0 / in-progress homework, not the completed state.

---

## Status-driven flow

- Use only the **top-level `status`** from the API. Possible values: `none`, `recording_1_required`, `report_generating`, `completed`. Don’t rely on raw DB status.
- Flow can skip steps (e.g. after recording 1 → `report_generating` then `completed`). Derive the displayed step from `status` and handle all values.

---

## Quick checklist

| Item | Backend returns | Frontend |
|------|-----------------|----------|
| Step 0 video | `assigned_exercises[].video_url`, `description` | Show video + description when present; default intro video is now provided by backend. |
| Step 0 state | `assigned_exercises`, optional `tutor_video_description` | Show the normal no-active-session state; there is no countdown timer. |
| End of report | `report_cta` (e.g. “Send the homework to the coach!”) | Show as primary CTA; on click POST `leave-report`, then sign out → `/logged-out`. |
| Paths | `/v2/homework/session/start`, `.../session/status`, `.../session/<id>/report` | BFF must use **session** in path (e.g. `/api/homework/session/start`). |

More detail: **`docs/APPLICATION-STATE.md`** (§3.5, §3.6), **`docs/FRONTEND-VIDEO-AND-DESCRIPTION.md`**, and **`.cursor/rules/architecture-taskmaster.mdc`**.
