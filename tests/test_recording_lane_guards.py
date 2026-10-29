"""
STORY    As a speaker, I want only my spoken takes to count as takes, and a
         new spoken take never folded into an earlier re-read, so that my
         take numbers and Ideal Text stay right.
OUTCOME
  O1  A "read" upload without its spoken take (no paired_session_id), or an
      ideal-text re-read (no paired_snippet_id, lane retired), gets 422 and
      nothing is stored.
  O2  Every accepted upload gets a fresh Take id; a session id the browser
      sends (a spent one) is never reused for the new recording.
  O3  A delivery-star snippet re-record (read + pair + snippet) is accepted,
      binds to its spoken take WITHOUT taking a new take number, and reaches
      analysis as a "read"; a spoken upload does take a take number.
  O4  Only a spoken take builds the Ideal Text; a read never does.
PROVES   O1 -> test_unpaired_or_retired_read_is_refused_before_storage
         O2 -> test_new_take_never_reuses_a_session_id_from_the_browser
         O3 -> test_snippet_rerecord_binds_to_its_take_without_a_take_number
         O4 -> test_only_a_spoken_take_builds_the_ideal_text
WHY      Founder bugs 2026-07-20: a re-read counted as a take and a spoken
         take was analysed as the re-read.
"""
from __future__ import annotations

import io
import sys
import types
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

try:
    from flask import Flask

    from routes.v2 import lab_recording as route
    from services.lab_analysis_dispatch import PendingAnalysis
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    _IMPORT_ERROR = e

