from flask import Flask, jsonify, send_from_directory, request, redirect
from flask_cors import CORS
import os
from werkzeug.exceptions import RequestEntityTooLarge
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
from config import Config

config = Config()

# Initialize Sentry.
#
# traces_sample_rate was 1.0 — a performance transaction for EVERY request,
# including the health checks Railway polls continuously. That burns the
# quota on noise, and a burned quota means no ERROR visibility on the live
# loop when it matters. Sampling is env-tunable (SENTRY_TRACES_SAMPLE_RATE)
# and defaults to 5% in production / 0 elsewhere; error capture is
# unaffected — it is not sampled.
if config.SENTRY_DSN:
    sentry_sdk.init(
        dsn=config.SENTRY_DSN,
        integrations=[FlaskIntegration()],
        traces_sample_rate=config.SENTRY_TRACES_SAMPLE_RATE,
        profiles_sample_rate=config.SENTRY_PROFILES_SAMPLE_RATE,
        environment=config.ENV,
        release=config.RELEASE_SHA or None,
        # Never let Sentry itself become the leak this sweep is closing:
        # no request bodies, no headers, no user PII in the event payload.
        send_default_pii=False,
        max_request_body_size="never",
    )

# Secret configuration audit (P2 ops sweep 2026-08-03). Runs before the
# app is built: in production and staging a placeholder credential, a
# truncated key, a staging box pointed at the production database or a
# live Stripe key raise here and the deploy rolls back to the last good
# release. In development it only logs. Never prints a secret VALUE.
from services.secrets import enforce_at_boot  # noqa: E402

enforce_at_boot()

app = Flask(__name__)
# Global request cap: must allow both recording uploads and larger admin reference video uploads.
app.config["MAX_CONTENT_LENGTH"] = max(
    int(getattr(config, "MAX_AUDIO_SIZE_MB", 25)),
    int(getattr(config, "MAX_REFERENCE_VIDEO_SIZE_MB", 500)),
) * 1024 * 1024
# Explicit headers so browser uploads from Next admin (Bearer + multipart) pass
# preflight. Accept + X-Requested-With added 2026-07-15: big deck uploads
# (>~4.5MB) bypass the Vercel BFF body cap and hit
# POST /v2/lab/presentation/extract DIRECTLY from the browser — the fetch
# sends those two headers, and a preflight fails on ANY unlisted header even
# when the origin matches.
CORS(
    app,
    origins=config.CORS_ORIGINS,
    supports_credentials=True,
    allow_headers=["Authorization", "Content-Type", "X-Internal-Secret",
                   "Accept", "X-Requested-With", "X-Dev-Key"],
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)

# Register blueprints (v2 / taskmaster MVP only)
from routes.auth import auth_bp
from routes.recordings import recordings_v2_bp
from routes.user import user_bp
from routes.admin import admin_bp
from routes.v2_routes import v2_bp
from routes.internal_webhooks import internal_webhooks_bp
from routes.snippet_labels_routes import snippet_labels_bp
from routes.dev_bugs import dev_bugs_bp
from routes.dev_tasks import dev_tasks_bp
from routes.journal import journal_bp
from routes.token_routes import tokens_bp
from routes.life_routes import life_bp
from routes.life_reminders_webhook import life_reminders_webhook_bp

