"""A speaker may change a judgement; the first answer stays, on a
disposable database (0440, D-FW-9; founder QA1 A).

Runs the real revise_take_feedback_response_v1 and the readers' overlay
(DatabaseService._latest_self_reports over psycopg2). Pins: a change is a
new revision and the first answer's row is byte-for-byte unchanged; the
same answer again is a replay; going back to the first answer is a
revision; a rewrite's answer is not revisable; no first answer, nothing to
revise; a revision is never edited; two concurrent changes get two
numbers; the readers see the latest with the first beside it; closed to
the browser roles; applying the file again keeps every row."""
from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace

import psycopg2
import psycopg2.extras
import pytest

from services.db import DatabaseService

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)
MIGRATION = (Path(__file__).resolve().parents[1] / "migrations"
             / "a_speaker_may_change_a_judgement.sql")


@pytest.fixture(scope="module")
def db():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.take_feedback_self_report')")
        if cur.fetchone()[0] is None:
            conn.close()
            pytest.skip("this lane has no take_feedback_self_report")
    try:
        yield conn
    finally:
        conn.close()


def _first(cur, *, family="confident_voice", response="no"):
    take, owner = str(uuid.uuid4()), str(uuid.uuid4())
    cur.execute("INSERT INTO public.v2_sessions (id, arc_id, user_id, take_index) "
                "VALUES (%s, 'arc-x', %s, 1)", (take, owner))
    cur.execute(
        "INSERT INTO public.take_feedback_self_report (arc_id, take_session_id, "
        "owner_user_id, feedback_id, feedback_family, snippet_id, response) "
        "VALUES ('arc-x', %s, %s, 'item-1', %s, %s, %s) RETURNING id",
        (take, owner, family, str(uuid.uuid4()), response))
    return take, owner, cur.fetchone()[0]


def _revise(cur, take, owner, response, item="item-1"):
    cur.execute("SELECT public.revise_take_feedback_response_v1(%s, %s, %s, %s)",
                (take, owner, item, response))
    return cur.fetchone()[0]


def _row(cur, report_id):
    cur.execute("SELECT to_jsonb(r) FROM public.take_feedback_self_report r "
                "WHERE id = %s", (report_id,))
    return cur.fetchone()[0]


def test_a_change_is_kept_beside_the_first(db):
    with db.cursor() as cur:
        take, owner, report = _first(cur)
        before = _row(cur, report)
        changed = _revise(cur, take, owner, "yes")
        assert changed["outcome"] == "revised"
        assert changed["row"]["response"] == "yes"
        assert changed["row"]["first_response"] == "no"
        assert changed["row"]["revision"] == 1
        assert _revise(cur, take, owner, "yes")["outcome"] == "replayed"
        back = _revise(cur, take, owner, "no")
        assert (back["outcome"], back["row"]["revision"]) == ("revised", 2)
        assert _row(cur, report) == before
        cur.execute("SELECT revision, response FROM "
                    "public.take_feedback_self_report_revision WHERE report_id = %s "
                    "ORDER BY revision", (report,))
        assert cur.fetchall() == [(1, "yes"), (2, "no")]


def test_only_a_confident_voice_judgement_reopens(db):
    with db.cursor() as cur:
        take, owner, _ = _first(cur, family="rewrite_clarity", response="keep_wording")
        assert _revise(cur, take, owner, "yes")["outcome"] == "not_revisable"
        assert _revise(cur, take, owner, "yes", item="never-answered")["outcome"] == (
            "not_answered")
        assert _revise(cur, take, str(uuid.uuid4()), "yes")["outcome"] == "not_answered"
        with pytest.raises(psycopg2.Error):
            _revise(cur, take, owner, "maybe")
        with pytest.raises(psycopg2.Error):
            _revise(cur, "not-a-take", owner, "yes")


