# Prompt for the senior engineer — keep the ML code aligned with the locked architecture

Paste everything below this line.

---

You are the senior backend engineer on willab (`backend-cursor`, with `frontend-cursor` for the BFF and surfaces). A read-only ML provenance audit of `origin/main` (backend 87a9309, manifest 0350; frontend 6768fbc) produced 98 findings. Your job is to close the ones listed here so that the data foundation and the serving paths obey the locked architecture, and to leave a regression test behind for each one so it cannot reopen. The audit report with every finding's evidence is at the link the founder gives you; finding ids below (A-1, LEGACY-1, ...) refer to it.

## Ground rules that do not bend

1. Run the WILLAB DECISION FILTER on every change and put the one-line stamp in the PR. Everything here is F1-SURFACE hardening or F1-SUPPORT for the named in-flight task "canary widening readiness"; nothing here is a feature.
2. You are not authorizing anything. Do not enable dataset creation, training, evaluation, promotion, the MLC-2 cutover, the MLC-3 rollout, the founder-canary consent route, or the learning-exposure ack proxy. Where a fix needs a gate to exist, build the gate closed. Activation decisions are the founder's, in the runbook, with the readiness evaluators green.
3. No user-facing copy changes without founder sign-off. Where a finding names copy (FE-4, FE-5), open a question for the founder and leave the strings alone.
4. Migrations are idempotent, additive, never drop, and are rehearsed on the PostgreSQL tier before merge. `MIGRATE_ON_BOOT=1` means merging a migration runs it in production. CONFIG-FIRST: any change that reads a new variable sets that variable on every Railway service (web, worker, every cron) before the code merges, and you verify from the boot log.
5. The gate is `scripts/local_ci.sh` (Actions minutes are out). A change that touches migrations or a rehearsed RPC caller runs the rehearsal tier; if it cannot run, the change is red.
6. Each workstream below ends with the named regression tests passing. A test that passes today, before your change, is not a regression test; prove it fails first.
7. Never widen a PR. One workstream per PR unless two are inseparable. Keep the canonical tables append-only; add rows, columns, triggers and checks, never rewrite history.

## Workstream 1 — close the ungated model promotion and serving path (blocker)

Findings: LEGACY-1, J1-2, E-6, H-1, E-5, J1-3.

Today `scripts/promote_openai_model.py` writes `runtime_config.openai_surface_model_<surface>` and `services/llm.py` serves that model on the next request, including the Take-1 Ideal Text composition (surface `best_presentation`) and Say It Stronger. Nothing reads `MLC2_PROMOTION_ENABLED`; the only "gate" is a self-hashed local JSON report.

Changes:
- `services/ml_surface_contracts.resolve_surface_model` returns the default model and logs `promotion_disabled` unless `Config.MLC2_PROMOTION_ENABLED` is true. Do not remove the runtime_config read; fence it.
- `scripts/promote_openai_model.py` exits before any write while `MLC2_PROMOTION_ENABLED` is false, and additionally requires the current `prompts.lock.json` hash for the surface and stores it beside the model id (H-1). `scripts/run_openai_preference_finetune.py` and `scripts/export_openai_preference_jsonl.py` exit while `MLC2_TRAINING_ENABLED` / `MLC2_DATASET_RELEASES_ENABLED` are false.
- Remove `moment_suggestion` from `SURFACES` in `ml_surface_contracts.py` or make `contract_for_surface` consult `mlc2_foundation.REJECTED_LEARNING_ALIASES` (E-6). The four-id map must be a subset of the aliases the DB registry accepts.
- Rename or re-document `TAKE_FEEDBACK_POLICY_V3_MODE` so its name says "shadow write"; it does not select the served policy (J1-3).
- Add a migration that installs a BEFORE INSERT OR UPDATE trigger on `runtime_config` rejecting any `openai_surface_model_%` write unless a transaction GUC set only by the promotion script is present, and revoke direct INSERT/UPDATE on that table from `service_role` for those keys if feasible. Rehearse it.

