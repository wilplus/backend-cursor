"""Persistence boundary for the first-client exercise service.

The service deliberately keeps SQL authority in reviewed RPCs. This repository
contains only transport normalization and narrowly-scoped read composition,
keeping the shared DatabaseService from becoming workflow glue.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_SERVICE_OPERATION_MODES = (
    "allowlisted_service",
    "cohort_service",
    "general_service",
)


class FirstClientRepository:
    """RPC/read facade for the gated first-client service."""

    def __init__(self, client_provider: Callable[[], Any]) -> None:
        self._client_provider = client_provider

    @property
    def client(self) -> Any:
        """Return the current client, including replacements after reconnect."""
        return self._client_provider()

    @staticmethod
    def _rpc_row(data: Any) -> Optional[dict]:
        if isinstance(data, dict):
            return data
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        return None

    def get_current_ideal_text_document_snapshot(
        self, project_id: str,
    ) -> Optional[dict]:
        """Read the current immutable Ideal Text payload for one Project."""
        try:
            heads = (self.client.table("ideal_text_document_heads")
                     .select("snapshot_id,source_generation")
                     .eq("arc_id", str(project_id)).limit(1).execute().data or [])
            if not heads or not heads[0].get("snapshot_id"):
                return None
            rows = (self.client.table("ideal_text_document_snapshots")
                    .select("*").eq("id", str(heads[0]["snapshot_id"]))
                    .eq("project_id", str(project_id)).limit(1).execute().data or [])
            return rows[0] if rows else None
        except Exception as error:
            logger.warning(
                "current Ideal Text snapshot read failed project=%s: %s",
                project_id, error,
            )
            return None

    def ensure_service_enrollment(
        self,
        *,
        acquisition_principal_id: str,
        owner_user_id: str,
        idempotency_key: str,
    ) -> Optional[dict]:
        """Resolve the current rollout and create/replay exact enrollment."""
        try:
            result = self.client.rpc(
                "ensure_mlc3_service_enrollment_v2",
                {
                    "p_acquisition_principal_id": str(
                        acquisition_principal_id
                    ),
                    "p_owner_user_id": str(owner_user_id),
                    "p_idempotency_key": str(idempotency_key),
                },
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning(
                "MLC-3 rollout enrollment failed principal=%s: %s",
                acquisition_principal_id,
                error,
            )
            return None

    def record_feedback_self_speaker_target(
        self, payload: dict,
    ) -> Optional[dict]:
        """Persist the exact affirmative source-voice routing action."""
        try:
            result = self.client.rpc(
                "record_mlc3_feedback_self_speaker_target_v1", payload,
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Source self-speaker confirmation failed: %s", error)
            return None

    def confirm_practice_speaker_and_pair(
        self, payload: dict,
    ) -> Optional[dict]:
        """Persist practice voice identity and create an exact same-speaker pair."""
        try:
            result = self.client.rpc(
                "confirm_mlc3_practice_speaker_and_pair_v1", payload,
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Practice self-speaker confirmation failed: %s", error)
            return None

    def record_feedback_v3_service_candidate_set(
        self, bundle: dict,
    ) -> Optional[dict]:
        """Atomically record one complete, dataset-ineligible V3 inventory."""
        if not isinstance(bundle, dict):
            return None
        required = (
            "owner_principal_id", "project_id", "take_id", "candidates",
            "selected_keys", "versions", "input_hash", "idempotency_key",
        )
        if any(not bundle.get(key) for key in required):
            return None
        try:
            result = self.client.rpc(
                "record_feedback_v3_service_candidate_set_v1", {
                    "p_acquisition_principal_id": str(
                        bundle["owner_principal_id"]
                    ),
                    "p_project_id": str(bundle["project_id"]),
                    "p_take_id": str(bundle["take_id"]),
                    "p_bundle": bundle,
                },
            ).execute()
            data = result.data
            if isinstance(data, list):
                return data[0] if data and isinstance(data[0], dict) else None
            return data if isinstance(data, dict) else None
        except Exception as error:
            logger.warning(
                "Feedback V3 service candidate set failed take=%s: %s",
                bundle.get("take_id"), error,
            )
            return None

    def freeze_feedback_v3_service_membership(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "freeze_feedback_v3_service_membership_v1", payload,
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Feedback V3 service freeze failed: %s", error)
            return None

    def prepare_feedback_v3_service_context(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "prepare_feedback_v3_service_context_v1", payload,
            ).execute()
            data = result.data
            if isinstance(data, list):
                return data[0] if data and isinstance(data[0], dict) else None
            return data if isinstance(data, dict) else None
        except Exception as error:
            logger.warning("Feedback V3 service context failed: %s", error)
            return None

    def ack_feedback_v3_service_render(self, payload: dict) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "ack_feedback_v3_service_render_v1", payload,
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Feedback V3 render receipt failed: %s", error)
            return None

    def record_feedback_v3_service_response(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "record_feedback_v3_service_response_v1", payload,
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Feedback V3 service response failed: %s", error)
            return None

    def freeze_exercise_service_offer_v2(self, payload: dict) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "freeze_exercise_service_offer_v2", payload,
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Exercise service offer freeze failed: %s", error)
            return None

    def record_exercise_offer_service_event(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "record_exercise_offer_service_event_v1", payload,
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Exercise service event failed: %s", error)
            return None

    def get_exercise_service_offer(
        self, offer_id: str, acquisition_principal_id: str,
    ) -> Optional[dict]:
        try:
            rows = (self.client.table("exercise_service_offers")
                    .select("*").eq("id", str(offer_id))
                    .eq("acquisition_principal_id",
                        str(acquisition_principal_id))
                    .in_("operation_mode", list(_SERVICE_OPERATION_MODES))
                    .eq("serves_user", True).eq("dataset_eligible", False)
                    .limit(1).execute().data or [])
            return rows[0] if rows else None
        except Exception as error:
            logger.warning("Exercise service offer read failed: %s", error)
            return None

    def resolve_exercise_service_offer_read(
        self, offer_id: str, acquisition_principal_id: str,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "resolve_exercise_service_offer_read_v1",
                {
                    "p_offer_id": str(offer_id),
                    "p_acquisition_principal_id": str(acquisition_principal_id),
                },
            ).execute().data
            return dict(result) if isinstance(result, dict) else self._rpc_row(result)
        except Exception as error:
            logger.warning("Exercise service authoritative read failed: %s", error)
            return None

    def get_exercise_service_version(self, exercise_version_id: str) -> Optional[dict]:
        try:
            versions = (self.client.table("exercise_versions")
                        .select("*").eq("id", str(exercise_version_id))
                        .eq("safety_state", "approved")
                        .eq("catalogue_state", "active")
                        .limit(1).execute().data or [])
            if not versions:
                return None
            version = dict(versions[0])
            media_id = version.get("media_object_id")
            media = (self.client.table("exercise_media_objects")
                     .select("id,bucket,object_key,exact_bytes_sha256,"
                             "byte_size,content_type")
                     .eq("id", str(media_id)).limit(1).execute().data or [])
            version["media"] = media[0] if media else None
            return version
        except Exception as error:
            logger.warning("Exercise service version read failed: %s", error)
            return None

    def create_exercise_practice_service_session(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "create_exercise_practice_service_session_v1", payload,
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Practice service session creation failed: %s", error)
            return None

    def get_exercise_practice_service_session(
        self, session_id: str, acquisition_principal_id: str,
    ) -> Optional[dict]:
        try:
            rows = (self.client.table("exercise_practice_sessions")
                    .select("*").eq("id", str(session_id))
                    .eq("acquisition_principal_id",
                        str(acquisition_principal_id))
                    .in_("operation_mode", list(_SERVICE_OPERATION_MODES))
                    .eq("serves_user", True).eq("dataset_eligible", False)
                    .limit(1).execute().data or [])
            return rows[0] if rows else None
        except Exception as error:
            logger.warning("Practice service session read failed: %s", error)
            return None

    def resolve_exercise_practice_session_read(
        self, session_id: str, acquisition_principal_id: str,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "resolve_exercise_practice_session_read_v1",
                {
                    "p_session_id": str(session_id),
                    "p_acquisition_principal_id": str(acquisition_principal_id),
                },
            ).execute().data
            return dict(result) if isinstance(result, dict) else self._rpc_row(result)
        except Exception as error:
            logger.warning("Practice service authoritative read failed: %s", error)
            return None

    def resolve_exercise_practice_media_read(
        self, attempt_id: str, acquisition_principal_id: str,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "resolve_exercise_practice_media_read_v1",
                {
                    "p_attempt_id": str(attempt_id),
                    "p_acquisition_principal_id": str(acquisition_principal_id),
                },
            ).execute().data
            return dict(result) if isinstance(result, dict) else self._rpc_row(result)
        except Exception as error:
            logger.warning("Practice media authoritative read failed: %s", error)
            return None

    def get_exercise_service_source_audio(
        self, audio_lineage_id: str, acquisition_principal_id: str,
    ) -> Optional[dict]:
        try:
            rows = (self.client.table("exercise_audio_lineages")
                    .select("id,start_offset_ms,duration_ms,"
                            "processing_audio_object_id,"
                            "processing_audio_objects!inner("
                            "id,bucket,object_key,exact_bytes_sha256,"
                            "byte_size,content_type,deleted_at)")
                    .eq("id", str(audio_lineage_id))
                    .eq("acquisition_principal_id",
                        str(acquisition_principal_id))
                    .is_("processing_audio_objects.deleted_at", "null")
                    .limit(1).execute().data or [])
            return rows[0] if rows else None
        except Exception as error:
            logger.warning("Exercise source audio read failed: %s", error)
            return None

    def reserve_exercise_practice_service_upload(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "reserve_exercise_practice_service_upload_v2", payload,
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Practice service upload reservation failed: %s", error)
            return None

    def ack_exercise_practice_service_upload(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "ack_exercise_practice_service_upload_v1", payload,
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Practice service upload acknowledgement failed: %s", error)
            return None

    def finalize_exercise_practice_service_media(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "finalize_exercise_practice_service_media_v1", payload,
            ).execute()
            data = result.data
            return data if isinstance(data, dict) else self._rpc_row(data)
        except Exception as error:
            logger.warning("Practice service media finalization failed: %s", error)
            return None

    def authorize_exercise_practice_transcription(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "authorize_exercise_practice_transcription_v1", payload,
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning(
                "Practice transcription authorization failed: %s", error
            )
            return None

    def finalize_exercise_practice_transcription(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "finalize_exercise_practice_transcription_v1", payload,
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning(
                "Practice transcription finalization failed: %s", error
            )
            return None

    def mark_exercise_practice_transcription_dispatched(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "mark_exercise_practice_transcription_dispatched_v1", payload,
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning(
                "Practice transcription dispatch failed: %s", error
            )
            return None

    def reconcile_exercise_practice_transcription(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "reconcile_exercise_practice_transcription_v1", payload,
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.error(
                "Practice transcription reconciliation failed: %s", error
            )
            return None

    def reconcile_exercise_practice_transcription_request(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "reconcile_exercise_practice_transcription_request_v1",
                payload,
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.error(
                "Practice transcription request reconciliation failed: %s",
                error,
            )
            return None

    def attach_exercise_practice_service_attempt(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "attach_exercise_practice_service_attempt_v1", payload,
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Practice service attempt attachment failed: %s", error)
            return None

    def record_exercise_practice_service_measurement(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "record_exercise_practice_service_measurement_v1", payload,
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Practice service measurement failed: %s", error)
            return None

    def record_exercise_practice_service_validity(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "record_exercise_practice_service_validity_v1", payload,
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Practice service validity failed: %s", error)
            return None

    def freeze_exercise_practice_service_selection(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "freeze_exercise_practice_service_selection_v1", payload,
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Practice service selection failed: %s", error)
            return None

    def record_exercise_practice_service_event(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "record_exercise_practice_service_event_v1", payload,
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Practice service event failed: %s", error)
            return None

    def freeze_exercise_service_pair(self, payload: dict) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "freeze_exercise_service_pair_v1", payload,
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Exercise service pair freeze failed: %s", error)
            return None

    def assign_exercise_service_owner_pair(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "assign_exercise_service_owner_pair_v1", payload,
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Exercise service owner pair failed: %s", error)
            return None

    def submit_exercise_service_owner_pair_judgment(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "submit_exercise_service_owner_pair_judgment_v1", payload,
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Exercise service owner preference failed: %s", error)
            return None

    def get_exercise_service_owner_pair(
        self, practice_session_id: str, acquisition_principal_id: str,
    ) -> Optional[dict]:
        """Return the exact current service pair without exposing blind state."""
        try:
            pairs = (self.client.table("exercise_pair_revisions")
                     .select("*")
                     .eq("practice_session_id", str(practice_session_id))
                     .eq("acquisition_principal_id",
                         str(acquisition_principal_id))
                     .in_("operation_mode", list(_SERVICE_OPERATION_MODES))
                     .order("comparison_revision", desc=True)
                     .limit(1).execute().data or [])
            if not pairs:
                return None
            pair = dict(pairs[0])
            assignments = (self.client.table("exercise_pair_assignments")
                           .select("*")
                           .eq("pair_revision_id", str(pair["id"]))
                           .eq("reviewer_principal_id",
                               str(acquisition_principal_id))
                           .eq("reviewer_role", "owner")
                           .in_("operation_mode", list(_SERVICE_OPERATION_MODES))
                           .limit(1).execute().data or [])
            pair["assignment"] = assignments[0] if assignments else None
            return pair
        except Exception as error:
            logger.warning("Exercise service owner pair read failed: %s", error)
            return None

    def list_exercise_service_review_sessions(
        self, project_id: str,
    ) -> Optional[list[dict]]:
        """List only first-client sessions with a frozen first-valid attempt."""
        try:
            return (self.client.table("exercise_practice_sessions")
                    .select("id,acquisition_principal_id,project_id")
                    .eq("project_id", str(project_id))
                    .in_("operation_mode", list(_SERVICE_OPERATION_MODES))
                    .eq("serves_user", True).eq("dataset_eligible", False)
                    .order("created_at").execute().data or [])
        except Exception as error:
            logger.warning("Exercise service review sessions failed: %s", error)
            return None

    def freeze_exercise_service_blind_review_set(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "freeze_exercise_service_blind_review_set_v1", payload,
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Exercise service review-set freeze failed: %s", error)
            return None

    def get_exercise_service_blind_review_set(
        self, review_set_id: str, reviewer_principal_id: str,
    ) -> Optional[dict]:
        try:
            sets = (self.client.table("exercise_service_blind_review_sets")
                    .select("*").eq("id", str(review_set_id))
                    .eq("reviewer_principal_id", str(reviewer_principal_id))
                    .limit(1).execute().data or [])
            if not sets:
                return None
            review_set = dict(sets[0])
            assignment_ids = [
                review_set["source_confidence_assignment_id"],
                review_set["practice_confidence_assignment_id"],
            ]
            assignments = (self.client.table(
                "exercise_service_confidence_assignments"
            ).select("*").in_("id", assignment_ids)
                           .eq("reviewer_principal_id",
                               str(reviewer_principal_id))
                           .execute().data or [])
            judgments = (self.client.table(
                "exercise_service_confidence_judgments"
            ).select("*").in_("assignment_id", assignment_ids)
                         .eq("reviewer_principal_id",
                             str(reviewer_principal_id))
                         .execute().data or [])
            review_set["assignments"] = assignments
            review_set["judgments"] = judgments
            return review_set
        except Exception as error:
            logger.warning("Exercise service review-set read failed: %s", error)
            return None

    def ack_exercise_service_confidence_render(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "ack_exercise_service_confidence_render_v1", payload,
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Exercise service review render failed: %s", error)
            return None

    def submit_exercise_service_confidence_judgment(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "submit_exercise_service_confidence_judgment_v1", payload,
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Exercise service review judgment failed: %s", error)
            return None

    def complete_exercise_service_blind_review(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "complete_exercise_service_blind_review_v1", payload,
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Exercise service review completion failed: %s", error)
            return None

    def access_exercise_service_blind_reveal(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "access_exercise_service_blind_reveal_v1", payload,
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Exercise service reveal access failed: %s", error)
            return None

    def get_exercise_service_guidance_context(
        self, review_set_id: str, reviewer_principal_id: str,
    ) -> Optional[dict]:
        """Read post-blind product context; RPCs still authorize every write."""
        try:
            sets = (self.client.table("exercise_service_blind_review_sets")
                    .select("*").eq("id", str(review_set_id))
                    .eq("reviewer_principal_id", str(reviewer_principal_id))
                    .limit(1).execute().data or [])
            if not sets:
                return None
            review_set = dict(sets[0])
            grants = (self.client.table("exercise_service_blind_reveal_grants")
                      .select("*").eq("review_set_id", str(review_set_id))
                      .eq("reviewer_principal_id", str(reviewer_principal_id))
                      .limit(1).execute().data or [])
            if not grants:
                return None
            sessions = (self.client.table("exercise_practice_sessions")
                        .select("*").eq("id", review_set["practice_session_id"])
                        .in_("operation_mode", list(_SERVICE_OPERATION_MODES))
                        .limit(1).execute().data or [])
            if not sessions:
                return None
            session = dict(sessions[0])
            offers = (self.client.table("exercise_service_offers")
                      .select("*").eq("id", session["source_offer_id"])
                      .in_("operation_mode", list(_SERVICE_OPERATION_MODES))
                      .limit(1).execute().data or [])
            if not offers:
                return None
            offer = dict(offers[0])
            items = (self.client.table("feedback_v3_membership_items")
                     .select("*").eq("membership_id",
                                      offer["feedback_membership_id"])
                     .eq("candidate_id", offer["feedback_candidate_id"])
                     .in_("operation_mode", list(_SERVICE_OPERATION_MODES))
                     .eq("selected", True).limit(1).execute().data or [])
            candidate_sets = (self.client.table("exercise_candidate_sets")
                              .select("need_contract_id")
                              .eq("id", offer["n1_candidate_set_id"])
                              .limit(1).execute().data or [])
            assignments = (self.client.table(
                "exercise_service_confidence_assignments"
            ).select("*").eq(
                "id", review_set["source_confidence_assignment_id"]
            ).eq("reviewer_principal_id", str(reviewer_principal_id))
                         .limit(1).execute().data or [])
            measurements = (self.client.table(
                "exercise_practice_measurement_revisions"
            ).select("raw_measurements,safeguards,extractor_version,"
                     "feature_schema_version")
             .eq("attempt_id", review_set["practice_attempt_id"])
             .in_("operation_mode", list(_SERVICE_OPERATION_MODES))
             .order("measurement_revision", desc=True).limit(1)
             .execute().data or [])
            if not items or not candidate_sets or not assignments:
                return None
            return {
                "review_set": review_set,
                "reveal_grant": dict(grants[0]),
                "practice_session": session,
                "offer": offer,
                "feedback_item": dict(items[0]),
                "source_assignment": dict(assignments[0]),
                "need_contract_id": candidate_sets[0]["need_contract_id"],
                "features": dict(measurements[0]) if measurements else {},
            }
        except Exception as error:
            logger.warning("Exercise service guidance context failed: %s", error)
            return None

    def reserve_coach_guidance_service_upload(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            return self._rpc_row(self.client.rpc(
                "reserve_coach_guidance_service_upload_v1", payload,
            ).execute().data)
        except Exception as error:
            logger.warning("Coach guidance service upload reserve failed: %s", error)
            return None

    def record_coach_guidance_service_upload_event(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            return self._rpc_row(self.client.rpc(
                "record_coach_guidance_service_upload_event_v1", payload,
            ).execute().data)
        except Exception as error:
            logger.warning("Coach guidance service upload event failed: %s", error)
            return None

    def finalize_coach_guidance_service_media(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "finalize_coach_guidance_service_media_v1", payload,
            ).execute().data
            return dict(result) if isinstance(result, dict) else self._rpc_row(result)
        except Exception as error:
            logger.warning("Coach guidance service media finalize failed: %s", error)
            return None

    def create_coach_guidance_service_attachment(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            return self._rpc_row(self.client.rpc(
                "create_coach_guidance_service_attachment_v1", payload,
            ).execute().data)
        except Exception as error:
            logger.warning("Coach guidance service attachment failed: %s", error)
            return None

    def record_coach_guidance_service_event(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            return self._rpc_row(self.client.rpc(
                "record_coach_guidance_service_event_v1", payload,
            ).execute().data)
        except Exception as error:
            logger.warning("Coach guidance service event failed: %s", error)
            return None

    def publish_coach_guidance_service_exercise(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            return self._rpc_row(self.client.rpc(
                "publish_coach_guidance_service_exercise_v1", payload,
            ).execute().data)
        except Exception as error:
            logger.warning("Coach guidance service publication failed: %s", error)
            return None

    def list_coach_guidance_service_assignments(
        self, membership_id: str, acquisition_principal_id: str,
    ) -> Optional[list[dict]]:
        """Return assigned service versions; lifecycle writes remain RPC-only."""
        try:
            attachments = (self.client.table("coach_guidance_attachments")
                           .select("*").eq("feedback_membership_id",
                                            str(membership_id))
                           .eq("acquisition_principal_id",
                               str(acquisition_principal_id))
                           .in_("operation_mode", list(_SERVICE_OPERATION_MODES))
                           .execute().data or [])
            result: list[dict] = []
            for attachment in attachments:
                versions = (self.client.table("coach_guidance_attachment_versions")
                            .select("*").eq("attachment_id", attachment["id"])
                            .in_("operation_mode", list(_SERVICE_OPERATION_MODES))
                            .eq("serves_user", True).order(
                                "version_number", desc=True
                            ).limit(1).execute().data or [])
                if not versions:
                    continue
                assigned = (self.client.table("coach_guidance_lifecycle_events")
                            .select("id").eq("attachment_version_id",
                                             versions[0]["id"])
                            .eq("event_kind", "assigned")
                            .in_("operation_mode", list(_SERVICE_OPERATION_MODES))
                            .limit(1).execute().data or [])
                if assigned:
                    result.append({
                        "attachment": dict(attachment),
                        "version": dict(versions[0]),
                    })
            return result
        except Exception as error:
            logger.warning("Coach guidance service assignments failed: %s", error)
            return None

    def resolve_coach_guidance_service_media_read(
        self, attachment_version_id: str, acquisition_principal_id: str,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "resolve_coach_guidance_service_media_read_v1",
                {
                    "p_attachment_version_id": str(attachment_version_id),
                    "p_recipient_principal_id": str(acquisition_principal_id),
                },
            ).execute().data
            return dict(result) if isinstance(result, dict) else self._rpc_row(
                result
            )
        except Exception as error:
            logger.warning("Coach guidance media read failed: %s", error)
            return None

    def get_processing_audio_object(self, object_id: str) -> Optional[dict]:
        try:
            rows = (self.client.table("processing_audio_objects")
                    .select("id,acquisition_principal_id,bucket,object_key,"
                            "exact_bytes_sha256,byte_size,content_type,deleted_at")
                    .eq("id", str(object_id)).is_("deleted_at", "null")
                    .limit(1).execute().data or [])
            return rows[0] if rows else None
        except Exception as error:
            logger.warning("Processing audio object read failed: %s", error)
            return None

    def resolve_exercise_confidence_media_read(
        self, playback_reference_id: str, reviewer_principal_id: str,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "resolve_exercise_confidence_media_read_v1",
                {
                    "p_playback_reference_id": str(playback_reference_id),
                    "p_reviewer_principal_id": str(reviewer_principal_id),
                },
            ).execute().data
            return dict(result) if isinstance(result, dict) else self._rpc_row(result)
        except Exception as error:
            logger.warning("Confidence media authoritative read failed: %s", error)
            return None

    # ── D5 inline coach exercise authoring (dark/gated) ───────────────

    def prepare_coach_inline_blind_batch(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "prepare_coach_inline_blind_batch_v1", payload
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Coach inline blind batch failed: %s", error)
            return None

    def ack_coach_inline_blind_render(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "ack_coach_inline_blind_render_v1", payload
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Coach inline blind render failed: %s", error)
            return None

    def submit_coach_inline_blind_judgment(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "submit_coach_inline_blind_judgment_v1", payload
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Coach inline blind judgment failed: %s", error)
            return None

    def get_project_identity(self, project_id: str) -> Optional[dict]:
        try:
            rows = (self.client.table("projects")
                    .select("id,owner_principal_id")
                    .eq("id", str(project_id)).limit(1).execute().data or [])
            return dict(rows[0]) if rows else None
        except Exception as error:
            logger.warning("Coach inline project identity failed: %s", error)
            return None

    def freeze_coach_guidance_batch(self, payload: dict) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "freeze_synthetic_coach_guidance_batch_v1", payload
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Coach inline batch freeze failed: %s", error)
            return None

    def complete_coach_guidance_batch(self, payload: dict) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "complete_synthetic_coach_guidance_batch_v1", payload
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Coach inline batch completion failed: %s", error)
            return None

    def prepare_coach_inline_guidance_context(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "prepare_coach_inline_guidance_context_v1", payload
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Coach inline guidance context failed: %s", error)
            return None

    def issue_coach_inline_general_authority(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "issue_coach_inline_general_authority_v1", payload
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Coach inline general authority failed: %s", error)
            return None

    def reserve_coach_inline_upload(self, payload: dict) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "reserve_synthetic_coach_guidance_upload_v1", payload
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Coach inline upload reserve failed: %s", error)
            return None

    def record_coach_inline_upload_event(self, payload: dict) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "record_synthetic_coach_guidance_upload_event_v1", payload
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Coach inline upload event failed: %s", error)
            return None

    def register_exercise_media_object(self, payload: dict) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "register_exercise_media_object_v1", payload
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Coach inline media object failed: %s", error)
            return None

    def register_coach_inline_media(self, payload: dict) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "register_synthetic_coach_guidance_media_v1", payload
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Coach inline media binding failed: %s", error)
            return None

    def create_coach_inline_attachment(self, payload: dict) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "create_coach_inline_exercise_attachment_v1", payload
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Coach inline attachment failed: %s", error)
            return None

    def create_coach_inline_general_guidance(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "create_coach_inline_general_guidance_v1", payload
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Coach inline general guidance failed: %s", error)
            return None

    def create_coach_inline_exercise_draft(
        self, payload: dict,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "create_coach_inline_exercise_draft_v1", payload
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Coach inline exercise draft failed: %s", error)
            return None

    def resolve_coach_inline_media_read(
        self, draft_id: str, reviewer_principal_id: str,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "resolve_coach_inline_media_read_v1",
                {
                    "p_draft_id": str(draft_id),
                    "p_reviewer_principal_id": str(reviewer_principal_id),
                },
            ).execute()
            data = result.data
            return dict(data) if isinstance(data, dict) else self._rpc_row(data)
        except Exception as error:
            logger.warning("Coach inline media read failed: %s", error)
            return None

    def resolve_coach_inline_blind_audio_read(
        self, assignment_id: str, reviewer_user_id: str,
        reviewer_principal_id: str,
    ) -> Optional[dict]:
        """Resolve one opaque coach assignment to its authorized R2 clip."""
        try:
            result = self.client.rpc(
                "resolve_coach_inline_blind_audio_read_v1", {
                    "p_evidence_review_assignment_id": str(assignment_id),
                    "p_reviewer_user_id": str(reviewer_user_id),
                    "p_reviewer_principal_id": str(reviewer_principal_id),
                },
            ).execute()
            data = result.data
            return dict(data) if isinstance(data, dict) else self._rpc_row(data)
        except Exception as error:
            logger.warning("Coach inline blind audio read failed: %s", error)
            return None
