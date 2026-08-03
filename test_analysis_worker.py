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

Run: python3 -m unittest test_analysis_worker
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

    def test_engine_gets_the_closures_exact_arguments(self):
        captured = {}
        with patch.dict(sys.modules, {
            "services.lab_recording": self._fake_lab_module(captured),
        }):
            readout, sent = aw.run_full_analysis(
                session_id=_SID,
                user_id=None,
                recording_id=_REC,
                audio_bytes=b"\x1aE\xdf\xa3webm",
                filename="lab.webm",
                session_context={"topic": "t"},
                parent_audio_url="https://media/x.webm",
                recording_kind="read",
                paired_session_id="pair-1",
            )
        self.assertEqual(captured, {
            "session_id": _SID,
            "user_id": None,
            "recording_id": _REC,
            "audio_bytes": b"\x1aE\xdf\xa3webm",
            "filename": "lab.webm",
            "session_context": {"topic": "t"},
            "parent_audio_url": "https://media/x.webm",
            "recording_kind": "read",
            "paired_session_id": "pair-1",
        })
        self.assertEqual(readout, {"snippets": [1, 2]})
        self.assertFalse(sent)

    def test_guest_never_reaches_coach_or_cadence(self):
        # If the guest path tried cadence/auto-send, these imports would
        # explode — their absence from sys.modules is the proof.
        captured = {}
        poison = {
            "services.lab_recording": self._fake_lab_module(captured),
        }
        for name in ("services.session_cadence", "services.lab_send",
                     "services.arc_notifications"):
            sys.modules.pop(name, None)
        with patch.dict(sys.modules, poison):
            _, sent = aw.run_full_analysis(
                session_id=_SID, user_id=None, recording_id=_REC,
                audio_bytes=b"x", filename="lab.webm",
                session_context=None, parent_audio_url="https://a",
            )
        self.assertFalse(sent)
        self.assertNotIn("services.session_cadence", sys.modules)
        self.assertNotIn("services.lab_send", sys.modules)

    def test_progress_callback_failure_never_breaks_pipeline(self):
        captured = {}

        def _broken_progress(stage, percent, message):
            raise RuntimeError("FE poll table missing")

        with patch.dict(sys.modules, {
            "services.lab_recording": self._fake_lab_module(captured),
        }):
            readout, _ = aw.run_full_analysis(
                session_id=_SID, user_id=None, recording_id=_REC,
                audio_bytes=b"x", filename="lab.webm",
                session_context=None, parent_audio_url="https://a",
                progress=_broken_progress,
            )
        self.assertEqual(readout, {"snippets": [1, 2]})

    def test_progress_stages_are_mechanical_labels_only(self):
        """AC-9 probe: progress surfaces plumbing words, never read/score
        vocabulary."""
        captured = {}
        seen = []
        with patch.dict(sys.modules, {
            "services.lab_recording": self._fake_lab_module(captured),
        }):
            aw.run_full_analysis(
                session_id=_SID, user_id=None, recording_id=_REC,
                audio_bytes=b"x", filename="lab.webm",
                session_context=None, parent_audio_url="https://a",
                progress=lambda s, p, m: seen.append((s, p, m)),
            )
        self.assertTrue(seen)
        banned = ("score", "verdict", "rank", "charisma", "stress")
        for stage, _, message in seen:
            blob = f"{stage} {message or ''}".lower()
            for word in banned:
                self.assertNotIn(word, blob)


if __name__ == "__main__":
    unittest.main()
