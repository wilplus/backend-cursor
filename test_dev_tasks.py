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

    def test_markdown_export_embeds_images(self):
        rows = [{"id": 1, "theme": "T1", "epic": "1.1", "user_story": "s", "priority": 1,
                 "order_key": 1.0, "body": "fix it", "images": ["data:image/png;base64,AAA", "data:image/png;base64,BBB"]}]
        md = svc.to_markdown(rows)
        self.assertIn("![screenshot 1](data:image/png;base64,AAA)", md)
        self.assertIn("![screenshot 2](data:image/png;base64,BBB)", md)

    def test_markdown_export_no_images_key_is_fine(self):
        rows = [{"id": 1, "theme": "T1", "epic": "1.1", "user_story": "s", "priority": 1,
                 "order_key": 1.0, "body": "fix it"}]
        self.assertNotIn("![screenshot", svc.to_markdown(rows))

    def test_markdown_export_in_order(self):
        rows = _simulate([_cls("T2", "2.1", "s", body="second"),
                          _cls("T1", "1.1", "s", body="first")])
        md = svc.to_markdown(rows)
        self.assertLess(md.index("first"), md.index("second"))
        self.assertIn("# WillpowerLab", md)


# 1x1 PNG and 1x1 GIF as the frontend stores them (data: URLs).
_PNG_URL = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0"
            "lEQVR4nGNgAAIAAAUAAen63NgAAAAASUVORK5CYII=")
