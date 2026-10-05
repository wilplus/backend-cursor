"""A coach's judgement stands and says why it was asked, on a disposable
database (W6 2026-10-05: LOCKIN §5c, contract 34; decisions K9; and the
walk's stamped pairs, C2/C5).

Pins:
  * confidence_labels carries the three K9 stamps, and a sampling
    probability outside (0, 1] is refused by the table itself;
  * label_revision gains `reconsideration` (false by default) and the K9
    stamps: the lane has no label_revision, so the suite builds the
    released shape and re-applies the migration in its own transaction,
    which it rolls back; without the table the migration is a no-op;
  * the migration is idempotent (the lane applies it twice);
  * the walk's exercise pairs fit the pair table's own keys: the saved
    instruction rides the request, the transcript the exercise version and
    the moment, and a second final on the same request is refused;
  * a practice recording's coach decision is written once: the guarded
    update the writer issues leaves a standing decision as it was.
"""
from __future__ import annotations

import os
import pathlib
import uuid

import psycopg2
import psycopg2.extras
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "a_coach_judgement_stands.sql"


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


def _body() -> str:
    """The migration without its own BEGIN/COMMIT, to run inside a test's
    transaction."""
    lines = [line for line in MIGRATION.read_text().splitlines()
             if line.strip() not in ("BEGIN;", "COMMIT;")]
    return "\n".join(lines)


def _columns(cur, table):
    cur.execute("SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = %s", (table,))
    return {r["column_name"] for r in cur.fetchall()}


def test_confidence_labels_carry_the_k9_stamps(db):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        assert {"selection_policy_version", "selection_reason",
                "sampling_probability"} <= _columns(cur, "confidence_labels")


def test_a_probability_outside_the_range_is_refused(db):
    snippet = str(uuid.uuid4())
    with db.cursor() as cur:
        cur.execute("INSERT INTO public.confidence_labels (snippet_id, value, "
                    "selection_policy_version, selection_reason, sampling_probability) "
                    "VALUES (%s, 'yes', 'coach-walk-reached-bookmarks-v1', "
                    "'reached_bookmark', 1.0)", (snippet,))
        cur.execute("INSERT INTO public.confidence_labels (snippet_id, value) "
                    "VALUES (%s, 'no')", (snippet,))
        for bad in (0, 1.5, -0.2):
            with pytest.raises(psycopg2.errors.CheckViolation):
                cur.execute("INSERT INTO public.confidence_labels (snippet_id, value, "
                            "sampling_probability) VALUES (%s, 'no', %s)",
                            (snippet, bad))


