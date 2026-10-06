"""0454 (an_erasure_voids_the_released_copies.sql), read as text.

The released-lane rehearsal
(tests/test_an_erasure_voids_the_released_copies_postgres.py) executes it;
this pins what a reader of the file relies on:

  * it is 0454 in the manifest, applied twice by the released lane after
    0453, and its suite is in the tier;
  * it is additive: one transaction, no destructive statement, every
    function closed to browser roles and open to service_role, no
    environment variable read;
  * each of the four functions it re-issues is its LATEST definition in
    manifest order plus the one statement it is re-issued for, in the place
    that statement must run, and nothing else; the weekly refresh is not
    re-issued (new releases are the export's eligibility decision's);
  * the void has two reasons of its own, apart from the refresh's, and
    sends a voided release's pairs back to waiting as the refresh does.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"
NAME = "an_erasure_voids_the_released_copies.sql"
VERSION = "0454"
SQL = (MIGRATIONS / NAME).read_text()

sys.path.insert(0, str(ROOT / "scripts"))
import migrate  # noqa: E402


def _function(sql: str, name: str) -> str:
    start = sql.index(f"CREATE OR REPLACE FUNCTION public.{name}(")
    body = sql.index("$$", start)
    return sql[start:sql.index("$$;", body + 2) + 3]


def _squash(text: str) -> str:
    text = re.sub(r"--[^\n]*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _manifest() -> list[tuple[str, str]]:
    rows = []
    for line in (MIGRATIONS / "manifest.txt").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            version, filename = line.split("\t")
            rows.append((version, filename))
    return rows


def _latest_before(name: str) -> tuple[str, str]:
    """The last file before 0454, in manifest order, defining `name`."""
    found = None
    for version, filename in _manifest():
        if version == VERSION:
            break
        if f"FUNCTION public.{name}(" in (MIGRATIONS / filename).read_text():
            found = (version, filename)
    assert found, name
    return found


#: The one statement each re-issued function gains, as written in the file.
ADDED = {
    "stop_phase1_learning_v1": """
    PERFORM public.void_pair_releases_v1(ARRAY(
        SELECT listed.release_id FROM public.pair_release_owners listed
         WHERE listed.owner_principal_id = p_acquisition_principal_id
        UNION
        SELECT pair.release_id FROM public.feedback_pairs pair
         WHERE pair.owner_principal_id = p_acquisition_principal_id
           AND pair.release_id IS NOT NULL
    ), 'owner_erasure_requested');""",
    "request_project_deletion_v1":
        "PERFORM public.void_project_pair_releases_v1(p_project_id);",
    "start_due_project_deletion_v1":
        "PERFORM public.void_project_pair_releases_v1(request.project_id);",
    "confirm_project_deletion_v1":
        "PERFORM public.void_project_pair_releases_v1(request.project_id);",
}

#: Where each latest definition lives today. A later migration that
#: re-issues one of them must move this, and re-pin what it changes.
LATEST = {
    "stop_phase1_learning_v1": "a_deletion_completes_after_seven_days.sql",
    "request_project_deletion_v1": "a_project_deletion_can_be_requested.sql",
    "start_due_project_deletion_v1": "a_deletion_completes_after_seven_days.sql",
    "confirm_project_deletion_v1": "one_project_can_be_purged.sql",
}

NEW = {"void_pair_releases_v1", "void_project_pair_releases_v1"}


class MigrationTests(unittest.TestCase):

    def test_it_is_0454_applied_twice_after_0453_and_its_suite_runs(self):
        manifest = _manifest()
        self.assertIn((VERSION, NAME), manifest)
        self.assertEqual(manifest[manifest.index((VERSION, NAME)) - 1],
                         ("0453", "v4_asks_coaches_two_blind_questions.sql"))
        recipe = (ROOT / "tests/integration/confident_moment_rehearsal.sh").read_text()
        self.assertEqual(recipe.count(f"hard migrations/{NAME}"), 2)
        first = recipe.index(f"hard migrations/{NAME}")
        self.assertLess(recipe.rindex("hard migrations/a_skip_keeps_an_empty_receipt.sql"),
                        first)
        # Released lane only: inside the nearest `if [ "$LANE" = "released" ]`.
        opened = recipe.rindex('if [ "$LANE" = "released" ]; then\n', 0, first)
        self.assertNotIn("\nfi", recipe[opened:first])
        self.assertTrue(recipe[first:].startswith(
            f"hard migrations/{NAME}\n  hard migrations/{NAME}\nfi\n"))
        tier = (ROOT / "scripts/rehearsal_tier.sh").read_text()
        self.assertIn("tests/test_an_erasure_voids_the_released_copies_postgres.py", tier)

    def test_it_is_one_additive_transaction_closed_to_browsers(self):
        self.assertEqual(migrate.destructive_statements(SQL), [])
        self.assertEqual(migrate.unbalanced_delimiters(SQL), [])
        body = _squash(SQL)
        self.assertTrue(body.startswith("BEGIN;"))
        self.assertTrue(body.endswith("COMMIT;"))
        self.assertEqual((body.count("BEGIN;"), body.count("COMMIT;")), (1, 1))
        for statement in ("CREATE TABLE", "ALTER TABLE", "DROP ", "TRUNCATE",
                          "DELETE FROM", "current_setting", "GRANT INSERT",
                          "GRANT UPDATE", "GRANT DELETE", "GRANT ALL"):
            self.assertNotIn(statement, body, statement)
        functions = set(re.findall(r"CREATE OR REPLACE FUNCTION public\.(\w+)\(", SQL))
        self.assertEqual(functions, NEW | set(ADDED))
        for name in functions:
            self.assertRegex(SQL, rf"REVOKE ALL ON FUNCTION public\.{name}\([^;]*\)\s+"
                                  r"FROM PUBLIC, anon, authenticated;", name)
            self.assertRegex(SQL, rf"GRANT EXECUTE ON FUNCTION public\.{name}\([^;]*\)\s+"
                                  r"TO service_role;", name)
            self.assertIn("SECURITY DEFINER SET search_path = public", _function(SQL, name))

    def test_each_reissued_function_is_its_latest_definition_plus_one_statement(self):
        for name, added in ADDED.items():
            with self.subTest(name):
                version, filename = _latest_before(name)
                self.assertEqual(filename, LATEST[name])
                self.assertLess(int(version), int(VERSION))
                before = _squash(_function((MIGRATIONS / filename).read_text(), name))
                after = _squash(_function(SQL, name))
                statement = _squash(added)
                self.assertEqual(after.count(statement), 1)
                self.assertEqual(after.replace(statement + " ", "", 1), before)

    def test_each_statement_runs_where_it_must(self):
        def order(name: str, *marks: str) -> None:
            body = _squash(_function(SQL, name))
            places = [body.index(_squash(mark)) for mark in marks]
            self.assertEqual(places, sorted(places), name)

        # After the person's pairs leave the pool, before the count returns.
        order("stop_phase1_learning_v1", "SET releasable = false",
              "GET DIAGNOSTICS v_count = ROW_COUNT;", ADDED["stop_phase1_learning_v1"],
              "RETURN v_count;")
        # Only once a new request is written: a replay or an open request
        # returns before it.
        order("request_project_deletion_v1", "RETURN request; END IF;",
              "INSERT INTO public.project_deletion_requests",
              ADDED["request_project_deletion_v1"], "RETURN request; END;")
        # Once the purge request exists, before the request is confirmed.
        for name in ("start_due_project_deletion_v1", "confirm_project_deletion_v1"):
            order(name, "INSERT INTO public.data_purge_requests",
                  "SELECT id INTO purge_id", ADDED[name], "SET state = 'confirmed'")

    def test_the_weekly_refresh_is_left_as_it_was(self):
        self.assertNotIn("refresh_feedback_pair_consent_v1", _squash(SQL))
        self.assertNotIn("releasable =", _squash(_function(SQL, "void_project_pair_releases_v1")))
        self.assertNotIn("SET releasable", _squash(_function(SQL, "void_pair_releases_v1")))

    def test_the_void_has_reasons_of_its_own_and_sends_pairs_back_as_the_refresh_does(self):
        void = _squash(_function(SQL, "void_pair_releases_v1"))
        self.assertIn("p_reason NOT IN ( 'owner_erasure_requested', "
                      "'project_erasure_requested' )", void)
        self.assertIn("AND release.voided_at IS NULL", void)
        version, filename = _latest_before("refresh_feedback_pair_consent_v1")
        refresh = _squash(_function((MIGRATIONS / filename).read_text(),
                                    "refresh_feedback_pair_consent_v1"))
        reset = "SET release_id = NULL, exported_at = NULL"
        self.assertIn(reset, refresh)
        self.assertIn(reset, void)
        for reason in ("owner_erasure_requested", "project_erasure_requested"):
            self.assertNotIn(reason, refresh)
        for reason in ("consent_withdrawn", "owner_service_ended"):
            self.assertIn(reason, refresh)
            self.assertNotIn(reason, void)
        project = _squash(_function(SQL, "void_project_pair_releases_v1"))
        self.assertIn("'project_erasure_requested'", project)
        # The project's Takes as the one-project purge finds them.
        version, filename = _latest_before("resolve_phase1_purge_project_graph_v1")
        graph = _squash(_function((MIGRATIONS / filename).read_text(),
                                  "resolve_phase1_purge_project_graph_v1"))
        takes = "session.project_id = p_project_id OR session.arc_id = p_project_id::text"
        self.assertIn(takes, graph)
        self.assertIn(takes, project)

    def test_requests_made_before_it_get_what_their_request_would_have_done(self):
        tail = _squash(SQL[SQL.rindex("DO $$"):])
        self.assertEqual(tail, _squash("""
            DO $$
            BEGIN
                PERFORM public.stop_phase1_learning_v1(principal.id)
                   FROM public.owner_principals principal
                  WHERE public.phase1_learning_stopped_v1(principal.id);
                PERFORM public.void_project_pair_releases_v1(request.project_id)
                   FROM public.project_deletion_requests request
                  WHERE request.state IN ('pending', 'confirmed');
            END;
            $$;

            COMMIT;"""))


if __name__ == "__main__":
    unittest.main()
