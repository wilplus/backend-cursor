"""Blinded A/B slide pairs — the same slide, two takes, no labels.

WHY THIS EXISTS (founder 2026-08-11, after the piece-(b) audit). Two things
block best-text-per-slide ranking, and neither is code:

  * the DELIVERY term of power_score is ranking-inert
    (VOICE_CONFIDENCE_RANKING_ENABLED, default OFF) until the composite is
    anchored against blinded human ratings;
  * LINE-LEVEL cross-take selection is hard-disabled
    (cross_take_selection._LINE_LEVEL_ENABLED) until a fuzzy-alignment spike
    can run on real multi-take arcs.

One act produces both. A coach comparing take A's slide 3 against take B's
slide 3 gives (i) a human preference to correlate the composite against and
(ii) a matched cross-take pair, which is exactly the alignment ground truth
the spike needs. Same speaker, same slide, same deck — a comparability no
external corpus can offer, because nobody publishes their outtakes.

BLINDING IS THE WHOLE INSTRUMENT, so it is enforced HERE rather than in the
UI:

  * a served side carries ONLY words + audio + timing. No session id, no
    take index, no timestamp — nothing from which "this is the later take"
    can be inferred. A rater who knows which take is which is rating a
    story about improvement, not a delivery.
  * which take shows LEFT is decided by a hash of the pair, not by take
    order. Stable, so re-opening a pair never flips it under the coach's
    hand; varied across pairs, so position bias cannot ride along with
    recency. The stored verdict records the true sides, so that bias is
    measurable after the fact rather than merely hoped away.

Pure. No database, no network — the caller passes takes in, pairs come out.
"""
from __future__ import annotations

import base64
import hashlib
from typing import Any, NamedTuple, Optional

# A slide version with fewer real words than this is not a delivery anyone
# can judge — an empty slide, or a speaker who skipped past it. Comparing it
# would collect a verdict about silence.
_MIN_WORDS = 4


class _Take(NamedTuple):
    """One take, reduced to what a comparison needs.

    Named fields rather than a plain dict, and not for tidiness: a dict
    literal's inferred value type is the JOIN of everything in it, so a str,
    an Any and a dict in the same literal make EVERY read
    `str | dict | Any | None`. Under that type `pair_id(si, a["session_id"],
    …)` and `min(a["session_id"], …)` below stop being checked at all —
    which is precisely where a session id could go missing unnoticed. This
    keeps them checked.
    """

    session_id: str
    audio_ref: Any
    by_index: dict


def _words(text: Any) -> int:
    return len((text or "").split()) if isinstance(text, str) else 0


def _by_index(slide_transcripts: Any) -> dict:
    """{slide_index: row} from a take's persisted per-slide 1:1 transcript."""
    out: dict = {}
    for t in (slide_transcripts or []):
        if isinstance(t, dict) and isinstance(t.get("index"), int):
            out[t["index"]] = t
    return out


def pair_id(slide_index: int, session_a: str, session_b: str) -> str:
    """A stable, opaque handle for one comparison.

    Canonical order (sorted session ids) so the SAME two takes on the same
    slide always produce the same id however the caller ordered them —
    otherwise a re-serve would look like a second, different pair and the
    corpus would double-count one judgment."""
    lo, hi = sorted([str(session_a), str(session_b)])
    raw = f"{int(slide_index)}|{lo}|{hi}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_pair_id(token: Any) -> Optional[tuple]:
    """(slide_index, session_lo, session_hi) or None when unreadable."""
    if not isinstance(token, str) or not token:
        return None
    try:
        pad = "=" * (-len(token) % 4)
        parts = base64.urlsafe_b64decode(token + pad).decode().split("|")
        if len(parts) != 3:
            return None
        return (int(parts[0]), parts[1], parts[2])
    except Exception:
        return None


def left_is_lo(token: str) -> bool:
    """Does the canonically-FIRST session show on the left?

    A hash of the pair, not the take order — see the blinding note above.
    Deterministic, so the layout is stable across serves; uncorrelated with
    recency, so position bias cannot hide inside "the newer one was always
    on the right"."""
    digest = hashlib.sha256(token.encode()).digest()
    return digest[0] % 2 == 0


def build_pairs(takes: Any, slides: Any) -> list:
    """Every judgeable (slide × take-pair) for one arc, blinded and ordered.

    `takes`: [{session_id, slide_transcripts, audio_ref}] — order irrelevant.
    `slides`: the arc's deck, for the slide's own title (context the coach is
    allowed: what the AUDIENCE saw is not a cue about which take this is).

    Returns [{pair_id, slide_index, slide_title, left:{…}, right:{…}}], slide
    order then pair order. A slide where fewer than two takes have real
    speech yields nothing — there is no comparison to make."""
    rows: list[_Take] = []
    for t in (takes or []):
        if isinstance(t, dict) and t.get("session_id"):
            rows.append(_Take(
                session_id=str(t["session_id"]),
                audio_ref=t.get("audio_ref"),
                by_index=_by_index(t.get("slide_transcripts")),
            ))
    if len(rows) < 2:
        return []
    deck = slides if isinstance(slides, list) else []
    out: list = []
    for si in range(len(deck)):
        have = [r for r in rows
                if _words((r.by_index.get(si) or {}).get("transcript"))
                >= _MIN_WORDS]
        if len(have) < 2:
            continue
        sl = deck[si] if isinstance(deck[si], dict) else {}
        for i in range(len(have)):
            for j in range(i + 1, len(have)):
                a, b = have[i], have[j]
                tok = pair_id(si, a.session_id, b.session_id)
                lo_id = min(a.session_id, b.session_id)
                first = a if a.session_id == lo_id else b
                second = b if first is a else a
                left, right = (
                    (first, second) if left_is_lo(tok) else (second, first)
                )
                out.append({
                    "pair_id": tok,
                    "slide_index": si,
                    "slide_title": (sl.get("title") or ""),
                    "left": _side(left, si),
                    "right": _side(right, si),
                })
    return out


def _side(row: _Take, slide_index: int) -> dict:
    """One side of a comparison — words, audio, timing. NOTHING that
    identifies WHICH take this is: no session id, no take index, no
    created_at. The blinding lives here."""
    t = row.by_index.get(slide_index) or {}
    return {
        "transcript": t.get("transcript") or "",
        "audio_ref": row.audio_ref,
        "start_offset_ms": t.get("start_offset_ms"),
        "duration_ms": t.get("duration_ms"),
    }


def resolve_verdict(token: Any, verdict: Any) -> Optional[dict]:
    """Turn a blinded answer back into a row about real takes.

    ('left' | 'right' | 'tie') + the pair token → which SESSION won, plus
    the true side assignment so position bias stays measurable. None when
    the token or the verdict is unreadable — an unresolvable judgment is
    dropped, never guessed into the corpus."""
    parts = decode_pair_id(token)
    if parts is None or verdict not in ("left", "right", "tie"):
        return None
    slide_index, lo, hi = parts
    left, right = (lo, hi) if left_is_lo(str(token)) else (hi, lo)
    winner = None
    if verdict == "left":
        winner = left
    elif verdict == "right":
        winner = right
    return {
        "slide_index": slide_index,
        "session_left": left,
        "session_right": right,
        "verdict": verdict,
        "winner_session_id": winner,
    }
