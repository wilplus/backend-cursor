#!/usr/bin/env python3
"""Preview or publish cold-open snapshots for existing Ideal Text documents.

Dry-run is the default.  ``--apply`` is deliberately explicit because a
snapshot publication is a product-state write.  The script never creates or
repairs an Ideal Text; it only materializes documents that already have an
owned, successfully processed spoken Take.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.db import db  # noqa: E402
from services.ideal_text_core_snapshot import publish_for_arc  # noqa: E402


def _arc_ids(limit: int | None) -> list[str]:
    out: list[str] = []
    offset = 0
    page_size = 500
    while limit is None or len(out) < limit:
        high = offset + page_size - 1
        rows = (
            db.client.table("coach_arc_ideal_text")
            .select("arc_id")
            .range(offset, high)
            .execute().data
            or []
        )
        if not rows:
            break
        for row in rows:
            arc_id = str(row.get("arc_id") or "")
            if arc_id and arc_id not in out:
                out.append(arc_id)
                if limit is not None and len(out) >= limit:
                    break
        if len(rows) < page_size:
            break
        offset += page_size
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")

    counts: dict[str, Any] = {
        "mode": "apply" if args.apply else "preview",
        "eligible": 0,
        "published": 0,
        "skipped_missing_lineage": 0,
        "failed": 0,
    }
    for arc_id in _arc_ids(args.limit):
        sessions = db.get_arc_sessions(arc_id) or []
        spoken = [
            row for row in sessions
            if row.get("recording_kind") != "read"
            and not row.get("paired_session_id")
            and row.get("analysis_state") in (None, "ready")
        ]
        latest = sorted(spoken, key=lambda row: row.get("take_index") or 0)[-1] \
            if spoken else {}
        if not latest.get("owner_principal_id") \
                or not latest.get("project_id") \
                or not (latest.get("user_id") or latest.get("owner_principal_id")):
            counts["skipped_missing_lineage"] += 1
            continue
        counts["eligible"] += 1
        if not args.apply:
            continue
        result = publish_for_arc(db, arc_id)
        if result:
            counts["published"] += 1
        else:
            counts["failed"] += 1

    print(json.dumps(counts, sort_keys=True))
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

