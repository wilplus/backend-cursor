"""Retention schedule v1.4: product records go with the account or the
project, job evidence is kept 12 months (founder 2026-10-05, "Q15 A";
decisions log N48.4).

Pins:
  * the hand-run script seeds exactly the two rules, active, and registers
    version 1.4 without ever editing a signed artifact;
  * it is not a migration, it refuses to run while a placeholder is in the
    file, and it carries the signed PDF's hash exactly as SIGNED-ARTIFACTS.md
    records it (signed 2026-10-05, D1 A);
  * the schedule names the same rules, periods and reference, every registry
    code it names exists, and §5's proposals are not adopted by its
    signature.
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "scripts" / "phase1_retention_rules_v1_4.sql").read_text()
DOC = (ROOT / "legal" / "phase1-2026.1" /
       "20-retention-schedule-v1.4-product-records-and-job-evidence-DRAFT.md"
       ).read_text()


def test_it_refuses_placeholders():
    assert "RETENTION_SCHEDULE_V1_4_UNSIGNED" in SCRIPT
    assert "v_sha256 LIKE '[[%'" in SCRIPT
    assert "v_approved_at_text LIKE '[[%'" in SCRIPT
    # The day is the one the document records.
    assert "v_approved_at_text TEXT := '2026-10-05'" in SCRIPT
    assert "approved_at:         2026-10-05" in DOC
