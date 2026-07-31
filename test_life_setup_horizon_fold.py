"""Life Panel setup — item horizons folded onto strategy screens (2026-07-30).

The FE's document-upload flow pre-fills the eight STRATEGY screens from a
drafted document. It cannot fold on an item's `horizon`, because that is a
DIFFERENT vocabulary:

    item horizon      now | month | quarter | year | five_year | ten_year | twenty_year
    strategy horizon  daily | weekly | monthly | quarterly | yearly | five_year | ten_year | twenty_year

They coincide only on the long end, so five of the eight screens would never
fill. This pins the translation.

  H-1  the mapping is total over HORIZONS and lands inside STRATEGY_HORIZONS;
  H-2  `horizon` is left untouched — apply-proposed validates it against
       HORIZONS when it writes the item, so renaming it would break every
       applied row;
  H-3  an unmapped horizon yields None (the FE's remainder review), never a
       guess and never a drop;
  H-4  `weekly` has no source, documented rather than faked.

Run: ./venv/bin/python -m unittest test_life_setup_horizon_fold
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock

from services import life_panel as lp

# services.life_engine imports life_store -> services.db, which builds a real
# supabase client at import time and needs env we do not have here. Stub it in
# setUpModule (NOT at module top, which would leak into sibling test modules
# that decide at import time whether the real services.db is available), and
# RESTORE the original in tearDown — a bare pop() leaves a second
# DatabaseService singleton behind and silently breaks patches elsewhere.
_ORIG_SERVICES_DB = None


def setUpModule():
    global _ORIG_SERVICES_DB
    _ORIG_SERVICES_DB = sys.modules.get("services.db")
    stub = types.ModuleType("services.db")
    stub.db = MagicMock()
    stub.DatabaseService = MagicMock()
    sys.modules["services.db"] = stub


def tearDownModule():
    if _ORIG_SERVICES_DB is not None:
        sys.modules["services.db"] = _ORIG_SERVICES_DB
    else:
        sys.modules.pop("services.db", None)


class MappingTests(unittest.TestCase):

    def test_every_item_horizon_maps_into_a_real_strategy_horizon(self):
        # H-1: total over HORIZONS, and no mapping invents a screen that
        # doesn't exist.
        for h in lp.HORIZONS:
            got = lp.strategy_horizon_for(h)
            self.assertIsNotNone(got, f"{h} has no strategy screen")
            self.assertIn(got, lp.STRATEGY_HORIZONS, h)

    def test_the_four_short_horizons_are_renamed_not_dropped(self):
        self.assertEqual(lp.strategy_horizon_for("now"), "daily")
        self.assertEqual(lp.strategy_horizon_for("month"), "monthly")
        self.assertEqual(lp.strategy_horizon_for("quarter"), "quarterly")
        self.assertEqual(lp.strategy_horizon_for("year"), "yearly")

    def test_the_long_horizons_pass_through_unchanged(self):
        for h in ("five_year", "ten_year", "twenty_year"):
            self.assertEqual(lp.strategy_horizon_for(h), h)

    def test_weekly_has_no_item_source(self):
        # H-4: documented gap. Nothing in HORIZONS means "this week", so the
        # weekly screen cannot pre-fill from a document. Pinned so nobody
        # later "fixes" it by silently aliasing another horizon onto weekly.
        self.assertNotIn("weekly", lp.ITEM_TO_STRATEGY_HORIZON.values())

    def test_unknown_and_malformed_yield_none_never_a_guess(self):
        for bad in ("bogus", "", "   ", None, 42, [], {}, True):
            self.assertIsNone(lp.strategy_horizon_for(bad), repr(bad))

    def test_case_and_whitespace_tolerated(self):
        self.assertEqual(lp.strategy_horizon_for("  MONTH "), "monthly")


class DraftRowShapeTests(unittest.TestCase):
    """H-2/H-3 — what /setup/propose-from-document actually returns."""

    def _draft(self, items, parsed=None):
        from unittest.mock import patch
        from services import life_engine as eng
        with patch.object(eng, "_complete", return_value=(parsed or {"goals": []})), \
             patch.object(eng.life_importer, "plan_strategy",
                          return_value={"items": items}), \
             patch.object(eng, "_log_derivation", lambda *a, **k: None):
            return eng.draft_items_from_document("u1", "some document text")

    def test_strategy_horizon_is_added_alongside_horizon(self):
        out = self._draft([{"title": "ship it", "horizon": "quarter"}])
        self.assertEqual(out[0]["strategy_horizon"], "quarterly")
        # H-2: the original is untouched — apply-proposed needs it valid.
        self.assertEqual(out[0]["horizon"], "quarter")
        self.assertIn(out[0]["horizon"], lp.HORIZONS)

    def test_unmapped_horizon_becomes_null_not_missing(self):
        # H-3: the key is always present, so the FE can branch on its value
        # rather than on key existence.
        out = self._draft([{"title": "x", "horizon": None},
                           {"title": "y", "horizon": "bogus"}])
        for row in out:
            self.assertIn("strategy_horizon", row)
            self.assertIsNone(row["strategy_horizon"])

    def test_a_bet_row_still_carries_the_key(self):
        # Bets are deliberately NOT folded by the FE (their screen is behind
        # the upload step), but the BE must not special-case them — the FE
        # decides, from `bet`, and needs a consistent row shape.
        out = self._draft([{"title": "b", "horizon": "year", "bet": "one"}])
        self.assertEqual(out[0]["strategy_horizon"], "yearly")
        self.assertEqual(out[0]["bet"], "one")

    def test_non_dict_rows_do_not_crash_the_draft(self):
        out = self._draft([{"title": "ok", "horizon": "now"}, None, "junk"])
        self.assertEqual(out[0]["strategy_horizon"], "daily")

    def test_no_items_is_not_an_error(self):
        self.assertEqual(self._draft([]), [])


class HintedDraftRowShapeTests(unittest.TestCase):
    """H-5 — where the document dock's kind hint and this fold meet.

    The dock lets the FE say which panel view the user was standing on, and
    the rows drafted for that kind LEAD the response. Those rows are phrases,
    principles and wins — none of which carries an item `horizon` at all.

    They must still carry `strategy_horizon`, because H-3 is the FE branching
    on its VALUE rather than on the key being there, and these are the first
    rows it is handed. Which is why the stamp runs AFTER the hinted prepend,
    not before it — the ordering is the contract, so it is pinned here.
    """

    def _draft(self, items, lines, kind):
        from unittest.mock import patch
        from services import life_engine as eng
        with patch.object(eng, "_complete", return_value={"goals": []}), \
             patch.object(eng.life_importer, "plan_strategy",
                          return_value={"items": items}), \
             patch.object(eng.life_importer, "plan_document_lines",
                          return_value=lines), \
             patch.object(eng, "_log_derivation", lambda *a, **k: None):
            return eng.draft_items_from_document("u1", "text", kind=kind)

    def test_the_hinted_row_leads_and_still_carries_the_key(self):
        out = self._draft([{"title": "ship it", "horizon": "quarter"}],
                          [{"title": "hold the line", "kind": "phrase"}],
                          "phrase")
        # The hinted row leads — the user is standing on /panel/phrases.
        self.assertEqual(out[0]["title"], "hold the line")
        # And it carries the key, mapped to None: a phrase has no horizon, so
        # it routes to the FE's remainder review instead of being folded onto
        # a dated strategy screen. That is the right screen for it.
        self.assertIn("strategy_horizon", out[0])
        self.assertIsNone(out[0]["strategy_horizon"])
        # The base row underneath is folded exactly as it was before.
        self.assertEqual(out[1]["strategy_horizon"], "quarterly")

    def test_no_drafted_row_hinted_or_not_lacks_the_field(self):
        # The invariant stated over the WHOLE response rather than per-row:
        # this is the one the FE actually leans on, and the one that breaks
        # if the stamp ever moves back above the prepend.
        out = self._draft([{"title": "a", "horizon": "now"},
                           {"title": "b", "horizon": None}],
                          [{"title": "p1"}, {"title": "p2"}],
                          "principle")
        self.assertEqual(len(out), 4)
        for row in out:
            self.assertIn("strategy_horizon", row)

    def test_a_hint_the_base_pass_covers_folds_as_it_always_did(self):
        # `goal` is not a lines kind, so no second pass runs and the result
        # is the un-hinted one — including the fold.
        out = self._draft([{"title": "ship it", "horizon": "month"}],
                          [{"title": "never asked for"}],
                          "goal")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["strategy_horizon"], "monthly")


if __name__ == "__main__":
    unittest.main()
