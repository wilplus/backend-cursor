# Backend test module classification (2026-09-13)

| test module | tier | runs in CI? | result (this run) | cases | test last touched | subject last touched | verdict | why |
|---|---|---|---|---|---|---|---|---|
| test_ab_slide_pairs.py | F1-path | collected | 15 pass/0 skip | 15 | 2026-08-11 | 2026-08-11 | KEEP |  |
| test_acoustic_kpi.py | F1-path | collected | 46 pass/0 skip | 46 | 2026-08-28 | 2026-09-09 | KEEP | subject moved 2026-09-09, test last touched 2026-08-28 |
| test_analysis_state_broadcast.py | F1-path | collected | 8 pass/0 skip | 8 | 2026-08-26 | 2026-08-04 | KEEP |  |
| test_analysis_worker.py | F1-path | collected | 9 pass/0 skip | 9 | 2026-08-26 | 2026-08-29 | KEEP |  |
| test_audio_metrics_features.py | F1-path | collected | 10 pass/0 skip | 10 | 2026-06-04 | 2026-08-06 | KEEP | subject moved 2026-08-06, test last touched 2026-06-04 |
| test_audio_ref_resolver.py | F1-path | collected | 8 pass/0 skip | 8 | 2026-08-11 | 2026-09-09 | KEEP | subject moved 2026-09-09, test last touched 2026-08-11 |
| test_coach_snippet_save.py | F1-path | collected | 7 pass/0 skip | 7 | 2026-08-22 | n/a | KEEP |  |
| test_context_document.py | F1-path | collected | 17 pass/0 skip | 17 | 2026-08-24 | 2026-09-01 | KEEP | subject moved 2026-09-01, test last touched 2026-08-24 |
| test_create_take.py | F1-path | collected | 9 pass/0 skip | 8 | 2026-08-24 | 2026-08-29 | KEEP |  |
| test_cross_take_selection.py | F1-path | collected | 11 pass/0 skip | 11 | 2026-06-15 | 2026-08-22 | KEEP | subject moved 2026-08-22, test last touched 2026-06-15 |
| test_db_session_status.py | F1-path | collected | 4 pass/0 skip | 4 | 2026-06-05 | n/a | KEEP |  |
| test_delivery_alignment.py | F1-path | collected | 15 pass/0 skip | 15 | 2026-08-15 | 2026-08-15 | KEEP |  |
| test_delivery_cues.py | F1-path | collected | 26 pass/0 skip | 26 | 2026-08-29 | 2026-08-29 | KEEP |  |
| test_delivery_stars.py | F1-path | collected | 41 pass/0 skip | 41 | 2026-08-29 | 2026-08-29 | KEEP |  |
| test_dimension_registry.py | F1-path | collected | 40 pass/0 skip | 40 | 2026-08-06 | 2026-08-06 | KEEP |  |
| test_draft_delivery_lifecycle.py | F1-path | collected | 4 pass/0 skip | 4 | 2026-04-24 | 2026-04-24 | KEEP |  |
| test_eager_ideal_text.py | F1-path | collected | 30 pass/0 skip | 30 | 2026-08-24 | 2026-09-01 | KEEP | subject moved 2026-09-01, test last touched 2026-08-24 |
| test_f0_octave.py | F1-path | collected | 4 pass/0 skip | 4 | 2026-06-08 | 2026-08-06 | KEEP | subject moved 2026-08-06, test last touched 2026-06-08 |
| test_feedback_repository.py | F1-path | collected | 6 pass/0 skip | 6 | 2026-08-24 | 2026-08-29 | KEEP |  |
| test_feedback_supersession.py | F1-path | collected | 12 pass/0 skip | 12 | 2026-08-17 | 2026-08-29 | KEEP |  |
| test_ffmpeg_audio_extract.py | F1-path | collected | 3 pass/0 skip | 3 | 2026-04-22 | 2026-04-22 | KEEP | tiny module (≤3 cases) — merge candidate |
| test_golden_datasets.py | F1-path | collected | 10 pass/0 skip | 10 | 2026-08-04 | n/a | KEEP |  |
| test_guest_readout_video.py | F1-path | collected | 12 pass/0 skip | 12 | 2026-08-24 | 2026-08-29 | KEEP |  |
| test_ideal_bubble_backfill.py | F1-path | collected | 9 pass/0 skip | 9 | 2026-08-03 | 2026-08-26 | KEEP |  |
| test_ideal_decision_ledger.py | F1-path | collected | 30 pass/0 skip | 30 | 2026-08-18 | 2026-09-01 | KEEP | subject moved 2026-09-01, test last touched 2026-08-18 |
| test_ideal_text_annotations.py | F1-path | collected | 34 pass/0 skip | 34 | 2026-07-28 | 2026-08-03 | KEEP | subject moved 2026-08-03, test last touched 2026-07-28 |
| test_ideal_text_block.py | F1-path | collected | 8 pass/0 skip | 8 | 2026-08-24 | 2026-09-01 | KEEP | subject moved 2026-09-01, test last touched 2026-08-24 |
| test_ideal_text_parts.py | F1-path | collected | 119 pass/0 skip | 119 | 2026-08-26 | 2026-09-09 | KEEP | subject moved 2026-09-09, test last touched 2026-08-26 |
| test_ideal_text_quality_gate.py | F1-path | collected | 7 pass/0 skip | 7 | 2026-08-17 | 2026-08-17 | KEEP |  |
| test_ideal_text_read.py | F1-path | collected | 21 pass/0 skip | 21 | 2026-08-22 | 2026-09-01 | KEEP | subject moved 2026-09-01, test last touched 2026-08-22 |
| test_ideal_text_report.py | F1-path | collected | 6 pass/0 skip | 6 | 2026-08-22 | 2026-08-29 | KEEP |  |
| test_ideal_text_route.py | F1-path | collected | 9 pass/0 skip | 9 | 2026-08-11 | 2026-09-09 | KEEP | subject moved 2026-09-09, test last touched 2026-08-11 |
| test_ideal_text_slide_linkage.py | F1-path | collected | 13 pass/0 skip | 13 | 2026-08-29 | 2026-09-09 | KEEP | subject moved 2026-09-09, test last touched 2026-08-29 |
| test_ideal_text_variants.py | F1-path | collected | 19 pass/0 skip | 19 | 2026-08-24 | 2026-08-03 | KEEP |  |
| test_instant_ideal_text.py | F1-path | collected | 12 pass/0 skip | 12 | 2026-08-15 | 2026-08-26 | KEEP |  |
| test_intake_context.py | F1-path | collected | 38 pass/0 skip | 38 | 2026-07-26 | 2026-07-26 | KEEP |  |
| test_intervention_candidates.py | F1-path | collected | 75 pass/0 skip | 75 | 2026-08-26 | 2026-09-01 | KEEP | subject moved 2026-09-01, test last touched 2026-08-26 |
| test_job_queue_timeouts.py | F1-path | collected | 9 pass/0 skip | 9 | 2026-08-04 | 2026-08-28 | KEEP |  |
| test_jobs_status_route.py | F1-path | collected | 12 pass/0 skip | 12 | 2026-08-03 | 2026-09-01 | KEEP | subject moved 2026-09-01, test last touched 2026-08-03 |
| test_key_moments.py | F1-path | collected | 15 pass/0 skip | 15 | 2026-08-22 | 2026-08-29 | KEEP |  |
| test_key_points.py | F1-path | collected | 24 pass/0 skip | 24 | 2026-08-10 | 2026-09-09 | KEEP | subject moved 2026-09-09, test last touched 2026-08-10 |
| test_lab_analysis_dispatch.py | F1-path | collected | 7 pass/0 skip | 7 | 2026-08-27 | 2026-09-01 | KEEP | subject moved 2026-09-01, test last touched 2026-08-27 |
| test_lab_audio_intake.py | F1-path | collected | 5 pass/0 skip | 5 | 2026-08-21 | 2026-08-21 | KEEP |  |
| test_lab_recording.py | F1-path | collected | 30 pass/0 skip | 30 | 2026-08-21 | 2026-08-29 | KEEP |  |
| test_lab_recording_gate.py | F1-path | collected | 3 pass/0 skip | 3 | 2026-08-24 | 2026-08-24 | KEEP | tiny module (≤3 cases) — merge candidate |
| test_lab_recording_intake.py | F1-path | collected | 8 pass/0 skip | 8 | 2026-08-21 | 2026-08-21 | KEEP |  |
| test_lab_recording_persistence.py | F1-path | collected | 6 pass/0 skip | 6 | 2026-08-24 | 2026-08-29 | KEEP |  |
| test_lab_recording_response.py | F1-path | collected | 8 pass/0 skip | 8 | 2026-08-21 | 2026-08-29 | KEEP |  |
| test_lab_send.py | F1-path | collected | 9 pass/0 skip | 9 | 2026-08-24 | 2026-08-29 | KEEP |  |
| test_living_transcript.py | F1-path | collected | 106 pass/0 skip | 106 | 2026-08-22 | 2026-09-01 | KEEP | subject moved 2026-09-01, test last touched 2026-08-22 |
| test_manager_engine.py | F1-path | collected | 69 pass/0 skip | 69 | 2026-08-26 | 2026-08-26 | KEEP |  |
| test_min_content_gate.py | F1-path | collected | 10 pass/0 skip | 10 | 2026-07-15 | 2026-08-06 | KEEP | subject moved 2026-08-06, test last touched 2026-07-15 |
| test_moment_reference.py | F1-path | collected | 28 pass/0 skip | 28 | 2026-07-26 | 2026-09-01 | KEEP | subject moved 2026-09-01, test last touched 2026-07-26 |
| test_moment_suggestions.py | F1-path | collected | 105 pass/0 skip | 105 | 2026-08-29 | 2026-09-09 | FIX | imports services.moment_direction which no longer exists (guarded skip) |
| test_moment_suggestions_funnel.py | F1-path | collected | 3 pass/0 skip | 3 | 2026-08-10 | n/a | KEEP | tiny module (≤3 cases) — merge candidate |
| test_openai_client_timeouts.py | F1-path | collected | 6 pass/0 skip | 6 | 2026-08-03 | 2026-08-22 | KEEP |  |
| test_openai_report_progress.py | F1-path | collected | 3 pass/0 skip | 3 | 2026-08-22 | 2026-08-22 | KEEP | tiny module (≤3 cases) — merge candidate |
| test_orphan_sweep_and_concurrency.py | F1-path | collected | 23 pass/0 skip | 23 | 2026-08-06 | 2026-09-01 | KEEP | subject moved 2026-09-01, test last touched 2026-08-06 |
| test_parallel.py | F1-path | collected | 14 pass/0 skip | 14 | 2026-08-21 | 2026-08-29 | KEEP |  |
| test_pause_count_exactness.py | F1-path | collected | 10 pass/0 skip | 10 | 2026-08-06 | 2026-08-06 | KEEP |  |
| test_per_slide_budget.py | F1-path | collected | 16 pass/0 skip | 16 | 2026-08-11 | 2026-08-26 | KEEP |  |
| test_pieces_slide_stickiness.py | F1-path | collected | 19 pass/0 skip | 19 | 2026-08-22 | 2026-08-29 | KEEP |  |
| test_pipeline_admin.py | F1-path | collected | 16 pass/0 skip | 16 | 2026-08-10 | 2026-08-10 | KEEP |  |
| test_pipeline_health.py | F1-path | collected | 17 pass/0 skip | 17 | 2026-08-06 | 2026-08-06 | KEEP |  |
| test_pipeline_job_retry.py | F1-path | collected | 2 pass/0 skip | 2 | 2026-08-26 | 2026-09-01 | KEEP | subject moved 2026-09-01, test last touched 2026-08-26; tiny module (≤3 cases) — merge candidate |
| test_pipeline_stage_execution.py | F1-path | collected | 5 pass/0 skip | 5 | 2026-08-28 | 2026-08-28 | KEEP |  |
| test_pipeline_timing.py | F1-path | collected | 12 pass/0 skip | 12 | 2026-08-18 | 2026-08-29 | KEEP |  |
| test_polish_as_suggestions.py | F1-path | collected | 9 pass/0 skip | 9 | 2026-08-15 | 2026-09-01 | KEEP | subject moved 2026-09-01, test last touched 2026-08-15 |
| test_power_phrase_ranking.py | F1-path | collected | 19 pass/0 skip | 19 | 2026-08-22 | 2026-08-29 | KEEP |  |
| test_presentation_change_intent.py | F1-path | collected | 7 pass/0 skip | 7 | 2026-08-19 | 2026-08-19 | KEEP |  |
| test_presentation_delete.py | F1-path | collected | 12 pass/0 skip | 12 | 2026-08-24 | 2026-09-01 | KEEP | subject moved 2026-09-01, test last touched 2026-08-24 |
| test_presentation_extract.py | F1-path | collected | 4 pass/0 skip | 4 | 2026-06-19 | n/a | KEEP |  |
| test_prior_take_changes.py | F1-path | collected | 24 pass/0 skip | 24 | 2026-08-04 | 2026-09-09 | KEEP | subject moved 2026-09-09, test last touched 2026-08-04 |
| test_processing_jobs.py | F1-path | collected | 34 pass/0 skip | 34 | 2026-08-28 | 2026-09-01 | KEEP | subject moved 2026-09-01, test last touched 2026-08-28 |
| test_project_setup.py | F1-path | collected | 5 pass/0 skip | 5 | 2026-08-24 | 2026-09-01 | KEEP | subject moved 2026-09-01, test last touched 2026-08-24 |
| test_projects.py | F1-path | collected | 5 pass/0 skip | 5 | 2026-08-24 | 2026-08-29 | KEEP |  |
| test_protected_phrases.py | F1-path | collected | 17 pass/0 skip | 17 | 2026-07-20 | 2026-08-26 | KEEP | subject moved 2026-08-26, test last touched 2026-07-20 |
| test_readout_context.py | F1-path | collected | 5 pass/0 skip | 5 | 2026-08-21 | 2026-08-21 | KEEP |  |
| test_readout_snippets.py | F1-path | collected | 5 pass/0 skip | 5 | 2026-08-22 | 2026-08-22 | KEEP |  |
| test_recording_feedback_scoring.py | F1-path | collected | 4 pass/0 skip | 4 | 2026-08-28 | 2026-08-28 | KEEP |  |
| test_recording_kind.py | F1-path | collected | 5 pass/0 skip | 5 | 2026-08-03 | n/a | KEEP |  |
| test_recording_persistence.py | F1-path | collected | 2 pass/0 skip | 2 | 2026-08-21 | 2026-08-21 | KEEP | tiny module (≤3 cases) — merge candidate |
| test_recording_piece_analysis.py | F1-path | collected | 5 pass/0 skip | 5 | 2026-08-28 | 2026-08-29 | KEEP |  |
| test_recording_prompt_intent.py | F1-path | collected | 11 pass/0 skip | 11 | 2026-08-06 | 2026-08-29 | KEEP |  |
| test_recording_transcript_persistence.py | F1-path | collected | 3 pass/0 skip | 3 | 2026-08-21 | 2026-08-21 | KEEP | tiny module (≤3 cases) — merge candidate |
| test_recording_transcription.py | F1-path | collected | 8 pass/0 skip | 8 | 2026-09-08 | 2026-09-08 | KEEP |  |
| test_rehearsal_roots.py | F1-path | collected | 4 pass/0 skip | 4 | 2026-08-18 | 2026-08-18 | KEEP |  |
| test_reread_fold.py | F1-path | collected | 18 pass/0 skip | 18 | 2026-08-26 | 2026-09-09 | KEEP | subject moved 2026-09-09, test last touched 2026-08-26 |
| test_resolve_audio_refs.py | F1-path | collected | 4 pass/0 skip | 4 | 2026-08-10 | 2026-09-09 | KEEP | subject moved 2026-09-09, test last touched 2026-08-10 |
| test_say_it_stronger.py | F1-path | collected | 41 pass/0 skip | 41 | 2026-08-28 | 2026-08-29 | KEEP |  |
| test_segmentation.py | F1-path | collected | 8 pass/0 skip | 8 | 2026-06-08 | 2026-08-06 | KEEP | subject moved 2026-08-06, test last touched 2026-06-08 |
| test_slide_boundary_metrics.py | F1-path | collected | 21 pass/0 skip | 21 | 2026-08-11 | 2026-08-11 | KEEP |  |
| test_slide_clock_offset.py | F1-path | collected | 22 pass/0 skip | 22 | 2026-07-26 | 2026-08-29 | KEEP | subject moved 2026-08-29, test last touched 2026-07-26 |
| test_slide_corrections.py | F1-path | collected | 11 pass/0 skip | 11 | 2026-08-11 | n/a | KEEP |  |
| test_slide_paragraphs.py | F1-path | collected | 21 pass/0 skip | 21 | 2026-08-14 | 2026-08-26 | KEEP |  |
| test_slide_word_split.py | F1-path | collected | 50 pass/0 skip | 50 | 2026-08-11 | 2026-08-14 | KEEP |  |
| test_snippet_salience.py | F1-path | collected | 21 pass/0 skip | 21 | 2026-06-06 | 2026-06-06 | KEEP |  |
| test_snippet_stickiness.py | F1-path | collected | 12 pass/0 skip | 12 | 2026-08-03 | 2026-08-04 | KEEP |  |
| test_speed_metric.py | F1-path | collected | 3 pass/0 skip | 3 | 2026-06-12 | 2026-08-29 | KEEP | subject moved 2026-08-29, test last touched 2026-06-12; tiny module (≤3 cases) — merge candidate |
| test_suggestion_feedback.py | F1-path | collected | 21 pass/0 skip | 21 | 2026-08-24 | 2026-09-09 | KEEP | subject moved 2026-09-09, test last touched 2026-08-24 |
| test_suggestion_quotes.py | F1-path | collected | 13 pass/0 skip | 13 | 2026-07-20 | 2026-08-22 | KEEP | subject moved 2026-08-22, test last touched 2026-07-20 |
| test_swap_detector.py | F1-path | collected | 26 pass/0 skip | 26 | 2026-08-15 | 2026-08-26 | KEEP |  |
| test_swap_offer.py | F1-path | collected | 21 pass/0 skip | 21 | 2026-08-13 | 2026-08-29 | KEEP |  |
| test_take_comparison.py | F1-path | collected | 7 pass/0 skip | 7 | 2026-06-26 | 2026-06-26 | KEEP |  |
| test_take_lifecycle.py | F1-path | collected | 5 pass/0 skip | 5 | 2026-08-27 | 2026-08-27 | KEEP |  |
| test_take_review.py | F1-path | collected | 13 pass/0 skip | 13 | 2026-08-26 | 2026-09-07 | KEEP | subject moved 2026-09-07, test last touched 2026-08-26 |
| test_tracked_changes.py | F1-path | collected | 8 pass/0 skip | 8 | 2026-08-14 | 2026-08-26 | KEEP |  |
| test_transcript_edit_route.py | F1-path | collected | 28 pass/0 skip | 28 | 2026-08-24 | 2026-08-24 | KEEP |  |
| test_user_ideal_edit.py | F1-path | collected | 23 pass/0 skip | 23 | 2026-08-04 | 2026-09-09 | KEEP | subject moved 2026-09-09, test last touched 2026-08-04 |
| test_verbal_markers.py | F1-path | collected | 36 pass/0 skip | 36 | 2026-08-05 | 2026-08-10 | KEEP |  |
| test_wave4_phase2.py | F1-path | collected | 13 pass/0 skip | 13 | 2026-06-11 | 2026-08-29 | KEEP | subject moved 2026-08-29, test last touched 2026-06-11 |
| test_wave4_slides.py | F1-path | collected | 19 pass/0 skip | 19 | 2026-08-03 | 2026-08-29 | KEEP |  |
| test_whisper_compress.py | F1-path | collected | 2 pass/0 skip | 2 | 2026-06-11 | 2026-08-29 | KEEP | subject moved 2026-08-29, test last touched 2026-06-11; tiny module (≤3 cases) — merge candidate |
| test_worker_fork_safety.py | F1-path | collected | 16 pass/0 skip | 16 | 2026-08-28 | 2026-08-28 | KEEP |  |
| tests/test_atomic_take_feedback_response.py | F1-path | collected | 2 pass/0 skip | 2 | 2026-08-29 | n/a | KEEP | tiny module (≤3 cases) — merge candidate |
| tests/test_coach_guidance_delivery_d3.py | F1-path | collected | 14 pass/0 skip | 14 | 2026-09-10 | 2026-09-10 | KEEP |  |
| tests/test_coach_guidance_delivery_d3_postgres.py | F1-path | collected; skips without live-DB DSN | 0 pass/14 skip | 13 | 2026-09-09 | n/a | MOVE to tests/integration (opt-in) | never runs in CI; needs a disposable Postgres DSN |
| tests/test_feedback_data_contract.py | F1-path | collected | 8 pass/0 skip | 8 | 2026-09-09 | 2026-09-09 | KEEP |  |
| tests/test_ideal_text_cold_open.py | F1-path | collected | 12 pass/0 skip | 12 | 2026-09-07 | 2026-09-09 | KEEP |  |
| tests/test_recording_roots.py | F1-path | collected | 7 pass/0 skip | 4 | 2026-09-07 | 2026-09-09 | KEEP |  |
| tests/test_rooting_phrase.py | F1-path | collected | 2 pass/0 skip | 2 | 2026-08-26 | 2026-08-26 | KEEP | tiny module (≤3 cases) — merge candidate |
| tests/test_rooting_phrase_qualification_postgres.py | F1-path | collected; skips without live-DB DSN | 0 pass/24 skip | 18 | 2026-09-08 | n/a | MOVE to tests/integration (opt-in) | never runs in CI; needs a disposable Postgres DSN |
| tests/test_rooting_phrase_qualification_v1.py | F1-path | collected | 12 pass/0 skip | 8 | 2026-09-08 | 2026-09-08 | KEEP |  |
| tests/test_rushed_phrase_endings_n1.py | F1-path | collected | 4 pass/0 skip | 4 | 2026-09-09 | 2026-09-09 | KEEP |  |
| tests/test_snippet_transcription.py | F1-path | collected | 2 pass/0 skip | 2 | 2026-09-09 | 2026-09-09 | KEEP | tiny module (≤3 cases) — merge candidate |
| tests/test_take_feedback_manager.py | F1-path | collected | 7 pass/0 skip | 7 | 2026-09-07 | 2026-09-07 | KEEP |  |
| tests/test_take_feedback_policy_v3.py | F1-path | collected | 7 pass/0 skip | 7 | 2026-08-29 | 2026-09-09 | KEEP | subject moved 2026-09-09, test last touched 2026-08-29 |
| tests/test_take_feedback_policy_v3_integration.py | F1-path | collected | 2 pass/0 skip | 2 | 2026-08-29 | n/a | KEEP | tiny module (≤3 cases) — merge candidate |
| tests/test_take_feedback_responses.py | F1-path | collected | 4 pass/0 skip | 4 | 2026-09-08 | 2026-09-08 | KEEP |  |
| tests/test_take_feedback_set.py | F1-path | collected | 1 pass/0 skip | 1 | 2026-09-07 | 2026-09-07 | KEEP | tiny module (≤3 cases) — merge candidate |
| test_annotation_capture.py | F2 | collected | 47 pass/0 skip | 47 | 2026-07-28 | 2026-08-29 | KEEP | subject moved 2026-08-29, test last touched 2026-07-28 |
| test_annotation_mode.py | F2 | collected | 8 pass/0 skip | 8 | 2026-08-26 | 2026-09-09 | KEEP | subject moved 2026-09-09, test last touched 2026-08-26 |
| test_candidate_capture.py | F2 | collected | 7 pass/0 skip | 7 | 2026-06-27 | 2026-06-27 | KEEP |  |
| test_coach_comment_drafter.py | F2 | collected | 20 pass/0 skip | 20 | 2026-08-26 | 2026-08-29 | KEEP |  |
| test_coach_publish_service.py | F2 | collected | 10 pass/0 skip | 10 | 2026-08-24 | 2026-08-24 | KEEP |  |
| test_coach_session.py | F2 | collected | 12 pass/0 skip | 12 | 2026-08-26 | 2026-08-29 | KEEP |  |
| test_coach_session_language.py | F2 | collected | 5 pass/0 skip | 5 | 2026-09-08 | n/a | KEEP |  |
| test_coach_video.py | F2 | collected | 7 pass/0 skip | 7 | 2026-08-29 | 2026-09-09 | KEEP | subject moved 2026-09-09, test last touched 2026-08-29 |
| test_coach_video_capture.py | F2 | collected | 9 pass/0 skip | 9 | 2026-08-22 | 2026-08-22 | KEEP |  |
| test_confidence_dataset.py | F2 | collected | 13 pass/0 skip | 13 | 2026-08-29 | 2026-08-29 | KEEP |  |
| test_confidence_evaluation.py | F2 | collected | 12 pass/0 skip | 12 | 2026-08-26 | 2026-08-29 | KEEP |  |
| test_confidence_labels.py | F2 | collected | 22 pass/0 skip | 22 | 2026-08-26 | 2026-08-26 | KEEP |  |
| test_confidence_review_policy.py | F2 | collected | 5 pass/0 skip | 5 | 2026-08-18 | 2026-08-29 | KEEP |  |
| test_confidence_review_status.py | F2 | collected | 5 pass/0 skip | 5 | 2026-08-18 | 2026-09-09 | KEEP | subject moved 2026-09-09, test last touched 2026-08-18 |
| test_confidence_reviews.py | F2 | collected | 19 pass/0 skip | 19 | 2026-08-17 | 2026-08-29 | KEEP |  |
| test_confidence_rollout.py | F2 | collected | 13 pass/0 skip | 13 | 2026-08-26 | 2026-08-26 | KEEP |  |
| test_confident_voice_practice.py | F2 | collected | 27 pass/0 skip | 27 | 2026-09-09 | 2026-09-09 | KEEP |  |
| test_drift_job.py | F2 | collected | 18 pass/0 skip | 18 | 2026-08-05 | 2026-08-06 | KEEP |  |
| test_drift_monitor.py | F2 | collected | 29 pass/0 skip | 29 | 2026-08-05 | 2026-08-05 | KEEP |  |
| test_label_quorum.py | F2 | collected | 54 pass/0 skip | 54 | 2026-08-26 | 2026-08-26 | KEEP |  |
| test_learning_exposure_route.py | F2 | collected | 3 pass/0 skip | 3 | 2026-08-27 | 2026-08-27 | KEEP | tiny module (≤3 cases) — merge candidate |
| test_learning_exposures.py | F2 | collected | 8 pass/0 skip | 8 | 2026-08-27 | 2026-08-27 | KEEP |  |
| test_master_document.py | F2 | collected | 27 pass/9 skip | 36 | 2026-08-24 | 2026-09-09 | FIX (drop 9 retired cases) | 9 cases skipped 'retired incumbent/challenger endpoint' |
| test_ml_dpo_loop.py | F2 | collected | 11 pass/0 skip | 11 | 2026-08-26 | 2026-08-26 | KEEP |  |
| test_mlc2_foundation.py | F2 | collected | 9 pass/0 skip | 9 | 2026-08-27 | 2026-08-27 | KEEP |  |
| test_rater_languages.py | F2 | collected | 7 pass/0 skip | 7 | 2026-09-08 | 2026-09-08 | KEEP |  |
| test_star_verdicts.py | F2 | collected | 34 pass/0 skip | 34 | 2026-08-29 | 2026-08-29 | KEEP |  |
| test_state_ratings.py | F2 | collected | 50 pass/0 skip | 50 | 2026-08-26 | 2026-08-26 | KEEP |  |
| test_training_deletion.py | F2 | collected | 7 pass/0 skip | 7 | 2026-08-24 | 2026-09-09 | KEEP | subject moved 2026-09-09, test last touched 2026-08-24 |
| test_vc_backfill.py | F2 | collected | 13 pass/0 skip | 13 | 2026-08-29 | 2026-08-29 | KEEP |  |
| test_voice_album.py | F2 | collected | 20 pass/0 skip | 20 | 2026-08-26 | 2026-08-29 | KEEP |  |
| tests/test_blind_review_media.py | F2 | collected | 6 pass/0 skip | 4 | 2026-09-09 | 2026-09-09 | KEEP |  |
| tests/test_coach_blind_gate.py | F2 | collected | 7 pass/0 skip | 7 | 2026-09-08 | 2026-09-08 | KEEP |  |
| tests/test_dataset_releases.py | F2 | collected | 11 pass/0 skip | 6 | 2026-08-27 | 2026-08-27 | KEEP |  |
| tests/test_first_client_refactor.py | F2 | collected | 3 pass/0 skip | 3 | 2026-09-09 | 2026-09-10 | KEEP | tiny module (≤3 cases) — merge candidate |
| tests/test_founder_confidence_comparison.py | F2 | collected | 5 pass/0 skip | 5 | 2026-08-24 | 2026-09-09 | KEEP | subject moved 2026-09-09, test last touched 2026-08-24 |
| tests/test_mlc2_confidence.py | F2 | collected | 7 pass/0 skip | 4 | 2026-08-27 | 2026-08-27 | KEEP |  |
| tests/test_mlc2_confidence_blind.py | F2 | collected | 8 pass/0 skip | 3 | 2026-08-27 | 2026-08-27 | KEEP | tiny module (≤3 cases) — merge candidate |
| tests/test_mlc2_confidence_cutover_integration.py | F2 | collected | 9 pass/0 skip | 6 | 2026-08-27 | 2026-08-27 | KEEP |  |
| tests/test_mlc2_confidence_producer.py | F2 | collected | 8 pass/0 skip | 5 | 2026-08-27 | 2026-08-27 | KEEP |  |
| tests/test_mlc2_confidence_readiness.py | F2 | collected | 22 pass/0 skip | 6 | 2026-08-28 | 2026-08-27 | KEEP |  |
| tests/test_mlc3_coach_inline_authoring_d5.py | F2 | collected | 16 pass/0 skip | 16 | 2026-09-09 | 2026-09-10 | KEEP |  |
| tests/test_mlc3_coach_inline_authoring_d5_postgres.py | F2 | collected; skips without live-DB DSN | 0 pass/12 skip | 12 | 2026-09-09 | n/a | MOVE to tests/integration (opt-in) | never runs in CI; needs a disposable Postgres DSN |
| tests/test_mlc3_dark_assignment_contract.py | F2 | collected | 6 pass/0 skip | 6 | 2026-08-30 | 2026-09-10 | KEEP | subject moved 2026-09-10, test last touched 2026-08-30 |
| tests/test_mlc3_dark_assignments_postgres.py | F2 | collected; skips without live-DB DSN | 0 pass/57 skip | 39 | 2026-08-30 | 2026-09-10 | MOVE to tests/integration (opt-in) | never runs in CI; needs a disposable Postgres DSN |
| tests/test_mlc3_exercise_foundation.py | F2 | collected | 12 pass/0 skip | 12 | 2026-08-30 | n/a | KEEP |  |
| tests/test_mlc3_first_client_feedback.py | F2 | collected | 3 pass/0 skip | 3 | 2026-09-10 | 2026-09-10 | KEEP | tiny module (≤3 cases) — merge candidate |
| tests/test_mlc3_first_client_service_d2.py | F2 | collected | 35 pass/0 skip | 25 | 2026-09-10 | 2026-09-10 | KEEP |  |
| tests/test_mlc3_first_client_service_postgres.py | F2 | collected; skips without live-DB DSN | 0 pass/73 skip | 26 | 2026-09-09 | n/a | MOVE to tests/integration (opt-in) | never runs in CI; needs a disposable Postgres DSN |
| tests/test_mlc3_founder_canary_monitor.py | F2 | collected | 5 pass/0 skip | 5 | 2026-09-09 | 2026-09-09 | KEEP |  |
| tests/test_mlc3_founder_canary_readiness.py | F2 | collected | 28 pass/0 skip | 28 | 2026-09-10 | 2026-09-09 | KEEP |  |
| tests/test_mlc3_founder_canary_readiness_postgres.py | F2 | collected; skips without live-DB DSN | 0 pass/9 skip | 8 | 2026-09-09 | n/a | MOVE to tests/integration (opt-in) | never runs in CI; needs a disposable Postgres DSN |
| tests/test_mlc3_general_service_monitor.py | F2 | collected | 4 pass/0 skip | 4 | 2026-09-10 | 2026-09-10 | KEEP |  |
| tests/test_mlc3_general_service_readiness.py | F2 | collected | 4 pass/0 skip | 4 | 2026-09-10 | 2026-09-10 | KEEP |  |
| tests/test_mlc3_general_user_service_d4.py | F2 | collected | 18 pass/0 skip | 18 | 2026-09-10 | 2026-09-10 | KEEP |  |
| tests/test_mlc3_general_user_service_d4_postgres.py | F2 | collected; skips without live-DB DSN | 0 pass/34 skip | 21 | 2026-09-10 | n/a | MOVE to tests/integration (opt-in) | never runs in CI; needs a disposable Postgres DSN |
| tests/test_mlc3_n1_source_pattern_postgres.py | F2 | collected; skips without live-DB DSN | 0 pass/34 skip | 10 | 2026-09-07 | 2026-09-10 | MOVE to tests/integration (opt-in) | never runs in CI; needs a disposable Postgres DSN |
| tests/test_mlc3_pilot_storage.py | F2 | collected | 7 pass/0 skip | 7 | 2026-09-09 | 2026-09-09 | KEEP |  |
| tests/test_voice_album_machine_quorum.py | F2 | collected | 1 pass/0 skip | 1 | 2026-08-29 | 2026-08-29 | KEEP | tiny module (≤3 cases) — merge candidate |
| test_acoustic_targets_deleted.py | fence | collected | 8 pass/0 skip | 8 | 2026-08-06 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_canonical_product.py | fence | collected | 4 pass/0 skip | 3 | 2026-08-24 | 2026-08-24 | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_coach_auth.py | fence | collected | 8 pass/0 skip | 8 | 2026-08-03 | 2026-08-03 | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_consent_endpoint.py | fence | collected | 10 pass/0 skip | 10 | 2026-08-03 | 2026-08-29 | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_data_foundation_canary.py | fence | collected | 3 pass/0 skip | 3 | 2026-08-27 | 2026-08-29 | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_delivery_layer.py | fence | collected | 22 pass/0 skip | 22 | 2026-08-26 | 2026-09-09 | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_entrypoint_python.py | fence | collected | 7 pass/0 skip | 7 | 2026-08-04 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_error_sanitization.py | fence | collected | 20 pass/0 skip | 20 | 2026-08-18 | 2026-08-03 | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_f1_observability.py | fence | collected | 4 pass/0 skip | 4 | 2026-06-27 | 2026-06-27 | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_ideal_text_confirmation.py | fence | collected | 10 pass/0 skip | 10 | 2026-08-26 | 2026-09-01 | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_jwks.py | fence | collected | 1 pass/0 skip | 1 | 2026-01-23 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_jwt_verify.py | fence | NOT COLLECTED | 0 pass/0 skip | 0 | 2026-01-23 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_ledger_acceptance_freeze.py | fence | collected | 3 pass/0 skip | 3 | 2026-08-17 | 2026-08-26 | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_local_ci_mirror.py | fence | collected | 9 pass/0 skip | 9 | 2026-08-11 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_lounge_kind_migration.py | fence | collected | 3 pass/0 skip | 3 | 2026-07-16 | 2026-08-24 | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_marker_hygiene.py | fence | collected | 21 pass/0 skip | 21 | 2026-07-27 | 2026-09-01 | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_master_doc_output_guards.py | fence | collected | 28 pass/0 skip | 28 | 2026-08-24 | 2026-08-29 | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_migration_security_rules.py | fence | collected | 11 pass/0 skip | 11 | 2026-08-04 | 2026-08-14 | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_migrations.py | fence | collected | 66 pass/0 skip | 66 | 2026-08-24 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_mlc2_consent_endpoint.py | fence | collected | 6 pass/0 skip | 6 | 2026-08-28 | 2026-08-29 | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_ops_guardrails.py | fence | collected | 43 pass/0 skip | 43 | 2026-08-03 | 2026-09-09 | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_optional_auth.py | fence | collected | 5 pass/0 skip | 5 | 2026-08-03 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_pieces_canonical.py | fence | collected | 29 pass/0 skip | 29 | 2026-08-03 | 2026-08-29 | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_project_ownership.py | fence | collected | 4 pass/0 skip | 4 | 2026-08-24 | 2026-08-24 | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_project_tenant_isolation.py | fence | collected | 2 pass/0 skip | 2 | 2026-08-27 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_prompt_registry.py | fence | collected | 4 pass/0 skip | 4 | 2026-08-04 | 2026-08-04 | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_provenance.py | fence | collected | 29 pass/0 skip | 29 | 2026-08-12 | 2026-08-10 | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_rate_limits.py | fence | collected | 33 pass/0 skip | 33 | 2026-08-29 | 2026-08-24 | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_rating_resume_is_own_only.py | fence | collected | 9 pass/0 skip | 9 | 2026-08-07 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_recording_lane_guards.py | fence | collected | 13 pass/0 skip | 13 | 2026-08-24 | 2026-09-09 | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_rls_guard.py | fence | collected | 18 pass/0 skip | 18 | 2026-08-04 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_schema_column_types.py | fence | collected | 4 pass/0 skip | 4 | 2026-08-06 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_session_globals_wiring.py | fence | collected | 5 pass/0 skip | 5 | 2026-08-06 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_session_summary_allowlist.py | fence | collected | 12 pass/0 skip | 12 | 2026-06-04 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_single_deliverable.py | fence | collected | 55 pass/0 skip | 55 | 2026-08-26 | 2026-09-09 | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_snippet_table_name.py | fence | collected | 8 pass/0 skip | 8 | 2026-08-10 | 2026-08-10 | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_snippet_value_resolution.py | fence | collected | 27 pass/0 skip | 27 | 2026-08-06 | 2026-08-06 | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_stress_snippets_retired.py | fence | collected | 3 pass/0 skip | 3 | 2026-08-10 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_stripe_not_our_product.py | fence | collected | 31 pass/0 skip | 31 | 2026-08-15 | 2026-08-15 | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_video_url_validation.py | fence | collected | 4 pass/0 skip | 4 | 2026-02-22 | 2026-02-22 | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_word_diff_gate.py | fence | collected | 17 pass/0 skip | 17 | 2026-05-28 | 2026-05-28 | KEEP (fence) | asserts a written invariant; age is irrelevant |
| tests/test_canonical_feedback_migration.py | fence | collected | 9 pass/0 skip | 9 | 2026-08-27 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| tests/test_learning_surface_exposure_migration.py | fence | collected | 8 pass/0 skip | 8 | 2026-08-27 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| tests/test_mlc2_confidence_migration.py | fence | collected | 7 pass/0 skip | 7 | 2026-08-27 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| tests/test_mlc2_confidence_readiness_migration.py | fence | collected | 4 pass/0 skip | 4 | 2026-08-28 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| tests/test_mlc2_confidence_rehearsal_contract.py | fence | collected | 3 pass/0 skip | 3 | 2026-08-27 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| tests/test_mlc2_confidence_slice4_migration.py | fence | collected | 8 pass/0 skip | 8 | 2026-08-28 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| tests/test_mlc2_confidence_slice4_rehearsal_contract.py | fence | collected | 2 pass/0 skip | 2 | 2026-08-27 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| tests/test_mlc2_confidence_slice6_rehearsal_contract.py | fence | collected | 2 pass/0 skip | 2 | 2026-08-27 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| tests/test_mlc2_consent_configuration_migration.py | fence | collected | 6 pass/0 skip | 6 | 2026-08-28 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| tests/test_mlc2_foundation_migration.py | fence | collected | 16 pass/0 skip | 16 | 2026-08-27 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| tests/test_mlc2_foundation_rehearsal_contract.py | fence | collected | 3 pass/0 skip | 3 | 2026-08-27 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| tests/test_mlc2_legacy_isolation.py | fence | collected | 6 pass/0 skip | 6 | 2026-08-27 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| tests/test_mlc2_pgcrypto_search_path_migration.py | fence | collected | 4 pass/0 skip | 4 | 2026-08-29 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| tests/test_mlc3_exercise_rehearsal_contract.py | fence | collected | 3 pass/0 skip | 3 | 2026-08-30 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| tests/test_owner_claim_audit_migration.py | fence | collected | 7 pass/0 skip | 7 | 2026-08-27 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| tests/test_phase1_compliance_contract.py | fence | collected | 9 pass/0 skip | 9 | 2026-08-29 | 2026-08-29 | KEEP (fence) | asserts a written invariant; age is irrelevant |
| tests/test_phase1_deletion_completion.py | fence | collected | 16 pass/0 skip | 16 | 2026-09-09 | 2026-09-10 | KEEP (fence) | asserts a written invariant; age is irrelevant |
| tests/test_phase1_deletion_rehearsal_contract.py | fence | collected | 2 pass/0 skip | 2 | 2026-08-29 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| tests/test_phase1_processing_rehearsal_contract.py | fence | collected | 2 pass/0 skip | 2 | 2026-08-29 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| tests/test_recording_attempt_migration.py | fence | collected | 6 pass/0 skip | 6 | 2026-08-27 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| tests/test_seven_surface_dataset_release_migration.py | fence | collected | 3 pass/0 skip | 3 | 2026-08-27 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| tests/test_seven_surface_readiness_migration.py | fence | collected | 3 pass/0 skip | 3 | 2026-08-27 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| tests/test_take_feedback_policy_v3_rehearsal_contract.py | fence | collected | 2 pass/0 skip | 2 | 2026-08-29 | n/a | KEEP (fence) | asserts a written invariant; age is irrelevant |
| test_training_import.py | retired | collected; ALL SKIP | 0 pass/62 skip | 62 | 2026-08-29 | 2026-09-09 | DELETE-CANDIDATE or FIX | 62/62 skipped 'legacy training imports intentionally disabled in Phase 1' |
| test_voice_confidence.py | retired | collected | 41 pass/34 skip | 75 | 2026-08-29 | 2026-08-29 | DELETE 34 retired cases | 34/40 cases skipped as 'retired sex-routed contract retained as historical test text' |
| test_best_presentation.py | retired? | collected | 52 pass/0 skip | 52 | 2026-08-22 | 2026-08-29 | DECIDE (Q) | Best Presentation is retired per L1 but the module is live code with 13 importers |
| test_arc_batch.py | scaffolding | collected | 6 pass/0 skip | 6 | 2026-08-24 | 2026-08-24 | KEEP (off-path) | valid but protects non-F1 surface |
| test_arc_entitlement.py | scaffolding | collected | 8 pass/0 skip | 8 | 2026-07-24 | 2026-07-24 | KEEP (off-path) | valid but protects non-F1 surface |
| test_arc_notifications.py | scaffolding | collected | 16 pass/0 skip | 16 | 2026-08-26 | 2026-08-26 | KEEP (off-path) | valid but protects non-F1 surface |
| test_arc_unlock.py | scaffolding | collected | 8 pass/0 skip | 8 | 2026-07-30 | n/a | KEEP (off-path) | valid but protects non-F1 surface |
| test_audit_intent.py | scaffolding | collected | 9 pass/0 skip | 9 | 2026-06-15 | 2026-06-15 | KEEP (off-path) | valid but protects non-F1 surface |
| test_auth_request.py | scaffolding | quarantined | 0 pass/0 skip | 1 | 2026-08-03 | n/a | QUARANTINE→FIX or DELETE | ignored by CI since 2026-08; needs stubs or removal |
| test_chat_intents.py | scaffolding | collected | 11 pass/0 skip | 11 | 2026-06-25 | 2026-06-25 | KEEP (off-path) | valid but protects non-F1 surface |
| test_chat_persist.py | scaffolding | collected | 12 pass/0 skip | 12 | 2026-08-29 | 2026-08-29 | KEEP (off-path) | valid but protects non-F1 surface |
| test_community_content.py | scaffolding | collected | 55 pass/0 skip | 55 | 2026-07-26 | 2026-09-01 | KEEP (off-path) | valid but protects non-F1 surface; subject moved 2026-09-01, test last touched 2026-07-26 |
| test_dad_jokes.py | scaffolding | collected | 5 pass/0 skip | 5 | 2026-06-25 | 2026-06-25 | KEEP (off-path) | valid but protects non-F1 surface |
| test_dev_bugs.py | scaffolding | collected | 43 pass/0 skip | 43 | 2026-07-27 | 2026-08-03 | KEEP (off-path) | valid but protects non-F1 surface; subject moved 2026-08-03, test last touched 2026-07-27 |
| test_dev_tasks.py | scaffolding | collected | 61 pass/0 skip | 61 | 2026-08-03 | 2026-08-22 | KEEP (off-path) | valid but protects non-F1 surface |
| test_domains.py | scaffolding | collected | 11 pass/0 skip | 11 | 2026-06-15 | 2026-06-15 | KEEP (off-path) | valid but protects non-F1 surface |
| test_email_threading.py | scaffolding | collected | 21 pass/0 skip | 21 | 2026-08-24 | 2026-08-24 | KEEP (off-path) | valid but protects non-F1 surface |
| test_explore_arc.py | scaffolding | collected | 6 pass/0 skip | 6 | 2026-08-24 | 2026-08-24 | KEEP (off-path) | valid but protects non-F1 surface |
| test_feeling_performance.py | scaffolding | collected | 11 pass/0 skip | 11 | 2026-06-15 | 2026-06-15 | KEEP (off-path) | valid but protects non-F1 surface |
| test_feelings.py | scaffolding | collected | 9 pass/0 skip | 9 | 2026-06-15 | 2026-06-15 | KEEP (off-path) | valid but protects non-F1 surface |
| test_goal_update.py | scaffolding | collected | 11 pass/0 skip | 11 | 2026-06-15 | 2026-06-15 | KEEP (off-path) | valid but protects non-F1 surface |
| test_intervention_spend.py | scaffolding | collected | 15 pass/0 skip | 15 | 2026-08-12 | 2026-08-12 | KEEP (off-path) | valid but protects non-F1 surface |
| test_interview_completion_gate.py | scaffolding | collected | 17 pass/0 skip | 17 | 2026-06-06 | 2026-05-28 | KEEP (off-path) | valid but protects non-F1 surface |
| test_journal.py | scaffolding | collected | 89 pass/0 skip | 89 | 2026-08-18 | 2026-08-19 | KEEP (off-path) | valid but protects non-F1 surface |
| test_journal_image.py | scaffolding | collected | 62 pass/0 skip | 62 | 2026-07-28 | 2026-09-01 | KEEP (off-path) | valid but protects non-F1 surface; subject moved 2026-09-01, test last touched 2026-07-28 |
| test_journey_messages.py | scaffolding | collected | 6 pass/0 skip | 6 | 2026-08-18 | 2026-09-09 | KEEP (off-path) | valid but protects non-F1 surface; subject moved 2026-09-09, test last touched 2026-08-18 |
| test_kpi_timeline.py | scaffolding | collected | 13 pass/0 skip | 13 | 2026-06-06 | 2026-06-06 | KEEP (off-path) | valid but protects non-F1 surface |
| test_life_panel.py | scaffolding | collected | 383 pass/0 skip | 383 | 2026-08-04 | 2026-08-29 | KEEP (off-path) | valid but protects non-F1 surface |
| test_life_setup_horizon_fold.py | scaffolding | collected | 52 pass/0 skip | 52 | 2026-08-01 | 2026-08-04 | KEEP (off-path) | valid but protects non-F1 surface |
| test_llm_usage.py | scaffolding | collected | 24 pass/0 skip | 24 | 2026-08-26 | 2026-08-29 | KEEP (off-path) | valid but protects non-F1 surface |
| test_lounge_messages.py | scaffolding | collected | 31 pass/0 skip | 31 | 2026-06-25 | 2026-08-24 | KEEP (off-path) | valid but protects non-F1 surface; subject moved 2026-08-24, test last touched 2026-06-25 |
| test_named_emotion.py | scaffolding | collected | 7 pass/0 skip | 7 | 2026-08-22 | 2026-08-22 | KEEP (off-path) | valid but protects non-F1 surface |
| test_next_session_icebreaker.py | scaffolding | collected | 30 pass/0 skip | 30 | 2026-06-06 | 2026-06-06 | KEEP (off-path) | valid but protects non-F1 surface |
| test_onboarding_opener.py | scaffolding | collected | 20 pass/0 skip | 20 | 2026-07-14 | 2026-08-29 | KEEP (off-path) | valid but protects non-F1 surface; subject moved 2026-08-29, test last touched 2026-07-14 |
| test_product_discovery.py | scaffolding | collected | 5 pass/0 skip | 5 | 2026-08-25 | 2026-08-25 | KEEP (off-path) | valid but protects non-F1 surface |
| test_rate_windows.py | scaffolding | collected | 17 pass/0 skip | 17 | 2026-08-06 | 2026-08-06 | KEEP (off-path) | valid but protects non-F1 surface |
| test_sentry.py | scaffolding | quarantined | 0 pass/0 skip | 0 | 2026-01-23 | n/a | QUARANTINE→FIX or DELETE | ignored by CI since 2026-08; needs stubs or removal |
| test_session_cadence.py | scaffolding | collected | 20 pass/0 skip | 20 | 2026-08-26 | 2026-08-26 | KEEP (off-path) | valid but protects non-F1 surface |
| test_session_previews.py | scaffolding | collected | 4 pass/0 skip | 4 | 2026-08-22 | n/a | KEEP (off-path) | valid but protects non-F1 surface |
| test_step2_peer_review.py | scaffolding | collected | 16 pass/0 skip | 16 | 2026-08-06 | 2026-08-17 | KEEP (off-path) | valid but protects non-F1 surface |
| test_strategy_export.py | scaffolding | collected | 12 pass/0 skip | 12 | 2026-07-27 | 2026-07-27 | KEEP (off-path) | valid but protects non-F1 surface |
| test_token_arc_charged.py | scaffolding | collected | 8 pass/0 skip | 8 | 2026-08-22 | 2026-08-22 | KEEP (off-path) | valid but protects non-F1 surface |
| test_token_pricing.py | scaffolding | collected | 100 pass/0 skip | 100 | 2026-08-22 | 2026-08-22 | KEEP (off-path) | valid but protects non-F1 surface |
| test_upsert_arbiters.py | scaffolding | collected | 3 pass/0 skip | 3 | 2026-08-06 | n/a | KEEP (off-path) | valid but protects non-F1 surface |
| test_user_patterns.py | scaffolding | collected | 14 pass/0 skip | 14 | 2026-08-15 | 2026-08-22 | KEEP (off-path) | valid but protects non-F1 surface |
| test_user_session_summary_phases.py | scaffolding | collected | 25 pass/0 skip | 25 | 2026-06-04 | n/a | KEEP (off-path) | valid but protects non-F1 surface |
| test_wave2_be.py | scaffolding | collected | 9 pass/0 skip | 9 | 2026-08-14 | 2026-07-15 | KEEP (off-path) | valid but protects non-F1 surface |
| test_wave3_be.py | scaffolding | collected | 11 pass/0 skip | 11 | 2026-08-24 | 2026-08-29 | KEEP (off-path) | valid but protects non-F1 surface |
| test_will_voice.py | scaffolding | collected | 13 pass/0 skip | 13 | 2026-06-06 | 2026-08-29 | KEEP (off-path) | valid but protects non-F1 surface; subject moved 2026-08-29, test last touched 2026-06-06 |
| tests/integration/test_api_seams.py | scaffolding | NOT COLLECTED | 0 pass/0 skip | 12 | 2026-08-03 | n/a | KEEP (off-path) | valid but protects non-F1 surface |
| tests/test_admin_user_directory.py | scaffolding | collected | 3 pass/0 skip | 3 | 2026-08-26 | 2026-08-26 | KEEP (off-path) | valid but protects non-F1 surface |
| tests/test_ceo_foundation.py | scaffolding | collected | 21 pass/0 skip | 21 | 2026-08-26 | 2026-08-27 | KEEP (off-path) | valid but protects non-F1 surface |
| tests/test_ceo_intelligence.py | scaffolding | collected | 10 pass/0 skip | 10 | 2026-08-26 | 2026-08-29 | KEEP (off-path) | valid but protects non-F1 surface |
| tests/test_ceo_work_items.py | scaffolding | collected | 9 pass/0 skip | 9 | 2026-08-25 | 2026-08-26 | KEEP (off-path) | valid but protects non-F1 surface |
| tests/test_processing_stages.py | scaffolding | collected | 3 pass/0 skip | 3 | 2026-08-26 | 2026-08-26 | KEEP (off-path) | valid but protects non-F1 surface |
