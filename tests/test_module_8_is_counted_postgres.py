"""0395 on a disposable database: the readiness report has eight rows, the
eighth read from the exercise tables, and a release may name module 8.

Founder 2026-09-29, decision 2 (audit G-5). Released lane only: 0395
re-creates get_seven_surface_readiness_v1 over the 0299 tables, which the
narrow lane does not carry; the suite skips itself where the function is
absent rather than reading that as a failure.

The target must be a disposable local database whose name starts with
``willab_confident_moment_``.
"""
from __future__ import annotations

import json
import os
import uuid

import psycopg2
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
    with conn.cursor() as cur:
        cur.execute("SELECT to_regproc('public.get_seven_surface_readiness_v1')")
        if cur.fetchone()[0] is None:
            conn.close()
            pytest.skip("0395 applies on the released lane only")
    try:
        yield conn
    finally:
        conn.close()


def _report(db) -> dict:
    with db.cursor() as cur:
        cur.execute("SELECT public.get_seven_surface_readiness_v1()")
        value = cur.fetchone()[0]
    return value if isinstance(value, dict) else json.loads(value)


def _assign(db, *, owner: str, take: str, snippet: str) -> str:
    """One frozen singleton assignment through the released RPC (0372)."""
    with db.cursor() as cur:
        cur.execute(
            "SELECT id FROM public.assign_confident_voice_exercise_v1("
            "%s, %s, %s, 'v3_exercise_block', 'exercise-matching-v1', "
            "%s::jsonb)",
            (owner, take, snippet,
             json.dumps([{"exercise_id": "hear-every-word-v1", "version": 1}])),
        )
        return str(cur.fetchone()[0])


def test_module_8_counts_assignments_renders_and_practices(db):
    before = _report(db)["surfaces"][-1]
    owner = str(uuid.uuid4())
    take, snippet = str(uuid.uuid4()), str(uuid.uuid4())
    assignment = _assign(db, owner=owner, take=take, snippet=snippet)
    with db.cursor() as cur:
        cur.execute(
            "SELECT id FROM public.record_exercise_rendered_v1(%s, %s, %s, %s)",
            (owner, take, snippet, "hear-every-word-v1"))
        assert cur.fetchone()[0] is not None
        cur.execute(
            "INSERT INTO public.confident_voice_practice "
            "(id, owner_user_id, take_session_id, project_id, "
            "machine_assessment) VALUES (%s, %s, %s, %s, %s::jsonb)",
            (str(uuid.uuid4()), owner, take, str(uuid.uuid4()),
             json.dumps({"exercise_assignment_id": assignment})))
    after = _report(db)["surfaces"][-1]

    assert after["prepared_presentation_count"] == \
        before["prepared_presentation_count"] + 1
    assert after["visible_exposure_count"] == before["visible_exposure_count"] + 1
    assert after["shown_presentation_count"] == \
        before["shown_presentation_count"] + 1
    assert after["answered_exposure_count"] == \
        before["answered_exposure_count"] + 1
    assert after["status"] == "collecting"
    assert after["versioned_presentation_count"] == \
        after["prepared_presentation_count"]
    assert {"matching_policy_version": "exercise-matching-v1",
            "exposure_policy_version": "exercise-80-20-v1"} in after["versions"]
