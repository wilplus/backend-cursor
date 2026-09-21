"""One variable named after a column made the V3 write impossible.

PRODUCTION, 2026-09-21. With 0344's parenthesis in place the candidate-set
write got past its advisory lock for the first time, ran every insert, and
then PostgreSQL answered on the first count:

    {'code': '42702', 'message': 'column reference "candidate_set_id" is
     ambiguous', 'details': 'It could refer to either a PL/pgSQL variable
     or a table column.'}

THE LINES, in ``record_feedback_v3_service_candidate_set_v1`` (D2):

    DECLARE
        candidate_set_id UUID;
    ...
     WHERE row.candidate_set_id = candidate_set_id;

PL/pgSQL's default ``variable_conflict = error`` refuses to guess which
``candidate_set_id`` the right-hand side means. The comparison appears four
times in the body, so no path past the inserts could finish. 0348 states the
author's own convention (every column is alias-qualified; a bare name is a
variable) as ``#variable_conflict use_variable`` at the top of the body.

The reproduction and the repaired call run for real against a disposable
PostgreSQL in ``tests/test_mlc3_general_user_service_d4_postgres.py``. These
assertions read the migration text, so the registration and the in-place
repair discipline are guarded in the unit tier too.
"""
from __future__ import annotations

import pathlib
import unittest

MIGRATIONS = pathlib.Path(__file__).resolve().parent.parent / "migrations"
FIX = MIGRATIONS / "the_candidate_set_writer_resolves_its_own_variable.sql"
MANIFEST = MIGRATIONS / "manifest.txt"


def _sql(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


class TheFixIsRegistered(unittest.TestCase):
    def test_the_migration_exists(self):
        self.assertTrue(FIX.is_file())

    def test_it_is_in_the_manifest_after_0347(self):
        # A migration outside the manifest never runs. `MIGRATE_ON_BOOT=1`
        # makes the manifest the difference between shipped and inert.
        lines = _sql(MANIFEST).splitlines()
        self.assertIn(f"0348\t{FIX.name}", lines)
        self.assertEqual(lines[-1], f"0348\t{FIX.name}")

    def test_it_repairs_in_place_rather_than_re_creating_the_function(self):
        # D4 rewrote this body to swap the resolver and 0344 parenthesised
        # its lock key. Re-issuing D2's text would revert both, so the fix
        # reads the CURRENT definition and inserts one line into it.
        body = _sql(FIX)
        self.assertIn("pg_get_functiondef", body)
        self.assertNotIn("CREATE OR REPLACE FUNCTION", body)
        self.assertIn("#variable_conflict use_variable", body)

    def test_it_is_idempotent_and_degrades(self):
        body = _sql(FIX)
        self.assertIn("to_regprocedure", body)
        self.assertIn("pragma present, no change", body)
        self.assertIn("absent, nothing to repair", body)

    def test_it_refuses_rather_than_guessing_on_an_unexpected_shape(self):
        self.assertIn("CANDIDATE_SET_BODY_SHAPE_UNEXPECTED", _sql(FIX))
