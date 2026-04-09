#!/usr/bin/env python3
"""
Normalize existing admin_student_send_drafts payloads to canonical contract.

Editable fields (always present when recoverable):
  - email_draft
  - task_draft
  - script_draft

AI baselines:
  - ai_email_draft
  - ai_task_suggestion
  - ai_script_draft

Compatibility alias:
  - video_script mirrors script_draft

Usage:
  python3 scripts/backfill_copilot_draft_contract.py --dry-run
  python3 scripts/backfill_copilot_draft_contract.py --status pending --limit 1000
  python3 scripts/backfill_copilot_draft_contract.py --user-id <uuid>
"""

import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.db import db  # noqa: E402


def _first_non_empty(*values):
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _payload(row: dict) -> dict:
    payload = row.get("draft_payload")
    return payload if isinstance(payload, dict) else {}


def _normalize(row: dict) -> dict:
    base = dict(_payload(row))
    ai_email = _first_non_empty(base.get("ai_email_draft"), row.get("ai_draft_message"))
    ai_task = _first_non_empty(
        base.get("ai_task_suggestion"),
        row.get("ai_suggested_task_text"),
        row.get("master_task_text"),
    )
    ai_script = _first_non_empty(base.get("ai_script_draft"), row.get("ai_draft_video_script"))

    email_draft = _first_non_empty(
        base.get("email_draft"),
        base.get("email_message"),
        base.get("homework_comment"),
        ai_email,
    )
    task_draft = _first_non_empty(
        base.get("task_draft"),
        base.get("task_text"),
        ai_task,
        row.get("master_task_text"),
    )
    script_draft = _first_non_empty(
        base.get("script_draft"),
        base.get("video_script"),
        ai_script,
    )

    base["ai_email_draft"] = ai_email
    base["ai_task_suggestion"] = ai_task
    base["ai_script_draft"] = ai_script
    base["email_draft"] = email_draft
    base["task_draft"] = task_draft
    base["script_draft"] = script_draft
    base["video_script"] = script_draft
    return base


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser(description="Backfill copilot draft payload contract.")
    parser.add_argument("--user-id", type=str, default=None, help="Scope to one user_id")
    parser.add_argument("--status", type=str, default=None, help="Filter by row status (pending/sent)")
    parser.add_argument("--limit", type=int, default=3000, help="Max rows to scan")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing")
    args = parser.parse_args()

    status = (args.status or "").strip().lower() or None
    limit = max(1, min(10000, int(args.limit)))

    rows = db.list_admin_student_send_drafts(status=status)[:limit]
    if args.user_id:
        rows = [r for r in rows if str(r.get("user_id") or "") == args.user_id]

    if not rows:
        print("No rows found.")
        return

    changed = 0
    for row in rows:
        row_id = row.get("id")
        user_id = row.get("user_id")
        original = _payload(row)
        normalized = _normalize(row)
        if normalized == original:
            continue

        changed += 1
        task_preview = (_first_non_empty(normalized.get("task_draft")) or "")[:80]
        print(f"{'DRY' if args.dry_run else 'UPD'} {row_id} user={user_id} task='{task_preview}'")

        if args.dry_run:
            continue

        update_body = {
            "draft_payload": normalized,
            "updated_at": _now_iso(),
        }
        task_text = _first_non_empty(normalized.get("task_draft"))
        if task_text:
            update_body["master_task_text"] = task_text
        db.client.table("admin_student_send_drafts").update(update_body).eq("id", row_id).execute()

    print(f"Done. scanned={len(rows)} changed={changed} dry_run={args.dry_run}")


if __name__ == "__main__":
    main()
