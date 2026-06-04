"""Regression: v2_update_session_status_unscoped must write status ONLY.

History (willab beta smoke test, 2026-06-04): the method wrote
``{"status": ..., "updated_at": ...}`` but ``v2_sessions`` has NO
``updated_at`` column (confirmed against the live schema). PostgREST
rejected the ENTIRE update (PGRST204 "could not find the 'updated_at'
column"), so the status flip silently never landed. Both callers swallow
it in try/except:
  * services.lab_send.send_lab_recording_to_coach (willab merge→send) —
    sessions never reached the coach queue and history showed
    'readout_ready' instead of 'review_pending'.
  * services.session_publish finalize (old-funnel publish flip).

This guards the payload so a stray ``updated_at`` (or any phantom column)
can't creep back in.

Run: python3 -m unittest test_db_session_status
"""
from __future__ import annotations

import sys
import types
import unittest


# Stub heavy deps so services.db imports without a live client / sentry.
for _m in ("supabase", "sentry_sdk"):
    if _m not in sys.modules:
        sys.modules[_m] = types.ModuleType(_m)
sys.modules["supabase"].create_client = lambda *a, **k: None  # type: ignore[attr-defined]
sys.modules["supabase"].Client = object  # type: ignore[attr-defined]

try:
    from services.db import DatabaseService
    _IMPORT_ERR = None
except Exception as e:  # pragma: no cover - env/bootstrap guard
    DatabaseService = None  # type: ignore[assignment]
    _IMPORT_ERR = e


class _Chain:
    """Minimal chainable fake capturing the PostgREST call shape."""

    def __init__(self, cap, rows):
        self.cap = cap
        self._rows = rows

    def table(self, name):
        self.cap["table"] = name
        return self

    def update(self, payload):
        self.cap["update"] = dict(payload)
        return self

    def eq(self, col, val):
        self.cap.setdefault("eq", []).append((col, val))
        return self

    def execute(self):
        return types.SimpleNamespace(data=self._rows)


@unittest.skipIf(DatabaseService is None, f"services.db import failed: {_IMPORT_ERR}")
class V2UpdateSessionStatusUnscopedTests(unittest.TestCase):

    def _svc(self, cap, rows):
        # __new__ skips __init__ so no real Supabase client is built.
        svc = DatabaseService.__new__(DatabaseService)
        svc.client = _Chain(cap, rows)
        return svc

    def test_payload_is_status_only(self):
        cap = {}
        svc = self._svc(cap, [{"id": "sid-123", "status": "pending_admin_review"}])
        out = svc.v2_update_session_status_unscoped("sid-123", "pending_admin_review")
        self.assertEqual(cap["table"], "v2_sessions")
        self.assertEqual(
            cap["update"], {"status": "pending_admin_review"},
            "v2_sessions has no updated_at column — writing it makes "
            "PostgREST reject the whole update (PGRST204).",
        )
        self.assertNotIn("updated_at", cap["update"])
        self.assertEqual(cap["eq"], [("id", "sid-123")])
        self.assertEqual(out, {"id": "sid-123", "status": "pending_admin_review"})

    def test_returns_none_when_no_row(self):
        cap = {}
        svc = self._svc(cap, [])
        self.assertIsNone(
            svc.v2_update_session_status_unscoped("missing", "pending_admin_review")
        )


if __name__ == "__main__":
    unittest.main()
