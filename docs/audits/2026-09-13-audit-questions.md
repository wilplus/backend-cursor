# Audit questions — decisions needed before cleanup — 2026-09-13

*These are the questions the 2026-09-13 engineering audit could not answer
from the code. Each one states the evidence, the options, and what changes
with the answer. ★ marks the questions that gate the most work: answer those
first. Backend report: [`2026-09-13-engineering-audit.md`](2026-09-13-engineering-audit.md).
Frontend report: `frontend-cursor/docs/audits/2026-09-13-engineering-audit.md`.*

Answer format that works: the question id, the option letter, one line of
reasoning if it is not the recommended one. Every answer becomes a filtered
task with its own `FILTER:` stamp.

---

## Part 1 — Tests

### ★ Q-T1. What is the rule for a test that is 100% skipped?

**Evidence.** `test_training_import.py` (62 cases, all skipped since Phase 1
disabled legacy imports), 34 of 40 cases in `test_voice_confidence.py`
("retired sex-routed contract retained as historical test text"), 9 in
`test_master_document.py` ("retired incumbent/challenger endpoint").
They cost nothing to run and protect nothing.

**Options.**
- (a) **Delete skipped-forever cases; keep a one-line fence test where the
  retirement matters** (recommended). The sex-routed fence already exists in
  `test_stress_snippets_retired.py` and `test_acoustic_targets_deleted.py`.
- (b) Keep them as "historical text" (status quo). Then the rule should be
  written down so nobody deletes them by accident.
- (c) Move them under `docs/` as prose, since that is what they are.

**Changes with the answer.** 105 skipped cases, and whether
`services/training_import.py` (0% coverage, disabled) is deleted with its
test.

### ★ Q-T2. The eight `tests/*_postgres.py` rehearsal suites: opt-in tier, or delete?

**Evidence.** 257 cases skip in every automated run because no
`*_REHEARSAL_DSN` is set. They are the only tests of
`first_client_repository.py` (1,118 lines, 15.7% coverage) and the MLC-3
storage paths. Their docstrings say "disposable".

**Options.**
- (a) **Move to `tests/integration/`, add a documented `make rehearse`
  target and a DSN, and run them on demand before any MLC-3 release**
  (recommended if MLC-3 is still going to ship).
- (b) Wire a throwaway Postgres into CI (the workflow header explains why
  this was rejected before: Supabase-specific SQL).
- (c) Delete them; they were "disposable".

**Changes with the answer.** Whether 257 cases and ~2,000 test lines stay,
and whether `first_client_repository.py` ever gets a gate.

### Q-T3. The CI quarantine list names four files that do not exist. Fix the list, and what happens to the two real ones?

**Evidence.** `tests.yml` and `local_ci.sh` ignore
`test_admin_student_profile_regressions.py`, `test_guest_funnel.py`,
`test_homework_regressions.py`, `test_score_unification.py` (all gone), plus
`test_sentry.py` (a print script, no test functions) and
`test_auth_request.py` (live network). `test_jwt_verify.py` is the same kind
of script and is not even quarantined. `test_local_ci_mirror.py` only checks that the two lists agree.

**Options.**
- (a) **Drop the four phantoms; delete `test_sentry.py`, `test_jwt_verify.py`
  and `test_auth_request.py` (or move them to `scripts/` as the manual checks
  they are)**
  (recommended). Add an assertion to `test_local_ci_mirror.py` that every
  ignored file exists.
- (b) Leave the list; it is harmless.

**Changes with the answer.** Small, but it decides whether the quarantine
mechanism means anything.

### Q-T4. Is `services/best_presentation.py` retired code or the live per-slide selection engine?

**Evidence.** L1 retires "Best Presentation as a separate product artifact".
The module (765 lines) is imported by 13 backend modules including
`ideal_text_block.py`, `analysis_worker.py`, `transcript_document.py`; 15
test files cover it at 87.6%; the `/v2/explore/arc/<id>/best-presentation`
route is live; the FE ships `BestPresentationOverlay.tsx` (476 lines,
untested) plus a client and a BFF route, referenced from `Lounge`,
`WillabSurface`, `LibraryOverlay`, `CoachIdealTextPanel`.

