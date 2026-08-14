"""GET /v2/explore/arc/<arc_id>/ideal-text — slide linkage (FE handoff
2026-08-03, FE PR #222): the two additive fields the interleaved reading
view needs cross-device:

  * top-level `presentation_ref` — the arc's served deck PDF url (first
    non-null across takes in take order, never clobbered by a deckless
    retake);
  * `pieces[]` — one entry per "\n\n"-paragraph of the served `text`,
    with `slide_index` attached ONLY when the machine assembly's piece
    list aligns 1:1 with the served paragraphs (anything weaker degrades
    to null and the FE falls back to its exact-count zip).

The provenance must NEVER put the composer (its LLM pass included) on
this GET — the legacy path reads only the persisted compose cache.

Run: python3 -m unittest test_ideal_text_slide_linkage
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

try:
    from flask import Flask, request
    from routes import v2_routes as v2
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    v2 = None
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
                 patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value=row), \
                 patch.object(v2.db, "get_user_ideal_edit",
                              return_value=edit), \
                 patch.object(v2.db, "get_user_arc_ideal_notes",
                              return_value=None), \
                 patch.object(v2.db, "get_best_presentation_cache",
                              return_value=cache, create=True):
                out = v2.v2_explore_get_ideal_text.__wrapped__(ARC)
            resp, status = out if isinstance(out, tuple) else (out, 200)
            return resp.get_json(), status

    def test_deck_ref_and_aligned_slide_indexes_served(self):
        sessions = [_sess("t1", 1, presentation_ref=DECK),
                    _sess("t2", 2, presentation_ref=DECK)]
        row = _row(auto_text="First slide's words.\n\nSecond slide's words.")
        cache = {"signature": "sig", "payload": {
            "presentation_ref": DECK,
            "slides": [
                _pick(0, "First slide's words.", "sn1", "t1", 1),
                _pick(1, "Second slide's words.", "sn2", "t2", 2),
                # A slide with no pick — assemble skips it, so must we.
                _pick(2, "", None, None, None),
            ]}}
        body, status = self._get(sessions=sessions, row=row, cache=cache)
        self.assertEqual(status, 200)
        self.assertEqual(body["presentation_ref"], DECK)
        pieces = body["pieces"]
        self.assertEqual(len(pieces), 2)
        self.assertEqual([p["piece_key"] for p in pieces], [0, 1])
        self.assertEqual([p["slide_index"] for p in pieces], [0, 1])
        self.assertEqual(pieces[0]["snippet_id"], "sn1")
        self.assertEqual(pieces[0]["take_session_id"], "t1")
        self.assertEqual(pieces[1]["take_index"], 2)
        self.assertEqual(pieces[0]["status"], "settled")
        self.assertIsNone(pieces[0]["challenger"])
        self.assertEqual(pieces[0]["text"], "First slide's words.")

    def test_deckless_retake_never_clobbers_the_deck_ref(self):
        # Take 2 dropped presentation_ref — the arc still has its deck.
        sessions = [_sess("t1", 1, presentation_ref=DECK), _sess("t2", 2)]
        body, _ = self._get(sessions=sessions, row=_row())
        self.assertEqual(body["presentation_ref"], DECK)

    def test_deckless_arc_serves_null_ref_and_null_indexes(self):
        sessions = [_sess("t1", 1), _sess("t2", 2)]
        row = _row(auto_text="One paragraph.\n\nAnother paragraph.")
        # Even with a (deckless, section-keyed) compose cache present the
        # indexes must NOT attach — a section is not a deck page.
        cache = {"signature": "sig", "payload": {
            "presentation_ref": None,
            "slides": [_pick(0, "One paragraph.", "sn1", "t1", 1),
                       _pick(1, "Another paragraph.", "sn2", "t1", 1)]}}
        body, _ = self._get(sessions=sessions, row=row, cache=cache)
        self.assertIsNone(body["presentation_ref"])
        self.assertEqual(len(body["pieces"]), 2)
        self.assertTrue(all(p["slide_index"] is None
                            for p in body["pieces"]))

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

    def test_no_cache_row_serves_null_indexes_without_composing(self):
        sessions = [_sess("t1", 1, presentation_ref=DECK)]
        row = _row(auto_text="Para one.\n\nPara two.")
        from services import best_presentation as bp
        with patch.object(bp, "build_best_presentation",
                          side_effect=AssertionError(
                              "composer must never run on the GET")):
            body, status = self._get(sessions=sessions, row=row, cache=None)
        self.assertEqual(status, 200)
        self.assertEqual(body["presentation_ref"], DECK)
        self.assertEqual(len(body["pieces"]), 2)
        self.assertTrue(all(p["slide_index"] is None
                            for p in body["pieces"]))

    def test_empty_text_serves_empty_pieces(self):
        sessions = [_sess("t1", 1, presentation_ref=DECK)]
        body, _ = self._get(sessions=sessions,
                            row=_row(auto_text="", text="", version=None))
        self.assertEqual(body["pieces"], [])

    def test_reads_never_resolve_the_deck_ref(self):
        # A paired re-read carrying a deck ref is not a take — it must not
        # become the arc's deck.
        read = {"id": "r1", "user_id": "u1", "take_index": None,
                "recording_kind": "read", "paired_session_id": "t1",
                "intake_context": {"presentation_ref": "https://x/wrong.pdf"}}
        sessions = [read, _sess("t1", 1)]
        body, _ = self._get(sessions=sessions, row=_row())
        self.assertIsNone(body["presentation_ref"])


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class MasterDocumentProvenanceTests(unittest.TestCase):
    """Under the master flag the skeleton blocks own slide_index — a
    single-block document attaches it; the block's real status rides."""

    def setUp(self):
        self.app = Flask(__name__)

    def _get(self, *, blocks, text):
        sessions = [_sess("t1", 1, presentation_ref=DECK)]
        row = _row(auto_text=text)
        with self.app.test_request_context():
            request.user_id = "u1"
            with patch.dict(os.environ,
                            {"LIVING_TRANSCRIPT_ENABLED": "1",
                             "MASTER_DOCUMENT_ENABLED": "1"}), \
                 patch("routes.v2.explore_ideal_text._arc_owned_by_caller",
                              return_value=(True, sessions)), \
                 patch("routes.v2.explore_ideal_text._moments_entitled", return_value=False), \
                 patch("routes.v2.explore_ideal_text._moment_explanations_map",
                              return_value={}), \
                 patch("routes.v2.explore_ideal_text._ideal_save_state",
                              return_value={}), \
                 patch("routes.v2.explore_ideal_text._tracked_changes_block",
                              return_value={}), \
                 patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value=row), \
                 patch.object(v2.db, "get_user_ideal_edit",
                              return_value=None), \
                 patch.object(v2.db, "get_user_arc_ideal_notes",
                              return_value=None), \
                 patch.object(v2.db, "list_ideal_text_blocks",
                              return_value=blocks, create=True):
                out = v2.v2_explore_get_ideal_text.__wrapped__(ARC)
            resp, status = out if isinstance(out, tuple) else (out, 200)
            return resp.get_json(), status

    def test_single_block_attaches_the_blocks_slide(self):
        blocks = [{"block_key": 0, "active": True, "status": "settled",
                   "slide_index": 4,
                   "incumbent_take_session_id": "t1",
                   "incumbent_take_index": 1,
                   "incumbent_pieces": [{"snippet_id": "sn1",
                                         "text": "The words."}],
                   "challenger_take_index": None}]
        body, status = self._get(blocks=blocks, text="The words.")
        self.assertEqual(status, 200)
        pieces = body["pieces"]
        self.assertEqual(len(pieces), 1)
        self.assertEqual(pieces[0]["slide_index"], 4)
        self.assertEqual(pieces[0]["snippet_id"], "sn1")
        self.assertEqual(pieces[0]["status"], "settled")
        # The keyed pill→picker join (FE picker handoff 2026-08-03).
        self.assertEqual(pieces[0]["block_key"], 0)

    def test_pending_upgrade_status_rides_honestly(self):
        blocks = [{"block_key": 0, "active": True,
                   "status": "pending_upgrade", "slide_index": 0,
                   "incumbent_take_session_id": "t1",
                   "incumbent_take_index": 1,
                   "incumbent_pieces": [{"snippet_id": "sn1",
                                         "text": "The words."}],
                   "challenger_take_index": 2}]
        body, _ = self._get(blocks=blocks, text="The words.")
        self.assertEqual(body["pieces"][0]["status"], "pending_upgrade")
        self.assertEqual(body["pieces"][0]["challenger"], 2)

    def test_multi_block_single_paragraph_degrades_to_null(self):
        # A LEGACY/stale persisted text: two blocks but one served
        # paragraph (the pre-§11.1 space-join wall). The mirror emits one
        # row per would-be paragraph (2), the wall has 1 — counts
        # disagree, every index degrades to null rather than guessing.
        # Self-heals on the next take, when the capped assembly persists.
        blocks = [
            {"block_key": 0, "active": True, "status": "settled",
             "slide_index": 0, "incumbent_take_session_id": "t1",
             "incumbent_take_index": 1,
             "incumbent_pieces": [{"snippet_id": "sn1", "text": "One."}],
             "challenger_take_index": None},
            {"block_key": 10, "active": True, "status": "settled",
             "slide_index": 1, "incumbent_take_session_id": "t1",
             "incumbent_take_index": 1,
             "incumbent_pieces": [{"snippet_id": "sn2", "text": "Two."}],
             "challenger_take_index": None},
        ]
        body, _ = self._get(blocks=blocks, text="One. Two.")
        self.assertEqual(len(body["pieces"]), 1)
        self.assertIsNone(body["pieces"][0]["slide_index"])

    def test_two_blocks_two_paragraphs_both_attach(self):
        # The §11.1 world: block boundary = paragraph boundary, so the
        # capped assembly's text aligns 1:1 and both slides attach.
        blocks = [
            {"block_key": 0, "active": True, "status": "settled",
             "slide_index": 0, "incumbent_take_session_id": "t1",
             "incumbent_take_index": 1,
             "incumbent_pieces": [{"snippet_id": "sn1", "text": "One."}],
             "challenger_take_index": None},
            {"block_key": 10, "active": True, "status": "settled",
             "slide_index": 1, "incumbent_take_session_id": "t1",
             "incumbent_take_index": 1,
             "incumbent_pieces": [{"snippet_id": "sn2", "text": "Two."}],
             "challenger_take_index": None},
        ]
        body, _ = self._get(blocks=blocks, text="One.\n\nTwo.")
        self.assertEqual([p["slide_index"] for p in body["pieces"]],
                         [0, 1])
        self.assertEqual([p["block_key"] for p in body["pieces"]],
                         [0, 10])

    def test_a_capped_block_serves_one_row_per_paragraph_same_slide(self):
        # SPEC §11.1: a long block packs into SEVERAL served paragraphs.
        # The provenance mirror runs the same packer over the same rows,
        # so the counts align and every sibling paragraph carries the
        # block's slide and key. (3 × ~90-char pieces pack [2, 1] under
        # the 200 cap — the served text just has to agree on the count.)
        long_piece = "x" * 90
        blocks = [
            {"block_key": 7, "active": True, "status": "settled",
             "slide_index": 4, "incumbent_take_session_id": "t1",
             "incumbent_take_index": 1,
             "incumbent_pieces": [
                 {"snippet_id": f"sn{i}", "text": long_piece}
                 for i in range(3)],
             "challenger_take_index": None},
        ]
        body, _ = self._get(blocks=blocks,
                            text="first served paragraph\n\nsecond one")
        self.assertEqual([p["slide_index"] for p in body["pieces"]],
                         [4, 4])
        self.assertEqual([p["block_key"] for p in body["pieces"]],
                         [7, 7])
        self.assertEqual([p["snippet_id"] for p in body["pieces"]],
                         ["sn0", "sn2"])


