"""The retention report (founder 2026-10-05, Q3b and Q4; N45, N46, N50): the
list the cleaner shows before its first real run. Since migration 0423 it
reads the one definition of what is due (public.retention_report_v1), which
every run of the cleaner reads too (services/retention_cleaner.py; N48.4
Q16 A); 0426 took the founder's bug list off it and added rule 4.

Pins that the report can change nothing, that it counts by rule and never
by person, that the founder's periods are written once, that a claimed guest
is never counted, that no evidence table, no financial table and not the
founder's bug list is on its log list, and that rule 4 takes exactly the
financial records, five years after their financial year in Polish time.
tests/test_retention_cleaner_postgres.py runs it against a database.
"""
from __future__ import annotations

import pathlib
import re

from services.data_purge_registry import DEPENDENCIES

ROOT = pathlib.Path(__file__).resolve().parents[1]
SQL = (ROOT / "scripts" / "retention_report.sql").read_text()
CODE = "\n".join(line.split("--", 1)[0] for line in SQL.splitlines())
#: The clean-up's migrations: 0423 wrote the definitions, 0426 re-issued
#: four of them and added rule 4's. A later one wins, as in the database.
CLEANUP = ("old_data_goes_on_a_schedule.sql",
           "financial_records_go_after_five_years.sql")
MIGRATION_CODES = [
    "\n".join(line.split("--", 1)[0]
              for line in (ROOT / "migrations" / name).read_text().splitlines())
    for name in CLEANUP]
MIGRATION_CODE = "\n".join(MIGRATION_CODES)

#: Tables that must never be on a sweep list: evidence (append-only or the
#: registry's retain dispositions).
NEVER = {
    "processing_authorization_receipts", "processing_authorization_snapshots",
    "processing_recording_attempts", "processing_provider_operations",
    "phase1_processing_job_events", "data_purge_events",
    "ai_transparency_exposures", "phase1_authorization_admin_events",
    "owner_claim_events",
}
#: Kept five years after their financial year (v1.3), then rule 4's.
FINANCIAL = {"token_ledger", "llm_usage"}

#: Every definition the report reads, directly or through another.
DEFINITIONS = (
    "retention_report_v1", "retention_cutoffs_v1", "retention_column_present_v1",
    "retention_live_audio_v1", "retention_due_guests_v1",
    "retention_due_audio_v1", "retention_last_audio_accounts_v1",
    "retention_measurement_stores_v1", "retention_measurement_rows_sql_v1",
    "retention_store_present_v1", "retention_measurement_dirty_sql_v1",
    "retention_count_measurements_v1", "retention_due_measurements_v1",
    "retention_log_relations_v1", "retention_log_condition_v1",
    "retention_due_logs_v1", "retention_financial_cut_v1",
    "retention_financial_relations_v1", "retention_financial_condition_v1",
    "retention_due_financial_v1",
)


def function(name: str) -> tuple[str, str]:
    """(header, body) of one function's latest definition."""
    for code in reversed(MIGRATION_CODES):
        matches = re.findall(
            rf"CREATE OR REPLACE FUNCTION public\.{name}\((.*?)\n\$\$;",
            code, re.S)
        if matches:
            header, _, body = matches[-1].partition("AS $$")
            return header, body
    raise AssertionError(name)


def test_it_changes_nothing():
    for verb in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "DROP", "ALTER",
                 "CREATE", "GRANT", "CALL", "PERFORM"):
        assert not re.search(rf"\b{verb}\b", CODE, re.I), verb
    # The one function it calls is the definition every run reads ...
    assert re.findall(r"public\.(\w+)\(", CODE) == ["retention_report_v1"]
    # ... and every definition under it is declared STABLE or IMMUTABLE, so
    # the database refuses a change made through any of them.
    for name in DEFINITIONS:
        header, body = function(name)
        assert re.search(r"\b(STABLE|IMMUTABLE)\b", header), name
        for verb in ("INSERT", "UPDATE", "DELETE"):
            assert not re.search(rf"\b{verb}\b", body), (name, verb)


