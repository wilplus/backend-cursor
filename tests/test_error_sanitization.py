"""P0 audit 2026-08-03 — nothing leaks to the client.

Covers the three findings in one place:
  * ``utils.errors.scrub`` actually removes the secret/path shapes it
    claims to;
  * the global handler answers JSON with generic copy and no exception
    text in a production-shaped environment;
  * ``safe_error`` keeps the ``{code, error}`` envelope the FE already
    parses, so this is a sanitization change and not a contract change.
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("JWT_SECRET", "test-secret-value-not-a-placeholder")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")

from flask import Flask  # noqa: E402

from utils.errors import (  # noqa: E402
    error_payload, register_error_handlers, safe_error, scrub,
)


class ScrubTests(unittest.TestCase):
    """Each case is a string we have actually seen in an error response."""

    def test_openai_key_is_redacted(self):
        out = scrub("AuthenticationError: bad key sk-proj-abc123DEF456ghi789")
        self.assertNotIn("abc123DEF456ghi789", out)
        self.assertIn("sk-***", out)

    def test_jwt_is_redacted(self):
        jwt = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
               "eyJyb2xlIjoic2VydmljZV9yb2xlIn0.s1gn4tur3v4lu3")
        out = scrub(f"PostgREST rejected token {jwt}")
        self.assertNotIn("s1gn4tur3v4lu3", out)
        self.assertIn("***jwt***", out)

    def test_postgres_dsn_credentials_are_redacted(self):
        out = scrub("could not connect: postgresql://user:secret-pass@db.host:5432/app")
        self.assertNotIn("secret-pass", out)

    def test_absolute_server_paths_are_redacted(self):
        out = scrub('File "/app/services/lab_recording.py", line 812, in process')
        self.assertNotIn("/app/services", out)

    def test_traceback_paths_are_redacted(self):
        out = scrub("/home/user/backend-cursor/routes/v2_routes.py:15821")
        self.assertNotIn("backend-cursor", out)

    def test_aws_access_key_id_is_redacted(self):
        out = scrub("InvalidAccessKeyId: AKIAIOSFODNN7EXAMPLE is not valid")
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", out)

    def test_authorization_header_is_redacted(self):
        out = scrub("request failed: Authorization: Bearer abc.def.ghi")
        self.assertNotIn("abc.def.ghi", out)

    def test_output_is_truncated(self):
        out = scrub("x" * 5000)
        self.assertLessEqual(len(out), 601)

    def test_none_is_safe(self):
        self.assertEqual(scrub(None), "")


class ErrorPayloadTests(unittest.TestCase):

    def setUp(self):
        self._env = os.environ.get("EXPOSE_ERROR_DETAILS")
        os.environ["EXPOSE_ERROR_DETAILS"] = "0"

    def tearDown(self):
        if self._env is None:
            os.environ.pop("EXPOSE_ERROR_DETAILS", None)
        else:
            os.environ["EXPOSE_ERROR_DETAILS"] = self._env

    def test_envelope_keeps_the_shape_the_frontend_parses(self):
        body = error_payload("RECORDING_ERROR", 500)
        self.assertEqual(body["code"], "RECORDING_ERROR")
        self.assertIsInstance(body["error"], str)
        self.assertTrue(body["ref"])

    def test_exception_text_is_absent_when_detail_is_off(self):
        exc = RuntimeError("connect to postgresql://u:p@prod-db/app failed")
        body = error_payload("DB_ERROR", 500, exc=exc)
        self.assertNotIn("detail", body)
        self.assertNotIn("prod-db", str(body))

    def test_detail_is_still_scrubbed_when_exposed(self):
        os.environ["EXPOSE_ERROR_DETAILS"] = "1"
        exc = RuntimeError("bad key sk-proj-SUPERSECRETVALUE123")
        body = error_payload("X", 500, exc=exc)
        self.assertIn("detail", body)
        self.assertNotIn("SUPERSECRETVALUE123", body["detail"])

    def test_extra_fields_ride_along(self):
        body = error_payload("TRAIN_FAILED", 500, extra={"run_id": "r-1"})
        self.assertEqual(body["run_id"], "r-1")


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

    def test_unknown_route_is_json_not_html(self):
        r = self.client.get("/no-such-route")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_json()["error"], "Not found.")

    def test_safe_error_hides_the_exception(self):
        r = self.client.get("/caught")
        self.assertEqual(r.status_code, 500)
        raw = r.get_data(as_text=True)
        self.assertNotIn("pw@prod", raw)
        self.assertEqual(r.get_json()["code"], "V2_ERROR")

    def test_every_error_carries_a_correlation_ref(self):
        # The ref is what makes generic copy supportable: the user reads
        # it off the screen, we find the real exception in the logs.
        self.assertTrue(self.client.get("/boom").get_json()["ref"])


class PropagationTests(unittest.TestCase):
    """The catch-all must not swallow exceptions in tests / debug."""

    def test_testing_mode_still_raises(self):
        app = Flask(__name__)
        app.testing = True
        register_error_handlers(app)

        @app.route("/boom")
        def boom():
            raise RuntimeError("should reach the test runner")

        with self.assertRaises(RuntimeError):
            app.test_client().get("/boom")


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

    def test_no_route_returns_subprocess_output(self):
        offenders = []
        for path in self.ROUTE_FILES:
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as fh:
                for n, line in enumerate(fh, 1):
                    stripped = line.strip()
                    if stripped.startswith("#"):
                        continue
                    if ('"stderr"' in stripped or '"stdout"' in stripped
                            or "_stdout\":" in stripped):
                        offenders.append(f"{path}:{n}: {stripped[:90]}")
        self.assertEqual(
            offenders, [],
            "subprocess output returned to a client (argv + absolute "
            "paths):\n" + "\n".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
