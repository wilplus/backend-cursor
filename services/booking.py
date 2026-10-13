"""Booking page v1 (founder 2026-10-13).

One host (the admin), one meeting type, paid upfront on Stripe.

  settings      one row in booking_settings, edited at /admin/booking
  open times    the host's weekly hours (in the host's time zone), minus the
                busy times in the host's Proton Calendar share link (ICS),
                minus live bookings, each widened by the buffers
  checkout      hold the slot (booking_hold, advisory-locked), open a Stripe
                Checkout Session, confirm on checkout.session.completed
  confirmation  one email to the guest and one to the host, each with the same
                calendar invite (.ics) and the Google Meet link, so the lesson
                lands in both calendars

Every time crosses the API as a UTC ISO string; the browser shows it in the
viewer's own time zone. Cancel and reschedule are by reply email in v1.

Commerce, not a read on a speaker: nothing here touches recordings, the Ideal
Text or feedback.
"""
from __future__ import annotations

import base64
import html
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parseaddr
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config import Config
from services.db import db

logger = logging.getLogger(__name__)
config = Config()

BOOKING_KIND = "booking"
SLOT_STEP_MIN = 30
# Stripe's shortest Checkout expiry is 30 minutes. The hold outlives it a
# little, so a guest who pays in the last second still finds the slot held.
CHECKOUT_MINUTES = 30
HOLD_MINUTES = CHECKOUT_MINUTES + 5
CURRENCIES = ("usd", "eur", "pln", "gbp")
DAYS = ("0", "1", "2", "3", "4", "5", "6")  # Sunday=0, JS getDay() order

SETTINGS_FIELDS = (
    "slug", "title", "host_name", "duration_min", "price_cents", "currency",
    "buffer_before_min", "buffer_after_min", "notice_hours", "horizon_days",
    "timezone", "weekly_hours", "calendar_ics_url", "meet_url", "enabled", "bonus_tokens", "new_user_discount_pct", "allow_skip_payment",
)


