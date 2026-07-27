#!/usr/bin/env python3
"""Backfill dev_tasks.images from the source bug's screenshots.

`dev_tasks.images` is only populated at generation time (services/dev_tasks.py,
inside the insert), and the column landed later than the tasks themselves
(migrations/add_dev_tasks_images.sql, default '[]'). So every task generated
before that migration has an EMPTY images array even though its source bug still
carries the screenshot — which means Copy all / Export have nothing to hand over
for those rows. This copies them across, once.

Reads `dev_bugs` via services.dev_bugs._bug_images, so the legacy single
`image_url` (rows predating multi-image) is picked up too, not just the array.

Idempotent — only touches tasks whose images array is empty AND whose bug
actually has one, so re-running is a no-op. Tasks with images already, or with no
bug_id, or whose bug is gone, are left alone.

Usage:
    python3 scripts/backfill_dev_task_images.py --dry-run
    python3 scripts/backfill_dev_task_images.py
    python3 scripts/backfill_dev_task_images.py --limit 50
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.db import db  # noqa: E402
from services.dev_bugs import _bug_images  # noqa: E402

logger = logging.getLogger("backfill_dev_task_images")

_TASKS = "dev_tasks"
_BUGS = "dev_bugs"


def _tasks_missing_images(limit: int) -> list[dict]:
    """Tasks with a bug_id whose images array is empty (archived ones included —
    an archived task is still exportable history)."""
    res = (
        db.client.table(_TASKS)
        .select("id,bug_id,images,status")
        .not_.is_("bug_id", "null")
        .order("id", desc=False)
        .limit(limit)
        .execute()
    )
    rows = res.data or []
    return [r for r in rows if not (r.get("images") or [])]


def _bug_map(bug_ids: list[int]) -> dict[int, list[str]]:
    """bug_id -> its images, for the bugs these tasks came from."""
    if not bug_ids:
        return {}
    res = (
        db.client.table(_BUGS)
        .select("id,image_url,images")
        .in_("id", bug_ids)
        .execute()
    )
    return {row["id"]: _bug_images(row) for row in (res.data or [])}


def run_backfill(*, limit: int, dry_run: bool) -> tuple[int, int]:
    tasks = _tasks_missing_images(limit)
    logger.info("tasks with an empty images array: %d", len(tasks))
    if not tasks:
        return 0, 0

    bugs = _bug_map(sorted({int(t["bug_id"]) for t in tasks}))
    filled = skipped = 0

    for t in tasks:
        images = bugs.get(int(t["bug_id"])) or []
        if not images:
            # the bug genuinely has no screenshot, or it was deleted
            skipped += 1
            continue
        if dry_run:
            logger.info("DRY task=%s bug=%s -> %d image(s)", t["id"], t["bug_id"], len(images))
            filled += 1
            continue
        try:
            db.client.table(_TASKS).update({"images": images}).eq("id", t["id"]).execute()
        except Exception as e:  # noqa: BLE001
            logger.warning("update failed task=%s err=%s", t["id"], type(e).__name__)
            skipped += 1
            continue
        logger.info("OK task=%s bug=%s -> %d image(s)", t["id"], t["bug_id"], len(images))
        filled += 1

    logger.info("done. filled=%d skipped=%d dry_run=%s", filled, skipped, dry_run)
    return filled, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=1000,
                        help="Max task rows to scan (default: 1000)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change, write nothing")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    run_backfill(limit=args.limit, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
