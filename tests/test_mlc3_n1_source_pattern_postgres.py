"""Disposable PostgreSQL tests for the disabled N1 pattern foundation."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

import psycopg2
import pytest
from psycopg2.extras import Json

from services.data_purge_registry import dependency_by_code
from tests.test_mlc3_dark_assignments_postgres import (
    DSN,
    add_exercise,
    assign,
    connect,
    insert_source_frame,
    make_context,
    one,
    query,
    rpc,
    wait_for_lock,
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


def test_closest_known_pattern_remains_rankable_and_is_frozen(db, ctx):
    source = source_pattern(db, ctx, "confident")
    version_ids = [str(version["id"]) for version in ctx["versions"]]
    supported = {
        version_ids[0]: ["near_confident"],
        version_ids[1]: ["low_confidence_rushing_dominant"],
        version_ids[2]: ["confident"],
    }
    for version, patterns in supported.items():
        profile(db, version, patterns)
    assignment = assign(db, ctx)
    snapshot = rpc(
        db,
        "freeze_exercise_n1_pattern_snapshot_v1",
        assignment["id"],
        source["id"],
        str(uuid4()),
    )
    candidates = query(
        db,
        "SELECT acquisition_principal_id,exercise_version_id,pattern_distance,"
        "supported_confidence_patterns "
        "FROM exercise_n1_pattern_candidates WHERE candidate_set_id=%s",
        (assignment["id"],),
    )
    distance = {
        str(row["exercise_version_id"]): row["pattern_distance"]
        for row in candidates
        if str(row["exercise_version_id"]) in version_ids
    }
    assert distance == {
        version_ids[0]: 1,
        version_ids[1]: 2,
        version_ids[2]: 0,
    }
    assert snapshot["candidate_count"] == len(candidates)
    assert not snapshot["serves_user"] and not snapshot["dataset_eligible"]
    assert all(row["acquisition_principal_id"] == ctx["owner"] for row in candidates)
    assert all(
        row["supported_confidence_patterns"] == supported[str(row["exercise_version_id"])]
        for row in candidates
        if str(row["exercise_version_id"]) in version_ids
    )


def test_composite_principal_lineage_rejects_cross_principal_rows(db):
    first = make_context(db)
    second = make_context(db)
    first_source = source_pattern(db, first)
    second_source = source_pattern(db, second)
    for version in first["versions"]:
        profile(db, version["id"], ["confident"])
    assignment = assign(db, first)

    snapshot_values = (
        assignment["id"],
        first["owner"],
        second_source["id"],
        Json([]),
        "1" * 64,
        "2" * 64,
        str(uuid4()),
    )
    with pytest.raises(psycopg2.Error):
        query(
            db,
            "INSERT INTO exercise_n1_pattern_snapshots("
            "candidate_set_id,acquisition_principal_id,source_pattern_result_id,"
            "ordinal_policy_version,inventory,candidate_count,inventory_sha256,"
            "snapshot_sha256,idempotency_key) VALUES ("
            "%s,%s,%s,'confidence-pattern-distance-v1',%s,0,%s,%s,%s)",
            snapshot_values,
        )

    with pytest.raises(psycopg2.Error):
        query(
            db,
            "INSERT INTO exercise_n1_pattern_snapshots("
            "candidate_set_id,acquisition_principal_id,source_pattern_result_id,"
            "ordinal_policy_version,inventory,candidate_count,inventory_sha256,"
            "snapshot_sha256,idempotency_key) VALUES ("
            "%s,%s,%s,'confidence-pattern-distance-v1',%s,0,%s,%s,%s)",
            (
                assignment["id"],
                second["owner"],
                second_source["id"],
                Json([]),
                "3" * 64,
                "4" * 64,
                str(uuid4()),
            ),
        )

    replay_key = str(uuid4())
    frozen = rpc(
        db,
        "freeze_exercise_n1_pattern_snapshot_v1",
        assignment["id"],
        first_source["id"],
        replay_key,
    )
    replay = rpc(
        db,
        "freeze_exercise_n1_pattern_snapshot_v1",
        assignment["id"],
        first_source["id"],
        replay_key,
    )
    assert replay["snapshot_sha256"] == frozen["snapshot_sha256"]
    assert replay["acquisition_principal_id"] == first["owner"]

    later_version = add_exercise(db, first)
    with pytest.raises(psycopg2.Error):
        query(
            db,
            "INSERT INTO exercise_n1_pattern_candidates("
            "candidate_set_id,acquisition_principal_id,exercise_version_id,"
            "compatibility_profile_id,source_pattern,supported_confidence_patterns,"
            "pattern_distance,compatibility_state,exclusion_reason,candidate_sha256) "
            "VALUES (%s,%s,%s,NULL,'confident','{}',NULL,'excluded',"
            "'profile_not_available_asof',%s)",
            (assignment["id"], second["owner"], later_version["id"], "5" * 64),
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


@pytest.mark.parametrize("pattern", [None, "rating_yes", "unknown"])
def test_missing_human_or_unknown_source_pattern_fails_closed(db, ctx, pattern):
    prediction = one(
        db,
        "SELECT prediction_id FROM learning_profile_observations WHERE id=%s",
        (ctx["observation"],),
    )["prediction_id"]
    if pattern is not None:
        query(
            db,
            "UPDATE ml_machine_predictions SET raw_output=raw_output||%s WHERE id=%s",
            (Json({"source_pattern": pattern}), prediction),
        )
    with pytest.raises(psycopg2.Error, match="N1_SOURCE_PATTERN_PROVENANCE_INVALID"):
        rpc(
            db,
            "register_exercise_n1_source_pattern_v1",
            ctx["lineage"],
            ctx["observation"],
            ctx["auth"],
            str(uuid4()),
        )


def test_foreign_clip_machine_result_and_direct_writes_fail(db, ctx):
    source = source_pattern(db, ctx)
    with pytest.raises(psycopg2.Error, match="N1_SOURCE_PATTERN_PROVENANCE_INVALID"):
        rpc(
            db,
            "register_exercise_n1_source_pattern_v1",
            ctx["second_lineage"],
            ctx["observation"],
            ctx["auth"],
            str(uuid4()),
        )
    query(db, "SET ROLE service_role")
    try:
        with pytest.raises(psycopg2.Error):
            query(
                db,
                "INSERT INTO exercise_n1_source_pattern_results(" 
                "acquisition_principal_id,audio_lineage_id,source_observation_id," 
                "machine_prediction_id,source_pattern,source_pattern_policy_version," 
                "ordinal_policy_version,prediction_output_sha256,result_sha256," 
                "completed_at,idempotency_key) SELECT acquisition_principal_id," 
                "audio_lineage_id,source_observation_id,machine_prediction_id," 
                "source_pattern,source_pattern_policy_version,ordinal_policy_version," 
                "prediction_output_sha256,result_sha256,completed_at,%s " 
                "FROM exercise_n1_source_pattern_results WHERE id=%s",
                (str(uuid4()), source["id"]),
            )
    finally:
        if db.get_transaction_status() != psycopg2.extensions.TRANSACTION_STATUS_INERROR:
            query(db, "RESET ROLE")


def test_profiles_missing_at_assignment_are_typed_excluded(db, ctx):
    source = source_pattern(db, ctx)
    assignment = assign(db, ctx)
    for version in ctx["versions"]:
        profile(db, version["id"], ["confident"])
    snapshot = rpc(
        db,
        "freeze_exercise_n1_pattern_snapshot_v1",
        assignment["id"],
        source["id"],
        str(uuid4()),
    )
    rows = query(
        db,
        "SELECT n.compatibility_state,n.exclusion_reason,c.eligibility AS base_eligibility "
        "FROM exercise_n1_pattern_candidates n JOIN exercise_candidates c "
        "ON c.candidate_set_id=n.candidate_set_id AND c.exercise_version_id=n.exercise_version_id "
        "WHERE n.candidate_set_id=%s",
        (snapshot["candidate_set_id"],),
    )
    assert rows
    assert all(row["compatibility_state"] == "excluded" for row in rows)
    assert all(
        row["exclusion_reason"] == (
            "profile_not_available_asof"
            if row["base_eligibility"] == "eligible"
            else "base_candidate_excluded"
        )
        for row in rows
    )


def test_idempotency_key_cannot_cross_candidate_sets(db):
    first = make_context(db, create_frame=False)
    cloned_block = "speech-block:" + uuid4().hex
    first["source_frame"]["blocks"].append(
        {
            **first["source_frame"]["blocks"][0],
            "block_id": cloned_block,
        }
    )
    insert_source_frame(db, first)
    first_source = source_pattern(db, first)
    for version in first["versions"]:
        profile(db, version["id"], ["confident"])
    first_assignment = assign(db, first)
    shared_key = str(uuid4())
    frozen = rpc(
        db,
        "freeze_exercise_n1_pattern_snapshot_v1",
        first_assignment["id"],
        first_source["id"],
        shared_key,
    )

    second_assignment = assign(
        db,
        first,
        block=cloned_block,
        key=str(uuid4()),
    )
    with pytest.raises(psycopg2.Error, match="N1_PATTERN_SNAPSHOT_REPLAY_CONFLICT"):
        rpc(
            db,
            "freeze_exercise_n1_pattern_snapshot_v1",
            second_assignment["id"],
            first_source["id"],
            shared_key,
        )

    persisted = one(
        db,
        "SELECT candidate_set_id,source_pattern_result_id,inventory_sha256,snapshot_sha256 "
        "FROM exercise_n1_pattern_snapshots WHERE idempotency_key=%s",
        (shared_key,),
    )
    assert persisted["candidate_set_id"] == frozen["candidate_set_id"]
    assert persisted["source_pattern_result_id"] == frozen["source_pattern_result_id"]
    assert persisted["inventory_sha256"] == frozen["inventory_sha256"]
    assert persisted["snapshot_sha256"] == frozen["snapshot_sha256"]


def test_concurrent_idempotency_key_cannot_cross_candidate_sets(db):
    context = make_context(db, create_frame=False)
    cloned_block = "speech-block:" + uuid4().hex
    context["source_frame"]["blocks"].append(
        {
            **context["source_frame"]["blocks"][0],
            "block_id": cloned_block,
        }
    )
    insert_source_frame(db, context)
    source = source_pattern(db, context)
    for version in context["versions"]:
        profile(db, version["id"], ["confident"])
    first_assignment = assign(db, context)
    second_assignment = assign(
        db,
        context,
        block=cloned_block,
        key=str(uuid4()),
    )
    shared_key = str(uuid4())
    blocker_key = 718_204_913
    query(
        db,
        "CREATE OR REPLACE FUNCTION public.n1_test_block_snapshot_insert_v1() "
        "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
        f"PERFORM pg_advisory_xact_lock({blocker_key}); RETURN NEW; END $$",
    )
    query(
        db,
        "CREATE TRIGGER n1_test_block_snapshot_insert "
        "BEFORE INSERT ON exercise_n1_pattern_snapshots FOR EACH ROW "
        "EXECUTE FUNCTION public.n1_test_block_snapshot_insert_v1()",
    )
    holder = connect()
    holder.autocommit = False
    query(holder, "SELECT pg_advisory_xact_lock(%s)", (blocker_key,))

    def freeze(candidate_set_id, application_name):
        connection = connect()
        try:
            query(connection, "SET application_name=%s", (application_name,))
            return rpc(
                connection,
                "freeze_exercise_n1_pattern_snapshot_v1",
                candidate_set_id,
                source["id"],
                shared_key,
            )
        finally:
            connection.close()

    first_application = "n1_first_" + uuid4().hex
    second_application = "n1_second_" + uuid4().hex
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            first = workers.submit(freeze, first_assignment["id"], first_application)
            wait_for_lock(db, first_application, "advisory")
            second = workers.submit(freeze, second_assignment["id"], second_application)
            wait_for_lock(db, second_application, "advisory")
            holder.commit()
            frozen = first.result(timeout=5)
            with pytest.raises(psycopg2.Error, match="N1_PATTERN_SNAPSHOT_REPLAY_CONFLICT"):
                second.result(timeout=5)
    finally:
        holder.rollback()
        holder.close()
        query(db, "DROP TRIGGER IF EXISTS n1_test_block_snapshot_insert ON exercise_n1_pattern_snapshots")
        query(db, "DROP FUNCTION IF EXISTS public.n1_test_block_snapshot_insert_v1()")

    persisted = one(
        db,
        "SELECT candidate_set_id,source_pattern_result_id FROM exercise_n1_pattern_snapshots "
        "WHERE idempotency_key=%s",
        (shared_key,),
    )
    assert persisted["candidate_set_id"] == frozen["candidate_set_id"]
    assert persisted["source_pattern_result_id"] == source["id"]


NONFINITE = [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")]
BOUND_FIELDS = [
    "supported_ratio_min",
    "supported_ratio_max",
    "preferred_ratio_min",
    "preferred_ratio_max",
]


@pytest.mark.parametrize("field", BOUND_FIELDS)
@pytest.mark.parametrize("value", NONFINITE, ids=["nan", "positive_infinity", "negative_infinity"])
def test_registration_rpc_rejects_every_nonfinite_ratio(db, ctx, field, value):
    bounds = {
        "supported_min": Decimal("1"),
        "supported_max": Decimal("2"),
        "preferred_min": Decimal("1.1"),
        "preferred_max": Decimal("1.5"),
    }
    argument = {
        "supported_ratio_min": "supported_min",
        "supported_ratio_max": "supported_max",
        "preferred_ratio_min": "preferred_min",
        "preferred_ratio_max": "preferred_max",
    }[field]
    bounds[argument] = value
    with pytest.raises(psycopg2.Error, match="N1_VERSION_PROFILE_INVALID"):
        profile(db, ctx["versions"][0]["id"], ["confident"], **bounds)


@pytest.mark.parametrize("field", BOUND_FIELDS)
@pytest.mark.parametrize("value", NONFINITE, ids=["nan", "positive_infinity", "negative_infinity"])
def test_table_constraints_reject_every_nonfinite_ratio(db, ctx, field, value):
    version = add_exercise(db, ctx)
    columns = {
        "supported_ratio_min": Decimal("1"),
        "supported_ratio_max": Decimal("2"),
        "preferred_ratio_min": Decimal("1.1"),
        "preferred_ratio_max": Decimal("1.5"),
    }
    columns[field] = value
    with pytest.raises(psycopg2.Error):
        query(
            db,
            "INSERT INTO exercise_n1_version_compatibility_profiles("
            "exercise_version_id,supported_confidence_patterns,supported_ratio_min,"
            "supported_ratio_max,preferred_ratio_min,preferred_ratio_max,editorial_priority,"
            "publisher_approval_ref,publisher_evidence_sha256,profile_sha256,idempotency_key) "
            "VALUES (%s,ARRAY['confident'],%s,%s,%s,%s,50,'synthetic-approval',%s,%s,%s)",
            (
                version["id"],
                columns["supported_ratio_min"],
                columns["supported_ratio_max"],
                columns["preferred_ratio_min"],
                columns["preferred_ratio_max"],
                "9" * 64,
                "8" * 64,
                str(uuid4()),
            ),
        )
