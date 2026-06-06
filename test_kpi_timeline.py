"""Unit tests for services.kpi_timeline (AC-9 split-sink compliant).

Covers the shaping logic + the AC-9 privacy guarantee. The DB read
is mocked; we check the data-transformation contract FE consumes.

AC-9 / split-sink wall (willab handoff §2, §5.1): KPI is PRIVATE-LANE
(coach-side, §5). This endpoint is the user's own timeline
(@require_auth), so it must NEVER serialize kpi_score or any
KPI-derived verdict (trend / latest_kpi / first_kpi / delta). The
user keeps their ACOUSTIC trajectory (wpm / fillers / stickiness —
user-facing per §3.3); the KPI is withheld. The DB rows still carry
kpi_score (it filters the series to scored sessions) but it is never
emitted. These tests guard that the KPI never leaks out.

Run: python3 -m unittest test_kpi_timeline
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch


# services.db pulls in supabase/postgrest, which aren't in the test
# image, so we stub it — in setUpModule, NOT at import time. A stub
# left in sys.modules at import time leaks into sibling test modules:
# test_homework_regressions decides at import time whether the real
# services.db is importable, and a leaked stub makes it run against
# the fake instead of skipping. tearDownModule restores the state.
_ORIG_SERVICES_DB = None


def setUpModule():
    global _ORIG_SERVICES_DB
    _ORIG_SERVICES_DB = sys.modules.get("services.db")
    stub = types.ModuleType("services.db")
    stub.db = MagicMock()
    sys.modules["services.db"] = stub


def tearDownModule():
    if _ORIG_SERVICES_DB is not None:
        sys.modules["services.db"] = _ORIG_SERVICES_DB
    else:
        sys.modules.pop("services.db", None)


# Private-lane keys that must NEVER appear in a user-facing payload.
_FORBIDDEN_SERIES_KEYS = {"kpi_score", "smoothed_kpi"}
_FORBIDDEN_SUMMARY_KEYS = {
    "latest_kpi", "first_kpi", "delta_first_to_last", "trend",
}


class SeriesShapeTests(unittest.TestCase):

    def _build(self, rows):
        from services import kpi_timeline as mod
        from services.db import db
        with patch.object(db, "get_user_kpi_timeline_rows", return_value=rows):
            return mod.build_user_kpi_timeline("uid-1")

    def test_empty_user_returns_empty_series(self):
        out = self._build([])
        self.assertEqual(out["series"], [])
        self.assertEqual(out["summary"]["sessions_count"], 0)

    def test_single_session_renders_acoustic_only(self):
        """A user with one session sees their acoustic row — but
        NOT a kpi_score (AC-9)."""
        out = self._build([{
            "id": "sid-1",
            "created_at": "2026-01-01T10:00:00Z",
            "kpi_score": 0.42,
            "global_wpm": 145,
            "global_fillers": 8,
            "stickiness_score": 0.6,
            "source": "interview",
        }])
        self.assertEqual(len(out["series"]), 1)
        self.assertEqual(out["series"][0]["session_number"], 1)
        self.assertNotIn("kpi_score", out["series"][0])

    def test_series_ordered_oldest_to_newest(self):
        """FE plots left-to-right so the BE owns the ordering. DB
        layer already orders ascending; this guards the contract."""
        out = self._build([
            {"id": "sid-1", "created_at": "2026-01-01T10:00:00Z",
             "kpi_score": 0.30, "source": "interview"},
            {"id": "sid-2", "created_at": "2026-02-01T10:00:00Z",
             "kpi_score": 0.50, "source": "interview"},
            {"id": "sid-3", "created_at": "2026-03-01T10:00:00Z",
             "kpi_score": 0.65, "source": "interview"},
        ])
        self.assertEqual(out["series"][0]["session_number"], 1)
        self.assertEqual(out["series"][1]["session_number"], 2)
        self.assertEqual(out["series"][2]["session_number"], 3)

    def test_missing_source_defaults_to_interview(self):
        """Pre-foundation-migration rows have no source column. The
        consumer contract is 'always present, defaults to interview'."""
        out = self._build([{
            "id": "s1", "created_at": "2026-01-01T10:00:00Z",
            "kpi_score": 0.42,
        }])
        self.assertEqual(out["series"][0]["source"], "interview")

    def test_audit_upload_source_preserved(self):
        out = self._build([{
            "id": "s1", "created_at": "2026-01-01T10:00:00Z",
            "kpi_score": 0.42,
            "source": "audit_upload",
        }])
        self.assertEqual(out["series"][0]["source"], "audit_upload")

    def test_raw_metrics_block_present_with_nulls(self):
        """Raw acoustic metrics ride along on every row; missing values
        are None, not absent — FE consumes one stable shape."""
        out = self._build([{
            "id": "s1", "created_at": "2026-01-01T10:00:00Z",
            "kpi_score": 0.5,
            # global_* missing entirely
        }])
        rm = out["series"][0]["raw_metrics"]
        self.assertIn("global_wpm", rm)
        self.assertIn("global_fillers", rm)
        self.assertIn("stickiness_score", rm)
        self.assertIsNone(rm["global_wpm"])

    def test_string_kpi_score_filtered(self):
        """Defensive — a string kpi_score (schema drift) skips the row
        rather than crashing. The kpi_score still gates inclusion even
        though it isn't emitted."""
        out = self._build([
            {"id": "s1", "created_at": "2026-01-01T10:00:00Z",
             "kpi_score": "0.5", "source": "interview"},  # poisoned
            {"id": "s2", "created_at": "2026-02-01T10:00:00Z",
             "kpi_score": 0.6, "source": "interview"},
        ])
        self.assertEqual(len(out["series"]), 1)
        self.assertEqual(out["series"][0]["session_id"], "s2")

    def test_int_kpi_score_row_included(self):
        """An int kpi_score is a valid score → the row passes the
        filter and appears (acoustic-only); kpi itself isn't emitted."""
        out = self._build([{
            "id": "s1", "created_at": "2026-01-01T10:00:00Z",
            "kpi_score": 1, "source": "interview",
        }])
        self.assertEqual(len(out["series"]), 1)
        self.assertNotIn("kpi_score", out["series"][0])


