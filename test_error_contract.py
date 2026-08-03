"""services/error_contract.py — the backend ALWAYS answers JSON.

The FE parses ``{"code", "error"}`` on every failure path. Before the
catch-all existed only 413/405 were handled, so an unhandled exception (or
a plain 404) rendered Werkzeug's HTML page and the Next.js app crashed on
``JSON.parse`` — on exactly the responses it most needs to survive.

The load-bearing assertions here, in rough order of what would hurt most
if it silently regressed:

  * an unhandled exception is JSON 500, not HTML;
  * Sentry still SEES that exception (registering errorhandler(Exception)
    suppresses Flask's got_request_exception, which is how the sentry-sdk
    Flask integration normally captures — so the handler must capture
    explicitly, and this test is the only thing standing between us and a
    silently blind Sentry);
  * HTTPExceptions keep their own status (a 404 must not become a 500);
  * the pre-existing 413/405 handlers still win over the catch-all;
  * production never leaks exception internals in the body.

Flask-route classes skip locally when app deps are missing and run in CI
(house gotcha — keep assertions in sync with the module).

Run: python3 -m unittest test_error_contract
"""
from __future__ import annotations

import logging
import sys
import types
import unittest

# Stub heavy deps before services.* pulls supabase / sentry.
for _m in ("supabase", "sentry_sdk"):
    if _m not in sys.modules:
        sys.modules[_m] = types.ModuleType(_m)
if not hasattr(sys.modules["supabase"], "create_client"):
    sys.modules["supabase"].create_client = lambda *a, **k: None  # type: ignore[attr-defined]
    sys.modules["supabase"].Client = object  # type: ignore[attr-defined]
if not hasattr(sys.modules["sentry_sdk"], "capture_exception"):
    sys.modules["sentry_sdk"].capture_exception = lambda *a, **k: None  # type: ignore[attr-defined]

try:
    from flask import Flask, abort, jsonify
    from werkzeug.exceptions import RequestEntityTooLarge
    from services import error_contract
    _IMPORT_ERR = None
except Exception as e:  # pragma: no cover - env/bootstrap guard
    Flask = None
    abort = None
    jsonify = None
    RequestEntityTooLarge = None
    error_contract = None
    _IMPORT_ERR = e


class _Config:
    """Stands in for config.Config — only the fields the handlers read."""
    MAX_AUDIO_SIZE_MB = 25
    MAX_REFERENCE_VIDEO_SIZE_MB = 500
    is_production = False


@unittest.skipIf(_IMPORT_ERR is not None,
                 f"error-contract tests require flask: {_IMPORT_ERR}")
