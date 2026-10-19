"""
STORY    As a speaker, I want to save helper words on a paragraph I have not
         locked, without it locking, so that the first pass works without an
         error.
OUTCOME
  O1  PUT root on an unlocked paragraph answers 200 saved with my words, and
      writes exactly those words and their span.
  O2  Never-5 (the speaker's words are theirs to commit): saving helper words
      never locks the paragraph -- no lock is written.
PROVES   O1 -> test_unlocked_paragraph_saves_helper_words_without_locking
         O2 -> test_unlocked_paragraph_saves_helper_words_without_locking
WHY      #442 put the save before the Lock step; every first-pass save got a
         409 PART_NOT_LOCKED (founder 2026-09-24: save them, do not lock).
"""
from __future__ import annotations

import inspect
from unittest.mock import Mock

from flask import Flask, request

import routes.v2.explore_ideal_text as route

TEXT = "The exact accepted sentence."
PHRASE = "accepted sentence"
START, END = 10, 27


def _part(*, locked: bool):
    return {"id": "part-1", "ord": 0, "text": TEXT, "locked": locked}


def _client(monkeypatch, *, locked: bool, saved: bool = True):
    database = Mock()
    database.set_ideal_text_part_root.return_value = saved
    monkeypatch.setattr(route, "db", database)
    monkeypatch.setattr(route, "_arc_owned_by_caller", lambda _arc: (True, []))
    monkeypatch.setattr(
        route, "_locked_parts",
        lambda _arc, _user, _echo: [_part(locked=locked)],
    )

    app = Flask(__name__)

    @app.before_request
    def actor():
        request.user_id = "actor-1"

    app.add_url_rule(
        "/test/<arc_id>/<part_id>",
        view_func=inspect.unwrap(route.v2_explore_set_part_root),
        methods=["PUT"],
    )
    return app.test_client(), database


def test_unlocked_paragraph_saves_helper_words_without_locking(monkeypatch):
    client, database = _client(monkeypatch, locked=False)

    response = client.put(
        "/test/arc-1/part-1",
        json={"text_echo": TEXT, "phrase": PHRASE,
              "start": START, "end": END},
    )

    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["saved"] is True
    assert (body["root_phrase"], body["root_start"], body["root_end"]) == (
        PHRASE, START, END)
    database.set_ideal_text_part_root.assert_called_once_with(
        arc_id="arc-1", user_id="actor-1", part_id="part-1",
        phrase=PHRASE, start=START, end=END)
    database.set_ideal_text_part_lock.assert_not_called()
    database.replace_ideal_text_parts.assert_not_called()