Tests: `tests/test_lane2_promotion_is_dark.py::test_promote_openai_model_refuses_when_mlc2_promotion_disabled`, `::test_resolve_surface_model_ignores_runtime_config_when_promotion_disabled`, `tests/test_ml_dpo_loop.py::test_rejected_canonical_alias_is_not_a_trainable_surface`, `tests/test_ml_surface_prompt_parity.py::test_promote_requires_locked_prompt_hash`, `tests/test_take_feedback_policy_selection.py::test_v3_mode_only_controls_shadow_write`.

## Workstream 2 — serving must fail closed when lineage cannot be written (blocker)

Findings: A-1, A-2, A-3, B-1, J1-4.

The V3 Confident Voice service path serves rows when `record_feedback_v3_service_candidate_set_v1` or `freeze_feedback_v3_service_membership_v1` fails, and the browser receives uuid5 candidate ids that exist in no table. With `PLF1_PROCESSING_AUTHORIZATION_MODE` at its default `off`, no Phase-1 attempt, audio object, sha256 verification or authorization snapshot is written, so every served row has an empty audio and consent hop.

Changes:
- In `services/mlc3_first_client_feedback.py`, a lineage RPC failure returns `V3Unavailable(reason)` instead of serving without lineage. Update `tests/test_v3_end_to_end_production_shape.py:399-410`, which currently pins the wrong behaviour.
- `prepare_first_client_feedback` (or the route guard `mlc3_service_required`) refuses with `V3Unavailable('processing_boundary_not_enforced')` when `ProcessingAuthorizationService().enforced` is false. The same check goes into `routes/v2/lab_recording.py` when `finalize_recording` returns `None` and the MLC-3 service is enabled.
- In `services/ideal_text_changes.py` the compatibility `take_feedback_exposure` row for a V3-served Take must carry the V3 policy version and a candidate set that contains the selected keys; move `exposure_snapshot` after the V3 replacement, or write a second snapshot (A-2).
- `app.py` and `worker.py` log one boot line with the effective value of every gate flag (names and values only, never the principal UUID or secrets): `PLF1_PROCESSING_AUTHORIZATION_MODE`, `TAKE_FEEDBACK_POLICY_V3_MODE`, `DATA_FOUNDATION_CANARY_ENABLED`, `MLC3_SERVICE_ENABLED`, `MLC3_COACH_INLINE_AUTHORING_ENABLED`, `CONFIDENT_MOMENT_BUNDLE_V1_ENABLED`, `MLC2_CONFIDENCE_MONITORING_ENABLED`, whether `MLC2_CONFIDENCE_CANARY_PRINCIPAL_ID` is set. `bin/railway-web.sh` and `bin/railway-worker.sh` echo `PLF1_PROCESSING_AUTHORIZATION_MODE` unconditionally (J1-4, B-1).
- `ProcessingAuthorizationService.finalize_recording` in `off` mode logs a warning naming the recording as unlineaged; silence is not acceptable.

Tests: `tests/test_v3_served_rows_have_durable_record.py::test_every_served_v3_row_has_a_persisted_exposure`, `tests/test_phase1_mode_required_for_v3_service.py::test_v3_service_refuses_when_processing_authorization_not_enforced`, `tests/test_ideal_text_changes_v3_exposure_label.py::test_v3_served_take_records_v3_policy_and_matching_candidate_set`, `tests/test_boot_gate_log.py::test_app_boot_emits_gate_summary_line`, `tests/test_railway_boot_scripts.py::test_boot_scripts_log_plf1_mode`.

## Workstream 3 — bind authorization to the acquiring principal (major)

Findings: B-2, B-3, B-8, B-11, B-6.

Changes (migration plus service):
- `issue_phase1_provider_permit_v1` verifies that `p_source_take_id` / `p_source_recording_id` belong to `p_acquisition_principal_id` (via `processing_recording_attempts`, else `v2_sessions.owner_principal_id` at acquisition as recorded in `owner_claim_events`) and raises `PROCESSING_SOURCE_PRINCIPAL_MISMATCH` otherwise.
- `resolve_phase1_acquisition_principal_v1` returns the claim source whenever an `owner_claim_events` row exists, regardless of whether the source holds a receipt; a claimed guest without a receipt raises `PROCESSING_PRINCIPAL_UNRESOLVED` rather than falling through to the target.
- `accept_phase1_processing_authorization_v1` takes an actor binding (authenticated user id or guest proof hash) checked against `owner_principals`; the route passes it from the token.
- `ProcessingAuthorizationService.resolve_acquisition_principal` uses the same resolution in `off` mode as in `enforce` mode.
- Every fan-out thread that calls an LLM inside `protected_provider_scope` (`coach_comment_drafter.py:219`, `say_it_stronger.py:303`, `snippet_truncation.py:817`, `conversation_summary.py:116`) runs under `contextvars.copy_context().run` as `services/parallel.py` already does; the two admin routes that call LLMs on user data (`routes/v2/admin.py:1121`, `:1437`) get `phase1_provider_route`.

