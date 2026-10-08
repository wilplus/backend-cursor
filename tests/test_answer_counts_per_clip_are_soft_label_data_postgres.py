"""Answer counts per clip are soft-label data, on a disposable database
(0442; V4 brief 1.7, Q1, Q2, Q3; V17 A; build plan D-ML-11).

Pins:
  * the table exists with RLS on; browser roles hold nothing on it or on the
    function; service_role reads, deletes and calls the function, and
    cannot write the table by hand;
  * the file applied again changes nothing;
  * the function counts only what the quorum would count: coach and
    game_peer lanes, no self-report, no game_owner lane, no Audio-unclear
    abstention, no anonymous rater, no bootstrap lane; In-between counts
    half; Not sure is counted apart and takes no share; the machine's
    proposal beside an answer is never read;
  * a clip nobody answered gets zeros and no soft label; the table's own
    checks refuse a row whose sum or soft label is wrong;
  * a non-blind row (0411) is not counted, as the quorum does not count it;
    historical 'neutral' counts as Not sure;
  * two refreshes of one clip are serialized: a refresh that started before
    a newer rating committed cannot overwrite the newer count;
  * the quorum (services.label_quorum) is untouched: MACHINE_VOTES stays 0
    and its lanes stay coach and game_peer, whatever the counts say.
"""
from __future__ import annotations

import os
import pathlib
import threading
import time
import uuid
from decimal import Decimal

import psycopg2
import psycopg2.extras
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "answer_counts_per_clip_are_soft_label_data.sql"


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


def _role_exists(cur, role: str) -> bool:
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
    return cur.fetchone() is not None


def _label(cur, snippet_id, *, value, lane="coach", rater=None,
           self_report=False, unrateable=False, machine_value=None,
           state_id="confidence", blind=True):
    cur.execute(
        "INSERT INTO public.confidence_labels (snippet_id, rater_id, source, "
        "confident, state_id, value, lane, self_report, unrateable, machine_value, "
        "blind) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (snippet_id, rater or str(uuid.uuid4()),
         "coach" if lane in ("coach", "bootstrap") else "game",
         True if value == "yes" else False if value == "no" else None,
         state_id, value, lane, self_report, unrateable, machine_value, blind))


def _counts(cur, snippet_id) -> dict:
    cur.execute("SELECT * FROM public.refresh_clip_answer_counts_v1(%s)", (snippet_id,))
    return dict(cur.fetchone())


def test_the_table_and_the_function_exist_behind_the_door(db):
    with db.cursor() as cur:
        cur.execute("SELECT relrowsecurity FROM pg_class WHERE relname = 'clip_answer_counts'")
        assert cur.fetchone() == (True,)
        cur.execute("SELECT prosecdef, proconfig FROM pg_proc "
                    "WHERE proname = 'refresh_clip_answer_counts_v1'")
        secdef, config = cur.fetchone()
        assert secdef is True
        assert any(c.startswith("search_path=") for c in (config or []))
        for role in ("anon", "authenticated"):
            if not _role_exists(cur, role):
                continue
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                cur.execute("SELECT has_table_privilege(%s, 'public.clip_answer_counts', %s)",
                            (role, privilege))
                assert cur.fetchone()[0] is False, (role, privilege)
            cur.execute("SELECT has_function_privilege(%s, "
                        "'public.refresh_clip_answer_counts_v1(uuid)', 'EXECUTE')", (role,))
            assert cur.fetchone()[0] is False, role
        # PUBLIC is grantee 0 in an ACL; nothing may be granted to it.
        cur.execute("SELECT count(*) FROM pg_class c, aclexplode(c.relacl) a "
                    "WHERE c.oid = 'public.clip_answer_counts'::regclass AND a.grantee = 0")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM pg_proc p, aclexplode(p.proacl) a "
                    "WHERE p.oid = 'public.refresh_clip_answer_counts_v1(uuid)'::regprocedure "
                    "AND a.grantee = 0")
        assert cur.fetchone()[0] == 0
        if _role_exists(cur, "service_role"):
            for privilege, expected in (("SELECT", True), ("DELETE", True),
                                        ("INSERT", False), ("UPDATE", False)):
                cur.execute("SELECT has_table_privilege('service_role', "
                            "'public.clip_answer_counts', %s)", (privilege,))
                assert cur.fetchone()[0] is expected, privilege
            cur.execute("SELECT has_function_privilege('service_role', "
                        "'public.refresh_clip_answer_counts_v1(uuid)', 'EXECUTE')")
            assert cur.fetchone()[0] is True


