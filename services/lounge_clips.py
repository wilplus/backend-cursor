"""Fresh links for the speaker's clips in the Lounge (founder lock
2026-10-12, moment and feedback chat): a walk step stores the moment's
signed link, which dies after six hours. On every read the link is
signed again from the moment's own recording, but only for a recording
that belongs to the reader. Best-effort: anything unreadable keeps the
stored link, and the player shows its existing "unavailable".
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


def refresh_walk_clips(messages: list, user_id: str, database: Any,
                       resolve: Callable[[dict], Optional[str]]) -> None:
    """Re-sign `metadata.clip.src` in place on the reader's walk steps."""
    wanted: dict = {}
    for m in messages or []:
        meta = m.get("metadata") if m.get("kind") == "walk_step" else None
        clip = meta.get("clip") if isinstance(meta, dict) else None
        sid = meta.get("take_session_id") if isinstance(meta, dict) else None
        if isinstance(clip, dict) and clip.get("snippet_id") and sid:
            wanted.setdefault(str(sid), []).append(clip)
    for sid, clips in wanted.items():
        try:
            rows = {str(r.get("id")): r
                    for r in database.get_snippets_by_session(sid) or []
                    if str(r.get("user_id") or "") == str(user_id)}
        except Exception:
            logger.warning("lounge clips: snippets unreadable for %s", sid,
                           exc_info=True)
            continue
        for clip in clips:
            row = rows.get(str(clip["snippet_id"]))
            try:
                url = resolve(row) if row else None
            except Exception:
                logger.warning("lounge clips: could not sign %s",
                               clip["snippet_id"], exc_info=True)
                url = None
            if url and row:
                clip["src"] = url
                clip["start_ms"] = row.get("start_offset_ms")
                clip["duration_ms"] = row.get("duration_ms")