Tests: `tests/test_phase1_processing_postgres.py::test_permit_rejects_foreign_source_recording`, `::test_claimed_guest_without_receipt_cannot_be_authorized_by_target`, `::test_accept_requires_actor_binding`, `tests/test_phase1_gate_identity.py::test_resolution_is_mode_independent`, `tests/test_authorized_provider_scope.py::test_fanout_threads_inherit_protected_scope`, `tests/test_phase1_route_coverage.py`.

## Workstream 4 — make deletion reach every derived artifact (major)

Findings: B-4, B-5, B-7, C-1, C-2, C-3, C-4, C-5, C-6, C-7, C-8, A-5, I-7.

Changes:
- `freeze_phase1_purge_inventory_v4` and `mark_phase1_storage_object_purged_v1` accept `source_relation = 'processing_practice_objects'` (B-4). Today a subject with one practice recording cannot be purged at all.
- `audit_phase1_purge_catalog_v1` adds `take_id`, `speaker_id`, `recording_attempt_id`, `practice_attempt_id`, `reviewer_principal_id` to its column list; register `feedback_language_delivery_take_arm_operations` and `ml_speaker_split_assignments` in `data_purge_registry.py` with an explicit disposition (B-5).
- Add a subject-invalidation RPC for dataset releases that writes `dataset_exclusions` rows with `reason_code='subject_withdrawn'`, add an index on `dataset_release_items(owner_principal_id)`, and make every reader of release items honour `dataset_exclusions` (C-1). Add a consumer for `ml_purge_requests` that writes supersession rows for `ml_object_artifacts` (C-4).
- Lane-2 exports and fine-tune uploads write a ledger row (provider file id, job id, manifest sha256, code commit, owner-principal to line-hash index) before the upload proceeds, so the purge can locate and the provider-deletion contract can act (B-7, C-2, I-4). The annotation export records sha256 and byte size and stops writing `student_id` and coach free text to a multi-subject object, or registers the object as a purge target per contained principal (C-3).
- Change `ON DELETE CASCADE` to `RESTRICT` for the seven learning-lineage FKs from `v2_sessions` and for `user_consents`, `user_consent_events`, `owner_principals`, `admin_annotation_events` to `auth.users`; `v2_delete_session` and `run_cleanup_v2_sessions.py` refuse when learning lineage exists (C-6, C-8, I-7).
- Add a `data_subject_holds` relation and make `request_phase1_purge_v1` return `review_required` while a hold is active (C-7).
- Make the four "source is live" guards consult `processing_audio_object_deletion_events` (A-5).
- The F1 Ideal Text readers take the `mlc3-service-principal:<P>` advisory key or refuse while a purge request is open; `db.get_ideal_text_document_snapshot` becomes one RPC statement (C-5).

Tests: `tests/test_phase1_deletion_completion_postgres.py::test_freeze_and_mark_accept_practice_object_targets`, `::test_catalog_audit_columns_cover_take_and_speaker`, `::test_purge_refuses_under_active_hold`, `tests/test_dataset_releases.py::test_withdrawal_after_release_invalidates_subject_items`, `tests/test_data_purge_registry.py::test_every_subject_bearing_relation_is_classified_postgres`, `tests/test_lane2_export_lineage.py::test_finetune_upload_records_provider_operation`, `tests/test_annotation_export_purge_reach.py::test_export_objects_are_purge_targets`, `tests/test_user_sessions.py::test_take_delete_refuses_when_learning_lineage_exists`, `tests/test_phase1_purge_blocks_downstream_freezes_postgres.py::test_freeze_after_verified_purge_raises`, `tests/test_confident_moment_coaching_bundle_postgres.py::test_f1_document_reads_serialize_against_purge_request`.

