# Engineering audit — backend (`backend-cursor`) — 2026-09-13

*Read-only audit, executed from the prompt in
[`2026-09-13-engineering-audit-prompt.md`](2026-09-13-engineering-audit-prompt.md).
Raw tool outputs are under [`raw/`](raw/). The founder's decision questions
are in [`2026-09-13-audit-questions.md`](2026-09-13-audit-questions.md).
The matching frontend report lives in `frontend-cursor/docs/audits/`.*

Commit audited: `4acaa2c` (2026-09-10). Run on Python 3.11.15 with
`requirements.txt` installed (CI pins 3.12.1; `pywebpush` could not be built
here, it is lazy-imported and nothing in the suite needed it).

---

## Executive summary

1. **The suite is green and fast, but 6.7% of it never runs.** 5,410 cases,
   5,048 pass, 0 fail, 362 skip, 2 min wall. 257 of the skips are eight
   `tests/*_postgres.py` "disposable rehearsal" modules gated on a DSN nobody
   sets in CI; 62 are a whole module (`test_training_import.py`) disabled by
   policy; 34 are retired sex-routed cases kept "as historical test text".
2. **The CI quarantine list is stale.** Four of the six `--ignore` entries in
   `tests.yml` and `scripts/local_ci.sh` name files that no longer exist.
3. **Coverage is bimodal.** The F1 services (`slide_word_split`,
   `ideal_text_block`, `ideal_text_parts`, `manager_engine`,
   `take_feedback_policy_v3`) sit at 90–96%. The two things every F1 request
   passes through, `services/db.py` (20.5%) and `services/openai_service.py`
   (17.6%), are the least tested large files in the repo.
4. **`services/db.py` is the structural problem.** 18,724 lines, 582 methods,
   135 importers, 106 methods with no caller anywhere (2,152 lines), 188
   functions graded C or worse, maintainability index 0.
5. **The routes layer is where the worst complexity lives.**
   `_tracked_changes_block` in `routes/v2/explore_ideal_text.py` is 901 lines,
   cyclomatic complexity 185, with 15 broad `except Exception` blocks and 13
   distinct DB calls. It is the single most complex function in either repo
   and it sits on the Ideal Text read path.
6. **Retired constructs are still executable code.** `services/skills/`
   (charisma, stress) is imported by two live routes; `best_presentation.py`
   is imported by 13 modules although L1 retires the artifact; "charisma"
   appears in 54 production files.
7. **Three ways to call the LLM, two ways to reach the database.**
   `openai_service`, `services/llm`, `services/llm_config`, plus 11 files
   that call the OpenAI client directly (one constructs its own client).
   `db.py` and four `*_repository` modules coexist with different idioms.
8. **Test infrastructure is duplicated 63 times.** 63 test modules define
   their own fake DB class; 42 pre-seed `sys.modules` placeholders that
   `conftest.py` was written to make unnecessary; only 12 use `tests/fakes.py`.
9. **Dead weight is measurable, not huge:** 7 scripts with zero references,
   `snippet_truncation.py` (825 lines, zero importers, 0% coverage), 18 config
   attributes no production code reads, 17 modules at 0% coverage, 54 modules parked under
   `mypy ignore_errors` (including F1 modules `lab_recording` and
   `slide_word_split`).

---

## Method and limitations

| What | How | Where |
|---|---|---|
| Test inventory, imports, skips | AST scan of 308 test modules | `raw/module_to_tests.json`, `raw/test_classification.md` |
| Test run | `pytest` with the CI placeholder env, coverage on | `raw/pytest_summary.txt`, `raw/coverage_by_file.txt` |
| Ages | `git log` per file after `--unshallow` (1,263 commits) | `raw/test_file_ages.txt`, `raw/source_file_ages.txt` |
| Complexity | `radon cc`, `radon mi` | `raw/radon_cc_top200.txt`, `raw/radon_mi.txt` |
| Dead code | `vulture --min-confidence 60`; grep-verified for `db.py` | `raw/vulture_min60.txt`, `raw/db_methods_no_caller.txt` |
| Duplication | `jscpd --min-lines 15 --min-tokens 100` | `raw/jscpd.txt` |
| Route reachability | Flask route table vs. every string in the frontend `src/` | `raw/routes_without_fe_caller.txt` |

