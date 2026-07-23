"""willab — audio-only annotation mode (Stage 4 / T4, founder 2026-07-23).

The coach uploads audio → snippets → the existing coach labeling UI,
with NO ideal-text assembly, to bank annotations toward the 1,000 goal.

Pinned here:
  * reuses the shipped cutter (process_lab_recording) — no new chunker;
  * NO assembly runs on this path (maybe_assemble / process_new_take are
    never called);
  * the session enters the SAME coach queue (source='audit_upload' →
    send_lab_recording_to_coach), tagged annotation_mode so the FE
    labels it;
  * audio only — video refused (AUDIO_ONLY), same gate as the student
    upload.

Run: python3 -m unittest test_annotation_mode
"""
from __future__ import annotations

import io
import unittest
from unittest.mock import patch

try:
    from flask import Flask, request
    from routes import v2_routes as v2
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    v2 = None
    _IMPORT_ERROR = e


def _file(name="clip.webm", ctype="audio/webm", body=b"x" * 4096):
    from werkzeug.datastructures import FileStorage
    return FileStorage(stream=io.BytesIO(body), filename=name,
                       content_type=ctype)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class AnnotationUploadTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def _post(self, *, file=None, form=None, gate_ok=True, snippets=3):
        data = {"audio_file": file if file is not None else _file()}
        if form:
            data.update(form)
        calls = {"assembled": False, "process": None, "sent": None,
                 "intake": None}

        def _proc(**kw):
            calls["process"] = kw
            return {"snippets": [{"id": f"s{i}"} for i in range(snippets)]}

        with self.app.test_request_context(
                method="POST", data=data,
                content_type="multipart/form-data"):
            request.user_id = "coach-1"
            with patch("services.min_content_gate.evaluate_min_content_bytes",
                       return_value={"ok": gate_ok, "reason": "no_speech"}), \
                 patch("services.coach_video_storage.put_coach_object_bytes",
                       return_value=None), \
                 patch("services.coach_video_storage.coach_media_public_url",
                       return_value="https://cdn/x.webm"), \
                 patch.object(v2.db, "v2_get_session_by_id",
                              return_value=None), \
                 patch.object(v2.db, "v2_create_guest_session",
                              return_value={"id": "x"}), \
                 patch.object(v2.db, "set_session_user_id",
                              return_value=True), \
                 patch.object(v2.db, "set_session_source",
                              return_value=True), \
                 patch.object(v2.db, "set_session_intake_context",
                              side_effect=lambda sid, ctx: calls.update(
                                  intake=ctx) or True), \
                 patch("services.lab_recording.process_lab_recording",
                       side_effect=_proc), \
                 patch("services.lab_send.send_lab_recording_to_coach",
                       side_effect=lambda sid, uid: calls.update(
                           sent=(sid, uid)) or {"ok": True}), \
                 patch("services.ideal_text_block.maybe_assemble_ideal_text",
                       side_effect=AssertionError("assembly must not run")), \
                 patch("services.master_document.process_new_take",
                       side_effect=AssertionError("assembly must not run")):
                out = v2.v2_coach_annotation_upload.__wrapped__()
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status, calls

    def test_audio_becomes_labelable_snippets_no_assembly(self):
        body, status, calls = self._post(
            form={"label": "Keynote rehearsal"}, snippets=4)
        self.assertEqual(status, 201)
        self.assertEqual(body["n_snippets"], 4)
        self.assertTrue(body["annotation_mode"])
        # the shipped cutter ran; no assembly (its patches would have
        # raised) — the request reaching 201 is the proof
        self.assertIsNotNone(calls["process"])
        # session marked annotation-mode + queued
        self.assertTrue(calls["intake"]["annotation_mode"])
        self.assertEqual(calls["intake"]["topic"], "Keynote rehearsal")
        # queued to the coach under the uploader's id
        self.assertEqual(calls["sent"][1], "coach-1")

    def test_no_label_defaults_topic(self):
        _, status, calls = self._post()
        self.assertEqual(status, 201)
        self.assertEqual(calls["intake"]["topic"], "Annotation")

    def test_video_is_refused(self):
        body, status, _ = self._post(
            file=_file("talk.mp4", "video/mp4"))
        self.assertEqual(status, 415)
        self.assertEqual(body["code"], "AUDIO_ONLY")

    def test_silent_file_rejected_before_processing(self):
        body, status, calls = self._post(gate_ok=False)
        self.assertEqual(status, 422)
        self.assertEqual(body["code"], "RECORDING_REJECTED")
        self.assertIsNone(calls["process"])   # never chopped
        self.assertIsNone(calls["sent"])      # never queued

    def test_missing_audio_400(self):
        with self.app.test_request_context(
                method="POST", data={}, content_type="multipart/form-data"):
            request.user_id = "coach-1"
            out = v2.v2_coach_annotation_upload.__wrapped__()
            resp, status = out if isinstance(out, tuple) else (out, 200)
        self.assertEqual(status, 400)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class QueueLabelTests(unittest.TestCase):
    """The annotation session rides the SAME queue, tagged so the FE can
    distinguish it from a student take."""

    def test_queue_row_carries_annotation_mode(self):
        app = Flask(__name__)
        rows = [
            {"id": "a", "user_id": "coach-1",
             "intake_context": {"topic": "Annotation",
                                "annotation_mode": True}},
            {"id": "b", "user_id": "u2",
             "intake_context": {"topic": "A student take"}},
        ]
        with app.test_request_context():
            request.user_id = "coach-1"
            with patch.object(v2.db, "list_review_queue", return_value=rows), \
                 patch.object(v2, "_coach_state_map", return_value={}), \
                 patch.object(v2, "_coach_session_state",
                              return_value="to_review"), \
                 patch.object(v2, "_coach_pseudonym", return_value="Falcon"), \
                 patch.object(v2.db, "get_snippets_by_session",
                              return_value=[{"id": "s"}]):
                out = v2.v2_coach_queue.__wrapped__()
                resp, status = out if isinstance(out, tuple) else (out, 200)
        by_id = {r["session_id"]: r for r in resp.get_json()}
        self.assertTrue(by_id["a"]["annotation_mode"])
        self.assertFalse(by_id["b"]["annotation_mode"])


if __name__ == "__main__":
    unittest.main()
