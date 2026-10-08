"""V4 B1.8/B1.9: the two blind coach sheets (build plan D-ML-13; founder
S-B8 A, QG4 B, QG9 A, QB7 B, QB8 A, V18 A, V19 A, V20 A)."""
from __future__ import annotations

import json
import pathlib
import random
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest

from services import v4_coach_sheets as cs

ROOT = pathlib.Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def on(monkeypatch):
    from config import Config
    monkeypatch.setattr(Config, "V4_COACH_SHEETS_ENABLED", True, raising=False)
    monkeypatch.setattr(cs, "rater_role", lambda uid: "founder" if uid == "founder" else "coach")


def test_the_switch_is_on_by_default_and_every_door_404s_when_off(monkeypatch):
    from config import Config
    # ON since 2026-10-08 (founder: "turn it all ON"); still a code constant.
    src = (ROOT / "config.py").read_text()
    assert "    V4_COACH_SHEETS_ENABLED = True\n" in src
    assert 'getenv("V4_COACH_SHEETS_ENABLED")' not in src
    assert Config.V4_COACH_SHEETS_ENABLED is True
    monkeypatch.setattr(Config, "V4_COACH_SHEETS_ENABLED", False)
    assert cs.pick_queue(None, rater_id="c")[0] == 404
    assert cs.surer_answer(None, rater_id="c", sheet_id="s", body={})[0] == 404
    assert cs.fill_pick_sheets(None, rater_id="c", week="w") == []


def test_the_sheet_holds_v4s_and_v3s_moments_among_three():
    block = {"snippet_ids": ["a", "b", "c", "d", "e"]}
    for seed in range(20):
        chosen = cs.sheet_clips(block, "d", "e", rng=random.Random(seed))
        assert len(chosen) == 3 and {"d", "e"} <= set(chosen)


def test_least_sure_blocks_come_first():
    frames = [{"take_session_id": "t", "frame": {"blocks": [
        {"block_id": "b1", "snippet_ids": ["a", "b"]},
        {"block_id": "b2", "snippet_ids": ["c", "d"]},
        {"block_id": "b3", "snippet_ids": ["e"]}]}}]
    picks = {"t": [{"block_id": "b1", "sureness": 0.9}, {"block_id": "b2", "sureness": 0.1},
                   {"block_id": "b3", "sureness": 0.0}]}
    assert [c["block"]["block_id"] for c in cs.candidate_blocks(frames, picks)] == ["b2", "b1"]


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


def test_a_week_is_ten_blocks_and_never_more(monkeypatch):
    db = _Db()
    written = cs.fill_pick_sheets(db, rater_id="c1", week="2026-W41", rng=random.Random(1), now=NOW)
    assert len(written) == cs.WEEKLY_CAP
    assert cs.fill_pick_sheets(db, rater_id="c1", week="2026-W41", rng=random.Random(2), now=NOW) == []
    slices = Counter(s["slice"] for s in written)
    assert set(slices) <= {"unsure", "random"} and slices["unsure"] >= 4


def test_a_coach_is_asked_an_old_block_again_unmarked(monkeypatch):
    db = _Db()
    old = {"id": "old", "rater_id": "c1", "take_session_id": "t", "block_id": "b9",
           "clip_ids": ["c9a", "c9b"], "slice": "unsure", "week": "2026-W39",
           "answered_at": (NOW - timedelta(days=16)).isoformat(),
           "v4_snippet_id": "c9a", "v3_snippet_id": "c9b"}
    db.sheets.append(old)
    seen = 0
    for seed in range(40):
        db.sheets = [old]
        written = cs.fill_pick_sheets(db, rater_id="c1", week="2026-W41", rng=random.Random(seed), now=NOW)
        seen += sum(1 for w in written if w["slice"] == "repick" and w["repick_of"] == "old")
    assert 0 < seen < 40
    db.sheets = [{**old, "rater_id": "founder"}]
    written = cs.fill_pick_sheets(db, rater_id="founder", week="2026-W41", rng=random.Random(0), now=NOW)
    assert not any(w["slice"] == "repick" for w in written)


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


