# Willab — user stories and acceptance criteria

Status: **draft for founder review**, written 2026-09-20 against the code on
`main` in `backend-cursor` and `frontend-cursor`.

This document enumerates **every action the product exposes**, as user stories
with acceptance criteria, from the three perspectives that exist in the code:

| Perspective | Product name used here | How the code identifies it |
|---|---|---|
| End user | **Speaker** | `@require_auth` (Supabase JWT); some pre-signup actions run as a guest principal |
| Coach | **Coach** | `@require_coach` / `@require_admin_or_coach` — an allowlist row in `coach_users` (`routes/admin.py`) |
| Master coach / admin | **Master Coach** | `@require_admin` — an allowlist row in `admin_users` (`routes/admin.py`); a strict superset of Coach |

> **The role model is an allowlist, not a JWT claim.** `is_coach` and
> `is_admin` both key on the *token email* against a service-role table read.
> A frontend `is_coach` flag is never the gate. Every acceptance criterion in
> Parts B and C therefore has an implicit negative twin: *a caller who is
> neither gets `403 FORBIDDEN` and no payload.* That twin is stated once, as
> **G-7**, rather than repeated 90 times.

## How to read this

- **Source of truth.** Where a criterion restates product law, it cites the
  clause in [`CANONICAL_PRODUCT_CONTRACT.md`](CANONICAL_PRODUCT_CONTRACT.md)
  as `§n`. **The contract wins on every conflict, including with this file.**
  Where a criterion describes current implementation *below* the contract's
  altitude, it cites the route or component instead.
- **Tier tags** are the WILLAB DECISION FILTER tiers from `CLAUDE.md`, so a
  reader can tell critical path from scaffolding at a glance:
  `[F1-CORE]` · `[F1-SURFACE]` · `[F1-SUPPORT]` · `[F2]` · `[SCAFFOLDING]`.
  **A tag is a description of where the story sits, never a licence to work
  on it.** Scaffolding stories are documented so the surface is complete;
  documenting one does not schedule it.
- **Open questions** are marked `⚠ FOUNDER DECISION NEEDED` inline rather than
  resolved by guesswork. Nine of them are collected in §D.11.
- **User-facing copy in this document is illustrative, not approved.** Under
  the LIVE LOOP fence all surfaced copy needs founder sign-off. Strings shown
  in `quotes` are either already fixed by the contract (§29, §35i, §24f) or
  marked `⟨copy TBD⟩`.

Story IDs are stable: `US-S-*` Speaker, `US-C-*` Coach, `US-M-*` Master Coach,
`US-X-*` cross-role invariants. Appendix A maps every route in both repos to
the story that covers it, so "each and every action" is checkable rather than
asserted.

---

## §0 — Global acceptance criteria

**These apply to every story in this document.** A story is not done if any
of them fails, and no story may quietly opt out of one. They are the four
fences plus the three locked choices, written in testable form.

**G-1 — No scores, verdicts, or numbers to the Speaker (AC-9, §24i).**
Given any Speaker-facing surface, when it renders, then it shows no score,
percentage, ratio, band name, rank, probability, classifier output, count of
findings, or comparison to other users. Coverage percentages, delivery bands,
PPV estimates, priority values and block counts are internal arbitration
inputs only. `"Let's practice"` carries no number, no band name and no
"below average" phrasing — it is an invitation to act, never a verdict.
*Test:* `noStarsOnUserSurfaces.test.ts` (source scan, not a render test —
the star lane died as six separate renderers, so the invariant must hold of
the code, not of one mounted surface).

**G-2 — Every measured state has one written operational definition
(CONSTRUCT).** Given a state the product measures, when it is surfaced, then
it traces to a written operational definition in SPEC §1.4/§17 and asks
exactly one thing. Confident Voice asks *one* qualitative question about how
assured the delivery sounds. A state with no written definition cannot ship.
Charisma/stress/threat/challenge vocabulary is retired (2026-08-13, 2026-08-29)
and must not reappear in any surface, field, or prompt.
*Test:* `_CONSTRUCT_RE` + CI probe on the master document.

**G-3 — Coach labels are blind (BLIND COACH, §34, §35f).** Given a rater who
has not yet submitted an immutable judgment on a clip, when the rating surface
renders, then it shows no user label, no machine prediction, no other rater's
rating, no need evidence, no exercise candidate, and no detector verdict.
After submission, those are revealed for comparison. The shadow model never
surfaces its guess as a badge anywhere.
*Test:* `blindLabelingIsBlind.test.ts` — `services/state_ratings.py` stamps
`saw_model_output: false` on every row it writes, which *asserts* the
invariant; a corpus cannot be un-poisoned afterwards, because an anchored
label is indistinguishable from a blind one.

**G-4 — The live loop never waits (LIVE LOOP, §23, §24h, §39, §43).** Given
any failure in feedback, coach review, exercise assignment, learning, billing
lookup, or notification, when the Speaker's next action is record → process →
Ideal Text → next Take, then that loop still runs. Coach review is
asynchronous and never gates immediate feedback or the next Take. A V3
feedback failure shows a short notice with a retry control and never blocks
recording, transcription, Ideal Text, or the next Take.

**G-5 — Ideal Text is the one canonical document (L1, §7–§9).** Given any
later Take, machine proposal, coach action, or best-of assembly, when it
produces output, then Ideal Text is not rebuilt or silently changed. It
changes only through direct user editing, an explicitly accepted proposal, or
a prior **Keep evolving** choice for that Paragraph. Best Presentation as a
separate product artifact is retired.

**G-6 — Only Manager-approved candidates surface (L2, §22, §25, §26).** Given
a detector output, when it would reach the Speaker, then it has passed Manager
arbitration under the *active versioned policy*, is within that policy's
budget, and was frozen before exposure. Responding to one item never causes a
previously hidden replacement to appear. V3 never silently substitutes V2
(§24h). No lane is ever filled by invention: an honest
`no_defensible_candidate` lane shows no card.

**G-7 — Authorization is enforced server-side, per role (L3 adjacent).** Given
a caller without the required allowlist row, when they call any Coach or
Master Coach endpoint — including by guessing the URL — then the backend
returns `403 FORBIDDEN` with no payload. Frontend role gates exist for the
person who guesses a URL, never for security. Given a Speaker calling any
owner-scoped route for a resource they do not own, then the response is 403/404
and never another user's data. Guest-capable routes use `@optional_auth`: a
**signed Guest ID** carries the same authority as an authenticated owner, and a
**bare session UUID is never authorization** (see US-X-010 AC4).

**G-8 — Provenance stays separate (L3, §31, §35g).** Given machine prediction,
owner routing, blind peer rating, coach judgment, detector verdict, exercise
outcome, and professional authoring, when any is stored, then each keeps its
own provenance type and none is stored under a shared semantic label. Signals
are never transferred between recordings: Voice Album admission requires
Machine Yes + User Yes + Coach Yes **on the exact same recording**.

**G-9 — Owner-visible identity never leaks to a Coach (§B.4 coach contract).**
Given any Coach-facing payload, when it renders, then the Speaker appears as a
stable salted pseudonym (`Playful Octopus`) plus domain — never a `user_id`,
real name, or email. Same user → same handle across queue and overlay, with
no stored map.

**G-10 — Every state-changing action is auditable (§16, §35j).** Given an
edit, lock, unlock, keep-evolving choice, root-phrase choice, feedback
response, coach judgment, or publication, when it succeeds, then an immutable
record is appended with timestamp and provenance. Surfaced feedback sets write
an exposure ledger containing the complete candidate set, evidence, internal
scores, selected candidate, model and prompt version, and user action.

**G-11 — Phase-1 processing authority is one boundary.** Given
`PLF1_PROCESSING_AUTHORIZATION_MODE=enforce`, when any recording, retry,
provider call, or policy-version acceptance happens, then it passes the
canonical authorization/snapshot/permit path. No route-local consent logic, no
direct provider clients. Phase-2 corpus, dataset, training, evaluation,
promotion and exercise-adequacy paths stay disabled until separately
authorized (`routes/phase2_guard.py`).

**G-12 — Accessibility and resilience baseline.** Given any surface, when it
renders, then colour is never the sole differentiator (§24g), the exercise
pulse honours `prefers-reduced-motion`, every interactive control is
keyboard-reachable and labelled, and a failed network call leaves the previous
state intact rather than a blank screen.

---

# Part A — The Speaker

The person rehearsing a talk. Everything in **F1** is theirs: voice → durable
Recording Attempt → per-slide transcript → project-specific Ideal Text →
evidence-backed Manager Feedback, Take after Take, never waiting for a coach.

## A1 — Account, access and consent

### US-S-001 — Sign up `[F1-SURFACE]`
**As a** Speaker, **I want** to create an account with email and password,
**so that** my Projects, Ideal Text and Takes are durable and mine.

- **AC1** Given valid email and password, when I submit sign-up, then an
  account is created via Supabase (`POST /signup`, aliased `POST /v2/auth/signup`)
  and I land signed in, without re-entering anything I already gave.
- **AC2** Given an email already registered, then I get a clear, non-enumerating
  message and a route to sign in or reset — never a stack trace or a raw
  Supabase error.
- **AC3** Given I created work as a guest before signing up (US-S-004), when
  sign-up completes, then that work is claimed to my account atomically
  (US-S-005) and nothing is orphaned.
- **AC4** Given sign-up succeeds, then the free token grant is applied **once
  per user** and does not renew (§48).
- **AC5** Weak/malformed input is rejected server-side, not only in the browser.

### US-S-002 — Sign in, sign out, recover access `[F1-SURFACE]`
**As a** Speaker, **I want** to sign in, sign out, reset a forgotten password
and change my password, **so that** I can always get back to my work.

- **AC1** `POST /login` with correct credentials returns a session; the app
  routes me to where I left off (`GET /v2/user/sessions/current`), not to a
  generic home.
- **AC2** `POST /reset-password` always responds the same way whether or not
  the address exists (no account enumeration); a reset email is sent only for
  a real account.
- **AC3** From `/update-password` and `/change-password` I can set a new
  password while signed in; the old session is invalidated per Supabase policy.
- **AC4** Sign-out (`/api/auth/logout`) clears the session cookie and lands me
  on `/logged-out`; pressing Back does not restore an authenticated view.
- **AC5** OAuth completion (`/auth/callback`, `/auth/oauth-complete`) ends in
  the same signed-in state as password login, with the same routing.
- **AC6** Given a `redirectTo` on a gated route, when I sign in, then I arrive
  at the route I originally asked for.

### US-S-003 — Give, see and withdraw consent `[F1-SURFACE]`
**As a** Speaker, **I want** to be asked clearly for each permission and to
change my mind later, **so that** I control what happens with my voice.

- **AC1** Four prompted moments are tracked independently
  (`GET/PUT /v2/user/consent`, `/v2/user/sharing-consent`): microphone access,
  voice-sharing, email notifications, and Terms acceptance.
- **AC2** A flag that is `null` means *never asked* — the app may prompt. A
  flag that is `true`/`false` means answered, with `*_set_at` stamped at the
  moment of the answer. `has_answered` stays false until at least one is
  non-null.
- **AC3** Terms acceptance writes an **append-only** ledger row at
  `CURRENT_TERMS_VERSION`. `terms_consent: false` is rejected — the ledger is
  never updated or un-accepted; a re-accept inserts a new row.
- **AC4** Setting mic/share/email back to `null` is a valid *clear*, and the
  app may prompt again.
- **AC5** A `PUT` with no recognised field is `400 INVALID_INPUT`, not a
  silent no-op.
- **AC6** Declining voice-sharing never blocks F1: I can still record,
  process, get Ideal Text and get Feedback (G-4).
- **AC7** Founder-programme consent (`/v2/user/mlc2-consent`) is read, granted
  and withdrawn explicitly, with `DELETE` as a real withdrawal — not a flag
  flip that keeps processing.

### US-S-004 — Start before signing up (guest) `[F1-SURFACE]`
**As a** first-time visitor, **I want** to record a Take before creating an
account, **so that** I can see the product work before committing.

- **AC1** `POST /v2/projects` creates an immutable Project bound to a guest
  principal; identity never derives from display name, topic, deck hash or
  recency (contract, provenance walls).
- **AC2** As a guest I can complete setup, record, process, and see my Ideal
  Text and Feedback.
- **AC3** A guest Take is strictly scoped to its guest principal — no guest can
  read another principal's Project (G-7).
- **AC4** The send-to-coach gate is the point where sign-up is required
  (`sendgate_unsigned`, `useWillabFlow.ts`), and the prompt explains why.
- **AC5** Leaving and returning within the same browser restores the guest
  Project rather than starting a new one.

### US-S-005 — Claim guest work after signing up `[F1-SURFACE]`
**As a** new Speaker, **I want** work I did as a guest to become mine on
sign-up, **so that** I never re-record to get an account.

- **AC1** `POST /v2/projects/claim` binds the **complete** guest-owned graph —
  Project, Recording Attempts, Takes, Ideal Text, feedback, anchors — to my
  authenticated user id, atomically.
- **AC2** A partial failure leaves the guest graph intact and claimable again;
  it never half-migrates.
- **AC3** Claiming is idempotent: a repeat call with the same guest principal
  succeeds without duplicating anything.
- **AC4** A guest graph already claimed by another account cannot be re-claimed
  (403), and the response does not reveal the other account.
- **AC5** Lounge messages created as a guest merge into the signed-in thread
  exactly once (`POST /v2/user/lounge/messages` idempotent batch append).

### US-S-006 — Maintain my profile `[SCAFFOLDING]`
**As a** Speaker, **I want** to set my intake profile and preferences,
**so that** the product knows my context.

- **AC1** `GET/POST /v2/user/profile` reads and writes the intake profile; it
  is explicitly non-recording data.
- **AC2** `GET/PATCH /v2/metric-questions` lets me set my three custom metric
  questions; a partial patch updates only the fields sent.
- **AC3** Profile fields never participate in Project identity (contract,
  provenance walls).
- **AC4** No profile field is required to record. A blank profile never blocks
  F1 (G-4).

---

## A2 — Project setup and slide structure

### US-S-010 — Create a Project `[F1-SURFACE]`
**As a** Speaker, **I want** each talk to be its own container, **so that**
Takes, Ideal Text and feedback for one talk never mix with another's.

- **AC1** One Project ID equals one Arc ID (§1.1). "Arc" is internal/legacy
  and never shown to me as a second entity.
- **AC2** Project isolation uses immutable Project ID **plus authenticated
  owner ID** (§1.2). Two Projects may share a display name without colliding.
- **AC3** A Project owns its setup, one slide structure, its Takes, its Ideal
  Text, its feedback, its anchors and its journey state (§1.3).
- **AC4** Renaming a Project never changes its identity or re-routes its Takes.

### US-S-011 — Attach a slide structure `[F1-CORE]`
**As a** Speaker, **I want** to upload my deck or rehearse without one,
**so that** my speech is segmented against the slides I will actually present.

- **AC1** A slide structure is **either** an uploaded PDF **or** a
  project-specific deckless structure (§1.4). There is no third kind.
- **AC2** `POST /v2/lab/presentation/extract` accepts the deck, extracts its
  slides, and returns the ordered slide structure; uploads over
  `_PRESENTATION_MAX_MB` (20 MB) are rejected with a clear reason, and the
  frontend mirrors the same guard so I learn before the upload.
- **AC3** The structure may be **replaced before the first completed Take** and
  is **immutable afterwards**. A changed deck starts a new Project (§1.4), and
  the app says so before I lose the link, not after.
- **AC4** Slide order from the PDF is preserved exactly; no slide is dropped,
  merged or reordered.
- **AC5** A failed extraction leaves the Project usable — I can retry or
  continue deckless (G-4).

### US-S-012 — Attach a context document `[F1-SUPPORT]`
**As a** Speaker, **I want** to attach supplementary material, **so that**
generated Ideal Text knows what I actually mean.

- **AC1** `GET /v2/explore/arc/<id>/context-document` reports whether one is
  attached; `POST` uploads it.
- **AC2** A context document informs generation only. It never becomes Ideal
  Text, never becomes a Slide, and never counts as a Take (§1.6).
- **AC3** Removing or failing to attach one never blocks recording (G-4).

### US-S-013 — Set up a recording session `[F1-SURFACE]`
**As a** Speaker, **I want** setup to remember what I did last time,
**so that** a second Take costs me one tap, not a form.

- **AC1** `GET /v2/explore/arc/<id>/setup` returns the saved setup so
  continuing a Project **never re-asks** what I already answered.
- **AC2** `GET /v2/user/last-setup` powers *do the same as last time* across
  Projects.
- **AC3** When I record from the dashboard, the app asks first whether this is
  a new topic or another Take of an existing Project
  (`lab_project_pick`, founder 2026-07-22).
- **AC4** Refreshing or reopening mid-setup restores state and never repeats
  setup (§45).
- **AC5** `GET /v2/config/recording` supplies device/limit configuration before
  the mic opens, so I am told about a limit before I hit it.

### US-S-014 — One emotional check-in before Take 1 `[SCAFFOLDING]`
**As a** Speaker, **I want** to be asked once how I am feeling,
**so that** the session starts human without turning into a quiz.

- **AC1** The check-in (`lab_feelings`, `FeelingsCheckIn.tsx`) appears **once**,
  before Take 1. Later Takes do not repeat it (`useWillabFlow.ts`).
- **AC2** Pre-recording uses one supportive, non-manipulative framing and
  records **no experimental condition** (§59). The threat/challenge priming
  experiment is retired.
- **AC3** Skipping the check-in never blocks recording (G-4).
- **AC4** No answer here becomes a training label, a feedback input, or a
  surfaced read (G-8, G-1).

---

## A3 — Recording a Take

### US-S-020 — Record with the microphone `[F1-CORE]`
**As a** Speaker, **I want** to record my talk against my slides,
**so that** every word lands on the slide I said it on.

- **AC1** Recording Mode renders the Slide and, as memory cues, the accepted
  orange roots for that Slide — and nothing else competing for attention
  (§20).
- **AC2** Slide advance during recording is captured with timing, so word→slide
  bucketing at the two-clocks boundary has ground truth to work from.
- **AC3** Stopping the recording submits the audio and moves me to processing
  (`recording_stopped` → `lab_processing`); I never have to press a second
  "submit".
- **AC4** The submitted audio is preserved as a durable **Recording Attempt**
  the moment it arrives (§1.5) — before analysis is attempted, so an analysis
  failure can never lose my speech.
- **AC5** A denied microphone permission produces a specific, recoverable
  message with a route to fix it, not a dead screen.
- **AC6** Losing the network mid-recording does not discard captured audio;
  the attempt is preserved or the failure is explicit.

