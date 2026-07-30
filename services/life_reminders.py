"""Opt-in web-push reminders for the Life Panel (founder decision 2026-07-30).

THE ONE SANCTIONED DELIVERY PATH. L-4's "zero nudges" is amended by explicit
founder decision, narrowly: a web-push reminder the user turned ON themselves,
per slot, in the panel settings. Everything else stays banned, and the
NoNudgesTests in test_life_panel.py hold that line:

  * every default is OFF — a user who never touches the settings receives
    exactly nothing;
  * the slot ladder only (founder, extended 2026-07-30): daily morning,
    daily evening, then the checkout cadence weekly, monthly, quarterly,
    yearly, fiveyear, tenyear — every rung strictly opt-in;
  * delivery code lives in THIS module and nowhere else. life_engine,
    life_store, life_chat and life_import stay fully banned from anything
    outbound; routes/life_routes.py may expose the settings endpoints but
    never imports pywebpush and never sends;
  * generation stays delivery-free: ensure_daily_card / ensure_evening_pass
    write a row and return, exactly as before.

Copy in the payloads is the founder's (2026-07-30) and is deliberately humble:
each reminder says a thing is READY and asks the day's own question. Nothing
counts missed days, nothing says "come back", and a reminder never fires twice
for the same local day (life_reminder_log's unique index is the idempotency,
not application state).

Table I/O for the three reminder tables lives here rather than in
services/life_store: life_store's reads are one-owner by design and enforced,
while ``run_reminder_slot`` legitimately iterates every user who opted in.
Keeping the cross-user read in the module that owns delivery keeps that
exception exactly as wide as the founder's decision and no wider.

Config (os.environ, read at call time so tests and Railway both work):
  VAPID_PUBLIC_KEY      the applicationServerKey the browser subscribes with
  VAPID_PRIVATE_KEY     signs the pushes; ABSENT ⇒ sending is a graceful no-op
  VAPID_SUBJECT         mailto:/https: contact claim (default below)
  LIFE_REMINDER_SECRET  guards the internal cron webhook (routes/
                        life_reminders_webhook.py)
  LIFE_REMINDER_ANCHOR_YEAR
                        optional; a year on the five/ten-year cadence. The
                        fiveyear/tenyear crons fire yearly and this gate
                        no-ops the off years (see slot_due_this_year).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# The full ladder (founder, extended 2026-07-30): the two daily slots, then
# the checkout cadence weekly → ten-year. Longer cadences deep-link to
# EXISTING surfaces; there are no checkout views or tables.
SLOTS: tuple = ("morning", "evening", "weekly", "monthly", "quarterly",
                "yearly", "fiveyear", "tenyear")

# Founder copy, 2026-07-30. One short line each; the URL lands on the surface
# the reminder is about, never a marketing page. The monthly-and-longer
# checkouts land on the panel home, where the horizon strategy documents
# live; the weekly stays on the Sunday review.
PAYLOADS: dict = {
    "morning": {
        "title": "☀️ Morning check-in is ready",
        "body": "What's today's one thing?",
        "url": "/panel/today",
    },
    "evening": {
        "title": "🌙 Evening review is open",
        "body": "Did the one thing happen?",
        "url": "/panel/today",
    },
    "weekly": {
        "title": "🔭 Weekly review",
        "body": "Your week is ready to close",
        "url": "/panel/week",
    },
    "monthly": {
        "title": "🔭 Monthly checkout",
        "body": "A month of the bet, reviewed",
        "url": "/panel",
    },
    "quarterly": {
        "title": "🔭 Quarterly checkout",
        "body": "The quarter against the plan",
        "url": "/panel",
    },
    "yearly": {
        "title": "🔭 Yearly checkout",
        "body": "The year against the horizon",
        "url": "/panel",
    },
    "fiveyear": {
        "title": "🔭 Five-year checkout",
        "body": "Five years of the bet, reviewed",
        "url": "/panel",
    },
    "tenyear": {
        "title": "🔭 Ten-year checkout",
        "body": "Horizon 2035",
        "url": "/panel",
    },
}

# OFF is the whole point, for every rung of the ladder. These are the fields
# PUT /v2/life/reminders may touch, and the defaults a user who never opted
# in is read as having.
DEFAULT_SETTINGS: dict = {
    **{f"{slot}_enabled": False for slot in SLOTS},
    "tz_offset_minutes": 0,
}

_SETTINGS_TABLE = "life_reminder_settings"
_SUBSCRIPTIONS_TABLE = "life_push_subscriptions"
_LOG_TABLE = "life_reminder_log"

# UTC-14:00 … UTC+14:00 covers every real timezone.
_TZ_OFFSET_RANGE = (-14 * 60, 14 * 60)


def _t(table: str):
    from services.db import db
    return db.client.table(table)


def _rows(result: Any) -> list[dict]:
    data = getattr(result, "data", None)
    return list(data) if isinstance(data, list) else []


def _one(result: Any) -> Optional[dict]:
    rows = _rows(result)
    return rows[0] if rows else None


# ═════════════════════════════════════════════════════════════════════════
# Keys + settings
# ═════════════════════════════════════════════════════════════════════════

def public_key() -> Optional[str]:
    """The applicationServerKey, or None. None ⇒ the FE hides the toggles
    behind a hint — the feature simply is not configured."""
    return (os.environ.get("VAPID_PUBLIC_KEY") or "").strip() or None


def _private_key() -> Optional[str]:
    return (os.environ.get("VAPID_PRIVATE_KEY") or "").strip() or None


def _subject() -> str:
    return ((os.environ.get("VAPID_SUBJECT") or "").strip()
            or "mailto:hello@willpowerlab.com")


def get_settings(user_id: str) -> dict:
    """This user's switches, defaults when no row exists. Never raises."""
    try:
        row = _one(_t(_SETTINGS_TABLE).select("*")
                   .eq("user_id", user_id).limit(1).execute()) or {}
    except Exception as e:
        logger.warning("life_reminders: get_settings failed user=%s: %s",
                       user_id, e)
        row = {}
    out = dict(DEFAULT_SETTINGS)
    for key in DEFAULT_SETTINGS:
        if key in row and row[key] is not None:
            out[key] = row[key]
    return out


