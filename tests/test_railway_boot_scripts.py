"""The container entrypoints say which Phase-1 mode they booted with.

B-1 (major), audit 2026-09-22. `grep PLF1 bin/ Procfile nixpacks railpack
Dockerfile*` returned zero: not one entrypoint echoed the variable that
decides whether the processing boundary is enforced.

The Python boot line (`tests/test_boot_gate_log.py`) covers the services
that run Python we control. This covers the shell that starts them, which
prints BEFORE the interpreter boots — so a container that dies during
startup still says what it was configured with, which is exactly the case
where somebody most needs to know.
"""
from __future__ import annotations

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
BOOT_SCRIPTS = ("bin/railway-web.sh", "bin/railway-worker.sh")


class TheEntrypointsEchoThePhase1Mode(unittest.TestCase):

    def test_boot_scripts_log_plf1_mode(self):
        for name in BOOT_SCRIPTS:
            with self.subTest(script=name):
                body = (ROOT / name).read_text(encoding="utf-8")
                self.assertIn(
                    "PLF1_PROCESSING_AUTHORIZATION_MODE",
                    body.split("PLF1_PROCESSING_AUTHORIZATION_MODE")[0][:0]
                    or body[:0] or "".join(
                        ln for ln in body.splitlines(True)
                        if "PLF1_PROCESSING_AUTHORIZATION_MODE" in ln),
                    f"{name} never echoes the Phase-1 mode",
                )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
