"""
STORY    As the founder, I want every Take since N86 to keep its dark frame
         and its whole V4 record, and every Take before it to keep the one
         it has, so that V4 is measured on every Take.
OUTCOME
  O1  A Take whose frame the code builds today is stored, drawn, mapped,
      read and picked, every row under that frame's policy.
  O2  A Take drawn before N86 and opened since keeps its first frame: its
      V4 rows, the database's rule and the app's read all name dark-v3,
      beside the dark-v4 frame now stored.
  O3  Take N from before N86 and Take N+1 after it meet: Take N's outcomes
      are computed from both Takes' reads, at the paragraph level.
  O4  A Take whose old detector reads were set aside gets its "recomputed"
      row from a dark-v4 frame.
PROVES   O1 -> test_a_take_since_n86_is_drawn_mapped_read_and_picked
         O2 -> test_take_n_before_n86_and_take_n_plus_1_after_it_meet
         O3 -> test_take_n_before_n86_and_take_n_plus_1_after_it_meet
         O4 -> test_an_old_detector_read_is_recomputed_by_a_dark_v4_frame
WHY      0489: #1207 (N86, 2026-10-20) moved the frame's labels with no
         migration, so no Take since kept its frame or anything after it.
         Released lane, which carries the V4 chain (0447 to 0457) and 0489;
         every write is rolled back.
"""
from __future__ import annotations

import decimal
import types
import uuid

import psycopg2.extras
import pytest

from services import v4_picker
from services.take_feedback_policy_v3 import DARK_POLICY_VERSIONS, POLICY_VERSION
from tests import (
    test_the_shadow_writer_accepts_the_frame_the_code_builds_postgres as base,
)

DSN = base.DSN
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

DARK_V3 = DARK_POLICY_VERSIONS[1]
V4_TABLES = ("v4_random_moments", "v4_moment_paragraphs", "v4_willfidence_reads",
             "v4_willfidence_takes", "v4_picks", "v4_pick_takes")
#: One Paragraph per slide, the same in both Takes, so Take N's outcomes are
#: read at the paragraph level.
PARAGRAPHS = {0: str(uuid.uuid4()), 1: str(uuid.uuid4())}


@pytest.fixture
def cur():
    yield from base.cur.__wrapped__()


def _call(cur, function, *args):
    cur.execute(f"SELECT public.{function}({', '.join(['%s'] * len(args))}) AS r", args)
    return cur.fetchone()["r"]


def _record(cur, take, frame, snippets):
    """The app's side once the frame is stored, in its order: the draw and
    the map (`_write_v3_shadow`), then the read and the picks
    (`willfidence.run_read`), each through its database function."""
    drawn = _call(cur, "draw_v4_random_moments_v1", take)
    mapped = _call(cur, "record_v4_moment_paragraphs_v1", take, psycopg2.extras.Json([
        {"block_id": b["block_id"], "paragraph_id": PARAGRAPHS[b["slide_index"]]}
        for b in frame["blocks"]]))
    read = _call(cur, "record_v4_willfidence_reads_v1", take, psycopg2.extras.Json([
        {"block_id": b["block_id"], "filler": 1, "hedging": 0.5, "slide_fit": 1,
         "holding_together": 1, "role": "main_point"} for b in frame["blocks"]]))
    cur.execute("SELECT block_id, s, w, willfident, role, sound_clips "
                "FROM public.v4_willfidence_reads WHERE take_session_id = %s", (take,))
    # Numbers as PostgREST hands them to the picker: JSON numbers.
    reads = [{k: float(v) if isinstance(v, decimal.Decimal) else v for k, v in r.items()}
             for r in cur.fetchall()]
    picked = _call(cur, "record_v4_picks_v1", take, psycopg2.extras.Json(
        v4_picker.pick_take(frame, snippets, reads)))
    return [drawn["outcome"], mapped["outcome"], read["outcome"], picked["outcome"]]


def _policies(cur, take):
    """The policies each V4 table holds for this Take."""
    found = set()
    for table in V4_TABLES:
        cur.execute(f"SELECT DISTINCT policy_version FROM public.{table} "
                    "WHERE take_session_id = %s", (take,))
        found |= {(table, r["policy_version"]) for r in cur.fetchall()}
    return found


def _stored_before_n86(cur, seed):
    """The Take's frame as 0441 stored it before N86: dark-v3, frame-v6."""
    frame = {**seed["frame"], "policy_version": DARK_V3,
             "frame_schema_version": "take-feedback-policy-v3-frame-v6",
             "pick_log": {**seed["frame"]["pick_log"], "policy_version": DARK_V3},
             "frame_hash": "3" * 64}
    cur.execute(
        "INSERT INTO public.take_feedback_policy_v3_shadow_frames (take_session_id, "
        "recording_id, policy_version, arc_id, acquisition_principal_id, owner_user_id, "
        "take_index, frame, frame_hash) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (seed["take"], seed["recording"], DARK_V3, seed["arc_id"], seed["principal"],
         seed["user_id"], seed["take_index"], psycopg2.extras.Json(frame),
         frame["frame_hash"]))
    return frame


