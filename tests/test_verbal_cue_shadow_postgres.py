"""The shadow stage and its silent log, executed on a disposable database (0386).

Founder 2026-09-28, D2 + D3. Pins:

  * the library accepts `shadow`, and a shadow entry must name its detector;
  * the three spoken-word cues are seeded in the shadow stage;
  * verdicts are insert-once per (clip, cue, version) and never change;
  * only a cue the library measures (shadow or detected) can be logged;
  * a verdict can never be marked as serving a user or a dataset;
  * browser roles reach nothing; the server writes through the function and
    may read and erase.
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


def _scalar(db, sql, args=()):
    with db.cursor() as cur:
        cur.execute(sql, args)
        row = cur.fetchone()
        return row[0] if row else None


def _row(take, snippet, cue="hedging", fired=True, version="verbal-cues-v1"):
    return {"take_session_id": take, "snippet_id": snippet,
            "recording_id": str(uuid.uuid4()), "error_id": cue,
            "detector_version": version, "language": "en", "fired": fired,
            "measurements": {"n_words": 12, "count": 2}}


def _record(db, rows):
    return _scalar(db, "SELECT public.record_verbal_cue_shadow_v1(%s::jsonb)",
                   (psycopg2.extras.Json(rows),))


def test_the_three_cues_are_seeded_in_the_shadow_stage(db):
    with db.cursor() as cur:
        cur.execute("SELECT error_id, status, detector_ref FROM public.speaking_error "
                    "WHERE error_id IN ('filler_cluster','hedging','restart_repair') "
                    "ORDER BY error_id")
        rows = cur.fetchall()
    assert [r[0] for r in rows] == ["filler_cluster", "hedging", "restart_repair"]
    assert all(r[1] == "shadow" and r[2] for r in rows)


def test_a_shadow_entry_must_name_its_detector(db):
    with pytest.raises(psycopg2.Error, match="detected_needs_detector"):
        with db.cursor() as cur:
            cur.execute("INSERT INTO public.speaking_error (error_id, label, "
                        "definition, asks, status) VALUES "
                        "('no_detector_here','x','x','x','shadow')")
    with pytest.raises(psycopg2.Error, match="status_check"):
        with db.cursor() as cur:
            cur.execute("INSERT INTO public.speaking_error (error_id, label, "
                        "definition, asks, status, detector_ref) VALUES "
                        "('bad_status','x','x','x','maybe','d')")


def test_verdicts_are_insert_once(db):
    take, snippet = str(uuid.uuid4()), str(uuid.uuid4())
    assert _record(db, [_row(take, snippet), _row(take, snippet, "restart_repair")]) == 2
    # A retried job writes nothing new, whatever it now thinks.
    assert _record(db, [_row(take, snippet, fired=False)]) == 0
    assert _scalar(db, "SELECT fired FROM public.verbal_cue_shadow_observations "
                       "WHERE snippet_id = %s AND error_id = 'hedging'", (snippet,)) is True
    # A new detector version is a new verdict.
    assert _record(db, [_row(take, snippet, version="verbal-cues-v2")]) == 1


def test_only_a_measured_cue_can_be_logged(db):
    with db.cursor() as cur:
        cur.execute("INSERT INTO public.speaking_error (error_id, label, definition, "
                    "asks, status) VALUES ('only_named_here','x','x','x','observed') "
                    "ON CONFLICT DO NOTHING")
    with pytest.raises(psycopg2.Error, match="CUE_NOT_MEASURED"):
        _record(db, [_row(str(uuid.uuid4()), str(uuid.uuid4()), "only_named_here")])


def test_malformed_rows_are_refused(db):
    base = _row(str(uuid.uuid4()), str(uuid.uuid4()))
    for bad in ({**base, "fired": "yes"}, {**base, "language": ""},
                {**base, "measurements": []}):
        with pytest.raises(psycopg2.Error, match="INPUT_INVALID"):
            _record(db, [bad])


def test_a_verdict_never_changes_and_never_serves(db):
    snippet = str(uuid.uuid4())
    _record(db, [_row(str(uuid.uuid4()), snippet)])
    for assignment in ("fired = false", "serves_user = true"):
        with pytest.raises(psycopg2.Error):
            with db.cursor() as cur:
                cur.execute(f"UPDATE public.verbal_cue_shadow_observations "
                            f"SET {assignment} WHERE snippet_id = %s", (snippet,))
    with pytest.raises(psycopg2.Error, match="serves_user"):
        with db.cursor() as cur:
            cur.execute("INSERT INTO public.verbal_cue_shadow_observations "
                        "(take_session_id, snippet_id, error_id, detector_version, "
                        "language, fired, measurements, serves_user) VALUES "
                        "('t','s','hedging','v','en',true,'{}'::jsonb,true)")


def test_who_may_do_what(db):
    with db.cursor() as cur:
        for role in ("anon", "authenticated"):
            cur.execute("SELECT has_table_privilege(%s, "
                        "'public.verbal_cue_shadow_observations', 'SELECT')", (role,))
            assert cur.fetchone()[0] is False
            cur.execute("SELECT has_function_privilege(%s, "
                        "'public.record_verbal_cue_shadow_v1(jsonb)', 'EXECUTE')",
                        (role,))
            assert cur.fetchone()[0] is False
        for privilege, expected in (("SELECT", True), ("DELETE", True),
                                    ("INSERT", False), ("UPDATE", False)):
            cur.execute("SELECT has_table_privilege('service_role', "
                        "'public.verbal_cue_shadow_observations', %s)", (privilege,))
            assert cur.fetchone()[0] is expected, privilege