## Workstream 5 — split integrity and release validation (blocker)

Findings: D-1, D-2, D-3, D-4, D-5, D-6, E-3, F-3, G-2, G-5, I-2.

All of these live in `create_dataset_release_v1` (migration 0300 body) and `services/dataset_releases.py`. The function currently trusts the caller for checksums, cutoff, taxonomy, consent and split strategy. Keep it callable only by `service_role`; do not wire a producer.

Changes to the RPC (one migration, `CREATE OR REPLACE`, rehearsed):
- Recompute `manifest_checksum` and each `item_checksum` server-side and raise `dataset release manifest checksum mismatch` (I-2); CHECK both columns as hex64.
- Raise when an item's owner has a stored `dataset_split_assignments.strategy_version` different from the manifest's (D-3).
- Raise when the same `evidence_span_id` appears twice in a release; add UNIQUE `(release_id, evidence_span_id)` (D-5).
- Require a creation timestamp per item and raise when it postdates `source_cutoff_at`; require `label_row_id` and verify it exists (D-6).
- Require `taxonomy_versions` to name every taxonomy present in the items and raise on a mix (F-3).
- Require, per owner, an eligible unwithdrawn `ml_consent_snapshots` row with pooled authorization before any item is accepted (G-2); require, for generation surfaces, an exact machine-draft linkage (`feedback_candidate_id` + `candidate_output_sha256` or an artifact id) in the item payload (E-3).
- Guest claim: `claim_guest_owner` must either carry the guest's `dataset_split_assignments` row to the target (and raise on conflict) or refuse the claim while a release references the guest (D-1). Decide with the founder which; both keep one voice in one split.
- Unify the split universes: the release path and `assign_ml_speaker_split_v1` must derive the split from one key (speaker) and one hash formula; a new `split_policy_version` may not move a speaker that any release holds in `test` (D-2, D-4).
- Either extend the release/presentation/judgment CHECKs to include `exercise_adequacy_classification` or set its `ml_learning_surfaces.trainable` to false until a release path exists (G-5). Ask the founder.

Tests: `tests/test_dataset_release_rpc_postgres.py::test_rpc_rejects_manifest_whose_checksum_does_not_match_items`, `tests/test_dataset_release_strategy_postgres.py::test_release_rejects_items_whose_assignment_strategy_differs`, `tests/test_dataset_release_dedup_postgres.py::test_release_items_unique_per_evidence_span`, `tests/test_dataset_release_cutoff_postgres.py::test_items_after_source_cutoff_are_rejected`, `tests/test_create_dataset_release_postgres.py::test_rpc_rejects_taxonomy_mix`, `tests/test_dataset_release_postgres.py::test_release_rejects_unconsented_owner`, `tests/test_dataset_releases.py::test_generation_items_require_exact_machine_draft_link`, `tests/test_dataset_release_claim_postgres.py::test_claimed_guest_evidence_keeps_its_original_split`, `tests/test_split_universe_consistency_postgres.py::test_release_split_matches_speaker_split`, `tests/test_ml_speaker_split_postgres.py::test_new_policy_cannot_move_a_frozen_test_speaker`, `tests/test_mlc3_exercise_rehearsal_contract.py::test_learning_surface_registry_matches_release_vocabulary`.

## Workstream 6 — Lane-2 corpus hygiene (major)

Findings: E-1, E-2, D-7, LEGACY-2, I-3, I-1, LEGACY-4.

