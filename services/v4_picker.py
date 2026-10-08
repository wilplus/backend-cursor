"""The V4 picker, dark beside V3 (V4 Phase 1, B1.6; build plan D-ML-12;
founder P1, P2, P3, V13 A, V14 A, V15 A, V15a A, V16a A, QB6 A, QB7 B, H2,
S-B1b A; migration 0452).

WHAT IT DECIDES, per block of a Take, and serves nothing.

  Allowed first (P1). The sound read of the block (V3's delivery band, the
  same cut the Manager uses) decides what kind a block may carry: praise
  only on a block read confident; a clearer version or an exercise only on
  one read weak. A block with no read carries nothing. V16a A: V4 picks the
  moment and the kind; the exercise picker still picks the video.

  The kind. Read weak: the clearer version when V3 found a defensible one
  in the block (its anchored rewrite), else the exercise when the block
  carries one, else nothing. Read confident: praise when V3 found a
  defensible one, else nothing. Nothing is ever invented (L2, contract 25).

  The moment (QB7 B: only moments that need work). On a block that may
  carry a clearer version or an exercise, the clip with the widest gap
  1 - S*W, read clip by clip (S its own universal-v3 read stretched, W the
  mean of its filler, hedging and slide-fit signals); none on a praise or
  empty block, which is the "None needs it" the coach sheet can answer.

  The rank (P2): importance x (1 - S*W) x sureness, on the block's own
  willfidence read (B1.3).
    importance  the role weight of the block's role from the one call per
                Take (S-B1b A, version 1);
    sureness    evidence strength x (1 - disagreement), sound reads only
                (QB6 A): strength = the share of the block's clips carrying
                a universal-v3 read; disagreement = the share of the clips
                with a live detector verdict whose verdict contradicts the
                block's read (a problem detector fired on a block read
                confident, or none fired on a block read weak).
  Picked: the three highest-ranked blocks that may carry a clearer version
  or an exercise (H2: the walk takes the speaker through at most three).

  Fallback (V15 A, per block). Below ``SURENESS_CUTOFF`` (a placeholder,
  O2 / V14 A: set from dark-run data), or with no role or no read, the
  block takes V3's pick, and the reason is logged with it, never silent.
  V4 still records its own pick on every block (V15a A), so the two can be
  compared; falling back on more than one block in five fails the exit gate.

  Confident Voice stays on the block's best-sounding moment (P3): V4 does not
  touch it. Slide coverage stays a backend target, never a floor on output.

Internal only (AC-9): no rank, weight or read reaches a payload.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

from services import willfidence as wf
from services.v4_take_tags import ROLE_WEIGHTS, ROLES_VERSION

logger = logging.getLogger(__name__)

PICKER_VERSION = "v4-picker-v1"
#: O2, V14 A: placeholder until the dark run shows where V4 starts picking
#: clearly worse than V3.
SURENESS_CUTOFF = 0.3
CUTOFF_VERSION = "sureness-cutoff-v0-placeholder"
#: H2: at most three paragraphs per walk.
PICKS_PER_TAKE = 3
IMPROVE_KINDS = ("rewrite", "exercise")


def _confident(block: dict) -> Optional[bool]:
    from services.take_feedback_policy_v3 import CONFIDENT_BANDS
    band = block.get("delivery_band")
    if band is None:
        return None
    return band in CONFIDENT_BANDS


def _anchored(frame: dict, lane: str) -> dict[str, str]:
    """{block_id: candidate_id} of V3's anchored notes in one verbal lane."""
    lanes = frame.get("verbal_lanes") or {}
    anchors = (lanes.get(lane) or {}).get("anchors") or []
    return {str(a.get("block_id")): str(a.get("candidate_id")) for a in anchors
            if isinstance(a, dict) and a.get("block_id")}