def test_a_revision_is_never_edited(db):
    with db.cursor() as cur:
        take, owner, report = _first(cur)
        _revise(cur, take, owner, "in_between")
        with pytest.raises(psycopg2.Error, match="NEVER EDITED"):
            cur.execute("UPDATE public.take_feedback_self_report_revision "
                        "SET response = 'yes' WHERE report_id = %s", (report,))


def test_two_concurrent_changes_get_two_numbers(db):
    with db.cursor() as cur:
        take, owner, report = _first(cur)
    barrier = threading.Barrier(2)
    outcomes: list = []

    def worker(answer):
        conn = psycopg2.connect(DSN)
        conn.autocommit = True
        try:
            barrier.wait()
            with conn.cursor() as cur:
                outcomes.append(_revise(cur, take, owner, answer)["outcome"])
        finally:
            conn.close()

    threads = [threading.Thread(target=worker, args=(a,)) for a in ("yes", "not_sure")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert sorted(outcomes) == ["revised", "revised"]
    with db.cursor() as cur:
        cur.execute("SELECT array_agg(revision ORDER BY revision) FROM "
                    "public.take_feedback_self_report_revision WHERE report_id = %s",
                    (report,))
        assert cur.fetchone()[0] == [1, 2]


class _Table:
    def __init__(self, conn):
        self.conn, self.ids = conn, []

    def select(self, *_a):
        return self

    def in_(self, _column, ids):
        self.ids = list(ids)
        return self

    def execute(self):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT report_id, response, revision, created_at FROM "
                        "public.take_feedback_self_report_revision "
                        "WHERE report_id = ANY(%s)", (self.ids,))
            return SimpleNamespace(data=[dict(r) for r in cur.fetchall()])


def test_the_readers_see_the_latest_with_the_first_beside_it(db):
    with db.cursor() as cur:
        take, owner, report = _first(cur)
        _revise(cur, take, owner, "in_between")
        _revise(cur, take, owner, "yes")
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM public.take_feedback_self_report WHERE id = %s",
                    (report,))
        rows = [dict(cur.fetchone())]
    client = SimpleNamespace(table=lambda _name: _Table(db))
    latest = DatabaseService._latest_self_reports(
        SimpleNamespace(client=client), rows)  # type: ignore[arg-type]
    assert latest[0]["response"] == "yes"
    assert latest[0]["first_response"] == "no"
    assert latest[0]["id"] == report


def test_closed_to_the_browser_and_idempotent(db):
    with db.cursor() as cur:
        cur.execute("SELECT relrowsecurity FROM pg_class WHERE oid = "
                    "'public.take_feedback_self_report_revision'::regclass")
        assert cur.fetchone()[0] is True
        for role in ("public", "anon", "authenticated"):
            if role != "public":
                cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
                if cur.fetchone() is None:
                    continue
                cur.execute("SELECT has_table_privilege(%s, "
                            "'public.take_feedback_self_report_revision', "
                            "'SELECT, INSERT, UPDATE, DELETE')", (role,))
                assert cur.fetchone()[0] is False
            cur.execute("SELECT has_function_privilege(%s, "
                        "'public.revise_take_feedback_response_v1(text, text, text, text)', "
                        "'EXECUTE')", (role,))
            assert cur.fetchone()[0] is False, role
        cur.execute("SELECT count(*) FROM public.take_feedback_self_report_revision")
        before = cur.fetchone()[0]
        cur.execute(MIGRATION.read_text())
        cur.execute("SELECT count(*) FROM public.take_feedback_self_report_revision")
        assert cur.fetchone()[0] == before
        cur.execute("SELECT count(*) FROM pg_trigger WHERE tgname = "
                    "'take_feedback_self_report_revision_never_changes'")
        assert cur.fetchone()[0] == 1
        # Another suite in this lane may rebuild take_feedback_self_report
        # (dropping the key with it); applying the file again puts the key
        # back exactly once, which is the idempotency that matters.
        cur.execute(MIGRATION.read_text())
        cur.execute("SELECT count(*) FROM pg_constraint WHERE conname = "
                    "'take_feedback_self_report_revision_report_fkey'")
        assert cur.fetchone()[0] == 1