Changes:
- `admin_annotation_events` gets an `origin` column with a CHECK enum (`coach_edit_of_machine_draft`, `coach_only`, `machine_only_approved`), `producing_model_id` and `prompt_version` columns, and an append-only trigger. Writers set `origin` explicitly; the SFT builder `event_to_openai_messages` and the DPO exporter reject anything except `coach_edit_of_machine_draft` (E-1, D-7, E-5). Invert `tests/test_annotation_capture.py::test_final_only_card_still_captured`.
- `moment_suggestions`, `charisma_snippets` and `coach_snippet_drafts` stop regenerating a machine draft in place under an existing coach final; either refuse the upsert while `*_final IS NOT NULL` or version the draft and store the draft sha256 the final answered (E-2).
- The three coach routes that capture into `admin_annotation_events` (`routes/v2/coach.py:2548`, `ideal_text_annotations.py:266/282`, the publish delivery) capture only under an explicit, default-off `LANE2_CAPTURE_ENABLED` constant, and never for `field_name='moment_suggestion'` (LEGACY-2).
- The annotation export checkpoint uses `(created_at, id)` as a cursor (I-3). Decide with the founder whether `/v2/internal/annotation-export` stays 410; if it does, remove `bin/railway-annotation-export-cron.sh` and `Dockerfile.annotation-cron` so a dead cron cannot be re-provisioned (I-1, LEGACY-4). Add the 410 route test either way.

Tests: `tests/test_ml_finetuning_export.py::test_sft_example_requires_exact_machine_draft`, `::test_unedited_ai_output_is_never_an_sft_target`, `tests/test_moment_suggestion_draft_lineage_postgres.py::test_regenerated_draft_cannot_orphan_a_coach_final`, `tests/test_lane2_capture_is_dark.py::test_coach_routes_do_not_write_admin_annotation_events`, `tests/test_annotation_export.py::test_checkpoint_does_not_skip_rows_sharing_boundary_created_at`, `tests/test_phase2_guard_routes.py::test_internal_learning_routes_return_410_regardless_of_secret`.

## Workstream 7 — label quality and blindness (blocker)

Findings: F-1, F-2, J1-6, F-4, F-5.

Changes:
- `PUT /coach/snippets/<id>/confidence-label`: a second submission by the same coach after the response revealed the owner answer and machine value is a flagged post-reveal revision, never an in-place `upsert` of `confidence_labels.value`; `record_confidence_coach_judgment_v1` raises once `coach_evidence_comparison_v1` has been served for that span and coach (F-1). `get_confidence_label_corpus` reads `label_revision`, not the overwritten current row.
- Re-review labels carry `lane='coach_rereview'`; `label_quorum` excludes them from quorum; Voice Album's coach leg may still accept them (J1-6).
- Define a quorum for canonical judgments: a release item for `confidence_classification` needs two independent blind raters in agreement or an explicit adjudication row; compute and store a chance-corrected agreement statistic in the readiness report (F-2).
- `owner_voice_album_routing` gets `taxonomy_version NOT NULL DEFAULT 'confidence-owner-five-state-v1'`; new `neutral`/`unrateable` writes are rejected by trigger (F-4). `create_dataset_release_v1` consults `ml_contract_epochs` (F-5).

Tests: `tests/test_coach_confidence_relabel_after_reveal.py::test_second_put_after_reveal_is_rejected`, `tests/test_canonical_confidence_postgres.py::test_record_coach_judgment_rejects_after_comparison`, `tests/test_label_quorum.py::test_rereview_rows_are_excluded_from_quorum`, `tests/test_dataset_release_quorum.py::test_release_item_requires_settled_multi_rater_label`, `tests/test_owner_voice_album_routing_postgres.py::test_new_neutral_write_is_rejected`, `tests/test_dataset_release_epoch_gate_postgres.py::test_create_release_refuses_when_epoch_dataset_creation_disabled`.

## Workstream 8 — provenance completeness on the served chain (major)

Findings: A-4, A-6, A-7, A-8, A-9, A-10, A-11, H-2, H-3, H-4, H-5, H-6.