def _span_clip(block: dict, frame: dict, lane: str, candidate_id: str) -> Optional[str]:
    """The clip a verbal candidate's words sit in (its document span inside
    one of the block's pieces)."""
    lanes = frame.get("verbal_lanes") or {}
    row = next((c for c in (lanes.get(lane) or {}).get("candidates") or []
                if str(c.get("candidate_id")) == candidate_id), None)
    span = (row or {}).get("document_span") or {}
    start = span.get("start")
    for piece in block.get("pieces") or []:
        if isinstance(start, int) and piece.get("start", 0) <= start < piece.get("end", 0):
            return str(piece.get("snippet_id"))
    return None


def v3_pick(block: dict, frame: dict) -> tuple[Optional[str], Optional[str]]:
    """V3's kind and clip on a block, by the same reading of its frame."""
    rewrite = _anchored(frame, "rewrite_clarity").get(str(block.get("block_id")))
    if rewrite:
        return "rewrite", _span_clip(block, frame, "rewrite_clarity", rewrite)
    if block.get("carries_exercise"):
        return "exercise", str(block.get("selected_candidate_id") or "").rsplit(":", 1)[-1] or None
    if _anchored(frame, "great_formulation").get(str(block.get("block_id"))):
        return "praise", None
    return None, None


def kind_for(block: dict, frame: dict) -> Optional[str]:
    """P1, then the evidence V3 found: never a kind the read forbids, never
    one with nothing behind it."""
    confident = _confident(block)
    block_id = str(block.get("block_id"))
    if confident is None:
        return None
    if confident:
        return "praise" if block_id in _anchored(frame, "great_formulation") else None
    if block_id in _anchored(frame, "rewrite_clarity"):
        return "rewrite"
    if block.get("carries_exercise"):
        return "exercise"
    return None


def clip_gap(snippet: dict) -> Optional[float]:
    metrics = snippet.get("metrics") if isinstance(snippet.get("metrics"), dict) else {}
    s = wf.sound([metrics])
    text = str(snippet.get("transcript") or "")
    w = wf.partial_w(wf.filler(text), wf.hedging(text), wf.slide_fit([metrics]))
    return None if s is None or w is None else 1.0 - s * w


def moment_for(block: dict, kind: Optional[str], snippets: dict[str, dict]) -> Optional[str]:
    """The clip that most needs work, on a block that may carry it."""
    if kind not in IMPROVE_KINDS:
        return None
    gaps = [(clip_gap(snippets[str(c)]), str(c)) for c in block.get("snippet_ids") or []
            if str(c) in snippets]
    measured = [(g, c) for g, c in gaps if g is not None]
    if not measured:
        return None
    return max(measured, key=lambda pair: (pair[0], pair[1]))[1]


def _detector_verdicts(snippet: dict) -> Optional[bool]:
    """Did any live problem detector fire on this clip (None: none could be
    measured)."""
    from services.confident_voice_practice import acoustic_snapshot
    from services.detector_rollout import ERRORS, LIVE_DETECTOR, REGISTRY
    snapshot = acoustic_snapshot(snippet)
    verdicts = []
    for error_id in ERRORS:
        _, detector = REGISTRY.get(LIVE_DETECTOR.get(error_id, ""), ("off", None))
        if detector is not None:
            fired = detector(error_id, snapshot)
            if fired is not None:
                verdicts.append(bool(fired))
    return any(verdicts) if verdicts else None


def sureness(block: dict, snippets: dict[str, dict]) -> tuple[float, float, float]:
    """(strength, disagreement, sureness) from sound reads only (QB6 A)."""
    clips = [snippets[str(c)] for c in block.get("snippet_ids") or [] if str(c) in snippets]
    total = len(block.get("snippet_ids") or [])
    with_read = sum(1 for c in clips if wf.sound([c.get("metrics")]) is not None)
    strength = with_read / total if total else 0.0
    confident = _confident(block)
    verdicts = [v for v in (_detector_verdicts(c) for c in clips) if v is not None]
    if confident is None or not verdicts:
        disagreement = 0.0
    else:
        contradicting = sum(1 for fired in verdicts if fired == confident)
        disagreement = contradicting / len(verdicts)
    return strength, disagreement, strength * (1.0 - disagreement)


