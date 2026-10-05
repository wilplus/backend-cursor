"""The retention report (founder 2026-10-05, Q3b and Q4; N45): the list the
cleaner shows before its first real run. Pins that it can delete nothing,
that it counts by rule and never by person, that it uses the founder's
periods, and that no evidence or financial table is ever on its log list.
"""
from __future__ import annotations

import pathlib
import re

from services.data_purge_registry import DEPENDENCIES

ROOT = pathlib.Path(__file__).resolve().parents[1]
SQL = (ROOT / "scripts" / "retention_report.sql").read_text()
CODE = "\n".join(line.split("--", 1)[0] for line in SQL.splitlines())

#: Tables that must never be on a sweep list: evidence (append-only or the
#: registry's retain dispositions) and the financial records kept five years.
NEVER = {
    "processing_authorization_receipts", "processing_authorization_snapshots",
    "processing_recording_attempts", "processing_provider_operations",
    "phase1_processing_job_events", "data_purge_events",
    "ai_transparency_exposures", "phase1_authorization_admin_events",
    "owner_claim_events", "token_ledger", "llm_usage",
}


def test_it_changes_nothing():
    for verb in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "DROP", "ALTER",
                 "CREATE", "GRANT", "CALL", "PERFORM"):
        assert not re.search(rf"\b{verb}\b", CODE, re.I), verb
    assert "_v1(" not in CODE  # no RPC either


def test_it_is_not_a_migration():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text()
    assert "retention_report.sql" not in manifest


def test_the_founders_periods():
    assert "interval '30 days'" in CODE
    assert "interval '12 months'" in CODE
    assert "interval '90 days'" in CODE


def test_a_claimed_guest_is_never_counted():
    assert "p.claimed_at IS NULL" in CODE
    assert "owner_claim_events" in CODE
    assert "COALESCE(op.claimed_by_owner_principal_id, op.id)" in CODE


def test_it_counts_by_rule_never_by_person():
    select_lists = re.findall(r"^SELECT (\d), '([^']+)'", CODE, re.M)
    assert select_lists and all(rule in "123" for rule, _ in select_lists)
    assert "count(*)" in CODE
    assert "user_id," not in CODE and "email" not in CODE


def test_no_evidence_or_financial_table_is_swept():
    swept = set(re.findall(r"older than 90 days: ([a-z0-9_]+)", CODE))
    assert swept == {"processing_jobs", "dev_bugs", "life_reminder_log",
                     "admin_annotations_log", "mlc3_service_backpressure_events"}
    assert not swept & NEVER
    retained = {d.relation for d in DEPENDENCIES if d.disposition == "retain"}
    assert not swept & retained


def test_the_founders_definition_of_last_use_is_written_down():
    assert "NOTHING RECORDS \"LAST USE\"" in SQL
    assert "decisions log N46" in SQL
    assert "Until the founder confirms" not in SQL