def test_applied_again_the_file_changes_nothing(db):
    snippet = str(uuid.uuid4())
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        _label(cur, snippet, value="yes")
        before = _counts(cur, snippet)
        cur.execute("SELECT count(*) FROM public.clip_answer_counts")
        rows_before = cur.fetchone()["count"]
        cur.execute(MIGRATION.read_text())
        cur.execute("SELECT count(*) FROM public.clip_answer_counts")
        assert cur.fetchone()["count"] == rows_before
        cur.execute("SELECT * FROM public.clip_answer_counts WHERE snippet_id = %s", (snippet,))
        after = dict(cur.fetchone())
        assert after == before


def test_only_the_quorum_s_human_votes_are_counted_and_in_between_counts_half(db):
    snippet = str(uuid.uuid4())
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # Counted: a coach's Yes, a peer's In-between, a coach's No, a coach's
        # Not sure (kept apart). The machine's proposal beside each is noise.
        _label(cur, snippet, value="yes", lane="coach", machine_value="no")
        _label(cur, snippet, value="in_between", lane="game_peer", machine_value="no")
        _label(cur, snippet, value="no", lane="coach", machine_value="yes")
        _label(cur, snippet, value="not_sure", lane="coach", machine_value="yes")
        # Never counted (L3, Q3): the speaker on their own clip, twice over;
        # an Audio-unclear abstention; an anonymous row; the bootstrap lane;
        # another instrument's state.
        _label(cur, snippet, value="yes", lane="coach", self_report=True)
        _label(cur, snippet, value="yes", lane="game_owner")
        _label(cur, snippet, value="yes", lane="coach", unrateable=True)
        _label(cur, snippet, value="yes", lane="bootstrap")
        _label(cur, snippet, value="yes", lane="coach", state_id="warmth")
        cur.execute("INSERT INTO public.confidence_labels (snippet_id, rater_id, source, "
                    "confident, state_id, value, lane) "
                    "VALUES (%s, NULL, 'game', true, 'confidence', 'yes', 'game_peer')",
                    (snippet,))
        row = _counts(cur, snippet)
    assert (row["yes_count"], row["in_between_count"], row["no_count"],
            row["not_sure_count"], row["perceptual_count"]) == (1, 1, 1, 1, 3)
    # Q1 / V17 A: (1 + 0.5 + 0) / 3.
    assert row["soft_label"] == Decimal("0.50000")
    assert row["lanes_counted"] == ["coach", "game_peer"]
    assert row["rule_version"] == "soft-label-v1"
    # The quorum reads the same ledger and is untouched by the counts.
    from services import label_quorum as lq
    assert lq.MACHINE_VOTES == 0
    assert lq.QUORUM_LANES == ("coach", "game_peer")
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM public.confidence_labels WHERE snippet_id = %s", (snippet,))
        ledger = [dict(r) for r in cur.fetchall()]
    for r in ledger:
        r["rater_id"] = str(r["rater_id"]) if r["rater_id"] else None
    assert lq.resolve(ledger)["machine_votes"] == 0


def test_a_clip_nobody_answered_has_zeros_and_no_soft_label(db):
    snippet = str(uuid.uuid4())
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        row = _counts(cur, snippet)
        assert (row["yes_count"], row["in_between_count"], row["no_count"],
                row["not_sure_count"], row["perceptual_count"]) == (0, 0, 0, 0, 0)
        assert row["soft_label"] is None
        # A second refresh after one answer rebuilds the same row.
        _label(cur, snippet, value="in_between", lane="game_peer")
        row = _counts(cur, snippet)
        assert row["perceptual_count"] == 1
        assert row["soft_label"] == Decimal("0.50000")
        cur.execute("SELECT count(*) FROM public.clip_answer_counts WHERE snippet_id = %s",
                    (snippet,))
        assert cur.fetchone()["count"] == 1
        with pytest.raises(psycopg2.errors.RaiseException):
            cur.execute("SELECT * FROM public.refresh_clip_answer_counts_v1(NULL)")


