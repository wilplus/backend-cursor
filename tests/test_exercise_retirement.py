"""Founder retire / bring-back: the active flag the serving read already honours."""
from __future__ import annotations

import random
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from services.coach_exercise_preference import served_view
from services.confident_voice_practice import (
    offerable_exercises,
    reviewed_active_exercises,
)
from services.exercise_retirement import set_exercise_active

ROOT = Path(__file__).resolve().parents[1]


def _row(exercise_id: str, *, active: bool = True, video: str | None = "https://v",
         post_id: str | None = None) -> dict:
    row = {
        "exercise_id": exercise_id,
        "active": active,
        "title": exercise_id,
        "instruction": "say it",
        "explanation_video_url": video,
    }
    if post_id:
        row["journal_post_id"] = post_id
    return row


class FlagFake:
    def __init__(self, row: dict | None, post: dict | None = None, *, write_fails: bool = False):
        self.row = dict(row) if isinstance(row, dict) else None
        self.post = post
        self.write_fails = write_fails
        self.writes: list[tuple[str, bool]] = []

    def get_diagnostic_exercise(self, exercise_id: str):
        if self.row and self.row.get("exercise_id") == exercise_id:
            return dict(self.row)
        return None

    def get_journal_post_by_id(self, post_id: str):
        return self.post

    def set_diagnostic_exercise_active(self, exercise_id: str, active: bool):
        self.writes.append((exercise_id, active))
        if self.write_fails:
            return None
        if self.row is not None:
            self.row["active"] = active
            return dict(self.row)
        return None


class ServingFake:
    """get_active_diagnostic_exercise honours the flag the way the real read does."""

    def __init__(self) -> None:
        self.rows = {
            "ex-live": _row("ex-live"),
            "ex-other": _row("ex-other"),
        }
        self.writes: list[tuple[str, bool]] = []

    def list_diagnostic_exercises(self):
        return [dict(row) for row in self.rows.values()]

    def get_diagnostic_exercise(self, exercise_id: str):
        row = self.rows.get(exercise_id)
        return dict(row) if row else None

    def get_active_diagnostic_exercise(self, exercise_id: str):
        row = self.rows.get(str(exercise_id or ""))
        if row and row["active"] is True and row.get("explanation_video_url"):
            return dict(row)
        return None

    def get_journal_post_by_id(self, post_id: str):
        return None

    def set_diagnostic_exercise_active(self, exercise_id: str, active: bool):
        self.writes.append((exercise_id, active))
        self.rows[exercise_id]["active"] = active
        return dict(self.rows[exercise_id])


class SwapFake:
    def __init__(self) -> None:
        self.retired = {"ex-c"}

    def get_confident_voice_exercise_assignment(self, take_session_id: str, snippet_id: str):
        return {"id": "a1", "selected_exercise_id": "ex-a", "selection_mode": "top"}

    def get_exercise_match_trace(self, assignment_id: str):
        return {"trace": {"candidates": [
            {"exercise_id": "ex-a", "outcome": "ranked"},
            {"exercise_id": "ex-b", "outcome": "ranked"},
            {"exercise_id": "ex-c", "outcome": "ranked"},
        ]}}

    def get_active_diagnostic_exercise(self, exercise_id: str):
        if exercise_id in self.retired:
            return None
        return {"exercise_id": exercise_id, "title": exercise_id, "instruction": "do it"}

    def list_speaking_errors(self):
        return []


