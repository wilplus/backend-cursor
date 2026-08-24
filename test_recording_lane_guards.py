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
from types import SimpleNamespace
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
            project = SimpleNamespace(
                project_id="project-1", idempotency_key="upload-1",
                duplicate_take=None, principal=SimpleNamespace(id="owner-1"),
            )
            with patch("routes.v2.lab_recording.resolve_take_project",
                       return_value=project), \
                 patch("routes.v2.lab_recording."
                       "ensure_project_presentation_unchanged"), \
                 patch.object(v2.db, "v2_get_session_by_id") as m_sess, \
                 patch("services.coach_video_storage.put_coach_object_bytes") \
                    as m_put:
                out = v2.v2_lab_create_recording.__wrapped__()
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status, m_sess, m_put

    PAIR = "3f7c1b6e-6f5a-4a7e-9f2b-8c1d0e5a4b39"
    SNIP = "aaaa1111-aaaa-1111-aaaa-111111111111"

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

    def test_ideal_text_reread_is_retired_422(self):
        # Founder 2026-08-05: "read out loud" is gone. A WELL-FORMED read
        # with no target snippet is that retired lane — refused, so a stale
        # client cannot mint a phantom take (the ideal-text version is now
        # the spoken take count, so one would un-verify a real text).
        body, status, _, m_put = self._post(
            {"topic": "t", "recording_kind": "read",
             "paired_session_id": self.PAIR})
        self.assertEqual(status, 422)
        self.assertIn("retired", body["error"].lower())
        m_put.assert_not_called()

    def test_delivery_star_snippet_rerecord_still_passes(self):
        # The read lane SURVIVES for the delivery-star snippet re-record —
        # a separate live feature that shares the wire and was never in
        # scope for the retirement. It must not hit the retirement guard.
        body, status, _, _ = self._post(
            {"topic": "t", "recording_kind": "read",
             "paired_session_id": self.PAIR,
             "paired_snippet_id": self.SNIP})
        self.assertNotIn(
            "retired", ((body or {}).get("error", "") or "").lower())

    def test_spoken_without_pair_is_fine_past_the_guard(self):
        # A spoken take needs no pair — it must not hit the read guard
        # (it proceeds and fails later on its own merits).
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
class ImmutableTakeIdentityTests(unittest.TestCase):
    """A fresh Take id is minted server-side; browser session ids are inert."""

    def test_storage_always_mints_and_never_accepts_guest_session_id(self):
        from services.lab_recording_persistence import store_recording_audio
        source = inspect.getsource(store_recording_audio)
        self.assertIn("session_id = str(uuid.uuid4())", source)
        self.assertNotIn("requested_session_id", source)
        self.assertNotIn("guest_session_id", source)


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
        from routes.v2 import lab_recording
        src = inspect.getsource(lab_recording._analysis_response)
        self.assertIn("recording_kind=upload.recording_kind", src)

    def test_read_still_links_and_tags_without_counting(self):
        # The read lane survives for the DELIVERY-STAR snippet re-record:
        # it inherits the parent's arc + take number and is tagged — it
        # just never assembles. (The ideal-text re-read that used to share
        # this lane is refused at the guard; see UnpairedReadTests.)
        from services.create_take import attach_recording_to_project
        src = inspect.getsource(attach_recording_to_project)
        self.assertIn("bind_variant(", src)
        self.assertIn('recording_kind == "read"', src)

    def test_the_ideal_text_reread_is_pinned_out_at_the_guard(self):
        # The retirement pinned at the source: a read with no target
        # snippet is refused before any storage.
        from services.lab_recording_intake import parse_recording_lane
        src = inspect.getsource(parse_recording_lane)
        self.assertIn('paired_snippet_id', src)
        self.assertIn('retired', src)


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