Limitations. (1) Python 3.11 here, 3.12.1 in CI; nothing behaved differently
but it is not the pinned mirror. (2) The route-reachability check is a string
match; routes behind the four catch-all BFF proxies and routes called by cron
containers cannot be verified statically and are bucketed separately.
(3) `vulture` flags every Flask handler as "unused" (they are called by the
router), so its route-file numbers are false positives; only the `db.py`
numbers were re-verified by grep across the whole repo including tests.
(4) The eval probes (`tests/evals/`) need an OpenAI key and were not run.
(5) "Stale" means the subject module has a commit in a later month than the
test's last commit; it is a prompt to re-read, not proof of rot. The suite
passes, so no stale test is currently wrong.

---

## A. Test necessity

### A.1 Inventory

| | |
|---|---|
| Test modules | 308 (235 at repo root, 73 under `tests/`) |
| Test functions | 5,245 in 84,652 lines (68% of the size of the production code) |
| Style | 212 `unittest.TestCase`, 92 pytest-style, 4 mixed |
| Run (this audit) | 5,410 cases: 5,048 pass, 362 skip, 0 fail, 121 s wall |
| Coverage | 56.4% of 46,558 statements |
| Tiers (see table) | 130 F1-path, 64 fence, 59 F2, 52 scaffolding, 3 retired |

### A.2 The gate itself

- **Stale quarantine list.** `tests.yml` and `scripts/local_ci.sh` ignore six
  modules. `test_admin_student_profile_regressions.py`, `test_guest_funnel.py`,
  `test_homework_regressions.py` and `test_score_unification.py` do not exist.
  `test_local_ci_mirror.py` only checks that the two lists match each other,
  not that the entries exist.
- **Two modules are quarantined for real.** `test_auth_request.py` does a live
  login over the network. `test_sentry.py` is not a test: it is a `print`
  script that exits when `SENTRY_DSN` is unset. Neither has run in CI since
  2026-08-11.
- **`test_jwt_verify.py` is the same kind of script** (`load_dotenv`, prints
  a banner, no test functions). Pytest collects it, imports it, runs nothing.
  Untouched since 2026-01-23.
- **Two hidden suites.** Eight `tests/*_postgres.py` modules (257 cases) skip
  unless a `*_REHEARSAL_DSN` variable is set; nothing in CI or
  `local_ci.sh` sets one. They are the only tests of the MLC-3 storage
  paths (`first_client_repository.py`, 1,118 lines, 15.7% coverage).
  `tests/evals/` (3 probes) needs an OpenAI key that CI does not have.

### A.3 What is skipped and why (362 cases)

| Cases | Module | Reason string | Read |
|---|---|---|---|
| 257 | 8 × `tests/*_postgres.py` | "disposable … rehearsal only" | never run anywhere automated |
| 62 | `test_training_import.py` | "legacy training imports are intentionally disabled in Phase 1" | whole module is a policy no-op; subject `training_import.py` is at 0% coverage |
| 34 | `test_voice_confidence.py` | "retired sex-routed contract retained as historical test text" | dead cases kept on purpose; the file still carries 40 cases of which 6 run |
| 9 | `test_master_document.py` | "retired incumbent/challenger endpoint" | dead cases |

### A.4 Tests on retired constructs

The product retired charisma/stress vocabulary (2026-08-13), challenge/threat
routing and speaker-sex processing (2026-08-29), and Best Presentation as an
artifact (L1). The tests split cleanly into fences and dead weight:

- **Fence tests, KEEP:** `test_stress_snippets_retired.py`,
  `test_acoustic_targets_deleted.py`, `test_master_doc_output_guards.py`,
  `test_marker_hygiene.py`, `test_session_summary_allowlist.py`,
  `test_canonical_product.py`, `test_provenance.py`,
  `test_recording_lane_guards.py`, `test_rating_resume_is_own_only.py`. These
  assert the retirement holds. Several do it by grepping the repo
  (`test_stress_snippets_retired` 5.7 s, `test_snippet_table_name` 6.3 s,
  `test_session_globals_wiring` 11.6 s), which is why they are among the
  slowest modules.
- **Dead weight:** the 34 skipped cases in `test_voice_confidence.py`, the 9
  in `test_master_document.py`, all 62 in `test_training_import.py`.
- **Ambiguous, needs a decision:** `test_best_presentation.py` (15 test files
  import `services.best_presentation`; the module is live, 87.6% covered, and
  is the per-slide selection engine that other F1 modules import). The name
  is retired; the code is not.

