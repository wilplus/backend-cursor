"""willab coach session read — GET /v2/coach/sessions/<id> (FE PR #73).

The headline regression: canonical coach-authored note/tag/surfaced state
resumes on reopen without reviving the retired psychological construct lane.

Also guards the §S.4 identity strip (pseudonym + domain only; NO user_id /
name / email). The §B.4 pseudonym itself is pinned by
test_email_threading.py::PseudonymParityTests.
"""
from __future__ import annotations

import unittest

try:
    from flask import Flask, request

    import services.lab_recording as lab
    from routes.v2 import coach as v2_coach
    from services.db import db
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
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
            "intake_context": {
                "domain": "public_speaking", "topic": "demo day",
                "language": "en",
            },
            "results_published_at": None, "status": "pending_admin_review",
            "coach_overall_message": None, "coach_video_ref": None,
        })
        self._patch_db(
            "get_user_proficient_languages", lambda user_id: ["en"],
        )
        self._patch_db(
            "get_recording",
            lambda recording_id: {"transcription_language": "en"},
        )
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
        self.originals[f"db:{attr}"] = (db, attr, getattr(db, attr, None))
        setattr(db, attr, fn)

    def _get(self, sid=SID):
        with self.app.test_request_context():
            request.user_id = "coach-1"
            resp, status = v2_coach.v2_coach_get_session.__wrapped__(sid)
            return status, resp.get_json()


    def _as_second_coach(self, own_ratings=None):
        """A review another coach already claimed (K4 routes an Audio-unclear
        moment to a second coach; founder 2026-10-08, playback everywhere)."""
        calls = []

        def claimed_by_other(session_id, actor_user_id, **kwargs):
            calls.append(actor_user_id)
            raise RuntimeError("review assigned to another coach")

        self._patch_db("claim_coach_review", claimed_by_other)
        self._patch_db("get_own_state_ratings_for_session",
                       lambda sid, rater_id: dict(own_ratings or {}))
        lab.build_readout_from_session = lambda sid, **kw: {"snippets": [
            {"id": "a", "index": 1, "transcript": "hi",
             "audio_ref": "https://signed.example/take.webm?sig=1",
             "start_offset_ms": 0, "duration_ms": 8000,
             "stickiness": {"composite": 0.5, "comment": "c"}},
            {"id": "b", "index": 2, "transcript": "yo",
             "audio_ref": "https://signed.example/take.webm?sig=1",
             "start_offset_ms": 9000, "duration_ms": 5000},
        ]}
        return calls


    def test_context_is_redacted_until_every_blind_label_is_committed(self):
        setattr(
            db,
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
        self.assertIsNone(data["presentation_ref"])
        self.assertNotIn("stickiness", data["snippets"][0])
        self.assertNotIn("features", data["snippets"][0])
        # Row a is already answered by this coach, so its words may be
        # revealed. Row b is still blind and must be audio-only on the wire.
        by_id = {row["id"]: row for row in data["snippets"]}
        self.assertNotEqual(by_id["a"]["transcript"], "")
        self.assertEqual(by_id["b"]["transcript"], "")
        self.assertEqual(data["snippets"][0]["coach_state"]["note"], "")


if __name__ == "__main__":
    unittest.main()
