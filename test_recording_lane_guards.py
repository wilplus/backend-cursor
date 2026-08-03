"""willab — recording-lane guards (founder bugs 2026-07-20).

"Please do not count re-read as a separate take — only a spoken take is a
real take" + "after the re-read, recording the spoken version analyses the
re-read". Three guards, pinned here:

  A1 an UNPAIRED read is rejected 422 before any storage (it used to fall
     through as SPOKEN: taking a take number, assembling, minting a
     version);
  A2 a SPENT session id (one that already owns a recording / a lane /
     analysis) is never reused — a fresh session is minted, so a new
     spoken take can never be folded into the previous re-read;
  A3 assembly/version/bubble run for SPOKEN takes ONLY — the SD-mode
     condition `_rec_kind == "spoken" or _single_deliverable_enabled()`
     let a re-read run the whole pipeline (regenerate suggestions,
     reassemble, bump the version, fire the ready bubble).

Run: python3 -m unittest test_recording_lane_guards
"""
from __future__ import annotations

import inspect
import io
import unittest
from unittest.mock import patch

try:
    from flask import Flask
    from routes import v2_routes as v2
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    v2 = None
    _IMPORT_ERROR = e

SESS = "11111111-1111-4111-8111-111111111111"
PAIR = "22222222-2222-4222-8222-222222222222"


def _file(name="take.webm", ctype="audio/webm", body=b"x" * 32):
    from werkzeug.datastructures import FileStorage
    return FileStorage(stream=io.BytesIO(body), filename=name,
                       content_type=ctype)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class UnpairedReadTests(unittest.TestCase):
    """A1 — a read without its spoken take is refused, and refused EARLY
    (before storage/processing), so nothing about it can be persisted."""

    def setUp(self):
        self.app = Flask(__name__)

    def _post(self, form):
        data = {"audio_file": _file()}
        data.update(form)
        with self.app.test_request_context(
                method="POST", data=data,
                content_type="multipart/form-data"):
            # Any storage/DB touch would mean the guard ran too late.
            with patch.object(v2.db, "v2_get_session_by_id") as m_sess, \
                 patch("services.coach_video_storage.put_coach_object_bytes") \
                    as m_put:
                out = v2.v2_lab_create_recording.__wrapped__()
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status, m_sess, m_put

    def test_read_without_pair_422_before_any_storage(self):
        body, status, m_sess, m_put = self._post(
            {"topic": "my talk", "recording_kind": "read"})
        self.assertEqual(status, 422)
        self.assertEqual(body["code"], "INVALID_INPUT")
        self.assertIn("paired_session_id", body["error"])
        m_put.assert_not_called()     # nothing stored
        m_sess.assert_not_called()    # nothing even looked up

    def test_read_with_malformed_pair_422(self):
        _, status, _, _ = self._post({"topic": "t", "recording_kind": "read",
                                      "paired_session_id": "not-a-uuid"})
        self.assertEqual(status, 422)

    def test_spoken_without_pair_is_fine_past_the_guard(self):
        # A spoken take needs no pair — it must not hit the read guard
        # (it proceeds and fails later on its own merits, never 422 with
        # the paired_session_id message).
        body, status, _, _ = self._post({"topic": "t"})
        self.assertNotEqual(
            (body or {}).get("error", ""),
            "A re-read needs the spoken take it belongs to "
            "(paired_session_id).")

    def test_kind_case_and_padding_still_guarded(self):
        _, status, _, _ = self._post({"topic": "t",
                                      "recording_kind": "  READ  "})
        self.assertEqual(status, 422)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class SpentSessionGuardTests(unittest.TestCase):
    """A2 — the id in the form is only reused when the session is FRESH."""

    SRC = None

    @classmethod
    def setUpClass(cls):
        cls.SRC = inspect.getsource(v2.v2_lab_create_recording)

    def _spent_markers(self):
        """The row fields that mark a session as already owning a
        recording — each must be consulted by the guard."""
        return ("recording_1_id", "recording_kind", "paired_session_id",
                "analysis_state", "results_published_at")

    def test_guard_consults_every_spent_marker(self):
        for field in self._spent_markers():
            self.assertIn(f'_prior.get("{field}")', self.SRC,
                          f"spent-session guard ignores {field}")

    def test_guard_fails_closed_on_lookup_error(self):
        # An unknown state must mint fresh, never risk folding a take into
        # a spent session.
        self.assertIn("_spent = True", self.SRC)

    def test_fresh_id_is_still_honoured(self):
        self.assertIn("guest_session_id = _sid_in or str(uuid.uuid4())",
                      self.SRC)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ReadNeverAssemblesTests(unittest.TestCase):
    """A3 — the source-level pin: assembly is gated on SPOKEN alone. The
    old `or _single_deliverable_enabled()` made every re-read reassemble
    (new version + ready bubble) in the mode that is LIVE in prod."""

    def test_assembly_gate_is_spoken_only(self):
        # The pipeline body (and this gate with it) moved VERBATIM to
        # services/analysis_worker.py::run_full_analysis (async-queue
        # extraction 2026-08-03) so sync/daemon/queue modes share one
        # implementation. The pin follows the code: the gate lives there
        # on SPOKEN alone, un-OR'd — and the handler still carries the
        # lane through the seam.
        from services import analysis_worker
        wsrc = inspect.getsource(analysis_worker.run_full_analysis)
        self.assertIn('if arc_id and recording_kind == "spoken":', wsrc)
        self.assertNotIn("_single_deliverable_enabled", wsrc)
        src = inspect.getsource(v2.v2_lab_create_recording)
        self.assertIn("recording_kind=_rec_kind", src)

    def test_read_still_links_and_tags_without_counting(self):
        # The read lane itself is untouched: it inherits the parent's arc
        # + take number and is tagged — it just never assembles.
        src = inspect.getsource(v2.v2_lab_create_recording)
        self.assertIn('db.set_session_recording_kind(', src)
        self.assertIn('arc_take_count = take_index', src)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class SpokenOnlyIsArcTruthTests(unittest.TestCase):
    """The founder's rule end-to-end: every arc-level count/selection
    surface already filters to spoken takes — pinned so a refactor can't
    quietly let reads back in."""

    def test_spoken_arc_sessions_drops_reads_and_paired_rows(self):
        from services.best_presentation import spoken_arc_sessions
        rows = [
            {"id": "t1", "take_index": 1},
            {"id": "r1", "take_index": 1, "recording_kind": "read",
             "paired_session_id": "t1"},
            {"id": "r2", "take_index": 1, "paired_session_id": "t1"},
            {"id": "t2", "take_index": 2, "recording_kind": "spoken"},
        ]
        self.assertEqual([s["id"] for s in spoken_arc_sessions(rows)],
                         ["t1", "t2"])


if __name__ == "__main__":
    unittest.main()
