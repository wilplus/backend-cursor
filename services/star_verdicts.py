"""Coach star verdicts (founder 2026-07-27) — the DECISION-layer correction
corpus for the voice-text analytics.

WHY THIS EXISTS. The coach can already correct what a star SAYS: the
(ai_draft, coach_final) pairs on comments and say-it-stronger cards ride
admin_annotation_events into the DPO/fine-tune exports. Nothing could correct
whether a star should have FIRED. A preference pair over two strings teaches a
generator to write better copy; it can never teach a detector to stay quiet.

So: one coach judgment per fired star.

    keep              the trigger was right (the endorsement signal — mirrors
                      'approved_as_is' on the prose side)
    wrong_kind        a star belonged here, but not this one; ``corrected_device``
                      carries what it should have been (a labeled confusion pair)
    should_not_fire   the trigger was wrong; this moment deserved silence

FENCES.
  * BLIND COACH — THE live fence for this module. This surface deliberately
    shows the coach the machine's guess and asks them to judge it. That is safe
    here (a star is not a confidence label) and unsafe anywhere near the
    labeling lane, so: a separate endpoint from the blind labeling surface, and
    this corpus is NEVER joined into training_labels. The module is banned from
    importing training_labels / learning_serve / challenge_threat at all
    (pinned by test), so a future edit cannot quietly cross the wall.
  * AC-9 — a verdict is coach->machine only. Nothing here is ever surfaced back
    to the student.
  * L1 — a verdict never mutates text. It judges a star; the student's copy is
    untouched.

KNOWN GAP, DELIBERATE: false NEGATIVES are not captured. A star that should
have fired and didn't leaves no row, because there is no object to judge. That
needs its own surface and was scoped out. ``corpus_summary`` reports this in
every pull so a training run cannot mistake this for a balanced sample.

Pure — validation, vocabulary, and corpus shaping only. No DB, no LLM.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

VERDICTS = ("keep", "wrong_kind", "should_not_fire")

# The star families, mirroring moment_suggestions.kind (the CHECK in
# alter_moment_suggestions_kind_delivery.sql). A verdict on a kind this table
# doesn't know is rejected rather than stored — an unknown kind means the star
# vocabulary moved and this module wasn't updated.
STAR_KINDS = ("emphasize", "replace", "structure", "delivery")

_MAX_NOTE_LEN = 1000


def _devices_for_kind(kind: str) -> tuple:
    """The device vocabulary a given star family may carry.

    Imported from the modules that OWN each vocabulary rather than re-declared,
    so adding a delivery device in one place can't leave this validator
    silently rejecting it. Falls back to an empty tuple (device-free family) if
    an import fails — validation then only accepts device=None, which is the
    safe direction."""
    try:
        if kind == "delivery":
            from services.delivery_stars import DELIVERY_DEVICES
            return tuple(DELIVERY_DEVICES)
        if kind == "structure":
            from services.moment_suggestions import _STRUCT_DEVICES
            return tuple(_STRUCT_DEVICES)
    except Exception as e:
        logger.warning("star_verdicts: device vocabulary import failed "
                       "kind=%s: %s", kind, e)
        return ()
    # emphasize / replace are single-device families — the kind IS the device.
    return ()


def valid_devices(kind: Any) -> tuple:
    """Public accessor for the device vocabulary of a star family (the coach UI
    renders the 'wrong kind -> which one?' choices from this)."""
    k = (kind or "").strip() if isinstance(kind, str) else ""
    if k not in STAR_KINDS:
        return ()
    return _devices_for_kind(k)


def _clean_str(v: Any, limit: int = 200) -> Optional[str]:
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s:
        return None
    return s[:limit]


def validate_verdict(payload: Any) -> tuple[Optional[dict], Optional[str]]:
    """Validate one coach verdict → ``(row, None)`` or ``(None, error)``.

    ``row`` is the storable shape (no id, no timestamps — the DB owns those).
    Pure and total: every rejection carries a message the route can hand back
    verbatim, so a malformed judgment fails loudly at the boundary instead of
    landing in the corpus as junk."""
    if not isinstance(payload, dict):
        return None, "body: must be an object"

    verdict = _clean_str(payload.get("verdict"), 40)
    if verdict not in VERDICTS:
        return None, f"verdict: must be one of {', '.join(VERDICTS)}"

    kind = _clean_str(payload.get("star_kind"), 40)
    if kind not in STAR_KINDS:
        return None, f"star_kind: must be one of {', '.join(STAR_KINDS)}"

    allowed = _devices_for_kind(kind)
    device = _clean_str(payload.get("star_device"), 40)
    if device is not None and allowed and device not in allowed:
        return None, (f"star_device: must be one of {', '.join(allowed)} "
                      f"for star_kind={kind}")
    if device is not None and not allowed:
        # A single-device family carrying a device string means the caller is
        # confused about the vocabulary; reject rather than store a value no
        # reader will understand.
        return None, f"star_device: star_kind={kind} carries no device"

    corrected = _clean_str(payload.get("corrected_device"), 40)
    if verdict == "wrong_kind":
        if corrected is None:
            return None, ("corrected_device: required when "
                          "verdict=wrong_kind (the correction IS the signal)")
        # The correction may name another FAMILY (delivery -> structure) or
        # another device within one, so it validates against the union.
        if corrected not in _all_devices() and corrected not in STAR_KINDS:
            return None, ("corrected_device: must be a known star device or "
                          "star kind")
        if corrected == device:
            return None, ("corrected_device: must differ from star_device "
                          "(that is a 'keep', not a 'wrong_kind')")
    elif corrected is not None:
        return None, ("corrected_device: only valid when "
                      "verdict=wrong_kind")

    row: dict = {
        "star_kind": kind,
        "star_device": device,
        "verdict": verdict,
        "corrected_device": corrected,
        "note": _clean_str(payload.get("note"), _MAX_NOTE_LEN),
        "star_version": _clean_str(payload.get("star_version"), 80),
    }
    return row, None


def _all_devices() -> tuple:
    out: list = []
    for k in STAR_KINDS:
        out.extend(_devices_for_kind(k))
    return tuple(out)


def stars_with_verdicts(suggestions: Any, verdicts: Any) -> list:
    """The coach review list: every fired star for a session, each carrying the
    coach's existing judgment (or None).

    ``suggestions`` = moment_suggestions rows; ``verdicts`` = {snippet_id: row}.
    Pure. AC-9 note: this is a COACH payload, so it may carry the machine's
    guess (that is the point) — but it deliberately does NOT carry
    acoustic_read, direction, or any shadow prediction, because those belong to
    the confidence-labeling lane and must not travel with an analytics review
    (BLIND COACH). Anything added here must be checked against that."""
    by_snippet = verdicts if isinstance(verdicts, dict) else {}
    out: list = []
    for s in (suggestions or []):
        if not isinstance(s, dict):
            continue
        sid = str(s.get("snippet_id") or "")
        if not sid:
            continue
        kind = s.get("kind")
        # Delivery stars carry their device in `trigger`; the other families
        # are single-device, so the kind is the whole story.
        device = s.get("trigger") if kind == "delivery" else None
        existing = by_snippet.get(sid)
        out.append({
            "snippet_id": sid,
            "star_kind": kind,
            "star_device": device,
            "why": s.get("why"),
            "replacement_text": s.get("replacement_text"),
            "trigger": s.get("trigger"),
            "verdict": (existing or {}).get("verdict"),
            "corrected_device": (existing or {}).get("corrected_device"),
            "note": (existing or {}).get("note"),
            "judged": bool(existing),
            # What the coach may pick when they answer "wrong kind".
            "device_options": list(valid_devices(kind)),
        })
    return out


def corpus_summary(verdict_rows: Any) -> dict:
    """Class balance for a corpus pull — so a training run can see whether the
    data is usable before it trains on it.

    Always reports ``false_negatives_captured: False``: this corpus records
    only judgments on stars that FIRED, so it is precision data, not a balanced
    sample of the detector's behaviour. A caller that treats it as the latter
    will overfit toward silence."""
    rows = [r for r in (verdict_rows or []) if isinstance(r, dict)]
    by_verdict: dict = {v: 0 for v in VERDICTS}
    by_kind: dict = {}
    confusions: dict = {}
    for r in rows:
        v = r.get("verdict")
        if v in by_verdict:
            by_verdict[v] += 1
        k = r.get("star_kind")
        if k:
            by_kind[k] = by_kind.get(k, 0) + 1
        if v == "wrong_kind":
            pair = f"{r.get('star_device') or r.get('star_kind')}" \
                   f"->{r.get('corrected_device')}"
            confusions[pair] = confusions.get(pair, 0) + 1
    return {
        "total": len(rows),
        "by_verdict": by_verdict,
        "by_kind": by_kind,
        "confusions": confusions,
        "false_negatives_captured": False,
    }