class BookingError(Exception):
    """A request we refuse, with a code the frontend maps to words."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


# ---------------------------------------------------------------- settings

def get_settings() -> dict:
    rows = (db.client.table("booking_settings").select("*").eq("id", 1)
            .limit(1).execute().data) or []
    if not rows:
        raise BookingError("NOT_SET_UP", "booking_settings has no row", 503)
    return rows[0]


def _hhmm(value: Any) -> int:
    m = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", str(value or ""))
    if not m:
        raise BookingError("INVALID_HOURS", f"Times must look like 09:00, got {value!r}.")
    return int(m.group(1)) * 60 + int(m.group(2))


def _clean_hours(raw: Any) -> dict:
    if not isinstance(raw, dict):
        raise BookingError("INVALID_HOURS", "weekly_hours must be an object.")
    out: dict[str, list[list[str]]] = {}
    for day in DAYS:
        ranges = raw.get(day) or []
        if not isinstance(ranges, list):
            raise BookingError("INVALID_HOURS", "Each day is a list of [from, until] pairs.")
        clean = []
        for pair in ranges:
            if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
                raise BookingError("INVALID_HOURS", "Each day is a list of [from, until] pairs.")
            a, b = _hhmm(pair[0]), _hhmm(pair[1])
            if b <= a:
                raise BookingError("INVALID_HOURS", "The end of a day's hours must be after the start.")
            clean.append([str(pair[0]), str(pair[1])])
        if clean:
            out[day] = clean
    return out


def validate_settings(payload: dict, current: dict) -> dict:
    """Merge a partial update onto the current row and check every field."""
    if not isinstance(payload, dict):
        raise BookingError("INVALID_INPUT", "Send the settings as a JSON object.")
    s: dict[str, Any] = {k: current.get(k) for k in SETTINGS_FIELDS}
    s.update({k: v for k, v in payload.items() if k in SETTINGS_FIELDS})

    slug = str(s["slug"] or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", slug):
        raise BookingError("INVALID_SLUG", "The link may use lowercase letters, numbers and dashes.")
    s["slug"] = slug
    s["title"] = str(s["title"] or "").strip()[:120] or "1-on-1 lesson"
    s["host_name"] = str(s["host_name"] or "").strip()[:120] or "Artur Willoński"

    def _int(key: str, lo: int, hi: int) -> int:
        try:
            v = int(s[key])
        except (TypeError, ValueError):
            raise BookingError("INVALID_INPUT", f"{key} must be a whole number.")
        if not lo <= v <= hi:
            raise BookingError("INVALID_INPUT", f"{key} must be between {lo} and {hi}.")
        return v

    s["duration_min"] = _int("duration_min", 15, 240)
    s["price_cents"] = _int("price_cents", 0, 10_000_000)
    s["buffer_before_min"] = _int("buffer_before_min", 0, 240)
    s["buffer_after_min"] = _int("buffer_after_min", 0, 240)
    s["notice_hours"] = _int("notice_hours", 0, 720)
    s["horizon_days"] = _int("horizon_days", 1, 365)
    s["bonus_tokens"] = _int("bonus_tokens", 0, 10_000_000)
    s["new_user_discount_pct"] = _int("new_user_discount_pct", 0, 100)
    s["currency"] = str(s["currency"] or "").lower()
    if s["currency"] not in CURRENCIES:
        raise BookingError("INVALID_CURRENCY", f"Currency must be one of {', '.join(CURRENCIES)}.")
    try:
        ZoneInfo(str(s["timezone"]))
    except (ZoneInfoNotFoundError, ValueError):
        raise BookingError("INVALID_TIMEZONE", f"Unknown time zone {s['timezone']!r}.")
    s["weekly_hours"] = _clean_hours(s["weekly_hours"])
    # Calendar links: one per line, every calendar listed blocks the page.
    links = [u.strip() for u in str(s["calendar_ics_url"] or "").splitlines() if u.strip()]
    meet = str(s["meet_url"] or "").strip()
    for url in [*links, meet]:
        if url and not re.match(r"^(https?|webcal)://", url):
            raise BookingError("INVALID_URL", "Each link must be a web link.")
    s["calendar_ics_url"] = "\n".join(links)
    s["meet_url"] = meet
    s["enabled"] = bool(s["enabled"])
    s["allow_skip_payment"] = bool(s.get("allow_skip_payment"))
    if s["enabled"] and not s["meet_url"]:
        raise BookingError("MEET_REQUIRED", "Add the Google Meet link before turning the page on.")
    return s


def save_settings(payload: dict) -> dict:
    clean = validate_settings(payload, get_settings())
    clean["updated_at"] = datetime.now(timezone.utc).isoformat()
    db.client.table("booking_settings").update(clean).eq("id", 1).execute()
    _ICS_CACHE.clear()
    return get_settings()


def public_settings(slug: str) -> dict:
    """The page's public face, or NOT_FOUND when the link is wrong or off."""
    s = get_settings()
    if not s.get("enabled") or (slug or "").strip().lower() != s["slug"]:
        raise BookingError("NOT_FOUND", "No booking page at this link.", 404)
    return {
        "slug": s["slug"], "title": s["title"], "host_name": s["host_name"],
        "duration_min": s["duration_min"], "price_cents": s["price_cents"],
        "currency": s["currency"], "horizon_days": s["horizon_days"],
        "host_timezone": s["timezone"], "bonus_tokens": s.get("bonus_tokens") or 0,
    }


# ------------------------------------------------------- per-person prices

def user_price(user_id: str) -> Optional[int]:
    """The admin's price for this person, or None when they pay the list price."""
    rows = (db.client.table("booking_user_prices").select("price_cents").eq("user_id", user_id)
            .limit(1).execute().data) or []
    return int(rows[0]["price_cents"]) if rows else None


