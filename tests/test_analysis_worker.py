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


@unittest.skipIf(aw is None, f"import failed: {_IMPORT_ERR}")
class ReadyBeforeTrailingWorkTests(unittest.TestCase):
    """The speaker hears "ready" before the work they never waited on
    (founder 2026-10-14, the wait): the shadow logs, the coach email and
    the Say-It-Stronger cards run after the flip, inside the job, and a
    failure among them never reaches the speaker."""

    def _run(self, *, shadow_raises=False):
        from services.degradation import DegradationLog
        order = []

        def _module(name, **attrs):
            mod = types.ModuleType(name)
            for key, value in attrs.items():
                setattr(mod, key, value)
            return mod

        def _verbal(db, sid):
            order.append("verbal_cue_shadow")
            if shadow_raises:
                raise RuntimeError("shadow log down")
            return 1

        log = DegradationLog("take_analysis")
        with patch.dict(sys.modules, {
            "services.lab_recording": _module(
                "services.lab_recording",
                process_lab_recording=lambda **kw: {"snippets": [1]}),
            "services.verbal_cues": _module(
                "services.verbal_cues", record_take=_verbal),
            "services.acoustic_cues": _module(
                "services.acoustic_cues",
                record_take=lambda db, sid: order.append(
                    "acoustic_cue_shadow")),
            "services.detector_candidates": _module(
                "services.detector_candidates",
                register_candidates=lambda: None),
            "services.detector_rollout": _module(
                "services.detector_rollout",
                record_take=lambda db, sid: order.append(
                    "detector_rollout_shadow")),
            "services.say_it_stronger": _module(
                "services.say_it_stronger",
                wait_for_cards=lambda sid: order.append("cards") or True),
        }):
            readout, sent = aw.run_full_analysis(
                session_id=_SID,
                user_id=None,
                recording_id=_REC,
                audio_bytes=b"x",
                filename="lab.webm",
                session_context=None,
                parent_audio_url="https://a",
                degradation=log,
                on_ready=lambda: order.append("ready"),
            )
        return order, readout, log

    def test_ready_comes_first_and_the_cards_are_waited_for(self):
        order, readout, _ = self._run()
        self.assertEqual(readout, {"snippets": [1]})
        self.assertEqual(order[0], "ready")
        self.assertEqual(set(order[1:-1]), {
            "verbal_cue_shadow", "acoustic_cue_shadow",
            "detector_rollout_shadow"})
        self.assertEqual(order[-1], "cards")

    def test_trailing_work_failing_never_reaches_the_speaker(self):
        order, readout, log = self._run(shadow_raises=True)
        self.assertEqual(readout, {"snippets": [1]})
        self.assertEqual(order[0], "ready")
        self.assertEqual(order[-1], "cards")
        self.assertIn({"stage": "take_analysis.verbal_cue_shadow",
                       "kind": "RuntimeError"},
                      log.payload()["degraded"])


if __name__ == "__main__":
    unittest.main()
