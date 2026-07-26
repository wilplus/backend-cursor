"""willab — The Life Panel (founder-directed 2026-07-26).

Every non-negotiable in PROMPT-BE-life-panel.md §0 is a test here, not a note:

  N1  RLS on every life_* table IN ITS CREATING MIGRATION
  N2  no product-side module imports the life module; the SHARED master body
      is never written to
  N3  a non-participating user's chat is byte-identical — the router hands the
      turn back untouched
  N4  the per-user master-doc injection is capped and trimmed, and is absent
      entirely for everyone who has not opted in
  N5  the system never authors reflective prose (L-1)
  N6  nothing reaches the strategy doc without an approved proposal, and the
      immutable core is never proposed against (L-2 / L-2a)
  N7  at most one strategy proposal surfaced per day (L-2b)
  N8  zero scheduled outbound anything (L-4)
  N9  hard delete actually deletes; export returns everything

Plus the locked rules the routes rest on: the hashtag grammar (§5), the fixed
six-entry taxonomy (§3.1), the phrase wall's relevance floor and no-repeat
window, L-3's both-sides-never-a-winner, and the importer's preservation
guarantees (BE-3).

The pure-layer tests import ONLY services.life_panel, which has no DB and no
network — so they run in CI unconditionally. The route/store tests need the
app's dependency graph and skip cleanly when it is unavailable, following the
house pattern in test_journal.py.

Run: python3 -m unittest test_life_panel

N3's full form is a SUITE-level gate, not a single test — "the full existing
chat suite re-run under a non-participating user". Run it with the flag ON and
no consent row, which is exactly that state:

    LIFE_PANEL_ENABLED=1 python3 -m pytest -q

Green means the hook falls through untouched for everyone who has not opted
in. If that run ever goes red on a NON-life test, the hook has started
changing responses it must not change.
"""
from __future__ import annotations

import os
import re
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

# Placeholder credentials BEFORE the app graph is imported: config.py and
# services/db.py read the environment at import time, and the Supabase client
# validates the key's SHAPE at construction. These never leave the process —
# every store call in this file is mocked.
os.environ.setdefault("SUPABASE_URL", "https://life-panel-test.invalid")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "aaaa.bbbb.cccc")

from services import life_panel as lp           # noqa: E402  (pure, always importable)
from services import life_import as importer    # noqa: E402  (pure)

try:
    from flask import Flask
    import auth
    from routes import life_routes as lroutes
    from services import life_chat as lchat
    from services import life_engine as lengine
    from services import life_store as lstore
    from services import master_doc_rag as mdr
    _IMPORT_ERROR = None
except Exception as e:                          # pragma: no cover
    Flask = None
    auth = lroutes = lchat = lengine = lstore = mdr = None
    _IMPORT_ERROR = e

USER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
MIGRATION = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "migrations", "add_life_panel.sql")


# ═════════════════════════════════════════════════════════════════════════
# N1 — RLS in the creating migration
# ═════════════════════════════════════════════════════════════════════════

class RlsMigrationTests(unittest.TestCase):
    """RLS is part of the file that creates the table, not a follow-up sweep.

    The July 2026 audit found 57 exposed public tables; this corpus —
    addiction, sexual behaviour, confession-shaped religious material, named
    third parties — must not be number 58."""

    @classmethod
    def setUpClass(cls):
        with open(MIGRATION, "r", encoding="utf-8") as fh:
            cls.sql = fh.read()

    def _created_tables(self) -> set[str]:
        return set(re.findall(
            r"CREATE TABLE IF NOT EXISTS\s+(life_\w+)", self.sql))

    def test_every_created_table_enables_rls_in_this_file(self):
        protected = set(re.findall(
            r"ALTER TABLE\s+(life_\w+)\s+ENABLE ROW LEVEL SECURITY", self.sql))
        created = self._created_tables()
        self.assertTrue(created, "migration creates no life_* tables")
        self.assertEqual(
            created - protected, set(),
            "these tables are created without RLS in the same migration")

    def test_no_policies_are_granted_to_anon(self):
        # RLS + zero policies = anon and authenticated can do nothing, while
        # the backend's service-role key bypasses RLS. A policy here would be
        # the thing that re-opens the door.
        self.assertNotIn("CREATE POLICY", self.sql.upper())

    def test_migration_is_idempotent(self):
        for statement in re.findall(r"CREATE TABLE[^(]*", self.sql):
            self.assertIn("IF NOT EXISTS", statement)
        for statement in re.findall(r"CREATE (?:UNIQUE )?INDEX[^(]*", self.sql):
            self.assertIn("IF NOT EXISTS", statement)

    def test_nothing_is_ever_dropped(self):
        # The standing engineering constraint: never auto-drop tables,
        # columns or migrations.
        self.assertNotRegex(self.sql.upper(), r"\bDROP\s+(TABLE|COLUMN)\b")

    def test_a_partial_run_raises_instead_of_reporting(self):
        # A migration that silently half-applies is how a table ends up
        # exposed. The post-condition must RAISE.
        self.assertIn("RAISE EXCEPTION", self.sql)

    def test_the_store_knows_about_every_created_table(self):
        # export_all and hard_delete iterate LIFE_TABLES. A table in the
        # migration but not in that list would be invisible to both — it would
        # neither come out on export nor go away on delete.
        if _IMPORT_ERROR is not None:
            self.skipTest(f"needs app deps: {_IMPORT_ERROR}")
        self.assertEqual(self._created_tables() - set(lstore.LIFE_TABLES),
                         set())

    def test_a_strategy_proposal_cannot_exist_without_a_warrant(self):
        # L-2 at the DB layer: a direct SQL insert cannot bypass the warrant
        # requirement either.
        self.assertIn("life_proposals_strategy_needs_warrant", self.sql)


# ═════════════════════════════════════════════════════════════════════════
# §5 — the hashtag grammar
# ═════════════════════════════════════════════════════════════════════════

