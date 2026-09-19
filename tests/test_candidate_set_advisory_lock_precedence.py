"""One missing pair of parentheses made the V3 write impossible.

PRODUCTION, 2026-09-19. The first time V3 ever reached its candidate-set
write -- ``piece_has_no_part_id`` had stood it down before this point on
every Take since the cutover -- PostgreSQL answered:

    {'code': '22P02', 'details': 'Token "feedback" is invalid.',
     'message': 'invalid input syntax for type json'}

THE LINE, in ``record_feedback_v3_service_candidate_set_v1`` (D2):

    PERFORM pg_advisory_xact_lock(hashtextextended(
        'feedback-v3-service-candidate-set:' ||
        p_bundle->>'idempotency_key', 0
    ));

``||`` and ``->>`` are both in PostgreSQL's "any other operator" precedence
class and LEFT associative, so that is not ``literal || (p_bundle->>'key')``.
It is ``(literal || p_bundle) ->> 'key'``, which resolves to
``jsonb || jsonb``, coerces the literal to jsonb, and asks the JSON lexer to
read ``feedback-v3-service-candidate-set:``. It takes the bare word
``feedback``, meets the ``-``, and raises 22P02.

Reproduced byte for byte on a local PostgreSQL 16 before the fix existed:

    SELECT hashtextextended('feedback-v3-service-candidate-set:' ||
                            '{"idempotency_key":"k"}'::jsonb->>'k', 0);
    ERROR:  invalid input syntax for type json
    DETAIL:  Token "feedback" is invalid.

and then, with the migration applied to a function carrying the same broken
expression, returning a row instead.

WHY A TEXT TEST AND NOT ONLY A POSTGRES ONE. The rehearsal tier proves the
repaired function runs; it cannot prove nobody writes the bug again in a new
migration, because a new migration's function is new SQL. These assertions
read the migration text, so the pattern itself is what is guarded -- the
cheapest place to catch the only class of defect that can make an entire
feature unreachable while every unit test stays green.
"""
from __future__ import annotations

import pathlib
import re
import unittest

MIGRATIONS = pathlib.Path(__file__).resolve().parent.parent / "migrations"
FIX = MIGRATIONS / "fix_candidate_set_advisory_lock_precedence.sql"
MANIFEST = MIGRATIONS / "manifest.txt"

# `'literal' || something->>'key'` with no parentheses: the exact shape that
# binds as `(literal || something) ->> 'key'`.
UNPARENTHESISED = re.compile(
    r"'[^']*'\s*\|\|\s*[A-Za-z_][A-Za-z0-9_]*\s*->>", re.MULTILINE)

# THE ONE THAT SHIPPED, AND WHY IT STAYS IN THE FILE. A released migration is
# never edited -- the tree is the history of what ran, and rewriting D2 would
# make every cluster that already applied it disagree with its own record.
# 0344 repairs the installed function instead. So this line is expected to
# remain here forever, and the guard below carries it as a named baseline
# rather than being loosened until it stops seeing it. Anything NOT on this
# list is a new occurrence and fails.
REPAIRED_IN_0344 = frozenset({
    ("add_mlc3_first_client_service_d2.sql", 1907),
})


def _sql(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


class TheFixIsRegistered(unittest.TestCase):
    def test_the_migration_exists(self):
        self.assertTrue(FIX.is_file())

    def test_it_is_in_the_manifest(self):
        # A migration outside the manifest never runs. `MIGRATE_ON_BOOT=1`
        # makes the manifest the difference between shipped and inert.
        self.assertIn(FIX.name, _sql(MANIFEST))

    def test_it_repairs_in_place_rather_than_re_creating_the_function(self):
        # D4 rewrites this function's body to swap the resolver. Re-issuing
        # D2's text would silently revert that cutover, so the fix reads the
        # CURRENT definition and replaces one expression in it.
        body = _sql(FIX)
        self.assertIn("pg_get_functiondef", body)
        self.assertNotIn("CREATE OR REPLACE FUNCTION", body)

    def test_it_is_idempotent_and_degrades(self):
        body = _sql(FIX)
        self.assertIn("to_regprocedure", body)
        self.assertIn("already parenthesised", body)
        self.assertIn("absent, nothing to repair", body)

    def test_it_refuses_rather_than_guessing_on_an_unexpected_shape(self):
        # `idempotency_key` appears five times in that body; only the
        # advisory-lock call carries the `, 0` seed. Replacing "all of them"
        # if that ever stops being true would rewrite statements nobody
        # reviewed here.
        self.assertIn("CANDIDATE_SET_LOCK_PATTERN_UNEXPECTED", _sql(FIX))


class TheBugDoesNotComeBack(unittest.TestCase):
    """The pattern, not the instance."""

    def test_no_migration_concatenates_a_literal_onto_a_bare_json_arrow(self):
        offenders: list[str] = []
        for path in sorted(MIGRATIONS.glob("*.sql")):
            text = _sql(path)
            # Collapse the newline the original spanned, so a break between
            # `||` and the operand cannot hide the pattern -- which is
            # exactly how it survived review the first time.
            joined = re.sub(r"\|\|\s*\n\s*", "|| ", text)
            for match in UNPARENTHESISED.finditer(joined):
                line = joined[:match.start()].count("\n") + 1
                if (path.name, line) in REPAIRED_IN_0344:
                    continue
                offenders.append(f"{path.name}:{line}: {match.group(0)}")
        self.assertEqual(offenders, [], "\n".join(
            ["unparenthesised '||' before '->>' — binds as (lit || json). "
             "Parenthesise the arrow: `lit || (row->>'key')`."]
            + offenders))

    def test_the_baseline_still_describes_something_real(self):
        # A stale exemption is worse than none: it silently forgives a line
        # that has moved, and the moved line is then unguarded. If D2 is ever
        # renumbered or reformatted, this fails and the baseline is updated
        # deliberately rather than rotting.
        for name, line in REPAIRED_IN_0344:
            text = _sql(MIGRATIONS / name)
            joined = re.sub(r"\|\|\s*\n\s*", "|| ", text)
            found = {
                joined[:m.start()].count("\n") + 1
                for m in UNPARENTHESISED.finditer(joined)
            }
            self.assertIn(line, found, f"{name}:{line} no longer matches")

    def test_the_guard_actually_catches_the_original_line(self):
        # A guard nobody has seen fail is a guard nobody knows works.
        original = (
            "    PERFORM pg_advisory_xact_lock(hashtextextended(\n"
            "        'feedback-v3-service-candidate-set:' ||\n"
            "        p_bundle->>'idempotency_key', 0\n"
            "    ));"
        )
        joined = re.sub(r"\|\|\s*\n\s*", "|| ", original)
        self.assertTrue(UNPARENTHESISED.search(joined))

    def test_the_repaired_form_passes_the_guard(self):
        repaired = (
            "        'feedback-v3-service-candidate-set:' ||\n"
            "        (p_bundle->>'idempotency_key'), 0"
        )
        joined = re.sub(r"\|\|\s*\n\s*", "|| ", repaired)
        self.assertIsNone(UNPARENTHESISED.search(joined))

    def test_a_plain_text_parameter_is_not_flagged(self):
        # The sibling locks concatenate a TEXT parameter and are correct;
        # a guard that failed them would be deleted within a week.
        joined = "'feedback-v3-service-membership:' || p_idempotency_key, 0"
        self.assertIsNone(UNPARENTHESISED.search(joined))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
