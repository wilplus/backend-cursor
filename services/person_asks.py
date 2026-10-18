"""Asks to one person (founder 2026-10-13, step 2). Table: person_asks.

The admin asks one person for a missing answer from their profile; the
person's app shows it the next time they open the chat (founder 2026-10-18;
it used to wait for their next Take), one at a time, in the footer slot the
app's own offers use.

  whatsapp     the app's WhatsApp offer (answered when the number is saved)
  home_screen  the app's add-to-home-screen offer (answered when the app is
               next opened from the home screen)
  consent      a pointer to the Data & consent page, where the person answers
               on the locked consent screen itself (opened when they tap it)
  promo        their special plan price, pointing to the pricing screen
  lesson       their lesson price, pointing to the booking page

Any consent can be asked again, also after a "no", but not within 30 days of
the last "no" (founder 2026-10-13: privacy law wants consent given freely).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from services.db import db

KINDS = ("whatsapp", "home_screen", "consent", "promo", "lesson")
CONSENT_KEYS = ("processing", "personalised_practice", "sensitive_information",
                "training", "share", "email")
WAIT_AFTER_NO = timedelta(days=30)
OPEN = ("waiting", "shown")


class AskError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_for(user_id: str, limit: int = 20) -> list[dict]:
    return (db.client.table("person_asks").select("*").eq("user_id", user_id)
            .order("created_at", desc=True).limit(limit).execute().data) or []


def create(user_id: str, kind: str, consent_key: Optional[str], *,
           admin_id: str, consents: list[dict]) -> dict:
    """Send one ask. `consents` is the profile's consent list, which carries
    each consent's state and the date of its last "no"."""
    if kind not in KINDS:
        raise AskError("INVALID_KIND", "Unknown ask.")
    if kind == "consent":
        if consent_key not in CONSENT_KEYS:
            raise AskError("INVALID_CONSENT", "Unknown consent.")
        row = next((c for c in consents if c.get("key") == consent_key), None)
        if row and row.get("state") == "yes":
            raise AskError("ALREADY_YES", "They already said yes to this.", 409)
        last_no = (row or {}).get("last_no_at")
        if last_no:
            again = datetime.fromisoformat(str(last_no).replace("Z", "+00:00")) + WAIT_AFTER_NO
            if again > datetime.now(timezone.utc):
                raise AskError("TOO_SOON", f"They said no recently. You can ask again on {again:%b %d}.", 409)
    else:
        consent_key = None
    q = (db.client.table("person_asks").select("id").eq("user_id", user_id).eq("kind", kind)
         .in_("status", list(OPEN)))
    q = q.eq("consent_key", consent_key) if consent_key else q.is_("consent_key", "null")
    if q.limit(1).execute().data:
        raise AskError("ALREADY_ASKED", "This is already waiting for them.", 409)
    rows = db.client.table("person_asks").insert({
        "user_id": user_id, "kind": kind, "consent_key": consent_key, "created_by": admin_id,
    }).execute().data or []
    return rows[0] if rows else {}


def next_for(user_id: str) -> Optional[dict]:
    """The oldest ask the person has not answered yet. A price ask carries
    the price it tells them about; one whose price has ended is closed."""
    rows = (db.client.table("person_asks").select("id,kind,consent_key,status")
            .eq("user_id", user_id).in_("status", list(OPEN))
            .order("created_at").limit(5).execute().data) or []
    for ask in rows:
        if ask["kind"] == "promo":
            from services import plan_promotions
            ask["promotion"] = plan_promotions.active(user_id)
            if not ask["promotion"]:
                answered(user_id, "promo")
                continue
        if ask["kind"] == "lesson":
            ask["lesson"] = lesson_offer(user_id)
            if not ask["lesson"] or ask["lesson"]["price_cents"] >= ask["lesson"]["list_price_cents"]:
                answered(user_id, "lesson")
                continue
        return ask
    return None


def lesson_offer(user_id: str) -> Optional[dict]:
    """This person's 1-on-1 lesson: price, list price and the
    booking link, or None when the booking page is off."""
    from services import booking
    s = booking.get_settings()
    try:
        offer = booking.offer_for(s["slug"], user_id)
    except booking.BookingError:
        return None
    return {"slug": s["slug"], "host_name": s["host_name"], "duration_min": s["duration_min"],
            "price_cents": offer["price_cents"], "list_price_cents": offer["list_price_cents"],
            "currency": offer["currency"]}


def mark(user_id: str, ask_id: str, event: str) -> None:
    """The person's app reports `shown` (they saw it) or `opened` (they
    tapped through to the consent page)."""
    if event == "shown":
        (db.client.table("person_asks").update({"status": "shown", "shown_at": _now()})
         .eq("id", ask_id).eq("user_id", user_id).eq("status", "waiting").execute())
    elif event == "opened":
        (db.client.table("person_asks").update({"status": "opened", "resolved_at": _now()})
         .eq("id", ask_id).eq("user_id", user_id).in_("status", list(OPEN)).execute())
    else:
        raise AskError("INVALID_EVENT", "event must be shown or opened")


def answered(user_id: str, kind: str) -> None:
    """The answer arrived by its own road (number saved, home-screen open)."""
    (db.client.table("person_asks").update({"status": "answered", "resolved_at": _now()})
     .eq("user_id", user_id).eq("kind", kind).in_("status", list(OPEN)).execute())