### US-S-021 — Upload a file instead `[F1-SURFACE]`
**As a** Speaker, **I want** to upload an existing recording,
**so that** a talk I already gave can become a Take.

- **AC1** `POST /v2/lab/recordings` accepts an audio file up to
  `_LAB_MAX_AUDIO_MB` (100 MB) — presentations run minutes, not seconds.
- **AC2** Video-only extensions (`mp4, mov, m4v, avi, mkv, mpeg, mpg, wmv,
  flv, 3gp`) are rejected at upload with a clear reason. `.webm` is
  deliberately **accepted**, because the live mic records `audio/webm`.
- **AC3** A rejected upload (422) returns me to the mic
  (`upload_rejected` → `lab_recording`), not to an error page.
- **AC4** Oversized audio is compressed to 16 kHz mono mp3 before the provider
  call rather than failing, since the provider itself caps at 25 MB.
- **AC5** An upload creates exactly one strictly owned, project-scoped Take
  attempt — never a second Project.

### US-S-022 — Understand what counts as a Take `[F1-CORE]`
**As a** Speaker, **I want** the Take count to mean something,
**so that** my journey progress is honest.

- **AC1** A **Recording Attempt** is the preserved submitted audio. A **Take**
  exists and counts **only after processing succeeds** (§1.5).
- **AC2** Retrying processing reuses the same Recording Attempt and **never**
  increments the Take count (§1.5).
- **AC3** Read sessions, practice sessions, coach training imports and
  processing retries **never become Takes** (§1.6).
- **AC4** The Take number shown to me equals the number of successfully
  processed Takes for that Project — no more, no less.

### US-S-023 — Discard a Take I do not want `[F1-SURFACE]`
**As a** Speaker, **I want** to throw away a bad Take deliberately,
**so that** a false start does not pollute my document.

- **AC1** Discard is an explicit confirmed action (`DiscardTakeDialog.tsx`);
  nothing is discarded by navigating away.
- **AC2** Discarding never mutates Ideal Text, locks, or accepted roots (G-5).
- **AC3** `DELETE /v2/user/sessions/<id>` deletes one recording session by id,
  owner-only, and returns 403/404 for anyone else (G-7).
- **AC4** A discarded Take is removed from the Take count and from the journey
  progress consistently — not from one and not the other.

---

## A4 — Processing, waiting and failure

### US-S-030 — Wait for processing without being trapped `[F1-CORE]`
**As a** Speaker, **I want** to close the tab or lock my phone while my Take
processes, **so that** I am not held hostage by a progress bar.

- **AC1** Processing is **durable when I leave the waiting screen** (§43).
  Closing the tab or locking the phone never kills the pipeline.
- **AC2** Returning later resumes the correct state
  (`ProcessingResumeOverlay.tsx`, `GET /v2/user/sessions/current`) rather than
  restarting or showing an empty Lounge.
- **AC3** While waiting I get honest progress, not a fabricated percentage
  (G-1); waiting-screen content is informational only.
- **AC4** `GET /v2/jobs/<job_id>/status` reports pending / processing /
  terminal states, and a redeploy mid-job re-runs the job via the sweeper
  rather than stranding me in `processing`.

### US-S-031 — Survive a processing failure `[F1-CORE]`
**As a** Speaker, **I want** a failed analysis to cost me a retry and not my
recording, **so that** I never have to give the talk again.

- **AC1** Failure **preserves the Recording Attempt** (§43).
- **AC2** `POST /v2/lab/recordings/<id>/retry-processing` retries against that
  same preserved attempt, and the retry does not increment the Take count
  (§1.5).
- **AC3** A failure never routes me to an unrelated Chat (§43) — the retry
  control is where the failure is.
- **AC4** `POST /v2/lab/recordings/<id>/retry-ideal-text` retries document
  generation alone, without re-transcribing.
- **AC5** Repeated failure gives me a way out that keeps my audio: park the
  Take (`park` → `parked`) and come back.

### US-S-032 — Park a Take `[F1-SURFACE]`
**As a** Speaker, **I want** to hold a Take instead of discarding it,
**so that** I can decide later without losing it.

- **AC1** Park is offered from the readout and both send gates
  (`TRANSITIONS.park`), and is distinct from discard (US-S-023).
- **AC2** A parked Take is restored on my next visit
  (`hasParkedReadout`, `willabParked.ts`) with its readout intact.
- **AC3** Parking never sends anything to a coach and never publishes (G-4).

### US-S-033 — Land on my document automatically `[F1-CORE]`
**As a** Speaker, **I want** the app to open my Ideal Text when it is ready,
**so that** the loop closes without me hunting for it.

- **AC1** When processing **and** initial document/feedback preparation
  succeed, the app automatically opens that Project's Ideal Text (§44).
- **AC2** If document preparation fails but transcription succeeded, I am told
  precisely that, and the retry is document-only (US-S-031 AC4).
- **AC3** The auto-open happens once per Take; refreshing does not re-trigger
  it as a navigation event.

---

## A5 — Ideal Text: the one canonical document

> **Naming note.** §11 makes **Paragraph** the canonical unit for identity,
> editing, protection, feedback attachment and root generation. The routes say
> `parts`, `blocks`, `pieces` and `snippets`; those are API spellings, **not**
> alternative product names. Stories below use *Paragraph* and name the route
> spelling where it matters. See **Q-9** in §D.11 for the one place the word
> *block* is genuinely overloaded.

### US-S-040 — Get my Ideal Text after Take 1 `[F1-CORE]`
**As a** Speaker, **I want** a coherent project-specific document after my
first Take, **so that** I have something to rehearse against.

- **AC1** Take 1 creates the initial project-specific Ideal Text (§8).
- **AC2** The hierarchy is Project → ordered Slides → ordered Paragraphs →
  exact text spans (§10), and the rendered document matches it exactly.
- **AC3** Every Paragraph has a stable identity that survives ordinary wording
  edits (§12); split and merge create new Paragraph IDs and the prior IDs
  remain in history and provenance only.
- **AC4** The document is coherent prose for *my* talk — not a raw transcript,
  not a template.
- **AC5** `GET /v2/explore/arc/<id>/ideal-text` returns the canonical document;
  `/ideal-text/core` returns the strict read-only cold-open document and
  `/ideal-text/enrichment` the optional sections bound to it.

### US-S-041 — Later Takes never overwrite my document `[F1-CORE]`
**As a** Speaker, **I want** Take 4 to leave my document alone unless I say
otherwise, **so that** work I have memorised is not deleted under me.

- **AC1** Later Takes **never** replace Ideal Text with the latest transcript
  or reconstruct it from best fragments (§8). Best Presentation is retired
  (§7).
- **AC2** Later Takes produce evidence, feedback and **proposals** (§9).
- **AC3** Ideal Text changes **only** through (a) my direct edit, (b) a
  proposal I explicitly accept, or (c) a prior **Keep evolving** choice for
  that Paragraph (§9).
- **AC4** No coach action, machine proposal or publication silently changes my
  text (§15, §40).

### US-S-042 — Edit my document in place `[F1-SURFACE]`
**As a** Speaker, **I want** to rewrite my own words directly,
**so that** the document is mine.

- **AC1** `PUT /v2/explore/arc/<id>/ideal-text/user-edit` persists an in-place
  edit of one Paragraph.
- **AC2** An ordinary wording edit **keeps** the Paragraph ID (§12).
- **AC3** Every edit appends an immutable Paragraph revision with timestamp and
  provenance (§16) — nothing is overwritten in place in history.
- **AC4** Editing clears stale root metadata for that Paragraph (§19).
- **AC5** Editing a locked Paragraph is an explicit act: it either requires an
  unlock or is itself recorded as an explicit edit of settled text — it is
  never a silent unlock (§14).
- **AC6** Top-bar/global editing is not a path to changing text
  (`noTopBarEditing.test.ts`); editing happens at the Paragraph.

### US-S-043 — Keep a private notebook copy `[SCAFFOLDING]`
**As a** Speaker, **I want** personal notes that are not the canonical
document, **so that** I can think without editing my script.

- **AC1** `PUT /v2/explore/arc/<id>/ideal-text/notes` saves my personal
  notebook copy.
- **AC2** Notes never become Ideal Text, are never sent to a coach as document
  changes, and never feed Manager arbitration (G-5, G-8).

### US-S-044 — Accept a cross-take proposal, or keep my wording `[F1-CORE]`
**As a** Speaker, **I want** to decide each proposed change myself,
**so that** improvement is something I choose.

- **AC1** `POST /v2/explore/arc/<id>/blocks/<key>/decide` takes
  `action: "accept" | "keep"` plus `take_session_id` as a **race guard**.
- **AC2** **Accept** → the offered wording becomes canonical, the document
  reassembles at once, the version bumps and a snapshot is written.
- **AC3** **Keep** → the offer is remembered on that Paragraph's rejected list
  and is **never re-offered for that Take**.
- **AC4** A stale echo returns `409 STALE_OFFER` rather than applying a
  decision to a document that has moved underneath me.
- **AC5** An offer that is no longer pending returns `409 NOT_PENDING`.
- **AC6** `POST /v2/explore/arc/<id>/prior-take/decide` decides a change that
  came from an **earlier** Take: accept replaces the current wording and
  **bakes forward** as an approved ledger row keyed on the phrase, so it is
  never re-litigated; keep dismisses it permanently.
- **AC7** Accepting requires `proposed_text`; the server never infers what I
  accepted.

### US-S-045 — Mix and match wordings across Takes `[F1-SURFACE]`
**As a** Speaker, **I want** to point a Paragraph at any version I have ever
said, **so that** the best line from Take 2 can live in my Take 5 document.

- **AC1** `GET /v2/explore/arc/<id>/blocks/variants` returns the pool: this
  Take's wording, earlier Takes' wordings, and my own edits.
- **AC2** `POST /v2/explore/arc/<id>/blocks/<key>/select` points the Paragraph
  at any pooled variant.
- **AC3** Selecting is **never destructive** — the displaced text stays in the
  pool.
- **AC4** Each selection records a new revision and the document reassembles at
  once.
- **AC5** Variants are shown as choices, never ranked with a score (G-1).

### US-S-046 — Go back to an earlier version `[F1-SURFACE]`
**As a** Speaker, **I want** to undo my way out of a mess,
**so that** experimenting is safe.

- **AC1** `GET /v2/explore/arc/<id>/ideal-text/revisions` returns the
  composition timeline.
- **AC2** Restoring a revision **repoints**, never deletes: Paragraphs that
  revision recorded write through; Paragraphs added since stay as they are.
- **AC3** A restore lands as a **new revision**, so the restore is itself
  undoable.
- **AC4** Undo restores the complete prior text, root, and decision state
  together (§19) — not the text alone.

### US-S-047 — Save = accept and freeze `[F1-SURFACE]`
**As a** Speaker, **I want** an explicit "this is my script now",
**so that** I can stop deciding and start rehearsing.

- **AC1** `POST /v2/explore/arc/<id>/ideal-text/save` accepts the document's
  current state as my script.
- **AC2** Every **unactioned** offer resolves as *kept-mine* — Save leaves a
  clean document, never hidden pending state.
- **AC3** The saved version is stamped as a save row; take badges hide and the
  re-read control gates on it.
- **AC4** The frozen snapshot rides the existing per-version history lane, so a
  save is restorable like any revision.
- **AC5** Saving with nothing to save returns `409 NOTHING_TO_SAVE` rather than
  writing a no-op revision.

### US-S-048 — Correct my transcript `[F1-CORE]`
**As a** Speaker, **I want** to fix what the transcriber misheard,
**so that** the document and the feedback are built on what I actually said.

- **AC1** `PUT /v2/user/sessions/<id>/transcript-edits` saves my corrected
  transcript text for that Take.
- **AC2** A transcript correction is provenance-typed as *owner correction* and
  never as a machine transcription (G-8).
- **AC3** Correcting the transcript does not silently rewrite Ideal Text (G-5);
  it corrects the evidence.
- **AC4** Corrections survive a processing retry of the same Recording Attempt.

### US-S-049 — See the document's working state `[F1-SURFACE]`
**As a** Speaker, **I want** to see at a glance what is still open,
**so that** I know when I am done.

- **AC1** A Paragraph holding an unsettled judgement renders in a softened
  grey; a settled one renders in ordinary text colour with **no mark at all**
  (§24g-1).
- **AC2** Grey applies at **block level, never at word level** — no sentence
  changes colour midway and no gap appears.
- **AC3** There is **no third "done" state**: clean text *is* the settled
  state, and the document empties as I work rather than accumulating marks.
- **AC4** The only two signals are the grey block and the bookmark. No
  underline, highlight, or badge on the text.
- **AC5** Only the bookmark opens. The text itself is never tappable.

---

## A6 — Feedback (Manager-arbitrated, V3 served since 2026-09-18)

### US-S-050 — Get feedback after every Take `[F1-CORE]`
**As a** Speaker, **I want** evidence-backed feedback immediately after each
Take, **so that** the next Take is better without waiting for a human.

- **AC1** Machine Feedback appears **immediately after processing**; coach
  review is asynchronous and never blocks the next Take (§23).
- **AC2** Under **V3** the Manager surfaces **exactly one relative-best
  Confident Voice item per valid block, on every Take including Take 1**
  (§24b). There is no whole-Take item cap.
- **AC3** The Manager partitions each contiguous Slide run at persisted
  Paragraph boundaries into blocks closest to **75 words** (normally 60–90).
  It never cuts words, fabricates boundaries, reorders chronology, or crosses a
  Slide boundary (§24a). An indivisible short or long Paragraph stays intact
  with a typed partition exception.
- **AC4** The only user-facing families are **Confident Voice**, **Actionable
  Improvement** and **Evidence-backed Praise** (§21). Moment, star,
  intervention, lane, device, candidate, suggestion-kind and model score are
  internal terms and never appear to me.
- **AC5** Every surfaced item references exact Project, Take, Slide, Paragraph
  and evidence span; Confident Voice additionally carries a **playable audio
  interval** (§28).
- **AC6** Weak evidence uses tentative language. Feedback never invents words,
  praise, or certainty (§25).
- **AC7** V3 never silently substitutes V2. On failure the client retries once
  automatically, then shows a short notice with a retry control — and the
  failure never blocks recording, transcription, Ideal Text or the next Take
  (§24h, G-4).

### US-S-051 — Work a Confident Voice item `[F1-CORE]`
**As a** Speaker, **I want** each item to give me a read and something to do,
**so that** no bookmark is a dead end.

- **AC1** Every surfaced Confident Voice item carries **both** its delivery
  read **and** the tap-to-root phrase step that follows it (§24e).
- **AC2** **Emphasis is that step** — not a fourth Feedback family and not a
  budget (§24e).
- **AC3** No bookmark is ever empty, because the judgement and the rooting step
  are always there (§24e).
- **AC4** Confidence under V3 is **relative to the eligible clips inside its
  block** — it is never surfaced as an objective claim that the clip is
  confident (§25).
- **AC5** No band, percentage, rank or count is shown (G-1).

### US-S-052 — Answer the Confident Voice question `[F2]`
**As a** Speaker, **I want** to say whether that clip sounded assured to me,
**so that** my own read is on the record.

- **AC1** The primary responses are exactly `Yes — Confident`, `In-between`,
  and `No — Not confident`, plus secondary `Not sure` and `Audio unclear`
  (§29).
- **AC2** The response is an **immutable self-report** tied to the exact clip
  and Take (§29). It is never editable in place; a change is a new,
  timestamped row.
- **AC3** `No` blocks orange styling and Voice Album admission **for that exact
  clip** and suppresses that exact clip from resurfacing (§30).
- **AC4** `No` does **not** penalise the Paragraph, my voice, or materially
  stronger audio in a future Take (§30).
- **AC5** `Yes` permits later styling consideration but never applies styling
  itself (§30).
- **AC6** My answer is a routing signal, **never blind training ground truth**
  (§30, L3).
- **AC7** Routes: `POST /v2/user/snippets/<id>/confidence-agree` (canonical
  routing) and `/confidence-review` (backward-compatible alias) behave
  identically and write one row, not two.

### US-S-053 — Respond to an Actionable Improvement `[F1-CORE]`
**As a** Speaker, **I want** three honest options on a suggested rewrite,
**so that** I am never forced to take advice I disagree with.

- **AC1** The options are exactly **Apply suggestion**, **Edit myself**, and
  **Keep wording** (§35i).
- **AC2** At most **one** Actionable Improvement per Take — the highest-ranked
  of the Take (§24f). It is capped because, unlike a relative-best read, it
  asserts a finding and can be wrong.
- **AC3** **Apply** changes the wording of the block it sat in, and its
  bookmark **re-anchors** to the rewritten block rather than the superseded
  span (§24f-1). A bookmark that cannot re-anchor is removed rather than left
  pointing at text that no longer exists.
- **AC4** An Improvement overlapping an accepted orange root requires warning
  and confirmation; applying it removes the root styling (§19).
- **AC5** A rewrite is never proposed on a **locked** Paragraph — a lock
  changes which intervention layer may fire, and composition is illegal there
  (§15, `v2_explore_set_part_lock`).
- **AC6** When the Take has no honest Improvement candidate, the note is simply
  **absent** — no card, no placeholder, no invented finding (§25).
- **AC7** `POST /v2/user/takes/<id>/feedback-response` appends one immutable
  owner response; `POST /v2/user/snippets/<id>/suggestion-feedback` records one
  Apply / prefer tap. Shown is not positive and skip is not rejection (§35h).

### US-S-054 — Respond to Praise `[F1-SURFACE]`
**As a** Speaker, **I want** praise that quotes what I actually did,
**so that** it is information and not flattery.

- **AC1** Praise must quote or otherwise identify **real textual evidence**;
  modest praise is valid when it is the best honest candidate (§27).
- **AC2** At most **two** Praise per Take, anchored on the **most and
  second-most Confident Voice items of that Take**, ranked on delivery bands,
  not on fidelity to the Ideal Text (§24f).
- **AC3** *At most* two, not always two: a Take with only one defensible praise
  candidate surfaces one, and inventing a second is forbidden (§24f, §25).
- **AC4** Neither the ranking that selects them nor any position among them is
  ever surfaced (§24i) — the two render **identically** (§24g).
- **AC5** Response options are exactly **Useful**, **Not useful**, **Not sure**
  (§35i). Praise responses **never style text**.
- **AC6** Confident Voice, Improvement and Praise responses use separate
  schemas and remain separate datasets; a user response is not a gold label
  (§35h).

### US-S-055 — Read the bookmark hierarchy correctly `[F1-SURFACE]`
**As a** Speaker, **I want** the marks to mean one thing each,
**so that** I know where to look first.