_GIF_URL = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ExportBundleTests(unittest.TestCase):
    """Export ships the screenshots as real files.

    A .md with megabytes of inline base64 renders in almost nothing (GitHub and
    most editors refuse data: URIs) and can't be opened as an image, so once a task
    has a screenshot the export becomes a ZIP whose markdown links real files.
    """

    def _rows_with_images(self):
        rows = _simulate([_cls("T1", "1.1", "s", body="first"),
                          _cls("T2", "2.1", "s", body="second")])
        rows[0]["images"] = [_PNG_URL, _GIF_URL]
        return rows

    def _zip(self, rows):
        import io
        import zipfile
        payload, mime, name = svc.export_bundle(rows)
        return zipfile.ZipFile(io.BytesIO(payload)), mime, name

    def test_zip_when_a_task_has_images(self):
        z, mime, name = self._zip(self._rows_with_images())
        self.assertEqual(mime, "application/zip")
        self.assertEqual(name, "willpowerlab-backlog.zip")
        self.assertIn("backlog.md", z.namelist())

    def test_image_files_land_with_the_right_extension(self):
        z, _, _ = self._zip(self._rows_with_images())
        self.assertIn("images/task-1-1.png", z.namelist())
        self.assertIn("images/task-1-2.gif", z.namelist())

    def test_image_bytes_survive_the_round_trip(self):
        import base64
        z, _, _ = self._zip(self._rows_with_images())
        self.assertEqual(z.read("images/task-1-1.png"),
                         base64.b64decode(_PNG_URL.split(",", 1)[1]))
        self.assertTrue(z.read("images/task-1-1.png").startswith(b"\x89PNG"))

    def test_zip_markdown_links_files_instead_of_inlining_base64(self):
        z, _, _ = self._zip(self._rows_with_images())
        md = z.read("backlog.md").decode("utf-8")
        self.assertIn("![screenshot 1](images/task-1-1.png)", md)
        self.assertIn("![screenshot 2](images/task-1-2.gif)", md)
        self.assertNotIn("data:image", md)                 # the whole point of the ZIP
        self.assertLess(md.index("first"), md.index("second"))   # priority order held

    def test_plain_markdown_stays_self_contained_when_there_is_nothing_to_bundle(self):
        rows = _simulate([_cls("T1", "1.1", "s", body="only")])
        payload, mime, name = svc.export_bundle(rows)
        self.assertEqual(mime, "text/markdown")
        self.assertEqual(name, "willpowerlab-backlog.md")
        self.assertIn("only", payload.decode("utf-8"))

    def test_http_images_stay_as_links_and_are_not_fetched(self):
        """An export must not depend on network egress."""
        rows = _simulate([_cls("T1", "1.1", "s", body="x")])
        rows[0]["images"] = ["https://example.com/shot.png"]
        payload, mime, _ = svc.export_bundle(rows)
        self.assertEqual(mime, "text/markdown")            # nothing decodable to bundle
        self.assertIn("https://example.com/shot.png", payload.decode("utf-8"))

    def test_undecodable_image_is_skipped_not_fatal(self):
        rows = _simulate([_cls("T1", "1.1", "s", body="x")])
        rows[0]["images"] = ["data:image/png;base64,%%%not-base64%%%", _PNG_URL, None, ""]
        z, mime, _ = self._zip(rows)
        self.assertEqual(mime, "application/zip")
        # numbered over what made it in, so the file name matches its "screenshot N"
        self.assertEqual([n for n in z.namelist() if n.startswith("images/")],
                         ["images/task-1-1.png"])
        self.assertIn("![screenshot 1](images/task-1-1.png)",
                      z.read("backlog.md").decode("utf-8"))


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class TransformTests(unittest.TestCase):

    def test_classify_none_without_client(self):
        fake = MagicMock()
        fake.client = None
        with patch.dict("sys.modules", {"services.openai_service": MagicMock(openai_service=fake)}):
            self.assertIsNone(svc.classify_bug("some bug"))

    def test_classify_parses_json(self):
        fake_client = MagicMock()
        msg = MagicMock()
        msg.content = '{"theme":"T1","epic":"1.1","user_story":"as a user...","body":"x","priority":1}'
        fake_client.chat.completions.create.return_value = MagicMock(choices=[MagicMock(message=msg)])
        fake_mod = MagicMock()
        fake_mod.openai_service = MagicMock(client=fake_client)
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
            out = svc.generate_task_for_bug(
                {"id": 99, "text": "make versioning show history", "images": ["data:img1", "data:img2"]})
        self.assertEqual(out, inserted)
        # the row we tried to insert carried a computed order_key + frozen ranks + the bug's images
        insert_arg = client.table.return_value.insert.call_args.args[0]
        self.assertEqual(insert_arg["bug_id"], 99)
        self.assertEqual(insert_arg["theme"], "T1")
        self.assertEqual(insert_arg["priority"], 1)
        self.assertIn("order_key", insert_arg)
        self.assertGreater(insert_arg["order_key"], 0)
        self.assertEqual(insert_arg["images"], ["data:img1", "data:img2"])

    def test_generate_task_noop_on_empty_or_no_openai(self):
        with patch.object(svc, "classify_bug", return_value=None):
            self.assertIsNone(svc.generate_task_for_bug({"id": 1, "text": "x"}))
        self.assertIsNone(svc.generate_task_for_bug({"id": 1, "text": "  "}))


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ReevalTests(unittest.TestCase):

    def test_flag_off_is_noop(self):
        with patch.object(svc.config, "DEV_TASKS_REEVAL_ENABLED", False):
            self.assertEqual(svc.reevaluate({"id": 1, "priority": 1}), [])

    def test_low_priority_new_task_skips_llm(self):
        with patch.object(svc.config, "DEV_TASKS_REEVAL_ENABLED", True), \
             patch.object(svc, "_reeval_llm") as m:
            self.assertEqual(svc.reevaluate({"id": 1, "priority": 3}), [])
            m.assert_not_called()

    def test_plan_bump_lands_in_new_priority_bucket(self):
        base = 1e12 + 1e9 + 1e6 + 1 * svc._BUCKET  # T1 / epic1 / story1 / P1
        existing = [{"id": 9, "theme": "T1", "epic_rank": 1, "story_rank": 1, "priority": 1, "order_key": base}]
        self.assertEqual(svc.plan_bump(existing, {"id": 2, "theme": "T1", "epic_rank": 1, "story_rank": 1}, 1), base + 1)

    def test_bumps_only_unpinned_upward_and_stamps_reason(self):
        existing = [
            {"id": 2, "priority": 3, "pinned": False, "theme": "T1", "epic": "1.1", "epic_rank": 1, "story_rank": 1, "order_key": 5.0},
            {"id": 3, "priority": 2, "pinned": True,  "theme": "T1", "epic": "1.1", "epic_rank": 1, "story_rank": 1, "order_key": 6.0},
            {"id": 4, "priority": 1, "pinned": False, "theme": "T1", "epic": "1.1", "epic_rank": 1, "story_rank": 1, "order_key": 7.0},
        ]
        deltas = [
            {"id": 2, "new_priority": 1, "reason": "blocks the new task"},  # apply P3->P1
            {"id": 3, "new_priority": 1, "reason": "x"},                    # pinned -> skip
            {"id": 4, "new_priority": 3, "reason": "x"},                    # demotion -> skip
        ]
        client = MagicMock()
        with patch.object(svc.config, "DEV_TASKS_REEVAL_ENABLED", True), \
             patch.object(svc.config, "DEV_TASKS_REEVAL_MAX_CHANGES", 5), \
             patch.object(svc, "_active_rows", return_value=existing), \
             patch.object(svc, "_reeval_llm", return_value=deltas), \
             patch.object(svc.db, "client", client):
            applied = svc.reevaluate({"id": 1, "priority": 1})
        self.assertEqual([a["id"] for a in applied], [2])
        upd = client.table.return_value.update.call_args.args[0]
        self.assertEqual(upd["priority"], 1)
        self.assertEqual(upd["bump_reason"], "blocks the new task")
        self.assertIn("order_key", upd)

    def test_cap_limits_changes(self):
        existing = [{"id": i, "priority": 3, "pinned": False, "theme": "T1", "epic": "1.1",
                     "epic_rank": 1, "story_rank": 1, "order_key": float(i)} for i in range(2, 8)]
        deltas = [{"id": i, "new_priority": 1, "reason": "r"} for i in range(2, 8)]
        with patch.object(svc.config, "DEV_TASKS_REEVAL_ENABLED", True), \
             patch.object(svc.config, "DEV_TASKS_REEVAL_MAX_CHANGES", 2), \
             patch.object(svc, "_active_rows", return_value=existing), \
             patch.object(svc, "_reeval_llm", return_value=deltas), \
             patch.object(svc.db, "client", MagicMock()):
            applied = svc.reevaluate({"id": 1, "priority": 1})
        self.assertEqual(len(applied), 2)   # capped


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

    def test_export_defaults_to_pdf(self):
        """The Export button sends no format — it must get the PDF, the one shape
        where the screenshots reliably travel."""
        pdf = (b"%PDF-1.4stub", "application/pdf", "willpowerlab-backlog.pdf")
        with patch.object(rt.svc, "export_pdf", return_value=pdf) as m_pdf, \
             patch.object(rt.svc, "export_bundle") as m_zip:
            r = self.client.get("/api/dev-tasks/export", headers=self._h())
        self.assertEqual(r.status_code, 200)
        self.assertIn("application/pdf", r.headers["Content-Type"])
        self.assertIn("willpowerlab-backlog.pdf", r.headers["Content-Disposition"])
        self.assertEqual(r.data, b"%PDF-1.4stub")
        m_pdf.assert_called_once()
        m_zip.assert_not_called()
        # the client reads the extension off this header, so it must be exposed
        self.assertIn("Content-Disposition", r.headers.get("Access-Control-Expose-Headers", ""))

    def test_export_markdown_download(self):
        bundle = (b"# backlog\n", "text/markdown", "willpowerlab-backlog.md")
        with patch.object(rt.svc, "export_bundle", return_value=bundle):
            r = self.client.get("/api/dev-tasks/export?format=md", headers=self._h())
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/markdown", r.headers["Content-Type"])
        self.assertIn("attachment", r.headers["Content-Disposition"])
        self.assertIn("willpowerlab-backlog.md", r.headers["Content-Disposition"])

    def test_export_zip_download_when_images_present(self):
        bundle = (b"PK\x03\x04stub", "application/zip", "willpowerlab-backlog.zip")
        with patch.object(rt.svc, "export_bundle", return_value=bundle):
            r = self.client.get("/api/dev-tasks/export?format=zip", headers=self._h())
        self.assertEqual(r.status_code, 200)
        self.assertIn("application/zip", r.headers["Content-Type"])
        self.assertIn("willpowerlab-backlog.zip", r.headers["Content-Disposition"])
        self.assertEqual(r.data, b"PK\x03\x04stub")

    def test_unknown_format_falls_back_to_pdf(self):
        pdf = (b"%PDF-1.4stub", "application/pdf", "willpowerlab-backlog.pdf")
        with patch.object(rt.svc, "export_pdf", return_value=pdf):
            r = self.client.get("/api/dev-tasks/export?format=docx", headers=self._h())
        self.assertIn("application/pdf", r.headers["Content-Type"])

    # ---- which format actually got served (so a surprise .zip explains itself) ----

    def test_pdf_response_reports_its_format_and_no_fallback(self):
        pdf = (b"%PDF-1.4stub", "application/pdf", "willpowerlab-backlog.pdf")
        with patch.object(rt.svc, "export_pdf", return_value=pdf):
            r = self.client.get("/api/dev-tasks/export", headers=self._h())
        self.assertEqual(r.headers["X-Export-Format"], "pdf")
        self.assertNotIn("X-Export-Fallback", r.headers)

    def test_zip_from_a_failed_pdf_is_flagged_as_a_fallback(self):
        """reportlab missing → export_pdf returns the ZIP. The client must be able to
        tell that apart from "the PDF build isn't deployed yet"."""
        zipped = (b"PK\x03\x04stub", "application/zip", "willpowerlab-backlog.zip")
        with patch.object(rt.svc, "export_pdf", return_value=zipped):
            r = self.client.get("/api/dev-tasks/export", headers=self._h())
        self.assertEqual(r.headers["X-Export-Format"], "zip")
        self.assertEqual(r.headers["X-Export-Fallback"], "1")

    def test_explicitly_requested_zip_is_not_flagged_as_a_fallback(self):
        zipped = (b"PK\x03\x04stub", "application/zip", "willpowerlab-backlog.zip")
        with patch.object(rt.svc, "export_bundle", return_value=zipped):
            r = self.client.get("/api/dev-tasks/export?format=zip", headers=self._h())
        self.assertEqual(r.headers["X-Export-Format"], "zip")
        self.assertNotIn("X-Export-Fallback", r.headers)

    def test_format_headers_are_exposed_to_the_browser(self):
        pdf = (b"%PDF-1.4stub", "application/pdf", "willpowerlab-backlog.pdf")
        with patch.object(rt.svc, "export_pdf", return_value=pdf):
            r = self.client.get("/api/dev-tasks/export", headers=self._h())
        exposed = r.headers.get("Access-Control-Expose-Headers", "")
        for h in ("Content-Disposition", "X-Export-Format", "X-Export-Fallback"):
            self.assertIn(h, exposed)

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


