"""
STORY    As a speaker, I want my chosen helper words to stay on their slide
         after a later Take, and out-of-date ones refused, so that my helper
         words stay until I pick new ones.
OUTCOME
  O1  Helper words whose Paragraph was changed or belongs elsewhere are
      refused rather than shown in the wrong place.
  O2  The helper-words route returns the helper words currently chosen.
  O3  Helper words picked in an earlier Take still appear, on the slide's
      Paragraph now.
  O4  After a Clearer version the walk's helper words come on their own
      (N309): the sentence the practice was opened on goes to the slide,
      with or without a try, whole, past eight words too (N323 item 2);
      words not in it are refused.
  O5  The walk locks the paragraph first and saves the words after: those
      words show on the recording screen and the page, and a pick on the
      same paragraph in the next Take replaces them.
PROVES   O1 -> test_stale_or_invalid_live_root_fails_closed
         O2 -> test_recording_roots_route_returns_the_live_root
         O3 -> test_helper_words_from_an_earlier_take_stay_on_their_slide
         O4 -> test_the_clearer_versions_sentence_becomes_my_helper_words
         O5 -> test_the_walks_helper_words_show_on_the_next_take
WHY      Never-rule 5; founder 2026-10-13, project "S"; founder 2026-10-31
         (N309 item 3, "the helper words come on their own").
"""
from __future__ import annotations

import inspect
from unittest.mock import Mock

import pytest
from flask import Flask, request

from services.recording_roots import RecordingRootsStale, project_recording_roots


def _snapshot(*, slide_index=1):
    return {
        "id": "snapshot-1",
        "payload_sha256": "a" * 64,
        "payload": {
            "text": "The exact accepted sentence.",
            "parts": [{
                "id": "part-1", "ord": 0,
                "text": "The exact accepted sentence.", "locked": False,
                "iteration": 0,
            }],
            "pieces": [{
                "text": "The exact accepted sentence.",
                "slide_index": slide_index,
            }],
        },
    }


def _live_rows():
    return [{
        "id": "part-1", "ord": 0,
        "text": "The exact accepted sentence.",
        "locked_at": "2026-09-07T10:00:00Z", "iteration": 1,
        "root_phrase": "accepted sentence", "root_start": 10,
        "root_end": 27,
    }]


@pytest.mark.parametrize("mutation", ["id", "text"])
def test_stale_or_invalid_live_root_fails_closed(mutation):
    rows = _live_rows()
    if mutation == "id":
        rows[0]["id"] = "part-foreign"
    else:
        rows[0]["text"] = "Changed text."
    with pytest.raises(RecordingRootsStale):
        project_recording_roots(_snapshot(), rows)


def test_recording_roots_route_returns_the_live_root(monkeypatch):
    import routes.v2.explore_ideal_text as route

    database = Mock()
    database.get_ideal_text_document_core.return_value = _snapshot()
    database.get_ideal_text_parts.return_value = _live_rows()
    monkeypatch.setattr(route, "db", database)
    monkeypatch.setattr(route, "_arc_owned_by_caller", lambda _arc: (True, []))

    app = Flask(__name__)

    @app.before_request
    def actor():
        request.user_id = "actor-1"

    app.add_url_rule(
        "/test/<arc_id>",
        view_func=inspect.unwrap(route.v2_explore_get_recording_roots),
    )
    response = app.test_client().get("/test/arc-1")

    assert response.status_code == 200
    assert response.get_json()["roots"][0]["text"] == "accepted sentence"
    database.get_ideal_text_parts.assert_called_once_with(
        "arc-1", "actor-1", with_lock=True)


def _route_response(monkeypatch, *, live_rows, slide_rows):
    import routes.v2.explore_ideal_text as route

    database = Mock()
    database.get_ideal_text_document_core.return_value = _snapshot()
    database.get_ideal_text_parts.return_value = live_rows
    database.get_slide_helper_words.return_value = slide_rows
    monkeypatch.setattr(route, "db", database)
    monkeypatch.setattr(route, "_arc_owned_by_caller", lambda _arc: (True, []))
    app = Flask(__name__)

    @app.before_request
    def actor():
        request.user_id = "actor-1"

    app.add_url_rule(
        "/test/<arc_id>",
        view_func=inspect.unwrap(route.v2_explore_get_recording_roots),
    )
    return app.test_client().get("/test/arc-1")


def test_helper_words_from_an_earlier_take_stay_on_their_slide(monkeypatch):
    """Founder 2026-10-13, project "S": the Paragraph the words were picked
    on is gone after a later Take, and the live Paragraphs are mid-change.
    The words still reach the page, on the Slide's Paragraph now."""
    rows = _live_rows()
    rows[0]["text"] = "Changed text."
    response = _route_response(monkeypatch, live_rows=rows, slide_rows=[{
        "slide_index": 1, "ord": 0, "phrase": "accepted sentence",
        "take_session_id": "take-1", "source_part_id": "part-from-take-1",
        "locked_at": "2026-10-10T09:00:00Z",
    }])

    assert response.status_code == 200
    assert response.get_json()["roots"] == [{
        "part_id": "part-1", "slide_index": 1,
        "text": "accepted sentence", "type": "flagship",
    }]


