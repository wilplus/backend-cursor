"""
STORY    As the founder, I want the coach panel's blind learning lanes (the
         error audit and the block pick) to stay blind, answered once, and
         only about speakers who said yes, so that learning never leaks into
         what coaches see or reaches a speaker who did not agree.
OUTCOME
  O1  An audit item takes one answer, once: a second answer is 409, a value
      outside yes/no/cant_tell is 400.
  O2  The coach's sheets are blind (Never rule 2: no coach sees the
      machine's guess before answering): an audit item carries the clip and
      the error's own question, never whether the detector fired, its
      measurements or version; a block-pick sheet carries audio clips,
      never the Manager's pick or the words.
  O3  A Take whose speaker does not hold the training yes is never put on a
      block-pick sheet: nothing is written.
  O4  A block pick the database refuses (written by another writer first)
      is skipped and the rest are still written.
PROVES   O1 -> test_an_audit_item_takes_one_answer_once
         O2 -> test_the_coach_sheets_are_blind
         O3 -> test_no_training_yes_writes_no_block_pick
         O4 -> test_a_refused_block_pick_is_skipped_and_the_rest_are_written
WHY      Founder 2026-10-01 (F6, C5-b). O4: a Take has one frame per policy
         version sharing block ids, and an insert refused by
         coach_block_pick_once (a 500) emptied the coach's queue.
"""
from __future__ import annotations

import importlib
import json
import random
import re
import sys

import pytest

from services import coach_block_pick as bp
from services import error_presence_audit as epa

BLOCK = {"block_id": "b1", "selected_candidate_id": "cand-2", "confidence_candidates": [
    {"candidate_id": "cand-1", "snippet_id": "s1", "eligibility": "eligible"},
    {"candidate_id": "cand-2", "snippet_id": "s2", "eligibility": "eligible"},
    {"candidate_id": "cand-3", "snippet_id": "s3", "eligibility": "eligible"},
    {"candidate_id": "cand-4", "snippet_id": "s4", "eligibility": "excluded"}]}
ONE = {"block_id": "b2", "selected_candidate_id": "cand-9", "confidence_candidates": [
    {"candidate_id": "cand-9", "snippet_id": "s9", "eligibility": "eligible"}]}
WORDS = "the words spoken here"


class _Db:
    """The rows the two lanes read and write, in memory."""

    def __init__(self):
        self.exposures: set = set()
        self.audits: list = []
        self.picks: list = []

    def record_coach_clip_exposure(self, **kwargs):
        key = (kwargs["coach_id"], kwargs["clip_id"])
        fresh = key not in self.exposures
        self.exposures.add(key)
        return fresh

    def list_coach_clip_exposures(self, coach_id, clip_ids):
        return [{"clip_id": c} for c in clip_ids if (coach_id, c) in self.exposures]

    def count_coach_blind_answers(self, coach_id, week):
        return 0

    def blind_line_cleared(self, line, owner_id, week):
        return False

    def get_snippet_by_id(self, sid):
        return {"id": sid, "audio_segment_path": f"s/{sid}.webm", "transcript": WORDS}

    # the error audit
    def list_speaking_errors(self):
        return [{"error_id": "rushing", "label": "Rushing", "asks": "Do you hear rushing here?"}]

    def list_error_presence_audit_pending(self, coach_id):
        return [a for a in self.audits if a["coach_id"] == coach_id and not a.get("answer")]

    def list_error_presence_audit_by_coach(self, coach_id):
        return [a for a in self.audits if a["coach_id"] == coach_id]

    def list_audit_candidates(self, errors):
        return [{"clip_id": f"c{i}", "error_id": "rushing", "fired": i % 2 == 0,
                 "speaker_user_id": f"s{i % 5}", "take_session_id": f"t{i}",
                 "detector_version": "rules-v1", "measurements": {"wpm": 100 + i},
                 "answered_count": 0} for i in range(12)]

    def insert_error_presence_audit(self, row):
        self.audits.append({"id": f"aud-{len(self.audits) + 1}", "answer": None, **row})
        return self.audits[-1]

    def answer_error_presence_audit(self, *, audit_id, coach_id, answer):
        row = next((a for a in self.audits
                    if a["id"] == audit_id and a["coach_id"] == coach_id), None)
        if not row or row.get("answer"):
            return None
        row["answer"] = answer
        return row

    # the block pick
    def list_coach_block_picks_pending(self, coach_id):
        return [p for p in self.picks if p["coach_id"] == coach_id and not p.get("answered_at")]

    def list_coach_block_picks_by_coach(self, coach_id):
        return [p for p in self.picks if p["coach_id"] == coach_id]

    def list_takes_coach_is_walking(self, coach_id):
        return ["take-walking"]

    def list_recent_v3_frames(self, limit=200):
        return [{"take_session_id": "take-walking", "policy_version": "v3",
                 "frame": {"blocks": [BLOCK]}},
                {"take_session_id": "take-2", "policy_version": "v3",
                 "frame": {"blocks": [BLOCK, ONE]}}]

    def insert_coach_block_pick(self, row):
        self.picks.append({"id": f"pick-{len(self.picks) + 1}", "answered_at": None, **row})
        return self.picks[-1]