class _PoolAuditDB:
    """Fake db for the ranking-pool exclusion audit: an arc with one
    SPOKEN take and one paired READ, both fully transcribed and labeled
    — the adversarial setup where a read WOULD win if it ever entered."""

    def __init__(self):
        self.sessions = [
            {"id": "t1", "take_index": 1, "recording_kind": "spoken",
             "created_at": "2026-08-01T10:00:00Z",
             "intake_context": {
                 "topic": "T",
                 "slides": [{"title": "S1", "body": ""}],
                 "slide_advances": [{"index": 0, "t_ms": 0}],
             }},
            # The read is NEWER and coach-labeled challenge — if any lane
            # ever admits it, it would both seed the skeleton and win the
            # pick. It must do neither.
            {"id": "r1", "take_index": 1, "recording_kind": "read",
             "paired_session_id": "t1",
             "created_at": "2026-08-02T10:00:00Z",
             "intake_context": {
                 "topic": "T",
                 "slides": [{"title": "S1", "body": ""}],
                 "slide_advances": [{"index": 0, "t_ms": 0}],
             }},
        ]
        self.snips = {
            "t1": [{"id": "sp1", "start_offset_ms": 0, "duration_ms": 900,
                    "transcript": "the spoken words",
                    "storage_path": "s3://sp1",
                    "metrics": {"overall_score": 0.2}}],
            "r1": [{"id": "rd1", "start_offset_ms": 0, "duration_ms": 900,
                    "transcript": "the script read back",
                    "storage_path": "s3://rd1",
                    "metrics": {"overall_score": 0.99,
                                "recording_kind": "read"}}],
        }
        self.blocks_written = []

    def get_arc_sessions(self, arc_id):
        return list(self.sessions)

    def get_snippets_by_session(self, sid):
        return list(self.snips.get(sid, []))

    def get_best_presentation_edits(self, arc_id):
        return {}

    def get_coach_best_presentation_edits(self, arc_id):
        return {}

    def v2_get_session_by_id(self, sid):
        for s in self.sessions:
            if s["id"] == sid:
                return s
        return None

    def upsert_ideal_text_block(self, arc_id, block_key, fields):
        self.blocks_written.append((block_key, fields))
        return True

    def list_ideal_text_blocks(self, arc_id):
        return []


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class RankingPoolExclusionAuditTests(unittest.TestCase):
    """F1-CORE guard (handoff §4, 2026-08-03): `recording_kind: "read"`
    sessions are STRICTLY excluded from the best-text-per-slide pool —
    selection AND challenger generation. A read's transcript is the
    script read back; inside the pool it would dominate text-quality
    signals while being the behavior the product trains users out of.
    The audit found reads already excluded at every lane (the
    spoken_arc_sessions load filter + the worker's spoken-only gate);
    these tests pin that so a refactor can't quietly let them back in."""

    def test_read_snippets_never_enter_selection(self):
        # End-to-end: even a newer, higher-scoring, coach-challenge-
        # labeled read never surfaces in the composed slides.
        from services import best_presentation as bp
        _orig = bp._render_composition
        bp._render_composition = lambda picks, slides: None
        try:
            out = bp.build_best_presentation("a1", database=_PoolAuditDB(),
                                             coach_view=True)
        finally:
            bp._render_composition = _orig
        for s in (out.get("slides") or []):
            self.assertNotEqual(s.get("session_id"), "r1")
            self.assertNotEqual(s.get("snippet_id"), "rd1")
            self.assertNotIn("script read back", s.get("text") or "")
            self.assertNotIn("script read back", s.get("verbatim") or "")

    def test_master_skeleton_never_seeds_from_a_read(self):
        # The skeleton seeds from the LATEST spoken take with pieces —
        # a newer read must not be that seed.
        from services.master_document import build_skeleton
        db = _PoolAuditDB()
        rows = build_skeleton("a1", db)
        self.assertTrue(rows, "skeleton should build from the spoken take")
        for row in rows:
            self.assertEqual(row["incumbent_take_session_id"], "t1")
            for p in row["incumbent_pieces"]:
                self.assertNotEqual(p["snippet_id"], "rd1")

if __name__ == "__main__":
    unittest.main()
