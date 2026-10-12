"""The speaker's in-place edit of the Ideal Text (PUT
/explore/arc/<arc_id>/ideal-text/user-edit, founder 2026-07-17).

Moved out of ``routes.v2.explore_ideal_text`` unchanged (founder 2026-10-12).
The route keeps the ownership gate, the cold-open publication after a save
and the 500 boundary. Every save is ONE database-owned text/parts/revision
transaction (``compare_and_set_user_ideal_edit``, D22-D24); nothing here
writes the owner lane or a part directly, and the edit never overwrites the
coach canonical or the legacy notebook copy (L1 — separate lanes).

Two wire shapes:

  * CURRENT — carries the full compare-and-set state
    (``expected_user_text_revision``/``_sha256``, ``idempotency_key`` and a
    ``parts`` lineage of expected and desired rows); every field is checked
    before the write and the RPC's answer is checked after it.
  * LEGACY — the frozen old-client contract ({text, version, parts?}),
    adapted to the same RPC; it 409s VERSION_SUPERSEDED against a newer
    version.
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from services.refusal import Refusal

logger = logging.getLogger(__name__)

_CAS_KEYS = frozenset({
    "expected_user_text_revision", "expected_user_text_sha256",
    "idempotency_key",
})
_BIGINT_MAX = 9223372036854775807
_DIGITS = r"[1-9][0-9]*"
_SHA256 = r"[0-9a-f]{64}"


def _invalid(error: str) -> Refusal:
    return Refusal("INVALID_INPUT", error, 400)


def _error_code(error) -> str:
    """The database's typed code inside an error, or the generic one."""
    match = re.search(
        r"\b(CONFIDENT_MOMENT_[A-Z0-9_]+|FEEDBACK_LANGUAGE_[A-Z0-9_]+|MLC3_[A-Z0-9_]+)\b",
        str(error),
    )
    return match.group(1) if match else "CONFIDENT_MOMENT_DATABASE_FAILURE"


def _refuse_typed(error) -> None:
    """A typed Ideal Text refusal from the database is a 409 with its code;
    anything else propagates."""
    code = _error_code(error)
    if code.startswith("IDEAL_TEXT_"):
        raise Refusal(code, None, 409) from error


def _request_shape(body: Any) -> bool:
    """Whether the body is the CURRENT (CAS) shape; refuses a bad key set."""
    if not isinstance(body, dict):
        raise _invalid("object required")
    keys = set(body)
    is_current = _CAS_KEYS <= keys
    if is_current:
        allowed = {"text", "version", "parts", *_CAS_KEYS, "reapplied"}
        required = {"text", "version", "parts", *_CAS_KEYS}
        if keys - allowed or not required <= keys:
            raise _invalid("request keys invalid")
    elif keys - {"text", "version", "parts", "reapplied"} or keys & _CAS_KEYS:
        raise _invalid("request keys invalid")
    if "reapplied" in body and not isinstance(body["reapplied"], bool):
        raise _invalid("reapplied must be boolean")
    return is_current


def _text_and_version(body: dict) -> tuple[str, int]:
    text = body.get("text")
    if not isinstance(text, str):
        raise _invalid("text is required")
    version = body.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise _invalid("version must be a positive integer")
    text = re.sub(r"<[^>]*>", "", text).strip()   # markers ride through
    if len(text) > 20000:
        raise _invalid("text too long")
    if not text:
        raise Refusal("IDEAL_TEXT_EMPTY_EDIT_REJECTED", None, 400)
    return text, version


# ── the CURRENT shape ───────────────────────────────────────────────────────

