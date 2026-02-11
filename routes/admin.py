"""Admin routes (v2). is_admin / require_admin used by v2_routes."""
from flask import Blueprint, request, jsonify
from auth import require_auth
from services.db import db
import sentry_sdk
import logging

logger = logging.getLogger(__name__)
admin_bp = Blueprint("admin", __name__)


def is_admin(user_id: str) -> bool:
    """Check if user is an admin by email from token payload."""
    try:
        token_payload = getattr(request, "token_payload", None)
        if not token_payload:
            return False
        user_email = token_payload.get("email")
        if not user_email:
            return False
        admin_result = (
            db.client.table("admin_users")
            .select("id")
            .eq("email", user_email)
            .eq("is_active", True)
            .execute()
        )
        return len(admin_result.data) > 0
    except Exception as e:
        logger.error(f"Error checking admin status: {str(e)}")
        return False


def require_admin(f):
    """Decorator to require admin authentication."""
    from functools import wraps
    from auth import require_auth as base_require_auth

    @wraps(f)
    @base_require_auth
    def decorated_function(*args, **kwargs):
        if not is_admin(request.user_id):
            return jsonify({"code": "FORBIDDEN", "error": "Admin access required"}), 403
        return f(*args, **kwargs)

    return decorated_function


@admin_bp.route("/recordings", methods=["GET"])
@require_admin
def get_admin_recordings():
    """Get recordings for admin review (paginated)."""
    try:
        limit = request.args.get("limit", default=20, type=int)
        offset = request.args.get("offset", default=0, type=int)
        result = (
            db.client.table("recordings")
            .select("*, user_id")
            .order("created_at", desc=True)
            .limit(limit)
            .offset(offset)
            .execute()
        )
        recordings = result.data or []
        return jsonify({
            "recordings": recordings,
            "limit": limit,
            "offset": offset,
            "count": len(recordings),
        }), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "RECORDINGS_ERROR", "error": str(e)}), 500
