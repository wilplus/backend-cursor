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

import copy
import pathlib

import psycopg2
import psycopg2.errors
import psycopg2.extras
import pytest

from services import v4_picker as vp
from tests import test_a_take_draws_its_random_moments_postgres as draw_suite
from tests import test_each_pick_learns_if_the_paragraph_rose_postgres as outcome_suite
from tests import test_the_machine_reads_willfidence_postgres as read_suite
from tests import test_the_shadow_writer_accepts_the_frame_the_code_builds_postgres as base
from tests import test_the_v4_picker_runs_dark_beside_v3_postgres as pick_suite
from tests import test_v4_asks_coaches_two_blind_questions_postgres as sheet_suite

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


def test_no_map_on_the_earlier_take_writes_nothing(cur):
    _apply(cur)
    first, second = outcome_suite._two_takes(cur)
    outcome_suite._map(cur, second, P1)
    _read_both(cur, first, second)
    assert outcome_suite._compute(cur, second["take"]) == {"outcome": "no_map"}
    assert outcome_suite._outcomes(cur, first["take"]) == []


def test_no_map_on_the_later_take_writes_nothing(cur):
    _apply(cur)
    first, second = outcome_suite._two_takes(cur)
    outcome_suite._map(cur, first, P1)
    _read_both(cur, first, second)
    assert outcome_suite._compute(cur, second["take"]) == {"outcome": "no_map"}
    assert outcome_suite._outcomes(cur, first["take"]) == []


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


def test_a_mapped_moment_without_a_paragraph_still_falls_back_to_its_slide(cur):
    _apply(cur)
    first, second = outcome_suite._two_takes(cur)
    outcome_suite._map(cur, first, None)
    outcome_suite._map(cur, second, None)
    _read_both(cur, first, second)
    assert outcome_suite._compute(cur, second["take"])["outcome"] == "computed"
    assert {r["match_level"] for r in outcome_suite._outcomes(cur, first["take"])} == {"slide"}


# ── 2. a pick stores only what the read and the block hold ────────────────

def _picked_take(cur, **read_override):
    seed = outcome_suite._take(cur)
    read_suite._record(cur, seed["take"], read_suite._reads(seed["frame"], **read_override))
    cur.execute("SELECT id::text AS id, metrics, transcript FROM public.snippets "
                "WHERE session_id = %s", (seed["take"],))
    snippets = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT block_id, s, w, willfident, role FROM public.v4_willfidence_reads "
                "WHERE take_session_id = %s", (seed["take"],))
    reads = [{k: (float(v) if hasattr(v, "as_tuple") else v) for k, v in r.items()}
             for r in cur.fetchall()]
    return seed, vp.pick_take(seed["frame"], snippets, reads)


def _refused(cur, rows, take, match):
    with pytest.raises(psycopg2.errors.RaiseException, match=match):
        pick_suite._record(cur, take, rows)


def test_the_pickers_own_rows_still_store(cur):
    _apply(cur)
    seed, rows = _picked_take(cur)
    assert pick_suite._record(cur, seed["take"], rows) == {"outcome": "picked",
                                                           "blocks": len(rows)}


def test_a_willfident_the_read_does_not_have_is_refused(cur):
    """Before 0457, abs(payload - NULL) was NULL and the row passed."""
    _apply(cur)
    seed, rows = _picked_take(cur, filler=None, hedging=None, slide_fit=None,
                              holding_together=None)
    assert all(r["willfident"] is None for r in rows)
    rows = copy.deepcopy(rows)
    rows[0].update(willfident=0.5, gap=0.5)
    _refused(cur, rows, seed["take"], "V4_PICKS_NOT_ALLOWED")


def test_a_v3_clip_outside_the_block_is_refused(cur):
    _apply(cur)
    seed, rows = _picked_take(cur)
    rows = copy.deepcopy(rows)
    rows[0]["v3_snippet_id"] = "not-a-clip-of-this-block"
    if rows[0]["fallback"]:
        rows[0]["used_snippet_id"] = rows[0]["v3_snippet_id"]
    _refused(cur, rows, seed["take"], "V4_PICKS_NOT_ALLOWED")


def test_a_rank_position_that_is_not_whole_is_refused(cur):
    _apply(cur)
    seed, rows = _picked_take(cur)
    rows = copy.deepcopy(rows)
    ranked = next((r for r in rows if r["rank_position"] is not None), None)
    if ranked is None:
        pytest.skip("this seed ranks no block")
    ranked["rank_position"] = ranked["rank_position"] + 0.4
    _refused(cur, rows, seed["take"], "V4_PICKS_INVALID")


