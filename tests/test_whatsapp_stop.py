"""
STORY    As someone who gets our WhatsApp messages, I want to reply STOP and
         have them stop, so that I am never messaged again against my wish.
OUTCOME
  O1  Meta's check when the webhook is set is answered only with the right
      verify token; with either key unset the door is shut (503).
  O2  A delivery Meta did not sign changes nothing (401).
  O3  STOP turns the messages off for the account at that number and the
      booking that carries it, and answers with the signed words; other
      accounts and other replies are left as they were.
PROVES   O1 -> test_metas_check_needs_the_verify_token
         O2 -> test_an_unsigned_delivery_changes_nothing
         O3 -> test_stop_turns_the_messages_off
WHY      Founder 2026-10-28, N237.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

from config import Config
from services import whatsapp_notify as wn
from services.db import db

DOOR = "/v2/whatsapp/webhook"
SECRET = "app-secret"


class _Table:
    """Rows that filter by eq, so only the matching account changes."""

    def __init__(self, rows):
        self.rows, self._where, self._set = rows, {}, None

    def select(self, *_a):
        self._where, self._set = {}, None
        return self

    def update(self, values):
        self._where, self._set = {}, values
        return self

    def eq(self, column, value):
        self._where[column] = value
        return self

    def execute(self):
        hit = [r for r in self.rows if all(r.get(k) == v for k, v in self._where.items())]
        for r in hit if self._set else []:
            r.update(self._set)
        return MagicMock(data=hit)


def _reply(text, sender="447700900123"):
    return {"entry": [{"changes": [{"value": {"messages": [
        {"from": sender, "type": "text", "text": {"body": text}}]}}]}]}


def _signed(payload, secret=SECRET):
    raw = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {"X-Hub-Signature-256": sig, "Content-Type": "application/json"}


@pytest.fixture()
def door():
    """The webhook on a test app: two accounts, one booking, each message
    Meta receives kept in `sent`."""
    from flask import Flask

    from routes.v2 import register_domains
    from routes.v2.blueprint import v2_bp

    register_domains()
    app = Flask(__name__)
    app.register_blueprint(v2_bp, url_prefix="/v2")
    tables = {
        "user_settings": _Table([
            {"user_id": "u1", "whatsapp_phone": "+447700900123", "whatsapp_opted_in_at": "t"},
            {"user_id": "u2", "whatsapp_phone": "+48600100200", "whatsapp_opted_in_at": "t"}]),
        "bookings": _Table([{"id": "b1", "guest_whatsapp": "+447700900123"}]),
    }
    sent: list[dict] = []

    def _post(url, json, headers, timeout):
        sent.append(json)
        return MagicMock(status_code=200)

    with ExitStack() as stack:
        for name, value in {"WHATSAPP_NOTIFICATIONS": True, "WHATSAPP_ACCESS_TOKEN": "tok",
                            "WHATSAPP_PHONE_NUMBER_ID": "1055", "WHATSAPP_REDIRECT_TO": "",
                            "WHATSAPP_WEBHOOK_VERIFY_TOKEN": "verify-me",
                            "WHATSAPP_APP_SECRET": SECRET}.items():
            stack.enter_context(patch.object(Config, name, value, create=True))
        stack.enter_context(patch.object(wn.httpx, "post", _post))
        stack.enter_context(patch.object(db, "client", MagicMock(table=lambda n: tables[n])))
        yield app.test_client(), tables, sent


def test_metas_check_needs_the_verify_token(door):
    client, _, _ = door
    ok = client.get(DOOR + "?hub.mode=subscribe&hub.verify_token=verify-me&hub.challenge=42")
    assert ok.status_code == 200 and ok.get_data(as_text=True) == "42"
    assert client.get(DOOR + "?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=42").status_code == 403
    for key in ("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "WHATSAPP_APP_SECRET"):
        with patch.object(Config, key, ""):
            assert client.get(DOOR + "?hub.mode=subscribe&hub.verify_token=verify-me").status_code == 503
            raw, headers = _signed(_reply("STOP"))
            assert client.post(DOOR, data=raw, headers=headers).status_code == 503


def test_an_unsigned_delivery_changes_nothing(door):
    client, tables, sent = door
    raw, _ = _signed(_reply("STOP"))
    _, other = _signed(_reply("STOP"), secret="another-secret")
    assert client.post(DOOR, data=raw, headers={"Content-Type": "application/json"}).status_code == 401
    assert client.post(DOOR, data=raw, headers=other).status_code == 401
    assert tables["user_settings"].rows[0]["whatsapp_phone"] == "+447700900123"
    assert sent == []


def test_stop_turns_the_messages_off(door):
    client, tables, sent = door
    for text in ("thanks!", "stop sending me the reminder"):
        raw, headers = _signed(_reply(text))
        assert client.post(DOOR, data=raw, headers=headers).status_code == 200
    assert tables["user_settings"].rows[0]["whatsapp_phone"] == "+447700900123" and sent == []

    raw, headers = _signed(_reply(" Stop. "))
    assert client.post(DOOR, data=raw, headers=headers).status_code == 200
    me, other = tables["user_settings"].rows
    assert me["whatsapp_phone"] is None and me["whatsapp_opted_in_at"] is None
    assert other["whatsapp_phone"] == "+48600100200"
    assert tables["bookings"].rows[0]["guest_whatsapp"] is None
    assert sent == [{"messaging_product": "whatsapp", "to": "447700900123",
                     "type": "text", "text": {"body": wn.STOPPED}}]
