"""Unit tests for services.lounge_messages (BE contract §3.15).

Covers the pure validation + page-shaping the two Lounge endpoints
lean on. The module is dependency-free (no services.db import), so no
stub is needed.

Run: python3 -m unittest test_lounge_messages
"""
from __future__ import annotations

import unittest
import uuid


def _cid() -> str:
    # Deterministic-enough UUIDs for tests (uuid4 banned in workflow
    # scripts, but fine in a plain unittest process).
    return str(uuid.uuid4())


class ValidateBatchTests(unittest.TestCase):

    def _v(self, body):
        from services.lounge_messages import validate_lounge_batch
        return validate_lounge_batch(body)

    def _msg(self, **over):
        base = {
            "client_id": _cid(),
            "role": "user",
            "kind": "text",
            "body": "hello",
            "client_created_at": "2026-06-01T12:00:00Z",
        }
        base.update(over)
        return base

    # ── Happy paths ────────────────────────────────────────────────

    def test_valid_single_message(self):
        out = self._v({"messages": [self._msg()]})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["role"], "user")
        self.assertEqual(out[0]["kind"], "text")

    def test_valid_batch_all_roles_and_kinds(self):
        msgs = [
            self._msg(role="user", kind="text"),
            self._msg(role="bot", kind="joke"),
            self._msg(role="system", kind="status",
                      metadata={"session_id": "s1"}),
            self._msg(role="bot", kind="recording_summary"),
            self._msg(role="system", kind="insight",
                      metadata={"insight_ref": "i1"}),
        ]
        out = self._v({"messages": msgs})
        self.assertEqual(len(out), 5)

    def test_best_presentation_ready_is_a_valid_kind(self):
        # server-inserted card kind (the DB CHECK is the real guard) — must be
        # in VALID_KINDS so the validate path doesn't reject it.
        from services.lounge_messages import VALID_KINDS
        self.assertIn("best_presentation_ready", VALID_KINDS)
        out = self._v({"messages": [
            self._msg(role="bot", kind="best_presentation_ready",
                      metadata={"arc_id": "a1", "topic": "Q3"})]})
        self.assertEqual(out[0]["kind"], "best_presentation_ready")

    def test_missing_body_defaults_to_empty_string(self):
        m = self._msg()
        del m["body"]
        out = self._v({"messages": [m]})
        self.assertEqual(out[0]["body"], "")

    def test_null_body_becomes_empty_string(self):
        out = self._v({"messages": [self._msg(body=None)]})
        self.assertEqual(out[0]["body"], "")

    def test_iso_with_offset_accepted(self):
        out = self._v({"messages": [
            self._msg(client_created_at="2026-06-01T12:00:00+02:00"),
        ]})
        self.assertEqual(len(out), 1)

    def test_metadata_object_preserved(self):
        out = self._v({"messages": [
            self._msg(kind="status", metadata={"session_id": "abc"}),
        ]})
        self.assertEqual(out[0]["metadata"], {"session_id": "abc"})

    # ── Rejections ─────────────────────────────────────────────────

    def test_non_dict_body_rejected(self):
        from services.lounge_messages import LoungeValidationError
        for bad in ["x", 42, [1], None]:
            with self.assertRaises(LoungeValidationError):
                self._v(bad)

    def test_empty_messages_rejected(self):
        from services.lounge_messages import LoungeValidationError
        with self.assertRaises(LoungeValidationError):
            self._v({"messages": []})
        with self.assertRaises(LoungeValidationError):
            self._v({"messages": "nope"})

    def test_batch_over_ceiling_rejected(self):
        from services.lounge_messages import (
            LoungeValidationError, MAX_BATCH,
        )
        msgs = [self._msg() for _ in range(MAX_BATCH + 1)]
        with self.assertRaises(LoungeValidationError) as cm:
            self._v({"messages": msgs})
        self.assertIn(str(MAX_BATCH), str(cm.exception))

    def test_batch_at_ceiling_accepted(self):
        from services.lounge_messages import MAX_BATCH
        msgs = [self._msg() for _ in range(MAX_BATCH)]
        out = self._v({"messages": msgs})
        self.assertEqual(len(out), MAX_BATCH)

    def test_non_uuid_client_id_rejected(self):
        from services.lounge_messages import LoungeValidationError
        with self.assertRaises(LoungeValidationError) as cm:
            self._v({"messages": [self._msg(client_id="not-a-uuid")]})
        self.assertIn("client_id", str(cm.exception))

    def test_bad_role_rejected(self):
        from services.lounge_messages import LoungeValidationError
        with self.assertRaises(LoungeValidationError) as cm:
            self._v({"messages": [self._msg(role="admin")]})
        self.assertIn("role", str(cm.exception))

    def test_bad_kind_rejected(self):
        from services.lounge_messages import LoungeValidationError
        with self.assertRaises(LoungeValidationError) as cm:
            self._v({"messages": [self._msg(kind="metrics")]})
        self.assertIn("kind", str(cm.exception))

    def test_missing_client_created_at_rejected(self):
        from services.lounge_messages import LoungeValidationError
        m = self._msg()
        del m["client_created_at"]
        with self.assertRaises(LoungeValidationError):
            self._v({"messages": [m]})

    def test_unparseable_client_created_at_rejected(self):
        from services.lounge_messages import LoungeValidationError
        with self.assertRaises(LoungeValidationError):
            self._v({"messages": [self._msg(client_created_at="yesterday")]})

    def test_body_over_cap_rejected(self):
        from services.lounge_messages import (
            LoungeValidationError, MAX_BODY_LEN,
        )
        with self.assertRaises(LoungeValidationError):
            self._v({"messages": [self._msg(body="x" * (MAX_BODY_LEN + 1))]})

    def test_non_object_metadata_rejected(self):
        from services.lounge_messages import LoungeValidationError
        with self.assertRaises(LoungeValidationError):
            self._v({"messages": [self._msg(metadata="oops")]})

    def test_error_message_indexes_the_bad_row(self):
        """A multi-row batch names which row failed."""
        from services.lounge_messages import LoungeValidationError
        msgs = [self._msg(), self._msg(role="bogus"), self._msg()]
        with self.assertRaises(LoungeValidationError) as cm:
            self._v({"messages": msgs})
        self.assertIn("[1]", str(cm.exception))


