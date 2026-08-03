"""Global, Redis-backed rate limiting for the paid surfaces (F1-SURFACE).

Why this exists
---------------
Every authenticated Whisper/LLM endpoint used to be uncapped: one retry
loop in a client could run the OpenAI bill up without anything on the
backend saying no. The only limiter was an in-process dict on the guest
funnel — per-worker, so the real cap was ``workers x stated cap``, and it
reset on every restart/redeploy.

This module is the one place that answers "how many of these may you
do?". It is backed by the SAME Redis the pipeline queue already needs
(``REDIS_URL``), so the cap is durable and shared across every gunicorn
worker and every web instance.

Live-loop contract (CLAUDE.md: never break record -> transcribe -> coach
-> read). A limiter sits in front of EVERY decorated request, so its
failure modes matter more than its features:

  * ``flask_limiter`` missing            -> null limiter, decorators are
                                            identity, app boots.
  * ``RATE_LIMIT_ENABLED=0``             -> limiter registered but off.
  * ``REDIS_URL`` unset                  -> ``memory://`` (per-worker,
                                            logged loudly at boot). Same
                                            weak guarantee as the dict it
                                            replaces — never a crash.
  * broker dead / unreachable            -> ``swallow_errors`` +
                                            ``in_memory_fallback`` degrade
                                            to per-worker counting, and
                                            flask-limiter's exponential
                                            backoff re-probes Redis.
  * broker BLACKHOLED (packets dropped)  -> the socket timeouts below cap
                                            the damage at a couple of
                                            seconds. Without them a
                                            request hangs FOREVER; this is
                                            measured, not theoretical, so
                                            do not remove them.

Keys: the authenticated subject when a Bearer token is present, else the
client IP. The subject is read WITHOUT verifying the signature on
purpose — the limiter runs before ``@require_auth``, verification costs a
JWKS round-trip, and forging a ``sub`` only buys a fresh bucket for a
request that then 401s without spending a cent on OpenAI.

Tiers (all env-tunable, see ``.env.example``). Defaults are set to stop a
runaway loop (hundreds of requests a minute) while sitting far above what
a human doing real work can produce, because a limit that trips on a real
session breaks the live loop:

  ``whisper_limit``  audio upload -> transcription
  ``llm_limit``      one interactive LLM call (chat/coaching turn)
  ``heavy_limit``    multi-call generation, media processing, training

Usage::

    from services import rate_limits

    @v2_bp.route("/coaching/turn", methods=["POST"])
    @rate_limits.llm_limit
    @require_auth
    def v2_coaching_turn():
        ...

Undecorated routes are UNLIMITED — there are no default limits. That is
deliberate: health probes, cron webhooks and the FE's polling GETs must
never be capped, and an opt-in list can't accidentally take out a surface
nobody thought about.
"""
from __future__ import annotations

import logging
import os
from typing import Callable, Optional

logger = logging.getLogger(__name__)

try:
    from flask import request
except Exception:  # pragma: no cover - env/bootstrap guard
    request = None  # type: ignore[assignment]

try:
    from flask_limiter import Limiter as _Limiter
    _IMPORT_ERROR: Optional[Exception] = None
except Exception as _limiter_err:  # pragma: no cover - env/bootstrap guard
    _Limiter = None  # type: ignore[assignment]
    _IMPORT_ERROR = _limiter_err


# ── env helpers ──────────────────────────────────────────────────────────

def _flag(name: str, default: str = "1") -> bool:
    return (os.getenv(name) or default).strip().lower() in ("1", "true", "yes")


def _limit_string(name: str, default: str) -> str:
    """A flask-limiter limit expression from env, e.g. "20 per minute".

    A blank/unset var falls back to the default. A malformed one is NOT
    validated here — flask-limiter parses it per request and, with
    ``swallow_errors`` on, logs and allows rather than 500s.
    """
    return (os.getenv(name) or "").strip() or default


def _int_env(name: str, default: int) -> int:
    """Positive integer env var; unset/blank/malformed falls back."""
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


# ── defaults ─────────────────────────────────────────────────────────────
# Sized against the threat (a client loop doing 10+ req/s), not against
# tidiness. Raise them in env before you raise them here.

DEFAULT_WHISPER_LIMIT = "20 per minute;200 per hour"
DEFAULT_LLM_LIMIT = "30 per minute;400 per hour"
DEFAULT_HEAVY_LIMIT = "10 per minute;100 per hour"

#: The generic 429 line is NOT defined here — ``utils.errors._STATUS_COPY``
#: already owns it ("Too many requests — slow down and try again."), and two
#: copies of one sentence drift. Only a limit with its own ``error_message``
#: (the guest funnel) overrides it; see ``breach_message``.

