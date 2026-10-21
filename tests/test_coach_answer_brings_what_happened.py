"""
STORY    As a coach, I want "What happened" to come back with my saved answer,
         fast, and never before I answer.
OUTCOME
  O1  A first answer's save carries the moment's read: the passage, my own
      answer, the machine's "heard", and the exposure is recorded; the save
      reads no piece of the talk beyond the one judged (it took 9 s).
  O2  BLIND COACH: an Audio unclear answer carries no read.
PROVES   O1 -> test_a_first_answer_brings_what_happened_without_reading_the_talk
         O2 -> test_audio_unclear_brings_nothing
WHY      Founder 2026-10-21 (N99): "please make sure it is smooth that it
         loads fast"; C2 (founder 2026-10-08): What happened arrives with the
         saved answer.
"""
from __future__ import annotations

import pytest

from routes.v2 import coach as v2_coach
from tests.test_training_import_on import (
    ARC, IMPORTER, REC, SID, FakeDB, _call, _snippets,
)


class ReadingDB(FakeDB):
    """The imported talk, plus the reads the moment's read makes."""

    def __init__(self, snippets):
        super().__init__(snippets)
        self.talk_reads = 0
        self.exposures: list = []

    def get_snippets_by_session(self, sid):
        self.talk_reads += 1
        return super().get_snippets_by_session(sid)

    def get_own_state_ratings_for_session(self, _sid, rater_id):
        return {r["snippet_id"]: {"value": r["row"]["value"], "unrateable": r["row"]["unrateable"]}
                for r in self.ratings if r.get("rater_id") == rater_id}

    def get_exercise_coach_request(self, _sid, _snip):
        return None

    def get_moment_suggestion(self, _snip):
        return None

    def get_user_profile(self, _uid):
        return {"goal": "Speak at the meetup"}

    def record_coach_clip_exposure(self, **exposure):
        self.exposures.append(exposure)
        return True


@pytest.fixture
def talk(monkeypatch):
    fake = ReadingDB(_snippets(count=3))
    fake.sessions[SID] = {"id": SID, "arc_id": ARC, "take_index": 1, "recording_id": REC,
                          "source": "training_import", "user_id": IMPORTER,
                          "intake_context": {"topic": "Plan", "language": "en"}}
    monkeypatch.setattr(v2_coach, "db", fake)
    return fake


def test_a_first_answer_brings_what_happened_without_reading_the_talk(talk):
    clip = talk.snippets[1]
    status, body = _call(v2_coach.v2_coach_put_confidence_label, clip["id"], method="PUT",
                         json={"state_id": "confidence", "value": "no"})
    assert status == 200, body
    read = body["moment_read"]
    assert read["passage"] == clip["transcript"].strip()
    assert read["coach_answer"] == "no"
    assert read["heard"] == [{"kind": "nothing", "key": "nothing"}]
    assert read["request"] is None
    assert [e["clip_id"] for e in talk.exposures] == [clip["id"]]
    assert talk.talk_reads == 0


def test_audio_unclear_brings_nothing(talk):
    clip = talk.snippets[0]
    status, body = _call(v2_coach.v2_coach_put_confidence_label, clip["id"], method="PUT",
                         json={"state_id": "confidence", "value": "audio_unclear"})
    assert status == 200, body
    assert "moment_read" not in body
    assert talk.exposures == []
