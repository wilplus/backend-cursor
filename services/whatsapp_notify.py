"""WhatsApp: "the feedback from your coach is in" (founder 2026-10-12).

The speaker leaves a phone number in the Lounge's second footer offer (after
"Add to home screen"). Once the coach is done sharing (their word for a
Take, or their answers on moments), the speaker gets one WhatsApp message
beside the Lounge bubble (N171; when and to whom: ``coach_feedback_notice``).
It carries
no speaker content and no score (AC-9): only that feedback is in, and the
link to the app.

Storage is two columns on ``user_settings`` (0465), so the account-deletion
purge already takes the number with it.

Sent through Meta's WhatsApp Cloud API directly (no reseller). Sending is
off unless ``WHATSAPP_NOTIFICATIONS=true`` and the Meta variables are set
(config.py). It is always best-effort: a failed or skipped
message never fails the coach's save (LIVE LOOP).
"""
from __future__ import annotations

import hashlib
import hmac
import html
import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from urllib.parse import quote

import httpx

from config import Config

_log = logging.getLogger(__name__)

#: The message, as the founder worded it (2026-10-12).
COACH_FEEDBACK_IN = "The feedback from your coach is in!"

# E.164: a plus, a country code that does not start with 0, 8 to 15 digits.
_E164 = re.compile(r"^\+[1-9]\d{7,14}$")
_SEPARATORS = re.compile(r"[\s\-().]")
_GRAPH_URL = "https://graph.facebook.com/v21.0/{phone_number_id}/messages"
_TIMEOUT_SEC = 8.0


class WhatsAppRefusal(Exception):
    def __init__(self, message: str, code: str = "INVALID_INPUT", status: int = 422):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status

    @property
    def body(self) -> dict:
        return {"code": self.code, "error": self.message}


def normalize_phone(raw: Any) -> str:
    """The number in E.164 (+447700900123), or WhatsAppRefusal. Spaces,
    dashes, dots and brackets are dropped; a leading 00 counts as +."""
    text = _SEPARATORS.sub("", str(raw or "").strip())
    if text.startswith("00"):
        text = "+" + text[2:]
    if not _E164.match(text):
        raise WhatsAppRefusal(
            "Enter the number with its country code, for example +44 7700 900123.")
    return text


def _settings(database: Any):
    return database.client.table("user_settings")


def whatsapp_state(database: Any, user_id: str) -> dict:
    """GET: {"phone": str|None}. A read failure reads as no number."""
    try:
        res = (_settings(database).select("whatsapp_phone")
               .eq("user_id", str(user_id)).limit(1).execute())
        row = (res.data or [{}])[0] or {}
        return {"phone": row.get("whatsapp_phone") or None}
    except Exception as e:  # noqa: BLE001 -- the offer just shows again
        _log.warning("whatsapp state read failed user=%s: %s", user_id, e)
        return {"phone": None}


def save_phone(database: Any, user_id: str, body: Any) -> dict:
    """PUT {"phone": "..."}: validate and save, stamping the opt-in time."""
    fields = body if isinstance(body, dict) else {}
    phone = normalize_phone(fields.get("phone"))
    now = datetime.now(timezone.utc).isoformat()
    _settings(database).upsert({
        "user_id": str(user_id),
        "whatsapp_phone": phone,
        "whatsapp_opted_in_at": now,
        "updated_at": now,
    }, on_conflict="user_id").execute()
    # The Lounge's WhatsApp ask is answered; never let its bookkeeping
    # block the number itself.
    try:
        from services import person_asks
        person_asks.answered(str(user_id), "whatsapp")
    except Exception:  # noqa: BLE001 -- bookkeeping only
        _log.warning("whatsapp ask bookkeeping failed user=%s", user_id, exc_info=True)
    return {"phone": phone}


#: After a number is saved (founder 2026-10-15, approved in chat), word for
#: word as the Lounge's form says it (frontend WHATSAPP_COPY.saved).
SAVED = "Saved ✓ We'll message you on WhatsApp at {phone} when your coach's feedback is in."
#: A number typed in the chat waits for its code (N235): the WhatsApp
#: sign-up's words (N214 item 6), as the form's code step says them.
CHECK = "Enter the code we sent you on WhatsApp"

# A message that is only a phone number: digits with the usual separators.
_PHONE_LIKE = re.compile(r"^\+?[\d\s\-().]+$")


def _typed_number(question: str) -> bool:
    text = question.strip()
    return bool(_PHONE_LIKE.match(text)) and 7 <= sum(c.isdigit() for c in text) <= 15


