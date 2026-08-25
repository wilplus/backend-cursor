"""Admin JWT routes for CEO Bugs and Tasks."""
from __future__ import annotations

from flask import Blueprint, Response, jsonify, request

from routes.admin import require_admin
from services import ceo_work_items as work
from utils.errors import safe_error


ceo_work_items_bp = Blueprint("ceo_work_items", __name__)


def _admin_id() -> str:
    return str(getattr(request, "user_id", "") or "")


def _no_store(payload: dict, status: int = 200):
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response, status


def _failure(exc: Exception, operation: str):
    if isinstance(exc, work.CeoWorkItemError):
        return _no_store({
            "code": "INVALID_CEO_WORK_ITEM",
            "error": str(exc),
        }, 400)
    if isinstance(exc, work.CeoWorkItemNotFound):
        return _no_store({
            "code": "CEO_WORK_ITEM_NOT_FOUND",
            "error": "Not found.",
        }, 404)
    return safe_error(
        "CEO_WORK_ITEM_ERROR",
        500,
        exc=exc,
        log=f"ceo: {operation} failed admin={_admin_id()}",
    )


@ceo_work_items_bp.route("/v2/admin/ceo/bugs", methods=["GET", "POST"])
@require_admin
def ceo_bugs_collection():
    try:
        if request.method == "GET":
            return _no_store({
                "bugs": work.list_bugs(
                    request.args.get("project"), request.args.get("view")
                )
            })
        body = request.get_json(silent=True) or {}
        created = work.create_bug(
            _admin_id(),
            body.get("project"),
            body.get("text"),
            body.get("attachments"),
        )
        return _no_store(created, 202)
    except Exception as exc:
        return _failure(exc, "bugs collection")


@ceo_work_items_bp.route("/v2/admin/ceo/bugs/<bug_id>", methods=["PATCH", "DELETE"])
@require_admin
def ceo_bug_item(bug_id: str):
    try:
        project = request.args.get("project")
        if request.method == "DELETE":
            if request.args.get("confirmed") != "1":
                raise work.CeoWorkItemError("confirmed=1 is required for deletion")
            deleted = work.delete_bug(project, bug_id)
            return _no_store({"deleted": deleted})
        body = request.get_json(silent=True) or {}
        return _no_store({"bug": work.update_bug(project, bug_id, body)})
    except Exception as exc:
        return _failure(exc, "bug item")


@ceo_work_items_bp.route("/v2/admin/ceo/bugs/<bug_id>/retry", methods=["POST"])
@require_admin
def ceo_bug_retry(bug_id: str):
    try:
        return _no_store(
            work.retry_bug(request.args.get("project"), bug_id), 202
        )
    except Exception as exc:
        return _failure(exc, "bug retry")


@ceo_work_items_bp.route("/v2/admin/ceo/tasks", methods=["GET", "POST"])
@require_admin
def ceo_tasks_collection():
    try:
        if request.method == "GET":
            return _no_store({
                "tasks": work.list_tasks(
                    request.args.get("project"),
                    request.args.get("view"),
                    request.args.get("feature_id"),
                )
            })
        body = request.get_json(silent=True) or {}
        task = work.create_task(_admin_id(), body.get("project"), body)
        return _no_store({"task": task}, 201)
    except Exception as exc:
        return _failure(exc, "tasks collection")


@ceo_work_items_bp.route("/v2/admin/ceo/tasks/export", methods=["GET"])
@require_admin
def ceo_tasks_export():
    try:
        project = request.args.get("project")
        tasks = work.list_tasks(project, "active", request.args.get("feature_id"))
        markdown = work.task_markdown(project, tasks)
        name = f"ceo-{work.validate_project(project)}-tasks.md"
        return Response(
            markdown,
            mimetype="text/markdown",
            headers={
                "Content-Disposition": f"attachment; filename={name}",
                "Cache-Control": "no-store",
            },
        )
    except Exception as exc:
        return _failure(exc, "task export")


@ceo_work_items_bp.route(
    "/v2/admin/ceo/tasks/<task_id>", methods=["PATCH", "DELETE"]
)
@require_admin
def ceo_task_item(task_id: str):
    try:
        project = request.args.get("project")
        if request.method == "DELETE":
            if request.args.get("confirmed") != "1":
                raise work.CeoWorkItemError("confirmed=1 is required for deletion")
            deleted = work.delete_task(project, task_id)
            return _no_store({"deleted": deleted})
        body = request.get_json(silent=True) or {}
        return _no_store({"task": work.update_task(project, task_id, body)})
    except Exception as exc:
        return _failure(exc, "task item")


@ceo_work_items_bp.route(
    "/v2/admin/ceo/tasks/<task_id>/reorder", methods=["POST"]
)
@require_admin
def ceo_task_reorder(task_id: str):
    try:
        body = request.get_json(silent=True) or {}
        work.reorder_task(request.args.get("project"), task_id, body.get("after_id"))
        return _no_store({"ok": True})
    except Exception as exc:
        return _failure(exc, "task reorder")


@ceo_work_items_bp.route("/v2/admin/ceo/tasks/<task_id>/done", methods=["POST"])
@require_admin
def ceo_task_done(task_id: str):
    try:
        changed = work.complete_task(
            _admin_id(), request.args.get("project"), task_id
        )
        return _no_store({"ok": True, "changed": changed})
    except Exception as exc:
        return _failure(exc, "task completion")


@ceo_work_items_bp.route("/v2/admin/ceo/tasks/<task_id>/archive", methods=["POST"])
@require_admin
def ceo_task_archive(task_id: str):
    try:
        work.set_task_status(request.args.get("project"), task_id, "archived")
        return _no_store({"ok": True})
    except Exception as exc:
        return _failure(exc, "task archive")


@ceo_work_items_bp.route("/v2/admin/ceo/tasks/<task_id>/restore", methods=["POST"])
@require_admin
def ceo_task_restore(task_id: str):
    try:
        work.set_task_status(request.args.get("project"), task_id, "active")
        return _no_store({"ok": True})
    except Exception as exc:
        return _failure(exc, "task restore")
