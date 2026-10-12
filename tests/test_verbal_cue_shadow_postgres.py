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
