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
        with patch.object(eng, "_complete_ex",
                          return_value=((parsed or {"goals": []}),
                                        eng.OUTCOME_OK)), \
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
        with patch.object(eng, "_complete_ex",
                          return_value=({"goals": []}, eng.OUTCOME_OK)), \
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


class TruncatedExtractionTests(unittest.TestCase):
    """A 19,787-character goals document answered "nothing that reads as a
    goal came out of that document" (screenshot, 2026-07-31).

    It was not a prompt problem and the document was not empty. The output cap
    was 2000 tokens; a strategy document that size holds far more than that in
    goals JSON, so the model stopped mid-object, JSON mode left a string that
    would not parse, _complete returned None, and the panel reported the
    document as goal-less. `finish_reason == "length"` was on the response the
    whole time and nothing read it.

      X-1  a truncated read is reported as TRUNCATED, not as "nothing found";
      X-2  the cap fits the largest document the endpoint accepts;
      X-3  the endpoint tells the FE whether the READ worked, which is a
           different question from whether the document held anything.
    """

    def setUp(self):
        try:
            from services import life_engine
        except Exception as e:                      # pragma: no cover
            self.skipTest(f"needs app deps: {e}")
        self.eng = life_engine

    def _call(self, content, finish_reason):
        from unittest.mock import MagicMock, patch
        choice = MagicMock(message=MagicMock(content=content),
                           finish_reason=finish_reason)
        client = MagicMock()
        client.chat.completions.create.return_value = MagicMock(
            choices=[choice])
        with patch.object(self.eng, "_client", return_value=client), \
             patch.object(self.eng, "_log_derivation"):
            return self.eng._complete_ex(
                self.eng.SPEC_LIFE_DOC_DRAFT, system="s", user="u",
                surface="doc_draft", user_id="u1")

    # ── X-1 ───────────────────────────────────────────────────────────────

    def test_a_cut_off_answer_is_truncated_not_unparseable(self):
        # The exact shape the cap produces: valid JSON right up to the cut.
        parsed, outcome = self._call(
            '{"goals": [{"title": "Ship the panel"}, {"title": "Rai',
            "length")
        self.assertIsNone(parsed)
        self.assertEqual(outcome, self.eng.OUTCOME_TRUNCATED)

    def test_malformed_at_its_own_length_is_still_unparseable(self):
        # Different cause, different fix — do not collapse them back together.
        parsed, outcome = self._call("not json at all", "stop")
        self.assertIsNone(parsed)
        self.assertEqual(outcome, self.eng.OUTCOME_UNPARSEABLE)

    def test_json_that_closed_as_the_cap_hit_is_still_not_a_clean_read(self):
        # It parses, so the old code would have called this a success — but
        # the document holds more than what came back.
        parsed, outcome = self._call('{"goals": []}', "length")
        self.assertEqual(parsed, {"goals": []})
        self.assertEqual(outcome, self.eng.OUTCOME_TRUNCATED)

    def test_a_complete_answer_is_ok(self):
        parsed, outcome = self._call('{"goals": [{"title": "Ship"}]}', "stop")
        self.assertEqual(outcome, self.eng.OUTCOME_OK)
        self.assertEqual(parsed["goals"][0]["title"], "Ship")

    def test_every_failure_mode_is_marked_as_a_failure(self):
        # The set the endpoint branches on. A new outcome that means "we fell
        # over" but is missing here would go out as a clean read.
        for outcome in (self.eng.OUTCOME_NO_CLIENT,
                        self.eng.OUTCOME_CALL_FAILED,
                        self.eng.OUTCOME_EMPTY,
                        self.eng.OUTCOME_TRUNCATED,
                        self.eng.OUTCOME_UNPARSEABLE):
            self.assertIn(outcome, self.eng.FAILED_OUTCOMES, outcome)
        self.assertNotIn(self.eng.OUTCOME_OK, self.eng.FAILED_OUTCOMES)

    # ── X-2 ───────────────────────────────────────────────────────────────

    def test_the_cap_fits_the_largest_document_the_endpoint_accepts(self):
        # The upload truncates input at 20,000 characters. The answer has to
        # have room to describe a document that size; 2000 tokens did not, and
        # that shortfall was silent.
        self.assertGreaterEqual(self.eng.SPEC_LIFE_DOC_DRAFT.max_tokens, 8000)

    # ── X-3 ───────────────────────────────────────────────────────────────

    def test_the_draft_reports_the_outcome_alongside_the_rows(self):
        from unittest.mock import patch
        with patch.object(self.eng, "_complete_ex",
                          return_value=(None, self.eng.OUTCOME_TRUNCATED)), \
             patch.object(self.eng, "_log_derivation"):
            items, outcome = self.eng.draft_items_from_document_ex("u1", "x")
        self.assertEqual(outcome, self.eng.OUTCOME_TRUNCATED)
        # The three locked bets are always seeded, so "no goals" has never
        # meant "no rows" — which is exactly why the row count could not be
        # used to tell a failed read from an empty document.
        self.assertEqual({i["kind"] for i in items}, {"bet"})

    def test_the_old_entry_point_still_returns_just_the_rows(self):
        # Existing callers must not have to care about the outcome.
        from unittest.mock import patch
        with patch.object(self.eng, "_complete_ex",
                          return_value=({"goals": [{"title": "Ship"}]},
                                        self.eng.OUTCOME_OK)), \
             patch.object(self.eng, "_log_derivation"):
            items = self.eng.draft_items_from_document("u1", "x")
        self.assertIsInstance(items, list)
        self.assertIn("goal", {i["kind"] for i in items})


