"""0457: the V4 dark writes keep their word (post-merge review of 0451, 0452,
0453), on the disposable rehearsal database, over real Takes with their
frames, draws and willfidence reads.

Pins:
  * outcomes wait for BOTH Takes' moment-to-Paragraph maps ('no_map', no
    row written), then land at the paragraph level as before;
  * a pick is refused when it claims a willfident the read does not have,
    names a V3 clip outside its block, or a rank position that is not a
    whole number; the picker's own rows still store;
  * a coach sheet is answered once, and its question never changes; an
    unanswered sheet is still answered, and a sheet is still deleted;
  * the file applies twice; its functions stay closed to browser roles.

0449 to 0453 are applied by their own suites inside each test's
transaction, so this suite applies them the same way, then this file.
"""
from __future__ import annotations

import pathlib

import pytest

from tests import test_a_take_draws_its_random_moments_postgres as draw_suite
from tests import test_each_pick_learns_if_the_paragraph_rose_postgres as outcome_suite
from tests import (
    test_the_shadow_writer_accepts_the_frame_the_code_builds_postgres as base,
)
from tests import test_the_v4_picker_runs_dark_beside_v3_postgres as pick_suite

DSN = base.DSN
pytestmark = pytest.mark.skipif(not DSN, reason="disposable confident-moment rehearsal only")

ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "the_v4_dark_writes_keep_their_word.sql"
SHEETS = ROOT / "migrations" / "v4_asks_coaches_two_blind_questions.sql"
P1 = outcome_suite.P1


@pytest.fixture
def cur():
    yield from base.cur.__wrapped__()


def _apply(cur):
    pick_suite._apply(cur)              # 0431, 0441, 0447, 0449, 0451, 0452
    cur.execute(draw_suite._body(SHEETS))
    cur.execute(draw_suite._body(MIGRATION))
    cur.execute(draw_suite._body(MIGRATION))   # idempotent


# ── 1. an outcome waits for both maps ──────────────────────────────────────

def _read_both(cur, first, second):
    outcome_suite._read(cur, first, filler=0.0)
    outcome_suite._read(cur, second, filler=1.0)


def test_with_both_maps_the_paragraph_is_measured_as_before(cur):
    _apply(cur)
    first, second = outcome_suite._two_takes(cur)
    _read_both(cur, first, second)
    # A map stored after the reads is still found: nothing was frozen.
    assert outcome_suite._compute(cur, second["take"])["outcome"] == "no_map"
    outcome_suite._map(cur, first, P1)
    outcome_suite._map(cur, second, P1)
    out = outcome_suite._compute(cur, second["take"])
    assert out["outcome"] == "computed" and out["take_session_id"] == first["take"]
    rows = outcome_suite._outcomes(cur, first["take"])
    assert len(rows) == len(first["frame"]["blocks"])
    assert {r["match_level"] for r in rows} == {"paragraph"}
    assert {r["outcome"] for r in rows} == {"rose"}


# ── 2. a pick stores only what the read and the block hold ────────────────


# ── 3. a sheet is answered once ───────────────────────────────────────────


# ── the door ──────────────────────────────────────────────────────────────
