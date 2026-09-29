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

# The coaching bundle (add_confident_moment_coaching_bundle_v1.sql) revoked
# feedback_revisions from service_role entirely, SELECT included. 0389 never
# widens, so that table stays unreadable; every other table keeps SELECT.
LOCKED_ENTIRELY = ("feedback_revisions",)
READ_KEPT = tuple(t for t in TABLES if t not in LOCKED_ENTIRELY)

# The one writer that is not SECURITY DEFINER: a trigger on projects that
# only fires inside claim_guest_owner (a definer); see 0389's header.
KNOWN_NON_DEFINER_WRITERS = {
    ("transfer_learning_surfaces_on_owner_claim", "projects"),
}

WRITE_PATTERN = (
    r"(insert\s+into|update|delete\s+from)\s+(public\.)?("
    + "|".join(TABLES)
    + r")\M"
)


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


class TestTheLaneCarriesTheTables:
    def test_every_granted_table_exists_here(self, present):
        """A missing table would make a refusal below vacuous."""
        assert set(TABLES) - present == set()


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

    @pytest.mark.parametrize("table", TABLES)
    def test_insert_is_refused(self, db, table):
        column = _plain_column(db, table)
        with _ServiceRole(db) as cur:
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute(
                    f"INSERT INTO public.{table} ({column}) "
                    f"SELECT {column} FROM public.{table} WHERE false"
                )

    @pytest.mark.parametrize("table", TABLES)
    def test_update_is_refused(self, db, table):
        column = _plain_column(db, table)
        with _ServiceRole(db) as cur:
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute(
                    f"UPDATE public.{table} SET {column} = {column} "
                    "WHERE false"
                )

    @pytest.mark.parametrize("table", TABLES)
    def test_delete_is_refused(self, db, table):
        with _ServiceRole(db) as cur:
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute(f"DELETE FROM public.{table} WHERE false")

    @pytest.mark.parametrize("table", TABLES)
    def test_truncate_is_refused(self, db, table):
        """Privilege is checked before anything else TRUNCATE looks at, so
        the refusal is the privilege error, not a foreign-key one."""
        with _ServiceRole(db) as cur:
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute(f"TRUNCATE public.{table}")


class TestServiceRoleStillReads:
    @pytest.mark.parametrize("table", READ_KEPT)
    def test_select_is_kept(self, db, table):
        """The Ideal Text repository and the purge read these directly."""
        with _ServiceRole(db) as cur:
            cur.execute(f"SELECT count(*) FROM public.{table}")
            assert cur.fetchone()[0] >= 0

    @pytest.mark.parametrize("table", LOCKED_ENTIRELY)
    def test_a_table_locked_before_stays_locked(self, db, table):
        """0389 never widens: the bundle's full revoke survives it."""
        with _ServiceRole(db) as cur:
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute(f"SELECT count(*) FROM public.{table}")

    def test_the_grant_is_exactly_select(self, db, present):
        with db.cursor() as cur:
            cur.execute(
                "SELECT table_name, string_agg(privilege_type, ',' "
                "ORDER BY privilege_type) "
                "FROM information_schema.role_table_grants "
                "WHERE table_schema = 'public' AND grantee = 'service_role' "
                "AND table_name = ANY(%s) GROUP BY table_name",
                (list(present),),
            )
            grants = dict(cur.fetchall())
        assert grants == {t: "SELECT" for t in present if t in READ_KEPT}


class TestWhyTheRevokeIsSafe:
    def test_every_writer_is_a_definer_except_the_owner_claim_trigger(self, db):
        """A plain function or trigger that wrote one of these tables would
        run with the caller's privileges and start failing under 0389. The
        catalog shows exactly one, and it is the trigger 0389's header
        explains."""
        with db.cursor() as cur:
            cur.execute(
                "SELECT p.proname, COALESCE(t.tgrelid::regclass::text, '') "
                "FROM pg_proc p JOIN pg_namespace ns ON ns.oid = p.pronamespace "
                "LEFT JOIN pg_trigger t ON t.tgfoid = p.oid AND NOT t.tgisinternal "
                "WHERE ns.nspname = 'public' AND NOT p.prosecdef "
                "AND p.prosrc ~* %s",
                (WRITE_PATTERN,),
            )
            non_definers = set(cur.fetchall())
        assert non_definers == KNOWN_NON_DEFINER_WRITERS

    def test_the_owner_claim_rpc_is_a_definer(self, db):
        """The trigger above only writes inside this function's transaction.
        Not every lane installs the claim RPC; where it is installed it must
        be a definer, or the trigger's writes would run as the caller."""
        with db.cursor() as cur:
            cur.execute(
                "SELECT p.prosecdef FROM pg_proc p "
                "JOIN pg_namespace ns ON ns.oid = p.pronamespace "
                "WHERE ns.nspname = 'public' AND p.proname = 'claim_guest_owner'"
            )
            rows = cur.fetchall()
        if not rows:
            pytest.skip("claim_guest_owner is not installed on this lane; "
                        "the definer check is a claim about production")
        assert all(row[0] for row in rows), rows

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