class ServiceTests(unittest.TestCase):
    def test_retire_and_bring_back_flip_the_flag(self):
        fake = FlagFake(_row("hear-every-word-v1", active=True))
        status, payload = set_exercise_active(fake, "hear-every-word-v1", {"active": False})
        self.assertEqual(status, 200)
        self.assertEqual(payload, {
            "exercise_id": "hear-every-word-v1", "active": False, "changed": True})
        self.assertFalse(fake.row["active"])

        status, payload = set_exercise_active(fake, "hear-every-word-v1", {"active": True})
        self.assertEqual(status, 200)
        self.assertTrue(payload["changed"])
        self.assertTrue(payload["active"])
        self.assertTrue(fake.row["active"])

    def test_same_state_does_not_write(self):
        fake = FlagFake(_row("hear-every-word-v1", active=True))
        status, payload = set_exercise_active(fake, "hear-every-word-v1", {"active": True})
        self.assertEqual(status, 200)
        self.assertFalse(payload["changed"])
        self.assertEqual(fake.writes, [])

    def test_refuses_a_non_bool_a_bad_id_and_an_unknown_id(self):
        fake = FlagFake(_row("hear-every-word-v1"))
        status, payload = set_exercise_active(fake, "hear-every-word-v1", {"active": 1})
        self.assertEqual(status, 400)
        self.assertEqual(payload["code"], "INVALID_INPUT")

        status, payload = set_exercise_active(fake, "Bad Id", {"active": False})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "unknown exercise id")

        status, payload = set_exercise_active(fake, "missing-exercise", {"active": False})
        self.assertEqual(status, 404)
        self.assertEqual(payload["code"], "NOT_FOUND")
        self.assertEqual(fake.writes, [])

    def test_bring_back_needs_a_video_and_a_published_post(self):
        no_video = FlagFake(_row("hear-every-word-v1", active=False, video=None))
        status, payload = set_exercise_active(no_video, "hear-every-word-v1", {"active": True})
        self.assertEqual(status, 409)
        self.assertEqual(payload["code"], "NEEDS_VIDEO")
        self.assertEqual(no_video.writes, [])

        draft = FlagFake(
            _row("hear-every-word-v1", active=False, post_id="post-1"),
            post={"status": "draft"})
        status, payload = set_exercise_active(draft, "hear-every-word-v1", {"active": True})
        self.assertEqual(status, 409)
        self.assertEqual(payload["code"], "POST_NOT_PUBLISHED")
        self.assertEqual(draft.writes, [])

    def test_a_failed_write_is_500(self):
        fake = FlagFake(_row("hear-every-word-v1", active=True), write_fails=True)
        status, payload = set_exercise_active(fake, "hear-every-word-v1", {"active": False})
        self.assertEqual(status, 500)
        self.assertEqual(payload["code"], "V2_ERROR")


class ServingTests(unittest.TestCase):
    def test_a_retired_exercise_is_never_matched_or_offered(self):
        fake = ServingFake()
        status, payload = set_exercise_active(fake, "ex-other", {"active": False})
        self.assertEqual((status, payload["changed"]), (200, True))
        matched = {row.get("exercise_id") for row in reviewed_active_exercises(fake)}
        offered = {row.get("exercise_id") for row in offerable_exercises(fake)}
        self.assertNotIn("ex-other", matched)
        self.assertNotIn("ex-other", offered)
        self.assertIn("ex-live", matched)
        self.assertIn("ex-live", offered)

        status, payload = set_exercise_active(fake, "ex-other", {"active": True})
        self.assertEqual((status, payload["changed"]), (200, True))
        matched = {row.get("exercise_id") for row in reviewed_active_exercises(fake)}
        offered = {row.get("exercise_id") for row in offerable_exercises(fake)}
        self.assertIn("ex-other", matched)
        self.assertIn("ex-other", offered)


class SwapListTests(unittest.TestCase):
    def test_retired_pool_mates_drop_but_the_served_one_stays(self):
        fake = SwapFake()
        view = served_view(fake, take_session_id="t", snippet_id="s", rng=random.Random(1))
        self.assertIsNotNone(view)
        pool = {item["exercise_id"]: item for item in view["pool"]}
        self.assertNotIn("ex-c", pool)
        self.assertIn("ex-a", pool)
        self.assertIn("ex-b", pool)
        self.assertTrue(pool["ex-a"]["served"])
        self.assertFalse(pool["ex-b"]["served"])

        fake.retired.add("ex-a")
        view = served_view(fake, take_session_id="t", snippet_id="s", rng=random.Random(1))
        pool = {item["exercise_id"]: item for item in view["pool"]}
        self.assertNotIn("ex-c", pool)
        self.assertIn("ex-a", pool)
        self.assertTrue(pool["ex-a"]["served"])
        self.assertIn("ex-b", pool)


class GateTests(unittest.TestCase):
    def test_the_route_is_founder_gated(self):
        source = (ROOT / "routes" / "v2" / "coach_exercises.py").read_text()
        start = source.index("def v2_admin_exercise_active")
        head = source[source.rindex("@v2_bp.route", 0, start):start]
        self.assertIn("@require_founder", head)
        self.assertIn("/admin/exercises/<exercise_id>/active", head)

    def test_put_without_a_token_is_refused(self):
        try:
            from app import app
        except Exception:
            self.skipTest("app import failed")
        res = app.test_client().put(
            "/v2/admin/exercises/hear-every-word-v1/active",
            json={"active": False})
        self.assertIn(res.status_code, (401, 403))

    def test_the_route_retires_through_the_service(self):
        import routes.v2.coach_exercises as route
        fake = FlagFake(_row("ex-a", active=True))
        with Flask(__name__).test_request_context(
                "/v2/admin/exercises/ex-a/active", method="PUT",
                json={"active": False}):
            with patch.object(route, "db", fake):
                response, status = route.v2_admin_exercise_active.__wrapped__("ex-a")
        self.assertEqual(status, 200)
        self.assertEqual(response.get_json(), {
            "exercise_id": "ex-a", "active": False, "changed": True})
        self.assertFalse(fake.row["active"])
