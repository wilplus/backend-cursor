"""Every gate flag says its value at boot, on every service that reads it.

J1-4 (minor) and B-1 (major), audit 2026-09-22.

CONFIG-FIRST says to verify a per-service variable from that service's BOOT
LOG rather than the Railway panel, because the panel shows what somebody
typed and the log shows what the process read. J1-4 is that no boot line
printed any gate flag at all, so the rule could not be followed for the
flags that decide whether the Phase-1 boundary is enforced, whether the V3
service serves, or whether the confidence canary is bound.

B-1 is the consequence: the deployed value of
`PLF1_PROCESSING_AUTHORIZATION_MODE` is not derivable from outside for any
service except the web one, which exposes it on a route. The worker and the
crons have no observable surface at all.

This is the same lesson `EveryServiceReportsItsOwnConfig` learned on
2026-09-22 for the stored bookmark set, one flag family over. The habit is
now a test both times.

NOTHING HERE PRINTS A SECRET. Names and values only; a flag whose value
identifies a person is reported as set or unset, never by id.
"""
from __future__ import annotations

import os
import pathlib
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parent.parent


class TheSummaryItselfIsHonest(unittest.TestCase):


    def test_it_reports_the_value_the_process_actually_read(self):
        """Not the default, and not the panel — the live value."""

        from services.gate_flags import gate_summary

        with patch.dict(os.environ,
                        {"PLF1_PROCESSING_AUTHORIZATION_MODE": "enforce"}):
            self.assertIn(
                "PLF1_PROCESSING_AUTHORIZATION_MODE=enforce", gate_summary())
        with patch.dict(os.environ,
                        {"PLF1_PROCESSING_AUTHORIZATION_MODE": "off"}):
            self.assertIn(
                "PLF1_PROCESSING_AUTHORIZATION_MODE=off", gate_summary())


class EveryServiceReportsItsGates(unittest.TestCase):
    """The J1-4 half, in the shape #614 established for CONFIG-FIRST.

    The worker is the service whose setting is invisible from outside, and
    it is also the one that WRITES the lineage. It needs this line more than
    the web service, not less.
    """

    def _reports(self, entrypoint: str) -> bool:
        body = (ROOT / entrypoint).read_text(encoding="utf-8")
        return "gate_summary" in body

    def test_app_boot_emits_gate_summary_line(self):
        self.assertTrue(self._reports("app.py"),
                        "app.py never logs the gate summary")

    def test_worker_boot_emits_gate_summary_line(self):
        self.assertTrue(self._reports("worker.py"),
                        "worker.py never logs the gate summary")

if __name__ == "__main__":  # pragma: no cover
    unittest.main()