### A.5 Stale tests

55 modules were last touched in an earlier month than their subject module's
latest commit; 41 of them are F1-path. All pass. The ones worth a re-read
first, because the subject moved most:

| Test | Test last touched | Subject | Subject last touched |
|---|---|---|---|
| `test_audio_metrics_features.py` | 2026-06-04 | `services/audio_metrics.py` | 2026-08-06 |
| `test_f0_octave.py` | 2026-06-08 | `services/audio_metrics.py` | 2026-08-06 |
| `test_cross_take_selection.py` | 2026-06-15 | `services/cross_take_selection.py` | 2026-08-22 |
| `test_min_content_gate.py` | 2026-07-15 | `services/min_content_gate.py` | 2026-08-06 |
| `test_protected_phrases.py` | 2026-07-20 | `services/protected_phrases.py` | 2026-08-26 |
| `test_ideal_text_annotations.py` | 2026-07-28 | `services/ideal_text_annotations.py` | 2026-08-03 |
| `test_annotation_capture.py` | 2026-07-28 | `services/star_verdicts.py` | 2026-08-29 |
| `test_moment_reference.py` | 2026-07-26 | `services/ideal_text_block.py` | 2026-09-01 |

Full list: filter `raw/test_classification.md` for "subject moved".

### A.6 Duplication and fragmentation in the suite

- **63 modules define their own fake DB** (`_Db` ×26, `_FakeDB` ×10,
  `_FakeDb` ×8, `FakeDB` ×4, `FakeDatabase` ×4, plus `_Client`, `_FakeClient`,
  `_Chain`, `_Boom`). `tests/fakes.py` (141 lines) is used by 12.
- **42 modules pre-seed `sys.modules`** with empty placeholders for
  `supabase`/`sentry_sdk`; `conftest.py` documents this as import-order
  roulette it exists to end.
- **45 modules import `routes.v2_routes`**, the compatibility façade, and 46
  `patch()` sites in 19 files rebind names on it. The façade exists because of
  the tests (its own docstring says so).
- **One subject, many files:** `ideal_text_block` 19 test files,
  `lab_recording` 19, `explore_ideal_text` 15, `best_presentation` 15,
  `arc_notifications` 11, `openai_service` 10. Thirteen subjects have tests in
  both the repo root and `tests/`.
- **41 test-function names repeat across modules** (e.g. `test_empty_safe` in
  4, `test_junk_never_raises` in 3). Mostly a naming pattern, not literal
  duplicates, but `test_audit_intent.py` and `test_goal_update.py` share three
  identically named cases on the same shape of code.
- **19 modules have ≤3 cases.** Merge candidates once their subject is fixed.
- **Wave/sprint-named modules** (`test_wave2_be.py`, `test_wave3_be.py`,
  `test_wave4_*`, `test_step2_peer_review.py`, `test_mlc2_*`, `test_mlc3_*`,
  `*_d3/_d4/_d5`) name a delivery, not a subject. They pass, but nobody can
  find "the test for X" by name.

### A.7 What has no tests

51 of 313 production modules are imported by no test (12,649 lines). 17 are at
0% coverage after the run:

| Statements | Module | Note |
|---|---|---|
| 318 | `routes/v2/user_chat.py` | 910 lines, also `mypy ignore_errors`; two routes have no FE caller |
| 300 | `services/snippet_truncation.py` | **zero importers anywhere: dead module** |
| 164 | `services/tutor_video_url.py` | last touched 2026-04-16 |
| 159 | `services/copilot_video_pipeline.py` | 2026-04-16; flag `COPILOT_VIDEO_PIPELINE_ENABLED` is read nowhere |
| 155 | `services/session_concatenation.py` | |
| 127 | `services/metrics_v2.py` | 2026-05-13; only importer is `session_metrics.py` (14.6%) |
| 111 | `services/annotation_export.py` | 2026-04-09 |
| 110 | `services/stickiness.py` | mypy-ignored |
| 105 | `services/snippet_extraction.py` | |
| 104 | `services/reference_video_upload_worker.py` | 2026-05-16 |
| 98 | `services/training_import.py` | disabled by policy |
| 86 | `services/arc_checkout.py` | mypy-ignored; `/v2/arc/<id>/checkout` has no FE caller |
| 50/41/40/40/23 | `fact_check`, `conversation_summary`, `casual_voice_analytics`, `unsubscribe_tokens`, `auto_comment` | all last touched May–June |

