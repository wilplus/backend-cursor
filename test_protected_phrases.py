"""willab — protected phrases (founder 2026-07-20, gradual refinement PR-3).

Pinned here, rule by rule:
  4a. RECURRING WORDING — a phrase in >= 2 spoken takes is the speaker's
      voice: recurrence detection + the noise floor;
  4b. USER-EDIT INHERITANCE — the edit decomposes into phrase decisions
      (word-level difflib, marker-stripped); insertions skip, rewrites
      bail, deletions carry an empty replacement that ONLY a user_edit
      row may bake.

Run: python3 -m unittest test_protected_phrases
"""
from __future__ import annotations

import unittest

from services.ideal_decision_ledger import bake_piece
from services.protected_phrases import (
    collect_take_texts,
    decompose_user_edit,
    phrase_recurs,
    record_user_edit_decisions,
)


class PhraseRecursTests(unittest.TestCase):
    TAKES = ["we always say boom town in the demo",
             "and boom town lands the close every time",
             "a third take without the phrase"]

    def test_two_takes_protect(self):
        self.assertTrue(phrase_recurs("Boom  Town", self.TAKES))

    def test_one_take_does_not(self):
        self.assertFalse(phrase_recurs("lands the close", self.TAKES))

    def test_noise_floor(self):
        self.assertFalse(phrase_recurs("the", self.TAKES))
        self.assertFalse(phrase_recurs("", self.TAKES))
        self.assertFalse(phrase_recurs(None, self.TAKES))

    def test_empty_corpus_never_protects(self):
        self.assertFalse(phrase_recurs("boom town", []))


class CollectTakeTextsTests(unittest.TestCase):
    class _Db:
        def get_arc_sessions(self, arc_id):
            return [
                {"id": "t1", "take_index": 1, "recording_kind": "spoken"},
                {"id": "r1", "take_index": 1, "recording_kind": "read",
                 "paired_session_id": "t1"},
                {"id": "t2", "take_index": 2, "recording_kind": "spoken"},
            ]

        def get_snippets_by_session(self, sid):
            return {"t1": [{"transcript": "Hello  WORLD"},
                           {"transcript": "part two"}],
                    "t2": [{"transcript": "second take"}],
                    "r1": [{"transcript": "read text must not count"}],
                    }.get(sid, [])

    def test_spoken_only_normalized_joined(self):
        texts = collect_take_texts(self._Db(), "a1")
        self.assertEqual(texts, ["hello world part two", "second take"])

    def test_best_effort_on_broken_db(self):
        self.assertEqual(collect_take_texts(object(), "a1"), [])
        self.assertEqual(collect_take_texts(self._Db(), None), [])


class DecomposeTests(unittest.TestCase):
    def test_word_replace_block(self):
        out = decompose_user_edit("we kept showing up every day",
                                  "we stayed relentless every day")
        self.assertEqual(out, [{"old": "kept showing up",
                                "new": "stayed relentless"}])

    def test_deletion_block(self):
        out = decompose_user_edit("we really truly shipped it",
                                  "we shipped it")
        self.assertEqual(out, [{"old": "really truly", "new": ""}])

    def test_pure_insertion_skipped(self):
        out = decompose_user_edit("we shipped it",
                                  "we quickly shipped it")
        self.assertEqual(out, [])

    def test_rewrite_bails_to_nothing(self):
        out = decompose_user_edit(
            "alpha beta gamma delta epsilon zeta",
            "one two three four five six seven eight")
        self.assertEqual(out, [])

    def test_markers_stripped_before_diff(self):
        base = ("[[moment:s1|t1]]we {{orange:kept showing up}} every "
                "day[[/moment]]")
        out = decompose_user_edit(base, "we stayed strong every day")
        self.assertEqual(out, [{"old": "kept showing up",
                                "new": "stayed strong"}])

    def test_identical_or_empty_is_empty(self):
        self.assertEqual(decompose_user_edit("same", "same"), [])
        self.assertEqual(decompose_user_edit("", "x"), [])
        self.assertEqual(decompose_user_edit(None, None), [])


class UserEditBakeTests(unittest.TestCase):
    def test_user_deletion_bakes(self):
        row = {"kind": "replace", "target_phrase": "really truly",
               "display_phrase": "really truly", "replacement_text": "",
               "decision": "approved", "source": "user_edit"}
        out = bake_piece("we really truly shipped it", [row])
        self.assertEqual(out, "we shipped it")

    def test_generated_empty_replacement_never_wipes(self):
        row = {"kind": "replace", "target_phrase": "really truly",
               "display_phrase": "really truly", "replacement_text": "",
               "decision": "approved", "source": "user_star"}
        text = "we really truly shipped it"
        self.assertEqual(bake_piece(text, [row]), text)


class RecordUserEditTests(unittest.TestCase):
    class _Db:
        def __init__(self):
            self.rows = []

        def upsert_ideal_decision(self, **kw):
            self.rows.append(kw)
            return True

    def test_blocks_land_as_approved_user_edit_rows(self):
        db = self._Db()
        n = record_user_edit_decisions(
            db, "a1",
            base_text="we kept showing up and really truly shipped it",
            user_text="we stayed relentless and shipped it",
            version=2)
        self.assertEqual(n, len(db.rows))
        self.assertGreaterEqual(n, 1)
        for r in db.rows:
            self.assertEqual(r["kind"], "replace")
            self.assertEqual(r["decision"], "approved")
            self.assertEqual(r["source"], "user_edit")
            self.assertEqual(r["version"], 2)

    def test_rewrite_writes_nothing(self):
        db = self._Db()
        n = record_user_edit_decisions(
            db, "a1", base_text="alpha beta gamma delta",
            user_text="totally different words entirely here now",
            version=1)
        self.assertEqual((n, db.rows), (0, []))

    def test_broken_db_never_raises(self):
        n = record_user_edit_decisions(
            object(), "a1", base_text="a b c", user_text="a x c")
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
