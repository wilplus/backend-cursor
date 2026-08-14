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

    def test_an_oversize_emphasize_keeps_its_words_and_loses_its_paint(self):
        """§F.4 (founder 2026-08-10) — emphasis is a UNIT-window
        intervention. A moment accept's target is the WHOLE snippet
        transcript, and painting it wrapped sentences in orange. The row
        stays approved; only the paint is refused."""
        phrase = " ".join(["spoken"] * 30)
        text = f"Start. {phrase} End."
        out = bake_piece(text, [_row(kind="emphasize", phrase=phrase,
                                     repl=None)])
        self.assertEqual(out, text)
        self.assertNotIn("{{orange:", out)

    def test_the_bake_ceiling_is_the_shared_constant(self):
        from services.ideal_text_block import ACCENT_WINDOW_MAX_WORDS
        at = " ".join(["w"] * ACCENT_WINDOW_MAX_WORDS)
        over = " ".join(["w"] * (ACCENT_WINDOW_MAX_WORDS + 1))
        self.assertIn("{{orange:", bake_piece(
            f"a {at} b", [_row(kind="emphasize", phrase=at, repl=None)]))
        self.assertNotIn("{{orange:", bake_piece(
            f"a {over} b", [_row(kind="emphasize", phrase=over, repl=None)]))

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


class LaneClassTests(unittest.TestCase):
    """§12.3 — the BE half of the deck's class mapping, one home. The
    precedence pins mirror FE displayKind.ts (source before kind, kind
    before why); the contract test below keeps the two from drifting."""

    def test_source_beats_kind(self):
        from services.ideal_decision_ledger import lane_class
        # An acoustic swap is kind='replace' on the wire but IS delivery.
        self.assertEqual(
            lane_class("replace", source="acoustic_swap"), "delivery")

    def test_kind_classes(self):
        from services.ideal_decision_ledger import lane_class
        self.assertEqual(lane_class("emphasize"), "style")
        self.assertEqual(lane_class("bold"), "style")
        self.assertEqual(lane_class("advice"), "flow")

    def test_why_routes_cross_take_to_flow(self):
        from services.ideal_decision_ledger import lane_class
        for why in ("energy", "steadiness", "coverage", "overall"):
            self.assertEqual(lane_class("replace", why=why), "flow")

    def test_default_is_clarity(self):
        from services.ideal_decision_ledger import lane_class
        self.assertEqual(lane_class("replace"), "clarity")
        self.assertEqual(lane_class("polish"), "clarity")
        self.assertEqual(lane_class(None), "clarity")


class IntentKeysTests(unittest.TestCase):
    def test_pairs_from_rows_that_know_where(self):
        from services.ideal_decision_ledger import intent_keys
        rows = [
            {"slide_index": 2, "lane_class": "clarity"},
            {"slide_index": 0, "lane_class": "style"},
            {"slide_index": None, "lane_class": "clarity"},   # legacy row
            {"slide_index": True, "lane_class": "clarity"},   # bool ≠ slide
            {"slide_index": 3, "lane_class": None},           # legacy row
        ]
        self.assertEqual(intent_keys(rows),
                         {(2, "clarity"), (0, "style")})
        self.assertEqual(intent_keys([]), set())
        self.assertEqual(intent_keys(None), set())


class RecordCarriesIntentTests(unittest.TestCase):
    """record_star_decision writes the §12.3 intent key alongside the
    phrase key — and never invents one it does not have."""

    class _Db:
        def __init__(self):
            self.kw = None

        def upsert_ideal_decision(self, **kw):
            self.kw = kw
            return True

    def test_slide_and_class_ride_the_upsert(self):
        from services.ideal_decision_ledger import record_star_decision
        db = self._Db()
        ok = record_star_decision(
            db, "arc-1", suggestion={"trigger": "unconfident"},
            target="document_replace", action="dismissed",
            target_text="the words", snippet_id="sn1", slide_index=4)
        self.assertTrue(ok)
        self.assertEqual(db.kw["slide_index"], 4)
        self.assertEqual(db.kw["lane_class"], "clarity")

    def test_emphasize_records_style(self):
        from services.ideal_decision_ledger import record_star_decision
        db = self._Db()
        record_star_decision(
            db, "arc-1", suggestion={}, target="document_bold",
            action="applied", target_text="the words",
            snippet_id="sn1", slide_index=1)
        self.assertEqual(db.kw["lane_class"], "style")

    def test_unknown_slide_stays_none(self):
        from services.ideal_decision_ledger import record_star_decision
        db = self._Db()
        record_star_decision(
            db, "arc-1", suggestion={}, target="document_replace",
            action="dismissed", target_text="the words",
            snippet_id="sn1", slide_index=True)   # bool ≠ slide
        self.assertIsNone(db.kw["slide_index"])


if __name__ == "__main__":
    unittest.main()
