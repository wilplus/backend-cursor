# SPEC — Sales Training Mode (draft, not implemented)

**Status:** DRAFT for founder review. No code has been written. Section 9 is the
implementation prompt to hand to an engineer or agent once the open decisions in
section 2 are settled.

**Origin:** founder request 2026-09-25, for the hair-spa front-desk pilot
(24 employees, 5 locations, 8 takes over 2 weeks, blind listening by colleagues
and an outside panel, compared with real sales).

```
FILTER: ADVANCE-F2 (conditional) — cat F2 — fences clear IF §3 holds (AC-9, CONSTRUCT, BLIND, LIVE LOOP, copy sign-off) — locks clear IF peer/panel lanes stay separate (L3) — redirect: none
```

---

## 1. What it is

**Sales Training Mode** is a per-user mode that an admin turns on for chosen users.
A user in the mode:

1. practices a fixed sales pack (one project, four slides: open and ask,
   recommend, objection, close) across 8 takes in the normal Lab;
2. is told **before** some takes that the take will be shared with colleagues for
   blind listening. Takes without that notice are never shared;
3. listens to and rates anonymous clips from colleagues at other locations.

Everything else is the normal app. Recording, processing, Ideal Text and Manager
Feedback run exactly as they do today.

The purpose is research: to find out whether (a) blind listeners can pick out the
best sellers, (b) people improve over 8 takes, and (c) knowing a take will be
heard by peers changes how people speak (the "shared" vs "private" comparison
within each person).

## 2. Open decisions (founder)

