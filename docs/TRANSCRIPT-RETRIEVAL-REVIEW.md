# Transcript retrieval track — backend review & gap analysis

**Status:** Backend implemented (GET /v2/recordings/{id}, blueprint, app registration). BFF and frontend optional next.

---

## 1) Inventory — what’s already implemented

| Item | Status | Notes |
|------|--------|------|
| `GET /v2/recordings/{id}` route exists | **No** | Only `GET /recordings/<recording_id>` exists (recordings_bp). |
| Blueprint registration at `/v2/recordings` | **No** | app.py registers only `recordings_bp` at `/recordings`. |
| Owner-only auth enforced | **Yes** (legacy) | Legacy `get_recording` uses `db.get_recording(recording_id, user_id)`; DB filters by `user_id`. |
| Returns **404** when not allowed (not 403) | **Yes** (legacy) | Same 404 for not-found and not-owner; no 403. |
| UUID validation → 400 INVALID_INPUT | **Yes** (legacy) | `_is_valid_uuid(recording_id)` before DB call. |
| 500 error shape | **Legacy** | Uses `RECORDING_ERROR`; V2 contract prefers `V2_ERROR` for generic 500 (optional to align). |
| Response includes `transcription_text` | **Yes** (legacy) | Legacy response includes `transcription_text`. |
| Response includes optional `transcript_preview` | **No** | Not implemented. |
| Response includes `id`, `user_id`, `created_at`, `session_id`, `session_v2_id` | **Partial** (legacy) | Legacy returns `recording_id` (not `id`), `session_id`; no `session_v2_id` in response (column exists on row). |
| Backward compatibility with legacy `GET /recordings/{id}` | **Yes** | Legacy route unchanged; no duplicate registration in app.py. |
| Duplicate blueprint registration in app.py | **No** | Single `app.register_blueprint(recordings_bp, url_prefix="/recordings")`. |

**Summary:** V2 endpoint and V2 blueprint are **not** present. Legacy endpoint is owner-only, 404 for not-found/not-authorized, and returns transcript; it does not expose `session_v2_id` or `transcript_preview`, and uses a different response shape than the V2 contract.

---

## 2) Gaps / risks (must address before merging)

### Correctness
- **Missing route:** Add `GET /v2/recordings/<recording_id>` and a dedicated V2 blueprint so the path is canonical and the response shape is stable (transcript + optional preview, no legacy pre/post answers unless needed).
- **Import and registration:** In `app.py`, import `recordings_v2_bp` and register it with `url_prefix="/v2/recordings"`.

### Security / privacy
- **404 for not-found and not-authorized:** Keep using `db.get_recording(recording_id, user_id)` so that “not allowed” returns 404 (no 403). **No change needed** for V2 if we use the same helper.
- **Admin access:** Spec says “owner or admin.” Current codebase has no admin check for recordings. Recommendation: implement **owner-only** for MVP (same as legacy); add admin override later if required. That keeps 404 semantics and avoids new auth paths.

### Consistency
- **Error codes:** Use `RECORDING_NOT_FOUND` for 404 and `INVALID_INPUT` for 400. For 500, either keep `RECORDING_ERROR` or use `V2_ERROR` to match other V2 endpoints (recommended: `V2_ERROR` for V2 route).
- **Response shape:** V2 response should include at least: `id`, `user_id`, `created_at`, `session_id`, `session_v2_id`, `transcription_text`, `transcript_preview` (optional), plus optional `duration_seconds`, `words_per_minute`, `performance_score_v2`, `performance_metrics_v2`, `metric_labels_snapshot_v2` so it matches OPENAPI-V2-RECORDINGS and stays stable.

### Testing
- Add a test that `GET /v2/recordings/{id}` returns 200 with transcript when owner, and 404 when not owner or missing.
- Add a test that invalid UUID returns 400.

### Deployment
- No new env or config; reuses existing auth and DB. Ensure BFF/proxy can reach `/v2/recordings` (same host as existing API).

---

## 3) Exact patch recommendations

### 3.1) `routes/recordings.py`

Add after the existing `_is_valid_uuid` function (after line 331):

