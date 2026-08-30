"""Reviewed allowlist for Phase-1 subject-data deletion.

The registry is deliberately code, not mutable database configuration.  A
deployment therefore cannot silently teach the purge worker how to delete a
new relation.  Source and database-catalog audits compare every discovered
subject-bearing relation with this manifest; an unknown relation becomes a
``review_required`` target.

``delete`` dependencies contain product/content state. ``retain`` entries are
minimal legal/security evidence and require an active retention rule at purge
time. ``external_review`` entries belong to a separately governed lineage
(currently the dark MLC-2 foundation) and fail closed if any matching rows
exist. ``non_subject`` relations are global configuration or actor/admin data,
not data belonging to the acquisition principal being purged.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Literal

Disposition = Literal["delete", "retain", "external_review"]
LocatorKind = Literal[
    "principal", "user", "project", "take", "recording", "snippet",
    "permit", "job", "speaker", "practice", "practice_attempt",
    "exercise_audio_lineage", "exercise_blind_packet"
]


@dataclass(frozen=True)
class PurgeDependency:
    code: str
    relation: str
    selector_column: str
    locator_kind: LocatorKind
    disposition: Disposition
    target_kind: str = "database_row"
    delete_order: int = 100
    retention_category: str | None = None


DEPENDENCIES: tuple[PurgeDependency, ...] = (
    # Durable delivery state is cancelled before deletion and contains no
    # evidence that must survive the request.
    PurgeDependency("phase1_outbox", "phase1_processing_outbox",
                    "processing_job_id", "job", "delete",
                    "processing_queue", 10),
    PurgeDependency("phase1_job_events", "phase1_processing_job_events",
                    "processing_job_id", "job", "external_review",
                    "processing_queue", 300),
    PurgeDependency("phase1_jobs", "phase1_processing_jobs",
                    "acquisition_principal_id", "principal", "delete",
                    "processing_queue", 20),
    PurgeDependency("policy_carryovers", "processing_job_carryovers",
                    "acquisition_principal_id", "principal", "delete",
                    "processing_queue", 20),
    PurgeDependency("runtime_jobs", "processing_jobs", "user_id", "user",
                    "delete", "processing_queue", 20),
    PurgeDependency("provider_operations", "processing_provider_operations",
                    "permit_id", "permit", "retain",
                    "provider_operation", 200, "processor_evidence"),
    PurgeDependency("orphan_metadata", "processing_orphan_objects",
                    "acquisition_principal_id", "principal", "delete",
                    "database_row", 15),
    PurgeDependency("coach_delivery", "coach_review_delivery_outbox",
                    "session_id", "take", "delete", "coach_packet", 25),
    PurgeDependency("coach_drafts", "coach_snippet_drafts", "session_id",
                    "take", "delete", "coach_packet", 25),
    PurgeDependency("coach_revisions", "coach_review_revisions", "session_id",
                    "take", "delete", "coach_packet", 30),

    # Exact user-facing evidence and derived state.
    PurgeDependency("feedback_exposure", "take_feedback_exposure", "session_id",
                    "take", "external_review", "derived_feedback", 300),
    PurgeDependency("feedback_self_report", "take_feedback_self_report",
                    "session_id", "take", "external_review",
                    "derived_feedback", 300),
    PurgeDependency("suggestion_feedback", "user_suggestion_feedback",
                    "session_id", "take", "delete", "derived_feedback", 35),
    PurgeDependency("moment_suggestions", "moment_suggestions",
                    "owner_principal_id", "principal", "delete",
                    "derived_feedback", 35),
    PurgeDependency("feedback_sets", "ideal_text_feedback_sets",
                    "take_session_id", "take", "delete", "derived_feedback", 35),
    PurgeDependency("star_verdicts", "star_verdicts", "session_id", "take",
                    "delete", "derived_feedback", 35),
    PurgeDependency("snippet_reviews", "snippet_confidence_reviews",
                    "session_id", "take", "delete", "derived_feedback", 35),
    PurgeDependency("peer_labels", "snippet_peer_labels", "session_id", "take",
                    "delete", "derived_feedback", 35),
    PurgeDependency("slide_corrections", "snippet_slide_corrections",
                    "session_id", "take", "delete", "derived_feedback", 35),
    PurgeDependency("transcript_edits", "user_transcript_edits", "session_id",
                    "take", "delete", "transcript", 40),
    PurgeDependency("snippets", "snippets", "session_id", "take", "delete",
                    "transcript", 45),
    # The pre-rename physical table contains rows from multiple producers.
    # The Phase-1 resolver cannot safely delete it without the exact producer
    # ownership predicate, so any match is routed to explicit review.
    PurgeDependency("legacy_snippets_table_review", "charisma_snippets",
                    "session_id", "take", "external_review", "transcript", 300),
    PurgeDependency("recordings", "recordings", "session_v2_id", "take",
                    "delete", "database_row", 50),
    PurgeDependency("recordings_v1", "recordings", "session_id", "take",
                    "delete", "database_row", 50),
    PurgeDependency("recording_feelings", "recording_feelings", "recording_id",
                    "recording", "delete", "database_row", 45),
    PurgeDependency("read_alignments", "read_alignments", "recording_id",
                    "recording", "delete", "database_row", 45),
    PurgeDependency("candidate_windows", "candidate_windows", "recording_id",
                    "recording", "delete", "derived_feedback", 45),
    PurgeDependency("evidence_spans", "evidence_spans", "recording_id",
                    "recording", "delete", "derived_feedback", 45),
    PurgeDependency("retired_stress_corpus", "stress_snippets", "recording_id",
                    "recording", "external_review", "dataset_lineage", 300),

    # Ideal Text/project data. Arc identifiers are the canonical project IDs.
    PurgeDependency("ideal_blocks", "ideal_text_blocks", "arc_id", "project",
                    "delete", "derived_feedback", 55),
    PurgeDependency("ideal_saves", "ideal_text_saves", "arc_id", "project",
                    "delete", "derived_feedback", 55),
    PurgeDependency("ideal_versions", "ideal_text_versions", "arc_id", "project",
                    "delete", "derived_feedback", 55),
    PurgeDependency("ideal_decisions", "ideal_decision_ledger", "arc_id",
                    "project", "delete", "derived_feedback", 55),
    PurgeDependency("ideal_compositions", "ideal_text_compositions", "arc_id",
                    "project", "delete", "derived_feedback", 55),
    PurgeDependency("ideal_composition_head", "ideal_text_composition_head",
                    "arc_id", "project", "delete", "derived_feedback", 55),
    PurgeDependency("ideal_part", "ideal_text_part", "arc_id", "project",
                    "delete", "derived_feedback", 55),
    PurgeDependency("ideal_part_revision", "ideal_text_part_revision", "arc_id",
                    "project", "external_review", "derived_feedback", 300),
    PurgeDependency("ideal_block_variants", "ideal_text_block_variants", "arc_id",
                    "project", "delete", "derived_feedback", 55),
    PurgeDependency("coach_ideal", "coach_arc_ideal_text", "arc_id", "project",
                    "delete", "coach_packet", 55),
    PurgeDependency("user_ideal_notes", "user_arc_ideal_notes", "arc_id",
                    "project", "delete", "derived_feedback", 55),
    PurgeDependency("best_cache", "best_presentation_cache", "arc_id", "project",
                    "delete", "cache", 55),
    PurgeDependency("best_edits", "best_presentation_edits", "arc_id", "project",
                    "delete", "derived_feedback", 55),
    PurgeDependency("coach_best_edits", "coach_best_presentation_edits", "arc_id",
                    "project", "delete", "coach_packet", 55),
    PurgeDependency("arc_context", "arc_context_documents", "arc_id", "project",
                    "delete", "database_row", 55),
    PurgeDependency("arc_acoustics", "arc_part_acoustics", "arc_id", "project",
                    "delete", "database_row", 55),

    # Account/profile and conversational product state.
    PurgeDependency("lounge", "lounge_messages", "user_id", "user", "delete",
                    "database_row", 60),
    PurgeDependency("settings", "user_settings", "user_id", "user", "delete",
                    "database_row", 60),
    PurgeDependency("student_details", "v2_student_details", "user_id", "user",
                    "delete", "database_row", 60),
    PurgeDependency("speaker_profile", "v2_speaker_profiles", "user_id", "user",
                    "delete", "database_row", 60),
    PurgeDependency("sniper_profile", "user_sniper_profile", "user_id", "user",
                    "delete", "database_row", 60),
    PurgeDependency("sniper_metrics", "session_sniper_metrics", "user_id", "user",
                    "delete", "database_row", 60),
    PurgeDependency("acoustic_baseline", "user_acoustic_baseline", "user_id",
                    "user", "delete", "database_row", 60),
    PurgeDependency("voice_album", "voice_album", "user_id", "user", "delete",
                    "derived_feedback", 60),
    PurgeDependency("voice_album_practice", "voice_album_practice",
                    "practice_attempt_id", "practice_attempt", "delete",
                    "derived_feedback", 60),
    PurgeDependency("voice_album_routing", "owner_voice_album_routing", "user_id",
                    "user", "delete", "derived_feedback", 60),
    PurgeDependency("practice", "confident_voice_practice", "id", "practice",
                    "delete", "derived_feedback", 60),
    PurgeDependency("practice_attempt", "confident_voice_practice_attempt",
                    "id", "practice_attempt", "delete", "derived_feedback", 60),
    PurgeDependency("user_audits", "user_audits", "user_id", "user", "delete",
                    "database_row", 60),
    PurgeDependency("uploaded_files", "user_uploaded_files", "user_id", "user",
                    "delete", "database_row", 60),
    PurgeDependency("journal_posts", "journal_post", "user_id", "user", "delete",
                    "database_row", 60),
    PurgeDependency("journal_community", "journal_community_post", "user_id",
                    "user", "delete", "database_row", 60),
    PurgeDependency("product_discoveries", "user_product_discoveries", "user_id",
                    "user", "delete", "database_row", 60),
    PurgeDependency("coaching_sessions", "coaching_sessions", "user_id", "user",
                    "delete", "database_row", 65),
    PurgeDependency("coaching_attempts", "coaching_attempts", "user_id", "user",
                    "delete", "database_row", 65),
    PurgeDependency("v2_sessions", "v2_sessions", "owner_principal_id",
                    "principal", "delete", "database_row", 80),
    PurgeDependency("legacy_attempts", "recording_attempts", "owner_principal_id",
                    "principal", "external_review", "database_row", 300),
    PurgeDependency("canonical_takes", "takes", "owner_principal_id",
                    "principal", "external_review", "database_row", 300),
    PurgeDependency("canonical_transition_events_review",
                    "processing_transition_events", "owner_principal_id",
                    "principal", "external_review", "database_row", 300),
    PurgeDependency("rejected_takes", "rejected_takes", "owner_principal_id",
                    "principal", "delete", "database_row", 80),
    PurgeDependency("projects", "projects", "owner_principal_id", "principal",
                    "delete", "database_row", 90),

    # Canonical intake coordinates are minimal immutable deletion evidence;
    # the bytes themselves are a separate storage target and are erased first.
    PurgeDependency("audio_metadata", "processing_audio_objects",
                    "acquisition_principal_id", "principal", "retain",
                    "database_row", 200, "deletion_evidence"),
    PurgeDependency("audio_deletion_evidence",
                    "processing_audio_object_deletion_events",
                    "acquisition_principal_id", "principal", "retain",
                    "database_row", 200, "deletion_evidence"),
    PurgeDependency("recording_boundary", "processing_recording_attempts",
                    "acquisition_principal_id", "principal", "retain",
                    "database_row", 200, "deletion_evidence"),

    # Minimal proof is retained only under an active exact retention rule.
    PurgeDependency("authorization_receipts", "processing_authorization_receipts",
                    "acquisition_principal_id", "principal", "retain",
                    "database_row", 200, "authorization_evidence"),
    PurgeDependency("authorization_snapshots", "processing_authorization_snapshots",
                    "acquisition_principal_id", "principal", "retain",
                    "database_row", 200, "authorization_evidence"),
    PurgeDependency("service_blocks", "processing_service_blocks",
                    "acquisition_principal_id", "principal", "retain",
                    "database_row", 200, "deletion_evidence"),
    PurgeDependency("provider_permits", "processing_provider_permits",
                    "acquisition_principal_id", "principal", "retain",
                    "provider_operation", 200, "processor_evidence"),
    PurgeDependency("ai_exposures", "ai_transparency_exposures",
                    "acquisition_principal_id", "principal", "retain",
                    "database_row", 200, "transparency_evidence"),
    PurgeDependency("legacy_terms", "user_consents", "user_id", "user",
                    "retain", "database_row", 200, "authorization_evidence"),
    PurgeDependency("legacy_terms_events", "user_consent_events", "user_id",
                    "user", "retain", "database_row", 200,
                    "authorization_evidence"),
    PurgeDependency("owner_identity", "owner_principals", "id", "principal",
                    "retain", "database_row", 200, "deletion_evidence"),
    PurgeDependency("owner_claim_source", "owner_claim_events",
                    "source_owner_principal_id", "principal", "retain",
                    "database_row", 200, "deletion_evidence"),
    PurgeDependency("owner_claim_target", "owner_claim_events",
                    "target_owner_principal_id", "principal", "retain",
                    "database_row", 200, "deletion_evidence"),

    # These historical/mixed-purpose paths are attributable, but deleting
    # them automatically would invent retention and dependency conclusions.
    # A matching row therefore blocks completion for an explicit resolver.
    PurgeDependency("v1_sessions_review", "recording_sessions", "user_id",
                    "user", "external_review", "database_row", 300),
    PurgeDependency("moment_unlocks_review", "moment_unlocks", "user_id",
                    "user", "external_review", "database_row", 300),
    PurgeDependency("student_profile_review", "student_profile", "user_id",
                    "user", "external_review", "database_row", 300),
    PurgeDependency("student_overrides_review", "v2_student_overrides",
                    "user_id", "user", "external_review", "database_row", 300),
    PurgeDependency("student_memory_review", "v2_student_coaching_memory",
                    "user_id", "user", "external_review", "database_row", 300),
    PurgeDependency("student_post_questions_review",
                    "v2_student_post_recording_questions", "user_id", "user",
                    "external_review", "database_row", 300),
    PurgeDependency("admin_session_override_review", "admin_session_overrides",
                    "user_id", "user", "external_review", "database_row", 300),
    PurgeDependency("admin_student_draft_review", "admin_student_send_drafts",
                    "user_id", "user", "external_review", "coach_packet", 300),
    PurgeDependency("admin_annotation_review", "admin_annotation_events",
                    "user_id", "user", "external_review", "coach_packet", 300),
    PurgeDependency("content_exposure_review", "content_exposures", "user_id",
                    "user", "external_review", "derived_feedback", 300),
    PurgeDependency("few_shot_review", "few_shot_retrievals", "user_id",
                    "user", "external_review", "dataset_lineage", 300),
    PurgeDependency("dimension_evaluation_review", "dimension_evaluations",
                    "user_id", "user", "external_review", "dataset_lineage", 300),
    PurgeDependency("intervention_arm_review", "intervention_arms", "user_id",
                    "user", "external_review", "dataset_lineage", 300),
    PurgeDependency("confidence_labels_review", "confidence_labels",
                    "snippet_id", "snippet", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("confidence_rereview", "confidence_rereview_queue",
                    "owner_user_id", "user", "external_review",
                    "coach_packet", 300),
    PurgeDependency("label_revision_review", "label_revision", "snippet_id",
                    "snippet", "external_review", "dataset_lineage", 300),
    PurgeDependency("intervention_decisions_review", "intervention_decisions",
                    "arc_id", "project", "external_review",
                    "derived_feedback", 300),
    PurgeDependency("performance_scores_review", "performance_scores",
                    "recording_id", "recording", "external_review",
                    "derived_feedback", 300),
    PurgeDependency("pre_answers_review", "pre_recording_answers",
                    "recording_session_id", "take", "external_review",
                    "database_row", 300),
    PurgeDependency("post_answers_review", "post_recording_answers",
                    "session_id", "take", "external_review",
                    "database_row", 300),
    PurgeDependency("session_commands_review", "session_command_options",
                    "session_id", "take", "external_review",
                    "database_row", 300),
    PurgeDependency("v2_reports_review", "v2_reports", "session_v2_id", "take",
                    "external_review", "database_row", 300),
    PurgeDependency("admin_annotation_log_review", "admin_annotations_log",
                    "user_id", "user", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("admin_uploaded_reference_review",
                    "admin_uploaded_reference_videos", "user_id", "user",
                    "external_review", "dataset_lineage", 300),
    PurgeDependency("copilot_upload_jobs_review",
                    "copilot_reference_upload_jobs", "student_user_id", "user",
                    "external_review", "processing_queue", 300),
    PurgeDependency("arc_deliveries_review", "arc_batch_deliveries", "user_id",
                    "user", "external_review", "database_row", 300),
    PurgeDependency("arc_purchases_review", "arc_purchases", "user_id", "user",
                    "external_review", "database_row", 300),
    PurgeDependency("stripe_grants_review", "stripe_checkout_credit_grants",
                    "user_id", "user", "external_review", "database_row", 300),
    PurgeDependency("student_tasks_review", "tasks", "user_id", "user",
                    "external_review", "database_row", 300),
    PurgeDependency("coaching_directives_review", "coaching_directives_queue",
                    "user_id", "user", "external_review", "database_row", 300),
    PurgeDependency("coach_ai_review", "coach_ai_conversations", "user_id",
                    "user", "external_review", "database_row", 300),
    PurgeDependency("admin_archive_review", "admin_copilot_queue_archives",
                    "user_id", "user", "external_review", "database_row", 300),
    PurgeDependency("token_ledger_review", "token_ledger", "user_id", "user",
                    "retain", "database_row", 300, "financial_evidence"),
    PurgeDependency("llm_usage_review", "llm_usage", "user_id", "user",
                    "retain", "database_row", 300, "financial_evidence"),

    # The Life Panel owns a separate reviewed hard-delete workflow. Until it
    # is transactionally connected to this resolver, matching data blocks the
    # Phase-1 purge instead of being silently skipped or deleted out of order.
    PurgeDependency("life_consent_review", "life_consent", "user_id", "user",
                    "external_review", "database_row", 300),
    PurgeDependency("life_setup_review", "life_setup", "user_id", "user",
                    "external_review", "database_row", 300),
    PurgeDependency("life_notes_review", "life_notes", "user_id", "user",
                    "external_review", "database_row", 300),
    PurgeDependency("life_cases_review", "life_cases", "user_id", "user",
                    "external_review", "database_row", 300),
    PurgeDependency("life_items_review", "life_items", "user_id", "user",
                    "external_review", "database_row", 300),
    PurgeDependency("life_strategy_review", "life_strategy", "user_id", "user",
                    "external_review", "database_row", 300),
    PurgeDependency("life_proposals_review", "life_proposals", "user_id", "user",
                    "external_review", "database_row", 300),
    PurgeDependency("life_applications_review", "life_applications", "user_id",
                    "user", "external_review", "database_row", 300),
    PurgeDependency("life_days_review", "life_days", "user_id", "user",
                    "external_review", "database_row", 300),
    PurgeDependency("life_weeks_review", "life_weeks", "user_id", "user",
                    "external_review", "database_row", 300),
    PurgeDependency("life_period_reviews_review", "life_period_reviews",
                    "user_id", "user", "external_review", "database_row", 300),
    PurgeDependency("life_setup_documents_review", "life_setup_documents",
                    "user_id", "user", "external_review", "database_row", 300),
    PurgeDependency("life_push_subscriptions_review", "life_push_subscriptions",
                    "user_id", "user", "external_review", "database_row", 300),
    PurgeDependency("life_reminder_settings_review", "life_reminder_settings",
                    "user_id", "user", "external_review", "database_row", 300),
    PurgeDependency("life_reminder_log_review", "life_reminder_log", "user_id",
                    "user", "external_review", "database_row", 300),
    PurgeDependency("life_user_copy_review", "life_user_copy", "user_id", "user",
                    "external_review", "database_row", 300),

    # MLC-2 is dark, but any lineage already attached to this principal must
    # enter its separately reviewed exceptional-purge traversal.
    PurgeDependency("ml_speaker_binding", "ml_speaker_principals",
                    "acquisition_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("ml_purge", "ml_purge_requests",
                    "acquisition_principal_id", "principal", "external_review",
                    "model_lineage", 300),
    PurgeDependency("v3_shadow", "take_feedback_policy_v3_shadow_frames",
                    "acquisition_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("v3_detector_reconciliation",
                    "take_feedback_detector_reconciliation",
                    "take_session_id", "take", "external_review",
                    "dataset_lineage", 300),

    # Canonical feedback/learning ledgers are append-only by design. Their
    # subject paths are fully classified here, but they enter the separately
    # reviewed exceptional-purge traversal instead of ordinary DELETE calls.
    PurgeDependency("canonical_transcript_versions", "transcript_versions",
                    "owner_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("canonical_slides", "slides", "owner_principal_id",
                    "principal", "external_review", "dataset_lineage", 300),
    PurgeDependency("canonical_paragraphs", "paragraphs",
                    "owner_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("canonical_acoustics", "acoustic_feature_snapshots",
                    "owner_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("canonical_candidate_sets", "candidate_sets",
                    "owner_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("canonical_machine_predictions", "machine_predictions",
                    "owner_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("canonical_generation_runs", "generation_runs",
                    "owner_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("canonical_processing_stage_runs", "processing_stage_runs",
                    "owner_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("canonical_split_assignments", "dataset_split_assignments",
                    "owner_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("canonical_release_items", "dataset_release_items",
                    "owner_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("canonical_dataset_exclusions", "dataset_exclusions",
                    "owner_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("learning_surface_presentations",
                    "learning_surface_presentations", "owner_principal_id",
                    "principal", "external_review", "dataset_lineage", 300),
    PurgeDependency("learning_surface_exposure_receipts",
                    "learning_surface_exposure_receipts", "owner_principal_id",
                    "principal", "external_review", "dataset_lineage", 300),
    PurgeDependency("ml_canonical_events", "ml_canonical_events",
                    "acquisition_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("ml_object_artifacts", "ml_object_artifacts",
                    "acquisition_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("ml_evidence_spans", "ml_evidence_spans",
                    "acquisition_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("ml_consent_events", "ml_consent_events",
                    "acquisition_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("ml_consent_snapshots", "ml_consent_snapshots",
                    "acquisition_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("ml_product_actions", "ml_product_actions",
                    "acquisition_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("ml_candidate_sets", "ml_candidate_sets",
                    "acquisition_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("ml_confidence_producer_receipts",
                    "ml_confidence_producer_receipts",
                    "acquisition_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("exercise_authorization_checks",
                    "exercise_authorization_checks",
                    "acquisition_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("exercise_learning_profiles", "learning_profiles",
                    "speaker_id", "speaker", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("exercise_audio_lineages", "exercise_audio_lineages",
                    "id", "exercise_audio_lineage", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("exercise_blind_packets", "exercise_blind_packets",
                    "id", "exercise_blind_packet", "external_review",
                    "coach_packet", 300),
    PurgeDependency("exercise_blind_packet_events",
                    "exercise_blind_packet_events", "blind_packet_id",
                    "exercise_blind_packet", "external_review",
                    "coach_packet", 300),
    # M3-3 dark frames carry direct, RPC-derived acquisition ownership. They
    # are inventoried even though serving/learning is disabled. Matching rows
    # block purge completion pending the separate canonical retention review.
    # Observations/history (including exclusion IDs) cannot cross principals;
    # the deferred finalizer enforces this. Shared profile identity is already
    # inventoried above by speaker. Any future cross-principal feature reuse
    # needs explicit authorization AND a new dependency traversal before use.
    PurgeDependency("exercise_profile_observations", "learning_profile_observations",
                    "acquisition_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("exercise_feature_snapshots", "exercise_selection_feature_snapshots",
                    "acquisition_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("exercise_candidate_sets", "exercise_candidate_sets",
                    "acquisition_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("exercise_candidates", "exercise_candidates",
                    "acquisition_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("exercise_assignments", "exercise_assignments",
                    "acquisition_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("exercise_randomization", "exercise_randomization_assignments",
                    "acquisition_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("exercise_requests", "exercise_requests",
                    "acquisition_principal_id", "principal", "external_review",
                    "coach_packet", 300),

    # Historical corpora and review stores are frozen or mixed-purpose. They
    # are named explicitly so catalog audit is complete, while their matches
    # block until a dedicated retention/purge decision exists.
    PurgeDependency("legacy_acoustic_labels", "acoustic_labels",
                    "recording_id", "recording", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("legacy_recording_review_annotations",
                    "recording_review_annotations", "session_id", "take",
                    "external_review", "dataset_lineage", 300),
    PurgeDependency("legacy_recording_reviews", "recording_reviews",
                    "session_id", "take", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("legacy_reflection_clips", "reflection_clips", "user_id",
                    "user", "external_review", "dataset_lineage", 300),
    PurgeDependency("legacy_shadow_predictions", "shadow_predictions",
                    "session_id", "take", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("legacy_snippet_labels", "snippet_labels", "snippet_id",
                    "snippet", "external_review", "dataset_lineage", 300),
    PurgeDependency("legacy_strong_sides", "strong_sides_library", "user_id",
                    "user", "external_review", "dataset_lineage", 300),
    PurgeDependency("legacy_training_labels", "training_labels", "session_id",
                    "take", "external_review", "dataset_lineage", 300),

    # Legacy practice/game state is ordinary user-owned product data where the
    # physical schema exposes an exact account coordinate.
    PurgeDependency("legacy_game_saves", "game_saves", "user_id", "user",
                    "delete", "database_row", 70),
    PurgeDependency("legacy_focus_questions", "v2_focus_questions", "user_id",
                    "user", "delete", "database_row", 70),
    PurgeDependency("legacy_focus_tasks", "v2_focus_tasks", "user_id", "user",
                    "delete", "database_row", 70),
    PurgeDependency("legacy_warm_up_tasks", "v2_warm_up_tasks", "user_id",
                    "user", "delete", "database_row", 70),
)


# Relations used by runtime code but not owned by the student/acquisition
# principal being purged. Keeping them here makes the source audit explicit.
NON_SUBJECT_RELATIONS: frozenset[str] = frozenset({
    "admin_users", "coach_users", "admin_annotation_export_runs",
    "admin_notifications", "arc_invite_codes", "casual_voice_benchmarks",
    "chat_question_pool", "coach_video_assets",
    "dad_jokes", "diagnostic_exercise",
    "model_training_runs", "post_recording_questions",
    "pre_recording_questions", "professional_notes_specific_questions",
    "reference_distribution", "runtime_config", "slide_ab_verdicts",
    "tasks_pool", "v2_metric_definitions", "v2_metric_questions",
    "v2_universal_questions",
    "ceo_admin_view_state", "ceo_analysis_runs", "ceo_artifact_comments",
    "ceo_artifact_revisions", "ceo_artifacts", "ceo_bugs", "ceo_features",
    "ceo_projects", "ceo_reevaluation_requests", "ceo_source_snapshots",
    "ceo_tasks", "ceo_timeline_events", "dev_bugs", "dev_tasks",
    "data_purge_requests", "data_purge_targets", "data_purge_events",
    "data_rights_requests", "data_retention_rules",
    "processing_policy_versions", "processing_policy_purposes",
    "processing_purpose_registry", "processing_legal_artifacts",
    "processing_authorization_receipt_purposes",
    "exercise_need_contracts", "exercise_media_objects",
    "exercise_definitions", "exercise_versions",
    "exercise_catalog_snapshots", "exercise_catalog_snapshot_items",
    "exercise_media_availability_checks",
    "data_purge_inventory_manifests", "processing_provider_deletion_contracts",
    "processing_provider_deletion_contract_events", "detector_version",
})

# Child relations whose reviewed foreign key deletes with an allowlisted
# parent. They are not queried independently by the resolver, but they remain
# explicit so the dependency audit cannot mistake them for global data.
CASCADE_RELATIONS: frozenset[str] = frozenset({
    "coaching_attempt_annotations", "journal_post_image",
})

# Runtime-selected relation names that a literal-only source scan cannot see.
# Tests bind these values to the defining modules so a new dynamic path fails
# closed until the registry is deliberately updated.
DYNAMIC_RUNTIME_RELATIONS: frozenset[str] = frozenset({
    "charisma_snippets", "snippets", "student_profile",
    "user_sniper_profile", "v2_student_details", "token_ledger", "llm_usage",
    "life_consent", "life_setup", "life_notes", "life_cases", "life_items",
    "life_strategy", "life_proposals", "life_applications", "life_days",
    "life_weeks", "life_period_reviews", "life_setup_documents",
    "life_push_subscriptions", "life_reminder_settings", "life_reminder_log",
    "life_user_copy", "dev_bugs", "dev_tasks",
})


def classified_relations() -> frozenset[str]:
    return (
        frozenset(item.relation for item in DEPENDENCIES)
        | NON_SUBJECT_RELATIONS
        | CASCADE_RELATIONS
    )


def dependency_manifest_sha256() -> str:
    payload = [asdict(item) for item in DEPENDENCIES]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def dependency_by_code(code: str) -> PurgeDependency | None:
    return next((item for item in DEPENDENCIES if item.code == code), None)
