"""Life Panel setup — item horizons folded onto strategy screens (2026-07-30).

The FE's document-upload flow pre-fills the eight STRATEGY screens from a
drafted document. It cannot fold on an item's `horizon`, because that is a
DIFFERENT vocabulary:

    item horizon      now | week | month | quarter | year | five_year | ten_year | twenty_year
    strategy horizon  daily | weekly | monthly | quarterly | yearly | five_year | ten_year | twenty_year

They coincide only on the long end, so five of the eight screens would never
fill. This pins the translation.

  H-1  the mapping is total over HORIZONS and lands inside STRATEGY_HORIZONS;
  H-2  `horizon` is left untouched — apply-proposed validates it against
       HORIZONS when it writes the item, so renaming it would break every
       applied row;
  H-3  an unmapped horizon yields None (the FE's remainder review), never a
       guess and never a drop;
  H-4  `week` reaches the weekly screen, and it is the ONLY thing that does —
       superseding the original H-4, which pinned the gap where "weekly" had
       no item-horizon source at all (closed 2026-07-31);
  H-5  the kind hint and the fold meet: every drafted row carries the field,
       hinted rows included;
  H-6  a database without the week migration DOWNGRADES the row, it never
       loses it.

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

    def test_week_reaches_the_weekly_screen(self):
        # H-4: the gap this file used to pin is closed. "week" is a real item
        # horizon now and it is the thing that fills the weekly screen.
        self.assertEqual(lp.strategy_horizon_for("week"), "weekly")
        self.assertIn("week", lp.HORIZONS)

    def test_only_week_reaches_weekly(self):
        # The other half of H-4, and the reason the original gap was worth
        # pinning: "weekly" must have exactly ONE source. Aliasing a second
        # horizon onto it — "now" being the tempting one — would put goals of
        # a different scale on the weekly screen.
        sources = [k for k, v in lp.ITEM_TO_STRATEGY_HORIZON.items()
                   if v == "weekly"]
        self.assertEqual(sources, ["week"])

    def test_now_still_means_now(self):
        # Adding "week" must not have quietly re-pointed "now". Every [NOW]
        # goal already written renders on the daily screen and keeps doing so.
        self.assertEqual(lp.strategy_horizon_for("now"), "daily")

    def test_every_strategy_screen_now_has_a_source(self):
        # The mapping is total in BOTH directions: no screen is left that a
        # document can never pre-fill. This is what the fix actually bought.
        reachable = set(lp.ITEM_TO_STRATEGY_HORIZON.values())
        self.assertEqual(reachable, set(lp.STRATEGY_HORIZONS))

    def test_week_is_not_in_the_pre_migration_vocabulary(self):
        # The fallback path keys off this tuple; if "week" ever leaked into
        # it, apply-proposed would stop degrading and start losing rows on a
        # database where the migration has not run.
        self.assertNotIn("week", lp.HORIZONS_BEFORE_WEEK)
        self.assertEqual(set(lp.HORIZONS) - set(lp.HORIZONS_BEFORE_WEEK),
                         {"week"})

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


class WeekMigrationFallbackTests(unittest.TestCase):
    """H-6 — apply-proposed against a database that has not run the migration.

    `week` is not a nullable extra column like origin_document_id; it is a
    CHECK constraint, so an unmigrated database rejects the WHOLE insert. And
    life_store.insert_item swallows the error and returns None, so without a
    fallback the row a person read and individually ticked would vanish behind
    a 201 and a shorter `created` list.

    The rule these pin: a migration nobody has run costs the weekly screen its
    pre-fill. It never costs the row.
    """

    def setUp(self):
        try:
            from routes import life_routes
        except Exception as e:                      # pragma: no cover
            self.skipTest(f"needs app deps: {e}")
        self.routes = life_routes

    def _run(self, fields, rejects):
        """Insert `fields`, with a fake store that rejects some payloads.

        `rejects` is a predicate on the payload — True means the database
        refused it. Returns (row, attempts)."""
        from unittest.mock import patch
        attempts = []

        def fake_insert(user_id, payload):
            attempts.append(dict(payload))
            return None if rejects(payload) else {"id": "row-1", **payload}

        with patch.object(self.routes.store, "insert_item", fake_insert):
            row = self.routes._insert_ticked_item("u1", dict(fields))
        return row, attempts

    # ── the healthy database ──────────────────────────────────────────────

    def test_a_migrated_database_writes_week_on_the_first_attempt(self):
        row, attempts = self._run(
            {"kind": "goal", "title": "ship", "horizon": "week"},
            rejects=lambda p: False)
        self.assertEqual(row["horizon"], "week")
        self.assertEqual(len(attempts), 1, "no retry should be needed")

    # ── the week constraint has not been migrated ─────────────────────────

    def test_an_unmigrated_week_lands_as_a_null_horizon_not_a_lost_row(self):
        row, _ = self._run(
            {"kind": "goal", "title": "ship", "horizon": "week"},
            rejects=lambda p: p.get("horizon") == "week")
        self.assertIsNotNone(row, "the ticked row must never be lost")
        self.assertIsNone(row["horizon"])

    def test_the_downgrade_is_never_a_different_horizon(self):
        # A weekly goal moved onto the daily screen would be the system
        # inventing a due date the person did not write. NULL — the remainder
        # review — is the only acceptable downgrade.
        _, attempts = self._run(
            {"kind": "goal", "title": "ship", "horizon": "week"},
            rejects=lambda p: p.get("horizon") == "week")
        for payload in attempts:
            self.assertIn(payload.get("horizon"), ("week", None))

    def test_the_downgrade_keeps_the_provenance_stamp(self):
        # Only the field that was actually refused is given up.
        row, _ = self._run(
            {"kind": "goal", "title": "ship", "horizon": "week",
             "origin_document_id": "doc-1"},
            rejects=lambda p: p.get("horizon") == "week")
        self.assertIsNone(row["horizon"])
        self.assertEqual(row["origin_document_id"], "doc-1")

    # ── the stamp column has not been migrated ────────────────────────────

    def test_an_unmigrated_stamp_keeps_the_week_horizon(self):
        # The mirror of the above: give up the stamp, keep the screen.
        row, _ = self._run(
            {"kind": "goal", "title": "ship", "horizon": "week",
             "origin_document_id": "doc-1"},
            rejects=lambda p: "origin_document_id" in p)
        self.assertEqual(row["horizon"], "week")
        self.assertNotIn("origin_document_id", row)

    # ── neither migration has run ─────────────────────────────────────────

    def test_neither_migration_still_creates_the_row(self):
        row, _ = self._run(
            {"kind": "goal", "title": "ship", "horizon": "week",
             "origin_document_id": "doc-1"},
            rejects=lambda p: ("origin_document_id" in p
                               or p.get("horizon") == "week"))
        self.assertIsNotNone(row, "the ticked row must never be lost")
        self.assertIsNone(row["horizon"])
        self.assertNotIn("origin_document_id", row)

    # ── the failure that is NOT a migration ───────────────────────────────

    def test_a_real_outage_is_still_a_skipped_row_not_a_crash(self):
        # insert_item cannot say WHY it failed, so the ladder is best-effort.
        # A database that is simply down exhausts it and returns None, which
        # is what the endpoint already does with a row it could not create.
        row, attempts = self._run(
            {"kind": "goal", "title": "ship", "horizon": "week",
             "origin_document_id": "doc-1"},
            rejects=lambda p: True)
        self.assertIsNone(row)
        self.assertLessEqual(len(attempts), 4, "the ladder must terminate")

    def test_a_row_with_no_week_and_no_stamp_is_tried_exactly_once(self):
        # The ordinary row must not pay for either fallback.
        row, attempts = self._run(
            {"kind": "goal", "title": "ship", "horizon": "month"},
            rejects=lambda p: False)
        self.assertIsNotNone(row)
        self.assertEqual(len(attempts), 1)


class DegradeOnlyWhereItIsEarnedTests(unittest.TestCase):
    """The fallback belongs to apply-proposed and nowhere else.

    apply-proposed may downgrade a week horizon because the model inferred it
    from a document and the ROW is what the person ticked. A manual create is
    the opposite: the person chose "week" on a form, so silently storing it
    with no horizon would be the panel overruling an explicit choice without
    saying so. That path fails the save instead, and says so."""

    def setUp(self):
        try:
            from routes import life_routes
        except Exception as e:                      # pragma: no cover
            self.skipTest(f"needs app deps: {e}")
        self.routes = life_routes

    def test_only_apply_proposed_uses_the_degrading_insert(self):
        import inspect
        source = inspect.getsource(self.routes)
        callers = [line.strip() for line in source.splitlines()
                   if "_insert_ticked_item(" in line
                   and "def _insert_ticked_item" not in line]
        # One call site: the apply-proposed loop. If a second appears, the
        # degrade has spread to a path that never earned it.
        self.assertEqual(len(callers), 1, callers)

    def test_the_manual_create_still_reports_a_failed_save(self):
        import inspect
        source = inspect.getsource(self.routes.life_item_create)
        self.assertIn("Could not save", source)
        # The CALL form, not the bare name — the route carries a comment
        # naming the helper to say why it deliberately does not use it, and a
        # test that cannot tell those apart would forbid its own explanation.
        self.assertNotIn("_insert_ticked_item(", source)
        self.assertIn("store.insert_item(", source)


class ExtractionVocabularyTests(unittest.TestCase):
    """The vocabulary is only half the fix — the extractor has to emit it.

    Adding `week` to HORIZONS and to the mapping closes the gap on paper. If
    the document-draft prompt never tells the model that `week` is available,
    nothing ever carries it and the weekly screen stays exactly as empty as it
    was, with the fix looking done."""

    def setUp(self):
        try:
            from services import life_engine
        except Exception as e:                      # pragma: no cover
            self.skipTest(f"needs app deps: {e}")
        self.prompt = life_engine._DOC_DRAFT_SYSTEM

    def test_the_prompt_offers_week_as_a_horizon(self):
        self.assertIn("week", self.prompt)

    def test_the_prompt_lists_every_horizon_the_writer_accepts(self):
        # A value the model can emit but sanitize_confirmed_item would null,
        # or one the writer accepts but the model is never told about, is a
        # silently half-wired vocabulary.
        for horizon in lp.HORIZONS:
            self.assertIn(horizon, self.prompt, horizon)

    def test_week_is_scoped_rather_than_offered_as_a_default(self):
        # An unqualified "week" in the list would have the model reach for it
        # whenever a document looks short-term, which fills the weekly screen
        # with goals nobody scoped to a week.
        self.assertIn("this week", self.prompt.lower())


if __name__ == "__main__":
    unittest.main()
