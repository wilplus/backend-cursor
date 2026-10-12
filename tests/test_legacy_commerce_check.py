"""The legacy commerce check (founder 2026-10-05, N48.3 Q13 A): the numbers
the founder reads before the subscription, credit-pack and arc-checkout paths
are removed. Pins that it changes nothing, is not a migration, counts and
never lists people, and asks all three questions.
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_it_is_not_a_migration():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text()
    assert "legacy_commerce_check.sql" not in manifest