STORAGE_OPTIONS = {
    # Fail fast, exactly like services/job_queue.py. A blackholed broker
    # with no timeouts hangs every request indefinitely.
    "socket_connect_timeout": 2,
    "socket_timeout": 2,
}


def whisper_limit_value() -> str:
    return _limit_string("RATE_LIMIT_WHISPER", DEFAULT_WHISPER_LIMIT)


def llm_limit_value() -> str:
    return _limit_string("RATE_LIMIT_LLM", DEFAULT_LLM_LIMIT)


def heavy_limit_value() -> str:
    return _limit_string("RATE_LIMIT_HEAVY", DEFAULT_HEAVY_LIMIT)


def guest_funnel_ip_limit_value() -> str:
    """Preserves GUEST_FUNNEL_RATE_LIMIT_PER_IP_PER_HOUR (default 5)."""
    return f"{_int_env('GUEST_FUNNEL_RATE_LIMIT_PER_IP_PER_HOUR', 5)} per hour"


def guest_funnel_global_limit_value() -> str:
    """Preserves GUEST_FUNNEL_RATE_LIMIT_GLOBAL_PER_HOUR (default 200)."""
    return f"{_int_env('GUEST_FUNNEL_RATE_LIMIT_GLOBAL_PER_HOUR', 200)} per hour"


# ── keys ─────────────────────────────────────────────────────────────────

def client_ip() -> str:
    """Best-effort client IP — X-Forwarded-For first (Railway/CDN)."""
    try:
        xff = (request.headers.get("X-Forwarded-For") or "").strip()
        if xff:
            return xff.split(",")[0].strip() or (request.remote_addr or "0.0.0.0")
        return request.remote_addr or "0.0.0.0"
    except Exception:
        return "0.0.0.0"


def _bearer_subject() -> Optional[str]:
    """``sub`` from the Bearer JWT, signature NOT verified (see module doc)."""
    try:
        header = (request.headers.get("Authorization") or "").strip()
        if not header.startswith("Bearer "):
            return None
        token = header[len("Bearer "):].strip()
        if not token:
            return None
        import jwt
        payload = jwt.decode(token, options={"verify_signature": False,
                                             "verify_exp": False})
        sub = payload.get("sub")
        return str(sub) if sub else None
    except Exception:
        # Malformed/opaque token — fall back to IP. Never raise into the
        # request path from a key function.
        return None


def identity_key() -> str:
    """The default bucket: one per signed-in user, else one per IP."""
    sub = _bearer_subject()
    return f"u:{sub}" if sub else f"ip:{client_ip()}"


def ip_key() -> str:
    return f"ip:{client_ip()}"


def global_key() -> str:
    """One shared bucket for everyone — the anti-botnet cap."""
    return "global"


def view_arg_key(name: str) -> Callable[[], str]:
    """A bucket per URL path segment — e.g. one per ``<session_id>``."""
    def key() -> str:
        try:
            value = (request.view_args or {}).get(name)
            return f"{name}:{value}" if value else f"{name}:unknown"
        except Exception:
            return f"{name}:unknown"
    return key


def _forced() -> bool:
    """``{"force": true}`` in the JSON body — an explicit override of a
    double-click guard. Flask caches the parsed body, so reading it here
    (in before_request) does not consume it from the view."""
    try:
        return (request.get_json(silent=True) or {}).get("force") is True
    except Exception:
        return False


# ── the limiter ──────────────────────────────────────────────────────────

class _NullLimiter:
    """Stand-in when flask_limiter is unavailable: every decorator is the
    identity, so route modules import and register exactly the same."""

    enabled = False

    def limit(self, *_a, **_kw) -> Callable:
        def decorator(fn):
            return fn
        return decorator

    def exempt(self, fn):
        return fn

    def request_filter(self, fn):
        return fn

    def init_app(self, _app) -> None:
        return None

    @property
    def current_limit(self):
        return None


def _build_limiter():
    if _Limiter is None:
        logger.warning(
            "rate_limits: flask_limiter unavailable (%s) — rate limiting is "
            "OFF. Paid endpoints are uncapped.", _IMPORT_ERROR,
        )
        return _NullLimiter()
    return _Limiter(
        key_func=identity_key,
        # No default limits: capping is opt-in per route (see module doc).
        default_limits=[],
        storage_options=STORAGE_OPTIONS,
    )


limiter = _build_limiter()


def storage_uri() -> str:
    """Where the counters live.

    RATE_LIMIT_STORAGE_URI wins (lets us point the limiter at a different
    Redis than the queue); otherwise we share the queue's REDIS_URL, kept
    apart by RATELIMIT_KEY_PREFIX. With neither, ``memory://`` — per-worker
    and lost on restart, i.e. no better than the dict this replaces, so it
    is logged as a warning at boot.
    """
    explicit = (os.getenv("RATE_LIMIT_STORAGE_URI") or "").strip()
    if explicit:
        return explicit
    redis_url = (os.getenv("REDIS_URL") or "").strip()
    if redis_url:
        return redis_url
    return "memory://"