@pytest.fixture
def consented(monkeypatch):
    """Every speaker may be asked about: practice on, on the current notice,
    no objection, the training yes held. Each test narrows what it needs."""
    # Patched where the lanes look them up at call time (sys.modules, and
    # coach_block_pick's own pair_consent), so a module another test
    # re-imported cannot slip the real read back in.
    importlib.import_module("services.verbal_cues")
    importlib.import_module("services.snippet_audio_url")
    monkeypatch.setattr(sys.modules["services.verbal_cues"], "_practice_permitted",
                        lambda db, take: True)
    monkeypatch.setattr(epa, "_on_notice_version", lambda db, take: True)
    monkeypatch.setattr(epa, "_objected", lambda db, take: False)
    monkeypatch.setattr(bp.pair_consent, "take_may_reach_a_coach_sheet",
                        lambda db, take: True)
    monkeypatch.setattr(sys.modules["services.snippet_audio_url"], "resolve_snippet_audio_url",
                        lambda row, database=None: f"https://audio.invalid/{row['id']}")


def test_an_audit_item_takes_one_answer_once(consented):
    db = _Db()
    epa.sample_for_coach(db, coach_id="c", rng=random.Random(1))
    audit_id = db.audits[0]["id"]
    assert epa.answer(db, coach_id="c", audit_id=audit_id,
                      body={"answer": "yes"}) == (200, {"recorded": True})
    assert epa.answer(db, coach_id="c", audit_id=audit_id, body={"answer": "no"})[0] == 409
    assert epa.answer(db, coach_id="c", audit_id=db.audits[1]["id"],
                      body={"answer": "maybe"})[0] == 400
    assert [a["answer"] for a in db.audits[:2]] == ["yes", None]


def test_the_coach_sheets_are_blind(consented):
    db = _Db()
    epa.sample_for_coach(db, coach_id="c", rng=random.Random(1))
    status, sheet = epa.queue(db, coach_id="c")
    assert status == 200 and sheet["items"]
    for item in sheet["items"]:
        assert item["asks"] == "Do you hear rushing here?"
        assert item["audio_ref"] == f"https://audio.invalid/{item['clip_id']}"
        assert not {"fired_at_sampling", "fired", "measurements", "detector_version",
                    "sampling_probability"} & set(item)

    bp.sample_for_coach(db, coach_id="c", week="w", rng=random.Random(2))
    status, sheet = bp.queue(db, coach_id="c")
    assert status == 200 and len(sheet["items"]) == 1
    clips = sheet["items"][0]["clips"]
    assert {c["clip_id"] for c in clips} == {"s1", "s2", "s3"}
    assert all(c["audio_ref"] for c in clips)
    text = json.dumps(sheet["items"])
    assert "manager" not in text and "cand-" not in text and WORDS not in text


def test_no_training_yes_writes_no_block_pick(consented, monkeypatch):
    monkeypatch.setattr(bp.pair_consent, "take_may_reach_a_coach_sheet",
                        lambda db, take: False)
    db = _Db()
    assert bp.sample_for_coach(db, coach_id="c", week="w", rng=random.Random(2)) == []
    assert db.picks == [] and db.exposures == set()


def test_a_refused_block_pick_is_skipped_and_the_rest_are_written(consented):
    db = _Db()
    frames = [f for f in _Db().list_recent_v3_frames() if f["take_session_id"] == "take-2"]
    other = json.loads(re.sub(r'"s(\d)"', r'"t\1"', json.dumps(frames))
                       .replace("take-2", "take-3").replace('"b1"', '"b3"'))
    db.list_recent_v3_frames = lambda limit=200: frames + [
        {**f, "policy_version": "v3-older"} for f in frames] + other
    plain = db.insert_coach_block_pick

    def once(row):
        if row["take_session_id"] == "take-2":  # another writer got there first
            raise RuntimeError("duplicate key value violates coach_block_pick_once")
        return plain(row)

    db.insert_coach_block_pick = once
    written = bp.sample_for_coach(db, coach_id="coach-1", week="w", rng=random.Random(2))
    assert [(w["take_session_id"], w["block_id"]) for w in written] == [("take-3", "b3")]
