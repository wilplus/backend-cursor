# Panel State Matrix

Shared contract between the frontend (input panel below the bubble thread) and
the backend (endpoints + auth gates) describing every input-panel scenario the
user can land in. The frontend uses this to derive `panelState` deterministically
from `(authState, surface, phase, server flags)`. The backend uses it to know
which surfaces each endpoint must serve and which auth gates apply.

When the matrix and the code disagree, the matrix is the authority — update the
matrix first, then the code (frontend and backend in parallel), then re-link
this doc from any prompt that depends on it.

---

## Preamble — `user_label` semantic (PIN; do not relax)

Throughout this matrix and the `POST /v2/chat/snippet-followup` endpoint, a
boolean `user_label` field means **agreement with the AI's existing
`coach_label` on the snippet**. It does NOT encode the binary
`charisma`/`stress` type.

  - `user_label = true`  ⇒ the user **agrees** with the AI/coach's existing
    `coach_label`. ("Yes, I see what you mean — that was indeed
    {charisma|stress}.")
  - `user_label = false` ⇒ the user **disagrees** with the AI/coach's existing
    `coach_label`. ("Actually, I don't think that was
    {charisma|stress}.")

The type (`charisma` vs `stress`) is encoded by `snippet.coach_label` /
`snippet.snippet_type` on the snippet row and never on the
`user_label` field. If we ever want to capture "user disagrees AND
proposes the opposite type" we'll add a separate `user_proposed_type`
field — we will not overload `user_label`.

The backend asserts this contract by returning
`debug.user_label_interpretation = "agreement"` on every response from
`/v2/chat/snippet-followup`. Frontend MAY assert on this field in dev to catch
drift. If the value is ever `"type"`, the contract has silently regressed and
both sides should fail loud.

---

## Endpoint contract — `POST /v2/chat/snippet-followup`

The frontend hits this endpoint after a user clicks
agree/disagree on a snippet labeling prompt.

**Auth:** `@require_auth`. Owner-scoped — the snippet's `user_id` must equal
the caller's `request.user_id`. Foreign snippets return `404 NOT_FOUND` (not
403) so we don't leak existence.

**Request body (JSON):**

```json
{
  "snippet_id": "<uuid>",
  "user_label": true | false
}
```

**Response 200 (JSON):**

```json
{
  "followup_text": "<one short conversational question, ≤2 sentences>",
  "debug": {
    "model": "gpt-4o-mini",
    "user_label_interpretation": "agreement"
  }
}
```

**Error responses:**
  - `400 INVALID_INPUT` — missing/malformed `snippet_id` or `user_label`
  - `404 NOT_FOUND` — snippet does not exist OR belongs to a different user
  - `422 SNIPPET_CONTEXT_UNAVAILABLE` — snippet exists & owned but lacks
    `admin_comment` (cannot prompt a coherent follow-up)
  - `500 V2_ERROR` — LLM failure, parse failure, etc. (Sentry-captured)

**Determinism:** strict JSON via `response_format={"type": "json_object"}`,
single-shot (no retry loop), `temperature=0.4` (we want some warmth, not
mechanical text). On any failure the endpoint returns 500 — the frontend
keeps the user's agree/disagree click captured locally and may retry.

---

## Row schema

| Column | Meaning |
| --- | --- |
| `row_id` | Stable identifier (`LO-` logged-out, `LI-` logged-in, `BP-` blind spot). |
| `scenario` | Plain-English description of the surface + phase the user is in. |
| `primaryControl` | What the panel's primary affordance is: `mic` \| `text` \| `buttons` \| `label` \| `send` \| `none`. |
| `textInputEnabled` | Whether the numeric/free-text input below is active. |
| `micEnabled` | Whether the mic button is mounted and clickable. |
| `paperclipVisible` | Whether the upload paperclip icon is rendered. |
| `notes` | Anything the panel-state machine needs to know that doesn't fit a column. |

---

## Logged-out (`LO-`) — anonymous / pre-signup surfaces

| row_id | scenario | primaryControl | textInputEnabled | micEnabled | paperclipVisible | notes |
| --- | --- | --- | --- | --- | --- | --- |
| LO-1 | Interview onboarding, cold start (first question) | `mic` | `false` | `true` | `false` | Voice-only by design; mic answers go to `/v2/public/interview/upload-answer`. |
| LO-2 | Interview onboarding, mid-conversation (turns 2..N-1) | `mic` | `false` | `true` | `false` | Same panel as LO-1; `guest_session_id` carries identity. |
| LO-3 | Interview onboarding, final turn → signup gate | `buttons` | `false` | `false` | `false` | Panel swaps to "Create account to continue" CTA. Mic disabled to prevent late audio after signup nav. |
| LO-4 | Anonymous Q&A (`BP-1`) — user asks freeform between turns | `none` | `false` | `false` | `false` | NOT a supported surface today. Panel must NOT silently accept input it can't route. See BP-1. |

## Logged-in (`LI-`) — authenticated coaching surfaces

| row_id | scenario | primaryControl | textInputEnabled | micEnabled | paperclipVisible | notes |
| --- | --- | --- | --- | --- | --- | --- |
| LI-1 | Pre-recording warmup / homework brief | `buttons` | `false` | `false` | `false` | "Start recording" CTA owns the panel. No text/mic until recording begins. |
| LI-2 | Active coaching session (recording in progress) | `mic` | `false` | `true` | `true` | Paperclip allowed for asynchronous file upload (e.g. reference clip). |
| LI-3 | Post-recording, awaiting admin review (`PENDING_COACH`) | `none` | `false` | `false` | `false` | Backend gate `PRIOR_SESSION_PENDING_REVIEW` (B2) rejects new uploads; panel reflects that. |
| LI-4 | Snippet labeling (agree/disagree on `coach_label`) | `label` | `false` | `false` | `false` | Two-button: Agree / Disagree → emits `user_label: bool` to `POST /v2/chat/snippet-followup`. See PIN above. |
| LI-5 | Snippet follow-up chat (after `user_label` capture) | `mic` | `false` | `true` | `false` | Bubble thread shows AI `followup_text`; user voice-replies. Reply capture is BE Prompt 2 (deferred). |
| LI-6 | Homework return state — user has a delivered assignment | `buttons` | `false` | `false` | `false` | "View assignment" CTA. No free input here. |
| LI-7 | Snippet playback / scrub | `none` | `false` | `false` | `false` | Panel stays quiet; transport controls are on the snippet card, not the panel. |

## Blind spots (`BP-`) — known surfaces the panel does NOT handle correctly today

| row_id | scenario | status | remediation owner | notes |
| --- | --- | --- | --- | --- |
| BP-1 | Anonymous Q&A — user types into an onboarding panel that has no input route | OPEN | FE + BE | Today the panel silently swallows clicks. Either render `primaryControl: none` (current matrix decision) OR ship an `/anon/qa` endpoint. Decided: keep `none` for v1. |
| BP-2 | `PENDING_COACH` double-upload — user starts a new recording while prior session is under review | **FIXED** in `7a6d516` | BE (shipped) | Backend gates `POST /v2/coaching/trial-recording` and `POST /v2/user/chat/upload-answer` with `409 PRIOR_SESSION_PENDING_REVIEW`. Frontend SHOULD also reflect this in LI-3 (panel = `none`) so the user never sees a 409 they can't avoid. |
| BP-3 | State machine `end=true` write-after-close — async transcript/summary arrives after the session has been marked complete | OPEN | BE | Write path must check session status before persisting; if closed, log and drop. Not a panel concern but documented here so FE doesn't surface a stale "we're still listening" state. |
| BP-4 | Paperclip per-turn flag UX — `show_upload_ui` will be added to interview endpoints (BE Prompt 1) but the latch semantics (sticky vs per-turn) aren't decided | DEFERRED | BE + product | Pending BE Prompt 1. Default for v1: `show_upload_ui = false` (paperclip hidden) on all `/v2/public/interview/*` responses. |
| BP-5 | Mid-onboarding resume — user closes the tab on LO-2 and returns hours later | OPEN | FE | Today: cold restart, no resume. Acceptable for v1. Document so we don't accidentally ship partial state without a resume path. |
| BP-6 | Stale signed URL on snippet playback (LI-7) | OPEN | BE | Signed URLs expire; the snippet card silently 404s mid-playback. Re-sign on demand via `/v2/snippets/<id>/playback-url` (not yet built). |

---

## How to add a row

1. Pick the prefix: `LO-` (logged-out), `LI-` (logged-in), or `BP-`
   (panel-state machine does NOT handle this yet — document it before shipping
   a fix so the frontend has something to point its TODO at).
2. Use the next free integer. Never renumber — row IDs are linked from prompts,
   tickets, and Sentry breadcrumbs.
3. If the row depends on a new backend endpoint or response field, also update
   the Endpoint contract section above and cross-link to the BE prompt that
   ships it.
4. Frontend `derive(panelState)` must have a unit test covering the new row.
