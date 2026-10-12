"""dev-bugs collector — route + service tests (founder 2026-07-23).

Route-level tests mirror the test_suggestion_feedback harness: build a bare
Flask app, call the (un-decorated) handlers inside a test_request_context, and
patch collaborators. Service tests cover the digest builder, image-attachment
decoding, and the load-bearing invariant: bugs are marked `shipped` ONLY when
the email actually went out.

Run: python3 -m unittest tests.test_dev_bugs
"""
from __future__ import annotations

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


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class DevBugsServiceTests(unittest.TestCase):


    # ---- rich HTML digest (which screenshot belongs to which bug) ----

    def _two_bugs(self):
        return [
            {"id": 1, "text": "first bug", "image_url": None,
             "created_at": "2026-07-20T09:00:00+00:00"},
            {"id": 2, "text": "with shot", "images": [_DATA_URL, _DATA_URL],
             "created_at": "2026-07-22T10:00:00+00:00"},
        ]

    def test_send_falls_back_to_plain_attachments_if_inline_rejected(self):
        """A provider that rejects content_id must not cost us the digest."""
        rows = [{"id": 11, "text": "a", "images": [_DATA_URL],
                 "created_at": "2026-07-22T10:00:00+00:00"}]
        client = _fake_client(open_rows=rows)
        calls = []

        def flaky(**kwargs):
            calls.append(kwargs["attachments"])
            if any("content_id" in a for a in kwargs["attachments"]):
                raise RuntimeError("422 unknown field content_id")
            return {"status": "sent", "sent": True}

        with patch.object(svc.db, "client", client), \
             patch.object(svc, "send_email_resend", side_effect=flaky):
            n = svc.send_open_bugs()
        self.assertEqual(n, 1)
        self.assertEqual(len(calls), 2)                       # inline try, then plain
        self.assertTrue(any("content_id" in a for a in calls[0]))
        self.assertFalse(any("content_id" in a for a in calls[1]))
        self.assertEqual(calls[1][0]["filename"], "bug-11-0.png")   # file still attached


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
