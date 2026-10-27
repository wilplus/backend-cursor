"""Which one problem the AI clip practises: pace, pause, stress or fillers
(founder lock 2026-10-12, docs/FOUNDER-LOCK-ai-voice-practice-2026-10-12.md
section 5; fillers added by the founder 2026-10-18).

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
  fillers hesitations ("um", "uh": the closed list the transcript fence
          removes silently, services.transcript_smoothing) per 100 words of
          the sentence, above the speaker's own median on this Take (0 with
          no median: a usually clean speaker). ``Config.AI_VOICE_FILLER_GAP_PER_100``
          more than their usual is the line. The AI lane is English (the
          request and the re-hearing both say so), so the English list.

The highest severity wins if it reaches ``Config.AI_VOICE_MIN_SEVERITY``
(0.2 since 2026-10-15; 0.4 is the line itself); otherwise the default, stress on the main point, marked
``default`` (founder 2026-10-15: always a better version to copy). The minimum and every normalization
range (``Config.AI_VOICE_PACE_*``, ``AI_VOICE_PAUSE_*``,
``AI_VOICE_STRESS_GAP_DB``) are configuration, read at each pick. An
exercise that didn't help this speaker twice running is held back, and a
small share of picks takes the runner-up, so the stored cycles can later
tell which exercise helps. Both are deterministic from the practice id. Internal only (AC-9): no number
leaves the server.
"""
from __future__ import annotations

import hashlib
import re
import statistics
from typing import Any, Iterable, Optional

from config import Config

PROBLEMS = ("pace", "pause", "stress", "fillers")
#: v2 (2026-10-18): the fillers problem joined the three.
RULES_VERSION = "ai-voice-severity-v2"
#: The language the AI lane speaks and hears; the hesitation list follows it.
LANE_LANGUAGE = "en"

#: Severity at the line where the existing rule already calls it a problem.
AT_THE_LINE = 0.4
#: An exercise that did not improve the speaker's next try this many times
#: in a row is held back (its severity scaled by HELD_BACK_FACTOR).
HELD_BACK_AFTER = 2
HELD_BACK_FACTOR = 0.75

REASONS = {
    "pace": "speech_rate_above_own_usual",
    "pause": "fewer_pauses_than_own_usual",
    "stress": "flatter_than_own_usual",
    "fillers": "more_fillers_than_own_usual",
}
TARGET_CHANGE = {
    "pace": {"type": "relative_decrease", "metric": "words_per_minute", "value": 0.10},
    "pause": {"type": "insert_pause", "metric": "pause_before_target_s", "value": 0.5},
    "stress": {"type": "raise_contrast", "metric": "target_loudness_db", "value": 3.0},
    "fillers": {"type": "remove_fillers", "metric": "fillers_per_100_words", "value": 0.0},
}
#: Why a clip was made when no problem reached the line: the default.
DEFAULT_REASON = "no_clear_problem_default"
GENERATION_INTENT = {
    "pace": {"delivery": "slightly slower and deliberate"},
    "pause": {"delivery": "one natural pause before the main point"},
    "stress": {"delivery": "the key phrase stands out naturally"},
    "fillers": {"delivery": "the same sentence, its hesitations left out"},
}
#: The problems that need no target phrase.
_NO_PHRASE = ("pace", "fillers")


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _metric(snippet: dict, name: str) -> Optional[float]:
    metrics = snippet.get("metrics") if isinstance(snippet, dict) else None
    return _number((metrics or {}).get(name)) if isinstance(metrics, dict) else None


def fillers_per_100(text: Any, language: Optional[str] = LANE_LANGUAGE) -> Optional[float]:
    """Hesitations per 100 words of a text; None when it has no words."""
    from services.transcript_smoothing import count_fillers
    words = len(re.findall(r"[\w']+", str(text or "")))
    if words <= 0:
        return None
    return round(100.0 * count_fillers(str(text), language) / words, 3)


def own_medians(take_snippets: Iterable[dict]) -> dict:
    """The speaker's own usual pace, pausing, loudness range and fillers on
    this Take."""
    out: dict[str, Optional[float]] = {}
    rows = list(take_snippets or [])
    for name in ("wpm", "pause_ratio", "dynamic_db"):
        values = [v for v in (_metric(row, name) for row in rows) if v is not None]
        out[name] = statistics.median(values) if len(values) >= 3 else None
    rates = [v for v in (fillers_per_100((row or {}).get("transcript"))
                         for row in rows if isinstance(row, dict)) if v is not None]
    out["fillers_per_100"] = statistics.median(rates) if len(rates) >= 3 else None
    return out


def _ranged(over: float, gap: float) -> float:
    """How far past the comfortable point, on a range where ``gap`` reaches
    AT_THE_LINE; 0 when the range is not a positive number."""
    return _clamp(AT_THE_LINE * over / gap) if gap > 0 else 0.0


def pace_severity(wpm: Optional[float], median: Optional[float]) -> float:
    if wpm is None:
        return 0.0
    if median is None:
        comfort = float(Config.AI_VOICE_PACE_COMFORT_NO_MEDIAN)
        line = float(Config.AI_VOICE_PACE_LINE_NO_MEDIAN)
    else:
        comfort = median
        line = max(median + float(Config.AI_VOICE_PACE_OVER_MEDIAN_WPM),
                   median * float(Config.AI_VOICE_PACE_OVER_MEDIAN_RATIO))
    return _ranged(wpm - comfort, line - comfort)


def pause_severity(ratio: Optional[float], median: Optional[float]) -> float:
    if ratio is None:
        return 0.0
    gap = float(Config.AI_VOICE_PAUSE_GAP_RATIO)
    comfort = max(median if median is not None else 0.0,
                  float(Config.AI_VOICE_PAUSE_FLOOR_RATIO) + gap)
    return _ranged(comfort - ratio, gap)


