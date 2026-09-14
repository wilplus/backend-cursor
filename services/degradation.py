"""Typed degradation markers for the Ideal Text read path (audit Q-C1).

Founder decision 2026-09-14 (Q-C1, option a): every stage on the read path
either succeeds or returns a typed ``degraded`` marker the FE can show —
never a silently shorter payload. Before this module the path had fifteen
``except Exception`` blocks in one function, each turning a failure into a
partial payload plus a log line nobody reads at request time.

A ``DegradationLog`` is created once per request (or per pipeline run) and
threaded through the stages. A stage that used to be wrapped in a swallow-all
now runs through :meth:`DegradationLog.run`, which keeps the exact fallback
behaviour (the default value, the mutation done so far) and records what
degraded. A fallback taken without an exception — "span check failed, serving
none" — is recorded with :meth:`DegradationLog.note`.

The payload is ``{"degraded": [{"stage": ..., "kind": ...}]}`` and is ABSENT
when nothing degraded, so a healthy response is byte-identical to before.
``kind`` is the exception class name (or the noted reason), never the
message: messages can carry ids and provider text, and the marker is
user-visible. The message goes to the log, as it always did.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(frozen=True)
class Degradation:
    """One stage that fell back. ``stage`` is dotted and path-prefixed
    (``ideal_text.changes.praise_playback``); ``kind`` names why."""

    stage: str
    kind: str

    def as_payload(self) -> dict[str, str]:
        return {"stage": self.stage, "kind": self.kind}


class DegradationLog:
    """The typed record of every fallback one read (or run) took."""

    def __init__(self, path: str) -> None:
        self.path = str(path)
        self.items: list[Degradation] = []

    def _name(self, stage: str) -> str:
        return f"{self.path}.{stage}" if self.path else str(stage)

    def record(self, stage: str, error: BaseException) -> Degradation:
        """A stage raised and its fallback was taken."""
        item = Degradation(self._name(stage), type(error).__name__)
        self.items.append(item)
        logger.warning("%s degraded (%s): %s", item.stage, item.kind, error)
        return item

    def note(self, stage: str, kind: str) -> Degradation:
        """A stage chose its fallback without raising (a failed check)."""
        item = Degradation(self._name(stage), str(kind))
        self.items.append(item)
        logger.warning("%s degraded (%s)", item.stage, item.kind)
        return item

    def run(self, stage: str, fn: Callable[[], T],
            default: Optional[T] = None) -> Optional[T]:
        """Run ``fn``; on any exception record the stage and return
        ``default``. Exactly what a swallow-all ``except`` did, with a
        marker instead of silence."""
        try:
            return fn()
        except Exception as error:
            self.record(stage, error)
            return default

    def __len__(self) -> int:
        return len(self.items)

    def __bool__(self) -> bool:
        return bool(self.items)

    def payload(self) -> dict[str, Any]:
        """``{"degraded": [...]}``, or ``{}`` when nothing degraded."""
        if not self.items:
            return {}
        return {"degraded": [item.as_payload() for item in self.items]}