Large, low-coverage, on-path:

| Coverage | Statements | Module |
|---|---|---|
| 20.5% | 7,381 | `services/db.py` |
| 17.6% | 629 | `services/openai_service.py` (holds `transcribe_audio`, CC 43) |
| 22.0% | 626 | `routes/v2/coaching.py` |
| 16.1% | 622 | `routes/v2/admin.py` (20 of 21 routes have no FE caller) |
| 15.7% | 573 | `services/first_client_repository.py` (only the DSN-gated suite touches it) |
| 41.6% | 777 | `routes/v2/user_sessions.py` |
| 52.1% | 1,235 | `routes/v2/explore_ideal_text.py` |
| 52.5% | 158 | `services/analysis_worker.py` |
| 49.5% | 182 | `services/ideal_text_core_snapshot.py` |

### A.8 Cost

90 s of test time; one test is 24.5 s
(`test_audio_metrics_features::test_all_ten_readout_features_present`,
real librosa on real audio). The five repo-grepping fence modules cost ~35 s
together. Everything else is sub-second.

### A.9 Verdict table

The per-module table (308 rows) is in
[`raw/test_classification.md`](raw/test_classification.md). Verdict counts:

| Verdict | Modules |
|---|---|
| KEEP | 179 |
| KEEP (fence) | 64 |
| KEEP (off-path) | 50 |
| MOVE to `tests/integration` as opt-in | 8 (`*_postgres.py`) |
| QUARANTINE → FIX or DELETE | 2 (`test_sentry.py`, `test_auth_request.py`) |
| DELETE the skipped cases | 2 (`test_voice_confidence.py` 34 cases, `test_master_document.py` 9 cases) |
| DELETE-CANDIDATE or FIX | 1 (`test_training_import.py`, whole module) |
| FIX | 1 (`test_moment_suggestions.py` imports `services.moment_direction`, which no longer exists, behind a guarded skip) |
| DECIDE | 1 (`test_best_presentation.py`) |

Plus: `test_jwt_verify.py` (no test functions) → DELETE or convert.

---

## B. Cyclomatic complexity

### B.1 Distribution (`radon cc`, 4,237 functions and methods)

| Grade | CC | Count |
|---|---|---|
| A | 1–5 | 2,460 |
| B | 6–10 | 1,011 |
| C | 11–20 | 561 |
| D | 21–30 | 118 |
| E | 31–40 | 45 |
| F | 41+ | 42 |

205 functions are above 20; 42 are above 40. The nine modules at
maintainability index **0**: `routes/life_routes.py`,
`routes/v2/explore_ideal_text.py`, `routes/v2/user_sessions.py`,
`routes/v2/coach.py`, `services/life_engine.py`, `services/openai_service.py`,
`services/first_client_repository.py`,
`services/mlc3_founder_canary_readiness.py`, `services/db.py`.

### B.2 The worst 30

