"""services/rate_limits.py — the cap on the paid Whisper/LLM routes.

Every authenticated Whisper/LLM endpoint used to be uncapped, so a client
retry loop could run the OpenAI bill up unchecked. These tests pin the two
things that make the cap worth having:

  * it actually stops a loop, and answers the JSON error contract when it
    does (429 / RATE_LIMITED / retry_after_seconds + Retry-After);
  * it can NEVER take the live loop down — a missing package, a disabled
    flag, a dead broker and an unset REDIS_URL all degrade to serving, not
    to 500s.

Plus the two behaviours a careless refactor would quietly lose: CORS
preflights must not spend the user's budget (a browser sends OPTIONS before
every cross-origin POST, so counting them halves every cap), and
undecorated routes — health probes, cron webhooks, the FE's polling GETs —
must stay unlimited.

Each test reloads the module so it gets a fresh Limiter + empty storage;
the limiter is a process-wide singleton in production, which is correct
there and hermetic-hostile here.

Flask-route classes skip locally when app deps are missing and run in CI
(house gotcha — keep assertions in sync with the module).

Run: python3 -m unittest test_rate_limits
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import types
import unittest
from unittest.mock import patch

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
    import jwt
    from flask import Flask, jsonify
    from utils.errors import register_error_handlers
    from utils import errors as errors_mod
    from services import rate_limits as rl
    _IMPORT_ERR = None
    if isinstance(rl.limiter, rl._NullLimiter):
        # flask_limiter absent — the module degraded to no-op decorators, so
        # there is no limiting behaviour to assert here.
        _IMPORT_ERR = RuntimeError("flask_limiter unavailable")
except Exception as e:  # pragma: no cover - env/bootstrap guard
    jwt = None
    Flask = None
    jsonify = None
    register_error_handlers = None
    errors_mod = None
    rl = None
    _IMPORT_ERR = e


def _bearer(sub: str) -> dict:
    """An Authorization header for ``sub``. The limiter reads the subject
    WITHOUT verifying the signature, so any well-formed JWT will do."""
    return {"Authorization": f"Bearer {jwt.encode({'sub': sub}, 'k', algorithm='HS256')}"}


@unittest.skipIf(_IMPORT_ERR is not None,
                 f"rate-limit tests require flask + flask_limiter: {_IMPORT_ERR}")
class _Base(unittest.TestCase):
    #: env every test starts from — no REDIS_URL, so storage is memory://
    ENV = {"RATE_LIMIT_ENABLED": "1"}

    def setUp(self):
        self._env = patch.dict(os.environ, self.ENV, clear=False)
        self._env.start()
        for var in ("REDIS_URL", "RATE_LIMIT_STORAGE_URI", "RATE_LIMIT_WHISPER",
                    "RATE_LIMIT_LLM", "RATE_LIMIT_HEAVY",
                    "RATE_LIMIT_REGENERATE"):
            if var not in self.ENV:
                os.environ.pop(var, None)
        # Fresh Limiter + empty counters per test.
        self.rl = importlib.reload(rl)
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)
        self.addCleanup(self._env.stop)

    def _app(self, build):
        """``build(app, rl)`` registers the views; we wire the limiter and
        the app-wide error net exactly the way app.py does — init_app
        installs the 429 handler, utils.errors nets everything else."""
        app = Flask(f"t{id(self)}")
        build(app, self.rl)
        self.rl.init_app(app)
        register_error_handlers(app)
        return app


class CapTests(_Base):
    ENV = {"RATE_LIMIT_ENABLED": "1", "RATE_LIMIT_LLM": "3 per minute"}

    def _llm_app(self):
        def build(app, r):
            @app.route("/llm", methods=["POST"])
            @r.llm_limit
            def llm():
                return jsonify(ok=True)

            @app.route("/free", methods=["POST"])
            def free():
                return jsonify(ok=True)
        return self._app(build)

    def test_cap_stops_a_loop(self):
        c = self._llm_app().test_client()
        codes = [c.post("/llm").status_code for _ in range(6)]
        self.assertEqual(codes, [200, 200, 200, 429, 429, 429])

    def test_429_answers_the_json_error_contract(self):
        c = self._llm_app().test_client()
        for _ in range(3):
            c.post("/llm")
        r = c.post("/llm")
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.mimetype, "application/json")
        body = r.get_json()
        self.assertEqual(body["code"], "RATE_LIMITED")
        # Generic copy comes from utils.errors' status table — one source of
        # truth, so this can't drift away from the rest of the API.
        self.assertEqual(body["error"], errors_mod._STATUS_COPY[429])
        self.assertGreaterEqual(body["retry_after_seconds"], 1)
        self.assertEqual(r.headers["Retry-After"],
                         str(body["retry_after_seconds"]))
        # utils.errors' correlation id must survive our custom handler —
        # it is the join key between this response, the log line and Sentry.
        self.assertRegex(body["ref"], r"^[0-9a-f]{8}$")

    def test_429_body_never_leaks_the_limit_expression(self):
        """"3 per 1 minute" is flask-limiter's internal description, not
        copy we show anyone."""
        c = self._llm_app().test_client()
        for _ in range(4):
            r = c.post("/llm")
        self.assertNotIn("per 1 minute", r.get_data(as_text=True))

    def test_successful_responses_carry_no_retry_after(self):
        """flask-limiter's header injection stamps Retry-After on 200s too.
        A FE that backs off on "is Retry-After present?" would then throttle
        itself on every success — so headers stay off by default."""
        r = self._llm_app().test_client().post("/llm")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.headers.get("Retry-After"))

    def test_budget_headers_are_opt_in(self):
        with patch.dict(os.environ, {"RATE_LIMIT_HEADERS": "1"}):
            self.rl = importlib.reload(rl)
            r = self._llm_app().test_client().post("/llm")
        self.assertEqual(r.headers.get("X-RateLimit-Limit"), "3")

    def test_undecorated_routes_are_never_capped(self):
        """Health probes, cron webhooks and polling GETs live here."""
        c = self._llm_app().test_client()
        self.assertEqual({c.post("/free").status_code for _ in range(30)},
                         {200})

    def test_cors_preflight_does_not_spend_the_budget(self):
        """A browser sends OPTIONS before every cross-origin POST. If those
        counted, every cap would be half what it says."""
        c = self._llm_app().test_client()
        for _ in range(10):
            c.open("/llm", method="OPTIONS")
        self.assertEqual(c.post("/llm").status_code, 200)


class KeyingTests(_Base):
    ENV = {"RATE_LIMIT_ENABLED": "1", "RATE_LIMIT_LLM": "2 per minute"}

    def _app_with_llm(self):
        def build(app, r):
            @app.route("/llm", methods=["POST"])
            @r.llm_limit
            def llm():
                return jsonify(ok=True)
        return self._app(build)

    def test_one_user_cannot_spend_anothers_budget(self):
        c = self._app_with_llm().test_client()
        for _ in range(2):
            self.assertEqual(c.post("/llm", headers=_bearer("user-a")).status_code, 200)
        self.assertEqual(c.post("/llm", headers=_bearer("user-a")).status_code, 429)
        # A different signed-in user is unaffected.
        self.assertEqual(c.post("/llm", headers=_bearer("user-b")).status_code, 200)

    def test_same_user_shares_one_bucket_across_ips(self):
        """Keying on the subject (not the IP) is what makes the cap mean
        something — otherwise a loop just rotates its source address."""
        c = self._app_with_llm().test_client()
        head = _bearer("user-a")
        for ip in ("1.1.1.1", "2.2.2.2"):
            self.assertEqual(
                c.post("/llm", headers={**head, "X-Forwarded-For": ip}).status_code,
                200)
        self.assertEqual(
            c.post("/llm", headers={**head, "X-Forwarded-For": "3.3.3.3"}).status_code,
            429)

    def test_anonymous_callers_fall_back_to_ip(self):
        c = self._app_with_llm().test_client()
        for _ in range(2):
            c.post("/llm", headers={"X-Forwarded-For": "9.9.9.9"})
        self.assertEqual(
            c.post("/llm", headers={"X-Forwarded-For": "9.9.9.9"}).status_code, 429)
        self.assertEqual(
            c.post("/llm", headers={"X-Forwarded-For": "8.8.8.8"}).status_code, 200)

    def test_garbage_bearer_token_does_not_raise(self):
        """A key function that throws would 500 every request on the route."""
        c = self._app_with_llm().test_client()
        r = c.post("/llm", headers={"Authorization": "Bearer not-a-jwt"})
        self.assertEqual(r.status_code, 200)


class RegenerateTests(_Base):
    """The icebreaker double-click guard: one per session per minute,
    overridable with force=true."""

    def _regen_app(self):
        def build(app, r):
            @app.route("/s/<session_id>/regen", methods=["POST"])
            @r.regenerate_limit
            def regen(session_id):
                return jsonify(ok=True)
        return self._app(build)

    def test_second_click_on_the_same_session_is_capped(self):
        c = self._regen_app().test_client()
        self.assertEqual(c.post("/s/abc/regen", json={}).status_code, 200)
        r = c.post("/s/abc/regen", json={})
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.get_json()["error"], self.rl.REGENERATE_MESSAGE)
        self.assertGreaterEqual(r.get_json()["retry_after_seconds"], 1)

    def test_other_sessions_are_independent(self):
        c = self._regen_app().test_client()
        c.post("/s/abc/regen", json={})
        self.assertEqual(c.post("/s/xyz/regen", json={}).status_code, 200)

    def test_force_bypasses_the_guard(self):
        c = self._regen_app().test_client()
        c.post("/s/abc/regen", json={})
        self.assertEqual(c.post("/s/abc/regen", json={"force": True}).status_code, 200)

    def test_force_must_be_the_boolean_true(self):
        c = self._regen_app().test_client()
        c.post("/s/abc/regen", json={})
        self.assertEqual(c.post("/s/abc/regen", json={"force": "yes"}).status_code, 429)


class DecoratorStackTests(_Base):
    """The production shape: a Blueprint, and the limit decorator sitting
    ABOVE an auth decorator.

    flask-limiter resolves a request's limits by ``module.qualname`` of the
    registered view, so the whole stack has to preserve those through
    ``functools.wraps``. It does — but silently: get it wrong and the cap
    simply never applies, with nothing failing anywhere. Hence this test.
    """

    ENV = {"RATE_LIMIT_ENABLED": "1", "RATE_LIMIT_LLM": "2 per minute"}

    def test_limit_applies_through_an_auth_wrapper_on_a_blueprint(self):
        from functools import wraps
        from flask import Blueprint, request

        def require_auth(f):  # same shape as auth.require_auth
            @wraps(f)
            def decorated(*a, **kw):
                if not request.headers.get("Authorization"):
                    return jsonify(code="UNAUTHORIZED"), 401
                return f(*a, **kw)
            return decorated

        r = self.rl
        bp = Blueprint("v2", __name__)

        @bp.route("/paid", methods=["POST"])
        @r.llm_limit
        @require_auth
        def paid():
            return jsonify(ok=True)

        app = Flask(f"stack{id(self)}")
        app.register_blueprint(bp)
        r.init_app(app)
        register_error_handlers(app)

        c = app.test_client()
        head = _bearer("user-stack")
        self.assertEqual([c.post("/paid", headers=head).status_code
                          for _ in range(3)], [200, 200, 429])

    def test_limit_is_spent_even_when_the_view_rejects(self):
        """The limiter runs before the view, so an unauthenticated flood
        can't probe a paid route for free."""
        from functools import wraps
        from flask import request

        def require_auth(f):
            @wraps(f)
            def decorated(*a, **kw):
                if not request.headers.get("Authorization"):
                    return jsonify(code="UNAUTHORIZED"), 401
                return f(*a, **kw)
            return decorated

        def build(app, r):
            @app.route("/paid", methods=["POST"])
            @r.llm_limit
            @require_auth
            def paid():
                return jsonify(ok=True)

        c = self._app(build).test_client()
        head = {"X-Forwarded-For": "4.4.4.4"}
        self.assertEqual([c.post("/paid", headers=head).status_code
                          for _ in range(3)], [401, 401, 429])


