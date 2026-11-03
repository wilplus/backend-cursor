"""Asks to one person (founder 2026-10-13, step 2). Table: person_asks.

The admin asks one person for a missing answer from their profile; the
person's app shows it the next time they open the chat, one at a time, in
the bar at the top of the chat, never in the buttons under it (N391).

  whatsapp  the WhatsApp form (answered when the number is saved); the next
            visit's ask is one too, made by the app (``ask_from_visit``)
  consent   the question, answered No | Yes (founder 2026-10-18); one the
            app cannot show still points to the Data & consent page
  promo     their special plan price, pointing to the pricing screen
  lesson    their lesson price, pointing to the booking page

The home-screen ask is deleted (N391): none is sent, an open one is closed.
Was: the footer slot the app's own offers use, at the end of a Take.

Any consent can be asked again, also after a "no", but not within 30 days of
the last "no" (founder 2026-10-13: privacy law wants consent given freely).
A consent ask answered in the chat while the consent is still not given is a
"no" too. "share" and "email" are not asked: no screen answers them any more
(founder 2026-10-18). The app's own WhatsApp ask (no ``created_by``) carries
its opener and is done once shown (N294 item 8, N295).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from services.db import db

KINDS = ("whatsapp", "consent", "promo", "lesson")
#: The opener of the next visit's WhatsApp ask (founder 2026-10-31, N295).
VISIT_OPENER = "It seems you enjoy using WillpowerLab."
CONSENT_KEYS = ("processing", "personalised_practice", "sensitive_information",
                "training")
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
        last_no = max(filter(None, [(row or {}).get("last_no_at"),
                                    _last_chat_no(user_id, str(consent_key))]),
                      key=_when, default=None)
        if last_no:
            again = _when(last_no) + WAIT_AFTER_NO
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


def _when(value) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _last_chat_no(user_id: str, consent_key: str) -> Optional[str]:
    """When this consent was last answered in the chat. A yes makes the
    consent "yes" (refused above), so an answered ask is a "no"."""
    rows = (db.client.table("person_asks").select("resolved_at").eq("user_id", user_id)
            .eq("kind", "consent").eq("consent_key", consent_key).eq("status", "answered")
            .order("resolved_at", desc=True).limit(1).execute().data) or []
    return rows[0].get("resolved_at") if rows else None


def next_for(user_id: str) -> Optional[dict]:
    """The oldest ask the person has not answered yet. A price ask carries
    the price it tells them about; one whose price has ended is closed."""
    rows = (db.client.table("person_asks").select("id,kind,consent_key,status,created_by")
            .eq("user_id", user_id).in_("status", list(OPEN))
            .order("created_at").limit(5).execute().data) or []
    for ask in rows:
        if ask["kind"] not in KINDS:  # the home screen, deleted (N391)
            answered(user_id, ask["kind"])
            continue
        if ask.pop("created_by", None) is None and ask["kind"] == "whatsapp":
            ask["opener"] = VISIT_OPENER
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


def ask_from_visit(user_id: str, *, since: str, most: int) -> None:
    """The next visit's WhatsApp ask, made by the app (N294 item 8, N391):
    only when none is open, fewer than ``most`` were made, and none since
    ``since`` (the newest Take done: one per Take)."""
    made = (db.client.table("person_asks").select("status,created_at")
            .eq("user_id", user_id).eq("kind", "whatsapp").is_("created_by", "null")
            .execute().data) or []
    if len(made) >= most or any(r.get("status") in OPEN for r in made):
        return
    if since and any(_when(r["created_at"]) >= _when(since) for r in made if r.get("created_at")):
        return
    db.client.table("person_asks").insert({"user_id": user_id, "kind": "whatsapp"}).execute()


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
    """The person's app reports `shown` (they saw it), `opened` (they
    tapped through to the consent page) or `answered` (they answered a
    consent ask in the chat, no or yes)."""
    if event == "shown":
        (db.client.table("person_asks").update({"status": "shown", "shown_at": _now()})
         .eq("id", ask_id).eq("user_id", user_id).eq("status", "waiting").execute())
        # The app's own ask is shown once (N294 item 8): it is done.
        (db.client.table("person_asks").update({"status": "answered", "resolved_at": _now()})
         .eq("id", ask_id).eq("user_id", user_id).is_("created_by", "null").execute())
    elif event == "opened":
        (db.client.table("person_asks").update({"status": "opened", "resolved_at": _now()})
         .eq("id", ask_id).eq("user_id", user_id).in_("status", list(OPEN)).execute())
    elif event == "answered":
        (db.client.table("person_asks").update({"status": "answered", "resolved_at": _now()})
         .eq("id", ask_id).eq("user_id", user_id).eq("kind", "consent")
         .in_("status", list(OPEN)).execute())
    else:
        raise AskError("INVALID_EVENT", "event must be shown, opened or answered")


def answered(user_id: str, kind: str) -> None:
    """The answer arrived by its own road (number saved, home-screen open)."""
    (db.client.table("person_asks").update({"status": "answered", "resolved_at": _now()})
     .eq("user_id", user_id).eq("kind", kind).in_("status", list(OPEN)).execute())
