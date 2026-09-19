"""Fail-closed preparation of allowlisted Feedback V3 product rows.

This module is a product integration seam, not a learning producer.  It
creates a fresh service candidate inventory, freezes it against the current
Ideal Text snapshot, and adds exercise context only where an independently
frozen N1 inventory already exists for the exact clip.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from hashlib import sha256
from typing import Any, NamedTuple
import uuid

from services.coach_guidance_delivery import principal_is_allowlisted
from services.feedback_data_contract import build_feedback_exposure_bundle
from services.take_feedback_policy_v3 import build_service_candidate_frame
from services.take_feedback_policy_v3_service import prepare_v3_service_inventory


logger = logging.getLogger(__name__)


class V3Unavailable(NamedTuple):
    """V3 was asked for this Take and could not produce it.

    NOT THE SAME AS "V3 does not apply here" (founder 2026-09-18, contract
    24h). A user outside the service gets the legacy answer and nothing is
    wrong; a user inside it whose take V3 could not process has hit a fault,
    and the old code returned `None` for both — so a broken V3 and a
    working one looked identical from the outside. That is how a production
    defect survived two days of being looked at directly.

    `None` now means only "not applicable". Everything past the gate returns
    one of these, and the caller surfaces it instead of quietly serving V2.
    """

    reason: str


def _not_applicable(take_id: Any, reason: str) -> None:
    """V3 was never in play for this Take — the legacy answer is correct.

    Kept separate from `_decline` on purpose. Collapsing the two is what made
    "you are not in the service" indistinguishable from "the service broke",
    and the whole point of 24h is that those two must never look alike again.

    Returns nothing, so its one call site is a log line plus `return None`
    rather than the single `return _decline(...)` the failure exits use. Two
    lines is worth it here: typing it `-> None` is what lets mypy prove no
    FAILURE path can ever reach this exit by mistake.
    """
    logger.info("first_client: v3 not applicable take=%s reason=%s",
                take_id or "?", reason)
    return None


def _decline(take_id: Any, reason: str, detail: str = "") -> V3Unavailable:
    """Say WHY v3 stood down, then stand down.

    FOUNDER 2026-09-17, after an afternoon of log searches that found
    nothing: "please make the V3 finally work." It could not be made to
    work because it could not be diagnosed — this function is fail-closed
    by design, with a separate `return None` at each of its checks, and not
    one of them said anything. The surface simply fell back to v2 and the
    only evidence was an absence.

    Naming them is what found the real defect. `service_enrollment_missing`
    was the twelfth, and once it started speaking it turned out to be a gate
    that no user could ever pass — the Phase-2 exercise purpose it demanded
    is the one the acceptance function refuses to write. It is gone (see
    `prepare_first_client_feedback`); the remaining eleven are real.

    Fail-closed is right and stays. Fail-SILENT is not the same thing and
    was never intended: refusing to serve a candidate you cannot prove is a
    safety property, refusing to say which proof was missing is just a
    missing log line. Every exit now names itself once per attempt.

    INFO, not WARNING: standing down is the designed behaviour, not a
    fault. `first_client` in the backend log is now a complete account of
    why this take is on v2 rather than v3.

    `detail` CARRIES THE UNDERLYING ERROR, LOG-ONLY (2026-09-18). Naming the
    exits was half the job: `source_snapshot_rpc_failed` says a PostgreSQL
    call raised, and a bare `except Exception` then threw away the one thing
    that identifies WHICH guard raised it. The RPC reaches
    `require_mlc3_service_access_v2`, which can answer
    MLC3_ROLLOUT_NOT_ACTIVE, MLC3_CURRENT_ENROLLMENT_REQUIRED,
    MLC3_COHORT_MEMBERSHIP_REQUIRED or FEEDBACK_V3_SOURCE_SNAPSHOT_INVALID —
    four different states, four different fixes, one indistinguishable log
    line. That cost a production day of guessing.

    It stays OUT of `V3Unavailable`: the reason code is what the client is
    handed, and a database error string is a server diagnostic, not a
    payload. Nothing here asserts anything about the speaker.
    """
    logger.info("first_client: v3 stood down take=%s reason=%s%s",
                take_id or "?", reason,
                f" detail={detail}" if detail else "")
    # Returned, not raised, so `return _decline(...)` stays one statement at
    # each of the eleven exits. Splitting them into a log line plus a bare
    # return is twenty-two lines in which one exit can quietly lose its log
    # again — the exact failure this function exists to prevent.
    return V3Unavailable(reason)


def _exercise_context_available(
    database: Any, *, principal_id: str, owner_user_id: str, take_id: str,
) -> bool:
    """May this take's Confident Voice rows carry exercise context?

    THIS IS NOT A GATE ON FEEDBACK (founder 2026-09-17, "I want the V3 in all
    its wholeness", then option A: V3 must not need the exercise purpose).

    `prepare_first_client_feedback` used to `return None` when enrollment
    failed, which put the whole of V3 — Manager arbitration, the 75-word block
    partition, every Confident Voice item — behind the MLC-3 EXERCISE service.
    That gate is unreachable by construction: `ensure_mlc3_service_enrollment_v2`
    demands a receipt carrying `personalized_exercise_recommendation`, and
    `accept_phase1_processing_authorization_v1` raises PHASE2_PURPOSE_FORBIDDEN
    on any policy that lists it. One function requires the purpose, the only
    function that can write it refuses — so no user could ever satisfy the gate
    and V3 could never serve anyone.

    Nothing between the caller's entry and its membership freeze needs it. The
    SQL says so: `record_feedback_v3_service_candidate_set_v1` has no MLC-3
    check at all, and `freeze_feedback_v3_service_membership_v1` calls
    `require_mlc3_service_principal_v1` — active service contract plus
    allowlist, no rollout, no enrollment, no dual-purpose receipt. Only
    `prepare_feedback_v3_service_context_v1` reaches Phase-2 exercise data, and
    that one is authorized separately in PostgreSQL anyway.

    So enrollment decides ONE thing: whether a row carries its exercise
    context. Without it the row still surfaces and the reader falls back to the
    Confident Voice question, which is the state the frontend already renders
    (`mapFirstClientService` → null). Standing down from the Phase-2 path when
    it is unauthorized is the boundary working, not a degradation.
    """
    enrollment = database.ensure_service_enrollment(
        acquisition_principal_id=principal_id,
        owner_user_id=str(owner_user_id),
        idempotency_key=f"feedback-entry:{take_id}",
    )
    if isinstance(enrollment, dict) and enrollment.get("id"):
        return True
    logger.info(
        "first_client: v3 serving take=%s WITHOUT exercise context "
        "(reason=service_enrollment_unavailable)", take_id or "?",
    )
    return False


def _canonical_index(bundle: dict) -> dict[tuple[str, str], dict]:
    return {
        (str(row.get("feedback_family") or ""), str(row.get("candidate_key") or "")): row
        for row in bundle.get("candidates") or []
        if isinstance(row, dict)
    }


def prepare_first_client_feedback(
    *,
    database: Any,
    session: Any,
    take_document: Any,
    served_text: str,
    snippets: Any,
    suggestions: Any,
    feedback_candidates: Iterable[Any],
    owner_user_id: str,
) -> list[dict] | V3Unavailable | None:
    """Rows, a typed failure, or ``None`` when V3 does not apply here.

    Three outcomes, not two (contract 24h). ``None`` means this Take is
    outside the service and the legacy answer is correct. A `V3Unavailable`
    means V3 owned this Take and could not produce it, which the caller
    surfaces rather than papering over with V2.
    """
    take = session if isinstance(session, dict) else {}
    principal_id = str(take.get("owner_principal_id") or "")
    project_id = str(take.get("project_id") or "")
    take_id = str(take.get("id") or "")
    if (
        not principal_is_allowlisted(principal_id=principal_id)
        or not project_id
        or not take_id
        or str(owner_user_id or "") != str(take.get("user_id") or owner_user_id)
    ):
        _not_applicable(take_id, "not_allowlisted_or_identity_incomplete")
        return None
    # Enrichment, NOT a gate — see `_exercise_context_available`.
    exercise_context = _exercise_context_available(
        database, principal_id=principal_id,
        owner_user_id=str(owner_user_id), take_id=take_id,
    )
    # D20 snapshot-first boundary. Immutable evidence coordinates may only be
    # produced after PostgreSQL identifies the exact current source surface.
    try:
        snapshot_result = database.client.rpc(
            "read_feedback_v3_candidate_source_snapshot_v1",
            {
                "p_acquisition_principal_id": principal_id,
                "p_project_id": project_id,
                "p_take_id": take_id,
            },
        ).execute()
        source_snapshot = getattr(snapshot_result, "data", snapshot_result)
    except Exception as exc:
        return _decline(take_id, "source_snapshot_rpc_failed", str(exc))
    if not isinstance(source_snapshot, dict) or set(source_snapshot) != {
        "snapshot_contract_version", "document_snapshot_id",
        "source_generation", "surface", "surface_sha256",
    }:
        return _decline(take_id, "source_snapshot_shape_unexpected")
    try:
        snapshot_id = str(uuid.UUID(str(source_snapshot.get(
            "document_snapshot_id"
        ))))
    except (TypeError, ValueError, AttributeError):
        return _decline(take_id, "source_snapshot_id_not_a_uuid")
    source_generation = source_snapshot.get("source_generation")
    if (
        source_snapshot.get("snapshot_contract_version")
        != "feedback-v3-candidate-source-snapshot-v1"
        or snapshot_id != source_snapshot.get("document_snapshot_id")
        or not isinstance(source_generation, int)
        or isinstance(source_generation, bool)
        or source_generation < 1
        or source_snapshot.get("surface") != served_text
        or source_snapshot.get("surface_sha256")
        != sha256(served_text.encode("utf-8")).hexdigest()
    ):
        return _decline(take_id, "source_snapshot_does_not_match_served_text")
    frame = build_service_candidate_frame(
        take_document=take_document,
        snippets=snippets,
        suggestions=suggestions,
        feedback_candidates=feedback_candidates,
        take_index=take.get("take_index"),
        expected_recording_id=take.get("recording_1_id"),
    )
    inventory_detail: list[str] = []
    inventory = prepare_v3_service_inventory(
        frame=frame,
        take_document=take_document,
        feedback_candidates=feedback_candidates,
        detail=inventory_detail,
    )
    if inventory is None:
        # Six gates share this one reason. `detail` names which closed — the
        # same fix `_decline` itself is, applied one layer down.
        return _decline(
            take_id, "service_inventory_unavailable", "; ".join(inventory_detail)
        )
    bundle = build_feedback_exposure_bundle(
        session=take,
        transcript_document=take_document,
        served_text=served_text,
        candidates=inventory["candidates"],
        selected_keys=inventory["selected_keys"],
        manager_rules_version="take-feedback-policy-v3-serving-v1",
        document_snapshot_id=str(source_snapshot["document_snapshot_id"]),
        document_surface_sha256=str(source_snapshot["surface_sha256"]),
    )
    if bundle is None or len(bundle.get("candidates") or []) != len(
        inventory["membership_items"]
    ):
        return _decline(take_id, "exposure_bundle_membership_count_mismatch")
    candidate_result = database.record_feedback_v3_service_candidate_set(bundle)
    if (
        not isinstance(candidate_result, dict)
        or str(candidate_result.get("candidate_set_id") or "")
        != str(bundle["candidate_set_id"])
    ):
        return _decline(take_id, "candidate_set_write_failed")
    canonical = _canonical_index(bundle)
    membership_items: list[dict] = []
    for raw in inventory["membership_items"]:
        row = dict(raw)
        item = canonical.get((row["feedback_family"], row["candidate_key"]))
        if item is None:
            return _decline(take_id, "membership_candidate_not_in_bundle")
        row["candidate_id"] = item["id"]
        membership_items.append(row)
    membership = database.freeze_feedback_v3_service_membership({
        "p_acquisition_principal_id": principal_id,
        "p_project_id": project_id,
        "p_take_id": take_id,
        "p_candidate_set_id": bundle["candidate_set_id"],
        "p_document_snapshot_id": str(source_snapshot["document_snapshot_id"]),
        "p_block_partition_version": inventory["block_partition_version"],
        "p_items": membership_items,
        "p_idempotency_key": (
            f"feedback-v3-service-membership:{bundle['candidate_set_id']}:"
            f"{source_snapshot['document_snapshot_id']}"
        ),
    })
    if not isinstance(membership, dict) or not membership.get("id"):
        return _decline(take_id, "membership_freeze_failed")

    visible: list[dict] = []
    for raw in inventory["visible_rows"]:
        row = dict(raw)
        family = str(row.get("feedback_family") or "")
        key = str(row.get("id") or "")
        exact = canonical.get((family, key))
        if exact is None:
            return _decline(take_id, "visible_row_candidate_not_in_bundle")
        row.update({
            "candidate_id": str(exact["id"]),
            "feedback_membership_id": str(membership["id"]),
            "feedback_exposure_id": str(exact["exposure_id"]),
        })
        if family == "confident_voice" and exercise_context:
            context = database.prepare_feedback_v3_service_context({
                "p_membership_id": str(membership["id"]),
                "p_candidate_id": str(exact["id"]),
                "p_acquisition_principal_id": principal_id,
                "p_idempotency_key": (
                    f"feedback-v3-service-context:{membership['id']}:"
                    f"{exact['id']}"
                ),
            })
            if isinstance(context, dict):
                row["mlc3_service"] = {
                    "project_id": project_id,
                    "take_id": take_id,
                    "membership_id": str(membership["id"]),
                    "candidate_id": str(exact["id"]),
                    "feedback_exposure_id": str(exact["exposure_id"]),
                    "content_identity_sha256": str(
                        membership["content_identity_sha256"]
                    ),
                    "n1_candidate_set_id": str(
                        context["n1_candidate_set_id"]
                    ),
                    "authorization_check_id": str(
                        context["authorization_check_id"]
                    ),
                    "source_acquisition_receipt_id": str(
                        context["source_acquisition_receipt_id"]
                    ),
                }
        visible.append(row)
    if not visible:
        # ZERO ROWS IS NOT AN ANSWER, IT IS A STAND-DOWN (founder 2026-09-18:
        # "it was loading long and then showed no bookmarks on the text ZERO").
        #
        # `visible` is built by appending over inventory["visible_rows"]. When
        # that arrives empty the loop appends nothing and this used to return
        # `[]` — which is not None, so the caller in ideal_text_changes took it
        # as a complete V3 result, replaced the working V2 feedback with it and
        # cleared the styles. The user recorded a Take, waited through every
        # RPC this function makes, and got nothing at all: strictly worse than
        # before V3 was activated.
        #
        # Under the V3 policy a Take with any valid block yields at least one
        # Confident Voice item, so an empty inventory means something upstream
        # produced nothing rather than honestly declining. The "honest empty
        # lane shows no card" rule in L2 is about the rewrite and praise lanes
        # inside a populated result — it is not a licence to return an empty
        # result. Declining here preserves the legacy response, which is the
        # contract this function's own docstring states, and names the reason
        # in the log instead of failing silently.
        return _decline(take_id, "inventory_returned_no_visible_rows")
    return visible
