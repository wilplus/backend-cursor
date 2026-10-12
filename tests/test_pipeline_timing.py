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

Run: python3 -m unittest tests.test_pipeline_timing
"""
from __future__ import annotations

import logging
import unittest



class WiringTests(unittest.TestCase):
    def test_the_worker_marks_every_stage_it_emits(self):
        # The progress `_emit`s are the pipeline's own idea of where its
        # boundaries are. A stage that reports progress but records no time
        # is a stage nobody can find when it turns out to be the slow one.
        import inspect

        from services import analysis_worker as aw

        src = inspect.getsource(aw.run_full_analysis)
        for stage in (
            "transcribing", "ideal_text", "feedback_moments",
            "speaking_anchors",
        ):
            self.assertIn(f'_emit(progress, "{stage}"', src)
            self.assertIn(f'tl.mark("{stage}")', src)
        # The totals line is closed by the CONTEXT MANAGER, not by a trailing
        # statement — a trailing `tl.done()` is skipped by the very crash whose
        # timings you wanted, so its absence here is the point.
        self.assertIn("with _Timeline(session_id) as tl:", src)
        self.assertNotIn("\n    tl.done()", src)


class RootLoggingTests(unittest.TestCase):
    """The timers existed and could still not be found (founder 2026-08-12).

    `logger.info` in this process propagates to the ROOT logger, and under
    gunicorn root has no handler — records fall through to
    logging.lastResort, which is fixed at WARNING. So every INFO line in the
    web service was discarded, timers included. The worker was fine, which is
    why it went unnoticed: PIPELINE_QUEUE_ENABLED decided whether the logs
    existed.
    """

    def test_configure_logging_gives_the_root_logger_a_handler(self):
        import logging as _logging

        from services.logging_setup import configure_logging

        root = _logging.getLogger()
        saved = list(root.handlers)
        try:
            root.handlers.clear()
            configure_logging()
            self.assertTrue(root.handlers, "root logger still has no handler")
            self.assertLessEqual(root.level, _logging.INFO)
        finally:
            root.handlers[:] = saved

    def test_it_never_stomps_handlers_someone_else_installed(self):
        # basicConfig semantics, kept on purpose: pytest's capture plugin and
        # a future --log-config both own root legitimately. Losing the logs a
        # second time, by clobbering, is harder to find than the first time.
        import logging as _logging

        from services.logging_setup import configure_logging

        root = _logging.getLogger()
        saved = list(root.handlers)
        try:
            mine = _logging.NullHandler()
            root.handlers[:] = [mine]
            configure_logging()
            self.assertEqual(root.handlers, [mine])
        finally:
            root.handlers[:] = saved

    def test_both_entrypoints_configure_it_before_anything_logs(self):
        # app.py is the one that was broken; worker.py must keep using the
        # same function so a run's timing lines look identical in either
        # Railway service.
        import re

        for path in ("app.py", "worker.py"):
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
            self.assertIn("configure_logging()", src, path)
            call = src.index("configure_logging()\n")
            head = src[:call]
            # Nothing that emits a boot log may run first — the boot checks
            # are the first thing anyone reads in a Railway log.
            for boot in re.findall(r"^\w[\w.]*\(\)$", head, re.M):
                self.assertNotIn("check", boot, f"{path}: {boot} logs first")
                self.assertNotIn("enforce", boot, f"{path}: {boot} logs first")


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    unittest.main()