class ExtractionHonestyRouteTests(unittest.TestCase):
    """X-3 on the wire. The endpoint has to say whether the READ worked.

    NOTE what this does NOT do: it does not change a word of what the user
    sees. The message in the screenshot is product copy and stays held for
    founder sign-off. This is the signal the FE needs in order to stop saying
    it when it is not true."""

    def setUp(self):
        try:
            from routes import life_routes
        except Exception as e:                      # pragma: no cover
            self.skipTest(f"needs app deps: {e}")
        self.routes = life_routes

    def test_the_endpoint_sends_whether_the_read_worked(self):
        import inspect
        source = inspect.getsource(self.routes.life_setup_propose_from_document)
        self.assertIn("extraction_ok", source)
        self.assertIn("FAILED_OUTCOMES", source)

    def test_it_is_a_status_not_a_score(self):
        # AC-9: no numbers, no verdicts, no "we found 4 of 11". A boolean
        # about our own plumbing is not a judgement about the person.
        import inspect
        source = inspect.getsource(self.routes.life_setup_propose_from_document)
        self.assertNotIn("confidence", source.lower())
        self.assertNotIn("score", source.lower())

    def test_the_user_facing_copy_is_not_written_here(self):
        # The fix is the signal, not the sentence. If a message for the FE to
        # render ever appears in this endpoint, it needs sign-off first.
        import inspect
        source = inspect.getsource(self.routes.life_setup_propose_from_document)
        for phrase in ("came out of that document", "yours to fill in",
                       "we could not read"):
            self.assertNotIn(phrase, source, phrase)


if __name__ == "__main__":
    unittest.main()


