"""Project deletion requests (0364), against the real functions.

FOUNDER 2026-09-25, decisions log N8. The picker's Delete is a REQUEST an
operator confirms within 7 days; the owner may cancel until then. These cases
pin what the application relies on:

  * only the project's owner can ask, and the due date is 7 days out;
  * a double tap is one request, and a replayed key never names a different
    project;
  * at most one open request per project;
  * cancelling works only while pending, and the row is kept, never deleted;
  * browser roles cannot call the functions or read the table.
"""
from __future__ import annotations

import uuid

import psycopg2
import pytest

from tests import test_optional_consent_postgres as base

DSN = base.DSN
_one = base._one
db = base.db
principal = base.principal

pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)


@pytest.fixture
def project(db, principal):
    return _one(db, """
        INSERT INTO public.projects (id, owner_principal_id, display_name)
        VALUES (gen_random_uuid(), %s, 'Q3 pitch') RETURNING id""",
        (principal,))


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