class WrappedTransparencyTests(_Base):
    """``route.__wrapped__(...)`` must still reach the UNDECORATED handler.

    39 test modules and 112 call sites in this repo invoke a route that way
    to run the handler without auth. ``functools.wraps`` points
    ``__wrapped__`` at whatever was wrapped, so a limiter stacked above
    ``@require_auth`` silently makes it the AUTH wrapper — and every one of
    those calls becomes a 401 against a mock that never sees a request.

    That is not hypothetical: it took out 47 tests on this branch's first
    CI run. These tests are the guard.
    """

    def _auth_stack(self):
        """The production shape: limit above an auth decorator that 401s."""
        from functools import wraps

        def require_auth(f):
            @wraps(f)
            def decorated(*a, **kw):
                return jsonify(code="UNAUTHORIZED"), 401
            return decorated

        def handler():
            return "HANDLER"

        return handler, require_auth(handler)

    def test_wrapped_skips_past_the_limiter_and_the_auth_wrapper(self):
        handler, authed = self._auth_stack()
        for tier in ("llm_limit", "whisper_limit", "heavy_limit"):
            with self.subTest(tier=tier):
                view = getattr(self.rl, tier)(authed)
                self.assertIs(view.__wrapped__, handler)
                self.assertEqual(view.__wrapped__(), "HANDLER")

    def test_wrapped_survives_stacked_limit_decorators(self):
        """Regenerate remains transparent when stacked under llm."""
        handler, authed = self._auth_stack()
        def factory(f):
            return self.rl.llm_limit(self.rl.regenerate_limit(f))
        self.assertEqual(factory(authed).__wrapped__(), "HANDLER")

    def test_undecorated_handler_keeps_pointing_at_itself(self):
        """No inner decorator to skip — __wrapped__ is the handler."""
        def handler():
            return "HANDLER"
        self.assertEqual(self.rl.llm_limit(handler).__wrapped__(), "HANDLER")

    def test_the_runtime_order_is_still_limit_then_auth(self):
        """Transparency is a metadata fix — it must not reorder the stack.

        The limiter still runs FIRST, so an unauthenticated flood spends its
        budget instead of probing a paid route for free: 401, 401, then 429.
        """
        with patch.dict(os.environ, {"RATE_LIMIT_LLM": "2 per minute"}):
            self.rl = importlib.reload(rl)
            _handler, authed = self._auth_stack()

            def build(app, r):
                app.add_url_rule("/paid", "paid", r.llm_limit(authed),
                                 methods=["POST"])

            c = self._app(build).test_client()
            codes = [c.post("/paid").status_code for _ in range(3)]
        self.assertEqual(codes, [401, 401, 429])


