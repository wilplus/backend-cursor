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

    # ── Take-N setup restore (founder bug 2026-07-13) ────────────────────

    def test_setup_block_rides_the_readout(self):
        from services import lab_recording as mod
        from services.db import db
        ctx = {"topic": "My pitch", "audience": "investors",
               "target_length_seconds": 300,
               "slides": [{"title": "S1", "body": "b"}],
               "presentation_ref": "https://cdn/deck.pdf",
               "slide_advances": [{"index": 0, "t_ms": 0}]}
        with patch.object(db, "get_snippets_by_session", return_value=[_snippet("a")]), \
             patch.object(db, "v2_get_session_by_id", return_value={}), \
             patch.object(db, "get_session_intake_context", return_value=ctx), \
             patch.object(db, "get_session_slide_transcripts", return_value=None), \
             patch.object(db, "get_user_transcript_edits", return_value=[]):
            out = mod.build_readout_from_session("sess1", include_insights=False)
        self.assertEqual(out["setup"], {
            "topic": "My pitch", "audience": "investors",
            "target_length_seconds": 300,
            "slides": [{"title": "S1", "body": "b"}],
            "presentation_ref": "https://cdn/deck.pdf",
        })  # slide_advances deliberately NOT in setup (per-recording timeline)

    def test_setup_block_deckless_topic_only(self):
        from services import lab_recording as mod
        from services.db import db
        with patch.object(db, "get_snippets_by_session", return_value=[_snippet("a")]), \
             patch.object(db, "v2_get_session_by_id", return_value={}), \
             patch.object(db, "get_session_intake_context",
                          return_value={"topic": "My talk"}), \
             patch.object(db, "get_session_slide_transcripts", return_value=None), \
             patch.object(db, "get_user_transcript_edits", return_value=[]):
            out = mod.build_readout_from_session("sess1", include_insights=False)
        self.assertEqual(out["setup"]["topic"], "My talk")
        self.assertEqual(out["setup"]["slides"], [])

    def test_setup_omitted_when_context_empty(self):
        from services import lab_recording as mod
        from services.db import db
        with patch.object(db, "get_snippets_by_session", return_value=[_snippet("a")]), \
             patch.object(db, "v2_get_session_by_id", return_value={}), \
             patch.object(db, "get_session_intake_context", return_value={}), \
             patch.object(db, "get_session_slide_transcripts", return_value=None), \
             patch.object(db, "get_user_transcript_edits", return_value=[]):
            out = mod.build_readout_from_session("sess1", include_insights=False)
        self.assertNotIn("setup", out)

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

    def test_coach_final_card_wins_over_auto(self):
        # Engine 1 (2026-07-11): the coach-corrected card replaces the auto
        # one on the user readout; the coach packet keeps the draft beside it.
        from services import lab_recording as mod
        from services.db import db
        auto = {"already_strong": False, "upgrades": [],
                "rewrite_your_voice": "auto", "rewrite_polished": "auto",
                "why": None, "version": 1}
        final = {**auto, "rewrite_polished": "coach corrected",
                 "edited_by_coach": True}
        snips = [_snippet("a", say_it_stronger=auto,
                          say_it_stronger_final=final)]
        with patch.object(db, "get_snippets_by_session", return_value=snips), \
             patch.object(db, "v2_get_session_by_id", return_value={}), \
             patch.object(db, "get_user_transcript_edits", return_value=[]):
            out = mod.build_readout_from_session("sess1", include_insights=False)
            coach = mod.build_readout_from_session(
                "sess1", include_insights=False, include_slide_scores=True)
        self.assertEqual(out["snippets"][0]["say_it_stronger"], final)
        self.assertNotIn("say_it_stronger_draft", out["snippets"][0])
        self.assertEqual(coach["snippets"][0]["say_it_stronger_draft"], auto)

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
        # >300 chars → a TRUE legacy blob (the read-back probe re-splits
        # only past the 300 hard cap since the 2026-07-15 sentence work).
        words = [f"word{i}" for i in range(60)]
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