def is_durable() -> bool:
    """True when counters are shared across workers (i.e. not memory://)."""
    return not storage_uri().startswith("memory://")


def register_429(app) -> None:
    """Install the 429 handler.

    ``utils.errors.register_error_handlers`` already nets every
    HTTPException into ``{code, error, ref}``. This one wins for 429 —
    Flask resolves the code-keyed handler before the class-keyed
    HTTPException one, whenever each was registered — because the generic
    net would drop the two things a throttled caller actually needs: how
    long to wait, and the guest funnel's own copy.

    The envelope stays utils.errors' so the FE has ONE error shape; the
    generic 429 line comes from their status table rather than being
    duplicated here.
    """
    from utils.errors import error_payload
    from flask import jsonify

    @app.errorhandler(429)
    def _handle_rate_limited(e):
        retry_after = retry_after_seconds()
        payload = error_payload(
            "RATE_LIMITED", 429,
            message=breach_message(e),
            extra={"retry_after_seconds": retry_after},
        )
        logger.info("rate limited [ref=%s] %s %s scope=%s retry_after=%ss",
                    payload.get("ref"), _req_method(), _req_path(),
                    breach_scope(e), retry_after)
        response = jsonify(payload)
        response.headers["Retry-After"] = str(retry_after)
        return response, 429


def _req_path() -> str:
    try:
        return (request.path or "")[:200]
    except Exception:
        return ""


def _req_method() -> str:
    try:
        return request.method or ""
    except Exception:
        return ""


def init_app(app) -> None:
    """Wire the limiter onto ``app``. Never raises — a limiter that cannot
    start must not stop the app from serving."""
    if isinstance(limiter, _NullLimiter):
        return
    try:
        register_429(app)
    except Exception as e:
        logger.error("rate_limits: 429 handler registration failed (%s) — "
                     "throttled callers fall back to the generic envelope "
                     "from utils.errors.", e)
    try:
        uri = storage_uri()
        app.config.setdefault("RATELIMIT_STORAGE_URI", uri)
        app.config.setdefault("RATELIMIT_STORAGE_OPTIONS", STORAGE_OPTIONS)
        app.config.setdefault("RATELIMIT_ENABLED", _flag("RATE_LIMIT_ENABLED"))
        # Namespaced so limiter keys never collide with the RQ queue's keys
        # in the shared Redis.
        app.config.setdefault("RATELIMIT_KEY_PREFIX", "willab-rl")
        # moving-window preserves the guest funnel's documented "sliding
        # 1-hour window" and denies the burst-at-window-edge that
        # fixed-window allows (2x the cap across a boundary).
        app.config.setdefault(
            "RATELIMIT_STRATEGY",
            (os.getenv("RATE_LIMIT_STRATEGY") or "moving-window").strip(),
        )
        # OFF by default: flask-limiter's header injection puts Retry-After
        # on SUCCESSFUL responses too, and a FE that backs off on "is
        # Retry-After present?" would then throttle itself on every 200.
        # The 429 handler sets Retry-After itself, so nothing is lost. Turn
        # on to also publish the X-RateLimit-* budget headers.
        app.config.setdefault("RATELIMIT_HEADERS_ENABLED",
                              _flag("RATE_LIMIT_HEADERS", "0"))
        # The two live-loop switches: storage errors log instead of 500ing,
        # and a dead broker degrades to per-worker counting.
        app.config.setdefault("RATELIMIT_SWALLOW_ERRORS", True)
        app.config.setdefault("RATELIMIT_IN_MEMORY_FALLBACK_ENABLED", True)

        limiter.init_app(app)

        @limiter.request_filter
        def _exempt_cors_preflight() -> bool:
            """A browser sends OPTIONS before every cross-origin POST. Those
            preflights must not spend the user's budget — without this each
            real action would cost two."""
            try:
                return request.method == "OPTIONS"
            except Exception:
                return False

        if not _flag("RATE_LIMIT_ENABLED"):
            logger.warning("rate_limits: DISABLED via RATE_LIMIT_ENABLED — "
                           "paid endpoints are uncapped.")
        elif is_durable():
            logger.info("rate_limits: active, durable storage (shared across "
                        "workers), strategy=%s",
                        app.config.get("RATELIMIT_STRATEGY"))
        else:
            logger.warning(
                "rate_limits: active but storage is IN-PROCESS (memory://) — "
                "set REDIS_URL so the cap is global instead of per-worker.")
    except Exception as e:
        logger.error("rate_limits: init failed (%s) — continuing WITHOUT "
                     "rate limiting so the live loop keeps serving.", e,
                     exc_info=True)


