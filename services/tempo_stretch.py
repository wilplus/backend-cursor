"""The tempo step's stretch (founder 2026-10-26, N162, N166; frontend
docs/flows/feedback-walk-and-chat.md §2 "Tempo", build step 3).

Which stretch of a Take the tempo step practises: the clip the pace scale
reads furthest from the green (N166 item 1), whether it ran fast or slow,
and what it was about.

The pace scale (N142, ``pace-scale-v1``) runs on the speaker's voice in the
browser. Here the same rules run on the Take's word timings: inside a word
is voice, between words is quiet. The meter's activity is replayed 10 ms at
a time over the whole Take, and each clip is read by how much of its time
the dot spent past the green on the right (rushed) or on the left (slow).
The clip with the largest share wins; under ``MIN_OUTSIDE`` no stretch is
picked and the walk passes the step by.

The topic is one small-model call inside the Take's protected provider
scope (``services.take_summary._under_authority``), kept only when it is a
short plain phrase (``read_topic``); otherwise the step says "that part".
Internal only (AC-9): no number leaves the server.
"""
from __future__ import annotations

import logging
import re
import threading
from collections import OrderedDict
from typing import Any, Optional

logger = logging.getLogger(__name__)

RULES_VERSION = "tempo-stretch-v1"
FRAME_MS = 10
#: The settled speeds of the pace scale (N142; frontend
#: src/lib/willab/pace/paceSignal.ts INSTANT_CONFIG). Kept in step by hand.
MIN_GAP_MS = 250
FALL_UPPER_MS = 2600
FALL_LOWER_MS = 5000
RISE_JUMP_MS = 400
RISE_BASE_MS = 1300
RISE_MID_BOOST = 1.25
RISE_TOP_BOOST = 1.37
#: The green on the scale: |2a - 1| <= 0.45, so activity in [0.275, 0.725].
GREEN_LOW = 0.275
GREEN_HIGH = 0.725
#: A clip needs this share of its time outside the green to be practised.
MIN_OUTSIDE = 0.25
#: Said back when no topic passes the guard.
FALLBACK_TOPIC = "that part"


def activity_path(voiced: list[bool]) -> list[float]:
    """The pace scale's activity, one value per 10 ms frame of voice or
    quiet, by the settled rules (N142). Pure."""
    a = 0.0
    gap = 100000
    run = 0
    out: list[float] = []
    for v in voiced:
        gap = 0 if v else min(gap + 1, 100000)
        pause = gap * FRAME_MS >= MIN_GAP_MS
        run = 0 if pause else run + FRAME_MS
        if v:
            gentle = 0.15 / RISE_BASE_MS
            if a < 0.5:
                speed = 0.5 / RISE_JUMP_MS
            elif a < 0.65:
                speed = gentle
            elif a < 0.75:
                speed = gentle * RISE_MID_BOOST
            else:
                speed = gentle * RISE_TOP_BOOST
            zone = 0.56 if a >= 0.75 else 0.63 if a >= 0.6 else 1.0
            brake = 1.0 if run >= 22000 else zone * 0.25 if a >= 0.5 else 0.5 if a >= 0.3 else 1.0
            a = min(1.0, a + speed * brake * FRAME_MS)
        elif not pause and a <= 0.75:
            pass  # a gap between words: hold
        elif a > 0.75:
            a = max(0.5, a - 0.5 * FRAME_MS / 1000)
        else:
            span = FALL_UPPER_MS if a > 0.5 else FALL_LOWER_MS
            sink = 0.4 if a < 0.37 else 0.5 if 0.4 <= a <= 0.6 else 1.0
            a = max(0.0, a - sink * 0.5 * FRAME_MS / span)
        out.append(a)
    return out


def _words(snippets: list[dict]) -> list[tuple[float, float]]:
    """Every timed word of the Take, (start, end) in seconds, once each."""
    seen: set[tuple[float, float]] = set()
    for s in snippets:
        for w in s.get("words") or []:
            if not isinstance(w, dict):
                continue
            st, en = w.get("start"), w.get("end")
            if isinstance(st, (int, float)) and isinstance(en, (int, float)) and en >= st:
                seen.add((float(st), float(en)))
    return sorted(seen)


