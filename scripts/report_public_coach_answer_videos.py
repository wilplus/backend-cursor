#!/usr/bin/env python3
"""List coach answer videos still stored at a PUBLIC journal link.

Since 2026-10-15 (founder, fix 5) a coach's answer video is stored privately
in the coach-media bucket under the speaker's id and re-signed on every read
(services/coach_answer_video.py). Videos saved before that sit in the public
journal bucket. A resolved answer's video cannot be rewritten in place (the
0446 guard keeps the request row and its history in step), so this script
only reports them: request id, Take and link, for the founder to decide
(re-upload through the coach panel, or delete the public object by hand).

Usage: ./venv/bin/python scripts/report_public_coach_answer_videos.py
Read-only.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    from services.db import db
    from services.journal_media import journal_public_base_url
    base = (journal_public_base_url() or "").rstrip("/")
    if not base:
        print("No public journal base configured: nothing can be public.")
        return 0
    found = 0
    for table in ("exercise_coach_requests", "exercise_coach_request_answer_versions"):
        id_column = "id" if table == "exercise_coach_requests" else "request_id"
        rows = (db.client.table(table)
                .select(f"{id_column},take_session_id,answer_video_ref")
                .like("answer_video_ref", f"{base}/%").execute().data) or []
        for row in rows:
            found += 1
            print(f"{table}\t{row.get(id_column)}\t{row.get('take_session_id')}\t"
                  f"{row.get('answer_video_ref')}")
    print(f"{found} public answer video link(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