app.register_blueprint(auth_bp, url_prefix="/auth")
app.register_blueprint(recordings_v2_bp, url_prefix="/v2/recordings")
app.register_blueprint(user_bp, url_prefix="/user")
app.register_blueprint(admin_bp, url_prefix="/admin")
app.register_blueprint(v2_bp)
app.register_blueprint(internal_webhooks_bp)
app.register_blueprint(snippet_labels_bp, url_prefix="/admin/snippet-labels")
# dev-bugs collector: full paths baked into the blueprint (no prefix), like
# internal_webhooks_bp. Serves /api/dev-bugs* + the /dev-bugs page.
app.register_blueprint(dev_bugs_bp)
# dev-tasks backlog API (same x-dev-key gate). Serves /api/dev-tasks*.
app.register_blueprint(dev_tasks_bp)
# Journal (blog): PUBLIC /v2/journal/* reads (no auth — the FE server-renders
# them) + password-gated /v2/internal/journal/* CMS. Full paths baked in.
app.register_blueprint(journal_bp)
# Token balance API: /v2/tokens/* behind TOKEN_PRICING_ENABLED (default 0).
# With the flag off every endpoint answers 200 {"enabled": false} rather than
# 404, so the FE has one probe that tells "pricing is off" apart from "the
# backend is broken". Read-only — nothing here charges. Full paths baked in.
app.register_blueprint(tokens_bp)
# The Life Panel: /v2/life/* behind LIFE_PANEL_ENABLED (default 0). With the
# flag off every route 404s, so registering the blueprint changes nothing
# observable until the flag is flipped. Full paths baked in — v2_routes.py is
# untouched by this feature apart from the guarded chat-router hook.
app.register_blueprint(life_bp)
# Opt-in life reminders cron webhook (X-Internal-Secret: LIFE_REMINDER_SECRET).
app.register_blueprint(life_reminders_webhook_bp)
# Durable pipeline job polling (async-queue work): GET /v2/jobs/<id>/status
# + the internal sweep poke. Full paths baked in.
from routes.jobs import jobs_bp
app.register_blueprint(jobs_bp)

# Rate limiting (services/rate_limits.py). The @rate_limits.*_limit
# decorators on the paid routes registered themselves while the blueprints
# above were imported; this call attaches the storage + the before_request
# check. It never raises — a limiter that can't start must not stop the app
# from serving (live loop).
from services import rate_limits
rate_limits.init_app(app)


@app.errorhandler(RequestEntityTooLarge)
@app.errorhandler(413)
def handle_413(e):
    """Return JSON when request body exceeds MAX_CONTENT_LENGTH."""
    path = (request.path or "").strip()
    if "/v2/admin/copilot/reference-videos/upload" in path:
        return jsonify({
            "code": "PAYLOAD_TOO_LARGE",
            "error": (
                f"Reference video is too large. Max allowed is "
                f"{int(getattr(config, 'MAX_REFERENCE_VIDEO_SIZE_MB', 500))}MB."
            ),
        }), 413
    return jsonify({
        "code": "PAYLOAD_TOO_LARGE",
        "error": f"Request body exceeds {config.MAX_AUDIO_SIZE_MB}MB limit. Keep recording under {config.MAX_AUDIO_SIZE_MB}MB.",
    }), 413


@app.errorhandler(405)
def handle_405(e):
    return jsonify({"code": "METHOD_NOT_ALLOWED", "error": "Method not allowed"}), 405


# Global JSON error net (P0 audit 2026-08-03). Catches what route-level
# try/except cannot — exceptions raised before a route's own handler,
# abort() calls, and Flask's stock HTML 404/500 pages. Clients get
# {code, error, ref} with GENERIC copy; the real exception goes to the log
# + Sentry under the same ref. Registered AFTER the 413/405 handlers above
# so their specific copy still wins (Flask resolves most-specific first).
from utils.errors import register_error_handlers  # noqa: E402

register_error_handlers(app)


def _health_response():
    """Single response for all health endpoints so frontend gets 200 regardless of path."""
    return {"status": "ok"}, 200


@app.route("/", methods=["GET"])
def root():
    """Public root health check; frontend may use base URL with no path.

    Exception: the dev-bugs collector subdomain (dev.willpowerlab.com) serves its
    single-page UI here, same-origin with its /api/dev-bugs API. Every other host
    (Railway health probes, the app domain) still gets the JSON health payload.
    """
    from routes.dev_bugs import is_dev_bugs_host, serve_dev_bugs_page
    if is_dev_bugs_host(request.host):
        return serve_dev_bugs_page()
    return _health_response()


@app.route("/health", methods=["GET"])
def health():
    return _health_response()


