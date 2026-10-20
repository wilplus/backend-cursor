# willab BE → FE handoff — last-pass before test & clear

**Status (2026-06-04):** all willab BE endpoints are **live on prod** (`main` @ `43bd9a3`, Railway deployed). The merge→send status-flip bug (phantom `updated_at` column) is **fixed** (PR #4). Full read+write loop smoke-tested against prod (synthetic upload → merge → history → byte-identical re-read). This doc gives the FE everything to wire seam ③, the send gate, Library, and Insights.

Source of truth for the *why*: `docs/willab_be_contract_v0.3.md` (§-refs below).

---

## A–E — Lab lifecycle (the seam ③ answers)

State machine (§3.0, BE owns it):
`created → processing → readout_ready → parked ⇄ queued → review_pending → insights_ready`

The FE never computes state — **every read endpoint returns a `state` string**. Derivation (so you know what it means):
`results_published_at` set → `insights_ready`; else `status == pending_admin_review` → `review_pending`; else → `readout_ready`.

**A. Upload — synchronous.** `POST /v2/lab/recordings` is multipart + **blocks ~3–5s** and returns the finished Readout (201). No polling. Gate runs **first** (§4): `< 60s` or no-speech → `422 RECORDING_REJECTED` (re-record), nothing persisted. Public/guest — **no auth** (account is created at Send).

**B. Park / re-read / history.** Park = **held + resumable, never discarded** (§3.0). The Readout is persisted at upload (snippets + features + the per-snippet stickiness), so it reloads **byte-identical** an hour later or on history scroll-back via `GET /v2/user/sessions/<id>/readout`. List past reports with `GET /v2/user/readouts`. (Both owner-scoped, post-merge.)

**C. Send — signed + unsigned, one path.** There is **no separate send endpoint** — `POST /v2/auth/merge-session` **composes merge→send** (§3.5). It claims the guest session into the account *then* sends to the coach queue. Idempotent; a retry recovers a stuck send. **Confirmation only on send success** (§3.6): on success → `review_pending` + a confirmation message; on flip failure → `500 SEND_FAILED` (never a false "sent"). *(This is the bug just fixed — before, it falsely reported sent.)*

**D. States to render.** Exactly three user-facing: `readout_ready` (recorded, not sent), `review_pending` (sent, human reviewing), `insights_ready` (coach published). Provided as `state` on every read.

**E. Returning user.** `profile` persists per user (`GET /v2/user/profile`) — if `domain`/`goal` are set, the FE can **skip intake**. History via `/v2/user/readouts`. Lounge thread persists + rehydrates (`/v2/user/lounge/messages`).

> If your original A–E were worded differently, paste them and I'll answer point-by-point — but these are the lifecycle facts seam ③ needs.

---

## Endpoint contracts (exact shapes)

### ③ Upload — `POST /v2/lab/recordings` (public, multipart)
Form fields: `audio_file` (req), `topic` (req), `audience?`, `target_length_seconds?` (int), `domain_vocabulary?` (JSON array or CSV), `guest_session_id?` (reuse else minted).
```jsonc
201 { "status":"ok", "session_id":"<uuid>", "recording_id":"<uuid>",
      "session_context": { "topic","audience","target_length_seconds","domain_vocabulary" },
      "readout": { "snippets": [ /* §3.3 below */ ] } }
422 { "code":"RECORDING_REJECTED", "error":"…", "gate":{reason,duration_sec,voiced_sec,thresholds} }  // too_short | no_speech
400 AUDIO_FILE_REQUIRED | INVALID_INPUT   413 FILE_TOO_LARGE (25MB)
```

### §3.3 snippet shape (same on upload, re-read, and coach-authoring)
```jsonc
{ "id":"<uuid>", "index": 1, "transcript":"…",
  "audio_ref":"<parent audio url>", "start_offset_ms": 5800, "duration_ms": 5400,
  "features": { "f0_mean","f0_sd","speech_rate","mean_pause","pause_ratio",
                "loudness_range","voiced_ratio","f0_slope","pause_regularity",
                "intensity_envelope","f0_mid_end_delta" },   // any may be null
  "stickiness": { "composite": 0.0, "comment": null },
  "coach": { "note":"…", "tag":"strong|to_work_on" }          // POST-PUBLISH ONLY
}
```
Parent-audio + offset-window model: `audio_ref` is the whole recording; play the window with `start_offset_ms`/`duration_ms` (your `MediaPlayer` already does this).

### Re-read / history
```
GET /v2/user/sessions/<id>/readout   → 200 { session_id, published, state, readout:{ snippets[], insights_payload? } }   (404 non-owner)
GET /v2/user/readouts                → 200 { readouts:[ {session_id, created_at, topic, state} ], count }   // newest first
```

### Send gate (C) — `POST /v2/auth/merge-session` (auth)
```jsonc
Body: { "anonymous_session_id":"<uuid>" }
200 { "status":"ok", "session_id", "analysis_status":"sent_to_coach", "review_pending":true, "post_signup_confirmation":{headline,body} }
500 { "code":"SEND_FAILED", ... }     // claimed but send flip failed — retry (idempotent)
409 ALREADY_CLAIMED  404 GUEST_SESSION_NOT_FOUND  410 GUEST_SESSION_EXPIRED  503 GUEST_FUNNEL_DISABLED
```
Unsigned flow (§3.5): park → OAuth → merge-session (merge precedes send). Recording is parked *before* redirect, so an abandoned OAuth loses nothing.

### Library (§7) — `GET /v2/user/library?tag=` (auth)
```jsonc
200 { "entries":[ {id, session_id, snippet_id, note, tag, snippet_ref, created_at} ], "count": int }   // newest first
```
`tag` filter optional: `strong | to_work_on`. Ingested automatically when insights are read; librarian-not-judge (pure replay of coach notes, no trajectory computed).

### Insights (§6) — no new endpoint; read the re-read post-publish
When `state == insights_ready` / `published == true`, `GET /v2/user/sessions/<id>/readout` carries the coach layer:
- **per snippet:** `snippet.coach = { note, tag }`  ← this is the per-snippet "insight"
- **overall:** `readout.insights_payload = { overall_message?, snippet_notes:[{snippet_id,note,tag}] }`

> **Naming note:** the FE called it `insight`; BE delivers it as **`snippet.coach.note`/`.tag`** + **`insights_payload.overall_message`** (optional). No extra BE call — it's folded into the re-read.

### Lounge merge-on-signup (§7.8) — `POST /v2/user/lounge/messages` (auth)
```jsonc
Body: { "messages":[ {client_id, role, kind, body, metadata?, client_created_at} ] }
200 { "messages":[ …persisted rows with server id ] }   // idempotent on (user_id, client_id)
```
On signup, replay the localStorage thread as batches through **this** endpoint (no separate /merge alias). `client_created_at` preserves order; `client_id` dedupes.

### Returning-user intake — `GET/PUT /v2/user/profile`, `PUT /v2/user/intake-context`
`profile` = `{ domain, goal, domain_vocabulary_default[] }`. Set at intake; gates the skip.

---

## Migrations to run on Supabase (gates the authed endpoints)
`add_profile_to_user_settings` · `add_lounge_messages_table` · `add_insights_payload_to_v2_sessions` · `add_strong_sides_library_table` · `add_training_labels_table` · `add_foundation_discriminators` (the `source` column — history filter).
*(Smoke test confirmed these are already applied on prod; re-list here for completeness / other envs.)*

## Verified live (prod smoke test, synthetic recording)
Upload → 201 (10 snippets, real features) · merge → `review_pending` (after fix) · `/v2/user/readouts` shows it · re-read **R1 ≡ R2 byte-identical** · `/v2/user/profile|library|readouts` → 200.

## Open / FE-owned
- Consent versioning (§3.13) — minor, not blocking the loop.
- Phase-5 clearing (delete old funnel) — **last**, gated on the D1 decision (homework REPLACE vs COEXIST).
