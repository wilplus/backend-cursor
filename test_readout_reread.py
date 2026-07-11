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

    # ── Deckless full transcript, chunked (founder 2026-07-11 re-cut) ─────

    _DECKLESS_CTX: dict = {}  # no "slides" key at all → the deckless branch

    def test_deckless_new_style_chunks_fold_with_spans(self):
        # New-style persist: the chunks THEMSELVES are the entries, each with
        # its audio span — folded as-is so playback can't drift from text.
        from services import lab_recording as mod
        from services.db import db
        stx = [
            {"index": 0, "transcript": "part one",
             "start_offset_ms": 0, "duration_ms": 3000},
            {"index": 1, "transcript": "part two",
             "start_offset_ms": 3200, "duration_ms": 2500},
        ]
        with patch.object(db, "get_snippets_by_session", return_value=[_snippet("a")]), \
             patch.object(db, "v2_get_session_by_id", return_value={}), \
             patch.object(db, "get_session_intake_context", return_value=self._DECKLESS_CTX), \
             patch.object(db, "get_session_slide_transcripts", return_value=stx), \
             patch.object(db, "get_user_transcript_edits", return_value=[]):
            out = mod.build_readout_from_session("sess1", include_insights=False)
        self.assertEqual(out["full_transcript"], "part one part two")
        chunks = out["full_transcript_chunks"]
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[1]["start_offset_ms"], 3200)
        self.assertEqual(chunks[1]["duration_ms"], 2500)
        self.assertNotIn("slides", out)          # no deck → no slides key
        self.assertNotIn("slide_transcripts", out)  # decked-only field

    def test_deckless_legacy_blob_rechunks_without_spans(self):
        from services import lab_recording as mod
        from services.db import db
        blob = " ".join(f"word{i}" for i in range(80))  # >> 200 chars
        stx = [{"index": 0, "transcript": blob,
                "start_offset_ms": 0, "duration_ms": 60000}]
        with patch.object(db, "get_snippets_by_session", return_value=[_snippet("a")]), \
             patch.object(db, "v2_get_session_by_id", return_value={}), \
             patch.object(db, "get_session_intake_context", return_value=self._DECKLESS_CTX), \
             patch.object(db, "get_session_slide_transcripts", return_value=stx), \
             patch.object(db, "get_user_transcript_edits", return_value=[]):
            out = mod.build_readout_from_session("sess1", include_insights=False)
        chunks = out["full_transcript_chunks"]
        self.assertGreater(len(chunks), 1)
        self.assertNotIn("start_offset_ms", chunks[0])  # no fake spans
        self.assertEqual(" ".join(c["transcript"] for c in chunks), blob)

    def test_audience_exposed_from_setup(self):
        # Backlog 1.4 — the training-setup audience rides the readout so the
        # FE can suffix insight one-liners "(audience: investors)".
        from services import lab_recording as mod
        from services.db import db
        with patch.object(db, "get_snippets_by_session", return_value=[_snippet("a")]), \
             patch.object(db, "v2_get_session_by_id", return_value={}), \
             patch.object(db, "get_session_intake_context",
                          return_value={"audience": "  investors  "}), \
             patch.object(db, "get_session_slide_transcripts", return_value=None), \
             patch.object(db, "get_user_transcript_edits", return_value=[]):
            out = mod.build_readout_from_session("sess1", include_insights=False)
        self.assertEqual(out["audience"], "investors")

    def test_blank_audience_omitted(self):
        from services import lab_recording as mod
        from services.db import db
        with patch.object(db, "get_snippets_by_session", return_value=[_snippet("a")]), \
             patch.object(db, "v2_get_session_by_id", return_value={}), \
             patch.object(db, "get_session_intake_context",
                          return_value={"audience": "   "}), \
             patch.object(db, "get_session_slide_transcripts", return_value=None), \
             patch.object(db, "get_user_transcript_edits", return_value=[]):
            out = mod.build_readout_from_session("sess1", include_insights=False)
        self.assertNotIn("audience", out)

    def test_parent_audio_ref_exposed(self):
        # Parent+offset model: every snippet's audio_segment_path IS the
        # full-take audio — surfaced top-level for section playback.
        out = self._build([_snippet("a")])
        self.assertEqual(out["parent_audio_ref"], "https://x/parent.webm")

    def test_deckless_no_persisted_transcript_omits_both_fields(self):
        from services import lab_recording as mod
        from services.db import db
        with patch.object(db, "get_snippets_by_session", return_value=[_snippet("a")]), \
             patch.object(db, "v2_get_session_by_id", return_value={}), \
             patch.object(db, "get_session_intake_context", return_value=self._DECKLESS_CTX), \
             patch.object(db, "get_session_slide_transcripts", return_value=None):
            out = mod.build_readout_from_session("sess1", include_insights=False)
        self.assertNotIn("full_transcript", out)
        self.assertNotIn("full_transcript_chunks", out)

    # ── "Say It Stronger" + user transcript edits (founder 2026-07-07) ────

    def test_say_it_stronger_folds_from_persisted_row(self):
        from services import lab_recording as mod
        from services.db import db
        sis = {"already_strong": False, "upgrades": [],
               "rewrite_your_voice": "We ship it.",
               "rewrite_polished": "We will ship it.",
               "why": "Direct beats hedged.", "version": 1}
        snips = [_snippet("a", say_it_stronger=sis), _snippet("b")]
        with patch.object(db, "get_snippets_by_session", return_value=snips), \
             patch.object(db, "v2_get_session_by_id", return_value={}), \
             patch.object(db, "get_user_transcript_edits", return_value=[]):
            out = mod.build_readout_from_session("sess1", include_insights=False)
        by_id = {s["id"]: s for s in out["snippets"]}
        self.assertEqual(by_id["a"]["say_it_stronger"], sis)
        self.assertIsNone(by_id["b"]["say_it_stronger"])  # not generated yet

    def test_user_edited_text_folds_per_snippet(self):
        from services import lab_recording as mod
        from services.db import db
        edits = [{"snippet_id": "a", "chunk_index": None, "text": "fixed text"}]
        with patch.object(db, "get_snippets_by_session",
                          return_value=[_snippet("a"), _snippet("b")]), \
             patch.object(db, "v2_get_session_by_id", return_value={}), \
             patch.object(db, "get_user_transcript_edits", return_value=edits):
            out = mod.build_readout_from_session("sess1", include_insights=False)
        by_id = {s["id"]: s for s in out["snippets"]}
        self.assertEqual(by_id["a"]["user_edited_text"], "fixed text")
        self.assertIsNone(by_id["b"]["user_edited_text"])
        # the original transcript is NEVER replaced — edit rides beside it
        self.assertEqual(by_id["a"]["transcript"], "transcript a")

    def test_user_edited_text_folds_on_deckless_chunks(self):
        from services import lab_recording as mod
        from services.db import db
        words = [f"w{i}" for i in range(60)]
        stx = [{"index": 0, "transcript": " ".join(words),
                "start_offset_ms": 0, "duration_ms": 30000}]
        edits = [{"snippet_id": None, "chunk_index": 1, "text": "my fix"}]
        with patch.object(db, "get_snippets_by_session", return_value=[_snippet("a")]), \
             patch.object(db, "v2_get_session_by_id", return_value={}), \
             patch.object(db, "get_session_intake_context", return_value=self._DECKLESS_CTX), \
             patch.object(db, "get_session_slide_transcripts", return_value=stx), \
             patch.object(db, "get_user_transcript_edits", return_value=edits):
            out = mod.build_readout_from_session("sess1", include_insights=False)
        chunks = out["full_transcript_chunks"]
        self.assertIsNone(chunks[0]["user_edited_text"])
        self.assertEqual(chunks[1]["user_edited_text"], "my fix")


