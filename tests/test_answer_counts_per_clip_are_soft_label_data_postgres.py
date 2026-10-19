"""
STORY    As the founder, I want each clip's answer counts built only from blind
         human answers, never the machine's guess, so that soft labels for
         training reflect real listeners.
OUTCOME
  O1  Never-2: the machine's guess stored beside an answer is never counted;
      only the human answer is.
  O2  Only the coach and game_peer lanes count; a self-report, the
      game_owner and bootstrap lanes and an Audio-unclear abstention do not.
      In-between counts half in the soft label.
  O3  A non-blind rating is not counted; the old 'neutral' counts as Not sure,
      which takes no share of the soft label.
PROVES   O1 -> test_only_blind_human_lanes_count_and_the_machine_guess_never_does
         O2 -> test_only_blind_human_lanes_count_and_the_machine_guess_never_does
         O3 -> test_a_non_blind_row_is_not_counted_and_neutral_is_not_sure
WHY      0442 (V4 brief 1.7, Q3): the soft label is human-only, like the quorum.
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


def _label(cur, snippet_id, *, value, lane="coach", self_report=False,
           unrateable=False, machine_value=None, blind=True):
    cur.execute(
        "INSERT INTO public.confidence_labels (snippet_id, rater_id, source, "
        "confident, state_id, value, lane, self_report, unrateable, machine_value, "
        "blind) "
        "VALUES (%s, %s, %s, %s, 'confidence', %s, %s, %s, %s, %s, %s)",
        (snippet_id, str(uuid.uuid4()),
         "coach" if lane in ("coach", "bootstrap") else "game",
         True if value == "yes" else False if value == "no" else None,
         value, lane, self_report, unrateable, machine_value, blind))


def _counts(cur, snippet_id) -> tuple:
    cur.execute("SELECT * FROM public.refresh_clip_answer_counts_v1(%s)", (snippet_id,))
    row = cur.fetchone()
    return (row["yes_count"], row["in_between_count"], row["no_count"],
            row["not_sure_count"], row["perceptual_count"], row["soft_label"])


def test_only_blind_human_lanes_count_and_the_machine_guess_never_does(db):
    snippet = str(uuid.uuid4())
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # Counted: each human answer differs from the machine's guess beside
        # it, so a count that read the guess would come out different.
        _label(cur, snippet, value="yes", lane="coach", machine_value="no")
        _label(cur, snippet, value="in_between", lane="game_peer", machine_value="yes")
        _label(cur, snippet, value="no", lane="coach", machine_value="yes")
        # Not counted: the speaker on their own clip, the owner and bootstrap
        # lanes, an Audio-unclear abstention.
        _label(cur, snippet, value="yes", lane="game_peer", self_report=True)
        _label(cur, snippet, value="yes", lane="game_owner")
        _label(cur, snippet, value="yes", lane="bootstrap")
        _label(cur, snippet, value="audio_unclear", lane="coach", unrateable=True,
               machine_value="yes")
        counts = _counts(cur, snippet)
    # Yes 1, In-between 1/2, No 0 over three answers.
    assert counts == (1, 1, 1, 0, 3, Decimal("0.50000"))


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
        counts = _counts(cur, snippet)
    assert counts == (1, 0, 0, 1, 1, Decimal("1.00000"))