try:
    import routes.v2_routes as _v2_mod
    import routes.life_routes as _life_mod
    _ROUTES_ERR = None
except Exception as e:  # pragma: no cover - needs the full app deps
    _v2_mod = _life_mod = None
    _ROUTES_ERR = e


@unittest.skipIf(_ROUTES_ERR is not None,
                 f"route-module tests need the app deps: {_ROUTES_ERR}")
class RealRouteTransparencyTests(unittest.TestCase):
    """The same guard as WrappedTransparencyTests, but on the REAL routes.

    That class proves the decorators behave; this one proves they were
    APPLIED that way on every capped route — which is what the 47 failing
    tests actually depended on.
    """

    def test_every_capped_route_exposes_its_raw_handler(self):
        # Iterate EVERY registry bucket (the /v2 layer is split across
        # routes/v2_routes.py + routes/v2/* since the god-file split).
        # routes.v2_routes re-exports every moved handler, so resolving the
        # v2 buckets through it also re-verifies the re-export surface the
        # suite's `v2.<handler>.__wrapped__()` convention depends on.
        capped = {}
        for path, expected in CoveredRoutesTests.EXPECTED.items():
            mod = _life_mod if path == "routes/life_routes.py" else _v2_mod
            for name in expected:
                capped[name] = mod
        self.assertGreaterEqual(len(capped), 30, "route list went stale")
        for name, mod in capped.items():
            with self.subTest(route=name):
                view = getattr(mod, name, None)
                self.assertIsNotNone(view, f"{name} disappeared")
                inner = getattr(view, "__wrapped__", None)
                self.assertIsNotNone(inner, f"{name} lost __wrapped__")
                # The raw handler wraps nothing further. Anything else means
                # a decorator layer leaked into the test convention.
                self.assertIsNone(
                    getattr(inner, "__wrapped__", None),
                    f"{name}.__wrapped__ is still a wrapper — route tests "
                    f"calling {name}.__wrapped__() will hit auth, not the "
                    f"handler")


