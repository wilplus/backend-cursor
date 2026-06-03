# willab — BE Clearing Map
**Companion to** `docs/willab_design_decisions_v1.2.md` (§1–§14) and `docs/willab_be_contract_v0.3.md`. This is the **"what already exists"** half for the **backend** repo, so build-agents implement the **delta**, not blind.

**Read-only audit.** Every verdict cites a real path. `UNVERIFIED` where not confirmed by reading. Verdicts: **REUSE · ADAPT · RELOCATE · DELETE · BUILD-NEW · DORMANT · CROSS-REPO(FE) · CONFLICT/RISK.** Produced by a 5-agent grounded scan + spot-verification; no code was changed.

---

## 0. STOP-AND-FLAG (read first)

The clearing prompt named four stop conditions. Findings:

1. **🟠 Readout pipeline is real but feature-incomplete — gates the Readout (§5).** Whisper, ffmpeg, librosa, stickiness all exist. BUT only **4 of the 10** per-snippet Readout features have a producer today. **Missing/partial:** `f0_sd`, `f0_slope`, `f0_mid_end_delta`, `pause_ratio`, `pause_regularity`, `intensity_envelope`. The pipeline emits `pitch_center_st` (single median, not mean+SD), `pause_ms` (not ratio), `dynamic_db`, `energy_ratio`, `wpm`. **Building the missing 6 in `services/audio_metrics.py` is a prerequisite for the Readout contract (§3.3).**
2. **🟠 Snippet segmentation is MVP-grade — gates multi-snippet Readout.** `services/snippet_extraction.py` (charisma) currently extracts the **whole recording as one snippet** (no VAD/pause sub-segmentation); `services/stress_snippet_service.py` extracts acoustic events but caps at 8. The Readout's "Snippet 2 of 5, tap-to-advance" presumes **multiple per-snippet cards from one recording** → needs real pause/VAD segmentation. BUILD-NEW/ADAPT.
3. **🔴 AC-9 violation CONFIRMED (in the to-be-deleted funnel).** `POST /v2/public/interview/upload-answer` (`routes/v2_routes.py:13197`) has **no `@require_auth`** and returns `freemium_tease.kpi_score` to **anonymous** users (built `:13707`, returned `:13798`). `kpi_score` is a classifier-derived value; AC-9 says it must not reach users. It's intentional in the *current* freemium funnel but is exactly what the beta forbids. The cutover deletes this funnel — **confirm the deletion removes this path; if any of it survives, gate/remove the tease.**
4. **🟢 No confirmed Lounge→coach-packet leak.** The admin session-detail endpoint (`GET /v2/admin/sessions/<id>`, `:16396`) reads `v2_sessions` + `charisma_snippets` only; `coach_ai_conversations` (db.py `:4319`) is **not** included. **Residual risk:** `_render_chat_thread` (`:1076`) is `UNVERIFIED` — confirm it excludes any chat-history table before the Lounge ships. Codify the exclusion (invariant §5.1 / AC-6).

**Plus:** the contract's "reuse `/v2/internal/publish-session-results`" is accurate — that route exists (`:14617`), alongside `/v2/admin/sessions/<id>/publish` (`:15322`). No mismatch.

---

## 1. Verdict matrix (by BE contract handoff / store)