| CC | Lines | Function | Path tier |
|---|---|---|---|
| 185 | 901 | `routes/v2/explore_ideal_text.py:1975 _tracked_changes_block` | **F1 (Ideal Text read)** |
| 112 | 223 | `services/mlc3_founder_canary_readiness.py:265 validate_deployment_attestation` | F2 ops |
| 85 | 269 | `services/feedback_data_contract.py:294 build_feedback_exposure_bundle` | **F1 (Manager exposure)** |
| 74 | 191 | `services/take_feedback_policy_v3_service.py:34 prepare_v3_service_inventory` | **F1 (V3 policy)** |
| 66 | 264 | `routes/v2/coach.py:766 v2_coach_get_session` | F2 |
| 65 | 216 | `routes/v2/explore_ideal_text.py:175 _ideal_piece_provenance` | **F1** |
| 62 | 308 | `routes/v2/coach.py:3265 v2_coach_confidence_queue` | F2 |
| 61 | 117 | `services/mlc3_general_service_readiness.py:141 validate_general_deployment_attestation` | F2 ops |
| 61 | 142 | `services/journal.py:271 validate_post_body` | scaffolding |
| 59 | 668 | `config.py:73 Config` (class) | infra |
| 58 | 269 | `routes/v2/coach_guidance_delivery.py:313 v2_coach_guidance_attachment` | F2 |
| 57 | 202 | `services/manager_engine.py:592 arbitrate` | **F1 (Manager)** |
| 56 | 310 | `services/intervention_candidates.py:865 select` | **F1 (candidates)** |
| 56 | 200 | `routes/v2/explore_ideal_text.py:3215 v2_explore_put_ideal_user_edit` | **F1 (Ideal Text edit)** |
| 55 | 123 | `services/confident_voice_practice.py:341 attach_exercise_offer` | F2 |
| 53 | 136 | `routes/v2/user_sessions.py:1721 v2_start_confident_voice_practice` | F2 |
| 52 | 179 | `services/take_feedback_candidates.py:87 current_take_confident_voice_candidate` | **F1** |
| 51 | 233 | `routes/v2/user_sessions.py:862 v2_user_suggestion_feedback` | F1-surface |
| 50 | 215 | `services/ideal_text_parts.py:309 compose_locked` | **F1 (Ideal Text)** |
| 49 | 186 | `services/ideal_text_block.py:394 maybe_assemble_ideal_text` | **F1 (initial Ideal Text)** |
| 49 | 300 | `routes/v2/coaching.py:637 v2_coaching_state_machine_turn` | scaffolding |
| 48 | 336 | `services/analysis_worker.py:118 _run_full_analysis_impl` | **F1 (pipeline)** |
| 47 | 193 | `services/tracked_changes.py:239 build_tracked_changes` | **F1** |
| 47 | 148 | `routes/v2/coach.py:1370 v2_coach_confident_voice_practice` | F2 |
| 45 | 105 | `services/take_feedback_policy_v3.py:353 _verbal_inventory` | **F1 (V3)** |
| 44 | 78 | `services/tracked_changes.py:434 build_coach_revision_changes` | F2 |
| 44 | 117 | `services/take_review.py:33 finalize_later_take_review` | **F1 (later Take)** |
| 44 | 110 | `services/db.py:3975 v2_get_sessions_with_previews` | F1-surface |
| 44 | 184 | `routes/v2/user_chat.py:183 _build_longitudinal_context_block` | scaffolding, 0% covered |
| 43 | 201 | `services/openai_service.py:251 transcribe_audio` | **F1 (transcription)** |

Next 30 are in `raw/radon_cc_top200.txt`.

### B.3 Why the F1 ones are complex

Structural signature of each (from the AST): `ifs`, `try` blocks, broad
`except Exception`, distinct `db.` calls, `.get(` dict reads.

| Function | Lines | ifs | try | broad except | db calls | `.get(` | Read |
|---|---|---|---|---|---|---|---|
| `_tracked_changes_block` | 901 | 44 | 15 | 15 | 13 | 73 | **Accidental.** A route-private helper doing DB reads, ledger reconciliation, diffing and payload shaping in one body, each stage wrapped in its own swallow-all `except`. Fifteen silent-fallback points on the Ideal Text read path. |
| `v2_explore_get_ideal_text` | 465 | 11 | 4 | 4 | 5 | 15 | Accidental: the route is the orchestrator. |
| `build_feedback_exposure_bundle` | 270 | 16 | 0 | 0 | 0 | 50 | **Mixed.** Pure and untried, but 50 dict `.get` reads means the data contract is a dict, not a type; every optional key is a branch. |
| `prepare_v3_service_inventory` | 192 | 17 | 0 | 0 | 0 | 52 | Same: 52 `.get`, 14 return points. |
| `_ideal_piece_provenance` | 216 | 13 | 2 | 2 | 3 | 49 | Same pattern inside a route. |
| `arbitrate` (manager) | 204 | 12 | 0 | 0 | 0 | 3 | **Inherent.** Pure ranking over three lanes with budget rules; no I/O, no fallbacks. Complexity is the policy. Well covered (94.7%). |
| `select` (intervention candidates) | 310 | 11 | 1 | 1 | 0 | 23 | Mostly inherent, one very long body; 92.7% covered. |
| `compose_locked` | 215 | 17 | 0 | 0 | 0 | 10 | Inherent-ish (lock/merge rules); 96% covered. |
| `maybe_assemble_ideal_text` | 186 | 19 | 5 | 5 | 0 | 16 | Five broad excepts on the initial-Ideal-Text path: each is a place a silent degradation can hide. |
| `_run_full_analysis_impl` | 336 | 14 | 11 | 11 | 3 | 8 | **Accidental.** Eleven try blocks, eleven swallow-alls: the pipeline is a chain of "try stage, log, continue". |
| `transcribe_audio` | 201 | 14 | 3 | 3 | 0 | 4 | Provider retries, compression fallbacks and format sniffing in one method; 17.6% module coverage. |
| `build_tracked_changes` | 193 | 21 | 1 | 0 | 0 | 12 | Inherent diff logic; 86% covered. |
| `finalize_later_take_review` | 118 | 13 | 2 | 2 | 0 | 19 | Mixed. |