class CoveredRoutesTests(unittest.TestCase):
    """Drift guard: the routes that spend money on OpenAI must carry a cap.

    Static (AST) on purpose — it needs no app deps, so it runs everywhere
    and fails loudly if a decorator is dropped or a handler renamed. It
    does NOT claim the list is exhaustive; it claims these specific paid
    surfaces stay covered.
    """

    # The /v2 route layer is split across routes/v2_routes.py and the domain
    # modules under routes/v2/ (god-file split). Handlers are keyed by the
    # file that OWNS them now — every (handler, decorator) pair below is
    # unchanged from the registry's introduction; only the path keys moved
    # with the code.
    EXPECTED = {
        "routes/v2/lab_recording.py": {
            "v2_lab_create_recording": "whisper_limit",
            "v2_lab_presentation_extract": "heavy_limit",
        },
        "routes/v2/coach.py": {
            "v2_coach_annotation_upload": "whisper_limit",
            "v2_coach_training_import": "whisper_limit",
            "v2_coach_put_say_it_stronger": "llm_limit",
            "v2_coach_verify_ideal_text": "heavy_limit",
            "v2_coach_approve_ideal_text": "heavy_limit",
            "v2_coach_session_recut": "heavy_limit",
            "v2_coach_session_video": "heavy_limit",
        },
        "routes/v2/user_chat.py": {
            "v2_user_chat_first_question": "llm_limit",
        },
        "routes/v2/coaching.py": {
            "v2_chat_query": "llm_limit",
            "v2_chat_snippet_followup": "llm_limit",
            "v2_coaching_intro_bubble": "llm_limit",
            "v2_coaching_state_machine_turn": "llm_limit",
            "v2_coaching_turn": "llm_limit",
            "v2_onboarding_opener_next": "llm_limit",
            "v2_onboarding_opener_start": "llm_limit",
        },
        "routes/v2/admin.py": {
            "v2_admin_regenerate_next_session_icebreaker": "regenerate_limit",
            "v2_admin_suggest_directives_queue": "llm_limit",
        },
        "routes/v2/explore_ideal_text.py": {
            "v2_explore_save_ideal_text": "llm_limit",
            "v2_explore_decide_block": "llm_limit",
            "v2_explore_decide_prior_take": "llm_limit",
        },
        "routes/life_routes.py": {
            "life_board": "llm_limit",
            "life_note_create": "llm_limit",
            "life_case_create": "llm_limit",
            "life_lookup": "llm_limit",
            "life_proposal_approve": "llm_limit",
            "life_setup_complete": "heavy_limit",
            "life_setup_propose_from_document": "heavy_limit",
            "life_wins_derive": "heavy_limit",
        },
    }

    def test_paid_routes_carry_their_limit_decorator(self):
        import ast
        import os
        root = os.path.dirname(os.path.abspath(__file__))
        for path, expected in self.EXPECTED.items():
            with open(os.path.join(root, path)) as fh:
                tree = ast.parse(fh.read())
            found = {
                n.name: {d.id for d in n.decorator_list
                         if isinstance(d, ast.Name)}
                for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
            }
            for handler, decorator in expected.items():
                with self.subTest(path=path, handler=handler):
                    self.assertIn(handler, found,
                                  f"{path}: handler {handler} is gone — if it "
                                  f"moved, move its cap with it")
                    self.assertIn(decorator, found[handler],
                                  f"{path}: {handler} lost @{decorator} — that "
                                  f"route spends money on OpenAI")

    def test_no_in_process_rate_limit_dicts_remain(self):
        """Both per-worker dicts were replaced by the shared limiter. A new
        one would quietly reintroduce the `cap x workers` bug."""
        import os
        root = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(root, "routes/v2_routes.py")) as fh:
            source = fh.read()
        for ghost in ("_icebreaker_regen_last",
                      "_ICEBREAKER_REGEN_RATE_LIMIT_SEC"):
            with self.subTest(ghost=ghost):
                self.assertNotIn(f"{ghost} =", source)


