"""The canonical learning-evidence tables refuse a direct write from the
service key (0389).

R-1 (audit 2026-09-22, major). 0296 and 0299 ended with `GRANT ALL ON TABLE
... TO service_role` on twenty-eight tables. service_role bypasses row level
security, so any process holding the service key could INSERT into
candidate_sets, evidence_spans or dataset_release_items directly and skip the
SECURITY DEFINER RPCs that carry the contract's checks; the append-only
triggers refuse UPDATE and DELETE, never an INSERT.

These cases execute the boundary on the released lane: as service_role, each
of the four write privileges is refused on every one of those tables, SELECT
still works where it worked before (and stays refused on the one table the
coaching bundle locked entirely), and the catalog shows why the revoke is
safe — every function that writes one of the tables is a definer, except the
one owner-claim trigger this test pins by name.

Every write attempt below matches zero rows (`WHERE false`, or a TRUNCATE in
a transaction that is always rolled back), so a database that still grants
the privilege — origin/main before 0389 — lets it through and the assertion
fails; nothing is ever written.

The target must be a disposable local database whose name starts with
``willab_confident_moment_``.
"""
from __future__ import annotations

import os

import psycopg2
import psycopg2.errors
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

# The two grant blocks 0389 revokes, verbatim.
GRANTED_BY_0296 = (
    "transcript_versions", "slides", "paragraphs", "evidence_spans",
    "acoustic_feature_snapshots", "candidate_sets", "feedback_candidates",
    "feedback_exposures", "machine_predictions", "generation_runs",
    "evidence_review_assignments", "confidence_self_reports",
    "confidence_coach_labels", "confidence_peer_labels",
    "praise_helpfulness", "correction_decisions", "paragraph_decisions",
    "feedback_revisions", "voice_album_admissions", "accepted_flagships",
    "root_phrases", "processing_stage_runs", "dataset_releases",
    "dataset_split_assignments", "dataset_release_items",
    "dataset_exclusions",
)
GRANTED_BY_0299 = (
    "learning_surface_presentations", "learning_surface_exposure_receipts",
)
TABLES = GRANTED_BY_0296 + GRANTED_BY_0299


@pytest.fixture(scope="module")
def db():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    if not parsed.get("host", "").startswith(
        ("/tmp/willab-", "/private/tmp/willab-")
    ):
        raise RuntimeError("Refusing a database outside the rehearsal socket")
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(scope="module")
def present(db):
    """The listed tables this lane actually carries; a table the lane lacks
    is reported by name, never silently passed."""
    with db.cursor() as cur:
        cur.execute(
            "SELECT n FROM unnest(%s::text[]) n "
            "WHERE to_regclass('public.' || n) IS NOT NULL",
            (list(TABLES),),
        )
        return {row[0] for row in cur.fetchall()}


def _plain_column(db, table):
    """One column a zero-row INSERT ... SELECT may name (not identity, not
    generated), read from pg_attribute as the connection's own role, so the
    statement below is refused on privilege and nothing else."""
    with db.cursor() as cur:
        cur.execute(
            "SELECT a.attname FROM pg_attribute a "
            "WHERE a.attrelid = ('public.' || %s)::regclass AND a.attnum > 0 "
            "AND NOT a.attisdropped AND a.attidentity = '' "
            "AND a.attgenerated = '' ORDER BY a.attnum LIMIT 1",
            (table,),
        )
        row = cur.fetchone()
    assert row, f"{table} has no plain column"
    return row[0]


class _ServiceRole:
    """A transaction as service_role that is always rolled back."""

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        self.conn.autocommit = False
        self.cur = self.conn.cursor()
        self.cur.execute("SET ROLE service_role")
        return self.cur

    def __exit__(self, *exc):
        self.conn.rollback()
        self.cur.execute("RESET ROLE")
        self.conn.commit()
        self.cur.close()
        self.conn.autocommit = True
        return False


class TestServiceRoleCannotWrite:
    def test_service_role_cannot_insert_into_canonical_tables(self, db, present):
        """The finding's named regression test (job1_review.md, R-1): one
        pass over every granted table the lane carries. The parametrized
        cases below give the per-table diagnosis."""
        refused = []
        for table in sorted(present):
            column = _plain_column(db, table)
            with _ServiceRole(db) as cur:
                try:
                    cur.execute(
                        f"INSERT INTO public.{table} ({column}) "
                        f"SELECT {column} FROM public.{table} WHERE false"
                    )
                except psycopg2.errors.InsufficientPrivilege:
                    refused.append(table)
        assert sorted(refused) == sorted(present)


class TestWhyTheRevokeIsSafe:


    @pytest.mark.parametrize("rpc", [
        "record_feedback_v3_service_candidate_set_v1",
        "record_feedback_v3_service_response_v1",
    ])
    def test_the_served_v3_writers_stay_executable(self, db, rpc):
        """The write path that remains: the two RPCs every V3 Take goes
        through are definers and service_role may still call them. (Not
        every writer is meant to be callable — the coaching bundle revoked
        record_feedback_language_coach_revision_v1 on purpose — so this
        names the live pair rather than sweeping.)"""
        with db.cursor() as cur:
            cur.execute(
                "SELECT p.prosecdef, "
                "has_function_privilege('service_role', p.oid, 'EXECUTE') "
                "FROM pg_proc p JOIN pg_namespace ns ON ns.oid = p.pronamespace "
                "WHERE ns.nspname = 'public' AND p.proname = %s",
                (rpc,),
            )
            rows = cur.fetchall()
        assert rows, f"{rpc} is not installed on this lane"
        assert all(secdef and executable for secdef, executable in rows), rows