- **AC1** The exercise item renders **orange and pulsing**; the Take's two most
  Confident Voice items render **green, identically**; every other item renders
  **orange** (§24g).
- **AC2** First and second are never distinguished from one another — a visible
  ordering would be a surfaced ranking (§24g, G-1).
- **AC3** Colour is never the sole differentiator, and the pulse honours
  reduced-motion (§24g, G-12).
- **AC4** Coach updates on a locked deck render as a plain orange mark with no
  pulse, so nothing competes with the exercise for attention (§24g).
- **AC5** On a ten-item Take, at most four items carry an anchored note and the
  rest carry the delivery read and the rooting step alone — which is the
  architecture, not a defect (§24f).

### US-S-056 — Get an exercise only where it matters `[F2]`
**As a** Speaker, **I want** at most one exercise per Take,
**so that** I actually do it.

- **AC1** At most **one** exercise per Take, on the **weakest item below the
  neutral delivery band** (§24f).
- **AC2** Other below-neutral items show `"Let's practice"` **without** an
  exercise — a list of exercises is a list nobody starts (§24f).
- **AC3** `"Let's practice"` carries no number, band name, comparison, or
  "below average" phrasing. It is an invitation to act, never a verdict on me
  (§24i).

### US-S-057 — Trust that the set does not shift under me `[F1-CORE]`
**As a** Speaker, **I want** the feedback set to be fixed once shown,
**so that** answering one item is not a slot machine.

- **AC1** The complete selected set for the active policy version is **frozen
  before exposure** (§26).
- **AC2** Responding to one item never causes a previously hidden replacement
  to appear (§26).
- **AC3** Refresh, retry and reopening show the same set for that Take.
- **AC4** Coverage is a target on **selection**, never a floor on output: a
  Slide with no defensible candidate stays uncovered and records a typed
  reason, and no item is invented, padded or promoted to reach a percentage
  (§24d).

### US-S-058 — Open my feedback later `[F1-SURFACE]`
**As a** Speaker, **I want** to come back to a Take's feedback,
**so that** I can work it over several sittings.

- **AC1** `GET /v2/explore/arc/<id>/feedback` returns the per-Take feedback I
  open from the document.
- **AC2** `GET /v2/user/sessions/<id>/readout` and `GET /v2/user/readouts`
  re-read canonical readouts and scroll back through history.
- **AC3** Re-reading never re-runs arbitration or changes the frozen set
  (§26).
- **AC4** A readout for a Take I do not own returns 403/404 (G-7).

---

## A7 — Locks, protection and rooting phrases

### US-S-060 — Resolve, then commit — two separate actions `[F1-CORE]`
**As a** Speaker, **I want** resolving feedback and committing a Paragraph to
be different decisions, **so that** answering a question does not silently
freeze my text.

- **AC1** Resolving Feedback and committing a Paragraph are **separate user
  actions** (§13).
- **AC2** Only after this Take's Feedback for a Paragraph is resolved does the
  app ask me to choose **Lock for next Take** or **Keep evolving** (§13).
- **AC3** A Paragraph with **undecided** interventions **cannot be locked**,
  and the reverse applies for unlock — auto-disregarding a pending rewrite
  would write a decision I never made into my one document
  (`v2_explore_set_part_lock` R3/R5).
- **AC4** Approve is not lock: promoting one wording over a series of decided
  changes decides no intervention (R2).

### US-S-061 — Lock a Paragraph `[F1-CORE]`
**As a** Speaker, **I want** a hard commit on words I have memorised,
**so that** nothing rewrites them under me.

- **AC1** `PUT /v2/explore/arc/<id>/parts/<id>/lock` with `{locked, text_echo}`.
- **AC2** `text_echo` is **required**: a lock is a claim about specific words,
  so locking against a document that has moved returns `409` rather than
  settling a Paragraph I never read.
- **AC3** A lock is a **hard version commit**: it preserves the exact words
  through later Takes until I explicitly edit or unlock (§14).
- **AC4** A lock changes which **intervention layer** may fire: open takes
  composition (the machine may propose changing the words); locked takes
  accentuation (it may only propose styling words already there).
- **AC5** Protection blocks machine rewrite, restructure, add and cut
  proposals. Vocal feedback may still reference protected text (§15).
- **AC6** A coach may raise a material correction as an **explicit proposal**;
  nobody silently changes protected text (§15).

### US-S-062 — Keep evolving `[F1-CORE]`
**As a** Speaker, **I want** to say "this one can still change",
**so that** the machine knows it has permission.

- **AC1** **Keep evolving** is explicit permission for a later Take's
  Manager-selected working version to replace that Paragraph (§14).
- **AC2** Keep evolving is **not an implicit unlock** of anything else (§14).
- **AC3** The choice appends an immutable Paragraph revision with provenance
  (§16).

### US-S-063 — Choose an orange root phrase `[F1-CORE]`
**As a** Speaker, **I want** to pick the exact words that anchor me,
**so that** I have a memory cue I chose.

- **AC1** **Immediately after a lock**, the app asks whether to make a proposed
  exact phrase orange, choose different exact words from that Paragraph, or
  skip (§18).
- **AC2** Orange styling is **never inferred** from praise or from a confidence
  response (§18).
- **AC3** `PUT /v2/explore/arc/<id>/parts/<id>/root` accepts, replaces, or
  skips the prompt — all three are first-class outcomes.
- **AC4** Editing or unlocking clears stale root metadata (§19).
- **AC5** Undo restores the complete prior text, root and decision state (§19).
- **AC6** Before Take 3, an uncovered Slide has **no generated fallback root**.
  After Take 3, the Manager may propose **at most one** root for an uncovered
  Slide — and I must still explicitly lock and apply it (§20).
- **AC7** Accepted anchors persist across Takes and are **never automatically
  replaced**; first-time Paragraph/Slide coverage precedes replacement
  optimisation, and a replacement candidate must independently deserve
  attention (§47).

### US-S-064 — See my live roots while recording `[F1-SURFACE]`
- **AC1** `GET /v2/explore/arc/<id>/recording-roots` returns the live committed
  roots bound to the current document.
- **AC2** A root is eligible for Recording Mode **only** when its Paragraph is
  locked **and** I explicitly accepted the orange action (§20).
- **AC3** No surface duplicates a root as a separate third text layer (§20).

---

## A8 — Presentation Mode and export

### US-S-070 — Present from my document `[F1-SURFACE]`
**As a** Speaker, **I want** a presentation view,
**so that** I can deliver from the thing I built.

- **AC1** Presentation Mode renders, **in order**: the Slide image, the
  accepted roots, and normal-sized Ideal Text (§20).
- **AC2** Recording Mode renders the same accepted roots as memory cues (§20).
- **AC3** No root is duplicated as a separate third text layer (§20).
- **AC4** Nothing in Presentation Mode shows a score, band, or count (G-1).

### US-S-071 — Export my presentation notes `[F1-SURFACE]`
- **AC1** `ExportFormatDialog` offers exactly `pdf` and `docx`
  (`PresentationExportFormat`).
- **AC2** The export renders the same order as Presentation Mode (§20).
- **AC3** An exhausted token balance never removes access to export (§51).
- **AC4** The exported file contains no internal identifiers, candidate sets,
  scores or provenance fields (G-1, G-8).

---

## A9 — Confidence practice and exercises

### US-S-080 — Practise a passage again `[F2]`
**As a** Speaker, **I want** to re-record one passage,
**so that** I can hear myself do it better.

- **AC1** `POST /v2/user/snippets/<id>/confidence-practice` opens or resumes
  **one optional same-passage practice** for that exact clip.
- **AC2** A practice session may contain **at most three** same-passage
  Recording Attempts (§35d).
- **AC3** Practice attempts are **not** presentation Takes and never mutate
  Ideal Text, locks, or orange roots (§35d, §1.6).
- **AC4** `POST /v2/user/confidence-practice/<id>/attempts` records an attempt;
  `/complete` dismisses or retains it.
- **AC5** Saving a practice attempt **never admits it** to the Voice Album
  directly (§33).
- **AC6** Comparison is **qualitative**. No acoustic score, rank, probability
  or machine verdict is shown (§35e, G-1).
- **AC7** Opening, skipping, timing out, or making no attempt is **not** an
  effectiveness label (§35e).

### US-S-081 — Receive an assigned exercise `[F2]`
**As a** Speaker, **I want** to be given a specific exercise for a specific
clip, **so that** practice is targeted rather than generic.

- **AC1** An exercise may be assigned to an exact clip **only after** I submit
  the five-state Confident Voice response for it (§35a).
- **AC2** `Audio unclear` **blocks matching** for that clip (§35a). The other
  responses remain separate self-reports and never override deterministic
  eligibility.
- **AC3** A **deterministic safety and need-compatibility gate runs before
  ranking**. A model may rank only eligible versions and may never bypass the
  gate (§35b).
- **AC4** The complete in-scope catalogue is frozen with every version marked
  eligible or typed-excluded (§35b).
- **AC5** If none is eligible, the product creates a **post-blind coach
  request** rather than inventing or forcing an exercise (§35b).
- **AC6** Serving selects only the **deterministic top eligible** exercise
  until a primary endpoint, horizon, missing-data treatment and evaluation
  contract are separately approved (§35c).
- **AC7** I am shown **which exact exercise version** was assigned and its
  prior use, so the product does not unknowingly repeat it (§35d).
- **AC8** Any future 80/20 exploration is an exposure policy, not a dataset
  split, and must freeze the pool, probabilities, stable draw, policy version
  and selected version without re-randomising on refresh or retry (§35c).

### US-S-082 — Do an assigned exercise `[F2]`
- **AC1** `POST /v2/user/mlc3/exercise-offers` creates the offer; `GET
  /v2/user/mlc3/exercise-offers/<id>` reads it; `/playback` serves the exact
  exercise bytes **through the authenticated service**, never a public URL.
- **AC2** `POST .../practice-sessions` opens the session; `.../attempts`
  records attempts; `.../events` records offered / opened / skipped as typed
  events, none of which is an effectiveness label (§35e).
- **AC3** `POST /v2/user/mlc3/practice-attempts/<id>/speaker` records **only an
  explicit affirmative** source-voice confirmation; silence is never consent.
- **AC4** `POST .../practice-sessions/<id>/preference` records my qualitative
  preference and returns no score (G-1).
- **AC5** Exercise outcomes **never train Confidence Classification** (§35g).
- **AC6** Every step is behind `@mlc3_service_required`; when the service is
  off the surface is absent, not broken, and F1 is unaffected (G-4).

### US-S-083 — Work a Confident Moment bundle `[F2]`
- **AC1** `GET /v2/explore/arcs/<projectId>/confident-moment-bundles` returns
  only canonical **database-owned** bundles — never a client-assembled one.
- **AC2** `POST /v2/user/confident-moment-bundles/<id>/render` acknowledges a
  **visible** render; a render acknowledgement is evidence of exposure, not of
  agreement (§35h).
- **AC3** `.../attachments/<id>/response` records my response per family with
  that family's own schema (§35h).
- **AC4** `.../root-actions` records a public database-derived root transition,
  gated by the coverage gate.
- **AC5** `.../source-playback` serves the exact source clip only; no other
  recording is reachable through it (G-8).
- **AC6** `.../coach-updates/<revisionId>/render` acknowledges a coach update
  separately from the original bundle render — the two are never one event
  (G-8, §39).

---

## A10 — Voice Album

### US-S-090 — See my Voice Album `[F2]`
**As a** Speaker, **I want** a place that collects the moments where I really
sounded like myself, **so that** progress is something I can hear.

- **AC1** `GET /v2/voice-album` returns my canonical **cross-project** Album;
  `GET /v2/explore/arc/<id>/voice-album` returns one Project's aligned moments.
- **AC2** A clip enters the Album **only** when **Machine Yes + User Yes +
  Coach Yes** independently refer to **that same recording** (§32).
- **AC3** Signals are **never transferred between recordings** (§32, G-8).
- **AC4** A selected practice attempt may enter only through those same three
  signals on **that exact attempt** (§35g).
- **AC5** The Album shows no score, ranking or count (G-1).
- **AC6** `GET /v2/voice-album/moment-history` shows where one Album moment
  came from, with each signal's provenance distinct (G-8).

### US-S-091 — Answer the queue of clips waiting on me `[F2]`
- **AC1** `GET /v2/voice-album/practice-queue` returns clips still waiting for
  my Confident Voice answer.
- **AC2** `POST /v2/voice-album/practice-answer` records my five-state answer
  on one of my own practice clips, immutably (§29).
- **AC3** An empty queue is a normal, calm state — not an error and not a nag.

### US-S-092 — Add my own note to a moment `[F2]`
- **AC1** `POST /v2/voice-album/note` appends my own note to one Album moment.
- **AC2** My note is owner-authored provenance and is never read as a rating,
  a label, or training data (G-8).

### US-S-093 — Be introduced to the Album once `[F2]`
- **AC1** The Voice Album introduction is emitted **once per user**, after the
  first eligible clip **and** Take 3 completion (§34).
- **AC2** It **never repeats for later Projects** (§34).

### US-S-094 — Learn the outcome of coach review, calmly `[F2]`
- **AC1** **User Yes / Coach Yes** admits **silently** (§34).
- **AC2** **User No / Coach Yes** may later become a separate Album
  disagreement exercise and **never** enables project styling (§34).
- **AC3** **User Yes / Coach No** requires coach re-review and may produce a
  calm explanation **after a confirmed No** (§34).
- **AC4** **User No / Coach No** is silent (§34).
- **AC5** Coach review **never changes project styling I already accepted**
  (§34, §38).
- **AC6** Any Album disagreement exercise is a purpose-specific personal flow
  inside Voice Album with its own state and the three-signal provenance rules —
  it is **not** the retired generic Game renamed (§60).

---

## A11 — Asking for, and receiving, coach review

### US-S-100 — Send a Take to a coach `[F2]`
**As a** Speaker, **I want** to ask a human to look at a Take,
**so that** I get judgement a machine cannot give.

- **AC1** `POST /v2/projects/<id>/takes/<id>/send-to-coach` sends **one
  explicit Take**; nothing is sent implicitly by recording.
- **AC2** Sending requires sign-in; an unsigned Speaker meets the send gate and
  is told why (US-S-004 AC4).
- **AC3** After sending, my state is `review_pending`, and it is **server
  truth** — settled from the newest readout, never from a tap
  (`useWillabFlow.ts`, `HomeStatus`).
- **AC4** While review is pending I can still record the next Take, edit, lock
  and export (G-4, §39).
- **AC5** Sending consumes the coach-review allowance exactly once; a failed
  send consumes nothing.

### US-S-101 — Receive coach feedback without being overwritten `[F2]`
- **AC1** Coach review and delivery are **item-level**; items and clips may
  reach me independently (§39).
- **AC2** A Take-level "reviewed" state is an **aggregate summary only** and
  never gates immediate feedback or the next Take (§39).
- **AC3** The coach does **not** own or publish a competing full-document
  version; coach wording changes arrive as **explicit correction proposals**
  with preserved machine lineage and my accept/reject decision (§40).
- **AC4** A material correction becomes a **new accept/reject proposal** if I
  have already seen or acted on the original (§37).
- **AC5** Routine agreement is **silent**; explanation refinement does not
  change my text (§37).
- **AC6** Coach actions never silently change accepted user text (§38).

### US-S-102 — Receive an optional coach video note `[F2]`
- **AC1** A coach may share **only** an optional **Take-level** video note;
  per-item breakthrough videos and per-item Star Verdict videos are **retired**
  (§41).
- **AC2** It is **explicitly shared**, **never autoplays**, and **never gates
  progress** (§41).
- **AC3** It carries **no detector label and no Feedback verdict** (§41, G-1).

### US-S-103 — Receive assigned guidance `[F2]`
- **AC1** `GET /v2/user/mlc3/guidance/<membershipId>` delivers assigned
  guidance; **delivery is separate from authoring, judgement and publication**
  (provenance walls).
- **AC2** `/playback` serves the assigned private guidance with its
  before/after material through the authenticated service only.
- **AC3** `POST /v2/user/mlc3/guidance/<attachmentVersionId>/events` records
  typed exposure events; none is an agreement or an effectiveness label
  (§35h).
- **AC4** Guidance never rewrites my Ideal Text (G-5).

### US-S-104 — Receive an audit `[SCAFFOLDING]`
- **AC1** `GET /v2/user/audits` returns my signed audit deliveries.
- **AC2** An audit is read-only to me and never changes my document (G-5).
- **AC3** `GET /v2/user/recording-progress` reports progress toward the first
  audit **without** a score or percentage read on my speaking (G-1).
  ⚠ **FOUNDER DECISION NEEDED** — a "progress toward audit" count is commerce
  eligibility, not a speaking read, but it is one rename away from looking like
  a score. See **Q-5**.

---

## A12 — Tokens, purchase and balance

### US-S-110 — See what I have `[SCAFFOLDING]`
- **AC1** `GET /v2/tokens/balance` returns balance, tier and coach allowance.
- **AC2** `GET /v2/tokens/history` returns ledger rows newest first, paged
  backwards by `before_id`.
- **AC3** `GET /v2/tokens/arc/<id>` shows what this Project's once-per-Project
  actions cost and which are already paid — before I commit to one.
- **AC4** `GET /v2/tokens/recording-band` tells me the **longest recording my
  balance covers**, before the mic opens (US-S-013 AC5).
- **AC5** Commerce numbers are money, not a read on a speaker — AC-9 governs
  quality reads, not prices (`/admin/tokens` header comment).

### US-S-111 — Buy tokens `[SCAFFOLDING]`
- **AC1** `GET /v2/tokens/prices` returns the price list **with its version**.
- **AC2** `POST /v2/tokens/checkout` opens Stripe Checkout; `POST
  /v2/tokens/portal` opens the billing portal.
- **AC3** Every purchase is a **one-time package** of tokens plus any included
  coach-review credits (§49).
- **AC4** Balances **remain until consumed** and do **not renew** (§49).
- **AC5** There are **no subscriptions, billing periods, renewal dates or
  monthly plans** (§50).
  ⚠ **FOUNDER DECISION NEEDED** — `tokens_checkout` is documented as *"a Stripe
  Checkout Session for a recurring tier"* and `tokens_balance` returns *"when it
  renews"*. That is the retired subscription model still live in code against
  §49/§50. See **Q-1** — this is the sharpest contract/code conflict found.
- **AC6** The free grant occurs **once per user** and does not renew monthly
  (§48).

### US-S-112 — Never lose what I made `[F1-SURFACE]`
- **AC1** An exhausted balance may block **new paid actions** but **never**
  removes access to existing Projects, Ideal Text, Feedback, exports, or Voice
  Album entries (§51).
