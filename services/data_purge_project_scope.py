"""One project's purge (P1-B; decisions log N8, N12; founder 2026-09-26,
"make the delete work").

The account purge (`DataPurgeOrchestrator`) reaches everything a person owns.
A project purge must reach exactly one project and nothing beside it, with the
same fail-closed contract: an inventory frozen before the first destructive
call, every target resolved or the request stops for review.

How it narrows the account machinery:

  * the subject graph comes from `resolve_phase1_purge_project_graph_v1`. Its
    principal, user, speaker and permit lists are EMPTY on purpose, so any
    registry dependency keyed by the account reaches no row by itself;
  * each account-keyed dependency is placed in exactly one of three lists
    below. A dependency that holds project content is re-pointed at the
    project, take, snippet, job or practice column that says which project a
    row belongs to (`PROJECT_SELECTORS`). One that holds only the person's own
    settings or the account's legal evidence is left alone (`ACCOUNT_LEVEL`).
    One the lineage wipe reaches through its parent is left to it
    (`WIPED_WITH_PARENT`). Everything else - a separately governed lineage,
    or one nobody placed yet - stops the purge for review whenever the
    account has any row there, exactly as the account purge would;
  * storage is the project's audio, its practice recordings and nothing
    else. Orphan objects and provider operations belong to no project and are
    never frozen (the freeze refuses them too);
  * the finished purge marks the user's request done.

Retention schedule v1.5 (founder 2026-10-05, N50 P1-P6) places its records
the same way, once v1.5 is registered: a record that names its project, its
Take or its snippet goes with the project; the V3 feedback rows that name
only their membership are reached through the project's memberships, which
the project graph lists since 0429 (`feedback_v3_membership_ids`); a
person's settings, enrollment and own reviews of others stay with the
account; and a record no project column reaches is listed in
`PROJECT_REVIEW`: any such row the account holds stops a project purge for
review, as it did before v1.5.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from services.data_purge import (
    GRAPH_KEYS,
    DataPurgeOrchestrator,
    PurgeTarget,
    SubjectGraph,
    _one,
)
from services.data_purge_registry import (
    DEPENDENCIES,
    PurgeDependency,
    dependency_manifest_sha256,
)

PROJECT_RESOLVER_VERSION = "phase1-project-purge-resolver-v1"


@dataclass(frozen=True)
class ProjectSubjectGraph(SubjectGraph):
    """One project's graph: the account graph's keys, plus the project's V3
    feedback memberships (0429), the only way to reach the rows that name a
    membership and no project."""

    feedback_v3_membership_ids: tuple[str, ...] = ()

    def values(self, locator_kind: str) -> tuple[str, ...]:
        if locator_kind == "feedback_v3_membership":
            return self.feedback_v3_membership_ids
        return super().values(locator_kind)

    def payload(self) -> dict[str, list[str]]:
        return {**super().payload(), "feedback_v3_membership_ids":
                list(self.feedback_v3_membership_ids)}


PROJECT_GRAPH_KEYS: tuple[str, ...] = (
    *GRAPH_KEYS, "feedback_v3_membership_ids")

#: Account-keyed dependencies that hold project content, re-pointed at the
#: column that names the project: code -> (selector column, locator kind).
PROJECT_SELECTORS: Mapping[str, tuple[str, str]] = {
    # Processing queue for this project's recording attempts.
    "phase1_jobs": ("id", "job"),
    "policy_carryovers": ("processing_job_id", "job"),
    "runtime_jobs": ("session_id", "take"),
    # Takes, their words and everything built on them.
    "v2_sessions": ("id", "take"),
    "legacy_attempts": ("project_id", "project"),
    "canonical_takes": ("project_id", "project"),
    "canonical_transition_events_review": ("project_id", "project"),
    "canonical_transcript_versions": ("project_id", "project"),
    "canonical_slides": ("project_id", "project"),
    "canonical_paragraphs": ("project_id", "project"),
    "canonical_candidate_sets": ("project_id", "project"),
    "canonical_machine_predictions": ("project_id", "project"),
    "canonical_generation_runs": ("project_id", "project"),
    "canonical_processing_stage_runs": ("project_id", "project"),
    "evidence_spans": ("project_id", "project"),
    "recording_boundary": ("project_id", "project"),
    "rejected_takes": ("arc_id", "project"),
    "sniper_metrics": ("session_id", "take"),
    "uploaded_files": ("session_id", "take"),
    # The project's ideal text and moments.
    "projects": ("id", "project"),
    "ideal_document_snapshot": ("project_id", "project"),
    "moment_suggestions": ("arc_id", "project"),
    "voice_album_routing": ("arc_id", "project"),
    "voice_album_notes": ("arc_id", "project"),
    "legacy_game_saves": ("arc_id", "project"),
    # Practice recorded from this project's takes.
    "practice_object_metadata": ("practice_attempt_id", "practice_attempt"),
    "coaching_sessions": ("source_snippet_id", "snippet"),
    "coaching_attempts": ("snippet_id", "snippet"),
    # Retention schedule v1.4's product records whose rows name the project
    # (arc_id): deleted with it. Placed only while product-records-v1 is
    # active; until then they count as unplaced, exactly as before v1.4.
    "moment_unlocks_review": ("arc_id", "project"),
    "arc_deliveries_review": ("arc_id", "project"),
    # Retention schedule v1.5 (N50 P1, P2, P5, P6): records that name their
    # project, Take or snippet go with it. Placed only once v1.5 is
    # registered and product-records-v1 is active; until then they count as
    # unplaced, exactly as before v1.5.
    "learning_surface_presentations": ("project_id", "project"),
    "learning_surface_exposure_receipts": ("project_id", "project"),
    "ideal_text_user_edit_cas_operations": ("project_id", "project"),
    "confident_moment_text_update_capabilities": ("project_id", "project"),
    "feedback_v3_memberships": ("project_id", "project"),
    # The rows of those memberships, which name no project themselves.
    "feedback_v3_membership_items": ("membership_id", "feedback_v3_membership"),
    "feedback_v3_owner_responses": ("membership_id", "feedback_v3_membership"),
    "feedback_v3_service_render_receipts": (
        "membership_id", "feedback_v3_membership"),
    "feedback_v3_service_response_bindings": (
        "membership_id", "feedback_v3_membership"),
    "ml_canonical_events": ("project_id", "project"),
    "ml_evidence_spans": ("project_id", "project"),
    "ml_candidate_sets": ("project_id", "project"),
    # take_id is the canonical take, whose id is its take session's.
    "ml_confidence_producer_receipts": ("take_id", "take"),
    "v3_shadow": ("arc_id", "project"),
    "exercise_practice_sessions": ("project_id", "project"),
    "exercise_service_offers": ("project_id", "project"),
    "exercise_service_confidence_assignments": ("project_id", "project"),
    "confident_moment_bundle_attachments": ("project_id", "project"),
    "confident_moment_owner_decision_bindings": ("project_id", "project"),
    "root_phrase_coverage_frames": ("project_id", "project"),
    "confident_moment_bundle_projections": ("project_id", "project"),
    "confident_moment_bundle_text_update_bindings": ("project_id", "project"),
    "confident_moment_coach_authorability_inventories": (
        "project_id", "project"),
    "confident_moment_blind_assignment_bindings": ("project_id", "project"),
    "root_phrase_content_versions": ("project_id", "project"),
    "root_phrase_semantic_input_snapshots": ("project_id", "project"),
    "root_phrase_product_actions": ("project_id", "project"),
    "root_phrase_block_heads": ("project_id", "project"),
    "coach_guidance_review_frames": ("project_id", "project"),
    # A reflection clip is a stretch of one snippet; a strong side names
    # the Take its note was made on.
    "legacy_reflection_clips": ("snippet_id", "snippet"),
    "legacy_strong_sides": ("session_id", "take"),
    # A free founding pass names the arc, the project, it unlocked.
    "arc_purchases_founding_pass": ("arc_id", "project"),
}

#: Account-keyed dependencies that belong to the person, not to a project:
#: their settings and profile, and the account's legal, security and billing
#: evidence. A project purge leaves them exactly as they are.
ACCOUNT_LEVEL: frozenset[str] = frozenset({
    "lounge", "settings", "student_details", "speaker_profile",
    "sniper_profile", "acoustic_baseline", "user_audits",
    "product_discoveries", "legacy_focus_questions", "legacy_focus_tasks",
    "legacy_warm_up_tasks",
    "orphan_metadata", "provider_operations", "audio_metadata",
    "audio_deletion_evidence", "authorization_receipts",
    "consent_choice_events", "authorization_snapshots", "service_blocks",
    "provider_permits", "ai_exposures", "legacy_terms", "legacy_terms_events",
    "owner_identity", "owner_claim_source", "owner_claim_target",
    "token_ledger_review", "llm_usage_review", "ml_consent_events",
    # Rings (0394): a person's ring, its history and their announcement
    # answers belong to the account, not to any project.
    "principal_ring", "principal_ring_history", "ring_announcement_decisions",
    # A pair release names whose passages it holds (0405): the person's
    # membership in a weekly file belongs to the account, not to a project;
    # the weekly refresh voids the release for the object sweep.
    "pair_release_owners", "fine_tune_run_owners", "golden_judgements_by_owner",
    # A coach's own model readings (0409): their voice, under the coach
    # agreement; they belong to the coach's account, not to any project.
    "coach_readings",
    # A rater's own answers on others' clips (0410): the rater's account.
    "lend_your_ear_answers", "delayed_measure_votes",
    # A coach's own choices, blind answers and exposures (0411): the
    # coach's account; the Take-keyed twins of three of them go with the
    # Take under their own codes.
    "coach_exercise_preference_by_coach", "error_presence_audit_by_coach",
    "coach_block_pick_by_coach", "coach_clip_exposures",
    # Retention schedule v1.4: product records and job evidence that name
    # only the person, never a project. Deleted with the account (or kept
    # 12 months as job evidence); a project purge leaves them. Placed only
    # while their rule is active; until then they count as unplaced and a
    # row there stops a project purge for review, exactly as before v1.4.
    "coach_ai_review", "content_exposure_review", "student_profile_review",
    "student_memory_review", "student_overrides_review",
    "student_post_questions_review", "admin_session_override_review",
    "admin_archive_review", "admin_student_draft_review",
    "admin_annotation_review", "admin_annotation_log_review",
    "confidence_rereview", "dimension_evaluation_review",
    "intervention_arm_review", "coaching_directives_review",
    "life_consent_review", "life_setup_review", "life_notes_review",
    "life_cases_review", "life_items_review", "life_strategy_review",
    "life_proposals_review", "life_applications_review", "life_days_review",
    "life_weeks_review", "life_period_reviews_review",
    "life_setup_documents_review", "life_push_subscriptions_review",
    "life_reminder_settings_review", "life_reminder_log_review",
    "life_user_copy_review",
    "few_shot_review", "copilot_upload_jobs_review",
    "feedback_language_delivery_materialization_jobs",
    # Retention schedule v1.5: a reviewer's, author's, approver's or
    # recipient's own rows about someone else's work, the speaker's learning
    # profile, enrollment and speaker identity, the consent snapshot (kept as
    # evidence), a paid arc (kept as a financial record) and the reference
    # videos made for the speaker. They belong to the person; a project
    # purge leaves them. Placed only once v1.5 is registered and their rule
    # is active; until then they count as unplaced, exactly as before v1.5.
    "exercise_pair_assignment_reviewers", "exercise_pair_judgment_reviewers",
    "exercise_reviewer_context", "exercise_authoring_draft_authors",
    "exercise_service_confidence_assignment_reviewers",
    "exercise_service_confidence_render_reviewers",
    "exercise_service_confidence_judgment_reviewers",
    "exercise_service_blind_review_set_reviewers",
    "exercise_service_blind_reveal_grant_reviewers",
    "exercise_service_blind_reveal_access_reviewers",
    "mlc3_service_principal_allowlist_approvers",
    "feedback_language_delivery_recipients",
    "feedback_language_delivery_reviewers", "feedback_revision_reviewers",
    "confident_moment_coach_wording_reviewers",
    "coach_guidance_independent_media_reviewers",
    "coach_inline_source_role_reviewers", "coach_inline_exercise_draft_authors",
    "coach_inline_context_assessment_reviewers",
    "exercise_learning_profiles", "ml_speaker_binding", "ml_purge",
    "mlc3_service_principal_allowlist_subjects", "mlc3_service_cohort_members",
    "mlc3_service_enrollment_revisions", "mlc3_service_access_events",
    "mlc3_speaker_acquisition_revisions", "mlc3_self_speaker_assertions",
    "mlc3_target_speaker_bindings",
    "mlc3_comparison_speaker_eligibility_revisions",
    "ml_consent_snapshots", "arc_purchases_paid",
    "reference_videos_library", "reference_videos_own",
})

#: Retention schedule v1.5's records a project purge cannot reach by
#: project: each names only the person, and the row that names the project
#: is its parent (an item of a frame, an event of a session, a judgment of
#: an assignment). The account purge deletes them. A project purge stops for
#: review whenever the account holds any (PROJECT_SCOPE_UNRESOLVED), exactly
#: as it did before v1.5; all of them sit behind switches that are off.
PROJECT_REVIEW: frozenset[str] = frozenset({
    "canonical_dataset_exclusions", "canonical_release_items",
    "canonical_split_assignments", "coach_guidance_attachment_versions",
    "coach_guidance_attachments", "coach_guidance_independent_media_reviews",
    "coach_guidance_lifecycle_events", "coach_guidance_media_bindings",
    "coach_guidance_media_source_dependencies",
    "coach_guidance_media_validity_events",
    "coach_guidance_publication_invalidations", "coach_guidance_publications",
    "coach_guidance_reveal_accesses", "coach_guidance_reveal_grant_judgments",
    "coach_guidance_reveal_grants", "coach_guidance_review_batches",
    "coach_guidance_review_frame_items", "coach_guidance_upload_events",
    "coach_guidance_upload_permits", "coach_guidance_upload_recoveries",
    "coach_inline_context_assessments", "coach_inline_exercise_drafts",
    "coach_inline_exercise_eligibility_reviews", "coach_inline_source_roles",
    "confident_moment_bundle_projection_items",
    "confident_moment_coach_authorability_items",
    "confident_moment_coach_wording_subjects", "exercise_assignments",
    "exercise_authoring_drafts", "exercise_authorization_checks",
    "exercise_candidate_sets", "exercise_candidates",
    "exercise_feature_snapshots", "exercise_n1_pattern_candidates",
    "exercise_n1_pattern_snapshots", "exercise_n1_source_patterns",
    "exercise_pair_assignments", "exercise_pair_judgments",
    "exercise_pair_revisions", "exercise_practice_attempts",
    "exercise_practice_events", "exercise_practice_measurements",
    "exercise_practice_selections", "exercise_practice_transcription_runs",
    "exercise_practice_upload_recoveries", "exercise_practice_validity",
    "exercise_profile_observations", "exercise_randomization",
    "exercise_requests", "exercise_service_acquisition_receipts",
    "exercise_service_blind_reveal_accesses",
    "exercise_service_blind_reveal_grants",
    "exercise_service_blind_review_sets",
    "exercise_service_confidence_judgments",
    "exercise_service_confidence_render_receipts",
    "exercise_service_offer_candidates", "exercise_service_offer_events",
    "exercise_service_requests", "feedback_language_revision_deliveries",
    "feedback_revision_subjects", "ml_object_artifacts", "ml_product_actions",
    "root_phrase_coverage_items", "root_phrase_owner_alignment_actions",
    "root_phrase_qualification_revisions", "root_phrase_semantic_results",
})

#: Rows with no project column of their own that the take-record wipe
#: (`tombstone_phase1_purge_lineage_v1`) reaches through their parent and
#: counts in its `not_blank` check: code -> the parent's code.
WIPED_WITH_PARENT: Mapping[str, str] = {
    "canonical_acoustics": "evidence_spans",
}

#: Held by a project but outliving it under a rule that does not exist yet:
#: training copies stay while the training choice is on (draft policy 3.2,
#: section 4a). Any such row stops the purge for review.
PROJECT_HOLDS: Mapping[str, tuple[str, str]] = {
    "training_corpus_items": ("source_project_id", "project"),
}

_ACCOUNT_LOCATORS = frozenset({"principal", "user", "speaker", "permit"})


def account_keyed_codes() -> frozenset[str]:
    return frozenset(
        dependency.code for dependency in DEPENDENCIES
        if dependency.locator_kind in _ACCOUNT_LOCATORS
    )


def project_placement_sha256() -> str:
    """The registry's hash and this module's placement of it, together: a
    frozen project purge refuses to resume if either changed."""
    encoded = json.dumps({
        "registry": dependency_manifest_sha256(),
        "project_selectors": {k: list(v) for k, v in PROJECT_SELECTORS.items()},
        "account_level": sorted(ACCOUNT_LEVEL),
        "project_review": sorted(PROJECT_REVIEW),
        "wiped_with_parent": dict(WIPED_WITH_PARENT),
        "project_holds": {k: list(v) for k, v in PROJECT_HOLDS.items()},
    }, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class ProjectPurgeOrchestrator(DataPurgeOrchestrator):
    """Freeze, resolve and verify one `project_deletion` purge request."""

    scope = "project"
    resolver_version = PROJECT_RESOLVER_VERSION
    freeze_function = "freeze_phase1_project_purge_inventory_v1"

    def __init__(self, database: Any) -> None:
        super().__init__(database)
        self._project_id = ""
        self._principal_id = ""
        self._account_graph: SubjectGraph | None = None

    def _request(self, purge_request_id: str) -> dict:
        row = _one(
            self.client.table("data_purge_requests")
            .select("id,acquisition_principal_id,trigger_kind,state,project_id")
            .eq("id", purge_request_id).limit(1).execute().data
        )
        if not row:
            raise ValueError("PURGE_REQUEST_NOT_FOUND")
        if row.get("trigger_kind") != "project_deletion" or not row.get("project_id"):
            raise RuntimeError("PURGE_NOT_A_PROJECT_DELETION")
        self._project_id = str(row["project_id"])
        self._principal_id = str(row["acquisition_principal_id"])
        return row

    def build_subject_graph(
        self, principal_id: str, _existing_relations: frozenset[str],
    ) -> SubjectGraph:
        if not self._project_id:
            raise RuntimeError("PURGE_PROJECT_UNKNOWN")
        result = self.client.rpc("resolve_phase1_purge_project_graph_v1", {
            "p_acquisition_principal_id": principal_id,
            "p_project_id": self._project_id,
        }).execute()
        payload = _one(result.data)
        if not payload:
            raise RuntimeError("PURGE_SUBJECT_GRAPH_RESOLUTION_FAILED")
        if any(not isinstance(payload.get(key), list)
               for key in PROJECT_GRAPH_KEYS):
            raise RuntimeError("PURGE_SUBJECT_GRAPH_INVALID")
        graph = ProjectSubjectGraph(**{
            key: tuple(str(item) for item in payload[key])
            for key in PROJECT_GRAPH_KEYS
        })
        if graph.principal_ids or graph.user_ids or graph.permit_ids \
                or graph.speaker_ids or graph.project_ids != (self._project_id,):
            raise RuntimeError("PURGE_SUBJECT_GRAPH_NOT_ONE_PROJECT")
        return graph

    def _dependency_manifest_sha(self) -> str:
        return project_placement_sha256()

    def _graph_from_manifest(self, raw_graph: Mapping[str, Any]) -> SubjectGraph:
        return ProjectSubjectGraph(**{
            key: tuple(str(item) for item in raw_graph.get(key, []))
            for key in PROJECT_GRAPH_KEYS
        })

    def _account(self) -> SubjectGraph:
        """The whole account's coordinates, only ever to COUNT rows a
        project purge cannot place (never to delete anything)."""
        if self._account_graph is None:
            self._account_graph = super().build_subject_graph(
                self._principal_id, frozenset(),
            )
        return self._account_graph

    def _dependency(self, code: str) -> PurgeDependency | None:
        dependency = super()._dependency(code)
        if dependency is None or dependency.code not in PROJECT_SELECTORS:
            return dependency
        selector, locator = PROJECT_SELECTORS[dependency.code]
        return replace(
            dependency, selector_column=selector,
            locator_kind=locator,  # type: ignore[arg-type]
        )

    def _dependency_target(
        self,
        dependency: PurgeDependency,
        graph: SubjectGraph,
        existing_relations: frozenset[str],
    ) -> PurgeTarget | None:
        code = dependency.code
        if code in PROJECT_HOLDS:
            selector, locator = PROJECT_HOLDS[code]
            held = replace(
                dependency, selector_column=selector,
                locator_kind=locator,  # type: ignore[arg-type]
            )
            if dependency.relation in existing_relations and self._count(
                held, graph.values(locator), existing_relations,
            ):
                return PurgeTarget(
                    "unknown", f"dependency:{code}", 1,
                    {"reason_code": "PROJECT_ROWS_OUTLIVE_THE_PROJECT",
                     "dependency_code": code},
                )
            return None
        placed = (
            code in PROJECT_SELECTORS or code in ACCOUNT_LEVEL
            or code in WIPED_WITH_PARENT
        )
        decided, _rule = self._decided(dependency, existing_relations)
        if dependency.carved_from and _rule is None:
            # Not decided yet: its rows are still the original entry's.
            return None
        if dependency.ruled_by and decided.disposition == "external_review":
            # A ruled dependency whose rule (or schedule) is not in force is
            # the unplaced external_review entry it was before, counted so.
            placed = False
        remapped = (self._dependency(code) or dependency) if placed else dependency
        if (
            dependency.locator_kind in _ACCOUNT_LOCATORS
            and not placed
            and dependency.relation in existing_relations
        ):
            held_by_account = self._count(
                dependency, self._account().values(dependency.locator_kind),
                existing_relations,
            )
            if held_by_account:
                return PurgeTarget(
                    "unknown", f"dependency:{code}", held_by_account,
                    {"reason_code": "PROJECT_SCOPE_UNRESOLVED",
                     "dependency_code": code,
                     "relation": dependency.relation},
                )
        return super()._dependency_target(remapped, graph, existing_relations)

    def _practice_targets(
        self, graph: SubjectGraph, existing_relations: frozenset[str],
    ) -> list[PurgeTarget]:
        targets: list[PurgeTarget] = []
        rows = self._rows(
            "processing_practice_objects",
            "id,storage_provider,bucket,object_key,exact_bytes_sha256,deleted_at",
            selector="practice_attempt_id", values=graph.practice_attempt_ids,
            existing_relations=existing_relations,
        )
        for row in rows:
            provider = str(row.get("storage_provider") or "")
            already_purged = row.get("deleted_at") is not None
            targets.append(PurgeTarget(
                "r2_object" if provider == "r2" else "supabase_object",
                f"practice-object:{row.get('id')}",
                0 if already_purged else 1, {
                    "provider": provider,
                    "bucket": str(row.get("bucket") or ""),
                    "key": str(row.get("object_key") or ""),
                    "sha256": str(row.get("exact_bytes_sha256") or ""),
                    "source_relation": "processing_practice_objects",
                    "source_id": str(row.get("id") or ""),
                    "already_purged": already_purged,
                }))
        return targets

    def _storage_targets(
        self, graph: SubjectGraph, existing_relations: frozenset[str],
    ) -> list[PurgeTarget]:
        targets: list[PurgeTarget] = []
        attempts = self._rows(
            "processing_recording_attempts", "id,recording_id",
            selector="project_id", values=graph.project_ids,
            existing_relations=existing_relations,
        )
        attempts = [
            row for row in attempts if row.get("id")
        ]
        attempt_ids = tuple(sorted(self._ids(attempts, "id")))
        objects = self._rows(
            "processing_audio_objects",
            "id,recording_attempt_id,acquisition_principal_id,storage_provider,"
            "bucket,object_key,exact_bytes_sha256,deleted_at",
            selector="recording_attempt_id", values=attempt_ids,
            existing_relations=existing_relations,
        )
        deleted_audio_ids = self._ids(self._rows(
            "processing_audio_object_deletion_events", "audio_object_id",
            selector="audio_object_id",
            values=tuple(sorted(self._ids(objects, "id"))),
            existing_relations=existing_relations,
        ), "audio_object_id")
        recording_of = {
            str(row["id"]): str(row.get("recording_id") or "") for row in attempts
        }
        canonical_recordings: set[str] = set()
        for row in objects:
            if str(row.get("acquisition_principal_id") or "") != self._principal_id:
                targets.append(PurgeTarget(
                    "unknown", f"audio-object:{row.get('id')}", 1,
                    {"reason_code": "PROJECT_AUDIO_OWNER_MISMATCH"},
                ))
                continue
            canonical_recordings.add(
                recording_of.get(str(row.get("recording_attempt_id")), ""))
            provider = str(row.get("storage_provider") or "")
            already_purged = (
                row.get("deleted_at") is not None
                or str(row.get("id") or "") in deleted_audio_ids
            )
            targets.append(PurgeTarget(
                "r2_object" if provider == "r2" else "supabase_object",
                f"audio-object:{row.get('id')}", 0 if already_purged else 1, {
                    "provider": provider,
                    "bucket": str(row.get("bucket") or ""),
                    "key": str(row.get("object_key") or ""),
                    "sha256": str(row.get("exact_bytes_sha256") or ""),
                    "source_relation": "processing_audio_objects",
                    "source_id": str(row.get("id") or ""),
                    "already_purged": already_purged,
                }))
        targets.extend(self._practice_targets(graph, existing_relations))
        corpus = self._rows(
            "training_corpus_items", "id", selector="source_project_id",
            values=graph.project_ids, existing_relations=existing_relations,
        )
        for row in corpus:
            targets.append(PurgeTarget(
                "unknown", f"training-copy:{row.get('id')}", 1,
                {"reason_code": "PROJECT_ROWS_OUTLIVE_THE_PROJECT"},
            ))
        legacy = set(graph.recording_ids) - {v for v in canonical_recordings if v}
        for recording_id in sorted(legacy):
            targets.append(PurgeTarget(
                "unknown", f"legacy-audio:{recording_id}", 1,
                {"reason_code": "EXACT_AUDIO_OBJECT_LINEAGE_MISSING"},
            ))
        uploads = self._rows(
            "user_uploaded_files", "id", selector="session_id",
            values=graph.take_ids, existing_relations=existing_relations,
        )
        for row in uploads:
            targets.append(PurgeTarget(
                "unknown", f"user-upload:{row.get('id')}", 1,
                {"reason_code": "UPLOAD_PROVIDER_AND_SHA256_UNRESOLVED"},
            ))
        return targets

    def _provider_targets(
        self, graph: SubjectGraph, existing_relations: frozenset[str],
    ) -> list[PurgeTarget]:
        # Provider copies are the account's processor evidence; the project
        # graph carries no permit, and the freeze refuses any operation.
        return []

    def _reference_video_targets(
        self, graph: SubjectGraph, existing_relations: frozenset[str],
    ) -> list[PurgeTarget]:
        # A reference video belongs to the account (v1.5 P4); a project
        # purge leaves it and its file alone.
        return []

    def _object_is_shared(
        self, provider: str, bucket: str, key: str, principal_ids: Any,
    ) -> bool:
        # The project graph lists no principal; the owner is the requester.
        return super()._object_is_shared(
            provider, bucket, key, (self._principal_id,),
        )

    def run(self, purge_request_id: str) -> dict:
        outcome = super().run(purge_request_id)
        if (outcome.get("result") or {}).get("state") == "done":
            completed = self.client.rpc("complete_project_deletion_v1", {
                "p_purge_request_id": purge_request_id,
            }).execute()
            outcome["project_deletion"] = _one(completed.data) or {}
        return outcome


def orchestrator_for(database: Any, purge_request_id: str) -> DataPurgeOrchestrator:
    """The orchestrator that owns this request's scope."""
    row = _one(
        database.client.table("data_purge_requests").select("trigger_kind")
        .eq("id", purge_request_id).limit(1).execute().data
    )
    if not row:
        raise ValueError("PURGE_REQUEST_NOT_FOUND")
    if row.get("trigger_kind") == "project_deletion":
        return ProjectPurgeOrchestrator(database)
    return DataPurgeOrchestrator(database)