def test_the_clearer_versions_sentence_becomes_my_helper_words(monkeypatch):
    from services import practice_adoption, slide_helper_words

    picked = []
    monkeypatch.setattr(slide_helper_words, "record_pick",
                        lambda _db, arc, user, part, take, words, **_: picked.append((arc, part, take, words)))
    database = Mock()
    database.takes.get_arc_sessions.return_value = [{"id": "take-3", "take_index": 3}]
    # Opened on the Clearer version's words; no try was kept yet.
    practice = {"id": "p-1", "project_id": "arc-1", "status": "open",
                "exact_passage": "We're already seeing real traction."}
    status, body = practice_adoption.helper_words_from_practice(
        database, practice, "part-1", "We're already seeing real traction.", "user-1",
        source="passage")
    assert (status, body) == (200, {"saved": True, "phrase": "We're already seeing real traction."})
    assert picked == [("arc-1", "part-1", "take-3", "We're already seeing real traction.")]
    # Words that are not the sentence's are refused, and nothing is saved.
    status, _ = practice_adoption.helper_words_from_practice(
        database, practice, "part-1", "we are seeing traction", "user-1", source="passage")
    assert status == 400 and len(picked) == 1
    # A Clearer version of twelve words is saved whole (N323 item 2).
    twelve = "We're already seeing real traction with three paying customers this quarter alone."
    status, body = practice_adoption.helper_words_from_practice(
        database, {**practice, "exact_passage": twelve}, "part-1", twelve, "user-1",
        source="passage")
    assert (status, body) == (200, {"saved": True, "phrase": twelve})
    assert picked[-1] == ("arc-1", "part-1", "take-3", twelve)
    # Without the walk's source, an open practice still needs a judged try.
    assert practice_adoption.helper_words_from_practice(
        database, practice, "part-1", "real traction", "user-1")[0] == 409


class _Arc:
    """One arc's paragraph and its Slide's helper words, kept as the
    database keeps them."""

    def __init__(self):
        self.parts = [dict(_live_rows()[0], locked_at=None, root_phrase=None,
                           root_start=None, root_end=None)]
        self.slide_rows: list = []
        self.takes = Mock()

    def get_ideal_text_document_core(self, _arc, _user):
        return _snapshot()

    def get_ideal_text_parts(self, _arc, _user, with_lock=False):
        return [dict(p) for p in self.parts]

    def set_ideal_text_part_lock(self, _arc, _user, _part, locked, revision_action=None):
        self.parts = [dict(p, locked_at="2026-11-03T10:00:00Z" if locked else None)
                      for p in self.parts]
        return True

    def set_ideal_text_part_root(self, *, arc_id, user_id, part_id, phrase, start, end):
        self.parts = [dict(p, root_phrase=phrase, root_start=start, root_end=end)
                      for p in self.parts]
        return True

    def get_slide_helper_words(self, _arc, _user):
        return [dict(r) for r in self.slide_rows]

    def replace_slide_helper_words(self, _arc, _user, slide, rows):
        self.slide_rows = [r for r in self.slide_rows if r["slide_index"] != slide] + [
            dict(r, slide_index=slide) for r in rows]
        return True

    def v2_get_session_by_id(self, _sid):
        return {}

    def get_latest_ideal_text_part_revision(self, **_):
        return {}

    def record_canonical_paragraph_decision(self, _decision):
        return None

    def record_canonical_root_phrase(self, _root):
        return None


def test_the_walks_helper_words_show_on_the_next_take(monkeypatch):
    """N309 item 3: the Clearer version's sentence shows under the slide in
    the next Take and on the Ideal Text. The walk locks first, then saves the
    words; a pick on that paragraph in the next Take replaces them (Q14 A)."""
    import routes.v2.explore_ideal_text as route
    from services import practice_adoption
    from services.ideal_text_part_actions import lock_part, root_part
    from services.ideal_text_parts import serve

    arc = _Arc()
    monkeypatch.setattr(route, "db", arc)
    monkeypatch.setattr(route, "_arc_owned_by_caller", lambda _arc: (True, []))
    app = Flask(__name__)

    @app.before_request
    def actor():
        request.user_id = "actor-1"

    app.add_url_rule("/test/<arc_id>",
                     view_func=inspect.unwrap(route.v2_explore_get_recording_roots))

    def roots():
        return [r["text"] for r in app.test_client().get("/test/arc-1").get_json()["roots"]]

    sentence = "We're already seeing real traction."
    take_one = [{"id": "take-1", "take_index": 1}]
    arc.takes.get_arc_sessions.return_value = take_one
    lock_part(arc, arc_id="arc-1", user_id="actor-1", part_id="part-1",
              parts=serve(arc.parts), locked=True, body={}, sessions=take_one)
    practice = {"id": "p-1", "project_id": "arc-1", "status": "open",
                "exact_passage": sentence}
    assert practice_adoption.helper_words_from_practice(
        arc, practice, "part-1", sentence, "actor-1", source="passage")[0] == 200
    assert roots() == [sentence]

    take_two = take_one + [{"id": "take-2", "take_index": 2}]
    lock_part(arc, arc_id="arc-1", user_id="actor-1", part_id="part-1",
              parts=serve(arc.parts), locked=True, body={}, sessions=take_two)
    root_part(arc, arc_id="arc-1", user_id="actor-1", part_id="part-1",
              target=serve(arc.parts)[0],
              body={"phrase": "accepted sentence", "start": 10, "end": 27},
              sessions=take_two)
    assert roots() == ["accepted sentence"]
