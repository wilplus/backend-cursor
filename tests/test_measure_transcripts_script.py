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
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

from services import recording_transcription as rt
from services.processing_authorization import ProcessingAuthorizationError

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

    def test_example_folder_has_the_documented_layout(self):
        folder = os.path.join(self.golden, "example-01")
        self.assertEqual(
            sorted(os.listdir(folder)),
            ["audio.wav", "item.json", "slide-01.txt", "slide-02.txt",
             "stub_transcription.json"])
        self.assertGreater(os.path.getsize(os.path.join(folder, "audio.wav")), 1000)

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

    def test_without_a_pipeline_timeline_the_truth_is_used_and_no_offset_claimed(self):
        meta_path = os.path.join(self.golden, "example-01", "item.json")
        with open(meta_path, encoding="utf-8") as fh:
            meta = json.load(fh)
        meta.pop("pipeline_slide_advances")
        meta.pop("pipeline_slide_clock_offset_ms")
        with open(meta_path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh)
        self.assertEqual(mt.main([self.golden, "--stub", "--out", self.out]), 0)
        with open(self.out, encoding="utf-8") as fh:
            (item,) = json.load(fh)["items"]
        self.assertEqual(item["timeline_source"], "truth")
        self.assertIsNone(item["offset"])
        # On the true boundary (800 ms) "Today" at 840 ms is on the right slide.
        self.assertEqual(item["slide_assignment"]["wrong_slide"], 0)

    def test_label_mismatch_is_a_refusal(self):
        meta_path = os.path.join(self.golden, "example-01", "item.json")
        with open(meta_path, encoding="utf-8") as fh:
            meta = json.load(fh)
        meta["true_slide_changes_s"] = [0.5, 0.9]      # two changes, two slides
        with open(meta_path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh)
        self.assertEqual(mt.main([self.golden, "--stub", "--out", self.out]), 3)
        self.assertFalse(os.path.exists(self.out))

    def test_stub_report_is_not_written_to_the_measure_folder_by_default_in_tests(self):
        # The default report path is docs/audit/measure/<date>.json; the tests
        # always pass --out so a stubbed run never leaves a fake baseline.
        self.assertTrue(mt.REPORT_DIR.endswith(os.path.join("docs", "audit", "measure")))


class ProviderRefusalTests(unittest.TestCase):
    """S-3."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.golden = os.path.join(self.tmp.name, "golden")
        mt.write_example(self.golden)
        self.items = mt.load_golden(self.golden)

    def tearDown(self):
        self.tmp.cleanup()

    def test_enforced_gate_needs_a_take_id_before_any_call(self):
        service = MagicMock()
        service.enforced = True
        with patch("services.processing_authorization.ProcessingAuthorizationService",
                   return_value=service):
            with self.assertRaises(mt.MeasureRefusal) as ctx:
                mt.provider_transcriber(self.items)
        self.assertIn("take_id", str(ctx.exception))
        self.assertIn("example-01", str(ctx.exception))

    def test_no_provider_configured_is_a_refusal(self):
        service = MagicMock()
        service.enforced = False
        openai_stub = types.ModuleType("services.openai_service")
        openai_stub.OpenAIService = MagicMock(return_value=MagicMock(client=None))  # type: ignore[attr-defined]
        with patch("services.processing_authorization.ProcessingAuthorizationService",
                   return_value=service), patch.dict(
                sys.modules, {"services.openai_service": openai_stub}):
            with self.assertRaises(mt.MeasureRefusal) as ctx:
                mt.provider_transcriber(self.items)
        self.assertIn("not configured", str(ctx.exception))

    def test_main_reports_a_refusal_as_exit_3(self):
        service = MagicMock()
        service.enforced = True
        out = os.path.join(self.tmp.name, "r.json")
        with patch("services.processing_authorization.ProcessingAuthorizationService",
                   return_value=service):
            self.assertEqual(mt.main([self.golden, "--out", out]), 3)
        self.assertFalse(os.path.exists(out))


class RecordingProviderAdapterTests(unittest.TestCase):
    """S-4."""

    def test_gate_off_carries_the_inactive_marker(self):
        authorization = MagicMock()
        authorization.enforced = False
        database = MagicMock()
        adapter = rt.recording_provider_adapter(
            database, authorization, session_id="s1", recording_id="r1", user_id="u1")
        self.assertEqual(adapter.coordinates.acquisition_principal_id, "phase1-gate-inactive")
        self.assertEqual((adapter.coordinates.take_id, adapter.coordinates.recording_id), ("s1", "r1"))
        self.assertIs(adapter.authorization, authorization)
        database.v2_get_session_by_id.assert_not_called()

    def test_gate_on_resolves_the_owner(self):
        authorization = MagicMock()
        authorization.enforced = True
        authorization.resolve_acquisition_principal.return_value = "principal-9"
        database = MagicMock()
        database.v2_get_session_by_id.return_value = {"owner_principal_id": "owner-1"}
        adapter = rt.recording_provider_adapter(
            database, authorization, session_id="s1", recording_id="r1", user_id="u1")
        self.assertEqual(adapter.coordinates.acquisition_principal_id, "principal-9")
        authorization.resolve_acquisition_principal.assert_called_once_with(
            "owner-1", user_id="u1", recording_id="r1")

    def test_gate_on_unresolved_owner_refuses(self):
        authorization = MagicMock()
        authorization.enforced = True
        authorization.resolve_acquisition_principal.return_value = ""
        database = MagicMock()
        database.v2_get_session_by_id.return_value = {}
        with self.assertRaises(ProcessingAuthorizationError) as ctx:
            rt.recording_provider_adapter(
                database, authorization, session_id="s1", recording_id=None, user_id=None)
        self.assertEqual(ctx.exception.code, "PROCESSING_PRINCIPAL_UNRESOLVED")


if __name__ == "__main__":
    unittest.main()
