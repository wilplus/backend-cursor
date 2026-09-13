"""Regression evidence for the production-shaped fixture helpers.

These prove the new helpers against a REAL released-migration schema, built by
`tests/integration/confident_moment_rehearsal.sh released`. That is the point of
them: the legacy helpers only work against narrow test-only table copies, and
that divergence previously hid a defect that made a migration unable to apply to
production.

Nothing here touches the legacy helpers or any suite that still uses them.
"""
from __future__ import annotations

import os
from uuid import uuid4

import psycopg2
import pytest

from tests.confident_moment_production_fixtures import (
    CONSENT_POLICY_VERSION,
    _copy_hash,
    accept_authorization,
    create_product_rows,
    grant_consent,
    one,
    query,
    register_policy,
    register_speaker,
)

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="disposable rehearsal only")


@pytest.fixture
def db():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    connection = psycopg2.connect(**parsed)
    connection.autocommit = True
    try:
        yield connection
    finally:
        connection.close()


def _product_rows(db):
    return create_product_rows(db)


def test_released_rehearsal_applies_recording_attempt_take_boundary(db):
    """The released lane contains 0297's functions and exact identity checks."""
    assert one(
        db,
        "SELECT to_regprocedure('public.register_recording_attempt_v1(uuid,uuid,"
        "uuid,text,uuid,text,text,text,text)') IS NOT NULL AS present",
    )["present"] is True
    constraints = {
        row["conname"]: row["definition"]
        for row in query(
            db,
            "SELECT conname,pg_get_constraintdef(oid) AS definition "
            "FROM pg_constraint WHERE conrelid='public.takes'::regclass",
        )
    }
    assert "take_identity_matches_attempt" in constraints
    assert "id = recording_attempt_id" in constraints[
        "take_identity_matches_attempt"
    ]


def test_product_rows_follow_exact_v2_attempt_take_lineage(db):
    ids = _product_rows(db)
    row = one(
        db,
        "SELECT s.id AS session_id,s.project_id AS session_project_id,"
        "a.id AS attempt_id,a.upload_idempotency_key,a.recording_kind,a.status,"
        "a.attempt_count,a.provenance_eligible,a.created_at,a.terminal_at,"
        "t.id AS take_id,t.recording_attempt_id,t.take_index,t.completion_hash,"
        "t.completed_at FROM v2_sessions s "
        "JOIN recording_attempts a ON a.id=s.id "
        "JOIN takes t ON t.recording_attempt_id=a.id WHERE s.id=%s",
        (ids["attempt"],),
    )
    assert row["session_id"] == row["attempt_id"] == row["take_id"]
    assert row["take_id"] == row["recording_attempt_id"]
    assert row["session_project_id"] == ids["project"]
    for field in (
        "upload_idempotency_key", "recording_kind", "status", "attempt_count",
        "provenance_eligible", "created_at", "terminal_at", "take_index",
        "completion_hash", "completed_at",
    ):
        assert row[field] is not None, field


def test_policy_registration_uses_the_canonical_phase1_writers(db):
    """A phase-1 policy is registered and activated, not inserted raw."""
    policy = register_policy(db)
    row = one(
        db,
        "SELECT status,activated_at,product_legal_artifact_id,"
        "terms_copy,terms_copy_sha256 FROM processing_policy_versions "
        "WHERE version=%s",
        (policy["version"],),
    )
    assert row["status"] == "active"
    assert row["activated_at"] is not None
    # The canonical writer links the legal artifact; a raw insert never would.
    assert row["product_legal_artifact_id"] is not None
    # The RPC recomputes the copy hashes, so these must be the real digests.
    assert row["terms_copy_sha256"] == _copy_hash(row["terms_copy"])
    assert row["terms_copy_sha256"] == policy["terms"]


def test_phase1_policy_refuses_a_phase2_purpose(db):
    """The fixture cannot smuggle a phase-2 purpose into a phase-1 policy."""
    with pytest.raises(psycopg2.Error) as failure:
        register_policy(
            db,
            version=f"phase2-probe-{uuid4().hex[:8]}",
            purpose_ids=("coach_review", "personalized_exercise_recommendation"),
        )
    assert "PHASE2_PURPOSE_FORBIDDEN" in str(failure.value)


