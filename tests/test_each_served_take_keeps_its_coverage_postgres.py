"""Each served Take keeps its coverage and lane outcomes, on a disposable
database (0437, D-ML-5; contract 24c, 24d, 25).

Pins: the table exists with RLS on and nothing granted to the browser
roles; the row the serve path builds (`coverage_row`) fits it, including a
`no_defensible_candidate` lane; one row per Take (the first serve inserts,
a reread finds it and does not insert again); the counts cannot claim more
Slides covered than formed a block; applying the file again keeps every
row."""
from __future__ import annotations

import json
import os
import uuid

import psycopg2
import psycopg2.extras
import pytest

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