def test_one_answer_once_and_only_from_the_sheet():
    db = _Db()
    cs.fill_pick_sheets(db, rater_id="c1", week="w", rng=random.Random(3), now=NOW)
    sheet = db.sheets[0]
    assert cs.pick_answer(db, rater_id="c1", sheet_id=sheet["id"], body={"clip_id": "nope"})[0] == 400
    assert cs.pick_answer(db, rater_id="c1", sheet_id=sheet["id"], body={})[0] == 400
    assert cs.pick_answer(db, rater_id="c2", sheet_id=sheet["id"], body={"none_needs_it": True})[0] == 404
    assert cs.pick_answer(db, rater_id="c1", sheet_id=sheet["id"], body={"none_needs_it": True})[0] == 200
    assert cs.pick_answer(db, rater_id="c1", sheet_id=sheet["id"], body={"none_needs_it": True})[0] == 409


def test_golden_agreement_is_against_the_founder_and_none_counts():
    rows = [
        {"take_session_id": "t", "block_id": "b1", "rater_role": "founder", "answered_at": "x",
         "answer_snippet_id": "a", "v4_snippet_id": "a", "v3_snippet_id": "b"},
        {"take_session_id": "t", "block_id": "b2", "rater_role": "founder", "answered_at": "x",
         "none_needs_it": True, "v4_snippet_id": None, "v3_snippet_id": "c"},
        {"take_session_id": "t", "block_id": "b1", "rater_role": "coach", "answered_at": "x",
         "answer_snippet_id": "b", "v4_snippet_id": "a", "v3_snippet_id": "b"},
        {"take_session_id": "t", "block_id": "b2", "rater_role": "coach", "answered_at": "x",
         "none_needs_it": True, "v4_snippet_id": None, "v3_snippet_id": "c"},
    ]
    assert cs.golden_agreement(rows) == {"golden_blocks": 2, "v4_agreement": 1.0,
                                         "v3_agreement": 0.0, "coach_agreement": 0.5}


@pytest.mark.parametrize("said,quality,new", [
    ("I think maybe we could start the pilot in March.", "hedging", "We could start the pilot in March."),
    ("Um, we basically grew forty percent.", "filler", "We grew forty percent."),
    ("We grew forty percent.", "hedging", None),
])
def test_the_machine_version_takes_one_quality_out(said, quality, new):
    assert cs.machine_version(said, quality) == new


def test_the_slices_are_forty_forty_twenty_against_the_bar():
    rng = random.Random(5)
    draws = Counter(cs.slice_of(0.9, 0.6, rng) for _ in range(5000))
    assert draws["below"] == 0
    assert 0.75 < draws["above"] / 5000 < 0.85  # above + below both land above here
    draws = Counter(cs.slice_of(0.2, 0.6, rng) for _ in range(5000))
    assert 0.15 < draws["random"] / 5000 < 0.25 and draws["above"] == 0


def test_the_quality_least_answered_goes_first():
    assert cs.least_sure_quality(Counter({"filler": 5, "hedging": 2}))[0] == "hedging"


def test_a_surer_answer_makes_its_pair():
    class Db:
        row = {"id": "s", "said_text": "a", "new_text": "b"}

        def get_v4_surer_sheet(self, sid, rater):
            return dict(self.row)

        def answer_v4_surer_sheet(self, sid, rater, answer, chosen, rejected):
            self.saved = (answer, chosen, rejected)
            return {"id": sid}
    db = Db()
    assert cs.surer_answer(db, rater_id="c", sheet_id="s", body={"answer": "yes"})[0] == 200
    assert db.saved == ("yes", "b", "a")
    cs.surer_answer(db, rater_id="c", sheet_id="s", body={"answer": "cant_tell"})
    assert db.saved == ("cant_tell", None, None)
    assert cs.surer_answer(db, rater_id="c", sheet_id="s", body={"answer": "maybe"})[0] == 400


def test_the_signed_words():
    assert cs.WORDING["pick"]["none"] == "None needs it"
    assert cs.WORDING["surer"]["question"] == "Is the new version surer?"
    assert {k: cs.WORDING["surer"][k] for k in ("yes", "no", "cant_tell")} == {"yes": "Yes", "no": "No", "cant_tell": "Can't tell"}
    assert cs.WORDING["pick"]["queue_line"] == cs.WORDING["surer"]["queue_line"] == "Also waiting · blind"


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
