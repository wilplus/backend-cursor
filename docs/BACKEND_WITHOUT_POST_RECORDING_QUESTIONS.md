# Backend Without Post-Recording Questions

This note documents the current backend contract for the web app after removing the post-recording questions step from the main homework journey.

## Goal

The web app no longer calls:

- `GET /v2/homework/session/<session_id>/questions`
- `POST /v2/homework/session/<session_id>/post-answers`

The student path for this client is now:

1. `POST /v2/homework/session/start`
2. `POST /v2/homework/session/<session_id>/recording-1`
3. `POST /v2/homework/session/<session_id>/self-rating`
4. `GET /v2/homework/session/<session_id>/report`

The report must be produced without requiring post-answers.

## Backend Behavior

### Recording 1

`POST /session/<session_id>/recording-1` stores the recording, creates the recording row, enqueues background processing, and moves the session into report generation:

- internal DB status: `completing_from_recording_1`
- public API status: `report_generating`

The response should be enough for the client to leave the recording step and begin polling status/report.

### Self-rating

`POST /session/<session_id>/self-rating` is the only required step between recording submission and the final report for this client.

- If background processing is already complete, self-rating finishes the session immediately.
- If processing is still running, the self-rating timestamp is stored and the background job completes the session once processing finishes.
- If processing failed, the backend falls back to a minimal completion path so the client can still reach a report.

### Report

`GET /session/<session_id>/report` remains the canonical polling target.

- Returns `200` once the session is completed and the report payload is ready.
- Returns `409` with `REPORT_NOT_READY` while the report is still being generated.
- May run a fallback completion step if processing is done but completion was not triggered yet.

## Status Contract

The current web app should not rely on `post_questions`.

Rules:

- Treat `completing_from_recording_1` as `report_generating`.
- Treat legacy `post_questions` as compatibility-only backend state, not as a step the current client should branch on.
- Use top-level API `status`, `recording_1_processing_status`, and `ready_for_self_rating` to drive the UI.
- Do not derive client flow from raw `session.status`.

In practice:

- `GET /session/status` should let the client decide between:
  - record now
  - wait for processing
  - show self-rating
  - poll report
  - show completed report

It should not require any `questions` or `post-answers` branch for this web app.

## Legacy Compatibility

Keeping old backend pieces is optional:

- The admin post-question pool can remain in the database for now.
- Legacy `post_questions` rows can still be recognized internally.
- If other clients still depend on the old endpoints, they can be kept or deprecated separately.

The important constraint is that the current web client must be able to complete homework and receive a report without ever calling post-question endpoints.