class AC9PrivacyGuardTests(unittest.TestCase):
    """The split-sink wall, asserted positively: no KPI value or
    KPI-derived verdict may appear in the user payload."""

    def _build(self, rows):
        from services import kpi_timeline as mod
        from services.db import db
        with patch.object(db, "get_user_kpi_timeline_rows", return_value=rows):
            return mod.build_user_kpi_timeline("uid-1")

    def test_no_kpi_in_series_rows(self):
        out = self._build([
            {"id": "s1", "created_at": "2026-01-01T10:00:00Z",
             "kpi_score": 0.30, "source": "interview"},
            {"id": "s2", "created_at": "2026-02-01T10:00:00Z",
             "kpi_score": 0.55, "source": "interview"},
        ])
        for row in out["series"]:
            leaked = _FORBIDDEN_SERIES_KEYS & set(row.keys())
            self.assertEqual(leaked, set(), f"KPI leaked into series: {leaked}")

    def test_no_kpi_verdict_in_summary(self):
        out = self._build([
            {"id": "s1", "created_at": "2026-01-01T10:00:00Z",
             "kpi_score": 0.30, "source": "interview"},
            {"id": "s2", "created_at": "2026-02-01T10:00:00Z",
             "kpi_score": 0.70, "source": "interview"},
        ])
        leaked = _FORBIDDEN_SUMMARY_KEYS & set(out["summary"].keys())
        self.assertEqual(leaked, set(), f"KPI verdict leaked: {leaked}")


class FieldContractTests(unittest.TestCase):
    """Guard the (AC-9-compliant) field-name contract FE consumes."""

    def _build(self, rows):
        from services import kpi_timeline as mod
        from services.db import db
        with patch.object(db, "get_user_kpi_timeline_rows", return_value=rows):
            return mod.build_user_kpi_timeline("uid-1")

    def test_top_level_keys(self):
        out = self._build([])
        self.assertEqual(set(out.keys()), {"series", "summary"})

    def test_series_row_keys(self):
        out = self._build([{
            "id": "s1", "created_at": "2026-01-01T10:00:00Z",
            "kpi_score": 0.5, "source": "interview",
        }])
        self.assertEqual(
            set(out["series"][0].keys()),
            {"session_id", "session_date", "session_number",
             "raw_metrics", "source"},
        )

    def test_summary_keys(self):
        out = self._build([])
        self.assertEqual(set(out["summary"].keys()), {"sessions_count"})


if __name__ == "__main__":
    unittest.main()