Changes:
- `v2_sessions.recording_1_id` cannot be repointed once set (trigger); `processing_recording_attempts.id` and `recording_id` gain FKs; `evidence_hash` includes `recording_id` and the audio sha256 (A-4).
- Empty `CODE_COMMIT_SHA` is refused at the bundle builder and by a CHECK `code_commit ~ '^[0-9a-f]{7,40}$'` on `candidate_sets` (A-6).
- `feedback_v3_memberships` (or a linked immutable frame row) stores `confidence_detector_version`, `acoustic_feature_schema_version`, `feature_extractor_version`, `threshold_version`, `source_code_sha256`, `deployment_commit`, all non-blank and CHECK-constrained; the V3 service writer inserts an `acoustic_feature_snapshots` row per served confident_voice candidate with a `baseline_sha256` and the contributing session ids (A-7, A-10). Store a NOT NULL `speaker_binding_id` on `candidate_sets` (A-9). Extend `feedback_candidate_output_sha256_v1` to cover `candidate_score`, `rank_evidence`, `detector_version` and `evidence_hash` (A-11).
- Pin the feature schema: a golden test of `_analyze_pcm` key set and values behind `acoustic-feature-schema-v1`; reject foreign `feature_schema_version` strings at every writer (H-3).
- One Python `root_phrase_normalization.normalize_transcript_v1` byte-identical to `root_phrase_normalize_transcript_v1` in SQL, with a parity test; one shared word tokenizer for V3 blocks, verbal markers and wpm (H-2, H-6); one `feature_stats` implementation and a baseline fingerprint on every stamp (H-5); a record-time vs backfill parity test (H-4).

Tests: `tests/test_recording_lineage_constraints_postgres.py`, `tests/test_code_commit_provenance.py::test_empty_commit_is_refused`, `tests/test_v3_service_versions_persisted_postgres.py::test_membership_carries_implementation_versions`, `tests/test_voice_confidence_baseline_provenance.py::test_stamp_records_baseline_identity`, `tests/test_feedback_candidate_output_hash_postgres.py::test_output_hash_changes_when_machine_evidence_changes`, `tests/test_feature_schema_pin.py`, `tests/test_rooting_phrase_normalizer_parity_postgres.py::test_sql_and_python_normalizers_agree`, `tests/test_train_serve_parity.py`, `tests/test_word_count_contract.py::test_single_tokenizer`.

## Workstream 9 — AC-9 surfaces (major)

Findings: J1-1, FE-1, FE-2, FE-3, FE-5, FE-6, FE-7; FE-4 is a founder copy question.

Changes:
- Backend: `GET /v2/recordings/<id>` stops emitting `performance_score_v2`, `performance_metrics_v2`, `metric_labels_snapshot_v2`; add a generic key fence test over every non-admin, non-coach blueprint for `score|ratio|probability|verdict|classifier|kpi` (J1-1). `readout_snippets.py` stops sending `stickiness.composite`, `power_score`/`overall_score`/`rank` and the raw feature vector to user endpoints; if ordering needs them, order server-side.
- Frontend: every user BFF route under `src/app/api/v2/{user,explore,lab,voice-album,projects}` declares an explicit projection allowlist instead of relaying verbatim (FE-1). Delete the dead legacy renderers (`CompletedCard.tsx` metrics, `FeaturesDataBlock`, `FeaturesData`, `PerformanceScore` types, the unused `confidence-review` route and service) and add source-scanning fences for `} wpm`, `} Hz`, `} dB`, `pauseRatio`, `voicedRatio` on user components (FE-2, FE-3, FE-7). The founder email leaves the bundle; the MLC-2 consent gate and the corpus comparison visibility read a server capability (FE-6). Gate `/coach/audit/<id>` behind blind completion and delete the dead "Stress as fuel" branch (FE-5).

Tests: `tests/test_ac9_recordings_route.py`, `tests/test_ac9_key_fence.py`, `src/app/api/userRoutesProjectAllowlist.test.ts`, `src/components/willab/noAcousticNumbersOnUserSurfaces.test.ts`, `src/components/willab/mlc2ConsentGateIsServerDriven.test.ts`, `src/app/coach/audit/coachAuditFence.test.ts`.

## Workstream 10 — make the tests test the released schema (major)

Findings: FIX-1 through FIX-7, J2-1, J2-2, J2-3, J2-4, J2-5, LEGACY-3, LEGACY-5, I-5, I-6, G-6, J1-5.

