"""Retention schedule v1.3: financial records are kept five years (founder
2026-10-05, "It should be kept for 5 years"; decisions log N43).

Pins:
  * the hand-run script seeds exactly one rule, ``financial-evidence-v1``,
    on the category the purge registry's retain dependencies carry, so the
    erasure stops falling over on RETENTION_RULE_UNRESOLVED once it runs;
  * it is not a migration, and it refuses to run while the signed PDF's hash
    or signing day is still a placeholder;
  * the schedule it registers names the same rule, period and reference.
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_it_is_not_a_migration():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text()
    assert "phase1_retention_rules_v1_3.sql" not in manifest
    assert not (ROOT / "migrations" / "phase1_retention_rules_v1_3.sql").exists()
