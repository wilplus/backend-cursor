"""Internal diagnostics; the retired coach-review publish door answers 410."""
from __future__ import annotations

import logging
import os

from flask import jsonify

from config import Config
from routes.admin import require_admin_or_coach
from routes.v2.blueprint import v2_bp
from utils.errors import safe_error

logger = logging.getLogger(__name__)
config = Config()


@v2_bp.route("/internal/whisper-health", methods=["GET"])
def v2_internal_whisper_health():
    """Report whether transcription credentials and the provider are healthy."""
    try:
        from services.openai_service import OpenAIService

        service = OpenAIService()
        key = config.OPENAI_API_KEY or ""
        reachable = False
        api_error: str | None = None
        model_count = 0
        if service.client:
            try:
                models = service.client.models.list()
                reachable = True
                model_count = len(getattr(models, "data", []) or [])
            except Exception as error:
                api_error = f"{type(error).__name__}: {error}"
        return jsonify({
            "client_initialized": service.client is not None,
            "api_key_present": bool(key),
            "api_key_length": len(key),
            "api_key_prefix": (key[:7] + "...") if key else None,
            "api_reachable": reachable,
            "api_error": api_error,
            "api_model_count": model_count,
            "git_sha": (
                os.environ.get("RAILWAY_GIT_COMMIT_SHA")
                or os.environ.get("RAILWAY_DEPLOYMENT_ID")
            ),
            "env_visible": {
                "OPENAI_API_KEY": bool(os.environ.get("OPENAI_API_KEY")),
                "BACKEND_URL_INTERNAL": bool(
                    os.environ.get("BACKEND_URL_INTERNAL")
                ),
                "R2_PUBLIC_BASE_URL": bool(
                    os.environ.get("R2_PUBLIC_BASE_URL")
                ),
            },
        }), 200
    except Exception as error:
        logger.error("whisper-health failed: %s", error, exc_info=True)
        return safe_error("INTERNAL_ERROR", 500, exc=error)


# ── the canonical coach-review publish boundary: RETIRED ─────────────────
# Founder 2026-09-30, B3 (contract 65), removed 2026-10-01 on the founder's
# "do P2-19 now". The internal door answers 410 and writes nothing; the
# revision and outbox tables stay as history. A coach's answer reaches the
# speaker on its moment the moment it is shared (35g-2) and the Take word
# its Take (35g-6).

@v2_bp.route("/internal/publish-session-results", methods=["POST"])
@require_admin_or_coach
def v2_internal_publish_session_results_gone():
    return jsonify({
        "code": "GONE",
        "error": "The arc-level delivery was retired (founder 2026-09-30, B3 to B6).",
    }), 410
