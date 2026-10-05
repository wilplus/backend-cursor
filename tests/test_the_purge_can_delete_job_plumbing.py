"""0425: the purge can delete the job plumbing it lists (decided 2026-10-05
on W3-B1's finding; the three tables stay "delete with the account", and
retention schedule v1.4 is unchanged).

Pins:
  * the migration grants DELETE to the service role on exactly
    phase1_processing_outbox, processing_job_carryovers and
    processing_orphan_objects, and grants or revokes nothing else;
  * it removes no row, so the runner applies it on boot, and it is in the
    manifest once, as 0425, right after 0424;
  * those three are exactly the purge's direct deletes on tables 0310 left
    SELECT-only, once the v1.4 rules are active: the job row and its events
    get no grant, because v1.4 keeps them as job evidence;
  * the released rehearsal lane applies it twice, after 0424.

The behaviour is proved on PostgreSQL in
tests/test_product_records_purge_postgres.py (TestTheJobPlumbingGoesWithTheAccount).
"""
from __future__ import annotations

import pathlib
import re

from scripts.migrate import destructive_statements, strip_sql_comments
from services.data_purge_registry import DEPENDENCIES, before_its_rule

ROOT = pathlib.Path(__file__).resolve().parents[1]
FILENAME = "the_purge_can_delete_job_plumbing.sql"
SQL = (ROOT / "migrations" / FILENAME).read_text(encoding="utf-8")
BODY = strip_sql_comments(SQL)
MANIFEST = (ROOT / "migrations" / "manifest.txt").read_text(encoding="utf-8")
LANE = (ROOT / "tests" / "integration" /
        "confident_moment_rehearsal.sh").read_text(encoding="utf-8")

THE_THREE = {"phase1_processing_outbox", "processing_job_carryovers",
             "processing_orphan_objects"}


def _select_only_in_0310() -> set[str]:
    """The tables 0310's closing loop leaves the service role SELECT on and
    nothing else, read from the file rather than retyped."""
    boundary = strip_sql_comments(
        (ROOT / "migrations" / "add_phase1_processing_boundary.sql")
        .read_text(encoding="utf-8"))
    for block in re.findall(r"DO \$\$(.*?)\$\$;", boundary, re.S):
        if "GRANT SELECT ON public.%I TO service_role" in block:
            names = re.search(r"ARRAY\[(.*?)\]", block, re.S)
            assert names, "0310's grant loop lost its table list"
            return set(re.findall(r"'([a-z0-9_]+)'", names.group(1)))
    raise AssertionError("0310's SELECT-only grant loop was not found")


def test_it_grants_delete_on_exactly_the_three_tables():
    grants = re.findall(r"\b(?:GRANT|REVOKE)\b[^;]*;", BODY)
    assert sorted(" ".join(g.split()) for g in grants) == sorted(
        f"GRANT DELETE ON TABLE public.{table} TO service_role;"
        for table in THE_THREE)


def test_it_removes_no_row_and_runs_on_boot():
    assert destructive_statements(SQL) == []
    assert "BEGIN;" in BODY and "COMMIT;" in BODY
    for table in THE_THREE:
        assert f"table_name = '{table}'" in BODY, f"{table} grant is unguarded"


def test_it_is_0425_once_right_after_0424():
    lines = [line for line in MANIFEST.splitlines() if line.strip()]
    assert MANIFEST.count(FILENAME) == 1
    index = lines.index(f"0425\t{FILENAME}")
    assert lines[index - 1] == (
        "0424\ta_purge_deletes_the_product_records_it_froze.sql")


def test_the_three_are_the_purges_direct_deletes_on_select_only_tables():
    select_only = _select_only_in_0310()
    assert THE_THREE <= select_only
    ruled = {d.relation for d in DEPENDENCIES
             if d.disposition == "delete" and d.relation in select_only}
    assert ruled == THE_THREE, (
        "with the v1.4 rules active, every table the purge deletes directly "
        "among 0310's SELECT-only ones must be one 0425 opens")
    before = {before_its_rule(d).relation for d in DEPENDENCIES
              if before_its_rule(d).disposition == "delete"
              and d.relation in select_only}
    # Before v1.4 is active the registry also lists the job row for deletion
    # (it always did). 0425 does not open it: an erasure of someone with a
    # job stops for review at the job's events first, and v1.4 keeps both.
    assert before == THE_THREE | {"phase1_processing_jobs"}
    assert "phase1_processing_jobs" not in BODY
    assert "phase1_processing_job_events" not in BODY


def test_the_released_lane_applies_it_twice_after_0424():
    applied = re.findall(r"hard migrations/([a-z0-9_]+\.sql)", LANE)
    assert applied.count(FILENAME) == 2
    last_0424 = max(i for i, name in enumerate(applied)
                    if name == "a_purge_deletes_the_product_records_it_froze.sql")
    assert min(i for i, name in enumerate(applied) if name == FILENAME) > last_0424
