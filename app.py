from flask import Flask, jsonify, send_from_directory, request, redirect
from flask_cors import CORS
import os
from werkzeug.exceptions import RequestEntityTooLarge
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
from config import Config

config = Config()

# Initialize Sentry
if config.SENTRY_DSN:
    sentry_sdk.init(
        dsn=config.SENTRY_DSN,
        integrations=[FlaskIntegration()],
        traces_sample_rate=1.0,
        environment=config.ENV,
    )

app = Flask(__name__)
# Global request cap: must allow both recording uploads and larger admin reference video uploads.
app.config["MAX_CONTENT_LENGTH"] = max(
    int(getattr(config, "MAX_AUDIO_SIZE_MB", 25)),
    int(getattr(config, "MAX_REFERENCE_VIDEO_SIZE_MB", 500)),
) * 1024 * 1024
# Explicit headers so browser uploads from Next admin (Bearer + multipart) pass preflight.
CORS(
    app,
    origins=config.CORS_ORIGINS,
    supports_credentials=True,
    allow_headers=["Authorization", "Content-Type", "X-Internal-Secret"],
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)

# Register blueprints (v2 / taskmaster MVP only)
from routes.auth import auth_bp
from routes.recordings import recordings_v2_bp
from routes.user import user_bp
from routes.admin import admin_bp
from routes.v2_routes import v2_bp
from routes.homework import homework_bp
from routes.internal_webhooks import internal_webhooks_bp
from routes.snippet_labels_routes import snippet_labels_bp

app.register_blueprint(auth_bp, url_prefix="/auth")
app.register_blueprint(recordings_v2_bp, url_prefix="/v2/recordings")
app.register_blueprint(user_bp, url_prefix="/user")
app.register_blueprint(admin_bp, url_prefix="/admin")
app.register_blueprint(v2_bp)
app.register_blueprint(homework_bp)
app.register_blueprint(internal_webhooks_bp)
app.register_blueprint(snippet_labels_bp, url_prefix="/admin/snippet-labels")


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


def _health_response():
    """Single response for all health endpoints so frontend gets 200 regardless of path."""
    return {"status": "ok"}, 200


@app.route("/", methods=["GET"])
def root():
    """Public root health check; frontend may use base URL with no path."""
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
        logger.error(f"JWKS health check failed: {str(e)}")
        supabase_url = _normalize_supabase_url(config.SUPABASE_URL) if config.SUPABASE_URL else "not configured"
        jwks_url = f"{supabase_url}/auth/v1/.well-known/jwks.json" if config.SUPABASE_URL else "N/A"
        return {
            "status": "error",
            "jwks_accessible": False,
            "error": str(e),
            "jwks_url": jwks_url,
            "supabase_url": config.SUPABASE_URL
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


with app.app_context():
    _startup_cleanup()


if __name__ == "__main__":
    app.run(debug=not config.is_production, host="0.0.0.0", port=5000)
