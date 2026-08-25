"""Stable domain boundary for the admin-only CEO abstract.

CEO observes and describes Product and Research. It owns only ``ceo_*``
records and has no command path into application runtime data. Keeping the
small vocabulary here prevents routes and future analysis workers from
inventing parallel meanings for project, feature, lens, or surface.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from services.db import db


PROJECT_KEYS = ("product", "research")
SURFACES = ("overview", "bugs", "tasks", "settings")
LENSES = ("architecture", "ml", "vision")
SCOPE_KINDS = ("project", "feature")


class CeoValidationError(ValueError):
    """An admin supplied a value outside the fixed CEO vocabulary."""


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
) -> dict:
    """Shape the single initial CEO read without hiding source records.

    Only the latest artifact revision rides in the bootstrap response. Full
    revision history will have its own endpoint when editing is introduced;
    returning every version here would make normal navigation grow forever.
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

    return {
        "projects": project_rows,
        "features": feature_rows,
        "artifacts": artifact_rows,
        "view_state": state_rows,
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
    revisions = (
        db.client.table("ceo_artifact_revisions")
        .select(
            "id,artifact_id,version,content,ownership,status,created_by,created_at"
        )
        .order("version", desc=True)
        .execute()
        .data
    )
    view_states = (
        db.client.table("ceo_admin_view_state")
        .select("project_key,surface,active_feature_id,active_lens")
        .eq("admin_user_id", admin_user_id)
        .execute()
        .data
    )
    return assemble_bootstrap(
        projects=projects,
        features=features,
        artifacts=artifacts,
        revisions=revisions,
        view_states=view_states,
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