**Options.**
- (a) **The selection functions are live infrastructure under the wrong
  name: rename the module (e.g. `slide_selection.py`), delete the route,
  overlay, client and BFF route, keep the tests under the new name.**
- (b) It is fully retired: delete all of it and re-home the 13 importers.
- (c) It is a live surface and L1 means something narrower; say what.

**Changes with the answer.** ~1,500 lines across both repos, 15 backend
test files, 1 FE test file, and whether the word "best presentation"
survives in user-facing code.

### Q-T5. Speaker sex on the frontend: retire the surface or keep collecting the field?

**Evidence.** The backend has zero references (fence held). The FE still
ships four prompt components, the gate, the profile field in signup,
plan chips and the training corpus client, and two tests
(`userProfile.sex.test.ts`, `speakerSexAskGate.test.ts`). The
`userProfile.sex` test's own header says the backend uses it to "suppress
its acoustic fallback", which no longer exists.

**Options.**
- (a) **Delete the prompts, the gate, the field plumbing and both tests;
  keep the column audit-only** (recommended; matches the 2026-08-29 lock).
- (b) Keep the field for a non-processing purpose; name the purpose and the
  operational definition it traces to (CONSTRUCT fence).

**Changes with the answer.** ~600 FE lines, 2 tests, 15 files.

### Q-T6. `e2e/deck.spec.mjs` runs nowhere. Add it to CI or delete it?

**Evidence.** Founder spec 2026-08-11, pins the transcript-review deck
wiring in a real browser; not in the CI job or the README table.
`TranscriptReviewDeck.tsx` (953 lines, 24 props) has no other test.

**Options.**
- (a) **Add it to the `e2e` job next to `ideal-text-canonical`**
  (recommended; it is F1 surface).
- (b) Delete it if the deck harness no longer matches the surface.

### Q-T7. Does the core record flow need an automated end-to-end check?