def chat_turn(database: Any, user_id: Optional[str], question: str) -> Optional[dict]:
    """The chat's intercept (founder 2026-10-20): a number typed while the
    newest ask in the thread is the WhatsApp ask is the answer to it.
    Nothing is saved here: the number gets the messages and signs in only
    once its WhatsApp code is typed (founder 2026-10-28, N230, N235), so the
    form opens on the code step for it (``row_metadata`` "check" with the
    number; the app sends the code). Without its country code the form opens
    with it, with the same words it shows under the field. ``{"answer",
    "row_metadata", "offer"}``; None for any other turn."""
    if not user_id or not _typed_number(question or ""):
        return None
    from services.chat_app_context import newest_ask
    if newest_ask(database, user_id) != "whatsapp":
        return None
    try:
        phone = normalize_phone(question)
    except WhatsAppRefusal as refusal:
        return {"answer": refusal.message, "offer": "whatsapp",
                "row_metadata": {"whatsapp": "invalid"}}
    return {"answer": CHECK, "offer": "whatsapp",
            "row_metadata": {"whatsapp": "check", "phone": phone}}


#: The answer to STOP (founder, N265; signed, Never 4).
STOPPED = "Done. We've stopped the WhatsApp messages."
_STOP = re.compile(r"^\s*stop[\s.!]*$", re.IGNORECASE)
#: What a reply that is not text was, in the founder's email (N265 item 2).
_KINDS = {"image": "a photo", "audio": "a voice message", "video": "a video",
          "document": "a document", "sticker": "a sticker", "location": "a location",
          "contacts": "a contact card", "reaction": "a reaction"}


def signed_by_meta(secret: str, body: bytes, header: str) -> bool:
    """Meta signs every webhook delivery: X-Hub-Signature-256 is "sha256="
    and the HMAC-SHA256 of the raw body with the app's secret."""
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, (header or "").strip())


def _messages(payload: Any):
    entries = payload.get("entry") if isinstance(payload, dict) else None
    for entry in entries or []:
        for change in (entry or {}).get("changes") or []:
            for msg in ((change or {}).get("value") or {}).get("messages") or []:
                if isinstance(msg, dict):
                    yield msg


def _text_of(msg: dict) -> str:
    """A reply's words: a text's body, or a template button's label."""
    kind = msg.get("type")
    if kind == "text":
        return str((msg.get("text") or {}).get("body") or "")
    if kind == "button":
        return str((msg.get("button") or {}).get("text") or "")
    return ""


def handle_replies(database: Any, payload: Any, *, config: Any = None) -> dict:
    """Meta's webhook payload: each reply that says STOP turns the sender's
    WhatsApp messages off (N237); any other reply is emailed to the founder
    while WHATSAPP_FORWARD_REPLIES is on (N265), and is not read otherwise."""
    cfg = config or Config()
    out = {"stopped": 0, "forwarded": 0}
    for msg in _messages(payload):
        try:
            phone = normalize_phone("+" + str(msg.get("from") or "").lstrip("+"))
        except WhatsAppRefusal:
            continue
        if msg.get("type") == "text" and _STOP.match(_text_of(msg)):
            stop_messages(database, phone, config=cfg)
            out["stopped"] += 1
        elif cfg.WHATSAPP_FORWARD_REPLIES:
            forward_reply(database, phone, msg, config=cfg)
            out["forwarded"] += 1
    return out


def forward_reply(database: Any, phone: str, msg: dict, *, config: Any = None) -> None:
    """A reply other than STOP (N265 item 2, N171 item 6), emailed to the
    founder: the number, the admin page of each account at it, and the
    reply's words or what kind of message it was. Never raises: a 500 would
    make Meta send the whole delivery again, STOP's answer with it."""
    cfg = config or Config()
    e = html.escape
    try:
        from services.email_service import send_email_resend
        rows = (_settings(database).select("user_id").eq("whatsapp_phone", phone)
                .execute().data) or []
        base = (cfg.FRONTEND_URL or "").rstrip("/")
        pages = [f"{base}/admin/users/{quote(str(r['user_id']))}" for r in rows]
        words = _text_of(msg)
        kind = str(msg.get("type") or "")
        said = (f"<blockquote>{e(words).replace(chr(10), '<br>')}</blockquote>" if words
                else f"<p>It was {e(_KINDS.get(kind, f'a {kind} message'))}, so there are no words to show.</p>")
        who = ("".join(f'<p><a href="{e(u)}">{e(u)}</a></p>' for u in pages) if pages
               else "<p>No account gets WhatsApp messages at this number.</p>")
        send_email_resend(
            to=(cfg.ADMIN_EMAIL or "").strip(),
            subject=f"WhatsApp reply from {phone}",
            html=f"<p>A reply to our WhatsApp number from <strong>{e(phone)}</strong>:</p>{said}{who}",
        )
    except Exception as err:  # noqa: BLE001 -- STOP and the other replies go on
        _log.warning("whatsapp: a reply was not forwarded: %s", type(err).__name__)


