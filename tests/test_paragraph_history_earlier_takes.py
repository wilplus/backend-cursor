"""Earlier Takes rows carry that Take's recording for the Slide and the
owner's own answer on it (founder 2026-09-28, decision 5)."""
from __future__ import annotations

from types import SimpleNamespace

from services.paragraph_history import with_earlier_take_details


def _snippet(sid, slide, start, duration, url="https://audio/take.webm"):
    return {"id": sid, "start_offset_ms": start, "duration_ms": duration,
            "metrics": {"piece": {"slide_index": slide}}, "url": url}


class FakeDatabase:
    def __init__(self):
        self.takes = SimpleNamespace(get_arc_sessions=lambda arc: [
            {"id": "t1", "take_index": 1},
            {"id": "t2", "take_index": 2},
            {"id": "r1", "take_index": 3, "recording_kind": "read"},
        ])
        self.snippets = {
            "t1": [_snippet("a", 0, 0, 1000), _snippet("b", 1, 1000, 2000),
                   _snippet("c", 1, 3000, 1500)],
            "t2": [_snippet("d", 0, 0, 900)],
        }
        self.reports = {
            "t1": [
                {"feedback_family": "confident_voice", "snippet_id": "b",
                 "response": "no"},
                {"feedback_family": "confident_voice", "snippet_id": "c",
                 "response": "yes"},
                {"feedback_family": "great_formulation", "snippet_id": "b",
                 "response": "helpful"},
            ],
        }

    def get_snippets_by_session(self, sid):
        return self.snippets.get(sid, [])

    def list_take_feedback_self_reports(self, sid, user):
        return self.reports.get(sid, [])

    def get_slide_corrections(self, sid):  # pragma: no cover - optional read
        return []


def _history():
    return {"slide_index": 1, "versions": [
        {"take_index": 1, "paragraphs": ["one"]},
        {"take_index": 2, "paragraphs": ["two"]},
    ]}


def test_a_take_that_spoke_the_slide_gets_its_clip_and_the_owners_answer():
    out = with_earlier_take_details(
        FakeDatabase(), "arc", "user", _history(), lambda s: s["url"])
    first = out["versions"][0]
    assert first["take_session_id"] == "t1"
    # One file: the clip runs from the first piece on the Slide to the end
    # of the last.
    assert first["clip"] == {"snippet_audio_ref": "https://audio/take.webm",
                             "start_offset_ms": 1000, "duration_ms": 3500}
    # The latest Confident Voice answer on this Slide's clips; other
    # families never stand in for it.
    assert first["answer"] == "yes"


def test_a_take_that_did_not_speak_the_slide_shows_no_player():
    out = with_earlier_take_details(
        FakeDatabase(), "arc", "user", _history(), lambda s: s["url"])
    second = out["versions"][1]
    assert second["take_session_id"] == "t2"
    assert "clip" not in second and "answer" not in second


def test_audio_that_cannot_be_resolved_shows_no_player():
    out = with_earlier_take_details(
        FakeDatabase(), "arc", "user", _history(), lambda s: None)
    assert "clip" not in out["versions"][0]
