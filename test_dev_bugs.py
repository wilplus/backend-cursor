"""dev-bugs collector — route + service tests (founder 2026-07-23).

Route-level tests mirror the test_suggestion_feedback harness: build a bare
Flask app, call the (un-decorated) handlers inside a test_request_context, and
patch collaborators. Service tests cover the digest builder, image-attachment
decoding, and the load-bearing invariant: bugs are marked `shipped` ONLY when
the email actually went out.

Run: python3 -m unittest test_dev_bugs
"""
from __future__ import annotations

import base64
import unittest
from unittest.mock import MagicMock, patch

try:
    from flask import Flask, request
    from routes import dev_bugs as rb
    from services import dev_bugs as svc
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    rb = None
    svc = None
    _IMPORT_ERROR = e

# 1x1 transparent PNG, base64 (as a data: URL the frontend would store).
_PNG_B64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4"
            "nGNgAAIAAAUAAen63NgAAAAASUVORK5CYII=")
_DATA_URL = f"data:image/png;base64,{_PNG_B64}"


def _unpack(out):
    resp, status = (out[0], out[1]) if isinstance(out, tuple) else (out, 200)
    if hasattr(resp, "get_json"):
        return resp.get_json(), status
    return resp, status


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class DevBugsRouteTests(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)

    def _call_collection(self, method="GET", body=None, key="secret"):
        headers = {"x-dev-key": key} if key is not None else {}
        with self.app.test_request_context(method=method, json=body, headers=headers):
            return _unpack(rb.dev_bugs_collection())

    # ---- key gate ----

    def test_disabled_when_no_key_configured(self):
        with patch.object(rb.config, "DEV_BUGS_KEY", ""):
            body, status = self._call_collection(key="whatever")
        self.assertEqual(status, 503)
        self.assertEqual(body["code"], "DISABLED")

    def test_missing_key_401(self):
        with patch.object(rb.config, "DEV_BUGS_KEY", "secret"):
            body, status = self._call_collection(key=None)
        self.assertEqual(status, 401)
        self.assertEqual(body["code"], "UNAUTHORIZED")

    def test_wrong_key_401(self):
        with patch.object(rb.config, "DEV_BUGS_KEY", "secret"):
            body, status = self._call_collection(key="nope")
        self.assertEqual(status, 401)

    # ---- GET / POST / DELETE / send ----

    def test_get_lists(self):
        canned = {"open": [{"id": 1, "text": "x", "image": None}], "shipped": []}
        with patch.object(rb.config, "DEV_BUGS_KEY", "secret"), \
             patch.object(rb.svc, "list_bugs", return_value=canned):
            body, status = self._call_collection(method="GET")
        self.assertEqual(status, 200)
        self.assertEqual(body, canned)

    def test_post_creates(self):
        with patch.object(rb.config, "DEV_BUGS_KEY", "secret"), \
             patch.object(rb.svc, "create_bug", return_value=42) as m:
            body, status = self._call_collection(
                method="POST", body={"text": "boom", "image": None})
        self.assertEqual(status, 201)
        self.assertEqual(body["id"], 42)
        m.assert_called_once_with("boom", None)

    def test_post_empty_400(self):
        with patch.object(rb.config, "DEV_BUGS_KEY", "secret"), \
             patch.object(rb.svc, "create_bug", side_effect=ValueError("empty")):
            body, status = self._call_collection(
                method="POST", body={"text": "  ", "image": None})
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "BAD_REQUEST")

    def test_delete_open(self):
        with patch.object(rb.config, "DEV_BUGS_KEY", "secret"), \
             patch.object(rb.svc, "delete_bug") as m:
            with self.app.test_request_context(
                    method="DELETE", headers={"x-dev-key": "secret"}):
                body, status = _unpack(rb.dev_bugs_delete(9))
        self.assertEqual(status, 204)
        m.assert_called_once_with(9)

    def test_send_ok(self):
        with patch.object(rb.config, "DEV_BUGS_KEY", "secret"), \
             patch.object(rb.svc, "send_open_bugs", return_value=3):
            with self.app.test_request_context(
                    method="POST", headers={"x-dev-key": "secret"}):
                body, status = _unpack(rb.dev_bugs_send())
        self.assertEqual(status, 200)
        self.assertEqual(body["sent"], 3)

    def test_send_email_not_sent_503(self):
        with patch.object(rb.config, "DEV_BUGS_KEY", "secret"), \
             patch.object(rb.svc, "send_open_bugs",
                          side_effect=RuntimeError("SEND_EMAILS off")):
            with self.app.test_request_context(
                    method="POST", headers={"x-dev-key": "secret"}):
                body, status = _unpack(rb.dev_bugs_send())
        self.assertEqual(status, 503)
        self.assertEqual(body["code"], "EMAIL_NOT_SENT")

    def test_edit_open_bug(self):
        with patch.object(rb.config, "DEV_BUGS_KEY", "secret"), \
             patch.object(rb.svc, "update_bug", return_value={"id": 9, "text": "fixed"}) as m:
            with self.app.test_request_context(
                    method="PATCH", json={"text": "fixed"}, headers={"x-dev-key": "secret"}):
                body, status = _unpack(rb.dev_bugs_edit(9))
        self.assertEqual(status, 200)
        self.assertEqual(body["bug"]["text"], "fixed")
        m.assert_called_once_with(9, text="fixed")

    def test_edit_missing_404(self):
        with patch.object(rb.config, "DEV_BUGS_KEY", "secret"), \
             patch.object(rb.svc, "update_bug", return_value=None):
            with self.app.test_request_context(
                    method="PATCH", json={"text": "x"}, headers={"x-dev-key": "secret"}):
                body, status = _unpack(rb.dev_bugs_edit(9))
        self.assertEqual(status, 404)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class DevBugsServiceTests(unittest.TestCase):

    def test_attachment_from_data_url(self):
        att = svc._attachment_for({"id": 5, "image_url": _DATA_URL})
        self.assertEqual(att["filename"], "bug-5.png")
        self.assertEqual(att["content_type"], "image/png")
        # content is a list of byte ints matching the decoded payload
        self.assertEqual(bytes(att["content"]), base64.b64decode(_PNG_B64))

    def test_update_bug_open_only_and_trims(self):
        client = MagicMock()
        client.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = \
            MagicMock(data=[{"id": 9, "text": "fixed", "image_url": None, "status": "open", "created_at": "t"}])
        with patch.object(svc.db, "client", client):
            out = svc.update_bug(9, text="  fixed  ")
        self.assertEqual(out["text"], "fixed")
        client.table.return_value.update.assert_called_once_with({"text": "fixed"})

    def test_update_bug_none_text_is_noop(self):
        client = MagicMock()
        with patch.object(svc.db, "client", client):
            self.assertIsNone(svc.update_bug(9, text=None))
        client.table.return_value.update.assert_not_called()

    def test_attachment_from_http_url(self):
        att = svc._attachment_for({"id": 6, "image_url": "https://x.test/a.jpg"})
        self.assertEqual(att, {"filename": "bug-6.jpg", "path": "https://x.test/a.jpg"})

    def test_attachment_none_and_garbage(self):
        self.assertIsNone(svc._attachment_for({"id": 7, "image_url": None}))
        self.assertIsNone(svc._attachment_for({"id": 8, "image_url": "notaurl"}))

    def test_build_body_has_context_and_lines(self):
        bugs = [
            {"id": 1, "text": "first bug", "image_url": None,
             "created_at": "2026-07-20T09:00:00+00:00"},
            {"id": 2, "text": "with shot", "image_url": _DATA_URL,
             "created_at": "2026-07-22T10:00:00+00:00"},
        ]
        body = svc._build_body(bugs)
        self.assertIn("product-backlog triage assistant", body)
        self.assertIn("=== BUGS (reported 20 Jul → 22 Jul) ===", body)
        self.assertIn("1. [20 Jul] first bug", body)
        self.assertIn("2. [22 Jul] with shot  (screenshot attached)", body)

    def test_send_empty_is_noop(self):
        client = _fake_client(open_rows=[])
        with patch.object(svc.db, "client", client), \
             patch.object(svc, "send_email_resend") as m_mail:
            n = svc.send_open_bugs()
        self.assertEqual(n, 0)
        m_mail.assert_not_called()

    def test_send_marks_shipped_only_when_sent(self):
        rows = [{"id": 11, "text": "a", "image_url": None,
                 "created_at": "2026-07-22T10:00:00+00:00"}]
        client = _fake_client(open_rows=rows)
        with patch.object(svc.db, "client", client), \
             patch.object(svc.config, "DEV_BUGS_TO", "artur@willonski.com"), \
             patch.object(svc, "send_email_resend",
                          return_value={"status": "sent", "sent": True}) as m_mail:
            n = svc.send_open_bugs()
        self.assertEqual(n, 1)
        m_mail.assert_called_once()
        # subject + recipient
        self.assertEqual(m_mail.call_args.kwargs["subject"], "dev-bugs")
        self.assertEqual(m_mail.call_args.kwargs["to"], "artur@willonski.com")
        # marked shipped
        client.table.return_value.update.assert_called_once_with(
            {"status": "shipped", "sent_at": "now()"})
        client.table.return_value.update.return_value.in_.assert_called_once_with("id", [11])

    def test_send_does_not_ship_when_not_sent(self):
        rows = [{"id": 12, "text": "b", "image_url": None,
                 "created_at": "2026-07-22T10:00:00+00:00"}]
        client = _fake_client(open_rows=rows)
        with patch.object(svc.db, "client", client), \
             patch.object(svc, "send_email_resend",
                          return_value={"status": "pending", "sent": False}):
            with self.assertRaises(RuntimeError):
                svc.send_open_bugs()
        client.table.return_value.update.assert_not_called()


def _fake_client(open_rows):
    """A MagicMock Supabase client whose select-chain .execute().data == open_rows."""
    client = MagicMock()
    exec_result = MagicMock()
    exec_result.data = open_rows
    # select(...).eq(...).order(...).execute()  AND  select(...).order(...).execute()
    tbl = client.table.return_value
    tbl.select.return_value.eq.return_value.order.return_value.execute.return_value = exec_result
    tbl.select.return_value.order.return_value.execute.return_value = exec_result
    return client


if __name__ == "__main__":
    unittest.main()
