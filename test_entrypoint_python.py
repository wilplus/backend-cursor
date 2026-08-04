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

Run: python3 -m unittest test_entrypoint_python
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

_ENTRYPOINTS = ("bin/railway-web.sh", "bin/railway-worker.sh")


def _code(path: str) -> str:
    """Shell source minus comment lines — the comments quote the old broken
    shape while explaining it, so a naive grep would match the prose."""
    src = Path(path).read_text(encoding="utf-8")
    return "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )


class PathEditsAppendTests(unittest.TestCase):

    def test_no_path_edit_prepends(self):
        """Every `export PATH=` in both entrypoints extends the EXISTING path
        on the left — `PATH="${PATH}:..."`. A prepend puts whatever directory
        ffmpeg (or a nix profile) lives in ahead of the venv, and /usr/bin
        holding a system python3 is precisely how both services broke."""
        edit = re.compile(r'export PATH=(.*)$')
        for path in _ENTRYPOINTS:
            for line in _code(path).splitlines():
                m = edit.search(line)
                if not m:
                    continue
                value = m.group(1).strip()
                self.assertTrue(
                    value.startswith('"${PATH}:'),
                    f"{path}: PATH edit does not append — a directory is "
                    f"being placed ahead of the venv: {line.strip()}",
                )

    def test_both_entrypoints_still_edit_path(self):
        """Guards the guard: if the PATH edits are removed wholesale the
        append test above passes vacuously while ffmpeg resolution silently
        changes. Each entrypoint keeps at least one (appending) edit."""
        for path in _ENTRYPOINTS:
            self.assertIn('export PATH="${PATH}:', _code(path),
                          f"{path}: the ffmpeg PATH edit disappeared")


class WorkerInterpreterPinTests(unittest.TestCase):

    def test_worker_resolves_python_by_absolute_path(self):
        """The venv is consulted explicitly — VIRTUAL_ENV first, then the
        Railpack/Nixpacks default /app/.venv — so the interpreter choice
        never rides on PATH order at all."""
        code = _code("bin/railway-worker.sh")
        self.assertIn('"$VIRTUAL_ENV/bin/python"', code)
        self.assertIn("/app/.venv/bin/python", code)

    def test_worker_execs_the_pinned_interpreter(self):
        code = _code("bin/railway-worker.sh")
        self.assertIn('exec "$PYTHON" worker.py', code)
        self.assertNotIn("exec python3 worker.py", code,
                         "the bare exec is back — the exact outage shape")

    def test_pin_happens_before_the_path_edits(self):
        """Order is load-bearing: pinned after the appends is safe today, but
        pinning first means even a reintroduced prepend cannot reach the
        exec. Keep the strong ordering."""
        code = _code("bin/railway-worker.sh")
        pin = code.find("PYTHON=")
        first_edit = code.find('export PATH=')
        self.assertNotEqual(pin, -1)
        self.assertNotEqual(first_edit, -1)
        self.assertLess(pin, first_edit,
                        "bin/railway-worker.sh: interpreter resolved after "
                        "PATH is edited")


class ShadowingReproductionTest(unittest.TestCase):
    """The mechanism itself, demonstrated with a fake /usr/bin.

    A `python3` that fails on import stands in for the system interpreter; a
    working one stands in for the venv. The old prepend shape must resolve to
    the broken one and the shipped append shape to the venv one — so the test
    proves the invariant matters, not merely that the source says so."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.system = Path(self.tmp, "usr-bin")     # holds ffmpeg AND python3
        self.venv = Path(self.tmp, "venv-bin")
        self.system.mkdir()
        self.venv.mkdir()
        for name, body in (
            ("python3", "#!/bin/sh\necho SYSTEM\nexit 1\n"),
            ("ffmpeg", "#!/bin/sh\n"),
        ):
            f = self.system / name
            f.write_text(body)
            f.chmod(0o755)
        venv_py = self.venv / "python3"
        venv_py.write_text("#!/bin/sh\necho VENV\n")
        venv_py.chmod(0o755)

    def _run(self, script: str) -> str:
        # Real PATH stays on the END so `sh` itself resolves; the fakes lead,
        # so they are what python3/ffmpeg resolve to.
        env = dict(os.environ,
                   PATH=f"{self.venv}:{self.system}:{os.environ.get('PATH', '')}")
        return subprocess.run(
            ["sh", "-c", script], capture_output=True, text=True, env=env,
        ).stdout.strip()

    def test_prepending_the_ffmpeg_dir_shadows_the_venv(self):
        """The pre-#341 shape — proof the outage mechanism is real."""
        out = self._run(
            f'export PATH="{self.system}:$PATH"\n'
            'python3 -c anything\n'
        )
        self.assertEqual(out, "SYSTEM")

    def test_appending_keeps_the_venv_interpreter(self):
        """The shipped shape: ffmpeg still resolvable, python untouched."""
        out = self._run(
            f'export PATH="${{PATH}}:{self.system}"\n'
            'command -v ffmpeg >/dev/null || echo NO-FFMPEG\n'
            'python3 -c anything\n'
        )
        self.assertEqual(out, "VENV")


if __name__ == "__main__":
    unittest.main()