| Contract (§) | Element | Verdict | Path(s) / evidence | Note |
|---|---|---|---|---|
| §1 | **`lounge_messages`** store | **BUILD-NEW** | none — no "lounge" in migrations/ or db.py | full table + `GET/POST /v2/user/lounge/messages` per §3.15 + Appendix A |
| §1 | **`strong_sides_library`** store | **BUILD-NEW** | none — no "strong_side(s)" anywhere | per-user tagged-snippet store; ingest-on-read (§3.11) |
| §1 | **`session_context`** | **ADAPT** | `services/intake_context.py`; `v2_sessions.intake_context` JSONB; db.py `get/set_session_intake_context` | Task 9 shipped `{topic, audience, target_length_seconds}`. **Gap: `domain_vocabulary` missing.** Scope is per-session today; beta wants per-recording (OK if session≈recording). Add `domain_vocabulary`. |
| §1 | **`profile`** (domain enum + goal) | **ADAPT / BUILD-NEW** | `user_settings.inferred_learner_profile` + `.baseline_summary` (derived, exist); `v2_speaker_profiles.main_goal` (free-text) | **Gap: no `domain` enum** (5 values). Derived fields exist; the typed domain + canonical goal field do not. Add domain enum + goal. |
| §1 | **`labels`** (direction-v1, private) | **ADAPT / BUILD-NEW** (gated §7.1) | per-snippet `charisma_snippets.coach_label` (binary `charisma\|no_charisma`) + `coach_label_notes`; `stress_snippets.coach_label`+`reason_chip`; session-level `admin_annotations_log` (RLHF pairs) | Per-snippet labeling **exists but wrong schema**: binary, not `threat\|ambiguous\|challenge`, not schema-versioned, no `was_pre_filled/was_overridden`. **Blocked by §7.1 label-schema decision.** |
| §4/§5 | Whisper → ffmpeg → librosa → stickiness | **REUSE** | `openai_service.transcribe_audio` (whisper-1, `:183`); `audio_metrics.decode_audio_to_pcm` (`:53`); `audio_metrics._compute_librosa_features` (`:416`, new `484d7c1`); `stickiness.py` (`:47`) | all four stages exist |
| §5 | 10-feature Readout set | **BUILD-NEW (6 of 10)** | `audio_metrics._analyze_pcm` | see §0 item 1 — 4 present, 6 missing/partial |
| §4/§5 | snippet segmentation (VAD/pause) | **BUILD-NEW / ADAPT** | `snippet_extraction.py:62`, `stress_snippet_service.py` | see §0 item 2 — MVP one-snippet/event-based only |
| §14 | segmentation top-N (~10) cap | **REUSE** | `stress_snippet_service` / `charisma_snippet_service` `max_snippets=8` (MMR select), `recording_1_job.py` | cap exists; bump 8→~10 |
| §3.9 | publish endpoint | **ADAPT** | `/v2/internal/publish-session-results` (`:14617`) **and** `/v2/admin/sessions/<id>/publish` (`:15322`, `v2_admin_publish_session`); email `_send_results_ready_email` (`:15679`); `record_snippet_publish_annotations` (db.py `:6873`) | add `insights_payload` (overall msg + notes + tags); fire training-annotation event; no per-publish retrain |
| §6a | publish signals (FE) | **REUSE / re-point** | flips `v2_sessions.results_published_at` → FE realtime sub + poll watch this column; `ResultsReadyEmail` (FE) | re-point from `reviewing` phase → status region (FE work) |
| §2/§4.8 | coach packet (excl. Lounge) | **ADAPT(+doc)** | `GET /v2/admin/sessions/<id>` (`:16396`) | safe today; codify Lounge-exclusion + verify `_render_chat_thread` (`:1076`) — §0 item 4 |
| §3.4–3.7/§13 | send + OAuth merge-then-send | **REUSE(pattern) + BUILD-NEW** | `_merge_anonymous_session_into_user` (`:13837`); claim routes `/v2/public/shaky-voice/claim` (`:14017`), `/v2/auth/merge-session` (`:14041`); atomic `v2_claim_guest_session` | ordered merge→send→flip pattern exists; **idempotency-key store BUILD-NEW**; offline queue partial/`UNVERIFIED` |
| §3.13 | consent record | **ADAPT** | `user_settings` consent flags; `add_consent_flags_to_user_settings.sql`, `add_consent_preferences_to_user_settings.sql`, `add_user_consents_table.sql`, `user_consent_events` | has consent infra; add `consent_version` + version-bump re-prompt logic |
| §3.12 | Lounge bot (librarian) | **REUSE + ADAPT** | `/v2/chat/query` master-doc RAG (FE BFF; BE `master_doc_rag.py`) | add library to context + librarian guardrail in prompt |

---

## 2. DELETE / DORMANT list + blast radius (sequence before building over)

