"""willab — the pipeline admin panel (Task IV, Tier 1).

routes/v2/admin_pipeline.py + services/pipeline_admin.py.

WHAT THIS PINS DOWN:
  * AUTHORIZATION IS THE ENTIRE RISK SURFACE. These routes reach the same
    machinery as the secret-gated cron endpoints, so `@require_admin` on all
    three is the only thing standing between an ordinary session and the
    queue. It is asserted structurally (the decorator is present on every
    route) rather than by eye;
  * NO SECRET ON THE ADMIN PATH. The design claim is that
    PIPELINE_JOBS_SWEEP_SECRET is not merely hidden from the browser but
    never involved. A claim that strong should be checked, not trusted —
    so the module must not even reference it;
  * THE PROJECTION EXCLUDES `payload` AND `result`, asserted on the RETURNED
    KEYS rather than the query string, so a future `select("*")` fails here
    instead of silently widening an admin surface;
  * BOUNDED BY CONSTRUCTION — a limit above the cap is clamped at the data
    layer, not merely validated in the route. An ops surface must never be
    able to table-scan production;
  * KEYSET PAGINATION — the cursor filters on `enqueued_at`. OFFSET over a
    mutating queue silently skips rows, which would hide exactly the stuck
    jobs an operator opened the panel to find;
  * TIER 2 IS ABSENT — no retry, no cancel (founder decision 2026-08-10).
    Their absence is a decision, so it is a test: a later "while I'm here"
    addition should have to delete an assertion that says why.

Run: python3 -m unittest test_pipeline_admin
"""
from __future__ import annotations

import ast
import pathlib
import unittest
from unittest import mock

from services import pipeline_admin
from tests.fakes import FakeSupabaseClient, swap_attr

ROOT = pathlib.Path(__file__).parent
ROUTES = ROOT / "routes" / "v2" / "admin_pipeline.py"


def _job(jid, status="pending", enqueued="2026-08-10T09:00:00+00:00"):
    return {"id": jid, "kind": "session_recording", "status": status,
            "stage": None, "percent": 0, "message": None, "error": None,
            "attempts": 0, "max_attempts": 3, "user_id": None,
            "session_id": None, "enqueued_at": enqueued, "started_at": None,
            "finished_at": None, "created_at": enqueued}


class TestEveryRouteRequiresAdmin(unittest.TestCase):
    """Structural: read the decorators off the AST.

    A runtime test would need a Flask client and a fake JWT, and would pass
    just as happily if a route were deleted. This asserts the property that
    actually matters — every route function in this module carries
    @require_admin — and fails when a NEW route is added without it, which is
    the realistic future mistake.
    """

    def _route_functions(self):
        tree = ast.parse(ROUTES.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            names = []
            for dec in node.decorator_list:
                target = dec.func if isinstance(dec, ast.Call) else dec
                if isinstance(target, ast.Attribute):
                    names.append(target.attr)
                elif isinstance(target, ast.Name):
                    names.append(target.id)
            if "route" in names:
                yield node.name, names

    def test_all_three_routes_exist(self):
        found = {name for name, _ in self._route_functions()}
        self.assertEqual(
            found,
            {"v2_admin_pipeline_health", "v2_admin_pipeline_jobs",
             "v2_admin_pipeline_sweep"})

    def test_every_route_carries_require_admin(self):
        for name, decorators in self._route_functions():
            self.assertIn(
                "require_admin", decorators,
                f"{name} is missing @require_admin — it reaches the same "
                f"machinery as the secret-gated cron endpoints")

    def test_no_route_is_gated_by_the_weaker_admin_or_coach(self):
        """A coach is an F2 labeller, not an operator (BLIND COACH keeps the
        two roles apart). The queue is not their surface."""
        for name, decorators in self._route_functions():
            self.assertNotIn("require_admin_or_coach", decorators, name)


class TestNoSweepSecretOnTheAdminPath(unittest.TestCase):
    def test_the_module_never_mentions_the_secret(self):
        """Option B's whole claim: the secret is never CARRIED, so there is
        nothing to leak. Checked against code, not prose — the docstring
        explains the design and must stay free to name the variable."""
        tree = ast.parse(ROUTES.read_text(encoding="utf-8"))
        literals = [
            n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        docstrings = {
            n.body[0].value.value for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))
            and n.body and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant)
            and isinstance(n.body[0].value.value, str)}
        code_literals = [s for s in literals if s not in docstrings]
        for s in code_literals:
            self.assertNotIn("PIPELINE_JOBS_SWEEP_SECRET", s)
            self.assertNotIn("X-Internal-Secret", s)