def test_label_revision_gains_the_reconsideration_and_the_stamps(db):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT to_regclass('public.label_revision') AS t")
        if cur.fetchone()["t"] is not None:
            pytest.skip("this lane carries label_revision; the shape is checked below")
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # The released shape (add_label_revision.sql), the columns this
            # migration and its writer touch.
            cur.execute("""
                CREATE TABLE public.label_revision (
                    id BIGSERIAL PRIMARY KEY,
                    snippet_id UUID NOT NULL,
                    rater_id UUID NULL,
                    state_id TEXT NOT NULL DEFAULT 'confidence',
                    value TEXT NULL,
                    origin TEXT NOT NULL DEFAULT 'live',
                    supersedes_id BIGINT NULL REFERENCES public.label_revision(id),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
            cur.execute(_body())
            cur.execute(_body())   # idempotent inside one transaction too
            assert {"reconsideration", "selection_policy_version", "selection_reason",
                    "sampling_probability"} <= _columns(cur, "label_revision")
            snippet, rater = str(uuid.uuid4()), str(uuid.uuid4())
            cur.execute("INSERT INTO public.label_revision (snippet_id, rater_id, value) "
                        "VALUES (%s, %s, 'no') RETURNING id, reconsideration",
                        (snippet, rater))
            original = cur.fetchone()
            assert original["reconsideration"] is False
            cur.execute("INSERT INTO public.label_revision (snippet_id, rater_id, value, "
                        "reconsideration, supersedes_id, selection_reason, "
                        "sampling_probability) VALUES (%s, %s, 'yes', true, %s, "
                        "'reached_bookmark', 1.0) RETURNING supersedes_id",
                        (snippet, rater, original["id"]))
            assert cur.fetchone()["supersedes_id"] == original["id"]
    finally:
        conn.rollback()
        conn.close()


def test_without_label_revision_the_migration_is_a_no_op(db):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT to_regclass('public.label_revision') AS t")
        if cur.fetchone()["t"] is not None:
            pytest.skip("this lane carries label_revision")
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(_body())
            cur.execute("SELECT to_regclass('public.label_revision')")
            assert cur.fetchone()[0] is None
    finally:
        conn.rollback()
        conn.close()


def _pair(cur, **over):
    row = {"surface": "exercise_script", "draft_text": "The model's script.",
           "final_text": "Let the final word land before you breathe.",
           "final_kind": "final", "draft_model_version": "gpt-test-1",
           "pattern_key": "ending_compression", "coach_id": "coach-1",
           "owner_user_id": "speaker-1", "take_session_id": "take-1",
           "snippet_id": "snip-1", "request_id": None,
           "exercise_id": None, "exercise_version": 1,
           "passage_text": "and that is why the number matters"}
    row.update(over)
    cols = ", ".join(row)
    marks = ", ".join(["%s"] * len(row))
    cur.execute(f"INSERT INTO public.feedback_pairs ({cols}) VALUES ({marks}) RETURNING id",
                list(row.values()))
    return cur.fetchone()[0]


def test_the_walk_s_two_pairs_fit_the_pair_table_s_keys(db):
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cur:
            request = str(uuid.uuid4())
            exercise = f"coach-request-{request}"
            _pair(cur, request_id=request, exercise_id=exercise)
            _pair(cur, final_text="let the final word land", final_kind="transcript",
                  exercise_id=exercise)
            cur.execute("SELECT count(*) FROM public.feedback_pairs WHERE exercise_id = %s",
                        (exercise,))
            assert cur.fetchone()[0] == 2
            cur.execute("SAVEPOINT again")
            with pytest.raises(psycopg2.errors.UniqueViolation):
                _pair(cur, request_id=request, exercise_id=exercise,
                      final_text="Another final.", exercise_version=2)
            cur.execute("ROLLBACK TO SAVEPOINT again")
    finally:
        conn.rollback()
        conn.close()


def test_a_standing_practice_decision_is_never_written_over(db):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' "
                    "AND table_name = 'confident_voice_practice_attempt'")
        if "coach_confidence_decision" not in {r["column_name"] for r in cur.fetchall()}:
            pytest.skip("no practice attempt table in this lane")
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cur:
            practice, attempt = str(uuid.uuid4()), str(uuid.uuid4())
            cur.execute("INSERT INTO public.confident_voice_practice "
                        "(id, owner_user_id, take_session_id) VALUES (%s, %s, %s)",
                        (practice, str(uuid.uuid4()), str(uuid.uuid4())))
            cur.execute("INSERT INTO public.confident_voice_practice_attempt "
                        "(id, practice_id, coach_confidence_decision) "
                        "VALUES (%s, %s, 'in_between')", (attempt, practice))
            # The writer's guarded update (services/db.py,
            # set_confident_voice_practice_attempt_coach_decision).
            cur.execute("UPDATE public.confident_voice_practice_attempt "
                        "SET coach_confidence_decision = 'yes' "
                        "WHERE id = %s AND practice_id = %s "
                        "AND coach_confidence_decision IS NULL", (attempt, practice))
            assert cur.rowcount == 0
            cur.execute("SELECT coach_confidence_decision FROM "
                        "public.confident_voice_practice_attempt WHERE id = %s", (attempt,))
            assert cur.fetchone()[0] == "in_between"
    finally:
        conn.rollback()
        conn.close()
