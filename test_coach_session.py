"""willab coach session read — GET /v2/coach/sessions/<id> (FE PR #73).

The headline regression: the read folds BOTH coach lanes into per-snippet
`coach_state`, so note/tag/surfaced/direction ALL resume on reopen — not just
the label (the round-trip bug the alignment layer fixes).

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
            "insights_payload": None, "coach_video_ref": None,
        })
        # prior coach work: snippet "a" labeled + noted + tagged + surfaced; "b" blank
        self._patch_db("get_training_labels", lambda sid: [{"snippet_id": "a", "value": "challenge"}])
        self._patch_db("get_coach_snippet_drafts", lambda sid: [
            {"snippet_id": "a", "note": "strong open", "tag": "strong", "surfaced": True},
        ])
        # Phase 4 / Prompt 2 — AI-Commentator draft pre-fill for snippet "a".
        self._patch_db("get_ai_draft_coach_notes_by_session",
                       lambda sid: {"a": "🎤 Warm open — your pace lands well."})
        self._orig_build = lab.build_readout_from_session
        lab.build_readout_from_session = lambda sid: {"snippets": [
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

    def test_resume_folds_both_lanes(self):
        status, data = self._get()
        self.assertEqual(status, 200)
        snips = {s["id"]: s for s in data["snippets"]}
        # snippet "a": direction AND note/tag/surfaced all round-trip (the fix)
        cs = snips["a"]["coach_state"]
        self.assertEqual(cs["direction_label"], "challenge")
        self.assertEqual(cs["note"], "strong open")
        self.assertEqual(cs["tag"], "strong")
        self.assertTrue(cs["surfaced"])
        # snippet "b": nothing authored → empty coach_state, BUT surfaced by
        # default (§1.A opt-out-surface, FE handoff 2026-06-19 — no draft row
        # → shown). No AI draft for "b" either, so the note stays empty.
        cb = snips["b"]["coach_state"]
        self.assertIsNone(cb["direction_label"])
        self.assertEqual(cb["note"], "")
        self.assertIsNone(cb["tag"])
        self.assertTrue(cb["surfaced"])

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
            "intake_context": {}, "insights_payload": None, "coach_video_ref": None,
        })
        status, data = self._get()
        self.assertEqual(data["state"], "done")

    def test_ai_draft_coach_note_served_in_coach_state(self):
        # Prompt 2 PR-2 — the coach comment field opens pre-filled with the
        # AI-Commentator draft; snippets with no draft get None.
        status, data = self._get()
        snips = {s["id"]: s for s in data["snippets"]}
        self.assertEqual(
            snips["a"]["coach_state"]["ai_draft_coach_note"],
            "🎤 Warm open — your pace lands well.",
        )
        self.assertIsNone(snips["b"]["coach_state"]["ai_draft_coach_note"])

    def test_ai_draft_promoted_into_empty_note(self):
        # §1.B (FE handoff 2026-06-19) — an untouched snippet whose comment
        # field is empty opens PRE-FILLED with the AI draft (read-time; not
        # persisted). The immutable ai_draft_coach_note stays in the payload.
        setattr(v2.db, "get_ai_draft_coach_notes_by_session",
                lambda sid: {"a": "(a already authored)", "b": "🎤 Draft for b."})
        status, data = self._get()
        snips = {s["id"]: s for s in data["snippets"]}
        # "b": untouched (no draft row) → note seeded from its AI draft
        self.assertEqual(snips["b"]["coach_state"]["note"], "🎤 Draft for b.")
        self.assertEqual(snips["b"]["coach_state"]["ai_draft_coach_note"],
                         "🎤 Draft for b.")
        # "a": already authored "strong open" → AI draft must NOT overwrite it
        self.assertEqual(snips["a"]["coach_state"]["note"], "strong open")

    def test_snippet_shape_matches_fe(self):
        status, data = self._get()
        s = data["snippets"][0]
        for k in ("id", "index", "transcript", "audio_ref", "start_offset_ms",
                  "duration_ms", "stickiness", "coach_state",
                  "features"):  # C1/§B.1 — coach packet carries the 11-vector
            self.assertIn(k, s)
        for k in ("direction_label", "note", "tag", "surfaced"):
            self.assertIn(k, s["coach_state"])


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
