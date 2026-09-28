# Frontend brief: exercise routing, steps 1–3 (2026-09-28)

From the backend exercise-routing work on `wilplus/backend-cursor`
`claude/stoic-mayer-il3c6r`. The founder split the work: the backend owns the
engine and matching, the frontend (`wilplus/frontend-cursor`
`claude/stoic-lamport-t1xxt9`) owns placement and visuals. Merging the backend
PR runs migrations 0384 and 0385 in production.

**Founder decisions (2026-09-28):**
- **D1:** an exercise shows only when a detected problem fired on that exact
  clip.
- **D5/D5a:** with no exact fit, an exercise that lists the problem as a
  **secondary** target is served as a trial.
- **D6:** trials never compete with exact fits.
- **D2:** spoken-word cues may route exercises later.
- **D2a:** a rewrite on the same paragraph still wins.
- **D3:** new patterns are tested silently first.
- **D4:** the speaker may get one plain sentence on why this exercise (the copy
  needs founder sign-off).

Contract clauses: 35g-1 and 35g-2 in `docs/CANONICAL_PRODUCT_CONTRACT.md`.

## 1. Speaker: the V3 exercise item (`bookmark_tier = "exercise"`)

The payload shape is unchanged: `row.practice_exercise = {exercise_id,
version, title, instruction, introduction, yes_introduction, no_introduction,
explanation_video_ref, passage, practice_id, resume, matching_policy_version,
pattern_distance, done_before}`.

Behaviour to design for:

1. **The exercise item now often has no `practice_exercise` at all.** Either
   nothing was spotted, or nothing in the library targets what was. Per
   contract 24f the item shows "Let's practice" with no exercise. It should
   look intentional, not broken.
2. **New optional field `practice_exercise.chosen_by_coach: true`.** A coach
   picked this exercise for this exact moment, and it arrives on a later poll.
   Whether and how to say "your coach chose this" is your call, plus founder
   copy sign-off. The practice starts the normal way:
   `POST /v2/user/snippets/<snippet_id>/confidence-practice` with
   `exercise_id`. The backend accepts it.
3. **"Trial" is never in the payload.** Never infer it or show it. A trial
   looks exactly like any other exercise.
4. **Don't render `pattern_distance`** (a number, AC-9) **or
   `matching_policy_version`.** `pattern_distance` is pre-existing and will be
   removed from the payload in a follow-up.

## 2. Coach: the panel for a moment no exercise fitted

`GET` and `PUT /v2/coach/sessions/<session_id>/snippets/<snippet_id>/exercise-request`
(admin or coach auth). This needs a BFF proxy route under `src/app/api/v2/`,
like the existing `confidence-practice` one.

**Gate: the same as the practice review.**
- `409 BLIND_RATING_REQUIRED` until the coach has saved their own yes/no
  rating on that moment. Call the endpoint only after that, exactly like
  `/confidence-practice`. Nothing about the request may appear before the
  rating (the BLIND COACH fence), not even a badge saying one exists.
- `409 SPEAKER_PRACTICE_OFF`: the speaker turned practice off. Show nothing.
- `404 NOT_FOUND`: no request for this moment, which is the normal case. Show
  nothing.

**`GET` → `200`:**
```
{"request": {
  "id", "take_session_id", "snippet_id",
  "reason": "nothing_spotted" | "nothing_targets_it",
  "spotted": [{"error_id", "label"}],
  "created_at",
  "resolution": null | "exercise_chosen" | "exercise_authored" | "no_safe_match",
  "resolved_exercise_id", "resolved_at", "shared_at",
  "offered_since": bool,
  "available_exercises": [{"exercise_id", "version", "title", "instruction",
                           "explanation_video_ref"}]   // best match first
}}
```
- Copy ideas for `reason`: "Nothing specific was spotted", or "Spotted:
  \<labels> — no exercise in the library treats it yet".
- `offered_since: true` means the library has since matched this moment and
  the speaker already got that exercise, so a share from here won't reach
  them. Say so.

**`PUT` body, one of:**
```
{"resolution": "exercise_chosen", "exercise_id": "…", "share_with_user": bool}
{"resolution": "exercise_authored",
 "custom_exercise": {"title", "explanation_video_url" (required), "instruction"?,
                     "acoustic_problem_tags"? (defaults to what was spotted;
                     must be detectable library errors),
                     "matching_criteria"? {"primary_problem_tag"?}},
 "share_with_user": bool}
{"resolution": "no_safe_match"}          // cannot be shared
```
- Success returns `200 {"request": {…}}`.
- Errors: `400 INVALID_INPUT`, `409 EXERCISE_UNAVAILABLE`,
  `409 EXERCISE_COACH_REQUEST_ALREADY_RESOLVED`, and catalogue refusals such
  as `400 TAG_NOT_DETECTED`, which carry a readable sentence. Show that
  sentence as it is.
- **The answer is one-time.** Sending the same answer again is harmless and
  can add the share later: send the same resolution with
  `share_with_user: true`. A different answer is refused. The UI should make
  the commitment clear before submit.
- An authored exercise is filed into the shared library (id
  `coach-request-<id>`) and becomes reusable for any speaker whose clip shows
  that problem.

## 3. CMS: exercise editor

- `matching_criteria.primary_problem_tag` (optional) names the exercise's
  **one** main target. All other `acoustic_problem_tags` become secondary
  targets, which can only ever serve the exercise as a trial.
- It must be one of the exercise's own tags, or the save is refused with a
  sentence.
- With none set, every tag counts as a main target, which is how exercises
  behave today.
- Suggested UI: pick the main target from the tags already selected.

## Fences

- The speaker never sees scores, ranks, distances, the fit type, or "trial".
- The coach panel appears only after the coach's blind rating.
- All new user-facing copy goes to the founder for sign-off.

The shapes above are final for this PR. Only testing against a live backend
waits on the merge.
