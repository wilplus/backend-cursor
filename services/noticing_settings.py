"""What the speaking coach notices, as settings (N647 item 8, step 3).

The thresholds that decide what the feedback walk notices lived as Python
constants. Eight of them, the ones a dial can move (more or fewer catches,
one meaning), are read here instead, from one record:
``runtime_config`` key ``noticing_settings``, a JSON object
``{"version": "...", "values": {name: value}}``.

TODAY'S VALUES ARE THE DEFAULTS, and nothing changes while the record is
missing, unreadable, or holds the defaults. A value that is missing, of the
wrong type or outside its bounds falls back to its constant on its own; the
rest of the record still counts. ``tests/test_noticing_settings.py`` pins
``DEFAULTS`` to the constants in their own modules, name by name.

THE VERSION. ``version()`` is ``DEFAULT_VERSION`` while every value is the
default; otherwise ``noticing-`` and a hash of the values that differ, so a
log written under a moved threshold can never be compared with one written
under today's. The verbal cues stamp it into their detector version and the
policy frame into its practice policy, only when it is not the default.

THE SEAM FOR A SILENT TRY (step 4, a neighbouring session). A candidate is a
pure value, never stored: ``candidate(overrides)`` returns the full set with
the overrides that pass the bounds, and ``version_of(values)`` its version.
``with trying(values):`` runs the same rules on it, in that context only
(a ``contextvars`` value: other threads and requests keep the live set), and
the rules need no new argument. A caller runs the live rule, then the same
rule inside ``trying``, and logs the second result; it never serves it.

The record is read at most once a minute per process (``CACHE_SECONDS``),
and a failed read counts as missing for that minute. Never shown to anyone.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Iterator, Mapping, Optional

logger = logging.getLogger(__name__)

KEY = "noticing_settings"
DEFAULT_VERSION = "noticing-v0-defaults"
CACHE_SECONDS = 60.0

_BANDS_LOW = ("delivery_signal_low",)
_BANDS_TWO = ("delivery_signal_mid_low", "delivery_signal_low")
_BANDS_THREE = ("delivery_signal_neutral", "delivery_signal_mid_low",
                "delivery_signal_low")

#: Today's values, under the names of the constants they replace.
DEFAULTS: dict[str, Any] = {
    "tempo_stretch.MIN_OUTSIDE": 0.25,
    "verbal_cues.FILLER_MIN_COUNT": 2,
    "verbal_cues.FILLER_MIN_PER_100_WORDS": 5.0,
    "verbal_cues.HEDGE_MIN_COUNT": 2,
    "verbal_cues.RESTART_MIN_COUNT": 2,
    "take_feedback_policy_v3.PRACTICE_BANDS": _BANDS_TWO,
    "moment_pick.FLOOR": 0.6,
    "take_context.MATCH": 0.6,
}

#: What each value may be. Numbers: (type, low, high), both ends included.
#: The practice bands: one of the three runs from the bottom band up.
_BOUNDS: dict[str, Any] = {
    "tempo_stretch.MIN_OUTSIDE": (float, 0.05, 0.6),
    "verbal_cues.FILLER_MIN_COUNT": (int, 1, 6),
    "verbal_cues.FILLER_MIN_PER_100_WORDS": (float, 1.0, 15.0),
    "verbal_cues.HEDGE_MIN_COUNT": (int, 1, 6),
    "verbal_cues.RESTART_MIN_COUNT": (int, 1, 6),
    "take_feedback_policy_v3.PRACTICE_BANDS": (_BANDS_LOW, _BANDS_TWO, _BANDS_THREE),
    "moment_pick.FLOOR": (float, 0.3, 0.9),
    "take_context.MATCH": (float, 0.3, 0.9),
}


def _checked(name: str, value: Any) -> Any:
    """The value in its proper type when it is within bounds, else None."""
    bound = _BOUNDS.get(name)
    if bound is None:
        return None
    if isinstance(bound[0], tuple):
        if isinstance(value, (list, tuple)) and tuple(value) in bound:
            return tuple(value)
        return None
    kind, low, high = bound
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if kind is int and float(value) != int(value):
        return None
    if not low <= value <= high:
        return None
    return kind(value)


def candidate(overrides: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """The full set: the defaults, with each override that passes its bounds.
    Pure; stores nothing. An unknown name or a bad value is left out."""
    values = dict(DEFAULTS)
    for name, value in (overrides or {}).items():
        checked = _checked(str(name), value)
        if checked is not None:
            values[str(name)] = checked
    return values


def version_of(values: Mapping[str, Any]) -> str:
    """``DEFAULT_VERSION`` when every value is the default, else a hash of
    the ones that differ. Pure."""
    moved = {name: list(v) if isinstance(v, tuple) else v
             for name, v in sorted(values.items())
             if name in DEFAULTS and v != DEFAULTS[name]}
    if not moved:
        return DEFAULT_VERSION
    blob = json.dumps(moved, sort_keys=True, separators=(",", ":"))
    return "noticing-" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def _read_store() -> Optional[str]:
    from services.db import db
    return db.get_runtime_config(KEY)


_reader: Callable[[], Optional[str]] = _read_store
_lock = threading.Lock()
_cached: Optional[dict[str, Any]] = None
_cached_at = 0.0


def _parse(raw: Optional[str]) -> dict[str, Any]:
    if not raw:
        return dict(DEFAULTS)
    try:
        record = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("noticing_settings: the record is not JSON; using the defaults")
        return dict(DEFAULTS)
    stored = record.get("values") if isinstance(record, dict) else None
    if not isinstance(stored, dict):
        logger.warning("noticing_settings: the record has no values; using the defaults")
        return dict(DEFAULTS)
    values = candidate(stored)
    for name, value in stored.items():
        if name in DEFAULTS and values[name] != _checked(name, value):
            logger.warning("noticing_settings: %s is out of bounds; using its default", name)
    return values


def live() -> dict[str, Any]:
    """The values in force: the record, at most a minute old, else the
    defaults. Never raises."""
    global _cached, _cached_at
    now = time.monotonic()
    with _lock:
        if _cached is not None and now - _cached_at < CACHE_SECONDS:
            return _cached
        try:
            raw = _reader()
        except Exception as exc:  # the record is optional; the constants stand
            logger.warning("noticing_settings: read failed (%s); using the defaults",
                           exc, exc_info=True)
            raw = None
        _cached, _cached_at = _parse(raw), now
        return _cached


_trying: ContextVar[Optional[Mapping[str, Any]]] = ContextVar(
    "noticing_settings_trying", default=None)


@contextmanager
def trying(values: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    """Inside this block, and only in this context, the rules read
    ``values`` (from ``candidate``) instead of the live set."""
    token = _trying.set(candidate(values))
    try:
        yield _trying.get() or {}
    finally:
        _trying.reset(token)


def current() -> Mapping[str, Any]:
    """The candidate inside ``trying``, else the live set."""
    tried = _trying.get()
    return tried if tried is not None else live()


def value(name: str) -> Any:
    """One value, as the rules read it: from ``current()``."""
    found = current().get(name, DEFAULTS[name])
    return found if _checked(name, found) is not None else DEFAULTS[name]


def version() -> str:
    return version_of(current())


def use_reader(reader: Callable[[], Optional[str]]) -> None:
    """Swap where the record is read from, and drop the cache (tests, and a
    process that must not reach the database)."""
    global _reader, _cached
    with _lock:
        _reader, _cached = reader, None
