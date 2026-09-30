"""The label quorum as the data scientist reads it (build plan ML-7).

From the blind confidence labels (one row per rater per moment, coach and
peer lanes, never self-reports): how many labels, how many moments have
two human answers, how often two humans agree, and Cohen's kappa once
there are a hundred labels to make it mean something. Pure; the route
hands in the rows.

AC-9: these are numbers about the instrument, for the research role only.
"""
from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import Any, Optional

KAPPA_MIN_LABELS = 100
_DEFINITE = ("yes", "in_between", "no", "not_sure")
_HUMAN_LANES = ("coach", "game_peer", "peer")


def _value(row: dict) -> Optional[str]:
    if row.get("unrateable"):
        return "audio_unclear"
    value = row.get("value")
    if value in _DEFINITE:
        return str(value)
    if row.get("confident") is True:
        return "yes"
    if row.get("confident") is False:
        return "no"
    return None


def _human(row: dict) -> bool:
    if row.get("self_report"):
        return False
    lane = row.get("lane")
    return lane is None or lane in _HUMAN_LANES


def cohen_kappa(pairs: list[tuple[str, str]]) -> Optional[float]:
    """Cohen's kappa over paired answers; None with no pairs."""
    if not pairs:
        return None
    n = len(pairs)
    categories = sorted({a for a, _ in pairs} | {b for _, b in pairs})
    observed = sum(1 for a, b in pairs if a == b) / n
    left: dict[str, int] = defaultdict(int)
    right: dict[str, int] = defaultdict(int)
    for a, b in pairs:
        left[a] += 1
        right[b] += 1
    expected = sum((left[c] / n) * (right[c] / n) for c in categories)
    if expected >= 1.0:
        return 1.0
    return round((observed - expected) / (1 - expected), 3)


def quorum(rows: list[Any]) -> dict:
    """The quorum figures from confidence label rows."""
    by_snippet: dict[str, dict[str, str]] = defaultdict(dict)
    labels = 0
    for row in rows or []:
        if not isinstance(row, dict) or not _human(row):
            continue
        value = _value(row)
        snippet = str(row.get("snippet_id") or "")
        rater = str(row.get("rater_id") or "")
        if not value or not snippet or not rater:
            continue
        labels += 1
        by_snippet[snippet][rater] = value
    two_human = [answers for answers in by_snippet.values() if len(answers) >= 2]
    agreed = 0
    pairs: list[tuple[str, str]] = []
    for answers in two_human:
        values = [v for v in answers.values() if v != "audio_unclear"]
        raters = list(answers.items())
        for (_, a), (_, b) in combinations(raters, 2):
            if a == "audio_unclear" or b == "audio_unclear":
                continue
            pairs.append((a, b))
        if len(values) >= 2 and len(set(values)) == 1:
            agreed += 1
    return {
        "labels": labels,
        "moments": len(by_snippet),
        "moments_with_two_humans": len(two_human),
        "two_human_agreement": (round(agreed / len(two_human), 3) if two_human else None),
        "kappa": cohen_kappa(pairs) if labels >= KAPPA_MIN_LABELS else None,
        "kappa_from": KAPPA_MIN_LABELS,
    }