- **AC2** A billing outage never blocks recording, processing, Ideal Text or
  the next Take (G-4).
- **AC3** A blocked paid action states plainly what is blocked and what it
  costs, without a countdown, a streak, or a scarcity device (G-1, R3).

### US-S-113 — One-off audit purchase and invite codes `[SCAFFOLDING]`
- **AC1** `POST /v2/arc/<id>/checkout` starts Stripe Checkout for one audit =
  one Project.
- **AC2** `POST /v2/arc/<id>/redeem` redeems a founding free-pass invite code
  for that Project; an invalid or spent code fails clearly and consumes
  nothing.
- **AC3** `POST /v2/arc/<id>/unlock-moments` is the single paid item under the
  single deliverable; `POST /v2/arc/<id>/unlock` is **retired** and must not be
  reachable from any surface.
  ⚠ **FOUNDER DECISION NEEDED** — a retired route still registered is exactly
  the ambiguity §55 says needs an individual founder decision before removal.
  See **Q-2**.

---

## A13 — History, deletion and data rights

### US-S-120 — Browse my own history `[F1-SURFACE]`
- **AC1** `GET /v2/user/readouts` lists my Lab session history so I can scroll
  back to previous Takes.
- **AC2** `GET /v2/user/trainings` groups my training material **by Project**.
- **AC3** `GET /v2/recordings` lists my recordings with pagination, owner-only.
- **AC4** `GET /v2/recordings/<id>/playback-url` returns a **fresh signed URL**,
  owner-only, for when a readout's URL has expired — audio is never served from
  a public, guessable location (G-7).

### US-S-121 — Delete my work `[F1-SURFACE]`
- **AC1** `DELETE /v2/user/presentations/<id>` deletes a whole presentation
  (deck) **and all its Takes**, owner-only, and says so before I confirm.
- **AC2** `DELETE /v2/user/sessions/<id>` deletes one recording session by id,
  owner-only.
- **AC3** Deletion is confirmed, irreversible, and described accurately — no
  soft-delete described as deletion.
- **AC4** Deleting one Project never touches another (§1.2).

### US-S-122 — Exercise my data rights `[F1-SURFACE]`
- **AC1** `POST /v2/processing-authorization/data-rights` accepts exactly
  `access`, `export`, `correction`, `restriction`, `objection`; anything else is
  `422`.
- **AC2** An **idempotency key is required**; a repeat with the same key returns
  the same request rather than filing a second one.
- **AC3** `GET /v2/processing-authorization/data-export` prepares my
  authorization evidence; a failure returns `503 DATA_EXPORT_FAILED` and never
  a partial file presented as complete.
- **AC4** `POST /v2/processing-authorization/terminate` accepts exactly
  `service_termination` or `account_deletion`, requires an idempotency key, and
  returns a `purge_id`.
- **AC5** `GET /v2/processing-authorization/deletion/<purgeId>` reports that
  purge's honest status — never "done" before it is.
- **AC6** Cleanup of retired historical rows is a **separately authorized,
  previewed retention operation**, never an automatic migration side effect
  (`CLAUDE.md`, 2026-08-29).

### US-S-123 — Know when I am reading AI-rendered content `[F1-SURFACE]`
- **AC1** `POST /v2/processing-authorization/ai-rendered` requires complete
  rendered-exposure evidence: `ai_notice_version`, `surface`,
  `client_render_id`, `rendered_at`, `client_version`. Anything missing is
  `422` — the claim that a notice was shown is never accepted on trust.
- **AC2** `GET/POST /v2/processing-authorization` reads my authorization status
  and records acceptance of a policy version (`201` on accept).
- **AC3** Under `enforce` mode, every recording, retry and provider call passes
  this boundary (G-11).

### US-S-124 — Unsubscribe from email `[SCAFFOLDING]`
- **AC1** `POST /v2/public/unsubscribe` works from a **token in the email**,
  with no sign-in required.
- **AC2** An invalid or expired token fails without revealing whether the
  address exists.
- **AC3** Unsubscribing never affects my Projects, Takes or Album (§51).

---

## A14 — The Lounge, the journey and product discovery

### US-S-130 — Use the Lounge as home `[SCAFFOLDING]`
- **AC1** The Lounge is the always-mounted hub; review and Lab are **overlays,
  not routes** — so Back never walks me out of the authenticated shell and
  drops me at `/login` (the N1 architecture invariant).
- **AC2** `GET /v2/user/lounge/messages` rehydrates the thread (newest page,
  or pages older); `POST` is an **idempotent batch append**; `DELETE` clears my
  entire thread.
- **AC3** Guest messages merge into my signed-in thread exactly once
  (US-S-005 AC5).
- **AC4** Nothing in the Lounge is engagement machinery: no streak, no
  leaderboard, no nudge count (R3, worked example B).

### US-S-131 — Follow the guided journey `[F1-SURFACE]`
- **AC1** Takes 1–3 follow: Ideal Text → **See next steps** → stage-specific
  Chat bubble → return to the next recording action (§45).
- **AC2** Refresh and reopening **preserve the state** and never repeat setup
  (§45).
- **AC3** **Take 3 completes the guided journey.** Take 4+ is optional
  refinement and immediately offers **Record again** with no further
  See-next-steps loop (§46).
- **AC4** `POST /v2/explore/arc/<id>/journey/next-steps` appends the current
  Take's exact journey step; `GET /v2/explore/arc/<id>/progress` is a cheap
  poll for the "takes to your ideal presentation" read — expressed as remaining
  steps in the journey, never as a quality score (G-1).
- **AC5** Unshown low-priority queues **end after Take 3**, and "no changes
  needed" is a **successful** refinement result (§47).
- **AC6** Recording processing, Take completion, Ideal Text preparation, coach
  delivery, journey progress and Feedback decisions are **independent state
  machines**; a UI status may project them but no universal pending/ready/
  completed state controls them all (§42).

### US-S-132 — Ask a question in chat `[SCAFFOLDING]`
- **AC1** `POST /v2/chat/query` answers within the product's scope;
  `GET /v2/chat/session-state` drives the returning user's UI state.
- **AC2** Chat never surfaces a score, a band or a model verdict (G-1).
- **AC3** Chat is never a required step in the loop; skipping it never blocks
  the next Take (G-4).
- **AC4** A chat failure never strands me — the recording action stays
  reachable (§43).

### US-S-133 — Discover what the product offers `[SCAFFOLDING]`
- **AC1** `GET /v2/user/product-discoveries` returns products introduced by
  **durable, structured** Lounge offers — not ad-hoc bot chatter.
- **AC2** An offer is informational; declining one never degrades F1 (G-4).
- **AC3** `POST /v2/learning-exposures/ack` confirms that one prepared packet
  was actually shown; an acknowledgement is exposure evidence, never consent
  and never agreement (§35h).

### US-S-134 — Install the app `[SCAFFOLDING]`
- **AC1** The install prompt (`WillabInstallPrompt.tsx`) appears at most once
  per decision and is dismissible for good.
- **AC2** Declining installation never changes any F1 capability (G-4).

---

## A15 — Adjacent surfaces the Speaker can reach

> These are **SCAFFOLDING by construction**. They are listed for completeness
> of the action inventory. None may take priority over F1 work, and none may
> breach a fence.

### US-S-140 — Read the Journal `[SCAFFOLDING]`
- **AC1** `/blog` and `/blog/<slug>` render published posts;
  `GET /v2/journal/posts` is the public read.
- **AC2** Unpublished posts are unreachable by URL guess (G-7).
- **AC3** A post attached to a moment as further reading (US-C-063) opens
  read-only and never modifies the moment (G-5).

### US-S-141 — Read legal and marketing pages `[SCAFFOLDING]`
- **AC1** `/`, `/about`, `/privacy`, `/terms` render without authentication.
- **AC2** `/terms` states the version that `CURRENT_TERMS_VERSION` enforces, so
  the acceptance ledger and the page cannot disagree (US-S-003 AC3).

### US-S-142 — Use the Life panel `[SCAFFOLDING]`
- **AC1** `/panel/*` (today, week, timeline, goals, wins, phrases, principles,
  distractions, strategy, data, setup) reads and writes only through
  `/v2/life/*`.
- **AC2** The Life panel shares **no data, no provenance and no surface** with
  F1 feedback, confidence, or the Album (G-8).
- **AC3** `DELETE /v2/life/data` and `POST /v2/life/export` give the owner
  deletion and export of Life data independently of their Willab data.
- **AC4** No Life panel number is ever presented as a read on speaking (G-1).
- **AC5** Every `/v2/life/*` route is gated by `@life_route(...)`, which applies
  authentication and the three-tier gate **in that order**: `require_auth`, then
  feature-enabled (404 if off), then founder allowlist where marked (404 to
  everyone else — not 403, so the surface's existence is not disclosed), then
  consent (`_needs_consent`). `consent=False` is used **only** on the endpoints
  that exist to obtain consent (`/v2/life/state`, `/v2/life/consent`).

### US-S-143 — Reach developer surfaces `[SCAFFOLDING]`
- **AC1** `/dev/*` (corpus, deck, recording, marked-editor, speaking-errors,
  star-verdicts, life-bets) and `/game` are **not linked** from any Speaker
  surface.
- **AC2** Reaching one by URL exposes no other user's data (G-7).
- **AC3** The generic Game, its routes and saved game sessions are **retired**
  and are not renamed into Voice Album (§60).
  ⚠ **FOUNDER DECISION NEEDED** — `/game` still exists as a route against §60.
  See **Q-6**.

---

# Part B — The Coach

An allowlisted human reviewer (`coach_users`). The Coach is an **F2 labeler**,
not the founder (R4): the coach's wishes route to *"does this reduce manual
coach load through the shadow loop?"* before they become work. **Coach review
is asynchronous and never blocks the Speaker's loop** (G-4).

## B1 — Access, identity and the blind boundary

### US-C-001 — Get into the coach surfaces `[F2]`
- **AC1** Coach access is an **allowlist row** in `coach_users` keyed on the
  token email, read with the service role. A Supabase JWT `role` claim is never
  the gate, and a frontend `is_coach` flag is never the gate.
- **AC2** `@require_admin_or_coach` admits an allowlisted coach **or** an
  admin (the superset operator). A caller who is neither gets `403` with no
  payload (G-7).
- **AC3** Deactivating a coach (`is_active = false`) revokes access on the next
  request, with no deploy required.
- **AC4** Frontend coach routes (`/coach/*`) render nothing for a non-coach;
  that gate is for the person who guesses the URL, never for security.

### US-C-002 — See a Speaker as a pseudonym, never as a person `[F2]`
- **AC1** Every coach response carries `pseudonym` + `domain` **only** — never
  `user_id`, real name, or email (§B.4 red-line 6, G-9).
- **AC2** The pseudonym is a friendly adjective+animal drawn from a **salted,
  non-reversible** hash of the user id, stable across queue and overlay, with
  **no stored map**.
- **AC3** A coach can recognise a returning Speaker without ever learning who
  they are.
- **AC4** Wordlists are sized for beta and expand at roughly 10× user count;
  a collision is a product defect, not an acceptable coincidence.

### US-C-003 — Rate blind, then see everything `[F2]`
- **AC1** Before a coach submits an immutable judgment on a clip, the surface
  shows **no** user label, machine prediction, other rater's rating, need
  evidence, exercise candidate or detector verdict (§34, §35f, G-3).
- **AC2** After submission, those are revealed for comparison and training
  analysis (§34).
- **AC3** The original coach judgment is **never editable**; reconsideration is
  a **separately timestamped, provenance-bearing revision** (§34).
- **AC4** `services/state_ratings.py` stamps `saw_model_output: false` on every
  row — which **asserts** the invariant. If a machine read ever returns to the
  labeler card, every row written from it carries a false blindness claim, and
  the corpus cannot be un-poisoned (`blindLabelingIsBlind.test.ts`).
- **AC5** A coach who later authors an exercise may still participate in the
  confidence quorum **when their judgment predates reveal** (§35f).
- **AC6** Coach and peer confidence judgments remain independently blind and
  may be **plural** (§35f).
- **AC7** The language gate (`RaterLanguageGate.tsx`) ensures a rater only
  judges clips in a language they were verified for; a mismatched clip is not
  offered.

---

## B2 — The review queue

### US-C-010 — See what is waiting for me `[F2]`
- **AC1** `GET /v2/coach/queue` returns pseudonymised rows of sessions ready
  to review, newest first.
- **AC2** The queue lives **inline in the Lounge** as interleaved bubbles that
  open an overlay — **not as a route**. `/coach/willab` and
  `/coach/willab/<id>` are retired redirects kept so bookmarks do not 404 (N1).
- **AC3** Opening a review never remounts the shell, so browser-Back never
  walks the coach out to `/login` (the N1 bug).
- **AC4** Per-snippet `coach_state ∈ {pending, in_progress, done}` is the
  single vocabulary the queue and the overlay share.
- **AC5** An empty queue is a calm, explicit state.

### US-C-011 — Open one Take for review `[F2]`
- **AC1** `GET /v2/coach/sessions/<id>` returns the review payload for one
  Take: pseudonymised, split-sink, with per-snippet state.
- **AC2** The payload carries the **original** transcript for review; a
  Speaker's display-layer transcript correction rides beside it as
  `user_edited_text`, **never instead of** `transcript`
  (`v2_user_put_transcript_edit`).
- **AC3** Reviewing item-by-item is supported: items and clips may reach the
  Speaker independently (§39).
- **AC4** Deep-linking `?review=<id>` opens the overlay in the Lounge rather
  than navigating.

---

## B3 — Reviewing and saving a Take

### US-C-020 — Save per-snippet authoring immediately `[F2]`
- **AC1** `POST /v2/coach/sessions/<id>/snippets/<snippetId>` saves one
  snippet's authoring immediately (E1 / §B.3 / S.5) — the coach never loses
  work to a navigation.
- **AC2** A save writes to the coach **draft** store and delivers nothing to
  the Speaker.
- **AC3** A save is per-snippet and never rewrites a neighbouring snippet.

### US-C-021 — Save the whole Take and move on `[F2]`
- **AC1** `POST /v2/coach/sessions/<id>/save-feedback` persists this Take's
  authoring and stamps it **reviewed-and-saved**, so the coach can move to the
  next recording.
- **AC2** Save **delivers nothing to the Speaker** — only the explicit publish
  action does.
- **AC3** The body is save-at-once (`snippets[]` plus an optional
  `overall_message`); there is **no per-keystroke autosave**.
- **AC4** `overall_message` persists as the separate **Take-level** coach
  summary; exact-evidence paragraph feedback stays in the canonical draft
  repository until publish.
- **AC5** Every door writes through the **same shared helper**, so no second
  path can drift from the first.

### US-C-022 — Know what is left before I can publish `[F2]`
- **AC1** `GET /v2/coach/arc/<id>/review-state` answers *"what's left before I
  can publish?"* in **one read**, so the post-last-Take screen needs no
  client-side inference across per-Take calls.
- **AC2** It returns `can_publish` plus typed `blockers ∈ {TAKES_NOT_SAVED,
  IDEAL_TEXT_NOT_APPROVED, NO_TAKES}` and the `pending_session_ids`.
- **AC3** The preconditions it reports are **exactly** the ones
  `publish-analysis` enforces — served as data rather than discovered as a
  409 on a failed POST.

### US-C-023 — Publish a batch atomically `[F2]`
- **AC1** `POST /v2/coach/arc/<id>/publish-analysis` publishes the complete
  saved Take snapshots as **one atomic revision batch**.
- **AC2** A partial failure publishes nothing.
- **AC3** Publication is distinct from drafting, from judgement, and from
  notification (provenance walls); each has its own record.
- **AC4** Published coach wording reaches the Speaker as **correction
  proposals with preserved machine lineage** and a user accept/reject decision
  — never as a silent change to accepted text (§37, §40, G-5).
- **AC5** Routine agreement is **silent**; explanation refinement does not
  change the Speaker's text (§37).

---

## B4 — Confidence labelling (the core training signal)

### US-C-030 — Label one clip's confidence `[F2]`
- **AC1** `PUT /v2/coach/snippets/<id>/confidence-label` takes the five-state
  body: `value ∈ {yes, in_between, no, not_sure, audio_unclear}`, with optional
  `note` and `latency_ms`.
- **AC2** The three meanings stay **separate in storage**: `yes/in_between/no`
  are perceptual judgments, `not_sure` is **rater uncertainty**, and
  `audio_unclear` is a **technical failure**. They are never collapsed.
- **AC3** Re-labelling **replaces this rater's row** (the corpus wants their
  current view); other raters' rows are untouched, so multi-rater agreement
  stays possible.
- **AC4** `audio_unclear` is the **exception**: that artifact must go to a
  different eligible human, and the first rater cannot turn a second listen
  into a falsely independent answer.
- **AC5** **Lane is derived, never sent by the client.** It follows the
  verified rating act, not the clip source: this authenticated, blind,
  language-matched coach route writes `coach` for both rehearsal and
  imported-corpus clips. `bootstrap` is reserved for seeded/historical
  evidence.
- **AC6** The legacy body `{confident: bool, intensity?: 1..5}` is still
  accepted and translated (`true→yes`, `false→no`) so the cutover does not break
  a live surface — but a legacy body **cannot express `in_between`**, which is
  the whole reason the instrument changed.
- **AC7** Nothing about this label is ever surfaced to the Speaker (G-1, G-3).

### US-C-031 — Work the confidence queue for a Take `[F2]`
- **AC1** `GET /v2/coach/sessions/<id>/confidence-queue` returns the pieces
  queued for confidence labelling on one Take, **blind**.
- **AC2** The queue offers one clip at a time with playback, and the labelling
  instrument (`ConfidenceLabelChips.tsx`) carries no machine-derived field.
- **AC3** `GET /v2/coach/sessions/<id>/confidence-comparison` reveals
  comparison **only after** the coach's own judgments are submitted (§34).

### US-C-032 — Review a Speaker's practice attempt `[F2]`
- **AC1** `GET /v2/coach/sessions/<id>/snippets/<snippetId>/confidence-practice`
  gives the coach the Speaker's practice attempt for judgement.
- **AC2** Saving a practice attempt never admits it to the Album; **the coach
  judges the selected practice attempt itself** (§33).
- **AC3** Album admission still requires Machine Yes + User Yes + Coach Yes on
  **that exact attempt** (§35g, G-8).

---

## B5 — Ground truth on segmentation

### US-C-040 — Correct which slide was on screen `[F1-CORE]`
**This is the one coach action that is F1-CORE**: it is the only human check on
word→slide bucketing, which is load-bearing piece (a).