def _cas_pair_and_key(body: dict) -> tuple[Any, Any, str]:
    """(expected revision, expected hash, idempotency key)."""
    expected_revision = None
    raw_revision = body.get("expected_user_text_revision")
    expected_hash = body.get("expected_user_text_sha256")
    if raw_revision is not None:
        if not isinstance(raw_revision, str) or not re.fullmatch(_DIGITS, raw_revision):
            raise _invalid("revision must be a bigint string")
        expected_revision = int(raw_revision)
        if expected_revision > _BIGINT_MAX:
            raise _invalid("revision exceeds bigint")
    if (expected_revision is None) is not (expected_hash is None):
        raise _invalid("CAS pair invalid")
    if expected_hash is not None and (
        not isinstance(expected_hash, str)
        or not re.fullmatch(_SHA256, expected_hash)
    ):
        raise _invalid("hash invalid")
    operation_key = body.get("idempotency_key")
    if not isinstance(operation_key, str) or not operation_key.strip() \
            or len(operation_key) > 200:
        raise _invalid("idempotency_key invalid")
    return expected_revision, expected_hash, operation_key


def _valid_part_id(value) -> bool:
    """Is ``value`` a canonical (lowercase, unpadded) UUID string?"""
    try:
        return str(uuid.UUID(value)) == value
    except (TypeError, ValueError, AttributeError):
        return False


def _check_expected_part(position: int, row: Any) -> None:
    if not isinstance(row, dict) or set(row) != {
        "position", "part_id", "text_sha256", "locked",
        "current_part_revision_id",
    } or row.get("position") != position:
        raise _invalid("expected part invalid")
    if not _valid_part_id(row.get("part_id")):
        raise _invalid("part_id invalid")
    if not isinstance(row.get("locked"), bool) \
            or not isinstance(row.get("text_sha256"), str) \
            or not re.fullmatch(_SHA256, row["text_sha256"]):
        raise _invalid("expected part state invalid")
    head = row.get("current_part_revision_id")
    if head is not None and (not isinstance(head, str)
                             or not re.fullmatch(_DIGITS, head)):
        raise _invalid("part revision invalid")


def _check_desired_part(position: int, row: Any) -> None:
    if not isinstance(row, dict) or set(row) != {
        "position", "part_id", "text",
    } or row.get("position") != position or not isinstance(row.get("text"), str):
        raise _invalid("desired part invalid")
    if not _valid_part_id(row.get("part_id")):
        raise _invalid("part_id invalid")


def _check_parts_lineage(lineage: Any) -> None:
    if not isinstance(lineage, dict) or set(lineage) != {
        "expected_parts", "desired_parts",
    }:
        raise _invalid("parts lineage invalid")
    expected_parts = lineage.get("expected_parts")
    desired_parts = lineage.get("desired_parts")
    if not isinstance(expected_parts, list) or not isinstance(desired_parts, list):
        raise _invalid("parts arrays required")
    for position, row in enumerate(expected_parts):
        _check_expected_part(position, row)
    for position, row in enumerate(desired_parts):
        _check_desired_part(position, row)
    if len({row["part_id"] for row in expected_parts}) != len(expected_parts) \
            or len({row["part_id"] for row in desired_parts}) != len(desired_parts):
        raise _invalid("duplicate part")


def _is_bigint_string(value: Any) -> bool:
    return (isinstance(value, str) and re.fullmatch(_DIGITS, value) is not None
            and int(value) <= _BIGINT_MAX)


_RESPONSE_KEYS = frozenset({
    "ideal_text_user_edit_contract_version", "saved", "arc_id",
    "source_document_version", "previous_user_text_revision",
    "result_user_text_revision", "result_user_text_sha256",
    "desired_parts_lineage_sha256", "part_revisions", "dataset_eligible",
})


def _check_envelope_shape(result, arc_id, version) -> None:
    if not isinstance(result, dict):
        raise TypeError("invalid Ideal Text CAS response")
    if set(result) != _RESPONSE_KEYS \
            or result.get("ideal_text_user_edit_contract_version") != "ideal-text-user-edit-cas-v2" \
            or result.get("saved") is not True \
            or result.get("arc_id") != str(arc_id) \
            or result.get("dataset_eligible") is not False:
        raise TypeError("invalid Ideal Text CAS response shape")
    if result.get("source_document_version") != version:
        raise TypeError("invalid Ideal Text CAS source version")