**Evidence.** `e2e/record-flow.spec.mjs` is the only test of
record → Take from the user's side. It needs a live backend and runs by
hand. The bug it was written for ("I picked a project and nothing
happened") was invisible to every unit test.

**Options.**
- (a) **A stubbed backend mode for the BFF (`NEXT_PUBLIC_API_URL` pointing at
  a fixture server) so the spec can run in CI.** Cost: a fixture server.
- (b) Keep it manual; write down when it must be run (before any change to
  `Lounge`, `LabOverlay`, `useWillabFlow`, `useBackDismiss`).
- (c) Nothing.

### Q-T8. Should component tests exist at all?

**Evidence.** jsdom is installed; one `.test.tsx` exists (2 cases). Every
F1 surface component (`Lounge`, `LabOverlay`, `DeckChunkModal`,
`IdealTextReadout`, `IdealTextOverlay`, `ReportCard`, `RecordingSetup`)
is untested except through the five e2e harness pages. The AC-9 fence on
user surfaces is enforced by grepping source text
(`noStarsOnUserSurfaces.test.ts`).

**Options.**
- (a) **Yes, for the F1 surfaces only: render with fixture payloads, assert
  no number/score text appears, assert the three Feedback lanes render**
  (recommended; turns the AC-9 grep into a behavioural fence).
- (b) No; the e2e harnesses are the component tests. Then `deck.spec` must
  run (Q-T6) and the harness pages become load-bearing.

### Q-T9. Test naming: subject or delivery?

**Evidence.** Backend modules named `test_wave2_be`, `test_wave3_be`,
`test_wave4_*`, `test_step2_peer_review`, `test_mlc3_*_d4`; FE files named
`idealText.*.test.ts` ×12. 13 backend subjects have tests in both the repo
root and `tests/`. 19 backend and 13 FE test files have ≤3 cases.

**Options.**
- (a) **Rename by subject and merge the tiny modules into their subject's
  file; move everything under `tests/`** (recommended; mechanical, no
  behaviour change, one PR per repo).
- (b) Leave names; add a `# subject:` header line to each wave-named file.

### Q-T10. Should the fake-DB fixture be mandatory?

**Evidence.** 63 backend test modules define their own fake DB class; 42
pre-seed `sys.modules` placeholders that `conftest.py` makes unnecessary;
`tests/fakes.py` is used by 12. On the FE, `getAuthToken` is mocked in 21
files.

**Options.**
- (a) **Yes: migrate to `tests/fakes.py` module by module as tests are
  touched; delete the `sys.modules` pre-seeds now (conftest already covers
  them)** (recommended). FE: a shared `vi.mock` setup file for
  `auth-client`.
- (b) No; local fakes are fine.

**Changes with the answer.** Whether the `routes.v2_routes` façade can ever
be deleted (Q-A3), because the façade exists for those patch sites.

### Q-T11. Which slow fence tests may stay slow?

**Evidence.** 35 of 90 test seconds are five modules that grep the repo
(`test_session_globals_wiring` 11.6 s, `test_prompt_registry` 6.6 s,
`test_snippet_table_name` 6.3 s, `test_stress_snippets_retired` 5.7 s,
`test_snippet_value_resolution` 3.8 s) and one librosa test at 24.5 s
(`test_audio_metrics_features`, last touched 2026-06-04, subject moved
2026-08-06).

**Options.**
- (a) **Keep the grep fences, cache the file walk in a session fixture; move
  the librosa test behind a marker and run it in CI only** (recommended).
- (b) Leave as is; 2 minutes is fine.

### Q-T12. Coverage gate: yes or no, and on what?

**Evidence.** 56.4% overall; F1 services at 90–96%; `db.py` 20.5%,
`openai_service.py` 17.6%, `routes/v2/coaching.py` 22%, `routes/v2/admin.py`
16%. No gate exists.

**Options.**
- (a) **A per-file floor on the named F1 modules only (no drop below current),
  no global number** (recommended; a global number invites tests on
  scaffolding).
- (b) A global floor.
- (c) None.

---

## Part 2 — Complexity

### ★ Q-C1. What is the degradation policy for the Ideal Text read path?

**Evidence.** `_tracked_changes_block` (`routes/v2/explore_ideal_text.py`,
CC 185, 901 lines) has 15 `except Exception` blocks; `maybe_assemble_ideal_text`
has 5; `_run_full_analysis_impl` has 11. Each one turns a failure into a
partial payload with a log line. Splitting the function is mechanical once
the rule is known; without the rule, a refactor would either preserve 15
silent fallbacks or remove some without authority.

**Options.**
- (a) **"Every stage on the read path either succeeds or returns a typed
  `degraded` marker the FE can show; never a silently shorter payload."**
  Then each swallow-all becomes a named degradation and the function splits
  by stage.
- (b) "Fail the request on any stage failure" (simplest; changes user-visible
  behaviour under partial outages).
- (c) Keep swallow-alls; only extract stages (cosmetic).

**Changes with the answer.** How the two most complex functions in the repo
are refactored, and what the FE shows when a stage fails.

### ★ Q-C2. Typed records at the Manager / V3 boundary?

**Evidence.** `build_feedback_exposure_bundle` (CC 85, 50 dict `.get`),
`prepare_v3_service_inventory` (CC 74, 52 `.get`, 14 returns),
`_ideal_piece_provenance` (CC 65, 49 `.get`),
`current_take_confident_voice_candidate` (CC 52). These are pure, tested at
87–92%, and complex because every payload key is optional. `arbitrate`
(CC 57) by contrast is inherent policy and should stay as it is.

**Options.**
- (a) **Introduce dataclasses/TypedDicts for the Candidate, Evidence and
  Exposure records at the Manager boundary; the `.get` branches collapse to
  field access** (recommended; L2 unchanged, mypy starts catching shape
  errors).
- (b) Leave; the tests cover it.

### Q-C3. Are routes allowed to contain logic?

**Evidence.** Six of the 30 most complex backend functions are route
handlers or route-private helpers (`_tracked_changes_block`,
`v2_explore_get_ideal_text` 465 lines with 5 DB calls,
`v2_explore_put_ideal_user_edit`, `v2_coach_get_session`,
`v2_coach_confidence_queue`, `v2_post_take_feedback_response`). The August
god-file split moved them into domain files without moving them out of the
routes layer.

**Options.**
- (a) **Rule: a route validates, authorises, calls one service function,
  serialises. Enforce with a fence test that no `routes/` function exceeds
  N lines or calls `db.` more than once** (recommended; the fence is cheap,
  the migration is one function at a time).
- (b) No rule; refactor opportunistically.

### Q-C4. Where does the frontend's Lab state machine live?

**Evidence.** `LabOverlay.tsx` (1,834 lines, 13 `useEffect`, 116 state
setter calls) and `Lounge.tsx` (2,054 lines, 14 `useEffect`, 75 setters)
re-derive a state machine that `useWillabFlow.ts` already models as a
`WillabState` union.

**Options.**
- (a) **Move transitions into `useWillabFlow` (or a reducer); components
  render from state and dispatch events** (recommended; makes Q-T8 tests
  possible).
- (b) Leave; the surface works.

### Q-C5. `DeckChunkModal` (18 props, CC 121) and `TranscriptReviewDeck` (24 props): props-as-flags or a chunk model?

**Evidence.** The parent passes 18/24 props that the child branches on (63
and 47 ternaries). This is the per-slide transcript surface, piece (a) of
F1 on the user's side.

**Options.**
- (a) **One `ChunkState` object per chunk (status, lock, decision, edit
  affordances) computed once in `lib/willab/deckChunks.ts`, passed as one
  prop** (recommended; `deckChunks.ts` already has `groupChunksBySlide`, CC
  28, tested).
- (b) Leave.

### Q-C6. `IdealTextOverlay` and `IdealTextReadout`: one renderer or two surfaces?

**Evidence.** 1,255 and 1,283 lines, CC 52 and 32, three clone blocks
between them, both untested, both on the Ideal Text surface.

**Options.**
- (a) **One document renderer with an `edit`/`read` mode; the clones become
  one function each.**
- (b) They are different products (user edit vs. read-aloud); keep both, but
  extract the three cloned handlers into `lib/willab/`.

### Q-C7. Should complexity be gated?

**Evidence.** No `complexity` rule on the FE (`.eslintrc.json` is
`next/core-web-vitals` only); no `radon`/`xenon` step on the backend.
Nothing today would flag a new CC 121 function.

**Options.**
- (a) **Ratchet: fail CI on any function whose CC exceeds its current value
  or a threshold (say 25) for new functions; baseline file checked in**
  (recommended; same pattern as the BFF ratchet and the mypy ratchet).
- (b) Report only.
- (c) None.

---

## Part 3 — Abstractions and glue

### ★ Q-A1. `services/db.py`: split by domain, or keep one object and delete the dead methods?

**Evidence.** 18,724 lines, 582 methods, 135 importers, 106 methods with no
caller anywhere (2,152 lines), 20.5% coverage, MI 0, mypy-ignored. Tests
patch it by attribute name at ~360 sites, so every name is load-bearing for
the suite.

**Options.**
- (a) **Two steps: (1) delete the 106 uncalled methods now (verified: no
  caller in production, scripts, tests or `db.py` itself); (2) carve the F1
  tables (recordings, takes, paragraphs, ideal text, feedback) into
  repository modules on the `feedback_repository` idiom, leaving the rest in
  `db.py` until touched** (recommended; step 1 is a pure delete, step 2
  follows the idiom the newest F1 code already uses).
- (b) Delete dead methods only; never split.
- (c) Full split by domain in one go (weeks; every test that patches
  `v2.db.<method>` breaks).

**Changes with the answer.** The largest single cleanup in the repo and
whether the F1 data path ever gets a typed, testable seam.

### ★ Q-A2. One data-access idiom: which one?

**Evidence.** `feedback_repository.py`, `project_repository.py`,
`take_feedback_set.py` take a client and do not import `db`.
`first_client_repository.py` (1,118 lines) reaches `.client` 85 times.
`life_store.py` does both. `routes/auth.py` constructs its own Supabase
client three times.

**Options.**
- (a) **Repositories take an injected client (the `feedback_repository`
  shape); `db.py` shrinks toward it; no module constructs a client except
  `services/db.py`** (recommended; makes the fake-DB fixture one object).
- (b) Everything back onto `db.py`.

### ★ Q-A3. Delete the `routes/v2_routes.py` façade?

**Evidence.** 537 lines, no routes, exists so that 45 test modules can
import `routes.v2_routes` and 46 patch sites in 19 files can rebind names on
it. Also the most-churned file in the repo (519 commits) because it was the
god file.

**Options.**
- (a) **Yes: point the tests at the domain modules (`routes.v2.coach` etc.),
  then delete the façade and let `app.py` import the domain modules
  directly** (recommended; pure glue).
- (b) Keep it as the registration point only (drop the ~100 re-exports).

**Depends on.** Q-T10 (shared fakes) makes the test edits smaller.

### ★ Q-A4. One LLM client?

**Evidence.** Three layers (`openai_service` 13 importers, `services/llm` 25,
`llm_config` 27) plus 11 files calling `chat.completions.create` directly;
`life_engine.py` builds its own `openai.OpenAI` client. `transcribe_audio`
(F1 piece (a)) sits in the least-tested layer (17.6%).

**Options.**
- (a) **One `services/llm` entry with timeouts, usage accounting and the
  prompt registry; `openai_service` becomes transcription-only and gets
  tests; direct call sites migrate one at a time; a fence test forbids
  `openai.OpenAI(` outside one module** (recommended; the Phase-1
  authorisation boundary in `CLAUDE.md` already says "no direct provider
  clients").
- (b) Leave; add the fence test only.

### Q-A5. Config: one reader or many?

**Evidence.** 86 `os.environ` reads in 42 files outside `config.py`,
including `take_feedback_policy_v3.py` (5), `feedback_data_contract.py`
(3), `ideal_text_block.py` (2), `slide_word_split.py` (2). 18 `Config`
attributes are never read by production code (14 by nothing at all, 4 only
by tests or scripts), seven of them feature flags.

**Options.**
- (a) **Delete the 14 dead attributes (and the 4 test-only ones with their
  tests); move F1-module env reads to `Config`;
  fence test: `os.environ` only in `config.py` and `services/secrets.py`**
  (recommended; this is what CONFIG-FIRST assumes).
- (b) Delete dead attributes only.

### Q-A6. `services/skills/` (charisma, stress): delete, and what replaces the two imports?

**Evidence.** Retired 2026-08-13; 234 lines; no tests; imported by
`routes/v2/coaching.py` and `routes/v2/user_chat.py` (`get_skill`,
`resolve_for_snippet`). Two sibling modules (`charisma_snippet_service.py`,
`stress_snippet_service.py`) have zero importers. "charisma" appears in 54
production files, "stress" in 35, "challenge"/"threat" in 21/11 (mostly
prompt text and comments).

**Options.**
- (a) **Delete the two zero-importer modules now; delete `services/skills/`
  once the coaching state machine's intent lookup is replaced by a plain
  enum; then a copy sweep of the 54/35 files that a fence test keeps at
  zero** (recommended).
- (b) Keep `skills/` as the intent registry but rename the two skills to
  non-retired names.

### Q-A7. Which of the 60 uncalled backend routes are still products?

**Evidence.** `raw/routes_without_fe_caller.txt`. Standouts: 20 of 21 routes
in `routes/v2/admin.py` (question pool, directives queue, icebreaker, review
queue), all 7 `/v2/processing-authorization/*`, six arc routes
(`/explore/start`, `checkout`, `redeem`, `unlock`, `unlock-moments`,
`snippet-library`), `/v2/tokens/*`, `/v2/onboarding/opener/*`,
`/v2/user/chat/first-question`, `/v2/user/coaching/self-rating`,
`/v2/user/consent`, `/v2/user/kpi/timeline`, `/v2/journal/categories`,
`/api/admin/students*` aliases in `app.py`.

**Ask.** For each group: (a) called by something the FE audit cannot see
(curl, cron, an admin script) → keep and name the caller in a comment;
(b) retired → delete the route and its handler; (c) planned → keep behind a
flag. The `processing-authorization` group needs the Phase-1 owner's answer,
not a guess.

### Q-A8. Which BFF idiom wins, and by when?

**Evidence.** 59 routes on `callBackend`, 8 on `proxyJson`, 81 on direct
fetch (baseline 82). `proxyJson` is CC 47 and duplicates its error path
with `proxyMultipart`. Four catch-all proxies forward anything.

**Options.**
- (a) **`callBackend`; migrate the 81 by domain batch (the ratchet already
  tracks it), then fold the multipart case into `backend.ts` and delete
  `bff.ts`** (recommended).
- (b) Two idioms are fine; delete only `proxyJson`.

### Q-A9. The homework cluster: delete?

**Evidence.** `homework-client.ts` (574 lines), `types-homework.ts` (474,
two functions at CC 42/39), `homework-mock.ts`, `homework-task-fields.ts`;
only importer `Lounge.tsx`; 14 unused exports; the backend CI list still
names a deleted `test_homework_regressions.py`.

**Options.**
- (a) **Delete after removing the `Lounge.tsx` import** (recommended).
- (b) It is live; say which surface.

### Q-A10. Repo hygiene: is any of this deliberate?

**Evidence.** FE: `IMG_1681.mov` (83 MB) tracked; `cache/config.json`
tracked; 13 handoff `.md` at the root; `task-master-ai`, `typescript`,
`@types/*`, `tailwindcss`, `postcss`, `autoprefixer` in `dependencies`.
BE: 7 scripts with zero references; 213 files in `docs/` of which ~30 are
dated handoffs; `PHASE-A0-FINDINGS.md` at root.

**Options.**
- (a) **Remove the video from history (or at least from HEAD), move handoffs
  to `docs/handoffs/` with a one-line index, move dev tools to
  `devDependencies`, delete the 7 scripts** (recommended; no product
  behaviour).
- (b) Leave.

### Q-A11. mypy ratchet: is it allowed to shrink by deletion?

**Evidence.** 54 entries under `ignore_errors`, including F1 modules
`lab_recording` and `slide_word_split`, plus `db.py`, `openai_service`,
`best_presentation`, `routes.v2.user_chat`.

**Options.**
- (a) **Fix the two F1 modules first (they are small: 668 and 880 lines),
  then let Q-A1/Q-A4 remove `db.py` and `openai_service` entries by
  shrinking them** (recommended).
- (b) Leave the ratchet.

### Q-A12. Dev harness pages in the production tree: acceptable?

**Evidence.** Six `src/app/dev/*` routes ship in the production build,
each returning `null` under `NODE_ENV=production`. They are the e2e
harnesses.

**Options.**
- (a) Acceptable; add one line to `e2e/README.md` saying so.
- (b) Exclude them from the production build (Next.js `pageExtensions` or a
  `dev-only` directory outside `app/`).

---

## Suggested answer order

1. Q-T1, Q-T2, Q-A1, Q-A3, Q-T10 (they unlock each other: dead tests →
   shared fakes → façade deletion → `db.py` cleanup).
2. Q-C1, Q-C2, Q-C3 (the F1 read path and the Manager boundary).
3. Q-T4, Q-T5, Q-A6, Q-A9 (retired constructs; each is a delete once
   answered).
4. Q-A4, Q-A5, Q-A2 (the seams).
5. Q-T6, Q-T7, Q-T8, Q-C4, Q-C5, Q-C6 (the FE surfaces).
6. Everything else.