def test_authorization_receipt_and_snapshot_come_from_the_canonical_rpc(db):
    """Receipt and snapshot are written by the acceptance RPC, fully populated."""
    ids = _product_rows(db)
    policy = register_policy(db)
    accept_authorization(db, ids["owner"], policy)
    receipt = one(
        db,
        "SELECT id,policy_id,explicit_action,age_18_attested,accepted_at,"
        "evidence_sha256 FROM processing_authorization_receipts "
        "WHERE acquisition_principal_id=%s",
        (ids["owner"],),
    )
    assert receipt["explicit_action"] == "agree_and_continue"
    assert receipt["age_18_attested"] is True
    # Every NOT NULL the released table declares is populated by the RPC.
    assert receipt["accepted_at"] is not None
    assert receipt["evidence_sha256"] is not None
    # Acceptance writes the RECEIPT only. The per-operation snapshot is a
    # separate canonical writer, which is exactly the seam the legacy helpers
    # bypassed by inserting the snapshot row by hand.
    assert one(
        db,
        "SELECT count(*) n FROM processing_authorization_snapshots "
        "WHERE acquisition_principal_id=%s",
        (ids["owner"],),
    )["n"] == 0


def test_acceptance_is_refused_without_an_active_approved_policy(db):
    """Fail-closed: an unregistered policy version cannot authorize anything."""
    ids = _product_rows(db)
    policy = register_policy(db)
    with pytest.raises(psycopg2.Error) as failure:
        accept_authorization(
            db, ids["owner"], {**policy, "version": f"never-registered-{uuid4()}"}
        )
    assert "PROCESSING_POLICY_UNAPPROVED" in str(failure.value)


def test_speaker_identity_is_bound_through_its_canonical_writer(db):
    """ml_speakers/ml_speaker_principals are written by the RPC, not by hand."""
    ids = _product_rows(db)
    binding = register_speaker(db, ids["owner"])
    assert binding["acquisition_principal_id"] == ids["owner"]
    speaker = one(
        db,
        "SELECT s.identity_version,s.identity_hash,s.created_by "
        "FROM ml_speakers s JOIN ml_speaker_principals p ON p.speaker_id=s.id "
        "WHERE p.acquisition_principal_id=%s",
        (ids["owner"],),
    )
    # The released ml_speakers makes all of these NOT NULL; the legacy
    # `INSERT INTO ml_speakers VALUES (%s)` cannot satisfy them.
    assert speaker["identity_version"] == "speaker-resolution-v1"
    assert speaker["identity_hash"] is not None
    assert speaker["created_by"] is not None
    assert one(
        db,
        "SELECT count(*) n FROM ml_speaker_split_assignments a "
        "JOIN ml_speaker_principals p ON p.speaker_id=a.speaker_id "
        "WHERE p.acquisition_principal_id=%s",
        (ids["owner"],),
    )["n"] == 1


def test_consent_grant_and_snapshot_use_the_canonical_writers(db):
    """The per-take consent snapshot the confidence frame requires exists."""
    ids = _product_rows(db)
    register_speaker(db, ids["owner"])
    snapshot = grant_consent(db, ids["owner"], ids["attempt"], ids["take"])
    assert snapshot["consent_policy_version"] == CONSENT_POLICY_VERSION
    assert snapshot["grant_event_id"] is not None
    assert one(
        db,
        "SELECT count(*) n FROM ml_consent_snapshots "
        "WHERE acquisition_principal_id=%s AND recording_attempt_id=%s "
        "AND take_id=%s",
        (ids["owner"], ids["attempt"], ids["take"]),
    )["n"] == 1


def test_helpers_never_update_an_append_only_mlc2_table(db):
    """The whole point: this module writes final-form rows only.

    The legacy helpers insert blank rows and patch them afterwards, which the
    released MLC-2 append-only triggers reject outright.
    """
    import ast
    import inspect

    from tests import confident_moment_production_fixtures as module

    tree = ast.parse(inspect.getsource(module))
    statements = [
        node.value.upper().strip()
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and node.value.strip().upper().startswith(
            ("INSERT", "UPDATE", "DELETE", "SELECT")
        )
    ]
    assert statements, "no SQL literals found to inspect"
    offending = [s for s in statements if s.startswith(("UPDATE", "DELETE"))]
    assert not offending, f"fixtures must write final-form rows: {offending}"