def stress_severity(dynamic_db: Optional[float], median: Optional[float]) -> float:
    if dynamic_db is None or median is None:
        return 0.0
    return _ranged(median - dynamic_db, float(Config.AI_VOICE_STRESS_GAP_DB))


def filler_severity(per_100: Optional[float], median: Optional[float]) -> float:
    """How many more hesitations per 100 words than the speaker's own usual
    (0 with no usual); none in the sentence is never a problem."""
    if per_100 is None or per_100 <= 0:
        return 0.0
    comfort = median if median is not None else 0.0
    return _ranged(per_100 - comfort, float(Config.AI_VOICE_FILLER_GAP_PER_100))


def severities(snippet: dict, medians: dict, *, sentence: Optional[str] = None) -> dict[str, float]:
    text = sentence if sentence is not None else (snippet or {}).get("transcript")
    return {
        "pace": round(pace_severity(_metric(snippet, "wpm"), medians.get("wpm")), 3),
        "pause": round(pause_severity(_metric(snippet, "pause_ratio"),
                                      medians.get("pause_ratio")), 3),
        "stress": round(stress_severity(_metric(snippet, "dynamic_db"),
                                        medians.get("dynamic_db")), 3),
        "fillers": round(filler_severity(fillers_per_100(text),
                                         medians.get("fillers_per_100")), 3),
    }


def _held_back(history: Iterable[dict]) -> set[str]:
    """Problems whose last HELD_BACK_AFTER outcomes for this speaker were all
    not improved (newest first in ``history``). Only a clip that was made
    counts (``ready_at``, kept after a Delete): a try after one that failed
    its check was scored before 2026-10-21 and says nothing about the clip."""
    by_problem: dict[str, list[str]] = {}
    for row in history or []:
        if not row.get("ready_at"):
            continue
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
           history: Iterable[dict] = (), prefer: Optional[str] = None) -> Optional[dict]:
    """The one exercise for this clip. With every signal weak, the default
    (stress on the main point); None only when the sentence has no main
    point apart from itself.

    ``prefer``: the problem this week's level practises, on a plan (G7,
    N209; ``services.plan_walk.AI_PROBLEM``). It is the exercise whenever
    the clip shows it (its severity reaches the minimum) and it has what it
    needs; otherwise the pick is as without a plan."""
    scores = severities(snippet, medians, sentence=sentence)
    held = _held_back(history)
    if prefer in PROBLEMS and scores[prefer] >= float(Config.AI_VOICE_MIN_SEVERITY):
        phrase = None if prefer in _NO_PHRASE else target_phrase(sentence)
        if prefer in _NO_PHRASE or phrase:
            return _selection(prefer, phrase, scores, snippet, medians, held,  # type: ignore[arg-type]
                              explored=False, default=False, sentence=sentence)
    ranked = sorted(
        PROBLEMS,
        key=lambda p: -(scores[p] * (HELD_BACK_FACTOR if p in held else 1.0)))
    floor = float(Config.AI_VOICE_MIN_SEVERITY)
    eligible = [p for p in ranked if scores[p] >= floor]
    if not eligible:
        # Nothing clearly off: the main point said so it stands out, so the
        # speaker always hears a better version (founder 2026-10-15, A).
        # Recorded as a default, never as a problem found.
        phrase = target_phrase(sentence)
        if not phrase:
            return None
        return _selection("stress", phrase, scores, snippet, medians, held,
                          explored=False, default=True, sentence=sentence)
    explored = len(eligible) > 1 and _explores(seed)
    problem = eligible[1] if explored else eligible[0]
    phrase = None if problem in _NO_PHRASE else target_phrase(sentence)
    if problem not in _NO_PHRASE and not phrase:
        # No main point to pause before or stand out: the next problem that
        # needs none, if any.
        rest = [p for p in eligible if p in _NO_PHRASE]
        if not rest:
            return None
        problem, phrase = rest[0], None
    return _selection(problem, phrase, scores, snippet, medians, held,
                      explored=explored, default=False, sentence=sentence)


def _selection(problem: str, phrase: Optional[str], scores: dict, snippet: dict,
               medians: dict, held: set, *, explored: bool, default: bool,
               sentence: Optional[str] = None) -> dict:
    text = sentence if sentence is not None else (snippet or {}).get("transcript")
    return {
        "exercise": problem,
        "reason": DEFAULT_REASON if default else REASONS[problem],
        "default": default,
        "severity": scores[problem],
        "severity_scores": scores,
        "trigger_measurements": {
            "words_per_minute": _metric(snippet, "wpm"),
            "own_usual_words_per_minute": medians.get("wpm"),
            "pause_ratio": _metric(snippet, "pause_ratio"),
            "own_usual_pause_ratio": medians.get("pause_ratio"),
            "dynamic_db": _metric(snippet, "dynamic_db"),
            "own_usual_dynamic_db": medians.get("dynamic_db"),
            "fillers_per_100_words": fillers_per_100(text),
            "own_usual_fillers_per_100_words": medians.get("fillers_per_100"),
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
               "stress": ("dynamic_db", stress_severity),
               "fillers": ("fillers_per_100", filler_severity)}.get(problem)
    if measure is None:
        return "inconclusive"
    name, fn = measure
    b, a = _number((before or {}).get(name)), _number((after or {}).get(name))
    median = medians.get(name)
    if b is None or a is None or (problem == "stress" and median is None):
        return "inconclusive"
    sb, sa = fn(b, median), fn(a, median)
    if sa <= sb - 0.1:
        return "improved"
    if sa >= sb + 0.1:
        return "worsened"
    return "similar"
