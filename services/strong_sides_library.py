"""willab beta — strong-sides library ingest (design §7, contract §3.11).

On the user's READ of a published session's insights, the coach-tagged
snippets are ingested into strong_sides_library: the coach's note + tag
+ a reference to the snippet's raw data. The Lounge bot later retrieves
+ replays these.

Ingest-on-READ (not at publish, §3.11): the trigger is the user opening
their insights, so the library reflects what they've actually seen.
Idempotent (UNIQUE(user_id, snippet_id)) — re-reading never duplicates.

LIBRARIAN, NOT JUDGE (§7): this only stores + replays human-authored
coach notes. No trajectory/improvement computation anywhere near it.

build_library_rows is pure (join insights_payload notes ↔ snippet raw
data) and unit-tested; ingest_session_library does the DB I/O.
"""
from __future__ import annotations

from typing import Optional


def build_library_rows(
    *,
    user_id: str,
    session_id: str,
    insights_payload: Optional[dict],
    snippets: list,
) -> list[dict]:
    """Join the insights_payload coach notes onto the session's snippet
    raw data → the rows to upsert into strong_sides_library. Pure.

    Only tagged notes whose snippet is found are ingested (a note for a
    missing snippet is skipped — defensive against drift). Each row:
      {user_id, session_id, snippet_id, note, tag, snippet_ref}
    where snippet_ref = {transcript, features, audio_ref,
    start_offset_ms, duration_ms} (the replay material for the bot).
    """
    if not isinstance(insights_payload, dict):
        return []
    notes = insights_payload.get("snippet_notes") or []
    if not isinstance(notes, list) or not notes:
        return []

    # Index snippets by id for the join.
    from services.lab_recording import build_readout_features
    by_id: dict = {}
    for s in (snippets or []):
        sid = s.get("id")
        if sid is not None:
            by_id[str(sid)] = s

    rows: list[dict] = []
    for n in notes:
        if not isinstance(n, dict):
            continue
        sid = n.get("snippet_id")
        note = (n.get("note") or "").strip()
        tag = n.get("tag")
        if not sid or not note or tag not in ("strong", "to_work_on"):
            continue
        snip = by_id.get(str(sid))
        if not snip:
            continue
        rows.append({
            "user_id": user_id,
            "session_id": session_id,
            "snippet_id": str(sid),
            "note": note,
            "tag": tag,
            "snippet_ref": {
                "transcript": (
                    snip.get("transcript")
                    or snip.get("transcription_text")
                    or ""
                ),
                "features": build_readout_features(snip.get("metrics")),
                "audio_ref": snip.get("audio_segment_path"),
                "start_offset_ms": snip.get("start_offset_ms"),
                "duration_ms": snip.get("duration_ms"),
            },
        })
    return rows


def ingest_session_library(session_id: str, user_id: str) -> int:
    """Ingest a published session's coach-tagged snippets into the
    library. Idempotent + best-effort: returns the number of rows
    upserted, or 0 on any miss (no insights_payload, no owner, DB
    issue). Safe to call on every read — never raises.
    """
    if not session_id or not user_id:
        return 0
    from services.db import db

    try:
        session = db.v2_get_session_by_id(session_id) or {}
    except Exception:
        return 0
    insights = session.get("insights_payload")
    if not isinstance(insights, dict):
        return 0

    try:
        snippets = db.get_snippets_by_session(session_id) or []
    except Exception:
        snippets = []

    rows = build_library_rows(
        user_id=user_id,
        session_id=session_id,
        insights_payload=insights,
        snippets=snippets,
    )
    if not rows:
        return 0
    try:
        return db.upsert_strong_sides_library(rows)
    except Exception:
        return 0
