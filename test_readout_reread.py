"""Unit tests for build_readout_from_session (parked-restore + history).

The canonical §3.3 readout re-derived from PERSISTED snippets (features
+ persisted stickiness), + the post-publish coach-layer fold. DB mocked.

Run: python3 -m unittest test_readout_reread
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# services.db pulls in supabase/postgrest, which aren't in the test
# image, so we stub it — in setUpModule, NOT at import time. A stub
# left in sys.modules at import time leaks into sibling test modules:
# test_homework_regressions decides at import time whether the real
# services.db is importable, and a leaked stub makes it run against
# the fake instead of skipping. tearDownModule restores the state.
_ORIG_SERVICES_DB = None


def setUpModule():
    global _ORIG_SERVICES_DB
    _ORIG_SERVICES_DB = sys.modules.get("services.db")
    stub = types.ModuleType("services.db")
    stub.db = MagicMock()
    sys.modules["services.db"] = stub


def tearDownModule():
    if _ORIG_SERVICES_DB is not None:
        sys.modules["services.db"] = _ORIG_SERVICES_DB
    else:
        sys.modules.pop("services.db", None)


def _snippet(sid, **over):
    base = {
        "id": sid,
        "transcript": f"transcript {sid}",
        "audio_segment_path": "https://x/parent.webm",
        "start_offset_ms": 0,
        "duration_ms": 8000,
        "metrics": {
            "wpm": 140, "f0_mean": 165.0, "pause_ms": 220, "dynamic_db": 12.0,
            "stickiness": {"composite": 0.7, "comment": "Held one idea."},
        },
    }
    base.update(over)
    return base


class ReadoutFromSessionTests(unittest.TestCase):

    def _build(self, snippets, session=None, include_insights=True):
        from services import lab_recording as mod
        from services.db import db
        with patch.object(db, "get_snippets_by_session", return_value=snippets), \
             patch.object(db, "v2_get_session_by_id", return_value=(session or {})):
            return mod.build_readout_from_session(
                "sess1", include_insights=include_insights,
            )

    def test_coach_confirmed_breakthrough_marker(self):
        # threat then challenge (both coach-labelled, in time order) → the
        # challenge snippet carries the breakthrough badge; the threat doesn't.
        from services import lab_recording as mod
        from services.db import db
        snips = [
            _snippet("s1", start_offset_ms=0),
            _snippet("s2", start_offset_ms=5000),
        ]
        labels = [
            {"snippet_id": "s1", "value": "threat"},
            {"snippet_id": "s2", "value": "challenge"},
        ]
        with patch.object(db, "get_snippets_by_session", return_value=snips), \
             patch.object(db, "v2_get_session_by_id", return_value={}), \
             patch.object(db, "get_training_labels", return_value=labels):
            out = mod.build_readout_from_session("sess1", include_insights=True)
        by_id = {s["id"]: s for s in out["snippets"]}
        self.assertTrue(by_id["s2"]["breakthrough"])
        self.assertFalse(by_id["s1"]["breakthrough"])

    def test_no_breakthrough_without_coach_labels(self):
        out = self._build([_snippet("a")])  # MagicMock labels → empty
        self.assertFalse(out["snippets"][0]["breakthrough"])
        self.assertIsNone(out["snippets"][0]["breakthrough_note"])

    def test_rebuilds_features_and_persisted_stickiness(self):
        out = self._build([_snippet("a")])
        snip = out["snippets"][0]
        self.assertEqual(snip["id"], "a")
        self.assertEqual(snip["features"]["speech_rate"], 140)   # ← wpm
        self.assertEqual(snip["features"]["f0_mean"], 165.0)
        # stickiness comes from the PERSISTED metrics blob (the fix)
        self.assertEqual(snip["stickiness"]["composite"], 0.7)
        self.assertEqual(snip["stickiness"]["comment"], "Held one idea.")

    def test_features_block_excludes_stickiness_subkey(self):
        out = self._build([_snippet("a")])
        # the §3.3 features dict must NOT carry the internal stickiness key
        self.assertNotIn("stickiness", out["snippets"][0]["features"])

    def test_chronological_index(self):
        out = self._build([_snippet("a"), _snippet("b"), _snippet("c")])
        self.assertEqual([s["index"] for s in out["snippets"]], [1, 2, 3])

    def test_missing_stickiness_yields_none(self):
        s = _snippet("a")
        del s["metrics"]["stickiness"]
        out = self._build([s])
        self.assertIsNone(out["snippets"][0]["stickiness"]["composite"])

    def test_no_insights_pre_publish(self):
        out = self._build([_snippet("a")], session={"id": "sess1"})
        self.assertNotIn("insights_payload", out)
        self.assertNotIn("coach", out["snippets"][0])

    def test_folds_coach_layer_post_publish(self):
        session = {
            "id": "sess1",
            "insights_payload": {
                "overall_message": "Strong open.",
                "snippet_notes": [
                    {"snippet_id": "a", "note": "best 8s", "tag": "strong"},
                ],
            },
        }
        out = self._build([_snippet("a"), _snippet("b")], session=session)
        self.assertEqual(out["insights_payload"]["overall_message"], "Strong open.")
        # coach note folded onto snippet a, not b
        self.assertEqual(out["snippets"][0]["coach"]["note"], "best 8s")
        self.assertEqual(out["snippets"][0]["coach"]["tag"], "strong")
        # PR-2 backward-compat: a note that predates when/examples folds
        # with when=None / examples=[] so the FE hides them.
        self.assertIsNone(out["snippets"][0]["coach"]["when"])
        self.assertEqual(out["snippets"][0]["coach"]["examples"], [])
        self.assertNotIn("coach", out["snippets"][1])

    def test_folds_coach_when_examples(self):
        """PR-2 — when + examples on a snippet note round-trip into the
        per-snippet coach object."""
        session = {
            "id": "sess1",
            "insights_payload": {
                "overall_message": None,
                "snippet_notes": [{
                    "snippet_id": "a", "note": "best 8s", "tag": "strong",
                    "when": "right after the pause",
                    "examples": ["We should ship it.", "Let's go."],
                }],
            },
        }
        out = self._build([_snippet("a")], session=session)
        coach = out["snippets"][0]["coach"]
        self.assertEqual(coach["when"], "right after the pause")
        self.assertEqual(coach["examples"], ["We should ship it.", "Let's go."])

    def test_include_insights_false_skips_fold(self):
        session = {"id": "sess1", "insights_payload": {"overall_message": "x",
                   "snippet_notes": []}}
        out = self._build([_snippet("a")], session=session, include_insights=False)
        self.assertNotIn("insights_payload", out)

    def test_empty_session(self):
        out = self._build([])
        self.assertEqual(out["snippets"], [])

    # ── #A (readout) — COMPLETE per-slide 1:1 transcript on the payload ──

    _DECK_CTX = {
        "slides": [{"title": "S1", "body": ""}, {"title": "S2", "body": ""}],
        "slide_advances": [{"index": 0, "t_ms": 0}, {"index": 1, "t_ms": 5000}],
    }

    def test_attaches_persisted_slide_transcripts(self):
        from services import lab_recording as mod
        from services.db import db
        stx = [
            {"index": 0, "transcript": "welcome everyone",
             "start_offset_ms": 1000, "duration_ms": 1000},
            {"index": 1, "transcript": "here is the pitch",
             "start_offset_ms": 6000, "duration_ms": 2000},
        ]
        with patch.object(db, "get_snippets_by_session", return_value=[_snippet("a")]), \
             patch.object(db, "v2_get_session_by_id", return_value={}), \
             patch.object(db, "get_session_intake_context", return_value=self._DECK_CTX), \
             patch.object(db, "get_session_slide_transcripts", return_value=stx):
            out = mod.build_readout_from_session("sess1", include_insights=False)
        self.assertEqual(out["slide_transcripts"], stx)        # surfaced 1:1
        self.assertEqual(out["slides"], self._DECK_CTX["slides"])

    def test_slide_transcripts_fallback_from_snippet_words(self):
        # No persisted value (old recording) → best-effort from per-snippet words,
        # so the quiet first slide is still caught.
        from services import lab_recording as mod
        from services.db import db
        snip = _snippet("a", words=[
            {"word": "welcome", "start": 1.0, "end": 1.5},
            {"word": "everyone", "start": 1.6, "end": 2.0},
            {"word": "the", "start": 6.0, "end": 6.2},
            {"word": "pitch", "start": 6.3, "end": 6.8},
        ])
        with patch.object(db, "get_snippets_by_session", return_value=[snip]), \
             patch.object(db, "v2_get_session_by_id", return_value={}), \
             patch.object(db, "get_session_intake_context", return_value=self._DECK_CTX), \
             patch.object(db, "get_session_slide_transcripts", return_value=None):
            out = mod.build_readout_from_session("sess1", include_insights=False)
        by_idx = {t["index"]: t for t in out["slide_transcripts"]}
        self.assertEqual(by_idx[0]["transcript"], "welcome everyone")
        self.assertEqual(by_idx[1]["transcript"], "the pitch")

    def test_no_slide_transcripts_when_absent_and_no_words(self):
        from services import lab_recording as mod
        from services.db import db
        with patch.object(db, "get_snippets_by_session", return_value=[_snippet("a")]), \
             patch.object(db, "v2_get_session_by_id", return_value={}), \
             patch.object(db, "get_session_intake_context", return_value=self._DECK_CTX), \
             patch.object(db, "get_session_slide_transcripts", return_value=None):
            out = mod.build_readout_from_session("sess1", include_insights=False)
        self.assertNotIn("slide_transcripts", out)  # nothing to surface → omit


class TeaserScopeTests(unittest.TestCase):
    """Phase-1 free/paid scope boundary in build_readout_from_session.

    PAID (audit_paid=True, default) → full coach layer. UNPAID (audit_paid=
    False, the free-take teaser) → acoustic + breakthrough badges + the single
    strongest breakthrough video ONLY; insights_payload, written commentary,
    the session video, and the other breakthrough videos are all ABSENT."""

    @staticmethod
    def _session_with_two_breakthroughs():
        # Two coach-labelled breakthroughs (threat→challenge twice), each with a
        # coach video; ranks pick s4 (rank 1) over s2 (rank 3) as strongest.
        return {
            "id": "sess1",
            "insights_payload": {
                "overall_message": "Strong throughout.",
                "video_ref": "https://x/session-feedback.webm",
                "snippet_notes": [
                    {"snippet_id": "s2", "note": "nice recovery", "tag": "strong",
                     "breakthrough_video_ref": "https://x/bt-s2.webm"},
                    {"snippet_id": "s4", "note": "the best moment", "tag": "strong",
                     "breakthrough_video_ref": "https://x/bt-s4.webm"},
                ],
            },
        }

    @staticmethod
    def _snips_two_breakthroughs():
        return [
            _snippet("s1", start_offset_ms=0),
            _snippet("s2", start_offset_ms=5000,
                     metrics={"wpm": 140, "rank": 3,
                              "stickiness": {"composite": 0.6, "comment": "x"}}),
            _snippet("s3", start_offset_ms=10000),
            _snippet("s4", start_offset_ms=15000,
                     metrics={"wpm": 140, "rank": 1,
                              "stickiness": {"composite": 0.9, "comment": "y"}}),
        ]

    _LABELS = [
        {"snippet_id": "s1", "value": "threat"},
        {"snippet_id": "s2", "value": "challenge"},
        {"snippet_id": "s3", "value": "threat"},
        {"snippet_id": "s4", "value": "challenge"},
    ]

    def _build(self, *, audit_paid):
        from services import lab_recording as mod
        from services.db import db
        with patch.object(db, "get_snippets_by_session",
                          return_value=self._snips_two_breakthroughs()), \
             patch.object(db, "v2_get_session_by_id",
                          return_value=self._session_with_two_breakthroughs()), \
             patch.object(db, "get_training_labels", return_value=self._LABELS):
            return mod.build_readout_from_session(
                "sess1", include_insights=True, audit_paid=audit_paid,
            )

    def test_paid_full_scope(self):
        out = self._build(audit_paid=True)
        self.assertTrue(out["audit_paid"])
        # Full coach layer present.
        self.assertEqual(out["insights_payload"]["overall_message"],
                         "Strong throughout.")
        by_id = {s["id"]: s for s in out["snippets"]}
        self.assertEqual(by_id["s2"]["coach"]["note"], "nice recovery")
        self.assertEqual(by_id["s4"]["coach"]["note"], "the best moment")
        # BOTH breakthrough videos delivered.
        self.assertEqual(by_id["s2"]["breakthrough_video_ref"],
                         "https://x/bt-s2.webm")
        self.assertEqual(by_id["s4"]["breakthrough_video_ref"],
                         "https://x/bt-s4.webm")

    def test_teaser_withholds_commentary_and_session_video(self):
        out = self._build(audit_paid=False)
        self.assertFalse(out["audit_paid"])
        # insights_payload (carries overall_message + session video_ref) absent.
        self.assertNotIn("insights_payload", out)
        # No written commentary on any snippet.
        for s in out["snippets"]:
            self.assertNotIn("coach", s)

    def test_teaser_keeps_only_strongest_breakthrough_video(self):
        out = self._build(audit_paid=False)
        by_id = {s["id"]: s for s in out["snippets"]}
        # Acoustic + breakthrough badges survive.
        self.assertTrue(by_id["s2"]["breakthrough"])
        self.assertTrue(by_id["s4"]["breakthrough"])
        self.assertIn("features", by_id["s4"])
        # Exactly ONE breakthrough video — the strongest (s4, rank 1).
        with_video = [s["id"] for s in out["snippets"]
                      if s.get("breakthrough_video_ref")]
        self.assertEqual(with_video, ["s4"])
        self.assertEqual(by_id["s4"]["breakthrough_video_ref"],
                         "https://x/bt-s4.webm")
        self.assertNotIn("breakthrough_video_ref", by_id["s2"])

    def test_audit_paid_defaults_to_full(self):
        # Existing callers (no audit_paid kwarg) keep the full scope.
        from services import lab_recording as mod
        from services.db import db
        with patch.object(db, "get_snippets_by_session",
                          return_value=self._snips_two_breakthroughs()), \
             patch.object(db, "v2_get_session_by_id",
                          return_value=self._session_with_two_breakthroughs()), \
             patch.object(db, "get_training_labels", return_value=self._LABELS):
            out = mod.build_readout_from_session("sess1")
        self.assertTrue(out["audit_paid"])
        self.assertIn("insights_payload", out)


if __name__ == "__main__":
    unittest.main()
