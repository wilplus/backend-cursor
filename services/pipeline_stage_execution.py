"""Dependency-wave execution for the recording pipeline.

The pipeline is not a generic workflow engine.  Its dependencies stay visible
at the call site, where a completed prerequisite opens one small *ready wave*
of independent work.  This module supplies the invariants that every such wave
needs:

* bounded execution through :mod:`services.parallel`;
* results and required failures resolved in declaration order;
* unique stage identities, so two outputs cannot be joined ambiguously;
* canonical stage provenance recorded outside worker threads;
* explicit optionality, with optional failures logged rather than promoted.

A task submitted here must read shared immutable input and return its own
value.  Product/database mutations do not belong in the same wave unless their
storage boundary explicitly guarantees concurrent writes.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import Any, Callable, Optional


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReadyStage:
    """One independently runnable stage whose prerequisites already exist."""

    name: str
    run: Callable[[], Any]
    canonical_stage: Optional[str] = None
    required: bool = True


@dataclass(frozen=True)
class _StageOutcome:
    value: Any = None
    error: Optional[Exception] = None
    duration_ms: int = 0


def _validate(stages: tuple[ReadyStage, ...]) -> None:
    names = [stage.name for stage in stages]
    if any(not name for name in names) or len(names) != len(set(names)):
        raise ValueError("ready-stage names must be non-empty and unique")
    canonical = [
        stage.canonical_stage for stage in stages if stage.canonical_stage
    ]
    if len(canonical) != len(set(canonical)):
        raise ValueError(
            "one ready wave cannot own the same canonical stage twice"
        )


def run_ready_stages(
    *stages: ReadyStage,
    stage_recorder: Optional[Any] = None,
    log: logging.Logger = logger,
) -> dict[str, Any]:
    """Run one dependency-ready wave and return values keyed by stage name.

    Every callable is allowed to finish before a required failure is raised.
    The failure that surfaces is nevertheless the first required failure in
    declaration order, matching the deterministic collection contract of the
    underlying bounded executor.
    """
    declared = tuple(stages)
    _validate(declared)
    if not declared:
        return {}

    if stage_recorder is not None:
        for stage in declared:
            if stage.canonical_stage:
                stage_recorder.record(stage.canonical_stage, "running")

    def _capture(stage: ReadyStage) -> _StageOutcome:
        started = time.monotonic()
        try:
            value = stage.run()
        except Exception as error:
            return _StageOutcome(
                error=error,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        return _StageOutcome(
            value=value,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    from services.parallel import run_in_parallel

    outcomes = run_in_parallel(*(
        lambda stage=stage: _capture(stage) for stage in declared
    ))

    for stage, outcome in zip(declared, outcomes):
        log.info(
            "pipeline ready stage=%s duration=%dms ok=%s",
            stage.name,
            outcome.duration_ms,
            outcome.error is None,
        )

    if stage_recorder is not None:
        for stage, outcome in zip(declared, outcomes):
            if not stage.canonical_stage:
                continue
            if outcome.error is None:
                stage_recorder.record(stage.canonical_stage, "succeeded")
            else:
                stage_recorder.record(
                    stage.canonical_stage,
                    "failed",
                    error=outcome.error,
                )

    for stage, outcome in zip(declared, outcomes):
        if outcome.error is not None and stage.required:
            raise outcome.error

    values: dict[str, Any] = {}
    for stage, outcome in zip(declared, outcomes):
        if outcome.error is not None:
            log.warning(
                "optional ready stage failed stage=%s error=%s",
                stage.name,
                outcome.error,
            )
            values[stage.name] = None
        else:
            values[stage.name] = outcome.value
    return values
