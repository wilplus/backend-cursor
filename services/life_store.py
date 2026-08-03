"""The Life Panel — Supabase I/O (founder-directed, 2026-07-26).

Every read and write of a ``life_*`` table goes through here. Nothing else in
the repo touches those tables.

Why this module exists instead of methods on services/db.DatabaseService
────────────────────────────────────────────────────────────────────────
N2 says no product-side module may import the life module. If the life queries
lived in services/db.py — which every F1 path imports — then the shared
database service would carry life code, and the fence would be a comment
rather than a property of the import graph. Keeping them here makes the
direction one-way and checkable: life → db is fine, db → life never happens,
and the isolation test asserts it.

The house precedent is services/dev_tasks.py and services/dev_bugs.py, which
own their table through ``db.client`` for the same reason.

Degradation contract
────────────────────
Every read degrades to empty and every write returns None when the table is
absent or Supabase is unreachable, so deploying the code before running
migrations/add_life_panel.sql cannot 500 anything. The one exception is the
hard delete (BE-10): a delete that half-fails must SAY so, because "your data
is gone" is a promise, and a silent partial delete breaks it.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from services.db import db
from services import life_panel as lp

logger = logging.getLogger(__name__)

# Every table the feature owns. The export and the hard delete iterate this
# list, so a table added later is covered by both the moment it is listed here
# — the failure mode being designed out is a new table that quietly escapes
# "get it all out" and "wipe it all".
LIFE_TABLES: tuple[str, ...] = (
    "life_consent", "life_setup", "life_notes", "life_cases", "life_items",
    "life_strategy", "life_proposals", "life_applications", "life_days",
    "life_weeks", "life_period_reviews",
)

# Deleted in this order so a partial failure never strands a child row whose
# parent is gone: leaves first, then the roots, consent last (it is the record
# that the rest was ever allowed to exist).
_DELETE_ORDER: tuple[str, ...] = (
    "life_applications", "life_proposals", "life_items", "life_cases",
    "life_days", "life_weeks", "life_period_reviews", "life_strategy",
    "life_notes", "life_setup", "life_consent",
)


def _rows(result: Any) -> list[dict]:
    data = getattr(result, "data", None)
    return list(data) if isinstance(data, list) else []


def _one(result: Any) -> Optional[dict]:
    rows = _rows(result)
    return rows[0] if rows else None


def _t(table: str):
    return db.client.table(table)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═════════════════════════════════════════════════════════════════════════
# Consent (L-6) — the precondition for every other write
# ═════════════════════════════════════════════════════════════════════════

def get_consent(user_id: str, *, version: str) -> Optional[dict]:
    """The user's acceptance of THIS consent version, or None.

    Versioned rather than boolean on purpose: when the consent copy changes
    materially, everyone is asked again before another life row is written.
    An older acceptance stays in the table as history — it is the record that
    they agreed to the previous terms, which is exactly what an acceptance log
    is for."""
    try:
        return _one(
            _t("life_consent").select("*")
            .eq("user_id", user_id).eq("consent_version", version)
            .limit(1).execute()
        )
    except Exception as e:
        logger.warning("life: get_consent failed user=%s: %s", user_id, e)
        return None


def record_consent(user_id: str, *, version: str,
                   ip: Optional[str] = None) -> Optional[dict]:
    """Record acceptance. Idempotent — re-accepting the same version returns
    the existing row rather than stacking duplicates."""
    existing = get_consent(user_id, version=version)
    if existing:
        return existing
    try:
        return _one(_t("life_consent").insert({
            "user_id": user_id,
            "consent_version": version,
            "accepted_at": _now(),
            "ip": (ip or None),
        }).execute())
    except Exception as e:
        logger.error("life: record_consent failed user=%s: %s", user_id, e)
        return None


# ═════════════════════════════════════════════════════════════════════════
# Setup (§6.2) — save-and-resume, then a hard gate
# ═════════════════════════════════════════════════════════════════════════

def get_setup(user_id: str) -> Optional[dict]:
    try:
        return _one(
            _t("life_setup").select("*").eq("user_id", user_id)
            .limit(1).execute()
        )
    except Exception as e:
        logger.warning("life: get_setup failed user=%s: %s", user_id, e)
        return None


def upsert_setup(user_id: str, answers: dict) -> Optional[dict]:
    """Save partial answers. Eight horizons is long enough that people get
    interrupted partway; without this an interruption is an abandonment, and
    the gate has no second door."""
    payload = {
        "user_id": user_id,
        "answers": answers or {},
        "updated_at": _now(),
    }
    try:
        return _one(
            _t("life_setup").upsert(payload, on_conflict="user_id").execute()
        )
    except Exception as e:
        logger.error("life: upsert_setup failed user=%s: %s", user_id, e)
        return None


def complete_setup(user_id: str) -> Optional[dict]:
    try:
        return _one(
            _t("life_setup")
            .update({"completed_at": _now(), "updated_at": _now()})
            .eq("user_id", user_id).execute()
        )
    except Exception as e:
        logger.error("life: complete_setup failed user=%s: %s", user_id, e)
        return None


def setup_completed(user_id: str) -> bool:
    return bool((get_setup(user_id) or {}).get("completed_at"))


# ═════════════════════════════════════════════════════════════════════════
# Notes — append-only capture. Never edited, never deleted.
# ═════════════════════════════════════════════════════════════════════════

def list_reflection_notes(user_id: str, *, limit: int = 200,
                          since: Optional[str] = None,
                          until: Optional[str] = None) -> list[dict]:
    """The reality layer: every note tagged into the reflection route,
    newest first. Fetched raw and capped; relevance ranking happens in the
    engine, in-process, exactly as it does for principles.

    ``since``/``until`` (ISO date, inclusive/exclusive) window the fetch for
    the period reviews, which re-read a month or a quarter chronologically
    rather than by relevance. Omitted, the behaviour is exactly what the
    strategy comparison has always read."""
    try:
        q = (_t("life_notes").select("*")
             .eq("user_id", user_id)
             .in_("tag", list(lp.REFLECTION_TAGS)))
        if since:
            q = q.gte("created_at", since)
        if until:
            q = q.lt("created_at", until)
        return _rows(
            q.order("created_at", desc=True)
            .limit(max(1, min(limit, 500))).execute()
        )
    except Exception as e:
        logger.warning("life: list_reflection_notes failed user=%s: %s",
                       user_id, e)
        return []


def insert_note(user_id: str, body: str, *, source: str = "chat",
                tag: Optional[str] = None,
                pending_replay: bool = False) -> Optional[dict]:
    """Capture never fails and never blocks — that is the contract the whole
    router rests on. A note lands here regardless of tag, regardless of setup
    state, before any derivation is attempted."""
    try:
        return _one(_t("life_notes").insert({
            "user_id": user_id,
            "body": body or "",
            "source": source if source in lp.NOTE_SOURCES else "chat",
            "tag": tag,
            "pending_replay": bool(pending_replay),
        }).execute())
    except Exception as e:
        logger.error("life: insert_note failed user=%s: %s", user_id, e)
        return None


def list_notes(user_id: str, *, limit: int = 100, offset: int = 0,
               untagged_only: bool = False) -> list[dict]:
    try:
        q = (_t("life_notes").select("*").eq("user_id", user_id)
             .order("created_at", desc=True)
             .range(offset, offset + max(1, limit) - 1))
        if untagged_only:
            q = q.is_("tag", "null")
        return _rows(q.execute())
    except Exception as e:
        logger.warning("life: list_notes failed user=%s: %s", user_id, e)
        return []


def pending_replay_notes(user_id: str, *, limit: int = 50) -> list[dict]:
    """Notes typed before setup completed, OLDEST FIRST.

    §6.2: someone who reaches for `#mistake` is holding a thought they wanted
    recorded. Losing it to a redirect teaches them the tag costs something."""
    try:
        return _rows(
            _t("life_notes").select("*").eq("user_id", user_id)
            .eq("pending_replay", True)
            .order("created_at", desc=False).limit(limit).execute()
        )
    except Exception as e:
        logger.warning("life: pending_replay_notes failed user=%s: %s",
                       user_id, e)
        return []


def mark_replayed(user_id: str, note_ids: list[str]) -> int:
    """Clear the pending-replay flag after the engine has run those notes.

    Scoped to the owner as well as the ids. The ids always come from this
    user's own ``pending_replay_notes`` today, so the owner filter is
    redundant on the current call path — which is exactly why it has to be
    here: an id list from anywhere else would otherwise write across users,
    and the next caller will not remember that this one was safe."""
    if not note_ids:
        return 0
    try:
        res = (_t("life_notes")
               .update({"pending_replay": False, "replayed_at": _now()})
               .eq("user_id", user_id).in_("id", note_ids).execute())
        return len(_rows(res))
    except Exception as e:
        logger.warning("life: mark_replayed failed user=%s: %s", user_id, e)
        return 0


# ═════════════════════════════════════════════════════════════════════════
# Cases
# ═════════════════════════════════════════════════════════════════════════

def insert_case(user_id: str, fields: dict) -> Optional[dict]:
    payload = {"user_id": user_id, **(fields or {})}
    try:
        return _one(_t("life_cases").insert(payload).execute())
    except Exception as e:
        logger.error("life: insert_case failed user=%s: %s", user_id, e)
        return None


def update_case(user_id: str, case_id: str, fields: dict) -> Optional[dict]:
    if not fields:
        return get_case(user_id, case_id)
    try:
        return _one(
            _t("life_cases").update({**fields, "updated_at": _now()})
            .eq("id", case_id).eq("user_id", user_id).execute()
        )
    except Exception as e:
        logger.error("life: update_case failed id=%s: %s", case_id, e)
        return None


def get_case(user_id: str, case_id: str) -> Optional[dict]:
    try:
        return _one(
            _t("life_cases").select("*")
            .eq("id", case_id).eq("user_id", user_id).limit(1).execute()
        )
    except Exception as e:
        logger.warning("life: get_case failed id=%s: %s", case_id, e)
        return None


def list_cases(user_id: str, *, limit: int = 100, offset: int = 0,
               needs_review: bool = False) -> list[dict]:
    try:
        q = (_t("life_cases").select("*").eq("user_id", user_id)
             .order("created_at", desc=True)
             .range(offset, offset + max(1, limit) - 1))
        if needs_review:
            q = q.not_.is_("import_category_raw", "null")
        return _rows(q.execute())
    except Exception as e:
        logger.warning("life: list_cases failed user=%s: %s", user_id, e)
        return []


# ═════════════════════════════════════════════════════════════════════════
# Items
# ═════════════════════════════════════════════════════════════════════════

def insert_item(user_id: str, fields: dict) -> Optional[dict]:
    payload = {"user_id": user_id, **(fields or {})}
    try:
        return _one(_t("life_items").insert(payload).execute())
    except Exception as e:
        logger.error("life: insert_item failed user=%s: %s", user_id, e)
        return None


def update_item(user_id: str, item_id: str, fields: dict) -> Optional[dict]:
    if not fields:
        return get_item(user_id, item_id)
    try:
        return _one(
            _t("life_items").update({**fields, "updated_at": _now()})
            .eq("id", item_id).eq("user_id", user_id).execute()
        )
    except Exception as e:
        logger.error("life: update_item failed id=%s: %s", item_id, e)
        return None


def get_item(user_id: str, item_id: str) -> Optional[dict]:
    try:
        return _one(
            _t("life_items").select("*")
            .eq("id", item_id).eq("user_id", user_id).limit(1).execute()
        )
    except Exception as e:
        logger.warning("life: get_item failed id=%s: %s", item_id, e)
        return None


def delete_item(user_id: str, item_id: str) -> bool:
    try:
        res = (_t("life_items").delete()
               .eq("id", item_id).eq("user_id", user_id).execute())
        return bool(_rows(res))
    except Exception as e:
        logger.error("life: delete_item failed id=%s: %s", item_id, e)
        return False


def list_items(user_id: str, *, kind: Optional[str] = None,
               status: Optional[str] = None,
               collection: Optional[str] = None,
               limit: int = 500, offset: int = 0) -> list[dict]:
    try:
        q = (_t("life_items").select("*").eq("user_id", user_id)
             .order("order_key", desc=False)
             .range(offset, offset + max(1, limit) - 1))
        if kind:
            q = q.eq("kind", kind)
        if status:
            q = q.eq("status", status)
        if collection:
            q = q.eq("collection", collection)
        return _rows(q.execute())
    except Exception as e:
        logger.warning("life: list_items failed user=%s kind=%s: %s",
                       user_id, kind, e)
        return []


def principles(user_id: str, *, limit: int = 500) -> list[dict]:
    """Active principles only. A `proposed` principle has not been approved
    and must never be retrieved as if it were part of the archive — that is
    propose-never-commit, applied on the READ side too."""
    return list_items(user_id, kind="principle", status="active", limit=limit)


def items_for_case(user_id: str, case_id: str) -> list[dict]:
    try:
        return _rows(
            _t("life_items").select("*")
            .eq("user_id", user_id).eq("origin_case_id", case_id)
            .order("order_key", desc=False).execute()
        )
    except Exception as e:
        logger.warning("life: items_for_case failed case=%s: %s", case_id, e)
        return []


# ═════════════════════════════════════════════════════════════════════════
# Strategy — versioned, never overwritten
# ═════════════════════════════════════════════════════════════════════════

def latest_strategy(user_id: str) -> dict[str, dict]:
    """``{horizon: row}`` at each horizon's current version.

    Reads every version and folds in Python rather than issuing eight
    "max(version)" queries: the whole set is a handful of rows for one user,
    and one round trip beats eight."""
    try:
        rows = _rows(
            _t("life_strategy").select("*").eq("user_id", user_id)
            .order("version", desc=False).execute()
        )
    except Exception as e:
        logger.warning("life: latest_strategy failed user=%s: %s", user_id, e)
        return {}
    out: dict[str, dict] = {}
    for row in rows:
        horizon = row.get("horizon") or "weekly"
        prev = out.get(horizon)
        if prev is None or int(row.get("version") or 1) >= int(prev.get("version") or 1):
            out[horizon] = row
    return out


def insert_strategy_version(user_id: str, *, horizon: str, body: str,
                            reviewed_on: Optional[str] = None) -> Optional[dict]:
    """Append a new version. The prior one stays readable forever — that is
    what makes "every change is gated" auditable eight months and forty
    approvals later."""
    current = latest_strategy(user_id).get(horizon)
    version = int((current or {}).get("version") or 0) + 1
    try:
        return _one(_t("life_strategy").insert({
            "user_id": user_id,
            "horizon": horizon,
            "body": body or "",
            "version": version,
            "reviewed_on": reviewed_on,
        }).execute())
    except Exception as e:
        logger.error("life: insert_strategy_version failed user=%s h=%s: %s",
                     user_id, horizon, e)
        return None


def strategy_versions(user_id: str, *, horizon: str) -> list[dict]:
    try:
        return _rows(
            _t("life_strategy").select("*")
            .eq("user_id", user_id).eq("horizon", horizon)
            .order("version", desc=True).execute()
        )
    except Exception as e:
        logger.warning("life: strategy_versions failed: %s", e)
        return []


# ═════════════════════════════════════════════════════════════════════════
# Proposals — the L-2b budget lives in these queries
# ═════════════════════════════════════════════════════════════════════════

def count_surfaced_today(user_id: str, *, kind: str = "strategy",
                         today: Optional[date] = None) -> int:
    """How many proposals of this kind already surfaced today.

    THIS is the budget. It is a query, not a counter: a process-local counter
    drifts across gunicorn workers and resets on restart, so the budget would
    silently become "one per worker per day" — which on a four-worker dyno is
    four, and the rubber stamp is back."""
    day = (today or datetime.now(timezone.utc).date()).isoformat()
    try:
        res = (_t("life_proposals")
               .select("id", count="exact")
               .eq("user_id", user_id).eq("kind", kind)
               .eq("surfaced_on", day).execute())
        count = getattr(res, "count", None)
        return int(count) if count is not None else len(_rows(res))
    except Exception as e:
        logger.warning("life: count_surfaced_today failed user=%s: %s",
                       user_id, e)
        # Fail CLOSED: an unknown budget state queues the proposal rather than
        # surfacing it. A queued proposal reaches the founder at the weekly
        # review; an over-surfaced one erodes the approve button.
        return lp.DAILY_PROPOSAL_BUDGET


def insert_proposal(user_id: str, fields: dict) -> Optional[dict]:
    payload = {"user_id": user_id, **(fields or {})}
    try:
        return _one(_t("life_proposals").insert(payload).execute())
    except Exception as e:
        logger.error("life: insert_proposal failed user=%s: %s", user_id, e)
        return None


def get_proposal(user_id: str, proposal_id: str) -> Optional[dict]:
    try:
        return _one(
            _t("life_proposals").select("*")
            .eq("id", proposal_id).eq("user_id", user_id).limit(1).execute()
        )
    except Exception as e:
        logger.warning("life: get_proposal failed id=%s: %s", proposal_id, e)
        return None


def update_proposal(user_id: str, proposal_id: str,
                    fields: dict) -> Optional[dict]:
    try:
        return _one(
            _t("life_proposals").update(fields)
            .eq("id", proposal_id).eq("user_id", user_id).execute()
        )
    except Exception as e:
        logger.error("life: update_proposal failed id=%s: %s", proposal_id, e)
        return None


def list_proposals(user_id: str, *, status: Optional[str] = None,
                   kind: Optional[str] = None,
                   limit: int = 100) -> list[dict]:
    try:
        q = (_t("life_proposals").select("*").eq("user_id", user_id)
             .order("rank", desc=True).limit(limit))
        if status:
            q = q.eq("status", status)
        if kind:
            q = q.eq("kind", kind)
        return _rows(q.execute())
    except Exception as e:
        logger.warning("life: list_proposals failed user=%s: %s", user_id, e)
        return []


def expire_stale_proposals(user_id: str) -> int:
    """Queued proposals older than two weeks → expired.

    Ageing them out is the point: an unbounded queue turns the weekly review
    into an inbox, and an inbox is skimmed."""
    cutoff = (datetime.now(timezone.utc)).isoformat()
    try:
        res = (_t("life_proposals")
               .update({"status": "expired", "decided_at": cutoff})
               .eq("user_id", user_id).eq("status", "queued")
               .lt("expires_at", cutoff).execute())
        return len(_rows(res))
    except Exception as e:
        logger.warning("life: expire_stale_proposals failed user=%s: %s",
                       user_id, e)
        return 0


def retire_decision(user_id: str, *, old_principle_id: str,
                    new_principle_id: str) -> Optional[dict]:
    """A previously answered "does this retire #12?" pair, or None.

    A `dismissed` row here is the founder's "no" and it is ABSOLUTE: the
    question is never re-asked. Re-asking a settled veto is how a system
    wears someone down into an answer they already declined to give."""
    try:
        rows = _rows(
            _t("life_proposals").select("*")
            .eq("user_id", user_id).eq("kind", "retire")
            .eq("target", str(old_principle_id))
            .eq("proposed", str(new_principle_id)).limit(1).execute()
        )
        return rows[0] if rows else None
    except Exception as e:
        logger.warning("life: retire_decision failed: %s", e)
        return None


# ═════════════════════════════════════════════════════════════════════════
# Applications (L-5) — append-only
# ═════════════════════════════════════════════════════════════════════════

def insert_applications(user_id: str, rows: list[dict]) -> int:
    """Best-effort: a lost log line must never fail the answer the founder
    asked for. The log is evidence over months, not a transactional record.

    ``user_id`` is re-stamped onto every row rather than trusted from the
    caller's dicts. ``lp.application_rows_for`` already sets it correctly, so
    this is redundant today — and that is the point: an INSERT is the one
    place where scoping lives in the payload instead of a filter, so it is the
    one place a wrong owner would be written silently rather than rejected."""
    if not rows:
        return 0
    owned = [{**row, "user_id": user_id} for row in rows]
    try:
        return len(_rows(_t("life_applications").insert(owned).execute()))
    except Exception as e:
        logger.warning("life: insert_applications failed user=%s: %s",
                       user_id, e)
        return 0


def application_counts(user_id: str) -> dict[str, int]:
    """``{principle_id: times cited}`` — L-5's whole payoff."""
    try:
        rows = _rows(
            _t("life_applications").select("principle_id")
            .eq("user_id", user_id).limit(10000).execute()
        )
    except Exception as e:
        logger.warning("life: application_counts failed user=%s: %s",
                       user_id, e)
        return {}
    counts: dict[str, int] = {}
    for row in rows:
        pid = str(row.get("principle_id") or "")
        if pid:
            counts[pid] = counts.get(pid, 0) + 1
    return counts


