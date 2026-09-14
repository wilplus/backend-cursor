# Audit decisions — founder answers to the 2026-09-13 questions — 2026-09-14

*Answers to [`2026-09-13-audit-questions.md`](2026-09-13-audit-questions.md),
given in chat on 2026-09-14. This file is the decision log; every task that
follows from it carries the question id and its own `FILTER:` stamp.*

## Answers

| Id | Question | Answer | Meaning |
|---|---|---|---|
| Q-T1 ★ | Tests that are 100% skipped | **a** | delete the 105 skipped-forever cases and `services/training_import.py`; keep the existing fences |
| Q-T2 ★ | Eight `tests/*_postgres.py` rehearsal suites | **a** | move to `tests/integration/`, documented run target + DSN, run on demand before any MLC-3 release. Not deleted: they are the only tests of `first_client_repository.py` and the MLC-3 storage paths, and they are the 110 tests that verified migration 0327 before it shipped |
| Q-T3 | Stale CI quarantine list | **a** | drop the four phantom `--ignore` entries; move `test_sentry.py`, `test_jwt_verify.py`, `test_auth_request.py` out of the test tree (delete or `scripts/`); `test_local_ci_mirror.py` asserts every ignored file exists |
| Q-T4 | `services/best_presentation.py` | **a** | live selection engine under a retired name: rename the module, delete the route, the FE overlay, the client and the BFF route, keep the tests under the new name |
| Q-T5 | Speaker sex on the frontend | **a** | delete the four prompt components, the mount gate, the field plumbing and both tests; the column stays audit-only |
| Q-T6 | `e2e/deck.spec.mjs` | **a** | add it to the CI `e2e` job |
| Q-T7 | End-to-end check of the record flow | **a** | a stubbed backend mode for the BFF (fixture server) so `record-flow.spec.mjs` runs in CI |
| Q-T8 | Component tests for F1 surfaces | **a** | yes, F1 surfaces only: render with fixture payloads, assert no score text, assert the three Feedback lanes |
| Q-T9 | Test naming | **a** | rename by subject, merge tiny modules, move everything under `tests/`; one mechanical PR per repo |
| Q-T10 | Shared fake-DB fixture | **a** | mandatory; migrate as tests are touched; delete the `sys.modules` pre-seeds now; one shared `vi.mock` for `auth-client` on the FE |
| Q-T11 | Slow fence tests | **a** | keep the grep fences, cache the file walk in a session fixture; librosa test behind a marker, CI only |
| Q-T12 | Coverage gate | **a** | per-file floor on the named F1 modules only; no global number |
| Q-C1 ★ | Degradation policy, Ideal Text read path | **a** | every stage succeeds or returns a typed `degraded` marker the FE can show; never a silently shorter payload |
| Q-C2 ★ | Typed records at the Manager/V3 boundary | **b** | leave as dicts; the tests cover it |
| Q-C3 | Routes containing logic | **a** | rule: validate, authorise, one service call, serialise; fence test on `routes/` function size and DB calls |
| Q-C4 | Lab state machine location | **a** | move transitions into `useWillabFlow` (or a reducer). **Sequenced after Q-T7 and Q-T8**: no refactor of the record flow without a component or e2e net |
| Q-C5 | `DeckChunkModal` / `TranscriptReviewDeck` props | **a** | one `ChunkState` per chunk computed in `lib/willab/deckChunks.ts`, passed as one prop |
| Q-C6 | `IdealTextOverlay` + `IdealTextReadout` | **b** | keep both; extract the three cloned handlers into `lib/willab/` and test them. Merging two untested 1,255-line components is not on the table until they have tests |
| Q-C7 | Complexity gate | **a** | ratchet: fail CI above baseline CC or above 25 for new functions; baseline file checked in |
| Q-A1 ★ | `services/db.py` | **a** | delete the 106 uncalled methods now; then carve the F1 tables into repository modules on the `feedback_repository` idiom |
| Q-A2 ★ | One data-access idiom | **a** | repositories take an injected client; `db.py` shrinks toward it; only `services/db.py` constructs a client |
| Q-A3 ★ | `routes/v2_routes.py` façade | **a** | delete it after pointing the tests at the domain modules |
| Q-A4 ★ | One LLM client | **a** | one `services/llm` entry with timeouts, usage accounting and the prompt registry; `openai_service` becomes transcription-only and gets tests; direct call sites migrate one at a time; fence test forbids `openai.OpenAI(` outside one module. **Founder-set starting point** |
| Q-A5 | Config reads | **a** | delete the 14 dead attributes (and the 4 test-only ones with their tests); F1-module env reads move to `Config`; fence: `os.environ` only in `config.py` and `services/secrets.py` |
| Q-A6 | `services/skills/` | **a** | delete the two zero-importer modules now; `services/skills/` once the intent lookup is a plain enum; then a fenced copy sweep |
| Q-A7 | 60 uncalled routes | per group | see below |
| Q-A8 | BFF idiom | **a** | `callBackend`; migrate the 81 direct-fetch routes by domain batch; fold multipart into `backend.ts`; delete `bff.ts` |
| Q-A9 | Homework cluster (FE) | **a** | delete after removing the `Lounge.tsx` import |
| Q-A10 | Repo hygiene | **a** | video out of HEAD (or history), handoffs to `docs/handoffs/` with an index, dev tools to `devDependencies`, delete the 7 orphan scripts |
| Q-A11 | mypy ratchet | **a** | fix `lab_recording` and `slide_word_split` first; Q-A1 and Q-A4 shrink the `db.py` and `openai_service` entries |
| Q-A12 | Dev harness pages in the production tree | **a** | acceptable; one line in `e2e/README.md` |