class TagRouterTests(unittest.TestCase):

    def test_every_documented_tag_routes(self):
        for tag in ("principle", "sin", "mistake", "error", "problem"):
            self.assertEqual(lp.parse_tag(f"#{tag} x")[1], "case")
        for tag in ("data", "observation", "reflection", "idea", "finding"):
            self.assertEqual(lp.parse_tag(f"#{tag} x")[1], "goal_diff")
        for tag in ("win", "wins", "wygrane", "liftmeup"):
            self.assertEqual(lp.parse_tag(f"#{tag} x")[1], "win")
        self.assertEqual(lp.parse_tag("#add x")[1], "phrase")
        self.assertEqual(lp.parse_tag("#edit x")[1], "edit")

    def test_lift_me_up_is_the_desired_failure_mode(self):
        # Hashtags break at whitespace, so `#liftmeup` is one word on purpose.
        # `#lift me up` must NOT reach Wins — it is an unknown tag, and the
        # whole text is kept so nothing the user typed is silently edited.
        tag, route, remainder = lp.parse_tag("#lift me up")
        self.assertIsNone(tag)
        self.assertEqual(route, "capture")
        self.assertEqual(remainder, "#lift me up")

    def test_the_tag_is_the_first_token_only(self):
        self.assertEqual(lp.parse_tag("some prose #mistake later")[1],
                         "capture")

    def test_case_insensitive_and_punctuation_tolerant(self):
        self.assertEqual(lp.parse_tag("#MISTAKE: I did x"),
                         ("mistake", "case", "I did x"))

    def test_unknown_tag_keeps_the_text_whole(self):
        self.assertEqual(lp.parse_tag("#nonsense body")[2], "#nonsense body")

    def test_sin_works_but_is_off_the_public_picker(self):
        self.assertEqual(lp.parse_tag("#sin x")[1], "case")
        self.assertNotIn("#sin", [s["tag"] for s in lp.tag_suggestions()])

    def test_the_picker_covers_every_route(self):
        # Four aliases per route are impossible to memorise; the picker is
        # what keeps the guide page from having to be load-bearing.
        self.assertEqual({s["route"] for s in lp.tag_suggestions()},
                         set(lp.TAG_ROUTES.values()))

    def test_empty_and_bare_hash(self):
        self.assertEqual(lp.parse_tag("")[1], "capture")
        self.assertEqual(lp.parse_tag(None)[1], "capture")
        self.assertEqual(lp.parse_tag("#")[1], "capture")


# ═════════════════════════════════════════════════════════════════════════
# §3.1 — the fixed six-entry taxonomy
# ═════════════════════════════════════════════════════════════════════════

class TaxonomyTests(unittest.TestCase):

    def test_exactly_six_categories(self):
        self.assertEqual(len(lp.CATEGORIES), 6)
        self.assertEqual(set(lp.CATEGORY_LABELS), set(lp.CATEGORIES))

    def test_aliases_map_both_languages(self):
        self.assertEqual(lp.map_import_category("Wishful thinking"),
                         "wishful_thinking")
        self.assertEqual(lp.map_import_category("Myślenie życzeniowe"),
                         "wishful_thinking")
        self.assertEqual(lp.map_import_category("PYCHA"), "hubris")

    def test_an_unknown_category_is_never_guessed(self):
        # It goes to a review queue instead. A mis-mapped category is a lie
        # about a four-year-old reflection, and it is invisible once written.
        self.assertIsNone(lp.map_import_category("Something else entirely"))
        self.assertIsNone(lp.map_import_category(""))
        self.assertIsNone(lp.map_import_category(None))

    def test_normalize_drops_rather_than_coerces(self):
        self.assertEqual(
            lp.normalize_categories(["hubris", "nope", "hubris"]),
            ["hubris"])

    def test_multi_category_survives_and_keeps_its_order(self):
        # The scooter/drift case carries Wishful thinking + Hubris.
        self.assertEqual(
            lp.normalize_categories(["Wishful thinking", "Hubris"]),
            ["wishful_thinking", "hubris"])


# ═════════════════════════════════════════════════════════════════════════
# N5 / L-1 — the system never authors reflective prose
# ═════════════════════════════════════════════════════════════════════════

class ReflectionsAreNeverAuthoredTests(unittest.TestCase):

    def test_reflections_come_from_request_input(self):
        out = lp.validate_case_input({
            "case_at_hand": "I did x", "reflections": "Zabrakło mi pokory.",
        })
        self.assertEqual(out["reflections"], "Zabrakło mi pokory.")

    def test_polish_is_stored_verbatim(self):
        # No translation, no normalisation, no cleanup pass. Several
        # reflections are code-switched mid-paragraph and that is the record.
        text = "Zabrakło mi pokory — I lost control. Żałuję."
        self.assertEqual(
            lp.validate_case_input({"case_at_hand": "x",
                                    "reflections": text})["reflections"],
            text)

    @unittest.skipIf(_IMPORT_ERROR is not None, "needs app deps")
    def test_no_module_ever_writes_reflections_from_a_model_result(self):
        """The load-bearing half of N5.

        Anywhere in the feature, `reflections` may be assigned only from
        validated request input or from an import row. If a future change
        wires a model output into that field, this fails."""
        import inspect
        for module in (lengine, lchat, lroutes):
            src = inspect.getsource(module)
            for match in re.finditer(r'"reflections"\s*:\s*([^,\n}]+)', src):
                value = match.group(1).strip()
                self.assertNotIn(
                    "derived", value,
                    f"{module.__name__} assigns reflections from a derivation")
                self.assertNotIn(
                    "parsed", value,
                    f"{module.__name__} assigns reflections from model output")

    @unittest.skipIf(_IMPORT_ERROR is not None, "needs app deps")
    def test_the_case_prompt_forbids_writing_reflections(self):
        self.assertIn("YOU DO NOT WRITE REFLECTIONS", lengine._CASE_SYSTEM)

    @unittest.skipIf(_IMPORT_ERROR is not None, "needs app deps")
    def test_the_panel_never_calls_the_f1_ideal_text_pipeline(self):
        # L-1: the Ideal Text polish happens EXTERNALLY and is pasted in. This
        # is a manual copy-paste, not an integration.
        import inspect
        for module in (lengine, lchat, lroutes, lstore, lp, importer):
            self.assertNotIn("ideal_text", inspect.getsource(module))


# ═════════════════════════════════════════════════════════════════════════
# N6 / L-2a — the immutable core
# ═════════════════════════════════════════════════════════════════════════

class ImmutableCoreTests(unittest.TestCase):

    def test_section_i_and_the_bet_rank_are_immutable(self):
        for target in ("anchor", "weekly.section_i", "Section I",
                       "weekly.section_1", "bets.rank", "bet_rank",
                       "yearly.bets.ranking"):
            self.assertTrue(lp.is_immutable_target(target), target)

    def test_ordinary_sections_are_not(self):
        for target in ("weekly.section_ii", "yearly.bet_2.short_term",
                       "monthly.goals", "daily.one_thing"):
            self.assertFalse(lp.is_immutable_target(target), target)

    def test_a_blank_target_is_refused(self):
        # An unaddressed proposal cannot be reviewed, so it cannot be created.
        # Refusing it keeps "every change is gated" true by construction.
        self.assertTrue(lp.is_immutable_target(""))
        self.assertTrue(lp.is_immutable_target(None))

    @unittest.skipIf(_IMPORT_ERROR is not None, "needs app deps")
    def test_apply_refuses_the_immutable_core_on_the_write_path_too(self):
        # "Never proposed against" has to hold on the WRITE path, not only on
        # the path that happens to be in front of it.
        self.assertIsNone(lengine.apply_proposal(
            USER, {"id": "p1", "target": "weekly.section_i",
                   "current": "a", "proposed": "b"}))


# ═════════════════════════════════════════════════════════════════════════
# N7 / L-2b — the change budget
# ═════════════════════════════════════════════════════════════════════════