@app.route("/health/", methods=["GET"])
def health_trailing():
    """Health with trailing slash (some clients or proxies normalize to this)."""
    return _health_response()


@app.route("/api/health", methods=["GET"])
def api_health():
    """Health at /api/health in case frontend or BFF uses this path."""
    return _health_response()


@app.route("/api/admin/students", methods=["GET"])
def api_admin_students_alias():
    """Compatibility alias for callers using /api/admin/* directly against backend."""
    qs = request.query_string.decode().strip()
    target = "/v2/admin/students"
    if qs:
        target = f"{target}?{qs}"
    return redirect(target, code=308)


@app.route("/api/admin/students/<user_id>", methods=["GET", "PATCH", "DELETE"])
def api_admin_student_alias(user_id):
    """Compatibility alias for callers using /api/admin/* directly against backend."""
    return redirect(f"/v2/admin/students/{user_id}", code=308)

# Serve static assets (e.g. coach avatar for assignment email)
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


@app.route("/static/<path:filename>", methods=["GET"])
def serve_static(filename):
    """Serve files from static/ (e.g. coach-avatar.png for assignment email)."""
    return send_from_directory(STATIC_DIR, filename)


@app.route("/health/jwks", methods=["GET"])
def health_jwks():
    """Health check endpoint to verify JWKS connectivity"""
    from auth import get_jwks_client, _normalize_supabase_url
    import logging
    import httpx
    
    logger = logging.getLogger(__name__)
    
    try:
        # Test JWKS connectivity by initializing the client
        jwks_client = get_jwks_client()
        
        # Try to fetch JWKS to verify connectivity
        supabase_url = _normalize_supabase_url(config.SUPABASE_URL)
        jwks_url = f"{supabase_url}/auth/v1/.well-known/jwks.json"
        
        # Make a direct request to verify the endpoint is accessible
        response = httpx.get(jwks_url, timeout=5)
        response.raise_for_status()
        jwks = response.json()
        keys_count = len(jwks.get("keys", []))
        
        return {
            "status": "ok",
            "jwks_accessible": True,
            "keys_count": keys_count,
            "jwks_url": jwks_url,
            "supabase_url": config.SUPABASE_URL
        }, 200
    except Exception as e:
        # PUBLIC endpoint — no auth. It used to echo the exception plus the
        # Supabase project URL to anyone who asked; an httpx error carries
        # the full request URL, and a JWKS 401 carries key material in the
        # SDK's message. Operators read the detail from the log line.
        from utils.errors import new_ref, scrub

        ref = new_ref()
        logger.error("JWKS health check failed [ref=%s]: %s", ref, scrub(e))
        return {
            "status": "error",
            "jwks_accessible": False,
            "error": "JWKS endpoint unreachable.",
            "ref": ref,
        }, 503

def _startup_cleanup():
    """One-time housekeeping on first request: recover stale upload jobs left by prior restarts."""
    import logging
    _logger = logging.getLogger(__name__)
    try:
        from services.db import db
        n = db.mark_stale_upload_jobs_failed(stale_minutes=30)
        if n:
            _logger.info("Startup: marked %d stale upload job(s) as failed", n)
    except Exception as exc:
        _logger.warning("Startup cleanup skipped: %s", exc)
    # Durable pipeline jobs (async-queue work): re-enqueue orphans / fail
    # exhausted ones so a web redeploy also doubles as a recovery pass.
    # No-op (cheap SELECT) when the queue is off or nothing is stale.
    try:
        from services.job_queue import queue_configured
        if queue_configured():
            from services.pipeline_jobs import sweep_stale_jobs
            counts = sweep_stale_jobs()
            if counts.get("requeued") or counts.get("failed"):
                _logger.info("Startup: pipeline job sweep %s", counts)
    except Exception as exc:
        _logger.warning("Startup pipeline-job sweep skipped: %s", exc)


with app.app_context():
    _startup_cleanup()


if __name__ == "__main__":
    app.run(debug=not config.is_production, host="0.0.0.0", port=5000)
