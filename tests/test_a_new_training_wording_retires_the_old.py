"""0458 (a_new_training_wording_retires_the_old.sql), read as text.

The released-lane rehearsal
(tests/test_a_new_training_wording_retires_the_old_postgres.py) executes it;
this pins what a reader of the file relies on:

  * it is 0458 in the manifest, after 0457, applied twice by the released
    lane, and its suite is in the tier;
  * it is one transaction with no destructive statement and no environment
    read; it grants nothing to anyone, and revokes both functions from
    PUBLIC, the browser roles and service_role;
  * the trigger keeps 0302's name and message, and its one door is the
    supersede function's transaction-local setting, walked through only as
    that function's owner; the function locks the corpus before it counts
    every copy not yet purged; it sets the setting
    only around its one UPDATE, before it registers the successor through
    0373's configure function;
  * every reader of the training yes still ties a grant to a policy in force
    now, so a retired policy's yes reads as off without a row rewritten.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"
NAME = "a_new_training_wording_retires_the_old.sql"
VERSION = "0458"
SQL = (MIGRATIONS / NAME).read_text()
IN_FORCE = ("AND policy.active_from <= now() "
            "AND (policy.retired_at IS NULL OR policy.retired_at > now())")

sys.path.insert(0, str(ROOT / "scripts"))
import migrate  # noqa: E402


def _squash(text: str) -> str:
    text = re.sub(r"--[^\n]*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _function(sql: str, name: str) -> str:
    start = sql.index(f"CREATE OR REPLACE FUNCTION public.{name}(")
    body = sql.index("$$", start)
    return sql[start:sql.index("$$;", body + 2) + 3]


def _manifest() -> list[tuple[str, str]]:
    rows = []
    for line in (MIGRATIONS / "manifest.txt").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            version, filename = line.split("\t")
            rows.append((version, filename))
    return rows


def _latest(name: str) -> str:
    """The latest definition of a function, in manifest order."""
    found = ""
    for _, filename in _manifest():
        path = MIGRATIONS / filename
        if not path.exists():
            continue
        text = path.read_text()
        if f"CREATE OR REPLACE FUNCTION public.{name}(" in text:
            found = _function(text, name)
    assert found, name
    return found


class MigrationTests(unittest.TestCase):

    def test_it_is_0458_after_0457_and_its_suite_runs(self):
        manifest = _manifest()
        self.assertIn((VERSION, NAME), manifest)
        self.assertEqual(manifest[manifest.index((VERSION, NAME)) - 1],
                         ("0457", "the_v4_dark_writes_keep_their_word.sql"))
        recipe = (ROOT / "tests/integration/confident_moment_rehearsal.sh").read_text()
        self.assertEqual(recipe.count(f"hard migrations/{NAME}"), 2)
        tier = (ROOT / "scripts/rehearsal_tier.sh").read_text()
        released = next(line for line in tier.splitlines()
                        if line.lstrip().startswith('"confident-moment released|'))
        self.assertIn("tests/test_a_new_training_wording_retires_the_old_postgres.py",
                      released)

    def test_it_is_one_transaction_that_grants_nothing(self):
        self.assertEqual(migrate.destructive_statements(SQL), [])
        self.assertEqual(migrate.unbalanced_delimiters(SQL), [])
        body = _squash(SQL)
        self.assertTrue(body.startswith("BEGIN;"))
        self.assertTrue(body.endswith("COMMIT;"))
        self.assertEqual((body.count("BEGIN;"), body.count("COMMIT;")), (1, 1))
        for statement in ("CREATE TABLE", "ALTER TABLE", "TRUNCATE", "DELETE FROM",
                          "GRANT ", "DO $$", "getenv", "INSERT INTO"):
            self.assertNotIn(statement, body, statement)
        self.assertEqual(re.findall(r"CREATE OR REPLACE FUNCTION public\.(\w+)\(", SQL),
                         ["guard_ml_consent_policy_mutation_v1",
                          "supersede_mlc2_training_consent_policy_v1"])
        self.assertIn("REVOKE ALL ON FUNCTION public.guard_ml_consent_policy_mutation_v1() "
                      "FROM PUBLIC, anon, authenticated, service_role;", body)
        self.assertIn("TEXT, TEXT, TIMESTAMPTZ) FROM PUBLIC, anon, authenticated, "
                      "service_role;", body)

    def test_the_trigger_keeps_its_name_and_message(self):
        body = _squash(SQL)
        self.assertIn("DROP TRIGGER IF EXISTS ml_consent_policies_append_only "
                      "ON public.ml_consent_policies;", body)
        self.assertIn("CREATE TRIGGER ml_consent_policies_append_only BEFORE UPDATE OR "
                      "DELETE ON public.ml_consent_policies FOR EACH ROW EXECUTE "
                      "FUNCTION public.guard_ml_consent_policy_mutation_v1();", body)
        guard = _squash(_function(SQL, "guard_ml_consent_policy_mutation_v1"))
        self.assertIn("RAISE EXCEPTION 'MLC-2 canonical records are append-only'", guard)
        for condition in ("TG_OP = 'UPDATE'", "door = OLD.version",
                          "OLD.grant_scope = 'training_only'",
                          "OLD.retired_at IS NULL", "NEW.retired_at IS NOT NULL",
                          "(to_jsonb(NEW) - 'retired_at') = (to_jsonb(OLD) - 'retired_at')",
                          "current_user = ( SELECT pg_get_userbyid(fn.proowner)",
                          "'public.supersede_mlc2_training_consent_policy_v1(text, text, '"):
            self.assertIn(condition, guard)
        # The door is named by this file's function alone.
        door = "willab.training_policy_supersede"
        for path in MIGRATIONS.glob("*.sql"):
            if path.name != NAME:
                self.assertNotIn(door, path.read_text(), path.name)

    def test_the_door_opens_around_one_update_then_configure_registers(self):
        fn = _squash(_function(SQL, "supersede_mlc2_training_consent_policy_v1"))
        open_at = fn.index("set_config('willab.training_policy_supersede', predecessor.version, true)")
        update_at = fn.index("UPDATE public.ml_consent_policies SET retired_at = p_active_from")
        close_at = fn.index("set_config('willab.training_policy_supersede', '', true)")
        register_at = fn.rindex("public.configure_mlc2_training_consent_policy_v1(")
        self.assertLess(open_at, update_at)
        self.assertLess(update_at, close_at)
        self.assertLess(close_at, register_at)
        self.assertEqual(fn.count("UPDATE public."), 1)
        self.assertLess(fn.index("TRAINING_POLICY_PREDECESSOR_HAS_ACTIVE_COPIES"), open_at)
        self.assertLess(fn.index("TRAINING_POLICY_SWITCH_IN_THE_PAST"), open_at)
        # The corpus is held still before it is checked, and every copy not
        # yet purged (active, purge_pending, or any later state) blocks.
        lock_at = fn.index("LOCK TABLE public.training_corpus_items IN SHARE ROW "
                           "EXCLUSIVE MODE;")
        self.assertLess(lock_at, fn.index("FROM public.training_corpus_items item"))
        self.assertIn("AND item.state <> 'purged'", fn)
        self.assertNotIn("item.state = 'active'", fn)
        publish = _squash((ROOT / "legal/phase1-2026.1/PUBLISH-3.5-2026-10-08.sql")
                          .read_text())
        self.assertIn("AND item.state <> 'purged') AS active_training_copies_under_v1",
                      publish)

    def test_every_reader_ties_a_yes_to_a_policy_in_force_now(self):
        status = _squash(_latest("get_mlc2_training_consent_status_v2"))
        self.assertIn(IN_FORCE, status)
        grant = _squash(_latest("record_mlc2_training_consent_grant_v2"))
        self.assertIn("AND active_from <= p_occurred_at AND (retired_at IS NULL OR "
                      "retired_at > p_occurred_at);", grant)
        view = _squash((MIGRATIONS / "a_pair_remembers_the_yes.sql").read_text())
        view = view[view.index("CREATE OR REPLACE VIEW public.training_consent_active_grants"):]
        self.assertIn(IN_FORCE, view[:view.index(";")])


if __name__ == "__main__":
    unittest.main()
