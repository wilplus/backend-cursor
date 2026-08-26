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

import inspect
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

    def test_take_one_cannot_return_without_database_confirmation(self):
        from services.ideal_text_confirmation import IdealTextUnconfirmedError

        captured = {}
        with patch.dict(sys.modules, {
            "services.lab_recording": self._fake_lab_module(captured),
        }), patch(
            "services.ideal_text_confirmation."
            "build_initial_ideal_text_from_stored_artifacts",
            side_effect=IdealTextUnconfirmedError("arc-1"),
        ) as build:
            with self.assertRaises(IdealTextUnconfirmedError):
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
                    take_index=1,
                )
        build.assert_called_once()
        self.assertEqual(
            build.call_args.kwargs["source_session_id"],
            _SID,
        )

    def test_later_take_never_calls_initial_document_builder(self):
        captured = {}
        with patch.dict(sys.modules, {
            "services.lab_recording": self._fake_lab_module(captured),
        }), patch(
            "services.ideal_text_confirmation."
            "build_initial_ideal_text_from_stored_artifacts",
        ) as build:
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
        build.assert_not_called()

    def test_later_take_result_fires_only_after_the_full_worker(self):
        src = inspect.getsource(aw.run_full_analysis)
        result_at = src.index("finalize_later_take_review")
        self.assertGreater(result_at, src.index("offer_for_take"))
        self.assertLess(result_at, src.rindex("return readout_local"))
        self.assertIn("take_index > 1", src[result_at - 500:result_at + 500])
        self.assertGreater(src.index("fire_ideal_version_ready", result_at),
                           result_at)

    def test_later_take_uses_the_normal_version_card(self):
        from services.arc_notifications import fire_ideal_version_ready
        captured = {}

        class _Db:
            def insert_lounge_messages(self, uid, messages):
                captured["messages"] = messages
                return messages

            def get_arc_sessions(self, arc_id):
                return []

        self.assertTrue(fire_ideal_version_ready(
            _Db(), "user-1", "arc-1", 2))
        message = captured["messages"][0]
        self.assertEqual(message["body"], "Your ideal text is ready.")
        self.assertEqual(message["metadata"], {
            "arc_id": "arc-1",
            "variant": "ready",
            "version": 2,
            "topic": None,
        })

    def test_take_one_unconfirmed_card_has_exact_copy_and_actions(self):
        from services.arc_notifications import fire_ideal_text_unconfirmed
        captured = {}

        class _Db:
            def insert_lounge_messages(self, uid, messages):
                captured["messages"] = messages
                return messages

        self.assertTrue(fire_ideal_text_unconfirmed(
            _Db(), "user-1", "arc-1", _SID, 1))
        message = captured["messages"][0]
        self.assertEqual(message["client_id"], _SID)
        self.assertEqual(
            message["body"],
            "We processed your take, but couldn’t create your Ideal Text.")
        self.assertEqual(message["metadata"], {
            "variant": "ideal_text_unconfirmed",
            "arc_id": "arc-1",
            "take_session_id": _SID,
            "take_index": 1,
            "actions": ["retry_ideal_text", "view_take_feedback"],
        })


if __name__ == "__main__":
    unittest.main()