| # | Decision | Default in this spec |
|---|---|---|
| D1 | Which takes are shared | **Take 1 private and unannounced. Even takes (2, 4, 6, 8) shared and announced. Odd takes (1, 3, 5, 7) private.** This is configurable (`share_pattern`). If "uneven" means odd takes, set the pattern to odd-except-1. |
| D2 | Can a user make an announced take private instead? | **Yes, always.** The take then stays private, and the choice is logged. Consent must stay voluntary. |
| D3 | Second listener question, "Would you buy from her?" | **Not built until defined.** It needs a one-line operational definition, answer options and a new SPEC §17 entry (CONSTRUCT fence). Until then only the existing confidence question ships. |
| D4 | Spacing between takes | **At most one take per calendar day** (user's local time). |
| D5 | Outside panel | Outside listeners get rater-only accounts in the same mode (`role = panel`). They never record. |
| D6 | All user-facing copy in §6 | **DRAFT.** It needs founder sign-off before release (LIVE LOOP fence). |

## 3. Non-negotiable rules

1. **Never share an unannounced take.** A clip enters the listening queue only if
   the take has `visibility = 'shared'` **and** a stored `announced_at` earlier
   than the recording start. Takes recorded before the mode was on, or without a
   notice, are never shared, including retroactively.
2. **No numbers to users (AC-9).** Employees never see ratings, counts,
   rankings, percentages or who rated what, about themselves or anyone else.
   Results leave the system only through the admin export.
3. **Separate rating lanes (L3).** Ratings in this mode are stored in new lanes
   `sales_peer` and `sales_panel`. They are **not** in `PANEL_LANES` or
   `QUORUM_LANES`. They never produce a quorum label, never count toward Voice
   Album admission, and never enter a training corpus. The existing
   `game_peer` lane is not reused because it is counted in the panel quorum.
4. **Blind listening.** The rater sees no name, no location, no take number, no
   transcript, no machine output and no other rating. Raters never get their own
   clips or clips from their own location.
5. **The live loop is untouched.** The notice appears before recording and
   blocks nothing after it. Processing, Ideal Text and Feedback do not wait for
   ratings, and ratings never change them.
6. **Consent comes first.** No recording or rating in the mode before the user
   has accepted the mode's consent (versioned, stored, withdrawable).
   Withdrawing removes all of that user's clips from the queue immediately.
7. **One construct, one question (CONSTRUCT).** The confidence question uses the
   existing `conf-q-v2` wording and five answers. Nothing new is measured without
   a §17 entry.

## 4. Roles

| Role | Records | Rates | Sees results |
|---|---|---|---|
| `member` (employee) | yes | yes (other locations only) | own qualitative notes, on request, delivered offline |
| `panel` (outside listener) | no | yes (all locations) | nothing |
| admin / founder | no | no | admin export only |

## 5. User stories and acceptance criteria

### US-1 Admin enables the mode
*As an admin, I turn Sales Training Mode on for chosen users and assign each one
a cohort, a location and a role.*

- AC-1.1 Given the global flag `SALES_TRAINING_MODE` is `off`, no user sees
  anything from this spec, even if enrolled.
- AC-1.2 Given the flag is `on` and a user is not enrolled, their app is
  unchanged.
- AC-1.3 An enrollment records `cohort_id`, `location_id`, `role`,
  `share_pattern` and `enabled`. Disabling it hides the mode and stops new
  shared takes; clips already in the queue stay unless consent is withdrawn.

### US-2 Member joins
*As an employee, I open the app and understand what the mode is and what will
be shared before I record anything.*

- AC-2.1 On first sign-in after enrollment the member sees the **Welcome** screen,
  then **Consent**. Lab recording in the sales project is blocked until consent is
  accepted.
- AC-2.2 Consent states in plain words: some takes will be shared; I will be told
  before each one; takes without a notice are never shared; my name is hidden;
  I will listen to colleagues from other locations; I can withdraw any time.
- AC-2.3 Acceptance stores `consent_version`, a hash of the text and a
  timestamp. Declining leaves the account usable without the mode.
- AC-2.4 After consent the sales pack project is in the member's project list,
  already set up (four slides), with no upload needed.

### US-3 Member records a private take
- AC-3.1 On a take whose pattern slot is private, the pre-record screen is
  exactly the normal one. There is no notice and no "private" label.
- AC-3.2 The take gets `visibility = 'private'`, which is final. It never
  enters the queue.

### US-4 Member records a shared take
*As an employee, before a shared take I am told it will be heard by colleagues.*

- AC-4.1 On a shared slot, the pre-record screen shows the **Shared-take notice**
  before the record button is enabled. `announced_at` is stored when the notice
  is shown.
- AC-4.2 The notice has two actions: **Record shared take** and
  **Keep this one private**. The second sets `visibility = 'private'` and
  `share_declined_at`, and the take is recorded normally.
- AC-4.3 While recording, a small persistent tag reads "Shared take". Nothing
  else about recording changes.
- AC-4.4 The visibility is fixed once recording starts. Retakes and re-uploads
  of the same take inherit it.
- AC-4.5 After processing, the normal Feedback and Ideal Text appear with no
  extra waiting. One quiet line confirms that the take goes to blind listening.
- AC-4.6 Server check: a shared take whose `announced_at` is missing or later
  than the recording start is stored as private and logged as an error.

### US-5 Take pacing and progress
- AC-5.1 The Lab shows "Take N of 8" for the sales project. This is a count of
  the member's own practice, not a score.
- AC-5.2 After a take, the next one unlocks the next calendar day, and the screen
  says so ("Your next take opens tomorrow"). Default is D4.
- AC-5.3 After take 8 the project stays usable as normal practice. Further
  takes are private and not part of the study.

### US-6 Member or panel listener rates clips
*As a listener, I hear short anonymous clips and answer one question each.*

- AC-6.1 A **Listen** entry appears in the menu for `member` and `panel`
  roles only.
- AC-6.2 One clip is one slide segment of a shared take. The queue never contains
  the rater's own clips or (for members) clips from the rater's location, and it
  is shuffled across people and takes.
- AC-6.3 The screen shows only a player, the question
  "Does the speaker sound confident here?" and five answers:
  Yes · In-between · No · Not sure · Audio unclear.
- AC-6.4 The rater cannot skip ahead without answering or choosing
  "Audio unclear". An answer cannot be changed once the next clip loads.
- AC-6.5 The only progress shown is "12 of 70 listened". No results, averages or
  labels from other raters appear anywhere.
- AC-6.6 Assignment aims for at least 3 ratings per clip across raters and
  stops giving a clip once it has 5.
- AC-6.7 Each answer is stored with `lane` (`sales_peer` or `sales_panel`),
  `question_id`, `rater_id`, `clip_id`, `latency_ms` and `created_at`.

### US-7 Member withdraws
- AC-7.1 Settings has **Leave sales training**. Confirming it stops sharing,
  removes all of the member's clips from the queue within one minute, and keeps
  their private practice.
- AC-7.2 Ratings the member already gave stay, unless they also ask for deletion.

### US-8 Admin exports results
- AC-8.1 An admin-only export returns one CSV row per rating: pseudonymous rater,
  rater role and location, clip owner, owner location, take index, slide,
  visibility, answer, timestamps.
- AC-8.2 A second CSV returns acoustic metrics and the transcript per clip
  (from existing snippet data), for private and shared takes of consented
  members.
- AC-8.3 No export or result is reachable from any member or panel screen.

## 6. Screens (DRAFT copy — needs founder sign-off)

**Welcome**
> **Sales training**
> Practice one short customer conversation eight times over two weeks. Some of
> your takes will be heard by colleagues from other salons, without your name.
> You'll always be told before a take is shared.
> [Continue]

**Consent**
> Before you start
> - Your takes are recorded and analyzed to help you practice.
> - Some takes will be shared with colleagues for blind listening. You'll see a
>   notice before each one. Takes without a notice are never shared.
> - Your name and location are never shown to listeners.
> - You'll also listen to colleagues from other locations.
> - You can leave at any time in Settings.
> [I agree] [Not now]

**Shared-take notice** (pre-record, shared slots only)
> **This take will be shared**
> Colleagues from other salons will listen to it without your name.
> [Record shared take]  [Keep this one private]

**Recording tag:** `Shared take`

**After a shared take:** `This take goes to blind listening.`

**Pacing:** `Take 3 of 8 · Your next take opens tomorrow`

**Listen**
> Clip 12 of 70
> ▶ (player)
> Does the speaker sound confident here?
> [Yes] [In-between] [No] [Not sure] [Audio unclear]

## 7. User flow

```
Admin enrolls user ─► Welcome ─► Consent ─┬─ Not now ─► normal app, mode inactive
                                          └─ I agree
                                                │
              ┌─────────────────────────────────┴───────────────┐
              ▼                                                 ▼
      Lab: sales pack, Take N of 8                    Listen (menu)
              │                                                 │
     slot = share_pattern[N]                          clip ─► answer ─► next
       ├─ private ─► normal pre-record                          │
       └─ shared  ─► Shared-take notice                  "12 of 70 listened"
                       ├─ Keep private ─► private take
                       └─ Record shared ─► take (tag "Shared take")
              │
      normal processing ─► Feedback + Ideal Text (unchanged)
              │
      shared? ─► clips ─► listening queue (other locations, shuffled)
              │
      next take opens tomorrow
```

## 8. Out of scope

- Any score, ranking, leaderboard or result screen for members.
- The "Would you buy" question until D3 is settled.
- CRM or sales-data integration. Sales numbers stay offline with the client.
- Changes to Manager arbitration, Ideal Text, the V3 feedback policy, or the
  coach queue.

## 9. Implementation prompt

> Copy everything in this section into a new session opened on both repos
> (`backend-cursor`, `frontend-cursor`).

```text
Implement "Sales Training Mode" exactly as specified in
backend-cursor/docs/SPEC-sales-training-mode.md. Read the whole spec first, plus
both CLAUDE.md files, docs/CANONICAL_PRODUCT_CONTRACT.md and SPEC.md §17. Run
the WILLAB DECISION FILTER and emit the verdict before writing code.

Hard rules (reject your own change if any fails):
- An unannounced take is never shared. Enforce it server-side, not only in the UI.
- No rating, count, rank or percentage reaches a member or panel screen (AC-9).
- New lanes `sales_peer` and `sales_panel` are NOT added to PANEL_LANES
  (services/state_ratings.py) or QUORUM_LANES (services/label_quorum.py). Add a
  test that fails if they are. Do not reuse `game_peer`.
- The record → process → Ideal Text → Feedback loop is untouched. No new
  awaits or gates after recording starts.
- All copy is taken verbatim from spec §6 and marked DRAFT behind the flag.
- The only question is conf-q-v2. Do not add "would you buy".

Backend (Flask, Postgres; follow docs/MIGRATIONS.md — idempotent, IF NOT EXISTS,
add to migrations/manifest.txt only when the web, worker and cron services
already have SALES_TRAINING_MODE set, per the CONFIG-FIRST rule):

  -- migrations/add_sales_training_mode.sql
  CREATE TABLE IF NOT EXISTS sales_training_cohorts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    project_template_ref TEXT NOT NULL,           -- the 4-slide sales pack
    share_pattern TEXT NOT NULL DEFAULT 'even',   -- 'even' | 'odd_except_first'
    takes_target SMALLINT NOT NULL DEFAULT 8,
    min_hours_between_takes SMALLINT NOT NULL DEFAULT 0,  -- D4 uses calendar day
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
  );
  CREATE TABLE IF NOT EXISTS sales_training_members (
    user_id UUID PRIMARY KEY,
    cohort_id UUID NOT NULL REFERENCES sales_training_cohorts(id),
    location_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('member','panel')),
    enabled BOOLEAN NOT NULL DEFAULT true,
    consent_version TEXT, consent_text_sha256 TEXT, consented_at TIMESTAMPTZ,
    withdrawn_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
  );
  CREATE TABLE IF NOT EXISTS sales_training_take_visibility (
    take_session_id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    take_index SMALLINT NOT NULL,
    visibility TEXT NOT NULL CHECK (visibility IN ('private','shared')),
    announced_at TIMESTAMPTZ,
    share_declined_at TIMESTAMPTZ,
    recording_started_at TIMESTAMPTZ,
    copy_version TEXT,
    CHECK (visibility = 'private'
           OR (announced_at IS NOT NULL
               AND recording_started_at IS NOT NULL
               AND announced_at < recording_started_at))
  );
  -- ratings: reuse confidence_labels with lane IN ('sales_peer','sales_panel');
  -- extend ck_confidence_labels_lane accordingly.
  -- queue bookkeeping: sales_training_assignments(clip_id, rater_id, assigned_at,
  --   answered_at) with UNIQUE(clip_id, rater_id).

  Routes (routes/v2/sales_training.py, all @require_auth, 404 when flag off or
  not enrolled):
    GET  /v2/sales-training/me              -> {role, cohort, take_count, next_take_opens_at, consent_required}
    POST /v2/sales-training/consent         -> {consent_version, text_sha256}
    POST /v2/sales-training/withdraw
    POST /v2/sales-training/takes/next      -> decides slot BEFORE recording:
                                               {take_index, visibility, notice_required}
    POST /v2/sales-training/takes/<sid>/announce      -> sets announced_at
    POST /v2/sales-training/takes/<sid>/keep-private  -> visibility='private'
    GET  /v2/sales-training/listen/next     -> {clip_id, audio_url, question_id, progress:{done,total}}
    PUT  /v2/sales-training/listen/<clip_id>  body {value, unrateable}
  Admin (require_admin):
    POST /v2/admin/sales-training/members   (bulk upsert)
    GET  /v2/admin/sales-training/export/ratings.csv
    GET  /v2/admin/sales-training/export/clips.csv

  Share gate: when a take finishes processing, enqueue its slide clips only if
  the visibility row satisfies the CHECK above AND the member has consented and
  not withdrawn. Otherwise log `sales_training.share_refused` and enqueue
  nothing.

  Rating queue: exclude rater's own clips; exclude rater's location for role
  'member'; shuffle; hide take_index; prefer clips with < 3 ratings; cap at 5.
  The response must not contain the owner id, location, take index, transcript,
  machine value or other ratings.

  Share-gate hook: call sales_training.share_gate from services/analysis_worker.py
  AFTER the take's normal processing has committed, in a try/except that logs
  and never raises (a gate failure must not affect the take).

Frontend (Next.js App Router; BFF proxies under src/app/api/v2/sales-training/*
and src/app/api/v2/admin/sales-training/*):
  - src/app/admin/users/page.tsx: add a "Sales training" column per user
    (location select, role select member|panel, on/off toggle) -> members API.
  - NEW src/app/sales-training/page.tsx: Welcome + Consent (spec §6), shown once
    after enrollment; redirect here from the Lab while consent_required.
  - src/components/willab/RecordingSetup.tsx: for the sales project, call
    takes/next before enabling Record; if notice_required, render the
    Shared-take notice, call announce when it is shown, wire
    "Keep this one private". Private slots render the unchanged screen.
  - Recording screen: small "Shared take" tag for shared takes only.
  - "Take N of 8 · Your next take opens tomorrow" line; Record disabled until then.
  - NEW src/app/sales-training/listen/page.tsx: player, conf-q-v2 text, five
    buttons, "N of M listened". No other data.
  - src/components/AppMenu.tsx: "Listen" entry for member/panel roles only.
  - src/app/panel/data (settings/data page): "Leave sales training" with an
    in-page confirm (no window.confirm).

Tests (must pass; backend via scripts/local_ci.sh):
  - unannounced shared take is never enqueued (unit + route)
  - announced_at after recording start => stored private + logged
  - own clips and own-location clips never returned to a member rater
  - listen/next payload has none of the forbidden fields
  - sales lanes absent from PANEL_LANES and QUORUM_LANES
  - withdraw removes queued clips
  - flag off => all routes 404 and the FE shows nothing
  - live-loop regression: processing time and Feedback payload unchanged for a
    sales take vs a normal take

Deliver as two PRs (backend first, frontend second), each with the FILTER stamp
line in the description. Do not merge; the founder signs off copy and D1–D6.
```
