"""Playback serving across the app (founder 2026-10-08: "make sure the
playbacks work all across the app").

* the coach Take video is written to the bucket the reads resolve, with
  R2_BUCKET_NAME != COACH_FEEDBACK_VIDEO_BUCKET (#484 made the caller's bucket
  authoritative, so the literal named a bucket that need not exist);
* a ref that cannot be signed reaches no <audio src>: callers omit the player;
* the blind error-audit and block-pick sheets serve the finalized parent ref
  with its window (audio_segment_path is NULL after finalize), audio and
  offsets only;
* /v2/recordings/<id>/playback-url signs a Lab Take against its own R2 bucket.

Run: python3 -m pytest tests/test_playback_serving.py
"""
from __future__ import annotations

import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask, request

from services import coach_video_storage as cvs
from services import lab_audio_storage

R2_BUCKET = "coach-media-r2"
LITERAL = "coach_feedback_videos"


def _r2_cfg():
    return SimpleNamespace(
        R2_BUCKET_NAME=R2_BUCKET, COACH_FEEDBACK_VIDEO_BUCKET=LITERAL,
        R2_ACCOUNT_ID="a", R2_ACCESS_KEY_ID="k", R2_SECRET_ACCESS_KEY="s",
        R2_LAB_AUDIO_BUCKET="", R2_LAB_AUDIO_PUBLIC_BASE_URL="",
        COACH_FEEDBACK_VIDEO_MAX_MB=100,
    )


