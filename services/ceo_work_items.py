"""Admin-only Bugs and Tasks for CEO.

The module owns only ``ceo_*`` records. A bug creates one fallback task
atomically; model enrichment is best-effort and can never make capture fail.
Manual feature corrections and task edits are protected from a late model
response.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from services.ceo import PROJECT_KEYS
from services.db import db


logger = logging.getLogger(__name__)

BUG_COLS = (
    "id,project_key,feature_id,text,attachments,status,"
    "classification_status,created_at,updated_at,archived_at"
)
TASK_COLS = (
    "id,project_key,feature_id,bug_id,title,user_story,body,attachments,"
    "priority,order_key,status,generation_status,manually_edited,created_at,"
    "updated_at,done_at,archived_at"
)
MAX_TEXT_CHARS = 12_000
MAX_TASK_CHARS = 20_000
MAX_ATTACHMENTS = 4
MAX_ATTACHMENT_CHARS = 420_000
MAX_ATTACHMENTS_TOTAL_CHARS = 1_300_000


class CeoWorkItemError(ValueError):
    """A safe, admin-facing validation failure."""


class CeoWorkItemNotFound(LookupError):
    """The requested CEO entity does not exist in the stated project."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_project(value: Any) -> str:
    project = str(value or "").strip().lower()
    if project not in PROJECT_KEYS:
        raise CeoWorkItemError("project must be product or research")
    return project


def normalize_attachments(value: Any) -> list[dict]:
    """Return bounded attachment records, accepting legacy data-URL strings."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise CeoWorkItemError("attachments must be a list")
    if len(value) > MAX_ATTACHMENTS:
        raise CeoWorkItemError(f"at most {MAX_ATTACHMENTS} attachments are allowed")
    out: list[dict] = []
    total = 0
    for item in value:
        if isinstance(item, str):
            kind, data_url, name = "image", item, ""
        elif isinstance(item, dict):
            kind = str(item.get("kind") or "image").strip().lower()
            data_url = str(item.get("data_url") or item.get("url") or "").strip()
            name = str(item.get("name") or "").strip()[:160]
        else:
            raise CeoWorkItemError("each attachment must be an object")
        if kind not in ("image", "audio"):
            raise CeoWorkItemError("attachment kind must be image or audio")
        expected = "data:image/" if kind == "image" else "data:audio/"
        if not data_url.startswith(expected) and not data_url.startswith("https://"):
            raise CeoWorkItemError(f"{kind} attachment must be a data URL")
        if len(data_url) > MAX_ATTACHMENT_CHARS:
            raise CeoWorkItemError("an attachment is too large")
        total += len(data_url)
        if total > MAX_ATTACHMENTS_TOTAL_CHARS:
            raise CeoWorkItemError("attachments are too large in total")
        out.append({"kind": kind, "data_url": data_url, "name": name})
    return out


def _rows(value: Any) -> list[dict]:
    return [row for row in (value or []) if isinstance(row, dict)]


def _one(rows: Any) -> dict | None:
    shaped = _rows(rows)
    return shaped[0] if shaped else None


def _feature(project: str, feature_id: Any) -> dict | None:
    clean = str(feature_id or "").strip()
    if not clean:
        return None
    result = (
        db.client.table("ceo_features")
        .select("id,project_key,name,status")
        .eq("id", clean)
        .eq("project_key", project)
        .execute()
    )
    match = next(
        (
            row
            for row in _rows(result.data)
            if str(row.get("id") or "") == clean
            and row.get("project_key") == project
            and row.get("status") == "active"
        ),
        None,
    )
    if match is None:
        raise CeoWorkItemError("feature is not active in this project")
    return match


def list_bugs(project_key: Any, view: Any = "open") -> list[dict]:
    project = validate_project(project_key)
    status = "archived" if str(view or "").lower() == "archive" else "open"
    result = (
        db.client.table("ceo_bugs")
        .select(BUG_COLS)
        .eq("project_key", project)
        .eq("status", status)
        .order("created_at", desc=True)
        .execute()
    )
    return [
        {**row, "attachments": normalize_attachments(row.get("attachments"))}
        for row in _rows(result.data)
    ]


def _spawn_enrichment(bug_id: str, task_id: str) -> None:
    def run() -> None:
        try:
            enrich_bug_task(bug_id, task_id)
        except Exception:
            logger.exception("ceo: bug enrichment failed bug=%s", bug_id)
            _mark_enrichment_failed(bug_id, task_id)

    try:
        threading.Thread(target=run, daemon=True, name="ceo-bug-enrichment").start()
    except Exception:
        logger.exception("ceo: could not start bug enrichment bug=%s", bug_id)
        _mark_enrichment_failed(bug_id, task_id)


def create_bug(
    admin_user_id: str,
    project_key: Any,
    text: Any,
    attachments: Any,
) -> dict:
    project = validate_project(project_key)
    clean_text = str(text or "").strip()
    if len(clean_text) > MAX_TEXT_CHARS:
        raise CeoWorkItemError(f"bug text must be at most {MAX_TEXT_CHARS} characters")
    clean_attachments = normalize_attachments(attachments)
    if not clean_text and not clean_attachments:
        raise CeoWorkItemError("bug text or an attachment is required")
    result = db.client.rpc(
        "ceo_create_bug_with_task",
        {
            "p_project_key": project,
            "p_text": clean_text,
            "p_attachments": clean_attachments,
            "p_created_by": admin_user_id,
        },
    ).execute()
    row = _one(result.data)
    if not row or not row.get("out_bug_id") or not row.get("out_task_id"):
        raise RuntimeError("CEO bug creation returned no work item ids")
    bug_id = str(row["out_bug_id"])
    task_id = str(row["out_task_id"])
    _spawn_enrichment(bug_id, task_id)
    return {"bug_id": bug_id, "task_id": task_id, "generation_status": "pending"}


def _model_draft(project: str, text: str, features: list[dict]) -> dict | None:
    if not text:
        return None
    try:
        from services.openai_service import openai_service

        client = openai_service.client
        if client is None:
            return None
        feature_lines = "\n".join(
            f'- id={row.get("id")} name={row.get("name")}' for row in features
        ) or "- no active features"
        system = f"""You turn one raw CEO bug into one coding-agent-ready task.