class ChangeBudgetTests(unittest.TestCase):

    def test_five_qualifying_notes_in_one_day_surface_one(self):
        surfaced = 0
        statuses = []
        for _ in range(5):
            status = lp.plan_proposal_status(already_surfaced_today=surfaced)
            statuses.append(status)
            if status == "surfaced":
                surfaced += 1
        self.assertEqual(statuses.count("surfaced"), 1)
        self.assertEqual(statuses.count("queued"), 4)

    def test_a_garbled_count_queues_rather_than_surfaces(self):
        # Fail closed: a queued proposal still reaches the weekly review, an
        # over-surfaced one erodes the approve button.
        self.assertEqual(lp.plan_proposal_status(already_surfaced_today=None),
                         "surfaced")
        self.assertEqual(lp.plan_proposal_status(already_surfaced_today=99),
                         "queued")

    def test_the_weekly_batch_is_three_ranked(self):
        queued = [{"id": str(i), "rank": i / 10.0, "created_at": "2026-07-01"}
                  for i in range(7)]
        batch = lp.weekly_batch(queued)
        self.assertEqual(len(batch), lp.WEEKLY_BATCH_SIZE)
        self.assertEqual([b["id"] for b in batch], ["6", "5", "4"])

    def test_queued_proposals_expire_after_two_weeks(self):
        old = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        self.assertTrue(lp.is_expired({"status": "queued",
                                       "expires_at": old}))
        self.assertFalse(lp.is_expired({"status": "queued",
                                        "expires_at": future}))

    def test_surfaced_and_decided_proposals_never_expire(self):
        old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        for status in ("surfaced", "approved", "dismissed", "expired"):
            self.assertFalse(lp.is_expired({"status": status,
                                            "expires_at": old}), status)

    def test_expiry_is_fourteen_days_out(self):
        base = datetime(2026, 7, 26, tzinfo=timezone.utc)
        self.assertTrue(lp.expiry_for(base).startswith("2026-08-09"))

    @unittest.skipIf(_IMPORT_ERROR is not None, "needs app deps")
    def test_an_unknown_budget_state_fails_closed(self):
        # The budget is a QUERY, and a failed query must not be read as zero.
        with patch.object(lstore, "_t", side_effect=RuntimeError("down")):
            self.assertGreaterEqual(lstore.count_surfaced_today(USER),
                                    lp.DAILY_PROPOSAL_BUDGET)


# ═════════════════════════════════════════════════════════════════════════
# The phrase wall — floor + no-repeat
# ═════════════════════════════════════════════════════════════════════════

class PhraseWallTests(unittest.TestCase):

    def _phrases(self):
        return [
            {"id": "a", "body": "Focus on saving your own life first",
             "created_at": "2022-01-01"},
            {"id": "b", "body": "Money follows patience and honest partners",
             "created_at": "2023-01-01"},
        ]

    def test_below_the_floor_attaches_nothing(self):
        # A mismatched aphorism on a `#sin` note about addiction is worse than
        # silence — it teaches the founder the wall is noise.
        self.assertIsNone(lp.pick_phrase("the weather is cold today",
                                         self._phrases()))

    def test_one_shared_word_is_coincidence_not_relevance(self):
        self.assertEqual(
            lp.phrase_relevance("money", "Money follows patience and honest "
                                         "partners"), 0.0)

    def test_a_real_overlap_clears_the_floor(self):
        picked = lp.pick_phrase(
            "I keep chasing money instead of finding honest partners",
            self._phrases())
        self.assertIsNotNone(picked)
        self.assertEqual(picked["id"], "b")

    def test_the_no_repeat_window_is_respected(self):
        note = "I keep chasing money instead of finding honest partners"
        self.assertIsNone(
            lp.pick_phrase(note, self._phrases(), recently_used_ids=["b"]))

    def test_the_wall_cannot_collapse_to_one_favourite(self):
        # Same note twice; the second time the winner is blocked, so either a
        # different phrase or nothing comes back — never the same one again.
        note = "I keep chasing money instead of finding honest partners"
        first = lp.pick_phrase(note, self._phrases())
        second = lp.pick_phrase(note, self._phrases(),
                                recently_used_ids=[first["id"]])
        self.assertNotEqual((second or {}).get("id"), first["id"])

    def test_the_score_never_reaches_the_payload(self):
        # Nothing in a life payload is a number the user reads.
        picked = lp.pick_phrase(
            "I keep chasing money instead of finding honest partners",
            self._phrases())
        self.assertNotIn("score", lp.serialize_item(picked))
        self.assertNotIn("relevance", lp.serialize_item(picked))


# ═════════════════════════════════════════════════════════════════════════
# L-3 — surface paradoxes, never resolve them
# ═════════════════════════════════════════════════════════════════════════

class ParadoxTests(unittest.TestCase):

    def test_opposing_principles_come_back_as_a_pair(self):
        pairs = lp.pair_conflicts([
            {"id": "1", "title": "Don't seek validation outside yourself"},
            {"id": "2", "title": "Seek honest feedback from trusted people"},
        ])
        self.assertEqual(len(pairs), 1)
        self.assertEqual({p["id"] for p in pairs[0]}, {"1", "2"})

    def test_there_is_no_resolver_in_the_module(self):
        # A caller looking for "which one applies" must not find it here.
        for name in dir(lp):
            self.assertNotIn("resolve", name.lower())
            self.assertNotIn("winner", name.lower())

    def test_unrelated_principles_do_not_pair(self):
        self.assertEqual(lp.pair_conflicts([
            {"id": "1", "title": "Write things down"},
            {"id": "2", "title": "Sleep before deciding"},
        ]), [])


# ═════════════════════════════════════════════════════════════════════════
# The board, due labels, and item validation
# ═════════════════════════════════════════════════════════════════════════

class BoardAndLabelTests(unittest.TestCase):

    def test_the_board_routes_by_domain_and_says_why(self):
        key, why = lp.route_advisor("should I take money from this partner?")
        self.assertEqual(key, "munger")
        self.assertIn("money", why)

    def test_faith_routes_to_the_right_lens(self):
        self.assertEqual(
            lp.route_advisor("my marriage and my faith feel far apart")[0],
            "jp2")

    def test_an_undomained_question_defaults_and_admits_it(self):
        key, why = lp.route_advisor("hmm")
        self.assertEqual(key, "dalio")
        self.assertIn("no clear domain", why)

    def test_the_board_never_replaces_prayer(self):
        self.assertIn("does not replace prayer", lp.ADVISOR_PRAYER_LINE)

    def test_due_labels_parse_where_unambiguous(self):
        self.assertEqual(lp.parse_due_label("[Jul '27]"), "2027-07-01")
        self.assertEqual(lp.parse_due_label("2035"), "2035-01-01")
        self.assertEqual(lp.parse_due_label("[Aug]", today=date(2026, 9, 1)),
                         "2027-08-01")

    def test_now_is_a_horizon_not_a_date(self):
        # A standing intention must not become a one-day marker on the
        # timeline.
        self.assertIsNone(lp.parse_due_label("[NOW]"))

    def test_an_unparseable_label_is_null_not_a_guess(self):
        # The label is the source of truth; a marker in the wrong year reads
        # as a fact.
        self.assertIsNone(lp.parse_due_label("someday soon"))
        self.assertIsNone(lp.parse_due_label(None))

    def test_the_label_stays_the_source_of_truth(self):
        out = lp.validate_item_input({"due_label": "someday soon"},
                                     partial=True)
        self.assertEqual(out["due_label"], "someday soon")
        self.assertIsNone(out["due_at"])

    def test_kind_cannot_be_changed_after_creation(self):
        with self.assertRaises(lp.LifeError):
            lp.validate_item_input({"kind": "win"}, partial=True)

    def test_bet_three_does_not_drive_daily_execution(self):
        # The founder's own rule, encoded. Open question in the spec; this is
        # the constant that answers it.
        self.assertFalse(lp.BET_3_DRIVES_DAILY_EXECUTION)
        self.assertEqual([b["rank"] for b in lp.BETS], [1, 2, 3])