- **AC1** `PUT /v2/coach/snippets/<id>/slide` takes `{slide_index: int}` to
  assert the slide that was **on screen** while the snippet was spoken, or
  `{slide_index: null}` to **withdraw** a correction (the pipeline was right).
- **AC2** Correctness is **what the audience was looking at** — *not* "these
  words are about slide N". A speaker who ran ahead of their own deck is **not**
  a bucketing error, and the coach-facing copy says so.
- **AC3** The index is validated against **this session's deck**; a correction
  pointing at a slide the deck does not have is a corrupt label and **fails
  here** rather than landing in the corpus.
- **AC4** The row is **append-only** — inserted, never upserted — so the trail
  of what the pipeline said and what the human said instead survives.
- **AC5** Every correction is also one `(speech window, slide)` training pair:
  the corpus any learned aligner would need before it could be trained at all.
- **AC6** Corrections never mutate the Speaker's Ideal Text (G-5).

### US-C-041 — Re-cut a session `[F1-SURFACE]`
- **AC1** `POST /v2/coach/sessions/<id>/recut` re-runs the segmenter on an
  existing Take.
- **AC2** A re-cut **never** creates a new Take or increments the Take count
  (§1.6).
- **AC3** A re-cut never rebuilds Ideal Text (G-5).
- **AC4** A failed re-cut leaves the prior segmentation intact.

### US-C-042 — See slide↔delivery coverage `[F2]`
- **AC1** `GET /v2/coach/sessions/<id>/slide-alignment` returns the claim
  ledger of slide↔delivery coverage for one Take.
- **AC2** It is a coach-only operational read; no coverage figure it contains
  is ever surfaced to the Speaker (§24i, G-1).

### US-C-043 — Confirm routing language for a historical Take `[F2]`
- **AC1** `PUT /v2/coach/sessions/<id>/language` confirms routing language for
  a historical Take with missing metadata.
- **AC2** It is confirmation of a **fact about the recording**, never a
  judgement about the speaker, and is provenance-typed accordingly (G-8).
- **AC3** A confirmed language routes future blind rating to language-matched
  raters only (US-C-003 AC7).

---

## B6 — Judging and correcting machine output

### US-C-050 — Judge one fired detector output `[F2]`
- **AC1** `PUT /v2/coach/snippets/<id>/star-verdict` records exactly one of
  `keep` (the output was right — the endorsement signal), `wrong_kind`
  (requires `corrected_device` — the confusion pair), or `should_not_fire`
  (this moment deserved silence).
- **AC2** Re-judging the same item **replaces** the previous verdict
  (idempotent).
- **AC3** Optional corrected wording (`*_final` keys) rides the **same PUT**,
  which makes the half-state — an edit with no verdict — **unrepresentable at
  the wire**. The edit→keep **pair** is what trains.
- **AC4** Partial semantics: an absent key **preserves** the stored correction.
  There is no null-clear on this route; the full-state star-text PUT keeps that.
- **AC5** Text writes happen **before** the verdict, so a `keep`'s corpus
  emission always carries the fresh wording; a guard-tripping string returns
  `400` before **anything** is written — the gesture stays atomic.
- **AC6** Nothing here mutates the machine's draft text or the Speaker's flow
  (G-5).
- **AC7** **Verdicts are never surfaced to the Speaker** (§AC-9, G-1).
- **AC8** No glyph anywhere renders as a star — the coach's approval mark is
  neutral, so no corner is left where the retired star lane can quietly return
  (`noStarsOnUserSurfaces.test.ts`).

### US-C-051 — Correct what an item says `[F2]`
- **AC1** `PUT /v2/coach/snippets/<id>/star-text` is the full-state write for
  corrected wording, including clearing it.
- **AC2** `PUT /v2/coach/snippets/<id>/say-it-stronger` records the
  coach-corrected stronger formulation for one snippet.
- **AC3** The original machine output **remains in history** (§36).
- **AC4** A material correction becomes a **new accept/reject proposal** for
  the Speaker if they have seen or acted on the original (§37).
- **AC5** Machine-versus-coach outcomes are the **learning comparison** (§38);
  the pair is preserved, not overwritten.

### US-C-052 — Choose the feedback language a Speaker will read `[F2]`
- **AC1**
  `PUT /v2/coach/confident-moment-bundles/<id>/attachments/<id>/feedback-language`
  publishes the coach's wording for one attachment.
- **AC2** Publishing wording is **separate** from judging the clip and from
  notifying the Speaker (provenance walls).
- **AC3** The wording carries no band, score or ranking (G-1).
- **AC4** Wording that reaches the Speaker is user-facing copy and needs
  founder sign-off (LIVE LOOP). ⚠ See **Q-7**.

---

## B7 — The coach's view of Ideal Text

> ⚠ **FOUNDER DECISION NEEDED (Q-3).** §40 says *"The coach does not own or
> publish a competing full-document version"* and that coach wording changes
> are proposals the Speaker accepts or rejects. The routes below (built
> 2026-07-15/17, before the 2026-08-26 contract) let a coach **save a one-block
> edit of the ideal text, approve it, verify it and publish it**. Either these
> routes are pre-contract legacy to be re-shaped into proposals, or §40 needs
> amending. Per §55 this is a founder call, not an inference. **The ACs below
> describe the routes as built; they are not an endorsement of the shape.**

### US-C-060 — Read the coach copy of the document `[F2]`
- **AC1** `GET /v2/coach/arc/<id>/ideal-text` returns the coach's review copy
  of the one-block ideal text.
- **AC2** `GET /v2/coach/arc/<id>/best-presentation` is the coach's own preview
  only. Best Presentation is retired as a **product artifact** (§7); this read
  must never become a Speaker-facing document. ⚠ See **Q-2**.

### US-C-061 — Save, approve and verify `[F2]`
- **AC1** `PUT /v2/coach/arc/<id>/ideal-text` saves the coach's one-block edit;
  markers travel with the text, raw HTML is stripped, ≤20 000 chars.
- **AC2** `POST /v2/coach/arc/<id>/ideal-text/approve` approves for delivery
  (the publish precondition). With no saved coach block yet, the auto draft is
  persisted and approved in **one deterministic action**
  (review-without-edit approval) — never two states that can disagree.
- **AC3** An empty document returns `409 IDEAL_TEXT_EMPTY` rather than
  approving nothing.
- **AC4** `POST /v2/coach/arc/<id>/verify` marks the **current version**
  verified (who and when stamped, served text snapshotted) and fires the
  per-version verified notification to the Speaker.
- **AC5** The Speaker's GET then serves the verified text **free — no payment
  gate on the text, ever** (§51).
- **AC6** A new Take afterwards bumps the version, status resets to unverified,
  and the loop continues. Verify is **idempotent per version** and returns
  `already_verified` rather than double-firing a notification.
- **AC7** `409 NOTHING_TO_VERIFY` when there is no current version to verify.

### US-C-062 — See every fired item on a Project `[F2]`
- **AC1** `GET /v2/coach/arc/<id>/stars` returns every item the system fired on
  this Project with the coach's judgment alongside.
- **AC2** It is an operational read for the coach; nothing in it is surfaced to
  the Speaker (G-1).

### US-C-063 — Attach further reading to a moment `[SCAFFOLDING]`
- **AC1** `PUT /v2/coach/snippets/<id>/reference` attaches **or clears** a
  Journal post as further reading on one moment.
- **AC2** The reference is optional context, never a Feedback family, and never
  gates progress (§21, §57).

---

## B8 — Blinded A/B comparison

### US-C-070 — Judge two takes of the same slide, blind `[F2]`
- **AC1** `GET /v2/coach/arcs/<id>/ab-pairs` returns the **same slide, two
  takes, no labels** (founder 2026-08-11).
- **AC2** `PUT /v2/coach/arcs/<id>/ab-verdict` records
  `{pair_id, verdict: 'left' | 'right' | 'tie'}` — `tie` is a first-class
  answer, not a skip.
- **AC3** No take number, no machine read and no user answer is visible before
  the verdict (G-3).
- **AC4** `/coach/compare` is deliberately its **own route** rather than an
  overlay, because it is a queue — judge, next, judge, next — not something
  opened over a review and dismissed.
- **AC5** Blind peer comparison is retained **exclusively** for internal model
  training and evaluation and has **zero authority** over user Feedback, key
  moments, Manager selection, Ideal Text, styling, root phrases, journey
  behaviour, coach decisions, or Album eligibility (§35).
- **AC6** The blind peer quorum **never appears** in the rehearsal or personal
  coaching loop (§35).

---

## B9 — Guidance and inline exercise authoring

### US-C-080 — Author guidance for a Speaker `[F2]`
- **AC1** `POST /v2/coach/guidance/attachments` attaches authored guidance;
  `GET /v2/coach/guidance/batches/<arcId>` reads the batch for one Project.
- **AC2** `POST /v2/coach/guidance/publications` publishes; **drafting,
  judgement, publication and notification stay four distinct records**
  (provenance walls).
- **AC3** `POST /v2/coach/guidance/events` records typed authoring events; none
  is an effectiveness label (§35e).
- **AC4** Guidance delivery to the Speaker is a **separate explicit action**
  (§35f), never an automatic consequence of authoring.

### US-C-081 — Author a case-bound exercise inline `[F2]`
- **AC1** `POST /v2/coach/guidance/exercise-drafts` saves one **case-bound**
  exercise draft **below its exact case** — never a free-floating library item.
- **AC2** `GET /v2/coach/guidance/exercise-drafts/<id>/playback` serves the
  draft's audio through the authenticated service only.
- **AC3** A coach may choose an eligible exercise, author a versioned
  case-specific exercise, **or report no safe match** — and may do so **only
  after** submitting their immutable confidence judgment (§35f).
- **AC4** Authoring is gated by `MLC3_COACH_INLINE_AUTHORING_ENABLED`; when off
  the surface is absent, not broken (G-4).
- **AC5** Professional authoring is its own provenance type and never merges
  with judgement or machine output (§35g, G-8).

---

## B10 — MLC3 first-client blind review

### US-C-090 — Work an assigned blind review set `[F2]`
- **AC1** `GET /v2/coach/mlc3/reviews/<projectId>` lists the review set;
  `POST /v2/coach/mlc3/reviews/assignments/<id>/render` acknowledges that an
  assignment was actually rendered to the reviewer.
- **AC2** `GET /v2/coach/mlc3/reviews/playback/<playbackReferenceId>` serves
  **blind** playback — a reference id, not a recording id, so nothing about the
  source leaks through the URL.
- **AC3** `POST /v2/coach/mlc3/reviews/assignments/<id>/judgments` submits an
  **immutable** judgment; an `idempotency_key` makes a retry safe.
- **AC4** `GET /v2/coach/mlc3/source-playback/<assignmentId>` returns **only
  the exact canonical source clip** for that one assignment (G-8).
- **AC5** `POST /v2/coach/mlc3/reviews/<reviewSetId>/complete` closes the set;
  completion is explicit, never inferred from the last judgment.
- **AC6** `POST /v2/coach/mlc3/inline/assignments/<id>/render|judgments` is the
  inline variant and obeys the same blind boundary
  (`CoachInlineBlindExposureBoundary.tsx`).
- **AC7** When the MLC3 service is unavailable the routes return a typed
  unavailable response rather than a partial or guessed one (G-4).

---

## B11 — Students and audits

### US-C-100 — See my roster `[F2]`
- **AC1** `GET /v2/coach/students` returns a pseudonymised roster (G-9).
- **AC2** `GET /v2/coach/students/<userId>` is the pseudonymised drill-down for
  one Speaker.
- **AC3** No route in this section returns an email, a name, or a raw user id
  (G-9).

### US-C-101 — Assemble and send an audit `[SCAFFOLDING]`
- **AC1** `GET /v2/coach/students/<userId>/audit-data` returns the
  audit-assembly data for the interactive builder.
- **AC2** `GET /v2/coach/students/<userId>/audit` downloads the assembled
  audit.
- **AC3** `POST /v2/coach/students/<userId>/audit/send` is a **manual** trigger
  — an audit is never sent automatically.
- **AC4** The audit contains no score, band or classifier output (G-1).
- **AC5** Audit send respects the Speaker's email consent (US-S-003).

---

## B12 — Training corpus

### US-C-110 — Import audio as training data `[F2]`
- **AC1** `POST /v2/coach/training-imports` uploads **one** audio file as
  coach-reviewable training data.
- **AC2** An import is **never a Take** and never touches any Speaker's Project
  (§1.6, G-5).
- **AC3** The POST returns `202`; **the 202 is not the outcome**.
  `GET /v2/coach/training-imports/<sessionId>` polls the analysis.
- **AC4** `GET /v2/coach/training-imports` lists imports newest first.
- **AC5** `DELETE /v2/coach/training-imports/<sessionId>` is **archive**, not
  destroy — DELETE is the verb, archive is the semantics — and
  `GET .../restore` undoes it idempotently.
- **AC6** `/coach/corpus` is deliberately its own route, not a Lounge overlay:
  it is a bulk workbench (pick thirty files, wait, label a queue).
- **AC7** Phase-2 corpus, dataset, training, evaluation and promotion paths stay
  disabled until separately authorized (G-11).

### US-C-111 — Label imported clips `[F2]`
- **AC1** Imported clips are labelled through the **same** blind confidence
  instrument as rehearsal clips (US-C-030), and the derived lane is `coach` for
  both (US-C-030 AC5).
- **AC2** `/coach/corpus/summary/<sessionId>` summarises one import without
  revealing any machine read before judgement (G-3).

---

## B13 — The speaking error library

### US-C-120 — Name an observed speaking error `[F2]`
- **AC1** `POST /v2/coach/speaking-errors` names and defines **one observed**
  speaking error.
- **AC2** `GET /v2/coach/speaking-errors` returns the **whole library including
  retired entries**, so an author can see what already exists rather than
  coining a near-duplicate.
- **AC3** Every entry has a **written operational definition** and asks exactly
  one thing (G-2). An entry without one cannot ship.
- **AC4** `/coach/errors` is its own route because the CMS is gated on the
  shared admin password, which a coach does not have — **that is the entire
  reason the screen exists**.
- **AC5** Retiring an entry never rewrites historical labels that used it;
  entries are versioned, not rewritten (SPEC §3.2).

---

## B14 — The Take-level video note

### US-C-130 — Record one optional video note `[F2]`
- **AC1** `POST /v2/coach/sessions/<id>/video` attaches **one optional
  Take-level** video note.
- **AC2** Per-item breakthrough videos and per-item Star Verdict videos are
  **retired**; Star Verdict review remains **text-based** (§41).
- **AC3** The note is **explicitly shared**, never autoplays, never gates
  progress, and carries **no detector label or Feedback verdict** (§41, G-1).
- **AC4** Uploads are bounded by `COACH_FEEDBACK_VIDEO_MAX_MB` (100 MB) and
  land in `COACH_FEEDBACK_VIDEO_BUCKET`; media URLs are refreshed through
  `services/coach_video_storage.refreshed_media_url`, never served from a
  public path (G-7).

---

# Part C — The Master Coach (admin)

An allowlisted row in `admin_users`. The Master Coach is the **superset
operator**: `require_admin_or_coach` admits them everywhere a Coach may go, so
**every story in Part B is also a Master Coach story** and is not repeated
here. Part C covers what only they can do.

> **Four different gates guard the operator surfaces, and only one of them
> knows who you are.** This matters for G-10 (auditability) and is stated once
> here rather than in every story:
>
> | Gate | Mechanism | Identifies an actor? | Used by |
> |---|---|---|---|
> | `@require_admin` | `admin_users` allowlist on token email | **Yes** | `/v2/admin/*`, CEO workspace, tokens, users |
> | `JOURNAL_ADMIN_PASSWORD` | shared password in the **request body**, `hmac.compare_digest` | **No** | `/v2/internal/journal/*` (the CMS) |
> | `DEV_BUGS_KEY` | `x-dev-key` header | **No** | `/api/dev-bugs/*` |
> | Webhook secrets | `X-Internal-Secret`, `Stripe-Signature` | n/a (machine) | `/v2/internal/*` |
>
> ⚠ **FOUNDER DECISION NEEDED (Q-8)** — a shared password cannot satisfy G-10.
> A CMS publish is user-facing copy under the LIVE LOOP fence, and today
> nothing records **which human** published it.

## C1 — Operator access

### US-M-001 — Prove I am an admin `[SCAFFOLDING]`
- **AC1** `GET /v2/admin/whoami` returns `200 {admin: true}` for an admin and
  `403` for everyone else — a cheap, unambiguous probe.
- **AC2** `GET /v2/admin/health` returns 200 only for a valid admin token;
  `GET /v2/admin/health/dad-jokes` probes that one table's availability.
- **AC3** Admin status is a **service-role table read keyed on token email**,
  never a JWT claim and never a frontend flag (G-7).
- **AC4** `AdminGate` renders nothing for a non-admin, and the backend enforces
  independently — the frontend gate is for the URL-guesser.
- **AC5** Admin surfaces are **not linked in navigation**; they are bare
  internal tools reached by URL.

## C2 — The user directory

### US-M-010 — Look up an account `[SCAFFOLDING]`
- **AC1** `GET /v2/admin/users?limit&offset&search` lists a **bounded page** of
  accounts with `user_id`, `email`, `name`, `created_at`, `last_sign_in_at`,
  `email_confirmed_at`, `is_admin`.
- **AC2** `limit < 1` or `offset < 0` returns `400 INVALID_INPUT` — a bad page
  is refused, not silently clamped.
- **AC3** A non-integer `limit`/`offset` returns `400`, not a 500.
- **AC4** A directory outage returns `503 SERVICE_UNAVAILABLE`, not an empty
  list presented as "no users".
- **AC5** This is the **only** surface in the product that pairs a real
  identity with account state. It is admin-only and never reachable from a
  Coach surface (G-9).
- **AC6** Nothing here shows any speaking quality read (G-1).

## C3 — Token grants

### US-M-020 — Top up an account `[SCAFFOLDING]`
- **AC1** `POST /v2/admin/tokens/grant` with `{email|user_id, tokens, ref_id}`
  adds **non-expiring** tokens.
- **AC2** It grants to `bonus_balance`, **and the panel says so** — the monthly
  roll *sets* `token_balance`, so a grant written there would silently expire at
  the account's next period.
- **AC3** The balance breakdown is rendered as parts rather than one total,
  precisely so the operator can see **which half moved**.
- **AC4** `ref_id` makes a grant idempotent; a repeat with the same `ref_id`
  does not double-grant.
- **AC5** `GET /v2/admin/tokens/lookup` returns one account's balance:
  `200 · 400 · 404`, with `403` from the decorator.