Two patterns explain most of the accidental complexity: **dict payloads with
optional keys** (`.get` counts of 49–73) and **swallow-all exception
ladders** (15 and 11 in the two worst). Neither is a CC problem to fix with
extraction alone; the first wants typed records at the boundaries, the second
wants an explicit degradation policy.

### B.4 God files

| Lines | File | C+ functions | Coverage |
|---|---|---|---|
| 18,724 | `services/db.py` | 188 | 20.5% |
| 4,297 | `routes/v2/coach.py` | 30 | 43.3% |
| 3,414 | `routes/v2/explore_ideal_text.py` | 14 | 52.1% |
| 2,094 | `routes/v2/user_sessions.py` | 13 | 41.6% |
| 2,050 | `routes/v2/coaching.py` | 8 | 22.0% |
| 1,967 | `services/life_engine.py` | 12 | — |
| 1,958 | `routes/v2/admin.py` | 6 | 16.1% |
| 1,797 | `routes/life_routes.py` | 8 | — |
| 1,579 | `services/openai_service.py` | 30 | 17.6% |

`routes/v2/*` was split from a single `v2_routes.py` in August (that file has
519 commits, the most in the repo). The split moved lines; it did not move
logic out of the routes. Six of the thirty worst functions are still route
handlers or route-private helpers.

---

## C. Tightness of abstractions and glue code

### C.1 `services/db.py` — one object, every table

- 582 methods on `DatabaseService`; 135 production files import it.
- **106 methods have no caller anywhere** (production, scripts, tests, or
  inside `db.py`): 2,152 lines. Largest: `pop_pending_icebreaker_for_user`
  (94 lines), `v2_upsert_student_coaching_memory` (81),
  `v2_create_task_pool_entry_and_assign_student` (62),
  `v2_list_charisma_snippets` (54), `v2_delete_student` (52). Full list:
  `raw/db_methods_no_caller.txt`.
- Two more are referenced only by tests.
- Name families show the layers of history: `get_` 149, `v2_` 93, `list_` 49,
  `set_` 42, `update_` 31, `insert_` 28, `upsert_` 28, `create_` 25.
- The tests patch it by attribute (`v2.db.<method>` at ~360 sites per the
  façade docstring), which is why every method name is load-bearing for the
  suite even when production never calls it.

### C.2 Two data-access idioms

`feedback_repository.py` (255 lines), `project_repository.py` (127),
`take_feedback_set.py` (195) take a client and do not import `db`.
`first_client_repository.py` (1,118 lines, MI 0, 15.7% coverage) reaches
`.client` 85 times. `life_store.py` (893) does both. New F1 work (the
feedback repository) is on the cleaner idiom; the god object still owns
everything older.

### C.3 The `routes/v2_routes.py` façade

537 lines that contain no routes: imports every domain module (import order is
load-bearing) and re-exports ~100 names so `routes.v2_routes.<name>` keeps
resolving for the tests. 45 test modules import it; 46 patch sites in 19 files
rebind names on it. It is glue that exists only to avoid touching tests.

### C.4 Three ways to call the model

| Entry point | Production importers |
|---|---|
| `services/openai_service.py` (`OpenAIService`, 1,579 lines, mypy-ignored) | 13 |
| `services/llm.py` | 25 |
| `services/llm_config.py` | 27 |
| direct `chat.completions.create` / `audio.transcriptions.create` | 11 files: `routes/v2/coaching.py`, `routes/v2/user_chat.py`, `services/ceo_work_items.py`, `services/life_engine.py`, `services/dev_tasks.py`, `services/snippet_transcription.py`, `services/llm_usage.py`, `services/llm_schemas.py`, plus the three above |

