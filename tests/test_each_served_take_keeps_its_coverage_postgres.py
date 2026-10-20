"""
STORY    As the founder, I want each served Take's feedback coverage and lane
         outcomes stored once, so that I can see where feedback found nothing
         worth saying.
OUTCOME
  O1  The row the serve path builds (`coverage_row`) fits the table, with an
      empty lane typed `no_defensible_candidate`.
  O2  One row per Take: a second serve inserts nothing.
  O3  A row cannot claim more Slides covered than formed a block.
  O4  RLS is on and the browser roles (anon, authenticated) hold nothing.
  O5  Applying the migration again keeps every row.
PROVES   O1 -> test_the_row_the_serve_path_builds_fits_and_types_the_empty_lane
         O2 -> test_a_second_serve_keeps_one_row
         O3 -> test_covered_cannot_exceed_formed
         O4 -> test_browser_roles_reach_nothing
         O5 -> test_reapplying_the_migration_keeps_the_rows
NOTE     The insert below is the SQL the production writer's PostgREST upsert
         (`record_take_feedback_coverage`, on_conflict + ignore_duplicates)
         becomes; the writer itself talks to Supabase, not to psycopg2.
WHY      0437, D-ML-5; contract 24c, 24d, 25.
"""
from __future__ import annotations

import json
import os
import pathlib
import uuid

import psycopg2
import psycopg2.extras
import pytest

MIGRATION = (pathlib.Path(__file__).resolve().parents[1] / "migrations"
             / "each_served_take_keeps_its_coverage.sql")
DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)


@pytest.fixture(scope="module")
def db():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    try:
        yield conn
    finally:
        conn.close()


def _frame(*, covered: bool) -> dict:
    blocks = [
        {"slide_index": 0, "selected_candidate_id": "c1",
         "selection_reason": "relative_best"},
        {"slide_index": 1, "selected_candidate_id": "c2" if covered else None,
         "selection_reason": "relative_best" if covered else "no_exact_lineage"},
    ]
    return {
        "policy_version": "take-feedback-policy-v3-serving-v1",
        "coverage": {
            "assessable_slides": 2,
            "covered_slides": 2 if covered else 1,
            "uncovered": [] if covered else [
                {"slide_index": 1, "block_count": 1,
                 "reasons": ["no_exact_lineage"]}],
            "ratio": 1.0 if covered else 0.5,
            "required_floor": 0.7,
            "meets_floor": covered,
        },
        "blocks": blocks,
        "verbal_lanes": {
            "enabled": True,
            "rewrite_clarity": {"outcome": "selected"},
            "great_formulation": {"outcome": "no_defensible_candidate"},
        },
    }


def _insert(cur, row: dict) -> bool:
    cur.execute(
        "INSERT INTO public.take_feedback_coverage (take_session_id, project_id, "
        "take_index, policy_version, slides_with_blocks, slides_covered, "
        "required_floor, floor_met, uncovered, lane_outcomes) "
        "VALUES (%(take_session_id)s, %(project_id)s, %(take_index)s, "
        "%(policy_version)s, %(slides_with_blocks)s, %(slides_covered)s, "
        "%(required_floor)s, %(floor_met)s, %(uncovered)s, %(lane_outcomes)s) "
        "ON CONFLICT (take_session_id) DO NOTHING RETURNING take_session_id",
        {**row, "uncovered": json.dumps(row["uncovered"]),
         "lane_outcomes": json.dumps(row["lane_outcomes"])})
    return cur.fetchone() is not None


def _row(covered: bool = False) -> dict:
    from services.mlc3_first_client_feedback import coverage_row
    take = {"id": str(uuid.uuid4()), "project_id": str(uuid.uuid4()),
            "take_index": 1}
    row = coverage_row(take, _frame(covered=covered))
    assert row is not None
    return row


def test_the_row_the_serve_path_builds_fits_and_types_the_empty_lane(db):
    row = _row(covered=False)
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        assert _insert(cur, row) is True
        cur.execute("SELECT * FROM public.take_feedback_coverage "
                    "WHERE take_session_id = %s", (row["take_session_id"],))
        stored = cur.fetchone()
    assert stored["policy_version"] == "take-feedback-policy-v3-serving-v1"
    assert stored["slides_with_blocks"] == 2
    assert stored["slides_covered"] == 1
    assert stored["floor_met"] is False
    assert stored["lane_outcomes"] == {
        "confident_voice": "selected",
        "rewrite_clarity": "selected",
        "great_formulation": "no_defensible_candidate",
    }
    assert stored["uncovered"] == [
        {"slide_index": 1, "reasons": ["no_exact_lineage"]}]


def _count(cur, take_id: str) -> int:
    cur.execute("SELECT count(*) AS n FROM public.take_feedback_coverage "
                "WHERE take_session_id = %s", (take_id,))
    return cur.fetchone()["n"]


def test_a_second_serve_keeps_one_row(db):
    row = _row(covered=False)
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        assert _insert(cur, row) is True
        assert _insert(cur, {**_row(covered=True),
                             "take_session_id": row["take_session_id"]}) is False
        assert _count(cur, row["take_session_id"]) == 1
        cur.execute("SELECT slides_covered FROM public.take_feedback_coverage "
                    "WHERE take_session_id = %s", (row["take_session_id"],))
        assert cur.fetchone()["slides_covered"] == 1


def test_covered_cannot_exceed_formed(db):
    row = {**_row(covered=True), "slides_with_blocks": 1, "slides_covered": 2}
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        with pytest.raises(psycopg2.errors.CheckViolation,
                           match="take_feedback_coverage_counts"):
            _insert(cur, row)
        assert _count(cur, row["take_session_id"]) == 0


def test_browser_roles_reach_nothing(db):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT relrowsecurity FROM pg_class "
                    "WHERE oid = 'public.take_feedback_coverage'::regclass")
        assert cur.fetchone()["relrowsecurity"] is True
        for role in ("anon", "authenticated"):
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                cur.execute(
                    "SELECT has_table_privilege(%s, "
                    "'public.take_feedback_coverage', %s) AS ok",
                    (role, privilege))
                assert cur.fetchone()["ok"] is False, (role, privilege)
        cur.execute("SELECT has_table_privilege('service_role', "
                    "'public.take_feedback_coverage', 'INSERT') AS ok")
        assert cur.fetchone()["ok"] is True


def test_reapplying_the_migration_keeps_the_rows(db):
    row = _row(covered=True)
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        assert _insert(cur, row) is True
        cur.execute(MIGRATION.read_text())
        assert _count(cur, row["take_session_id"]) == 1
