"""Erase one training import for good (founder 2026-10-19).

The coach-scope DELETE only archives an import: a coach tidying a list must
never destroy rated corpus. This is the founder's own erase, for audio we
hold no rights to (YouTube and TED imports): the stored audio, then every
row the import or its review wrote, then the session itself.

What it removes is read from the purge registry's own map
(services/data_purge_registry.DEPENDENCIES): every relation addressed by the
import's take session, its clips, its recording or its own single-take arc.
Imports have no project, principal or recording attempt, so none of the
principal-scoped evidence the account purge keeps is reached.

What stays, on purpose:
  - the corpus processing ledger (corpus_import_registrations, permits,
    operations): the evidence that the import was processed under the
    founder's basis. It holds no audio and its triggers refuse a delete.
  - corpus_speaker_splits: a SHA-256 of the speaker key, shared by every
    import of that speaker, with no session and no name.

Order: the audio first, so a failure part-way never leaves audio with no row
pointing at it; the session last, so a failed run can simply run again.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from services.data_purge_registry import DEPENDENCIES
from services.snippet_tables import LEGACY_SNIPPETS_TABLE, SNIPPETS_TABLE

logger = logging.getLogger(__name__)

IMPORT_SOURCE = "training_import"

#: Append-only tables a plain delete cannot touch. An import never writes
#: them unless its ideal-text stage ran and was served; then it is refused
#: before anything is deleted. The detector reconciliation is evidence the
#: service role may only read (0311): even a delete of no rows is refused.
APPEND_ONLY = frozenset({
    "take_feedback_exposure",
    "take_feedback_self_report",
    "take_feedback_self_report_revision",
    "ideal_text_part_revision",
    "take_feedback_detector_reconciliation",
})

_LOCATORS = ("take", "snippet", "recording", "project")


class EraseRefused(Exception):
    """The import cannot be erased as asked; nothing was deleted."""

    def __init__(self, code: str, status: int = 409):
        super().__init__(code)
        self.code = code
        self.status = status


def _relations() -> list[tuple[int, str, str, str]]:
    """(order, relation, selector column, locator) to delete, deduplicated."""
    seen: set[tuple[str, str]] = set()
    out = []
    for dep in DEPENDENCIES:
        if dep.locator_kind not in _LOCATORS or dep.relation in APPEND_ONLY:
            continue
        key = (dep.relation, dep.selector_column)
        if key in seen:
            continue
        seen.add(key)
        out.append((dep.delete_order, dep.relation, dep.selector_column,
                    dep.locator_kind))
    for table in {SNIPPETS_TABLE, LEGACY_SNIPPETS_TABLE}:
        if (table, "session_id") not in seen:
            seen.add((table, "session_id"))
            out.append((45, table, "session_id", "take"))
    return sorted(out)


def _missing_table(error: Exception) -> bool:
    """A relation or column this environment never migrated: no rows."""
    text = str(error)
    return any(mark in text for mark in (
        "42P01", "42703", "PGRST205", "PGRST204", "does not exist",
        "Could not find the table"))


def _ids(client: Any, table: str, column: str, value: str) -> list[str]:
    # Production renamed charisma_snippets to snippets: the old name is
    # gone there, and a table that is not there holds no rows.
    try:
        rows = (client.table(table).select("id").eq(column, value)
                .execute().data or [])
    except Exception as error:  # noqa: BLE001 - database boundary
        if _missing_table(error):
            return []
        raise
    return [str(r["id"]) for r in rows if r.get("id")]


def _erase_audio(keys: list[str]) -> None:
    from services.coach_video_storage import (
        coach_videos_use_r2, default_media_bucket,
    )
    from services.lab_audio_storage import (
        delete_verified_lab_audio_object, get_exact_storage_object_bytes,
        verify_lab_audio_object_absent,
    )
    provider = "r2" if coach_videos_use_r2() else "supabase"
    bucket = default_media_bucket()
    for key in keys:
        # A run that stopped after the audio went finds it gone: fine.
        if verify_lab_audio_object_absent(key, bucket=bucket,
                                          storage_provider=provider):
            continue
        data = get_exact_storage_object_bytes(key, bucket=bucket,
                                              storage_provider=provider)
        if not delete_verified_lab_audio_object(
                key, bucket=bucket, storage_provider=provider,
                expected_sha256=hashlib.sha256(data).hexdigest()):
            raise RuntimeError("AUDIO_STILL_PRESENT")


def erase_training_import(database: Any, session_id: str) -> dict:
    """Erase one import: its audio, its rows, then its session.

    Raises EraseRefused (nothing deleted) for a missing session, a session
    that is not an import, or an import holding append-only rows. Any other
    failure raises with the import still present, safe to run again.
    """
    client = database.client
    sess = database.v2_get_session_by_id(str(session_id))
    if not sess:
        raise EraseRefused("NOT_FOUND", 404)
    if sess.get("source") != IMPORT_SOURCE:
        raise EraseRefused("NOT_AN_IMPORT")
    sid = str(session_id)

    recordings = (client.table("recordings").select("id,storage_path")
                  .eq("session_v2_id", sid).execute().data or [])
    values: dict[str, list[str]] = {
        "take": [sid],
        "recording": [str(r["id"]) for r in recordings if r.get("id")],
        "snippet": sorted({
            *_ids(client, SNIPPETS_TABLE, "session_id", sid),
            *(_ids(client, LEGACY_SNIPPETS_TABLE, "session_id", sid)
              if LEGACY_SNIPPETS_TABLE != SNIPPETS_TABLE else []),
        }),
        "project": [],
    }
    # The arc is the import's own; never reach rows of an arc anything else
    # shares.
    arc_id = str(sess.get("arc_id") or "")
    if arc_id and _ids(client, "v2_sessions", "arc_id", arc_id) == [sid]:
        values["project"] = [arc_id]

    for relation, column, locator in (
            ("take_feedback_exposure", "take_session_id", "take"),
            ("take_feedback_self_report", "take_session_id", "take"),
            ("take_feedback_detector_reconciliation", "take_session_id",
             "take"),
            ("ideal_text_part_revision", "arc_id", "project")):
        if not values[locator]:
            continue
        try:
            rows = (client.table(relation).select(column)
                    .in_(column, values[locator]).limit(1).execute().data)
        except Exception as error:  # noqa: BLE001 - database boundary
            if _missing_table(error):
                continue
            raise
        if rows:
            raise EraseRefused("IMPORT_HAS_APPEND_ONLY_ROWS")

    # Only keys under this import's own folder: a stray path never reaches
    # someone else's audio.
    prefix = f"willab_lab/{sid}/"
    _erase_audio([str(r["storage_path"]) for r in recordings
                  if str(r.get("storage_path") or "").startswith(prefix)])

    # The session names its recording; let go of it first, so the
    # recording's delete never depends on how that link is constrained.
    client.table("v2_sessions").update(
        {"recording_id": None, "recording_1_id": None}).eq("id", sid).execute()

    deleted: dict[str, int] = {}
    for _order, relation, column, locator in _relations():
        selected = values[locator]
        if not selected:
            continue
        try:
            rows = (client.table(relation).delete().in_(column, selected)
                    .execute().data or [])
        except Exception as error:  # noqa: BLE001 - database boundary
            if _missing_table(error):
                continue
            raise
        if rows:
            deleted[relation] = deleted.get(relation, 0) + len(rows)
    client.table("v2_sessions").delete().eq("id", sid).execute()
    if database.v2_get_session_by_id(sid):
        raise RuntimeError("SESSION_STILL_PRESENT")
    logger.info("training import erased sid=%s rows=%s", sid, deleted)
    return {"erased": True, "session_id": sid, "deleted": deleted}