def applications_for(user_id: str, principle_id: str,
                     *, limit: int = 200) -> list[dict]:
    try:
        return _rows(
            _t("life_applications").select("*")
            .eq("user_id", user_id).eq("principle_id", principle_id)
            .order("created_at", desc=True).limit(limit).execute()
        )
    except Exception as e:
        logger.warning("life: applications_for failed: %s", e)
        return []


def recently_attached_phrase_ids(
    user_id: str, *, window_days: int = lp.PHRASE_REPEAT_WINDOW_DAYS,
) -> list[str]:
    """Phrase ids attached inside the rolling window — the no-repeat rule.

    Without it the wall collapses to three favourites: the highest-scoring
    phrase for a recurring theme wins every time, and a wall that says the
    same three things stops being read."""
    since = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
    try:
        rows = _rows(
            _t("life_applications").select("principle_id")
            .eq("user_id", user_id).eq("context", "phrase")
            .gte("created_at", since).limit(500).execute()
        )
    except Exception as e:
        logger.warning("life: recently_attached_phrase_ids failed: %s", e)
        return []
    return [str(r.get("principle_id")) for r in rows if r.get("principle_id")]


# ═════════════════════════════════════════════════════════════════════════
# Days + weeks
# ═════════════════════════════════════════════════════════════════════════