class PiecesCanonicalReadoutTests(unittest.TestCase):
    """Pieces-canonical read side (founder 2026-07-14): identity
    instant_chunks (no midpoint guessing), the user-facing auto_comment
    (guarded), and the HARD fences — acoustic_read/potentiometer NEVER on the
    user readout, ONLY on the coach packet."""

    def _piece_row(self, sid, piece_index, slide_index=None, **over):
        m = {
            "wpm": 140, "f0_sd": 30.0, "pause_regularity": 0.5,
            "dynamic_db": 12.0, "voiced_ratio": 0.7,
            "piece": {"index": piece_index},
            "acoustic_read": {"potentiometer": 0.72,
                              "outside_normal_range": True,
                              "baseline": "take",
                              "version": "acoustic-read-v1"},
            # The record-time LEARNED tone word (founder carve-out) — the
            # USER surface's comment tone. The coach surface must ignore it.
            "user_tone_word": "confident",
            "recording_kind": "spoken",
            "stickiness": {"composite": None, "comment": None},
        }
        if slide_index is not None:
            m["piece"]["slide_index"] = slide_index
        base = {
            "id": sid, "transcript": f"piece text {piece_index}",
            "audio_segment_path": "https://x/parent.webm",
            "start_offset_ms": piece_index * 4000, "duration_ms": 3500,
            "metrics": m,
            # a coach LLM draft on the row — must NEVER leak to the user
            "ai_draft_coach_note": "Coach-only draft with a number 42.",
        }
        base.update(over)
        return base

    def _build(self, rows, include_slide_scores=False, stx=None, ctx=None,
               prefill=False):
        from services import lab_recording as mod
        from services.db import db
        # Machine comment is DEFAULT-OFF (founder 2026-07-14); the comment-
        # content tests opt in via prefill=True (COACH_PREFILL_ENABLED).
        with patch.object(mod, "_coach_prefill_enabled", return_value=prefill), \
             patch.object(db, "get_snippets_by_session", return_value=rows), \
             patch.object(db, "v2_get_session_by_id", return_value={}), \
             patch.object(db, "get_session_intake_context",
                          return_value=(ctx if ctx is not None else {})), \
             patch.object(db, "get_session_slide_transcripts",
                          return_value=stx), \
             patch.object(db, "get_user_transcript_edits", return_value=[]):
            return mod.build_readout_from_session(
                "sess1", include_insights=False,
                include_slide_scores=include_slide_scores,
            )

    def test_identity_instant_chunks_one_entry_per_piece(self):
        rows = [self._piece_row("a", 0, slide_index=0),
                self._piece_row("b", 1, slide_index=0),
                self._piece_row("c", 2, slide_index=1)]
        out = self._build(rows)
        ic = out["instant_chunks"]
        self.assertEqual(len(ic), 3)                       # 1:1, nothing doubled
        self.assertEqual([c["index"] for c in ic], [0, 1, 2])
        self.assertEqual([c["snippet_id"] for c in ic], ["a", "b", "c"])
        self.assertEqual(ic[2]["slide_index"], 1)
        self.assertEqual(ic[0]["transcript"], "piece text 0")
        self.assertEqual(ic[0]["start_offset_ms"], 0)

    def test_no_machine_comment_by_default(self):
        # Founder 2026-07-14: the user instant view is suggestions-only — no
        # machine comment unless COACH_PREFILL_ENABLED is set.
        rows = [self._piece_row("a", 0)]
        out = self._build(rows)               # prefill=False (default)
        self.assertIsNone(out["instant_chunks"][0].get("auto_comment"))
        self.assertNotIn("Coach-only draft",
                         out["snippets"][0].get("auto_comment") or "")

    def test_user_comment_learned_tone_when_prefill_on(self):
        rows = [self._piece_row("a", 0, slide_index=0)]
        out = self._build(rows, prefill=True)
        ic = out["instant_chunks"]
        # USER surface: the serve-time comment carries the LEARNED tone word
        # (user_tone_word) — never the coach's draft text.
        self.assertIn("sounded rather confident", ic[0]["auto_comment"])
        self.assertNotIn("Coach-only draft", ic[0]["auto_comment"])

    def test_duplicate_piece_indexes_dedup(self):
        # A retry/re-process can leave two full piece sets — the instant view
        # keeps the FIRST row per piece_index, never renders a chunk twice.
        rows = [self._piece_row("a", 0), self._piece_row("a2", 0),
                self._piece_row("b", 1)]
        out = self._build(rows)
        ic = out["instant_chunks"]
        self.assertEqual([c["index"] for c in ic], [0, 1])
        self.assertEqual(ic[0]["snippet_id"], "a")

    def test_user_readout_never_carries_the_potentiometer(self):
        # AC-9 / coach-only: acoustic_read must not appear ANYWHERE in the
        # user-facing readout — not on snippets, not on instant_chunks. The
        # coach's ai_draft text must not leak either.
        import json as _json
        rows = [self._piece_row("a", 0)]
        out = self._build(rows, include_slide_scores=False)
        raw = _json.dumps(out)
        self.assertNotIn("acoustic_read", raw)
        self.assertNotIn("potentiometer", raw)
        self.assertNotIn("outside_normal_range", raw)
        self.assertNotIn("Coach-only draft", raw)

    def test_coach_packet_carries_the_potentiometer(self):
        # The potentiometer is served REGARDLESS of the comment flag (it is
        # not a comment) — this is the coach's key-moment triage signal.
        rows = [self._piece_row("a", 0)]
        out = self._build(rows, include_slide_scores=True)  # prefill=False
        snip = out["snippets"][0]
        self.assertEqual(snip["acoustic_read"]["potentiometer"], 0.72)
        self.assertTrue(snip["acoustic_read"]["outside_normal_range"])
        self.assertEqual(snip["recording_kind"], "spoken")

    def test_coach_comment_tone_is_acoustic_not_learned_when_prefill_on(self):
        # The decisive blind test (only relevant when the pre-fill is on):
        # learned word says "stressed", acoustic lean says "confident" → the
        # COACH surface says confident (the model's guess never reaches the
        # labeling surface), the USER surface says stressed (the carve-out).
        rows = [self._piece_row("a", 0)]
        rows[0]["metrics"]["user_tone_word"] = "stressed"
        coach = self._build([dict(rows[0], metrics=dict(
            rows[0]["metrics"]))], include_slide_scores=True, prefill=True)
        user = self._build(rows, include_slide_scores=False, prefill=True)
        self.assertIn("confident", coach["snippets"][0]["auto_comment"])
        self.assertIn("stressed", user["snippets"][0]["auto_comment"])

    def test_legacy_rows_get_no_auto_comment_at_all(self):
        # Legacy salient-window sessions must NOT retroactively surface any
        # machine comment to users (the ai_draft was never user-facing copy).
        legacy = _snippet("a", start_offset_ms=500, duration_ms=1000)
        legacy["ai_draft_coach_note"] = "Legacy coach-only draft."
        out = self._build([legacy])
        self.assertNotIn("auto_comment", out["snippets"][0])

    def test_legacy_window_rows_keep_midpoint_join(self):
        # No piece provenance → the legacy path: instant_chunks come from the
        # persisted chunk list with midpoint attach, exactly as before.
        legacy = _snippet("a", start_offset_ms=500, duration_ms=1000)
        stx = [{"index": 0, "transcript": "part one",
                "start_offset_ms": 0, "duration_ms": 3000}]
        out = self._build([legacy], stx=stx)
        ic = out["instant_chunks"]
        self.assertEqual(len(ic), 1)
        self.assertEqual(ic[0]["transcript"], "part one")


