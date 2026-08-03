"""dev-tasks — API for the "user stories · tasks" backlog view.

All routes are gated by the SAME `x-dev-key` as dev-bugs (one dev tool, one key) —
the gate helper is reused from routes.dev_bugs. Full paths baked in (no prefix),
like the dev-bugs blueprint. See services/dev_tasks.py.

  GET    /api/dev-tasks?view=active|archive   -> {"tasks": [...], "view": ...}
  GET    /api/dev-tasks/export[?format=]      -> download of the active backlog.
                                                 default/pdf -> PDF with each screenshot
                                                 under its task; zip|md -> markdown, as a
                                                 ZIP with images/ when any task has one
  PATCH  /api/dev-tasks/<id>   {body,user_story,priority}  -> {"task": row}
  DELETE /api/dev-tasks/<id>                  -> 204
  POST   /api/dev-tasks/<id>/reorder  {after_id}  -> {"ok": true}  (after_id null = top)
  POST   /api/dev-tasks/<id>/done             -> archive
  POST   /api/dev-tasks/<id>/restore          -> un-archive
"""
from __future__ import annotations

import logging

import sentry_sdk
from flask import Blueprint, Response, jsonify, request

from routes.dev_bugs import _key_error
from services import dev_tasks as svc
from utils.errors import safe_error

logger = logging.getLogger(__name__)
dev_tasks_bp = Blueprint("dev_tasks", __name__)


def _err(e):
    sentry_sdk.capture_exception(e)
    logger.exception("dev_tasks route failed")
    return safe_error("DEV_TASKS_ERROR", 500, exc=e)


@dev_tasks_bp.route("/api/dev-tasks", methods=["GET"])
def list_tasks():
    err = _key_error()
    if err:
        return err
    try:
        view = (request.args.get("view") or "active").strip()
        view = view if view in ("active", "archive") else "active"
        return jsonify({"tasks": svc.list_tasks(view), "view": view}), 200
    except Exception as e:  # noqa: BLE001
        return _err(e)


@dev_tasks_bp.route("/api/dev-tasks/export", methods=["GET"])
def export_tasks():
    err = _key_error()
    if err:
        return err
    try:
        # PDF by default: it's the only format where the screenshots are guaranteed
        # to travel (a rich-text paste drops data: URI images in many targets).
        # ?format=zip keeps the markdown+files bundle for the paste-into-an-LLM path.
        fmt = (request.args.get("format") or "pdf").strip().lower()
        wanted_pdf = fmt not in ("zip", "md", "markdown")
        if wanted_pdf:
            payload, mime, filename = svc.export_pdf()
        else:
            payload, mime, filename = svc.export_bundle()
        # export_pdf() degrades to the ZIP when reportlab is missing/fails. Say so
        # out loud: without this the client can't tell "PDF not deployed yet" from
        # "deployed but reportlab absent" — both just arrive as a .zip.
        served = {"application/pdf": "pdf", "application/zip": "zip"}.get(mime, "markdown")
        fell_back = wanted_pdf and served != "pdf"
        headers = {
            "Content-Disposition": f"attachment; filename={filename}",
            "X-Export-Format": served,
            # the client names the saved file from Content-Disposition (the
            # extension varies) and reports the format from these
            "Access-Control-Expose-Headers":
                "Content-Disposition, X-Export-Format, X-Export-Fallback",
        }
        if fell_back:
            headers["X-Export-Fallback"] = "1"
        return Response(payload, mimetype=mime, headers=headers)
    except Exception as e:  # noqa: BLE001
        return _err(e)


@dev_tasks_bp.route("/api/dev-tasks/<int:task_id>", methods=["PATCH"])
def edit_task(task_id: int):
    err = _key_error()
    if err:
        return err
    try:
        body = request.get_json(silent=True) or {}
        return jsonify({"task": svc.update_task(task_id, body)}), 200
    except Exception as e:  # noqa: BLE001
        return _err(e)


@dev_tasks_bp.route("/api/dev-tasks/<int:task_id>", methods=["DELETE"])
def delete_task(task_id: int):
    err = _key_error()
    if err:
        return err
    try:
        svc.delete_task(task_id)
        return "", 204
    except Exception as e:  # noqa: BLE001
        return _err(e)


@dev_tasks_bp.route("/api/dev-tasks/<int:task_id>/reorder", methods=["POST"])
def reorder_task(task_id: int):
    err = _key_error()
    if err:
        return err
    try:
        body = request.get_json(silent=True) or {}
        after = body.get("after_id")
        after_id = int(after) if after is not None else None
        svc.reorder_task(task_id, after_id)
        return jsonify({"ok": True}), 200
    except (TypeError, ValueError):
        return jsonify({"code": "BAD_REQUEST", "error": "after_id must be an int or null"}), 400
    except Exception as e:  # noqa: BLE001
        return _err(e)


@dev_tasks_bp.route("/api/dev-tasks/<int:task_id>/done", methods=["POST"])
def done_task(task_id: int):
    err = _key_error()
    if err:
        return err
    try:
        svc.set_done(task_id)
        return jsonify({"ok": True}), 200
    except Exception as e:  # noqa: BLE001
        return _err(e)


@dev_tasks_bp.route("/api/dev-tasks/<int:task_id>/restore", methods=["POST"])
def restore_task(task_id: int):
    err = _key_error()
    if err:
        return err
    try:
        svc.restore_task(task_id)
        return jsonify({"ok": True}), 200
    except Exception as e:  # noqa: BLE001
        return _err(e)
