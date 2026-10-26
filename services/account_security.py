"""Email and password on Data & consent (WIL-95; founder 2026-10-26, N189).

What the card does, and the one log every change lands in:

  state               the email, whether the account has a password, and the
                      provider it signs in with when it has none
  change_email        checks the current password (an account with one),
                      refuses an address another account has, then sends a
                      one-time link to the new address and a notice to the
                      old one. Nothing changes until the link is opened.
  confirm_email       the link: the newest request only, unexpired; the
                      email changes, once (a second click is a no-op)
  change_password     checks the current password, sets the new one, signs
                      the person out on their other devices, sends a notice
  send_password_link  Forgot password? (a reset) or Set a password (an
                      account without one): Supabase's recovery link, in our
                      email, opening the live Set new password screen
  password_link_used  that screen saved a password: logged, and a notice for
                      a reset

Every request, change and wrong password is one row in
``account_security_events`` (migration 0493): the time, the IP address, the
device, the old and new email where one changed. Never a password, never a
token (only its SHA-256). Only the new address confirms an email change
(N189 item 2), so the confirmation is ours, not Supabase's double opt-in:
the backend sets the email itself when the link comes back.

The words of the emails are services/email_account_security.py.
"""
from __future__ import annotations

import hashlib
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional
from urllib.parse import quote

from services import email_account_security as mails

logger = logging.getLogger(__name__)

TABLE = "account_security_events"
LINK_HOURS = 24          # an email change link works this long
SET_FLOW_HOURS = 2       # a Set a password link used within this is a set
MIN_PASSWORD = 6         # the live forms' rule ("At least 6 characters")
MAX_PASSWORD = 72        # bcrypt reads no further; Supabase refuses longer
MAX_EMAIL = 320
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PROVIDER_NAMES = {"google": "Google", "linkedin_oidc": "LinkedIn", "linkedin": "LinkedIn"}


class AccountError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class Caller:
    """Who is asking, and from where (the log keeps both)."""
    user_id: str
    jwt: str = ""
    ip: Optional[str] = None
    user_agent: Optional[str] = None


class Ports:
    """Supabase Auth's admin API, the log table and the mailer. Tests pass an
    in-memory twin with the same methods."""

    def __init__(self, client_factory: Optional[Callable[[], Any]] = None,
                 table_client: Any = None,
                 sender: Optional[Callable[..., Any]] = None,
                 base_url: Optional[str] = None):
        from config import Config
        from services.db import db, new_client
        from services.email_service import send_email_resend
        self._new = client_factory or new_client
        self._db = table_client if table_client is not None else db.client
        self._send = sender or send_email_resend
        self.base_url = (base_url or Config.FRONTEND_URL
                         or "https://www.willpowerlab.com").rstrip("/")

    # -- Supabase Auth --------------------------------------------------------
    def get_user(self, user_id: str) -> dict[str, Any]:
        user = self._new().auth.admin.get_user_by_id(user_id).user
        meta = getattr(user, "app_metadata", None) or {}
        return {"email": str(getattr(user, "email", "") or ""),
                "providers": [str(p) for p in (meta.get("providers") or [])]}

    def has_password(self, user_id: str) -> bool:
        result = self._db.rpc("account_has_password_v1", {"p_user": user_id}).execute()
        return result.data is True

    def email_in_use(self, email: str, except_user: str) -> bool:
        result = self._db.rpc("account_email_in_use_v1", {
            "p_email": email, "p_except_user": except_user}).execute()
        return result.data is True

    def password_matches(self, email: str, password: str) -> bool:
        """Supabase's own password check, on a fresh client so no shared
        session changes (as routes/auth.py signs in). The session it opens is
        closed at once; only a refused password reads as False."""
        from gotrue.errors import AuthApiError
        client = self._new()
        try:
            session = client.auth.sign_in_with_password(
                {"email": email, "password": password}).session
        except AuthApiError as e:
            if getattr(e, "status", None) == 400:
                return False
            raise
        if session is None:
            return False
        try:
            client.auth.admin.sign_out(session.access_token, "local")
        except Exception as e:  # noqa: BLE001 -- the check stands; the session expires
            logger.warning("account security: check session not closed: %s", e)
        return True

    def update_user(self, user_id: str, attributes: dict[str, Any]) -> None:
        from gotrue.errors import AuthApiError
        try:
            self._new().auth.admin.update_user_by_id(user_id, attributes)
        except AuthApiError as e:
            if getattr(e, "code", None) == "email_exists" or "already" in str(e).lower():
                raise AccountError("EMAIL_TAKEN", "That email already has an account.", 409)
            raise

    def sign_out_others(self, jwt: str) -> None:
        self._new().auth.admin.sign_out(jwt, "others")

    def recovery_token_hash(self, email: str) -> str:
        result = self._new().auth.admin.generate_link({
            "type": "recovery", "email": email,
            "options": {"redirect_to": f"{self.base_url}/update-password"}})
        return str(result.properties.hashed_token)

    # -- the log ---------------------------------------------------------------
    def insert_event(self, row: dict[str, Any]) -> dict[str, Any]:
        result = self._db.table(TABLE).insert(row).execute()
        return (result.data or [row])[0]

    def latest_events(self, user_id: str, events: list[str], limit: int = 1) -> list[dict[str, Any]]:
        result = (self._db.table(TABLE).select("*").eq("user_id", user_id)
                  .in_("event", events).order("created_at", desc=True)
                  .limit(limit).execute())
        return list(result.data or [])

    def event_by_token(self, token_sha256: str) -> Optional[dict[str, Any]]:
        result = (self._db.table(TABLE).select("*")
                  .eq("token_sha256", token_sha256)
                  .eq("event", "email_change_requested").limit(1).execute())
        return (result.data or [None])[0]

    # -- the mailer ------------------------------------------------------------
    def send(self, to: str, mail: dict[str, Any]) -> bool:
        """True only when the email went (SEND_EMAILS off is not sent)."""
        rendered = mails.render(mail)
        try:
            result = self._send(to=to, subject=rendered["subject"],
                                html=rendered["html"], text=rendered["text"])
        except Exception as e:  # noqa: BLE001 -- the caller says it failed
            logger.warning("account security: email to %s not sent: %s", to, e)
            return False
        return not (isinstance(result, dict) and result.get("sent") is False)


