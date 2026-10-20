"""
STORY    As a speaker, I want my project deletion request handled safely in
         the database, so that only I can ask, a double tap is one request,
         and cancelling leaves a record (deletion).
OUTCOME
  O1  The owner's request is pending and due in 7 days.
  O2  Someone else's request for my project is refused (PROJECT_NOT_FOUND).
  O3  A double tap (same key) returns the same request; the same key can
      never name a different project.
  O4  At most one open request per project: a second key returns the open one.
  O5  Cancelling works while pending and keeps the row as `cancelled`; a
      confirmed request cannot be cancelled.
  O6  Browser roles can neither call the functions nor read the table.
  O7  With arc_id a UUID, as in production, my request is still pending and
      my project's erasure graph still holds the Take found by its arc.
PROVES   O1 -> test_owner_request_is_pending_and_due_in_seven_days
         O2 -> test_someone_elses_project_is_not_found
         O3 -> test_a_double_tap_is_one_request
         O4 -> test_a_project_has_at_most_one_open_request
         O5 -> test_cancelling_keeps_the_row
               test_a_confirmed_request_cannot_be_cancelled
         O6 -> test_browser_roles_are_refused
         O7 -> TestProductionArcIsAUuid::test_my_request_and_my_projects_graph_work
WHY      Founder 2026-09-25, decisions log N8 (0364): Delete is a request an
         operator confirms within 7 days. O7: founder 2026-10-20 (0488), both
         raised "operator does not exist: uuid = text" in production, whose
         arc_id is a UUID; this lane's narrow copy declares it TEXT.

Runs request_/cancel_project_deletion_v1 on the released rehearsal lane.
"""
from __future__ import annotations

import uuid

import psycopg2
import psycopg2.errors
import pytest

from tests import test_optional_consent_postgres as base

DSN = base.DSN
_one = base._one
db = base.db
principal = base.principal

pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)


def _project(db, principal):
    return _one(db, """
        INSERT INTO public.projects (id, owner_principal_id, display_name)
        VALUES (gen_random_uuid(), %s, 'Q3 pitch') RETURNING id""",
        (principal,))


@pytest.fixture
def project(db, principal):
    return _project(db, principal)


def _request(db, principal, project, key=None):
    with db.cursor() as cur:
        cur.execute("""
            SELECT id, state, due_at - requested_at, project_id
              FROM public.request_project_deletion_v1(%s, %s, %s)""",
            (principal, project, key or f"k-{uuid.uuid4()}"))
        return cur.fetchone()


def _cancel(db, principal, project):
    with db.cursor() as cur:
        cur.execute("""
            SELECT id, state, cancelled_at IS NOT NULL
              FROM public.cancel_project_deletion_v1(%s, %s)""",
            (principal, project))
        return cur.fetchone()


def test_owner_request_is_pending_and_due_in_seven_days(db, principal, project):
    request_id, state, window, project_id = _request(db, principal, project)
    assert state == "pending"
    assert window.days == 7
    assert str(project_id) == str(project)
    assert request_id


def test_someone_elses_project_is_not_found(db, principal, project):
    stranger = _one(db, """
        INSERT INTO public.owner_principals (id, user_id)
        VALUES (gen_random_uuid(), gen_random_uuid()) RETURNING id""")
    with pytest.raises(psycopg2.Error) as error:
        _request(db, stranger, project)
    assert "PROJECT_NOT_FOUND" in str(error.value)


def test_a_double_tap_is_one_request(db, principal, project):
    first = _request(db, principal, project, key="tap")
    again = _request(db, principal, project, key="tap")
    assert again[0] == first[0]

    other = _project(db, principal)
    with pytest.raises(psycopg2.Error) as error:
        _request(db, principal, other, key="tap")
    assert "IDEMPOTENCY_CONFLICT" in str(error.value)


def test_a_project_has_at_most_one_open_request(db, principal, project):
    first = _request(db, principal, project)
    second = _request(db, principal, project)
    assert second[0] == first[0]
    assert _one(db, """
        SELECT count(*) FROM public.project_deletion_requests
         WHERE project_id = %s""", (project,)) == 1


def test_cancelling_keeps_the_row(db, principal, project):
    request_id = _request(db, principal, project)[0]
    assert _cancel(db, principal, project) == (request_id, "cancelled", True)
    assert _one(db, """
        SELECT state FROM public.project_deletion_requests
         WHERE id = %s""", (request_id,)) == "cancelled"


def test_a_confirmed_request_cannot_be_cancelled(db, principal, project):
    request_id = _request(db, principal, project)[0]
    with db.cursor() as cur:
        cur.execute("""
            UPDATE public.project_deletion_requests
               SET state = 'confirmed', confirmed_at = now()
             WHERE id = %s""", (request_id,))
    with pytest.raises(psycopg2.Error) as error:
        _cancel(db, principal, project)
    assert "PROJECT_DELETION_ALREADY_CONFIRMED" in str(error.value)


def test_browser_roles_are_refused(db, principal, project):
    for role in ("anon", "authenticated"):
        for statement, args in (
            ("SELECT * FROM public.request_project_deletion_v1(%s, %s, 'k')",
             (principal, project)),
            ("SELECT * FROM public.cancel_project_deletion_v1(%s, %s)",
             (principal, project)),
            ("SELECT * FROM public.project_deletion_requests", ()),
        ):
            with db.cursor() as cur:
                cur.execute(f"SET ROLE {role}")
                try:
                    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                        cur.execute(statement, args)
                finally:
                    cur.execute("RESET ROLE")


UUID_PATTERN = "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


@pytest.fixture
def uuid_arc(db):
    """v2_sessions.arc_id as production declares it (UUID), and the
    recordings.session_id the graph reads, which this lane's narrow copy
    lacks, inside a transaction the test rolls back, so no other test sees
    either."""
    db.autocommit = False
    with db.cursor() as cur:
        cur.execute("ALTER TABLE public.recordings ADD COLUMN IF NOT EXISTS session_id uuid")
        cur.execute(f"""
            ALTER TABLE public.v2_sessions ALTER COLUMN arc_id TYPE uuid
            USING CASE WHEN arc_id ~* '{UUID_PATTERN}' THEN arc_id::uuid
                       ELSE md5(arc_id)::uuid END""")
    try:
        yield db
    finally:
        db.rollback()


class TestProductionArcIsAUuid:

    def test_my_request_and_my_projects_graph_work(self, db, principal, project, uuid_arc):
        take = _one(db, """
            INSERT INTO public.v2_sessions (
                id, arc_id, user_id, take_index, owner_principal_id)
            VALUES (gen_random_uuid(), %s, gen_random_uuid(), 1, %s)
            RETURNING id::text""", (project, principal))
        assert _request(db, principal, project)[1] == "pending"
        graph = _one(db, "SELECT public.resolve_phase1_purge_project_graph_v1(%s, %s)",
                     (principal, project))
        assert take in graph["take_ids"]
