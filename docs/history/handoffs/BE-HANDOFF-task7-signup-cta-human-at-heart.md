# BE handoff — Task 7: "4h human-at-heart" CTA + post-signup confirmation

Status: **Almost entirely FE work. One BE copy change (~5 LOC) and one product question to settle before I touch anything.** The backend plumbing is already shipped end-to-end across tasks 6 and the existing claim flow.

---

## TL;DR of the user journey vs. what's wired

| Step | Surface | Wired? |
|---|---|---|
| 1. User finishes session 1 | `POST /v2/public/interview/finalize` returns 200 with `completion.ready=true`, narrative + stickiness computed sync, `next.signup_cta: { show: true, copy: "..." }` | ✅ Task 6 — commit `082ea33` |
| 2. AI commentary block renders | FE reads `next.narrative_status` + the existing `session_kpi_narrative` field exposed on `/admin/sessions/<id>` GET / `compute-metrics` response | ✅ Phase 18.x — commit `24c3ee9` |
| 3. "Sign up for full analysis" CTA renders | FE reads `next.signup_cta.show` (true) + `next.signup_cta.copy` (currently the placeholder) | ⚠️ Copy needs update — see §1 |
| 4. User clicks CTA → signs up → claim fires | `POST /v2/public/shaky-voice/claim` body `{guest_session_id}` (or `POST /v2/auth/merge-session`) | ✅ Already shipped pre-task-7 |
| 5. Claim binds session to user + queues for admin review | `_merge_anonymous_session_into_user` calls `finalize_session_pending_admin_review` → computes metrics + KPI + narrative, flips status to `pending_admin_review`, sends admin notification email | ✅ Already wired |
| 6. Claim response confirms queue state | Returns `{ status: "ok", session_id, analysis_status: "queued", finalize: {...} }` | ✅ Already wired |
| 7. FE shows "human at heart, ~4h" confirmation message | Pure FE render off `analysis_status: "queued"` | ⏳ FE work |

**Net: one ~5-LOC copy change on BE (the CTA copy default) + a product decision on the SLA wording. Everything else is already plumbing that FE can wire today.**

---

## §1 — The BE copy change

Today's placeholder in [routes/v2_routes.py:17070](routes/v2_routes.py:17070):

```python
_FINALIZE_SIGNUP_CTA_COPY = (
    "Create your free account to save your results."
)
```

Task 7 wants this to match the brief's intent: a call to **the full professional analysis**, not just an account-save framing. Strawman new default:

```python
_FINALIZE_SIGNUP_CTA_COPY = (
    "Sign up for your full analysis."
)
```

