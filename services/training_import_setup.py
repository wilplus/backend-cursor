"""Finish (or correct) a training import's set-up without re-importing it.

An import's set-up is COMPLETE when its intake_context has a non-empty
(after strip) string topic AND a non-empty string language. Speaker label
and source are optional. No migration: everything lives in intake_context.

The save writes those keys onto the existing row and, when the speaker key
changes, records that speaker's learn/test split once. It never re-imports,
re-analyses, or touches labels. An unfinished import serves no moments.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_LANGUAGE_RE = re.compile(r"^[a-z]{2}$")
_TOPIC_MAX = 200
_SPEAKER_MAX = 120
_SOURCE_MAX = 500


def setup_complete(ctx: Any) -> bool:
    """True when topic and language are both non-empty after strip.

    A non-dict (a missing context, a list, anything else) is not complete:
    the queue and the clip playback then serve nothing.
    """
    if not isinstance(ctx, dict):
        return False
    topic = ctx.get("topic")
    language = ctx.get("language")
    if not isinstance(topic, str) or not topic.strip():
        return False
    if not isinstance(language, str) or not language.strip():
        return False
    return True


def _optional_str(value: Any, max_len: int) -> tuple[str | None, str | None]:
    """Optional text: None and blank stay unset; a non-str or an over-long
    value is INVALID_INPUT. Returns (stored, error_code)."""
    if value is None:
        return None, None
    if not isinstance(value, str):
        return None, "INVALID_INPUT"
    stripped = value.strip()
    if not stripped:
        return None, None
    if len(stripped) > max_len:
        return None, "INVALID_INPUT"
    return stripped, None


def parse_setup(body: Any) -> tuple[dict | None, str | None]:
    """From {topic, language, speaker_label?, source?} return (fields, None)
    or (None, error_code). source is stored under source_note."""
    if not isinstance(body, dict):
        return None, "INVALID_INPUT"
    topic = body.get("topic")
    if (not isinstance(topic, str) or not topic.strip()
            or len(topic.strip()) > _TOPIC_MAX):
        return None, "TOPIC_REQUIRED"
    language = body.get("language")
    if not isinstance(language, str):
        return None, "LANGUAGE_REQUIRED"
    language = language.strip().lower()
    if not _LANGUAGE_RE.match(language):
        return None, "LANGUAGE_REQUIRED"
    speaker_label, speaker_err = _optional_str(
        body.get("speaker_label"), _SPEAKER_MAX)
    if speaker_err:
        return None, speaker_err
    source_note, source_err = _optional_str(body.get("source"), _SOURCE_MAX)
    if source_err:
        return None, source_err
    return {
        "topic": topic.strip(),
        "language": language,
        "speaker_label": speaker_label,
        "source_note": source_note,
    }, None


def _with_setup(ctx: dict, fields: dict) -> dict:
    """Copy of ctx with the four set-up keys applied. None deletes the key
    so a cleared speaker or source does not linger as an empty string."""
    updated = dict(ctx)
    updated["topic"] = fields["topic"]
    updated["language"] = fields["language"]
    if fields["speaker_label"] is None:
        updated.pop("speaker_label", None)
    else:
        updated["speaker_label"] = fields["speaker_label"]
    if fields["source_note"] is None:
        updated.pop("source_note", None)
    else:
        updated["source_note"] = fields["source_note"]
    return updated


def apply_setup(database: Any, session_id: str, body: Any) -> tuple[int, dict]:
    """Save an import's set-up onto the existing row.

    400 from parse_setup, 404 when the session is missing, 409 when it is
    not a training import, 500 when the write fails. A speaker-split failure
    is logged and does not fail the save: the set-up is already written.
    """
    fields, error = parse_setup(body)
    if error or fields is None:
        return 400, {"code": error or "INVALID_INPUT"}
    session = database.v2_get_session_by_id(session_id)
    if not session:
        return 404, {"code": "NOT_FOUND"}
    if session.get("source") != "training_import":
        return 409, {"code": "NOT_AN_IMPORT"}
    existing = session.get("intake_context")
    ctx = existing if isinstance(existing, dict) else {}
    old_label = ctx.get("speaker_label")
    updated = _with_setup(ctx, fields)
    if not database.takes.set_session_intake_context(session_id, updated):
        return 500, {"code": "SERVER_ERROR"}
    _assign_split_if_speaker_changed(
        database, session_id, old_label, fields["speaker_label"])
    return 200, {
        "session_id": session_id,
        "topic": fields["topic"],
        "language": fields["language"],
        "speaker_label": fields["speaker_label"],
        "source": fields["source_note"],
        "setup_complete": True,
    }


def _assign_split_if_speaker_changed(database: Any, session_id: str,
                                    old_label: Any, new_label: Any) -> None:
    """The first assignment of a speaker wins. Only a changed key is sent,
    and a failure here must not undo the set-up just saved."""
    try:
        from services.corpus_split import assign_speaker_split, speaker_key_for
        new_key = speaker_key_for(new_label, session_id)
        if speaker_key_for(old_label, session_id) == new_key:
            return
        assign_speaker_split(database, new_key)
    except Exception:
        logger.warning(
            "speaker split assign failed sid=%s", session_id, exc_info=True)
