"""Stable domain boundary for the admin-only CEO abstract.

CEO observes and describes Product and Research. It owns only ``ceo_*``
records and has no command path into application runtime data. Keeping the
small vocabulary here prevents routes and future analysis workers from
inventing parallel meanings for project, feature, lens, or surface.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import UUID, uuid4

from services.db import db


PROJECT_KEYS = ("product", "research")
SURFACES = ("overview", "bugs", "tasks", "settings")
LENSES = ("architecture", "ml", "vision")
SCOPE_KINDS = ("project", "feature")


class CeoValidationError(ValueError):
    """An admin supplied a value outside the fixed CEO vocabulary."""


class CeoConflictError(RuntimeError):
    """An artifact changed after the admin began editing it."""


def _as_rows(value: Any) -> list[dict]:
    return [row for row in (value or []) if isinstance(row, dict)]


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _latest_revisions(revisions: Iterable[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for revision in revisions:
        artifact_id = str(revision.get("artifact_id") or "")
        if not artifact_id:
            continue
        current = latest.get(artifact_id)
        if current is None or _int(revision.get("version")) > _int(
            current.get("version")
        ):
            latest[artifact_id] = revision
    return latest


def assemble_bootstrap(
    *,
    projects: Any,
    features: Any,
    artifacts: Any,
    revisions: Any,
    view_states: Any,
    timeline_events: Any = None,
    comments: Any = None,
    reevaluation_requests: Any = None,
) -> dict:
    """Shape the single initial CEO read without hiding source records.

    Only the latest artifact revision rides in the bootstrap response. The
    immutable, capped timeline supplies navigation history without returning
    every document version and making normal navigation grow forever.
    """
    project_rows = sorted(
        _as_rows(projects),
        key=lambda row: (_int(row.get("position")), row.get("name") or ""),
    )
    feature_rows = sorted(
        _as_rows(features),
        key=lambda row: (
            PROJECT_KEYS.index(row.get("project_key"))
            if row.get("project_key") in PROJECT_KEYS
            else len(PROJECT_KEYS),
            _int(row.get("position")),
            row.get("name") or "",
        ),
    )
    latest = _latest_revisions(_as_rows(revisions))
    artifact_rows = []
    for artifact in _as_rows(artifacts):
        shaped = dict(artifact)
        shaped["revision"] = latest.get(str(artifact.get("id") or ""))
        artifact_rows.append(shaped)

    states_by_project = {
        row.get("project_key"): row
        for row in _as_rows(view_states)
        if row.get("project_key") in PROJECT_KEYS
    }
    state_rows = []
    for project in project_rows:
        project_key = project.get("project_key")
        stored = states_by_project.get(project_key) or {}
        state_rows.append({
            "project_key": project_key,
            "surface": stored.get("surface") or "bugs",
            "active_feature_id": stored.get("active_feature_id"),
            "active_lens": stored.get("active_lens") or "architecture",
        })

    reevaluation_by_trigger = {
        str(row.get("trigger_id") or ""): row.get("status") or "pending"
        for row in _as_rows(reevaluation_requests)
        if row.get("trigger_type") == "admin_requested"
    }
    comment_rows = []
    for comment in _as_rows(comments):
        shaped_comment = dict(comment)
        shaped_comment["reevaluation_status"] = reevaluation_by_trigger.get(
            str(comment.get("id") or ""),
            "pending",
        )
        comment_rows.append(shaped_comment)

    return {
        "projects": project_rows,
        "features": feature_rows,
        "artifacts": artifact_rows,
        "view_state": state_rows,
        "timeline": _as_rows(timeline_events),
        "comments": comment_rows,
        "vocabulary": {
            "projects": list(PROJECT_KEYS),
            "surfaces": list(SURFACES),
            "lenses": list(LENSES),
            "scope_kinds": list(SCOPE_KINDS),
        },
    }


def get_bootstrap(admin_user_id: str) -> dict:
    """Read the CEO tree and this admin's remembered position."""
    projects = (
        db.client.table("ceo_projects")
        .select("project_key,name,position")
        .order("position")
        .execute()
        .data
    )
    features = (
        db.client.table("ceo_features")
        .select("id,project_key,slug,name,description,position,status")
        .order("position")
        .execute()
        .data
    )
    artifacts = (
        db.client.table("ceo_artifacts")
        .select(
            "id,project_key,scope_kind,feature_id,lens,artifact_kind,"
            "default_ownership"
        )
        .execute()
        .data
    )
    revisions = db.client.rpc("ceo_latest_artifact_revisions").execute().data
    view_states = (
        db.client.table("ceo_admin_view_state")
        .select("project_key,surface,active_feature_id,active_lens")
        .eq("admin_user_id", admin_user_id)
        .execute()
        .data
    )
    timeline_events = (
        db.client.table("ceo_timeline_events")
        .select(
            "id,project_key,feature_id,event_type,entity_type,entity_id,"
            "summary,payload,created_at"
        )
        .order("created_at", desc=True)
        .limit(200)
        .execute()
        .data
    )
    comments = (
        db.client.table("ceo_artifact_comments")
        .select(
            "id,artifact_id,text,status,created_by,created_at,updated_at"
        )
        .order("created_at", desc=True)
        .limit(200)
        .execute()
        .data
    )
    reevaluation_requests = (
        db.client.table("ceo_reevaluation_requests")
        .select("trigger_type,trigger_id,status")
        .eq("trigger_type", "admin_requested")
        .order("created_at", desc=True)
        .limit(200)
        .execute()
        .data
    )
    return assemble_bootstrap(
        projects=projects,
        features=features,
        artifacts=artifacts,
        revisions=revisions,
        view_states=view_states,
        timeline_events=timeline_events,
        comments=comments,
        reevaluation_requests=reevaluation_requests,
    )