def _check_response_envelope(result, arc_id, version, is_current,
                             expected_revision) -> None:
    """The CAS RPC's top-level response contract. Raises TypeError on any
    violation."""
    _check_envelope_shape(result, arc_id, version)
    if not _is_bigint_string(result.get("result_user_text_revision")):
        raise TypeError("invalid Ideal Text CAS bigint")
    previous = result.get("previous_user_text_revision")
    if previous is not None and not _is_bigint_string(previous):
        raise TypeError("invalid previous Ideal Text CAS bigint")
    expected_wire_revision = (
        None if expected_revision is None else str(expected_revision))
    if is_current and previous != expected_wire_revision:
        raise TypeError("Ideal Text CAS previous revision mismatch")
    for field in ("result_user_text_sha256", "desired_parts_lineage_sha256"):
        if not isinstance(result.get(field), str) \
                or not re.fullmatch(_SHA256, result[field]):
            raise TypeError("invalid Ideal Text CAS hash")


_PART_ACTIONS = frozenset({
    "owner_part_created", "owner_part_text_updated",
    "owner_part_reordered", "owner_part_text_updated_and_reordered",
    "owner_part_removed",
})
_PART_REVISION_KEYS = frozenset({
    "part_id", "revision_id", "action", "previous_position", "result_position",
})


def _is_position(value: Any) -> bool:
    return type(value) is int and value >= 0


def _positions_fit(action: str, previous: Any, result: Any) -> bool:
    if action == "owner_part_created":
        return previous is None and _is_position(result)
    if action == "owner_part_removed":
        return result is None and _is_position(previous)
    return _is_position(previous) and _is_position(result)


def _part_revision_order(row: Any, seen: set) -> tuple:
    """One returned part revision, checked; its sort key."""
    if not isinstance(row, dict) or set(row) != _PART_REVISION_KEYS:
        raise TypeError("invalid part revision shape")
    try:
        part_id = str(uuid.UUID(row.get("part_id")))
    except (TypeError, ValueError, AttributeError) as error:
        raise TypeError("invalid part revision identity") from error
    if part_id != row.get("part_id") or part_id in seen:
        raise TypeError("invalid part revision identity")
    seen.add(part_id)
    if not _is_bigint_string(row.get("revision_id")):
        raise TypeError("invalid part revision bigint")
    action = row.get("action")
    previous, result = row.get("previous_position"), row.get("result_position")
    if action not in _PART_ACTIONS:
        raise TypeError("invalid part revision action")
    if not _positions_fit(action, previous, result):
        raise TypeError("invalid part revision positions")
    return (1 if action == "owner_part_removed" else 0,
            previous if result is None else result,
            uuid.UUID(part_id).bytes)


def _check_part_revisions(part_revisions: Any) -> None:
    """Every returned part revision names a real action against a unique
    part, with positions consistent with that action and a strictly
    increasing removed-last/position/part_id order."""
    if not isinstance(part_revisions, list):
        raise TypeError("invalid part revision inventory")
    seen: set = set()
    prior = None
    for row in part_revisions:
        order = _part_revision_order(row, seen)
        if prior is not None and order <= prior:
            raise TypeError("invalid part revision order")
        prior = order


def _save_current(database, *, arc_id, user_id, body, text, version) -> dict:
    expected_revision, expected_hash, operation_key = _cas_pair_and_key(body)
    lineage = body.get("parts")
    _check_parts_lineage(lineage)
    try:
        result = database.compare_and_set_user_ideal_edit(
            owner_user_id=str(user_id), arc_id=str(arc_id),
            source_document_version=version,
            expected_user_text_revision=expected_revision,
            expected_user_text_sha256=expected_hash,
            desired_user_text=text, desired_parts_lineage=lineage,
            idempotency_key=operation_key,
        )
    except Exception as error:
        _refuse_typed(error)
        raise
    _check_response_envelope(result, arc_id, version, True, expected_revision)
    _check_part_revisions(result.get("part_revisions"))
    if body.get("reapplied") is True:
        logger.info("ideal_edit.reapplied arc=%s version=%s chars=%d",
                    arc_id, version, len(text))
    return result