def test_it_is_not_a_migration():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text()
    assert "retention_report.sql" not in manifest


def test_the_founders_periods_are_written_once():
    _, cutoffs = function("retention_cutoffs_v1")
    for period in ("interval '30 days'", "interval '12 months'",
                   "interval '90 days'"):
        assert period in cutoffs
        assert MIGRATION_CODE.count(period) == 1, period
    _, financial = function("retention_financial_cut_v1")
    assert "interval '5 years'" in financial
    assert MIGRATION_CODE.count("interval '5 years'") == 1


def test_a_financial_year_is_the_calendar_year_in_polish_time():
    """v1.3: five years from the end of the financial year the record was
    made in. A row made in 2026 is due from 1 January 2032 in Warsaw."""
    _, cut = function("retention_financial_cut_v1")
    assert "date_trunc('year', p_as_of AT TIME ZONE 'Europe/Warsaw')" in cut
    assert cut.count("AT TIME ZONE 'Europe/Warsaw'") == 2
    _, condition = function("retention_financial_condition_v1")
    assert "t.created_at < $1" in condition


def test_a_claimed_guest_is_never_counted():
    _, guests = function("retention_due_guests_v1")
    for clause in ("p.user_id IS NULL", "p.guest_secret_hash IS NOT NULL",
                   "p.claimed_at IS NULL", "owner_claim_events"):
        assert clause in guests
    _, live = function("retention_live_audio_v1")
    assert "COALESCE(op.claimed_by_owner_principal_id, op.id)" in live


def test_last_use_is_the_later_of_making_and_any_project_change():
    _, due = function("retention_due_audio_v1")
    assert "a.created_at < c.audio_cut" in due
    assert "pr.owner_principal_id = a.owner_principal_id" in due
    assert "pr.updated_at >= c.audio_cut" in due


def test_it_counts_by_rule_never_by_person():
    header, body = function("retention_report_v1")
    assert "RETURNS TABLE (rule integer, would_delete text, how_many bigint)" in header
    assert re.search(r"SELECT rule, would_delete, how_many\s+FROM", CODE)
    assert "count(*)" in body
    assert "email" not in body and "user_id" not in body


def _log_tables() -> set[str]:
    _, body = function("retention_log_relations_v1")
    return set(re.findall(r"\('([a-z0-9_]+)', ARRAY", body))


def _financial_tables() -> set[str]:
    _, body = function("retention_financial_relations_v1")
    return set(re.findall(r"\('([a-z0-9_]+)', '[a-z0-9_]+'\)", body))


def test_no_evidence_or_financial_table_or_the_bug_list_is_a_log():
    swept = _log_tables()
    assert swept == {"processing_jobs", "life_reminder_log",
                     "admin_annotations_log", "mlc3_service_backpressure_events"}
    assert not swept & (NEVER | FINANCIAL)
    assert "dev_bugs" not in swept   # the founder's bug list (N50 C4 B)
    retained = {d.relation for d in DEPENDENCIES if d.disposition == "retain"}
    assert not swept & retained


def test_rule_4_takes_exactly_the_financial_records_and_no_evidence():
    # v1.3's financial records. v1.5's paid arc (N50 P2 A) is under the same
    # rule but not in Rule 4: P7 named the ledger and the LLM usage only, and
    # v1.5 §4 puts the arc to the founder.
    assert _financial_tables() == FINANCIAL == {
        d.relation for d in DEPENDENCIES
        if d.retention_category == "financial_evidence" and d.schedule is None}
    assert not _financial_tables() & NEVER
    _, report = function("retention_report_v1")
    assert "SELECT 4, 'financial records whose five years have ended: '" in report


def test_the_founders_definition_of_last_use_is_written_down():
    assert "NOTHING RECORDS \"LAST USE\"" in SQL
    assert "decisions log N46" in SQL
    assert "Until the founder confirms" not in SQL