class _Rows:
    """The slice of the PostgREST builder `get_v4_dark_frame` uses, as SQL
    in the test's own transaction."""

    def __init__(self, cur, table):
        self.cur, self.table, self.where, self.args, self.cap = cur, table, [], [], None

    def select(self, _columns):
        return self

    def eq(self, column, value):
        self.where.append(f"{column}::text = %s")
        self.args.append(str(value))
        return self

    def in_(self, column, values):
        self.where.append(f"{column}::text = ANY(%s)")
        self.args.append([str(v) for v in values])
        return self

    def limit(self, count):
        self.cap = int(count)
        return self

    def execute(self):
        query = f"SELECT * FROM public.{self.table} WHERE " + " AND ".join(self.where)
        self.cur.execute(query + (f" LIMIT {self.cap}" if self.cap else ""), self.args)
        return types.SimpleNamespace(data=[dict(r) for r in self.cur.fetchall()])


def _app(cur):
    """The real DatabaseService, its client answered by `_Rows`."""
    from services.db import DatabaseService
    service = DatabaseService.__new__(DatabaseService)
    service.client = types.SimpleNamespace(table=lambda name: _Rows(cur, name))
    return service


def test_a_take_since_n86_is_drawn_mapped_read_and_picked(cur):
    seed = base._seed_take(cur)
    assert base._write(cur, seed, seed["frame"])["outcome"] == "stored"
    assert _record(cur, seed["take"], seed["frame"], seed["snippets"]) == [
        "drawn", "mapped", "read", "picked"]
    assert _policies(cur, seed["take"]) == {(t, POLICY_VERSION) for t in V4_TABLES}
    assert _app(cur).get_v4_dark_frame(seed["take"]) == seed["frame"]


def test_take_n_before_n86_and_take_n_plus_1_after_it_meet(cur):
    before = base._seed_take(cur)
    old = _stored_before_n86(cur, before)
    assert _record(cur, before["take"], old, before["snippets"]) == [
        "drawn", "mapped", "read", "picked"]
    # Opened again since N86: the writer stores today's frame beside it, and
    # the Take keeps the frame its draw was made from.
    assert base._write(cur, before, before["frame"])["outcome"] == "stored"
    assert _call(cur, "draw_v4_random_moments_v1", before["take"])["outcome"] == "stored"
    assert _call(cur, "v4_frame_policy_v1", before["take"]) == DARK_V3
    assert _app(cur).get_v4_dark_frame(before["take"]) == old
    assert _policies(cur, before["take"]) == {(t, DARK_V3) for t in V4_TABLES}

    after = base._seed_take(cur, take_index=3, after=before)
    assert base._write(cur, after, after["frame"])["outcome"] == "stored"
    assert _record(cur, after["take"], after["frame"], after["snippets"]) == [
        "drawn", "mapped", "read", "picked"]
    outcome = _call(cur, "compute_v4_pick_outcomes_v1", after["take"])
    assert outcome["outcome"] == "computed", outcome
    assert outcome["moments"] == len(old["blocks"])
    cur.execute("SELECT DISTINCT policy_version, next_take_session_id::text AS next, "
                "match_level FROM public.v4_pick_outcomes WHERE take_session_id = %s",
                (before["take"],))
    assert [dict(r) for r in cur.fetchall()] == [
        {"policy_version": DARK_V3, "next": after["take"], "match_level": "paragraph"}]


def test_an_old_detector_read_is_recomputed_by_a_dark_v4_frame(cur):
    seed = base._seed_take(cur)
    candidate = next(c for b in seed["frame"]["blocks"] for c in b["confidence_candidates"]
                     if c["eligibility"] == "eligible")
    clip = candidate["clip_identity"]
    cur.execute(
        "INSERT INTO public.take_feedback_detector_reconciliation (take_session_id, "
        "recording_id, snippet_id, candidate_id, start_offset_ms, duration_ms, "
        "clip_identity_sha256, old_policy_version, old_detector_version, outcome, "
        "evidence_sha256) VALUES (%s, %s, %s, %s, %s, %s, %s, "
        "'take-feedback-policy-v3-dark-v2', 'voice-confidence-v2', "
        "'incompatible_detector_version', %s)",
        (seed["take"], seed["recording"], candidate["snippet_id"], candidate["candidate_id"],
         clip["start_offset_ms"], clip["duration_ms"], clip["clip_identity_sha256"], "0" * 64))
    assert base._write(cur, seed, seed["frame"])["outcome"] == "stored"
    cur.execute("SELECT replacement_policy_version FROM "
                "public.take_feedback_detector_reconciliation "
                "WHERE take_session_id = %s AND outcome = 'recomputed'", (seed["take"],))
    assert [r["replacement_policy_version"] for r in cur.fetchall()] == [POLICY_VERSION]
