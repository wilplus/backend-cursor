# Frontend implementation prompt: Video URL and description

**Copy this prompt into Cursor (or give it to your frontend dev) to implement the video + description feature. Full spec: `docs/FRONTEND-VIDEO-AND-DESCRIPTION.md` in the backend repo.**

---

## Prompt (copy from here)

You are implementing the **video URL and description** feature for the willab homework flow. The backend is already done: it accepts optional `video_url` and `video_description` when the admin sends an assignment, stores them on the session, and returns `tutor_video_url` and `tutor_video_description` in the session object from GET session/status.

Your tasks:

### 1. Admin: Send assignment with optional video and description

- **Where:** On the same screen/modal where the admin clicks “Send assignment” (or “Send homework”) for a student — e.g. student profile, Homework section.
- **Add two optional inputs:**
  - **Video URL (optional)** — single-line text input. Admin pastes a link (Loom, YouTube, etc.). Validate: must start with `http://` or `https://`, max 2048 characters (or rely on backend 400).
  - **Video description (optional)** — textarea. Short message to the student. Max 2000 characters (show counter or rely on backend 400).
- **On “Send assignment” click:**
  - If both are empty: call the API as today (no body or empty body).
  - If either has a value: send a JSON body in the POST, e.g. `{ "video_url": "...", "video_description": "..." }`. Omit keys that are empty.
- **BFF:** The route that proxies to `POST /v2/admin/students/<id>/send-assignment` must **forward the request body** to the backend. Do not strip or rename `video_url` or `video_description`. Handle 400 responses (e.g. INVALID_VIDEO_URL, INVALID_VIDEO_DESCRIPTION) and show the error message to the admin.

### 2. Student: Show video and description on the homework page

- **Data:** The session object from **GET session/status** (and after session/start) now includes:
  - `tutor_video_url?: string | null` — link to the coach’s video.
  - `tutor_video_description?: string | null` — optional message from the coach.
- **Types:** Add these two fields to your session type. Keep them in state wherever you store the current session.
- **When to show:** Only when `session.tutor_video_url` is non-empty (after trim). If only description were set without URL, the backend won’t send it for the student flow; so always key off `tutor_video_url`.
- **Where to show:** Pick one place and keep it consistent:
  - **Option A:** At the top of the homework flow (above warm-up / record) when there is an active session with a video.
  - **Option B:** On step 0 (no active session), e.g. “Your coach left you a message” + video + description, then “Start homework”.
  - **Option C:** On the report step (step 5) as “Message from your coach”.
- **Layout:**
  - If `tutor_video_description` is non-empty, show it **above** the video link (plain text; no HTML from backend).
  - Show a **“Watch video”** link with `href={session.tutor_video_url}`, `target="_blank"`, `rel="noopener"`. Optionally embed (e.g. YouTube iframe) if you detect the domain; a link is sufficient.
- Do not change the rest of the homework flow (status-driven, status, or other API contracts).

### 3. Checklist before you’re done

- [ ] Admin has two optional inputs (Video URL, Video description) and can send assignment with one or both.
- [ ] BFF forwards the POST body to the backend; 400 errors are shown to the admin.
- [ ] Session type includes `tutor_video_url` and `tutor_video_description`.
- [ ] Student sees the video block (description + “Watch video” link) in one clear place when the session has `tutor_video_url`.

**Reference:** Full spec with rules and examples: `docs/FRONTEND-VIDEO-AND-DESCRIPTION.md` (in the backend repo). Backend contract: POST send-assignment body optional `{ video_url?, video_description? }`; GET session/status returns session with `tutor_video_url`, `tutor_video_description` when set.

---

*(End of prompt)*
