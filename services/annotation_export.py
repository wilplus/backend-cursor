"""
Export admin_annotation_events to JSONL and record runs in admin_annotation_export_runs.

Used by scripts/export_annotation_events.py, admin HTTP trigger, and internal cron trigger.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from services.db import db

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_hash(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_checkpoint() -> tuple[Optional[str], Optional[str]]:
    rows = (
        db.client.table("admin_annotation_export_runs")
        .select("checkpoint_created_at,checkpoint_event_id,status,ended_at")
        .eq("status", "success")
        .order("ended_at", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        return None, None
    row = rows[0]
    return row.get("checkpoint_created_at"), row.get("checkpoint_event_id")


def _insert_run_start(created_by: str) -> dict:
    payload = {
        "status": "running",
        "started_at": _now_iso(),
        "created_by": created_by,
        "metadata": {},
    }
    res = db.client.table("admin_annotation_export_runs").insert(payload).execute()
    if not res.data:
        raise RuntimeError("Failed to create export run row")
    return res.data[0]


def _update_run(run_id: str, payload: dict) -> None:
    body = dict(payload)
    body["ended_at"] = _now_iso()
    db.client.table("admin_annotation_export_runs").update(body).eq("id", run_id).execute()


def _upload_bytes(*, bucket: str, path: str, data: bytes, content_type: str) -> None:
    db.client.storage.from_(bucket).upload(
        path=path,
        file=data,
        file_options={"content-type": content_type},
    )


@dataclass
class AnnotationExportResult:
    run_id: str
    status: str
    processed_count: int
    exported_count: int
    failed_count: int
    checkpoint_created_at: Optional[str]
    checkpoint_event_id: Optional[str]
    artifact_path: Optional[str]
    storage_uri: Optional[str]
    error_text: Optional[str]


def run_annotation_export(
    *,
    limit: int = 5000,
    output_dir: Optional[str] = None,
    dry_run: bool = False,
    created_by: str = "annotation_export",
    upload_bucket: Optional[str] = None,
    upload_prefix: str = "annotation-events",
) -> AnnotationExportResult:
    """
    Pull new rows from admin_annotation_events since last successful checkpoint,
    write JSONL (optional), optionally upload to Supabase Storage, advance checkpoint.
    """
    limit = max(1, min(50000, int(limit)))
    checkpoint_created_at, checkpoint_event_id = _load_checkpoint()
    run_row = _insert_run_start(created_by)
    run_id = str(run_row.get("id") or "")

    try:
        query = (
            db.client.table("admin_annotation_events")
            .select("*")
            .order("created_at", desc=False)
            .order("id", desc=False)
            .limit(limit)
        )
        if checkpoint_created_at:
            query = query.gt("created_at", checkpoint_created_at)
        events = query.execute().data or []

        processed = len(events)
        exported = 0
        failed = 0
        last_created_at = checkpoint_created_at
        last_event_id = checkpoint_event_id

        lines: list[str] = []
        for ev in events:
            try:
                prev_hash = ev.get("previous_value_hash") or _to_hash(ev.get("ai_original_text"))
                new_hash = ev.get("new_value_hash") or _to_hash(ev.get("coach_final_text"))
                line = {
                    "event_id": ev.get("id"),
                    "student_id": ev.get("user_id"),
                    "session_id": ev.get("session_id"),
                    "draft_id": ev.get("draft_id"),
                    "section_type": ev.get("section_type"),
                    "field_name": ev.get("field_name"),
                    "previous_value_hash": prev_hash,
                    "new_value_hash": new_hash,
                    "reason_chip": ev.get("reason_chip"),
                    "custom_reason": ev.get("custom_reason"),
                    "created_by": ev.get("created_by"),
                    "created_at": ev.get("created_at"),
                }
                lines.append(json.dumps(line, ensure_ascii=True))
                exported += 1
                last_created_at = ev.get("created_at") or last_created_at
                last_event_id = ev.get("id") or last_event_id
            except Exception:
                failed += 1

        artifact_path_str: Optional[str] = None
        storage_uri: Optional[str] = None
        body_bytes: Optional[bytes] = None
        wrote_any = False
        if lines:
            body_bytes = ("\n".join(lines) + "\n").encode("utf-8")

        if not dry_run and body_bytes:
            if not upload_bucket and not output_dir:
                raise RuntimeError(
                    "Annotation export needs a sink: set upload_bucket (Supabase Storage) "
                    "and/or output_dir (local path)."
                )
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            filename = f"admin-annotation-events-{ts}.jsonl"
            if upload_bucket:
                prefix = (upload_prefix or "annotation-events").strip().strip("/")
                object_path = f"{prefix}/{filename}"
                _upload_bytes(
                    bucket=upload_bucket,
                    path=object_path,
                    data=body_bytes,
                    content_type="application/x-ndjson",
                )
                storage_uri = f"storage://{upload_bucket}/{object_path}"
                wrote_any = True
            if output_dir:
                out_dir = Path(output_dir)
                out_dir.mkdir(parents=True, exist_ok=True)
                p = out_dir / filename
                p.write_bytes(body_bytes)
                artifact_path_str = str(p)
                wrote_any = True
            if not wrote_any:
                raise RuntimeError("Annotation export: no successful write (configure bucket and/or output_dir)")

        # Dry-run must not advance checkpoint (would skip events on next real export).
        cp_at = last_created_at if not dry_run else checkpoint_created_at
        cp_id = last_event_id if not dry_run else checkpoint_event_id

        _update_run(
            run_id,
            {
                "status": "success",
                "checkpoint_created_at": cp_at,
                "checkpoint_event_id": cp_id,
                "processed_count": processed,
                "exported_count": exported,
                "failed_count": failed,
                "export_uri": None if dry_run else (storage_uri or artifact_path_str),
                "metadata": {
                    "dry_run": dry_run,
                    "limit": limit,
                    "input_checkpoint_created_at": checkpoint_created_at,
                    "input_checkpoint_event_id": checkpoint_event_id,
                    "local_path": None if dry_run else artifact_path_str,
                    "storage_uri": None if dry_run else storage_uri,
                },
            },
        )
        return AnnotationExportResult(
            run_id=run_id,
            status="success",
            processed_count=processed,
            exported_count=exported,
            failed_count=failed,
            checkpoint_created_at=cp_at,
            checkpoint_event_id=str(cp_id) if cp_id else None,
            artifact_path=None if dry_run else artifact_path_str,
            storage_uri=None if dry_run else storage_uri,
            error_text=None,
        )
    except Exception as exc:
        _update_run(
            run_id,
            {
                "status": "failed",
                "processed_count": 0,
                "exported_count": 0,
                "failed_count": 1,
                "error_text": str(exc),
                "metadata": {
                    "dry_run": dry_run,
                    "limit": limit,
                    "input_checkpoint_created_at": checkpoint_created_at,
                    "input_checkpoint_event_id": checkpoint_event_id,
                },
            },
        )
        raise


def result_to_dict(r: AnnotationExportResult) -> dict:
    return {
        "run_id": r.run_id,
        "status": r.status,
        "processed_count": r.processed_count,
        "exported_count": r.exported_count,
        "failed_count": r.failed_count,
        "checkpoint_created_at": r.checkpoint_created_at,
        "checkpoint_event_id": r.checkpoint_event_id,
        "artifact_path": r.artifact_path,
        "storage_uri": r.storage_uri,
        "error_text": r.error_text,
    }
