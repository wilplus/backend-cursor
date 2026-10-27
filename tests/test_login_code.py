"""
STORY    As someone signing up or in with WhatsApp, I want my code to arrive
         on WhatsApp, and only when Supabase asked for it, so that my
         number is proven and nobody else can send codes in our name.
OUTCOME
  O1  A request signed with the hook's secret sends the code to the
      number with the login template, the code in its body and its Copy
      code button.
  O2  A request without Supabase's signature, signed with another secret
      or too old sends nothing (401); with no secret set the door is shut
      (503).
  O3  When WhatsApp sending is off the hook answers an error, so Supabase
      tells the person the code could not be sent.
  O4  A number being added in Settings gets its code at that number, which
      is not yet the account's.
PROVES   O1 -> test_a_signed_request_sends_the_code_on_whatsapp
         O2 -> test_an_unsigned_or_stale_request_sends_nothing
         O3 -> test_sending_off_answers_an_error
         O4 -> test_a_number_being_added_gets_the_code
WHY      Founder 2026-10-27, N214.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

from config import Config
from services import whatsapp_notify as wn

KEY = b"0123456789abcdef0123456789abcdef"
SECRET = "v1,whsec_" + base64.b64encode(KEY).decode()
BODY = {"user": {"id": "u1", "phone": "48600100200"}, "sms": {"otp": "482916"}}
DOOR = "/v2/internal/auth/send-sms"


def _signed(body: dict, *, key: bytes = KEY, stamp: int | None = None) -> tuple[bytes, dict]:
    raw = json.dumps(body).encode()
    stamp = int(time.time()) if stamp is None else stamp
    sig = base64.b64encode(hmac.new(key, f"msg_1.{stamp}.".encode() + raw, hashlib.sha256).digest()).decode()
    return raw, {"webhook-id": "msg_1", "webhook-timestamp": str(stamp),
                 "webhook-signature": f"v1,{sig}", "Content-Type": "application/json"}


@pytest.fixture()
def door():
    """The hook's door on a test app, WhatsApp on, each message Meta
    receives kept in `sent`."""
    from flask import Flask

    from routes.v2 import register_domains
    from routes.v2.blueprint import v2_bp

    register_domains()
    app = Flask(__name__)
    app.register_blueprint(v2_bp, url_prefix="/v2")
    sent: list[dict] = []

    def _post(url, json, headers, timeout):
        sent.append(json)
        return MagicMock(status_code=200)

    with ExitStack() as stack:
        for name, value in {"WHATSAPP_NOTIFICATIONS": True, "WHATSAPP_ACCESS_TOKEN": "tok",
                            "WHATSAPP_PHONE_NUMBER_ID": "1055", "WHATSAPP_TEMPLATE_LANGUAGE": "en",
                            "WHATSAPP_REDIRECT_TO": "", "WHATSAPP_LOGIN_TEMPLATE": "login_code",
                            "SEND_SMS_HOOK_SECRET": SECRET}.items():
            stack.enter_context(patch.object(Config, name, value, create=True))
        stack.enter_context(patch.object(wn.httpx, "post", _post))
        yield app.test_client(), sent


def test_a_signed_request_sends_the_code_on_whatsapp(door):
    client, sent = door
    raw, headers = _signed(BODY)
    res = client.post(DOOR, data=raw, headers=headers)
    assert res.status_code == 200
    assert len(sent) == 1 and sent[0]["to"] == "48600100200"
    template = sent[0]["template"]
    assert template["name"] == "login_code"
    assert template["components"] == [
        {"type": "body", "parameters": [{"type": "text", "text": "482916"}]},
        {"type": "button", "sub_type": "url", "index": "0",
         "parameters": [{"type": "text", "text": "482916"}]}]


def test_an_unsigned_or_stale_request_sends_nothing(door):
    client, sent = door
    raw, headers = _signed(BODY)
    assert client.post(DOOR, data=raw, headers={"Content-Type": "application/json"}).status_code == 401
    _, other = _signed(BODY, key=b"another-key-another-key-another!")
    assert client.post(DOOR, data=raw, headers=other).status_code == 401
    old_raw, old = _signed(BODY, stamp=int(time.time()) - 3600)
    assert client.post(DOOR, data=old_raw, headers=old).status_code == 401
    with patch.object(Config, "SEND_SMS_HOOK_SECRET", ""):
        assert client.post(DOOR, data=raw, headers=headers).status_code == 503
    assert sent == []


def test_sending_off_answers_an_error(door):
    client, sent = door
    raw, headers = _signed(BODY)
    with patch.object(Config, "WHATSAPP_NOTIFICATIONS", False):
        res = client.post(DOOR, data=raw, headers=headers)
    assert res.status_code == 503 and res.get_json()["error"]["http_code"] == 503
    assert sent == []


def test_a_number_being_added_gets_the_code(door):
    client, sent = door
    adding = {"user": {"id": "u2", "phone": "", "new_phone": "447700900123"},
              "sms": {"otp": "135790"}}
    named = {"user": {"id": "u3", "phone": "48600100200"},
             "sms": {"otp": "135790", "phone": "447700900999"}}
    for body in (adding, named):
        raw, headers = _signed(body)
        assert client.post(DOOR, data=raw, headers=headers).status_code == 200
    assert [m["to"] for m in sent] == ["447700900123", "447700900999"]
