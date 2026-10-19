"""
STORY    As a speaker, I want the silent spoken-word cue log never to reach me
         or a dataset, so that untested detectors do not affect my feedback.
OUTCOME
  O1  A known cue's verdict is logged once per (clip, cue, version); a retry
      writes nothing new.
  O2  A logged verdict can never be changed, and no verdict can be marked as
      serving a user.
  O3  A cue the library does not measure is never logged.
PROVES   O1 -> test_a_known_cue_is_logged_once
         O2 -> test_a_verdict_never_changes_and_never_serves
         O3 -> test_an_unknown_cue_is_refused
WHY      Founder 2026-09-28, D2 + D3 (migration 0386, the shadow stage).
"""
from __future__ import annotations

import os
import uuid

import psycopg2
import psycopg2.errors
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


def test_a_known_cue_is_logged_once(db):
    row = _row(str(uuid.uuid4()), str(uuid.uuid4()))
    assert _record(db, [row]) == 1
    assert _record(db, [row]) == 0
    assert _scalar(db, "SELECT count(*) FROM public.verbal_cue_shadow_observations "
                       "WHERE snippet_id = %s", (row["snippet_id"],)) == 1


def test_a_verdict_never_changes_and_never_serves(db):
    snippet = str(uuid.uuid4())
    assert _record(db, [_row(str(uuid.uuid4()), snippet)]) == 1
    for assignment in ("fired = false", "serves_user = true"):
        with pytest.raises(psycopg2.Error, match="VERBAL_CUE_SHADOW_IMMUTABLE"):
            with db.cursor() as cur:
                cur.execute(f"UPDATE public.verbal_cue_shadow_observations "
                            f"SET {assignment} WHERE snippet_id = %s", (snippet,))
    with pytest.raises(psycopg2.errors.CheckViolation, match="serves_user"):
        with db.cursor() as cur:
            cur.execute("INSERT INTO public.verbal_cue_shadow_observations "
                        "(take_session_id, snippet_id, error_id, detector_version, "
                        "language, fired, measurements, serves_user) VALUES "
                        "('t','s','hedging','v','en',true,'{}'::jsonb,true)")


def test_an_unknown_cue_is_refused(db):
    snippet = str(uuid.uuid4())
    with pytest.raises(psycopg2.Error, match="VERBAL_CUE_SHADOW_CUE_NOT_MEASURED"):
        _record(db, [_row(str(uuid.uuid4()), snippet, cue="not_a_library_cue")])
    assert _scalar(db, "SELECT count(*) FROM public.verbal_cue_shadow_observations "
                       "WHERE snippet_id = %s", (snippet,)) == 0
