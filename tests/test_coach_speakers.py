"""The Speakers button (coach panel lock, founder 2026-10-07).

Pins: the goal rides on the right speaker; a take is answered only once
nothing waits and the text is frozen; the shape never carries a name, an
email, a user id, or anything about a moment.
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask, request

import routes.v2.coach as route
from config import Config
from services.coach_moments_queue import moments_queue, speaker_goal
from services.coach_speakers import speakers_summary

app = Flask(__name__)


def _status(result):
    if isinstance(result, tuple):
        resp, status = result
        return resp, status
    return result, result.status_code


class GoalOnTheQueueTests(unittest.TestCase):
    def test_goal_lands_on_the_right_speaker(self):
        out = moments_queue(
            [
                {"id": "t1", "user_id": "u-a", "created_at": "1"},
                {"id": "t2", "user_id": "u-b", "created_at": "2"},
            ],
            moments_for=lambda r: [], reached_for=lambda s: set(),
            ratings_for=lambda s: {}, request_for=lambda s, n: None,
            pseudonym_for=lambda u: "Playful Octopus" if u == "u-a" else "Calm Heron",
            goal_for=lambda uid: {"u-a": "Pitch to the board"}.get(uid))
        by_name = {s["pseudonym"]: s["goal"] for s in out}
        self.assertEqual(by_name["Playful Octopus"], "Pitch to the board")
        self.assertIsNone(by_name["Calm Heron"])

    def test_goal_defaults_to_none(self):
        out = moments_queue(
            [{"id": "t", "user_id": "u", "created_at": "x"}],
            moments_for=lambda r: [], reached_for=lambda s: set(),
            ratings_for=lambda s: {}, request_for=lambda s, n: None,
            pseudonym_for=lambda u: "Calm Heron")
        self.assertIsNone(out[0]["goal"])
        self.assertIsNone(moments_queue(
            [{"id": "t2", "user_id": "u-b", "created_at": "y"}],
            moments_for=lambda r: [], reached_for=lambda s: set(),
            ratings_for=lambda s: {}, request_for=lambda s, n: None,
            pseudonym_for=lambda u: "Playful Octopus")[0]["goal"])


class SpeakerGoalTests(unittest.TestCase):
    def test_strips_the_goal(self):
        database = MagicMock()
        database.get_user_profile.return_value = {"goal": "  Win the room  "}
        self.assertEqual(speaker_goal(database, "u-a"), "Win the room")
        database.get_user_profile.assert_called_once_with("u-a")

    def test_empty_goal_is_none(self):
        database = MagicMock()
        database.get_user_profile.return_value = {"goal": ""}
        self.assertIsNone(speaker_goal(database, "u-a"))

    def test_missing_profile_is_none(self):
        database = MagicMock()
        database.get_user_profile.return_value = None
        self.assertIsNone(speaker_goal(database, "u-a"))

    def test_raise_is_none(self):
        database = MagicMock()
        database.get_user_profile.side_effect = RuntimeError("down")
        self.assertIsNone(speaker_goal(database, "u-a"))

    def test_no_profile_reader_is_none(self):
        self.assertIsNone(speaker_goal(object(), "u-a"))

    def test_empty_id_does_not_call(self):
        database = MagicMock()
        self.assertIsNone(speaker_goal(database, ""))
        self.assertIsNone(speaker_goal(database, None))
        database.get_user_profile.assert_not_called()


class SpeakersSummaryTests(unittest.TestCase):
    def test_answered_take_count_order_and_privacy(self):
        queue = [
            {
                "pseudonym": "Playful Octopus",
                "goal": "Pitch to the board",
                "waiting": 2,
                "waiting_for_text": 1,
                "user_id": "u-secret-9",
                "email": "ada@example.com",
                "takes": [
                    {
                        "session_id": "sess-1",
                        "take_index": 1,
                        "sent_at": "a",
                        "waiting": 0,
                        "waiting_for_text": False,
                        "moments": [{
                            "snippet_id": "snip-9",
                            "state": "judged",
                            "kind": "voice",
                        }],
                    },
                    {
                        "session_id": "sess-2",
                        "take_index": 2,
                        "sent_at": "b",
                        "waiting": 2,
                        "waiting_for_text": False,
                        "moments": [{"snippet_id": "snip-8", "state": "judge_it"}],
                    },
                    {
                        "session_id": "sess-3",
                        "take_index": 3,
                        "sent_at": "c",
                        "waiting": 0,
                        "waiting_for_text": True,
                        "moments": [],
                    },
                ],
            },
            {
                "pseudonym": "Calm Heron",
                "goal": None,
                "waiting": 0,
                "waiting_for_text": 0,
                "user_id": "u-other",
                "takes": [],
            },
        ]
        result = speakers_summary(queue)
        self.assertEqual(
            [s["pseudonym"] for s in result],
            ["Playful Octopus", "Calm Heron"])
        self.assertEqual(result[0]["take_count"], 3)
        self.assertEqual(result[1]["take_count"], 0)
        self.assertTrue(result[0]["takes"][0]["answered"])
        self.assertFalse(result[0]["takes"][1]["answered"])
        self.assertFalse(result[0]["takes"][2]["answered"])
        self.assertNotIn("moments", result[0]["takes"][0])
        blob = json.dumps(result)
        for forbidden in (
            "user_id", "snippet_id", "moments", "kind", "state",
            "@", "u-secret-9", "u-other", "ada@example.com",
        ):
            self.assertNotIn(forbidden, blob)

    def test_missing_keys_default_safely(self):
        result = speakers_summary([{"pseudonym": "Calm Heron"}])
        self.assertEqual(result[0]["goal"], None)
        self.assertEqual(result[0]["waiting"], 0)
        self.assertEqual(result[0]["waiting_for_text"], 0)
        self.assertEqual(result[0]["take_count"], 0)
        self.assertEqual(result[0]["takes"], [])


class SpeakersRouteTests(unittest.TestCase):
    def test_speakers_ok(self):
        with app.test_request_context("/v2/coach/speakers"):
            request.user_id = "coach-1"
            with patch("routes.v2.coach.db") as database, \
                    patch("routes.v2.coach.load_review_queue", return_value=([], {}, {})), \
                    patch("routes.v2.coach._language_matched_rows", return_value=[]), \
                    patch("services.coach_speakers.speakers_for_coach",
                          return_value=[{"pseudonym": "Calm Heron"}]):
                database.get_user_proficient_languages.return_value = ["en"]
                resp, status = _status(route.v2_coach_speakers.__wrapped__())
                self.assertEqual(status, 200)
                self.assertEqual(resp.get_json(), [{"pseudonym": "Calm Heron"}])

    def test_speakers_need_languages(self):
        with app.test_request_context("/v2/coach/speakers"):
            request.user_id = "coach-1"
            with patch("routes.v2.coach.db") as database:
                database.get_user_proficient_languages.return_value = []
                resp, status = _status(route.v2_coach_speakers.__wrapped__())
                self.assertEqual(status, 428)
                body = resp.get_json()
                self.assertEqual(body["code"], "RATER_LANGUAGES_REQUIRED")

    def test_speakers_failure(self):
        with app.test_request_context("/v2/coach/speakers"):
            request.user_id = "coach-1"
            with patch("routes.v2.coach.db") as database, \
                    patch("routes.v2.coach.load_review_queue",
                          side_effect=RuntimeError("boom")), \
                    patch("routes.v2.coach.sentry_sdk.capture_exception"):
                database.get_user_proficient_languages.return_value = ["en"]
                resp, status = _status(route.v2_coach_speakers.__wrapped__())
                self.assertEqual(status, 500)
                self.assertEqual(resp.get_json()["code"], "V2_ERROR")


class FlagTests(unittest.TestCase):
    def test_coach_students_still_off(self):
        self.assertFalse(Config.COACH_STUDENTS_ENABLED)
