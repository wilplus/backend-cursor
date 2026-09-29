"""Did the coach-judged practice attempt sound more confident? (0388)

On a disposable database. Pins the rule exercise-more-confident-v1: helped
only when the attempt's confidence composite is higher than the original's
AND the coach said Yes; either No is not_helped; a missing score or a missing
coach answer is pending. Also: one row per practice, recomputed in place when
the coach revises; it goes with its practice; it can never be a label or reach
a user; browser roles reach nothing.
"""
from __future__ import annotations

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


def _practice(db, original, attempt, coach):
    practice_id, attempt_id = str(uuid.uuid4()), str(uuid.uuid4())
    snapshot = {} if original is None else {"confidence": original}
    metrics = {} if attempt is None else {"confidence": attempt}
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO public.confident_voice_practice "
            "(id, owner_user_id, take_session_id, acoustic_evidence) "
            "VALUES (%s, gen_random_uuid(), gen_random_uuid(), %s)",
            (practice_id, psycopg2.extras.Json({"snapshot": snapshot})))
        cur.execute(
            "INSERT INTO public.confident_voice_practice_attempt "
            "(id, practice_id, acoustic_metrics, coach_confidence_decision) "
            "VALUES (%s, %s, %s, %s)",
            (attempt_id, practice_id, psycopg2.extras.Json(metrics), coach))
    return practice_id, attempt_id


def _record(db, practice_id, attempt_id):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM public.record_practice_more_confident_v1(%s, %s)",
                    (practice_id, attempt_id))
        return dict(cur.fetchone())


@pytest.mark.parametrize("original, attempt, coach, machine, outcome", [
    (-0.4, 0.35, "yes", "higher", "helped"),
    (0.1, 0.11, "yes", "higher", "helped"),          # any increase counts
    (-0.4, 0.35, "no", "higher", "not_helped"),
    (0.3, 0.3, "yes", "not_higher", "not_helped"),   # equal is not higher
    (0.3, -0.2, "yes", "not_higher", "not_helped"),
    (0.3, -0.2, "no", "not_higher", "not_helped"),
    (None, 0.5, "yes", "unmeasurable", "pending"),
    (0.1, None, "yes", "unmeasurable", "pending"),
    (-0.4, 0.35, None, "higher", "pending"),         # coach has not answered
])
def test_the_rule(db, original, attempt, coach, machine, outcome):
    row = _record(db, *_practice(db, original, attempt, coach))
    assert row["machine_leg"] == machine
    assert row["coach_leg"] == coach
    assert row["outcome"] == outcome
    assert row["rule_version"] == "exercise-more-confident-v1"
    assert row["is_label"] is False
    assert row["serves_user"] is False


def test_a_non_number_is_no_score(db):
    practice_id, attempt_id = _practice(db, 0.1, None, "yes")
    with db.cursor() as cur:
        cur.execute("UPDATE public.confident_voice_practice_attempt "
                    "SET acoustic_metrics = '{\"confidence\": \"0.9\"}' WHERE id = %s",
                    (attempt_id,))
    assert _record(db, practice_id, attempt_id)["machine_leg"] == "unmeasurable"


def test_one_row_per_practice_recomputed_when_the_coach_revises(db):
    practice_id, attempt_id = _practice(db, -0.4, 0.35, "yes")
    assert _record(db, practice_id, attempt_id)["outcome"] == "helped"
    with db.cursor() as cur:
        cur.execute("UPDATE public.confident_voice_practice_attempt "
                    "SET coach_confidence_decision = 'no' WHERE id = %s", (attempt_id,))
    assert _record(db, practice_id, attempt_id)["outcome"] == "not_helped"
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM public.practice_more_confident_outcomes "
                    "WHERE practice_id = %s", (practice_id,))
        assert cur.fetchone()[0] == 1


def test_an_attempt_of_another_practice_is_refused(db):
    practice_id, _ = _practice(db, 0.1, 0.2, "yes")
    _, other_attempt = _practice(db, 0.1, 0.2, "yes")
    with pytest.raises(psycopg2.Error, match="PRACTICE_MORE_CONFIDENT_NOT_FOUND"):
        _record(db, practice_id, other_attempt)


def test_it_can_never_be_a_label_or_serve_a_user(db):
    practice_id, attempt_id = _practice(db, 0.1, 0.2, "yes")
    _record(db, practice_id, attempt_id)
    for column in ("is_label", "serves_user"):
        with pytest.raises(psycopg2.Error):
            with db.cursor() as cur:
                cur.execute(f"UPDATE public.practice_more_confident_outcomes "
                            f"SET {column} = true WHERE practice_id = %s",
                            (practice_id,))


def test_it_goes_with_its_practice(db):
    practice_id, attempt_id = _practice(db, 0.1, 0.2, "yes")
    _record(db, practice_id, attempt_id)
    with db.cursor() as cur:
        cur.execute("DELETE FROM public.confident_voice_practice WHERE id = %s",
                    (practice_id,))
        cur.execute("SELECT count(*) FROM public.practice_more_confident_outcomes "
                    "WHERE practice_id = %s", (practice_id,))
        assert cur.fetchone()[0] == 0


def test_who_may_do_what(db):
    with db.cursor() as cur:
        for role in ("anon", "authenticated"):
            cur.execute("SELECT has_table_privilege(%s, "
                        "'public.practice_more_confident_outcomes', 'SELECT')", (role,))
            assert cur.fetchone()[0] is False
            cur.execute("SELECT has_function_privilege(%s, "
                        "'public.record_practice_more_confident_v1(uuid,uuid)', "
                        "'EXECUTE')", (role,))
            assert cur.fetchone()[0] is False
        for privilege, expected in (("SELECT", True), ("DELETE", True),
                                    ("INSERT", False), ("UPDATE", False)):
            cur.execute("SELECT has_table_privilege('service_role', "
                        "'public.practice_more_confident_outcomes', %s)", (privilege,))
            assert cur.fetchone()[0] is expected, privilege