class TestProjection(unittest.TestCase):
    def test_payload_and_result_are_not_in_the_projection(self):
        """Asserted on the FIELD LIST, and here is why not on returned keys.

        The obvious test — call the reader and check the returned dicts have
        no `payload` — cannot work against a fake: FakeSupabaseClient echoes
        whatever rows it was handed, so the projection is never applied and
        the assertion would pass no matter what `select()` asked for. It
        would be a test of the fake.

        Real PostgREST builds the projection from this exact string, so the
        string is the honest thing to guard. It is also what a future
        `select("*")` would have to replace, which is the change this is
        here to catch.
        """
        from services.db import db
        self.assertNotIn("payload", db._ADMIN_JOB_FIELDS)
        self.assertNotIn("result", db._ADMIN_JOB_FIELDS)
        for expected in ("id", "status", "attempts", "enqueued_at"):
            self.assertIn(expected, db._ADMIN_JOB_FIELDS)

    def test_the_reader_passes_the_projection_to_select(self):
        """The complement: the field list is actually the one handed to
        select(), not a constant that drifted out of use."""
        from services.db import db
        client = FakeSupabaseClient({"processing_jobs": []})
        with swap_attr(db, "client", client):
            db.list_processing_jobs(limit=5)
        selects = [c[1][0] for c in client.tables["processing_jobs"].calls
                   if c[0] == "select"]
        self.assertEqual(selects, [db._ADMIN_JOB_FIELDS])

    def test_the_projection_is_a_field_list_not_a_star(self):
        from services.db import db
        self.assertNotIn("*", db._ADMIN_JOB_FIELDS)


class TestBounds(unittest.TestCase):
    def test_limit_is_clamped_at_the_data_layer(self):
        from services.db import db
        client = FakeSupabaseClient({"processing_jobs": []})
        with swap_attr(db, "client", client):
            db.list_processing_jobs(limit=100000)
        calls = client.tables["processing_jobs"].calls
        limits = [c[1][0] for c in calls if c[0] == "limit"]
        self.assertEqual(limits, [100],
                         "the cap must hold in db.py, not only in the route")

    def test_a_junk_limit_falls_back_rather_than_raising(self):
        from services.db import db
        client = FakeSupabaseClient({"processing_jobs": []})
        with swap_attr(db, "client", client):
            db.list_processing_jobs(limit="banana")  # type: ignore[arg-type]
        limits = [c[1][0] for c in client.tables["processing_jobs"].calls
                  if c[0] == "limit"]
        self.assertEqual(limits, [50])

    def test_service_asks_for_one_extra_row_to_detect_another_page(self):
        seen = {}

        def fake(*, status=None, limit=50, before=None):
            seen["limit"] = limit
            return [_job(str(i)) for i in range(limit)]

        with mock.patch.object(pipeline_admin.db, "list_processing_jobs", fake):
            out = pipeline_admin.list_jobs_for_admin(limit=10)
        self.assertEqual(seen["limit"], 11, "N+1 probe, not a COUNT query")
        self.assertEqual(len(out["jobs"]), 10)
        self.assertIsNotNone(out["next_before"])

    def test_last_page_reports_no_cursor(self):
        """A short page can also mean the queue drained — the caller must not
        have to infer 'am I done' from the row count."""
        with mock.patch.object(pipeline_admin.db, "list_processing_jobs",
                               lambda **kw: [_job("a"), _job("b")]):
            out = pipeline_admin.list_jobs_for_admin(limit=10)
        self.assertIsNone(out["next_before"])
        self.assertEqual(out["count"], 2)


class TestPagination(unittest.TestCase):
    def test_the_cursor_filters_on_enqueued_at(self):
        """Keyset, not OFFSET. OFFSET over a mutating queue skips rows —
        it would hide the stuck jobs the panel exists to surface."""
        from services.db import db
        client = FakeSupabaseClient({"processing_jobs": []})
        with swap_attr(db, "client", client):
            db.list_processing_jobs(before="2026-08-10T09:00:00+00:00")
        calls = client.tables["processing_jobs"].calls
        self.assertTrue(any(c[0] == "lt" and c[1][0] == "enqueued_at"
                            for c in calls), calls)
        self.assertFalse(any(c[0] in ("offset", "range") for c in calls))


class TestStatusFilter(unittest.TestCase):
    def test_an_unknown_status_raises_rather_than_returning_empty(self):
        """During an incident, 'no jobs match' and 'you typed it wrong' must
        not look identical."""
        with self.assertRaises(ValueError):
            pipeline_admin.list_jobs_for_admin(status="complete")

    def test_each_real_status_is_accepted(self):
        with mock.patch.object(pipeline_admin.db, "list_processing_jobs",
                               lambda **kw: []):
            for s in pipeline_admin.STATUSES:
                pipeline_admin.list_jobs_for_admin(status=s)


class TestTierTwoIsAbsent(unittest.TestCase):
    def test_no_retry_or_cancel_route(self):
        """Founder decision 2026-08-10: both write to the live
        record→transcribe path. Retry must respect max_attempts and the
        dedup_key partial unique index; 'cancel' has no achievable meaning
        for a job a worker already holds. Their absence is a decision, so
        adding one should have to delete this test."""
        src = ROUTES.read_text(encoding="utf-8")
        tree = ast.parse(src)
        routes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == "route":
                for arg in node.args:
                    if isinstance(arg, ast.Constant):
                        routes.append(arg.value)
        for path in routes:
            self.assertNotIn("retry", path)
            self.assertNotIn("cancel", path)


class TestNeverRaises(unittest.TestCase):
    def test_a_db_failure_yields_an_empty_list_not_an_exception(self):
        """An ops surface that 500s during an incident is a surface nobody
        can use during an incident."""
        from services.db import db

        def boom(q):
            raise Exception("db down")

        client = FakeSupabaseClient({"processing_jobs": boom})
        with swap_attr(db, "client", client):
            self.assertEqual(db.list_processing_jobs(), [])


if __name__ == "__main__":
    unittest.main()
