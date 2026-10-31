"""Is the speaker getting better, and did the fix work? (founder 2026-10-31,
N291 items 1 and 2; N290 item 6.)

Two measures, for the founder only (the admin profile's Takes table,
``services.admin_takes``). Neither ever reaches a speaker (Never 1) or a
coach (Never 2).

ANCHORED WILLFIDENCE (N291 item 2). The willfidence the moments are picked
by reads the voice against the speaker's recent Takes, so as they improve
the reference rises with them and their progress disappears from it. This
one reads the voice against a frozen reference: the speaker's first Takes
(``FIRST_TAKES``, at least ``voice_confidence._BASELINE_MIN_SAMPLES`` usable
clips), the same cues, weights and words as the rolling one. Until those
first Takes exist it is not measured. A reference from all speakers, for
new speakers, comes later.

DID THE FIX WORK (N291 item 1). A fix worked when the same issue does not
come back on the next Take of the same talk, on the same slide. The fixes a
Take gave are read from its stored frame (the blocks the picker marked
``weakest`` or ``between``, N289), and its tempo stretch
(``tempo_stretch.pick``). On the next Take's clips of that slide:

  voice    came back when the slide's best heard clip is still under the floor
  clearer  came back when a clip of the slide still has words that need help
  tempo    came back when the next Take's stretch is on the same slide

"not_measured" when there is no next Take, the slide is not in it, or its
clips cannot be read. Read on demand; nothing is stored.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: How many of the speaker's first Takes make the frozen reference.
FIRST_TAKES = 5

CAME_BACK = "came_back"
GONE = "gone"
NOT_MEASURED = "not_measured"


# ── anchored willfidence ─────────────────────────────────────────────────────

def frozen_reference(first_takes_metrics: list[list[Any]]) -> Optional[dict]:
    """The speaker's frozen voice reference from their first Takes' clip
    metrics (oldest first), or None when there are too few usable clips.
    Pure."""
    from services.voice_confidence import _BASELINE_MIN_SAMPLES, feature_stats
    metrics = [m for take in first_takes_metrics[:FIRST_TAKES] for m in take if isinstance(m, dict)]
    return feature_stats(metrics, min_samples=_BASELINE_MIN_SAMPLES)


def anchored_willfidence(pieces: list[dict], reference: Optional[dict]) -> Optional[float]:
    """The mean S x W of a Take's clips, the voice read against the frozen
    reference; None when there is no reference or no clip can be read.
    Pure."""
    if not reference:
        return None
    from services import willfidence
    from services.voice_confidence import read_for_piece
    values = []
    for piece in pieces:
        metrics = piece.get("metrics") if isinstance(piece.get("metrics"), dict) else None
        read = read_for_piece(metrics, reference) if metrics else None
        s = willfidence.stretch(read.get("score")) if read else None
        if s is None:
            continue
        text = piece.get("transcript")
        w = willfidence.partial_w(willfidence.filler(text), willfidence.hedging(text),
                                  willfidence.slide_fit([metrics]))
        values.append(s * (1.0 if w is None else w))
    return sum(values) / len(values) if values else None


# ── did the fix work ─────────────────────────────────────────────────────────

def _clips_by_slide(frame: Any, snippets: list[dict]) -> dict[Any, list[dict]]:
    by_id = {str(s.get("id")): s for s in snippets if isinstance(s, dict) and s.get("id")}
    out: dict[Any, list[dict]] = {}
    for block in (frame or {}).get("blocks") or []:
        clips = [by_id[str(c)] for c in block.get("snippet_ids") or [] if str(c) in by_id]
        out.setdefault(block.get("slide_index"), []).extend(clips)
    return out


def fixes_of(frame: Any, snippets: list[dict]) -> list[dict]:
    """The fixes a Take gave: ``[{"slide_index", "kind"}]``, kind "voice",
    "clearer" or "tempo", in slide order. Pure."""
    found = []
    for block in (frame or {}).get("blocks") or []:
        if block.get("walk_slot") in ("weakest", "between") and block.get("carries_exercise") \
                and block.get("exercise_kind") in ("voice", "clearer"):
            found.append({"slide_index": block.get("slide_index"), "kind": block["exercise_kind"]})
    stretch = _stretch_slide(frame, snippets)
    if stretch is not None:
        found.append({"slide_index": stretch, "kind": "tempo"})
    return sorted(found, key=lambda f: (f["slide_index"] is None, f["slide_index"] or 0))


def _stretch_slide(frame: Any, snippets: list[dict]) -> Optional[Any]:
    from services import tempo_stretch
    try:
        chosen = tempo_stretch.pick(snippets)
    except Exception:  # noqa: BLE001 -- no stretch read: no tempo fix
        return None
    if not chosen:
        return None
    clip = str(snippets[chosen["index"]].get("id"))
    for slide, clips in _clips_by_slide(frame, snippets).items():
        if any(str(c.get("id")) == clip for c in clips):
            return slide
    return None


def _issue(kind: str, clips: list[dict], frame: Any, snippets: list[dict], slide: Any) -> Optional[bool]:
    """Whether the issue is on the slide's clips; None when unreadable."""
    from services import moment_pick
    from services.voice_confidence import stamped_score
    if kind == "tempo":
        return _stretch_slide(frame, snippets) == slide
    reads = [moment_pick.read(stamped_score(c.get("metrics")), c.get("transcript"), c.get("metrics"))
             for c in clips]
    if kind == "voice":
        heard = [r["s"] for r, c in zip(reads, clips)
                 if r["sound"] and len(str(c.get("transcript") or "").split()) >= moment_pick.MIN_WORDS]
        return max(heard) < moment_pick.FLOOR if heard else None
    if kind == "clearer":
        return any(r["words_help"] for r in reads) if reads else None
    return None


def outcome(fix: dict, next_frame: Any, next_snippets: list[dict]) -> str:
    """Whether one fix's issue came back on the next Take, same slide. Pure."""
    if not isinstance(next_frame, dict):
        return NOT_MEASURED
    clips = _clips_by_slide(next_frame, next_snippets).get(fix.get("slide_index"))
    if not clips:
        return NOT_MEASURED
    found = _issue(fix["kind"], clips, next_frame, next_snippets, fix.get("slide_index"))
    if found is None:
        return NOT_MEASURED
    return CAME_BACK if found else GONE


def fix_outcomes(database: Any, take_id: Any, next_take_id: Optional[Any]) -> list[dict]:
    """The fixes a Take gave and whether each came back on the next Take of
    the talk: ``[{"slide_index", "kind", "outcome"}]``. Never raises."""
    try:
        frame = database.get_v4_dark_frame(str(take_id))
        if not isinstance(frame, dict):
            return []
        fixes = fixes_of(frame, database.get_snippets_by_session(str(take_id)) or [])
        if not fixes:
            return []
        next_frame = database.get_v4_dark_frame(str(next_take_id)) if next_take_id else None
        next_snippets = (database.get_snippets_by_session(str(next_take_id)) or []) if next_take_id else []
        return [{**f, "outcome": outcome(f, next_frame, next_snippets)} for f in fixes]
    except Exception as error:  # noqa: BLE001 -- the Takes table stands without it
        logger.warning("take progress: fixes unread take=%s: %s", take_id, error)
        return []