## Q-A7 — routes with no frontend caller, per group

Rule: **keep only if someone names the caller.** Anything still unnamed
after the sweep converts to delete. Group 2 stays regardless.

| Group | Routes | Answer |
|---|---|---|
| 1 | 20 of 21 routes in `routes/v2/admin.py` | **a** keep and name the caller in a comment; unnamed after the sweep → delete |
| 2 | all 7 `/v2/processing-authorization/*` | **a** keep regardless: the Phase-1 authorization seam; no FE caller is expected and deleting them would breach the boundary |
| 3 | `/v2/explore/start`, `/v2/arc/<id>/checkout`, `redeem`, `unlock`, `unlock-moments`, `snippet-library` | **a** keep and name the caller; unnamed → delete |
| 4 | `/v2/tokens/balance`, `recording-band`, `history` | **a** keep and name the caller; unnamed → delete |
| 5 | `/v2/onboarding/opener/start`, `next` | **b** delete |
| 6 | `/v2/user/chat/first-question`, `/v2/user/coaching/self-rating` | **b** delete |
| 7 | `/v2/user/consent` | **a** keep: Phase-1 authorization adjacent; never delete consent blind |
| 7 | `/v2/user/kpi/timeline`, `/v2/user/results/<id>` | **b** delete: live AC-9 hazards; removing an unused one is a fence win |
| 7 | `/v2/journal/categories` | **b** delete |
| 8 | `/v2/jobs/<id>/status`, `/v2/learning-exposures/ack`, `/v2/coach/annotation-uploads`, `/v2/coach/audits` | **a** keep and name the caller; unnamed → delete |
| 9 | `/api/admin/students*` aliases in `app.py` | **b** delete |

## Sequencing constraints (founder notes)

1. **Start with Q-A4.** `transcribe_audio` at 17.6% module coverage is F1
   piece (a), the load-bearing one. Everything else is cheaper to defer.
2. **Q-C6 before any merge:** extract the three cloned handlers, get tests
   on them, then revisit merging. Not before.
3. **Q-C4 after Q-T7 and Q-T8:** moving 116 setter calls into a reducer is
   right, but that is the record flow; no refactor without a net.
4. **Q-T2 is (a), not (c):** the rehearsal suites run as an opt-in tier.

## Proposed work order (derived; each item is its own filtered PR)

Backend
1. **Q-A4** tests on `transcribe_audio`; one LLM entry; `openai_service` → transcription-only; fence test; `life_engine.py` stops building its own client; direct call sites migrate one per PR.
2. **Q-T1 + Q-T3 + Q-T10 (pre-seeds)** pure deletes: 105 skipped cases, `training_import.py`, four phantom ignores, three script-tests, 42 `sys.modules` pre-seeds.
3. **Q-A1 step 1** delete the 106 uncalled `db.py` methods.
4. **Q-T2** opt-in integration tier for the eight rehearsal suites.
5. **Q-A3 + Q-T10** re-point tests at domain modules via `tests/fakes.py`; delete the façade.
6. **Q-T4 / Q-A6 / Q-A5** retired-name rename, `skills/` removal, config cleanup, each with its fence.
7. **Q-C1 + Q-C3** typed degradation markers, route fence; then split `_tracked_changes_block` and `_run_full_analysis_impl` by stage.
8. **Q-A1 step 2 + Q-A2** F1 tables into injected-client repositories.
9. **Q-A7** caller sweep; delete groups 5, 6, 9 and the three group-7 routes now; convert unnamed keeps after the sweep.
10. **Q-T9 / Q-T11 / Q-T12 / Q-A11 / Q-A10** naming, slow fences, F1 coverage floor, mypy F1 modules, hygiene.

Frontend
1. **Q-T6** `deck.spec.mjs` into CI.
2. **Q-T7** fixture backend for `record-flow.spec.mjs`.
3. **Q-T8** rendered tests for the F1 surfaces (AC-9 as behaviour, three lanes).
4. **Q-T5 / Q-T4 / Q-A9** speaker-sex, Best Presentation overlay, homework cluster deletions.
5. **Q-C6 (b)** extract and test the three cloned handlers.
6. **Q-C5** `ChunkState` for the deck.
7. **Q-C4** state machine into `useWillabFlow` (only after 2 and 3).
8. **Q-A8** BFF migration by domain batch; delete `bff.ts`.
9. **Q-C7 / Q-T10 / Q-T9 / Q-A10 / Q-A12** complexity ratchet, shared auth mock, naming, hygiene, README line.
