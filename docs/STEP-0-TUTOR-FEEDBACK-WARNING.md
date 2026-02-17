# Step 0: show tutor feedback deadline warning

When the user has **no active session** and has **recently completed** a lesson (and the coach has not yet sent new homework), the backend includes a deadline and a ready-to-display message so the step 0 screen can show a warning.

## API

**GET /v2/homework/session/status** (when `has_active_session === false`):

- **tutor_feedback_deadline** (optional): ISO 8601 string, e.g. `"2026-02-18T15:00:00Z"`.
- **tutor_feedback_message** (optional): User-facing string, e.g.  
  `"Your coach has until 18 Feb 2026, 15:00 UTC to review your last lesson and send you new homework."`

Same fields can appear in:

- **POST /v2/homework/session/:id/post-answers** (success response).
- **GET /v2/homework/session/:id/report** (when session is completed and tutor hasn’t sent feedback).

## Frontend

On the **step 0 screen** (no active session, “start” / warm-up entry):

1. After calling `GET .../session/status`, check for `tutor_feedback_message` in the response.
2. If present, show it in an info/warning banner (e.g. above the “Start” or warm-up area).
3. Optionally use `tutor_feedback_deadline` for a countdown or formatted date.

If you don’t render `tutor_feedback_message`, the user will not see any warning on the step 0 screen.

## When the message is omitted

- User has an active session.
- User has never completed a lesson.
- Coach has already sent feedback (e.g. via “Send homework” in admin); then `tutor_feedback_sent_at` is set and the deadline is no longer returned.
- The deadline has already passed (window after completion has elapsed).
