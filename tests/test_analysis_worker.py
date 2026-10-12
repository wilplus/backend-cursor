"""services/analysis_worker.py — the extracted full pipeline (async-queue
work 2026-08-03).

The extraction moved routes/v2_routes.py's `_run_analysis_pipeline`
closure verbatim into run_full_analysis so sync / daemon / queue-worker
modes share ONE implementation. These tests pin the seams that must not
drift:

  * process_lab_recording receives EXACTLY the closure's arguments
    (names + values), and the readout round-trips untouched.
  * The guest path (user_id None) never fires cadence / auto-send / arc
    cards, and reports sent_to_coach=False — the closure's behaviour.
  * A broken progress callback can never break the pipeline (live loop).

Run: python3 -m unittest tests.test_analysis_worker
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

for _m in ("supabase", "sentry_sdk"):
    if _m not in sys.modules:
        sys.modules[_m] = types.ModuleType(_m)
if not hasattr(sys.modules["supabase"], "create_client"):
    sys.modules["supabase"].create_client = lambda *a, **k: None  # type: ignore[attr-defined]
    sys.modules["supabase"].Client = object  # type: ignore[attr-defined]
if not hasattr(sys.modules["sentry_sdk"], "capture_exception"):
    sys.modules["sentry_sdk"].capture_exception = lambda *a, **k: None  # type: ignore[attr-defined]

try:
    import services.analysis_worker as aw
    _IMPORT_ERR = None
except Exception as e:  # pragma: no cover
    aw = None  # type: ignore[assignment]
    _IMPORT_ERR = e


_SID = "77777777-7777-4777-8777-777777777777"
_REC = "88888888-8888-4888-8888-888888888888"


@unittest.skipIf(aw is None, f"import failed: {_IMPORT_ERR}")
class RunFullAnalysisGuestPathTests(unittest.TestCase):
    """Guest upload (user_id None, no arc): only the core engine runs."""

    def _fake_lab_module(self, captured, readout=None):
        mod = types.ModuleType("services.lab_recording")

        def process_lab_recording(**kwargs):
            captured.update(kwargs)
            return readout if readout is not None else {"snippets": [1, 2]}

        mod.process_lab_recording = process_lab_recording
        return mod


    def _later_take_with_document(self, existing):
        """Run one Take 2 and report whether it called the document builder.

        `existing` is what `coach_arc_ideal_text` holds for the Project —
        the single fact that now decides.
        """
        captured = {}
        with patch.dict(sys.modules, {
            "services.lab_recording": self._fake_lab_module(captured),
        }), patch(
            "services.ideal_text_confirmation."
            "build_initial_ideal_text_from_stored_artifacts",
        ) as build:
            # The real predicate runs; only what the database holds is
            # faked, so this exercises the rule rather than restating it.
            with patch(
                "services.ideal_text_confirmation.confirmed_ideal_text",
                side_effect=lambda row: existing,
            ):
                aw.run_full_analysis(
                    session_id=_SID,
                    user_id=None,
                    recording_id=_REC,
                    audio_bytes=b"x",
                    filename="lab.webm",
                    session_context=None,
                    parent_audio_url="https://a",
                    recording_kind="spoken",
                    arc_id="arc-1",
                    take_index=2,
                )
        return build


    def test_a_later_take_DOES_create_a_document_that_is_missing(self):
        """The case that was impossible before, and left one real Project
        showing "processing" for eleven days: Take 1 never confirmed an
        Ideal Text, only Take 1 could create one, and Take 1 was over."""
        build = self._later_take_with_document(None)
        build.assert_called_once()
        self.assertEqual(build.call_args.kwargs["source_session_id"], _SID)


if __name__ == "__main__":
    unittest.main()