- **AC6** This replaces the retired `/v2/internal/student-credits/*` pair, which
  took a shared `CREDIT_ADMIN_PASSWORD` **in the request body** — no password
  field, and **no secret in the client bundle**.
- **AC7** A token balance is **commerce, not a read on a speaker**. No quality
  signal appears on this surface, and nothing on it renders on a Speaker
  surface (G-1).
  ⚠ AC2's "next period" and the monthly roll are the same §48–§51 conflict as
  **Q-1**.

## C4 — Session and pipeline inspection

### US-M-030 — Inspect one session in full `[F1-SUPPORT]`
- **AC1** `GET /v2/admin/sessions/<id>` returns the comprehensive admin payload
  for one session.
- **AC2** `GET /v2/admin/sessions/<id>/readout` returns the coach authoring
  readout — **pseudonymised and free of model verdicts**, so an admin reading
  it before a judgement does not break the blind boundary (G-3).
- **AC3** `GET /v2/admin/review-queue` lists `review_pending` Lab sessions,
  newest first.
- **AC4** `GET /v2/recordings` (admin) pages all recordings for review.
- **AC5** Inspection is read-only: nothing in this section mutates a Speaker's
  Ideal Text, locks, roots, or feedback (G-5).
- **AC6** Every inspection of identified data is justified by an operational
  need; the surface is not a browsing tool (G-9 intent).

### US-M-031 — Watch the processing pipeline `[F1-SUPPORT]`
- **AC1** `GET /v2/internal/jobs/health` reports queue health;
  `POST /v2/internal/jobs/sweep` re-runs stranded jobs.
- **AC2** `GET /v2/internal/whisper-health` probes transcription availability.
- **AC3** A sweep **re-runs** a job against its preserved Recording Attempt and
  never creates a new Take (§1.5).
- **AC4** Queue mode failure **falls back** to the daemon or sync path, so
  flipping `PIPELINE_QUEUE_ENABLED` can never block an upload (G-4).
- **AC5** Internal endpoints are gated by `X-Internal-Secret`; an unconfigured
  secret returns `503 DISABLED` — **"off" and "wrong credential" are different
  answers**.

### US-M-032 — Publish session results `[F2]`
- **AC1** `POST /v2/internal/publish-session-results` is gated
  `@require_admin_or_coach`.
- **AC2** Publication is atomic and is separate from drafting, judgement and
  notification (provenance walls).
- **AC3** A Speaker who has unsubscribed receives no publish email, and the
  publish itself still succeeds (US-S-124 AC3).

## C5 — The question pool

### US-M-040 — Curate prompted questions `[SCAFFOLDING]`
- **AC1** `GET /v2/admin/question-pool?intent&locale` lists the pool filtered
  by intent and locale.
- **AC2** `POST /v2/admin/question-pool` inserts **one** question.
- **AC3** `PATCH /v2/admin/question-pool/<id>` partially updates one question.
- **AC4** `DELETE /v2/admin/question-pool/<id>` is a **soft delete**
  (`active = false`) — historical answers keep pointing at the question that
  was actually asked (SPEC §3.2, G-10).
- **AC5** Every pooled question asks **exactly one thing** and traces to a
  written operational definition (G-2). A question that bundles two asks cannot
  ship.
- **AC6** A pooled question that reaches a Speaker is user-facing copy and needs
  founder sign-off (LIVE LOOP). ⚠ See **Q-7**.

## C6 — The CEO workspace (founder product management)

### US-M-050 — Load the workspace `[SCAFFOLDING]`
- **AC1** `GET /v2/admin/ceo/bootstrap` returns the workspace in one read.
- **AC2** `/admin/ceo` renders behind `AdminGate` and is not linked in
  navigation.
- **AC3** Nothing in the CEO workspace is reachable from a Speaker or Coach
  surface (G-7).

### US-M-051 — Manage features and artifacts `[SCAFFOLDING]`
- **AC1** `GET/POST /v2/admin/ceo/projects/<projectKey>/features` lists and
  creates features; `GET/PUT .../view-state` persists workspace view state per
  project.
- **AC2** `PATCH /v2/admin/ceo/artifacts/<artifactId>` saves an artifact;
  `.../analysis` runs analysis; `.../comments` records comments.
- **AC3** `POST /v2/admin/ceo/analysis-runs/<runId>/review` records the
  founder's review of one analysis run.
- **AC4** `GET/POST /v2/admin/ceo/features/<featureId>/sources` manages a
  feature's sources.
- **AC5** The workspace is an internal planning tool: **nothing authored here
  becomes product behaviour without a normal gate-routed PR** (standing
  engineering constraints).

### US-M-052 — Manage bugs and tasks `[SCAFFOLDING]`
- **AC1** `GET/POST /v2/admin/ceo/bugs`, `PATCH/DELETE
  /v2/admin/ceo/bugs/<id>`, `POST .../retry`.
- **AC2** `GET/POST /v2/admin/ceo/tasks`, `POST .../done`, `.../archive`,
  `.../restore`, `GET /v2/admin/ceo/tasks/export`.
- **AC3** Archive and done are **distinct** states and restore is available for
  both — no work item is destroyed by a mis-tap.
- **AC4** Export produces the complete current set, not a page.

### US-M-053 — Use the founder bug collector `[SCAFFOLDING]`
- **AC1** `GET/POST /api/dev-bugs`, `PATCH/DELETE /api/dev-bugs/<id>`, and
  `POST /api/dev-bugs/send` require the header `x-dev-key: <DEV_BUGS_KEY>`,
  mirroring the `X-Internal-Secret` gate on `/v2/internal/*`.
- **AC2** The **page** at `/dev-bugs` is ungated — it prompts for the key
  client-side; enforcement is on the API, so an ungated page leaks nothing.
- **AC3** `DELETE` only works while `status = 'open'`, so shipped items keep
  their history.
- **AC4** `POST /api/dev-bugs/send` runs the same routine as the three-day
  cron; sending twice does not duplicate a digest.
- **AC5** `GET/DELETE/PATCH /api/dev-tasks/*`, `.../done`, `.../restore`,
  `.../reorder`, `/export` behave equivalently.
- **AC6** The key is compared with `hmac.compare_digest` and is never logged.

## C7 — The Journal CMS

### US-M-060 — Write and publish a post `[SCAFFOLDING]`
- **AC1** Every CMS route is `POST` with the password in the **body**, compared
  with `hmac.compare_digest` and **never logged**.
- **AC2** An unconfigured password returns `503 DISABLED` (the feature is off);
  a mismatch returns `401 Wrong password`. **These are different answers.**
- **AC3** `posts/create`, `posts/update`, `posts/get`, `posts/list` (all posts
  including drafts), `posts/delete`, `posts/publish`, `posts/unpublish`,
  `reorder`, `revalidate`.
- **AC4** `publish` makes a post publicly readable at `/v2/journal/posts` and
  `/blog/<slug>`; `unpublish` removes it from both immediately.
- **AC5** Published Journal content is user-facing copy and needs founder
  sign-off (LIVE LOOP). ⚠ See **Q-7**, **Q-8**.
- **AC6** No published post may surface a score, a band, or the retired
  charisma/stress/threat construct vocabulary (G-1, G-2).

### US-M-061 — Manage post media `[SCAFFOLDING]`
- **AC1** `image/generate` creates cover-image candidates; `image/list`,
  `image/select`, `image/delete` manage them.
- **AC2** `media/presign` issues a bounded upload URL; it is not a general
  file-hosting endpoint.
- **AC3** A selected image is explicit; nothing is auto-selected.

### US-M-062 — Manage community and diagnostic content `[SCAFFOLDING]`
- **AC1** `community/generate`, `community/list`, `community/update`,
  `community/delete` manage community entries.
- **AC2** `diagnostic-exercises/list` and `diagnostic-exercises/save` manage
  diagnostic exercises.
- **AC3** `speaking-errors/list` and `speaking-errors/save` are the CMS-side
  view of the library a Coach authors at `/coach/errors` (US-C-120) — the
  **same** entries through a different gate, never a second library that can
  disagree with the first.
  ⚠ Two gates over one library is exactly the ambiguity **Q-8** names.

## C8 — Machine-to-machine boundaries

### US-M-070 — Receive a payment webhook `[SCAFFOLDING]`
- **AC1** `POST /v2/internal/stripe/webhook` verifies `Stripe-Signature`
  against `STRIPE_WEBHOOK_SECRET` via `stripe.Webhook.construct_event`; an
  unverified body is never processed.
- **AC2** Missing `STRIPE_WEBHOOK_SECRET` or `STRIPE_SECRET_KEY` returns
  `503 DISABLED` rather than accepting unverified events.
- **AC3** Credit grants map from `STRIPE_CHECKOUT_PRICE_CREDITS_JSON`; an
  unknown price id grants nothing and is logged, never guessed.
- **AC4** Webhook processing is idempotent on the Stripe event id.
- **AC5** Subscription webhooks apply tier changes through
  `services/stripe_subscription_tiers.py`; **nothing is decided in the route**.
  ⚠ The subscription model itself is **Q-1**.

### US-M-071 — Run internal maintenance jobs `[SCAFFOLDING]`
- **AC1** `POST /v2/internal/drift/run`, `/v2/internal/annotation-export`,
  `/v2/internal/copilot-video/retrain`, `GET /v2/internal/life/reminders` are
  secret-gated and return `503 DISABLED` when unconfigured.
- **AC2** Phase-2 corpus, dataset, training, evaluation, promotion and
  exercise-adequacy paths remain **disabled** until separately authorized —
  `routes/phase2_guard.py` is the boundary, not a convention (G-11).
- **AC3** No maintenance job may run a retention purge as a side effect; purges
  are separately authorized and previewed (US-S-122 AC6).

## C9 — Operating the live system

### US-M-080 — Ship a change safely `[F1-SUPPORT]`
- **AC1** New work branches off `origin/main` and ships via **gate-routed PRs**
  (branch → PR → CI green → squash-merge). Tables, columns and migrations are
  never auto-dropped.
- **AC2** **On `main` means run in prod**: `MIGRATE_ON_BOOT=1` means
  `bin/railway-web.sh` applies pending migrations during container start, so
  **merging a migration IS running it**, before the app process boots.
- **AC3** Migrations are idempotent (`IF NOT EXISTS`) and degrade gracefully.
- **AC4** **CONFIG-FIRST:** when a migration's correctness depends on an
  environment variable, that variable is set on **every** Railway service (web,
  worker, cron) **before** the PR merges. The config waits for the code, never
  the reverse.
- **AC5** A *writer* service missing the variable is the worst case — the web
  app looks healthy while background jobs silently drop their writes. Verify
  from each service's **boot log**, not the Railway UI: the UI shows what was
  set, the log shows what the process read.
- **AC6** Ship the variable-reading code and the migration in the **same PR**
  so one container start does the whole cutover. If that is impossible, keep
  the migration out of `migrations/manifest.txt` until the config lands.
- **AC7** When GitHub Actions is out of minutes, the gate is
  `scripts/local_ci.sh` — it rebuilds the `checks` job environment (python
  3.12, pinned `ruff`/`mypy`, `requirements.txt`) and runs its steps in order.
  An ad-hoc `pytest && ruff && mypy` is **not** the job: a system `mypy` one
  major version behind CI's pin passed five real type errors the pinned one
  catches. `tests/test_local_ci_mirror.py` fails if script and workflow drift.
- **AC8** A runner-allocation failure (two red X's, zero billable ms, HTTP 404
  on logs) is **not** a code failure and re-running cannot help. Merge on local
  evidence and document the override in the squash commit.

### US-M-081 — Hold the fences `[F1-SUPPORT]`
- **AC1** The master document's construct fence (`_CONSTRUCT_RE`) plus its CI
  probe blocks the retired charisma/stress score vocabulary, and since
  2026-08-13 the charisma/threat **construct** at all (G-2).
- **AC2** `power_score` has **no** challenge/threat inputs; confidence uses one
  universal, **sex-blind** cue contract. The product neither collects speaker
  sex for processing nor infers it from pitch (2026-08-29).
- **AC3** Historical rows are **audit-only** and receive no new writes. They are
  never compatibility aliases, product evidence, or training input.
- **AC4** All product copy is held for founder sign-off. "It's a tiny copy
  tweak" is not an exemption (R13).
- **AC5** The WILLAB DECISION FILTER runs on **every** proposed change before
  work starts, and its verdict block is emitted. The filter text is kept
  **identical** across both repos — a divergence between the two copies is
  itself drift.

---

# Part D — Cross-role invariants and negative stories

These are the stories written as **"nobody may"**. They are the ones a feature
request quietly breaks, so they are written down as acceptance criteria and
tested, not carried in someone's head. Each names how it is enforced today.

### US-X-001 — Nobody surfaces a number to the Speaker `[FENCE: AC-9]`
- **AC1** No Speaker-facing surface renders a score, percentage, ratio, rank,
  band name, probability, classifier output, count of findings, or comparison
  to other users (§AC-9, §24i).
- **AC2** Coverage percentages, delivery bands, PPV estimates, priority values
  and block counts stay internal (§24i).
- **AC3** A Coach or Master Coach operational read (slide-alignment coverage,
  star verdicts, confidence comparison, token balances) **never leaks** onto a
  Speaker surface (US-C-042, US-C-062, US-M-020).
- **AC4** Enforced by `noStarsOnUserSurfaces.test.ts` as a **source scan**, not
  a render test — the star lane died as six separate renderers, so the
  invariant must hold of the code, not of one mounted surface.
- **AC5** Demand is not an argument: *"users want a score"* is rejected
  regardless of demand, and redirected to the qualitative read (R6).

### US-X-002 — Nobody ships a construct without a written definition `[FENCE: CONSTRUCT]`
- **AC1** Every measured state traces to a written operational definition
  (SPEC §1.4/§17) and asks exactly **one** thing.
- **AC2** A state with no definition entry **cannot ship** — this is the exact
  defect that retired "charisma" on 2026-08-13: it had no written definition,
  so nothing could say what a rater was being asked.
- **AC3** `confidence` is never folded together with charisma (SPEC §17).
- **AC4** The retired charisma/stress/threat/challenge vocabulary appears in no
  surface, field, prompt or new write. `power_score` has no challenge/threat
  inputs (2026-08-29).
- **AC5** The coach's historical challenge/threat rows in `training_labels` are
  a **corpus, not a construct claim**, and are versioned rather than rewritten
  (SPEC §3.2).
- **AC6** Enforced by `_CONSTRUCT_RE` plus its CI probe.

### US-X-003 — Nobody surfaces a blind guess as a badge `[FENCE: BLIND COACH]`
- **AC1** The shadow model never surfaces its guess as a badge anywhere (R9).
- **AC2** Model–human agreement is measured **off-surface**.
- **AC3** A rater sees no machine read before submitting (G-3), and
  `saw_model_output: false` is an assertion the surface must keep true.
- **AC4** Blind peer labels and quorum are **internal corpus evidence, never
  product decision inputs** (§35, provenance walls).

### US-X-004 — Nobody breaks the live loop `[FENCE: LIVE LOOP]`
- **AC1** record → process → Ideal Text → next Take runs regardless of the
  state of feedback, coach review, exercises, learning, billing, chat or
  notification (G-4).
- **AC2** Coach review is asynchronous and never gates immediate feedback or
  the next Take (§23, §39).
- **AC3** Merges are gate-routed (US-M-080).
- **AC4** All user-facing copy needs founder sign-off — small is not exempt
  (R13). ⚠ See **Q-7**.
- **AC5** Urgency justifies **sequencing**, never fence-breaking. A demo is not
  a reason; the fastest on-goal thing is (R14).

### US-X-005 — Nobody rebuilds Ideal Text `[LOCK: L1]`
- **AC1** No later Take, transcript, best-of assembly, machine proposal or
  coach action rebuilds or silently changes Ideal Text (§8, §9).
- **AC2** *"Let each Take regenerate the Ideal Text"* is rejected: generate
  **proposals** and require explicit acceptance (R7).
- **AC3** Best Presentation as a separate product artifact is retired (§7).
  Historical `best_presentation_ready` messages remain readable **only** as
  compatibility entry points to the live Ideal Text for that Project; they
  never rebuild, cache, or expose a separate document, and **no new message is
  created under that legacy kind** (§56).

### US-X-006 — Nobody bypasses Manager arbitration `[LOCK: L2]`
- **AC1** A raw Candidate never reaches the Speaker (§22).
- **AC2** *"Show every strong detector output"* is rejected — route Candidates
  through the Manager (R8).
- **AC3** The active versioned budget is never exceeded and never filled by
  invention: an honest `no_defensible_candidate` lane shows **no card** (§25).
- **AC4** V3 never silently substitutes V2; V2 is retained **only as superseded
  history** (§24h). ⚠ See **Q-4** for what "V3 has run clean" must mean before
  V2 is removed.
- **AC5** Coverage never overrides the evidence rule — a coverage floor that
  could override evidence would be a licence to fabricate (§24d).

### US-X-007 — Nobody mixes provenance `[LOCK: L3]`
- **AC1** Machine prediction, owner routing, blind peer rating, coach judgment,
  detector verdict, exercise outcome and professional authoring stay separate
  and are never stored under one semantic label (§31, §35g).
- **AC2** *"Owner agreement is good enough training data"* is rejected — owner
  routing stays separate from blind and coach labels (R10, §30).
- **AC3** Signals are never reused across recordings; Album admission needs all
  three signals on the **exact** recording (§32).
- **AC4** Exercise outcomes never train Confidence Classification (§35g).
- **AC5** The three Feedback families are **never merged into one
  undifferentiated training set** (§35k).
- **AC6** Praise selection/ranking is **not trained** until the exposure ledger
  is complete (§35k).

### US-X-008 — Nobody serves engagement `[DRIFT]`
- **AC1** No streak, leaderboard, badge count, daily nudge, scarcity device or
  retention loop exists on any surface (R3, worked example B).
- **AC2** *"More usage → more Takes → better learning"* is engagement dressed
  as F1 support and is rejected (R3).
- **AC3** The value is **a better speech**, not more sessions.

### US-X-009 — Nobody keeps a degraded legacy path `[§52–§57]`
- **AC1** Obsolete runtime pipelines, behavioural fallbacks, adapters and
  aliases are **removed**, not retained as degraded paths (§52).
- **AC2** Legacy compatibility never silently selects a different document,
  processing, feedback, learning or billing policy (provenance walls).
- **AC3** Migration history stays for reproducibility; obsolete live tables go
  only through an explicit new migration (§54).
- **AC4** **Any route, table or behaviour whose active use is ambiguous
  requires an individual founder decision before removal** (§55) — which is
  why §D.11 asks rather than deletes.