class CoachLayerAlwaysFreeTests(unittest.TestCase):
    """Founder re-price 2026-07-06: the coach layer (note, tag, transcript_
    corrected, breakthrough badge + video) folds UNCONDITIONALLY the instant
    the coach saves + surfaces it — regardless of ``audit_paid``. The old
    per-take/free-intro teaser scoping (withhold on an unpaid arc) is RETIRED;
    only the coach-corrected IDEAL TEXT, the breakthroughs LIST, the game, and
    the snippet library remain paid — none of which this function serves."""

    @staticmethod
    def _session_with_two_breakthroughs():
        # Two coach-labelled breakthroughs (threat→challenge twice), each with a
        # coach video + a corrected transcript on one of them.
        return {
            "id": "sess1",
            "insights_payload": {
                "overall_message": "Strong throughout.",
                "video_ref": "https://x/session-feedback.webm",
                "snippet_notes": [
                    {"snippet_id": "s2", "note": "nice recovery", "tag": "strong",
                     "breakthrough_video_ref": "https://x/bt-s2.webm"},
                    {"snippet_id": "s4", "note": "the best moment", "tag": "strong",
                     "breakthrough_video_ref": "https://x/bt-s4.webm",
                     "transcript_corrected": "The corrected line, verbatim."},
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

    def _build(self, *, audit_paid=True):
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

    def test_unpaid_arc_still_gets_full_coach_layer(self):
        out = self._build(audit_paid=False)
        self.assertFalse(out["audit_paid"])  # echoed as-is
        # Coach layer folds anyway — no payment gate on it.
        self.assertEqual(out["insights_payload"]["overall_message"],
                         "Strong throughout.")
        by_id = {s["id"]: s for s in out["snippets"]}
        self.assertEqual(by_id["s2"]["coach"]["note"], "nice recovery")
        self.assertEqual(by_id["s4"]["coach"]["note"], "the best moment")
        # BOTH breakthrough videos delivered (no "strongest only" narrowing).
        self.assertEqual(by_id["s2"]["breakthrough_video_ref"],
                         "https://x/bt-s2.webm")
        self.assertEqual(by_id["s4"]["breakthrough_video_ref"],
                         "https://x/bt-s4.webm")

    def test_coach_corrected_transcript_folds_when_present(self):
        out = self._build(audit_paid=False)
        by_id = {s["id"]: s for s in out["snippets"]}
        self.assertEqual(by_id["s4"]["coach"]["transcript_corrected"],
                         "The corrected line, verbatim.")
        # s2 never got one — present as None, not missing.
        self.assertIsNone(by_id["s2"]["coach"]["transcript_corrected"])

    def test_paid_arc_identical_coach_layer(self):
        # Payment changes nothing about this function's output.
        out_paid = self._build(audit_paid=True)
        out_unpaid = self._build(audit_paid=False)
        for k in ("insights_payload", "snippets"):
            self.assertEqual(out_paid[k], out_unpaid[k])

    def test_audit_paid_defaults_to_true_and_coach_layer_present(self):
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
