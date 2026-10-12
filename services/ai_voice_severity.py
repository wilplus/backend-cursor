"""Which one problem the AI clip practises: pace, pause or stress
(founder lock 2026-10-12, docs/FOUNDER-LOCK-ai-voice-practice-2026-10-12.md
section 5).

Each problem gets one severity from 0 (no sign of it) to 1 (strong), never
compared in its raw unit. Every severity is measured against the speaker's
OWN usual delivery on this Take (the median of their clips), so no accent,
pitch, voice level or speaking style is ever the target:

  pace    words per minute above the speaker's own median. The existing
          ``pace_high`` line (confident_voice_practice.exercise_eligibility:
          the median + 18, or x 1.12, whichever is larger; 175 with no
          median) is where severity reaches the minimum, 0.4.
  pause   the share of the clip spent pausing (``pause_ratio``) below the
          speaker's own median. ``insufficient_pauses`` (< 0.08) is the
          absolute line it can never be worse than.
  stress  the loudness range (``dynamic_db``) below the speaker's own
          median: a flatter delivery than they usually have. With no median
          there is no stress severity (no absolute loudness is a problem).

The highest severity wins if it reaches ``Config.AI_VOICE_MIN_SEVERITY``
(0.4); otherwise there is no exercise. An exercise that didn't help this
speaker twice running is held back, and a small share of picks takes the
runner-up, so the stored cycles can later tell which exercise helps. Both
are deterministic from the practice id. Internal only (AC-9): no number
leaves the server.
"""
from __future__ import annotations

import hashlib
import re
import statistics
from typing import Any, Iterable, Optional

from config import Config

PROBLEMS = ("pace", "pause", "stress")
RULES_VERSION = "ai-voice-severity-v1"

#: Severity at the line where the existing rule already calls it a problem.
AT_THE_LINE = 0.4
#: An exercise that did not improve the speaker's next try this many times
#: in a row is held back (its severity scaled by HELD_BACK_FACTOR).
HELD_BACK_AFTER = 2
HELD_BACK_FACTOR = 0.75

_PACE_NO_MEDIAN_LINE = 175.0
_PACE_NO_MEDIAN_COMFORT = 155.0
_PAUSE_ABSOLUTE_LINE = 0.08
_PAUSE_GAP = 0.06
_STRESS_GAP_DB = 4.0

REASONS = {
    "pace": "speech_rate_above_own_usual",
    "pause": "fewer_pauses_than_own_usual",
    "stress": "flatter_than_own_usual",
}
TARGET_CHANGE = {
    "pace": {"type": "relative_decrease", "metric": "words_per_minute", "value": 0.10},
    "pause": {"type": "insert_pause", "metric": "pause_before_target_s", "value": 0.5},
    "stress": {"type": "raise_contrast", "metric": "target_loudness_db", "value": 3.0},
}
GENERATION_INTENT = {
    "pace": {"delivery": "slightly slower and deliberate"},
    "pause": {"delivery": "one natural pause before the main point"},
    "stress": {"delivery": "the key phrase stands out naturally"},
}


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _metric(snippet: dict, name: str) -> Optional[float]:
    metrics = snippet.get("metrics") if isinstance(snippet, dict) else None
    return _number((metrics or {}).get(name)) if isinstance(metrics, dict) else None


def own_medians(take_snippets: Iterable[dict]) -> dict:
    """The speaker's own usual pace, pausing and loudness range on this Take."""
    out: dict[str, Optional[float]] = {}
    rows = list(take_snippets or [])
    for name in ("wpm", "pause_ratio", "dynamic_db"):
        values = [v for v in (_metric(row, name) for row in rows) if v is not None]
        out[name] = statistics.median(values) if len(values) >= 3 else None
    return out


def pace_severity(wpm: Optional[float], median: Optional[float]) -> float:
    if wpm is None:
        return 0.0
    if median is None:
        comfort, line = _PACE_NO_MEDIAN_COMFORT, _PACE_NO_MEDIAN_LINE
    else:
        comfort, line = median, max(median + 18.0, median * 1.12)
    return _clamp(AT_THE_LINE * (wpm - comfort) / (line - comfort))


def pause_severity(ratio: Optional[float], median: Optional[float]) -> float:
    if ratio is None:
        return 0.0
    comfort = max(median if median is not None else 0.0,
                  _PAUSE_ABSOLUTE_LINE + _PAUSE_GAP)
    return _clamp(AT_THE_LINE * (comfort - ratio) / _PAUSE_GAP)


def stress_severity(dynamic_db: Optional[float], median: Optional[float]) -> float:
    if dynamic_db is None or median is None:
        return 0.0
    return _clamp(AT_THE_LINE * (median - dynamic_db) / _STRESS_GAP_DB)


def severities(snippet: dict, medians: dict) -> dict[str, float]:
    return {
        "pace": round(pace_severity(_metric(snippet, "wpm"), medians.get("wpm")), 3),
        "pause": round(pause_severity(_metric(snippet, "pause_ratio"),
                                      medians.get("pause_ratio")), 3),
        "stress": round(stress_severity(_metric(snippet, "dynamic_db"),
                                        medians.get("dynamic_db")), 3),
    }


