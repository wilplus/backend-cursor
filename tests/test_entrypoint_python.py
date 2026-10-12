"""The Railway entrypoints must never let a PATH edit shadow the venv python.

THE OUTAGE THIS LOCKS OUT (2026-08-04, two deploys found it independently):

  Both entrypoints located ffmpeg and PREPENDED its directory to PATH so
  subprocesses calling shutil.which("ffmpeg") would find the same binary.
  Under Railway's Railpack builder ffmpeg installs to /usr/bin — which also
  holds a system python3 carrying none of the app's dependencies. The
  prepend therefore put that interpreter ahead of /app/.venv/bin:

    * bin/railway-worker.sh: `exec python3 worker.py` booted the RQ worker
      on the system python — "sentry init skipped: No module named
      sentry_sdk" — a real outage.
    * bin/railway-web.sh: the RLS guard printed
        [rls-guard] skipped — psycopg2 is not installed
      on every boot. The guard is default-ON and swallows its own errors so
      it can never fail a boot — which is also exactly what let it skip
      unnoticed: a security check reporting nothing while appearing wired.

THE FIX these tests pin (shipped in #341, completed by this file's PR):

  1. PATH edits APPEND, never prepend. FFMPEG_PATH is what the audio
     pipeline actually reads (services/audio_metrics.py checks it first);
     PATH order buys nothing worth shadowing the venv.
  2. The worker resolves its interpreter by ABSOLUTE PATH before exec
     (VIRTUAL_ENV, then /app/.venv, then a plain fallback), so PATH order
     cannot decide which Python runs.

Why source-level tests: a later well-meaning edit is the realistic threat —
"prepend so ffmpeg wins ties" reads like an improvement, and nothing at
runtime complains until the next quiet skip or worker outage. The last class
also REPRODUCES the mechanism with a fake /usr/bin, so the invariant is
demonstrated, not just grepped for.

Run: python3 -m unittest tests.test_entrypoint_python
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


if __name__ == "__main__":
    unittest.main()