class PrimingFenceTests(unittest.TestCase):
    """The pre-take priming manipulation (founder 2026-07-13) is a PRIVATE
    coach/research signal on the session row — it must NEVER surface in the
    user-facing readout (AC-9). build_readout_from_session reads snippets +
    intake_context, not the session's priming columns, so this asserts the
    fence holds even when the session row carries priming."""

    def test_priming_never_leaks_into_readout(self):
        import json as _json
        from services import lab_recording as mod
        from services.db import db
        # A session row LOADED with the manipulation label + phrase.
        session = {
            "priming_condition": "challenge",
            "priming_phrase": "This talk will be graded on delivery.",
            "insights_payload": None,
        }
        with patch.object(db, "get_snippets_by_session",
                          return_value=[_snippet("a")]), \
             patch.object(db, "v2_get_session_by_id", return_value=session), \
             patch.object(db, "get_session_intake_context", return_value={}), \
             patch.object(db, "get_user_transcript_edits", return_value=[]):
            out = mod.build_readout_from_session("sess1")
        raw = _json.dumps(out)
        self.assertNotIn("priming", raw)
        self.assertNotIn("challenge", raw)
        self.assertNotIn("graded", raw)


class InstantChunksTests(unittest.TestCase):
    """instant_chunks (founder 2026-07-13) — the ONE deduped chunk list for
    the instant synonym view: every spoken span exactly once, the snippet's
    say_it_stronger card attached to the chunk it was spoken in."""

    _SIS = {"already_strong": False,
            "upgrades": [{"original": "good", "upgrade": "compelling",
                          "kind": "upgrade"}],
            "why": "Sharper verb."}

    def _deckless(self, stx, snippets):
        from services import lab_recording as mod
        from services.db import db
        with patch.object(db, "get_snippets_by_session", return_value=snippets), \
             patch.object(db, "v2_get_session_by_id", return_value={}), \
             patch.object(db, "get_session_intake_context", return_value={}), \
             patch.object(db, "get_session_slide_transcripts", return_value=stx), \
             patch.object(db, "get_user_transcript_edits", return_value=[]):
            return mod.build_readout_from_session(
                "sess1", include_insights=False,
            )

    def test_deckless_card_attaches_to_the_chunk_it_was_spoken_in(self):
        stx = [
            {"index": 0, "transcript": "part one",
             "start_offset_ms": 0, "duration_ms": 3000},
            {"index": 1, "transcript": "part two",
             "start_offset_ms": 3200, "duration_ms": 2500},
        ]
        snips = [
            # midpoint 4200ms → chunk 1's span [3200, 5700)
            _snippet("a", start_offset_ms=3700, duration_ms=1000,
                     say_it_stronger=self._SIS),
        ]
        out = self._deckless(stx, snips)
        ic = out["instant_chunks"]
        self.assertEqual(len(ic), 2)
        self.assertIsNone(ic[0]["say_it_stronger"])
        self.assertIsNone(ic[0]["snippet_id"])
        self.assertEqual(ic[1]["say_it_stronger"], self._SIS)
        self.assertEqual(ic[1]["snippet_id"], "a")
        # the chunk text/spans are the canonical ones — nothing doubled.
        self.assertEqual(ic[1]["transcript"], "part two")
        self.assertEqual(ic[1]["start_offset_ms"], 3200)

    def test_each_snippet_attaches_to_exactly_one_chunk(self):
        # A snippet whose span straddles both chunks still lands on ONE
        # (its midpoint's) — never rendered twice.
        stx = [
            {"index": 0, "transcript": "part one",
             "start_offset_ms": 0, "duration_ms": 3000},
            {"index": 1, "transcript": "part two",
             "start_offset_ms": 3000, "duration_ms": 3000},
        ]
        snips = [
            # spans 2000→5000, midpoint 3500 → chunk 1 only
            _snippet("a", start_offset_ms=2000, duration_ms=3000,
                     say_it_stronger=self._SIS),
        ]
        out = self._deckless(stx, snips)
        ic = out["instant_chunks"]
        attached = [c for c in ic if c["say_it_stronger"] is not None]
        self.assertEqual(len(attached), 1)
        self.assertEqual(attached[0]["index"], 1)

    def test_coach_final_card_rides_the_chunk(self):
        # The chunk carries the same final-over-draft resolution as
        # snippets[] — the coach's corrected card wins.
        final = {"already_strong": True, "upgrades": [],
                 "why": "Coach approved.", "edited_by_coach": True}
        stx = [{"index": 0, "transcript": "part one",
                "start_offset_ms": 0, "duration_ms": 3000}]
        snips = [_snippet("a", start_offset_ms=500, duration_ms=1000,
                          say_it_stronger=self._SIS,
                          say_it_stronger_final=final)]
        out = self._deckless(stx, snips)
        self.assertEqual(out["instant_chunks"][0]["say_it_stronger"], final)

    def test_legacy_blob_chunks_have_no_spans_and_no_cards(self):
        # Legacy single-blob persist → text-only chunks (no spans) → no span
        # match → cards stay on snippets[]; the instant list still renders.
        blob = " ".join(f"word{i}" for i in range(80))
        stx = [{"index": 0, "transcript": blob,
                "start_offset_ms": 0, "duration_ms": 60000}]
        snips = [_snippet("a", say_it_stronger=self._SIS)]
        out = self._deckless(stx, snips)
        ic = out["instant_chunks"]
        self.assertGreater(len(ic), 1)
        self.assertTrue(all(c["say_it_stronger"] is None for c in ic))

    def test_decked_one_chunk_per_slide_with_card(self):
        from services import lab_recording as mod
        from services.db import db
        ctx = {"topic": "T", "slides": [{"title": "A"}, {"title": "B"}],
               "slide_advances": None}
        stx = [
            {"index": 0, "transcript": "slide one words",
             "start_offset_ms": 0, "duration_ms": 4000},
            {"index": 1, "transcript": "slide two words",
             "start_offset_ms": 4000, "duration_ms": 4000},
        ]
        snips = [_snippet("a", start_offset_ms=4500, duration_ms=1000,
                          say_it_stronger=self._SIS)]
        with patch.object(db, "get_snippets_by_session", return_value=snips), \
             patch.object(db, "v2_get_session_by_id", return_value={}), \
             patch.object(db, "get_session_intake_context", return_value=ctx), \
             patch.object(db, "get_session_slide_transcripts", return_value=stx), \
             patch.object(db, "get_user_transcript_edits", return_value=[]):
            out = mod.build_readout_from_session(
                "sess1", include_insights=False,
            )
        ic = out["instant_chunks"]
        self.assertEqual(len(ic), 2)
        self.assertEqual(ic[0]["slide_index"], 0)
        self.assertEqual(ic[1]["slide_index"], 1)
        self.assertIsNone(ic[0]["say_it_stronger"])
        self.assertEqual(ic[1]["say_it_stronger"], self._SIS)
        self.assertEqual(ic[1]["snippet_id"], "a")


if __name__ == "__main__":
    unittest.main()