def get_day(user_id: str, day: str) -> Optional[dict]:
    try:
        return _one(
            _t("life_days").select("*")
            .eq("user_id", user_id).eq("day", day).limit(1).execute()
        )
    except Exception as e:
        logger.warning("life: get_day failed user=%s day=%s: %s",
                       user_id, day, e)
        return None


def list_recent_days(user_id: str, *, limit: int = 20) -> list[dict]:
    """Newest card days first. One fetch, two DISJOINT consumers: the drafting
    memory reads the (drafted → accepted) pairs, the Sunday-review gate reads
    the displacement — and per the learning contract they never read each
    other's field. Sharing the query is fine; sharing the data is the breach."""
    try:
        return _rows(
            _t("life_days").select("day, draft_meta")
            .eq("user_id", user_id).order("day", desc=True)
            .limit(max(1, min(limit, 60))).execute()
        )
    except Exception as e:
        logger.warning("life: list_recent_days failed user=%s: %s",
                       user_id, e)
        return []


def day_by_id(user_id: str, day_id: str) -> Optional[dict]:
    """One day row, owner-scoped. The PATCH reads it before writing, because
    draft_meta is a MERGE (accepted text, a displacement) into what the
    morning wrote — a blind overwrite would discard the drafts."""
    try:
        return _one(
            _t("life_days").select("*")
            .eq("id", day_id).eq("user_id", user_id).limit(1).execute()
        )
    except Exception as e:
        logger.warning("life: day_by_id failed id=%s: %s", day_id, e)
        return None