def _window(s: dict) -> Optional[tuple[int, int]]:
    """A clip's place on the Take, in frames, from its own word timings."""
    times = [(float(w["start"]), float(w["end"])) for w in s.get("words") or []
             if isinstance(w, dict) and isinstance(w.get("start"), (int, float))
             and isinstance(w.get("end"), (int, float))]
    if not times:
        return None
    return int(min(a for a, _ in times) * 1000 // FRAME_MS), int(max(b for _, b in times) * 1000 // FRAME_MS)


def pick(snippets: list[dict]) -> Optional[dict]:
    """The clip furthest from the green and which side it leaned to, or None
    when no clip spends ``MIN_OUTSIDE`` of its time outside it. Pure."""
    words = _words(snippets)
    if not words:
        return None
    first = int(words[0][0] * 1000 // FRAME_MS)
    last = int(words[-1][1] * 1000 // FRAME_MS)
    voiced = [False] * (last - first + 1)
    for st, en in words:
        for f in range(int(st * 1000 // FRAME_MS) - first, int(en * 1000 // FRAME_MS) - first + 1):
            voiced[f] = True
    path = activity_path(voiced)
    best: Optional[dict] = None
    for index, s in enumerate(snippets):
        span = _window(s)
        if not span or not str(s.get("transcript") or "").strip():
            continue
        frames = path[max(0, span[0] - first): span[1] - first + 1]
        if not frames:
            continue
        rushed = sum(1 for v in frames if v > GREEN_HIGH) / len(frames)
        slow = sum(1 for v in frames if v < GREEN_LOW) / len(frames)
        outside = max(rushed, slow)
        if outside >= MIN_OUTSIDE and (best is None or outside > best["outside"]):
            best = {"index": index, "outside": outside, "reading": "rushed" if rushed >= slow else "slow"}
    return best


_SENTENCE = re.compile(r"(?<=[.?!])\s+")


def said_around(snippets: list[dict], index: int) -> dict:
    """The stretch with the sentence before and after it, as said. Pure."""
    def text(i: int) -> str:
        return " ".join(str(snippets[i].get("transcript") or "").split()) if 0 <= i < len(snippets) else ""
    before = [s for s in _SENTENCE.split(text(index - 1)) if s]
    after = [s for s in _SENTENCE.split(text(index + 1)) if s]
    return {"before": before[-1] if before else "", "stretch": text(index), "after": after[0] if after else ""}


_TOPIC_BANNED = re.compile(r"\d|%|[\"“”]|\bscore\b|\bwillfidence\b")


def read_topic(text: Optional[str]) -> Optional[str]:
    """The model's topic when it is a short plain phrase: 2 to 6 words, no
    number, quote or full sentence. Else None. Pure."""
    body = " ".join(str(text or "").strip().strip("'\"“”").rstrip(".!?").split())
    if not body or _TOPIC_BANNED.search(body):
        return None
    if not 2 <= len(body.split()) <= 6 or len(body) > 60:
        return None
    return body[0].lower() + body[1:] if not body[:2].isupper() else body


def write_topic(stretch: str, *, user_id: str, take: str, arc_id: str) -> Optional[str]:
    from services.llm import chat_complete
    from services.llm_config import SPEC_TEMPO_TOPIC
    from services.prompts.tempo_topic import SYSTEM
    result = chat_complete(spec=SPEC_TEMPO_TOPIC, system=SYSTEM, user=f"Passage: {stretch[:1200]}",
                           surface="tempo_topic", user_id=user_id, session_id=take, arc_id=arc_id)
    return read_topic(getattr(result, "text", None) if result else None)


_CACHE: "OrderedDict[str, Optional[dict]]" = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 256


def tempo_for_take(database: Any, *, take: str, user_id: str, arc_id: str) -> Optional[dict]:
    """{reading, topic, said} for the Take's tempo step, or None when no
    clip leaves the green. Read once per Take per process."""
    with _CACHE_LOCK:
        if take in _CACHE:
            _CACHE.move_to_end(take)
            return _CACHE[take]
    snippets = database.get_snippets_by_session(take) or []
    chosen = pick(snippets)
    result: Optional[dict] = None
    if chosen:
        said = said_around(snippets, chosen["index"])
        topic: Optional[str] = None
        try:
            from services.take_summary import _under_authority
            topic = _under_authority(database, take, lambda: write_topic(
                said["stretch"], user_id=user_id, take=take, arc_id=arc_id))
        except Exception as error:  # noqa: BLE001 -- the step says "that part"
            from services.processing_authorization import rethrow_processing_authorization
            rethrow_processing_authorization(error)
            logger.warning("tempo topic failed take=%s: %s", take, type(error).__name__, exc_info=True)
        result = {"reading": chosen["reading"], "topic": topic or FALLBACK_TOPIC, "said": said}
    with _CACHE_LOCK:
        _CACHE[take] = result
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return result