Changes:
- Rebuild the "released" rehearsal lane from the manifest 0001..head with Supabase stubs (`storage.buckets`, `auth.uid()`, `uuid_generate_v4()`, `tasks_pool`, `recordings`, `snippets`) instead of narrow fixtures, so `v2_sessions`, `paragraphs`, `evidence_spans`, `candidate_sets`, `owner_principals`, `confident_voice_practice` carry their real columns, constraints, triggers and RLS (FIX-1, FIX-3). Add the fixture-subset test so the narrow copies cannot drift again.
- Re-assert in the released lane each guarantee the narrow lane relaxes: one active policy, `ml_speakers.identity_hash`, the split-assignment FK/CHECK (FIX-4). Turn the 143 untested trigger/CHECK names into a parametrized mutation test and a ratchet (FIX-5). Execute the eight `*_rehearsal_contract.py` SQL scripts in the tier instead of string-asserting them (FIX-6). Add `processing_authorization.py`, `take_feedback_policy_v3*.py`, `ml_*_export.py`, `db.py`, `mlc2_confidence_producer.py`, `orphan_audio_cleanup.py`, `practice_audio_objects.py` and `routes/` to `rehearsal_trigger.sh` (FIX-7).
- `migrate.py doctor` live mode handles column claims through `information_schema.columns` and keeps reporting after an error (FIX-2).
- Function grants: one migration revoking EXECUTE FROM `anon, authenticated` by exact signature on the 16 post-sweep functions that only revoked PUBLIC; the CI rule checks per function signature, not per file substring; `rls_guard.py` probes `authenticated` as well as `anon` (J2-1). Per-function `SET search_path` check (J2-3). Decide with the founder whether `prepare_confident_moment_bundle_v1` / `freeze_root_phrase_coverage_frame_v1` get a `service_role` grant or the two repository methods and D11 registry lines are deleted (J2-2). Bring `willab_pre_request()` into the manifest (J2-5). Fix the RLS-AUDIT.md claims (J2-4).
- Add a test that every `DROP TABLE` in the manifest is on an explicit, authorized allowlist; for 0281, record the authorization or replace the drop with a write guard for any environment where it has not yet run (LEGACY-3). Delete or rewrite docs/LEARNING-TRACE.md so it names only code that exists (LEGACY-5).
- Retention: for each operational Phase-1 purpose require a non-null `retention_control_version` and an active `data_retention_rules` row, and add the recording sweep to the sweeper chain once the schedule is signed (I-5). Record sha256 and byte size for every exported object and write a sidecar manifest beside the data (I-6).
- MLC-2 monitoring readiness must consume a monitor-run receipt, not an env boolean (J1-5).

Tests: `tests/test_fixture_drift.py`, `tests/test_confident_moment_production_fixtures.py::test_released_lane_tables_carry_every_column_and_constraint_of_their_manifest_create_table`, `::test_released_lane_rejects_a_second_active_policy`, `tests/test_released_guards_postgres.py`, `tests/test_migration_guard_inventory.py`, `tests/test_local_ci_mirror.py::test_rehearsal_trigger_paths_cover_every_module_that_invokes_a_rehearsed_rpc`, `tests/test_migrations.py::DoctorLiveModeTests`, `tests/test_migration_security_rules.py::NewFunctionsRevokeExecuteTests`, `tests/test_rpc_grants_match_python_callers_rehearsal_contract.py`, `tests/test_migrations_never_drop_tables.py`, `tests/test_docs_reference_existing_code.py`, `tests/test_retention_execution_postgres.py`, `tests/test_mlc2_confidence_readiness.py::test_monitoring_evidence_requires_recent_monitor_run`.

## Questions to put to the founder before you start, not after

1. G-1: the learning-exposure ack proxy is missing by founder decision (2026-09-15). Leave it. Confirm this is still the intent, because every eligibility predicate is structurally zero without it.
2. G-3: the MLC-2 consent route returns 410 and its unit tests bypass the guard with `__wrapped__`. Should the tests assert the deployed 410 instead, so the suite stops being green about a dead route?
3. D-1 and G-5: which of the two options in Workstream 5 for guest claim and for the eighth surface.
4. FE-4: are "Not confirmed", "Coach reviewed" and "Coach did not confirm this moment" signed-off copy?
5. J2-2: grant or delete.
6. LEGACY-3: was the 0281 drop of `training_labels`, `shadow_predictions`, `model_versions` authorized, and has it already run in production?

## Order of work