def latest_day(user_id: str) -> Optional[dict]:
    """The most recent card — the ONLY row `#edit` may target (BE-8)."""
    try:
        return _one(
            _t("life_days").select("*").eq("user_id", user_id)
            .order("day", desc=True).limit(1).execute()
        )
    except Exception as e:
        logger.warning("life: latest_day failed user=%s: %s", user_id, e)
        return None


def upsert_day(user_id: str, day: str, fields: dict) -> Optional[dict]:
    payload = {"user_id": user_id, "day": day, **(fields or {}),
               "updated_at": _now()}
    try:
        return _one(
            _t("life_days").upsert(payload, on_conflict="user_id,day").execute()
        )
    except Exception as e:
        logger.error("life: upsert_day failed user=%s day=%s: %s",
                     user_id, day, e)
        return None


def update_day(user_id: str, day_id: str, fields: dict) -> Optional[dict]:
    try:
        return _one(
            _t("life_days").update({**fields, "updated_at": _now()})
            .eq("id", day_id).eq("user_id", user_id).execute()
        )
    except Exception as e:
        logger.error("life: update_day failed id=%s: %s", day_id, e)
        return None


def get_week(user_id: str, week_start: str) -> Optional[dict]:
    try:
        return _one(
            _t("life_weeks").select("*")
            .eq("user_id", user_id).eq("week_start", week_start)
            .limit(1).execute()
        )
    except Exception as e:
        logger.warning("life: get_week failed user=%s: %s", user_id, e)
        return None


