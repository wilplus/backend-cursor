# willab — FE ↔ BE Compatibility Audit (Lounge & Coach UX batch)

**Status:** BE-answered 2026-06-08 against `main` @ `97ef21ab2`. Verified-against-main,
not from memory — every row cites the handler it was checked at.

The FE calls BFF routes `/api/v2/…` → `${backend}/v2/…`. This file is the living
record of the FE→BE touchpoints for the C1/N1/U1–U13/C2 batch + the open decisions.

---

## §1 — existing contracts the FE depends on — CONFIRMED UNCHANGED

| Endpoint | FE expects | Verified at | Verdict |
|---|---|---|---|
| `POST /v2/chat/query` | `{answer: string}` | `return jsonify({"answer": …})` v2_routes.py:3579 | ✅ now `@optional_auth` (anon allowed; DSP/Path-B skipped for anon, `answer` always present) |
| `GET /v2/coach/queue` | rows `{session_id,pseudonym,domain,topic,n_snippets,state,sent_at}`, `state∈{pending,in_progress,done}` | v2_routes.py:7525, `_coach_session_state`:7517 | ✅ shape — **but see C2** |
| `GET /v2/coach/sessions/<id>` | `{…, video_ref, snippets[]{…,features}}` | v2_routes.py:7555; `features`:7590; `video_ref`:7606 | ✅ |
| `POST /v2/coach/sessions/<id>/snippets/<id>` | split-sink write, echoes `coach_state` | v2_routes.py:7615 — `direction_label`→`training_labels`; `note/tag/surfaced/when/examples`→drafts→`insights_payload`@publish | ✅ no cross-derivation |
| `POST /v2/coach/sessions/<id>/video` | `{video_ref}` | v2_routes.py:7754 → `{status,session_id,video_ref}` | ✅ superset |
| publish | `{overall_message,notes[],labels[],notify_client}` → published | v2_routes.py:4566; assemble-mode `{overall_message,notify_client}`:4452 | ✅ both modes |
| `GET /v2/user/sessions/<id>/readout` | `features`(incl `mean_pause_seconds`),`stickiness`,`insights_payload{overall_message,video_ref}`,snippets+`audio_ref`+offsets | v2_routes.py:7199 → `{session_id,published,state,readout}` — **all fields nested under `readout`** | ✅ FE reads `data.readout.*` |
| Lab upload (seam ③) | audio+session_context → readout, 201/422 | v2_routes.py:7965 `audit_upload` → `process_lab_recording` | ✅ |
| profile | `is_coach: boolean` | v2_routes.py:7056 (render-only) | ✅ |
| Lounge thread | server-persisted when signed in | `/v2/user/lounge/messages` GET/POST/DELETE:8074+ | ✅ |
| publish realtime + status reconcile | `review_pending`→`insights_ready` | v2_routes.py:7232/7291/7412 + lounge card on publish | ✅ |

**AC-9 invariant — HOLDS.** No private-lane field (`direction_label`, KPI, charisma,
salience/control) is serialized to a *user* surface. The C1 `features` add is
coach-surface only; the user readout already carried the same vector by design.

---

## §2 — new this batch

- **C1 — `features` on coach packet:** ✅ merged to `main` (`97ef21ab2`, PR #54).
  Auto-deploys off `main`. **Confirm live with one prod curl of
  `/v2/coach/sessions/<id>` → `snippets[].features` before the FE relies on it.**
- **U12 — coach review-pending email:** ⚠️ **does not exist.** The only willab-loop
  email is the user-facing results-ready email on publish (CTA → `/results`,
  v2_routes.py:4748). No email fires on send-to-coach; the coach polls the queue.
  Legacy coach templates (`/recordings/{id}/feedback`, `/admin/students/{id}`) are
  old-admin era and NOT wired into the willab send path. If a coach email is wanted
  it is net-new BE work → should link `/chat?review=<id>`.
- **C2 — queue `done` reconcile:** ⚠️ **gap.** `db.list_review_queue` (db.py:8696)
  filters out published rows (`if not r.get("results_published_at")`), so a published
  session is **dropped from `/v2/coach/queue`** — it never returns `state:"done"`
  there. The per-session `GET /v2/coach/sessions/<id>` DOES return `"done"`.
  **DECISION NEEDED:**
  - **(a) FE-only** — reconcile per-session via `GET /v2/coach/sessions/<id>`; treat
    queue-absence as "published". No BE change.
  - **(b) BE** — keep published rows in the queue with `state:"done"` (+ recency cap
    so the queue doesn't grow unbounded).
- **U3/U4 — bubble splitting:** no BE change. `answer` is a plain string with the
  LLM's own `\n\n`; deterministic breaks would be prompt-level (frozen).

---

## §3 — pending FE items — BE disposition

- **U6 — remove insights-ready banner:** ✅ safe. Publish appends the in-thread card
  `"Your coach's insights are ready."` (`kind:"insight"`), idempotent on
  `uuid5("willab-insight:<session_id>")` (v2_routes.py:4528). Caveats: best-effort
  (failure logged `lounge_append_failed`, non-fatal) + requires a claimed/signed-in
  owner. Keep the `insights_ready` state-reconcile as the thread-reload trigger.
- **U10 — feeling persistence:** no destination yet. Recommend `session_context.feeling`
  (enum `nervous|excited|calm|unsure`) — `intake_context` is JSONB, no migration.
- **U11 — server-configured recording minimum:** not exposed (client enforces 60s).
  Small add (config or `session_context`).
- **M1/M2 — credits + checkout:** balance store live in prod
  (`v2_student_details.credits`, `lab_credits_charged_at`,
  `stripe_checkout_credit_grants`); the checkout flow + balance-read endpoint are
  net-new.
- **C3 — coach student list:** net-new pseudonymized endpoint (§B.4 — pseudonym +
  domain only, never name/email).

---

## §4 — checklist

- [x] §1 contracts unchanged in code
- [x] C1 `features` on `/v2/coach/sessions/<id>` (merged; confirm via prod curl)
- [ ] Coach review-pending email link target = **N/A (no such email; net-new → `/chat?review=<id>`)**
- [ ] `/v2/coach/queue` returns `state:"done"` for published = **No (filtered out); pick C2 (a) or (b)**
- [x] In-thread "insights ready" appended on publish (U6 gate) = **yes, best-effort/claimed-owner**
- [ ] U10 feeling destination = **none yet; recommend `session_context.feeling`**
- [ ] U11 server min / M1-M2 credits+checkout / C3 student list = **net-new, freeze-gated**

---

## Open BE decisions (await founder/FE call)

1. **C2** — option (a) FE per-session reconcile, or (b) BE keeps published in queue.
2. **U12** — ship a coach review-pending email (→ `/chat?review=<id>`), or keep queue-poll only.
3. **U10/U11/M1/M2/C3** — unfreeze order once beta feedback lands.