class StrictDueDateTests(unittest.TestCase):
    """Extraction resolves the date; the label keeps the person's words.

    Founder 2026-08-01: the app forces concrete, achievable metrics, so a
    vague "to July 2031" must become a real calendar date at EXTRACTION —
    not be patched up by a frontend parser later.

      D-1  the resolved date leads, and the verbatim label survives beside it;
      D-2  parse_due_label stays the fallback for a row the model dated "";
      D-3  the date rides the round trip, so a ticked goal is CREATED with the
           date it was drafted with;
      D-4  the prompt is told today, because "[Aug]" cannot be resolved
           without it.
    """

    def setUp(self):
        try:
            from services import life_import, life_engine
        except Exception as e:                      # pragma: no cover
            self.skipTest(f"needs app deps: {e}")
        self.imp = life_import
        self.eng = life_engine

    # ── D-1 ───────────────────────────────────────────────────────────────

    def test_the_resolved_date_is_used_and_the_label_is_untouched(self):
        plan = self.imp.plan_strategy("u1", {"goals": [{
            "title": "A marriage with years on it",
            "due_label": "to July 2031",
            "due_date": "2031-07-01",
            "horizon": "five_year",
        }]})
        goal = next(i for i in plan["items"] if i["kind"] == "goal")
        self.assertEqual(goal["due_at"], "2031-07-01")
        # The card still reads what they wrote, not a database row.
        self.assertEqual(goal["due_label"], "to July 2031")

    def test_a_label_the_old_parser_could_never_read_now_has_a_date(self):
        # The exact regression: parse_due_label handles "[Jul '27]" and "2035"
        # but not a "to ..." prefix, so this goal had no date and could not be
        # placed on the timeline at all.
        self.assertIsNone(self.imp.lp.parse_due_label("to July 2031"))
        plan = self.imp.plan_strategy("u1", {"goals": [{
            "title": "x", "due_label": "to July 2031",
            "due_date": "2031-07-01"}]})
        goal = next(i for i in plan["items"] if i["kind"] == "goal")
        self.assertEqual(goal["due_at"], "2031-07-01")

    # ── D-2 ───────────────────────────────────────────────────────────────

    def test_the_parser_is_still_the_fallback(self):
        # An older payload, or a row the model gave no date for, behaves
        # exactly as it did before.
        plan = self.imp.plan_strategy("u1", {"goals": [
            {"title": "a", "due_label": "2035"},
            {"title": "b", "due_label": "2035", "due_date": ""},
        ]})
        for goal in (i for i in plan["items"] if i["kind"] == "goal"):
            self.assertEqual(goal["due_at"], "2035-01-01")

    def test_an_undateable_goal_still_has_no_date(self):
        # "Someday" gets none, and nothing invents one. A deadline nobody
        # wrote reads as a commitment they made.
        plan = self.imp.plan_strategy("u1", {"goals": [
            {"title": "x", "due_label": "someday", "due_date": ""}]})
        goal = next(i for i in plan["items"] if i["kind"] == "goal")
        self.assertIsNone(goal["due_at"])

    # ── D-3 ───────────────────────────────────────────────────────────────

    def test_the_date_survives_the_tick(self):
        # Drafted with a date, displayed, ticked, posted back. Recomputing
        # from the label here would create the row WITHOUT the date it was
        # shown with.
        fields = self.imp.sanitize_confirmed_item({
            "kind": "goal", "title": "A marriage with years on it",
            "due_label": "to July 2031", "due_at": "2031-07-01"})
        self.assertEqual(fields["due_at"], "2031-07-01")
        self.assertEqual(fields["due_label"], "to July 2031")

    def test_the_tick_accepts_either_spelling(self):
        for key in ("due_at", "dueAt", "due_date"):
            fields = self.imp.sanitize_confirmed_item({
                "kind": "goal", "title": "x", "due_label": "to July 2031",
                key: "2031-07-01"})
            self.assertEqual(fields["due_at"], "2031-07-01", key)

    def test_the_tick_falls_back_to_the_label(self):
        fields = self.imp.sanitize_confirmed_item({
            "kind": "goal", "title": "x", "due_label": "2035"})
        self.assertEqual(fields["due_at"], "2035-01-01")

    # ── D-4 ───────────────────────────────────────────────────────────────

    def test_the_prompt_asks_for_a_strict_date_and_is_told_today(self):
        self.assertIn("due_date", self.eng._DOC_DRAFT_SYSTEM)
        self.assertIn("YYYY-MM-DD", self.eng._DOC_DRAFT_SYSTEM)
        # Without today's date "[Aug]" and "by Friday" cannot be resolved, and
        # a model guessing the year puts a 2026 goal on 2024.
        self.assertIn("{today}", self.eng._DOC_DRAFT_SYSTEM)

    def test_the_prompt_still_says_the_label_is_verbatim(self):
        # The resolve is ADDITIVE. If this ever stops holding, the goal cards
        # start reading as ISO dates instead of what the person wrote.
        self.assertIn("VERBATIM", self.eng._DOC_DRAFT_SYSTEM)

    def test_the_prompt_formats_without_error(self):
        # It carries JSON braces, so every literal one must be doubled — a
        # miss here is a KeyError at the first draft, not at import.
        rendered = self.eng._DOC_DRAFT_SYSTEM.format(today="2026-08-01")
        self.assertIn("Today is 2026-08-01", rendered)
        self.assertIn('{"goals"', rendered)
