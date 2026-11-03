"""
STORY    As a person using the WillpowerLab iPhone app, I want a notification
         when my coach's feedback is in or someone in my chats writes, so that
         I come back at the right moment (N385, for N365 item 4).
OUTCOME
  O1  My iPhone's address is kept once, follows the account it was last
      given for, and is forgotten when I sign out; a malformed one is refused.
  O2  Without Apple's push key on the server, nothing is sent.
  O3  An app run from Xcode is reached on Apple's sandbox, which is then
      remembered; the push carries the title, the line and where to open.
  O4  An address Apple no longer knows is forgotten.
PROVES   O1 -> PushDevicesTest::test_a_phone_is_kept_once_and_follows_its_latest_account
         O2 -> PushDevicesTest::test_without_apples_key_nothing_is_sent
         O3 -> PushDevicesTest::test_an_app_run_from_xcode_is_reached_on_apples_sandbox
         O4 -> PushDevicesTest::test_an_address_apple_no_longer_knows_is_forgotten
WHY      Push in the iPhone app (founder 2026-11-03, N385); Apple's service is
         stood in for (services/push_devices.py).
"""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from services import push_devices
from tests.test_chats import _Store

ME = "11111111-1111-4111-8111-111111111111"
YOU = "22222222-2222-4222-8222-222222222222"
TOKEN = "ab" * 32


def _key() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()


class _Apple:
    """Apple's two push services: each host answers from ``answers``."""

    def __init__(self, answers):
        self.answers, self.sent = answers, []

    def post(self, url, json, headers):
        self.sent.append((url.split("/3/")[0], json, headers["apns-topic"]))
        status, reason = self.answers[url.split("/3/")[0]]
        return SimpleNamespace(status_code=status, json=lambda: {"reason": reason})


class PushDevicesTest(unittest.TestCase):
    def setUp(self):
        self.db = SimpleNamespace(client=_Store())
        env = {"APNS_KEY_ID": "KEY123", "APNS_TEAM_ID": "TEAM123", "APNS_AUTH_KEY": _key()}
        p = patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)

    def _rows(self):
        return self.db.client.tables.get("push_devices", [])

    def test_a_phone_is_kept_once_and_follows_its_latest_account(self):
        push_devices.save(self.db, ME, {"token": TOKEN.upper()})
        push_devices.save(self.db, ME, {"token": TOKEN})
        push_devices.save(self.db, YOU, {"token": TOKEN})
        self.assertEqual([(r["user_id"], r["token"]) for r in self._rows()], [(YOU, TOKEN)])
        for junk in ({"token": "not-a-token"}, {}, None):
            with self.assertRaises(push_devices.PushDeviceError):
                push_devices.save(self.db, ME, junk)
        push_devices.remove(self.db, YOU, {"token": TOKEN})
        self.assertEqual(self._rows(), [])

    def test_without_apples_key_nothing_is_sent(self):
        push_devices.save(self.db, ME, {"token": TOKEN})
        apple = _Apple({})
        with patch.dict(os.environ, {"APNS_AUTH_KEY": ""}):
            self.assertEqual(push_devices.push(self.db, ME, title=None, body="Hi", path="/chat",
                                               client=apple), 0)
        self.assertEqual(apple.sent, [])

    def test_an_app_run_from_xcode_is_reached_on_apples_sandbox(self):
        push_devices.save(self.db, ME, {"token": TOKEN})
        apple = _Apple({"https://api.push.apple.com": (400, "BadDeviceToken"),
                        "https://api.sandbox.push.apple.com": (200, "")})
        sent = push_devices.push(self.db, ME, title="Kasia", body="👍 It's good",
                                 path="/chat?with=t1", client=apple)
        self.assertEqual(sent, 1)
        self.assertEqual(self._rows()[0]["environment"], "sandbox")
        _, payload, topic = apple.sent[-1]
        self.assertEqual(topic, "com.willpowerlab.app")
        self.assertEqual(payload, {"aps": {"alert": {"title": "Kasia", "body": "👍 It's good"},
                                           "sound": "default"}, "path": "/chat?with=t1"})

    def test_an_address_apple_no_longer_knows_is_forgotten(self):
        push_devices.save(self.db, ME, {"token": TOKEN})
        apple = _Apple({"https://api.push.apple.com": (410, "Unregistered")})
        self.assertEqual(push_devices.push(self.db, ME, title=None, body="Hi", path="/chat",
                                           client=apple), 0)
        self.assertEqual(self._rows(), [])


if __name__ == "__main__":
    unittest.main()
