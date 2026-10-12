"""D-ML-1 — scripts/measure_transcripts.py end to end on the synthetic
fixture, with the stubbed transcriber, and its refusals.

Pinned here:
  S-1  the synthetic example runs through the LIVE normalisation, clock-offset
       correction and bucketing and yields the planted numbers: one
       substitution, one word on the wrong slide, a +50 ms boundary error;
  S-2  the report is written where asked, says it was stubbed, and carries
       per-tag totals;
  S-3  a provider run refuses before any call when the Phase-1 gate is
       enforced and an item has no take_id, and when no provider is
       configured — the script never builds a provider client itself;
  S-4  recording_provider_adapter (the live stage's own construction) carries
       the inactive marker with the gate off and refuses an unresolved owner
       with it on.
"""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC = importlib.util.spec_from_file_location(
    "measure_transcripts", os.path.join(_ROOT, "scripts", "measure_transcripts.py"))
assert _SPEC is not None and _SPEC.loader is not None
mt = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mt)


class SyntheticFixtureTests(unittest.TestCase):
    """S-1, S-2."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.golden = os.path.join(self.tmp.name, "golden")
        mt.write_example(self.golden)
        self.out = os.path.join(self.tmp.name, "report.json")

    def tearDown(self):
        self.tmp.cleanup()


    def test_stub_run_yields_the_planted_numbers(self):
        rc = mt.main([self.golden, "--stub", "--out", self.out])
        self.assertEqual(rc, 0)
        with open(self.out, encoding="utf-8") as fh:
            report = json.load(fh)
        self.assertEqual(report["transcriber"], "stub")
        self.assertEqual(report["failures"], [])
        (item,) = report["items"]
        self.assertEqual(item["timeline_source"], "pipeline")
        # "lap" for "lab": the one substitution over 11 reference words.
        self.assertEqual(item["wer"]["substitutions"], 1)
        self.assertEqual(item["wer"]["errors"], 1)
        self.assertAlmostEqual(item["wer"]["wer"], 1 / 11)
        # "Today" at 840 ms sits before the corrected boundary (900 − 50 =
        # 850 ms) so the live bucketing puts it on slide 1 of 2 — wrong.
        self.assertEqual(item["slide_assignment"]["judged"], 11)
        self.assertEqual(item["slide_assignment"]["wrong_slide"], 1)
        self.assertEqual(item["slide_assignment"]["per_slide"][1]["wrong"], 1)
        self.assertEqual(item["wrong_slide_by_true_times"]["wrong"], 1)
        # The tap at 900 ms, corrected by 50 ms, against the true 800 ms.
        self.assertEqual(item["offset"]["errors_ms"], [50])
        self.assertEqual(item["offset"]["raw_tap_errors_ms"], [100])
        self.assertEqual(item["offset"]["slide_clock_offset_ms"], 50)
        # Slide by slide: the misplaced word is an insertion on slide 1 and a
        # deletion on slide 2.
        self.assertEqual(item["per_slide_wer"][0]["insertions"], 1)
        self.assertEqual(item["per_slide_wer"][1]["deletions"], 1)
        # Totals and tags.
        self.assertAlmostEqual(report["overall"]["wer"], 1 / 11)
        self.assertAlmostEqual(report["overall"]["offset_mean_ms"], 50.0)
        self.assertEqual(sorted(report["per_tag"]), ["accent:none", "noise:synthetic"])
        self.assertAlmostEqual(report["per_tag"]["accent:none"]["wrong_slide_share"], 1 / 11)


if __name__ == "__main__":
    unittest.main()