@unittest.skipIf(Flask is None, f"flask/app import failed: {_IMPORT_ERROR}")
class LivingTranscriptProvenanceTests(unittest.TestCase):
    """The two defects that stripped every slide off the read surface
    (founder 2026-08-11).

    Both were invisible: no error, no null field, just `slide_index: null`
    everywhere and a deck with nothing to scroll through."""

    def _prov(self, doc, **kw):
        from routes.v2 import explore_ideal_text as mod
        # Imported INSIDE the function, so the patch has to land on the
        # source module rather than this one's namespace.
        with patch("services.transcript_document.build_transcript_document",
                   return_value=doc), \
                patch("services.ideal_text_block._living_transcript_enabled",
                      return_value=True), \
                patch("services.master_document.master_document_enabled",
                      return_value=False), \
                patch.object(mod.db, "get_snippets_by_session",
                             return_value=[], create=True):
            return mod._ideal_piece_provenance(ARC, **kw)

    def test_provenance_is_counted_in_PARAGRAPHS_not_snippets(self):
        # THE BUG: the caller aligns this list against the served text's
        # "\n\n" paragraphs BY LENGTH. Returning one row per snippet meant
        # that on any take where a slide held more than one piece the counts
        # disagreed, the alignment test failed, and every slide attachment
        # was silently dropped.
        doc = {
            "take_session_id": "t1",
            "pieces": [{"snippet_id": "a", "slide_index": 0},
                       {"snippet_id": "b", "slide_index": 0},
                       {"snippet_id": "c", "slide_index": 1}],
            "paragraphs": [
                {"snippet_id": "a", "slide_index": 0, "take_session_id": "t1",
                 "take_index": 1},
                {"snippet_id": "c", "slide_index": 1, "take_session_id": "t1",
                 "take_index": 1},
            ],
        }
        rows = self._prov(doc)
        self.assertEqual(len(rows), 2)          # paragraphs, not the 3 pieces
        self.assertEqual([r["slide_index"] for r in rows], [0, 1])

    def test_slide_zero_survives(self):
        # `or`-style falsiness on a 0 index would blank the FIRST slide of
        # every deck and nothing else — the kind of bug that reads as "the
        # intro is special".
        doc = {"take_session_id": "t1", "pieces": [],
               "paragraphs": [{"snippet_id": "a", "slide_index": 0,
                               "take_session_id": "t1", "take_index": 1}]}
        self.assertEqual(self._prov(doc)[0]["slide_index"], 0)

    def test_an_arc_with_NO_UPLOADED_DECK_still_attaches(self):
        # THE MOCK-DECK BUG: the deckless guard was applied to every lane,
        # including this one. But the cutter buckets words against the slides
        # the speaker actually SAW, and the built-in deck has slides and taps
        # without ever producing a PDF — so a whole class of recordings got
        # no slide attachment at all, for a reason that only applies to the
        # legacy compose lane.
        doc = {"take_session_id": "t1", "pieces": [],
               "paragraphs": [{"snippet_id": "a", "slide_index": 2,
                               "take_session_id": "t1", "take_index": 1}]}
        rows = self._prov(doc, deckless_ok=False)
        self.assertEqual([r["slide_index"] for r in rows], [2])

    def test_the_LEGACY_lane_stays_deckless_gated(self):
        # It keys picks by SECTION index, which is not a deck page. The guard
        # was right; it was just standing in the wrong place.
        from routes.v2 import explore_ideal_text as mod
        with patch("services.ideal_text_block._living_transcript_enabled",
                   return_value=False), \
                patch("services.master_document.master_document_enabled",
                      return_value=False):
            self.assertEqual(
                mod._ideal_piece_provenance(ARC, deckless_ok=False), [])


if __name__ == "__main__":
    unittest.main()