`services/life_engine.py` constructs its own `openai.OpenAI(...)` client,
bypassing whatever timeouts and usage accounting the service layer applies.
The transcription call (`transcribe_audio`, F1 piece (a)) lives inside the
least-tested of the three layers.

### C.5 Configuration leaks

- `Config` has 131 attributes. **18 are read by no production module**
  (14 of them by nothing at all; `MLC2_CONFIDENCE_MONITORING_ENABLED`,
  `MLC3_PILOT_PRINCIPAL_IDS`, `AUDIT_SLA_HOURS`, `BACKEND_URL` appear only in
  tests or scripts):
  `HOMEWORK_UNLOCK_WHEN_EMAIL_FAILS`, `MLC2_FOUNDATION_ENABLED`,
  `MLC2_CONFIDENCE_MONITORING_ENABLED`, `MAX_RECORDING_DURATION_SECONDS`,
  `MAX_USER_MEDIA_SIZE_MB`, `MLC3_PILOT_PRINCIPAL_IDS`,
  `COACHING_ATTEMPTS_DUAL_WRITE`, `LONGITUDINAL_FIRST_QUESTION_ENABLED`,
  `BASELINE_SUMMARY_ENABLED`, `LEARNER_MIRROR_ENABLED`, `AUDIT_SLA_HOURS`,
  `COACH_NAME`, `COACH_IMAGE_URL`, `BACKEND_URL`,
  `TUTOR_FEEDBACK_WINDOW_HOURS`, `COPILOT_VIDEO_PIPELINE_ENABLED`,
  `COPILOT_VIDEO_PIPELINE_SECRET`, `DIAGNOSE_SESSION_STATE_ENABLED`.
  Seven of these are feature flags that gate nothing in production code.
- **86 `os.environ`/`getenv` reads in 42 files outside `config.py`**, including
  `services/take_feedback_policy_v3.py` (5, the V3 policy),
  `services/feedback_data_contract.py` (3), `services/ideal_text_block.py` (2),
  `services/slide_word_split.py` (2). The CONFIG-FIRST rule in `CLAUDE.md`
  assumes one place reads the environment; there are 43.

### C.6 Retired constructs that are still code

| Construct | Retired | Still in code |
|---|---|---|
| charisma / stress skills | 2026-08-13 | `services/skills/{base,charisma,stress}.py` (234 lines), imported by `routes/v2/coaching.py` and `routes/v2/user_chat.py`; no tests; "charisma" in 54 production files, "stress" in 35 |
| charisma/stress snippet services | — | `services/charisma_snippet_service.py`, `services/stress_snippet_service.py`: zero importers, both `mypy ignore_errors` |
| Best Presentation | L1 (2026-08-26) | `services/best_presentation.py` 765 lines, imported by 13 modules, 15 test files, 87.6% covered; `/v2/explore/arc/<id>/best-presentation` route still registered and the FE still calls it |
| challenge / threat | 2026-08-29 | strings in 21 / 11 production files (mostly prompt text and comments; `services/star_verdicts.py`, `say_it_stronger.py` need a read) |
| speaker sex | 2026-08-29 | clean in the backend (0 hits) |

### C.7 Glue and dead modules

- **101 public one-line pass-through wrappers** (`return other(...)`): 8 in
  `services/rate_limits.py`, 5 in `app.py`, 4 each in `routes/life_routes.py`,
  `services/project_repository.py`, `services/dimension_registry.py`,
  `services/pipeline_jobs.py`. List: `raw/passthrough_wrappers.txt`.
- **Dead modules:** `services/snippet_truncation.py` (825 lines, no importer,
  0%), `charisma_snippet_service.py`, `stress_snippet_service.py`.
- **Scripts with zero references** in any file, Dockerfile, Procfile, doc or
  test: `backfill_copilot_draft_contract.py`,
  `backfill_ideal_text_document_snapshots.py`, `backfill_score_for_display.py`,
  `export_openai_finetuning_jsonl.py`, `extract_jwt_from_cookie.py`,
  `import_life_corpus.py`, `kpi_sanity_check.py`.
- **Duplication is low:** jscpd found 7 clones, 0.11% of lines. Notable pairs:
  `coach_video_storage.py` ↔ `user_media_storage.py` (24 lines),
  `mlc2_confidence.py` ↔ `mlc2_confidence_producer.py` (18 lines),
  `mlc2_confidence_readiness.py` ↔ `mlc3_founder_canary_readiness.py`.
