"""
STORY    As a coach who teaches models, I want the queue's tasks shown in the
         models tab as models being taught, each with what waits for me and
         opening where I answer it today, with nothing moved (N642 item 6,
         step one; N643 item 4).
OUTCOME
  O1  GET /v2/models/coach-tasks lists "Moments to answer", "Do you hear
      it?", "Pick the most confident", "Pick the moment for feedback" and
      "Which sounds surer", each with this coach's waiting count as the
      panel counts it and where it opens; ``coming`` is the coming list.
  O2  Reading it fills no line and answers nothing; a line that cannot be
      read waits 0.
  O3  Someone who is not a coach, or has neither ring, gets empty lists,
      not an error.
PROVES   O1 -> CoachTasksTest::test_each_task_is_a_model_with_what_waits
         O2 -> CoachTasksTest::test_reading_fills_nothing_and_a_failed_line_waits_nothing
         O3 -> CoachTasksTest::test_others_get_empty_lists
WHY      The smallest honest first step: the founder sees the waiting list
         as models being taught, taught where it is taught today.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

H = {"Authorization": "Bearer t"}
ME = "22222222-2222-2222-2222-222222222222"


def _items(n):
    return 200, {"items": [{"n": i} for i in range(n)]}


class CoachTasksTest(unittest.TestCase):
    def setUp(self):
        from flask import Flask

        import auth
        from routes.v2 import register_domains
        from routes.v2.blueprint import v2_bp
        register_domains()
        app = Flask(__name__)
        app.register_blueprint(v2_bp, url_prefix="/v2")
        self.client = app.test_client()
        self.rings = {"ai_models"}
        self.coach = True
        never = AssertionError("a read never fills a line")
        payload = {"sub": ME, "email": "c@example.com"}
        for p in (patch.object(auth, "verify_supabase_token", lambda _t: payload),
                  patch("services.rings.feature_is_on_for_user",
                        lambda feature, _user, database=None: feature in self.rings),
                  patch("routes.admin.is_coach", lambda _u: self.coach),
                  patch("routes.admin.is_admin", lambda _u: False),
                  patch("services.admin_person.auth_user",
                        lambda _u: {"user_metadata": {"models_wanted": {"video": "2026-11-11T08:00:00+00:00"}}}),
                  patch("services.coach_moments_queue.walk_for_coach",
                        lambda *_a, **_k: [{"waiting": 30}, {"waiting": 7}, {"waiting": 0}]),
                  patch("services.error_presence_audit.queue", lambda *_a, **_k: _items(4)),
                  patch("services.coach_block_pick.queue", lambda *_a, **_k: _items(2)),
                  patch("services.v4_coach_sheets.pick_queue", lambda *_a, **_k: _items(3)),
                  patch("services.v4_coach_sheets.surer_queue", lambda *_a, **_k: _items(0)),
                  patch("services.error_presence_audit.sample_for_coach", side_effect=never),
                  patch("services.v4_coach_sheets.fill_pick_sheets", side_effect=never)):
            p.start()
            self.addCleanup(p.stop)

    def _read(self):
        res = self.client.get("/v2/models/coach-tasks", headers=H)
        self.assertEqual(res.status_code, 200)
        return res.get_json()

    def test_each_task_is_a_model_with_what_waits(self):
        got = self._read()
        self.assertEqual([(t["id"], t["kind"], t["title"], t["waiting"], t["open"]) for t in got["tasks"]], [
            ("moments", "moments", "Moments to answer", 37, {"at": "coach_queue"}),
            ("hear_it", "hear_it", "Do you hear it?", 4, {"at": "screen", "screen": "error_audit"}),
            ("block_pick", "block_pick", "Pick the most confident", 2, {"at": "screen", "screen": "block_pick"}),
            ("moment_pick", "moment_pick", "Pick the moment for feedback", 3,
             {"at": "screen", "screen": "v4_moment_pick"}),
            ("surer", "surer", "Which sounds surer", 0, {"at": "screen", "screen": "v4_surer"})])
        self.assertTrue(all(t["line"] == "" for t in got["tasks"]))
        self.assertEqual([(c["kind"], c["wanted"]) for c in got["coming"]],
                         [("images", False), ("video", True), ("recordings", False)])

    def test_reading_fills_nothing_and_a_failed_line_waits_nothing(self):
        with patch("services.coach_block_pick.queue", side_effect=RuntimeError("down")), \
                self.assertLogs("services.model_coach_tasks", "WARNING"):
            got = self._read()
        self.assertEqual({t["id"]: t["waiting"] for t in got["tasks"]}["block_pick"], 0)

    def test_others_get_empty_lists(self):
        self.coach = False
        got = self._read()
        self.assertEqual(got["tasks"], [])
        self.assertEqual(len(got["coming"]), 3)
        self.rings = set()
        self.coach = True
        self.assertEqual(self._read(), {"tasks": [], "coming": []})


if __name__ == "__main__":
    unittest.main()