def upsert_week(user_id: str, week_start: str,
                fields: dict) -> Optional[dict]:
    payload = {"user_id": user_id, "week_start": week_start, **(fields or {}),
               "updated_at": _now()}
    try:
        return _one(
            _t("life_weeks")
            .upsert(payload, on_conflict="user_id,week_start").execute()
        )
    except Exception as e:
        logger.error("life: upsert_week failed user=%s: %s", user_id, e)
        return None


def list_weeks_between(user_id: str, since: str, until: str) -> list[dict]:
    """The month's week rows, oldest first — a month is made of its weeks.

    A week belongs to the period its ``week_start`` falls in: the straddle
    week at a month boundary was reviewed on the earlier month's Sunday, so
    it reads with that month."""
    try:
        return _rows(
            _t("life_weeks").select("*").eq("user_id", user_id)
            .gte("week_start", since).lt("week_start", until)
            .order("week_start", desc=False).execute()
        )
    except Exception as e:
        logger.warning("life: list_weeks_between failed user=%s: %s",
                       user_id, e)
        return []


# ═════════════════════════════════════════════════════════════════════════
# Period reviews — month + quarter (piece 5)
# ═════════════════════════════════════════════════════════════════════════
# Every read degrades to None/[] and the write returns None when the table is
# absent — deploying before migrations/add_life_period_reviews.sql runs costs
# the saved review, never the GET and never any other surface.