class ErrorContractTests(unittest.TestCase):
    def setUp(self):
        # The handler logs every crash with a traceback — correct in prod,
        # pure noise here, where crashing is the point of the fixture.
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)

    def _app(self, *, production: bool = False):
        app = Flask(__name__)
        cfg = _Config()
        cfg.is_production = production

        @app.route("/boom")
        def boom():
            raise RuntimeError("kaboom: secret internal detail")

        @app.route("/aborts")
        def aborts():
            abort(400, "you sent nonsense")

        @app.route("/big")
        def big():
            raise RequestEntityTooLarge()

        @app.route("/only-get", methods=["GET"])
        def only_get():
            return jsonify(ok=True)

        error_contract.register(app, cfg)
        return app

    # ── the whole point: never HTML ──────────────────────────────────────

    def test_unhandled_exception_is_json_500(self):
        r = self._app().test_client().get("/boom")
        self.assertEqual(r.status_code, 500)
        self.assertEqual(r.mimetype, "application/json")
        self.assertEqual(r.get_json()["code"], "INTERNAL_ERROR")
        self.assertEqual(r.get_json()["error"], "Internal server error")

    def test_unknown_path_is_json_404_not_html(self):
        r = self._app().test_client().get("/no-such-route")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.mimetype, "application/json")
        self.assertEqual(r.get_json()["code"], "NOT_FOUND")
        # Werkzeug's default description is browser copy — an API contract
        # gets the short status name instead.
        self.assertEqual(r.get_json()["error"], "Not Found")
        self.assertNotIn("spelling", r.get_data(as_text=True))

    def test_html_is_never_returned(self):
        client = self._app().test_client()
        for path in ("/boom", "/no-such-route", "/aborts"):
            with self.subTest(path=path):
                self.assertNotIn(b"<!doctype", client.get(path).data.lower())

    # ── HTTPExceptions keep their own status ─────────────────────────────

    def test_abort_keeps_its_status_and_description(self):
        r = self._app().test_client().get("/aborts")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["code"], "BAD_REQUEST")
        self.assertEqual(r.get_json()["error"], "you sent nonsense")

    def test_405_handler_still_wins_over_the_catch_all(self):
        r = self._app().test_client().post("/only-get")
        self.assertEqual(r.status_code, 405)
        self.assertEqual(r.get_json()["code"], "METHOD_NOT_ALLOWED")

    def test_413_handler_still_wins_over_the_catch_all(self):
        r = self._app().test_client().get("/big")
        self.assertEqual(r.status_code, 413)
        self.assertEqual(r.get_json()["code"], "PAYLOAD_TOO_LARGE")
        self.assertIn("25MB", r.get_json()["error"])

    # ── Sentry must still see crashes ────────────────────────────────────

    def test_unhandled_exception_is_captured_to_sentry(self):
        """errorhandler(Exception) suppresses got_request_exception, so the
        handler has to capture by hand. Without this the change would trade
        an HTML page for a blind Sentry."""
        seen = []
        sentry = sys.modules["sentry_sdk"]
        original = sentry.capture_exception
        sentry.capture_exception = lambda e, *a, **k: seen.append(e)
        try:
            self._app().test_client().get("/boom")
        finally:
            sentry.capture_exception = original
        self.assertEqual(len(seen), 1)
        self.assertIsInstance(seen[0], RuntimeError)

    def test_404_is_not_captured_to_sentry(self):
        seen = []
        sentry = sys.modules["sentry_sdk"]
        original = sentry.capture_exception
        sentry.capture_exception = lambda e, *a, **k: seen.append(e)
        try:
            self._app().test_client().get("/no-such-route")
        finally:
            sentry.capture_exception = original
        self.assertEqual(seen, [])

    # ── production must not leak internals ───────────────────────────────

    def test_production_hides_exception_detail(self):
        r = self._app(production=True).test_client().get("/boom")
        body = r.get_json()
        self.assertNotIn("detail", body)
        self.assertNotIn("secret internal detail", r.get_data(as_text=True))

    def test_non_production_surfaces_detail_for_debugging(self):
        body = self._app(production=False).test_client().get("/boom").get_json()
        self.assertIn("RuntimeError", body.get("detail", ""))

    # ── the debugger escape hatch ────────────────────────────────────────

    def test_propagate_exceptions_still_raises(self):
        """The local debug server and any caller that explicitly asks for
        propagation must still get a real traceback."""
        app = self._app()
        app.config["PROPAGATE_EXCEPTIONS"] = True
        with self.assertRaises(RuntimeError):
            app.test_client().get("/boom")

    # ── code derivation ──────────────────────────────────────────────────

    def test_http_error_code_names(self):
        from werkzeug.exceptions import (Forbidden, NotFound,
                                         ServiceUnavailable, Unauthorized)
        cases = [(NotFound(), "NOT_FOUND"), (Unauthorized(), "UNAUTHORIZED"),
                 (Forbidden(), "FORBIDDEN"),
                 (ServiceUnavailable(), "SERVICE_UNAVAILABLE")]
        for exc, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(error_contract.http_error_code(exc), expected)


if __name__ == "__main__":
    unittest.main()
