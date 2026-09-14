"""Contracts for dependency-ready processing waves."""
from __future__ import annotations

import threading
import time
import unittest

from services.pipeline_stage_execution import ReadyStage, run_ready_stages


class _Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, str | None]] = []

    def record(self, stage, status, *, error=None):
        self.events.append((
            stage,
            status,
            type(error).__name__ if error is not None else None,
        ))


class ReadyStageExecutionTests(unittest.TestCase):
    def test_independent_stages_overlap_and_results_keep_declared_names(self):
        barrier = threading.Barrier(2, timeout=1)

        def _work(value):
            barrier.wait()
            return value

        result = run_ready_stages(
            ReadyStage("first", lambda: _work(1)),
            ReadyStage("second", lambda: _work(2)),
        )

        self.assertEqual(result, {"first": 1, "second": 2})

    def test_required_failures_surface_in_declaration_order(self):
        def _fail(message, delay):
            time.sleep(delay)
            raise RuntimeError(message)

        with self.assertRaisesRegex(RuntimeError, "declared first"):
            run_ready_stages(
                ReadyStage("first", lambda: _fail("declared first", 0.02)),
                ReadyStage("second", lambda: _fail("finished first", 0.0)),
            )

    def test_optional_failure_is_none_and_canonical_outcomes_are_recorded(self):
        recorder = _Recorder()

        def _optional_failure():
            raise ValueError("not required")

        result = run_ready_stages(
            ReadyStage(
                "optional",
                _optional_failure,
                canonical_stage="candidate_generation",
                required=False,
            ),
            ReadyStage(
                "required",
                lambda: "ok",
                canonical_stage="feature_extraction",
            ),
            stage_recorder=recorder,
        )

        self.assertEqual(result, {"optional": None, "required": "ok"})
        self.assertEqual(recorder.events, [
            ("candidate_generation", "running", None),
            ("feature_extraction", "running", None),
            ("candidate_generation", "failed", "ValueError"),
            ("feature_extraction", "succeeded", None),
        ])

    def test_ambiguous_stage_names_fail_before_any_work_runs(self):
        called = []
        with self.assertRaisesRegex(ValueError, "unique"):
            run_ready_stages(
                ReadyStage("same", lambda: called.append(1)),
                ReadyStage("same", lambda: called.append(2)),
            )
        self.assertEqual(called, [])

    def test_duplicate_canonical_stage_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "canonical stage"):
            run_ready_stages(
                ReadyStage(
                    "one", lambda: 1, canonical_stage="transcription"
                ),
                ReadyStage(
                    "two", lambda: 2, canonical_stage="transcription"
                ),
            )


if __name__ == "__main__":
    unittest.main()