def stop_messages(database: Any, phone: str, *, config: Any = None) -> None:
    """STOP from ``phone`` (N237): every account that gets WhatsApp messages
    at it stops, as Remove does (the number it signs in with stays, N235
    item 3); a booking that carries it forgets it (N233); then the signed
    answer (N265), which WhatsApp delivers within 24 hours of the person's
    message."""
    rows = (_settings(database).select("user_id").eq("whatsapp_phone", phone)
            .execute().data) or []
    for row in rows:
        remove_phone(database, str(row["user_id"]))
    database.client.table("bookings").update({"guest_whatsapp": None}) \
        .eq("guest_whatsapp", phone).execute()
    _log.info("whatsapp: STOP turned the messages off accounts=%d", len(rows))
    try:
        send_template(phone, template="", params=[], text=STOPPED, config=config)
    except Exception as e:  # noqa: BLE001 -- the messages are off either way
        _log.warning("whatsapp: STOP's answer failed: %s", type(e).__name__)


def remove_phone(database: Any, user_id: str) -> dict:
    """DELETE: no more WhatsApp messages."""
    (_settings(database)
     .update({"whatsapp_phone": None, "whatsapp_opted_in_at": None,
              "updated_at": datetime.now(timezone.utc).isoformat()})
     .eq("user_id", str(user_id)).execute())
    return {"phone": None}


def feedback_path(arc_id: Any = None, take_session_id: Any = None) -> str:
    """Where the message opens, after the site: the project's walk on the
    coach's feedback (`/chat?lens=<arc>`, the address the coach bubble opens;
    founder 2026-10-14: tap and go), or the chat when the project is unknown.

    THE LINK NAMES ITS TAKE (founder 2026-10-21, N77): `&take=<session_id>`
    is the Take the coach wrote on, so a word left on an earlier Take opens
    as that Take's word; a word shows on its own Take only."""
    arc = str(arc_id or "").strip()
    if not arc:
        return "chat"
    take = str(take_session_id or "").strip()
    path = f"chat?lens={quote(arc, safe='')}"
    return f"{path}&take={quote(take, safe='')}" if take else path


def _message_body(path: str = "chat") -> str:
    link = (Config.FRONTEND_URL or "").rstrip("/")
    return f"{COACH_FEEDBACK_IN}\n{link}/{path}" if link else COACH_FEEDBACK_IN


def _payload(to: str, cfg: Any, path: str = "chat") -> dict:
    """The approved template when one is named (what WhatsApp requires for a
    message the business starts); else the plain text, which WhatsApp only
    delivers within 24 hours of the person's last message to the number.

    A template's link lives in Meta's template. With
    WHATSAPP_TEMPLATE_LINK_BUTTON on, the template's first button must be a
    dynamic URL (`https://www.willpowerlab.com/{{1}}`) and `path` fills it,
    so the button opens the project's feedback; off, the template's own
    link is sent as Meta stores it."""
    base = {"messaging_product": "whatsapp", "to": to.lstrip("+")}
    if cfg.WHATSAPP_TEMPLATE_NAME:
        template: dict[str, Any] = {
            "name": cfg.WHATSAPP_TEMPLATE_NAME,
            "language": {"code": cfg.WHATSAPP_TEMPLATE_LANGUAGE or "en"}}
        # A template with an image header needs the image on every send (the
        # one uploaded with the template is only Meta's review sample).
        components: list[dict] = []
        image = (cfg.WHATSAPP_TEMPLATE_HEADER_IMAGE_URL or "").strip()
        if image:
            components.append({"type": "header", "parameters": [
                {"type": "image", "image": {"link": image}}]})
        if getattr(cfg, "WHATSAPP_TEMPLATE_LINK_BUTTON", False):
            components.append({"type": "button", "sub_type": "url", "index": "0",
                               "parameters": [{"type": "text", "text": path}]})
        if components:
            template["components"] = components
        return {**base, "type": "template", "template": template}
    return {**base, "type": "text", "text": {"body": _message_body(path)}}


