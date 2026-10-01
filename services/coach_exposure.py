"""Coach blindness under the new flow (founder 2026-10-01, task 4), dark
behind the switches of the lanes that write it.

Three rules. (1) The request kind stays behind the blind gate: a coach reads
it only after their own rating (coach_moments_queue, coach_moment_read).
(2) The FIRST EXPOSURE of a coach to a clip is recorded, once per coach per
clip (table coach_clip_exposures, migration 0411): the moment read after a
rating, a request answered, an audit item, a block pick. A rating this coach
gives on that clip LATER is not blind (``blind = false``) and does not count
toward the quorum, the Voice Album's coach leg, or the delayed measure.
(3) A clip is never queued to a coach already exposed to it: the audit, the
block pick and the delayed measure ask ``unexposed`` first.

Nothing here reaches a speaker; nothing here is a label.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

_log = logging.getLogger(__name__)

CLIP_KINDS = ("snippet", "practice_attempt")
VIA = ("moment_read", "request", "audit", "block_pick", "walk")


def record_exposure(database: Any, *, coach_id: str, clip_id: str,
                    clip_kind: str = "snippet", via: str = "moment_read") -> bool:
    """The coach saw this clip's non-blind side now; once per coach per clip.
    True when this call recorded the first exposure. Never raises."""
    if clip_kind not in CLIP_KINDS or via not in VIA or not coach_id or not clip_id:
        return False
    writer = getattr(database, "record_coach_clip_exposure", None)
    if writer is None:
        return False
    try:
        return bool(writer(coach_id=str(coach_id), clip_id=str(clip_id),
                           clip_kind=clip_kind, via=via))
    except Exception as e:  # noqa: BLE001 — the read it rides on still serves
        _log.warning("coach exposure not recorded coach=%s clip=%s: %s",
                     coach_id, clip_id, e, exc_info=True)
        return False


def exposed_clip_ids(database: Any, coach_id: str, clip_ids: Iterable[str]) -> set[str]:
    """Which of these clips this coach has already been exposed to."""
    ids = [str(c) for c in clip_ids if c]
    reader = getattr(database, "list_coach_clip_exposures", None)
    if not ids or reader is None:
        return set()
    try:
        rows = reader(str(coach_id), ids) or []
    except Exception as e:  # noqa: BLE001 — unknown reads as exposed: the safe side
        _log.warning("coach exposure read failed coach=%s: %s", coach_id, e, exc_info=True)
        return set(ids)
    return {str(r.get("clip_id")) for r in rows if isinstance(r, dict) and r.get("clip_id")}


def is_exposed(database: Any, coach_id: str, clip_id: str) -> bool:
    return str(clip_id) in exposed_clip_ids(database, coach_id, [clip_id])


def unexposed(database: Any, coach_id: str, candidates: Iterable[dict],
              key: str = "clip_id") -> list[dict]:
    """The candidates this coach may still be shown blind."""
    rows = [c for c in candidates if isinstance(c, dict) and c.get(key)]
    seen = exposed_clip_ids(database, coach_id, [str(c[key]) for c in rows])
    return [c for c in rows if str(c[key]) not in seen]


def rating_is_blind(database: Any, *, coach_id: str, snippet_id: str) -> bool:
    """Whether a rating this coach gives NOW on this clip is blind: not if
    the clip's non-blind side was shown to them before."""
    return not is_exposed(database, coach_id, snippet_id)
