"""PIPELINE PHASE TIMINGS (founder 2026-08-11).

"The developer is refusing to guess why the loading times are slow… they want
to put tracking timers on the AI pipeline to see exactly which step takes the
longest, rather than blindly trying to fix it. My Recommendation: Hard agree.
Always measure before you cut."

The wait after a take is long enough to have been raised twice, and nothing
in the pipeline has ever recorded where the time goes. That is the same
position the intervention serve was in earlier the same evening, where an
hour of database queries answered a question one log line now answers.

The property worth testing is not the arithmetic — it is that a phase is
recorded WHEN IT CLOSES rather than in one summary at the end, because a run
that crashes is exactly the run whose timings you want and a summary written
after the last statement is the one you never get.

Run: python3 -m unittest test_pipeline_timing
"""
from __future__ import annotations

import logging
import unittest

from services.analysis_worker import _Timeline


class TimelineTests(unittest.TestCase):
    def test_each_phase_is_recorded_as_it_CLOSES(self):
        tl = _Timeline("s1")
        self.assertEqual(tl.phases, {})
        tl.mark("analysis")
        # The phase that just ENDED is the one now on the record — the new
        # one has not happened yet and has no duration to claim.
        self.assertIn("intake", tl.phases)
        self.assertNotIn("analysis", tl.phases)
        tl.mark("post_processing")
        self.assertIn("analysis", tl.phases)

    def test_a_crashed_run_still_leaves_the_phases_it_finished(self):
        # Nothing calls done() here — the simulation of a pipeline that threw
        # halfway. Everything completed before the throw is still recorded.
        tl = _Timeline("s1")
        tl.mark("analysis")
        tl.mark("post_processing")
        self.assertEqual(sorted(tl.phases), ["analysis", "intake"])

    def test_done_closes_the_LAST_phase(self):
        # "done" is a sentinel that closes `finalizing`; it is not itself a
        # phase and must never appear as one — a zero-length row in the
        # timings would read as a step that ran and took no time.
        tl = _Timeline("s1")
        tl.mark("analysis")
        tl.mark("finalizing")
        tl.done()
        self.assertEqual(sorted(tl.phases),
                         ["analysis", "finalizing", "intake"])
        self.assertNotIn("done", tl.phases)

    def test_durations_are_whole_milliseconds_never_a_float(self):
        # They are read off a log line by a human at 1am, not parsed.
        tl = _Timeline("s1")
        tl.mark("analysis")
        for v in tl.phases.values():
            self.assertIsInstance(v, int)
            self.assertGreaterEqual(v, 0)

    def test_every_phase_reaches_the_LOG_not_only_the_dict(self):
        # The dict is in-process and dies with the worker; the log is the
        # thing anyone can actually read afterwards.
        with self.assertLogs("services.analysis_worker", level="INFO") as cm:
            tl = _Timeline("sess-42")
            tl.mark("analysis")
            tl.done()
        blob = "\n".join(cm.output)
        self.assertIn("pipeline phase session=sess-42", blob)
        self.assertIn("intake=", blob)
        self.assertIn("pipeline timing session=sess-42 total=", blob)

    def test_a_missing_session_id_does_not_raise(self):
        # Best-effort like every other observability path here: instrumenta-
        # tion that can break the live loop is worse than none.
        for bad in (None, "", 7):
            tl = _Timeline(bad)   # type: ignore[arg-type]
            tl.mark("analysis")
            tl.done()


class WiringTests(unittest.TestCase):
    def test_the_worker_marks_every_stage_it_emits(self):
        # The progress `_emit`s are the pipeline's own idea of where its
        # boundaries are. A stage that reports progress but records no time
        # is a stage nobody can find when it turns out to be the slow one.
        import inspect

        from services import analysis_worker as aw

        src = inspect.getsource(aw.run_full_analysis)
        for stage in ("analysis", "post_processing", "finalizing"):
            self.assertIn(f'_emit(progress, "{stage}"', src)
            self.assertIn(f'tl.mark("{stage}")', src)
        self.assertIn("tl.done()", src)


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    unittest.main()
