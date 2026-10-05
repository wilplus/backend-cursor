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
import re

from services.data_purge_registry import DEPENDENCIES

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "scripts" / "phase1_retention_rules_v1_3.sql").read_text()
DOC = (ROOT / "legal" / "phase1-2026.1" /
       "19-retention-schedule-v1.3-financial-records-DRAFT.md").read_text()


def test_it_is_not_a_migration():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text()
    assert "phase1_retention_rules_v1_3.sql" not in manifest
    assert not (ROOT / "migrations" / "phase1_retention_rules_v1_3.sql").exists()


def test_it_seeds_the_one_financial_rule_active():
    rows = re.findall(r"\('([a-z0-9-]+)', '([a-z_]+)',\s*'([a-z0-9_]+)', v_artifact_id, (true|false)\)",
                      SCRIPT)
    assert rows == [("financial-evidence-v1", "financial_evidence",
                     "financial_year_end_plus_5_years", "true")]


def test_the_category_is_the_one_the_purge_retains_under():
    retained = {d.retention_category for d in DEPENDENCIES
                if d.disposition == "retain" and d.retention_category}
    assert "financial_evidence" in retained
    relations = {d.relation for d in DEPENDENCIES
                 if d.retention_category == "financial_evidence"}
    assert relations == {"token_ledger", "llm_usage"}


def test_it_refuses_placeholders():
    assert "RETENTION_SCHEDULE_V1_3_UNSIGNED" in SCRIPT
    assert "v_sha256 LIKE '[[%'" in SCRIPT
    assert "v_approved_at_text LIKE '[[%'" in SCRIPT
    # Shipped unsigned: the hash placeholder is still in the file; the day
    # is the one the document records.
    assert "'[[sha256 of the signed PDF" in SCRIPT
    assert "v_approved_at_text TEXT := '2026-10-05'" in SCRIPT
    assert "approved_at:         2026-10-05" in DOC


def test_it_registers_version_1_3_and_never_edits_a_signed_one():
    assert "artifact_kind = 'retention_schedule' AND version = '1.3'" in SCRIPT
    assert "'retention_schedule', '1.3'" in SCRIPT
    assert "UPDATE public.processing_legal_artifacts" not in SCRIPT
    assert "ON CONFLICT (rule_code) DO NOTHING" in SCRIPT


def test_the_document_names_the_same_rule_and_reference():
    assert "`financial-evidence-v1`" in DOC
    assert "`financial_year_end_plus_5_years`" in DOC
    assert "5 years from the end of the financial year" in DOC
    assert "WILLAB-PHASE1-2026.1-RET-v1.3" in DOC
    assert "WILLAB-PHASE1-2026.1-RET-v1.3" in SCRIPT
    assert "phase1-2026.1/legal/retention-schedule-v1.3.pdf" in DOC
    assert "phase1-2026.1/legal/retention-schedule-v1.3.pdf" in SCRIPT