class ConfigTests(_Base):
    def test_storage_prefers_explicit_uri_then_redis_then_memory(self):
        with patch.dict(os.environ, {"RATE_LIMIT_STORAGE_URI": "redis://explicit:6379",
                                     "REDIS_URL": "redis://queue:6379"}):
            self.assertEqual(self.rl.storage_uri(), "redis://explicit:6379")
        with patch.dict(os.environ, {"REDIS_URL": "redis://queue:6379"}):
            os.environ.pop("RATE_LIMIT_STORAGE_URI", None)
            self.assertEqual(self.rl.storage_uri(), "redis://queue:6379")
            self.assertTrue(self.rl.is_durable())
        os.environ.pop("REDIS_URL", None)
        os.environ.pop("RATE_LIMIT_STORAGE_URI", None)
        self.assertEqual(self.rl.storage_uri(), "memory://")
        self.assertFalse(self.rl.is_durable())

    def test_socket_timeouts_are_set(self):
        """Measured, not theoretical: a blackholed broker with no socket
        timeout blocks every request forever."""
        self.assertGreater(self.rl.STORAGE_OPTIONS["socket_connect_timeout"], 0)
        self.assertGreater(self.rl.STORAGE_OPTIONS["socket_timeout"], 0)

    def test_tier_values_come_from_env(self):
        with patch.dict(os.environ, {"RATE_LIMIT_LLM": "7 per second"}):
            self.assertEqual(self.rl.llm_limit_value(), "7 per second")
        with patch.dict(os.environ, {"RATE_LIMIT_LLM": "  "}):
            self.assertEqual(self.rl.llm_limit_value(), self.rl.DEFAULT_LLM_LIMIT)