| Target | Verdict | Blast radius (callers/routes) | Replaced by |
|---|---|---|---|
| Charisma/stress **contrast completion gate** | **ADAPT (strip tone)** | `services/interview_completion_gate.py` (`_evaluate_counts`, `session_1_completion_state`, `completion_state`); callers: `/public/interview/upload-answer` (`:13768`), `/public/interview/<id>/completion-state` (`:18425`), `/public/interview/contextual-next-question` (`:19241`) | min-content gate only (≥60s + has-speech); salvage duration logic + `_evaluate_counts` core |
| **contextual-next-question** steering | **DELETE** | route `/v2/public/interview/contextual-next-question` (`:19212`); `services/contextual_followup.py` (no other importers); `SPEC_CONTEXTUAL_FOLLOWUP` | nothing (steering interview dropped); FE reverts to soft opener |
| **next-session icebreaker** auto-prefill (Task 10) | **DORMANT** (columns stay) | 6 `v2_sessions.next_session_icebreaker_*` columns; gen call sites `session_publish.py` (`:143`, `:267`) + interview-finalize route; soft-queue read in `/v2/user/chat/first-question` (`:10571`/`~:10830`); 3 admin routes (GET/PUT/regenerate); `services/next_session_icebreaker.py` | columns dormant; un-wire generation + the first-question pop; concept → coach-authored overall message |
| **User-facing KPI / charisma_profile** | **DELETE from user surface** (DB cols dormant) | user routes: `/v2/user/sessions/<id>/summary` (`:8740`, already publish-gated), `/v2/user/results/<id>` (`:8220`,`:8229`), `/v2/chat/session-state` (`:11948`, publish-gated), `/v2/user/chat/upload-answer` (`:10731`, auth+finalized); **🔴 `/v2/public/interview/upload-answer` freemium_tease (`:13707`, UNAUTH)**; builder `services/charisma_profile.py` | T:C ratio is private (AC-9). Remove user exposure; keep cols for admin |
| **AcousticMetricsBubble / `metrics` bubble** | **n/a (FE-only)** | no BE dependency confirmed | Readout (FE) |
| **Homework product** | **DECISION — see §9.1** | ~28 routes `routes/homework.py` (`/v2/homework/*`); services `homework_completion.py`, `v2_flow_service.py`, `recording_1_job.py`, `sniper_realtime.py`, `sniper_scoring.py`, `tutor_video_url.py`; tables `tasks`, `v2_warm_up_task_pool`, homework cols on `v2_sessions`/`recordings`; `routes/internal_webhooks.py` | **gated — do not delete without the REPLACE/COEXIST decision** |

⚠️ Sequencing: the contrast-gate strip + KPI-removal thread through the public funnel and the user summary; **delete after the Readout/status/Insights surfaces exist** or `/chat` + the public funnel break mid-migration.

---

## 3. REUSE inventory (exists, used as-is or near-as-is)
Whisper (`openai_service.transcribe_audio`) · ffmpeg (`audio_metrics.decode_audio_to_pcm`, `ffmpeg_audio_extract`) · librosa block (`audio_metrics._compute_librosa_features`) · stickiness (`stickiness.py`) · segmentation top-N cap (`max_snippets`) · publish endpoints (`/v2/internal/publish-session-results`, `/v2/admin/sessions/<id>/publish`) · `_send_results_ready_email` · `record_snippet_publish_annotations` · anonymous-session merge (`_merge_anonymous_session_into_user` + claim routes) · master-doc RAG (`/v2/chat/query`) · admin session-detail (`GET /v2/admin/sessions/<id>`) · snippet comment/label write endpoints · consent infra (`user_consents` / `user_consent_events`) · `intake_context` (→ session_context base).

## 4. BUILD-NEW (true greenfield, BE)
`lounge_messages` table + `GET/POST /v2/user/lounge/messages` (idempotent on `(user_id, client_id)`, page-50, cursor paging) · `strong_sides_library` table + ingest-on-read + bot-retrieval read · the 6 missing Readout features · real VAD/pause snippet segmentation · `direction-v1` per-snippet label store (gated §7.1) · idempotency-key store for send (must survive OAuth redirect, §7.4) · offline send-queue + retry · `domain` enum + canonical goal on profile · `domain_vocabulary` on session_context · the training-annotation event on publish.