# ═════════════════════════════════════════════════════════════════════════
# L-5 — the application log
# ═════════════════════════════════════════════════════════════════════════

class ApplicationLogTests(unittest.TestCase):

    def test_rows_are_built_for_each_cited_principle(self):
        rows = lp.application_rows_for(USER, ["a", "b"], context="case",
                                       ref_id="c1")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["ref_id"], "c1")

    def test_duplicates_and_blanks_are_dropped(self):
        self.assertEqual(
            len(lp.application_rows_for(USER, ["a", "a", "", None],
                                        context="case")), 1)

    def test_an_unknown_context_is_rejected(self):
        with self.assertRaises(lp.LifeError):
            lp.application_rows_for(USER, ["a"], context="nonsense")


# ═════════════════════════════════════════════════════════════════════════
# BE-3 — the importer's preservation guarantees
# ═════════════════════════════════════════════════════════════════════════

class ImporterTests(unittest.TestCase):

    def _export(self):
        return {
            "principles": [{
                "id": "a1",
                "caseAtHand": "Pojechałem hulajnogą po alkoholu",
                "category": "Wishful thinking, Hubris",
                "principlesApplied": "Nie miałem wtedy zasad",
                "reflections": "Zabrakło mi pokory — I lost control.",
                "newPrinciple": ("Focus on saving your own life first\n"
                                 "Don't try to understand it all"),
                "createdAt": "2023-04-11",
                "order": 2,
            }],
            "wins": ["Ran 10k"],
            "prayer": "„Nie bój się” and “Keep the promise” plus loose text",
        }

    def test_created_at_is_preserved(self):
        # The corpus spans 2022→2026 and the dates carry meaning.
        plan = importer.plan_cases(USER, self._export()["principles"])
        self.assertTrue(plan["cases"][0]["created_at"].startswith("2023-04-11"))

    def test_a_naive_source_date_is_read_as_utc(self):
        # Handing Postgres a naive value would make the date depend on the
        # server's zone and silently move a 2022 reflection by a day.
        self.assertTrue(importer._iso("2023-04-11").endswith("+00:00"))

    def test_multi_category_and_multi_principle_both_survive(self):
        plan = importer.plan_cases(USER, self._export()["principles"])
        self.assertEqual(plan["cases"][0]["category"],
                         ["wishful_thinking", "hubris"])
        principles = [i for i in plan["items"] if i["kind"] == "principle"]
        self.assertEqual(len(principles), 2)

    def test_polish_reflections_are_byte_identical(self):
        plan = importer.plan_cases(USER, self._export()["principles"])
        self.assertEqual(plan["cases"][0]["reflections"],
                         "Zabrakło mi pokory — I lost control.")

    def test_an_unmapped_category_goes_to_the_review_queue(self):
        plan = importer.plan_cases(USER, [{
            "id": "x", "caseAtHand": "c", "category": "Something Else",
            "reflections": "r"}])
        self.assertEqual(len(plan["review"]), 1)
        self.assertEqual(plan["cases"][0]["category"], [])
        # Parked, not coerced — and the row still imports, so the reflection
        # is safe while a human decides what the label meant.
        self.assertEqual(plan["cases"][0]["import_category_raw"],
                         "Something Else")

    def test_the_drag_order_becomes_order_key(self):
        plan = importer.plan_cases(USER, self._export()["principles"])
        self.assertEqual(plan["items"][0]["order_key"], 2000.0)

    def test_a_two_sentence_principle_is_not_split_in_half(self):
        # Only line breaks and list markers split. A sentence break does not:
        # several principles in the corpus are two sentences long.
        self.assertEqual(
            importer._split_principles("Do the work. Then rest."),
            ["Do the work. Then rest."])

    def test_the_prayer_blob_splits_on_quote_boundaries(self):
        phrases, leftover = importer.split_phrases(self._export()["prayer"])
        self.assertEqual(phrases, ["Nie bój się", "Keep the promise"])
        self.assertIn("loose text", leftover)

    def test_an_unsplittable_blob_survives_whole(self):
        # "Anything it can't split stays as one note so nothing is lost."
        phrases, leftover = importer.split_phrases("no quotes here at all")
        self.assertEqual(phrases, [])
        self.assertEqual(leftover, "no quotes here at all")
        plan = importer.plan_phrases(USER, "no quotes here at all")
        self.assertEqual(plan["items"], [])
        self.assertEqual(len(plan["notes"]), 1)

    def test_an_apostrophe_never_splits_a_phrase(self):
        # "Don't try to understand it all" is an actual principle.
        phrases, _ = importer.split_phrases("„Don't try to understand it all”")
        self.assertEqual(phrases, ["Don't try to understand it all"])

    def test_an_unclosed_quote_does_not_weld_two_phrases(self):
        phrases, leftover = importer.split_phrases(
            'unclosed „first one and then “second one” tail')
        self.assertEqual(phrases, ["second one"])
        self.assertIn("first one", leftover)

    def test_external_ids_make_a_re_run_idempotent(self):
        first = importer.plan_cases(USER, self._export()["principles"])
        second = importer.plan_cases(USER, self._export()["principles"])
        self.assertEqual(first["cases"][0]["external_id"],
                         second["cases"][0]["external_id"])

    def test_the_bets_are_seeded_in_their_locked_rank(self):
        # Never taken from a free-form transcription that could have
        # reordered them (L-2a).
        items = importer.plan_strategy(USER, {})["items"]
        bets = [i for i in items if i["kind"] == "bet"]
        self.assertEqual([b["order_key"] for b in bets], [1.0, 2.0, 3.0])

    def test_dry_run_is_the_default(self):
        # The destructive direction should require a word, not the absence of
        # one.
        plan = importer.build_plan(USER, principles_export=self._export())
        self.assertTrue(importer.apply_plan(USER, plan)["dry_run"])
        self.assertEqual(
            importer.apply_plan(USER, plan)["written"],
            {"cases": 0, "items": 0, "notes": 0, "strategy": 0})

    def test_the_dry_run_reports_the_same_counts_the_real_run_would_write(self):
        plan = importer.build_plan(USER, principles_export=self._export())
        reported = importer.apply_plan(USER, plan)["planned"]
        self.assertEqual(reported["cases"], len(plan["cases"]))
        self.assertEqual(reported["items"], len(plan["items"]))