class LiveLoopTests(_Base):
    """CLAUDE.md's hard fence: the limiter must never be the reason a
    request fails. Each of these is a way it could have been."""

    def _probe_app(self):
        def build(app, r):
            @app.route("/llm", methods=["POST"])
            @r.llm_limit
            def llm():
                return jsonify(ok=True)
        return self._app(build)

    def test_disabled_flag_serves_everything(self):
        with patch.dict(os.environ, {"RATE_LIMIT_ENABLED": "0"}):
            self.rl = importlib.reload(rl)
            c = self._probe_app().test_client()
            self.assertEqual({c.post("/llm").status_code for _ in range(80)},
                             {200})

    def test_unreachable_broker_still_serves(self):
        """Connection refused on every counter read — requests must flow."""
        with patch.dict(os.environ, {"RATE_LIMIT_STORAGE_URI": "redis://127.0.0.1:1/0"}):
            self.rl = importlib.reload(rl)
            self.assertEqual(self._probe_app().test_client().post("/llm").status_code,
                             200)

    def test_init_app_never_raises(self):
        """A limiter that cannot start must not stop the app from booting."""
        with patch.dict(os.environ, {"RATE_LIMIT_STORAGE_URI": "not-a-real-scheme://x"}):
            self.rl = importlib.reload(rl)
            app = Flask("boot-probe")
            self.rl.init_app(app)  # must not raise

            @app.route("/ping")
            def ping():
                return jsonify(ok=True)
            register_error_handlers(app)
            self.assertEqual(app.test_client().get("/ping").status_code, 200)

    def test_missing_flask_limiter_degrades_to_no_limiting(self):
        """The package can vanish (a bad deploy, a trimmed image). Route
        modules import the decorators unconditionally, so they must still
        be applicable — as identities."""
        null = self.rl._NullLimiter()
        with patch.object(self.rl, "limiter", null):
            def view():
                return "ok"
            self.assertIs(self.rl.llm_limit(view), view)
            self.assertIs(self.rl.whisper_limit(view), view)
            self.assertIs(self.rl.heavy_limit(view), view)
            self.assertIs(self.rl.regenerate_limit(view), view)
        self.assertIsNone(null.init_app(Flask("null-probe")))

    def test_decorated_route_works_on_an_app_that_never_init_the_limiter(self):
        """Every route test in this repo builds its own Flask app and
        registers the blueprints WITHOUT calling rate_limits.init_app. The
        limit decorator calls into the limiter from inside the view wrapper,
        so if that path needed initialised storage, adding a cap to a route
        would break every existing test that touches it."""
        app = Flask(f"noinit{id(self)}")

        @app.route("/paid", methods=["POST"])
        @self.rl.llm_limit
        def paid():
            return jsonify(ok=True)

        c = app.test_client()  # note: no init_app, no error handlers
        self.assertEqual({c.post("/paid").status_code for _ in range(40)},
                         {200})

    def test_retry_after_is_sane_outside_a_breach(self):
        """The 429 helpers run inside an error handler — they must never
        raise, even when asked at a moment they know nothing about."""
        self.assertGreaterEqual(self.rl.retry_after_seconds(), 1)
        self.assertIsNone(self.rl.breach_message(object()))
        self.assertEqual(self.rl.breach_scope(object()), "unscoped")


if __name__ == "__main__":
    unittest.main()
