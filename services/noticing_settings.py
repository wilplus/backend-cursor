"""What the speaking coach notices, as settings (N647 item 8, step 3).

The thresholds that decide what the feedback walk notices, and how it ranks
the moments it picks, lived as Python constants. They are read here
instead, from one record: ``runtime_config`` key ``noticing_settings``, its
``value`` (the text column) holding a JSON object
``{"version": "...", "values": {name: value}}``. Other keys in that object
(a history, a note) are ignored. ``metadata`` is not read.

TODAY'S VALUES ARE THE DEFAULTS, and nothing changes while the record is
missing, unreadable, or holds the defaults. A value that is missing, of the
wrong type or outside its bounds falls back to its constant on its own; the
rest of the record still counts. ``tests/test_noticing_settings.py`` pins
every default to the constant in its own module, name by name.

THREE KINDS OF VALUE (``SPECS``):
  dial    a host may move it, a notch at a time, under one "thing noticed"
          (``THINGS``): one meaning, more or fewer catches.
  rank    it orders the moments, never adds or removes a catch. Only the
          founder may change it, by hand; ``step`` never touches it.
  pinned  listed so the inventory is whole, but held at its constant: a copy
          lives elsewhere (the frontend's pace scale, a SQL function), or it
          is structure, or it has its own calibration rule. The record cannot
          move it, and the code still reads the constant.

THE VERSION. ``version()`` is ``DEFAULT_VERSION`` while every value is the
default; otherwise ``noticing-`` and a hash of the values that differ, so a
log written under a moved threshold can never be compared with one written
under today's. The verbal cues stamp it into their detector version and the
policy frame into its practice policy, only when it is not the default.

THE SEAM FOR A SILENT TRY (step 4, a neighbouring session). All pure; nothing
here writes:
  ``setting_for(thing)``            the live values of a thing's dials
  ``step(settings, thing, "more")`` a candidate one notch over, within bounds
  ``candidate(overrides)``          the live set with the overrides; an
                                    unknown name or a bad value raises
  ``with_changes(settings, changes)``
  ``with trying(values):``          the same rules, reading the candidate, in
                                    this context only (a ``contextvars``
                                    value: other threads and requests keep
                                    the live set); the rules take no new
                                    argument. Log what they say; never serve
                                    it.

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
from typing import Any, Callable, Iterator, Mapping, NamedTuple, Optional

logger = logging.getLogger(__name__)

KEY = "noticing_settings"
DEFAULT_VERSION = "noticing-v0-defaults"
CACHE_SECONDS = 60.0

DIAL, RANK, PINNED = "dial", "rank", "pinned"
MORE, FEWER = "more", "fewer"

_LOW = ("delivery_signal_low",)
_TWO = ("delivery_signal_mid_low", "delivery_signal_low")
_THREE = ("delivery_signal_neutral", "delivery_signal_mid_low", "delivery_signal_low")


class Spec(NamedTuple):
    default: Any
    kind: str
    #: Numbers: (low, high), both included. A tuple of bands: the allowed sets.
    bounds: Any = None
    #: Dials: the notches, in the order that CATCHES MORE.
    notches: tuple = ()


SPECS: dict[str, Spec] = {
    # ── dials ──
    "tempo_stretch.MIN_OUTSIDE": Spec(0.25, DIAL, (0.15, 0.35), (0.35, 0.3, 0.25, 0.2, 0.15)),
    "verbal_cues.FILLER_MIN_COUNT": Spec(2, DIAL, (1, 4), (4, 3, 2, 1)),
    "verbal_cues.FILLER_MIN_PER_100_WORDS": Spec(5.0, DIAL, (3.0, 7.0), (7.0, 6.0, 5.0, 4.0, 3.0)),
    "verbal_cues.HEDGE_MIN_COUNT": Spec(2, DIAL, (1, 4), (4, 3, 2, 1)),
    "verbal_cues.RESTART_MIN_COUNT": Spec(2, DIAL, (1, 4), (4, 3, 2, 1)),
    "rewrite_gate.REPEATS_PER_100": Spec(2.0, DIAL, (1.0, 3.0), (3.0, 2.5, 2.0, 1.5, 1.0)),
    "rewrite_gate.MIN_REPEATS": Spec(2, DIAL, (1, 4), (4, 3, 2, 1)),
    "rewrite_gate.WORD_SIGNAL_FLOOR": Spec(0.7, DIAL, (0.5, 0.9), (0.5, 0.6, 0.7, 0.8, 0.9)),
    "take_feedback_policy_v3.PRACTICE_BANDS": Spec(_TWO, DIAL, (_LOW, _TWO, _THREE), (_LOW, _TWO, _THREE)),
    "moment_pick.FLOOR": Spec(0.6, DIAL, (0.5, 0.7), (0.5, 0.55, 0.6, 0.65, 0.7)),
    "take_context.MATCH": Spec(0.6, DIAL, (0.4, 0.8), (0.8, 0.7, 0.6, 0.5, 0.4)),
    # ── ranking: orders the moments, never a dial ──
    "moment_pick.VERBAL_LIFT": Spec(0.5, RANK, (0.0, 1.0)),
    "moment_pick.RELEVANCE_LIFT": Spec(0.25, RANK, (0.0, 1.0)),
    "moment_pick.TOUCHED_GIVE": Spec(0.2, RANK, (0.0, 0.5)),
    "moment_pick.PART_GIVE": Spec(0.15, RANK, (0.0, 0.5)),
    "moment_pick.STRETCH_WORDS": Spec(8, RANK, (5, 20)),
    "moment_pick.NEUTRAL_SOUND": Spec(0.5, RANK, (0.0, 1.0)),
    "v4_picker.SURENESS_CUTOFF": Spec(0.3, RANK, (0.0, 1.0)),
    # ── pinned: held at the constant ──
    "tempo_stretch.GREEN_LOW": Spec(0.275, PINNED),       # the frontend's pace scale has a copy
    "tempo_stretch.GREEN_HIGH": Spec(0.725, PINNED),      # the same
    "willfidence.CEILING_PER_100": Spec(10, PINNED),      # record_v4_willfidence_reads_v1 has a copy
    "rewrite_gate.SLIDE_FIT_FLOOR": Spec(0.5, PINNED),    # the read is only 0, 0.5 or 1
    "v4_reached_bar.BAR": Spec(0.6, PINNED),              # its own calibration rule
    "moment_pick.MIN_WORDS": Spec(5, PINNED),             # also the policy's block split: structure
    "take_feedback_policy_v3.CONFIDENT_BANDS": Spec(      # shared with confident_voice_practice
        ("delivery_signal_high", "delivery_signal_mid_high"), PINNED),
}

#: The things a host can name, and the dials under each.
THINGS: dict[str, tuple[str, ...]] = {
    "A rushed moment": ("tempo_stretch.MIN_OUTSIDE",),
    "Filler words": ("verbal_cues.FILLER_MIN_COUNT", "verbal_cues.FILLER_MIN_PER_100_WORDS"),
    "Hedging": ("verbal_cues.HEDGE_MIN_COUNT",),
    "Restarts": ("verbal_cues.RESTART_MIN_COUNT", "rewrite_gate.REPEATS_PER_100",
                 "rewrite_gate.MIN_REPEATS"),
    "Words that need a rewrite": ("rewrite_gate.WORD_SIGNAL_FLOOR",),
    "A voice that sounds unsure": ("take_feedback_policy_v3.PRACTICE_BANDS",),
    "A moment that needs a fix": ("moment_pick.FLOOR",),
    "Saying the key line": ("take_context.MATCH",),
}

DEFAULTS: dict[str, Any] = {name: spec.default for name, spec in SPECS.items()}
DIALABLE = frozenset(name for name, spec in SPECS.items() if spec.kind == DIAL)


def _checked(name: str, value: Any) -> Any:
    """The value in its proper type when the record may hold it, else None."""
    spec = SPECS.get(name)
    if spec is None:
        return None
    if spec.kind == PINNED:
        return spec.default if value == spec.default else None
    if isinstance(spec.default, tuple):
        if isinstance(value, (list, tuple)) and tuple(value) in spec.bounds:
            return tuple(value)
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    kind = type(spec.default)
    if kind is int and float(value) != int(value):
        return None
    low, high = spec.bounds
    if not low <= value <= high:
        return None
    return kind(value)


def defaults() -> dict[str, Any]:
    return dict(DEFAULTS)


def _lenient(base: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    """``base`` with each change it may hold; the rest left out (the stored
    record, where a bad value must fall back, never fail)."""
    values = {name: base.get(name, default) for name, default in DEFAULTS.items()}
    for name, value in (changes or {}).items():
        checked = _checked(str(name), value)
        if checked is not None:
            values[str(name)] = checked
    return values


def with_changes(settings: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    """``settings`` with ``changes``. Pure; stores nothing. ValueError on an
    unknown name, a pinned value moved, or a value outside its bounds: a
    typo never yields a candidate that quietly equals what it started from."""
    for name, value in (changes or {}).items():
        if str(name) not in SPECS:
            raise ValueError(f"noticing_settings: unknown name {name!r}")
        if _checked(str(name), value) is None:
            raise ValueError(f"noticing_settings: {name} may not hold {value!r}")
    return _lenient(settings, changes)


def candidate(overrides: Optional[Mapping[str, Any]] = None, *,
              base: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """The LIVE set (or ``base``, e.g. ``defaults()``) with ``overrides``, so
    every value not overridden keeps what is in force. Pure; raises as
    ``with_changes`` does."""
    return with_changes(live() if base is None else base, overrides or {})


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


def setting_for(thing: str, settings: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """The dials of one thing noticed, as ``settings`` holds them (live when
    None). KeyError for a thing that is not in ``THINGS``."""
    values = settings if settings is not None else live()
    return {name: values.get(name, DEFAULTS[name]) for name in THINGS[thing]}


def step(settings: Mapping[str, Any], thing: str, direction: str) -> dict[str, Any]:
    """A candidate: every dial of ``thing`` one notch toward catching more
    (``MORE``) or fewer (``FEWER``). A dial already at its last notch, or
    between notches, stays. Pure; only dials move."""
    if direction not in (MORE, FEWER):
        raise ValueError(f"direction must be {MORE!r} or {FEWER!r}")
    changes: dict[str, Any] = {}
    for name in THINGS[thing]:
        notches = SPECS[name].notches
        now = settings.get(name, DEFAULTS[name])
        if now not in notches:
            continue
        at = notches.index(now) + (1 if direction == MORE else -1)
        if 0 <= at < len(notches):
            changes[name] = notches[at]
    return with_changes(settings, changes)


def _read_store() -> Optional[str]:
    from services.db import db
    return db.get_runtime_config(KEY)


_reader: Callable[[], Optional[str]] = _read_store
_lock = threading.Lock()
_cached: Optional[dict[str, Any]] = None
_cached_at = 0.0
_refreshing = False
#: Bumped by ``use_reader``, so a read begun under the old reader never
#: lands in the cache of the new one.
_generation = 0


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
    values = _lenient(DEFAULTS, stored)
    for name, value in stored.items():
        if name in DEFAULTS and values[name] != _checked(name, value):
            logger.warning("noticing_settings: %s may not hold that value; using its default", name)
    return values


def live() -> dict[str, Any]:
    """The values in force: the record, at most a minute old, else the
    defaults. Never raises.

    The database read happens OUTSIDE the lock, so a slow read never holds
    up a caller: while one thread refreshes, every other caller gets the
    cached set at once (a minute old at most, plus the read). Only the very
    first callers, before any set is cached, read for themselves."""
    global _cached, _cached_at, _refreshing
    with _lock:
        now = time.monotonic()
        if _cached is not None and (now - _cached_at < CACHE_SECONDS or _refreshing):
            return _cached
        _refreshing = True
        reader, generation = _reader, _generation
    try:
        try:
            raw = reader()
        except Exception as exc:  # the record is optional; the constants stand
            logger.warning("noticing_settings: read failed (%s); using the defaults",
                           exc, exc_info=True)
            raw = None
        values = _parse(raw)
        with _lock:
            if generation == _generation:  # a reader swapped meanwhile wins
                _cached, _cached_at = values, time.monotonic()
            return values
    finally:
        with _lock:
            if generation == _generation:
                _refreshing = False


_trying: ContextVar[Optional[Mapping[str, Any]]] = ContextVar(
    "noticing_settings_trying", default=None)


@contextmanager
def trying(values: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    """Inside this block, and only in this context, the rules read
    ``values`` instead of the live set. ``values`` may be partial: what it
    leaves out keeps its live value (``candidate``); it raises as
    ``candidate`` does."""
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
    global _reader, _cached, _refreshing, _generation
    with _lock:
        _reader, _cached, _refreshing = reader, None, False
        _generation += 1
