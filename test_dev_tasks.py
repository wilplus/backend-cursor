"""dev-tasks — prioritization engine + transform tests (founder 2026-07-24).

The load-bearing tests are the STABILITY ones: an epic's/story's rank freezes on
first sight, existing tasks never move as new ones amass, and the list stays
ordered Theme > Epic > Story > Priority. Pure planning fns are tested directly
(no DB); the transform + wrappers are mocked.

Run: python3 -m unittest test_dev_tasks
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

try:
    from services import dev_tasks as svc
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    svc = None
    _IMPORT_ERROR = e

try:
    from flask import Flask
    from routes import dev_tasks as rt
    from routes import dev_bugs as rb
    _ROUTE_IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = rt = rb = None
    _ROUTE_IMPORT_ERROR = e


def _cls(theme, epic, story, priority=2, epic_rank=10, story_rank=10, body="do it"):
    return {"theme": theme, "epic": epic, "user_story": story, "priority": priority,
            "epic_rank": epic_rank, "story_rank": story_rank, "body": body}


def _simulate(classifications):
    """Insert each classification against the accumulated list (as generate_task_for_bug does),
    assigning ids 1..N. Returns the task rows with their computed order_key/ranks."""
    rows = []
    for i, c in enumerate(classifications, 1):
        plan = svc.plan_insert(rows, c)
        rows.append({
            "id": i, "theme": c["theme"], "epic": c["epic"], "user_story": c["user_story"],
            "priority": c["priority"], "epic_rank": plan["epic_rank"],
            "story_rank": plan["story_rank"], "order_key": plan["order_key"], "body": c["body"],
        })
    return rows


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class PlanningTests(unittest.TestCase):

    def test_theme_order_T1_before_T4(self):
        rows = _simulate([
            _cls("T4", "4.3 Release", "s"), _cls("T1", "1.1 versioning", "s"),
            _cls("T3", "3.1 shadow", "s"), _cls("T2", "2.2 schema", "s"),
        ])
        ordered = [r["theme"] for r in sorted(rows, key=svc.sort_key)]
        self.assertEqual(ordered, ["T1", "T2", "T3", "T4"])

    def test_epic_rank_frozen_on_first_sight(self):
        # First task in epic "1.2" sets epic_rank=3; a later task in the SAME epic
        # must reuse 3 even though GPT-4o now says 9 — same-epic tasks stay grouped.
        rows = _simulate([_cls("T1", "1.2 UX", "s1", epic_rank=3)])
        plan = svc.plan_insert(rows, _cls("T1", "1.2 UX", "s2", epic_rank=9))
        self.assertEqual(plan["epic_rank"], 3)

    def test_story_rank_frozen_on_first_sight(self):
        rows = _simulate([_cls("T1", "1.2 UX", "same story", story_rank=4)])
        plan = svc.plan_insert(rows, _cls("T1", "1.2 UX", "same story", story_rank=8))
        self.assertEqual(plan["story_rank"], 4)

    def test_same_bucket_appends_not_collides(self):
        rows = _simulate([_cls("T1", "1.1", "s", priority=1),
                          _cls("T1", "1.1", "s", priority=1)])
        k0, k1 = rows[0]["order_key"], rows[1]["order_key"]
        self.assertLess(k0, k1)                 # second appends after first
        self.assertEqual(k1, k0 + 1)

    def test_priority_orders_within_story(self):
        rows = _simulate([
            _cls("T1", "1.1", "s", priority=3), _cls("T1", "1.1", "s", priority=1),
            _cls("T1", "1.1", "s", priority=2),
        ])
        prios = [r["priority"] for r in sorted(rows, key=svc.sort_key)]
        self.assertEqual(prios, [1, 2, 3])

    def test_stability_existing_never_move_as_tasks_amass(self):
        # Insert a diverse stream; after each insert, no already-placed order_key changes,
        # and the sorted order is always non-decreasing in (theme,epic_rank,story_rank,priority).
        stream = []
        for i in range(30):
            t = f"T{(i % 4) + 1}"
            stream.append(_cls(t, f"{(i % 4)+1}.{(i % 3)+1} epic", f"story{i % 5}",
                               priority=(i % 3) + 1, epic_rank=(i % 3) + 1, story_rank=(i % 4) + 1))
        prev_keys = {}
        rows = []
        for i, c in enumerate(stream, 1):
            plan = svc.plan_insert(rows, c)
            rows.append({"id": i, "theme": c["theme"], "epic": c["epic"],
                         "user_story": c["user_story"], "priority": c["priority"],
                         "epic_rank": plan["epic_rank"], "story_rank": plan["story_rank"],
                         "order_key": plan["order_key"], "body": ""})
            # existing keys unchanged
            for r in rows[:-1]:
                self.assertEqual(prev_keys[r["id"]], r["order_key"])
            prev_keys = {r["id"]: r["order_key"] for r in rows}
        # final order is monotone in the composite rank
        srt = sorted(rows, key=svc.sort_key)
        def comp(r):
            return (svc._THEME_RANK.get(r["theme"], 5), r["epic_rank"], r["story_rank"], r["priority"])
        for a, b in zip(srt, srt[1:]):
            self.assertLessEqual(comp(a), comp(b))

    def test_reorder_to_top(self):
        rows = _simulate([_cls("T1", "1.1", "s"), _cls("T2", "2.1", "s"), _cls("T3", "3.1", "s")])
        # move id=3 (T3, last) to the top
        k = svc.plan_reorder(rows, task_id=3, after_id=None)
        self.assertLess(k, min(svc.sort_key(r)[0] for r in rows if r["id"] != 3))

    def test_reorder_after_middle(self):
        rows = _simulate([_cls("T1", "1.1", "s"), _cls("T2", "2.1", "s"), _cls("T3", "3.1", "s")])
        # move id=3 to right after id=1 → between id=1 and id=2
        k = svc.plan_reorder(rows, task_id=3, after_id=1)
        k1 = next(svc.sort_key(r)[0] for r in rows if r["id"] == 1)
        k2 = next(svc.sort_key(r)[0] for r in rows if r["id"] == 2)
        self.assertTrue(k1 < k < k2)

    def test_markdown_export_in_order(self):
        rows = _simulate([_cls("T2", "2.1", "s", body="second"),
                          _cls("T1", "1.1", "s", body="first")])
        md = svc.to_markdown(rows)
        self.assertLess(md.index("first"), md.index("second"))
        self.assertIn("# WillpowerLab", md)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class TransformTests(unittest.TestCase):

    def test_classify_none_without_client(self):
        fake = MagicMock(); fake.client = None
        with patch.dict("sys.modules", {"services.openai_service": MagicMock(openai_service=fake)}):
            self.assertIsNone(svc.classify_bug("some bug"))

    def test_classify_parses_json(self):
        fake_client = MagicMock()
        msg = MagicMock(); msg.content = '{"theme":"T1","epic":"1.1","user_story":"as a user...","body":"x","priority":1}'
        fake_client.chat.completions.create.return_value = MagicMock(choices=[MagicMock(message=msg)])
        fake_mod = MagicMock(); fake_mod.openai_service = MagicMock(client=fake_client)
        with patch.dict("sys.modules", {"services.openai_service": fake_mod}):
            out = svc.classify_bug("bug text")
        self.assertEqual(out["theme"], "T1")
        self.assertEqual(out["priority"], 1)

    def test_generate_task_inserts_with_computed_key(self):
        cls = _cls("T1", "1.1 versioning", "as a user I want X", priority=1, epic_rank=2, story_rank=1)
        client = MagicMock()
        # _active_rows() → empty; insert → echoes a row with id
        client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        inserted = {"id": 7}
        client.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[inserted])
        with patch.object(svc, "classify_bug", return_value=cls), \
             patch.object(svc.db, "client", client):
            out = svc.generate_task_for_bug({"id": 99, "text": "make versioning show history"})
        self.assertEqual(out, inserted)
        # the row we tried to insert carried a computed order_key + frozen ranks
        insert_arg = client.table.return_value.insert.call_args.args[0]
        self.assertEqual(insert_arg["bug_id"], 99)
        self.assertEqual(insert_arg["theme"], "T1")
        self.assertEqual(insert_arg["priority"], 1)
        self.assertIn("order_key", insert_arg)
        self.assertGreater(insert_arg["order_key"], 0)

    def test_generate_task_noop_on_empty_or_no_openai(self):
        with patch.object(svc, "classify_bug", return_value=None):
            self.assertIsNone(svc.generate_task_for_bug({"id": 1, "text": "x"}))
        self.assertIsNone(svc.generate_task_for_bug({"id": 1, "text": "  "}))


@unittest.skipIf(_ROUTE_IMPORT_ERROR is not None, f"needs flask: {_ROUTE_IMPORT_ERROR}")
class RouteTests(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(rt.dev_tasks_bp)
        self.client = self.app.test_client()
        self._p = patch.object(rb.config, "DEV_BUGS_KEY", "secret")
        self._p.start()

    def tearDown(self):
        self._p.stop()

    def _h(self, key="secret"):
        return {"x-dev-key": key} if key else {}

    def test_gate_401_without_key(self):
        self.assertEqual(self.client.get("/api/dev-tasks").status_code, 401)

    def test_list_active(self):
        with patch.object(rt.svc, "list_tasks", return_value=[{"id": 1}]) as m:
            r = self.client.get("/api/dev-tasks?view=active", headers=self._h())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["tasks"], [{"id": 1}])
        m.assert_called_once_with("active")

    def test_export_markdown_download(self):
        with patch.object(rt.svc, "export_markdown", return_value="# backlog\n"):
            r = self.client.get("/api/dev-tasks/export", headers=self._h())
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/markdown", r.headers["Content-Type"])
        self.assertIn("attachment", r.headers["Content-Disposition"])

    def test_patch_edit(self):
        with patch.object(rt.svc, "update_task", return_value={"id": 5, "body": "new"}) as m:
            r = self.client.patch("/api/dev-tasks/5", json={"body": "new"}, headers=self._h())
        self.assertEqual(r.status_code, 200)
        m.assert_called_once()

    def test_delete(self):
        with patch.object(rt.svc, "delete_task") as m:
            r = self.client.delete("/api/dev-tasks/5", headers=self._h())
        self.assertEqual(r.status_code, 204)
        m.assert_called_once_with(5)

    def test_reorder_after_and_top(self):
        with patch.object(rt.svc, "reorder_task") as m:
            r1 = self.client.post("/api/dev-tasks/5/reorder", json={"after_id": 2}, headers=self._h())
            r2 = self.client.post("/api/dev-tasks/5/reorder", json={"after_id": None}, headers=self._h())
        self.assertEqual((r1.status_code, r2.status_code), (200, 200))
        self.assertEqual(m.call_args_list[0].args, (5, 2))
        self.assertEqual(m.call_args_list[1].args, (5, None))

    def test_reorder_bad_after_400(self):
        r = self.client.post("/api/dev-tasks/5/reorder", json={"after_id": "nope"}, headers=self._h())
        self.assertEqual(r.status_code, 400)

    def test_done_and_restore(self):
        with patch.object(rt.svc, "set_done") as md, patch.object(rt.svc, "restore_task") as mr:
            rd = self.client.post("/api/dev-tasks/5/done", headers=self._h())
            rr = self.client.post("/api/dev-tasks/5/restore", headers=self._h())
        self.assertEqual((rd.status_code, rr.status_code), (200, 200))
        md.assert_called_once_with(5)
        mr.assert_called_once_with(5)

    def test_route_disambiguation_export_vs_int_id(self):
        rules = [str(r) for r in self.app.url_map.iter_rules()]
        self.assertIn("/api/dev-tasks/export", rules)
        self.assertIn("/api/dev-tasks/<int:task_id>", rules)


if __name__ == "__main__":
    unittest.main()
