# Architecture — Single Source of Truth

**Status:** authoritative as of Phase 18.
**Audience:** anyone editing the cold-start onboarding flow, session lifecycle, scoring, or publish gates on either repo.
**Rule:** any code change that contradicts this doc is reverted. Edit this doc IN THE SAME COMMIT as architectural changes; the `git log` on this file IS the change history.

This document supersedes any older onboarding / EBCP description in either repo. When this doc and a previous markdown disagree, this doc wins.

---

## 0. Core Principle

- **Frontend** owns presentation, hardcoded onboarding copy, and user timing.
- **Backend** owns dynamic logic, state transitions, scoring, and data persistence.
- There are **NO** duplicate strings or overlapping responsibilities.

If a question text is both in a backend Python file AND in a frontend TSX file, one of them is wrong — and per the rule above, the frontend wins for turns 1–4 and the backend wins for turn 5+.

---

## 1. The Cold Start (Turns 1–4) — Ownership & Copy

**Rule:** Frontend owns turns 1 through 4 entirely. They are 100% hardcoded, static strings.

The backend is NOT called by the frontend until the user has submitted their answer to turn 4 (via the `upload-answer` endpoint). The backend's `next-question` endpoint **refuses** requests for `turn_number ≤ 4` with `400 INVALID_INPUT` and a code of `TURN_OWNED_BY_FRONTEND`. This is a guardrail so a confused client can't accidentally drag the backend back into owning these turns.

The immutable strings for the frontend's `ONBOARDING_MESSAGES` array:

| Slot | Text |
|---|---|
| M1 | `Quick baseline first. I'm going to ask you some off-the-wall questions. Just go with it — there's a method.` |
| M2 | `All right. I want you to imagine you have a younger sibling who's struggling with a math problem. They're stuck, they're frustrated. What do you say to them?` |
| M3 | `Got it. One more. Picture this: you're in a meeting and someone presents an idea you strongly disagree with. Do you speak up immediately, or wait and think it through?` |
| M4 | `Last weird one, I promise. Do you generally like math? Quick yes or no — trust me, this matters.` |

**Returning users (`baseline_established=TRUE`) see the same M1–M4.** The strings are calibration prompts, not first-session-only content. The previous "smart-EBCP-bypass" branch in `_generate_llm_question` is removed in this phase as dead code.

---

## 2. The `baseline_established` Flip Point

**Rule:** `baseline_established` flips to `TRUE` **immediately upon successful submission of turn 4**.

- **Backend:** in `v2_public_interview_upload_answer`, when `turn_number == 4` and the upload succeeds, `mark_baseline_established(user_id)` fires before the response returns. The Phase 16 baseline-summary compute is triggered from the same point (synchronously here so the next turn-5 prompt has the digest ready).
- **Replaces:** the prior wiring where the flip happened lazily at the first turn-5 `next-question` request. That moved the side-effect away from the moment it semantically belonged.

Re-running upload-answer on turn 4 (idempotent retry) is safe — `mark_baseline_established` is upsert + a no-op when the flag is already TRUE.

---

## 3. Session End Condition (30s Rule)

**Rule:** the frontend enforces the 30-second aggregate threshold.

- **Frontend:** tracks aggregate recording duration across turns. When it hits 30s OR the user clicks "Done", calls `POST /v2/public/interview/finalize` (or the existing `/finalize-recording` admin route — frontend agent owns picking the right one).
- **Backend:** finalizes when the endpoint is hit. Does NOT track aggregate duration independently. The server should not assume a user is "done" based on elapsed time alone; finalize is always an explicit client action.

---

## 4. Turn 5+ Tone Alternation

**Rule:** backend dictates tone; frontend renders it blindly.

- **Backend** (existing, unchanged): `tone = "charisma" if (turn_number - 4) % 2 == 1 else "stress"`. Returned in the response: `{"tone": "...", ...}`.
- **Frontend:** removes any local tone-guessing logic. Reads `response.tone` and renders accordingly.

---

## 5. Follow-Up Question Provenance & AI Drafts

**Rule:** backend generates the draft; admin owns the final publish.

- **Backend:** auto-generates `ai_draft_follow_up_question` when the admin first saves a snippet's `admin_comment`. Implementation already lives in Phase 10 (`/admin/snippets/<id>/comment` handler). The `ai_draft_follow_up_question` column is immutable from the admin UI — it freezes the AI's original wording for the publish-time RLHF comparison.
- **Frontend:** the admin UI surfaces the draft as placeholder text on the editable `follow_up_question` field. Admin can keep, edit, or replace. The final saved string is what the user sees.
- **At publish time:** the (`ai_draft_follow_up_question`, `follow_up_question`) pair is emitted to `admin_annotation_events` for fine-tuning training (Phase 10). `approved_as_is` when they match; correction signal when they differ.

---

## 6. Publish Gate SQL

**Rule:** whitespace does not count as a comment.

- **Backend:** every read path that gates on "snippet has a comment" filters with `admin_comment IS NOT NULL AND TRIM(admin_comment) <> '' AND is_skipped = FALSE`. The Python supabase-py client doesn't expose a TRIM filter; the implementation applies a Python-side `.strip()` filter immediately after the DB `not_.is_("admin_comment", "null")` query (commit history on this file shows the change).

Functions affected:
- `services.db.v2_get_results_snippets_for_session` (user-facing /results)
- `services.db.get_snippets_with_comments_by_session` (admin views)

Any future read path that gates on `admin_comment` MUST apply the same strip-filter. If you find a third call site, add it to the list and patch it.

---

## 7. Snippet Extraction Targets

**Rule:** the pipeline targets 3–5 published snippets per session after Non-Maximum Suppression (NMS). Soft target, not a hard guarantee.

- A session with sparse audio (very short, low signal) may yield 0–2 snippets. That's fine.
- A long, dense session may yield 6+; NMS keeps the top 5 by composite score.
- Implementation: `services.snippet_truncation.apply_extracted_snippets`. Re-running is idempotent via window-keyed diff — same audio produces the same snippet set.

---

## 8. Backend ↔ Frontend Contract Summary

| Path | Method | Owner | When |
|---|---|---|---|
| (M1–M4 strings) | client-only | Frontend | First 4 turns — never hits backend |
| `/v2/public/interview/upload-answer` | POST | Backend | Every turn upload (1, 2, 3, 4, 5, …) |
| `/v2/public/interview/next-question` | POST | Backend | Turn 5+ only; turns 1–4 refused 400 |
| `/v2/public/interview/finalize` | POST | Backend | When frontend hits 30s aggregate OR user clicks Done |
| Compute Metrics (admin) | POST | Backend | Admin clicks; computes B6 + Stickiness + drift guard |
| Publish session | POST | Backend | Admin clicks; flips `results_published_at` + emits email + RLHF |
| Unsubscribe (token) | POST | Backend | User clicks footer link in email |

---

## Versioning

Same convention as `docs/ACOUSTIC-METRICS-INVENTORY.md`: edit this doc with the same commit that changes the contract. `git log -- docs/ARCHITECTURE_SINGLE_SOURCE_OF_TRUTH.md` is the history of architectural decisions.
