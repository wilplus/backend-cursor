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

NOTHING HERE PRINTS A SECRET. Names and values only; the canary principal is
reported as set or unset, never by id.
"""
from __future__ import annotations

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENTRYPOINTS = ("app.py", "worker.py")

# The flags that decide what is served, what is recorded and who is bound.
GATES = (
    "PLF1_PROCESSING_AUTHORIZATION_MODE",
    "TAKE_FEEDBACK_POLICY_V3_MODE",
    "DATA_FOUNDATION_CANARY_ENABLED",
    "MLC3_SERVICE_ENABLED",
    "MLC3_COACH_INLINE_AUTHORING_ENABLED",
    "CONFIDENT_MOMENT_BUNDLE_V1_ENABLED",
    "MLC2_CONFIDENCE_MONITORING_ENABLED",
    "MLC2_CONFIDENCE_CANARY_PRINCIPAL_ID",
    "REASONABLE_CONFIDENCE_ENABLED",
)


class TheSummaryItselfIsHonest(unittest.TestCase):

    def test_it_names_every_gate(self):
        from services.gate_flags import gate_summary

        line = gate_summary()
        for gate in GATES:
            with self.subTest(gate=gate):
                self.assertIn(gate, line)

    def test_it_reports_the_value_the_process_actually_read(self):
        """Not the default, and not the panel — the live value."""
        import os
        from unittest.mock import patch

        from services.gate_flags import gate_summary

        with patch.dict(os.environ,
                        {"PLF1_PROCESSING_AUTHORIZATION_MODE": "enforce"}):
            self.assertIn(
                "PLF1_PROCESSING_AUTHORIZATION_MODE=enforce", gate_summary())
        with patch.dict(os.environ,
                        {"PLF1_PROCESSING_AUTHORIZATION_MODE": "off"}):
            self.assertIn(
                "PLF1_PROCESSING_AUTHORIZATION_MODE=off", gate_summary())

    def test_it_never_prints_the_canary_principal(self):
        """AC-9 is not the fence here; a log is not a user surface. But a
        principal id in a deploy log is a subject identifier in a place
        nobody is treating as subject data."""
        import os
        from unittest.mock import patch

        from services.gate_flags import gate_summary

        principal = "9f8e7d6c-5b4a-4938-8271-605f4e3d2c1b"
        with patch.dict(os.environ,
                        {"MLC2_CONFIDENCE_CANARY_PRINCIPAL_ID": principal}):
            line = gate_summary()
        self.assertNotIn(principal, line)
        self.assertIn("MLC2_CONFIDENCE_CANARY_PRINCIPAL_ID=set", line)

    def test_it_is_one_line(self):
        """One line, so one log filter finds it on either service."""
        from services.gate_flags import gate_summary

        self.assertNotIn("\n", gate_summary())


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

    def test_they_say_it_in_the_same_words(self):
        """One search across both services, or it is two searches and
        somebody runs only the easy one."""
        import re

        phrasings = set()
        for name in ENTRYPOINTS:
            body = (ROOT / name).read_text(encoding="utf-8")
            phrasings.update(re.findall(r'"([^"\n]*gate flags[^"\n]*)"', body))
        self.assertEqual(len(phrasings), 2, phrasings)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
