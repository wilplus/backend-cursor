"""0441: the shadow writer keeps the pick log (V4 B1.1, build plan D-ML-6).

Runs against the disposable confident-moment rehearsal cluster only. The
Take, the frame and the writer call are the 0431 suite's own, so the two
suites can never drift apart.
"""
from __future__ import annotations

import pytest

from services.take_feedback_policy_v3 import PICK_LOG_VERSION
from tests import (
    test_the_shadow_writer_accepts_the_frame_the_code_builds_postgres as base,
)

DSN = base.DSN
_migration_body = base._migration_body
_seed_take = base._seed_take
_write = base._write

pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)


@pytest.fixture
def cur():
    yield from base.cur.__wrapped__()


def _fresh(cur):
    cur.execute(_migration_body())
    return _seed_take(cur)


def test_a_frame_with_its_pick_log_is_stored(cur):
    seed = _fresh(cur)
    assert seed["frame"]["pick_log"]["version"] == PICK_LOG_VERSION
    assert _write(cur, seed, seed["frame"])["outcome"] == "stored"
    cur.execute("SELECT frame -> 'pick_log' AS log FROM "
                "public.take_feedback_policy_v3_shadow_frames "
                "WHERE take_session_id = %s", (seed["take"],))
    assert cur.fetchone()["log"] == seed["frame"]["pick_log"]