def get_period_review(user_id: str, period: str,
                      period_start: str) -> Optional[dict]:
    try:
        return _one(
            _t("life_period_reviews").select("*")
            .eq("user_id", user_id).eq("period", period)
            .eq("period_start", period_start)
            .limit(1).execute()
        )
    except Exception as e:
        logger.warning("life: get_period_review failed user=%s: %s",
                       user_id, e)
        return None


def upsert_period_review(user_id: str, period: str, period_start: str,
                         fields: dict) -> Optional[dict]:
    payload = {"user_id": user_id, "period": period,
               "period_start": period_start, **(fields or {}),
               "updated_at": _now()}
    try:
        return _one(
            _t("life_period_reviews")
            .upsert(payload, on_conflict="user_id,period,period_start")
            .execute()
        )
    except Exception as e:
        logger.error("life: upsert_period_review failed user=%s: %s — if the "
                     "table is missing, run "
                     "migrations/add_life_period_reviews.sql", user_id, e)
        return None


def list_period_reviews_between(user_id: str, period: str, since: str,
                                until: str) -> list[dict]:
    """The saved reviews of one cadence inside a window, oldest first — the
    quarter reads its months the way the month reads its weeks."""
    try:
        return _rows(
            _t("life_period_reviews").select("*")
            .eq("user_id", user_id).eq("period", period)
            .gte("period_start", since).lt("period_start", until)
            .order("period_start", desc=False).execute()
        )
    except Exception as e:
        logger.warning("life: list_period_reviews_between failed user=%s: %s",
                       user_id, e)
        return []


