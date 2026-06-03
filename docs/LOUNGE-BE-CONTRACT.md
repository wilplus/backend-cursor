# Lounge BE Contract

The backend contract for the **Lounge** — the post-signup single-thread
`/chat` surface (FAQ + waiting + snippet-review loop). Every shape below
was pulled verbatim from `routes/v2_routes.py`, not from memory. When the
code and this doc disagree, the code wins — update this doc in the same PR
that changes a shape.

**Auth:** every endpoint here is `@require_auth` (Bearer JWT). Missing /
invalid token →
`401 {"code": "UNAUTHORIZED", "error": "Missing Authorization header"}`
(from the auth decorator).

**Two burns to watch on this surface** (see end of doc for detail):
1. `session-state` REVIEW_LOOP-only keys are *absent*, not null, in the
   other two states.
2. `snippet-followup` `422 SNIPPET_CONTEXT_UNAVAILABLE` is a normal state,
   not an error to toast.

---

## 1. `GET /v2/chat/session-state` — the router. Call FIRST on /chat load.

Tells the FE which mode to render. **No request body.**

### 200 — three shapes by `state`

```jsonc
// NO_SESSION — fresh signup, never recorded → route into onboarding
{
  "state": "NO_SESSION",
  "session_id": null,
  "created_at": null,
  "results_published_at": null
}

// PENDING_COACH — recorded, admin hasn't published → render waiting/FAQ chat.
// /v2/chat/query is fully usable in this state.
{
  "state": "PENDING_COACH",
  "session_id": "<uuid>",
  "created_at": "<iso8601>",
  "results_published_at": null
}

// REVIEW_LOOP — published → drop into snippet-review chat, snippets inline
{
  "state": "REVIEW_LOOP",
  "session_id": "<uuid>",
  "created_at": "<iso8601>",
  "results_published_at": "<iso8601>",
  "snippets": [
    {
      "id": "<uuid>",
      "snippet_type": "charisma" | "stress" | "unlabeled",
      "admin_comment": "string | null",
      "audio_url": "string | null",
      "transcript": "string | null",
      "turn_number": "number | null",
      "question_text": "string | null",
      "question_tone": "string | null",
      "start_offset_ms": "number",        // defaults to 0, never null
      "duration_ms": "number | null",
      "metrics": {
        "wpm": "number|null", "fillers": "number|null", "pause_ms": "number|null",
        "dynamic_db": "number|null", "pitch_center": "number|null", "energy": "number|null"
      }
    }
  ],
  "kpi_score": "number | null",
  "charisma_profile": "object | null",
  "ai_summary": "string | null"
}
```

### Errors
- `500` → `{"code": "V2_ERROR", "error": "Failed to evaluate session state"}`

> ⚠️ `snippets`, `kpi_score`, `charisma_profile`, `ai_summary` are present
> **only** when `state == "REVIEW_LOOP"`. In NO_SESSION / PENDING_COACH they
> are absent (destructuring yields `undefined`, not `null`).

---

## 2. `POST /v2/chat/query` — the chat turn. Dual-mode (JSON or multipart).

### Request — JSON path (text only)
```jsonc
{
  "question": "string (required)",
  "history": [ { "role": "user" | "assistant", "content": "string" } ]   // optional
}
```

### Request — multipart path (text + casual-voice audio)
`Content-Type: multipart/form-data`, form fields:

| field | type | required | notes |
| --- | --- | --- | --- |
| `question` | str | yes | same semantics as JSON |
| `history` | JSON-stringified array | no | bad JSON is silently dropped |
| `audio_file` | webm/opus blob | no* | *required to trigger casual-voice DSP |
| `transcript_source` | `"web_speech"` \| `"server_whisper"` | no | default `"web_speech"` |
| `audio_duration_sec` | float | no | hint only |

### 200 — identical shape for both paths
```jsonc
{
  "answer": "string",
  "show_upload_ui": "boolean",   // per-turn: reveal upload dropzone
  "show_record_ui": "boolean",   // per-turn: reveal in-app mic
  "debug": { }                   // opaque; do not render
}
```
`show_upload_ui` and `show_record_ui` are **mutually exclusive** — at most
one true per turn. Both are per-turn signals; do NOT cache across turns.

### Errors
- `400` → `{"code": "INVALID_INPUT", "error": "question must be a non-empty string"}`
- `500` → `{"code": "V2_ERROR", "error": "Chat query failed"}`

> ⚠️ The audio side is fire-and-forget. The response never waits on or
> reports DSP. A bad audio blob still returns a normal 200 with the answer.
> There is no audio-acknowledgement field.

---

## 3. `POST /v2/chat/snippet-followup` — after user agrees/disagrees with a label.

### Request
```jsonc
{
  "snippet_id": "<uuid> (required)",
  "user_label": true | false        // MUST be bool — AGREEMENT semantic (see below)
}
```

### 200
```jsonc
{
  "followup_text": "string",
  "debug": { "model": "gpt-4o-mini", "user_label_interpretation": "agreement" }
}
```

### Errors
- `400` → `{"code": "INVALID_INPUT", "error": "snippet_id must be a valid UUID"}`
- `400` → `{"code": "INVALID_INPUT", "error": "user_label must be a boolean (agreement semantic)"}`
- `404` → `{"code": "NOT_FOUND", "error": "Snippet not found"}` (also fires on foreign-owner — no 403, avoids existence leak)
- `422` → `{"code": "SNIPPET_CONTEXT_UNAVAILABLE", "error": "Snippet has no admin_comment yet"}`
- `500` → `{"code": "V2_ERROR", ...}`

