# What the frontend should know (homework flow)

Short reference for the frontend team. Backend contract and behavior that affects the UI.

---

## Paths and auth

- **BFF:** Call **`/api/homework/*`** (not `/api/homework/...` without `session`). Backend is **`/v2/homework/*`**. Example: **`POST /api/homework/session/start`** and **`GET /api/homework/session/status`** — the word **`session`** is required in the path.
- **Auth:** Send **`Authorization: Bearer <supabase_access_token>`** on every request. After login, use `supabase.auth.setSession({ access_token, refresh_token })` so backend and frontend stay in sync.

---

## Credits (homework)

Architecture the frontend should follow:

- **Balance:** `GET /api/homework/session/status` includes **`credits`** (integer). Present for **step 0** (`has_active_session: false`) and **while a session is active** (`has_active_session: true`). Default if unset in DB is **15** (server-side).
- **When credits change:** The backend deducts **5 credits once per completed homework session**, at the moment the session is marked **`completed`** and a **report** is created — **not** when the student calls **`POST .../session/start`**. Idempotency is enforced in the DB (`homework_credits_charged_at` on `v2_sessions`).
- **Starting a session:** **`POST .../session/start`** returns **402** with **`code: "INSUFFICIENT_CREDITS"`** only if **`credits <= 0`**. Any positive balance can start; **5 credits are removed on completion** (balance floors at 0), so e.g. **3 credits** is enough for one lesson (ends at 0). Body includes **`credits`** and **`message`**. No credits are subtracted on a successful start.
- **Abandoning:** **`POST .../session/<id>/abandon`** does **not** deduct credits (nothing was completed with a report).
- **UI guidance:** Show **`credits`** from the latest **status** response. After the report is ready / user returns to step 0, **refetch `GET session/status`** so the balance reflects the completion charge. Do **not** decrement credits in the client; treat the API as the source of truth.

---

## Step 0 (no active session)

- **`GET /api/homework/session/status`** returns `assigned_exercises`: `[ { id, title, video_url, description } ]`.
- The coach assignment video (`tutor_video_url`, `tutor_video_description`) is always returned when present — there is no hiding flag. Show it whenever it's in the response.
- **Display:** Show each exercise below the "Start homework" button. If **`video_url`** is present, show the video. If **`description`** is present, show it. The backend provides a default intro video for first-time users, so `video_url` can be present even for the "0-intro" exercise.
- There is **no countdown timer on step 0**.
- If `review_pending` is true, show the waiting message from `main_screen_message`. The student still sees the video if present.
- POST `session/start` is always allowed; there is no 409 SESSION_START_BLOCKED.

---

## Report screen

- **`GET /api/homework/session/<sessionId>/report`** returns (among other fields) **`report_cta`** (string, e.g. `"Finish the lesson and sign out"`). Use it as the **primary CTA button at the end of the report**.
- Below the primary CTA, show a **secondary action** in the same style as "Abandon session": **"Do your homework again"** — on click, call POST abandon → clear state → return to step 0.
- **After the primary CTA click:** Sign out and redirect to **`/logged-out`** with a sign-in CTA. No `leave-report` POST is needed (backend endpoint was removed).
- When the user signs in again, use **`GET /api/homework/session/status`** as the source of truth. Replace step-0 state from the status JSON — do **not** shallow-merge stale report state. Clear report sessionStorage/localStorage keys. Reference helper: **`docs/homework-bff-routes/homeworkApplyStep0State.ts`**.
- Report payload also includes: `report_text`, `scores`, `final_recording`, `performance_history`, optional `recording` (transcript, fillers, `audio_url`), `context_short`, `coach_insight`, `admin_grade`, and `report_comment`. When the session is still generating, backend returns **409** with `REPORT_NOT_READY` — poll until 200.
- When the session becomes `completed`, show the reviewing/report screen and hide any tutor video block.

---

## Emails

The student receives **one email** from the system related to homework:

- **New homework available** (`StudentNewHomework`) — sent by the backend when the coach triggers send-assignment. This is the signal to the student that new homework is ready.

There is **no** student completion email after submitting homework. The waiting screen at `/logged-out` is the only post-lesson feedback the student sees until the coach sends the next assignment.

---

## Status-driven flow

- Use only the **top-level `status`** from the API. Possible values: `none`, `recording_1_required`, `report_generating`, `completed`. Don't rely on raw DB status.
- Live flow: **step 0** (`none`) → **recording** (`recording_1_required`) → **report** (`completed`). Steps 2–4 are temporarily removed from the live flow (backed up in `docs/TEMPORARY-REMOVED-STEPS-2-3-4-BACKUP.md`).
- Flow can skip states (e.g. after recording 1 → `report_generating` then `completed`). Derive the displayed step from `status` and handle all values.

---

## Quick checklist

| Item | Backend returns | Frontend |
|------|-----------------|----------|
| Step 0 video | `assigned_exercises[].video_url`, `description`; `tutor_video_url`, `tutor_video_description` | Show video + description when present. Always show — no hiding flag. |
| Step 0 state | `assigned_exercises`, optional `tutor_video_description`, `review_pending`, `main_screen_message` | Normal no-active-session state; no countdown timer. |
| End of report — primary CTA | `report_cta` (e.g. "Finish the lesson and sign out") | Show as primary button; on click sign out → `/logged-out`. |
| End of report — secondary action | (hardcoded in frontend) | "Do your homework again" — same style as abandon; calls POST abandon → step 0. |
| Paths | `/v2/homework/session/start`, `.../session/status`, `.../session/<id>/report` | BFF must use **session** in path (e.g. `/api/homework/session/start`). |
| Credits | `credits` on **GET session/status**; **402** `INSUFFICIENT_CREDITS` on **POST session/start** if **`credits <= 0`** | Display from API only; refetch after completion; −5 on completion (not at start). |

More detail: **`docs/APPLICATION-STATE.md`** (§3.5, §3.6), **`docs/FRONTEND-VIDEO-AND-DESCRIPTION.md`**, and **`.cursor/rules/architecture-taskmaster.mdc`**.