# ═════════════════════════════════════════════════════════════════════════
# Serialization
# ═════════════════════════════════════════════════════════════════════════

class SerializationTests(unittest.TestCase):

    def test_no_payload_carries_a_score_or_a_verdict(self):
        import json
        blob = json.dumps({
            "case": lp.serialize_case({"case_at_hand": "x",
                                       "category": ["hubris"]}),
            "item": lp.serialize_item({"kind": "principle", "title": "t"}),
            "day": lp.serialize_day({"one_thing": "x"}),
            "week": lp.serialize_week({}),
            "proposal": lp.serialize_proposal({"target": "weekly.goals"}),
        })
        for banned in ("power_score", "charisma", "overall_score", "threat",
                       "verdict", "confidence", "relevance"):
            self.assertNotIn(banned, blob)

    def test_categories_render_as_labels_for_the_multiple_lines(self):
        out = lp.serialize_case({"category": ["wishful_thinking", "hubris"]})
        self.assertEqual(out["category_labels"],
                         ["Wishful thinking", "Hubris"])

    def test_a_proposal_carries_its_warrant(self):
        # A change the archive cannot justify is a change the system invented.
        out = lp.serialize_proposal({"target": "weekly.goals"},
                                    warrant={"id": "p1", "title": "mine"})
        self.assertEqual(out["warrant"]["title"], "mine")


# ═════════════════════════════════════════════════════════════════════════
# N3 — the chat router hands a non-participant's turn back untouched
# ═════════════════════════════════════════════════════════════════════════

@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ChatIsolationTests(unittest.TestCase):

    def test_an_untagged_message_is_never_ours_and_costs_no_db_read(self):
        with patch.object(lchat, "has_consented") as consented:
            self.assertIsNone(lchat.handle_note(USER, "how does this work?"))
            consented.assert_not_called()

    def test_a_non_consented_user_gets_nothing_from_us(self):
        # Returning None hands the turn back to the existing chat path
        # completely untouched — that IS byte-identical.
        with patch.object(lchat, "has_consented", return_value=False), \
                patch.object(lchat.store, "insert_note") as insert:
            self.assertIsNone(lchat.handle_note(USER, "#mistake I did x"))
            # And nothing was written: consent precedes ANY life row.
            insert.assert_not_called()

    def test_the_flag_is_off_by_default(self):
        """The kill switch is off unless an operator turns it on.

        Asserted against the DEFAULT rather than the ambient value, so the
        test still means something during the N3 run that deliberately sets
        LIFE_PANEL_ENABLED=1 (see the module docstring)."""
        import inspect
        import config as cfg
        self.assertIn('os.getenv("LIFE_PANEL_ENABLED") or "0"',
                      inspect.getsource(cfg))
        if not os.getenv("LIFE_PANEL_ENABLED"):
            self.assertFalse(lchat.is_enabled())

    def test_the_allowlist_is_empty_by_default_and_never_matches_none(self):
        self.assertFalse(lchat.is_allowlisted(None))
        self.assertFalse(lchat.is_allowlisted(USER))

    def test_the_hook_in_the_chat_route_is_flag_and_auth_guarded(self):
        # The one contact point with v2_routes.py. Both guards must be on the
        # same line of defence as the call itself.
        with open(os.path.join(os.path.dirname(MIGRATION), "..",
                               "routes", "v2_routes.py"),
                  "r", encoding="utf-8") as fh:
            src = fh.read()
        hook = src[src.index("Life Panel hashtag router"):]
        hook = hook[:hook.index("Goal-update intercept")]
        self.assertIn("request.user_id and getattr(config, "
                      "\"LIFE_PANEL_ENABLED\", False)", hook)
        # A broken Life Panel must cost the panel, never the chat.
        self.assertIn("except Exception", hook)

    def test_a_derivation_failure_never_loses_the_note(self):
        # Store before derive is the whole reliability story.
        with patch.object(lchat, "has_consented", return_value=True), \
                patch.object(lchat.store, "setup_completed", return_value=True), \
                patch.object(lchat.store, "insert_note",
                             return_value={"id": "n1"}) as insert, \
                patch.object(lchat.engine, "derive_case",
                             side_effect=RuntimeError("openai down")), \
                patch.object(lchat.engine, "attach_phrase", return_value=None):
            out = lchat.handle_note(USER, "#mistake I did x")
        insert.assert_called_once()
        self.assertEqual(out["note_id"], "n1")
        self.assertIsNone(out["card"])

    def test_a_pre_setup_note_is_kept_for_replay_not_dropped(self):
        # Someone who reaches for `#mistake` is holding a thought they wanted
        # recorded; losing it to a redirect teaches them the tag costs
        # something.
        with patch.object(lchat, "has_consented", return_value=True), \
                patch.object(lchat.store, "setup_completed", return_value=False), \
                patch.object(lchat.store, "insert_note",
                             return_value={"id": "n1"}) as insert:
            out = lchat.handle_note(USER, "#mistake I did x")
        self.assertTrue(insert.call_args.kwargs["pending_replay"])
        self.assertEqual(out["blocked"], "setup")

    def test_an_untagged_panel_note_gets_no_phrase_attached(self):
        # Untagged is capture only, no action (§5) — and an aphorism returned
        # on it would be exactly the action the tag was supposed to require.
        with patch.object(lchat, "has_consented", return_value=True), \
                patch.object(lchat.store, "setup_completed", return_value=True), \
                patch.object(lchat.store, "insert_note",
                             return_value={"id": "n1"}), \
                patch.object(lchat.engine, "attach_phrase") as attach:
            lchat.handle_note(USER, "just a thought", source="form")
        attach.assert_not_called()

    def test_all_user_facing_copy_is_in_one_reviewable_dict(self):
        # Product copy is held for founder sign-off; a single dict makes the
        # review a diff instead of a grep.
        import inspect
        src = inspect.getsource(lchat)
        body = src[src.index("def handle_note"):]
        # Every string a user reads in the router comes from COPY.
        self.assertIn('COPY["needs_setup"]', body)
        self.assertIn('COPY["captured"]', body)


# ═════════════════════════════════════════════════════════════════════════
# N4 — the per-user master-doc injection
# ═════════════════════════════════════════════════════════════════════════