def _numbers(read: dict) -> tuple[Optional[str], Optional[float], Optional[float], Optional[float]]:
    """(role, importance, S*W, gap) from the block's 0448 read."""
    role = read.get("role") if read.get("role") in ROLE_WEIGHTS else None
    importance = ROLE_WEIGHTS[role] if role else None
    s, w = read.get("s"), read.get("w")
    sw = float(s) * float(w) if s is not None and w is not None else None
    return role, importance, sw, (1.0 - sw if sw is not None else None)


def block_row(block: dict, frame: dict, by_clip: dict[str, dict], read: dict) -> dict:
    """V4's pick on one block, V3's beside it, unranked. Pure."""
    role, importance, sw, gap = _numbers(read)
    strength, disagreement, sure = sureness(block, by_clip)
    rank = importance * gap * sure if importance is not None and gap is not None else None
    kind = kind_for(block, frame)
    v3_kind, v3_clip = v3_pick(block, frame)
    reason = ("no_role" if importance is None else "no_read" if gap is None
              else "unsure" if sure < SURENESS_CUTOFF else None)
    return {
        "block_id": str(block.get("block_id") or ""), "role": role, "importance": importance,
        "willfident": sw, "gap": gap, "strength": strength,
        "disagreement": disagreement, "sureness": sure, "rank_score": rank,
        "v4_kind": kind, "v4_snippet_id": moment_for(block, kind, by_clip),
        "v3_kind": v3_kind, "v3_snippet_id": v3_clip,
        "fallback": reason is not None, "fallback_reason": reason,
    }


def rank_rows(rows: list[dict]) -> list[dict]:
    """Rank the improvable blocks, pick the top three, and say which pick is
    used (V3's on a fallback). Pure; returns the same rows."""
    eligible = sorted((r for r in rows if r["v4_kind"] in IMPROVE_KINDS and r["rank_score"] is not None),
                      key=lambda r: (-r["rank_score"], r["block_id"]))
    position = {r["block_id"]: i for i, r in enumerate(eligible, start=1)}
    for row in rows:
        row["rank_position"] = position.get(row["block_id"])
        row["picked"] = row["rank_position"] is not None and row["rank_position"] <= PICKS_PER_TAKE
        row["used_kind"] = row["v3_kind"] if row["fallback"] else row["v4_kind"]
        row["used_snippet_id"] = row["v3_snippet_id"] if row["fallback"] else row["v4_snippet_id"]
    return rows


def pick_take(frame: dict, snippets: Iterable[Any], reads: Iterable[dict]) -> list[dict]:
    """V4's pick on every block of a Take, with V3's beside it. Pure."""
    by_clip = {str(s.get("id")): s for s in snippets or [] if isinstance(s, dict) and s.get("id")}
    by_block = {str(r.get("block_id")): r for r in reads or [] if isinstance(r, dict)}
    return rank_rows([block_row(block, frame, by_clip, by_block.get(str(block.get("block_id") or "")) or {})
                      for block in frame.get("blocks") or []])


def fallback_share(rows: Iterable[dict]) -> Optional[float]:
    """V15a A: the share of blocks that fell back (more than 1 in 5 fails)."""
    rows = list(rows)
    return sum(1 for r in rows if r.get("fallback")) / len(rows) if rows else None


def run(database: Any, take_session_id: str, frame: dict, snippets: list) -> Optional[dict]:
    """Pick one Take dark and store it. Never raises."""
    try:
        reads = database.list_v4_willfidence_reads(take_session_id)
        rows = pick_take(frame, snippets, reads)
        return database.record_v4_picks(take_session_id, rows)
    except Exception as error:  # noqa: BLE001 -- dark measure; the Take stands
        logger.warning("v4 picks not stored take=%s: %s", take_session_id, error)
        return None


__all__ = ["PICKER_VERSION", "ROLES_VERSION", "pick_take", "run", "fallback_share"]
