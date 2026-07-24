"""dev-bugs — internal founder bug collector API + page (dev.willpowerlab.com).

Endpoints (all under the app, no blueprint prefix — full paths baked in, like
routes/internal_webhooks.py):

  GET    /api/dev-bugs        -> {"open": [...], "shipped": [...]}
  POST   /api/dev-bugs        -> 201 {"id"}      body {"text", "image"}
  DELETE /api/dev-bugs/<id>   -> 204             (only while status='open')
  POST   /api/dev-bugs/send   -> {"sent": <n>}   (same routine as the 3-day cron)
  GET    /dev-bugs[/]         -> the single-page UI (also served at the dev
                                  subdomain root via app.py root()).

The four /api/* routes require header `x-dev-key: <DEV_BUGS_KEY>` (mirrors the
`X-Internal-Secret` gate on /v2/internal/*). The page itself is un-gated (it just
prompts for the key client-side and enforcement happens on the API).
"""
from __future__ import annotations

import hmac
import logging
import os

import sentry_sdk
from flask import Blueprint, jsonify, request, send_from_directory

from config import Config
from services import dev_bugs as svc

logger = logging.getLogger(__name__)
config = Config()

dev_bugs_bp = Blueprint("dev_bugs", __name__)

# routes/ is one level under the repo root; static/ sits at the root.
STATIC_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static"
)
_PAGE_FILE = "dev_bugs.html"


def is_dev_bugs_host(host: str | None) -> bool:
    """True when the request Host is the dev-bugs collector subdomain.

    Matches the configured DEV_BUGS_HOST exactly, plus a `dev.` prefix fallback
    so it works even before DEV_BUGS_HOST is set explicitly.
    """
    if not host:
        return False
    name = host.split(":", 1)[0].strip().lower()
    return name == config.DEV_BUGS_HOST or name.startswith("dev.")


def serve_dev_bugs_page():
    """Serve the self-contained single-page UI from static/."""
    return send_from_directory(STATIC_DIR, _PAGE_FILE)


def _key_error():
    """None if the x-dev-key header is valid; else a (json, status) error tuple."""
    secret = (getattr(config, "DEV_BUGS_KEY", None) or "").strip()
    if not secret:
        return jsonify({"code": "DISABLED", "error": "DEV_BUGS_KEY not configured"}), 503
    supplied = (request.headers.get("x-dev-key") or "").strip()
    if not supplied or not hmac.compare_digest(supplied, secret):
        return jsonify({"code": "UNAUTHORIZED", "error": "Invalid or missing x-dev-key"}), 401
    return None


def _maybe_generate_task(bug_id, text, images=None):
    """Best-effort: turn a just-saved bug into a user-story task via GPT-4o, in a
    background thread so it NEVER blocks or breaks the bug save. Carries the bug's
    images onto the task. Gated by DEV_TASKS_ENABLED (default off)."""
    if not getattr(config, "DEV_TASKS_ENABLED", False):
        return
    if not (text or "").strip():
        return

    def _run():
        try:
            from services import dev_tasks
            dev_tasks.generate_task_for_bug({"id": bug_id, "text": text, "images": images or []})
        except Exception:  # noqa: BLE001
            logger.exception("dev_tasks: background task generation failed")

    try:
        import threading
        threading.Thread(target=_run, daemon=True).start()
    except Exception:  # noqa: BLE001
        logger.exception("dev_tasks: could not start generation thread")


# ─────────────────────────── page ───────────────────────────

@dev_bugs_bp.route("/dev-bugs", methods=["GET"])
@dev_bugs_bp.route("/dev-bugs/", methods=["GET"])
def dev_bugs_page():
    return serve_dev_bugs_page()


# ─────────────────────────── API ───────────────────────────

@dev_bugs_bp.route("/api/dev-bugs", methods=["GET", "POST"])
def dev_bugs_collection():
    err = _key_error()
    if err:
        return err
    try:
        if request.method == "GET":
            return jsonify(svc.list_bugs()), 200

        body = request.get_json(silent=True) or {}
        text = body.get("text", "")
        images = body.get("images")
        if images is None:
            single = body.get("image")  # legacy single-image clients
            images = [single] if single else []
        try:
            bug_id = svc.create_bug(text, images)
        except ValueError:
            return jsonify({"code": "BAD_REQUEST", "error": "empty"}), 400
        _maybe_generate_task(bug_id, text, images)
        return jsonify({"id": bug_id}), 201
    except Exception as e:  # noqa: BLE001
        sentry_sdk.capture_exception(e)
        logger.exception("dev_bugs collection failed")
        return jsonify({"code": "DEV_BUGS_ERROR", "error": str(e)}), 500


@dev_bugs_bp.route("/api/dev-bugs/<int:bug_id>", methods=["DELETE"])
def dev_bugs_delete(bug_id: int):
    err = _key_error()
    if err:
        return err
    try:
        svc.delete_bug(bug_id)
        return "", 204
    except Exception as e:  # noqa: BLE001
        sentry_sdk.capture_exception(e)
        logger.exception("dev_bugs delete failed")
        return jsonify({"code": "DEV_BUGS_ERROR", "error": str(e)}), 500


@dev_bugs_bp.route("/api/dev-bugs/<int:bug_id>", methods=["PATCH"])
def dev_bugs_edit(bug_id: int):
    err = _key_error()
    if err:
        return err
    try:
        body = request.get_json(silent=True) or {}
        row = svc.update_bug(bug_id, text=body.get("text"))
        if row is None:
            return jsonify({"code": "NOT_FOUND", "error": "open bug not found or nothing to update"}), 404
        return jsonify({"bug": row}), 200
    except Exception as e:  # noqa: BLE001
        sentry_sdk.capture_exception(e)
        logger.exception("dev_bugs edit failed")
        return jsonify({"code": "DEV_BUGS_ERROR", "error": str(e)}), 500


@dev_bugs_bp.route("/api/dev-bugs/send", methods=["POST"])
def dev_bugs_send():
    err = _key_error()
    if err:
        return err
    try:
        sent = svc.send_open_bugs()
        return jsonify({"sent": sent}), 200
    except RuntimeError as e:
        # Email did not go out (SEND_EMAILS off / provider error); bugs kept open.
        logger.warning("dev_bugs send not delivered: %s", e)
        return jsonify({"code": "EMAIL_NOT_SENT", "error": str(e)}), 503
    except Exception as e:  # noqa: BLE001
        sentry_sdk.capture_exception(e)
        logger.exception("dev_bugs send failed")
        return jsonify({"code": "DEV_BUGS_ERROR", "error": str(e)}), 500
