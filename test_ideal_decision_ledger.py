"""willab — the ideal-text decision ledger (founder 2026-07-20, gradual
refinement PR-2).

Pinned here, rule by rule:
  1. APPROVED = BAKED forever forward — bake_piece applies replaces/
     polishes/emphasizes wherever the phrase still occurs, never grafts
     onto absent phrases, never double-wraps an orange;
  2. DISMISSED = REMEMBERED — ledger keys cover both decisions;
  3. record_star_decision maps star taps → ledger rows (kind mapping,
     revert = clean slate);
  4. keys are PHRASES, not snippets (survive re-picking across takes).

Run: python3 -m unittest test_ideal_decision_ledger
"""
from __future__ import annotations

import unittest

from services.ideal_decision_ledger import (
    bake_piece,
    ledger_keys,
    normalize_phrase,
    record_star_decision,
)


def _row(kind="replace", phrase="the old words", repl="the new words",
         decision="approved", display=None):
    return {"kind": kind, "target_phrase": normalize_phrase(phrase),
            "display_phrase": display or phrase,
            "replacement_text": repl, "decision": decision}


class NormalizeTests(unittest.TestCase):
    def test_case_and_whitespace_fold(self):
        self.assertEqual(normalize_phrase("  The   Turn \n"), "the turn")

    def test_non_string_is_empty(self):
        self.assertEqual(normalize_phrase(None), "")
        self.assertEqual(normalize_phrase(42), "")


class LedgerKeysTests(unittest.TestCase):
    def test_both_decisions_count(self):
        keys = ledger_keys([_row(decision="approved"),
                            _row(kind="emphasize", phrase="keep this",
                                 decision="dismissed")])
        self.assertIn(("replace", "the old words"), keys)
        self.assertIn(("emphasize", "keep this"), keys)


class BakePieceTests(unittest.TestCase):
    def test_replace_bakes_where_phrase_occurs(self):
        out = bake_piece("Start. the old words. End.",
                         [_row()])
        self.assertEqual(out, "Start. the new words. End.")

    def test_polish_bakes_like_replace(self):
        out = bake_piece("we was ready", [_row(
            kind="polish", phrase="we was ready", repl="we were ready")])
        self.assertEqual(out, "we were ready")

    def test_emphasize_wraps_orange_once(self):
        out = bake_piece("hear this line now", [_row(
            kind="emphasize", phrase="this line", repl=None)])
        self.assertEqual(out, "hear {{orange:this line}} now")
        # A second bake pass over the baked text must not double-wrap.
        out2 = bake_piece(out, [_row(
            kind="emphasize", phrase="this line", repl=None)])
        self.assertEqual(out2, out)

    def test_absent_phrase_is_never_grafted(self):
        # Founder: changes apply "if they apply" — a different take's
        # phrasing won → the old decision silently doesn't match.
        text = "completely different words won this section"
        self.assertEqual(bake_piece(text, [_row()]), text)

    def test_dismissed_rows_never_bake(self):
        text = "Start. the old words. End."
        self.assertEqual(
            bake_piece(text, [_row(decision="dismissed")]), text)

    def test_case_insensitive_fallback_match(self):
        out = bake_piece("Start. The Old Words. End.", [_row()])
        self.assertEqual(out, "Start. the new words. End.")

    def test_longest_phrase_wins_overlap(self):
        rows = [_row(phrase="the old", repl="SHORT"),
                _row(phrase="the old words", repl="LONG")]
        out = bake_piece("say the old words twice", rows)
        self.assertIn("LONG", out)
        self.assertNotIn("SHORT", out)

    def test_noop_replacement_skipped(self):
        text = "the old words stay"
        self.assertEqual(
            bake_piece(text, [_row(repl="the old words")]), text)

    def test_non_string_passthrough(self):
        self.assertIsNone(bake_piece(None, [_row()]))
        self.assertEqual(bake_piece("", [_row()]), "")


class _FakeDb:
    def __init__(self):
        self.upserts, self.deletes = [], []

    def upsert_ideal_decision(self, **kw):
        self.upserts.append(kw)
        return True

    def delete_ideal_decision(self, arc_id, kind, phrase):
        self.deletes.append((arc_id, kind, phrase))
        return True


class RecordStarDecisionTests(unittest.TestCase):
    def test_applied_replace_with_polish_trigger_maps_to_polish(self):
        db = _FakeDb()
        ok = record_star_decision(
            db, "a1", suggestion={"trigger": "polish",
                                  "replacement_text": "smoother"},
            target="moment_replace", action="applied",
            target_text="The Rough  Span", snippet_id="s1", version=2)
        self.assertTrue(ok)
        row = db.upserts[0]
        self.assertEqual(row["kind"], "polish")
        self.assertEqual(row["decision"], "approved")
        self.assertEqual(row["target_phrase"], "the rough span")
        self.assertEqual(row["display_phrase"], "The Rough  Span")
        self.assertEqual(row["replacement_text"], "smoother")
        self.assertEqual(row["version"], 2)

    def test_applied_threat_replace_and_emphasize_kinds(self):
        db = _FakeDb()
        record_star_decision(
            db, "a1", suggestion={"trigger": "threat",
                                  "replacement_text": "steady"},
            target="moment_replace", action="applied", target_text="x y")
        record_star_decision(
            db, "a1", suggestion={"trigger": "charisma"},
            target="moment_emphasize", action="applied", target_text="z")
        self.assertEqual(db.upserts[0]["kind"], "replace")
        self.assertEqual(db.upserts[1]["kind"], "emphasize")
        self.assertIsNone(db.upserts[1]["replacement_text"])

    def test_dismissed_records_dismissed(self):
        db = _FakeDb()
        record_star_decision(
            db, "a1", suggestion={}, target="moment_emphasize",
            action="dismissed", target_text="keep away")
        self.assertEqual(db.upserts[0]["decision"], "dismissed")

    def test_reverted_deletes_the_row(self):
        db = _FakeDb()
        ok = record_star_decision(
            db, "a1", suggestion={"trigger": "polish"},
            target="moment_replace", action="reverted",
            target_text="The Rough Span")
        self.assertTrue(ok)
        self.assertEqual(db.deletes, [("a1", "polish", "the rough span")])
        self.assertEqual(db.upserts, [])

    def test_bad_inputs_are_inert(self):
        db = _FakeDb()
        self.assertFalse(record_star_decision(
            db, None, suggestion={}, target="moment_replace",
            action="applied", target_text="x"))
        self.assertFalse(record_star_decision(
            db, "a1", suggestion={}, target="moment_structure",
            action="applied", target_text="x"))
        self.assertFalse(record_star_decision(
            db, "a1", suggestion={}, target="moment_replace",
            action="preferred", target_text="x"))
        self.assertFalse(record_star_decision(
            db, "a1", suggestion={}, target="moment_replace",
            action="applied", target_text="   "))
        self.assertEqual((db.upserts, db.deletes), ([], []))


if __name__ == "__main__":
    unittest.main()
