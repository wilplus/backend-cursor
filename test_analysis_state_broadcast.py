"""The push half of the FE's push-first status transport (frontend-cursor
#232 / docs/BE-HANDOFF-analysis-state-push.md): every analysis_state flip
broadcasts a plumbing-state-only Supabase Realtime message, best-effort.

The handoff's three contracts, under test verbatim:
  1. Flip to each of processing/ready/failed → exactly ONE broadcast whose
     topic embeds the session UUID (the capability) and whose payload is
     plumbing state ONLY — never the readout, never scores (AC-9 split-sink).
  2. A broken/raising/slow notifier never breaks the pipeline:
     set_session_analysis_state still returns True and the write persists.
  3. A FAILED write broadcasts nothing — push must never announce a write
     that didn't land, or the FE's poll fallback and push would disagree.

Run: python3 -m unittest test_analysis_state_broadcast
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest import mock


# Stub heavy deps so services.db imports without a live client / sentry
# (same isolation pattern as test_db_session_status).
for _m in ("supabase", "sentry_sdk"):
    if _m not in sys.modules:
        sys.modules[_m] = types.ModuleType(_m)
sys.modules["supabase"].create_client = lambda *a, **k: None  # type: ignore[attr-defined]
sys.modules["supabase"].Client = object  # type: ignore[attr-defined]

try:
    from services import realtime_notify
    from services.db import DatabaseService
    _IMPORT_ERR = None
except Exception as e:  # pragma: no cover - env/bootstrap guard
    realtime_notify = None  # type: ignore[assignment]
    DatabaseService = None  # type: ignore[assignment]
    _IMPORT_ERR = e


class _Chain:
    """Minimal chainable fake capturing the PostgREST call shape."""

    def __init__(self, cap, fail=None):
        self.cap = cap
        self._fail = fail

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
        if self._fail is not None:
            raise self._fail
        return types.SimpleNamespace(data=[{"id": "sid"}])


@unittest.skipIf(realtime_notify is None, f"import failed: {_IMPORT_ERR}")
class BroadcastContractTests(unittest.TestCase):
    """broadcast_analysis_state — the wire contract the FE builds against."""

    def _post(self, **cfg):
        calls = []

        def fake_post(url, headers=None, json=None, timeout=None):
            calls.append({"url": url, "headers": headers,
                          "json": json, "timeout": timeout})

        patches = [mock.patch.object(realtime_notify.httpx, "post", fake_post)]
        for attr, value in cfg.items():
            patches.append(
                mock.patch.object(realtime_notify.config, attr, value))
        return calls, patches

    def test_contract_topic_event_and_plumbing_only_payload(self):
        calls, patches = self._post(
            SUPABASE_URL="https://proj.supabase.co/",
            SUPABASE_SERVICE_ROLE_KEY="sk-test",
        )
        with patches[0], patches[1], patches[2]:
            realtime_notify.broadcast_analysis_state("sid-uuid-1", "ready")
        self.assertEqual(len(calls), 1)
        call = calls[0]
        # Trailing slash on the configured URL must not double up.
        self.assertEqual(
            call["url"], "https://proj.supabase.co/realtime/v1/api/broadcast")
        self.assertEqual(call["headers"]["apikey"], "sk-test")
        self.assertEqual(call["headers"]["Authorization"], "Bearer sk-test")
        self.assertEqual(call["timeout"], 2.0)
        msgs = call["json"]["messages"]
        self.assertEqual(len(msgs), 1)
        # The channel NAME is the capability — same trust model as the guest
        # readout route.
        self.assertEqual(msgs[0]["topic"], "lab-session-sid-uuid-1")
        self.assertEqual(msgs[0]["event"], "analysis_state")
        self.assertFalse(msgs[0]["private"])
        # AC-9 split-sink: EXACTLY plumbing state, no readout, no scores.
        # A new key here is a contract change — FE ping + handoff update first.
        self.assertEqual(
            msgs[0]["payload"],
            {"session_id": "sid-uuid-1", "analysis_state": "ready"},
        )

    def test_never_raises_when_post_fails(self):
        with mock.patch.object(
            realtime_notify.httpx, "post",
            side_effect=RuntimeError("realtime down"),
        ), mock.patch.object(
            realtime_notify.config, "SUPABASE_URL", "https://x.supabase.co",
        ), mock.patch.object(
            realtime_notify.config, "SUPABASE_SERVICE_ROLE_KEY", "sk",
        ):
            realtime_notify.broadcast_analysis_state("sid", "failed")  # no raise

    def test_skips_quietly_without_config(self):
        calls, _ = [], None
        with mock.patch.object(
            realtime_notify.httpx, "post",
            lambda *a, **k: calls.append(1),
        ), mock.patch.object(
            realtime_notify.config, "SUPABASE_URL", "",
        ):
            realtime_notify.broadcast_analysis_state("sid", "ready")
        self.assertEqual(calls, [], "no config → no network attempt")


@unittest.skipIf(DatabaseService is None, f"services.db import failed: {_IMPORT_ERR}")
class DbFlipBroadcastTests(unittest.TestCase):
    """set_session_analysis_state — the ONE choke point every execution mode
    (daemon, RQ worker, recovery sweeps, training import) funnels through."""

    def _svc(self, cap, fail=None):
        # __new__ skips __init__ so no real Supabase client is built.
        svc = DatabaseService.__new__(DatabaseService)
        svc.client = _Chain(cap, fail=fail)
        return svc

    def test_every_state_broadcasts_once_after_the_write(self):
        for state in (
            "processing",
            "ready",
            "failed",
            "failed_ideal_text_unconfirmed",
        ):
            with mock.patch(
                "services.realtime_notify.broadcast_analysis_state"
            ) as bc:
                cap = {}
                out = self._svc(cap).set_session_analysis_state("sid-1", state)
                self.assertTrue(out)
                self.assertEqual(cap["table"], "v2_sessions")
                self.assertEqual(cap["eq"], [("id", "sid-1")])
                bc.assert_called_once_with("sid-1", state)

    def test_failed_write_broadcasts_nothing(self):
        with mock.patch(
            "services.realtime_notify.broadcast_analysis_state"
        ) as bc:
            cap = {}
            out = self._svc(cap, fail=Exception("boom")).\
                set_session_analysis_state("sid-1", "ready")
            self.assertFalse(out)
            bc.assert_not_called()

    def test_missing_column_path_broadcasts_nothing(self):
        # The migration-pending path (column absent) is a FAILED write.
        with mock.patch(
            "services.realtime_notify.broadcast_analysis_state"
        ) as bc:
            cap = {}
            out = self._svc(
                cap, fail=Exception("could not find the 'analysis_state' column"),
            ).set_session_analysis_state("sid-1", "ready")
            self.assertFalse(out)
            bc.assert_not_called()

    def test_raising_broadcast_never_breaks_the_flip(self):
        with mock.patch(
            "services.realtime_notify.broadcast_analysis_state",
            side_effect=RuntimeError("notifier exploded"),
        ):
            cap = {}
            out = self._svc(cap).set_session_analysis_state("sid-1", "ready")
            self.assertTrue(out, "a landed write must report True even if "
                                 "the best-effort notifier breaks")
            self.assertEqual(cap["update"], {"analysis_state": "ready"})

    def test_invalid_state_rejected_before_any_side_effect(self):
        with mock.patch(
            "services.realtime_notify.broadcast_analysis_state"
        ) as bc:
            cap = {}
            out = self._svc(cap).set_session_analysis_state("sid-1", "bogus")
            self.assertFalse(out)
            self.assertNotIn("update", cap)
            bc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
