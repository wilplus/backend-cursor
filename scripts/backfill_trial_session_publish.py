#!/usr/bin/env python3
"""Backfill unpublished coaching-trial v2_sessions.

Before commit 901c618 (auto-publish for coaching trial sessions),
every "Try this again" recording created a v2_session that was
never published — ``results_published_at`` stayed NULL so the user
never got an email, the session never showed up on /results, and
the dashboard hid the snippets even though they existed.

This script picks those orphaned trial sessions up and runs them
through ``auto_publish_trial_session`` — the same code path new
trial recordings now use. Idempotent: sessions that have been
published already are skipped by the filter.

Usage::

    python3 scripts/backfill_trial_session_publish.py --dry-run
    python3 scripts/backfill_trial_session_publish.py --since 7
    python3 scripts/backfill_trial_session_publish.py --user-id <uuid>
    python3 scripts/backfill_trial_session_publish.py --session-id <uuid>
    python3 scripts/backfill_trial_session_publish.py  # publish everything
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.db import db  # noqa: E402
from services.session_publish import auto_publish_trial_session  # noqa: E402


def _select_candidates(
    *,
    user_id: str | None,
    session_id: str | None,
    since_days: int | None,
    limit: int,
) -> list[dict]:
    """Find v2_sessions that look like unpublished coaching trials.

    Filter rationale:
      - results_published_at IS NULL  →  hasn't been published yet
      - user_id IS NOT NULL           →  bound to a real user (so the
                                          email + dashboard have
                                          somewhere to land)
      - recording_origin = 'coaching_trial' on the linked recordings
        row  →  scoped to trial flow only, so this script can't
        accidentally publish an onboarding session the admin meant
        to review

    PostgREST doesn't join across tables natively, so we filter on
    v2_sessions first then post-filter Python-side by looking up
    each session's recording.
    """
    q = (
        db.client.table("v2_sessions")
        .select(
            "id, user_id, status, created_at, results_published_at, "
            "recording_1_id",
        )
        .is_("results_published_at", "null")
        .not_.is_("user_id", "null")
        .order("created_at", desc=False)
        .limit(max(1, int(limit)))
    )
    if user_id:
        q = q.eq("user_id", user_id)
    if session_id:
        q = q.eq("id", session_id)
    if since_days is not None:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=since_days)
        ).isoformat()
        q = q.gte("created_at", cutoff)

    rows = q.execute().data or []

    # Post-filter to trial recordings only. We could also accept
    # rows with no recording linked (rare orphan case) but skipping
    # them keeps this conservative.
    trial_rows: list[dict] = []
    for r in rows:
        rid = r.get("recording_1_id")
        if not rid:
            continue
        try:
            rec = (
                db.client.table("recordings")
                .select("id, recording_origin")
                .eq("id", rid)
                .limit(1)
                .execute()
                .data
            ) or []
        except Exception as e:
            print(f"  [warn] could not load recording {rid}: {e}")
            continue
        if not rec:
            continue
        origin = (rec[0].get("recording_origin") or "").lower()
        if origin == "coaching_trial":
            trial_rows.append(r)

    return trial_rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Publish coaching-trial v2_sessions whose "
            "results_published_at is NULL. Runs the same "
            "auto_publish_trial_session pipeline that new trial "
            "recordings hit."
        )
    )
    parser.add_argument("--user-id", type=str, default=None,
                        help="Scope to one user_id")
    parser.add_argument("--session-id", type=str, default=None,
                        help="Scope to one session_id")
    parser.add_argument("--since", type=int, default=None,
                        metavar="DAYS",
                        help="Only sessions created within the last "
                             "N days (default: no time bound)")
    parser.add_argument("--limit", type=int, default=200,
                        help="Max sessions to scan (default 200)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print actions without publishing")
    args = parser.parse_args()

    candidates = _select_candidates(
        user_id=args.user_id,
        session_id=args.session_id,
        since_days=args.since,
        limit=args.limit,
    )
    print(
        f"Found {len(candidates)} unpublished coaching-trial sessions"
    )
    if not candidates:
        return 0

    if args.dry_run:
        for r in candidates:
            print(
                f"  [dry-run] would publish "
                f"sid={r['id']} user={r['user_id']} "
                f"status={r.get('status')} created={r.get('created_at')}"
            )
        return 0

    n_ok = 0
    n_skipped = 0
    n_failed = 0
    for r in candidates:
        sid = r["id"]
        uid = r["user_id"]
        print(f"  → publishing sid={sid} user={uid}")
        try:
            res = auto_publish_trial_session(
                session_id=sid, user_id=str(uid),
            )
            if res.get("ok"):
                n_ok += 1
                print(
                    f"    ok: published={res.get('published')} "
                    f"snippets={res.get('snippet_count')} "
                    f"email={res.get('email_status')} "
                    f"admin_email={res.get('admin_email_status')} "
                    f"profile_recomputed={res.get('learner_profile_recomputed')}"
                )
            else:
                n_skipped += 1
                print(
                    f"    skipped: reason={res.get('skipped_reason')} "
                    f"step_failed={res.get('step_failed')}"
                )
        except Exception as e:
            n_failed += 1
            print(f"    failed: {e}")

    print(
        f"\nDone. published={n_ok} skipped={n_skipped} failed={n_failed}"
    )
    return 0 if n_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
