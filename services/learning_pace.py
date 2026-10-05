"""The pace (founder 2026-09-30, C9; build plan ML-4): how fast each jar
fills and how many weeks to its bar, from the weekly snapshots.

Pure. Every number is about the system (a count of pairs, of tries, of
named moments), never about a person. A rate is the mean weekly change
over the last four snapshots; with fewer than two snapshots there is no
observed rate and the panel says so rather than guessing.
"""
from __future__ import annotations

import math
from typing import Any, Optional

WINDOW_WEEKS = 4


def _count(snapshot: Any, path: tuple[str, ...]) -> Optional[int]:
    node: Any = snapshot
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return int(node) if isinstance(node, (int, float)) and not isinstance(node, bool) else None


#: Every jar the panel draws: (jar id, the path in a snapshot, the bar).
#: A pair jar counts every releasable pair ever written (second plan,
#: 2026-10-05): it counted pairs not yet exported, so each weekly export
#: emptied it and the panel could never show it filling. Snapshots taken
#: before the count existed read as unknown, not zero.
JARS: tuple[tuple[str, tuple[str, ...], int], ...] = (
    ("pairs.praise_line", ("pairs", "praise_line", "releasable"), 200),
    ("pairs.clearer_version", ("pairs", "clearer_version", "releasable"), 200),
    ("pairs.exercise_script", ("pairs", "exercise_script", "releasable"), 200),
    ("exercise_jar.counted", ("exercise_jar", "counted"), 300),
)


def observed_rate(values: list[Optional[int]]) -> Optional[float]:
    """Mean weekly change over the last WINDOW_WEEKS consecutive readings
    (oldest first); None with fewer than two readings."""
    known = [v for v in values[-(WINDOW_WEEKS + 1):] if v is not None]
    if len(known) < 2:
        return None
    deltas = [b - a for a, b in zip(known, known[1:])]
    return sum(deltas) / len(deltas)


def weeks_to_bar(current: Optional[int], bar: int, rate: Optional[float]) -> Optional[float]:
    """Whole weeks until the bar at the given rate; 0 when already there;
    None when the rate is unknown or not positive."""
    if current is None:
        return None
    if current >= bar:
        return 0.0
    if rate is None or rate <= 0:
        return None
    return float(math.ceil((bar - current) / rate))


def pace(ledger: dict, snapshots: list[dict]) -> list[dict]:
    """One row per jar: the live count, the bar, the observed weekly rate
    and the weeks to the bar at that rate. `snapshots` oldest first, each a
    ledger dict as the weekly job stored it."""
    rows = []
    for jar, path, bar in JARS:
        history = [_count(s, path) for s in snapshots]
        current = _count(ledger, path)
        rate = observed_rate([*history, current])
        rows.append({
            "jar": jar,
            "current": current,
            "bar": bar,
            "observed_rate": rate,
            "weeks_to_bar": weeks_to_bar(current, bar, rate),
        })
    for cue, row in (ledger.get("shadow_cues") or {}).items():
        if not isinstance(row, dict):
            continue
        history = [_count(s, ("shadow_cues", cue, "named")) for s in snapshots]
        current = row.get("named") if isinstance(row.get("named"), int) else None
        rate = observed_rate([*history, current])
        rows.append({
            "jar": f"shadow_cues.{cue}",
            "current": current,
            "bar": int(row.get("named_bar") or 0),
            "observed_rate": rate,
            "weeks_to_bar": weeks_to_bar(current, int(row.get("named_bar") or 0), rate),
            "caught_rate": row.get("caught_rate"),
            "caught_bar": row.get("caught_bar"),
            "ready": bool(row.get("ready")),
        })
    return rows