(7 words → short, action-first. Matches the brief's "Sign up for full analysis" phrasing.)

This is the copy that ships in `next.signup_cta.copy` on the finalize 200 response. **FE renders it verbatim, doesn't override.** That's the whole point of the BE-flag contract — copy is A/B-able and personalisable server-side later without an FE redeploy.

If you want a different default copy, tell me the string and I'll ship it. Otherwise I'll use the above.

---

## §2 — The product question that blocks me

The brief itself flags this:

> "4h" is a hard SLA you'll have to actually deliver on. If volume spikes you eat your reputation. Consider "within one business day" as the public-facing string.

Three reasonable options for the post-signup confirmation message:

| Option | Copy | Trade-off |
|---|---|---|
| **A** | *"Our system is human at heart — your professional analysis arrives within ~4 hours."* | Crisp, matches the brainstorm. **You'll have to actually deliver in 4h on every claim**, or admins must staff to keep that promise. |
| **B (defensive)** | *"Our system is human at heart — a coach will personally review your session and email you within one business day."* | Honest under load. Slower-feeling but doesn't burn trust on a busy week. |
| **C (hybrid)** | *"Our system is human at heart — a coach will personally review your session. You'll usually hear back within a few hours; always within one business day."* | Sets expectations both ways. Slightly longer copy. |

I have no opinion on which is right — it's a coaching-ops capacity call. Whichever you pick, the copy can live either:

- **Pure FE**: static string in the FE bundle. Cheapest. Change requires a FE deploy.
- **BE-flag** (matching the signup CTA pattern): add `analysis_eta` to the claim response so the copy is A/B-able and changeable without FE deploy.

If you want BE-flag, tell me the string + I'll add the field to the claim response. If pure FE, no BE work needed for this — just decide and put it in the FE component.

---

## §3 — What FE needs to wire (the meat of the work)

### Step-by-step UX flow

1. **User finishes session 1.** Recorder is open. On the upload that flips `session_1_complete` (or `completion_state.ready`) to `true`, fire the existing `onThresholdReached` callback.

2. **FE calls** `POST /v2/public/interview/finalize` with `{ guest_session_id, total_duration_seconds, reason: "threshold" | "user_done" }`.

3. **On 200**, FE renders:
   - The AI commentary block (the narrative — already in the response chain; if FE doesn't have it cached, GET `/v2/admin/sessions/<id>` via the BFF works but the narrative is also available off the existing compute-metrics response that finalize triggered)
   - The signup CTA button with `next.signup_cta.copy` as the label
   - "Powered by [stickiness top topic]" or whatever surface FE wants for stickiness data (also available via the same routes)

4. **On 422 SESSION_INCOMPLETE** (defensive — shouldn't happen if FE honoured the probe), surface a toast: "Need one more answer to wrap up."

5. **User clicks CTA → signup flow → on success → FE calls** `POST /v2/public/shaky-voice/claim` with `{ guest_session_id }` + auth bearer.

6. **On 200**, FE reads `analysis_status: "queued"` and renders the post-signup confirmation message (the one whose copy you pick in §2).

7. Done. The session is now in the admin Pending Review queue; admin gets the notification email; coach reviews + publishes results; "Results Ready" email sends to the user (existing Phase 14 path).

### Concrete FE deliverables

- **Finalize handler** — already mostly in place if the existing flow has it; just consume `next.signup_cta.{show, copy}` and `next.narrative_status` from the new response.
- **Signup CTA button** — text from `next.signup_cta.copy`, action = navigate to signup.
- **Post-signup confirmation screen** — renders after the claim returns 200 with `analysis_status: "queued"`. Copy per §2. Maybe include the user's first name + a "we'll email you" line.
- **Idempotency** — if the user double-clicks the CTA or refreshes during signup, the claim handles it (the underlying `_merge_anonymous_session_into_user` is safe to call repeatedly; subsequent calls just re-finalize).

---

## §4 — What FE can stop doing

Anywhere the FE has logic that "decides on its own" when session 1 is complete (the old 30s `DEFAULT_AGGREGATE_THRESHOLD_SECONDS` constant in `ChatInterview.tsx`): **delete it.** Backend is now the gate authority via task 6. The only client-side completion math is the live-progress display ("X / 1 charisma answers" UI), which reads off `completion_state` or `session_1_gate` from upload-answer responses.

---

## §5 — Open questions in one place

| Q | My recommendation | Needs your call |
|---|---|---|
| New CTA copy default (replaces "Create your free account to save your results.") | `"Sign up for your full analysis."` | Confirm or override |
| Post-signup wait-time copy (A/B/C in §2) | **B** — defensive, won't burn trust on a busy week. You're at v1 ops capacity; promise the conservative envelope and over-deliver. | Pick A / B / C / custom |
| Wait-time copy delivery — pure FE string or BE-flag (`analysis_eta` field on claim response)? | **BE-flag** for consistency with the CTA pattern. ~3 LOC server-side; future tuning never needs a FE deploy. | Confirm |
| Anything else FE needs from the claim response? (eta in minutes, queue position, etc.) | Skip until requested — `analysis_status: "queued"` is the v1 signal. | If yes, what fields |

---

## §6 — Acceptance criteria (when both sides ship)

1. Guest user records session, hits the gate (charisma + stress + 60s) → FE shows AI commentary + signup CTA labelled per the new `next.signup_cta.copy`.
2. User clicks CTA → signs up → claim returns 200 with `analysis_status: "queued"`.
3. FE renders the post-signup confirmation message (whichever §2 option ships).
4. Session shows up in admin Pending Review queue within seconds (already true via `finalize_session_pending_admin_review`).
5. Admin gets the lesson-complete notification email (already true via `_send_lesson_complete_to_admin`).
6. When admin publishes → user gets the "Results Ready" email (existing Phase 14 path).

---

## Reply with

Three answers:

1. **CTA copy** — `"Sign up for your full analysis."` or something different
2. **Wait-time wording** — A / B / C / custom string
3. **Wait-time delivery** — pure FE or BE-flag (`analysis_eta` field on claim response)

Once I have those I ship the ~5-30 LOC BE change (copy update + optional eta field) and the contract is locked. FE can wire its half in parallel.
