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
    _hash,
    accept_authorization,
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
    """Product rows with NAMED columns, in final form, every NOT NULL supplied."""
    ids = {name: str(uuid4()) for name in ("owner", "project", "attempt", "take")}
    query(
        db,
        "INSERT INTO owner_principals(id,guest_secret_hash) VALUES(%s,%s)",
        (ids["owner"], _hash(f"owner-{ids['owner']}")),
    )
    query(
        db,
        "INSERT INTO projects(id,owner_principal_id,display_name) VALUES(%s,%s,%s)",
        (ids["project"], ids["owner"], "Production fixture project"),
    )
    query(
        db,
        "INSERT INTO recording_attempts(id,owner_principal_id,project_id) "
        "VALUES(%s,%s,%s)",
        (ids["attempt"], ids["owner"], ids["project"]),
    )
    query(
        db,
        "INSERT INTO takes(id,owner_principal_id,project_id,recording_attempt_id) "
        "VALUES(%s,%s,%s,%s)",
        (ids["take"], ids["owner"], ids["project"], ids["attempt"]),
    )
    return ids


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
