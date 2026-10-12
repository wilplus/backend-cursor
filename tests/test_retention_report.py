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

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_it_is_not_a_migration():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text()
    assert "retention_report.sql" not in manifest
