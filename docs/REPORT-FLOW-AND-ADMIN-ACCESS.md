# Report flow, transcript, coach insight, and admin access

Tracing the recording upload, transcript generation, admin access, and where the "coach has 24h" and AI messages are set.

---

## 1. Why you only see “coach has 24h” (no AI message)

The report UI is built to show:

- **AI text:** `reportData.coach_insight` (optional “2-sentence coach insight” from the backend).
- **Fallback:** if that’s empty, it shows:  
  `"Your coach has 24 hours to analyse your practice and send a feedback on your email!"`

So:

- The **frontend** always has a message to show (either AI or 24h).
- If you **only** see the 24h text, it means the backend is **not** sending `coach_insight` in the report (or it’s empty/null).

**Conclusion:** No AI message = backend is not populating (or not generating) `coach_insight` in the GET report response. The 24h copy is just the frontend fallback when `coach_insight` is missing.

---

## 2. Why the transcript is missing or incomplete

The frontend takes the transcript from the **report** API, not from the raw recording upload:

- Preferred: `reportData.recording.transcription_text`
- Fallback: `reportData.transcript` (legacy)

So:

- **Full transcript** = backend must put the full transcription in one of those fields in the **GET report** response.
- **No transcript / partial transcript** = either:
  - The backend never runs transcription for this recording, or
  - It runs it but doesn’t put the result in `recording.transcription_text` (or `transcript`), or
  - The report is returned before transcription (or full transcription) is ready.

**Conclusion:** Transcript issues are backend-side (when and how transcription is run and what is returned in the report).

---

## 3. Why the recording isn’t “sent” to the admin / admin can’t play it

From the frontend’s side:

- When the user reaches the **report step (step 5)**, the app calls **`notifyLessonComplete(sessionId)`** (and retries a few times). That hits:
  - `POST /api/homework/session/{sessionId}/notify-lesson-complete`
  - which is intended to tell the backend: “lesson is done, report is there, notify the admin (e.g. email).”
- The **student report UI** gets the playback URL from the **report**:
  - `reportData.final_recording.audio_url` or  
  - `reportData.recording.audio_url` or  
  - `reportData.recording_1.audio_url`

So:

- **Admin can play** only if:
  1. The backend stores the recording and links it to the session/report, and
  2. The **admin UI** gets that same recording (e.g. via an admin report/session API that returns an `audio_url` or a playback URL for that session).

If the admin can’t play:

- Either the **backend** doesn’t:
  - persist the recording in a place the admin API can use, or
  - return an `audio_url` (or equivalent) in the admin report/session response,
- Or the **admin UI** doesn’t call the right endpoint or doesn’t show the playback link.

**Conclusion:** “Recording not sent to admin” / “admin can’t play” is either backend (storage + admin API) or admin UI (using that API and showing the link).

---

## 4. Important: flow is “record once → report” (steps 2–4 skipped)

In the code, **all of** `task_block`, `final_task_ready`, and `post_questions` are mapped to **step 5** (report). So:

- After the user uploads **recording_1**, the backend returns something like `status: "task_block"` (with optional `task_block`).
- The frontend then **immediately** goes to **step 5** (report). There is **no** metric-answers step, **no** recording_2 step, and **no** post-questions step in the UI.

So from the frontend’s point of view:

- Only **recording_1** is ever uploaded.
- The “full” report (transcript, AI insight, playback) is expected to be generated from that **one** recording.

If the backend was originally built for a longer flow (e.g. “report only after recording_2” or “after post_answers”):

- It might still be **waiting for recording_2 or post_answers** before it runs transcription + full report + coach insight + admin notification.
- In that case it might return a **minimal or empty report** (or 404 for a while), and the frontend would show:
  - No transcript (or partial),
  - No AI message (so only the 24h fallback),
  - And the admin might never get a proper link to the recording.

**Conclusion:** The mismatch is likely backend: it must treat “recording_1 uploaded + status task_block” as “lesson complete” and then run the **full pipeline** (transcribe, build report, set `coach_insight`, set `recording.transcription_text` / `transcript`, attach `audio_url`, and notify admin / expose the recording to the admin API).

---

## 5. Summary

| What you see | Cause (from frontend + contract) |
|--------------|----------------------------------|
| Only “coach has 24h”, no AI message | Backend not returning (or not generating) `coach_insight` in GET report. |
| No or partial transcript | Backend not returning full (or any) `recording.transcription_text` or `transcript` in GET report. |
| Recording not “sent” / admin can’t play | Backend: either not storing/linking the recording for admin, or not returning an `audio_url` in the admin report/session API; or admin UI not using it. |
| Flow feels wrong | Frontend goes straight to report after recording_1; backend must support this “single recording → full report” flow. |

**Bottom line:** The behavior described is **fully consistent with the backend not yet supporting the current frontend flow** (one recording → full report + transcript + coach insight + admin playback). Fixing it requires backend (and possibly admin UI) changes: run transcription and report generation as soon as recording_1 is in, and populate `coach_insight`, `recording.transcription_text` (or `transcript`), and `audio_url`, and ensure the admin can access that recording (e.g. via notify-lesson-complete and the admin report/session API).
