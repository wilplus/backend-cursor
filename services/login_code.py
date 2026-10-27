"""The code that signs a speaker up or in with WhatsApp (founder 2026-10-27,
N214).

Supabase makes the code and checks it; its Send SMS hook hands the code to
this backend instead of an SMS provider (no Twilio), and we send it through
Meta's WhatsApp Cloud API with the Authentication template Meta approved
(WHATSAPP_LOGIN_TEMPLATE, "login_code"): Meta's own words, "{code} is your
verification code. For your security, do not share this code.", and a Copy
code button that carries the code.

Supabase signs every hook request the Standard Webhooks way (the
webhook-id, webhook-timestamp and webhook-signature headers, an HMAC-SHA256
over "{id}.{timestamp}.{body}"); a request that is not signed with
SEND_SMS_HOOK_SECRET sends nothing. The code itself is never logged.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import re
import time
from typing import Any, Mapping, Optional

from config import Config
from services import whatsapp_notify

logger = logging.getLogger(__name__)

#: How old a signed request may be, either way, in seconds.
TOLERANCE_SEC = 300
#: Meta's words for the code, sent only if no template is named.
TEXT = "{code} is your verification code. For your security, do not share this code."
_CODE = re.compile(r"^\d{4,10}$")


class HookRefusal(Exception):
    """A request we answer with an error; Supabase then tells the person
    the code could not be sent."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message

    @property
    def body(self) -> dict:
        return {"error": {"http_code": self.status, "message": self.message}}


def _key(secret: str) -> bytes:
    raw = secret.strip()
    for prefix in ("v1,", "whsec_"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
    try:
        return base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise HookRefusal(503, "SEND_SMS_HOOK_SECRET is not a Supabase hook secret")


def verify(secret: str, headers: Mapping[str, str], body: bytes,
           now: Optional[float] = None) -> dict:
    """The hook's JSON body when it carries a valid signature from Supabase;
    HookRefusal(401) otherwise."""
    msg_id = (headers.get("webhook-id") or "").strip()
    stamp = (headers.get("webhook-timestamp") or "").strip()
    signatures = (headers.get("webhook-signature") or "").strip()
    if not (msg_id and stamp and signatures):
        raise HookRefusal(401, "Missing signature")
    try:
        sent_at = int(stamp)
    except ValueError:
        raise HookRefusal(401, "Bad timestamp")
    if abs((now if now is not None else time.time()) - sent_at) > TOLERANCE_SEC:
        raise HookRefusal(401, "Stale request")
    signed = msg_id.encode() + b"." + stamp.encode() + b"." + body
    expected = base64.b64encode(hmac.new(_key(secret), signed, hashlib.sha256).digest()).decode()
    for part in signatures.split():
        version, _, signature = part.partition(",")
        if version == "v1" and hmac.compare_digest(signature, expected):
            try:
                payload = json.loads(body or b"{}")
            except ValueError:
                raise HookRefusal(400, "Body is not JSON")
            return payload if isinstance(payload, dict) else {}
    raise HookRefusal(401, "Bad signature")


def send(payload: dict, *, config: Any = None) -> None:
    """Send the hook's code to the hook's number on WhatsApp; HookRefusal
    when it cannot go."""
    cfg = config or Config()
    phone = str(((payload.get("user") or {}).get("phone")) or "").strip()
    code = str(((payload.get("sms") or {}).get("otp")) or "").strip()
    if not phone or not _CODE.match(code):
        raise HookRefusal(400, "No number or no code")
    to = phone if phone.startswith("+") else f"+{phone}"
    try:
        sent = whatsapp_notify.send_template(
            to, config=cfg, template=cfg.WHATSAPP_LOGIN_TEMPLATE, params=[code],
            button=code, text=TEXT.format(code=code))
    except Exception as error:  # noqa: BLE001 -- Meta's reason is logged by whatsapp_notify
        logger.warning("login code: WhatsApp refused the code to ...%s: %s",
                       to[-2:], type(error).__name__)
        raise HookRefusal(502, "WhatsApp did not take the message")
    if not sent:
        raise HookRefusal(503, "WhatsApp sending is off")
    logger.info("login code: sent on WhatsApp to ...%s", to[-2:])