def _require_choice(label: str, value: Any, allowed: tuple[str, ...]) -> str:
    clean = str(value or "").strip().lower()
    if clean not in allowed:
        raise CeoValidationError(f"{label} must be one of: {', '.join(allowed)}")
    return clean


def save_view_state(
    admin_user_id: str,
    project_key: Any,
    body: Any,
) -> dict:
    """Persist one complete navigation state after validating its address."""
    if not isinstance(body, dict):
        raise CeoValidationError("a JSON object is required")
    project = _require_choice("project_key", project_key, PROJECT_KEYS)
    surface = _require_choice("surface", body.get("surface"), SURFACES)
    lens = _require_choice("active_lens", body.get("active_lens"), LENSES)
    feature_id = str(body.get("active_feature_id") or "").strip() or None

    # Bugs are intentionally project-only and Settings is global. Clearing a
    # stale feature here makes that boundary true in storage, not just in UI.
    if surface in ("bugs", "settings"):
        feature_id = None
    elif feature_id:
        rows = (
            db.client.table("ceo_features")
            .select("id,project_key,status")
            .eq("id", feature_id)
            .eq("project_key", project)
            .eq("status", "active")
            .execute()
            .data
        )
        matching = any(
            str(row.get("id") or "") == feature_id
            and row.get("project_key") == project
            and row.get("status") == "active"
            for row in _as_rows(rows)
        )
        if not matching:
            raise CeoValidationError("active_feature_id is not active in this project")

    payload = {
        "admin_user_id": admin_user_id,
        "project_key": project,
        "surface": surface,
        "active_feature_id": feature_id,
        "active_lens": lens,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    (
        db.client.table("ceo_admin_view_state")
        .upsert(payload, on_conflict="admin_user_id,project_key")
        .execute()
    )
    return {
        "project_key": project,
        "surface": surface,
        "active_feature_id": feature_id,
        "active_lens": lens,
    }


def _require_uuid(label: str, value: Any) -> str:
    try:
        return str(UUID(str(value or "")))
    except (TypeError, ValueError, AttributeError) as exc:
        raise CeoValidationError(f"{label} must be a UUID") from exc


def _text(label: str, value: Any, *, maximum: int, required: bool = False) -> str:
    clean = str(value or "").strip()
    if required and not clean:
        raise CeoValidationError(f"{label} is required")
    if len(clean) > maximum:
        raise CeoValidationError(f"{label} must be at most {maximum} characters")
    return clean


def _identified_rows(
    label: str,
    value: Any,
    *,
    fields: tuple[str, ...],
    maximum_rows: int = 100,
    maximum_text: int = 4000,
) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise CeoValidationError(f"{label} must be a list")
    if len(value) > maximum_rows:
        raise CeoValidationError(f"{label} has too many rows")
    rows: list[dict] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise CeoValidationError(f"{label}[{index}] must be an object")
        row = {
            "id": _text(
                f"{label}[{index}].id",
                raw.get("id") or uuid4(),
                maximum=80,
                required=True,
            )
        }
        for field in fields:
            row[field] = _text(
                f"{label}[{index}].{field}",
                raw.get(field),
                maximum=maximum_text,
            )
        rows.append(row)
    return rows


def normalize_artifact_content(lens: str, content: Any) -> dict:
    """Validate one manual artifact revision against the fixed lens contract."""
    if not isinstance(content, dict):
        raise CeoValidationError("content must be an object")
    if lens == "architecture":
        return {
            "flows": _identified_rows(
                "flows", content.get("flows"), fields=("input", "measurement", "output")
            ),
            "risks": _identified_rows(
                "risks", content.get("risks"), fields=("text",)
            ),
            "next_steps": _identified_rows(
                "next_steps", content.get("next_steps"), fields=("text",)
            ),
        }
    if lens == "ml":
        nodes = _identified_rows(
            "nodes", content.get("nodes"), fields=("label", "detail")
        )
        node_ids = {row["id"] for row in nodes}
        edges = _identified_rows(
            "edges",
            content.get("edges"),
            fields=("from", "to", "label"),
            maximum_rows=200,
            maximum_text=80,
        )
        for edge in edges:
            if edge["from"] not in node_ids or edge["to"] not in node_ids:
                raise CeoValidationError("each ML edge must reference saved nodes")
        return {
            "nodes": nodes,
            "edges": edges,
            "risks": _identified_rows(
                "risks", content.get("risks"), fields=("text",)
            ),
            "next_steps": _identified_rows(
                "next_steps", content.get("next_steps"), fields=("text",)
            ),
        }
    if lens == "vision":
        return {
            "document": _text(
                "document", content.get("document"), maximum=200_000
            )
        }
    raise CeoValidationError("artifact lens is not supported")


def _artifact(artifact_id: str) -> dict:
    rows = (
        db.client.table("ceo_artifacts")
        .select("id,project_key,feature_id,lens")
        .eq("id", artifact_id)
        .execute()
        .data
    )
    artifact = next(
        (row for row in _as_rows(rows) if str(row.get("id") or "") == artifact_id),
        None,
    )
    if artifact is None:
        raise CeoValidationError("artifact does not exist")
    return artifact


def create_feature(admin_user_id: str, project_key: Any, body: Any) -> dict:
    if not isinstance(body, dict):
        raise CeoValidationError("a JSON object is required")
    project = _require_choice("project_key", project_key, PROJECT_KEYS)
    name = _text("name", body.get("name"), maximum=120, required=True)
    description = _text("description", body.get("description"), maximum=2000)
    result = (
        db.client.rpc("ceo_create_feature", {
            "p_project_key": project,
            "p_name": name,
            "p_description": description,
            "p_created_by": admin_user_id,
        })
        .execute()
        .data
    )
    rows = _as_rows(result)
    if not rows or not rows[0].get("out_feature_id"):
        raise RuntimeError("CEO feature creation returned no feature")
    return {
        "feature_id": str(rows[0]["out_feature_id"]),
        "bootstrap": get_bootstrap(admin_user_id),
    }


def save_artifact_revision(admin_user_id: str, artifact_id: Any, body: Any) -> dict:
    if not isinstance(body, dict):
        raise CeoValidationError("a JSON object is required")
    clean_artifact_id = _require_uuid("artifact_id", artifact_id)
    artifact = _artifact(clean_artifact_id)
    expected_version = _int(body.get("expected_version"), -1)
    if expected_version < 0:
        raise CeoValidationError("expected_version is required")
    current_rows = (
        db.client.table("ceo_artifact_revisions")
        .select("version")
        .eq("artifact_id", clean_artifact_id)
        .order("version", desc=True)
        .limit(1)
        .execute()
        .data
    )
    current_version = max(
        (_int(row.get("version")) for row in _as_rows(current_rows)),
        default=0,
    )
    if current_version != expected_version:
        raise CeoConflictError("artifact changed; reload before saving")
    content = normalize_artifact_content(str(artifact.get("lens") or ""), body.get("content"))
    result = (
        db.client.rpc("ceo_save_artifact_revision", {
            "p_artifact_id": clean_artifact_id,
            "p_content": content,
            "p_created_by": admin_user_id,
            "p_expected_version": expected_version,
        })
        .execute()
        .data
    )
    if not _as_rows(result):
        raise CeoConflictError("artifact changed; reload before saving")
    return {
        "artifact_id": clean_artifact_id,
        "bootstrap": get_bootstrap(admin_user_id),
    }


def comment_and_request_reevaluation(
    admin_user_id: str,
    artifact_id: Any,
    body: Any,
) -> dict:
    if not isinstance(body, dict):
        raise CeoValidationError("a JSON object is required")
    clean_artifact_id = _require_uuid("artifact_id", artifact_id)
    _artifact(clean_artifact_id)
    text = _text("comment", body.get("comment"), maximum=10_000, required=True)
    result = (
        db.client.rpc("ceo_comment_and_request_reevaluation", {
            "p_artifact_id": clean_artifact_id,
            "p_comment": text,
            "p_created_by": admin_user_id,
        })
        .execute()
        .data
    )
    rows = _as_rows(result)
    if not rows or not rows[0].get("out_comment_id"):
        raise RuntimeError("CEO reevaluation request returned no comment")
    return {
        "comment_id": str(rows[0]["out_comment_id"]),
        "bootstrap": get_bootstrap(admin_user_id),
    }