The project is {project.upper()}. Never move it to another project.
Choose feature_id only from the exact active list below, or null when uncertain.

ACTIVE FEATURES
{feature_lines}

Return strict JSON only:
{{
  "feature_id": "<exact id>" | null,
  "title": "<concise task title>",
  "user_story": "As a <role>, I want <outcome>, so that <benefit>.",
  "body": "<self-contained context, implementation request, and acceptance checks>",
  "priority": 1 | 2 | 3
}}"""
        response = client.chat.completions.create(
            model=openai_service._chat_model("copilot"),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": text[:8000]},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
            timeout=40,
        )
        raw = (response.choices[0].message.content or "").strip()
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except Exception as exc:
        logger.warning("ceo: model draft failed: %s", exc)
        return None


def _priority(value: Any, default: int = 2) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if 1 <= parsed <= 3 else default


def _mark_enrichment_failed(bug_id: str, task_id: str) -> None:
    (
        db.client.table("ceo_bugs")
        .update({"classification_status": "failed", "updated_at": _now()})
        .eq("id", bug_id)
        .eq("classification_status", "pending")
        .execute()
    )
    (
        db.client.table("ceo_tasks")
        .update({"generation_status": "failed", "updated_at": _now()})
        .eq("id", task_id)
        .eq("generation_status", "pending")
        .execute()
    )


def enrich_bug_task(bug_id: str, task_id: str) -> bool:
    bug = _one(
        db.client.table("ceo_bugs")
        .select(BUG_COLS)
        .eq("id", bug_id)
        .execute()
        .data
    )
    task = _one(
        db.client.table("ceo_tasks")
        .select(TASK_COLS)
        .eq("id", task_id)
        .eq("bug_id", bug_id)
        .execute()
        .data
    )
    if bug is None or task is None:
        return False
    project = validate_project(bug.get("project_key"))
    features = _rows(
        db.client.table("ceo_features")
        .select("id,project_key,name,status")
        .eq("project_key", project)
        .eq("status", "active")
        .execute()
        .data
    )
    draft = _model_draft(project, str(bug.get("text") or ""), features)
    if not draft:
        _mark_enrichment_failed(bug_id, task_id)
        return False

    allowed_features = {str(row.get("id")) for row in features}
    proposed_feature = str(draft.get("feature_id") or "").strip() or None
    if proposed_feature not in allowed_features:
        proposed_feature = None
    feature_id = (
        bug.get("feature_id")
        if bug.get("classification_status") == "manual"
        else proposed_feature
    )

    if bug.get("classification_status") != "manual":
        (
            db.client.table("ceo_bugs")
            .update({
                "feature_id": feature_id,
                "classification_status": "classified",
                "updated_at": _now(),
            })
            .eq("id", bug_id)
            .neq("classification_status", "manual")
            .execute()
        )

    if task.get("manually_edited") is not True:
        title = str(draft.get("title") or task.get("title") or "Task").strip()
        body = str(draft.get("body") or task.get("body") or "").strip()
        user_story = str(draft.get("user_story") or "").strip() or None
        (
            db.client.table("ceo_tasks")
            .update({
                "feature_id": feature_id,
                "title": title[:240],
                "user_story": user_story,
                "body": body[:MAX_TASK_CHARS],
                "priority": _priority(draft.get("priority")),
                "generation_status": "ready",
                "updated_at": _now(),
            })
            .eq("id", task_id)
            .eq("manually_edited", False)
            .execute()
        )
    else:
        (
            db.client.table("ceo_tasks")
            .update({
                "feature_id": feature_id,
                "generation_status": "manual",
                "updated_at": _now(),
            })
            .eq("id", task_id)
            .execute()
        )
    return True


def retry_bug(project_key: Any, bug_id: str) -> dict:
    project = validate_project(project_key)
    bug = _one(
        db.client.table("ceo_bugs")
        .select("id,project_key,classification_status")
        .eq("id", bug_id)
        .eq("project_key", project)
        .execute()
        .data
    )
    task = _one(
        db.client.table("ceo_tasks")
        .select("id,bug_id,manually_edited")
        .eq("bug_id", bug_id)
        .eq("project_key", project)
        .execute()
        .data
    )
    if bug is None or task is None:
        raise CeoWorkItemNotFound("bug or its task was not found")
    if bug.get("classification_status") != "manual":
        db.client.table("ceo_bugs").update({
            "classification_status": "pending", "updated_at": _now(),
        }).eq("id", bug_id).execute()
    if task.get("manually_edited") is not True:
        db.client.table("ceo_tasks").update({
            "generation_status": "pending", "updated_at": _now(),
        }).eq("id", task.get("id")).execute()
    task_id = str(task["id"])
    _spawn_enrichment(bug_id, task_id)
    return {"bug_id": bug_id, "task_id": task_id, "generation_status": "pending"}


def update_bug(project_key: Any, bug_id: str, fields: Any) -> dict:
    project = validate_project(project_key)
    if not isinstance(fields, dict):
        raise CeoWorkItemError("a JSON object is required")
    payload: dict[str, Any] = {"updated_at": _now()}
    if "text" in fields:
        text = str(fields.get("text") or "").strip()
        if len(text) > MAX_TEXT_CHARS:
            raise CeoWorkItemError("bug text is too long")
        payload["text"] = text
    if "feature_id" in fields:
        match = _feature(project, fields.get("feature_id"))
        payload["feature_id"] = match.get("id") if match else None
        payload["classification_status"] = "manual"
    if "status" in fields:
        status = str(fields.get("status") or "").strip().lower()
        if status not in ("open", "archived"):
            raise CeoWorkItemError("bug status must be open or archived")
        payload["status"] = status
        payload["archived_at"] = _now() if status == "archived" else None
    result = (
        db.client.table("ceo_bugs")
        .update(payload)
        .eq("id", bug_id)
        .eq("project_key", project)
        .execute()
    )
    row = _one(result.data)
    if row is None:
        raise CeoWorkItemNotFound("bug was not found")
    if "feature_id" in payload:
        (
            db.client.table("ceo_tasks")
            .update({"feature_id": payload["feature_id"], "updated_at": _now()})
            .eq("bug_id", bug_id)
            .eq("project_key", project)
            .execute()
        )
    return {**row, "attachments": normalize_attachments(row.get("attachments"))}


def delete_bug(project_key: Any, bug_id: str) -> bool:
    project = validate_project(project_key)
    row = _one(
        db.client.table("ceo_bugs")
        .select("id,project_key")
        .eq("id", bug_id)
        .eq("project_key", project)
        .execute()
        .data
    )
    if row is None:
        raise CeoWorkItemNotFound("bug was not found")
    result = (
        db.client.table("ceo_bugs")
        .delete()
        .eq("id", bug_id)
        .eq("project_key", project)
        .execute()
    )
    return bool(result.data)


def list_tasks(project_key: Any, view: Any = "active", feature_id: Any = None) -> list[dict]:
    project = validate_project(project_key)
    requested = str(view or "active").strip().lower()
    status = requested if requested in ("active", "done", "archived") else "active"
    query = (
        db.client.table("ceo_tasks")
        .select(TASK_COLS)
        .eq("project_key", project)
        .eq("status", status)
    )
    if feature_id:
        match = _feature(project, feature_id)
        query = query.eq("feature_id", match["id"] if match else "")
    result = query.order(
        "done_at" if status == "done" else "archived_at" if status == "archived" else "order_key",
        desc=status != "active",
    ).execute()
    return [
        {**row, "attachments": normalize_attachments(row.get("attachments"))}
        for row in _rows(result.data)
    ]


def _next_order_key(project: str) -> float:
    rows = _rows(
        db.client.table("ceo_tasks")
        .select("order_key")
        .eq("project_key", project)
        .order("order_key", desc=True)
        .limit(1)
        .execute()
        .data
    )
    try:
        return float(rows[0].get("order_key") or 0) + 1000 if rows else 1000
    except (TypeError, ValueError):
        return 1000


def _record_event(
    project: str,
    feature_id: str | None,
    event_type: str,
    entity_type: str,
    entity_id: str,
    summary: str,
    admin_user_id: str,
) -> None:
    db.client.table("ceo_timeline_events").insert({
        "project_key": project,
        "feature_id": feature_id,
        "event_type": event_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "summary": summary[:500],
        "created_by": admin_user_id,
    }).execute()


def create_task(admin_user_id: str, project_key: Any, fields: Any) -> dict:
    project = validate_project(project_key)
    if not isinstance(fields, dict):
        raise CeoWorkItemError("a JSON object is required")
    body = str(fields.get("body") or "").strip()
    title = str(fields.get("title") or "").strip()
    if not body:
        raise CeoWorkItemError("task body is required")
    if len(body) > MAX_TASK_CHARS:
        raise CeoWorkItemError("task body is too long")
    if not title:
        title = body.splitlines()[0][:100] or "Manual task"
    match = _feature(project, fields.get("feature_id")) if fields.get("feature_id") else None
    feature_id = str(match.get("id")) if match else None
    payload: dict[str, Any] = {
        "project_key": project,
        "feature_id": feature_id,
        "title": title[:240],
        "user_story": str(fields.get("user_story") or "").strip() or None,
        "body": body,
        "attachments": [],
        "priority": _priority(fields.get("priority")),
        "order_key": _next_order_key(project),
        "status": "active",
        "generation_status": "manual",
        "manually_edited": True,
        "created_by": admin_user_id,
    }
    result = db.client.table("ceo_tasks").insert(payload).execute()
    row = _one(result.data)
    if row is None:
        raise RuntimeError("CEO task creation returned no row")
    _record_event(
        project,
        feature_id,
        "task_created",
        "task",
        str(row.get("id")),
        title,
        admin_user_id,
    )
    return row


def update_task(project_key: Any, task_id: str, fields: Any) -> dict:
    project = validate_project(project_key)
    if not isinstance(fields, dict):
        raise CeoWorkItemError("a JSON object is required")
    payload: dict[str, Any] = {"manually_edited": True, "updated_at": _now()}
    for key, limit in (("title", 240), ("user_story", 1000), ("body", MAX_TASK_CHARS)):
        if key in fields:
            value = str(fields.get(key) or "").strip()
            if key in ("title", "body") and not value:
                raise CeoWorkItemError(f"task {key} must not be empty")
            payload[key] = value[:limit] or None
    if "priority" in fields:
        raw_priority = fields.get("priority")
        parsed = _priority(raw_priority, 0)
        if parsed == 0:
            raise CeoWorkItemError("priority must be 1, 2, or 3")
        payload["priority"] = parsed
    feature_was_set = "feature_id" in fields
    if feature_was_set:
        match = _feature(project, fields.get("feature_id"))
        payload["feature_id"] = match.get("id") if match else None
    result = (
        db.client.table("ceo_tasks")
        .update(payload)
        .eq("id", task_id)
        .eq("project_key", project)
        .execute()
    )
    row = _one(result.data)
    if row is None:
        raise CeoWorkItemNotFound("task was not found")
    if feature_was_set and row.get("bug_id"):
        db.client.table("ceo_bugs").update({
            "feature_id": payload.get("feature_id"),
            "classification_status": "manual",
            "updated_at": _now(),
        }).eq("id", row.get("bug_id")).eq("project_key", project).execute()
    return {**row, "attachments": normalize_attachments(row.get("attachments"))}


def plan_reorder(tasks: list[dict], task_id: str, after_id: str | None) -> float:
    ordered = sorted(tasks, key=lambda row: float(row.get("order_key") or 0))
    others = [row for row in ordered if str(row.get("id")) != task_id]
    if not others:
        return 0
    if after_id is None:
        return float(others[0].get("order_key") or 0) - 1
    index = next(
        (i for i, row in enumerate(others) if str(row.get("id")) == after_id),
        None,
    )
    if index is None:
        raise CeoWorkItemError("after_id is not an active task in this project")
    before = float(others[index].get("order_key") or 0)
    if index + 1 >= len(others):
        return before + 1
    after = float(others[index + 1].get("order_key") or 0)
    return (before + after) / 2


def reorder_task(project_key: Any, task_id: str, after_id: Any) -> None:
    project = validate_project(project_key)
    clean_after = str(after_id or "").strip() or None
    tasks = list_tasks(project, "active")
    if not any(str(row.get("id")) == task_id for row in tasks):
        raise CeoWorkItemNotFound("task was not found")
    new_key = plan_reorder(tasks, task_id, clean_after)
    db.client.table("ceo_tasks").update({
        "order_key": new_key, "updated_at": _now(),
    }).eq("id", task_id).eq("project_key", project).eq("status", "active").execute()


def complete_task(admin_user_id: str, project_key: Any, task_id: str) -> bool:
    project = validate_project(project_key)
    row = _one(
        db.client.table("ceo_tasks")
        .select("id,project_key")
        .eq("id", task_id)
        .eq("project_key", project)
        .execute()
        .data
    )
    if row is None:
        raise CeoWorkItemNotFound("task was not found")
    result = db.client.rpc(
        "ceo_complete_task",
        {"p_task_id": task_id, "p_admin_user_id": admin_user_id},
    ).execute()
    return bool(_rows(result.data))


def set_task_status(project_key: Any, task_id: str, status: str) -> None:
    project = validate_project(project_key)
    if status not in ("active", "archived"):
        raise CeoWorkItemError("unsupported task status")
    payload: dict[str, Any] = {
        "status": status,
        "updated_at": _now(),
        "archived_at": _now() if status == "archived" else None,
    }
    if status == "active":
        payload.update({
            "done_at": None,
            "order_key": _next_order_key(project),
        })
    result = (
        db.client.table("ceo_tasks")
        .update(payload)
        .eq("id", task_id)
        .eq("project_key", project)
        .execute()
    )
    if not result.data:
        raise CeoWorkItemNotFound("task was not found")


def delete_task(project_key: Any, task_id: str) -> bool:
    project = validate_project(project_key)
    task = _one(
        db.client.table("ceo_tasks")
        .select("id,project_key,bug_id")
        .eq("id", task_id)
        .eq("project_key", project)
        .execute()
        .data
    )
    if task is None:
        raise CeoWorkItemNotFound("task was not found")
    if task.get("bug_id"):
        return delete_bug(project, str(task["bug_id"]))
    result = (
        db.client.table("ceo_tasks")
        .delete()
        .eq("id", task_id)
        .eq("project_key", project)
        .execute()
    )
    return bool(result.data)


def task_markdown(project_key: Any, tasks: list[dict]) -> str:
    project = validate_project(project_key)
    lines = [f"# CEO — {project.title()} tasks", ""]
    for index, task in enumerate(tasks, 1):
        lines.extend([
            f"## {index}. [P{task.get('priority', 2)}] {task.get('title') or 'Task'}",
            "",
        ])
        if task.get("user_story"):
            lines.extend([str(task["user_story"]), ""])
        lines.extend([str(task.get("body") or "").strip(), ""])
        for attachment_index, attachment in enumerate(
            normalize_attachments(task.get("attachments")), 1
        ):
            if attachment.get("kind") == "image":
                lines.extend([
                    f"![attachment {attachment_index}]({attachment['data_url']})",
                    "",
                ])
    return "\n".join(lines).strip() + "\n"