- **AC5** Breakthrough Moments (§57), the threat/challenge framework (§58–§59),
  the generic Game (§60), the direction-learning subsystem (§61) and the
  Reflection Game (§62) are retired and must not reappear under new names.

### US-X-010 — Nobody widens a role by accident `[G-7]`
- **AC1** A Coach never gains an admin-only capability by a route being
  re-gated to `require_admin_or_coach` without a founder decision.
- **AC2** A Master Coach inherits every Coach capability **by design** (the
  superset operator), and that is stated, not incidental.
- **AC3** A Speaker never reaches a Coach or Master Coach surface, including by
  URL guess (G-7).
- **AC4** `@optional_auth` routes (guest-capable: `POST /v2/projects`,
  `POST /v2/lab/recordings`, the guest readout, transcript edits,
  suggestion-feedback, arc progress) accept a **signed Guest ID** with the same
  authority as an authenticated owner — and **a bare session UUID is never
  authorization** (`v2_user_put_transcript_edit`).

---

## §D.11 — Open questions for the founder

Each is a place where **code and contract disagree**, or where the contract is
silent on something already built. §55 says these are individual founder
decisions, so they are listed rather than resolved.

| # | Question | Evidence | Why it matters |
|---|---|---|---|
| **Q-1** | **Is the commercial model one-time packages or monthly subscriptions?** | §48–§51 say one-time packages, no subscriptions, no renewal dates, no monthly plans, balances remain until consumed. `routes/token_routes.py` says *"start a subscription for a tier"*, *"Every tier now renews monthly"*, returns `period_ends_at`, and `/admin/tokens` warns that *"the monthly roll SETS `token_balance`, so a grant there silently expires at the user's next period."* | The sharpest contract/code conflict found. It changes user-facing copy, the billing portal, the grant surface and §51's promise that an exhausted balance never removes access. |
| **Q-2** | **What happens to retired-but-registered routes?** | `POST /v2/arc/<id>/unlock` documents itself as RETIRED. `GET /v2/explore/arc/<id>/best-presentation` and `GET /v2/coach/arc/<id>/best-presentation` survive although §7 retires Best Presentation. `/game` survives although §60 retires it. | §52 says remove rather than retain degraded paths; §55 says ambiguous ones need a founder call. Right now both rules point at the same routes and disagree about who decides. |
| **Q-3** | **May a coach own a document version?** | §40: *"The coach does not own or publish a competing full-document version"*; coach wording changes are proposals the Speaker accepts or rejects. But `PUT /v2/coach/arc/<id>/ideal-text` saves a coach one-block edit, `/approve` approves it, `/verify` snapshots and delivers it, `/publish-analysis` publishes a batch. | Either those routes are pre-contract legacy to re-shape into proposals, or §40 needs amending. Until decided, L1 and G-5 have a live exception nobody has named. |
| **Q-4** | **What does "V3 has run clean" mean?** | §24 defers removing V2 *"until V3 has run clean"* but sets no criterion — no window, no defect class, no owner. V3 has been the served policy since 2026-09-18. | Without a written bar, V2 removal is either indefinite or arbitrary. Both are drift. A criterion (e.g. *N consecutive days, zero V3 typed failures, coverage ladder met on Takes 1–3*) makes it a decision instead of a mood. |
| **Q-5** | **Is "recording progress toward the first audit" a commerce counter or a read on the speaker?** | `GET /v2/user/recording-progress`. | It is commerce eligibility today, but it is one rename or one UI treatment away from reading like a score (AC-9). A written framing now prevents an accidental fence breach later. |
| **Q-6** | **Is `/game` gone, or kept?** | §60 retires the generic Game, its routes and saved sessions, and explicitly forbids renaming it into Voice Album. The `/game` route still exists in the frontend. | Same shape as Q-2, but §60 is unusually explicit, so the surviving route is more likely an oversight than a deliberate retention. |
| **Q-7** | **What is the mechanism for founder copy sign-off?** | The LIVE LOOP fence requires sign-off for all user-facing copy. Coach-published feedback language (US-C-052), pooled questions (US-M-040) and Journal posts (US-M-060) all reach Speakers, and none has a recorded sign-off step. | A fence with no mechanism is enforced by memory. A lightweight recorded approval (a field, a review label, a CI probe on a copy manifest) turns it into something testable. |
| **Q-8** | **Should shared-password gates keep authoring user-facing content?** | The CMS is gated by `JOURNAL_ADMIN_PASSWORD` in the request body; dev-bugs by `DEV_BUGS_KEY`. Neither identifies a human, so G-10 cannot hold for anything authored through them — including the speaking-error library, which a Coach also edits through an identified gate (US-C-062 AC3). | Two gates over one library means the audit trail depends on which door was used. Moving the CMS behind `@require_admin` would make it uniform, at the cost of admin allowlist rows for anyone who writes posts. |
| **Q-9** | **The word "block" means two different things.** | §24a "block" = a Manager partition of ~75 words used for V3 selection. `/v2/explore/arc/<id>/blocks/*` "block" = an Ideal Text composition unit, which §11 says is really a **Paragraph**. | §11 exists precisely to stop alternative product names for a Paragraph. Two live meanings of one word in the same document is how a coverage rule gets implemented against the wrong unit. Naming one of them (e.g. *assessment block* vs *Paragraph*) costs a rename and prevents a class of bug. |

---

# Appendix A — Coverage map: every backend route → its story

Generated from the route tables of `backend-cursor` on 2026-09-20 by walking
every `@*.route(...)` and `@*.get/post/put/patch/delete(...)` registration.
**The point of this table is falsifiability:** if a route is not here, the
claim "every action is covered" is wrong, and a reader can check that in one
pass rather than trusting the prose.

Gate column reads the decorators actually on the handler. `public` means no
decorator: for `/v2/internal/journal/*` the gate is the password in the request
body, for `/api/dev-*` the `x-dev-key` header, for `/v2/internal/*` the
`X-Internal-Secret` header, and for the rest the route is genuinely public
(auth entry points, health, static, published Journal reads) or a hard-disabled
placeholder.