# -- helpers --------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _clean_email(value: Any) -> str:
    return str(value or "").strip().lower()


def _valid_email(email: str) -> bool:
    return 0 < len(email) <= MAX_EMAIL and bool(_EMAIL.match(email))


def provider_name(providers: list[str]) -> Optional[str]:
    """The provider an account signs in with, as the card says it ("Google").
    None for an email account."""
    others = [p for p in providers if p and p != "email"]
    if not others:
        return None
    return PROVIDER_NAMES.get(others[0], others[0].replace("_", " ").title())


def _when(moment: datetime) -> str:
    """"26 October at 16:40 UTC"."""
    moment = moment.astimezone(timezone.utc)
    return f"{moment.day} {moment:%B} at {moment:%H:%M} UTC"


def _log(ports: Ports, user_id: str, event: str, caller: Optional[Caller] = None,
         **fields: Any) -> dict[str, Any]:
    row = {"user_id": user_id, "event": event,
           "ip": ((caller.ip or "")[:64] or None) if caller else None,
           "user_agent": ((caller.user_agent or "")[:512] or None) if caller else None}
    row.update({k: v for k, v in fields.items() if v is not None})
    return ports.insert_event(row)


def _log_quietly(ports: Ports, user_id: str, event: str, caller: Optional[Caller] = None,
                 **fields: Any) -> None:
    """A change that already happened is not undone by a log that failed;
    the failure goes to Sentry instead."""
    try:
        _log(ports, user_id, event, caller, **fields)
    except Exception as e:  # noqa: BLE001 -- reported, the change stands
        import sentry_sdk
        logger.error("account security: %s not logged for %s: %s", event, user_id, e)
        sentry_sdk.capture_exception(e)


def _check_password(ports: Ports, caller: Caller, email: str, password: Any,
                    while_doing: str) -> None:
    if not ports.password_matches(email, str(password or "")):
        _log_quietly(ports, caller.user_id, "password_check_failed", caller, source="settings")
        logger.info("account security: wrong password while %s", while_doing)
        raise AccountError("WRONG_PASSWORD", "That password isn’t right.")


# -- what the card does ------------------------------------------------------------

def state(ports: Ports, caller: Caller) -> dict[str, Any]:
    user = ports.get_user(caller.user_id)
    has_password = ports.has_password(caller.user_id)
    return {"email": user["email"], "has_password": has_password,
            "provider": None if has_password else provider_name(user["providers"])}


def change_email(ports: Ports, caller: Caller, new_email: Any,
                 current_password: Any = None) -> dict[str, Any]:
    to = _clean_email(new_email)
    if not _valid_email(to):
        raise AccountError("EMAIL_INVALID", "Enter an email address.")
    user = ports.get_user(caller.user_id)
    old = _clean_email(user["email"])
    if to == old:
        raise AccountError("EMAIL_SAME", "That is already your email.")
    if ports.has_password(caller.user_id):
        _check_password(ports, caller, old, current_password, "changing the email")
    if ports.email_in_use(to, caller.user_id):
        _log_quietly(ports, caller.user_id, "email_change_refused", caller,
                     old_email=old, new_email=to, source="settings")
        raise AccountError("EMAIL_TAKEN", "That email already has an account.", 409)
    token = secrets.token_urlsafe(32)
    # The row is the token's only record, so it is written before the link
    # leaves; a link without its row could never work.
    _log(ports, caller.user_id, "email_change_requested", caller,
         old_email=old, new_email=to, source="settings", token_sha256=_sha(token),
         expires_at=(_now() + timedelta(hours=LINK_HOURS)).isoformat())
    url = f"{ports.base_url}/auth/callback?type=email_change&token={quote(token)}"
    if not ports.send(to, mails.confirm_new(to=to, url=url)):
        raise AccountError("SEND_FAILED", "The email didn’t go.", 502)
    if old and not ports.send(old, mails.notice_old(to=to)):
        logger.warning("account security: notice to the old address not sent (%s)",
                       caller.user_id)
    return {"sent_to": to}


