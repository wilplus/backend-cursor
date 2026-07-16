"""willab — pin VALID_KINDS to the DB CHECK migration (founder fix-pack
2026-07-16, BE-1).

The P0 this guards against: PR #193 grew VALID_KINDS (feedback, ideal_text)
without a migration widening `lounge_messages_kind_check`. Server-side
inserts bypass validate_lounge_batch, insert_lounge_messages swallows the
CHECK rejection, and publish-analysis reported 4 bubbles while the student's
Lounge got nothing.

This suite makes that class of drift a CI failure: adding a kind to
VALID_KINDS without shipping a new kind migration (and bumping
_AUTHORITATIVE_MIGRATION below) turns the build red.

Run: python3 -m unittest test_lounge_kind_migration
"""
from __future__ import annotations

import pathlib
import re
import unittest

from services.lounge_messages import VALID_KINDS

# The LATEST lounge-kind migration — the DB CHECK's source of truth. When a
# new kind lands, ship a new migration and point this at it.
_AUTHORITATIVE_MIGRATION = "migrations/add_feedback_ideal_lounge_kinds.sql"

_CHECK_RE = re.compile(
    r"CHECK\s*\(\s*kind\s+IN\s*\((?P<body>[^)]*)\)", re.IGNORECASE | re.DOTALL
)


def _migration_kinds() -> tuple:
    path = pathlib.Path(__file__).parent / _AUTHORITATIVE_MIGRATION
    sql = path.read_text(encoding="utf-8")
    m = _CHECK_RE.search(sql)
    if not m:
        return ()
    return tuple(re.findall(r"'([a-z_]+)'", m.group("body")))


class LoungeKindMigrationPinTests(unittest.TestCase):

    def test_parse_is_not_vacuous(self):
        # A regex that stops matching must fail loudly, not pass on () == ().
        kinds = _migration_kinds()
        self.assertGreater(len(kinds), 5,
                           f"couldn't parse {_AUTHORITATIVE_MIGRATION}")

    def test_valid_kinds_equals_the_db_check(self):
        self.assertEqual(
            set(VALID_KINDS), set(_migration_kinds()),
            "VALID_KINDS and the DB CHECK diverged. Ship a new "
            "lounge-kind migration mirroring services/lounge_messages.py "
            "and bump _AUTHORITATIVE_MIGRATION in this test.",
        )

    def test_delivery_bubble_kinds_present(self):
        # The exact two kinds whose absence caused the P0.
        kinds = _migration_kinds()
        self.assertIn("feedback", kinds)
        self.assertIn("ideal_text", kinds)


if __name__ == "__main__":
    unittest.main()