def test_the_table_s_own_checks_hold(db):
    with db.cursor() as cur:
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("INSERT INTO public.clip_answer_counts (snippet_id, yes_count, "
                        "perceptual_count, soft_label) VALUES (%s, 2, 1, 1)", (str(uuid.uuid4()),))
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("INSERT INTO public.clip_answer_counts (snippet_id, yes_count, "
                        "perceptual_count, soft_label) VALUES (%s, 1, 1, NULL)", (str(uuid.uuid4()),))
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("INSERT INTO public.clip_answer_counts (snippet_id, soft_label) "
                        "VALUES (%s, 0.5)", (str(uuid.uuid4()),))


def test_service_role_calls_the_function_and_cannot_write_the_table_by_hand(db):
    with db.cursor() as cur:
        if not _role_exists(cur, "service_role"):
            pytest.skip("no service_role on this cluster")
    snippet = str(uuid.uuid4())
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SET ROLE service_role")
            cur.execute("SELECT perceptual_count FROM public.refresh_clip_answer_counts_v1(%s)",
                        (snippet,))
            assert cur.fetchone() == (0,)
            cur.execute("SELECT count(*) FROM public.clip_answer_counts WHERE snippet_id = %s",
                        (snippet,))
            assert cur.fetchone() == (1,)
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute("INSERT INTO public.clip_answer_counts (snippet_id) VALUES (%s)",
                            (str(uuid.uuid4()),))
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute("UPDATE public.clip_answer_counts SET yes_count = 9 "
                            "WHERE snippet_id = %s", (snippet,))
            cur.execute("DELETE FROM public.clip_answer_counts WHERE snippet_id = %s", (snippet,))
            cur.execute("SELECT count(*) FROM public.clip_answer_counts WHERE snippet_id = %s",
                        (snippet,))
            assert cur.fetchone() == (0,)
    finally:
        conn.close()


def test_a_non_blind_row_is_not_counted_and_neutral_is_not_sure(db):
    snippet = str(uuid.uuid4())
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        _label(cur, snippet, value="yes", lane="coach")
        # The rater had seen the clip's non-blind side: the quorum ignores
        # it (label_quorum, 0411), so the counts ignore it too.
        _label(cur, snippet, value="no", lane="coach", blind=False)
        _label(cur, snippet, value="no", lane="game_peer", blind=False)
        # Historical v1 spelling of Not sure.
        _label(cur, snippet, value="neutral", lane="game_peer")
        row = _counts(cur, snippet)
    assert (row["yes_count"], row["no_count"], row["not_sure_count"],
            row["perceptual_count"]) == (1, 0, 1, 1)
    assert row["soft_label"] == Decimal("1.00000")


def test_a_slow_refresh_cannot_overwrite_a_newer_count(db):
    """Two refreshes of one clip: the first holds the clip's lock until its
    transaction commits, the second waits and recounts after it, so the
    stored row is the newer count, never the older snapshot."""
    snippet = str(uuid.uuid4())
    writer = psycopg2.connect(DSN)
    other = psycopg2.connect(DSN)
    other.autocommit = True
    result: dict = {}
    try:
        with writer.cursor() as cur:
            _label(cur, snippet, value="yes", lane="coach")
            cur.execute("SELECT perceptual_count FROM "
                        "public.refresh_clip_answer_counts_v1(%s)", (snippet,))
            assert cur.fetchone() == (1,)

        def second():
            with other.cursor() as c2:
                c2.execute("SELECT perceptual_count FROM "
                           "public.refresh_clip_answer_counts_v1(%s)", (snippet,))
                result["count"] = c2.fetchone()[0]

        t = threading.Thread(target=second)
        t.start()
        # The second refresh waits on the clip's advisory lock.
        deadline = time.time() + 10
        waiting = False
        with db.cursor() as probe:
            while time.time() < deadline and not waiting:
                probe.execute("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
                              "AND NOT granted")
                waiting = probe.fetchone()[0] > 0
                if not waiting:
                    time.sleep(0.05)
        assert waiting, "the second refresh did not wait for the first"
        assert "count" not in result
        writer.commit()
        t.join(10)
        assert not t.is_alive()
        # It recounted after the first committed and saw the new label.
        assert result["count"] == 1
        with db.cursor() as cur:
            cur.execute("SELECT perceptual_count FROM public.clip_answer_counts "
                        "WHERE snippet_id = %s", (snippet,))
            assert cur.fetchone() == (1,)
    finally:
        writer.close()
        other.close()