| Backend route | Methods | Gate | Story |
|---|---|---|---|
| `/auth/signup` | POST | public | US-S-001 |
| `/signup` | POST | public | US-S-001 |
| `/login` | POST | public | US-S-002 |
| `/reset-password` | POST | public | US-S-002 |
| `/user/consent` | GET PUT | `require_auth` | US-S-003 |
| `/user/mlc2-consent` | GET POST DELETE | `require_auth` | US-S-003 |
| `/user/sharing-consent` | GET PUT | `require_auth` | US-S-003 |
| `/projects` | POST | `optional_auth` (owner **or signed Guest ID**) | US-S-004 |
| `/projects/claim` | POST | `require_auth` | US-S-005 |
| `/metric-questions` | GET PATCH | `require_auth` | US-S-006 |
| `/profile` | GET | `require_auth` | US-S-006 |
| `/user/profile` | GET POST | `require_auth` | US-S-006 |
| `/explore/start` | POST | `require_auth` | US-S-010 |
| `/lab/presentation/extract` | POST | `optional_auth` (owner **or signed Guest ID**) | US-S-011 |
| `/explore/arc/<arc_id>/context-document` | GET POST | `require_auth` | US-S-012 |
| `/config/recording` | GET | `optional_auth` (owner **or signed Guest ID**) | US-S-013 |
| `/explore/arc/<arc_id>/setup` | GET | `require_auth` | US-S-013 |
| `/user/last-setup` | GET | `require_auth` | US-S-013 |
| `/lab/recordings` | POST | `optional_auth` (owner **or signed Guest ID**) | US-S-021 |
| `/user/sessions/<session_id>` | DELETE | `require_auth` | US-S-023 / US-S-121 |
| `/v2/jobs/<job_id>/status` | GET | `optional_auth` (owner **or signed Guest ID**) | US-S-030 |
| `/session/status` | GET | `require_auth` | US-S-030 (routing) |
| `/user/sessions/current` | GET | `require_auth` | US-S-030 (routing) |
| `/lab/recordings/<session_id>/retry-processing` | POST | `optional_auth` (owner **or signed Guest ID**) | US-S-031 |
| `/lab/recordings/<session_id>/readout` | GET | `optional_auth` (owner **or signed Guest ID**) | US-S-033 |
| `/explore/arc/<arc_id>/ideal-text` | GET | `require_auth` | US-S-040 |
| `/explore/arc/<arc_id>/ideal-text/core` | GET | `require_auth` | US-S-040 |
| `/explore/arc/<arc_id>/ideal-text/enrichment` | GET | `require_auth` | US-S-040 |
| `/explore/arc/<arc_id>/ideal-text/user-edit` | PUT | `require_auth` | US-S-042 |
| `/explore/arc/<arc_id>/ideal-text/notes` | PUT | `require_auth` | US-S-043 |
| `/explore/arc/<arc_id>/blocks/<int:block_key>/decide` | GET | `require_auth` | US-S-044 |
| `/explore/arc/<arc_id>/prior-take/decide` | POST | `require_auth` | US-S-044 |
| `/explore/arc/<arc_id>/blocks/<int:block_key>/select` | GET | `require_auth` | US-S-045 |
| `/explore/arc/<arc_id>/blocks/variants` | GET | `require_auth` | US-S-045 |
| `/explore/arc/<arc_id>/ideal-text/revisions` | GET | `require_auth` | US-S-046 |
| `/explore/arc/<arc_id>/ideal-text/revisions/<int:revision>` | GET | `require_auth` | US-S-046 |
| `/explore/arc/<arc_id>/ideal-text/save` | POST | `require_auth` | US-S-047 |
| `/user/sessions/<session_id>/transcript-edits` | PUT | `optional_auth` (owner **or signed Guest ID**) | US-S-048 |
| `/explore/arc/<arc_id>/moments` | GET | `require_auth` | US-S-050 |
| `/explore/arc/<arc_id>/moments/<moment_id>` | GET | `require_auth` | US-S-050 |
| `/explore/arc/<arc_id>/feedback` | GET | `require_auth` | US-S-050 / US-S-058 |
| `/user/snippets/<snippet_id>/confidence-agree` | GET | `require_auth` | US-S-052 |
| `/user/snippets/<snippet_id>/confidence-review` | POST | `require_auth` | US-S-052 |
| `/user/snippets/<snippet_id>/suggestion-feedback` | GET | `optional_auth` (owner **or signed Guest ID**) | US-S-053 |
| `/user/takes/<take_session_id>/feedback-response` | GET | `require_auth` | US-S-053 |
| `/explore/arc/<arc_id>/take-comparison` | GET | `require_auth` | US-S-058 |
| `/user/readouts` | GET | `require_auth` | US-S-058 / US-S-120 |
| `/user/sessions/<session_id>/readout` | GET | `require_auth` | US-S-058 / US-S-120 |
| `/explore/arc/<arc_id>/parts/<part_id>/lock` | PUT | `require_auth` | US-S-061 |
| `/explore/arc/<arc_id>/parts/<part_id>/root` | PUT | `require_auth` | US-S-063 |
| `/explore/arcs/<arc_id>/rooting-phrase-qualification` | GET | hard-disabled placeholder (404) | US-S-063 (disabled placeholder) |
| `/explore/arcs/<arc_id>/rooting-phrase-qualification/actions` | POST | hard-disabled placeholder (404) | US-S-063 (disabled placeholder) |
| `/explore/arc/<arc_id>/recording-roots` | GET | `require_auth` | US-S-064 |
| `/explore/arc/<arc_id>/best-presentation` | GET | `require_auth` | US-S-070 (Q-2) |
| `/explore/arc/<arc_id>/best-presentation/slides/<int:index>` | GET | `require_auth` | US-S-070 (Q-2) |
| `/user/confidence-practice/<practice_id>` | GET | `require_auth` | US-S-080 |
| `/user/confidence-practice/<practice_id>/attempts` | GET | `require_auth` | US-S-080 |
| `/user/confidence-practice/<practice_id>/complete` | GET | `require_auth` | US-S-080 |
| `/user/snippets/<snippet_id>/confidence-practice` | GET | `require_auth` | US-S-080 |
| `/user/mlc3/exercise-offers` | POST | `mlc3_service_required` + `require_auth` | US-S-082 |
| `/user/mlc3/exercise-offers/<offer_id>` | GET | `mlc3_service_required` + `require_auth` | US-S-082 |
| `/user/mlc3/exercise-offers/<offer_id>/events` | POST | `mlc3_service_required` + `require_auth` | US-S-082 |
| `/user/mlc3/exercise-offers/<offer_id>/playback` | GET | `mlc3_service_required` + `require_auth` | US-S-082 |
| `/user/mlc3/exercise-offers/<offer_id>/practice-sessions` | POST | `mlc3_service_required` + `require_auth` | US-S-082 |
| `/user/mlc3/feedback/render` | POST | `mlc3_service_required` + `require_auth` | US-S-082 |
| `/user/mlc3/feedback/respond` | POST | `mlc3_service_required` + `require_auth` | US-S-082 |
| `/user/mlc3/feedback/speaker` | POST | `mlc3_service_required` + `require_auth` | US-S-082 |
| `/user/mlc3/practice-attempts/<attempt_id>/playback` | GET | `mlc3_service_required` + `require_auth` | US-S-082 |
| `/user/mlc3/practice-attempts/<attempt_id>/speaker` | POST | `mlc3_service_required` + `require_auth` | US-S-082 |
| `/user/mlc3/practice-sessions/<session_id>` | GET | `mlc3_service_required` + `require_auth` | US-S-082 |
| `/user/mlc3/practice-sessions/<session_id>/attempts` | POST | `mlc3_service_required` + `require_auth` | US-S-082 |
| `/user/mlc3/practice-sessions/<session_id>/events` | POST | `mlc3_service_required` + `require_auth` | US-S-082 |
| `/user/mlc3/practice-sessions/<session_id>/preference` | POST | `mlc3_service_required` + `require_auth` | US-S-082 |
| `/explore/arcs/<project_id>/confident-moment-bundles` | GET | `_bundle_gate` + `mlc3_service_required` + `require_auth` | US-S-083 |
| `/user/confident-moment-bundles/<bundle_id>/render` | POST | `_bundle_gate` + `mlc3_service_required` + `require_auth` | US-S-083 |
| `/user/confident-moment-bundles/<bundle_id>/root-actions` | POST | `_coverage_gate` + `mlc3_service_required` + `require_auth` | US-S-083 |
| `/explore/arc/<arc_id>/voice-album` | GET | `require_auth` | US-S-090 |
| `/voice-album` | GET | `require_auth` | US-S-090 |
| `/voice-album/moment-history` | GET | `require_auth` | US-S-090 |
| `/voice-album/practice-answer` | POST | `require_auth` | US-S-091 |
| `/voice-album/practice-queue` | GET | `require_auth` | US-S-091 |
| `/voice-album/note` | POST | `require_auth` | US-S-092 |
| `/user/mlc3/guidance/<attachment_version_id>/events` | POST | `mlc3_service_required` + `require_auth` | US-S-103 |
| `/user/mlc3/guidance/<attachment_version_id>/playback` | GET | `mlc3_service_required` + `require_auth` | US-S-103 |
| `/user/mlc3/guidance/<membership_id>` | GET | `mlc3_service_required` + `require_auth` | US-S-103 |
| `/user/audits` | GET | `require_auth` | US-S-104 |
| `/user/recording-progress` | GET | `require_auth` | US-S-104 |
| `/v2/tokens/arc/<arc_id>` | GET | `require_auth` | US-S-110 |
| `/v2/tokens/balance` | GET | `require_auth` | US-S-110 |
| `/v2/tokens/history` | GET | `require_auth` | US-S-110 |
| `/v2/tokens/recording-band` | GET | `require_auth` | US-S-110 |
| `/v2/tokens/checkout` | POST | `require_auth` | US-S-111 (Q-1) |
| `/v2/tokens/portal` | POST | `require_auth` | US-S-111 (Q-1) |
| `/v2/tokens/prices` | GET | `require_auth` | US-S-111 (Q-1) |
| `/arc/<arc_id>/checkout` | POST | `require_auth` | US-S-113 (Q-2) |
| `/arc/<arc_id>/redeem` | POST | `require_auth` | US-S-113 (Q-2) |
| `/arc/<arc_id>/unlock` | POST | `require_auth` | US-S-113 (Q-2) |
| `/arc/<arc_id>/unlock-moments` | POST | `require_auth` | US-S-113 (Q-2) |
| `/<recording_id>` | GET | `require_auth` | US-S-120 |
| `/<recording_id>/playback-url` | GET | `require_auth` | US-S-120 |
| `/arc/<arc_id>/snippet-library` | GET | `require_auth` | US-S-120 |
| `/user/trainings` | GET | `require_auth` | US-S-120 |
| `/recordings` | GET | `require_admin` + `require_auth` | US-S-120 / US-M-030 |
| `/user/presentations/<presentation_id>` | DELETE | `require_auth` | US-S-121 |
| `/processing-authorization/data-export` | GET | `optional_auth` (owner **or signed Guest ID**) | US-S-122 |
| `/processing-authorization/data-rights` | POST | `optional_auth` (owner **or signed Guest ID**) | US-S-122 |
| `/processing-authorization/deletion/<purge_id>` | GET | `optional_auth` (owner **or signed Guest ID**) | US-S-122 |
| `/processing-authorization/terminate` | POST | `optional_auth` (owner **or signed Guest ID**) | US-S-122 |
| `/processing-authorization` | GET POST | `optional_auth` (owner **or signed Guest ID**) | US-S-123 |
| `/processing-authorization/ai-rendered` | POST | `optional_auth` (owner **or signed Guest ID**) | US-S-123 |
| `/processing-authorization/principal` | POST | `optional_auth` (owner **or signed Guest ID**) | US-S-123 |
| `/public/unsubscribe` | POST | public | US-S-124 |
| `/user/lounge/messages` | GET POST DELETE | `require_auth` | US-S-130 |
| `/explore/arc/<arc_id>/journey/next-steps` | POST | `require_auth` | US-S-131 |
| `/explore/arc/<arc_id>/progress` | GET | `optional_auth` (owner **or signed Guest ID**) | US-S-131 |
| `/chat/query` | POST | `optional_auth` (owner **or signed Guest ID**) | US-S-132 |
| `/chat/session-state` | GET | `require_auth` | US-S-132 |
| `/coaching/turn` | POST | `require_auth` | US-S-132 |
| `/learning-exposures/ack` | POST | `require_auth` | US-S-133 |
| `/user/product-discoveries` | GET | `require_auth` | US-S-133 |
| `/v2/journal/posts` | GET | public | US-S-140 |
| `/v2/journal/posts/<slug>` | GET | public | US-S-140 |
| `/v2/life/board` | POST | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/cases` | GET POST | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/cases/<case_id>` | GET PATCH | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/consent` | POST | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/copy` | GET PUT | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/data` | DELETE | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/day` | GET | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/day/<day_id>` | PATCH | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/export` | POST | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/goals` | GET | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/items` | GET POST | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/items/<item_id>` | PATCH DELETE | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/lookup` | GET | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/month` | GET POST | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/notes` | GET POST | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/principles` | GET | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/principles/<item_id>` | GET | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/principles/<item_id>/retire` | POST | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/proposals` | GET | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/proposals/<proposal_id>/approve` | POST | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/proposals/<proposal_id>/dismiss` | POST | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/quarter` | GET POST | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/reminders` | GET PUT | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/reminders/public-key` | GET | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/reminders/subscription` | POST DELETE | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/setup` | GET PUT | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/setup/apply-proposed` | POST | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/setup/complete` | POST | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/setup/document` | POST | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/setup/documents` | GET | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/setup/propose-from-document` | POST | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/state` | GET | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/strategy` | GET | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/strategy/download` | GET | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/strategy/upload` | POST | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/timeline` | GET | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/week` | GET POST | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/v2/life/wins/derive` | POST | `life_route` (= `require_auth` + enabled/allowlist/consent) | US-S-142 |
| `/coach/queue` | GET | `require_admin_or_coach` | US-C-010 |
| `/coach/sessions/<session_id>` | GET | `require_admin_or_coach` | US-C-011 |
| `/coach/sessions/<session_id>/snippets/<snippet_id>` | POST | `require_admin_or_coach` | US-C-020 |
| `/coach/sessions/<session_id>/save-feedback` | POST | `require_admin_or_coach` | US-C-021 |
| `/coach/arc/<arc_id>/review-state` | GET | `require_admin_or_coach` | US-C-022 |
| `/coach/arc/<arc_id>/publish-analysis` | POST | `require_admin_or_coach` | US-C-023 |
| `/coach/snippets/<snippet_id>/confidence-label` | PUT | `require_admin_or_coach` | US-C-030 |
| `/coach/sessions/<session_id>/confidence-queue` | GET | `require_admin_or_coach` | US-C-031 |
| `/coach/snippets/<snippet_id>/slide` | PUT | `require_admin_or_coach` | US-C-040 |
| `/coach/sessions/<session_id>/recut` | POST | `require_admin_or_coach` | US-C-041 |
| `/coach/sessions/<session_id>/slide-alignment` | GET | `require_admin_or_coach` | US-C-042 |
| `/coach/sessions/<session_id>/language` | PUT | `require_admin_or_coach` | US-C-043 |
| `/coach/snippets/<snippet_id>/star-verdict` | PUT | `require_admin_or_coach` | US-C-050 |
| `/coach/snippets/<snippet_id>/say-it-stronger` | PUT | `require_admin_or_coach` | US-C-051 |
| `/coach/snippets/<snippet_id>/star-text` | PUT | `require_admin_or_coach` | US-C-051 |
| `/coach/arc/<arc_id>/best-presentation` | GET | `require_admin_or_coach` | US-C-060 (Q-3) |
| `/coach/arc/<arc_id>/ideal-text` | GET PUT | `require_admin_or_coach` | US-C-060 (Q-3) |
| `/coach/arc/<arc_id>/ideal-text/approve` | POST | `require_admin_or_coach` | US-C-061 (Q-3) |
| `/coach/arc/<arc_id>/verify` | POST | `require_admin_or_coach` | US-C-061 (Q-3) |
| `/coach/arc/<arc_id>/stars` | GET | `require_admin_or_coach` | US-C-062 |
| `/coach/snippets/<snippet_id>/reference` | PUT | `require_admin_or_coach` | US-C-063 |
| `/coach/arcs/<arc_id>/ab-pairs` | GET | `require_admin_or_coach` | US-C-070 |
| `/coach/arcs/<arc_id>/ab-verdict` | PUT | `require_admin_or_coach` | US-C-070 |
| `/coach/guidance/attachments` | POST | `require_admin_or_coach` | US-C-080 |
| `/coach/guidance/batches/<arc_id>` | GET | `require_admin_or_coach` | US-C-080 |
| `/coach/guidance/events` | POST | `require_admin_or_coach` | US-C-080 |
| `/coach/guidance/publications` | POST | `require_admin_or_coach` | US-C-080 |
| `/coach/guidance/exercise-drafts` | POST | `require_admin_or_coach` | US-C-081 |
| `/coach/guidance/exercise-drafts/<draft_id>/playback` | GET | `require_admin_or_coach` | US-C-081 |
| `/coach/mlc3/inline/assignments/<assignment_id>/judgments` | POST | `require_admin_or_coach` | US-C-090 |
| `/coach/mlc3/inline/assignments/<assignment_id>/render` | POST | `require_admin_or_coach` | US-C-090 |
| `/coach/mlc3/reviews/<project_id>` | GET | `require_admin_or_coach` | US-C-090 |
| `/coach/mlc3/reviews/<review_set_id>/complete` | POST | `require_admin_or_coach` | US-C-090 |
| `/coach/mlc3/reviews/assignments/<assignment_id>/judgments` | POST | `require_admin_or_coach` | US-C-090 |
| `/coach/mlc3/reviews/assignments/<assignment_id>/render` | POST | `require_admin_or_coach` | US-C-090 |
| `/coach/mlc3/reviews/playback/<playback_reference_id>` | GET | `require_admin_or_coach` | US-C-090 |
| `/coach/mlc3/source-playback/<assignment_id>` | GET | `require_admin_or_coach` | US-C-090 |
| `/coach/students` | GET | `require_admin_or_coach` | US-C-100 |
| `/coach/students/<user_id>` | GET | `require_admin_or_coach` | US-C-100 |
| `/coach/students/<user_id>/audit` | GET | `require_admin_or_coach` | US-C-101 |
| `/coach/students/<user_id>/audit-data` | GET | `require_admin_or_coach` | US-C-101 |
| `/coach/students/<user_id>/audit/send` | POST | `require_admin_or_coach` | US-C-101 |
| `/coach/training-imports` | GET POST | `require_admin_or_coach` | US-C-110 |
| `/coach/training-imports/<session_id>` | GET DELETE | `require_admin_or_coach` | US-C-110 |
| `/coach/training-imports/<session_id>/restore` | GET | `require_admin_or_coach` | US-C-110 |
| `/coach/speaking-errors` | GET POST | `require_admin_or_coach` | US-C-120 |
| `/coach/sessions/<session_id>/video` | POST | `require_admin_or_coach` | US-C-130 |
| `/admin/health` | GET | `require_admin` | US-M-001 |
| `/admin/health/dad-jokes` | GET | `require_admin` | US-M-001 |
| `/v2/admin/whoami` | GET | `require_admin` | US-M-001 |
| `/admin/users` | GET | `require_admin` | US-M-010 |
| `/v2/admin/tokens/grant` | POST | `require_admin` | US-M-020 |
| `/v2/admin/tokens/lookup` | GET | `require_admin` | US-M-020 |
| `/admin/review-queue` | GET | `require_admin` | US-M-030 |
| `/admin/sessions/<session_id>` | GET | `require_admin` | US-M-030 |
| `/admin/sessions/<session_id>/readout` | GET | `require_admin` | US-M-030 |
| `/internal/whisper-health` | GET | `X-Internal-Secret` header | US-M-031 |
| `/v2/internal/jobs/health` | GET | `X-Internal-Secret` header | US-M-031 |
| `/v2/internal/jobs/sweep` | POST | `X-Internal-Secret` header | US-M-031 |
| `/internal/publish-session-results` | POST | `require_admin_or_coach` | US-M-032 |
| `/admin/question-pool` | GET POST | `require_admin` | US-M-040 |
| `/admin/question-pool/<question_id>` | PATCH DELETE | `require_admin` | US-M-040 |
| `/v2/admin/ceo/artifacts/<artifact_id>` | PATCH | `require_admin` | US-M-051 |
| `/v2/admin/ceo/bootstrap` | GET | `require_admin` | US-M-051 |
| `/v2/admin/ceo/bugs` | GET POST | `require_admin` | US-M-052 |
| `/v2/admin/ceo/bugs/<bug_id>` | PATCH DELETE | `require_admin` | US-M-052 |
| `/v2/admin/ceo/bugs/<bug_id>/retry` | POST | `require_admin` | US-M-052 |
| `/v2/admin/ceo/tasks` | GET POST | `require_admin` | US-M-052 |
| `/v2/admin/ceo/tasks/<task_id>/archive` | POST | `require_admin` | US-M-052 |
| `/v2/admin/ceo/tasks/<task_id>/done` | POST | `require_admin` | US-M-052 |
| `/v2/admin/ceo/tasks/<task_id>/restore` | POST | `require_admin` | US-M-052 |
| `/v2/admin/ceo/tasks/export` | GET | `require_admin` | US-M-052 |
| `/api/dev-bugs` | GET POST | `x-dev-key` header (`DEV_BUGS_KEY`) | US-M-053 |
| `/api/dev-bugs/<int:bug_id>` | PATCH DELETE | `x-dev-key` header (`DEV_BUGS_KEY`) | US-M-053 |
| `/api/dev-bugs/send` | POST | `x-dev-key` header (`DEV_BUGS_KEY`) | US-M-053 |
| `/api/dev-tasks` | GET | `x-dev-key` header (`DEV_BUGS_KEY`) | US-M-053 |
| `/api/dev-tasks/<int:task_id>` | PATCH DELETE | `x-dev-key` header (`DEV_BUGS_KEY`) | US-M-053 |
| `/api/dev-tasks/<int:task_id>/done` | POST | `x-dev-key` header (`DEV_BUGS_KEY`) | US-M-053 |
| `/api/dev-tasks/<int:task_id>/reorder` | POST | `x-dev-key` header (`DEV_BUGS_KEY`) | US-M-053 |
| `/api/dev-tasks/<int:task_id>/restore` | POST | `x-dev-key` header (`DEV_BUGS_KEY`) | US-M-053 |
| `/api/dev-tasks/export` | GET | `x-dev-key` header (`DEV_BUGS_KEY`) | US-M-053 |
| `/dev-bugs` | GET | public | US-M-053 |
| `/dev-bugs/` | GET | public | US-M-053 |
| `/dev-bugs/icons/<name>` | GET | public | US-M-053 |
| `/dev-bugs/manifest.webmanifest` | GET | public | US-M-053 |
| `/v2/internal/journal/posts/create` | POST | password in body (`JOURNAL_ADMIN_PASSWORD`) | US-M-060 |
| `/v2/internal/journal/posts/delete` | POST | password in body (`JOURNAL_ADMIN_PASSWORD`) | US-M-060 |
| `/v2/internal/journal/posts/get` | POST | password in body (`JOURNAL_ADMIN_PASSWORD`) | US-M-060 |
| `/v2/internal/journal/posts/list` | POST | password in body (`JOURNAL_ADMIN_PASSWORD`) | US-M-060 |
| `/v2/internal/journal/posts/publish` | POST | password in body (`JOURNAL_ADMIN_PASSWORD`) | US-M-060 |
| `/v2/internal/journal/posts/unpublish` | POST | password in body (`JOURNAL_ADMIN_PASSWORD`) | US-M-060 |
| `/v2/internal/journal/posts/update` | POST | password in body (`JOURNAL_ADMIN_PASSWORD`) | US-M-060 |
| `/v2/internal/journal/reorder` | POST | password in body (`JOURNAL_ADMIN_PASSWORD`) | US-M-060 |
| `/v2/internal/journal/image/delete` | POST | password in body (`JOURNAL_ADMIN_PASSWORD`) | US-M-061 |
| `/v2/internal/journal/image/generate` | POST | password in body (`JOURNAL_ADMIN_PASSWORD`) | US-M-061 |
| `/v2/internal/journal/image/list` | POST | password in body (`JOURNAL_ADMIN_PASSWORD`) | US-M-061 |
| `/v2/internal/journal/image/select` | POST | password in body (`JOURNAL_ADMIN_PASSWORD`) | US-M-061 |
| `/v2/internal/journal/media/presign` | POST | password in body (`JOURNAL_ADMIN_PASSWORD`) | US-M-061 |
| `/v2/internal/journal/community/delete` | POST | password in body (`JOURNAL_ADMIN_PASSWORD`) | US-M-062 |
| `/v2/internal/journal/community/generate` | POST | password in body (`JOURNAL_ADMIN_PASSWORD`) | US-M-062 |
| `/v2/internal/journal/community/list` | POST | password in body (`JOURNAL_ADMIN_PASSWORD`) | US-M-062 |
| `/v2/internal/journal/community/update` | POST | password in body (`JOURNAL_ADMIN_PASSWORD`) | US-M-062 |
| `/v2/internal/journal/diagnostic-exercises/list` | GET | password in body (`JOURNAL_ADMIN_PASSWORD`) | US-M-062 |
| `/v2/internal/journal/diagnostic-exercises/save` | GET | password in body (`JOURNAL_ADMIN_PASSWORD`) | US-M-062 |
| `/v2/internal/journal/speaking-errors/list` | GET | password in body (`JOURNAL_ADMIN_PASSWORD`) | US-M-062 |
| `/v2/internal/journal/speaking-errors/save` | GET | password in body (`JOURNAL_ADMIN_PASSWORD`) | US-M-062 |
| `/v2/internal/stripe/webhook` | POST | `Stripe-Signature` | US-M-070 |
| `/v2/internal/student-credits/increment` | POST | `X-Internal-Secret` header | US-M-070 |
| `/v2/internal/annotation-export` | POST | `X-Internal-Secret` header | US-M-071 |
| `/v2/internal/copilot-video/retrain` | POST | `X-Internal-Secret` header | US-M-071 |
| `/v2/internal/drift/run` | POST | `X-Internal-Secret` header | US-M-071 |
| `/v2/internal/life/reminders` | GET | `X-Internal-Secret` header | US-M-071 |
| `/` | GET | public | infrastructure (no story) |
| `/api/health` | GET | public | infrastructure (no story) |
| `/health` | GET | public | infrastructure (no story) |
| `/health/` | GET | public | infrastructure (no story) |
| `/health/jwks` | GET | public | infrastructure (no story) |
| `/static/<path:filename>` | GET | public | infrastructure (no story) |

**278 distinct backend routes**, 304 route+method pairs, mapped onto the stories above with **0 unmapped**. (The document defines 138 stories in total; the rest describe frontend-only actions — recording gestures, locks, bookmarks, Presentation Mode — that have no route of their own.)

---

# Appendix B — Coverage map: every frontend page → its story

`frontend-cursor` App Router pages. Route groups (`(auth)`, `(protected)`) are
stripped, since they do not appear in the URL.

| Frontend route | Story |
|---|---|
| `/` | US-S-004 · US-S-141 |
| `/about` | US-S-141 |
| `/account/data-consent` | US-S-003 · US-S-122 |
| `/admin/ceo` | US-M-050 … US-M-052 |
| `/admin/tokens` | US-M-020 |
| `/admin/users` | US-M-010 |
| `/audits` | US-S-104 |
| `/auth/oauth-complete` | US-S-002 |
| `/blog` | US-S-140 |
| `/blog/[slug]` | US-S-140 |
| `/change-password` | US-S-002 |
| `/chat` | US-S-130 · US-S-132 · US-C-010 · US-C-011 |
| `/cms` | US-M-060 … US-M-062 |
| `/cms/new/[[...path]]` | US-M-060 … US-M-062 |
| `/coach/audit/[studentId]` | US-C-101 |
| `/coach/compare` | US-C-070 |
| `/coach/corpus` | US-C-110 · US-C-111 |
| `/coach/corpus/summary/[sessionId]` | US-C-110 · US-C-111 |
| `/coach/errors` | US-C-120 |
| `/coach/willab` | US-C-010 (retired redirect) |
| `/coach/willab/[sessionId]` | US-C-010 (retired redirect) |
| `/dashboard` | US-S-013 · US-S-131 |
| `/dashboard/pricing` | US-S-111 |
| `/dashboard/v2` | US-S-013 · US-S-131 |
| `/dev/corpus` | US-S-143 |
| `/dev/deck` | US-S-143 |
| `/dev/life-bets` | US-S-143 |
| `/dev/marked-editor` | US-S-143 |
| `/dev/recording` | US-S-143 |
| `/dev/speaking-errors` | US-S-143 |
| `/dev/star-verdicts` | US-S-143 |
| `/logged-out` | US-S-002 |
| `/login` | US-S-002 |
| `/panel` | US-S-142 |
| `/panel/data` | US-S-142 |
| `/panel/distractions` | US-S-142 |
| `/panel/goals` | US-S-142 |
| `/panel/phrases` | US-S-142 |
| `/panel/principles` | US-S-142 |
| `/panel/principles/[id]` | US-S-142 |
| `/panel/setup` | US-S-142 |
| `/panel/strategy` | US-S-142 |
| `/panel/timeline` | US-S-142 |
| `/panel/today` | US-S-142 |
| `/panel/week` | US-S-142 |
| `/panel/wins` | US-S-142 |
| `/privacy` | US-S-141 |
| `/profile` | US-S-006 |
| `/recordings/[id]` | US-S-120 |
| `/recordings/[id]/feedback` | US-S-050 · US-S-058 |
| `/reset-password` | US-S-002 |
| `/signup` | US-S-001 |
| `/terms` | US-S-141 |
| `/unsubscribe` | US-S-124 |
| `/update-password` | US-S-002 |
| `/voice-album` | US-S-090 … US-S-094 |

**56 frontend pages mapped**, 0 unmapped.

The BFF proxy routes under `src/app/api/**/route.ts` are not listed separately:
each forwards to the backend route of the same name, so it is covered by the
same story as its target in Appendix A. The two exceptions are
`/api/auth/*` (session cookie handling for US-S-001/US-S-002) and
`/api/results/state` + `/api/session/status` (client polling for US-S-030).

---

# Appendix C — What this document deliberately does not do

- **It does not schedule work.** A tier tag says where a story sits relative to
  F1; it is not a backlog priority. Under the decision filter, scaffolding
  passes only as the named unblocker of an in-flight F1/F2 task.
- **It does not approve copy.** Strings shown here are either already fixed by
  the contract or illustrative. Everything that reaches a Speaker still needs
  founder sign-off (LIVE LOOP).
- **It does not resolve the nine conflicts in §D.11.** §55 makes each an
  individual founder decision. Guessing one here would be exactly the silent
  drift the filter exists to stop.
- **It does not replace the contract.** Where this file and
  `CANONICAL_PRODUCT_CONTRACT.md` disagree, the contract wins and this file is
  the thing that is wrong.
