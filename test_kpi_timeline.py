"""Unit tests for services.kpi_timeline (tester-soft-v1 / M1.1 raw).

Covers the shaping logic + summary derivation. The DB read is
mocked; we're checking the data-transformation contract that FE
will consume.

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
def setUpModule():
    stub = types.ModuleType("services.db")
    stub.db = MagicMock()
    sys.modules["services.db"] = stub


def tearDownModule():
    sys.modules.pop("services.db", None)


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
        self.assertEqual(out["summary"]["trend"], "insufficient_data")
        self.assertIsNone(out["summary"]["latest_kpi"])

    def test_single_session_renders_but_trend_insufficient(self):
        """A user with only one session can still see their score —
        but the trend label is honest about not having enough data."""
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
        self.assertAlmostEqual(out["series"][0]["kpi_score"], 0.42)
        self.assertEqual(out["summary"]["trend"], "insufficient_data")

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

    def test_rising_trend_detected(self):
        out = self._build([
            {"id": "s1", "created_at": "2026-01-01T10:00:00Z",
             "kpi_score": 0.30, "source": "interview"},
            {"id": "s2", "created_at": "2026-02-01T10:00:00Z",
             "kpi_score": 0.55, "source": "interview"},
        ])
        self.assertEqual(out["summary"]["trend"], "rising")
        self.assertAlmostEqual(
            out["summary"]["delta_first_to_last"], 0.25, places=2,
        )

    def test_falling_trend_detected(self):
        out = self._build([
            {"id": "s1", "created_at": "2026-01-01T10:00:00Z",
             "kpi_score": 0.70, "source": "interview"},
            {"id": "s2", "created_at": "2026-02-01T10:00:00Z",
             "kpi_score": 0.45, "source": "interview"},
        ])
        self.assertEqual(out["summary"]["trend"], "falling")

    def test_flat_trend_within_band(self):
        """A ±0.05 delta sits in the flat band per the v1 rule."""
        out = self._build([
            {"id": "s1", "created_at": "2026-01-01T10:00:00Z",
             "kpi_score": 0.50, "source": "interview"},
            {"id": "s2", "created_at": "2026-02-01T10:00:00Z",
             "kpi_score": 0.52, "source": "interview"},
        ])
        self.assertEqual(out["summary"]["trend"], "flat")

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
        """Raw metrics ride along on every row; missing values are
        None, not absent — FE consumes one stable shape."""
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
        """Defensive — if the DB ever returns a string in kpi_score
        (schema drift), the row is skipped rather than crashing the
        chart. Documents the guard."""
        out = self._build([
            {"id": "s1", "created_at": "2026-01-01T10:00:00Z",
             "kpi_score": "0.5", "source": "interview"},  # poisoned
            {"id": "s2", "created_at": "2026-02-01T10:00:00Z",
             "kpi_score": 0.6, "source": "interview"},
        ])
        # Only the well-typed row survives.
        self.assertEqual(len(out["series"]), 1)
        self.assertEqual(out["series"][0]["session_id"], "s2")

    def test_int_kpi_score_coerced_to_float(self):
        out = self._build([{
            "id": "s1", "created_at": "2026-01-01T10:00:00Z",
            "kpi_score": 1, "source": "interview",
        }])
        self.assertIsInstance(out["series"][0]["kpi_score"], float)
        self.assertEqual(out["series"][0]["kpi_score"], 1.0)


class FieldContractTests(unittest.TestCase):
    """Guard the field-name contract FE will consume. A typo in any
    of these would silently break the chart on the rollout."""

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
             "kpi_score", "raw_metrics", "source"},
        )

    def test_summary_keys(self):
        out = self._build([])
        self.assertEqual(
            set(out["summary"].keys()),
            {"sessions_count", "latest_kpi", "first_kpi",
             "delta_first_to_last", "trend"},
        )

    def test_no_smoothed_kpi_in_v1(self):
        """V1 ships RAW. The smoothed_kpi field is reserved for a
        follow-up but explicitly absent now; FE chart code MUST
        handle its absence (won't break when it shows up later)."""
        out = self._build([{
            "id": "s1", "created_at": "2026-01-01T10:00:00Z",
            "kpi_score": 0.5, "source": "interview",
        }])
        self.assertNotIn("smoothed_kpi", out["series"][0])


if __name__ == "__main__":
    unittest.main()