SPOKEN = "22222222-2222-4222-8222-222222222222"
SNIPPET = "aaaa1111-aaaa-4111-8aaa-111111111111"


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class RecordingLaneRouteTests(unittest.TestCase):
    """POST /lab/recordings with only the outside world faked: the database,
    object storage, the audio gate, project lookup and the analysis queue.
    Lane parsing, Take-id minting, persistence and project binding are real.
    """

    def _post(self, form):
        from werkzeug.datastructures import FileStorage
        data = {"audio_file": FileStorage(
            stream=io.BytesIO(b"x" * 32), filename="take.webm",
            content_type="audio/webm")}
        data.update(form)
        project = SimpleNamespace(
            project_id="project-1", idempotency_key="upload-1",
            duplicate_take=None, principal=SimpleNamespace(id="owner-1"),
        )
        auth = MagicMock(enforced=False)
        auth.resolve_acquisition_principal.return_value = "owner-1"
        fakes = SimpleNamespace(db=MagicMock())
        with ExitStack() as stack, Flask(__name__).test_request_context(
                method="POST", data=data,
                content_type="multipart/form-data"):
            def fake(target, **kw):
                return stack.enter_context(patch(target, **kw))
            fake("routes.v2.lab_recording.db", new=fakes.db)
            fake("routes.v2.lab_recording.resolve_take_project",
                 return_value=project)
            fake("routes.v2.lab_recording.ProcessingAuthorizationService",
                 return_value=auth)
            fake("services.processing_authorization."
                 "ProcessingAuthorizationService", return_value=auth)
            fake("routes.v2.lab_recording._is_data_foundation_canary_owner",
                 return_value=False)
            fake("routes.v2.lab_recording.require_analyzable_recording",
                 return_value={"ok": True, "duration_sec": 30})
            fakes.put = fake("services.lab_audio_storage.put_lab_audio_bytes",
                             return_value="lab-bucket")
            fake("services.lab_audio_storage.storage_provider",
                 return_value="r2")
            fakes.reserve = fake("services.create_take.reserve_take",
                                 return_value=3)
            fakes.bind = fake("services.project_repository.ProjectRepository."
                              "bind_variant", return_value=2)
            fakes.dispatch = fake(
                "routes.v2.lab_recording.dispatch_recording_analysis",
                return_value=PendingAnalysis({"state": "processing"}))
            out = route.v2_lab_create_recording.__wrapped__()
            resp, status = out if isinstance(out, tuple) else (out, 200)
            return resp.get_json(), status, fakes

    def test_unpaired_or_retired_read_is_refused_before_storage(self):
        for form in (
            {"recording_kind": "read"},                         # no pair
            {"recording_kind": "read", "paired_session_id": "nope"},
            {"recording_kind": "read", "paired_snippet_id": SNIPPET},
            {"recording_kind": "read", "paired_session_id": SPOKEN},  # retired
        ):
            with self.subTest(form=form):
                body, status, fakes = self._post({"topic": "t", **form})
                self.assertEqual(status, 422)
                self.assertEqual(body["code"], "INVALID_INPUT")
                fakes.put.assert_not_called()
                fakes.db.takes.v2_create_recording_session.assert_not_called()
                fakes.reserve.assert_not_called()
                fakes.dispatch.assert_not_called()

    def test_new_take_never_reuses_a_session_id_from_the_browser(self):
        body, status, fakes = self._post(
            {"topic": "t", "session_id": SPOKEN, "recording_id": SPOKEN})
        self.assertEqual(status, 202)
        created = fakes.db.takes.v2_create_recording_session.call_args.args[0]
        self.assertNotEqual(created, SPOKEN)
        self.assertNotIn(SPOKEN, fakes.put.call_args.args[0])  # storage key
        inputs = fakes.dispatch.call_args.args[0]
        self.assertEqual(inputs.session_id, created)
        self.assertEqual(inputs.recording_kind, "spoken")
        self.assertEqual(inputs.take_index, 3)       # a real take number
        fakes.reserve.assert_called_once()
        fakes.bind.assert_not_called()
        # And a second upload mints a different id again.
        _, _, again = self._post({"topic": "t", "session_id": created})
        self.assertNotEqual(
            again.db.takes.v2_create_recording_session.call_args.args[0],
            created)

    def test_snippet_rerecord_binds_to_its_take_without_a_take_number(self):
        body, status, fakes = self._post(
            {"topic": "t", "recording_kind": "read",
             "paired_session_id": SPOKEN, "paired_snippet_id": SNIPPET})
        self.assertEqual(status, 202)
        fakes.put.assert_called_once()
        fakes.reserve.assert_not_called()
        self.assertEqual(fakes.bind.call_args.args[-1], SPOKEN)
        inputs = fakes.dispatch.call_args.args[0]
        self.assertEqual(inputs.recording_kind, "read")
        self.assertEqual(inputs.paired_session_id, SPOKEN)
        self.assertEqual(inputs.take_index, 2)       # the spoken take's number
        context = fakes.db.takes.set_session_intake_context.call_args.args[1]
        self.assertEqual(context["paired_snippet_id"], SNIPPET)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class SpokenOnlyAssemblyTests(unittest.TestCase):

    def _builds_ideal_text(self, recording_kind):
        import services.analysis_worker as aw
        lab = types.ModuleType("services.lab_recording")
        lab.process_lab_recording = lambda **kw: {"snippets": [1]}
        fake_db = MagicMock()
        fake_db.get_snippets_by_session.return_value = []
        with patch.dict(sys.modules, {"services.lab_recording": lab}), \
             patch("services.db.db", fake_db), \
             patch("services.analysis_worker.db", fake_db), \
             patch("services.ideal_text_confirmation."
                   "build_initial_ideal_text_from_stored_artifacts") as build:
            aw.run_full_analysis(
                session_id=SPOKEN, user_id=None, recording_id=SNIPPET,
                audio_bytes=b"x", filename="lab.webm", session_context=None,
                parent_audio_url="https://a", recording_kind=recording_kind,
                paired_session_id=SPOKEN if recording_kind == "read" else None,
                arc_id="project-1", take_index=1,
            )
        return build.called

    def test_only_a_spoken_take_builds_the_ideal_text(self):
        self.assertTrue(self._builds_ideal_text("spoken"))
        self.assertFalse(self._builds_ideal_text("read"))


if __name__ == "__main__":
    unittest.main()