class TheBucketWritesLandInIsTheBucketReadsUse(unittest.TestCase):

    def setUp(self):
        self._p = [patch.object(cvs, "_config", _r2_cfg),
                   patch.object(lab_audio_storage, "_config", _r2_cfg)]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def test_the_default_media_bucket_is_the_r2_bucket_under_r2(self):
        self.assertEqual(cvs.default_media_bucket(), R2_BUCKET)

    def test_the_supabase_fallback_keeps_the_legacy_bucket(self):
        cfg = _r2_cfg()
        cfg.R2_ACCOUNT_ID = ""
        with patch.object(cvs, "_config", lambda: cfg):
            self.assertEqual(cvs.default_media_bucket(), LITERAL)

    def test_the_lab_read_fallback_reads_where_pre_split_writes_land(self):
        self.assertEqual(lab_audio_storage.coach_bucket(), R2_BUCKET)
        self.assertEqual(lab_audio_storage.target_bucket(), R2_BUCKET)
        with patch("services.audio_storage.audio_bucket_name", lambda: "interview"):
            buckets = lab_audio_storage._candidate_buckets(None)
        self.assertEqual(buckets[0], R2_BUCKET)
        self.assertEqual(buckets[-1], LITERAL)   # old literal-bucket objects

    def test_the_coach_take_video_is_written_to_the_resolved_bucket(self):
        from routes.v2 import coach as coach_routes
        from services.db import db

        writes = []
        refs = []
        app = Flask(__name__)
        with patch.object(cvs, "put_coach_object_bytes",
                          lambda b, k, body, ct: writes.append((b, k))), \
                patch.object(db, "v2_get_session_by_id", lambda sid: {"id": sid}), \
                patch.object(db.takes, "set_session_coach_video_ref",
                             lambda sid, ref: refs.append(ref)), \
                patch.object(coach_routes, "refreshed_media_url", lambda r: r):
            with app.test_request_context(
                    method="POST", content_type="multipart/form-data",
                    data={"video_file": (io.BytesIO(b"\x00" * 64), "v.mp4")}):
                request.user_id = "coach-1"
                fn = coach_routes.v2_coach_session_video
                while hasattr(fn, "__wrapped__"):
                    fn = fn.__wrapped__
                resp, status = fn("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
        self.assertEqual(status, 200)
        self.assertEqual(writes[0][0], R2_BUCKET)
        self.assertTrue(refs[0].startswith(f"s3://{R2_BUCKET}/coach-feedback/"))
        self.assertEqual(resp.get_json()["video_ref"], refs[0])

    def test_an_existing_s3_ref_stays_authoritative(self):
        from services.audio_ref_resolver import resolve_playable_ref
        signs = []
        with patch.object(cvs, "presigned_get_coach_object",
                          lambda b, k, expires_in=0: (signs.append(b), "https://s/x")[1]):
            resolve_playable_ref(f"s3://{LITERAL}/coach-feedback/s/v.mp4")
        self.assertEqual(signs, [LITERAL])

    def test_no_writer_passes_the_literal_bucket_any_more(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        for rel in ("routes/v2/coach.py", "services/training_import.py"):
            src = (root / rel).read_text()
            self.assertNotIn('getattr(config, "COACH_FEEDBACK_VIDEO_BUCKET"', src, rel)
            self.assertNotIn('getattr(Config, "COACH_FEEDBACK_VIDEO_BUCKET"', src, rel)


class AnUnsignableRefReachesNoPlayer(unittest.TestCase):

    def test_the_snippet_resolver_returns_none_not_the_raw_column(self):
        from services.snippet_audio_url import resolve_snippet_audio_url
        with patch.object(cvs, "presigned_get_coach_object",
                          side_effect=RuntimeError("no creds")):
            self.assertIsNone(resolve_snippet_audio_url(
                {"audio_segment_path": "s3://b/willab_lab/s/t.webm"},
                database=SimpleNamespace(), app_config=SimpleNamespace()))

    def test_the_moment_playback_map_omits_an_unplayable_moment(self):
        from routes.v2 import arcs
        from services.db import db
        with patch.object(db, "get_snippets_by_session", lambda sid: [
                {"id": "s1", "audio_segment_path": "s3://b/k.webm",
                 "start_offset_ms": 0, "duration_ms": 1000}]), \
                patch.object(arcs, "_resolve_snippet_audio_url",
                             side_effect=RuntimeError("boom")):
            self.assertEqual(arcs._moment_playback_map(["t1"]), {})
        with patch.object(db, "get_snippets_by_session", lambda sid: [
                {"id": "s1", "audio_segment_path": "s3://b/k.webm"}]), \
                patch.object(arcs, "_resolve_snippet_audio_url", lambda s: None):
            self.assertEqual(arcs._moment_playback_map(["t1"]), {})

    def test_the_bake_drops_a_stored_raw_ref_but_keeps_the_card(self):
        from services import ideal_text_feedback_bake as bake
        block = {"changes": [
            {"snippet_id": "s1", "take_session_id": "t1",
             "snippet_audio_ref": "s3://b/k.webm", "start_offset_ms": 5},
            {"snippet_id": "s2", "take_session_id": "t1",
             "snippet_audio_ref": "https://old.example/k.webm"},
        ]}
        with patch("routes.v2.arcs._moment_playback_map", lambda ids: {}):
            out = bake._with_fresh_playback(block)
        self.assertEqual(len(out["changes"]), 2)
        self.assertIsNone(out["changes"][0]["snippet_audio_ref"])
        self.assertEqual(out["changes"][0]["start_offset_ms"], 5)
        self.assertEqual(out["changes"][1]["snippet_audio_ref"],
                         "https://old.example/k.webm")

    def test_the_practise_payload_and_album_take_a_none(self):
        from services.voice_album_history import _attempt_view
        view = _attempt_view({"id": "a1", "audio_ref": "s3://b/k.webm"},
                             selected_id="a1", resolve_audio=lambda r: None)
        self.assertIsNone(view["audio_url"])


class _AuditDb:
    """A finalized Take's snippet: audio_segment_path NULL, the parent on
    storage_path, the clip's window in offsets."""

    def __init__(self):
        self.audits = [{"id": "aud-1", "coach_id": "c", "clip_id": "s1",
                        "clip_kind": "snippet", "error_id": "rushing",
                        "answer": None},
                       {"id": "aud-2", "coach_id": "c", "clip_id": "p1",
                        "clip_kind": "practice_attempt", "error_id": "rushing",
                        "answer": None}]
        self.picks = [{"id": "pick-1", "coach_id": "c", "answered_at": None, "take_session_id": "t",
                       "candidate_snippet_ids": ["s1", "s2"]}]

    def list_speaking_errors(self):
        return [{"error_id": "rushing", "label": "Rushing", "asks": "Rushing?"}]

    def list_error_presence_audit_pending(self, coach_id):
        return [a for a in self.audits if a["coach_id"] == coach_id]

    def list_coach_block_picks_pending(self, coach_id):
        return list(self.picks)

    def get_snippet_by_id(self, sid):
        return {"id": sid, "audio_segment_path": None,
                "storage_path": f"willab_lab/take/{sid}.webm",
                "transcript": "secret words", "start_offset_ms": 12000,
                "duration_ms": 4000, "metrics": {"x": 1}}

    def get_confident_voice_practice_attempt(self, aid):
        return {"id": aid, "audio_ref": "s3://lab/confidence-practice/u/p/1.webm",
                "duration_ms": 3000}


def _fake_sign(bucket, key, expires_in=0, **_k):
    return f"https://signed/{bucket}/{key}"


class TheBlindSheetsPlayTheClip(unittest.TestCase):

    def test_the_error_audit_serves_the_parent_and_its_window(self):
        from services import error_presence_audit as epa
        with patch("config.Config.ERROR_PRESENCE_AUDIT_ENABLED", True, create=True), \
                patch.object(cvs, "presigned_get_coach_object", _fake_sign):
            status, payload = epa.queue(_AuditDb(), coach_id="c")
        self.assertEqual(status, 200)
        snip, practice = payload["items"]
        self.assertTrue(snip["audio_ref"].startswith("https://signed/"))
        self.assertIn("willab_lab/take/s1.webm", snip["audio_ref"])
        self.assertEqual((snip["start_offset_ms"], snip["duration_ms"]), (12000, 4000))
        self.assertEqual(practice["audio_ref"],
                         "https://signed/lab/confidence-practice/u/p/1.webm")
        self.assertEqual((practice["start_offset_ms"], practice["duration_ms"]), (0, 3000))
        # Blind: audio and offsets only.
        self.assertEqual(set(snip), {"audit_id", "clip_id", "audio_ref",
                                     "start_offset_ms", "duration_ms",
                                     "error_id", "label", "asks"})
        self.assertNotIn("secret words", str(payload))

    def test_the_block_pick_serves_the_parent_and_its_window(self):
        from services import coach_block_pick as bp
        with patch("config.Config.COACH_BLOCK_PICK_ENABLED", True, create=True), \
                patch("services.pair_consent.take_may_reach_a_coach_sheet",
                      lambda db, take: True), \
                patch.object(cvs, "presigned_get_coach_object", _fake_sign):
            status, payload = bp.queue(_AuditDb(), coach_id="c")
        self.assertEqual(status, 200)
        for clip in payload["items"][0]["clips"]:
            self.assertTrue(clip["audio_ref"].startswith("https://signed/"))
            self.assertEqual((clip["start_offset_ms"], clip["duration_ms"]), (12000, 4000))
            self.assertEqual(set(clip), {"clip_id", "letter", "audio_ref",
                                         "start_offset_ms", "duration_ms"})
        self.assertNotIn("secret words", str(payload))

    def test_an_unsignable_clip_has_no_player_and_no_crash(self):
        from services import error_presence_audit as epa
        with patch("config.Config.ERROR_PRESENCE_AUDIT_ENABLED", True, create=True), \
                patch.object(cvs, "presigned_get_coach_object",
                             side_effect=RuntimeError("down")):
            db = _AuditDb()
            db.create_signed_url = lambda *a: (_ for _ in ()).throw(RuntimeError("x"))
            status, payload = epa.queue(db, coach_id="c")
        self.assertEqual(status, 200)
        self.assertIsNone(payload["items"][0]["audio_ref"])
        self.assertIsNone(payload["items"][1]["audio_ref"])


class TheRecordingPlaybackUrl(unittest.TestCase):

    def _get(self, row, *, sign=_fake_sign, supabase=None):
        from routes import recordings
        from services.db import db
        app = Flask(__name__)
        calls = []

        def supabase_sign(bucket, path, ttl):
            calls.append((bucket, path))
            return supabase or "https://supabase/signed"

        with patch.object(db, "get_recording",
                          lambda rid, uid: row if uid == "owner" else None), \
                patch.object(db, "create_signed_url", supabase_sign), \
                patch.object(cvs, "presigned_get_coach_object", sign):
            with app.test_request_context():
                request.user_id = "owner"
                resp, status = recordings.get_recording_playback_url.__wrapped__(
                    "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
        return status, resp.get_json(), calls

    def test_a_lab_take_signs_against_its_own_r2_bucket(self):
        status, data, calls = self._get({
            "storage_path": "willab_lab/s/recording_x.webm",
            "audio_url": "s3://lab-bucket/willab_lab/s/recording_x.webm",
            "recording_origin": "willab_lab"})
        self.assertEqual(status, 200)
        self.assertEqual(data["audio_url"],
                         "https://signed/lab-bucket/willab_lab/s/recording_x.webm")
        self.assertEqual(calls, [])

    def test_an_unsignable_lab_take_is_404_not_a_dead_url(self):
        def boom(*_a, **_k):
            raise RuntimeError("down")
        status, data, _ = self._get({
            "storage_path": "willab_lab/s/r.webm",
            "audio_url": "s3://lab-bucket/willab_lab/s/r.webm"}, sign=boom)
        self.assertEqual(status, 404)
        self.assertEqual(data["code"], "AUDIO_UNAVAILABLE")

    def test_a_legacy_homework_recording_still_signs_in_supabase(self):
        status, data, calls = self._get({"storage_path": "u/rec.webm",
                                         "audio_url": None})
        self.assertEqual(status, 200)
        self.assertEqual(data["audio_url"], "https://supabase/signed")
        self.assertEqual(len(calls), 1)

    def test_another_user_still_gets_404(self):
        from routes import recordings
        from services.db import db
        app = Flask(__name__)
        with patch.object(db, "get_recording", lambda rid, uid: None):
            with app.test_request_context():
                request.user_id = "stranger"
                _resp, status = recordings.get_recording_playback_url.__wrapped__(
                    "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
