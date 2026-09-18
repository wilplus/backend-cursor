"""THE "PRACTICE NEW" QUEUE (founder 2026-09-18).

Every starred clip of yours you have not answered yet, one per screen. These
pins hold what may enter the queue, what must leave it, and that the five
states survive the write whole.

Run: python3 -m unittest tests.test_voice_album_practice_queue
"""
from __future__ import annotations

import unittest

from services.voice_album_practice_queue import build_practice_queue
from services.voice_album_routing import FIVE_STATES, five_state_response

ARC = "arc-1"


def _star(trigger="confident", kind="emphasize"):
    return {"kind": kind, "trigger": trigger}


class _Db:
    def __init__(self, *, stars=None, self_reports=None, routes=None,
                 snippets=None):
        self.stars = stars or {}
        self.self_reports = self_reports or []
        self.routes = routes or []
        self.snippets = snippets or {}

    def get_moment_suggestions_by_arc(self, arc_id):
        return self.stars

    def list_confident_voice_self_reports(self, arc_id):
        return self.self_reports

    def list_owner_voice_album_routes(self, arc_id):
        return self.routes

    def get_snippets_by_session(self, session_id):
        return self.snippets.get(session_id, [])


SESSIONS = {ARC: [
    {"id": "sess-1", "take_index": 1, "analysis_state": "ready",
     "created_at": "2026-08-01T00:00:00Z"},
    {"id": "sess-2", "take_index": 2, "analysis_state": "ready",
     "created_at": "2026-08-02T00:00:00Z"},
]}
SNIPPETS = {
    "sess-1": [{"id": "s1", "slide_index": 3, "duration_ms": 6000},
               {"id": "s2", "slide_index": 1, "duration_ms": 5000}],
    "sess-2": [{"id": "s3", "slide_index": 2, "duration_ms": 7000}],
}


def _build(db, sessions=None, titles=None):
    return build_practice_queue(
        sessions_by_arc=sessions if sessions is not None else SESSIONS,
        titles_by_arc=titles if titles is not None else {ARC: "Series A"},
        database=db,
        resolve_audio=lambda snippet: "https://cdn/" + str(snippet.get("id")),
    )


class WhatEntersTests(unittest.TestCase):
    def test_a_confident_star_with_no_answer_is_queued(self):
        db = _Db(stars={"s1": _star()}, snippets=SNIPPETS)
        out = _build(db)
        self.assertEqual([row["snippet_id"] for row in out], ["s1"])
        self.assertEqual(out[0]["arc_title"], "Series A")
        self.assertEqual(out[0]["audio_url"], "https://cdn/s1")

    def test_a_neutral_nomination_is_not_a_star(self):
        # Same rule the Album's machine leg applies; the two must not drift.
        db = _Db(stars={"s1": _star(trigger="neutral")}, snippets=SNIPPETS)
        self.assertEqual(_build(db), [])

    def test_a_replace_suggestion_is_not_a_star(self):
        db = _Db(stars={"s1": _star(kind="replace")}, snippets=SNIPPETS)
        self.assertEqual(_build(db), [])

    def test_a_take_still_processing_contributes_nothing(self):
        db = _Db(stars={"s1": _star(), "s3": _star()}, snippets=SNIPPETS)
        sessions = {ARC: [
            {"id": "sess-1", "take_index": 1, "analysis_state": "running"},
            {"id": "sess-2", "take_index": 2, "analysis_state": "ready"},
        ]}
        self.assertEqual([r["snippet_id"] for r in _build(db, sessions)], ["s3"])

    def test_a_read_is_not_a_take_of_its_own(self):
        db = _Db(stars={"s1": _star()}, snippets=SNIPPETS)
        sessions = {ARC: [
            {"id": "sess-1", "take_index": 1, "recording_kind": "read"},
        ]}
        self.assertEqual(_build(db, sessions), [])