def send_whatsapp(to: str, *, config: Any = None, path: str = "chat") -> bool:
    """One message through Meta's WhatsApp Cloud API. True when Meta accepted
    it; False when sending is off or not configured. Raises on a provider
    error."""
    cfg = config or Config()
    return _deliver(to, cfg, lambda number: _payload(number, cfg, path))


def send_template(to: str, *, template: str, params: list[str], text: str,
                  config: Any = None, button: Optional[str] = None) -> bool:
    """A message the business starts other than the coach's note (the
    booking's reminder, N144; the sign-in code, N214): the approved
    `template` with `params` as its body's {{1}}, {{2}}, ...; or `text` when
    no template is named, which WhatsApp only delivers within 24 hours of
    the person's last message. `button` fills the template's first button
    (an Authentication template's Copy code button carries the code). Same
    switch, number and redirect as send_whatsapp; raises on a provider
    error."""
    cfg = config or Config()

    def payload(number: str) -> dict:
        base = {"messaging_product": "whatsapp", "to": number.lstrip("+")}
        if not template:
            return {**base, "type": "text", "text": {"body": text}}
        components: list[dict] = [{"type": "body", "parameters": [
            {"type": "text", "text": p} for p in params]}]
        if button is not None:
            components.append({"type": "button", "sub_type": "url", "index": "0",
                               "parameters": [{"type": "text", "text": button}]})
        return {**base, "type": "template", "template": {
            "name": template,
            "language": {"code": cfg.WHATSAPP_TEMPLATE_LANGUAGE or "en"},
            "components": components}}

    return _deliver(to, cfg, payload)


def _deliver(to: str, cfg: Any, payload: Callable[[str], dict]) -> bool:
    if not cfg.WHATSAPP_NOTIFICATIONS:
        return False
    if not (cfg.WHATSAPP_ACCESS_TOKEN and cfg.WHATSAPP_PHONE_NUMBER_ID):
        _log.warning("whatsapp: WHATSAPP_NOTIFICATIONS is on but Meta is not configured")
        return False
    redirect = (cfg.WHATSAPP_REDIRECT_TO or "").strip()
    if redirect and not cfg.is_production:
        _log.info("whatsapp: redirecting a message to WHATSAPP_REDIRECT_TO (env=%s)", cfg.ENV)
        to = redirect
    body = payload(to)
    res = httpx.post(_GRAPH_URL.format(phone_number_id=cfg.WHATSAPP_PHONE_NUMBER_ID),
                     json=body,
                     headers={"Authorization": f"Bearer {cfg.WHATSAPP_ACCESS_TOKEN}"},
                     timeout=_TIMEOUT_SEC)
    if res.status_code >= 400:
        # Meta's own reason (code + message) so the Railway log says what to
        # fix; the request carried the token in a header, the reply never does.
        _log.warning("whatsapp: Meta refused the message status=%s error=%s",
                     res.status_code, _meta_error(res))
    res.raise_for_status()
    _log.info("whatsapp: Meta accepted the message template=%s",
              (body.get("template") or {}).get("name") or "(plain text)")
    return True


def _meta_error(res: Any) -> str:
    try:
        err = (res.json() or {}).get("error") or {}
        detail = (err.get("error_data") or {}).get("details") or ""
        return f"{err.get('code')} {err.get('message')} {detail}".strip()
    except Exception:  # noqa: BLE001 -- a log line, never a failure
        return (getattr(res, "text", "") or "")[:300]


def notify_coach_feedback_in(database: Any, user_id: Optional[str],
                             take_session_id: Optional[str] = None) -> bool:
    """The speaker's coach feedback is in: one WhatsApp message if they left
    a number, opening the Take's project on its feedback. Best-effort; never
    raises."""
    if not user_id or not Config.WHATSAPP_NOTIFICATIONS:
        return False
    try:
        phone = whatsapp_state(database, str(user_id)).get("phone")
        if not phone:
            _log.info("whatsapp: no number saved for user=%s, nothing sent", user_id)
            return False
        arc_id = None
        if take_session_id:
            session = database.v2_get_session_by_id(str(take_session_id)) or {}
            arc_id = session.get("arc_id")
        return send_whatsapp(str(phone), path=feedback_path(arc_id, take_session_id))
    except Exception as e:  # noqa: BLE001 -- the coach's save stands either way
        _log.warning("whatsapp coach-feedback message failed user=%s: %s",
                     user_id, type(e).__name__)
        return False

