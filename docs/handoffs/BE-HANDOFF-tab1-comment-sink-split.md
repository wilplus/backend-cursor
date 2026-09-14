# BE handoff — split the comment sinks (user-visible vs. pipeline-only)

Status: **BE-only routing change. FE work optional (UX label only). One product question for you below.**

---

## Brief recap

> Snippet comment → user AND pipeline. AI commentary edits → pipeline only. Already two distinct fields; just enforce the destinations.

Translation: when an admin edits **per-snippet comments**, the edit feeds the user's results page AND the RLHF log. When an admin edits the **session-level KPI narrative**, the edit feeds the RLHF log ONLY — users keep seeing the original AI-generated text, not the admin's correction.

The premise is right on (a) and almost right on (b). Today, both surfaces leak admin edits to the user. (a) is intentional and stays. (b) is the bug-shaped-thing this task fixes.

---

## What's already true (no change)

**Per-snippet `admin_comment`** writes already do the right thing:
- Persists to `charisma_snippets.admin_comment` ([routes/v2_routes.py:13293](routes/v2_routes.py:13293))
- User sees it on the published `/results` page (snippet card rendering reads the column directly).
- RLHF capture fires at publish time via `record_snippet_publish_annotations` → `admin_annotation_events` table (writes the (ai_draft, admin_final) pair per snippet).
- `acceptance_mode` flag persisted on the snippet row for the publish-time annotator to read.

Nothing to change here — it's already user + pipeline.

---

## What changes on BE

**Session-level KPI narrative** (`v2_sessions.ai_task_alignment_comment`, surfaced as `session_kpi_narrative` in API responses): admin edits currently leak to user-facing pages. After this task ships, they won't.

### The four leak sites

| Reader | What it returns | Today | After |
|---|---|---|---|
| `services/charisma_profile.py:878` `_build_narrative` | top-of-dashboard narrative on `/results` | reads `ai_task_alignment_comment` (= admin's edit if any) | read `session_kpi_narrative_ai_draft` (= immutable AI text) |
| `routes/v2_routes.py:8209` (user/results) | `ai_summary` | same | same fix |
| `routes/v2_routes.py:8539` (user/results) | `ai_summary` | same | same fix |
| `routes/v2_routes.py:11120` (user/sessions/current) | `ai_summary` | same | same fix |

All four switch to reading the IMMUTABLE `session_kpi_narrative_ai_draft` column (added in commit `24c3ee9` last task). Admin's edit stays in `ai_task_alignment_comment` and only feeds `admin_annotations_log` via the RLHF row the PATCH endpoint writes.

### The admin-facing surface stays the same

`GET /v2/admin/sessions/<id>` continues to return both fields under `global_metrics`:
- `session_kpi_narrative` — the editable value (what admin has saved)
- `session_kpi_narrative_ai_draft` — the immutable AI baseline

Admin Tab 1 still edits the same field via the same PATCH endpoint (`/v2/admin/sessions/<id>/kpi-narrative`). The gate, the override checkbox, the 422 response — all unchanged.

### "User-side publish events"

The publish path (`POST /v2/admin/sessions/<id>/publish`) ships these user-side side effects on click:
1. `results_published_at` stamped → makes the dashboard visible
2. "Results ready" email sent to the user
3. RLHF rows written to `admin_annotations_log` (session-level + per-position)

Per the brief, the snippet-comment edit is the only thing that should trigger user-side events — but really, **all user-side events are tied to the Publish action itself**, not to individual field saves. Per-snippet `admin_comment` saves through `/comment` don't trigger publish; they just update the column the published page later reads. Same for KPI narrative edits — `PATCH /kpi-narrative` doesn't trigger publish.

So the "only snippet-comment update triggers user-side publish events" framing is mildly misleading: NEITHER per-field save triggers publish. The publish click does. The fix is making sure the user-visible read paths don't surface admin's KPI narrative edits — which is what the four-site change above does.

---

## What FE needs to do — probably nothing, optionally one label tweak

### Required: nothing

The admin's existing edit UX, the PATCH contract, the gate behavior, the 422 envelope, the new `pinned` block, the response shape — all unchanged. FE doesn't need to touch a line for this task to take effect.

### Optional UX nuance — surface the new semantic

After the BE change ships, admins will edit the KPI narrative knowing their edits **won't be visible to the user**. That's a meaningful shift from how the field behaves today. Consider a subtle label / tooltip on the edit UI to reflect this:

Suggested copy (pick whichever fits your tone):
- *"Your edits train the model. They don't change what the user sees."*
- *"Internal — feeds the AI pipeline only. User sees the original draft."*
- *"Edits here improve future generations. User-facing copy stays as the AI wrote it."*

Putting it inline below the textarea (small grey text) is enough — admins will read it once, internalize it, ignore it after. No structural FE change needed; just one new string.

Per-snippet comment editor stays untouched — its edits DO reach the user, so no label change needed there.

---

## ⚠️ One product question I need you to confirm before BE ships

The brief says admin's KPI narrative edits should be **pipeline-only**. Hard interpretation: user sees the immutable AI text, NEVER admin's correction. Softer interpretation: user sees admin's correction ONLY when the admin published a real fix (the gate's diff > 5 path) and not on cosmetic edits.

| Option | What user sees on KPI narrative | When admin edit feeds RLHF | Implementation |
|---|---|---|---|
| **A (strict — brief literal)** | Always the immutable AI text | Always (on diff > 5 OR explicit minor-edit override) | Four leak sites read `session_kpi_narrative_ai_draft`. Editable column is RLHF-only. |
| **B (soft)** | Admin's edit when diff > 5; AI text on trivial / no edit | Same as A | Four sites read `ai_task_alignment_comment` when the diff is non-trivial, otherwise fall back to draft. Needs the leak sites to be diff-aware. |
| **C (status quo, do nothing)** | Always admin's edit (if any) | Already wired | Reject the brief — admin's edit IS the canonical "improved" text. |

My read of the brainstorm: **A** is what you want. The whole point of separating the columns is that admin's edits live in the pipeline, not in the user's results. The user's experience is bound to the AI's voice; the admin teaches the AI without overriding the user's session-specific story.

But A means admins might edit something they think will reach the user (the AI saying "you stayed composed" when the user clearly didn't), and that correction never surfaces. That's the trade-off the brief takes.

**Confirm A and I'll ship the four-site change in one ~20-LOC commit.** B is a follow-up if you change your mind. C is "drop this task entirely" — nothing to ship.

---

## Acceptance criteria when BE ships (Option A)

1. Admin edits session KPI narrative with a 10-word change → 200, `admin_annotations_log` row written, `session_kpi_narrative_ai_draft` UNCHANGED, `ai_task_alignment_comment` updated.
2. User reloads `/results` for that session → narrative shown is the AI's original (from `session_kpi_narrative_ai_draft`), NOT the admin's edit.
3. Per-snippet admin_comment edit → user sees the edit on the snippet card on `/results` (unchanged from today).
4. Both edits visible in admin's Tab 1 view (the GET endpoint surfaces both fields).
5. Publish click still works end-to-end (email + visibility + RLHF rows) regardless of which field was edited last.

---

## Reply with

Just "A" / "B" / "C". If A, I ship same-day. If A with a UX label, drop the copy you want and I'll ship a doc note pointing FE at it. If B or C, talk through the trade-off briefly and I'll adjust.
