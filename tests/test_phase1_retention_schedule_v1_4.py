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
import re

from scripts.migrate import destructive_statements
from services.data_purge_registry import DEPENDENCIES

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "scripts" / "phase1_retention_rules_v1_4.sql").read_text()
DOC = (ROOT / "legal" / "phase1-2026.1" /
       "20-retention-schedule-v1.4-product-records-and-job-evidence-DRAFT.md"
       ).read_text()
#: The document with every line break and run of spaces made one space, so a
#: phrase wrapped across lines still reads as itself.
FLAT = " ".join(DOC.split())


def test_it_is_not_a_migration():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text()
    assert "phase1_retention_rules_v1_4.sql" not in manifest
    assert not (ROOT / "migrations" / "phase1_retention_rules_v1_4.sql").exists()


def test_it_seeds_the_two_rules_active():
    rows = re.findall(
        r"\('([a-z0-9-]+)', '([a-z_]+)',\s*'([a-z0-9_]+)', v_artifact_id, (true|false)\)",
        SCRIPT)
    assert rows == [
        ("product-records-v1", "product_records",
         "deleted_with_account_or_project", "true"),
        ("job-evidence-v1", "job_evidence", "recorded_plus_12_months", "true"),
    ]


def test_it_refuses_placeholders():
    assert "RETENTION_SCHEDULE_V1_4_UNSIGNED" in SCRIPT
    assert "v_sha256 LIKE '[[%'" in SCRIPT
    assert "v_approved_at_text LIKE '[[%'" in SCRIPT
    # The day is the one the document records.
    assert "v_approved_at_text TEXT := '2026-10-05'" in SCRIPT
    assert "approved_at:         2026-10-05" in DOC


def test_it_carries_the_signed_hash_from_signed_artifacts():
    """Signed 2026-10-05 20:05:07 UTC: the script registers exactly the hash
    that SIGNED-ARTIFACTS.md records for 06 v1.4, never a placeholder."""
    table = (ROOT / "legal" / "phase1-2026.1" / "SIGNED-ARTIFACTS.md").read_text()
    current = table.split("## Current", 1)[1].split("\n## ", 1)[0]
    row = next(line for line in current.splitlines()
               if line.startswith("| 06 v1.4 |"))
    sha = re.search(r"`([0-9a-f]{64})`", row).group(1)
    assert f"v_sha256 TEXT := '{sha}';" in SCRIPT
    assert "'[[sha256 of the signed PDF" not in SCRIPT


def test_it_registers_version_1_4_and_never_edits_a_signed_one():
    assert "artifact_kind = 'retention_schedule' AND version = '1.4'" in SCRIPT
    assert "'retention_schedule', '1.4'" in SCRIPT
    assert "UPDATE public.processing_legal_artifacts" not in SCRIPT
    assert destructive_statements(SCRIPT) == []
    assert "ON CONFLICT (rule_code) DO NOTHING" in SCRIPT
    assert "bump to 1.5" in SCRIPT


def test_the_document_names_the_same_rules_and_reference():
    for needle in ("`product-records-v1`", "`product_records`",
                   "`deleted_with_account_or_project`", "`job-evidence-v1`",
                   "`job_evidence`", "`recorded_plus_12_months`",
                   "12 months from the day each was recorded",
                   "phase1-2026.1/legal/retention-schedule-v1.4.pdf",
                   "WILLAB-PHASE1-2026.1-RET-v1.4"):
        assert needle in DOC, needle
    assert "WILLAB-PHASE1-2026.1-RET-v1.4" in SCRIPT
    assert "phase1-2026.1/legal/retention-schedule-v1.4.pdf" in SCRIPT
    assert "supersedes 1.3 (signed 2026-10-05)" in DOC


def test_every_registry_code_it_names_exists():
    codes = {dependency.code for dependency in DEPENDENCIES}
    relations = {dependency.relation for dependency in DEPENDENCIES}
    named = set(re.findall(r"`([a-z0-9_]+)`", DOC))
    vocabulary = {"product_records", "job_evidence", "external_review",
                  "deleted_with_account_or_project", "recorded_plus_12_months",
                  "ruled_by", "delete", "retain", "data_retention_rules",
                  "rule_code", "evidence_category", "retention_until_rule",
                  "retention_schedule", "is_universal", "coach_drafts",
                  "coach_revisions", "token_ledger", "llm_usage",
                  "sha256", "object_key"}
    unknown = sorted(named - codes - relations - vocabulary)
    assert unknown == [], unknown


def test_the_proposals_are_not_adopted_by_the_signature():
    section = FLAT.split("## 5.", 1)[1].split("## 6.", 1)[0]
    assert "NOT adopted by this signature" in FLAT
    assert section.count("(for the founder)") == 6
    assert "(a proposal, for the founder)" in section
    signature = FLAT.split("## 7. Signature", 1)[1]
    assert "the proposals in §5 are not adopted by this signature" in signature


def test_it_says_the_purge_change_lands_with_0425():
    """0425 gives the service role DELETE on the three job-plumbing tables
    the purge deletes with the account; without it an erasure these rules
    let through would stop part-way, after the audio is gone. The script is
    run by hand, possibly before the purge change is deployed, so it says so
    rather than checking for it."""
    header = SCRIPT.split("DO $$", 1)[0]
    assert "migrations/the_purge_can_delete_job_plumbing.sql" in header
    for table in ("phase1_processing_outbox", "processing_job_carryovers",
                  "processing_orphan_objects"):
        assert table in header, table

