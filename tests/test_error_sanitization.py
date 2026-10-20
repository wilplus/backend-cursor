"""
STORY    As a speaker, I want any error to show me only generic text, with no
         internal paths or secrets, even if a deploy setting is wrong, so that
         nothing private leaks to my browser.
OUTCOME
  O1  An unexpected error answers 500 with a generic JSON code and none of the
      error's text, file paths or keys.
  O2  A deployed app with debug switched on still leaks no key, path or
      traceback.
  O3  No route file hands raw exception text back to the browser.
PROVES   O1 -> GlobalHandlerTests::test_uncaught_exception_returns_generic_json
         O2 -> DeployedNeverReRaisesTests::test_a_deployed_app_with_debug_on_leaks_nothing
         O3 -> RouteSweepTests::test_no_route_returns_raw_exception_text
WHY      P0 audit 2026-08-03: nothing leaks to the client.
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("JWT_SECRET", "test-secret-value-not-a-placeholder")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")

from flask import Flask  # noqa: E402

from utils.errors import (  # noqa: E402
    register_error_handlers,
    safe_error,
)


class GlobalHandlerTests(unittest.TestCase):
    """A production-shaped app: PROPAGATE_EXCEPTIONS off, detail off."""

    def setUp(self):
        self._env = os.environ.get("EXPOSE_ERROR_DETAILS")
        os.environ["EXPOSE_ERROR_DETAILS"] = "0"

        app = Flask(__name__)
        app.config["PROPAGATE_EXCEPTIONS"] = False
        register_error_handlers(app)

        @app.route("/boom")
        def boom():
            raise RuntimeError(
                'File "/app/services/db.py" line 9: key sk-proj-LEAKME12345'
            )

        @app.route("/caught")
        def caught():
            try:
                raise ValueError("postgresql://u:pw@prod/db unreachable")
            except ValueError as e:
                return safe_error("V2_ERROR", 500, exc=e)

        self.client = app.test_client()

    def tearDown(self):
        if self._env is None:
            os.environ.pop("EXPOSE_ERROR_DETAILS", None)
        else:
            os.environ["EXPOSE_ERROR_DETAILS"] = self._env

    def test_uncaught_exception_returns_generic_json(self):
        r = self.client.get("/boom")
        self.assertEqual(r.status_code, 500)
        body = r.get_json()
        self.assertEqual(body["code"], "INTERNAL_ERROR")
        raw = r.get_data(as_text=True)
        self.assertNotIn("LEAKME12345", raw)
        self.assertNotIn("/app/services", raw)
        self.assertNotIn("RuntimeError", raw)


class RouteSweepTests(unittest.TestCase):
    """Regression guard: the pattern must not come back.

    A grep test is blunt, but this specific leak was reintroduced by
    copy-paste from a neighbouring handler more than once — the whole
    reason it survived to a P0 audit.
    """

    ROUTE_FILES = [
        "routes/admin.py", "routes/auth.py", "routes/dev_bugs.py",
        "routes/dev_tasks.py", "routes/internal_webhooks.py",
        "routes/recordings.py", "routes/snippet_labels_routes.py",
        "routes/user.py", "routes/v2_routes.py", "routes/life_routes.py",
        "routes/journal.py", "routes/token_routes.py", "routes/jobs.py",
    ]

    def test_no_route_returns_raw_exception_text(self):
        import re

        pattern = re.compile(r'jsonify\([^)]*"error":\s*(?:f?")?[^)]*'
                             r'str\((?:e|exc|err)\)')
        offenders = []
        for path in self.ROUTE_FILES:
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as fh:
                for n, line in enumerate(fh, 1):
                    if pattern.search(line):
                        offenders.append(f"{path}:{n}")
        self.assertEqual(
            offenders, [],
            "raw exception text returned to a client — use "
            "utils.errors.safe_error instead:\n" + "\n".join(offenders),
        )


class DeployedNeverReRaisesTests(unittest.TestCase):
    """A deploy must not be able to lose its error net to an env var.

    Flask resolves DEBUG from FLASK_DEBUG at construction, not only from
    `flask run --debug`. While `app.debug` was part of the propagation test,
    one stray variable on a production host did two things silently: removed
    this net, and replaced the sanitized envelope with Flask's HTML page —
    tracebacks, absolute paths and any secret echoed in the exception text,
    straight to the browser, with no `ref` for support to join on.

    That is the leak the module docstring exists to prevent, so it is pinned
    here rather than left to a code comment.
    """

    def _app(self, *, debug, deployed, testing=False, propagate=None):
        from unittest.mock import patch
        app = Flask(__name__)
        app.debug = debug
        app.testing = testing
        if propagate is not None:
            app.config["PROPAGATE_EXCEPTIONS"] = propagate
        with patch("utils.errors._is_deployed", return_value=deployed):
            register_error_handlers(app)

        @app.route("/boom")
        def boom():
            raise RuntimeError('File "/app/x.py": key sk-proj-LEAKME12345')

        return app, patch("utils.errors._is_deployed", return_value=deployed)


    def test_a_deployed_app_with_debug_on_leaks_nothing(self):
        app, deployed = self._app(debug=True, deployed=True)
        with deployed:
            res = app.test_client().get("/boom")
        blob = res.get_data(as_text=True)
        self.assertNotIn("sk-proj-LEAKME12345", blob)
        self.assertNotIn("/app/x.py", blob)
        self.assertNotIn("Traceback", blob)


if __name__ == "__main__":
    unittest.main()
