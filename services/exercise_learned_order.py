"""ML-13: the learned exercise order, behind a constant (founder 2026-09-29,
E8; build plan ML-13). Built closed.

The matcher's order among exercises at the SAME fit (the same confidence
distance) is editorial today. When all three hold —

  * ``Config.EXERCISE_LEARNED_ORDER_ENABLED`` is True (a reviewed change
    after the founder's yes),
  * the jar passed its bar (300 counted tries, 30 per exercise), and
  * the fair test's machine-only pile beats the fixed ranking by its bar
    (five points of success with the interval above zero; the test's own
    ``meets_bar``)

— ties are ordered by the learned helped rate on study-group speakers
(``exercise_evaluation.train_rates``), trusted only at the per-exercise bar.
Anything else keeps today's order exactly. The safety gate is untouched:
this reorders an already-eligible pool and never adds to it.

Read once a while, not per offer: the jar is re-read at most every
CACHE_SECONDS. Internal order only; no rate leaves this module.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

_log = logging.getLogger(__name__)

CACHE_SECONDS = 600.0
# `at` is None until the first read: a monotonic clock starts near zero on a
# fresh machine, so 0.0 would read as "just cached" for the first ten minutes.
_CACHE: dict[str, Any] = {"at": None, "rates": None, "why": "not read yet"}
_LOCK = threading.Lock()


def _enabled(config: Any) -> bool:
    return bool(getattr(config, "EXERCISE_LEARNED_ORDER_ENABLED", False))


def learned_rates(database: Any) -> tuple[Optional[dict[str, float]], str]:
    """({exercise_id: helped_rate} for trusted exercises, why) once the jar
    is unsealed and the fair test meets its bar; else (None, why)."""
    from services.exercise_evaluation import MIN_PER_EXERCISE, evaluate_jar
    evaluation = evaluate_jar(database)
    if evaluation.get("sealed"):
        return None, f"jar sealed: {evaluation.get('why_not')}"
    pile = evaluation.get("machine_only") or {}
    fair = pile.get("fair_test") or {}
    if not fair.get("meets_bar"):
        return None, "fair test below its bar: " + "; ".join(fair.get("why_not") or ["unknown"])
    rates: dict[str, float] = {}
    for pref in pile.get("preferences") or []:
        if not isinstance(pref, dict):
            continue
        if pref.get("trusted") and isinstance(pref.get("helped_rate"), (int, float)) \
                and int(pref.get("counted") or 0) >= MIN_PER_EXERCISE:
            rates[str(pref.get("exercise_id"))] = float(pref["helped_rate"])
    return rates, "learned"


def _rates_cached(database: Any) -> tuple[Optional[dict[str, float]], str]:
    now = time.monotonic()
    with _LOCK:
        at = _CACHE["at"]
        if at is not None and now - float(at) < CACHE_SECONDS:
            return _CACHE["rates"], str(_CACHE["why"])
    try:
        rates, why = learned_rates(database)
    except Exception as e:  # noqa: BLE001 -- the fixed order stands
        _log.warning("learned exercise order unavailable: %s", e, exc_info=True)
        rates, why = None, f"unavailable: {str(e)[:120]}"
    with _LOCK:
        _CACHE.update(at=now, rates=rates, why=why)
    return rates, why


def clear_cache() -> None:
    with _LOCK:
        _CACHE.update(at=None, rates=None, why="not read yet")


def reorder(ranked: list[tuple], rates: Optional[dict[str, float]]) -> list[tuple]:
    """Within each run of equal distance, trusted rates first, highest
    first; the rest keep their order. Pure."""
    if not rates:
        return list(ranked)
    out: list[tuple] = []
    group: list[tuple] = []
    current: Any = object()
    for item in ranked:
        if group and item[0] != current:
            out.extend(_sort_group(group, rates))
            group = []
        current = item[0]
        group.append(item)
    out.extend(_sort_group(group, rates))
    return out


def _sort_group(group: list[tuple], rates: dict[str, float]) -> list[tuple]:
    indexed = list(enumerate(group))
    indexed.sort(key=lambda pair: (
        0 if str(pair[1][2]) in rates else 1,
        -rates.get(str(pair[1][2]), 0.0),
        pair[0]))
    return [item for _, item in indexed]


def apply(ranked: list[tuple], database: Any, *, config: Any = None) -> list[tuple]:
    """The matcher's hook: today's order unless the three conditions hold."""
    if config is None:
        from config import Config
        config = Config
    if not _enabled(config) or not ranked:
        return list(ranked)
    rates, _why = _rates_cached(database)
    return reorder(ranked, rates)
