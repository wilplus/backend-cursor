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

The payload shape: `row.practice_exercise = {exercise_id, version, title,
instruction, introduction, yes_introduction, no_introduction,
explanation_video_ref, passage, practice_id, resume, done_before}`, plus
`chosen_by_coach` on a coach-shared exercise. (Since 2026-09-29 it no longer
carries `matching_policy_version` or `pattern_distance`.)

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
4. **`pattern_distance` and `matching_policy_version` are gone** from the
   payload (founder 2026-09-29, AC-9). Nothing to render or ignore.

## 2. Coach: the panel for a moment no exercise fitted

`GET` and `PUT /v2/coach/sessions/<session_id>/snippets/<snippet_id>/exercise-request`
(admin or coach auth). This needs a BFF proxy route under `src/app/api/v2/`,
like the existing `confidence-practice` one.

**Gate: the same as the practice review.**
- `409 BLIND_RATING_REQUIRED` until the coach has saved their own rating on
  that moment (any of the five answers, founder 2026-09-29; until then only
  Yes and No counted). Call the endpoint only after that, exactly like
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
- The library list (`/v2/internal/journal/speaking-errors/list`) now has a
  third status, `shadow`: a detector is being tested silently. Show it as
  "being tested". It cannot be chosen as an exercise tag (the save refuses
  it), and the library form refuses to edit it (`409 ALREADY_IN_SHADOW`).

## 4. CMS: the gap view (step 5)

`POST /v2/internal/journal/exercise-gaps` uses the same CMS password as the
other internal endpoints. It is read-only.

Body: `{"password": "…", "days": 30}`. `days` is 1–90 and defaults to 30.

Response `200`:
```
{"days": 30,
 "patterns": [{
    "error_id", "label",
    "status": "detected" | "shadow" | "observed",
    "coverage": "no_exercise" | "trial_only" | "covered" | "being_tested" | "not_detectable_yet",
    "spotted": int,              // exercise moments it fired on in the window
    "open_coach_requests": int,  // unresolved requests naming it
    "main_exercises": [exercise_id], "secondary_exercises": [exercise_id],
    "shadow": {"clips_measured": int, "clips_fired": int}   // shadow only
 }],
 "nothing_spotted_open_requests": int,
 "unavailable": ["match_traces" | "coach_requests" | "shadow_observations"]}
```

- `patterns` is already in the order to show: patterns to film an exercise
  for first, then trial-only, covered, being tested, and not detectable yet.
- A name in `unavailable` means that source couldn't be read. Its numbers are
  not zeros, so say that rather than showing 0.
- This is an internal CMS screen, so numbers are fine here. It never goes
  anywhere near a speaker.

## 5. Coach: what the machine picked and why (step 6)

These fields appear only in coach payloads that are already behind the blind
rating.

**`GET /confidence-practice` → `practice.machine_pick`**, or `null` when the
moment had no automatic pick (a coach-shared exercise, or an older Take):
```
{"exercise_id", "version",
 "fit": "exact" | "trial" | null,
 "how_chosen": "best_match" | "trying_another" | "only_match",
 "traced": bool,
 "spotted": [{"error_id", "label"}],
 "candidates": [{"exercise_id",
                 "outcome": "ranked" | "excluded",
                 "reason": null | "nothing_spotted" | "targets_nothing_that_fired"
                         | "confidence_level_unplaceable" | "lower_fit_than_pool",
                 "rank", "fit", "main_targets", "secondary_targets"}],
 "rules_version"}
```

**`GET /exercise-request` → `request.candidates`**: the same candidate
rows, showing why nothing fitted.

Step 7 adds three things:
- Each candidate row carries `repeat_hits` (how many of this speaker's
  recurring problems it treats) and `done_before` (bool).
- `machine_pick.history` is
  `{available, repeated_patterns: [error_id], done_before: [exercise_id],
  earlier_takes}` as it stood at the draw. For example: "Rushing came up on
  earlier Takes too".
- Coach-facing only. The speaker already sees their own green "done" label
  on the card.

Notes:
- `trying_another` means the 80/20 draw picked a lower-ranked exercise on
  purpose, to learn whether it helps.
- A trial here is shown to the coach openly: it's their view, not the
  speaker's.
- `traced: false` means the pick is older than the saved reasons. Say that
  the reasons weren't recorded, rather than showing an empty list.
- Never shown, not even to the coach: the machine's confidence read of the
  clip and the raw measurements.
- Suggested UI: "Machine picked X (exact fit, best match) because it
  spotted Rushing", with a fold-out listing the other exercises and why
  each wasn't picked. The coach's existing choice controls stay as they are.

## 6. Speaker: confirm the exercise was seen (label spec, required)

The learning contract (§3.5 of `docs/MLC3-EXERCISE-ADEQUACY-DESIGN.md`)
counts an exercise as shown only once the speaker's app confirms it
rendered. Without this call, nothing can ever be learned about which
exercises help.

`POST /v2/user/snippets/<snippet_id>/exercise-rendered`, authenticated as the
speaker, needs a BFF proxy route like `confidence-practice`.

Body: `{"exercise_id": "<practice_exercise.exercise_id>"}`.

- **When:** the first time the exercise card (the one carrying
  `practice_exercise`) is actually visible on screen. For example, fire it
  from an IntersectionObserver at 50% visible, not when the data loads. Once
  per card per page view is enough. The backend records it once per offer
  anyway, so re-sending is harmless.
- **For every exercise card,** including a coach-shared one. The backend works
  out whether it counts.
- **Responses:**
  - `200 {"recorded": true}`: recorded.
  - `200 {"recorded": false}`: this moment had no automatic pick. Nothing to
    do.
  - `409 EXERCISE_OFFER_STALE`: the card shows an exercise other than the one
    offered. Refresh the Ideal Text.
  - `404`: not the speaker's snippet.
- **Fire-and-forget:** never block the UI on it, never retry in a loop, never
  show anything about it to the speaker.

## Fences

- The speaker never sees scores, ranks, distances, the fit type, or "trial".
- The coach panel appears only after the coach's blind rating.
- All new user-facing copy goes to the founder for sign-off.

The shapes above are final for this PR. Only testing against a live backend
waits on the merge.
