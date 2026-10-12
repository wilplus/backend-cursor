"""Persistence boundary for the first-client exercise service.

The service deliberately keeps SQL authority in reviewed RPCs. This repository
contains only transport normalization and narrowly-scoped read composition,
keeping the shared DatabaseService from becoming workflow glue.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

def _error_head(error: Any) -> str:
    """``code/message`` from a database error, for the FRONT of the line.

    THIRD CORRECTION TO ONE LOG LINE, and the last layer of the same onion
    (2026-09-20). #566 put the shape ahead of the take id; #572 put the
    error ahead of the shape. Both were right and neither was enough,
    because the error's OWN rendering buries the answer: PostgREST hands
    back ``{'code': ..., 'details': ..., 'hint': ..., 'message': ...}`` and
    ``message`` -- the only field naming which guard fired -- sorts last.

    On a phone that reads as ``error={'code': 'P000...`` and stops. P0001
    is merely "a plpgsql RAISE fired"; there are eight distinct ones in
    ``record_feedback_v3_service_candidate_set_v1`` alone, and the whole
    point of naming a condition is to say WHICH.

    So the two fields that answer the question are lifted to the front and
    the full error still follows. Identifiers and constants: these messages
    are literals like ``FEEDBACK_V3_SERVICE_SOURCE_NOT_LIVE``. No new
    exposure either way -- the complete error was already being logged.
    """
    fields: dict[str, Any] = {}
    args = getattr(error, "args", None)
    if isinstance(args, tuple) and args and isinstance(args[0], dict):
        fields = args[0]
    code = fields.get("code") or getattr(error, "code", None)
    message = fields.get("message") or getattr(error, "message", None)
    if not code and not message:
        # Not a structured database error -- the type is the most useful
        # thing available, and the full error follows on the same line.
        return type(error).__name__
    return f"{code or '?'}/{message or '?'}"


def _payload_shape(value: Any) -> str:
    """One level of a payload's SHAPE, and never a byte of its content.

    WHY SHAPE AND NOT THE PAYLOAD (2026-09-19). The candidate-set write began
    answering 22P02 `invalid input syntax for type json`, detail
    `Token "feedback" is invalid` -- which is the JSON lexer reading a bare
    word and stopping at a `-`, and the only `feedback-` strings in this call
    are the bundle's own `idempotency_key` (`feedback-exposure:...`) and one
    SQL literal. So some text is being read as JSON, and the fastest way to
    find which field is to see which of them is a string that should not be.

    The bundle carries the speaker's transcript. Logging it to diagnose a type
    error would trade a day of debugging for a permanent copy of someone's
    words in a log aggregator, so this renders KINDS and LENGTHS only:
    `o`bject, `a`rray, `s`tring, `b`ool, `n`ull, each with its size. A field
    that is `s` where the SQL expects an object is the answer, and no content
    is needed to see it.
    """
    if not isinstance(value, dict):
        return f"<{type(value).__name__}>"
    def kind(item: Any) -> str:
        if isinstance(item, bool):
            return "b"
        if item is None:
            return "n"
        if isinstance(item, dict):
            return f"o{len(item)}"
        if isinstance(item, list):
            return f"a{len(item)}"
        if isinstance(item, str):
            return f"s{len(item)}"
        return type(item).__name__
    return " ".join(f"{key}={kind(item)}"
                    for key, item in sorted(value.items()))


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
        missing = [key for key in required if not bundle.get(key)]
        if missing:
            # NOT SILENT (2026-09-19). This returned None with no log, and the
            # caller reports `candidate_set_write_failed` for it -- identical
            # to an RPC error from the outside. Key NAMES only: which field is
            # empty is the diagnosis, and its value is the speaker's.
            logger.warning(
                "Feedback V3 service candidate set incomplete missing=%s "
                "take=%s", ",".join(missing), bundle.get("take_id"),
            )
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
                data = data[0] if data and isinstance(data[0], dict) else None
            if not isinstance(data, dict):
                # THE WRITE THAT SUCCEEDED AND SAID NOTHING (2026-09-19).
                # This returned None with no log, and the caller turns that
                # into `candidate_set_write_failed` -- indistinguishable,
                # from the outside, from the RPC raising. So a Take could
                # stand down having reached PostgreSQL, run the whole
                # function, come back clean, and leave no trace of what came
                # back. Fourth shape of the same defect in one day; same
                # answer. Kind only, never content.
                logger.warning(
                    "Feedback V3 service candidate set returned no usable "
                    "row kind=%s take=%s",
                    type(result.data).__name__, bundle.get("take_id"),
                )
                return None
            returned = str(data.get("candidate_set_id") or "").strip().lower()
            sent = str(bundle.get("candidate_set_id") or "").strip().lower()
            if sent and returned != sent:
                # The caller refuses on exactly this and could not say why.
                # Both ids are ours -- `_stable_uuid` output and a UUID
                # column -- so neither is content.
                logger.warning(
                    "Feedback V3 service candidate set id mismatch "
                    "returned=%s sent=%s take=%s",
                    returned or "∅", sent, bundle.get("take_id"),
                )
            return data
        except Exception as error:
            # ERROR FIRST. THE SHAPE WAS THE RIGHT ANSWER TO THE WRONG
            # QUESTION (2026-09-19, second correction to this one line).
            #
            # #566 moved the shape ahead of the take id, because a
            # 36-character id in front of the answer clips the line before
            # anyone reads it. That reasoning was sound and the fix was too
            # literal: the shape it promoted is ~220 characters, so it now
            # clips the very field it was added to help diagnose. A phone
            # log list shows roughly the first sixty characters, and on
            # 2026-09-20 a stand-down was read as "no exception at all"
            # because the `error=` never came into view -- a wrong
            # conclusion drawn from a truncated line, which is exactly the
            # failure this ordering exists to prevent.
            #
            # So: the ERROR leads, because it is the answer; the shape
            # follows, because it is the supporting detail for when the
            # error is a type complaint; the take id stays last. Shapes
            # only, never content -- see `_payload_shape`.
            logger.warning(
                "Feedback V3 service candidate set failed %s "
                "shape=[%s] transcript=[%s] raw=%s take=%s",
                _error_head(error),
                _payload_shape(bundle),
                _payload_shape(bundle.get("transcript")),
                error,
                bundle.get("take_id"),
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

    def record_take_feedback_coverage(self, row: dict) -> Optional[bool]:
        """One row per served Take (0437, D-ML-5; contract 24c/24d/25).

        True when this serve wrote the Take's first row, False when the Take
        already had one (its counts are refreshed and `last_served_at`
        moves), None when the write failed. Best-effort: never raises, so a
        database fault can never block serving (LIVE LOOP). Internal only,
        never read by a route (AC-9)."""
        take_id = str(row.get("take_session_id") or "")
        if not take_id:
            return None
        try:
            inserted = (self.client.table("take_feedback_coverage")
                        .upsert(row, on_conflict="take_session_id",
                                ignore_duplicates=True)
                        .execute().data or [])
            if inserted:
                return True
            refresh = {key: value for key, value in row.items()
                       if key not in ("take_session_id", "first_served_at")}
            refresh["last_served_at"] = datetime.now(timezone.utc).isoformat()
            (self.client.table("take_feedback_coverage")
             .update(refresh).eq("take_session_id", take_id).execute())
            return False
        except Exception as error:  # noqa: BLE001 -- best-effort, logged
            logger.warning("take coverage write failed take=%s: %s",
                           take_id, _error_head(error))
            return None

    def list_take_feedback_coverage(self, limit: int = 50000) -> list[dict]:
        """Every served Take's floor, for the founder's V4 exit gate (BEXIT)
        only; never a route's read (AC-9). [] on failure."""
        try:
            return list(self.client.table("take_feedback_coverage")
                        .select("take_session_id,floor_met").limit(limit)
                        .execute().data or [])
        except Exception as error:  # noqa: BLE001 -- a report, logged
            logger.warning("take coverage read failed: %s", _error_head(error))
            return []

    def freeze_exercise_service_offer_v2(self, payload: dict) -> Optional[dict]:
        try:
            result = self.client.rpc(
                "freeze_exercise_service_offer_v2", payload,
            ).execute()
            return self._rpc_row(result.data)
        except Exception as error:
            logger.warning("Exercise service offer freeze failed: %s", error)
            return None
