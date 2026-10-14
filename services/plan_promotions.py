"""A special plan price for one person (founder 2026-10-14, step 3).

The admin sets it on the person's profile: a plan, their price and an end
date. Their pricing screen shows it with the normal price crossed out, and
checkout charges it (services/token_packages.py). One row per person in
plan_promotions; ending it sets ends_at to now.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from services.db import db


class PromotionError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _list_cents(plan: str) -> Optional[int]:
    from services.token_packages import package_spec
    spec = package_spec(plan)
    return int(spec["cents"]) if spec else None


def active(user_id: str) -> Optional[dict]:
    """{"plan", "price_cents", "list_cents", "ends_at"} while it runs, else None."""
    rows = (db.client.table("plan_promotions").select("plan,price_cents,ends_at")
            .eq("user_id", user_id).gt("ends_at", _now().isoformat()).limit(1).execute().data) or []
    if not rows:
        return None
    row = rows[0]
    list_cents = _list_cents(row["plan"])
    if list_cents is None or int(row["price_cents"]) >= list_cents:
        return None
    return {"plan": row["plan"], "price_cents": int(row["price_cents"]),
            "list_cents": list_cents, "ends_at": row["ends_at"]}


def save(user_id: str, *, plan: str, price_cents: int, ends_on: str, admin_id: str) -> dict:
    list_cents = _list_cents(plan)
    if list_cents is None:
        raise PromotionError("INVALID_PLAN", "Pick a plan.")
    if not 100 <= price_cents < list_cents:
        raise PromotionError("INVALID_PRICE", "Their price must be at least $1 and lower than the normal price.")
    try:
        ends = datetime.fromisoformat(f"{ends_on[:10]}T23:59:59+00:00")
    except ValueError:
        raise PromotionError("INVALID_DATE", "Pick an end date.")
    if ends <= _now():
        raise PromotionError("INVALID_DATE", "The end date must be in the future.")
    db.client.table("plan_promotions").upsert({
        "user_id": user_id, "plan": plan, "price_cents": price_cents,
        "ends_at": ends.isoformat(), "created_by": admin_id, "created_at": _now().isoformat(),
    }, on_conflict="user_id").execute()
    return active(user_id) or {}


def end(user_id: str) -> None:
    (db.client.table("plan_promotions").update({"ends_at": _now().isoformat()})
     .eq("user_id", user_id).gt("ends_at", _now().isoformat()).execute())