class ParseLimitTests(unittest.TestCase):

    def _p(self, raw):
        from services.lounge_messages import parse_limit
        return parse_limit(raw)

    def test_default_when_absent(self):
        from services.lounge_messages import DEFAULT_PAGE
        self.assertEqual(self._p(None), DEFAULT_PAGE)

    def test_clamps_to_max(self):
        from services.lounge_messages import MAX_PAGE
        self.assertEqual(self._p("99999"), MAX_PAGE)

    def test_floor_of_one(self):
        self.assertEqual(self._p("0"), 1)
        self.assertEqual(self._p("-5"), 1)

    def test_non_numeric_falls_back_to_default(self):
        from services.lounge_messages import DEFAULT_PAGE
        self.assertEqual(self._p("abc"), DEFAULT_PAGE)

    def test_valid_value_passthrough(self):
        self.assertEqual(self._p("25"), 25)


class BeforeCursorTests(unittest.TestCase):

    def _v(self, raw):
        from services.lounge_messages import validate_before_cursor
        return validate_before_cursor(raw)

    def test_none_is_none(self):
        self.assertIsNone(self._v(None))
        self.assertIsNone(self._v(""))
        self.assertIsNone(self._v("   "))

    def test_valid_iso_passthrough(self):
        self.assertEqual(
            self._v("2026-06-01T12:00:00Z"), "2026-06-01T12:00:00Z",
        )

    def test_bad_cursor_raises(self):
        from services.lounge_messages import LoungeValidationError
        with self.assertRaises(LoungeValidationError):
            self._v("not-a-timestamp")


class ShapePageTests(unittest.TestCase):
    """The DESC-fetch → ASC-page contract + has_more + oldest_cursor."""

    def _row(self, ts):
        return {"id": ts, "client_created_at": ts, "role": "user",
                "kind": "text", "body": ts}

    def _shape(self, rows_desc, limit):
        from services.lounge_messages import shape_lounge_page
        return shape_lounge_page(rows_desc, limit)

    def test_empty(self):
        out = self._shape([], 50)
        self.assertEqual(out["messages"], [])
        self.assertFalse(out["has_more"])
        self.assertIsNone(out["oldest_cursor"])

    def test_under_limit_no_more(self):
        # DB returns newest-first; fewer than limit → no older page.
        rows_desc = [self._row("t3"), self._row("t2"), self._row("t1")]
        out = self._shape(rows_desc, 50)
        self.assertFalse(out["has_more"])
        self.assertIsNone(out["oldest_cursor"])
        # Reversed to ASC for rendering.
        self.assertEqual(
            [m["client_created_at"] for m in out["messages"]],
            ["t1", "t2", "t3"],
        )

    def test_exactly_limit_plus_one_signals_more(self):
        # limit=2, DB returns 3 (limit+1) → has_more, trim to 2.
        rows_desc = [self._row("t3"), self._row("t2"), self._row("t1")]
        out = self._shape(rows_desc, 2)
        self.assertTrue(out["has_more"])
        # Page is the newest 2 (t3, t2), reversed to ASC → [t2, t3].
        self.assertEqual(
            [m["client_created_at"] for m in out["messages"]],
            ["t2", "t3"],
        )
        # oldest_cursor = oldest in the returned page = t2 (pass as
        # ?before= to fetch t1 and older).
        self.assertEqual(out["oldest_cursor"], "t2")

    def test_exactly_limit_no_more(self):
        # DB returns exactly limit (not limit+1) → no older page.
        rows_desc = [self._row("t2"), self._row("t1")]
        out = self._shape(rows_desc, 2)
        self.assertFalse(out["has_more"])
        self.assertIsNone(out["oldest_cursor"])
        self.assertEqual(
            [m["client_created_at"] for m in out["messages"]],
            ["t1", "t2"],
        )


if __name__ == "__main__":
    unittest.main()