def _usable_request(ports: Ports, token: Any) -> dict[str, Any]:
    row = ports.event_by_token(_sha(str(token or ""))) if token else None
    if not row:
        raise AccountError("LINK_INVALID", "This link doesn’t work.", 410)
    expires = row.get("expires_at")
    if not expires or datetime.fromisoformat(str(expires)) <= _now():
        raise AccountError("LINK_INVALID", "This link doesn’t work.", 410)
    newest = ports.latest_events(str(row["user_id"]), ["email_change_requested"], 1)
    if not newest or str(newest[0].get("id")) != str(row.get("id")):
        raise AccountError("LINK_INVALID", "This link doesn’t work.", 410)
    return row


def confirm_email(ports: Ports, token: Any, ip: Optional[str] = None,
                  user_agent: Optional[str] = None) -> dict[str, Any]:
    row = _usable_request(ports, token)
    user_id, to = str(row["user_id"]), _clean_email(row["new_email"])
    current = _clean_email(ports.get_user(user_id)["email"])
    if current == to:
        return {"email": to}            # the link opened twice
    caller = Caller(user_id=user_id, ip=ip, user_agent=user_agent)
    if ports.email_in_use(to, user_id):
        _log_quietly(ports, user_id, "email_change_refused", caller,
                     old_email=current, new_email=to, source="link")
        raise AccountError("EMAIL_TAKEN", "That email already has an account.", 409)
    ports.update_user(user_id, {"email": to, "email_confirm": True})
    _log_quietly(ports, user_id, "email_changed", caller,
                 old_email=current, new_email=to, source="link")
    return {"email": to}


def change_password(ports: Ports, caller: Caller, current_password: Any,
                    new_password: Any) -> dict[str, Any]:
    new = str(new_password or "")
    if not ports.has_password(caller.user_id):
        raise AccountError("NO_PASSWORD", "This account has no password yet.", 409)
    if len(new) < MIN_PASSWORD:
        raise AccountError("PASSWORD_TOO_SHORT", "Password must be at least 6 characters.")
    if len(new.encode()) > MAX_PASSWORD:
        raise AccountError("PASSWORD_TOO_LONG", "That password is too long.")
    email = _clean_email(ports.get_user(caller.user_id)["email"])
    _check_password(ports, caller, email, current_password, "changing the password")
    ports.update_user(caller.user_id, {"password": new})
    try:
        ports.sign_out_others(caller.jwt)
    except Exception as e:  # noqa: BLE001 -- the password changed; reported
        import sentry_sdk
        logger.error("account security: other devices not signed out: %s", e)
        sentry_sdk.capture_exception(e)
    _log_quietly(ports, caller.user_id, "password_changed", caller, source="settings")
    if email and not ports.send(email, mails.password_changed(when=_when(_now()))):
        logger.warning("account security: password notice not sent (%s)", caller.user_id)
    return {"changed": True}


def send_password_link(ports: Ports, caller: Caller) -> dict[str, Any]:
    """Forgot password? for an account with a password, Set a password for
    one without: the same recovery link, a different email."""
    user = ports.get_user(caller.user_id)
    email = _clean_email(user["email"])
    if not email:
        raise AccountError("NO_EMAIL", "This account has no email.", 409)
    has_password = ports.has_password(caller.user_id)
    url = (f"{ports.base_url}/auth/callback?type=recovery&token_hash="
           f"{quote(ports.recovery_token_hash(email))}")
    provider = provider_name(user["providers"]) or "Google"
    mail = (mails.reset(url=url) if has_password
            else mails.set_password(provider=provider, url=url))
    if not ports.send(email, mail):
        raise AccountError("SEND_FAILED", "The email didn’t go.", 502)
    kind = "reset" if has_password else "set"
    _log_quietly(ports, caller.user_id,
                 "password_reset_requested" if has_password else "password_set_requested",
                 caller, source="settings")
    return {"sent_to": email, "kind": kind}


def password_link_used(ports: Ports, caller: Caller) -> dict[str, Any]:
    """Set new password saved a password with an emailed link. A Set a
    password link asked for in the last two hours makes it the first
    password; anything else is a change, and a change gets the notice."""
    asked = ports.latest_events(
        caller.user_id, ["password_reset_requested", "password_set_requested"], 1)
    first = bool(asked) and asked[0].get("event") == "password_set_requested" and (
        datetime.fromisoformat(str(asked[0].get("created_at")))
        > _now() - timedelta(hours=SET_FLOW_HOURS))
    event = "password_set" if first else "password_changed"
    _log_quietly(ports, caller.user_id, event, caller, source="link")
    if event == "password_changed":
        email = _clean_email(ports.get_user(caller.user_id)["email"])
        if email and not ports.send(email, mails.password_changed(when=_when(_now()))):
            logger.warning("account security: password notice not sent (%s)", caller.user_id)
    return {"event": event}