class WhatLeavesTests(unittest.TestCase):
    def test_an_answer_given_inside_a_take_review_removes_the_clip(self):
        db = _Db(stars={"s1": _star()},
                 self_reports=[{"snippet_id": "s1", "response": "yes"}],
                 snippets=SNIPPETS)
        self.assertEqual(_build(db), [])

    def test_an_answer_given_here_removes_the_clip(self):
        db = _Db(stars={"s1": _star()},
                 routes=[{"snippet_id": "s1", "response": "in_between"}],
                 snippets=SNIPPETS)
        self.assertEqual(_build(db), [])

    def test_a_no_removes_the_clip_as_surely_as_a_yes(self):
        # The five states are answers. Re-asking someone until they say yes
        # is not a queue.
        db = _Db(stars={"s1": _star()},
                 routes=[{"snippet_id": "s1", "response": "no"}],
                 snippets=SNIPPETS)
        self.assertEqual(_build(db), [])

    def test_an_answer_on_a_different_clip_leaves_this_one_queued(self):
        db = _Db(stars={"s1": _star()},
                 routes=[{"snippet_id": "other", "response": "yes"}],
                 snippets=SNIPPETS)
        self.assertEqual([r["snippet_id"] for r in _build(db)], ["s1"])


class OrderTests(unittest.TestCase):
    def test_take_order_then_slide_order(self):
        db = _Db(stars={"s1": _star(), "s2": _star(), "s3": _star()},
                 snippets=SNIPPETS)
        # Take 1 before Take 2; inside Take 1, slide 1 before slide 3.
        self.assertEqual([r["snippet_id"] for r in _build(db)],
                         ["s2", "s1", "s3"])

    def test_a_clip_with_no_slide_sorts_last_within_its_take(self):
        snippets = {"sess-1": [
            {"id": "sA", "slide_index": None},
            {"id": "sB", "slide_index": 5},
        ]}
        db = _Db(stars={"sA": _star(), "sB": _star()}, snippets=snippets)
        sessions = {ARC: [{"id": "sess-1", "take_index": 1}]}
        self.assertEqual([r["snippet_id"] for r in _build(db, sessions)],
                         ["sB", "sA"])

    def test_projects_run_oldest_first(self):
        db = _Db(stars={"s1": _star()},
                 snippets={"old": [{"id": "s1", "slide_index": 1}],
                           "new": [{"id": "s1", "slide_index": 1}]})
        sessions = {
            "arc-old": [{"id": "old", "take_index": 1}],
            "arc-new": [{"id": "new", "take_index": 1}],
        }
        out = _build(db, sessions, titles={"arc-old": "First",
                                           "arc-new": "Second"})
        self.assertEqual([row["arc_id"] for row in out],
                         ["arc-old", "arc-new"])


class ResilienceTests(unittest.TestCase):
    def test_a_failed_read_yields_an_empty_queue_not_a_raise(self):
        class _Broken(_Db):
            def get_moment_suggestions_by_arc(self, arc_id):
                raise RuntimeError("database down")
        self.assertEqual(_build(_Broken()), [])

    def test_a_failed_snippet_read_skips_that_take_only(self):
        class _Partial(_Db):
            def get_snippets_by_session(self, session_id):
                if session_id == "sess-1":
                    raise RuntimeError("nope")
                return SNIPPETS.get(session_id, [])
        db = _Partial(stars={"s1": _star(), "s3": _star()}, snippets=SNIPPETS)
        self.assertEqual([r["snippet_id"] for r in _build(db)], ["s3"])


class NeverSurfacedTests(unittest.TestCase):
    def test_the_queue_carries_no_score_or_machine_read(self):
        db = _Db(stars={"s1": dict(_star(), power_score=0.91,
                                   machine_confidence="high")},
                 snippets=SNIPPETS)
        blob = str(_build(db))
        for banned in ("power_score", "machine_confidence", "0.91", "high"):
            self.assertNotIn(banned, blob)


class FiveStateTests(unittest.TestCase):
    def test_every_state_survives_the_write_whole(self):
        for state in FIVE_STATES:
            value, error = five_state_response({"response": state})
            self.assertIsNone(error)
            self.assertEqual(value, state)

    def test_the_retired_vocabulary_is_not_accepted_on_a_new_write(self):
        for legacy in ("neutral", "unrateable"):
            value, error = five_state_response({"response": legacy})
            self.assertIsNone(value)
            self.assertIsNotNone(error)

    def test_an_unknown_answer_is_rejected_rather_than_coerced(self):
        value, error = five_state_response({"response": "maybe"})
        self.assertIsNone(value)
        self.assertIsNotNone(error)

    def test_a_non_object_body_is_rejected(self):
        value, error = five_state_response("yes")
        self.assertIsNone(value)
        self.assertIsNotNone(error)


if __name__ == "__main__":
    unittest.main()
