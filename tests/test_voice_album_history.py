"""
STORY    As a speaker, I want the history behind an album moment told in
         words from the lanes that spoke, so that I see where it came from,
         with no scores.
OUTCOME
  O1  The history tells, in order, my answer, my coach's agreement (as
      "Your coach"), the exercise with my attempts, and my note.
  O2  A lane with no record stays quiet: it is simply absent, never a
      placeholder or a guess.
  O3  NEVER-1: no lane carries a score, ratio, confidence value or
      classifier output, and the machine's read is never an event.
  O4  NEVER-2: the story behind any moment outside the Album never tells
      the coach lane, so its silence cannot reveal a coach's verdict.
PROVES   O1 -> test_the_history_tells_each_lane_that_spoke_in_order
         O2 -> test_a_missing_lane_stays_quiet
         O3 -> test_the_history_tells_each_lane_that_spoke_in_order
         O4 -> test_the_story_behind_any_moment_never_tells_the_coach_lane
WHY      Founder 2026-09-18 ("the whole history so I can see from where it
         came from") and 2026-09-25 ("not any moments"); AC-9.
"""
from __future__ import annotations

import json

from services.voice_album_history import (
    COACH_DISPLAY,
    build_moment_history,
    build_snippet_history,
)

ARC, SNIP, OWNER = "arc-1", "snip-1", "user-1"
REPORT = {"snippet_id": SNIP, "feedback_family": "confident_voice",
          "response": "yes", "created_at": "2026-08-14T10:00:00Z",
          "machine_confidence": 0.91}
COACH_YES = {"rater_id": "coach1", "lane": "coach", "value": "yes",
             "state_id": "confidence", "self_report": False,
             "created_at": "2026-08-15T09:00:00Z", "score": 0.8}
PRACTICE = {
    "id": "prac-1", "snippet_id": SNIP, "slide_index": 2,
    "created_at": "2026-08-16T10:00:00Z", "selected_attempt_id": "att-2",
    "exercise_id": "hear-every-word-v1", "exercise_version": 1,
    "exercise_snapshot": {
        "title": "Hear every word",
        "instruction": "Read the same text again, slightly more slowly.",
        "explanation_video_url": "https://video/hear-every-word-v1",
    },
}
ATTEMPTS = [
    {"id": "att-1", "attempt_index": 1, "audio_ref": "a1", "duration_ms": 5400,
     "power_score": 0.4},
    {"id": "att-2", "attempt_index": 2, "audio_ref": "a2", "duration_ms": 6000,
     "power_score": 0.7},
]
NOTE = {"id": "n1", "moment_key": SNIP, "owner_user_id": OWNER,
        "body": "Slower worked.", "created_at": "2026-08-17T10:00:00Z"}
BANNED = ("power_score", "machine_confidence", "probability", "score",
          "confidence_value", "percentile", "0.91", "0.8", "0.4", "0.7")


class _Db:
    """The records each lane reads; any lane can be left empty."""

    def __init__(self, *, reports=(), labels=(), practice=None, attempts=(), notes=()):
        self.reports, self.labels = list(reports), list(labels)
        self.practice, self.attempts, self.notes = practice, list(attempts), list(notes)

    def list_take_feedback_self_reports_by_snippet(self, snippet_id):
        return [r for r in self.reports if r["snippet_id"] == snippet_id]

    def get_confidence_labels_by_snippet_ids(self, ids):
        return {i: list(self.labels) for i in ids}

    def get_confident_voice_practice_by_moment(self, _sid, _snippet_id, _owner=None):
        return self.practice

    def list_confident_voice_practice_attempts(self, _practice_id):
        return list(self.attempts)

    def list_voice_album_notes(self, *, arc_id, moment_key, owner_user_id):
        return [n for n in self.notes
                if n["moment_key"] == moment_key and n["owner_user_id"] == owner_user_id]


def _album_history(db):
    return build_moment_history(
        arc_id=ARC, moment_key=SNIP, owner_user_id=OWNER,
        entry={"snippet_id": SNIP, "take_session_id": "sess-1", "slide_index": 2,
               "entered_at": "2026-08-15T10:00:00Z"},
        take_index=2, database=db,
        resolve_audio=lambda ref: f"https://cdn/{ref}" if ref else None)


def _everything():
    return _Db(reports=[REPORT], labels=[COACH_YES], practice=PRACTICE,
               attempts=ATTEMPTS, notes=[NOTE])


def test_the_history_tells_each_lane_that_spoke_in_order():
    history = _album_history(_everything())
    assert history["origin"] == {"take_index": 2, "slide_index": 2,
                                 "at": "2026-08-15T10:00:00Z", "source": "snippet"}
    events = history["events"]
    assert [e["kind"] for e in events] == ["owner_answer", "coach_agreed", "exercise", "note"]
    owner, coach, exercise, note = events
    assert (owner["who"], owner["response"]) == ("You", "yes")
    assert coach["who"] == COACH_DISPLAY and "coach1" not in json.dumps(history)
    assert exercise["title"] == "Hear every word"
    assert [(a["attempt_id"], a["kept"]) for a in exercise["attempts"]] == [
        ("att-1", False), ("att-2", True)]
    assert note["body"] == "Slower worked."
    flat = json.dumps(history)
    for banned in BANNED:
        assert banned not in flat, banned
    assert "machine" not in {e["kind"] for e in events}


def test_a_missing_lane_stays_quiet():
    history = _album_history(_Db(reports=[REPORT]))
    assert [e["kind"] for e in history["events"]] == ["owner_answer"]
    assert _album_history(_Db())["events"] == []


def test_the_story_behind_any_moment_never_tells_the_coach_lane():
    history = build_snippet_history(
        arc_id=ARC, snippet_id=SNIP, owner_user_id=OWNER, take_session_id="sess-1",
        take_index=2, database=_everything())
    kinds = [e["kind"] for e in history["events"]]
    assert kinds == ["owner_answer", "exercise", "note"]
    assert COACH_DISPLAY not in json.dumps(history)