# ── the LEGACY shape ────────────────────────────────────────────────────────

def _legacy_parts(body: dict, text: str) -> Any:
    if "parts" not in body:
        return None
    from services.ideal_text_parts import InvalidParts, agrees_with_text, validate
    raw_parts = body.get("parts")
    if isinstance(raw_parts, list):
        raw_parts = [
            {**part, "text": re.sub(r"<[^>]*>", "", part["text"])}
            if isinstance(part, dict) and isinstance(part.get("text"), str)
            else part
            for part in raw_parts
        ]
    try:
        parts = validate(raw_parts)
    except InvalidParts as error:
        raise Refusal("INVALID_INPUT", str(error), 400) from error
    if not agrees_with_text(parts, text):
        raise _invalid("parts do not join to text")
    return parts


def _machine_text(row: dict) -> str:
    return ((row.get("auto_text") or "").strip()
            or ((row.get("text") or "").strip()
                if not (row.get("updated_by") or row.get("approved_at"))
                else ""))


def _legacy_result_ok(result: Any, arc_id: str, version: int) -> bool:
    return (isinstance(result, dict) and result.get("saved") is True
            and result.get("ideal_text_user_edit_contract_version")
            == "ideal-text-user-edit-cas-v2"
            and result.get("arc_id") == str(arc_id)
            and result.get("source_document_version") == version
            and result.get("dataset_eligible") is False)


def _record_edit_decisions(database, arc_id, row, machine, text, current) -> None:
    try:
        verified_version = row.get("verified_version")
        verified_text = (row.get("verified_text") or "").strip()
        base = (verified_text if verified_version == current and verified_text
                else machine)
        if base:
            from services.protected_phrases import record_user_edit_decisions
            record_user_edit_decisions(
                database, arc_id, base_text=base, user_text=text, version=current)
    except Exception as error:
        logger.warning("ideal user-edit: ledger failed arc=%s: %s", arc_id, error)


def _save_legacy(database, *, arc_id, user_id, body, text, version) -> dict:
    """Preserve the frozen old-client wire contract through the atomic RPC."""
    legacy_parts = _legacy_parts(body, text)
    row = database.ideal_text.get_coach_arc_ideal_text(arc_id) or {}
    machine = _machine_text(row)
    current = row.get("version") or (1 if machine else None)
    if not isinstance(current, int):
        raise Refusal("NOTHING_TO_EDIT", "No ideal text to edit yet.", 409)
    if version != current:
        raise Refusal("VERSION_SUPERSEDED", None, 409, current_version=current)
    result = database.compare_and_set_user_ideal_edit(
        owner_user_id=str(user_id), arc_id=str(arc_id),
        source_document_version=version, expected_user_text_revision=None,
        expected_user_text_sha256=None, desired_user_text=text,
        desired_parts_lineage=legacy_parts, idempotency_key=None,
    )
    if not _legacy_result_ok(result, arc_id, version):
        raise TypeError("invalid legacy Ideal Text CAS response")
    if body.get("reapplied") is True:
        logger.info("ideal_edit.reapplied arc=%s version=%s chars=%d",
                    arc_id, current, len(text))
    _record_edit_decisions(database, arc_id, row, machine, text, current)
    return {"saved": True, "arc_id": arc_id, "version": current}


def save_user_edit(database, *, arc_id: str, user_id: Any, body: Any) -> dict:
    """Save the speaker's edit; the response body. Raises ``Refusal`` for a
    refused request and ``TypeError`` for an RPC answer that breaks its
    contract (the route's 500)."""
    is_current = _request_shape(body)
    text, version = _text_and_version(body)
    if is_current:
        return _save_current(database, arc_id=arc_id, user_id=user_id,
                             body=body, text=text, version=version)
    try:
        return _save_legacy(database, arc_id=arc_id, user_id=user_id,
                            body=body, text=text, version=version)
    except Refusal:
        raise
    except Exception as error:
        _refuse_typed(error)
        raise
