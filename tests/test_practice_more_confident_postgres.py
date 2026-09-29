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


def _practice(db, original, attempt, coach, before="no"):
    """A practice whose coach rated the original `before` (blind) and the
    attempt `coach`. before=None: no blind rating; "unrateable": abstained."""
    practice_id, attempt_id = str(uuid.uuid4()), str(uuid.uuid4())
    snippet, rater = str(uuid.uuid4()), str(uuid.uuid4())
    snapshot = {} if original is None else {"confidence": original}
    metrics = {} if attempt is None else {"confidence": attempt}
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO public.confident_voice_practice "
            "(id, owner_user_id, take_session_id, acoustic_evidence, snippet_id) "
            "VALUES (%s, gen_random_uuid(), gen_random_uuid(), %s, %s)",
            (practice_id, psycopg2.extras.Json({"snapshot": snapshot}), snippet))
        cur.execute(
            "INSERT INTO public.confident_voice_practice_attempt "
            "(id, practice_id, acoustic_metrics, coach_confidence_decision, "
            "coach_confidence_decided_by) VALUES (%s, %s, %s, %s, %s)",
            (attempt_id, practice_id, psycopg2.extras.Json(metrics), coach, rater))
        if before is not None:
            cur.execute(
                "INSERT INTO public.confidence_labels "
                "(snippet_id, rater_id, value, unrateable) VALUES (%s, %s, %s, %s)",
                (snippet, rater, None if before == "unrateable" else before,
                 before == "unrateable"))
    return practice_id, attempt_id


def _record(db, practice_id, attempt_id):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM public.record_practice_more_confident_v1(%s, %s)",
                    (practice_id, attempt_id))
        return dict(cur.fetchone())


@pytest.mark.parametrize("original, attempt, before, after, machine, coach, outcome", [
    # coach heard it get better (No -> Yes), machine up: helped
    (-0.4, 0.35, "no", "yes", "higher", "yes", "helped"),
    (0.1, 0.11, "no", "in_between", "higher", "yes", "helped"),   # any rise
    (0.1, 0.5, "neutral", "yes", "higher", "yes", "helped"),
    # coach did not hear it get better
    (-0.4, 0.35, "no", "no", "higher", "no", "not_helped"),
    (-0.4, 0.35, "yes", "in_between", "higher", "no", "not_helped"),
    # machine not higher
    (0.3, 0.3, "no", "yes", "not_higher", "yes", "not_helped"),
    # already confident before and after: cannot tell
    (-0.4, 0.35, "yes", "yes", "higher", None, "pending"),
    # off the ladder or missing
    (-0.4, 0.35, "no", "not_sure", "higher", None, "pending"),
    (-0.4, 0.35, "no", "audio_unclear", "higher", None, "pending"),
    (-0.4, 0.35, "unrateable", "yes", "higher", None, "pending"),
    (-0.4, 0.35, None, "yes", "higher", None, "pending"),
    (-0.4, 0.35, "no", None, "higher", None, "pending"),
    (None, 0.5, "no", "yes", "unmeasurable", "yes", "pending"),
])
def test_the_rule(db, original, attempt, before, after, machine, coach, outcome):
    row = _record(db, *_practice(db, original, attempt, after, before=before))
    assert row["machine_leg"] == machine
    assert row["coach_leg"] == coach
    assert row["coach_after"] == after
    assert row["outcome"] == outcome
    assert row["rule_version"] == "exercise-more-confident-v2"
    assert row["is_label"] is False
    assert row["serves_user"] is False


def test_the_before_answer_is_the_same_coachs(db):
    # Another rater's blind "no" must not stand in for this coach's.
    practice_id, attempt_id = _practice(db, -0.4, 0.35, "yes", before=None)
    with db.cursor() as cur:
        cur.execute("SELECT snippet_id FROM public.confident_voice_practice "
                    "WHERE id = %s", (practice_id,))
        snippet = cur.fetchone()[0]
        cur.execute("INSERT INTO public.confidence_labels (snippet_id, rater_id, "
                    "value) VALUES (%s, gen_random_uuid(), 'no')", (snippet,))
    assert _record(db, practice_id, attempt_id)["outcome"] == "pending"


def test_a_non_number_is_no_score(db):
    practice_id, attempt_id = _practice(db, 0.1, None, "yes")
    with db.cursor() as cur:
        cur.execute("UPDATE public.confident_voice_practice_attempt "
                    "SET acoustic_metrics = '{\"confidence\": \"0.9\"}' WHERE id = %s",
                    (attempt_id,))
    assert _record(db, practice_id, attempt_id)["machine_leg"] == "unmeasurable"


def test_one_row_per_practice_recomputed_when_the_coach_revises(db):
    practice_id, attempt_id = _practice(db, -0.4, 0.35, "yes", before="no")
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
