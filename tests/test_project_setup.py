"""
STORY    As a speaker recording my next Take, I want the recording screen set
         up from my project: the words from my latest spoken Take and the
         project's current slides, so that I never re-enter my setup.
         (Critical path: next Take.)
OUTCOME
  O1  The slides and presentation come from the latest spoken Take that
      carried a deck, with the Take they were first used on; the words
      (topic, audience) from the latest spoken Take; a read-aloud Take never
      counts.
  O2  The setup is only the setup fields: no score, count, Take number or
      session id reaches the speaker (Never-1), and the setup itself is there.
  O3  Someone else's project answers 404 and shows nothing of it.
PROVES   O1 -> test_the_latest_deck_and_the_latest_words_set_up_the_next_take
         O2 -> test_the_setup_is_only_the_setup_fields
         O3 -> test_someone_elses_project_is_not_found
WHY      #1144 (founder 2026-10-16), then N257 (2026-10-29): the deck is
         the project's current one, updated inside the project.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from flask import Flask, request

    from routes.v2 import arcs as v2_arcs
    from services.db import db
    _IMPORT_ERROR = None
except Exception as error:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = error

PROJECT = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
USER = "11111111-1111-4111-8111-111111111111"
STRANGER = "99999999-9999-4999-8999-999999999999"
DECK_A = [{"title": "One", "body": "first"}]
DECK_B = [{"title": "Other", "body": "deck"}]


def _take(index, ctx, kind="spoken"):
    return {"id": f"take-{index}", "user_id": USER, "take_index": index,
            "recording_kind": kind, "intake_context": ctx}


TAKES = [
    _take(1, {"topic": "t1", "audience": "a1"}),                        # no deck
    _take(2, {"topic": "t2", "audience": "a2", "slides": DECK_A,
              "presentation_ref": "https://example.test/a.pdf"}),
    _take(3, {"topic": "t3", "audience": "a3", "slides": DECK_B,
              "presentation_ref": "https://example.test/b.pdf"}),
    _take(4, {"topic": "read", "audience": "read", "slides": DECK_B}, kind="read"),
]


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ProjectSetupEndpointTests(unittest.TestCase):

    def _get(self, takes, *, user_id=USER):
        with Flask(__name__).test_request_context(), \
                patch.object(db.takes, "get_arc_sessions", lambda arc_id: list(takes)), \
                patch.object(db, "get_project_row", lambda arc_id: None), \
                patch("routes.v2.arcs.refreshed_media_url", side_effect=lambda r: r):
            request.user_id = user_id
            out = v2_arcs.v2_explore_arc_setup.__wrapped__(PROJECT)
            response, status = out if isinstance(out, tuple) else (out, 200)
            return response.get_json(), status

    def test_the_latest_deck_and_the_latest_words_set_up_the_next_take(self):
        body, status = self._get(TAKES)
        self.assertEqual(status, 200)
        self.assertEqual((body["topic"], body["audience"]), ("t3", "a3"))
        self.assertEqual(body["slides"], DECK_B)
        self.assertEqual(body["presentation_ref"], "https://example.test/b.pdf")
        self.assertEqual((body["deck_changed"], body["deck_since_take"]),
                         (False, 3))

    def test_the_setup_is_only_the_setup_fields(self):
        body, _ = self._get(TAKES)
        self.assertEqual(set(body), {
            "arc_id", "topic", "audience", "strategic_context",
            "target_length_seconds", "slides", "presentation_ref",
            "deck_changed", "deck_since_take"})
        self.assertEqual(body["topic"], "t3")

    def test_someone_elses_project_is_not_found(self):
        body, status = self._get(TAKES, user_id=STRANGER)
        self.assertEqual(status, 404)
        self.assertEqual(body["code"], "NOT_FOUND")
        self.assertNotIn("topic", body)


if __name__ == "__main__":
    unittest.main()
