# Frontend: Video URL and Description — What to Build

This doc explains what the **frontend** needs to do so admins can attach a video (and optional description) to homework, and students can see both on the homework page.

---

## 1. Admin: Sending the assignment with video and description

### Where

On the screen where the admin sends homework to a student (e.g. student profile, “Homework” or “Send assignment” section). Same place as the existing “Send assignment” (or “Send homework”) button.

### New UI

Add **two optional inputs** (both can be empty):

| Field | Type | Label (suggestion) | Rules |
|-------|------|--------------------|--------|
| **Video URL** | Single-line text input | “Video URL (optional)” | Admin pastes a link (e.g. Loom, YouTube, Supabase Storage). Backend accepts only `http://` or `https://`, max 2048 chars. |
| **Video description** | Textarea or multi-line input | “Message to student (optional)” or “Video description (optional)” | Short message from the coach (e.g. “Focus on pacing this week”). Backend accepts max **2000 characters**. |

- Both are optional. Admin can send:
  - No video, no description (current behaviour).
  - Only video URL.
  - Video URL + description (recommended when a video is sent).
- You can show the description field only when a video URL is filled, or always show both.

### What to send to the backend

When the admin clicks **Send assignment**:

- **If both inputs are empty**  
  Call the API as you do today (no body, or empty body). No change to existing behaviour.

- **If at least one has a value**  
  Send a **JSON body** in the POST:

```json
{
  "video_url": "https://loom.com/share/abc123",
  "video_description": "Focus on keeping a steady pace in the first minute."
}
```

- Send only the keys that have a value (e.g. omit `video_description` if the admin left it empty).
- Backend:
  - **POST** path: same as now, e.g. `POST /api/admin/students/[id]/send-assignment` (your BFF then proxies to `POST /v2/admin/students/<id>/send-assignment`).
  - Validates `video_url` (must be http/https, max 2048 chars) and `video_description` (max 2000 chars). Returns 400 with a clear error if invalid.

### BFF

Your Next.js (or other) API route that proxies to the backend must **forward the request body** to the backend. So when the frontend sends `{ "video_url": "...", "video_description": "..." }`, the BFF should pass that same body to the Flask backend. Do not strip or rename these fields.

---

## 2. Student: Seeing the video and description on the homework page

### Where the data comes from

- After the student **starts** (or resumes) homework, the backend attaches the coach’s video (and description) to the **current session**.
- You already get the session from **GET session/status** (or equivalent). The backend now includes two extra fields on the **session** object when they exist:

| Field | Type | Meaning |
|-------|------|--------|
| `tutor_video_url` | `string \| null` | Link to the coach’s video (e.g. Loom, YouTube). |
| `tutor_video_description` | `string \| null` | Optional short message from the coach about the video. |

- If the admin didn’t send a video, both will be `null` or missing. If they sent only a URL, `tutor_video_url` is set and `tutor_video_description` may be `null`.

### Where to show it in the UI

- Show the video block only when **`session.tutor_video_url`** is non-empty (e.g. after trimming).
- **Place:** One clear place per assignment is enough, for example:
  - **Option A:** At the top of the homework flow (e.g. above “Warm-up” or “Record”) when there is an active session with a video.
  - **Option B:** On the “no active session” / step 0 screen, e.g. “Your coach left you a message” with the video and description, then “Start homework”.
  - **Option C:** On the report step (step 5) as “Message from your coach”.
- Pick one and keep it consistent so the student sees the message once per homework.

### How to show video and description

1. **Description**
   - If `session.tutor_video_description` is non-empty, show it **above** (or beside) the video link.
   - Treat it as plain text (or simple markdown if you support it). No need to allow HTML from the backend; it’s stored as plain text.

2. **Video**
   - **If it’s a page URL** (Loom, YouTube, etc.): show a **“Watch video”** link that opens `session.tutor_video_url` in a new tab (`target="_blank"`, `rel="noopener"`). Optionally you can try embedding (e.g. YouTube iframe) if you detect the domain; otherwise a link is enough.
   - **If it’s a direct video file URL:** you can use a `<video>` tag with `src={session.tutor_video_url}` or again a “Watch / download” link.

Suggested layout when both are present:

```
[Optional: tutor_video_description shown here as a short paragraph or block of text]

Watch video →  (link to tutor_video_url)
```

If only the URL is set, show only the “Watch video” link.

### TypeScript / state

- In your session type (from GET session/status), add:
  - `tutor_video_url?: string | null`
  - `tutor_video_description?: string | null`
- When you store the session in state (e.g. after GET session/status or after session/start), keep these two fields so the component that renders the “coach message” block can read them.

---

## 3. Summary checklist for frontend

- [ ] **Admin:** Two optional inputs — “Video URL” and “Video description” (max 2000 chars).
- [ ] **Admin:** On “Send assignment”, send `video_url` and/or `video_description` in the POST body when non-empty; BFF forwards body to backend.
- [ ] **Student:** Session type includes `tutor_video_url` and `tutor_video_description`.
- [ ] **Student:** When `session.tutor_video_url` is set, show a “Watch video” link (and optionally embed); when `session.tutor_video_description` is set, show it above or beside the link.
- [ ] **Student:** Video block appears in one clear place (e.g. top of flow or step 0 or report step).

No change to the rest of the homework flow (status-driven, status, or other API contracts). The backend already returns `tutor_video_url` and `tutor_video_description` in the session from GET session/status once the migrations are applied.