# ═════════════════════════════════════════════════════════════════════════
# BE-10 — export everything, delete everything
# ═════════════════════════════════════════════════════════════════════════

def export_all(user_id: str) -> dict:
    """Every row the user owns, table by table, raw.

    Deliberately RAW rather than serialized: an export exists so the founder
    can leave, and a shape tuned for this FE is a shape only this FE can read.
    Iterating LIFE_TABLES means a table added later is exported the moment it
    is listed there."""
    out: dict[str, Any] = {
        "exported_at": _now(),
        "user_id": user_id,
        "tables": {},
    }
    for table in LIFE_TABLES:
        try:
            rows = _rows(
                _t(table).select("*").eq("user_id", user_id)
                .limit(100000).execute()
            )
        except Exception as e:
            logger.warning("life: export %s failed user=%s: %s",
                           table, user_id, e)
            # An unreadable table is reported, never silently omitted — an
            # export missing a table looks exactly like an empty table.
            out.setdefault("errors", []).append(table)
            rows = []
        out["tables"][table] = rows
    return out


def hard_delete(user_id: str) -> dict:
    """Irreversible delete of everything this user owns.

    Returns ``{"deleted": {table: n}, "failed": [table...]}``. Unlike every
    other write here this does NOT swallow failure: a partial delete has to be
    reported, because "your data is gone" is a promise and a half-kept promise
    about this corpus is worse than a refusal."""
    deleted: dict[str, int] = {}
    failed: list[str] = []
    for table in _DELETE_ORDER:
        try:
            res = _t(table).delete().eq("user_id", user_id).execute()
            deleted[table] = len(_rows(res))
        except Exception as e:
            logger.error("life: hard_delete %s failed user=%s: %s",
                         table, user_id, e)
            failed.append(table)
    return {"deleted": deleted, "failed": failed}