def sanitize_settings(body: Any) -> dict:
    """The PUT contract: only the four known fields, typed, tz clamped."""
    if not isinstance(body, dict):
        return {}
    out: dict[str, Any] = {}
    for slot in SLOTS:
        key = f"{slot}_enabled"
        if key in body:
            out[key] = bool(body.get(key))
    if "tz_offset_minutes" in body:
        try:
            tz = int(body.get("tz_offset_minutes"))
        except (TypeError, ValueError):
            tz = 0
        out["tz_offset_minutes"] = max(_TZ_OFFSET_RANGE[0],
                                       min(_TZ_OFFSET_RANGE[1], tz))
    return out


def upsert_settings(user_id: str, fields: dict) -> Optional[dict]:
    """Write the user's own switches. Returns the effective settings."""
    clean = sanitize_settings(fields)
    if not clean:
        return get_settings(user_id)
    try:
        _t(_SETTINGS_TABLE).upsert({
            "user_id": user_id,
            **clean,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="user_id").execute()
    except Exception as e:
        logger.error("life_reminders: upsert_settings failed user=%s: %s",
                     user_id, e)
        return None
    return get_settings(user_id)


# ═════════════════════════════════════════════════════════════════════════
# Subscriptions
# ═════════════════════════════════════════════════════════════════════════

def list_subscriptions(user_id: str) -> list[dict]:
    try:
        return _rows(_t(_SUBSCRIPTIONS_TABLE).select("*")
                     .eq("user_id", user_id).limit(20).execute())
    except Exception as e:
        logger.warning("life_reminders: list_subscriptions failed user=%s: %s",
                       user_id, e)
        return []


def save_subscription(user_id: str, *, endpoint: str, p256dh: str, auth: str,
                      user_agent: Optional[str] = None) -> Optional[dict]:
    """Upsert on the endpoint URL — re-subscribing the same browser updates
    the keys rather than stacking rows."""
    if not (endpoint and p256dh and auth):
        return None
    try:
        return _one(_t(_SUBSCRIPTIONS_TABLE).upsert({
            "user_id": user_id,
            "endpoint": endpoint[:2000],
            "p256dh": p256dh[:500],
            "auth": auth[:500],
            "user_agent": (user_agent or "")[:300] or None,
        }, on_conflict="endpoint").execute())
    except Exception as e:
        logger.error("life_reminders: save_subscription failed user=%s: %s",
                     user_id, e)
        return None


def delete_subscription(user_id: str,
                        endpoint: Optional[str] = None) -> Optional[int]:
    """Remove one endpoint, or all of this user's. Returns the count, None on
    failure."""
    try:
        query = _t(_SUBSCRIPTIONS_TABLE).delete().eq("user_id", user_id)
        if endpoint:
            query = query.eq("endpoint", endpoint)
        return len(_rows(query.execute()))
    except Exception as e:
        logger.error("life_reminders: delete_subscription failed user=%s: %s",
                     user_id, e)
        return None


# ═════════════════════════════════════════════════════════════════════════
# Delivery — the one sanctioned sender
# ═════════════════════════════════════════════════════════════════════════

def send_web_push(subscription: dict, payload: dict) -> bool:
    """One push to one browser. False on ANY failure, including "not
    configured" — a missing VAPID key degrades to nothing sent, never an
    error a route surfaces. A 404/410 from the push service means the browser
    unsubscribed, so the dead row is deleted on the spot."""
    key = _private_key()
    if not key:
        return False
    try:
        from pywebpush import webpush, WebPushException  # lazy: optional dep
    except ImportError:
        logger.warning("life_reminders: pywebpush not installed")
        return False
    try:
        webpush(
            subscription_info={
                "endpoint": subscription.get("endpoint"),
                "keys": {
                    "p256dh": subscription.get("p256dh"),
                    "auth": subscription.get("auth"),
                },
            },
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=key,
            vapid_claims={"sub": _subject()},
        )
        return True
    except WebPushException as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status in (404, 410):
            delete_subscription(str(subscription.get("user_id") or ""),
                                str(subscription.get("endpoint") or ""))
        logger.warning("life_reminders: push failed status=%s", status)
        return False
    except Exception as e:
        logger.warning("life_reminders: push failed: %s",
                       type(e).__name__)
        return False


# ═════════════════════════════════════════════════════════════════════════
# The cron entry point
# ═════════════════════════════════════════════════════════════════════════

def _local_date(tz_offset_minutes: int,
                now: Optional[datetime] = None) -> str:
    moment = (now or datetime.now(timezone.utc))
    return (moment + timedelta(minutes=int(tz_offset_minutes or 0))).date() \
        .isoformat()


def slot_due_this_year(slot: str, *, now: Optional[datetime] = None) -> bool:
    """Whether a five/ten-year slot is due in the current year.

    Railway cron has no yearly-interval schedule, so those two crons fire
    every year and THIS gate decides which years count. Simplest correct
    thing: ``LIFE_REMINDER_ANCHOR_YEAR`` names a year on the cadence (say
    2025); the slot fires only when (year - anchor) is a whole number of
    periods. Unset or malformed ⇒ fire whenever the cron does — the operator
    is then choosing years by enabling the service, which is also correct,
    just manual. Every other slot is always due; its cron IS its cadence."""
    if slot not in ("fiveyear", "tenyear"):
        return True
    raw = (os.environ.get("LIFE_REMINDER_ANCHOR_YEAR") or "").strip()
    if not raw:
        return True
    try:
        anchor = int(raw)
    except ValueError:
        return True
    period = 5 if slot == "fiveyear" else 10
    year = (now or datetime.now(timezone.utc)).year
    return (year - anchor) % period == 0


def _claim(user_id: str, slot: str, sent_on: str) -> bool:
    """Insert the idempotency row FIRST. A unique-violation means another run
    already owns this (user, slot, local day) — skip, never double-fire."""
    try:
        rows = _rows(_t(_LOG_TABLE).insert({
            "user_id": user_id, "slot": slot, "sent_on": sent_on,
        }).execute())
        return bool(rows)
    except Exception:
        return False


def run_reminder_slot(slot: str, *, now: Optional[datetime] = None) -> dict:
    """One firing of one slot, across every user who opted into it.

    OPT-IN IS THE QUERY: only rows with ``{slot}_enabled = true`` are read,
    and such a row only exists because the user flipped the switch through
    the consented settings route. Idempotent per local day via the log
    table's unique index, so an over-eager cron cannot nag."""
    if slot not in SLOTS:
        return {"slot": slot, "error": "unknown slot", "eligible": 0,
                "sent": 0, "skipped": 0, "failed": 0}
    if not slot_due_this_year(slot, now=now):
        # A five/ten-year cron fires yearly; the anchor decides which years
        # count (see slot_due_this_year). An off-year is a clean no-op.
        return {"slot": slot, "eligible": 0, "sent": 0, "skipped": 0,
                "failed": 0, "off_year": True}
    try:
        enabled = _rows(_t(_SETTINGS_TABLE).select("*")
                        .eq(f"{slot}_enabled", True).limit(10000).execute())
    except Exception as e:
        logger.error("life_reminders: settings read failed slot=%s: %s",
                     slot, e)
        return {"slot": slot, "error": "settings read failed", "eligible": 0,
                "sent": 0, "skipped": 0, "failed": 0}

    payload = PAYLOADS[slot]
    counts = {"slot": slot, "eligible": len(enabled), "sent": 0,
              "skipped": 0, "failed": 0}
    for row in enabled:
        user_id = str(row.get("user_id") or "")
        if not user_id:
            counts["skipped"] += 1
            continue
        subs = list_subscriptions(user_id)
        if not subs:
            counts["skipped"] += 1
            continue
        sent_on = _local_date(row.get("tz_offset_minutes") or 0, now)
        if not _claim(user_id, slot, sent_on):
            counts["skipped"] += 1
            continue
        delivered = False
        for sub in subs:
            if send_web_push(sub, payload):
                delivered = True
        if delivered:
            counts["sent"] += 1
        else:
            counts["failed"] += 1
    return counts


# ═════════════════════════════════════════════════════════════════════════
# BE-10 hooks — the reminder rows leave and die with everything else
# ═════════════════════════════════════════════════════════════════════════

def export_user(user_id: str) -> Optional[dict]:
    """The user's reminder rows for the panel export. None on failure so the
    export can report itself incomplete."""
    try:
        return {
            _SETTINGS_TABLE: _rows(
                _t(_SETTINGS_TABLE).select("*")
                .eq("user_id", user_id).limit(10).execute()),
            _SUBSCRIPTIONS_TABLE: list_subscriptions(user_id),
        }
    except Exception as e:
        logger.warning("life_reminders: export failed user=%s: %s",
                       user_id, e)
        return None


def hard_delete_user(user_id: str) -> dict:
    """Wipe subscriptions, settings and the log for one user. Same contract
    as life_store.hard_delete: report, never pretend."""
    deleted: dict[str, int] = {}
    failed: list[str] = []
    for table in (_SUBSCRIPTIONS_TABLE, _LOG_TABLE, _SETTINGS_TABLE):
        try:
            res = _t(table).delete().eq("user_id", user_id).execute()
            deleted[table] = len(_rows(res))
        except Exception as e:
            logger.error("life_reminders: hard_delete %s failed user=%s: %s",
                         table, user_id, e)
            failed.append(table)
    return {"deleted": deleted, "failed": failed}
