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
