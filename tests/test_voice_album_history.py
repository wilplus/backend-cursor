"""THE HISTORY BEHIND ONE VOICE ALBUM MOMENT (founder 2026-09-18).

"I want the whole history so I can see from where it came from and the short
note at the end." These pins hold the shape of that account: which lanes may
speak, what they may never say, and that a missing lane goes quiet instead of
guessing.

Run: python3 -m unittest tests.test_voice_album_history
"""
from __future__ import annotations

import unittest

from services.voice_album_history import (
    build_moment_history,
)

ARC = "arc-1"
SNIP = "snip-1"


def _coach(value):
    return [{"rater_id": "coach1", "lane": "coach", "value": value,
             "state_id": "confidence", "self_report": False,
             "created_at": "2026-08-15T09:00:00Z"}]


class _Db:
    def __init__(self, *, reports=None, labels=None, practice=None,
                 attempts=None, notes=None, attempt_rows=None):
        self.reports = reports or []
        self.labels = labels or {}
        self.practice = practice
        self.attempts = attempts or []
        self.notes = notes or []
        self.attempt_rows = attempt_rows or {}
        self.inserted = []

    def list_take_feedback_self_reports_by_snippet(self, snippet_id):
        return [r for r in self.reports if r.get("snippet_id") == snippet_id]

    def get_confidence_labels_by_snippet_ids(self, ids):
        return {i: self.labels.get(i, []) for i in ids}

    def get_confident_voice_practice_by_take(self, sid, owner=None):
        return self.practice

    def get_confident_voice_practice_by_moment(self, sid, snippet_id, owner=None):
        return self.practice

    def get_confident_voice_practice(self, practice_id, owner=None):
        return self.practice

    def get_confident_voice_practice_attempt(self, attempt_id, practice_id=None):
        return self.attempt_rows.get(attempt_id)

    def list_confident_voice_practice_attempts(self, practice_id):
        return self.attempts

    def list_voice_album_notes(self, *, arc_id, moment_key, owner_user_id):
        return [n for n in self.notes
                if n.get("moment_key") == moment_key
                and n.get("owner_user_id") == owner_user_id]


def _build(db, *, moment=SNIP, entry=None, take_index=2, owner="user-1"):
    return build_moment_history(
        arc_id=ARC, moment_key=moment, owner_user_id=owner,
        entry=entry if entry is not None else {
            "snippet_id": SNIP, "take_session_id": "sess-1", "slide_index": 2,
            "entered_at": "2026-08-15T10:00:00Z",
        },
        take_index=take_index, database=db,
        resolve_audio=lambda ref: ("https://cdn/" + str(ref)) if ref else None,
    )


class ExerciseTests(unittest.TestCase):
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
        {"id": "att-1", "attempt_index": 1, "audio_ref": "a1",
         "duration_ms": 5400},
        {"id": "att-2", "attempt_index": 2, "audio_ref": "a2",
         "duration_ms": 6000},
    ]


class NeverSurfacedTests(unittest.TestCase):
    def test_no_lane_carries_a_score_ratio_or_classifier_output(self):
        db = _Db(
            reports=[{"snippet_id": SNIP, "feedback_family": "confident_voice",
                      "response": "yes", "created_at": "2026-08-14T10:00:00Z"}],
            labels={SNIP: _coach("yes")},
            practice=ExerciseTests.PRACTICE, attempts=ExerciseTests.ATTEMPTS,
        )
        blob = str(_build(db))
        for banned in ("power_score", "machine_confidence", "probability",
                       "score", "confidence_value", "percentile"):
            self.assertNotIn(banned, blob)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# THE STORY BEHIND ANY MOMENT (founder 2026-09-25).
#
# "the album shows your confident moments, not any moments." The Album is a
# trophy case — three separate yeses to get in — so the history above it can
# only ever be told about a moment that went well. The ones worth learning
# from are the others.
# ---------------------------------------------------------------------------
