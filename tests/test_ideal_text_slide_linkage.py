"""
STORY    As a speaker, I want each paragraph of my Ideal Text tied to its
         slide and my deck link kept, and my locked words shown even when
         composing fails, so that I can read my talk slide by slide.
OUTCOME
  O1  Pieces that line up 1:1 with the served paragraphs carry their slide.
  O2  Pieces that do not line up all degrade to slide_index null; the
      paragraph text still serves.
  O3  presentation_ref is the first deck across Takes; a later deckless
      Take never clobbers it.
  O4  The GET never runs the composer (only the stored compose cache is read).
  O5  A compose failure serves the pinned locked text, locks still on the wire.
PROVES   O1 -> test_aligned_pieces_carry_their_slide_index
         O2 -> test_misaligned_counts_degrade_every_index_to_null
         O3 -> test_a_deckless_retake_keeps_the_first_deck
         O4 -> test_aligned_pieces_carry_their_slide_index (composer patched to explode)
         O5 -> test_compose_exception_serves_the_pinned_state_with_its_locks
WHY      FE PR #222 (slide linkage); SPEC 12.1 field report #5 (compose fallback).
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from config import Config

try:
    from flask import Flask, request

    from routes.v2 import explore_ideal_text as v2_explore_ideal_text
    from services.db import db
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = e

ARC = "a1"
DECK = "https://cdn.example/willab_presentations/abc.pdf"


def _row(**over):
    row = {"arc_id": ARC, "text": "machine text", "auto_text": "machine text",
           "updated_by": None, "approved_at": None, "version": 3,
           "verified_version": None, "verified_text": None}
    row.update(over)
    return row


def _sess(sid, take_index, **ctx):
    return {"id": sid, "user_id": "u1", "take_index": take_index,
            "intake_context": {"topic": "My talk", **ctx}}


def _pick(index, text, snippet_id, session_id, take_index):
    return {"index": index, "text": text, "verbatim": text,
            "snippet_id": snippet_id, "session_id": session_id,
            "take_index": take_index}


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class SlideLinkageTests(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)

    def _get(self, *, sessions, row, cache=None, edit=None):
        with self.app.test_request_context():
            request.user_id = "u1"
            with patch("routes.v2.explore_ideal_text._arc_owned_by_caller",
                              return_value=(True, sessions)), \
                 patch("routes.v2.explore_ideal_text._moments_entitled", return_value=False), \
                 patch("routes.v2.explore_ideal_text._moment_explanations_map",
                              return_value={}), \
                 patch.object(db.ideal_text, "get_coach_arc_ideal_text",
                              return_value=row), \
                 patch.object(db, "get_user_ideal_edit",
                              return_value=edit), \
                 patch.object(db, "get_user_arc_ideal_notes",
                              return_value=None), \
                 patch.object(db, "get_best_presentation_cache",
                              return_value=cache, create=True), \
                 patch("services.ideal_text_block.maybe_assemble_ideal_text",
                       side_effect=AssertionError("composer ran on GET")) \
                    as composer:
                out = v2_explore_ideal_text.v2_explore_get_ideal_text.__wrapped__(ARC)
            resp, status = out if isinstance(out, tuple) else (out, 200)
            self.assertEqual(composer.call_count, 0)
            return resp.get_json(), status

    def test_aligned_pieces_carry_their_slide_index(self):
        sessions = [_sess("t1", 1, presentation_ref=DECK)]
        row = _row(auto_text="Para one.\n\nPara two.")
        cache = {"signature": "sig", "payload": {
            "presentation_ref": DECK,
            "slides": [_pick(3, "Para one.", "sn1", "t1", 1),
                       _pick(5, "Para two.", "sn2", "t1", 1)]}}
        body, status = self._get(sessions=sessions, row=row, cache=cache)
        self.assertEqual(status, 200)
        self.assertEqual(
            [(p["text"], p["slide_index"], p["snippet_id"])
             for p in body["pieces"]],
            [("Para one.", 3, "sn1"), ("Para two.", 5, "sn2")])

    def test_a_deckless_retake_keeps_the_first_deck(self):
        sessions = [_sess("t1", 1, presentation_ref=DECK), _sess("t2", 2)]
        body, status = self._get(sessions=sessions, row=_row())
        self.assertEqual(status, 200)
        self.assertEqual(body["presentation_ref"], DECK)


    def test_misaligned_counts_degrade_every_index_to_null(self):
        sessions = [_sess("t1", 1, presentation_ref=DECK)]
        # 3 cached picks, 2 served paragraphs (user edit / restructure /
        # stale cache) → nothing is provable → all null, FE zips or hides.
        row = _row(auto_text="Para one.\n\nPara two.")
        cache = {"signature": "sig", "payload": {
            "presentation_ref": DECK,
            "slides": [_pick(0, "Para one.", "sn1", "t1", 1),
                       _pick(1, "Extra.", "sn2", "t1", 1),
                       _pick(2, "Para two.", "sn3", "t1", 1)]}}
        body, _ = self._get(sessions=sessions, row=row, cache=cache)
        pieces = body["pieces"]
        self.assertEqual(len(pieces), 2)
        self.assertTrue(all(p["slide_index"] is None for p in pieces))
        # The paragraph identity itself still serves.
        self.assertEqual(pieces[1]["text"], "Para two.")


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ComposeFailureFallbackTests(unittest.TestCase):
    """SPEC §12.1 (founder 2026-08-14): a compose exception used to serve
    the RAW machine text — stored parts no longer joined, the parts block
    dropped off the wire, every lock invisible in one GET (field report
    #5). Now the pinned stored composition serves instead."""

    def test_compose_exception_serves_the_pinned_state_with_its_locks(self):
        app = Flask(__name__)
        sessions = [_sess("t1", 1, presentation_ref=DECK)]
        row = _row(auto_text="Machine text after a new take.")
        locked_rows = [
            {"id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "ord": 0,
             "text": "MY TYPED WORDS.",
             "locked_at": "2026-08-14T00:00:00Z"},
        ]
        with app.test_request_context():
            request.user_id = "u1"
            with patch.object(Config, "LIVING_TRANSCRIPT_ENABLED", True), \
                 patch("routes.v2.explore_ideal_text._arc_owned_by_caller",
                       return_value=(True, sessions)), \
                 patch("routes.v2.explore_ideal_text._moments_entitled",
                       return_value=False), \
                 patch("routes.v2.explore_ideal_text."
                       "_moment_explanations_map", return_value={}), \
                 patch("routes.v2.explore_ideal_text."
                       "_tracked_changes_block", return_value={}), \
                 patch.object(db.ideal_text, "get_coach_arc_ideal_text",
                              return_value=row), \
                 patch.object(db, "get_user_ideal_edit",
                              return_value=None), \
                 patch.object(db, "get_user_arc_ideal_notes",
                              return_value=None), \
                 patch.object(db, "get_ideal_text_parts",
                              return_value=locked_rows, create=True), \
                 patch("services.ideal_text_parts.compose_locked",
                       side_effect=RuntimeError("alignment blew up")):
                out = v2_explore_ideal_text.v2_explore_get_ideal_text.__wrapped__(ARC)
            resp, status = out if isinstance(out, tuple) else (out, 200)
            body = resp.get_json()
        self.assertEqual(status, 200)
        # The pinned composition — NOT the raw machine text.
        self.assertEqual(body["text"], "MY TYPED WORDS.")
        # And the lock is still on the wire.
        parts = body.get("parts")
        self.assertIsNotNone(parts)
        self.assertEqual([p["locked"] for p in parts], [True])


if __name__ == "__main__":
    unittest.main()