def set_user_price(user_id: str, price_cents: Optional[int]) -> Optional[int]:
    """Set one person's price; None goes back to the list price."""
    if price_cents is None:
        db.client.table("booking_user_prices").delete().eq("user_id", user_id).execute()
        return None
    if not 0 <= int(price_cents) <= 10_000_000:
        raise BookingError("INVALID_INPUT", "The price must be zero or more.")
    db.client.table("booking_user_prices").upsert({
        "user_id": user_id, "price_cents": int(price_cents),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).execute()
    return int(price_cents)


def _has_lesson(user_id: str) -> bool:
    rows = (db.client.table("bookings").select("id").eq("user_id", user_id)
            .eq("status", "confirmed").limit(1).execute().data) or []
    return bool(rows)


def offer_for(slug: str, user_id: str) -> dict:
    """What this person pays and gets. The page shows the list price crossed
    out when their price is lower."""
    page = public_settings(slug)
    own = user_price(user_id)
    price = page["price_cents"] if own is None else own
    # New-user offer: a % off for someone without a paid lesson yet. A price
    # set on their profile wins over it.
    pct = int(get_settings().get("new_user_discount_pct") or 0)
    if own is None and pct and not _has_lesson(user_id):
        price = round(page["price_cents"] * (100 - pct) / 100)
    return {
        "list_price_cents": page["price_cents"],
        "price_cents": price,
        "currency": page["currency"],
        "bonus_tokens": page["bonus_tokens"],
        "allow_skip_payment": PAYMENT_OFF or bool(get_settings().get("allow_skip_payment")),
    }


# Founder 2026-10-13: no payment for now; every booking confirms without
# Stripe. Set back to False to charge again.
PAYMENT_OFF = True


# ------------------------------------------------------ calendar busy times

@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime


_ICS_CACHE: dict[str, tuple[float, bytes]] = {}
_ICS_LOCK = threading.Lock()
ICS_FRESH_SECONDS = 300
ICS_STALE_SECONDS = 24 * 3600


def _fetch_ics(url: str) -> Optional[bytes]:
    """The feed body: fresh for 5 minutes, a stale copy for up to a day if
    Proton is down, and None when there is nothing usable (fail closed)."""
    now = time.time()
    with _ICS_LOCK:
        hit = _ICS_CACHE.get(url)
    if hit and now - hit[0] < ICS_FRESH_SECONDS:
        return hit[1]
    import httpx
    try:
        resp = httpx.get(url.replace("webcal://", "https://", 1), timeout=10,
                         follow_redirects=True)
        resp.raise_for_status()
        body = resp.content
        with _ICS_LOCK:
            _ICS_CACHE[url] = (now, body)
        return body
    except Exception as e:
        logger.warning("booking: calendar feed fetch failed: %s", e, exc_info=True)
        if hit and now - hit[0] < ICS_STALE_SECONDS:
            return hit[1]
        return None


def parse_busy(body: bytes, start: datetime, end: datetime, host_tz: ZoneInfo) -> list[Interval]:
    """Busy intervals in [start, end) from an ICS feed, recurring events
    expanded. Free (TRANSPARENT) and cancelled events don't block; all-day
    events block the whole day in the host's time zone."""
    import icalendar
    import recurring_ical_events

    cal = icalendar.Calendar.from_ical(body)
    out: list[Interval] = []
    for ev in recurring_ical_events.of(cal).between(start, end):
        if str(ev.get("TRANSP", "")).upper() == "TRANSPARENT":
            continue
        if str(ev.get("STATUS", "")).upper() == "CANCELLED":
            continue
        s = ev.get("DTSTART").dt
        e = ev.get("DTEND").dt if ev.get("DTEND") else None
        if isinstance(s, datetime):
            s = s if s.tzinfo else s.replace(tzinfo=host_tz)
            e = e if isinstance(e, datetime) else s + (ev.get("DURATION").dt if ev.get("DURATION") else timedelta(0))
            e = e if e.tzinfo else e.replace(tzinfo=host_tz)
        else:  # all-day
            e = e if isinstance(e, date) else s + timedelta(days=1)
            s = datetime(s.year, s.month, s.day, tzinfo=host_tz)
            e = datetime(e.year, e.month, e.day, tzinfo=host_tz)
        if e > s:
            out.append(Interval(s.astimezone(timezone.utc), e.astimezone(timezone.utc)))
    return out


def calendar_busy(s: dict, start: datetime, end: datetime) -> Optional[list[Interval]]:
    """Busy times from every calendar link (one per line). None means one
    of them could not be read, so nothing is offered."""
    busy: list[Interval] = []
    for url in (s.get("calendar_ics_url") or "").splitlines():
        url = url.strip()
        if not url:
            continue
        body = _fetch_ics(url)
        if body is None:
            return None
        try:
            busy += parse_busy(body, start, end, ZoneInfo(s["timezone"]))
        except Exception as e:
            logger.warning("booking: calendar feed could not be parsed: %s", e, exc_info=True)
            return None
    return busy


def live_bookings(start: datetime, end: datetime) -> list[Interval]:
    rows = (db.client.table("bookings").select("start_at,end_at,status,held_until")
            .in_("status", ["held", "confirmed"])
            .lt("start_at", end.isoformat()).gt("end_at", start.isoformat())
            .execute().data) or []
    now = datetime.now(timezone.utc)
    out = []
    for r in rows:
        if r["status"] == "held" and (not r.get("held_until") or _dt(r["held_until"]) <= now):
            continue
        out.append(Interval(_dt(r["start_at"]), _dt(r["end_at"])))
    return out


def _dt(value: str) -> datetime:
    d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------- open times

def open_slots(s: dict, start: datetime, end: datetime, *, now: Optional[datetime] = None,
               busy: Optional[list[Interval]] = None) -> list[datetime]:
    """Every start time in [start, end) a guest may book, in UTC."""
    now = now or datetime.now(timezone.utc)
    tz = ZoneInfo(s["timezone"])
    dur = timedelta(minutes=int(s["duration_min"]))
    before = timedelta(minutes=int(s["buffer_before_min"]))
    after = timedelta(minutes=int(s["buffer_after_min"]))
    earliest = max(start, now + timedelta(hours=int(s["notice_hours"])))
    latest = min(end, now + timedelta(days=int(s["horizon_days"])))
    if earliest >= latest:
        return []
    if busy is None:
        cal = calendar_busy(s, earliest - before - dur, latest + after + dur)
        if cal is None:
            return []
        busy = cal + live_bookings(earliest - before - dur, latest + after + dur)

    out: list[datetime] = []
    day = earliest.astimezone(tz).date() - timedelta(days=1)
    last_day = latest.astimezone(tz).date() + timedelta(days=1)
    while day <= last_day:
        weekday = str((day.weekday() + 1) % 7)  # Python Mon=0 -> Sunday=0
        for a, b in (s.get("weekly_hours") or {}).get(weekday, []):
            minute, stop = _hhmm(a), _hhmm(b)
            while minute + int(s["duration_min"]) <= stop:
                local = datetime(day.year, day.month, day.day, minute // 60, minute % 60, tzinfo=tz)
                st = local.astimezone(timezone.utc)
                # A wall time that doesn't exist (spring-forward) round-trips
                # to a different wall time; skip it rather than offer it.
                if st.astimezone(tz).replace(tzinfo=None) == local.replace(tzinfo=None):
                    en = st + dur
                    if earliest <= st < latest and not any(
                            st - before < b_.end and en + after > b_.start for b_ in busy):
                        out.append(st)
                minute += SLOT_STEP_MIN
        day += timedelta(days=1)
    return sorted(set(out))


# ----------------------------------------------------------------- checkout

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def start_checkout(*, slug: str, user_id: str, start_iso: str, name: str, email: str,
                   guest_timezone: str, note: str = "", embedded: bool = False,
                   skip_payment: bool = False) -> dict:
    """Hold the slot and open Stripe Checkout for a signed-in account, at that
    person's price (charged as an amount, not a Stripe product). Returns
    {"client_secret": ...} for the card form inside the booking page when
    `embedded`, else {"url": ...} for Stripe's own page; a free meeting skips
    Stripe and returns {"url": ...} to the confirmation."""
    s = get_settings()
    offer = offer_for(slug, user_id)  # raises NOT_FOUND when off or wrong link
    price = int(offer["price_cents"])
    # Booking without paying (temporary, only while the admin allows it): a
    # confirmed booking at 0 with no tokens; the lesson is settled outside.
    skip = PAYMENT_OFF or (skip_payment and offer["allow_skip_payment"])
    if skip:
        price = 0
    name, email, note = (name or "").strip()[:120], (email or "").strip()[:254], (note or "").strip()[:2000]
    if not name:
        raise BookingError("NAME_REQUIRED", "Add your name.")
    if not EMAIL_RE.match(email):
        raise BookingError("EMAIL_INVALID", "Check the email address.")
    try:
        ZoneInfo(guest_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        guest_timezone = "UTC"
    try:
        st = _dt(start_iso).astimezone(timezone.utc)
    except (TypeError, ValueError):
        raise BookingError("INVALID_TIME", "That time is not valid.")
    if st not in open_slots(s, st - timedelta(minutes=1), st + timedelta(minutes=1)):
        raise BookingError("SLOT_TAKEN", "That time was just taken. Pick another.", 409)

    en = st + timedelta(minutes=int(s["duration_min"]))
    held_until = datetime.now(timezone.utc) + timedelta(minutes=HOLD_MINUTES)
    booking_id = db.client.rpc("booking_hold", {
        "p_start_at": st.isoformat(), "p_end_at": en.isoformat(),
        "p_buffer_before": int(s["buffer_before_min"]), "p_buffer_after": int(s["buffer_after_min"]),
        "p_held_until": held_until.isoformat(), "p_guest_name": name, "p_guest_email": email,
        "p_guest_timezone": guest_timezone, "p_note": note, "p_title": s["title"],
        "p_price_cents": price, "p_currency": s["currency"], "p_meet_url": s["meet_url"],
    }).execute().data
    if not booking_id:
        raise BookingError("SLOT_TAKEN", "That time was just taken. Pick another.", 409)
    booking_id = str(booking_id)
    db.client.table("bookings").update({
        "user_id": user_id, "list_price_cents": int(offer["list_price_cents"]),
        "bonus_tokens": 0 if skip else int(offer["bonus_tokens"]),
        "due_cents": int(offer["price_cents"]) if skip else None,
    }).eq("id", booking_id).execute()
    base = (config.FRONTEND_URL or "https://www.willpowerlab.com").rstrip("/")

    if price == 0:
        _confirm(booking_id, session_id=None)
        return {"url": f"{base}/book/{s['slug']}/done?booking={booking_id}"}

    api_key = (getattr(config, "STRIPE_SECRET_KEY", None) or "").strip()
    if not api_key:
        _release(booking_id)
        raise BookingError("PAYMENTS_OFF", "Payments are not set up yet.", 503)
    import stripe
    stripe.api_key = api_key
    metadata = {"kind": BOOKING_KIND, "booking_id": booking_id}
    done_url = f"{base}/book/{s['slug']}/done?session_id={{CHECKOUT_SESSION_ID}}"
    where: dict[str, Any] = (
        {"ui_mode": "embedded", "return_url": done_url} if embedded
        else {"success_url": done_url, "cancel_url": f"{base}/book/{s['slug']}"})
    try:
        session = stripe.checkout.Session.create(
            **where,
            mode="payment",
            customer_email=email,
            line_items=[{
                "price_data": {
                    "currency": s["currency"],
                    "unit_amount": price,
                    "product_data": {"name": f"{s['title']} with {s['host_name']}"},
                },
                "quantity": 1,
            }],
            client_reference_id=booking_id,
            metadata=metadata,
            payment_intent_data={"metadata": metadata},
            invoice_creation={"enabled": True},
            expires_at=int(time.time()) + CHECKOUT_MINUTES * 60,
        )
    except Exception as e:
        logger.warning("booking: checkout open failed booking=%s: %s", booking_id, e, exc_info=True)
        _release(booking_id)
        raise BookingError("PAYMENT_ERROR", "Payment could not start. Try again.", 502)
    sid = session.get("id") if isinstance(session, dict) else getattr(session, "id", None)
    db.client.table("bookings").update({"stripe_session_id": sid}).eq("id", booking_id).execute()
    if embedded:
        return {"client_secret": _get(session, "client_secret")}
    return {"url": _get(session, "url")}


def _release(booking_id: str) -> None:
    db.client.table("bookings").update({"status": "cancelled"}).eq("id", booking_id) \
        .eq("status", "held").execute()


def _get(obj: Any, key: str) -> Any:
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def confirm_checkout(session_id: str) -> Optional[dict]:
    """Confirm the booking behind a paid Checkout Session. Idempotent; safe to
    call from the webhook and from the success page. Returns the booking row,
    or None when the session is not a paid booking of ours."""
    import stripe
    api_key = (getattr(config, "STRIPE_SECRET_KEY", None) or "").strip()
    if not api_key:
        return None
    stripe.api_key = api_key
    session = stripe.checkout.Session.retrieve(str(session_id))
    md = _get(session, "metadata") or {}
    booking_id = str(_get(md, "booking_id") or "")
    if _get(md, "kind") != BOOKING_KIND or not booking_id:
        return None
    rows = db.client.table("bookings").select("*").eq("id", booking_id).limit(1).execute().data or []
    if not rows:
        logger.error("booking: paid session %s names unknown booking %s", session_id, booking_id)
        return None
    row = rows[0]
    if _get(session, "payment_status") != "paid":
        return row
    if (str(_get(session, "currency") or "").lower() != row["currency"]
            or int(_get(session, "amount_total") or -1) != int(row["price_cents"])):
        logger.error("booking: amount mismatch session=%s booking=%s", session_id, booking_id)
        return row
    return _confirm(booking_id, session_id=str(session_id))


def _confirm(booking_id: str, *, session_id: Optional[str]) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    upd: dict[str, Any] = {"status": "confirmed", "confirmed_at": now}
    if session_id:
        upd["stripe_session_id"] = session_id
    # A paid hold is confirmed even if it outlived held_until: the guest paid.
    db.client.table("bookings").update(upd).eq("id", booking_id).in_("status", ["held", "cancelled"]) \
        .is_("confirmed_at", "null").execute()
    # Claim the emails exactly once, whoever gets here first.
    claimed = (db.client.table("bookings").update({"emails_sent_at": now}).eq("id", booking_id)
               .eq("status", "confirmed").is_("emails_sent_at", "null").execute().data) or []
    _grant_tokens(booking_id)
    row = (db.client.table("bookings").select("*").eq("id", booking_id).limit(1).execute().data or [{}])[0]
    if claimed:
        try:
            send_confirmation_emails(row)
        except Exception as e:  # the booking stands; the host sees it in admin
            logger.error("booking: confirmation emails failed booking=%s: %s", booking_id, e, exc_info=True)
    return row


def _grant_tokens(booking_id: str) -> None:
    """Add the lesson's tokens to the booker's account, once. A failed grant is
    released so the next confirm (Stripe retry or the success page) tries again."""
    now = datetime.now(timezone.utc).isoformat()
    claimed = (db.client.table("bookings").update({"tokens_granted_at": now}).eq("id", booking_id)
               .eq("status", "confirmed").gt("bonus_tokens", 0).not_.is_("user_id", "null")
               .is_("tokens_granted_at", "null").execute().data) or []
    if not claimed:
        return
    row = claimed[0]
    from services import token_account
    outcome = token_account.package_grant(
        str(row["user_id"]), tokens=int(row["bonus_tokens"]), coach_reviews=0,
        ref_id=f"booking:{booking_id}", package="booking_lesson")
    if not outcome.get("ok"):
        logger.error("booking: token grant failed booking=%s reason=%s", booking_id, outcome.get("reason"))
        db.client.table("bookings").update({"tokens_granted_at": None}).eq("id", booking_id).execute()


def booking_for_guest(*, session_id: str = "", booking_id: str = "") -> Optional[dict]:
    """What the success page shows. A Stripe session id is unguessable, so it
    is the guest's key; a booking id only works for a free meeting."""
    row = None
    if session_id:
        row = confirm_checkout(session_id)
    elif booking_id and re.fullmatch(r"[0-9a-f-]{36}", booking_id):
        rows = db.client.table("bookings").select("*").eq("id", booking_id) \
            .eq("price_cents", 0).limit(1).execute().data or []
        row = rows[0] if rows else None
    if not row:
        return None
    return {
        "status": row["status"], "title": row["title"], "start_at": row["start_at"],
        "end_at": row["end_at"], "guest_name": row["guest_name"], "guest_email": row["guest_email"],
        "guest_timezone": row["guest_timezone"],
        "meet_url": row["meet_url"] if row["status"] == "confirmed" else "",
        "price_cents": row["price_cents"], "currency": row["currency"],
        "list_price_cents": row.get("list_price_cents") or row["price_cents"],
        "bonus_tokens": row.get("bonus_tokens") or 0,
        "due_cents": row.get("due_cents") or 0,
    }


def admin_bookings() -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    rows = (db.client.table("bookings")
            .select("id,start_at,end_at,status,guest_name,guest_email,guest_timezone,note,price_cents,list_price_cents,currency,bonus_tokens,tokens_granted_at,confirmed_at")
            .eq("status", "confirmed").gte("end_at", since).order("start_at").execute().data) or []
    return rows


# ------------------------------------------------------------------- emails

def money(cents: int, currency: str) -> str:
    symbols = {"usd": "$", "eur": "€", "gbp": "£"}
    amount = f"{cents / 100:,.2f}".replace(".00", "")
    sym = symbols.get(currency.lower())
    return f"{sym}{amount}" if sym else f"{amount} {currency.upper()}"


def _when(start: datetime, end: datetime, tz_name: str) -> str:
    tz = ZoneInfo(tz_name)
    s, e = start.astimezone(tz), end.astimezone(tz)
    city = tz_name.split("/")[-1].replace("_", " ")
    return (f"{s:%A, %B} {s.day}, {s.strftime('%I:%M %p').lstrip('0')}"
            f" – {e.strftime('%I:%M %p').lstrip('0')} ({city} time)")


def _ics_text(value: str) -> str:
    return (value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def build_invite(row: dict, *, organizer_email: str, host_email: str, host_name: str) -> str:
    """An iCalendar REQUEST both mail apps (Proton, Gmail, Apple, Outlook)
    offer to add to the calendar."""
    fmt = "%Y%m%dT%H%M%SZ"
    start, end = _dt(row["start_at"]), _dt(row["end_at"])
    desc = f"Join on Google Meet: {row['meet_url']}\n\nTo cancel or move, reply to the confirmation email."
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//WillpowerLab//Booking//EN",
        "CALSCALE:GREGORIAN", "METHOD:REQUEST", "BEGIN:VEVENT",
        f"UID:booking-{row['id']}@willpowerlab.com",
        f"DTSTAMP:{datetime.now(timezone.utc).strftime(fmt)}",
        f"DTSTART:{start.astimezone(timezone.utc).strftime(fmt)}",
        f"DTEND:{end.astimezone(timezone.utc).strftime(fmt)}",
        f"SUMMARY:{_ics_text(row['title'] + ' with ' + host_name + ' & ' + row['guest_name'])}",
        f"DESCRIPTION:{_ics_text(desc)}",
        f"LOCATION:{_ics_text(row['meet_url'])}",
        f"URL:{row['meet_url']}",
        f"ORGANIZER;CN={_ics_text(host_name)}:mailto:{organizer_email}",
        f"ATTENDEE;CN={_ics_text(host_name)};ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:{host_email}",
        f"ATTENDEE;CN={_ics_text(row['guest_name'])};ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:{row['guest_email']}",
        "SEQUENCE:0", "STATUS:CONFIRMED", "TRANSP:OPAQUE",
        "BEGIN:VALARM", "TRIGGER:-PT1H", "ACTION:DISPLAY",
        f"DESCRIPTION:{_ics_text(row['title'])} in 1 hour", "END:VALARM",
        "END:VEVENT", "END:VCALENDAR",
    ]
    return "".join(_fold(line) + "\r\n" for line in lines)


def _fold(line: str) -> str:
    """RFC 5545: lines longer than 75 octets continue on a line starting
    with a space."""
    out: list[str] = []
    cur = b""
    for ch in line:
        enc = ch.encode("utf-8")
        if len(cur) + len(enc) > (75 if not out else 74):
            out.append(cur.decode("utf-8"))
            cur = b""
        cur += enc
    out.append(cur.decode("utf-8"))
    return "\r\n ".join(out)


def _email_html(paragraphs: list[str]) -> str:
    body = "".join(f'<p style="margin:0 0 14px">{p}</p>' for p in paragraphs)
    return ('<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
            f'font-size:15px;line-height:1.5;color:#141414;max-width:520px">{body}</div>')


def send_confirmation_emails(row: dict) -> None:
    from services.email_service import send_email_resend

    s = get_settings()
    host_email = (config.ADMIN_EMAIL or "artur@willonski.com").strip()
    organizer = parseaddr(config.RESEND_FROM_EMAIL or "")[1] or host_email
    invite = build_invite(row, organizer_email=organizer, host_email=host_email, host_name=s["host_name"])
    attachment = [{
        "filename": "invite.ics",
        "content": base64.b64encode(invite.encode("utf-8")).decode("ascii"),
        "content_type": "text/calendar; method=REQUEST; charset=UTF-8",
    }]
    start, end = _dt(row["start_at"]), _dt(row["end_at"])
    e = html.escape
    meet = e(row["meet_url"])
    meet_link = f'<a href="{meet}">{meet}</a>'
    first = e(row["guest_name"].split(" ")[0])
    guest_tz = row.get("guest_timezone") or "UTC"
    gs = start.astimezone(ZoneInfo(guest_tz))

    send_email_resend(
        to=row["guest_email"],
        subject=f"Confirmed: {row['title']}, {gs:%a %b} {gs.day} at {gs.strftime('%I:%M %p').lstrip('0')}",
        html=_email_html([
            f"Hi {first},",
            f"You're booked: {e(row['title'])} with {e(s['host_name'])}.",
            f"<strong>{e(_when(start, end, guest_tz))}</strong>",
            f"Join on Google Meet: {meet_link}",
            *([f"{int(row['bonus_tokens']):,} tokens are added to your WillpowerLab account."]
              if row.get("bonus_tokens") and row.get("user_id") else []),
            "The calendar invite is attached. Need to cancel or move it? Reply to this email.",
        ]),
        headers={"Reply-To": host_email},
        attachments=attachment,
    )
    note = f"<br>Note: {e(row['note'])}" if row.get("note") else ""
    send_email_resend(
        to=host_email,
        subject=f"New booking: {row['guest_name']}, {_when(start, end, s['timezone'])}",
        html=_email_html([
            f"<strong>{e(row['guest_name'])}</strong> ({e(row['guest_email'])}) booked {e(row['title'])}.",
            f"<strong>{e(_when(start, end, s['timezone']))}</strong><br>"
            f"Their time: {e(_when(start, end, guest_tz))}",
            f"Paid {e(money(int(row['price_cents']), row['currency']))}.{note}",
            f"Google Meet: {meet_link}",
        ]),
        headers={"Reply-To": row["guest_email"]},
        attachments=attachment,
    )