class _FakeTable:
    """Minimal Supabase table stub: records updates, replays canned selects."""

    def __init__(self, rows, writes):
        self._rows, self._writes, self._payload, self._id = rows, writes, None, None
        self.not_ = self

    def select(self, *_a, **_k):
        return self

    def is_(self, *_a, **_k):
        return self

    def in_(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def update(self, payload):
        self._payload = payload
        return self

    def eq(self, _col, value):
        self._id = value
        return self

    def execute(self):
        if self._payload is not None:
            self._writes.append((self._id, self._payload))
            self._payload = self._id = None
            return MagicMock(data=[])
        return MagicMock(data=self._rows)


class _FakeClient:
    def __init__(self, tasks, bugs):
        self.writes = []
        self._by_name = {"dev_tasks": tasks, "dev_bugs": bugs}

    def table(self, name):
        return _FakeTable(self._by_name[name], self.writes)


def _has_reportlab():
    try:
        import reportlab  # noqa: F401
        return True
    except Exception:  # pragma: no cover
        return False


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ExportPdfTests(unittest.TestCase):
    """The PDF is the one format where the screenshots are guaranteed to travel —
    a rich-text paste drops data: URI images in many targets (empty boxes)."""

    def _rows(self):
        rows = _simulate([_cls("T1", "1.1", "as a speaker I retry", body="first task"),
                          _cls("T2", "2.1", "as a coach I label", body="second task")])
        rows[0]["images"] = [_PNG_URL, _GIF_URL]
        return rows

    @unittest.skipUnless(_has_reportlab(), "needs reportlab")
    def test_pdf_is_a_valid_pdf_with_the_tasks_in_it(self):
        import io
        from pypdf import PdfReader
        payload, mime, name = svc.export_pdf(self._rows())
        self.assertEqual(mime, "application/pdf")
        self.assertEqual(name, "willpowerlab-backlog.pdf")
        self.assertTrue(payload.startswith(b"%PDF-"))
        reader = PdfReader(io.BytesIO(payload))
        self.assertGreaterEqual(len(reader.pages), 1)
        text = "\n".join(p.extract_text() for p in reader.pages)
        self.assertIn("as a speaker I retry", text)
        self.assertIn("as a coach I label", text)
        self.assertLess(text.index("first task"), text.index("second task"))  # priority order

    @unittest.skipUnless(_has_reportlab(), "needs reportlab")
    def test_screenshots_are_embedded_and_captioned_to_their_task(self):
        import io
        from pypdf import PdfReader
        payload, _, _ = svc.export_pdf(self._rows())
        reader = PdfReader(io.BytesIO(payload))
        embedded = 0
        for page in reader.pages:
            xobj = page.get("/Resources", {}).get("/XObject", {}) or {}
            embedded += sum(1 for k in xobj if xobj[k].get("/Subtype") == "/Image")
        self.assertEqual(embedded, 2)          # both of task 1's shots, really in the file
        text = "\n".join(p.extract_text() for p in reader.pages)
        self.assertIn("screenshot 1 · task #1", text)
        self.assertIn("screenshot 2 · task #1", text)

    @unittest.skipUnless(_has_reportlab(), "needs reportlab")
    def test_markup_in_task_text_cannot_break_the_render(self):
        rows = _simulate([_cls("T1", "1.1", "s", body="<b>x</b> & <script>y</script>")])
        payload, mime, _ = svc.export_pdf(rows)      # would raise if unescaped
        self.assertEqual(mime, "application/pdf")
        self.assertTrue(payload.startswith(b"%PDF-"))

    @unittest.skipUnless(_has_reportlab(), "needs reportlab")
    def test_no_images_still_produces_a_pdf(self):
        rows = _simulate([_cls("T1", "1.1", "s", body="text only")])
        payload, mime, _ = svc.export_pdf(rows)
        self.assertEqual(mime, "application/pdf")

    def test_falls_back_to_the_zip_when_reportlab_is_unavailable(self):
        """A missing or broken reportlab must not take Export down."""
        with patch.object(svc, "_render_pdf", side_effect=ImportError("no reportlab")):
            payload, mime, name = svc.export_pdf(self._rows())
        self.assertEqual(mime, "application/zip")
        self.assertEqual(name, "willpowerlab-backlog.zip")
        self.assertTrue(payload.startswith(b"PK"))


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class HydrateImagesTests(unittest.TestCase):
    """Read-time repair: an old task with an empty images array still Copies and
    Exports its bug's screenshots, with no backfill run first."""

    def _hydrate(self, tasks, bugs):
        client = _FakeClient(tasks, bugs)
        with patch.object(svc.db, "client", client):
            return svc.hydrate_images(tasks), client

    def test_empty_task_gets_its_bugs_images(self):
        rows, _ = self._hydrate(
            [{"id": 1, "bug_id": 3, "images": []}],
            [{"id": 3, "images": [_PNG_URL], "image_url": None}])
        self.assertEqual(rows[0]["images"], [_PNG_URL])

    def test_no_query_when_every_task_already_has_images(self):
        tasks = [{"id": 1, "bug_id": 3, "images": [_PNG_URL]}]
        client = _FakeClient(tasks, [])
        client.table = MagicMock(side_effect=AssertionError("must not query"))
        with patch.object(svc.db, "client", client):
            self.assertEqual(svc.hydrate_images(tasks), tasks)   # zero extra cost

    def test_task_without_bug_id_is_left_alone(self):
        rows, _ = self._hydrate([{"id": 1, "bug_id": None, "images": []}], [])
        self.assertEqual(rows[0]["images"], [])

    def test_a_failing_lookup_never_breaks_the_list(self):
        tasks = [{"id": 1, "bug_id": 3, "images": []}]
        broken = MagicMock()
        broken.table.side_effect = RuntimeError("supabase down")
        with patch.object(svc.db, "client", broken):
            self.assertEqual(svc.hydrate_images(tasks), tasks)

    def test_hydrated_task_exports_as_a_real_image_file(self):
        tasks = [{"id": 21, "bug_id": 3, "images": [], "order_key": 1.0,
                  "user_story": "s", "priority": 1, "body": "x"}]
        rows, _ = self._hydrate(tasks, [{"id": 3, "images": [_PNG_URL], "image_url": None}])
        payload, mime, _ = svc.export_bundle(rows)
        self.assertEqual(mime, "application/zip")
        import io
        import zipfile
        self.assertIn("images/task-21-1.png",
                      zipfile.ZipFile(io.BytesIO(payload)).namelist())


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class BackfillTaskImagesTests(unittest.TestCase):
    """scripts/backfill_dev_task_images.py — tasks generated before
    add_dev_tasks_images.sql have an empty images array even though their bug still
    has the screenshot. The backfill must fill exactly those and nothing else."""

    def _run(self, tasks, bugs, dry_run=False):
        import importlib
        bf = importlib.import_module("scripts.backfill_dev_task_images")
        client = _FakeClient(tasks, bugs)
        with patch.object(bf.db, "client", client):
            filled, skipped = bf.run_backfill(limit=100, dry_run=dry_run)
        return filled, skipped, client.writes

    def test_fills_an_empty_task_from_its_bug(self):
        filled, _, writes = self._run(
            tasks=[{"id": 7, "bug_id": 3, "images": [], "status": "active"}],
            bugs=[{"id": 3, "images": [_PNG_URL], "image_url": None}])
        self.assertEqual(filled, 1)
        self.assertEqual(writes, [(7, {"images": [_PNG_URL]})])

    def test_picks_up_the_legacy_single_image_url(self):
        """Bugs predating multi-image stored one `image_url`, not an array."""
        _, _, writes = self._run(
            tasks=[{"id": 8, "bug_id": 4, "images": [], "status": "active"}],
            bugs=[{"id": 4, "images": None, "image_url": _GIF_URL}])
        self.assertEqual(writes, [(8, {"images": [_GIF_URL]})])

    def test_task_that_already_has_images_is_untouched(self):
        filled, _, writes = self._run(
            tasks=[{"id": 9, "bug_id": 5, "images": [_PNG_URL], "status": "active"}],
            bugs=[{"id": 5, "images": [_GIF_URL], "image_url": None}])
        self.assertEqual((filled, writes), (0, []))     # idempotent: re-run is a no-op

    def test_bug_without_screenshots_is_skipped_not_written(self):
        filled, skipped, writes = self._run(
            tasks=[{"id": 10, "bug_id": 6, "images": [], "status": "active"}],
            bugs=[{"id": 6, "images": [], "image_url": None}])
        self.assertEqual((filled, skipped, writes), (0, 1, []))

    def test_deleted_bug_is_skipped_not_fatal(self):
        filled, skipped, writes = self._run(
            tasks=[{"id": 11, "bug_id": 999, "images": [], "status": "active"}],
            bugs=[])
        self.assertEqual((filled, skipped, writes), (0, 1, []))

    def test_archived_tasks_are_filled_too(self):
        """An archived task is still exportable history."""
        _, _, writes = self._run(
            tasks=[{"id": 12, "bug_id": 7, "images": [], "status": "archived"}],
            bugs=[{"id": 7, "images": [_PNG_URL], "image_url": None}])
        self.assertEqual(writes, [(12, {"images": [_PNG_URL]})])

    def test_dry_run_writes_nothing(self):
        filled, _, writes = self._run(
            tasks=[{"id": 13, "bug_id": 8, "images": [], "status": "active"}],
            bugs=[{"id": 8, "images": [_PNG_URL], "image_url": None}],
            dry_run=True)
        self.assertEqual((filled, writes), (1, []))

    def test_backfilled_task_then_exports_with_a_real_image_file(self):
        """End to end: the point of the backfill is that Export starts working."""
        task = {"id": 14, "bug_id": 9, "images": [], "status": "active",
                "order_key": 1.0, "user_story": "s", "priority": 1, "body": "x"}
        _, _, writes = self._run(tasks=[task],
                                 bugs=[{"id": 9, "images": [_PNG_URL], "image_url": None}])
        task["images"] = writes[0][1]["images"]          # apply what the backfill wrote
        payload, mime, _ = svc.export_bundle([task])
        self.assertEqual(mime, "application/zip")
        import io
        import zipfile
        z = zipfile.ZipFile(io.BytesIO(payload))
        self.assertIn("images/task-14-1.png", z.namelist())


if __name__ == "__main__":
    unittest.main()
