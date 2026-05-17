#!/usr/bin/env python3
"""Phase A1.1 — backfill cron for the few-shot annotation pool.

Pitfall #10 in the spec: ``record_snippet_publish_annotations()``
fires ONLY at publish time. Sessions where the admin typed
admin_comment / follow_up_question / etc. but never clicked Publish
have edits that never reach ``admin_annotation_events`` — they're
invisible to the few-shot retrieval pool and to future fine-tune
exports.

This script is the recovery: it finds those sessions and runs them
through the EXACT SAME diff/chip logic ``record_snippet_publish_
annotations()`` would have, so the few-shot pool can grow against
the work admins already did.

Safe to auto-run on a cron:
  * read-only on production tables (only writes to
    ``admin_annotation_events``, which is append-only audit data)
  * idempotent at session level (skips sessions that already have
    publish-path rows captured)
  * promotes nothing, trains nothing, never touches
    ``results_published_at`` or ``status`` — the session stays
    unpublished from the user's perspective

Usage:
    python3 scripts/backfill_few_shot_annotations.py --dry-run
    python3 scripts/backfill_few_shot_annotations.py --since-days 30
    python3 scripts/backfill_few_shot_annotations.py --session-id <uuid>
    python3 scripts/backfill_few_shot_annotations.py --limit 50

What it logs per run:
  sessions_scanned, sessions_skipped_already_captured,
  sessions_processed, events_written_total
A no-op run (no candidates) exits 0 with all-zero counts — does
not error.

What this script does NOT do (intentionally, per spec):
  * Does not loosen the fact-check / eligibility gate (Phase 5
    in services/coaching_outcomes.py). A permissive gate is the
    "biased labels" failure mode — don't widen the pool by
    weakening quality control.
  * Does not flip the session's results_published_at — the cron
    captures admin intent for training; user-visible publish
    state is a separate decision (admin still has to click).
  * Does not train, promote, or write to runtime_config.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.db import db  # noqa: E402


logger = logging.getLogger("backfill_few_shot_annotations")

# The publish-time writer fires for these field_names. We use them
# both to (a) probe whether a session is already captured and (b)
# document scope.
_PUBLISH_PATH_FIELDS = (
    "admin_comment",
    "follow_up_question",
    "evaluator_rationale",
    "coach_label_notes",
)


def _select_candidate_sessions(
    *,
    since_days: int | None,
    session_id: str | None,
    limit: int,
) -> list[dict]:
    """Find unpublished sessions where at least one snippet has a
    non-empty admin_comment set. These are the pitfall-#10 targets.

    Filter rationale:
      - results_published_at IS NULL  →  never went through publish,
                                          so publish-time annotation
                                          capture never ran
      - has at least one snippet with admin_comment set  →  admin
                                          actually did review work
                                          worth capturing
    """
    try:
        q = (
            db.client.table("v2_sessions")
            .select("id, user_id, created_at, results_published_at")
            .is_("results_published_at", "null")
            .order("created_at", desc=True)
            .limit(max(1, int(limit)))
        )
        if session_id:
            q = q.eq("id", session_id)
        if since_days is not None:
            cutoff = (
                datetime.now(timezone.utc) - timedelta(days=since_days)
            ).isoformat()
            q = q.gte("created_at", cutoff)
        sessions = q.execute().data or []
    except Exception as e:
        logger.warning("session query failed: %s", e)
        return []

    if not sessions:
        return []

    # Post-filter to "has at least one snippet with admin_comment".
    # PostgREST can't do EXISTS subqueries cleanly, so we batch.
    session_ids = [s["id"] for s in sessions]
    chunk_size = 200
    sessions_with_admin_work: set[str] = set()
    for i in range(0, len(session_ids), chunk_size):
        chunk = session_ids[i : i + chunk_size]
        try:
            snip_rows = (
                db.client.table("charisma_snippets")
                .select("session_id, admin_comment")
                .in_("session_id", chunk)
                .not_.is_("admin_comment", "null")
                .execute()
                .data
            ) or []
        except Exception as e:
            logger.warning("snippet probe failed for chunk: %s", e)
            continue
        for r in snip_rows:
            sid = r.get("session_id")
            if sid and (r.get("admin_comment") or "").strip():
                sessions_with_admin_work.add(sid)

    return [s for s in sessions if s["id"] in sessions_with_admin_work]


def _is_already_captured(session_id: str) -> bool:
    """Idempotency probe — true if admin_annotation_events already
    has any row for this session with a publish-path field_name.

    Coarse-grained at session level (per spec: a session already
    represented is skipped). Per-snippet partial-capture recovery
    isn't a v1 goal — once the session_id appears in the table for
    ANY publish-path field, we stop touching it. If admin later
    edits + re-publishes, the publish-time writer fires fresh
    rows; this cron stays out of the way.
    """
    try:
        existing = (
            db.client.table("admin_annotation_events")
            .select("id")
            .eq("session_id", session_id)
            .in_("field_name", list(_PUBLISH_PATH_FIELDS))
            .limit(1)
            .execute()
            .data
        ) or []
    except Exception as e:
        logger.warning(
            "idempotency probe failed for sid=%s err=%s — skipping "
            "to stay safe", session_id, e,
        )
        # Treat probe failure as "already captured" — never double-
        # write on uncertainty. The next run will try again with a
        # clean DB connection.
        return True
    return len(existing) > 0


def _resolve_admin_user_id(session: dict) -> str | None:
    """Find a plausible admin user_id to attribute the backfilled
    events to.

    Priority:
      1. SYSTEM_BACKFILL_USER_ID env var (a designated admin/system
         user whose attribution makes the audit log readable)
      2. The session's owner user_id as a last resort — not quite
         right (the user isn't an admin) but produces a non-NULL
         created_by so the row inserts

    If both miss, return None — caller skips the session. We never
    invent a UUID.
    """
    sys_id = (os.getenv("SYSTEM_BACKFILL_USER_ID") or "").strip()
    if sys_id:
        return sys_id
    return session.get("user_id")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Phase A1.1 backfill — recover annotation events from "
            "unpublished-but-reviewed sessions by replaying the "
            "publish-time diff/chip logic."
        )
    )
    parser.add_argument("--session-id", type=str, default=None,
                        help="Scope to one session UUID (for testing)")
    parser.add_argument("--since-days", type=int, default=None,
                        metavar="N",
                        help="Only sessions created in the last N days")
    parser.add_argument("--limit", type=int, default=200,
                        help="Max sessions to scan per run (default 200)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Resolve targets + print plan; no writes")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Per-session log lines (default summary only)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    candidates = _select_candidate_sessions(
        since_days=args.since_days,
        session_id=args.session_id,
        limit=args.limit,
    )
    logger.info(
        "scanned %d unpublished sessions with admin review activity",
        len(candidates),
    )

    if not candidates:
        logger.info(
            "no candidate sessions — pitfall-#10 starvation set is "
            "empty. Nothing to backfill."
        )
        return 0

    if args.dry_run:
        for s in candidates:
            already = _is_already_captured(s["id"])
            logger.info(
                "[dry-run] sid=%s user=%s created=%s "
                "already_captured=%s",
                s["id"], s.get("user_id"), s.get("created_at"),
                already,
            )
        return 0

    n_skipped = 0
    n_processed = 0
    n_events_total = 0
    n_no_admin = 0

    for s in candidates:
        sid = s["id"]
        if _is_already_captured(sid):
            n_skipped += 1
            if args.verbose:
                logger.debug(
                    "skip sid=%s — already represented in "
                    "admin_annotation_events", sid,
                )
            continue

        admin_user_id = _resolve_admin_user_id(s)
        if not admin_user_id:
            n_no_admin += 1
            logger.warning(
                "skip sid=%s — could not resolve admin_user_id "
                "(no SYSTEM_BACKFILL_USER_ID env, no session.user_id)",
                sid,
            )
            continue

        try:
            events_written = db.record_snippet_publish_annotations(
                session_id=sid,
                admin_user_id=str(admin_user_id),
            )
        except Exception as e:
            logger.warning(
                "backfill failed sid=%s err=%s — leaving for next run",
                sid, e,
            )
            continue

        n_processed += 1
        n_events_total += events_written
        logger.info(
            "backfilled sid=%s events_written=%d",
            sid, events_written,
        )

    logger.info(
        "DONE  sessions_scanned=%d  "
        "sessions_skipped_already_captured=%d  "
        "sessions_skipped_no_admin=%d  "
        "sessions_processed=%d  "
        "events_written_total=%d",
        len(candidates), n_skipped, n_no_admin, n_processed,
        n_events_total,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
