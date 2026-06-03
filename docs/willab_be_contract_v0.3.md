# willab — Backend Reference & FE↔BE Contract
> **Single reference point for the backend engineer.** Its job is alignment: the shapes FE depends on, the ordering BE must enforce, and the invariants that keep the design's promises intact. **Internal schema, storage engine, and queue implementation stay BE's call** — provided §5's invariants hold at the response boundary.
## Document control
| | |
|---|---|
| **Status** | Living document — updated as design evolves (see *Change log*) |
| **Version** | 0.3 — Lounge red-lines signed off (§7.5–7.8 → `[AGREED]`) |
| **Last updated** | 2026-06-03 |
| **Audience** | Backend engineer / agent |
| **BE-compatibility owner** | (you — the backend-focused designer) |
| **FE/flow owner** | the FE designer |
| **Source of truth (the *why*)** | `willab_design_decisions_dev.md` (mirrored here as `willab_design_decisions_v1.2.md`) — §-refs below point there |
| **This doc owns** | the *interface*. Where this and the dev doc agree, the dev doc owns *why*, this owns *how FE and BE meet* |
| **Consolidates** | FE-side Backend Handoff + the standalone Lounge thread-persistence BE handoff (now §3.15 + Appendix A) |
**Reading order:** §1 stores → §2 the split-sink wall (the data-integrity rule everything serves) → §3 FE↔BE contract points (the meeting places) → §4 pipeline → §5 invariants → §6 reuse map → §7 open items → §8 contract index (quick ref) → Appendix A (proposed Lounge schema).
**How to keep this updated:** every change lands in the *Change log* with a version bump. Decisions move through the status legend below; an item is not "done" until it reaches `[AGREED]`. Open items live in §7 with an owner so nothing silently drifts.
### Status legend
| Marker | Meaning |
|---|---|
| `[AGREED]` | Locked. FE + BE + design aligned. Change requires a change-log entry. |
| `[PROPOSED]` | Default on the table with a recommendation; awaiting sign-off. |
| `[OPEN]` | Decision not made — **blocks** the dependent BE work. |
| `[DORMANT]` | Columns/paths may exist but are inert this phase; do not wire. |
---
## 1. Persistent stores
Contract-level shape only — the fields FE/coach depend on, cardinality, scope. Column types/indexes are BE's call.
| Store | Cardinality | Key fields | Scope / retention |
|---|---|---|---|
| **`profile`** | 1 per user | `domain` (enum: `public_speaking` \| `sales` \| `executive_presence` \| `customer_service` \| `interview_prep`), `goal` (free text). Derives `inferred_learner_profile`, `baseline_summary`. | created at intake (§3.1); persists for the user |
| **`session_context`** | 1 per recording (1:many → profile) | `topic` (**required**), `audience?`, `target_length?`, `domain_vocabulary` (default from the §2 seed for the profile domain, editable) | created at Lab entry (§3.2); part of the coach packet |
| **`recording` / session artifact** | 1 per recording | raw audio, Whisper transcript (vocab-primed from `session_context`), librosa feature vector, `snippets[]`, stickiness score + comment, lifecycle state | state machine §3.0 |
| **`lounge_messages`** | thread per user | message rows (role, kind, text, ts) — concrete contract §3.15 | **signed:** server per user. **unsigned:** `localStorage`, **merged chronologically (append, never overwrite) on sign-up.** **Continuity only — never profiled, never in coach packet. User-deletable.** |
| **`consent`** | 1 per user/device | `consent_version`, `accepted_at` | `localStorage` unsigned, server signed, **carried over on sign-up**; re-prompt **only** on version bump (§3.13) |
| **`labels`** (private training lane) | per trained snippet | closed-set label values (schema `[OPEN]` — §7.1), optional private rationale | **pipeline-only, never user-facing.** Captured at publish |
| **`insights_payload`** (user lane) | 1 per published session | `overall_message` (**required**), `snippet_notes[]` (curated), `tags[]` (strong / to-work-on, on noted snippets) | published to user (§3.9) + library |
| **`strong_sides_library`** | grows per user | ingested tagged snippet (snippet ref + raw data + coach note + tag) | ingested **on the user's _read_** of insights (§3.11); read by the Lounge bot; **never trajectory/profiling** |
---
## 2. The split-sink wall (the one rule that governs everything)
Every session produces **two lanes that must never cross** (§14):
- **User lane** → `insights_payload` → published to the user + library. Curated, warm.
- **Private lane** → `labels` → classifier pipeline only. **Never appears in any user-facing response.**
**BE must guarantee, at the response boundary:**
1. No `labels`, classifier verdict, or T:C / KPI value is ever serialized into any payload the FE renders to an end user. **(AC-9.)**
2. The `lounge_messages` thread is never written into `profile` / `inferred_learner_profile` and never added to the coach packet.
3. **Coach packet = audio/transcript + features + stickiness + `profile` + `session_context`. It explicitly excludes the Lounge thread. (AC-6.)**
Enforced server-side (not trusted to FE), the no-judgment + privacy promises hold even if a client misbehaves.
---
## 3. FE↔BE contract points
### 3.0 Recording lifecycle state machine — `[AGREED]` (BE owns the state)
```
created → processing → readout_ready → parked ⇄ queued → review_pending → insights_ready
```
- **`parked`** = recorded, not sent; **held + resumable.** It is the hand-off token across the OAuth redirect (§3.5/§13). **Not discarded on divert.**
- Discard is **explicit-only** post-recording (+ unsigned-session-end sweep). Mid-recording discard-on-confirm needs no server artifact.
### 3.1 Intake submit → `profile` — `[AGREED]`
FE sends `{ domain, goal }`. BE creates the 1-per-user `profile`, kicks off `inferred_learner_profile` / `baseline_summary`. Non-recording step — no audio.
### 3.2 Lab entry → `session_context` — `[AGREED]`
FE sends `{ topic, audience?, target_length?, domain_vocabulary }`. **`topic` required** (BE rejects empty). `domain_vocabulary` defaults from the §2 seed but arrives editable.
### 3.3 Audio upload → processing pipeline → Readout payload — `[AGREED]`
- **Gate first:** reject if `< 60s` or no-speech (min-content gate, §4) **before** processing — return a re-record signal, persist nothing sendable.
- Pipeline: **Whisper** (primed with `session_context.domain_vocabulary`) → **ffmpeg** → **librosa** → snippet segmentation (pause/VAD) → stickiness scoring + comment.
- **Response shape FE renders the Readout from (contract):**
```jsonc
snippets[]: {
  id, index, transcript, audio_ref,            // SnippetPlayer
  features: {
    f0_mean, f0_sd, speech_rate, mean_pause, pause_ratio,
    loudness_range, voiced_ratio,
    f0_slope, pause_regularity, intensity_envelope, f0_mid_end_delta
  },
  stickiness: { composite, subscores?, comment }
}
```
Raw absolute values this phase (no baseline-relative; ISB is coach-side, §5).
### 3.4 Send to coach — signed-in (instant) — `[AGREED]`
- **Idempotent.** FE disables control on tap; BE dedupes on an idempotency key — a double-tap / double-call must not double-send.
- Payload = the coach packet (§2). **Never the Lounge thread.**
- Success flips the recording → `review_pending`. **Return success only when the send actually succeeds** (see §3.6).
### 3.5 Send to coach — unsigned (OAuth round-trip) — ORDERED — `[AGREED]`
On the OAuth callback, BE runs **in this exact order:**
1. **merge** the unsigned `localStorage` Lounge thread → server thread (chronological append, never overwrite);
2. **send** the `parked` recording (coach packet; same idempotency key as §3.4);
3. on send success → `review_pending`.
- Existing account at OAuth → login → same 1–3.
- The recording is `parked` **before** the redirect, so an abandoned/failed OAuth loses nothing.
### 3.6 "Confirmation only on send success" gate (critical) — `[AGREED]`
**Auth success ≠ send success.** After OAuth the account exists but the recording may still be queued. BE must not return a "sent/confirmed" state on auth completion alone — only when step 2 resolves. On failure/offline at callback: keep `parked` + **queued** + auto-retry.
### 3.7 Offline send-queue — `[AGREED]`
If offline at send (either path): recording stays `parked`, send is queued, auto-retries on reconnect. No data loss, no false "sent."
### 3.8 Coach review queue (admin) — `[AGREED]`
BE serves a list of `review_pending` sessions (topic · user · sent-at) → opens the authoring view (§14). Reuses admin `users/[userId]` Tab 1.
### 3.9 Publish (the pivot) — `[AGREED]`
Endpoint: **reuse `/v2/internal/publish-session-results`.** BE:
a. assemble + persist `insights_payload` (validate the publish contract, §3.10);
b. capture the `labels` as the training annotation event (private lane);
c. fire the **existing** publish event → `usePublishLiveSubscription` (realtime) + `useReviewingFetch` (poll fallback) + `ResultsReadyEmail`;
d. flip user session → `insights_ready`.
**Re-point** those three signals from the retired `reviewing` phase → the status region (§6a).
### 3.10 Publish-contract validation (BE-enforced gate) — `[AGREED]`
Reject publish unless: `overall_message` present · **≥1** curated snippet note present · every **noted** snippet carries a strong/to-work-on tag. No word-count gate on notes. → Guarantees the **library floor**: every published session yields ≥1 library entry, so the bot's "refresh your strong lines" is never empty.
### 3.11 Library ingest — on READ — `[AGREED]`
The tagged snippets ingest into `strong_sides_library` **when the user reads** the insights (not at publish). BE exposes the library for the bot to retrieve.
### 3.12 Lounge bot context assembly — `[AGREED]` (model verdict deferred — see §7.7)
- gpt-4o-mini context = **master science doc + this user's `strong_sides_library`** (retrieval).
- **Librarian, not judge:** the bot may retrieve/replay coach notes; BE/prompt must prevent cross-session synthesis ("you're improving"), fabricated scores, or pre-empting the coach (§7). The library feed is read-only replay of human-authored notes.
### 3.13 Consent — `[AGREED]`
On open: check `consent` record; if absent or version-bumped → `welcome_consent`. Else skip to intake/Lounge. Carry the record over on sign-up.
### 3.14 Delete — `[AGREED]`
Lounge thread is **user-deletable** (privacy commitment, §12/§3). Account deletion cascades the thread.
### 3.15 Lounge thread persistence (concrete contract) — *(consolidated from the standalone Lounge BE handoff)*
The Lounge is HOME and must read like a continuous chat that survives reload and device switch. Today the FE thread is in-memory and lost on reload; this is the per-user server store the FE rehydrates on mount and appends to. **Scope guardrails (do not violate):** text/transcripts only — **never audio** (Lounge speech is client-side Web Speech, not Whisper); and per §2 / AC-6 the thread is **never** part of the coach packet.
**Ownership boundary (one writer, one store):** the FE persists the bubbles it renders, **including bot replies**. `/v2/chat/query` (master-doc RAG) stays **stateless** about the thread. (`[AGREED]`, §7.6 — FE-append; BE does not write bot turns server-side.)
**`GET /v2/user/lounge/messages?limit=50&before=<iso8601>`** — `@require_auth`. Rehydrate on mount + scroll-up paging.
```jsonc
200 → {
  "messages": [ { "id","client_id","role","kind","body","metadata","client_created_at" } ], // ASC by client_created_at
  "has_more": true,                          // older messages exist before this page
  "oldest_cursor": "2026-06-01T12:00:00Z"    // pass as ?before= for the previous page; null when no older
}
```
No `before` → latest `limit` messages (bottom of thread). `before=<cursor>` → the page immediately older.
**`POST /v2/user/lounge/messages`** — `@require_auth`. Batch append (FE sends the user turn + bot reply together after each turn; system lines as they happen).
```jsonc
body → { "messages": [ { "client_id","role","kind","body","metadata"?,"client_created_at" } ] }
200  → { "messages": [ { ...persisted rows with server id } ] }
```
**Idempotent on `(user_id, client_id)`** — re-sending a stored `client_id` is a no-op upsert, not a duplicate.
**Merge on sign-up:** no separate endpoint — the same `POST` handles it. After account creation the FE replays its `localStorage` thread as one batch; `client_created_at` preserves order, `client_id` prevents dupes. (`[AGREED]`, §7.8 — standard `POST`, no `/merge` alias.)
**Field semantics:** `role` ∈ `user|bot|system`; `kind` ∈ `text|joke|status|recording_summary|insight`; `metadata` JSON carries e.g. `{ session_id, insight_ref }` on status/insight lines; `client_created_at` is the FE-stamped **ordering key** and survives merge.
**Edge cases:**
| Case | Handling |
|---|---|
| Append retry / double-tap | `UNIQUE(user_id, client_id)` upsert → no dupes |
| Double merge (re-signup) | same — idempotent on `client_id` |
| Account deletion (GDPR) | `ON DELETE CASCADE` wipes the thread |
| Coach packet assembly | **must exclude** `lounge_messages` (AC-6) |
| Huge thread | cursor paging via `before`; FE loads latest 50, pages up |
Proposed reference schema in **Appendix A**.
---
## 4. Processing + classifier pipeline
- **Acoustic pipeline:** Whisper → ffmpeg → librosa, server-side, **Lab audio only.** The Lounge is never measured/transcribed server-side (its speech is local Web Speech API).
- **Classifier training — admin labels are the only signal this phase.**
  - **Cold start (beta begins here):** no model → no pre-filled verdict; the coach labels from scratch. Those first labels bootstrap the classifier.
  - **Steady state:** the snippet shows a **pre-filled mechanical verdict**; coach **accepts** (cheap) or **overrides** (the high-value correction). Overrides are the training signal.
  - **Capture on publish; retrain on a batched/volumetric trigger — not per-publish** (threshold = BE's call, §7.2).
- The closed loop: correct → capture → retrain → better pre-fills → mostly accept → correction load falls.
### 4.1 librosa runtime cost + mandatory warmup — `[AGREED]` dep / warmup `[OPEN]` (§7.10)
**Dependency status:** librosa is now a committed dependency (`requirements.txt`, commit `2a245eb`). This is a **deliberate reversal of BE-3 prompt C3** ("Do NOT add `librosa` as a new dependency") — intentional, not accidental. As of that commit the dep is present but **no code uses it yet**; the cost below lands the moment the first caller (e.g. `audio_metrics.py` / the snippet pipeline) is wired.
**Measured cold-start (local smoke test, not estimate):**
| Operation | Time |
|---|---|
| `import librosa` | 0.01s |
| **First `librosa.feature.mfcc()` call (numba JIT compile)** | **27.3s** |
| Warmed-up call | 0.001s |
The 27s is a one-time-per-process numba JIT compile; every subsequent call is ~1ms. The operational hazard is that **every fresh gunicorn worker pays the 27s once before its first librosa-using request completes.** With the current `--workers 2`, that's **~55s of zombie startup after every deploy** if both workers take traffic immediately. Railway redeploys auto-fire on push to `main`, and Railway's **15s proxy timeout** means the first librosa-touching request times out → **502** (the same failure mode as the outage ~a week ago).
**Mandatory mitigation (an invariant, §5.12): warm librosa at worker startup, before the worker accepts traffic.** Two acceptable patterns:
1. **`bin/railway-web.sh` warmup line** — before gunicorn boots: `python -c "import librosa, numpy as np; librosa.feature.mfcc(y=np.zeros(16000), sr=16000)"`. Pays the 27s at deploy time, not request time.
2. **Gunicorn `post_worker_init` hook** — same warmup in a gunicorn config file. Cleaner, slightly more wiring.
**Sequencing rule:** the warmup hook ships in the **same PR as the first librosa caller** — never wire a request handler to librosa without the warmup in the same change, or the first real request 502s.
**Image-size context:** pre-librosa image ~204 MB → post-librosa **~350–400 MB** transitively (librosa + scipy + numba + llvmlite + soundfile + audioread + scikit-learn + soxr). First deploy build time rises visibly; cached layers help thereafter.
---
## 5. Invariants BE must enforce (not trust to FE)
1. **Split-sink wall** (§2): labels/KPI never in user payloads; Lounge thread never profiled, never in coach packet.
2. **Idempotent send** (§3.4): one logical send per recording regardless of taps/callbacks.
3. **Merge-then-send ordering** (§3.5): thread merge precedes send on the OAuth callback.
4. **Confirmation only on send success** (§3.6): auth success never implies sent.
5. **Min-content gate before processing** (§3.3): `<60s` / no-speech never enters the pipeline or becomes sendable.
6. **Park = held, resumable** (§3.0): post-recording divert / redirect / abandon never discards.
7. **Publish-contract validation** (§3.10): the library floor is enforced server-side.
8. **Consent re-prompt only on version bump** (§3.13).
9. **Library ingest on read, not publish** (§3.11).
10. **`topic` required** on `session_context` (§3.2).
11. **Lounge idempotent append/merge** (§3.15): `(user_id, client_id)` uniqueness; merge is chronological append, never overwrite.
12. **librosa warmed before traffic** (§4.1): a worker-startup warmup hook fires the first `librosa.feature.mfcc()` (27.3s numba JIT) **before** the worker accepts requests, so no real request eats the cold-start and 502s on Railway's 15s timeout. Ships in the same PR as the first librosa caller.
---
## 6. Reuse map (existing infra)
| Existing | Action |
|---|---|
| `/v2/internal/publish-session-results` | **reuse** as the publish pivot (§3.9) |
| `usePublishLiveSubscription` + `useReviewingFetch` + `ResultsReadyEmail` | **re-point** from the retired `reviewing` phase → status region (§6a) |
| admin `users/[userId]` Tab 1, coaching-rationale editable card, `NextSessionIcebreakerCard` (→ overall coach message) | **reuse** as the authoring surface (§14) |
| `reviewing` phase | **retire** (signals re-pointed; phase itself gone) |
| `AcousticMetricsBubble` + `metrics` bubble kind | **deleted** FE-side (no BE dependency should remain) |
| `CasualVoiceConsentModal` | **deleted**, replaced by `welcome_consent` (§12) |
| next-session icebreaker auto-prefill / session-2 wiring | **cut**; BE columns may stay `[DORMANT]` |
---
## 7. Open items register (consolidated — these gate / shape BE)
| # | Item | Status | Owner | Notes / recommendation |
|---|---|---|---|---|
| 7.1 | **Label schema** (§14) | `[OPEN]` blocking | Science / FE design | Either the master-doc **28 binary present/absent judgments** (→ ~12–16 surviving κ ≥ 0.60) **or** a **direction-only** bootstrap (threat / ambiguous / challenge). Sets the `labels` store shape. *Rec if undecided:* `{label_key → value}` set with a **closed, versioned** vocabulary, so either schema (and κ-pruning) fits without migration. No free-text emotion; "none fits" → explicit `ambiguous/none`. |
| 7.2 | **Retrain trigger threshold** (§4) | `[OPEN]` BE's call | BE | Volume/cadence is BE's to set — just **not per-publish**. |
| 7.3 | **Email verification timing** | `[OPEN]` | BE | OAuth verifies email inherently; confirm the verified address is the one `ResultsReadyEmail` uses, so insights can't black-hole. |
| 7.4 | **Idempotency key derivation** | `[OPEN]` | BE | Per-recording is the natural unit; confirm it **survives the OAuth redirect** (must, since the recording is `parked` across it). |
| 7.5 | **Lounge page size = 50** | `[AGREED]` | FE design | Locked at 50 (WhatsApp-like initial load). |
| 7.6 | **Lounge bot-reply persistence model** | `[AGREED]` — **FE-append** | FE design + BE | FE persists every bubble it renders (user, bot, system, joke) and owns `client_created_at` for all of them → one clock, one writer, consistent ordering. `/v2/chat/query` stays stateless about the thread; BE does **not** write bot turns server-side. (Rejected alternative: server-written bot turns, which would split the writer and force BE to own timestamps.) |
| 7.7 | **Lounge retention / TTL** | `[AGREED]` — **indefinite** | FE design | No TTL. Thread kept per user until account deletion (then cascades, §3.14). Revisit only if text-scale storage cost ever becomes material. |
| 7.8 | **Lounge merge route** | `[AGREED]` — **standard `POST`** | BE | Merge runs through the standard `POST /v2/user/lounge/messages` (idempotency + `client_created_at` ordering handle it). **No dedicated `/merge` alias** — observability isolation not needed for now. |
| 7.9 | **Lounge merge batch ceiling + RLS** | `[OPEN]` | BE | "Replay the local thread as one batch" can be large after a long unsigned session — define a **max batch size + FE chunking** and the upsert-conflict response shape. Also pin the **Supabase RLS** policy (user reads/writes only their own `lounge_messages`) rather than relying on the endpoint guard alone. |
| 7.10 | **librosa warmup hook** (§4.1) | `[OPEN]` blocking first librosa caller | BE | Dep committed (`2a245eb`), unused so far. Before any handler calls librosa, add a worker-startup warmup (`bin/railway-web.sh` line **or** gunicorn `post_worker_init`) so the 27.3s numba JIT is paid at deploy time, not on the first request (else 502 via Railway's 15s timeout). **Decision pending:** ship warmup as a *pre-emptive* PR now, or bundle it into the PR that wires the first caller. *Rec: pre-emptive* — it's cheap, idempotent, and removes a live outage pattern from every deploy regardless of when the first caller lands. |
---
## 8. FE↔BE contract index (quick reference)
| Meeting point | Method / event | Caller | Payload / shape | Idempotent? | Success condition |
|---|---|---|---|---|---|
| Intake | submit | FE | `{ domain, goal }` | — | `profile` created |
| Lab entry | submit | FE | `{ topic*, audience?, target_length?, domain_vocabulary }` | — | `session_context` created |
| Audio upload | upload | FE | audio + ctx ref | gate first | Readout payload (§3.3) or re-record signal |
| Send to coach (signed) | action | FE | coach packet (§2) | **yes** (key §7.4) | actual send → `review_pending` |
| Send to coach (unsigned) | OAuth callback | FE→BE | merge → send → flip (ordered §3.5) | **yes**, same key | step 2 resolves (§3.6) |
| Publish | `/v2/internal/publish-session-results` | admin/coach | `insights_payload` (validate §3.10) + `labels` capture | — | `insights_ready` + 3 signals fired |
| Library ingest | on read | FE read event | — | — | tagged snippets → `strong_sides_library` |
| Bot query | `/v2/chat/query` | FE | user message + retrieval ctx | stateless re: thread | librarian reply (no synthesis/scores) |
| Lounge rehydrate | `GET /v2/user/lounge/messages` | FE | `?limit&before` | — | ASC page + `has_more` + `oldest_cursor` |
| Lounge append/merge | `POST /v2/user/lounge/messages` | FE | `{ messages[] }` | **yes** `(user_id, client_id)` | persisted rows w/ server `id` |
| Consent | check/accept | FE | `consent_version` | — | record present / carried on sign-up |
| Delete | action | FE | — | — | thread removed (cascade on account delete) |
---
## Appendix A. Proposed reference schema — `lounge_messages`
*Internals are BE's call; this is a starting proposal aligned to the §3.15 contract. Adjust types/indexes freely as long as the endpoint shapes and §5.11 invariant hold.*
```sql
CREATE TABLE lounge_messages (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  client_id         UUID NOT NULL,              -- FE-generated; idempotency + dedup
  role              TEXT NOT NULL,              -- 'user' | 'bot' | 'system'
  kind              TEXT NOT NULL,              -- 'text' | 'joke' | 'status' | 'recording_summary' | 'insight'
  body              TEXT NOT NULL DEFAULT '',
  metadata          JSONB,                      -- e.g. { session_id, insight_ref } for status/insight lines
  client_created_at TIMESTAMPTZ NOT NULL,       -- FE-stamped; the ordering key (preserves merge order)
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, client_id)                   -- idempotent append + merge
);
CREATE INDEX ON lounge_messages (user_id, client_created_at);
```
`ON DELETE CASCADE` covers GDPR account-deletion. `UNIQUE(user_id, client_id)` makes append/merge idempotent (double-tap, retry, double-merge all safe). `role`/`kind` are shown as free `TEXT`; promote to enums or check-constraints at BE's discretion.
---
## Change log
| Version | Date | Change |
|---|---|---|
| 0.1 | 2026-06-03 | Initial consolidation. Restructured the FE-side Backend Handoff into a living BE reference; folded the standalone Lounge thread-persistence handoff into §3.15 + Appendix A; added the status legend, the consolidated open-items register (§7, merging the FE-handoff open items with the Lounge red-lines), and the FE↔BE contract index (§8). |
| 0.2 | 2026-06-03 | Recorded the **deliberate reversal of BE-3 C3** (librosa now committed, `2a245eb`). Added §4.1 with the measured 27.3s cold-start, the ~55s/2-worker deploy hazard + Railway 15s-timeout/502 failure mode, the two warmup patterns, the same-PR sequencing rule, and image-size context. Added invariant §5.12 (warm before traffic) and open item §7.10 (warmup hook — pre-emptive vs bundled). |
| 0.3 | 2026-06-03 | Lounge red-lines signed off → `[AGREED]`: page size **50** (§7.5); bot-reply persistence **FE-append**, `/chat/query` stays stateless (§7.6); retention **indefinite**, no TTL (§7.7); merge via **standard `POST`**, no `/merge` alias (§7.8). Synced the §3.15 body cross-references to match. |

---
## BE implementation status (this branch — appended by the BE agent, not part of the contract)
*Tracks which contract points are built on `claude/consent-endpoint`. Updated as work lands. Does not alter the contract.*
| Contract point | Status on this branch | Commit |
|---|---|---|
| §4.1 / §5.12 librosa warmup (§7.10) | **DONE** — gunicorn `post_worker_init` warmup (mfcc + chroma_stft) wired via `bin/railway-web.sh --config gunicorn_conf.py` | (this commit) |
| librosa dependency + first caller | **DONE** — `requirements.txt` + `services/audio_metrics.py` `_compute_librosa_features` (features → `charisma_snippets.metrics` JSONB) | `484d7c1` (hashes differ from contract's `2a245eb`; same substance) |
| Everything else (§1 stores, §3.1–3.15, publish pivot, lounge_messages, etc.) | **NOT STARTED** — awaiting build sequencing; several gated by `[OPEN]` items §7.1/§7.4/§7.9 | — |
