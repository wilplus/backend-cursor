"""The legacy commerce check (founder 2026-10-05, N48.3 Q13 A): the numbers
the founder reads before the subscription, credit-pack and arc-checkout paths
are removed. Pins that it changes nothing, is not a migration, counts and
never lists people, and asks all three questions.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SQL = (ROOT / "scripts" / "legacy_commerce_check.sql").read_text()
CODE = "\n".join(line.split("--", 1)[0] for line in SQL.splitlines())


def test_it_changes_nothing():
    for verb in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "DROP", "ALTER",
                 "CREATE", "GRANT", "CALL", "PERFORM", "DO"):
        assert not re.search(rf"\b{verb}\b", CODE, re.I), verb


def test_it_is_not_a_migration():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text()
    assert "legacy_commerce_check.sql" not in manifest


def test_it_counts_and_never_lists_a_person():
    assert "user_id" not in CODE
    assert "email" not in CODE.lower()
    selects = re.findall(r"\bSELECT\b", CODE)
    counts = re.findall(r"count\(\*\)", CODE)
    # One outer SELECT per row, each with exactly one count(*) under it.
    assert len(counts) == (len(selects) - 1) // 2


def test_the_three_questions():
    # Subscriptions: the statuses the code treated as live.
    assert "stripe_subscription_status" in CODE
    for status in ("'active'", "'trialing'", "'past_due'"):
        assert status in CODE
    assert "action = 'tier_change'" in CODE
    # Credit packs in the last 90 days.
    assert "stripe_checkout_credit_grants" in CODE
    assert "interval '90 days'" in CODE
    # Arc checkout purchases, not invite-code passes.
    assert "arc_purchases" in CODE
    assert "kind = 'paid' AND source = 'stripe'" in CODE
