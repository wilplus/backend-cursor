"""Snippet-labels export (willab Phase 4 / Prompt 1, B1).

Pure build_export_rows — no DB. Covers the join, class balance, and the §7
integrity drop (labels whose snippet lacks a complete 11-feature vector).

Run: python3 -m unittest test_learning_export
"""
from __future__ import annotations

import unittest

from services.learning_export import build_export_rows, FEATURES_11


def _full_metrics(**over):
    m = {k: 1.0 for k in FEATURES_11}
    m.update(over)
    return m


class BuildExportRowsTests(unittest.TestCase):
    def test_joins_label_with_features(self):
        labels = [{
            "snippet_id": "s1", "session_id": "sess1", "value": "challenge",
            "schema_version": "direction-v1", "was_pre_filled": False,
            "was_overridden": True, "labeled_at": "2026-06-01T00:00:00Z",
        }]
        rows, summary = build_export_rows(labels, {"s1": _full_metrics()})
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["label"], "challenge")
        self.assertEqual(set(r["features"]), set(FEATURES_11))
        self.assertTrue(r["was_overridden"])
        self.assertEqual(r["selection_source"], "heuristic")  # default
        self.assertEqual(summary["by_class"], {"challenge": 1})
        self.assertEqual(summary["dropped_no_features"], 0)

    def test_class_balance(self):
        labels = [
            {"snippet_id": f"s{i}", "value": v, "session_id": "x"}
            for i, v in enumerate(
                ["threat", "threat", "ambiguous", "challenge", "challenge", "challenge"]
            )
        ]
        metrics = {f"s{i}": _full_metrics() for i in range(len(labels))}
        _rows, summary = build_export_rows(labels, metrics)
        self.assertEqual(summary["by_class"],
                         {"threat": 2, "ambiguous": 1, "challenge": 3})
        self.assertEqual(summary["total"], 6)

    def test_drops_label_with_no_metrics(self):
        labels = [{"snippet_id": "s1", "value": "threat"}]
        rows, summary = build_export_rows(labels, {})  # no metrics for s1
        self.assertEqual(rows, [])
        self.assertEqual(summary["dropped_no_features"], 1)

    def test_drops_label_with_incomplete_features(self):
        partial = {"f0_mean": 180.0, "wpm": 120.0}  # only 2 of 11
        labels = [{"snippet_id": "s1", "value": "threat"}]
        rows, summary = build_export_rows(labels, {"s1": partial})
        self.assertEqual(rows, [])
        self.assertEqual(summary["dropped_no_features"], 1)

    def test_drops_label_missing_value_or_snippet(self):
        labels = [
            {"snippet_id": "s1"},               # no value
            {"value": "threat"},                 # no snippet_id
        ]
        rows, summary = build_export_rows(labels, {"s1": _full_metrics()})
        self.assertEqual(rows, [])
        self.assertEqual(summary["dropped_no_features"], 2)

    def test_bool_is_not_a_feature_value(self):
        # a stray boolean in metrics must not count as a numeric feature
        m = _full_metrics(f0_mean=True)
        labels = [{"snippet_id": "s1", "value": "threat"}]
        rows, summary = build_export_rows(labels, {"s1": m})
        self.assertEqual(rows, [])  # f0_mean=True → incomplete → dropped
        self.assertEqual(summary["dropped_no_features"], 1)

    def test_empty_input(self):
        rows, summary = build_export_rows([], {})
        self.assertEqual(rows, [])
        self.assertEqual(summary["total"], 0)
        self.assertEqual(summary["by_class"], {})


class SyntheticExclusionTests(unittest.TestCase):
    # Subsystem-S wall: synthetic snippets are HARD-EXCLUDED from the coach-truth
    # corpus so generated data can never contaminate it (or a downstream holdout).
    def _labels(self):
        return [
            {"snippet_id": "real1", "value": "challenge", "session_id": "x"},
            {"snippet_id": "synth1", "value": "challenge", "session_id": "x"},
            {"snippet_id": "real2", "value": "threat", "session_id": "x"},
        ]

    def _metrics(self):
        return {k: _full_metrics() for k in ("real1", "synth1", "real2")}

    def test_no_origin_map_keeps_everything(self):
        # Backward-compatible default: no exclusion until provenance is populated.
        rows, summary = build_export_rows(self._labels(), self._metrics())
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["dropped_synthetic"], 0)

    def test_synthetic_is_excluded(self):
        rows, summary = build_export_rows(
            self._labels(), self._metrics(),
            {"real1": "real", "synth1": "synthetic", "real2": None},
        )
        ids = {r["snippet_id"] for r in rows}
        self.assertEqual(ids, {"real1", "real2"})       # synth1 gone
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["dropped_synthetic"], 1)
        self.assertEqual(summary["by_class"], {"challenge": 1, "threat": 1})

    def test_null_and_real_origins_both_kept(self):
        rows, _ = build_export_rows(
            [{"snippet_id": "a", "value": "challenge", "session_id": "x"}],
            {"a": _full_metrics()}, {"a": None},
        )
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
