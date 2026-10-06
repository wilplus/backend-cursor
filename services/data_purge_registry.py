"""Reviewed allowlist for Phase-1 subject-data deletion.

The registry is deliberately code, not mutable database configuration.  A
deployment therefore cannot silently teach the purge worker how to delete a
new relation.  Source and database-catalog audits compare every discovered
subject-bearing relation with this manifest; an unknown relation becomes a
``review_required`` target.

``delete`` dependencies contain product/content state. ``retain`` entries are
minimal legal/security evidence and require an active retention rule at purge
time. A ``tombstone`` entry is a row retained evidence still points at: its
user content is wiped and the bare row is kept, under the same rule. ``external_review`` entries belong to a separately governed lineage
(currently the dark MLC-2 foundation) and fail closed if any matching rows
exist. ``non_subject`` relations are global configuration or actor/admin data,
not data belonging to the acquisition principal being purged.

A RULED dependency (``ruled_by`` set) is one retention schedule v1.4 decided
(legal/phase1-2026.1/20-retention-schedule-v1.4-product-records-and-job-evidence-DRAFT.md;
founder 2026-10-05, decisions log N48.4 Q15 A): product records are deleted
with the account or the project, job evidence is kept 12 months. It acts on
its ``disposition`` only while the signed rule it names is ACTIVE in
``data_retention_rules``; until the founder runs
``scripts/phase1_retention_rules_v1_4.sql`` it acts exactly as
``before_rule`` says, which is what it did before v1.4 (fail closed).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from typing import Literal

Disposition = Literal["delete", "retain", "tombstone", "external_review"]
LocatorKind = Literal[
    "principal", "user", "project", "take", "recording", "snippet",
    "permit", "job", "speaker", "practice", "practice_attempt",
    "exercise_audio_lineage", "exercise_blind_packet", "delivery_job"
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
    #: The rule_code of the signed retention row that decided this
    #: dependency (retention schedule v1.4). Until a row with this rule_code
    #: and this `retention_category` is active, the dependency acts exactly
    #: as `before_rule` says; once it is, `disposition` applies.
    ruled_by: str | None = None
    before_rule: Disposition = "external_review"


#: Retention schedule v1.4's two rules (founder 2026-10-05, N48.4 Q15 A),
#: seeded by scripts/phase1_retention_rules_v1_4.sql once the PDF is signed.
#: A product record goes with the account or the project; job evidence is
#: kept 12 months from when it was recorded, then the scheduled clean-up
#: deletes it.
PRODUCT_RECORDS = "product_records"
PRODUCT_RECORDS_RULE = "product-records-v1"
JOB_EVIDENCE = "job_evidence"
JOB_EVIDENCE_RULE = "job-evidence-v1"
RULE_CATEGORY: dict[str, str] = {
    PRODUCT_RECORDS_RULE: PRODUCT_RECORDS,
    JOB_EVIDENCE_RULE: JOB_EVIDENCE,
}


def _product_record(code: str, relation: str, selector_column: str,
                    locator_kind: LocatorKind, target_kind: str,
                    delete_order: int = 300) -> PurgeDependency:
    """Deleted with the account or the project, once product-records-v1 is
    active; until then it stops the erasure for review, as before v1.4."""
    return PurgeDependency(code, relation, selector_column, locator_kind,
                           "delete", target_kind, delete_order,
                           PRODUCT_RECORDS, ruled_by=PRODUCT_RECORDS_RULE)


def _job_evidence(code: str, relation: str, selector_column: str,
                  locator_kind: LocatorKind, target_kind: str,
                  delete_order: int = 300,
                  before_rule: Disposition = "external_review",
                  ) -> PurgeDependency:
    """Kept through an erasure under job-evidence-v1 (12 months from when it
    was recorded), once that rule is active; until then as before v1.4."""
    return PurgeDependency(code, relation, selector_column, locator_kind,
                           "retain", target_kind, delete_order, JOB_EVIDENCE,
                           ruled_by=JOB_EVIDENCE_RULE, before_rule=before_rule)


def before_its_rule(dependency: PurgeDependency) -> PurgeDependency:
    """The dependency as it acts while its v1.4 rule is not active: exactly
    the registry entry it had before v1.4 (same disposition, no category)."""
    if not dependency.ruled_by:
        return dependency
    return replace(dependency, disposition=dependency.before_rule,
                   retention_category=None, ruled_by=None)


DEPENDENCIES: tuple[PurgeDependency, ...] = (
    # Durable delivery state is cancelled before deletion and contains no
    # evidence that must survive the request.
    PurgeDependency("phase1_outbox", "phase1_processing_outbox",
                    "processing_job_id", "job", "delete",
                    "processing_queue", 10),
    # Job evidence (retention schedule v1.4): kept 12 months, then the
    # scheduled clean-up deletes it. Each event points at its job ON DELETE
    # RESTRICT, so the job row is kept with its events, for the same
    # period; before v1.4 is active the job row is deleted as it always was
    # (an event stops the erasure for review first).
    _job_evidence("phase1_job_events", "phase1_processing_job_events",
                  "processing_job_id", "job", "processing_queue", 300),
    _job_evidence("phase1_jobs", "phase1_processing_jobs",
                  "acquisition_principal_id", "principal", "processing_queue",
                  20, before_rule="delete"),
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

    # Exact user-facing evidence and derived state. What a Take showed and
    # the speaker's own answers are product records (retention schedule
    # v1.4): deleted with the account or the project. Both tables are
    # append-only; their trigger lets a running purge delete exactly the rows
    # its frozen inventory names, under the active rule (0424).
    _product_record("feedback_exposure", "take_feedback_exposure",
                    "take_session_id", "take", "derived_feedback"),
    _product_record("feedback_self_report", "take_feedback_self_report",
                    "take_session_id", "take", "derived_feedback"),
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
                    "snippet_id", "snippet", "delete", "derived_feedback", 35),
    PurgeDependency("peer_labels", "snippet_peer_labels", "snippet_id",
                    "snippet", "delete", "derived_feedback", 35),
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
    PurgeDependency("read_alignments", "read_alignments", "session_id",
                    "take", "delete", "database_row", 45),
    PurgeDependency("candidate_windows", "candidate_windows", "recording_id",
                    "recording", "delete", "derived_feedback", 45),
    # N12: canonical evidence is kept as an empty receipt (identifiers and
    # timestamps; the words erased), never deleted. See LINEAGE_TOMBSTONES.
    PurgeDependency("evidence_spans", "evidence_spans", "owner_principal_id",
                    "principal", "tombstone", "derived_feedback", 200,
                    "deletion_evidence"),
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
    PurgeDependency("ideal_slide_helper_words", "ideal_text_slide_helper_words",
                    "arc_id", "project", "delete", "derived_feedback", 55),
    PurgeDependency("ideal_slide_helper_words_log",
                    "ideal_text_slide_helper_words_log",
                    "arc_id", "project", "delete", "derived_feedback", 55),
    PurgeDependency("ideal_practice_adoptions",
                    "ideal_text_practice_adoptions",
                    "arc_id", "project", "delete", "derived_feedback", 55),
    # Every version of a Paragraph: a product record (v1.4), deleted with
    # the account or the project, through the same governed trigger (0424).
    _product_record("ideal_part_revision", "ideal_text_part_revision",
                    "arc_id", "project", "derived_feedback"),
    # Immutable cold-open read model. Heads go first because their restrictive
    # FK points at snapshots; generations are only durable publication work.
    # None is legal/training evidence, so all three follow product deletion.
    PurgeDependency("ideal_document_head", "ideal_text_document_heads",
                    "arc_id", "project", "delete", "cache", 53),
    PurgeDependency("ideal_document_snapshot",
                    "ideal_text_document_snapshots",
                    "acquisition_principal_id", "principal", "delete",
                    "cache", 54),
    PurgeDependency("ideal_document_generation",
                    "ideal_text_document_generations", "arc_id", "project",
                    "delete", "processing_queue", 55),
    # The Manager's block, materialised at the publish boundary so the
    # bookmarks arrive with the words (founder 2026-09-20). It holds this
    # speaker's own feedback over their own transcript, so it is subject data
    # and it deletes with the project like the snapshot it points at — BEFORE
    # that snapshot (53.5), because its FK is restrictive in the same way the
    # head's is. Derived, never evidence: it is one stored copy of a
    # computation the pipeline can make again from the snapshot, which is why
    # it is a `cache` kind and losing it costs only one recomputation.
    PurgeDependency("ideal_feedback_bake", "ideal_text_feedback_bakes",
                    "arc_id", "project", "delete", "cache", 53),
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
    # voice_album has no user column (add_voice_album.sql: arc_id, snippet_id);
    # its rows belong to a project. Until 2026-09-26 this selected `user_id`,
    # which no migration creates, so the inventory would fail for every
    # account that had any Voice Album row.
    PurgeDependency("voice_album", "voice_album", "arc_id", "project", "delete",
                    "derived_feedback", 60),
    PurgeDependency("voice_album_practice", "voice_album_practice",
                    "practice_attempt_id", "practice_attempt", "delete",
                    "derived_feedback", 60),
    PurgeDependency("voice_album_routing", "owner_voice_album_routing",
                    "owner_user_id", "user", "delete", "derived_feedback", 60),
    # The owner's own notes on a moment. Authored by the subject, about their
    # own recording, read by nobody else — so erasure is a plain delete on the
    # user key, with no evidence to retain on anyone's behalf.
    PurgeDependency("voice_album_notes", "voice_album_notes", "owner_user_id",
                    "user", "delete", "derived_feedback", 60),
    # A coach's naming of an error on a speaker's moment is a judgement about
    # THAT recording, so it goes with it. Ordered ahead of the practice row;
    # the table's ON DELETE CASCADE from the practice is only the backstop.
    PurgeDependency("coach_moment_error_events", "coach_moment_error_event",
                    "practice_id", "practice", "delete", "derived_feedback",
                    58),
    # What attaching an exercise from a speaker's moment taught the library.
    # The rows made from their moment go with it. The tag a teaching added
    # stays on the exercise: that is a claim about the EXERCISE, like any the
    # CMS makes, and carries nothing about the speaker. The table's ON DELETE
    # SET NULL from the practice is the backstop for any other path.
    PurgeDependency("library_teachings", "diagnostic_exercise_teaching",
                    "practice_id", "practice", "delete", "derived_feedback",
                    58),
    # The client's confirmation that the chosen exercise rendered, migration
    # 0387. Goes with the Take, ahead of the assignment it confirms.
    PurgeDependency("practice_exercise_exposure",
                    "confident_voice_exercise_exposures", "take_session_id",
                    "take", "delete", "derived_feedback", 59),
    # Whether the coach-judged practice attempt sounded more confident than
    # the original, migration 0388. About one speaker's practice: it goes
    # with it, ahead of the practice and attempt it reads.
    PurgeDependency("practice_more_confident_outcome",
                    "practice_more_confident_outcomes", "practice_id",
                    "practice", "delete", "derived_feedback", 59),
    # Why that choice was made, migration 0384. Goes with the Take, ahead of
    # the assignment it explains; its ON DELETE CASCADE is only the backstop.
    PurgeDependency("practice_exercise_match_trace",
                    "confident_voice_exercise_match_traces", "take_session_id",
                    "take", "delete", "derived_feedback", 59),
    # Silent verdicts of the shadow-stage spoken-word cues on a Take's clips,
    # migration 0386. About one speaker's Take: they go with it.
    PurgeDependency("verbal_cue_shadow_observations",
                    "verbal_cue_shadow_observations", "take_session_id",
                    "take", "delete", "derived_feedback", 59),
    # The coach request for a moment no exercise fitted, and the coach's
    # resolution of it, migration 0385. About one speaker's Take: it goes
    # with it.
    PurgeDependency("practice_exercise_coach_request",
                    "exercise_coach_requests", "take_session_id",
                    "take", "delete", "derived_feedback", 59),
    # The speaker's opens and skips of their bookmarks (0408). About one
    # speaker's Take: they go with it.
    PurgeDependency("moment_events", "moment_events", "take_session_id",
                    "take", "delete", "derived_feedback", 59),
    # Which after-practice steps a Take showed, and the Bold voices plays
    # the speaker heard (0409). About one speaker's Take: they go with it.
    PurgeDependency("after_practice_steps", "after_practice_steps",
                    "take_session_id", "take", "delete", "derived_feedback", 59),
    PurgeDependency("bold_voices_plays", "bold_voices_plays",
                    "take_session_id", "take", "delete", "derived_feedback", 59),
    # A coach's own model readings (0409): their voice, under the coach
    # agreement; they go with the coach.
    PurgeDependency("coach_readings", "coach_readings", "coach_id",
                    "principal", "delete", "derived_feedback", 35),
    # Phase 4 and 5 (0410). The share of a moment and the measure's pair
    # are about the speaker's Take: they go with it. A set is the listener's
    # Take's; the answers and the votes are the rater's own words about
    # someone else's clip: they go with the rater.
    PurgeDependency("voice_album_shares", "voice_album_shares",
                    "take_session_id", "take", "delete", "derived_feedback", 59),
    PurgeDependency("delayed_measure_pairs", "delayed_measure_pairs",
                    "take_session_id", "take", "delete", "derived_feedback", 59),
    PurgeDependency("lend_your_ear_sets", "lend_your_ear_sets",
                    "take_session_id", "take", "delete", "derived_feedback", 59),
    PurgeDependency("lend_your_ear_answers", "lend_your_ear_answers",
                    "listener_user_id", "principal", "delete", "derived_feedback", 35),
    PurgeDependency("delayed_measure_votes", "delayed_measure_votes",
                    "rater_id", "principal", "delete", "derived_feedback", 35),
    # The coach panel's learning additions (0411). The preference, the
    # audit and the block pick are about one speaker's Take (they go with
    # it) AND are one coach's own words (they go with the coach too). The
    # exposure record is the coach's alone.
    PurgeDependency("coach_exercise_preference", "coach_exercise_preference",
                    "take_session_id", "take", "delete", "derived_feedback", 59),
    PurgeDependency("coach_exercise_preference_by_coach", "coach_exercise_preference",
                    "coach_id", "principal", "delete", "derived_feedback", 35),
    PurgeDependency("error_presence_audit", "error_presence_audit",
                    "take_session_id", "take", "delete", "derived_feedback", 59),
    PurgeDependency("error_presence_audit_by_coach", "error_presence_audit",
                    "coach_id", "principal", "delete", "derived_feedback", 35),
    PurgeDependency("coach_block_pick", "coach_block_pick",
                    "take_session_id", "take", "delete", "derived_feedback", 59),
    PurgeDependency("coach_block_pick_by_coach", "coach_block_pick",
                    "coach_id", "principal", "delete", "derived_feedback", 35),
    PurgeDependency("coach_clip_exposures", "coach_clip_exposures",
                    "coach_id", "principal", "delete", "derived_feedback", 35),
    # The (draft, final) pairs a coach's answer about one speaker's moment
    # made (0402). The words are about that passage: they go with the Take.
    # Pairs from the exercise library (no take) are about the library.
    # The coach's one word for a speaker's Take (0403): about that Take, it
    # goes with it.
    # The founder's golden judgement names a speaker's moment (0404): it
    # goes with the moment, like a coach's blind label does.
    # A release names whose passages it carries (0405): the row goes with the
    # person, and the weekly refresh voids the release for the object sweep.
    PurgeDependency("pair_release_owners", "pair_release_owners",
                    "owner_principal_id", "principal", "delete",
                    "derived_feedback", 35),
    PurgeDependency("golden_judgements", "golden_judgements", "snippet_id",
                    "snippet", "delete", "derived_feedback", 35),
    # A text golden moment (0406) keeps the speaker's passage with the
    # judgement, so it goes with the person; the evaluation then refuses
    # the changed set until the founder re-seals it.
    PurgeDependency("golden_judgements_by_owner", "golden_judgements",
                    "owner_principal_id", "principal", "delete",
                    "derived_feedback", 35),
    # A fine-tune run names whose passages it learned from (0406): the row
    # goes with the person, and the weekly sweep deletes the provider's
    # files for a run with a withdrawn owner.
    PurgeDependency("fine_tune_run_owners", "fine_tune_run_owners",
                    "owner_principal_id", "principal", "delete",
                    "derived_feedback", 35),
    PurgeDependency("coach_take_words", "coach_take_words",
                    "take_session_id", "take", "delete", "derived_feedback", 58),
    PurgeDependency("feedback_pairs_by_take", "feedback_pairs",
                    "take_session_id", "take", "delete", "derived_feedback", 58),
    # A pattern the coach named on the moment itself rather than on a
    # practice row (0402): same judgement about that recording, same fate.
    PurgeDependency("coach_moment_error_events_by_take",
                    "coach_moment_error_event", "take_session_id",
                    "take", "delete", "derived_feedback", 58),
    # The frozen 80/20 exercise choice per (Take, moment), migration 0372.
    # Product state about one speaker's Take, not evidence: it goes with it.
    PurgeDependency("practice_exercise_assignment",
                    "confident_voice_exercise_assignments", "take_session_id",
                    "take", "delete", "derived_feedback", 60),
    PurgeDependency("practice", "confident_voice_practice", "id", "practice",
                    "delete", "derived_feedback", 60),
    PurgeDependency("practice_attempt", "confident_voice_practice_attempt",
                    "id", "practice_attempt", "delete", "derived_feedback", 60),
    # Where a practice recording lives in the bucket. `delete`, not `retain`
    # like its sibling processing_audio_objects: the row has an ON DELETE
    # CASCADE to confident_voice_practice_attempt, so declaring it retained
    # would be a claim the schema silently overrules at order 60. Ordered just
    # ahead of that family so the explicit delete is the mechanism and the
    # cascade is only the backstop. The BYTES are erased separately and first
    # — resolve_targets runs every storage target before any dependency row.
    PurgeDependency("practice_object_metadata", "processing_practice_objects",
                    "acquisition_principal_id", "principal", "delete",
                    "database_row", 55),
    PurgeDependency("user_audits", "user_audits", "user_id", "user", "delete",
                    "database_row", 60),
    PurgeDependency("uploaded_files", "user_uploaded_files", "user_id", "user",
                    "delete", "database_row", 60),
    PurgeDependency("product_discoveries", "user_product_discoveries", "user_id",
                    "user", "delete", "database_row", 60),
    PurgeDependency("coaching_sessions", "coaching_sessions", "user_id", "user",
                    "delete", "database_row", 65),
    PurgeDependency("coaching_attempts", "coaching_attempts", "user_id", "user",
                    "delete", "database_row", 65),
    # N12, "keep an empty receipt": the take session, its recording attempt,
    # the take and its transitions are pointed at ON DELETE RESTRICT by the
    # permanent record, so they stay as identifiers and times and everything
    # said is erased (migration 0379, tombstone_phase1_purge_lineage_v1).
    PurgeDependency("v2_sessions", "v2_sessions", "owner_principal_id",
                    "principal", "tombstone", "database_row", 200,
                    "deletion_evidence"),
    PurgeDependency("legacy_attempts", "recording_attempts", "owner_principal_id",
                    "principal", "tombstone", "database_row", 200,
                    "deletion_evidence"),
    PurgeDependency("canonical_takes", "takes", "owner_principal_id",
                    "principal", "tombstone", "database_row", 200,
                    "deletion_evidence"),
    PurgeDependency("canonical_transition_events_review",
                    "processing_transition_events", "owner_principal_id",
                    "principal", "tombstone", "database_row", 200,
                    "deletion_evidence"),
    PurgeDependency("rejected_takes", "rejected_takes", "owner_principal_id",
                    "principal", "delete", "database_row", 80),
    # Founder 2026-09-25 (decisions log N9): a TOMBSTONE, not a delete.
    # Every accepted recording attempt is retained as evidence
    # (recording_boundary) and points at its project ON DELETE RESTRICT, so
    # deleting the row was refused for anyone who had recorded a take and no
    # erasure could finish (tests/test_take_purge_postgres.py). The row's user
    # content — name, setup, deck link — is wiped; the bare row (id, owner,
    # dates) is kept under the deletion-evidence rule.
    PurgeDependency("projects", "projects", "owner_principal_id", "principal",
                    "tombstone", "database_row", 90, "deletion_evidence"),

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
    # A choice changed after accepting (0361) qualifies the receipt it names,
    # so it is kept as the same evidence, under the same rule, as the receipt:
    # proof of what the person agreed to and later withdrew.
    PurgeDependency("consent_choice_events", "processing_consent_choice_events",
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
    # Rings (0394): the person's ring, attributes (region, plan, language,
    # role, bucket), their answers to announcements, and the append-only
    # history of their ring. Personal, not evidence: all deleted. The service
    # key holds DELETE on exactly these three tables for this path.
    PurgeDependency("principal_ring", "principal_rings", "principal_id",
                    "principal", "delete", "database_row", 80),
    PurgeDependency("principal_ring_history", "principal_ring_changes",
                    "principal_id", "principal", "delete", "database_row", 80),
    PurgeDependency("ring_announcement_decisions",
                    "ring_announcement_decisions", "principal_id",
                    "principal", "delete", "database_row", 80),
    PurgeDependency("owner_claim_source", "owner_claim_events",
                    "source_owner_principal_id", "principal", "retain",
                    "database_row", 200, "deletion_evidence"),
    PurgeDependency("owner_claim_target", "owner_claim_events",
                    "target_owner_principal_id", "principal", "retain",
                    "database_row", 200, "deletion_evidence"),

    # Legacy product tables (retention schedule v1.4). Each is a record of
    # the speaker's own use of the product: what was shown, their own
    # answers, a coach's or an operator's work on their sessions, or a
    # judgement about their own recording. Deleted with the account (or with
    # the project where a column names it: data_purge_project_scope) once
    # product-records-v1 is active; until then a matching row stops the
    # erasure for review, exactly as before.
    #
    # Six tables here predate migrations/ (no CREATE in this repository; see
    # tests/test_purge_registry_selectors_exist.py LEGACY_TABLES). v1.4
    # decides the five product tables among them too, but the purge deletes
    # nothing whose production shape this repository cannot show: they stay
    # external_review until one read-only check and a reviewed change say so.
    # The sixth, few_shot_retrievals, is job evidence: kept, only counted.
    PurgeDependency("v1_sessions_review", "recording_sessions", "user_id",
                    "user", "external_review", "database_row", 300),
    _product_record("moment_unlocks_review", "moment_unlocks", "user_id",
                    "user", "database_row"),
    _product_record("student_profile_review", "student_profile", "user_id",
                    "user", "database_row"),
    _product_record("student_overrides_review", "v2_student_overrides",
                    "user_id", "user", "database_row"),
    _product_record("student_memory_review", "v2_student_coaching_memory",
                    "user_id", "user", "database_row"),
    _product_record("student_post_questions_review",
                    "v2_student_post_recording_questions", "user_id", "user",
                    "database_row"),
    _product_record("admin_session_override_review", "admin_session_overrides",
                    "user_id", "user", "database_row"),
    _product_record("admin_student_draft_review", "admin_student_send_drafts",
                    "user_id", "user", "coach_packet"),
    _product_record("admin_annotation_review", "admin_annotation_events",
                    "user_id", "user", "coach_packet"),
    _product_record("content_exposure_review", "content_exposures", "user_id",
                    "user", "derived_feedback"),
    # Which examples served one of the speaker's requests: operational
    # evidence of how the feedback was made, kept 12 months (v1.4). A kept
    # row is only counted, never touched, so its pre-migrations shape needs
    # no check before the rule acts.
    _job_evidence("few_shot_review", "few_shot_retrievals", "user_id",
                  "user", "dataset_lineage"),
    _product_record("dimension_evaluation_review", "dimension_evaluations",
                    "user_id", "user", "dataset_lineage"),
    _product_record("intervention_arm_review", "intervention_arms", "user_id",
                    "user", "dataset_lineage"),
    _product_record("confidence_labels_review", "confidence_labels",
                    "snippet_id", "snippet", "dataset_lineage"),
    _product_record("confidence_rereview", "confidence_rereview_queue",
                    "owner_user_id", "user", "coach_packet"),
    _product_record("label_revision_review", "label_revision", "snippet_id",
                    "snippet", "dataset_lineage"),
    _product_record("intervention_decisions_review", "intervention_decisions",
                    "arc_id", "project", "derived_feedback"),
    PurgeDependency("performance_scores_review", "performance_scores",
                    "recording_id", "recording", "external_review",
                    "derived_feedback", 300),
    PurgeDependency("pre_answers_review", "pre_recording_answers",
                    "recording_session_id", "take", "external_review",
                    "database_row", 300),
    PurgeDependency("post_answers_review", "post_recording_answers",
                    "session_id", "take", "external_review",
                    "database_row", 300),
    _product_record("session_commands_review", "session_command_options",
                    "session_id", "take", "database_row"),
    # After the take session's wipe (200): v2_sessions points at a report ON
    # DELETE SET NULL, and the wipe has already emptied that pointer.
    _product_record("v2_reports_review", "v2_reports", "session_v2_id", "take",
                    "database_row"),
    _product_record("admin_annotation_log_review", "admin_annotations_log",
                    "user_id", "user", "dataset_lineage"),
    # Not decided by v1.4 (proposed to the founder): a reference video made
    # for this speaker may since have become library content (is_universal),
    # and its stored file has no storage target in this purge.
    PurgeDependency("admin_uploaded_reference_review",
                    "admin_uploaded_reference_videos", "user_id", "user",
                    "external_review", "dataset_lineage", 300),
    _job_evidence("copilot_upload_jobs_review",
                  "copilot_reference_upload_jobs", "student_user_id", "user",
                  "processing_queue"),
    _product_record("arc_deliveries_review", "arc_batch_deliveries", "user_id",
                    "user", "database_row"),
    # Not decided by v1.4 (proposed to the founder): a purchase is a
    # financial record, which v1.3's financial-evidence-v1 keeps five years.
    PurgeDependency("arc_purchases_review", "arc_purchases", "user_id", "user",
                    "external_review", "database_row", 300),
    PurgeDependency("student_tasks_review", "tasks", "user_id", "user",
                    "external_review", "database_row", 300),
    _product_record("coaching_directives_review", "coaching_directives_queue",
                    "user_id", "user", "database_row"),
    _product_record("coach_ai_review", "coach_ai_conversations", "user_id",
                    "user", "database_row"),
    _product_record("admin_archive_review", "admin_copilot_queue_archives",
                    "user_id", "user", "database_row"),
    PurgeDependency("token_ledger_review", "token_ledger", "user_id", "user",
                    "retain", "database_row", 300, "financial_evidence"),
    PurgeDependency("llm_usage_review", "llm_usage", "user_id", "user",
                    "retain", "database_row", 300, "financial_evidence"),

    # The Life Panel: the person's own use of it, so product records (v1.4),
    # deleted with the account once product-records-v1 is active, in the
    # order its own hard delete uses (services/life_store.py _DELETE_ORDER:
    # leaves first, consent last, "the record that the rest was ever allowed
    # to exist"). No foreign key joins these tables; the order is the Life
    # Panel's, kept so a partial failure never strands a child row. Until the
    # rule is active, a matching row stops the erasure as before.
    _product_record("life_consent_review", "life_consent", "user_id", "user",
                    "database_row", 299),
    _product_record("life_setup_review", "life_setup", "user_id", "user",
                    "database_row", 291),
    _product_record("life_notes_review", "life_notes", "user_id", "user",
                    "database_row", 289),
    _product_record("life_cases_review", "life_cases", "user_id", "user",
                    "database_row", 284),
    _product_record("life_items_review", "life_items", "user_id", "user",
                    "database_row", 283),
    _product_record("life_strategy_review", "life_strategy", "user_id",
                    "user", "database_row", 288),
    _product_record("life_proposals_review", "life_proposals", "user_id",
                    "user", "database_row", 282),
    _product_record("life_applications_review", "life_applications",
                    "user_id", "user", "database_row", 281),
    _product_record("life_days_review", "life_days", "user_id", "user",
                    "database_row", 285),
    _product_record("life_weeks_review", "life_weeks", "user_id", "user",
                    "database_row", 286),
    _product_record("life_period_reviews_review", "life_period_reviews",
                    "user_id", "user", "database_row", 287),
    _product_record("life_setup_documents_review", "life_setup_documents",
                    "user_id", "user", "database_row", 290),
    _product_record("life_push_subscriptions_review",
                    "life_push_subscriptions", "user_id", "user",
                    "database_row", 292),
    _product_record("life_reminder_settings_review", "life_reminder_settings",
                    "user_id", "user", "database_row", 293),
    _product_record("life_reminder_log_review", "life_reminder_log",
                    "user_id", "user", "database_row", 294),
    _product_record("life_user_copy_review", "life_user_copy", "user_id",
                    "user", "database_row", 295),

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
                    "owner_principal_id", "principal", "tombstone",
                    "derived_feedback", 200, "deletion_evidence"),
    PurgeDependency("canonical_slides", "slides", "owner_principal_id",
                    "principal", "tombstone", "derived_feedback", 200,
                    "deletion_evidence"),
    PurgeDependency("canonical_paragraphs", "paragraphs",
                    "owner_principal_id", "principal", "tombstone",
                    "derived_feedback", 200, "deletion_evidence"),
    PurgeDependency("canonical_acoustics", "acoustic_feature_snapshots",
                    "owner_principal_id", "principal", "tombstone",
                    "derived_feedback", 200, "deletion_evidence"),
    PurgeDependency("canonical_candidate_sets", "candidate_sets",
                    "owner_principal_id", "principal", "tombstone",
                    "derived_feedback", 200, "deletion_evidence"),
    PurgeDependency("canonical_machine_predictions", "machine_predictions",
                    "owner_principal_id", "principal", "tombstone",
                    "derived_feedback", 200, "deletion_evidence"),
    PurgeDependency("canonical_generation_runs", "generation_runs",
                    "owner_principal_id", "principal", "tombstone",
                    "derived_feedback", 200, "deletion_evidence"),
    PurgeDependency("canonical_processing_stage_runs", "processing_stage_runs",
                    "owner_principal_id", "principal", "tombstone",
                    "derived_feedback", 200, "deletion_evidence"),
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
    # The record of a person's yes and no to training (founder 2026-09-26:
    # N10 counsel answer 9, N11 answer 1) is kept after an account erasure
    # as consent evidence, under the signed `consent_evidence` rule
    # (retention schedule v1.1). Until that rule is seeded the erasure still
    # stops for review (RETENTION_RULE_UNRESOLVED), as it did before.
    PurgeDependency("ml_consent_events", "ml_consent_events",
                    "acquisition_principal_id", "principal", "retain",
                    "dataset_lineage", 300, "consent_evidence"),
    PurgeDependency("ml_consent_snapshots", "ml_consent_snapshots",
                    "acquisition_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    # Training copies (P3 0375, P4 0376). Account erasure always deletes them
    # (C3): their audio first, as storage targets (_corpus_targets), then the
    # rows here. Keeping them through a PROJECT delete for someone with an
    # active training yes (`retain_while_training_consented`) arrives with the
    # project-scoped purge; every purge that exists today is principal-wide.
    PurgeDependency("training_corpus_items", "training_corpus_items",
                    "acquisition_principal_id", "principal", "delete",
                    "dataset_lineage", 57),
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
    # N1 pattern results and frozen companion inventories are exact-clip ML
    # provenance. They remain non-serving/non-dataset, but any matching row
    # must block ordinary deletion until its canonical purge path is reviewed.
    PurgeDependency("exercise_n1_source_patterns",
                    "exercise_n1_source_pattern_results",
                    "acquisition_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("exercise_n1_pattern_snapshots",
                    "exercise_n1_pattern_snapshots",
                    "acquisition_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("exercise_n1_pattern_candidates",
                    "exercise_n1_pattern_candidates",
                    "acquisition_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),

    # Restored MLC-3 P1/P2 and RPQ ledgers are synthetic and non-serving, but
    # they still contain exact subject/audio provenance.  Every acquisition-
    # owned row therefore fails closed through the canonical purge review.
    PurgeDependency("exercise_practice_sessions", "exercise_practice_sessions",
                    "acquisition_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("exercise_practice_upload_recoveries",
                    "exercise_practice_upload_recoveries",
                    "acquisition_principal_id", "principal", "external_review",
                    "storage_object", 300),
    PurgeDependency("exercise_practice_attempts", "exercise_practice_attempts",
                    "acquisition_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("exercise_practice_measurements",
                    "exercise_practice_measurement_revisions",
                    "acquisition_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("exercise_practice_validity",
                    "exercise_practice_validity_assessments",
                    "acquisition_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("exercise_practice_selections",
                    "exercise_practice_selection_revisions",
                    "acquisition_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("exercise_practice_events", "exercise_practice_events",
                    "acquisition_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("exercise_service_offers", "exercise_service_offers",
                    "acquisition_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("exercise_service_offer_candidates",
                    "exercise_service_offer_candidates",
                    "acquisition_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("exercise_service_offer_events",
                    "exercise_service_offer_events",
                    "acquisition_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("exercise_pair_revisions", "exercise_pair_revisions",
                    "acquisition_principal_id", "principal", "external_review",
                    "dataset_lineage", 300),
    PurgeDependency("exercise_pair_assignments", "exercise_pair_assignments",
                    "acquisition_principal_id", "principal", "external_review",
                    "coach_packet", 300),
    PurgeDependency("exercise_pair_assignment_reviewers",
                    "exercise_pair_assignments", "reviewer_principal_id",
                    "principal", "external_review", "coach_packet", 300),
    PurgeDependency("exercise_pair_judgments", "exercise_pair_judgments",
                    "acquisition_principal_id", "principal", "external_review",
                    "coach_packet", 300),
    PurgeDependency("exercise_pair_judgment_reviewers",
                    "exercise_pair_judgments", "reviewer_principal_id",
                    "principal", "external_review", "coach_packet", 300),
    PurgeDependency("exercise_reviewer_context",
                    "exercise_reviewer_context_events", "reviewer_principal_id",
                    "principal", "external_review", "coach_packet", 300),
    PurgeDependency("exercise_service_requests", "exercise_service_requests",
                    "acquisition_principal_id", "principal", "external_review",
                    "coach_packet", 300),
    PurgeDependency("exercise_authoring_drafts", "exercise_authoring_drafts",
                    "acquisition_principal_id", "principal", "external_review",
                    "coach_packet", 300),
    PurgeDependency("exercise_authoring_draft_authors",
                    "exercise_authoring_drafts", "author_principal_id",
                    "principal", "external_review", "coach_packet", 300),
    PurgeDependency("feedback_v3_memberships", "feedback_v3_memberships",
                    "acquisition_principal_id", "principal", "external_review",
                    "derived_feedback", 300),
    PurgeDependency("feedback_v3_membership_items",
                    "feedback_v3_membership_items", "acquisition_principal_id",
                    "principal", "external_review", "derived_feedback", 300),
    PurgeDependency("feedback_v3_owner_responses",
                    "feedback_v3_owner_responses", "acquisition_principal_id",
                    "principal", "external_review", "derived_feedback", 300),
    PurgeDependency("feedback_v3_service_render_receipts",
                    "feedback_v3_service_render_receipts",
                    "acquisition_principal_id", "principal",
                    "external_review", "derived_feedback", 300),
    PurgeDependency("feedback_v3_service_response_bindings",
                    "feedback_v3_service_response_bindings",
                    "acquisition_principal_id", "principal",
                    "external_review", "derived_feedback", 300),
    PurgeDependency("confident_moment_bundle_attachments",
                    "confident_moment_bundle_attachments",
                    "acquisition_principal_id", "principal",
                    "external_review", "derived_feedback", 300),
    PurgeDependency("confident_moment_owner_decision_bindings",
                    "confident_moment_owner_decision_bindings",
                    "acquisition_principal_id", "principal",
                    "external_review", "derived_feedback", 300),
    PurgeDependency("root_phrase_coverage_frames",
                    "root_phrase_coverage_frames", "acquisition_principal_id",
                    "principal", "external_review", "derived_feedback", 300),
    PurgeDependency("root_phrase_coverage_items",
                    "root_phrase_coverage_items", "acquisition_principal_id",
                    "principal", "external_review", "derived_feedback", 300),
    PurgeDependency("feedback_language_revision_deliveries",
                    "feedback_language_revision_deliveries",
                    "acquisition_principal_id", "principal",
                    "external_review", "derived_feedback", 300),
    PurgeDependency("feedback_language_delivery_recipients",
                    "feedback_language_revision_deliveries",
                    "recipient_principal_id", "principal",
                    "external_review", "derived_feedback", 300),
    PurgeDependency("feedback_language_delivery_reviewers",
                    "feedback_language_revision_deliveries",
                    "reviewer_principal_id", "principal",
                    "external_review", "derived_feedback", 300),
    PurgeDependency("feedback_revision_subjects", "feedback_revisions",
                    "acquisition_principal_id", "principal",
                    "external_review", "derived_feedback", 300),
    PurgeDependency("feedback_revision_reviewers", "feedback_revisions",
                    "rater_id", "principal", "external_review",
                    "derived_feedback", 300),
    PurgeDependency("confident_moment_bundle_projections",
                    "confident_moment_bundle_projections",
                    "acquisition_principal_id", "principal",
                    "external_review", "derived_feedback", 300),
    PurgeDependency("confident_moment_bundle_projection_items",
                    "confident_moment_bundle_projection_items",
                    "acquisition_principal_id", "principal",
                    "external_review", "derived_feedback", 300),
    PurgeDependency("ideal_text_user_edit_cas_operations",
                    "ideal_text_user_edit_cas_operations",
                    "acquisition_principal_id", "principal",
                    "external_review", "derived_feedback", 300),
    PurgeDependency("confident_moment_bundle_text_update_bindings",
                    "confident_moment_bundle_text_update_bindings",
                    "acquisition_principal_id", "principal",
                    "external_review", "derived_feedback", 300),
    PurgeDependency("confident_moment_text_update_capabilities",
                    "confident_moment_text_update_capabilities",
                    "acquisition_principal_id", "principal",
                    "external_review", "derived_feedback", 300),
    PurgeDependency("confident_moment_coach_authorability_inventories",
                    "confident_moment_coach_authorability_inventories",
                    "acquisition_principal_id", "principal",
                    "external_review", "coach_packet", 300),
    PurgeDependency("confident_moment_coach_authorability_items",
                    "confident_moment_coach_authorability_items",
                    "acquisition_principal_id", "principal",
                    "external_review", "coach_packet", 300),
    PurgeDependency("confident_moment_blind_assignment_bindings",
                    "confident_moment_blind_assignment_bindings",
                    "acquisition_principal_id", "principal",
                    "external_review", "coach_packet", 300),
    PurgeDependency("confident_moment_coach_wording_subjects",
                    "confident_moment_coach_wording_authority_bindings",
                    "acquisition_principal_id", "principal",
                    "external_review", "coach_packet", 300),
    PurgeDependency("confident_moment_coach_wording_reviewers",
                    "confident_moment_coach_wording_authority_bindings",
                    "reviewer_principal_id", "principal",
                    "external_review", "coach_packet", 300),
    # The delivery jobs, their events and claims are job evidence (v1.4):
    # kept 12 months, only counted, never touched. The bundle lineage they
    # deliver stays external_review above.
    _job_evidence("feedback_language_delivery_materialization_jobs",
                  "feedback_language_delivery_materialization_jobs",
                  "acquisition_principal_id", "principal",
                  "processing_queue"),
    _job_evidence("feedback_language_delivery_job_events",
                  "feedback_language_delivery_materialization_job_events",
                  "job_id", "delivery_job", "processing_queue"),
    _job_evidence("feedback_language_delivery_job_claim_attempts",
                  "feedback_language_delivery_job_claim_attempts",
                  "job_id", "delivery_job", "processing_queue"),
    _job_evidence("feedback_language_delivery_job_claim_heads",
                  "feedback_language_delivery_job_claim_heads",
                  "job_id", "delivery_job", "processing_queue"),
    _job_evidence("feedback_language_delivery_job_due_heads",
                  "feedback_language_delivery_job_due_heads",
                  "job_id", "delivery_job", "processing_queue"),
    PurgeDependency("exercise_service_acquisition_receipts",
                    "exercise_service_acquisition_receipts",
                    "acquisition_principal_id", "principal",
                    "external_review", "dataset_lineage", 300),
    PurgeDependency("exercise_practice_transcription_runs",
                    "exercise_practice_transcription_runs",
                    "acquisition_principal_id", "principal",
                    "external_review", "provider_artifact", 300),
    PurgeDependency("mlc3_service_principal_allowlist_subjects",
                    "mlc3_service_principal_allowlist",
                    "acquisition_principal_id", "principal",
                    "external_review", "authorization_receipt", 300),
    PurgeDependency("mlc3_service_principal_allowlist_approvers",
                    "mlc3_service_principal_allowlist",
                    "approved_by_principal_id", "principal",
                    "external_review", "authorization_receipt", 300),
    # D4 rollout access and speaker-routing provenance. Global rollout/risk
    # configuration is classified separately below; these rows are bound to
    # one exact acquisition principal and must participate in purge review.
    PurgeDependency("mlc3_service_cohort_members",
                    "mlc3_service_cohort_members",
                    "acquisition_principal_id", "principal",
                    "external_review", "authorization_receipt", 300),
    PurgeDependency("mlc3_service_enrollment_revisions",
                    "mlc3_service_enrollment_revisions",
                    "acquisition_principal_id", "principal",
                    "external_review", "authorization_receipt", 300),
    PurgeDependency("mlc3_service_access_events",
                    "mlc3_service_access_events",
                    "acquisition_principal_id", "principal",
                    "external_review", "authorization_receipt", 300),
    PurgeDependency("mlc3_speaker_acquisition_revisions",
                    "mlc3_speaker_acquisition_revisions",
                    "acquisition_principal_id", "principal",
                    "external_review", "dataset_lineage", 300),
    PurgeDependency("mlc3_self_speaker_assertions",
                    "mlc3_self_speaker_assertions",
                    "acquisition_principal_id", "principal",
                    "external_review", "dataset_lineage", 300),
    PurgeDependency("mlc3_target_speaker_bindings",
                    "mlc3_target_speaker_bindings",
                    "acquisition_principal_id", "principal",
                    "external_review", "dataset_lineage", 300),
    PurgeDependency("mlc3_comparison_speaker_eligibility_revisions",
                    "mlc3_comparison_speaker_eligibility_revisions",
                    "acquisition_principal_id", "principal",
                    "external_review", "dataset_lineage", 300),
    PurgeDependency("exercise_service_confidence_assignments",
                    "exercise_service_confidence_assignments",
                    "acquisition_principal_id", "principal",
                    "external_review", "coach_packet", 300),
    PurgeDependency("exercise_service_confidence_assignment_reviewers",
                    "exercise_service_confidence_assignments",
                    "reviewer_principal_id", "principal",
                    "external_review", "coach_packet", 300),
    PurgeDependency("exercise_service_confidence_render_receipts",
                    "exercise_service_confidence_render_receipts",
                    "acquisition_principal_id", "principal",
                    "external_review", "coach_packet", 300),
    PurgeDependency("exercise_service_confidence_render_reviewers",
                    "exercise_service_confidence_render_receipts",
                    "reviewer_principal_id", "principal",
                    "external_review", "coach_packet", 300),
    PurgeDependency("exercise_service_confidence_judgments",
                    "exercise_service_confidence_judgments",
                    "acquisition_principal_id", "principal",
                    "external_review", "coach_packet", 300),
    PurgeDependency("exercise_service_confidence_judgment_reviewers",
                    "exercise_service_confidence_judgments",
                    "reviewer_principal_id", "principal",
                    "external_review", "coach_packet", 300),
    PurgeDependency("exercise_service_blind_review_sets",
                    "exercise_service_blind_review_sets",
                    "acquisition_principal_id", "principal",
                    "external_review", "coach_packet", 300),
    PurgeDependency("exercise_service_blind_review_set_reviewers",
                    "exercise_service_blind_review_sets",
                    "reviewer_principal_id", "principal",
                    "external_review", "coach_packet", 300),
    PurgeDependency("exercise_service_blind_reveal_grants",
                    "exercise_service_blind_reveal_grants",
                    "acquisition_principal_id", "principal",
                    "external_review", "coach_packet", 300),
    PurgeDependency("exercise_service_blind_reveal_grant_reviewers",
                    "exercise_service_blind_reveal_grants",
                    "reviewer_principal_id", "principal",
                    "external_review", "coach_packet", 300),
    PurgeDependency("exercise_service_blind_reveal_accesses",
                    "exercise_service_blind_reveal_accesses",
                    "acquisition_principal_id", "principal",
                    "external_review", "coach_packet", 300),
    PurgeDependency("exercise_service_blind_reveal_access_reviewers",
                    "exercise_service_blind_reveal_accesses",
                    "reviewer_principal_id", "principal",
                    "external_review", "coach_packet", 300),
    # D3 coach-guidance records remain product evidence, not labels. They are
    # still subject-linked and therefore block ordinary purge completion until
    # the reviewed adapter resolves or invalidates their exact lineage.
    PurgeDependency("coach_guidance_review_frames",
                    "coach_guidance_review_frames", "acquisition_principal_id",
                    "principal", "external_review", "coach_packet", 300),
    PurgeDependency("coach_guidance_review_frame_items",
                    "coach_guidance_review_frame_items", "acquisition_principal_id",
                    "principal", "external_review", "coach_packet", 300),
    PurgeDependency("coach_guidance_review_batches",
                    "coach_guidance_review_batches", "acquisition_principal_id",
                    "principal", "external_review", "coach_packet", 300),
    PurgeDependency("coach_guidance_reveal_grants",
                    "coach_guidance_reveal_grants", "acquisition_principal_id",
                    "principal", "external_review", "coach_packet", 300),
    PurgeDependency("coach_guidance_reveal_grant_judgments",
                    "coach_guidance_reveal_grant_judgments",
                    "acquisition_principal_id", "principal",
                    "external_review", "coach_packet", 300),
    PurgeDependency("coach_guidance_reveal_accesses",
                    "coach_guidance_reveal_accesses",
                    "acquisition_principal_id", "principal",
                    "external_review", "coach_packet", 300),
    PurgeDependency("coach_guidance_media_bindings",
                    "coach_guidance_media_bindings", "acquisition_principal_id",
                    "principal", "external_review", "storage_object", 300),
    PurgeDependency("coach_guidance_upload_permits",
                    "coach_guidance_upload_permits", "acquisition_principal_id",
                    "principal", "external_review", "storage_object", 300),
    PurgeDependency("coach_guidance_upload_recoveries",
                    "coach_guidance_upload_recoveries",
                    "acquisition_principal_id", "principal", "external_review",
                    "storage_object", 300),
    PurgeDependency("coach_guidance_upload_events",
                    "coach_guidance_upload_events", "acquisition_principal_id",
                    "principal", "external_review", "storage_object", 300),
    PurgeDependency("coach_guidance_media_validity_events",
                    "coach_guidance_media_validity_events",
                    "acquisition_principal_id", "principal",
                    "external_review", "storage_object", 300),
    PurgeDependency("coach_guidance_independent_media_reviews",
                    "coach_guidance_independent_media_reviews",
                    "acquisition_principal_id", "principal",
                    "external_review", "storage_object", 300),
    PurgeDependency("coach_guidance_independent_media_reviewers",
                    "coach_guidance_independent_media_reviews",
                    "reviewer_principal_id", "principal",
                    "external_review", "coach_packet", 300),
    PurgeDependency("coach_guidance_media_source_dependencies",
                    "coach_guidance_media_bindings",
                    "source_acquisition_principal_id", "principal",
                    "external_review", "storage_object", 300),
    PurgeDependency("coach_guidance_attachments",
                    "coach_guidance_attachments", "acquisition_principal_id",
                    "principal", "external_review", "derived_feedback", 300),
    PurgeDependency("coach_guidance_attachment_versions",
                    "coach_guidance_attachment_versions",
                    "acquisition_principal_id", "principal", "external_review",
                    "derived_feedback", 300),
    PurgeDependency("coach_guidance_lifecycle_events",
                    "coach_guidance_lifecycle_events", "acquisition_principal_id",
                    "principal", "external_review", "derived_feedback", 300),
    PurgeDependency("coach_guidance_publications",
                    "coach_guidance_publications",
                    "source_acquisition_principal_id", "principal",
                    "external_review", "dataset_lineage", 300),
    PurgeDependency("coach_guidance_publication_invalidations",
                    "coach_guidance_publication_invalidations",
                    "source_acquisition_principal_id", "principal",
                    "external_review", "dataset_lineage", 300),
    # D5 inline authoring remains product-only, but every row is tied to the
    # exact acquisition principal and must participate in deletion traversal.
    PurgeDependency("coach_inline_source_roles",
                    "coach_inline_source_roles", "acquisition_principal_id",
                    "principal", "external_review", "coach_packet", 300),
    PurgeDependency("coach_inline_source_role_reviewers",
                    "coach_inline_source_roles", "reviewer_principal_id",
                    "principal", "external_review", "coach_packet", 300),
    PurgeDependency("coach_inline_exercise_drafts",
                    "coach_inline_exercise_drafts", "acquisition_principal_id",
                    "principal", "external_review", "derived_feedback", 300),
    PurgeDependency("coach_inline_exercise_draft_authors",
                    "coach_inline_exercise_drafts", "author_principal_id",
                    "principal", "external_review", "derived_feedback", 300),
    PurgeDependency("coach_inline_context_assessments",
                    "coach_inline_context_assessments",
                    "acquisition_principal_id",
                    "principal", "external_review", "coach_packet", 300),
    PurgeDependency("coach_inline_context_assessment_reviewers",
                    "coach_inline_context_assessments", "reviewer_principal_id",
                    "principal", "external_review", "coach_packet", 300),
    PurgeDependency("coach_inline_exercise_eligibility_reviews",
                    "coach_inline_exercise_eligibility_reviews",
                    "acquisition_principal_id", "principal",
                    "external_review", "dataset_lineage", 300),
    PurgeDependency("root_phrase_content_versions",
                    "root_phrase_content_versions", "acquisition_principal_id",
                    "principal", "external_review", "derived_feedback", 300),
    PurgeDependency("root_phrase_semantic_input_snapshots",
                    "root_phrase_semantic_input_snapshots",
                    "acquisition_principal_id", "principal", "external_review",
                    "derived_feedback", 300),
    PurgeDependency("root_phrase_semantic_results",
                    "root_phrase_semantic_results", "acquisition_principal_id",
                    "principal", "external_review", "derived_feedback", 300),
    PurgeDependency("root_phrase_owner_alignment_actions",
                    "root_phrase_owner_alignment_actions",
                    "acquisition_principal_id", "principal", "external_review",
                    "derived_feedback", 300),
    PurgeDependency("root_phrase_qualification_revisions",
                    "root_phrase_qualification_revisions",
                    "acquisition_principal_id", "principal", "external_review",
                    "derived_feedback", 300),
    PurgeDependency("root_phrase_product_actions",
                    "root_phrase_product_actions", "acquisition_principal_id",
                    "principal", "external_review", "derived_feedback", 300),
    PurgeDependency("root_phrase_block_heads", "root_phrase_block_heads",
                    "acquisition_principal_id", "principal", "external_review",
                    "derived_feedback", 300),

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
    # The licensed corpus (0410): clips licensed from elsewhere, not about
    # any speaker; the live view of shares reads tables purged on their own.
    "corpus_clips", "shared_clips_live",
    "admin_users", "coach_users", "admin_annotation_export_runs",
    "admin_notifications", "arc_invite_codes", "casual_voice_benchmarks",
    "chat_question_pool", "coach_video_assets",
    "dad_jokes", "diagnostic_exercise",
    # Its version rows (0399): the coach's texts, the AI draft and the video's
    # transcript, product vocabulary like the row they mirror. Coach content,
    # never a speaker's recording.
    "diagnostic_exercise_version",
    # The speaking error LIBRARY — names and written definitions of speech
    # patterns, beside diagnostic_exercise for the same reason: it is product
    # vocabulary, not anybody's recording. A row never says that a pattern
    # occurred in a particular take, so there is nothing here to purge when a
    # person asks to be deleted.
    "speaking_error",
    # The catalogue of signed lines (0401): one sentence per pattern, written
    # by the founder or a coach. Copy, never a speaker's words or recording;
    # nothing here names a person.
    "feedback_catalogue",
    # A dataset release manifest: counts, rules and a checksum, no subject
    # column (its items are the subject rows, classified above).
    "dataset_releases",
    # The ledger's weekly snapshots hold counts about the machine (0404).
    "ledger_snapshots",
    # A pair release's manifest and hashes (0405); whose passages it holds is
    # pair_release_owners, a dependency below, and the refresh voids the
    # release itself when an owner withdraws.
    "pair_releases",
    # The checks of a release's file and manifest (0430, F-8): hashes, sizes
    # and verdicts keyed by the release, never a person.
    "pair_release_verifications",
    # The research role, like admin_users and coach_users (0404).
    "research_users",
    # A surface's sealed golden set: a count and a hash (0404).
    "golden_sets",
    # Door 3 and 4 ledgers (0406): a run's file hashes, job and candidate
    # ids; a report about a model; a promotion's history. Whose passages a
    # run learned from is fine_tune_run_owners, a dependency above.
    "fine_tune_runs", "evaluation_reports", "model_promotions",
    # The view over fine_tune_runs and its owners that the withdrawal sweep
    # reads (0406): no row of its own.
    "fine_tune_runs_with_withdrawn_owner",
    # The view of the training yes in force now (0405), which the weekly
    # refresh, the release-time decision and the promotion's freshness check
    # read (PLF-P5, DOOR-4-WITHDRAWN): no row of its own; its rows are
    # ml_consent_events, classified with the account.
    "training_consent_active_grants",
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
    # A project deletion REQUEST (0364) is the deletion's own paperwork, like
    # data_purge_requests beside it: it names what to delete and is never the
    # content being deleted.
    "project_deletion_requests",
    # An account deletion REQUEST with its seven-day window (0422), the same
    # paperwork for a whole account: ids, times, a state and the evidence
    # hash of the purge that finished it.
    "account_deletion_requests",
    # The scheduled clean-up's own paperwork (0423), like the purge's above:
    # a run's counts and times, and the ids of the objects a live run claimed
    # with how each ended. No column names a person; what a run deleted is
    # recorded where every deletion is (processing_audio_object_deletion_
    # events, data_purge_requests).
    "retention_cleaner_runs", "retention_cleaner_audio_claims",
    "data_rights_requests", "data_retention_rules",
    "processing_policy_versions", "processing_policy_purposes",
    "processing_purpose_registry", "processing_legal_artifacts",
    # MLC-2 consent POLICIES and their approvals (0302, 0373): the wording a
    # yes was given against and who approved it. No speaker's data; the
    # per-person yes and no live in ml_consent_events.
    "ml_consent_policies", "ml_product_legal_approvals",
    # The public Journal (marketing posts written by WillpowerLab) and the
    # Stripe webhook's idempotency ledger (a checkout session id and a time,
    # no user). Neither has a column naming a person; both were listed under a
    # `user_id` that no migration creates (2026-09-26).
    "journal_post", "journal_community_post", "stripe_checkout_credit_grants",
    "processing_authorization_receipt_purposes",
    "exercise_need_contracts", "exercise_media_objects",
    "exercise_definitions", "exercise_versions",
    "exercise_catalog_snapshots", "exercise_catalog_snapshot_items",
    "exercise_media_availability_checks",
    "exercise_n1_version_compatibility_profiles",
    "mlc3_service_cohort_sets", "mlc3_service_activation_risk_decisions",
    "mlc3_service_rollout_revisions", "mlc3_service_backpressure_events",
    "feedback_language_delivery_scan_runs",
    "feedback_language_delivery_stalled_scan_halt_receipts",
    "data_purge_inventory_manifests", "processing_provider_deletion_contracts",
    "processing_provider_deletion_contract_events", "detector_version",
    # Rings (0394): which ring gets a feature, the default ring, the
    # founder-held announcement copy, and the append-only history of those
    # three. Rollout configuration; no row names a person. A person's own
    # ring row, decisions and history are `delete` dependencies above.
    "feature_rings", "ring_settings", "ring_announcements",
    "feature_ring_changes", "ring_setting_changes",
})

# Child relations whose reviewed foreign key deletes with an allowlisted
# parent. They are not queried independently by the resolver, but they remain
# explicit so the dependency audit cannot mistake them for global data.
CASCADE_RELATIONS: frozenset[str] = frozenset({
    "coaching_attempt_annotations", "journal_post_image",
})

# Child relations the lineage tombstone empties through their parent
# (tombstone_phase1_purge_lineage_v1, migration a_take_keeps_an_empty_receipt:
# `feedback_candidates` follows `candidate_sets`, its `rank_evidence` and
# `generated_output` erased). Read at runtime since F1 Repair Plan Phase 4,
# where an accepted rewrite takes its words from the candidate that served
# it; no resolver step of its own, like CASCADE_RELATIONS.
TOMBSTONE_CHILD_RELATIONS: frozenset[str] = frozenset({
    "feedback_candidates",
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
    # The scheduled clean-up (services/retention_cleaner.py) removes rows
    # from the relations its reviewed lists name: the four logs, the
    # voice-measurement stores and, once their five years end, the financial
    # records (token_ledger and llm_usage, above; N50 P7). life_reminder_log
    # is above too. dev_bugs is the founder's own bug list and is not the
    # clean-up's (N50 C4 B).
    "processing_jobs", "admin_annotations_log",
    "mlc3_service_backpressure_events", "dimension_evaluations",
    "session_sniper_metrics", "arc_part_acoustics", "user_acoustic_baseline",
})


def classified_relations() -> frozenset[str]:
    return (
        frozenset(item.relation for item in DEPENDENCIES)
        | NON_SUBJECT_RELATIONS
        | CASCADE_RELATIONS
        | TOMBSTONE_CHILD_RELATIONS
    )


def dependency_manifest_sha256() -> str:
    payload = [asdict(item) for item in DEPENDENCIES]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def dependency_by_code(code: str) -> PurgeDependency | None:
    return next((item for item in DEPENDENCIES if item.code == code), None)

#: Relations kept as an empty receipt by tombstone_phase1_purge_lineage_v1
#: (migration 0379, founder N12). The only other tombstone is the project row.
LINEAGE_TOMBSTONES: frozenset[str] = frozenset({
    "v2_sessions", "recording_attempts", "takes",
    "processing_transition_events", "transcript_versions", "slides",
    "paragraphs", "evidence_spans", "acoustic_feature_snapshots",
    "candidate_sets", "machine_predictions", "generation_runs",
    "processing_stage_runs",
})
