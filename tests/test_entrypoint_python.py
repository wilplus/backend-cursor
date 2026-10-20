"""
GUARD      The Railway worker starts on the app's venv Python, never the system
           one: bin/railway-worker.sh execs "$PYTHON" worker.py (an absolute
           interpreter resolved before exec), not a bare python3.
CATCHES    A well-meaning edit back to `exec python3 worker.py`, which lets a
           PATH change pick /usr/bin/python3 without the app's dependencies.
IF REMOVED The 2026-08-04 outage can return silently: the RQ worker booted on
           the system python ("No module named sentry_sdk").
PROVES     test_worker_execs_the_pinned_interpreter
             reads the shell SOURCE TEXT (comment lines stripped); it does
             not run the script
WHY        #341, 2026-08-04 outage.
"""
from __future__ import annotations

import unittest
from pathlib import Path


def _code(path: str) -> str:
    """Shell source minus comment lines — the comments quote the old broken
    shape while explaining it, so a naive grep would match the prose."""
    src = Path(path).read_text(encoding="utf-8")
    return "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )


class WorkerInterpreterPinTests(unittest.TestCase):

    def test_worker_execs_the_pinned_interpreter(self):
        code = _code("bin/railway-worker.sh")
        self.assertIn('exec "$PYTHON" worker.py', code)
        self.assertNotIn("exec python3 worker.py", code,
                         "the bare exec is back — the exact outage shape")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