def _held_back(history: Iterable[dict]) -> set[str]:
    """Problems whose last HELD_BACK_AFTER outcomes for this speaker were all
    not improved (newest first in ``history``)."""
    by_problem: dict[str, list[str]] = {}
    for row in history or []:
        problem = str(row.get("exercise") or "")
        outcome = row.get("outcome")
        if problem in PROBLEMS and outcome:
            by_problem.setdefault(problem, []).append(str(outcome))
    return {
        problem for problem, outcomes in by_problem.items()
        if len(outcomes) >= HELD_BACK_AFTER
        and all(o != "improved" for o in outcomes[:HELD_BACK_AFTER])
    }


def _explores(seed: str) -> bool:
    share = max(0.0, min(1.0, float(Config.AI_VOICE_EXPLORE_SHARE)))
    digest = hashlib.sha256(f"explore:{seed}".encode()).digest()
    return (int.from_bytes(digest[:4], "big") / 2**32) < share


_BREAKS = re.compile(r"[,;:—–]|\s(?:because|but|so|and|which|that|when|if)\s",
                     re.IGNORECASE)


def target_phrase(sentence: str, max_words: int = 4) -> Optional[str]:
    """The main point: the opening words of the sentence's last clause.

    The last clause is what follows the last comma, dash or joining word
    ("because", "but", "so", ...); with none, the last third of the
    sentence. At most ``max_words`` words, at least two. None when the
    sentence is too short to have a main point apart from itself.
    """
    words = (sentence or "").split()
    if len(words) < 5:
        return None
    breaks = list(_BREAKS.finditer(sentence))
    tail = sentence[breaks[-1].end():] if breaks else " ".join(
        words[len(words) - max(2, len(words) // 3):])
    tail_words = [w for w in tail.split() if w.strip()]
    if len(tail_words) < 2 or len(tail_words) >= len(words):
        tail_words = words[len(words) - max(2, len(words) // 3):]
    return " ".join(tail_words[:max_words]).strip(" ,;:.!?") or None


def select(snippet: dict, medians: dict, *, sentence: str, seed: str,
           history: Iterable[dict] = ()) -> Optional[dict]:
    """The one exercise for this clip, or None when every signal is weak."""
    scores = severities(snippet, medians)
    held = _held_back(history)
    ranked = sorted(
        PROBLEMS,
        key=lambda p: -(scores[p] * (HELD_BACK_FACTOR if p in held else 1.0)))
    floor = float(Config.AI_VOICE_MIN_SEVERITY)
    eligible = [p for p in ranked if scores[p] >= floor]
    if not eligible:
        return None
    explored = len(eligible) > 1 and _explores(seed)
    problem = eligible[1] if explored else eligible[0]
    phrase = target_phrase(sentence) if problem in ("pause", "stress") else None
    if problem in ("pause", "stress") and not phrase:
        # No main point to pause before or stand out: the next problem, if any.
        rest = [p for p in eligible if p == "pace"]
        if not rest:
            return None
        problem, phrase = rest[0], None
    return {
        "exercise": problem,
        "reason": REASONS[problem],
        "severity": scores[problem],
        "severity_scores": scores,
        "trigger_measurements": {
            "words_per_minute": _metric(snippet, "wpm"),
            "own_usual_words_per_minute": medians.get("wpm"),
            "pause_ratio": _metric(snippet, "pause_ratio"),
            "own_usual_pause_ratio": medians.get("pause_ratio"),
            "dynamic_db": _metric(snippet, "dynamic_db"),
            "own_usual_dynamic_db": medians.get("dynamic_db"),
        },
        "target_change": TARGET_CHANGE[problem],
        "target_phrase": phrase,
        "generation_intent": {**GENERATION_INTENT[problem],
                              "preserve_words": True, "preserve_accent": True},
        "explored": explored,
        "held_back": sorted(held),
        "rules_version": RULES_VERSION,
    }


def outcome(problem: str, before: dict, after: dict, medians: dict) -> str:
    """improved · similar · worsened · inconclusive, on the one problem only,
    in the same units and against the same own-usual line as the pick."""
    measure = {"pace": ("wpm", pace_severity),
               "pause": ("pause_ratio", pause_severity),
               "stress": ("dynamic_db", stress_severity)}.get(problem)
    if measure is None:
        return "inconclusive"
    name, fn = measure
    key = {"wpm": "wpm", "pause_ratio": "pause_ratio", "dynamic_db": "dynamic_db"}[name]
    b, a = _number((before or {}).get(key)), _number((after or {}).get(key))
    median = medians.get(name)
    if b is None or a is None or (problem == "stress" and median is None):
        return "inconclusive"
    sb, sa = fn(b, median), fn(a, median)
    if sa <= sb - 0.1:
        return "improved"
    if sa >= sb + 0.1:
        return "worsened"
    return "similar"