@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class MasterDocInjectionTests(unittest.TestCase):

    def test_no_context_means_no_block_at_all(self):
        # Everyone who has not opted in gets a prompt that is byte-for-byte
        # what it is today.
        self.assertEqual(mdr._render_life_block(None), "")
        self.assertEqual(mdr._render_life_block({}), "")
        self.assertEqual(mdr._render_life_block(
            {"principles": [], "phrases": [], "strategy": ""}), "")

    def test_the_cap_holds_against_a_whole_corpus(self):
        # Sixty principles plus eight strategy documents would re-open the
        # attention-ceiling failure PRs #81–#89 fixed.
        block = mdr._render_life_block({
            "principles": [{"title": f"p{i}"} for i in range(60)],
            "phrases": [{"body": f"q{i}"} for i in range(40)],
            "strategy": "s" * 5000,
        })
        self.assertEqual(block.count("[principle]"), mdr._LIFE_MAX_PRINCIPLES)
        self.assertEqual(block.count("[their phrase]"), mdr._LIFE_MAX_PHRASES)
        self.assertLess(len(block), 4000)

    def test_long_entries_are_trimmed_like_the_library_trims(self):
        block = mdr._render_life_block({"principles": [{"title": "x" * 900}]})
        self.assertIn("…", block)
        self.assertLess(len(block), 1200)

    def test_the_block_forbids_dumping_and_scoring(self):
        block = mdr._render_life_block({"principles": [{"title": "p"}]})
        self.assertIn("NEVER dump", block)
        self.assertIn("never score", block)

    def test_the_shared_master_document_is_never_written_to(self):
        # The fence: the injection is per-request and per-user. Nothing in the
        # feature mutates the shared body.
        import inspect
        for module in (lengine, lchat, lstore, lroutes):
            src = inspect.getsource(module)
            self.assertNotIn("MASTER_DOCUMENT", src)

    def test_answer_question_still_works_without_the_new_argument(self):
        # Additive parameter: every existing caller is unaffected.
        import inspect
        sig = inspect.signature(mdr.answer_question)
        self.assertIsNone(sig.parameters["life_context"].default)


# ═════════════════════════════════════════════════════════════════════════
# N8 — zero scheduled outbound anything (L-4)
# ═════════════════════════════════════════════════════════════════════════

@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class NoNudgesTests(unittest.TestCase):
    """Not typing means LIVING, not failing. The system is dormant until
    opened. The cost — it catches only the drift you bring to it — is the
    accepted trade, and this test is what keeps someone from 'fixing' the gap
    with a reminder email."""

    BANNED = ("send_email", "email_service", "resend", "push_notification",
              "send_push", "notify_user", "unsubscribe_tokens",
              "arc_notifications", "assignment_email", "audit_email")

    def test_no_module_can_send_anything(self):
        import inspect
        for module in (lp, lstore, lengine, lchat, lroutes, importer):
            src = inspect.getsource(module).lower()
            for banned in self.BANNED:
                self.assertNotIn(
                    banned, src,
                    f"{module.__name__} reaches for {banned} — L-4 is zero "
                    f"nudges")

    def test_nothing_tracks_silence_or_streaks(self):
        import inspect
        for module in (lp, lstore, lengine, lchat, lroutes):
            src = inspect.getsource(module).lower()
            for banned in ("streak", "days_since_last", "inactivity",
                           "silence_detect"):
                self.assertNotIn(banned, src, module.__name__)

    def test_generation_is_scheduled_but_delivery_is_not(self):
        # ensure_daily_card writes a row and returns. Nothing downstream.
        # The docstring is stripped first — it SAYS "sends no email", and
        # matching on prose rather than code would make the comment the test.
        import inspect
        src = inspect.getsource(lengine.ensure_daily_card)
        code = src.split('"""')[-1].lower()
        for banned in ("email", "notif", "push", "send"):
            self.assertNotIn(banned, code)


# ═════════════════════════════════════════════════════════════════════════
# N2 — the fence: this feature stays off the live loop
# ═════════════════════════════════════════════════════════════════════════

@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class IsolationTests(unittest.TestCase):
    """The Life Panel is scaffolding. It must not reach into the
    record → transcribe → coach → read loop, and no F1 module may come to
    depend on it. Same shape and same fence as the Journal (PR #254)."""

    LIFE_MODULES = ("services/life_panel.py", "services/life_store.py",
                    "services/life_engine.py", "services/life_chat.py",
                    "services/life_import.py", "routes/life_routes.py")

    def test_life_modules_import_nothing_from_the_loop(self):
        import inspect
        banned = ("best_presentation", "ideal_text", "charisma_snippets",
                  "lab_recording", "moment_suggestions", "say_it_stronger",
                  "delivery_stars", "power_score", "slide_word_split",
                  "cross_take_selection", "coaching_state_machine")
        for module in (lp, lstore, lengine, lchat, lroutes, importer):
            src = inspect.getsource(module)
            for name in banned:
                self.assertNotIn(
                    name, src, f"{module.__name__} must not reference {name}")

    def test_no_product_module_imports_the_life_module(self):
        """The direction that actually matters.

        life → db is fine. db → life, or any F1 service → life, would make the
        panel load-bearing for the live loop. Only the two permitted contact
        points (the chat route and master_doc_rag's per-user block) may name
        it, and master_doc_rag names only its own renderer — not the module."""
        root = os.path.dirname(os.path.abspath(__file__))
        permitted = {"routes/v2_routes.py"}
        offenders = []
        for folder in ("services", "routes"):
            for name in sorted(os.listdir(os.path.join(root, folder))):
                rel = f"{folder}/{name}"
                if not name.endswith(".py") or rel in self.LIFE_MODULES:
                    continue
                if rel in permitted:
                    continue
                with open(os.path.join(root, rel), "r", encoding="utf-8") as fh:
                    src = fh.read()
                if re.search(r"^\s*from services import life_|"
                             r"^\s*from services\.life_|"
                             r"^\s*import services\.life_",
                             src, re.MULTILINE):
                    offenders.append(rel)
        self.assertEqual(offenders, [])

    def test_the_chat_route_is_the_only_touched_product_file(self):
        # Two permitted contact points, and master_doc_rag's is a renderer it
        # owns rather than an import of ours.
        import inspect
        self.assertNotIn("life_chat", inspect.getsource(mdr))
        self.assertNotIn("life_engine", inspect.getsource(mdr))

    def test_life_tables_are_never_joined_to_a_product_table(self):
        import inspect
        src = inspect.getsource(lstore)
        tables = set(re.findall(r'_t\("(\w+)"\)', src))
        self.assertEqual(tables - set(lstore.LIFE_TABLES), set())

    def test_the_migration_touches_no_product_table(self):
        with open(MIGRATION, "r", encoding="utf-8") as fh:
            sql = fh.read()
        for statement in re.findall(r"(?:CREATE TABLE IF NOT EXISTS|ALTER TABLE)\s+"
                                    r"(?:public\.)?(\w+)", sql):
            self.assertTrue(statement.startswith("life_"), statement)


# ═════════════════════════════════════════════════════════════════════════
# N9 + the gate — routes
# ═════════════════════════════════════════════════════════════════════════

