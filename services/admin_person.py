"""One person's profile for the admin (founder 2026-10-13, step 1).

Everything the app holds about one account, read in one place for
/admin/users/<id>: who they are, where they are from, what they agreed to
(and how many times they said no), their tokens and their lesson price.

Each block reads on its own and comes back None when it cannot be read, so
one missing table never blanks the whole page.

The phone number and the home-screen install live in the account's own
Supabase user_metadata (whatsapp_phone, home_screen_at): they go with the
account when it is deleted, and need no table of their own.

Commerce and contact data, not a read on a speaker: nothing here touches
recordings, the Ideal Text or feedback.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, Callable, Optional

import httpx

from config import Config
from services.db import db

logger = logging.getLogger(__name__)
config = Config()


# ------------------------------------------------------------- auth account

def _auth_url(user_id: str) -> str:
    return f"{(config.SUPABASE_URL or '').rstrip('/')}/auth/v1/admin/users/{user_id}"


def _auth_headers() -> dict:
    key = config.SUPABASE_SERVICE_ROLE_KEY
    return {"Authorization": f"Bearer {key}", "apikey": key}


def auth_user(user_id: str) -> Optional[dict]:
    resp = httpx.get(_auth_url(user_id), headers=_auth_headers(), timeout=10)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def set_metadata(user_id: str, values: dict) -> None:
    """Merge keys into the account's user_metadata (None removes a key)."""
    resp = httpx.put(_auth_url(user_id), headers=_auth_headers(),
                     json={"user_metadata": values}, timeout=10)
    resp.raise_for_status()


# ------------------------------------------------------------------- blocks

def _safe(label: str, read: Callable[[], Any]) -> Any:
    try:
        return read()
    except Exception:
        logger.warning("admin person: %s could not be read", label, exc_info=True)
        return None


def _principal(user_id: str) -> Optional[str]:
    from services.processing_authorization import ProcessingAuthorizationService
    row = db.get_owner_principal_for_user(str(user_id))
    if not row:
        return None
    return ProcessingAuthorizationService(db).resolve_acquisition_principal(
        str(row["id"]), user_id=str(user_id))


def _receipt(principal: str) -> Optional[dict]:
    rows = (db.client.table("processing_authorization_receipts")
            .select("country_of_residence,locale,accepted_at,policy_id")
            .eq("acquisition_principal_id", principal)
            .order("accepted_at", desc=True).limit(1).execute().data) or []
    return rows[0] if rows else None


def _settings(user_id: str) -> dict:
    rows = (db.client.table("user_settings").select("*").eq("user_id", user_id)
            .limit(1).execute().data) or []
    return rows[0] if rows else {}


NoCount = tuple[int, Optional[str]]  # (how many times they said no, when last)


def _count(rows: list[dict], at: str) -> NoCount:
    times = sorted(str(r[at]) for r in rows if r.get(at))
    return len(rows), (times[-1] if times else None)


def _no_count_phase1(receipt_id: Optional[str], choice: str) -> NoCount:
    if not receipt_id:
        return 0, None
    rows = (db.client.table("processing_consent_choice_events").select("created_at")
            .eq("receipt_id", receipt_id).eq("choice", choice)
            .eq("event_kind", "withdraw").execute().data) or []
    return _count(rows, "created_at")


def _no_count_training(principal: str) -> NoCount:
    rows = (db.client.table("ml_consent_events").select("occurred_at")
            .eq("acquisition_principal_id", principal)
            .eq("event_kind", "withdraw").execute().data) or []
    return _count(rows, "occurred_at")


def _no_count_legacy(user_id: str, consent_type: str) -> NoCount:
    rows = (db.client.table("user_consent_events").select("set_at")
            .eq("user_id", user_id).eq("consent_type", f"{consent_type}_consent")
            .eq("consent_value", False).execute().data) or []
    return _count(rows, "set_at")


def _no(future) -> dict:
    count, last = future.result() or (0, None)
    return {"no_count": count, "last_no_at": last}


def _state(value: Optional[bool]) -> str:
    return "missing" if value is None else ("yes" if value else "no")


def consents(user_id: str, principal: Optional[str], settings: dict,
             receipt: Optional[dict]) -> list[dict]:
    """Every consent the app asks for: its state (yes / no / missing), when
    it was set, and how many times the person said no. The reads run side
    by side."""
    from services.processing_authorization import ProcessingAuthorizationService
    with ThreadPoolExecutor(max_workers=6) as pool:
        f_share_no = pool.submit(_safe, "share no", partial(_no_count_legacy, user_id, "share"))
        f_email_no = pool.submit(_safe, "email no", partial(_no_count_legacy, user_id, "email"))
        if principal:
            f_choices = pool.submit(_safe, "choices", partial(
                ProcessingAuthorizationService(db).consent_choices, principal))
            f_training = pool.submit(_safe, "training", partial(
                db.get_mlc2_training_consent_status, principal))
            f_training_no = pool.submit(_safe, "training no", partial(_no_count_training, principal))
            choices = f_choices.result() or {}
            rid = choices.get("receipt_id")
            f_phase1_no = {key: pool.submit(_safe, key, partial(_no_count_phase1, rid, key))
                           for key in ("personalised_practice", "sensitive_information")}

        out: list[dict] = []
        if principal:
            out.append({"key": "processing", "label": "Processing my recordings",
                        "state": "yes" if receipt else "missing",
                        "at": (receipt or {}).get("accepted_at"), "no_count": 0, "last_no_at": None})
            for key, label in (("personalised_practice", "Personalised practice"),
                               ("sensitive_information", "Sensitive information")):
                value = choices.get(key) if choices.get("has_receipt") else None
                out.append({"key": key, "label": label, "state": _state(value), "at": None,
                            **_no(f_phase1_no[key])})
            training = f_training.result() or {}
            withdrawn = bool(training.get("withdrawn"))
            out.append({"key": "training", "label": "Recordings help train the model",
                        "state": "yes" if training.get("active") else ("no" if withdrawn else "missing"),
                        "at": training.get("granted_at"), **_no(f_training_no)})
        for key, label, f_no in (("share", "Coach may share examples", f_share_no),
                                 ("email", "Email updates", f_email_no)):
            value = settings.get(f"{key}_consent_preference")
            if value is None:
                value = settings.get(f"{key}_consent")
            out.append({"key": key, "label": label, "state": _state(value),
                        "at": settings.get(f"{key}_consent_set_at"), **_no(f_no)})
    return out


