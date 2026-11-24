"""
STORY    As a speaker, I want my trainings list to show which talks have an
         Ideal Text ready, so that I know where I can record next.
OUTCOME
  O1  GET /v2/user/trainings groups Takes by arc, one card per talk, Takes in
      take order.
  O2  A talk is ideal_ready once the coach has corrected every slide; a talk
      with a slide still uncorrected is not.
  O3  A coach's training import is never in the coach's own project list
      (it has no project to archive, so it blocked "One project at a time").
  O4  Each Take carries the upload key it was sent with, so a Take kept on
      the phone knows whether it arrived (N556 item 3).
  O5  Since N689, practice and playback can read each Take's actual range.
PROVES   O1, O2, O4, O5 -> test_trainings_group_by_talk_and_mark_ideal_ready
         O3     -> test_a_training_import_is_not_a_project
WHY      Founder 2026-07-13 (arc-grouped trainings). The save-at-publish half
         (POST /v2/internal/publish-session-results) is retired and answers
         410 (routes/v2/canonical_publish.py), so it has no test here.
"""
from __future__ import annotations

import inspect
from unittest.mock import patch

from flask import Flask, request

from routes.v2 import user_sessions
from services.db import db
from services.user_trainings import _coverage

SLIDES = {"topic": "T", "slides": [{"title": "A"}, {"title": "B"}]}


def _take(sid, arc, index):
    return {"id": sid, "arc_id": arc, "take_index": index,
            "created_at": f"2026-07-1{index}T10:00:00Z", "intake_context": SLIDES,
            "results_published_at": None}


def test_trainings_group_by_talk_and_mark_ideal_ready():
    rows = [
        {**_take("s2", "ready", 2), "upload_idempotency_key": "k2",
         "intake_context": {**SLIDES, "slide_advances": [{"slide": 2}]}},
        {**_take("s1", "ready", 1),
         "intake_context": {**SLIDES, "slide_advances": [{"index": 0}, {"index": 1}]}},
        _take("s3", "half", 1),
    ]
    edits = {"ready": {0: "Edited.", 1: "Also edited."}, "half": {0: "Edited."}}
    with patch.object(db.takes, "list_user_arc_sessions", return_value=rows), \
            patch.object(db, "list_arc_batch_deliveries", return_value={}), \
            patch.object(db, "get_coach_best_presentation_edits_for_arcs",
                         return_value=edits) as batched_edits, \
            patch("services.project_deletion.with_deletion_state",
                  side_effect=lambda _db, trainings, _all: trainings), \
            Flask(__name__).test_request_context():
        request.user_id = "u1"
        resp, status = inspect.unwrap(user_sessions.v2_user_list_trainings)()
    assert status == 200
    cards = {t["arc_id"]: t for t in resp.get_json()["trainings"]}
    assert set(cards) == {"ready", "half"}
    assert [t["session_id"] for t in cards["ready"]["takes"]] == ["s1", "s2"]
    assert [t["upload_key"] for t in cards["ready"]["takes"]] == [None, "k2"]
    assert [t["recorded_range"] for t in cards["ready"]["takes"]] == [
        {"start_slide": 1, "end_slide": 2}, {"start_slide": 2, "end_slide": 2},
    ]
    assert "recorded_range" not in cards["half"]["takes"][0]
    assert {"practice_progress", "practice_chunks"}.isdisjoint(cards["ready"])
    assert cards["ready"]["take_count"] == 2
    assert cards["ready"]["ideal_ready"] is True
    assert cards["half"]["ideal_ready"] is False
    batched_edits.assert_called_once_with(["ready", "half"], strict=False)


def test_coverage_uses_distinct_spoken_sections_in_completed_takes():
    takes = [
        {"analysis_state": "ready", "intake_context": {"slide_advances": [{"index": 0}, {"index": 2}]}},
        {"status": "completed", "intake_context": {"slide_advances": [{"index": 0}, {"index": 2}, {"index": 9}]}},
        {"analysis_state": "failed", "intake_context": {"slide_advances": [{"index": 1}]}},
    ]
    assert _coverage(takes, 8, True) == {"practised": 2, "total": 8, "unit": "slides"}
    assert _coverage(takes, 0, False) == {"practised": 2, "total": 3, "unit": "sections"}


def test_picker_preserves_per_project_coach_read_fallback_on_batch_failure():
    rows = [_take("s1", "ready", 1), _take("s2", "half", 1)]
    edits = {"ready": {0: "Edited.", 1: "Also edited."}, "half": {0: "Edited."}}
    with patch.object(db.takes, "list_user_arc_sessions", return_value=rows), \
            patch.object(db, "list_arc_batch_deliveries", return_value={}), \
            patch.object(db, "get_coach_best_presentation_edits_for_arcs",
                         return_value=None), \
            patch.object(db, "get_coach_best_presentation_edits",
                         side_effect=lambda arc: edits[arc]) as per_arc_edits, \
            patch("services.project_deletion.with_deletion_state",
                  side_effect=lambda _db, trainings, _all: trainings), \
            Flask(__name__).test_request_context():
        request.user_id = "u1"
        resp, status = inspect.unwrap(user_sessions.v2_user_list_trainings)()

    assert status == 200
    cards = {t["arc_id"]: t for t in resp.get_json()["trainings"]}
    assert cards["ready"]["ideal_ready"] is True
    assert cards["half"]["ideal_ready"] is False
    assert per_arc_edits.call_count == 2


class _Rows:
    """Answers any select chain on v2_sessions with fixed rows."""

    def __init__(self, rows):
        self.rows = rows
        self.not_ = self

    def table(self, _name):
        return self

    def __getattr__(self, _name):
        return lambda *a, **k: self

    def execute(self):
        return type("R", (), {"data": self.rows})()


def test_a_training_import_is_not_a_project():
    from services.take_repository import TakeRepository
    rows = [{**_take("mine", "own", 1), "source": "audit_upload"},
            {**_take("old", "legacy", 1), "source": None},
            {**_take("clip", "g100", 1), "source": "training_import"}]
    repo = TakeRepository(type("Db", (), {"client": _Rows(rows)})())
    for strict in (False, True):
        listed = repo.list_user_arc_sessions("coach", strict=strict)
        assert [r["arc_id"] for r in listed] == ["own", "legacy"]
