"""Disposable PostgreSQL tests for the disabled N1 pattern foundation."""
from uuid import uuid4

import pytest
from psycopg2.extras import Json

from services.data_purge_registry import dependency_by_code
from tests.test_mlc3_dark_assignments_postgres import (
    DSN,
    assign,
    connect,
    make_context,
    one,
    query,
    rpc,
)

pytestmark = pytest.mark.skipif(not DSN, reason="disposable N1 rehearsal only")


@pytest.fixture
def db():
    connection = connect()
    yield connection
    connection.close()


@pytest.fixture
def ctx(db):
    return make_context(db)


def source_pattern(db, ctx, pattern="confident"):
    prediction = one(
        db,
        "SELECT prediction_id FROM learning_profile_observations WHERE id=%s",
        (ctx["observation"],),
    )["prediction_id"]
    query(
        db,
        "UPDATE ml_machine_predictions SET raw_output=raw_output||%s WHERE id=%s",
        (Json({"source_pattern": pattern}), prediction),
    )
    return rpc(
        db,
        "register_exercise_n1_source_pattern_v1",
        ctx["lineage"],
        ctx["observation"],
        ctx["auth"],
        str(uuid4()),
    )


def profile(
    db,
    exercise_version_id,
    patterns,
    *,
    supported_min=1,
    supported_max=2,
    preferred_min=1.1,
    preferred_max=1.5,
    key=None,
):
    return rpc(
        db,
        "register_exercise_n1_version_profile_v1",
        exercise_version_id,
        patterns,
        supported_min,
        supported_max,
        preferred_min,
        preferred_max,
        50,
        "synthetic-publisher-approval",
        "9" * 64,
        key or str(uuid4()),
    )


def test_deletion_inventory_attributes_every_n1_row_to_acquisition_principal(db):
    context = make_context(db)
    source = source_pattern(db, context)
    for version in context["versions"]:
        profile(db, version["id"], ["confident"])
    assignment = assign(db, context)
    snapshot = rpc(
        db,
        "freeze_exercise_n1_pattern_snapshot_v1",
        assignment["id"],
        source["id"],
        str(uuid4()),
    )

    expected = {
        "exercise_n1_source_patterns": 1,
        "exercise_n1_pattern_snapshots": 1,
        "exercise_n1_pattern_candidates": snapshot["candidate_count"],
    }
    for code, count in expected.items():
        dependency = dependency_by_code(code)
        assert dependency is not None
        assert dependency.selector_column == "acquisition_principal_id"
        rows = query(
            db,
            f"SELECT acquisition_principal_id FROM public.{dependency.relation} "
            "WHERE acquisition_principal_id=%s",
            (context["owner"],),
        )
        assert len(rows) == count
        assert all(row["acquisition_principal_id"] == context["owner"] for row in rows)
