"""The Reflection Game (F2 handoff §1, 2026-08-03).

The founder-locked fences, pinned:
  * NO DECOY LEAK — the user payload is an exact allowlist; nothing in
    it (or in its JSON) distinguishes a flagged clip from a decoy or
    carries model confidence.
  * BLIND COACH — the coach queue payload is audio + transcript only:
    no machine flag, no user vote, no user identity, pre-verdict.
  * AC-9 — no counts/streaks/scores on any surface; a list is a list.
  * CADENCE — at most 2 freshly-served clips per user per UTC day,
    server-enforced; re-serving an unvoted clip is free.
  * DECOYS — 1 in 4 by all-time position, duration-matched, measured
    speech only; never served without flagged material; a coach-
    verified decoy still lands in the library.

Run: python3 -m unittest test_reflection_game
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from services import reflection_game as rg

try:
    from flask import Flask, request
    from routes import v2_routes as v2
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    v2 = None
    _IMPORT_ERROR = e

# Strings that must NEVER appear in any user/coach-reachable JSON.
_LEAK_MARKERS = ("machine_flagged", "decoy", "confidence", "predicted",
                 "shadow", "score")


def _snip(sid, i, dur=3000, transcript="a solid confident line here"):
    return {"id": f"{sid}-sn{i}", "session_id": sid,
            "start_offset_ms": i * 4000, "duration_ms": dur,
            "transcript": transcript, "audio_segment_path": f"s3://{sid}{i}",
            "metrics": {"overall_score": 0.4}}


class _GameDB:
    def __init__(self):
        self.sessions = [
            {"id": "t1", "arc_id": "a1", "recording_kind": "spoken",
             "intake_context": {"topic": "My pitch",
                                "named_emotion": "nervous"}},
            {"id": "r1", "arc_id": "a1", "recording_kind": "read",
             "paired_session_id": "t1",
             "intake_context": {"topic": "My pitch"}},
        ]
        self.snips = {
            "t1": [_snip("t1", i) for i in range(6)],
            "r1": [_snip("r1", 0)],
        }
        # Shadow-flagged: four spoken moments + the read's one.
        self.flagged = {"t1-sn0", "t1-sn1", "t1-sn2", "t1-sn3", "r1-sn0"}
        self.labels = {}          # coach training labels by session
        self.clips = []
        self._next = 0
        self.served_today = 0

    # — pool sources —
    def list_user_arc_sessions(self, uid):
        return list(self.sessions)

    def get_snippets_by_sessions(self, sids):
        return {k: list(v) for k, v in self.snips.items()}

    def get_training_labels_by_sessions(self, sids):
        return {k: list(v) for k, v in self.labels.items()}

    def get_shadow_challenge_snippet_ids(self, ids):
        return {i for i in ids if i in self.flagged}

    # — clip rows —
    def list_reflection_clips(self, uid):
        return [dict(c) for c in self.clips if c["user_id"] == uid]

    def insert_reflection_clip(self, uid, fields):
        self._next += 1
        self.clips.append({"id": f"c{self._next}", "user_id": uid,
                           **fields, "served_at": None, "user_vote": None,
                           "coach_verdict": None})
        return True

    def mark_reflection_clips_served(self, ids):
        wanted = {str(i) for i in ids}
        for c in self.clips:
            if c["id"] in wanted and not c["served_at"]:
                c["served_at"] = "today"
        return True

    def count_reflection_clips_served_today(self, uid):
        return self.served_today


class PoolBuilderTests(unittest.TestCase):

    def test_every_fourth_position_is_a_matched_decoy(self):
        db = _GameDB()
        created = rg.ensure_clip_pool("u1", db)
        self.assertEqual(created, 4)
        flags = [c["machine_flagged"] for c in db.clips]
        self.assertEqual(flags, [True, True, True, False])
        decoy = db.clips[3]
        self.assertNotIn(decoy["snippet_id"], db.flagged)
        # Duration-matched and measured — an obvious giveaway defeats
        # the design.
        self.assertGreaterEqual(decoy["duration_ms"], 1500)

    def test_coach_labeled_snippets_stay_out_of_both_pools(self):
        db = _GameDB()
        db.labels = {"t1": [{"snippet_id": "t1-sn0", "value": "challenge"}]}
        rg.ensure_clip_pool("u1", db)
        self.assertNotIn("t1-sn0",
                         [c["snippet_id"] for c in db.clips])

    def test_no_flagged_material_means_no_clips_at_all(self):
        db = _GameDB()
        db.flagged = set()
        self.assertEqual(rg.ensure_clip_pool("u1", db), 0)
        self.assertEqual(db.clips, [])

    def test_short_fragments_never_become_clips(self):
        db = _GameDB()
        db.snips["t1"].append(_snip("t1", 9, dur=600))
        db.flagged.add("t1-sn9")
        rg.ensure_clip_pool("u1", db)
        self.assertNotIn("t1-sn9", [c["snippet_id"] for c in db.clips])

    def test_read_material_keeps_its_recording_kind(self):
        db = _GameDB()
        rg.ensure_clip_pool("u1", db)
        kinds = {c["snippet_id"]: c["recording_kind"] for c in db.clips}
        if "r1-sn0" in kinds:
            self.assertEqual(kinds["r1-sn0"], "read")
        # The source take's named emotion snapshots onto the clip (§1f).
        t1_clips = [c for c in db.clips if c["take_session_id"] == "t1"]
        self.assertTrue(all(c["named_emotion"] == "nervous"
                            for c in t1_clips))


class ServeCadenceTests(unittest.TestCase):

    def test_at_most_two_fresh_serves_per_day(self):
        db = _GameDB()
        out = rg.serve_clips("u1", db)
        self.assertEqual(len(out), 2)
        served = [c for c in db.clips if c["served_at"]]
        self.assertEqual(len(served), 2)

    def test_reserving_unvoted_clips_burns_no_allowance(self):
        db = _GameDB()
        rg.serve_clips("u1", db)
        db.served_today = 2          # the day's fresh allowance is spent
        out = rg.serve_clips("u1", db)
        self.assertEqual(len(out), 2)          # same two, re-served
        self.assertEqual(len([c for c in db.clips if c["served_at"]]), 2)

    def test_spent_allowance_and_voted_clips_serve_nothing(self):
        db = _GameDB()
        rg.serve_clips("u1", db)
        for c in db.clips:
            if c["served_at"]:
                c["user_vote"] = "best"
        db.served_today = 2
        self.assertEqual(rg.serve_clips("u1", db), [])


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class UserPayloadLeakTests(unittest.TestCase):
    """THE fence: a devtools reader must learn nothing about decoys."""

    def setUp(self):
        self.app = Flask(__name__)

    def _get_clips(self, rows):
        with self.app.test_request_context():
            request.user_id = "u1"
            with patch.object(rg, "serve_clips", return_value=rows), \
                 patch.object(v2.db, "get_snippets_by_ids",
                              return_value=[
                                  {"id": r["snippet_id"],
                                   "audio_segment_path":
                                       f"https://a/{r['snippet_id']}.mp3"}
                                  for r in rows]):
                out = v2.v2_reflection_get_clips.__wrapped__()
            resp, status = out if isinstance(out, tuple) else (out, 200)
            return resp.get_json(), status

    def _rows(self):
        return [
            {"id": "c1", "user_id": "u1", "snippet_id": "t1-sn0",
             "take_session_id": "t1", "arc_id": "a1",
             "machine_flagged": True, "recording_kind": "spoken",
             "named_emotion": "nervous", "topic": "My pitch",
             "start_offset_ms": 0, "duration_ms": 3000,
             "transcript": "words", "served_at": None,
             "user_vote": None, "coach_verdict": None},
            {"id": "c2", "user_id": "u1", "snippet_id": "t1-sn5",
             "take_session_id": "t1", "arc_id": "a1",
             "machine_flagged": False, "recording_kind": "spoken",
             "named_emotion": "nervous", "topic": "My pitch",
             "start_offset_ms": 4000, "duration_ms": 3100,
             "transcript": "other words", "served_at": None,
             "user_vote": None, "coach_verdict": None},
        ]

    def test_payload_is_the_exact_allowlist(self):
        body, status = self._get_clips(self._rows())
        self.assertEqual(status, 200)
        self.assertEqual(set(body.keys()), {"clips"})   # a list is a list
        for clip in body["clips"]:
            self.assertEqual(set(clip.keys()),
                             {"clip_id", "audio_ref", "start_offset_ms",
                              "duration_ms", "arc_id", "take_session_id"})

    def test_flagged_and_decoy_are_byte_indistinguishable_in_shape(self):
        body, _ = self._get_clips(self._rows())
        wire = json.dumps(body).lower()
        for marker in _LEAK_MARKERS:
            self.assertNotIn(marker, wire)
        c1, c2 = body["clips"]
        self.assertEqual(set(c1.keys()), set(c2.keys()))


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class VoteTests(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)

    def _vote(self, body, db_row):
        with self.app.test_request_context(json=body):
            request.user_id = "u1"
            with patch.object(v2.db, "set_reflection_vote",
                              return_value=db_row):
                out = v2.v2_reflection_vote.__wrapped__("c1")
            resp, status = out if isinstance(out, tuple) else (out, 200)
            return resp.get_json(), status

    def test_valid_vote_saves(self):
        body, status = self._vote({"vote": "best"}, {"id": "c1"})
        self.assertEqual(status, 200)
        self.assertTrue(body["saved"])

    def test_unknown_vote_word_400s(self):
        _, status = self._vote({"vote": "meh"}, {"id": "c1"})
        self.assertEqual(status, 400)

    def test_someone_elses_clip_404s(self):
        _, status = self._vote({"vote": "best"}, None)
        self.assertEqual(status, 404)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class BlindCoachTests(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)

    def test_queue_payload_is_audio_and_transcript_only(self):
        rows = [{"id": "c1", "user_id": "u1", "snippet_id": "t1-sn0",
                 "machine_flagged": True, "user_vote": "best",
                 "named_emotion": "nervous", "recording_kind": "spoken",
                 "start_offset_ms": 0, "duration_ms": 3000,
                 "transcript": "the words", "arc_id": "a1",
                 "take_session_id": "t1"}]
        with self.app.test_request_context():
            request.user_id = "coach1"
            with patch.object(v2.db, "list_reflection_clips_for_coach",
                              return_value=rows), \
                 patch.object(v2.db, "get_snippets_by_ids",
                              return_value=[{
                                  "id": "t1-sn0",
                                  "audio_segment_path": "https://a/x.mp3"}]):
                out = v2.v2_coach_reflection_queue.__wrapped__()
        resp, status = out if isinstance(out, tuple) else (out, 200)
        body = resp.get_json()
        self.assertEqual(status, 200)
        for clip in body["clips"]:
            self.assertEqual(set(clip.keys()),
                             {"clip_id", "audio_ref", "start_offset_ms",
                              "duration_ms", "transcript"})
        wire = json.dumps(body).lower()
        # Pre-verdict the coach sees NO machine flag and NO user vote —
        # and no user identity either.
        for marker in _LEAK_MARKERS + ("vote", "user_id", "emotion"):
            self.assertNotIn(marker, wire)

    def _verdict(self, body, db_row):
        with self.app.test_request_context(json=body):
            request.user_id = "coach1"
            with patch.object(v2.db, "set_reflection_verdict",
                              return_value=db_row):
                out = v2.v2_coach_reflection_verdict.__wrapped__("c1")
            resp, status = out if isinstance(out, tuple) else (out, 200)
            return resp.get_json(), status

    def test_verdict_saves_and_logs_the_matrix_off_surface(self):
        row = {"id": "c1", "user_id": "u1", "machine_flagged": False,
               "user_vote": "best", "coach_verdict": "confident",
               "recording_kind": "spoken", "named_emotion": "nervous"}
        with self.assertLogs("services.reflection_game",
                             level="INFO") as cm:
            body, status = self._verdict({"verdict": "confident"}, row)
        self.assertEqual(status, 200)
        self.assertTrue(body["saved"])
        self.assertEqual(set(body.keys()), {"saved"})
        self.assertIn("reflection.matrix", cm.output[0])
        self.assertIn("machine_flagged=False", cm.output[0])

    def test_unknown_verdict_400s_and_missing_clip_404s(self):
        _, status = self._verdict({"verdict": "great"}, {"id": "c1"})
        self.assertEqual(status, 400)
        _, status = self._verdict({"verdict": "confident"}, None)
        self.assertEqual(status, 404)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class LibraryTests(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)

    def test_library_lists_verified_moments_decoys_included(self):
        rows = [
            {"id": "c9", "user_id": "u1", "snippet_id": "t1-sn5",
             "machine_flagged": False,    # a coach-verified DECOY —
             "coach_verdict": "confident",  # still a library moment
             "arc_id": "a1", "topic": "My pitch",
             "start_offset_ms": 4000, "duration_ms": 3100,
             "verified_at": "2026-08-03T10:00:00Z",
             "user_vote": "best", "recording_kind": "spoken",
             "named_emotion": "nervous", "transcript": "w"},
        ]
        with self.app.test_request_context():
            request.user_id = "u1"
            with patch.object(v2.db, "list_confident_voices",
                              return_value=rows), \
                 patch.object(v2.db, "get_snippets_by_ids",
                              return_value=[{
                                  "id": "t1-sn5",
                                  "audio_segment_path": "https://a/y.mp3"}]):
                out = v2.v2_library_confident_voices.__wrapped__()
        resp, status = out if isinstance(out, tuple) else (out, 200)
        body = resp.get_json()
        self.assertEqual(status, 200)
        self.assertEqual(set(body.keys()), {"items"})   # no counts (AC-9)
        self.assertEqual(len(body["items"]), 1)
        item = body["items"][0]
        self.assertEqual(set(item.keys()),
                         {"id", "audio_ref", "start_offset_ms",
                          "duration_ms", "arc_id", "topic", "verified_at"})
        wire = json.dumps(body).lower()
        for marker in _LEAK_MARKERS:
            self.assertNotIn(marker, wire)


if __name__ == "__main__":
    unittest.main()
