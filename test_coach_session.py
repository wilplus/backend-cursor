"""willab coach session read — GET /v2/coach/sessions/<id> (FE PR #73).

The headline regression: canonical coach-authored note/tag/surfaced state
resumes on reopen without reviving the retired psychological construct lane.

Also guards the §S.4 identity strip (pseudonym + domain only; NO user_id /
name / email) and the §B.4 friendly pseudonym.
"""
from __future__ import annotations

import json
import unittest

try:
    from flask import Flask, request
    from routes import v2_routes as v2
    import services.lab_recording as lab
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    v2 = None
    lab = None
    _IMPORT_ERROR = e


SID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


@unittest.skipIf(_IMPORT_ERROR is not None, f"coach session tests need app deps: {_IMPORT_ERROR}")
class CoachSessionReadTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.originals = {}
        self._patch_db("v2_get_session_by_id", lambda sid: {
            "id": sid, "user_id": "user-xyz-secret",
            "intake_context": {"domain": "public_speaking", "topic": "demo day"},
            "results_published_at": None, "status": "pending_admin_review",
            "coach_overall_message": None, "coach_video_ref": None,
        })
        self._patch_db(
            "claim_coach_review",
            lambda session_id, actor_user_id, **kwargs: {
                "assigned_to": actor_user_id, "claimed": True,
            },
        )
        # Prior coach work: snippet "a" noted + tagged + surfaced; "b" blank.
        self._patch_db("get_coach_snippet_drafts", lambda sid: [
            {"snippet_id": "a", "note": "strong open", "tag": "strong", "surfaced": True},
        ])
        # These legacy shape/resume tests exercise the contextual second pass.
        # Commit the fixture coach's blind answers first so the new hard gate
        # legitimately unlocks the context they assert below.
        self._patch_db(
            "get_own_state_ratings_for_session",
            lambda sid, rater_id: {
                "a": {"value": "yes", "unrateable": False},
                "b": {"value": "neutral", "unrateable": False},
            },
        )
        # Phase 4 / Prompt 2 — AI-Commentator draft pre-fill for snippet "a".
        self._patch_db("get_ai_draft_coach_notes_by_session",
                       lambda sid: {"a": "🎤 Warm open — your pace lands well."})
        self._orig_build = lab.build_readout_from_session
        # The coach get-session route calls build_readout_from_session(sid,
        # include_slide_scores=True); accept whatever kwargs the real fn takes.
        lab.build_readout_from_session = lambda sid, **kw: {"snippets": [
            {"id": "a", "index": 1, "transcript": "hi", "audio_ref": "p/a.wav",
             "start_offset_ms": 0, "duration_ms": 8000,
             "stickiness": {"composite": 0.5, "comment": "c"}},
            {"id": "b", "index": 2, "transcript": "yo", "audio_ref": "p/b.wav",
             "start_offset_ms": 9000, "duration_ms": 5000,
             "stickiness": {"composite": 0.3, "comment": None}},
        ]}

    def tearDown(self):
        lab.build_readout_from_session = self._orig_build
        for target, attr, orig in self.originals.values():
            setattr(target, attr, orig)

    def _patch_db(self, attr, fn):
        self.originals[f"db:{attr}"] = (v2.db, attr, getattr(v2.db, attr, None))
        setattr(v2.db, attr, fn)

    def _get(self, sid=SID):
        with self.app.test_request_context():
            request.user_id = "coach-1"
            resp, status = v2.v2_coach_get_session.__wrapped__(sid)
            return status, resp.get_json()

    def test_resume_folds_coach_authoring(self):
        status, data = self._get()
        self.assertEqual(status, 200)
        snips = {s["id"]: s for s in data["snippets"]}
        # Snippet "a": canonical note/tag/surfaced state round-trips.
        cs = snips["a"]["coach_state"]
        self.assertEqual(cs["note"], "strong open")
        self.assertEqual(cs["tag"], "strong")
        self.assertTrue(cs["surfaced"])
        self.assertNotIn("direction_label", cs)
        # snippet "b": nothing authored → empty coach_state, and NOT shown by
        # default (founder 2026-07-14 — opt-IN surface: the coach narrows to
        # the moments they mark as key/breakthrough; all snippets start hidden).
        cb = snips["b"]["coach_state"]
        self.assertEqual(cb["note"], "")
        self.assertIsNone(cb["tag"])
        self.assertFalse(cb["surfaced"])
        self.assertNotIn("direction_label", cb)

    def test_identity_stripped(self):
        status, data = self._get()
        self.assertTrue(data["pseudonym"])
        self.assertNotIn("user_id", data)
        self.assertNotIn("email", data)
        # the raw user_id must never appear anywhere in the serialized payload
        self.assertNotIn("user-xyz-secret", json.dumps(data))
        self.assertEqual(data["domain"], "public_speaking")
        self.assertEqual(data["topic"], "demo day")

    def test_state_in_progress_when_authored(self):
        status, data = self._get()
        self.assertEqual(data["state"], "in_progress")

    def test_state_done_when_published(self):
        setattr(v2.db, "v2_get_session_by_id", lambda sid: {
            "id": sid, "user_id": "u", "results_published_at": "2026-06-06T00:00:00Z",
            "intake_context": {}, "coach_overall_message": None, "coach_video_ref": None,
        })
        status, data = self._get()
        self.assertEqual(data["state"], "done")

    def test_coach_comment_prefill_retired(self):
        # Founder 2026-07-14 — "no pre-filled comment; the system learns from
        # what the coach writes." The AI draft is neither served in coach_state
        # nor promoted into the note; an untouched snippet opens EMPTY.
        setattr(v2.db, "get_ai_draft_coach_notes_by_session",
                lambda sid: {"a": "(draft a)", "b": "🎤 Draft for b."})
        status, data = self._get()
        snips = {s["id"]: s for s in data["snippets"]}
        # "b": untouched → note stays empty (no promotion), no ai_draft key
        self.assertEqual(snips["b"]["coach_state"]["note"], "")
        self.assertNotIn("ai_draft_coach_note", snips["b"]["coach_state"])
        # "a": the coach's OWN authored note is preserved (that's their input)
        self.assertEqual(snips["a"]["coach_state"]["note"], "strong open")
        self.assertNotIn("ai_draft_coach_note", snips["a"]["coach_state"])

    def test_snippet_shape_matches_fe(self):
        status, data = self._get()
        s = data["snippets"][0]
        for k in ("id", "index", "transcript", "audio_ref", "start_offset_ms",
                  "duration_ms", "stickiness", "coach_state",
                  "features"):  # C1/§B.1 — coach packet carries the 11-vector
            self.assertIn(k, s)
        for k in ("note", "tag", "surfaced"):
            self.assertIn(k, s["coach_state"])
        self.assertNotIn("direction_label", s["coach_state"])

    def test_moments_preserve_source_order_without_legacy_acoustic_ranking(self):
        # The neutral acoustic baseline does not reorder the coach packet.
        # Source chronology is preserved and indices remain continuous.
        lab.build_readout_from_session = lambda sid, **kw: {"snippets": [
            {"id": "flat", "index": 0, "transcript": "t", "audio_ref": "p/f.wav",
             "start_offset_ms": 0, "duration_ms": 3000,
             "acoustic_read": {"potentiometer": 0.05, "outside_normal_range": False}},
            {"id": "key", "index": 1, "transcript": "t", "audio_ref": "p/k.wav",
             "start_offset_ms": 9000, "duration_ms": 3000,
             "acoustic_read": {"potentiometer": -0.9, "outside_normal_range": True}},
        ]}
        status, data = self._get()
        self.assertEqual(status, 200)
        self.assertEqual([s["id"] for s in data["snippets"]], ["flat", "key"])
        self.assertEqual([s["index"] for s in data["snippets"]], [0, 1])

    def test_context_is_redacted_until_every_blind_label_is_committed(self):
        setattr(
            v2.db,
            "get_own_state_ratings_for_session",
            lambda sid, rater_id: {
                "a": {"value": "yes", "unrateable": False},
            },
        )
        status, data = self._get()
        self.assertEqual(status, 200)
        self.assertFalse(data["context_unlocked"])
        self.assertEqual(data["blind_label"], {
            "labelled": 1, "total": 2, "complete": False,
        })
        self.assertEqual(data["domain"], "")
        self.assertEqual(data["slides"], [])
        self.assertIsNone(data["presentation_ref"])
        self.assertNotIn("stickiness", data["snippets"][0])
        self.assertNotIn("features", data["snippets"][0])
        self.assertEqual(data["snippets"][0]["coach_state"]["note"], "")


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class PseudonymTests(unittest.TestCase):
    def test_stable(self):
        self.assertEqual(v2._coach_pseudonym("user-1"), v2._coach_pseudonym("user-1"))

    def test_friendly_two_words_no_raw_id(self):
        p = v2._coach_pseudonym("user-1")
        self.assertIn(" ", p)                 # "Adjective Animal"
        self.assertNotIn("user-1", p)

    def test_variety_not_all_collide(self):
        names = {v2._coach_pseudonym(f"u{i}") for i in range(8)}
        self.assertGreater(len(names), 1)

    def test_empty_anonymous(self):
        self.assertEqual(v2._coach_pseudonym(None), "Anonymous")


if __name__ == "__main__":
    unittest.main()
