"""CONCURRENCY IN THE ANALYSIS PIPELINE (founder 2026-08-12, group 1).

The first production timing line read::

    total=42639ms {'intake': 176, 'analysis': 21548,
                   'post_processing': 6011, 'finalizing': 14566, 'kpi': 336}

Inside `analysis`, stickiness (2.22s) ran, and only then slide_claims (1.56s)
→ slide_entailment (1.97s). The two units share no data. This runs them at the
same time and removes no AI — every call that ran before still runs.

WHAT IS WORTH TESTING is not that threads are faster. It is the property that
makes the change safe to keep: results come back in SUBMISSION order. The
values here feed `overall_score` and therefore the L2 ranking blend, so a list
that reordered itself by whichever model answered first would make two
identical takes rank differently — non-determinism sourced from network
jitter, which is close to unreproducible.

Run: python3 -m unittest test_parallel
"""
from __future__ import annotations

import logging
import threading
import time
import unittest

from services.parallel import MAX_WORKERS, run_in_parallel


class OrderTests(unittest.TestCase):
    def test_results_are_in_SUBMISSION_order_not_completion_order(self):
        # The load-bearing property. The first thunk finishes LAST on purpose:
        # an as_completed() implementation passes every other test in this file
        # and fails this one.
        def slow():
            time.sleep(0.05)
            return "first"

        def quick():
            return "second"

        self.assertEqual(run_in_parallel(slow, quick), ["first", "second"])

    def test_the_same_inputs_give_the_same_output_every_time(self):
        # Determinism is the whole point: L2 must not depend on scheduling.
        def mk(i, delay):
            def _f():
                time.sleep(delay)
                return i
            return _f

        thunks = [mk(0, 0.03), mk(1, 0.0), mk(2, 0.015)]
        for _ in range(5):
            self.assertEqual(run_in_parallel(*thunks), [0, 1, 2])


class FailureTests(unittest.TestCase):
    def test_an_exception_surfaces_to_the_caller_as_it_would_sequentially(self):
        def boom():
            raise RuntimeError("model down")

        with self.assertRaises(RuntimeError):
            run_in_parallel(boom, lambda: "fine")

    def test_a_sibling_failure_does_not_corrupt_the_other_result(self):
        # Each thunk owns its own return value; nothing is shared. The pipeline
        # relies on this — the slide-scores unit carries its own try/except and
        # must still produce its ([], []) fallback if stickiness explodes.
        seen = []

        def ok():
            seen.append("ran")
            return ["kept"]

        def boom():
            raise ValueError("nope")

        with self.assertRaises(ValueError):
            run_in_parallel(boom, ok)
        # The sibling DID run — that is the honest cost of overlapping them,
        # and it is bounded at one wasted call rather than hidden.
        self.assertEqual(seen, ["ran"])


class BoundsTests(unittest.TestCase):
    def test_a_single_thunk_does_not_pay_for_a_thread_pool(self):
        # The one-call path must stay byte-identical to life before this
        # module: no pool, no thread, same call on the same stack.
        where = {}

        def only():
            where["thread"] = threading.current_thread().name
            return 7

        self.assertEqual(run_in_parallel(only), [7])
        self.assertEqual(where["thread"], threading.current_thread().name)

    def test_nothing_to_run_is_not_an_error(self):
        self.assertEqual(run_in_parallel(), [])
        self.assertEqual(run_in_parallel(None), [])   # type: ignore[arg-type]

    def test_the_pool_is_bounded_however_many_thunks_arrive(self):
        # A 270-piece talk must never become a thread per piece. The cap is a
        # ceiling on concurrency, not on completeness: every thunk still runs.
        live = {"now": 0, "peak": 0}
        lock = threading.Lock()

        def work():
            with lock:
                live["now"] += 1
                live["peak"] = max(live["peak"], live["now"])
            time.sleep(0.01)
            with lock:
                live["now"] -= 1
            return 1

        out = run_in_parallel(*[work] * 20)
        self.assertEqual(len(out), 20)          # all of them ran
        self.assertLessEqual(live["peak"], MAX_WORKERS)


class WiringTests(unittest.TestCase):
    def test_the_two_analysis_units_are_submitted_TOGETHER(self):
        import inspect

        from services import lab_recording as lr

        src = inspect.getsource(lr.process_lab_recording)
        self.assertIn("def _unit_stickiness", src)
        self.assertIn("def _unit_slide_scores", src)
        self.assertIn("run_in_parallel(\n        _unit_stickiness, "
                      "_unit_slide_scores)", src)
        # Both results are consumed AFTER the join, never read from inside the
        # other closure — that would reintroduce the dependency the split
        # exists to remove.
        join = src.index("run_in_parallel(")
        self.assertLess(src.index("def _unit_slide_scores"), join)
        self.assertLess(join, src.index("_overall_by_i"))

    def test_the_chained_pair_stays_chained(self):
        # slide_entailment consumes slide_claims' output, so those two are NOT
        # independent and must not be pulled apart by a later "optimisation".
        import inspect

        from services import slide_alignment as sa

        src = inspect.getsource(sa)
        self.assertLess(src.index("def _llm_decompose"),
                        src.index("def _entail_batch"))
        self.assertNotIn("run_in_parallel", src)


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    unittest.main()