Workstreams 1, 2 and 7 first; they are the ones that change what is served or labelled today. Then 5 and 4, which decide whether any future release can be trusted and deleted from. Then 3, 6, 8, 9. Workstream 10 runs alongside everything because it is what makes the other nine provable.

## Definition of done for the whole effort

Every named test exists and fails on `origin/main` before your change and passes after; `scripts/local_ci.sh` is green including the rehearsal tier; each PR carries the decision-filter stamp and lists the finding ids it closes; no gate has been opened; no user-facing string has changed without a founder decision id in the PR.

## Job 1 review deltas (2026-09-22, read after the workstreams above)

The critical review (`job1_review.md`, same folder) re-verified the 8 blockers and the 25 majors in sections A, B, D, E, F, G. Severity changes that alter workstream scope: A-3 blocker→major; A-4 major→minor; A-7 major→minor; D-5 major→minor; G-5 major→minor; G-3 stays blocker for the consent half only (the speaker half is R-2). The 21 adjudications were all confirmed. Thirteen new findings (R-1..R-13) fold into the workstreams as follows:

| finding | severity | goes to | what to add |
|---|---|---|---|
| R-1 direct service_role INSERT grants on 18 canonical tables | major | Workstream 5 | revoke INSERT/UPDATE/DELETE from service_role on the 0296/0299 tables (RPC-only), plus `tests/test_canonical_tables_are_rpc_only_postgres.py` |
| R-2 record_mlc3_self_speaker_target_v1 violates ml_speakers NOT NULLs | major | Workstream 3 | redefine the RPC to write identity_version/identity_hash/created_by and binding_kind/binding_proof_hash/bound_by; test on the released lane, not the narrow fixture |
| R-3 user_self_report admissible as training-eligible supervision | major | Workstream 7 | drop user_self_report and derived_product_state from PROVENANCE_KEYS for confidence items; tighten ml_judgment_provenance_check to force evaluation_only |
| R-4 V2-frozen feedback sets blank V3 rows on read | major | Workstream 2 | ideal_text_changes.py:941-1005 branch fix + `test_a_v2_freeze_does_not_blank_the_v3_rows_it_predates` |
| R-5 voice_album_admissions never written; Album coach leg reads the overwritable row | major | Workstream 7 | write an admission row bound to the exact coach label id; Album membership reads admissions |
| R-6 permit for unregistered recording | minor | Workstream 3 | permit RPC joins processing_recording_attempts |
| R-7 purge subject graph references recording.session_id | minor (blocker if prod matches) | Workstream 4 | resolve the column against production `\d recordings` first; fix the function, rehearse on the released lane |
| R-8 re-cut guard ignores star finals and verdicts | minor | Workstream 6 | guard probes finals and verdicts, 409 |
| R-9 DPO export excludes by similarity not chip | minor | Workstream 6 | exclude on reason_chip |
| R-10 two taxonomy strings on confidence_self_reports | minor | Workstream 8 | one taxonomy constant on both owner paths |
| R-11 readiness says split ready with one owner | minor | Workstream 5 | floor of two assigned owners or one per partition |
| R-12 canary scope enforced only in the Flask route | minor | Workstream 8 | nonfounder_canonical_take_count health invariant |
| R-13 openai_chat_model / openai_copilot_model served from runtime_config unguarded | minor | Workstream 1 | same allowlist and gated writer as the surface keys |

Unknowns that need production access before Workstreams 3 and 4 start: PLF1_PROCESSING_AUTHORIZATION_MODE per Railway service (boot logs), `\d public.recordings`, `\d ml_speakers`, the runtime_config model keys, and the mlc3 rollout state. See `job1_review.md` section 4.

## How to hand a workstream to an implementation session

The files live in the repo at `docs/audits/2026-09-22-ml-provenance/`. Nothing is "attached": open the session in `backend-cursor` (or `frontend-cursor` for Workstream 9), paste the Job 2 or Job 3 prompt from `job_prompts.md` with `<N>` replaced, and add one line: "The audit report is `docs/audits/2026-09-22-ml-provenance/willab_ml_provenance_audit.html`, the engineer prompt is `engineer_prompt.md` and the critical review is `job1_review.md` in the same folder; read the Job 1 review deltas section before the workstream."