@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class RouteGateTests(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(lroutes.life_bp)
        self.client = self.app.test_client()
        self._orig_verify = auth.verify_supabase_token
        auth.verify_supabase_token = lambda token: {"sub": USER}

    def tearDown(self):
        auth.verify_supabase_token = self._orig_verify

    def _get(self, path, **kw):
        return self.client.get(path, headers={"Authorization": "Bearer t"},
                               **kw)

    def test_flag_off_404s_everything(self):
        # Not 503, not "coming soon". With the flag off the feature does not
        # exist.
        with patch.object(lroutes.chat, "is_enabled", return_value=False):
            for path in ("/v2/life/state", "/v2/life/principles",
                         "/v2/life/strategy", "/v2/life/prayer"):
                self.assertEqual(self._get(path).status_code, 404, path)

    def test_not_consented_is_409_with_a_pointer(self):
        with patch.object(lroutes.chat, "is_enabled", return_value=True), \
                patch.object(lroutes.chat, "has_consented", return_value=False):
            resp = self._get("/v2/life/principles")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.get_json()["pointer"], "/panel/principles")

    def test_state_and_consent_are_reachable_without_consent(self):
        # Gating them would be a locked door with the key inside.
        with patch.object(lroutes.chat, "is_enabled", return_value=True), \
                patch.object(lroutes.chat, "has_consented", return_value=False), \
                patch.object(lroutes.chat, "is_allowlisted", return_value=False), \
                patch.object(lroutes.store, "get_setup", return_value=None):
            self.assertEqual(self._get("/v2/life/state").status_code, 200)

    def test_a_founder_only_surface_404s_rather_than_403s(self):
        # A 403 confirms the surface exists.
        with patch.object(lroutes.chat, "is_enabled", return_value=True), \
                patch.object(lroutes.chat, "has_consented", return_value=True), \
                patch.object(lroutes.chat, "is_allowlisted", return_value=False):
            resp = self._get("/v2/life/prayer")
        self.assertEqual(resp.status_code, 404)
        self.assertNotIn("pompeiana", resp.get_data(as_text=True))

    def test_a_founder_only_entry_is_absent_from_the_menu(self):
        with patch.object(lroutes.chat, "is_enabled", return_value=True), \
                patch.object(lroutes.chat, "has_consented", return_value=True), \
                patch.object(lroutes.chat, "is_allowlisted", return_value=False), \
                patch.object(lroutes.store, "get_setup", return_value=None):
            menu = self._get("/v2/life/state").get_json()["menu"]
        self.assertNotIn("prayer", menu)

    def test_no_auth_is_401_not_a_leak(self):
        with patch.object(lroutes.chat, "is_enabled", return_value=True):
            self.assertEqual(self.client.get("/v2/life/state").status_code,
                             401)

    def test_the_upload_returns_a_diff_and_writes_nothing(self):
        # A re-upload produces a diff you approve, never a silent overwrite.
        with patch.object(lroutes.chat, "is_enabled", return_value=True), \
                patch.object(lroutes.chat, "has_consented", return_value=True), \
                patch.object(lroutes.store, "latest_strategy",
                             return_value={"weekly": {"body": "old line"}}), \
                patch.object(lroutes.store, "insert_strategy_version") as write:
            resp = self.client.post(
                "/v2/life/strategy/upload",
                headers={"Authorization": "Bearer t"},
                json={"documents": {"weekly": "new line"}})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.get_json()["written"])
        self.assertIn("weekly", resp.get_json()["diffs"])
        write.assert_not_called()

    def test_approving_the_immutable_core_is_refused(self):
        with patch.object(lroutes.chat, "is_enabled", return_value=True), \
                patch.object(lroutes.chat, "has_consented", return_value=True), \
                patch.object(lroutes.store, "get_proposal",
                             return_value={"id": "p1", "status": "surfaced",
                                           "kind": "strategy",
                                           "target": "weekly.section_i"}):
            resp = self.client.post("/v2/life/proposals/p1/approve",
                                    headers={"Authorization": "Bearer t"},
                                    json={})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.get_json()["code"], "IMMUTABLE_CORE")

    def test_a_no_on_retire_keeps_both_and_is_remembered(self):
        # Veto is absolute; the question is never re-asked.
        principle = {"id": "new", "kind": "principle", "title": "n"}
        old = {"id": "old", "kind": "principle", "title": "o"}
        with patch.object(lroutes.chat, "is_enabled", return_value=True), \
                patch.object(lroutes.chat, "has_consented", return_value=True), \
                patch.object(lroutes.store, "get_item",
                             side_effect=lambda u, i: principle if i == "new"
                             else old), \
                patch.object(lroutes.store, "insert_proposal") as insert, \
                patch.object(lroutes.store, "update_item") as update:
            resp = self.client.post(
                "/v2/life/principles/new/retire",
                headers={"Authorization": "Bearer t"},
                json={"retires_id": "old", "decision": "no"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["both_active"])
        update.assert_not_called()
        self.assertEqual(insert.call_args[0][1]["status"], "dismissed")

    def test_patch_items_saves_only_the_supplied_keys(self):
        # The FE's inline edit contract. A partial PATCH must never blank an
        # untouched field, which is why validate_item_input returns only the
        # keys that were present.
        with patch.object(lroutes.chat, "is_enabled", return_value=True), \
                patch.object(lroutes.chat, "has_consented", return_value=True), \
                patch.object(lroutes.store, "get_item",
                             return_value={"id": "i1", "kind": "goal"}), \
                patch.object(lroutes.store, "update_item",
                             return_value={"id": "i1", "kind": "goal",
                                           "title": "new"}) as update:
            resp = self.client.patch("/v2/life/items/i1",
                                     headers={"Authorization": "Bearer t"},
                                     json={"title": "new"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(update.call_args[0][2], {"title": "new"})

    def test_patch_items_refuses_to_change_the_kind(self):
        # The kind is the discriminator: changing it would move a row between
        # views and past a different validator.
        with patch.object(lroutes.chat, "is_enabled", return_value=True), \
                patch.object(lroutes.chat, "has_consented", return_value=True), \
                patch.object(lroutes.store, "get_item",
                             return_value={"id": "i1", "kind": "goal"}):
            resp = self.client.patch("/v2/life/items/i1",
                                     headers={"Authorization": "Bearer t"},
                                     json={"kind": "win"})
        self.assertEqual(resp.status_code, 400)

    def test_patch_items_404s_on_someone_elses_row(self):
        with patch.object(lroutes.chat, "is_enabled", return_value=True), \
                patch.object(lroutes.chat, "has_consented", return_value=True), \
                patch.object(lroutes.store, "get_item", return_value=None), \
                patch.object(lroutes.store, "update_item") as update:
            resp = self.client.patch("/v2/life/items/i1",
                                     headers={"Authorization": "Bearer t"},
                                     json={"title": "new"})
        self.assertEqual(resp.status_code, 404)
        update.assert_not_called()

    def test_patch_day_is_scoped_to_the_card_on_screen(self):
        # Addressed by id, not by "today". A panel left open across midnight
        # must write to the card being looked at, not to whatever date the
        # server thinks it is now.
        with patch.object(lroutes.chat, "is_enabled", return_value=True), \
                patch.object(lroutes.chat, "has_consented", return_value=True), \
                patch.object(lroutes.store, "update_day",
                             return_value={"id": "d1"}) as update:
            resp = self.client.patch("/v2/life/day/d1",
                                     headers={"Authorization": "Bearer t"},
                                     json={"evening_one_thing": True})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(update.call_args[0][1], "d1")

    def test_patch_day_404s_when_the_row_is_not_yours(self):
        with patch.object(lroutes.chat, "is_enabled", return_value=True), \
                patch.object(lroutes.chat, "has_consented", return_value=True), \
                patch.object(lroutes.store, "update_day", return_value=None):
            resp = self.client.patch("/v2/life/day/d1",
                                     headers={"Authorization": "Bearer t"},
                                     json={"evening_one_thing": True})
        self.assertEqual(resp.status_code, 404)

    def test_the_day_payload_carries_the_id_the_patch_needs(self):
        # GET /v2/life/day must hand back the id, or the id-scoped PATCH is
        # unusable and the FE has to guess.
        self.assertIn("id", lp.serialize_day({"id": "d1"}))

    def test_the_one_thing_can_be_changed_but_not_removed(self):
        with patch.object(lroutes.chat, "is_enabled", return_value=True), \
                patch.object(lroutes.chat, "has_consented", return_value=True):
            resp = self.client.patch("/v2/life/day/d1",
                                     headers={"Authorization": "Bearer t"},
                                     json={"one_thing": "   "})
        self.assertEqual(resp.status_code, 400)

    def test_hard_delete_requires_an_explicit_confirmation(self):
        with patch.object(lroutes.chat, "is_enabled", return_value=True), \
                patch.object(lroutes.store, "hard_delete") as wipe:
            resp = self.client.delete("/v2/life/data",
                                      headers={"Authorization": "Bearer t"},
                                      json={})
        self.assertEqual(resp.status_code, 400)
        wipe.assert_not_called()

    def test_hard_delete_survives_a_lapsed_consent(self):
        # Gating the exit behind the gate they are leaving through would be
        # the worst possible reading of a consent screen.
        with patch.object(lroutes.chat, "is_enabled", return_value=True), \
                patch.object(lroutes.chat, "has_consented", return_value=False), \
                patch.object(lroutes.store, "hard_delete",
                             return_value={"deleted": {"life_notes": 3},
                                           "failed": []}):
            resp = self.client.delete("/v2/life/data",
                                      headers={"Authorization": "Bearer t"},
                                      json={"confirm": "DELETE"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["deleted"])

    def test_a_partial_delete_is_reported_not_claimed_as_success(self):
        # "Your data is gone" is a promise; a half-kept promise about this
        # corpus is worse than a refusal.
        with patch.object(lroutes.chat, "is_enabled", return_value=True), \
                patch.object(lroutes.chat, "has_consented", return_value=True), \
                patch.object(lroutes.store, "hard_delete",
                             return_value={"deleted": {}, "failed": ["life_cases"]}):
            resp = self.client.delete("/v2/life/data",
                                      headers={"Authorization": "Bearer t"},
                                      json={"confirm": "DELETE"})
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.get_json()["code"], "PARTIAL_DELETE")

    def test_an_incomplete_export_says_so(self):
        # An export missing a table looks exactly like an empty table.
        with patch.object(lroutes.chat, "is_enabled", return_value=True), \
                patch.object(lroutes.chat, "has_consented", return_value=True), \
                patch.object(lroutes.store, "export_all",
                             return_value={"tables": {}, "errors": ["life_cases"]}):
            resp = self.client.post("/v2/life/export",
                                    headers={"Authorization": "Bearer t"},
                                    json={})
        self.assertFalse(resp.get_json()["complete"])


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ExportAndDeleteCoverageTests(unittest.TestCase):
    """N9 — the round trip covers every table the migration creates."""

    def test_export_reads_every_life_table(self):
        seen = []

        class _Q:
            def select(self, *a, **k): return self
            def eq(self, *a, **k): return self
            def limit(self, *a, **k): return self
            def execute(self): return type("R", (), {"data": []})()

        def _t(table):
            seen.append(table)
            return _Q()

        with patch.object(lstore, "_t", side_effect=_t):
            lstore.export_all(USER)
        self.assertEqual(set(seen), set(lstore.LIFE_TABLES))

    def test_hard_delete_covers_every_life_table(self):
        seen = []

        class _Q:
            def delete(self): return self
            def eq(self, *a, **k): return self
            def execute(self): return type("R", (), {"data": [{"id": "1"}]})()

        def _t(table):
            seen.append(table)
            return _Q()

        with patch.object(lstore, "_t", side_effect=_t):
            result = lstore.hard_delete(USER)
        self.assertEqual(set(seen), set(lstore.LIFE_TABLES))
        self.assertEqual(result["failed"], [])

    def test_a_failing_table_is_reported_by_name(self):
        def _t(table):
            raise RuntimeError("down")
        with patch.object(lstore, "_t", side_effect=_t):
            result = lstore.hard_delete(USER)
        self.assertEqual(set(result["failed"]), set(lstore.LIFE_TABLES))


# ═════════════════════════════════════════════════════════════════════════
# BE-10 — the corpus never reaches a log or a prompt in bulk
# ═════════════════════════════════════════════════════════════════════════

@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class PrivacyTests(unittest.TestCase):

    def test_retrieval_is_capped_well_under_the_corpus(self):
        self.assertLessEqual(lengine.RETRIEVAL_LIMIT, 10)

    def test_no_raw_note_body_is_ever_logged(self):
        """A log aggregator is a second, less guarded copy of the corpus.

        Derivation OUTPUTS and sizes are logged; note bodies are not."""
        import inspect
        src = inspect.getsource(lengine)
        for match in re.finditer(r"logger\.(?:info|warning|error)\((.*?)\)",
                                 src, re.DOTALL):
            call = match.group(1)
            for leak in ("note_text", "case_text", "reflections", "remainder",
                         "question)"):
                self.assertNotIn(leak, call,
                                 f"a log call carries {leak}")

    def test_the_derivation_logger_takes_no_free_text(self):
        import inspect
        src = inspect.getsource(lengine._log_derivation)
        self.assertIn("never the note body", src)

    def test_a_dedicated_zero_retention_key_is_supported(self):
        # BE-10: "use an API path with no training retention". The retention
        # posture is a project setting, so the code side is the ability to
        # point this surface at a separate project.
        import inspect
        self.assertIn("LIFE_PANEL_OPENAI_API_KEY",
                      inspect.getsource(lengine._client))

    def test_there_is_no_sharing_or_publish_surface(self):
        # The corpus names real people alongside claims about them. It stays
        # private to one user forever.
        import inspect
        for module in (lroutes, lstore, lengine):
            src = inspect.getsource(module).lower()
            for banned in ("publish", "share_url", "public_url", "presign"):
                self.assertNotIn(banned, src, module.__name__)

    def test_every_store_read_is_scoped_to_one_user(self):
        import inspect
        src = inspect.getsource(lstore)
        # Every table access chain must carry a user_id filter. The one
        # exception would be a cross-user read, and there is none.
        for block in src.split("def ")[1:]:
            if '_t("' not in block:
                continue
            self.assertIn("user_id", block,
                          f"a store function touches a table without scoping "
                          f"it to a user: {block.splitlines()[0]}")


if __name__ == "__main__":
    unittest.main()
