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
import uuid
from decimal import Decimal

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
