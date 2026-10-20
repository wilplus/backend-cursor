"""
STORY    As a coach, I want the pick and "surer" sheets to show me only clips
         and words, so that I answer without the machine's guess.
OUTCOME
  O1  The pick sheet shows only the clip, a letter, the words and the audio
      timing, never the machine's ids, sureness or choice.
  O2  The "surer" sheet shows only the two wordings, never the slice,
      level, bar or the quality being varied.
  O3  A Take with two feedback versions still fills the sheets, each moment
      asked once, and a moment the database refuses is skipped, not an
      error.
PROVES   O1 -> test_the_sheet_payload_is_blind
         O2 -> test_the_pair_payload_is_blind
         O3 -> test_a_take_with_two_frames_still_fills_the_pick_sheets
WHY      Never-rule 2: coach judgements stay blind.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timezone

import pytest

from services import v4_coach_sheets as cs

NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def on(monkeypatch):
    monkeypatch.setattr(cs, "rater_role", lambda uid: "founder" if uid == "founder" else "coach")
    # 3.5 E4: every speaker here holds the training yes; the gate itself is
    # pinned in tests/test_learning_lanes_honour_3_5.py.
    monkeypatch.setattr(cs.pair_consent, "take_may_reach_a_coach_sheet", lambda db, take: True)


class _Db:
    def __init__(self):
        self.sheets, self.surer = [], []

    def list_v4_pick_sheets(self, rater):
        return [s for s in self.sheets if s["rater_id"] == rater]

    def list_takes_coach_is_walking(self, rater):
        return []

    def list_recent_v3_frames(self, limit=200):
        return [{"take_session_id": "t", "frame": {"blocks": [
            {"block_id": f"b{i}", "snippet_ids": [f"c{i}a", f"c{i}b"]} for i in range(15)]}}]

    def list_v4_picks(self, take):
        return [{"block_id": f"b{i}", "sureness": i / 20, "v4_snippet_id": f"c{i}a",
                 "v3_snippet_id": f"c{i}b"} for i in range(15)]

    def insert_v4_pick_sheet(self, row):
        row = {**row, "id": f"s{len(self.sheets)}"}
        self.sheets.append(row)
        return row

    def list_coach_clip_exposures(self, *a, **k):
        return []

    def record_coach_clip_exposure(self, *a, **k):
        return True

    def get_v4_pick_sheet(self, sheet_id, rater):
        return next((s for s in self.sheets if s["id"] == sheet_id and s["rater_id"] == rater), None)

    def answer_v4_pick_sheet(self, sheet_id, rater, clip, none):
        row = self.get_v4_pick_sheet(sheet_id, rater)
        row.update(answer_snippet_id=clip, none_needs_it=True if none else None, answered_at="x")
        return row

    def get_snippet_by_id(self, clip):
        return {"transcript": f"words of {clip}", "audio_segment_path": None}


def test_the_sheet_payload_is_blind():
    db = _Db()
    cs.fill_pick_sheets(db, rater_id="c1", week="w", rng=random.Random(3), now=NOW)
    status, body = cs.pick_queue(db, rater_id="c1")
    assert status == 200
    text = json.dumps(body)
    for leak in ("v4_snippet_id", "v3_snippet_id", "slice", "sureness", "unsure", "repick"):
        assert leak not in text
    assert set(body["items"][0]["moments"][0]) == {"clip_id", "letter", "words", "audio_ref",
                                                       "start_offset_ms", "duration_ms"}



def test_a_take_with_two_frames_still_fills_the_pick_sheets():
    """A Take has one frame per policy version and they share block ids.
    Each block is asked once (v4_moment_pick_sheets_once), and a block the
    database refuses is skipped, not a 500."""
    db = _Db()
    frames = db.list_recent_v3_frames()
    db.list_recent_v3_frames = lambda limit=200: frames + frames
    insert = db.insert_v4_pick_sheet

    def once(row):
        if any(s["block_id"] == row["block_id"] for s in db.sheets):
            raise RuntimeError("duplicate key value violates v4_moment_pick_sheets_once")
        if row["block_id"] == "b0":
            raise RuntimeError("the database refused this one")
        return insert(row)
    db.insert_v4_pick_sheet = once
    written = cs.fill_pick_sheets(db, rater_id="c1", week="w", rng=random.Random(3), now=NOW)
    ids = [w["block_id"] for w in written]
    assert written and len(ids) == len(set(ids)) and "b0" not in ids

def test_the_pair_payload_is_blind():
    """Post-merge review of 0453: the rows are read whole (select *), and the
    payload is built field by field, so a pair's slice, level, bar and the
    quality it varies never reach the coach (BLIND COACH, AC-9)."""
    class Db:
        def list_v4_surer_sheets(self, rater):
            return [{"id": "s1", "rater_id": rater, "rater_role": "coach",
                     "take_session_id": "t", "block_id": "b",
                     "said_text": "I think we grew.", "new_text": "We grew.",
                     "varied_quality": "hedging", "version_rule": "surer-pair-v1-lexical",
                     "slice": "above", "level": 0.71, "bar": 0.6,
                     "bar_version": "reached-bar-v0-placeholder", "week": "w",
                     "answer": None, "answered_at": None}]
    status, body = cs.surer_queue(Db(), rater_id="c1")
    assert status == 200
    assert [set(item) for item in body["items"]] == [{"sheet_id", "said", "new", "n", "of"}]
    text = json.dumps(body["items"])
    for leak in ("above", "0.71", "0.6", "hedging", "slice", "level", "bar", "reached-bar"):
        assert leak not in text, leak