## 5. ADAPT (exists, modify)
- `interview_completion_gate.py` — strip tone criteria; keep duration + add has-speech.
- `audio_metrics._analyze_pcm` — add the 6 missing features.
- `snippet_extraction.py` — real multi-snippet segmentation; bump cap 8→~10.
- publish endpoints — accept `insights_payload`, validate the §3.10 library floor, fire training-annotation event.
- `GET /v2/admin/sessions/<id>` — codify Lounge-exclusion; verify `_render_chat_thread`.
- `/v2/chat/query` (`master_doc_rag`) — add library context + librarian guardrail (note: Will's Voice anchor already injected, commit `4945920`).
- `_merge_anonymous_session_into_user` — extend to the ordered merge-(lounge)-then-send-(recording) with idempotency key.
- consent — add `consent_version` + version-bump re-prompt.
- `intake_context` — add `domain_vocabulary`.

## 6. Pipeline-readiness (BE-specific — replaces the FE map's "admin reconciliation")

| Stage | Ready? | Gap |
|---|---|---|
| Transcription (Whisper) | ✅ REUSE | vocab-priming from `session_context.domain_vocabulary` not yet wired (domain_vocabulary missing) |
| Decode (ffmpeg) | ✅ REUSE | — |
| Feature extraction (librosa) | 🟡 PARTIAL | 6/10 Readout features missing (§0.1); warmup landed (`gunicorn_conf.py`) |
| Segmentation | 🔴 MVP-only | one-snippet/event-based; real VAD/pause + per-snippet cards = BUILD-NEW (§0.2) |
| Top-N cap | ✅ REUSE | bump 8→~10 |
| Stickiness scoring + comment | ✅ REUSE | per-snippet comment exists |
| Coach packet assembly | 🟡 ADAPT | safe; add session_context+profile, codify Lounge-exclusion |
| Publish → insights_ready | 🟡 ADAPT | endpoint exists; add insights_payload + training event |

## 7. Cross-repo dependencies (FE ↔ BE)
- **BE→FE:** Readout payload shape (§3.3) blocks the FE Readout card; `results_published_at` flip drives FE realtime/poll; `lounge_messages` endpoints block FE Lounge persistence + merge glue; library read blocks bot context.
- **FE→BE:** FE owns lounge bubble writes incl. bot turns (`/v2/chat/query` stays stateless re: thread, §7.6); FE sends `client_id`+`client_created_at` (BE must honor as ordering/idempotency keys); FE drives ingest-on-read (BE exposes the read event); send-gate park-before-redirect is FE, merge-then-send ordering is BE (§3.5).

## 8. Conflicts / risks
1. **🔴 AC-9 anonymous KPI leak** (`:13707`) — confirmed; lives in the funnel the beta deletes. Must be removed/gated by the cutover (§9.4).
2. **🟠 Readout depends on 6 unbuilt features + real segmentation** — the single biggest BE build gate; the Readout cannot ship its contract until these land.
3. **Two products in one repo** (homework + chat funnel) — REPLACE/COEXIST gates total scope (§9.1).
4. **Wide-footprint deletions** (contrast gate, KPI surfaces, contextual-next-question) thread through the live public funnel + `/chat` — sequence after replacements.
5. **Lounge-exclusion is invariant, not yet codified** — `_render_chat_thread` UNVERIFIED; one careless future include = AC-6 breach.
6. **Label schema mismatch** — existing binary `coach_label` ≠ `direction-v1`; building before §7.1 resolves risks a migration.

## 9. Decisions surfaced (answer before build; do NOT resolve here)
1. **🔴 Homework product: REPLACE or COEXIST?** ~28 routes + 6 services + 3–4 tables, a separate live product the design ignores. Gates total BE scope. (Mirrors the FE map's §9.1 — must be answered jointly.)
2. **§7.1 label schema** — `direction-v1` vs the 28→12–16 scenario protocol. Blocks the `labels` store + whether existing `coach_label` is ADAPTed or replaced.
3. **§7.4 idempotency-key derivation** — per-recording, must survive the OAuth redirect. Blocks the send path.
4. **§7.9 lounge merge batch ceiling + Supabase RLS** — max batch + chunking + per-user RLS policy. Blocks merge hardening (core append can ship first).
5. **`session_context` per-recording vs per-session** — intake_context is per-`v2_sessions`. Confirm session≈recording in the beta, else session_context needs its own table.
6. **profile home** — extend `user_settings` (where derived fields live) or `v2_speaker_profiles` (where free-text goal lives)? Pick one to carry the domain enum + canonical goal.
7. **Cutover sequencing** — the live public funnel + `/chat` must stay shippable mid-migration; confirm the order (build Readout/status/Insights → re-point signals → delete old surfaces).

---
*Read-only audit. Verdicts grounded in the cited paths; `UNVERIFIED` items are flagged inline. Merges with `docs/willab_clearing_map_fe.md` (same 9-section schema) + the BE contract (`docs/willab_be_contract_v0.3.md`) to drive the build sequence.*
