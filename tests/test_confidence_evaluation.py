"""Versioned release gate for the Confident Voice model."""
from __future__ import annotations

import unittest

from services import confidence_evaluation as evaluation


def _prob(prediction, confidence=0.8):
    other = (1.0 - confidence) / 2.0
    return {label: confidence if label == prediction else other
            for label in evaluation.CLASSES}


def _row(index, truth, prediction=None, **slices):
    prediction = prediction or truth
    return {
        "snippet_id": f"s{index}",
        "truth": truth,
        "prediction": prediction,
        "probabilities": _prob(prediction),
        **slices,
    }


def _plan(**overrides):
    plan = {
        "plan_id": "gate-1",
        "registered_at": "2026-08-25T12:00:00Z",
        "model_version": "confidence-model-v1",
        "dataset_release_id": "confidence-test-v1",
        "baseline_name": "majority-class-v1",
        "thresholds": {
            "min_macro_f1": 0.70,
            "min_recall": {"yes": 0.60, "in_between": 0.60, "no": 0.60},
            "max_mean_brier": 0.20,
            "min_macro_f1_over_baseline": 0.05,
            "max_slice_macro_f1_drop": 0.20,
            "min_test_n": 9,
            "min_slice_n": 6,
            "min_slice_class_n": 2,
        },
        "baseline": {"macro_f1": 0.45, "mean_brier": 0.25},
        "supported_slices": {"language": ["en", "pl"],
                             "device": ["phone"]},
    }
    plan.update(overrides)
    return plan


class PlanTests(unittest.TestCase):

    def test_thresholds_are_explicit_and_plan_is_hashed(self):
        plan = evaluation.register_plan(_plan())
        self.assertEqual(len(plan["plan_hash"]), 64)
        self.assertEqual(plan["policy_version"], evaluation.POLICY_VERSION)
        with self.assertRaisesRegex(evaluation.EvaluationError, "thresholds"):
            evaluation.register_plan(_plan(thresholds=None))

    def test_modifying_a_registered_threshold_is_detected(self):
        plan = evaluation.register_plan(_plan())
        plan["thresholds"]["min_macro_f1"] = 0.1
        with self.assertRaisesRegex(evaluation.EvaluationError, "modified"):
            evaluation.evaluate_release(
                [_row(1, "yes")], plan,
                dataset_release_id="confidence-test-v1",
            )

    def test_dataset_release_must_match_preregistration(self):
        with self.assertRaisesRegex(evaluation.EvaluationError,
                                    "registered release"):
            evaluation.evaluate_release(
                [_row(1, "yes")], evaluation.register_plan(_plan()),
                dataset_release_id="other-release",
            )


class MetricTests(unittest.TestCase):

    def test_perfect_three_class_model_has_perfect_macro_f1(self):
        metrics = evaluation.classification_metrics([
            _row(1, "yes"), _row(2, "in_between"), _row(3, "no"),
        ])
        self.assertEqual(metrics["macro_f1"], 1.0)
        self.assertEqual(metrics["by_class"]["in_between"]["recall"], 1.0)
        self.assertLess(metrics["mean_multiclass_brier"], 0.03)

    def test_probabilities_are_required_and_must_sum_to_one(self):
        row = _row(1, "yes")
        row["probabilities"] = {"yes": 0.9, "in_between": 0.9, "no": 0.0}
        with self.assertRaisesRegex(evaluation.EvaluationError, "sum to 1"):
            evaluation.classification_metrics([row])

    def test_missing_middle_class_is_visible_even_when_accuracy_is_high(self):
        rows = []
        for index in range(8):
            rows.append(_row(index, "yes" if index < 4 else "no"))
        rows.extend([
            _row(8, "in_between", "yes"),
            _row(9, "in_between", "no"),
        ])
        metrics = evaluation.classification_metrics(rows)
        self.assertEqual(metrics["accuracy"], 0.8)
        self.assertEqual(metrics["by_class"]["in_between"]["recall"], 0.0)
        self.assertLess(metrics["macro_f1"], metrics["accuracy"])


class ReleaseGateTests(unittest.TestCase):

    def _balanced_rows(self):
        rows = []
        index = 0
        for language in ("en", "pl"):
            for truth in evaluation.CLASSES:
                for _ in range(2):
                    rows.append(_row(index, truth, language=language,
                                     device="phone"))
                    index += 1
        return rows

    def test_good_model_passes_global_and_supported_slices(self):
        report = evaluation.evaluate_release(
            self._balanced_rows(), evaluation.register_plan(_plan()),
            dataset_release_id="confidence-test-v1",
        )
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["slices"]["language"]["pl"]["status"],
                         "passed")

    def test_middle_class_recall_failure_blocks_release(self):
        rows = self._balanced_rows()
        for row in rows:
            if row["truth"] == "in_between":
                row["prediction"] = "yes"
                row["probabilities"] = _prob("yes")
        report = evaluation.evaluate_release(
            rows, evaluation.register_plan(_plan()),
            dataset_release_id="confidence-test-v1",
        )
        self.assertEqual(report["status"], "failed")
        failed = {check["name"] for check in report["global_checks"]
                  if not check["passed"]}
        self.assertIn("recall.in_between", failed)

    def test_sparse_supported_slice_is_insufficient_not_passed(self):
        plan = _plan(supported_slices={"language": ["en", "de"]})
        report = evaluation.evaluate_release(
            self._balanced_rows(), evaluation.register_plan(plan),
            dataset_release_id="confidence-test-v1",
        )
        self.assertEqual(
            report["slices"]["language"]["de"]["status"],
            "insufficient_evidence",
        )
        self.assertEqual(report["status"], "passed")

    def test_evidenced_slice_regression_blocks_release(self):
        rows = self._balanced_rows()
        for row in rows:
            if row["language"] == "pl":
                row["prediction"] = "yes"
                row["probabilities"] = _prob("yes")
        plan = _plan(thresholds={
            **_plan()["thresholds"], "min_macro_f1": 0.30,
            "min_recall": {"yes": 0.30, "in_between": 0.30, "no": 0.30},
        })
        report = evaluation.evaluate_release(
            rows, evaluation.register_plan(plan),
            dataset_release_id="confidence-test-v1",
        )
        self.assertEqual(report["slices"]["language"]["pl"]["status"],
                         "failed")
        self.assertEqual(report["status"], "failed")

    def test_declared_baseline_is_a_real_gate(self):
        plan = _plan(baseline={"macro_f1": 0.98, "mean_brier": 0.02})
        report = evaluation.evaluate_release(
            self._balanced_rows(), evaluation.register_plan(plan),
            dataset_release_id="confidence-test-v1",
        )
        self.assertEqual(report["status"], "failed")
        failed = {check["name"] for check in report["global_checks"]
                  if not check["passed"]}
        self.assertIn("beats_declared_baseline", failed)

    def test_tiny_test_set_cannot_pass_on_perfect_scores(self):
        plan = _plan(supported_slices={"language": ["en"]})
        rows = [_row(index, truth, language="en", device="phone")
                for index, truth in enumerate(evaluation.CLASSES)]
        report = evaluation.evaluate_release(
            rows, evaluation.register_plan(plan),
            dataset_release_id="confidence-test-v1",
        )
        self.assertEqual(report["status"], "failed")
        failed = {check["name"] for check in report["global_checks"]
                  if not check["passed"]}
        self.assertIn("test_sample_size", failed)


if __name__ == "__main__":
    unittest.main()