- **mypy ratchet:** 54 entries under `ignore_errors`, including the F1 modules
  `services.lab_recording` and `services.slide_word_split`, plus `services.db`,
  `services.openai_service`, `services.best_presentation`,
  `routes.v2.user_chat`, `routes.v2.admin`, `routes.v2_routes`.

### C.8 Routes with no frontend caller

298 routes registered. 114 have no string match in the frontend `src/`.
Bucketed (`raw/routes_without_fe_caller.txt`):

| Bucket | Routes | Read |
|---|---|---|
| behind a catch-all BFF proxy (`/v2/life/*` etc.) | 26 | unverifiable statically |
| `/v2/internal/*` webhooks and cron | 10 | not FE-facing by design |
| dev-bugs / dev-tasks UI served by the backend | 14 | a separate tool, not the product |
| legacy `/auth`, `/admin` blueprints | 4 | `routes/auth.py` constructs its own Supabase client 3 times |
| **no caller found** | **60** | see below |

The 60 include: **20 of 21 routes in `routes/v2/admin.py`** (question pool,
directives queue, icebreaker, review queue, health), all 7
`/v2/processing-authorization/*`, six arc routes (`/explore/start`,
`checkout`, `redeem`, `unlock`, `unlock-moments`, `snippet-library`), the
three `/v2/tokens/*`, `/v2/onboarding/opener/*`, `/v2/user/chat/first-question`,
`/v2/user/coaching/self-rating`, `/v2/user/consent`, `/v2/user/kpi/timeline`,
`/v2/user/results/<id>`, `/v2/journal/categories`, `/v2/jobs/<id>/status`,
`/v2/learning-exposures/ack`, `/v2/coach/annotation-uploads`,
`/v2/coach/audits`, and the `/api/admin/students*` aliases in `app.py`.
A route can be called from elsewhere (curl, cron, an old client); this list is
the input to a question, not a delete list.

### C.9 Documentation as glue

213 files under `docs/`, of which ~30 are dated `HANDOFF`/`BE-ANSWER`
messages between the two repos, plus `PHASE-A0-FINDINGS.md` at the root.
These are conversation, not reference; nothing marks which are current.

### C.10 Ranked buckets

**Delete (dead glue), ranked by F1 proximity**
1. 106 uncalled `db.py` methods (2,152 lines) — on the F1 import path of 135 files.
2. Skipped-forever tests: 34 in `test_voice_confidence.py`, 9 in `test_master_document.py`, `test_training_import.py`, `test_jwt_verify.py`; the four phantom entries in the CI ignore list.
3. `services/snippet_truncation.py`, `charisma_snippet_service.py`, `stress_snippet_service.py`; 14 config attributes nothing reads (18 that production never reads); 7 unreferenced scripts.
4. `services/skills/` once `routes/v2/coaching.py` and `user_chat.py` stop importing it (question Q-A6).

**Collapse (two layers that should be one)**
1. `routes/v2_routes.py` façade + the 45 test modules that need it → tests import domain modules directly; then delete the façade.
2. 63 private fake-DB classes → `tests/fakes.py`; 42 `sys.modules` pre-seeds → delete (conftest already does the job).
3. Three LLM entry points + 11 direct call sites → one client with timeouts and usage accounting; `life_engine.py` stops building its own.
4. `db.py` + `*_repository` → one idiom (question Q-A2).

**Tighten (real seams that leak)**
1. `_tracked_changes_block` (CC 185, 15 swallow-alls, 13 DB calls) and `_run_full_analysis_impl` (11 swallow-alls): decide a degradation policy, then the extraction is mechanical.
2. Dict payloads at the Manager/V3 boundary (`build_feedback_exposure_bundle`, `prepare_v3_service_inventory`, `_ideal_piece_provenance`: 50 `.get` each) → typed records.
3. `os.environ` reads in F1 modules → `Config`.
4. `openai_service.transcribe_audio` at 17.6% module coverage: the transcription piece (a) has the least tested provider seam.
5. Routes doing service work: six of the worst-30 functions are in `routes/`.

---

*Filter stamp for this audit:* `FILTER: JUSTIFIED-SCAFFOLDING — cat {SCAFFOLDING (read-only audit)} — fences {clear} — locks {clear} — redirect: findings ranked by F1 proximity; each cleanup is filtered separately via the question set.`