# ── tier decorators ──────────────────────────────────────────────────────
# Built fresh per view so each registers under its own view name.

def _transparent(decorated, original):
    """Keep ``view.__wrapped__`` pointing at the UNDECORATED handler.

    ``functools.wraps`` sets ``__wrapped__`` to whatever it wrapped, so
    stacking a limiter above ``@require_auth`` makes ``view.__wrapped__``
    the AUTH wrapper instead of the handler. That matters here because this
    repo's route tests call ``route.__wrapped__(...)`` to invoke a handler
    without auth — 112 call sites across 39 modules — and one extra layer
    turns every one of them into a 401 against a mock that never sees the
    request. (It did: 47 tests, first CI run.)

    So each tier decorator re-points ``__wrapped__`` past itself. The
    limiter becomes invisible to that convention, and the ordering that
    matters at runtime — limit BEFORE auth, so an unauthenticated flood
    still spends its budget — is preserved.
    """
    inner = getattr(original, "__wrapped__", None)
    if inner is not None:
        try:
            decorated.__wrapped__ = inner
        except Exception:  # pragma: no cover - exotic callables
            pass
    return decorated


def whisper_limit(fn):
    """Audio upload -> Whisper transcription."""
    return _transparent(
        limiter.limit(whisper_limit_value, key_func=identity_key,
                      scope="whisper")(fn), fn)


def llm_limit(fn):
    """One interactive LLM call — chat, coaching turn, suggestion."""
    return _transparent(
        limiter.limit(llm_limit_value, key_func=identity_key,
                      scope="llm")(fn), fn)


def heavy_limit(fn):
    """Multi-call generation, media processing, model training."""
    return _transparent(
        limiter.limit(heavy_limit_value, key_func=identity_key,
                      scope="heavy")(fn), fn)


REGENERATE_MESSAGE = ("Regenerate is rate-limited. Try again shortly, or pass "
                      "force=true.")


def regenerate_limit_value() -> str:
    return _limit_string("RATE_LIMIT_REGENERATE", "1 per minute")


def regenerate_limit(fn):
    """One regenerate per ``<session_id>`` per minute unless ``force=true``.

    Replaces the second in-process dict (the icebreaker regenerate map):
    same 60s window, same force bypass, but shared across workers, so an
    admin double-click can no longer buy a second LLM call just by landing
    on a different worker. Stacks with the caller's ``llm_limit``.
    """
    return _transparent(
        limiter.limit(regenerate_limit_value,
                      key_func=view_arg_key("session_id"),
                      scope="regenerate", error_message=REGENERATE_MESSAGE,
                      exempt_when=_forced)(fn), fn)


GUEST_FUNNEL_MESSAGE = ("Too many trial uploads — please wait a few minutes "
                        "and try again.")


def guest_funnel_limit(fn):
    """The anonymous funnel's per-IP AND global hourly caps.

    Replaces the in-process dict that used to live in routes/v2_routes.py:
    same two caps, same config vars, same 429 copy — but the counters are
    now shared across workers instead of multiplied by them.
    """
    outer = _transparent(
        limiter.limit(guest_funnel_global_limit_value, key_func=global_key,
                      scope="guest_funnel_global",
                      error_message=GUEST_FUNNEL_MESSAGE)(fn), fn)
    return _transparent(
        limiter.limit(guest_funnel_ip_limit_value, key_func=ip_key,
                      scope="guest_funnel_ip",
                      error_message=GUEST_FUNNEL_MESSAGE)(outer), outer)


# ── 429 payload ──────────────────────────────────────────────────────────

def retry_after_seconds() -> int:
    """Seconds until the breached window reopens (>=1)."""
    try:
        import time
        current = limiter.current_limit
        if current is not None and getattr(current, "reset_at", None):
            return max(1, int(current.reset_at - time.time()))
    except Exception:
        pass
    return 1


def breach_message(exc) -> Optional[str]:
    """The 429 text when a limit carries its OWN copy (the guest funnel
    does), else ``None`` so ``utils.errors`` supplies the generic line from
    its status table — one source of truth for that sentence, not two.

    Never the raw limit expression — flask-limiter puts "5 per 1 hour" in
    ``description``, and that is an internal detail, not copy.
    """
    try:
        limit = getattr(exc, "limit", None)
        custom = getattr(limit, "error_message", None) if limit else None
        if callable(custom):
            custom = custom()
        if custom and str(custom).strip():
            return str(custom).strip()
    except Exception:
        pass
    return None


def breach_scope(exc) -> str:
    """Which tier tripped — for logs only, never for the response body."""
    try:
        limit = getattr(exc, "limit", None)
        return str(getattr(limit, "scope", None) or "unscoped")
    except Exception:
        return "unknown"