def person(user_id: str) -> Optional[dict]:
    """The whole profile, or None when there is no such account."""
    from services import booking, person_asks, plan_promotions, token_account
    # SPEED: the reads don't depend on each other, so they run side by side
    # (one round trip's wait instead of ten in a row).
    with ThreadPoolExecutor(max_workers=8) as pool:
        f_user = pool.submit(auth_user, user_id)
        f_principal = pool.submit(_safe, "principal", partial(_principal, user_id))
        f_settings = pool.submit(_safe, "settings", partial(_settings, user_id))
        f_account = pool.submit(_safe, "tokens", partial(token_account.get_account, user_id))
        f_price = pool.submit(_safe, "lesson price", partial(booking.user_price, user_id))
        f_list = pool.submit(_safe, "list price", lambda: booking.get_settings()["price_cents"])
        f_asks = pool.submit(_safe, "asks", partial(person_asks.list_for, user_id))
        f_promo = pool.submit(_safe, "promotion", partial(plan_promotions.active, user_id))
        user = f_user.result()
        if not user:
            return None
        principal = f_principal.result()
        settings = f_settings.result() or {}
        receipt = _safe("receipt", partial(_receipt, principal)) if principal else None
        consent_rows = consents(user_id, principal, settings, receipt)
        account = f_account.result()
        deletion_row = _safe("deletion", partial(deletion, user_id, principal))
    meta = user.get("user_metadata") or {}
    name = meta.get("full_name") or meta.get("name") or meta.get("display_name")
    return {
        "user_id": user_id,
        "email": user.get("email"),
        "name": str(name).strip() if name else None,
        "created_at": user.get("created_at"),
        "last_sign_in_at": user.get("last_sign_in_at"),
        "country": (receipt or {}).get("country_of_residence"),
        "locale": (receipt or {}).get("locale"),
        "native_language": settings.get("profile_native_language"),
        "domain": settings.get("profile_domain"),
        "goal": settings.get("profile_goal"),
        "phone": meta.get("whatsapp_phone"),
        "home_screen_at": meta.get("home_screen_at"),
        "consents": consent_rows,
        "tokens": account and {
            "balance": account.get("balance"), "monthly": account.get("monthly_balance"),
            "bonus": account.get("bonus_balance"), "tier": account.get("tier"),
        },
        "lesson_price_cents": f_price.result(),
        "list_price_cents": f_list.result(),
        "asks": f_asks.result() or [],
        "promotion": f_promo.result(),
        "deletion": deletion_row,
    }


def deletion(user_id: str, principal: Optional[str]) -> Optional[dict]:
    """The account deletion that governs this person now, if any."""
    if not principal:
        return None
    from services.account_deletion import AccountDeletionService, deletion_view
    return deletion_view(AccountDeletionService(db).live_for_principal(principal))


def request_deletion(user_id: str, admin_id: str) -> dict:
    """The admin deletes this account (founder 2026-10-14). The same road as
    the person's own "Delete my account": processing stops now, the AI voice
    goes now, and everything else is purged after the seven-day window, in
    which the deletion can still be cancelled. An account that never agreed
    to processing holds no recordings, so its login is removed at once."""
    principal = _principal(user_id)
    if not principal:
        resp = httpx.delete(_auth_url(user_id), headers=_auth_headers(), timeout=10)
        resp.raise_for_status()
        logger.info("admin %s removed login without data user=%s", admin_id, user_id)
        return {"state": "done", "kind": "login_only"}
    from services.ai_voice_clone import erase_on_termination
    from services.processing_authorization import ProcessingAuthorizationService
    erase_on_termination(db, user_id, principal)
    from services.coach_answer_video import erase_for_user
    erase_for_user(user_id)
    from services.booking import erase_for_user as erase_bookings
    erase_bookings(user_id)
    row = ProcessingAuthorizationService(db).request_account_deletion(
        principal, idempotency_key=f"admin-delete:{user_id}", reason_code="ADMIN_DELETION")
    logger.info("admin %s requested account deletion user=%s", admin_id, user_id)
    return row


def cancel_deletion(user_id: str, request_id: str) -> dict:
    principal = _principal(user_id)
    if not principal:
        return {}
    from services.processing_authorization import ProcessingAuthorizationService
    return ProcessingAuthorizationService(db).cancel_account_deletion(principal, request_id)


def mark_home_screen(user_id: str) -> str:
    """Record, once, that this person opened the app from their home screen."""
    user = auth_user(user_id) or {}
    at = (user.get("user_metadata") or {}).get("home_screen_at")
    if not at:
        at = datetime.now(timezone.utc).isoformat()
        set_metadata(user_id, {"home_screen_at": at})
    from services import person_asks
    _safe("home-screen ask", partial(person_asks.answered, user_id, "home_screen"))
    return at