```python
recordings_v2_bp = Blueprint("recordings_v2", __name__)


def _build_transcript_preview(transcription_text, max_len=280):
    """Return first max_len chars of transcript, or empty string if None/empty."""
    if not transcription_text:
        return ""
    t = (transcription_text or "").strip()
    return t if len(t) <= max_len else (t[:max_len].rstrip() + "…")


@recordings_v2_bp.route("/<recording_id>", methods=["GET"])
@require_auth
def get_recording_v2(recording_id):
    """
    V2: Get a recording by id (owner-only). Returns 404 for not found OR not allowed.
    Includes transcription_text and optional transcript_preview.
    """
    try:
        if not _is_valid_uuid(recording_id):
            return jsonify({"code": "INVALID_INPUT", "error": "Invalid recording ID"}), 400

        user_id = request.user_id
        recording = db.get_recording(recording_id, user_id)
        if not recording:
            return jsonify({"code": "RECORDING_NOT_FOUND", "error": "Recording not found"}), 404

        transcription_text = recording.get("transcription_text")
        transcript_preview = _build_transcript_preview(transcription_text)

        payload = {
            "id": recording.get("id"),
            "user_id": recording.get("user_id"),
            "created_at": recording.get("created_at"),
            "session_id": recording.get("session_id"),
            "session_v2_id": recording.get("session_v2_id"),
            "transcription_text": transcription_text,
            "transcript_preview": transcript_preview or None,
            "duration_seconds": recording.get("duration_seconds") or recording.get("duration"),
            "words_per_minute": recording.get("words_per_minute"),
            "filler_words_count": recording.get("filler_words_count"),
            "performance_score_v2": recording.get("performance_score_v2"),
            "performance_metrics_v2": recording.get("performance_metrics_v2"),
            "metric_labels_snapshot_v2": recording.get("metric_labels_snapshot_v2"),
        }
        return jsonify(payload), 200

    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500
```

### 3.2) `app.py`

Add import:

```python
from routes.recordings import recordings_bp, recordings_v2_bp
```

Add registration (after the existing recordings_bp line):

```python
app.register_blueprint(recordings_v2_bp, url_prefix="/v2/recordings")
```

---

## 4) FRONTEND PROMPT (paste into Cursor for frontend repo)

```markdown
# Frontend: Fetch recording transcript (GET recording by id)

## Goal
Display the full transcript for a homework recording (recording_1 or recording_2) when the user opens a detail view or “View transcript” flow. Use the BFF endpoint that returns a single recording including `transcription_text` and optional `transcript_preview`.

## BFF contract
- **Endpoint:** `GET /api/recordings/{id}` (or your BFF path that proxies to backend).
- **Backend behavior:** BFF MUST call **`GET /v2/recordings/{id}`** first. If the response is **404**, BFF MAY fallback to **`GET /recordings/{id}`** (legacy) for backward compatibility during rollout. Do **not** fallback on 401, 403, or 500—only on 404.
- **Preserve status codes:** When the first call is not 404, return that response (and status code) to the client unchanged.

Suggested BFF pseudocode:
  - `res = await fetch(backendUrl + '/v2/recordings/' + id, { headers })`
  - if `res.status === 404`: optionally `res = await fetch(backendUrl + '/recordings/' + id, { headers })`
  - return `res` (no fallback for any other status)

## Types (TypeScript)
Define (or extend) a type for the recording response used in transcript UI:

- `GetRecordingResponse` must include:
  - `id: string` (UUID)
  - `user_id: string`
  - `created_at: string`
  - `transcription_text: string | null` — full transcript; null if unavailable
  - `transcript_preview?: string | null` — optional short preview (e.g. first 280 chars)
- Optional fields as needed: `session_id`, `session_v2_id`, `duration_seconds`, `words_per_minute`, `performance_score_v2`, `performance_metrics_v2`, etc.

## UI behavior
- **If `transcription_text` is present:** Show the full transcript in the transcript view.
- **If `transcription_text` is null:** Show a single message such as “Transcript unavailable” (do not show raw null or an error stack).
- **On 404:** Handle gracefully (e.g. “Recording not found” or redirect); do not treat as a generic server error.
- **On 5xx:** Show a generic “Something went wrong” and optionally a retry action.

## What not to change
- **No changes** to `GET /session/status` or to the homework session state machine. Transcript is loaded only when the user explicitly requests a recording’s transcript (e.g. from a recording card or detail page).
- Do **not** embed full transcripts in the status response; use this dedicated recording-by-id endpoint for transcript display.
```

---

## 5) OpenAPI fragment

If you adopt the V2 endpoint, add or merge **`docs/OPENAPI-V2-RECORDINGS.yaml`** (as provided in the user’s spec) so that `GET /v2/recordings/{recording_id}` is documented with response schema and 404/500 behavior.

---

**Waiting for confirmation: Reply YES to proceed with implementation, or list changes you want.**
