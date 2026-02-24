from flask import Flask, jsonify, send_from_directory
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
# Allow request bodies up to MAX_AUDIO_SIZE_MB (e.g. 25MB) so recording uploads don't get 413
app.config["MAX_CONTENT_LENGTH"] = config.MAX_AUDIO_SIZE_MB * 1024 * 1024
CORS(app, origins=config.CORS_ORIGINS, supports_credentials=True)

# Register blueprints (v2 / taskmaster MVP only)
from routes.auth import auth_bp
from routes.recordings import recordings_v2_bp
from routes.user import user_bp
from routes.admin import admin_bp
from routes.v2_routes import v2_bp
from routes.homework import homework_bp

app.register_blueprint(auth_bp, url_prefix="/auth")
app.register_blueprint(recordings_v2_bp, url_prefix="/v2/recordings")
app.register_blueprint(user_bp, url_prefix="/user")
app.register_blueprint(admin_bp, url_prefix="/admin")
app.register_blueprint(v2_bp)
app.register_blueprint(homework_bp)


@app.errorhandler(RequestEntityTooLarge)
@app.errorhandler(413)
def handle_413(e):
    """Return JSON when request body exceeds MAX_CONTENT_LENGTH (e.g. recording upload > 25MB)."""
    return jsonify({
        "code": "PAYLOAD_TOO_LARGE",
        "error": f"Request body exceeds {config.MAX_AUDIO_SIZE_MB}MB limit. Keep recording under {config.MAX_AUDIO_SIZE_MB}MB.",
    }), 413


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

if __name__ == "__main__":
    app.run(debug=not config.is_production, host="0.0.0.0", port=5000)