> ⚠️ `user_label` is the **agreement** semantic, NOT the type.
> `true` = "I agree with the coach's label." `false` = "I disagree."
> It is NOT `"charisma"` / `"stress"`.
> `debug.user_label_interpretation` is a permanent canary pinned to
> `"agreement"` — the FE-04 probe asserts exactly that string. Six
> mutual trip-wires defend this (3 BE, 3 FE); do not change it without
> a coordinated ping + matrix-doc update.

> ⚠️ The `422 SNIPPET_CONTEXT_UNAVAILABLE` is a **normal state** (admin
> labeled the type but didn't write a comment), not an error to toast.
> Suppress the follow-up bubble gracefully; don't surface "something went
> wrong."

---

## 4. `POST /v2/user/snippets/<snippet_id>/label` — record the binary self-label.

### Request — bool required, EITHER key accepted
```jsonc
{ "label": true | false }
// or, alias (kept in sync with snippet-followup's body shape):
{ "user_label": true | false }
// if both present, "label" wins
```

### 200
```jsonc
{
  "status": "ok",
  "snippet_id": "<uuid>",
  "user_charisma_label": "boolean",
  "user_charisma_label_set_at": "<iso8601>"
}
```

### Errors
- `400` → `{"code": "INVALID_INPUT", "error": "label (or user_label) must be a boolean (true or false)"}` (strings like `"charisma"` rejected)
- `404` → `{"code": "NOT_FOUND", "error": "Snippet not found or not owned by user"}`
- `500` → `{"code": "V2_ERROR", ...}`

---

## 5. `POST /v2/coaching/intro-bubble` — intro line for the new recording session.

### Request
```jsonc
{ "snippet_id": "<uuid> (required)" }
```

### 200 — ALWAYS 200 on a valid+owned snippet (fallback contract)
```jsonc
{
  "intro_text": "string",   // always present, always non-empty
  "debug": {
    "model": "gpt-4o-mini",
    "prompt_version": "coaching_intro_v1",
    "source": "directives_queue" | "llm" | "static_fallback"
  }
}
```

### Errors — only input / ownership, never generation
- `400` → `{"code": "INVALID_INPUT", "error": "snippet_id must be a valid UUID"}`
- `404` → `{"code": "NOT_FOUND", "error": "Snippet not found"}`

> ⚠️ This endpoint **never returns 5xx for LLM problems** — on any
> generation failure it falls back to a static string and returns 200.
> `intro_text` is always present and non-empty on a 200. Do NOT build a
> "generation failed" branch; there isn't one. `debug.source` tells you
> whether the line came from an admin-authored directive
> (`directives_queue`), the LLM (`llm`), or the static fallback
> (`static_fallback`) — for dev visibility only.

---

## 6. `GET` / `PUT /v2/user/sharing-consent` — the four consent flags.

### GET — no body. 200:
```jsonc
{
  "has_answered": "boolean",     // true if ANY of the four is non-null
  "mic_consent":   "true | false | null",
  "share_consent": "true | false | null",
  "email_consent": "true | false | null",
  "terms_consent": "true | false | null"
}
```
`null` = not yet answered (show the prompt for that slot). `true`/`false`
= answered.

### PUT — body is any subset of the four flags, each bool:
```jsonc
{ "mic_consent": true }   // or any combination of the 4 canonical keys
```
**200:** same shape as GET (post-write state echoed back).

### Errors
- `400` → `{"code": "INVALID_INPUT", "error": "<field> must be a boolean or null"}`
- `400` → `{"code": "INVALID_INPUT", "error": "Body must include at least one of: mic_consent, share_consent, email_consent, terms_consent"}`

> ⚠️ The legacy `opt_in` key was removed (Week-1 cleanup). If you still
> send it, it's silently ignored (logged server-side). Use `share_consent`
> directly.

---

## Adjacent endpoints (not strictly Lounge but in the same flow)

These power the recording handoff out of the Lounge. Documented briefly so
the FE has the full loop; full contracts live in their handler docstrings.

### `POST /v2/user/chat/upload-answer` — post-labeling recording upload
Multipart: `audio_file` (required), `source_snippet_id` (optional UUID),
`intent` (optional free-text), `question_text` (optional).
**201** → `{status: "ok", session_id, recording_id, session_status: "processing", acoustic_metrics: {...}, finalize: {...}}`.
**409** → `{code: "PRIOR_SESSION_PENDING_REVIEW", error: "...", pending_session_id}` (B2 gate — user has another session under review).

### `POST /v2/user/chat/first-question` — opening question for contextual chat
Query params: `sourceSnippetId` (UUID), `intent` (`charisma`|`stress`).
**200** → `{status: "ok", question, source, ...}`.

---

## Error envelope convention

Every non-2xx on this surface returns:
```jsonc
{ "code": "<MACHINE_CODE>", "error": "<human string>" }
```
Branch on `code`, not on the human `error` string (the latter may change
wording). Known codes on the Lounge surface: `UNAUTHORIZED`,
`INVALID_INPUT`, `NOT_FOUND`, `SNIPPET_CONTEXT_UNAVAILABLE`,
`PRIOR_SESSION_PENDING_REVIEW`, `V2_ERROR`.

---

_Last synced from `routes/v2_routes.py` — keep this doc in lockstep: any PR
that changes a Lounge endpoint's request/response/error shape updates this
file in the same commit._