def test_a_rank_position_that_is_text_is_refused_as_invalid(cur):
    _apply(cur)
    seed, rows = _picked_take(cur)
    rows = copy.deepcopy(rows)
    rows[0]["rank_position"] = "one"
    _refused(cur, rows, seed["take"], "V4_PICKS_INVALID")


# ── 3. a sheet is answered once ───────────────────────────────────────────

def test_a_pick_sheet_is_answered_once_and_its_question_is_fixed(cur):
    _apply(cur)
    sheet = sheet_suite._pick(cur)
    cur.execute("SAVEPOINT s")
    with pytest.raises(psycopg2.errors.RaiseException, match="V4_SHEET_QUESTION_IS_FIXED"):
        cur.execute("UPDATE public.v4_moment_pick_sheets SET clip_ids = ARRAY['b', 'c'] "
                    "WHERE id = %s", (sheet["id"],))
    cur.execute("ROLLBACK TO SAVEPOINT s")
    # The app's own answer: once, while unanswered.
    cur.execute("UPDATE public.v4_moment_pick_sheets SET answer_snippet_id = 'a', "
                "answered_at = now() WHERE id = %s AND answered_at IS NULL RETURNING id",
                (sheet["id"],))
    assert cur.fetchone() is not None
    for change in ("answer_snippet_id = 'b'", "none_needs_it = true, answer_snippet_id = NULL",
                   "slice = 'random'", "answered_at = NULL, answer_snippet_id = NULL"):
        cur.execute("SAVEPOINT s")
        with pytest.raises(psycopg2.errors.RaiseException, match="V4_SHEET_ANSWERED_ONCE"):
            cur.execute(f"UPDATE public.v4_moment_pick_sheets SET {change} WHERE id = %s",
                        (sheet["id"],))
        cur.execute("ROLLBACK TO SAVEPOINT s")
    # The purge still deletes it.
    cur.execute("DELETE FROM public.v4_moment_pick_sheets WHERE id = %s RETURNING id",
                (sheet["id"],))
    assert cur.fetchone() is not None


def test_a_surer_sheet_is_answered_once_and_its_pair_is_fixed(cur):
    _apply(cur)
    sheet = sheet_suite._surer(cur)
    cur.execute("SAVEPOINT s")
    with pytest.raises(psycopg2.errors.RaiseException, match="V4_SHEET_QUESTION_IS_FIXED"):
        cur.execute("UPDATE public.v4_surer_sheets SET new_text = 'We grew a lot.' "
                    "WHERE id = %s", (sheet["id"],))
    cur.execute("ROLLBACK TO SAVEPOINT s")
    cur.execute("UPDATE public.v4_surer_sheets SET answer = 'yes', chosen_text = new_text, "
                "rejected_text = said_text, answered_at = now() "
                "WHERE id = %s AND answered_at IS NULL RETURNING id", (sheet["id"],))
    assert cur.fetchone() is not None
    cur.execute("SAVEPOINT s")
    with pytest.raises(psycopg2.errors.RaiseException, match="V4_SHEET_ANSWERED_ONCE"):
        cur.execute("UPDATE public.v4_surer_sheets SET answer = 'no', chosen_text = said_text, "
                    "rejected_text = new_text WHERE id = %s", (sheet["id"],))
    cur.execute("ROLLBACK TO SAVEPOINT s")
    cur.execute("DELETE FROM public.v4_surer_sheets WHERE id = %s RETURNING id", (sheet["id"],))
    assert cur.fetchone() is not None


# ── the door ──────────────────────────────────────────────────────────────

def test_the_door(cur):
    _apply(cur)
    for role in ("anon", "authenticated"):
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
        if cur.fetchone() is None:
            continue
        for fn in ("public.compute_v4_pick_outcomes_v1(uuid)",
                   "public.record_v4_picks_v1(uuid, jsonb)",
                   "public.reject_v4_pick_sheet_rewrite_v1()",
                   "public.reject_v4_surer_sheet_rewrite_v1()"):
            cur.execute("SELECT has_function_privilege(%s, %s, 'EXECUTE') AS p", (role, fn))
            assert cur.fetchone()["p"] is False, (role, fn)
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'service_role'")
    if cur.fetchone() is not None:
        for fn in ("public.compute_v4_pick_outcomes_v1(uuid)",
                   "public.record_v4_picks_v1(uuid, jsonb)"):
            cur.execute("SELECT has_function_privilege('service_role', %s, 'EXECUTE') AS p",
                        (fn,))
            assert cur.fetchone()["p"] is True, fn
