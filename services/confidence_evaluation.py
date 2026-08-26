"""Pre-registered release evidence for the Confident Voice classifier.

This module answers one internal question: may a candidate model influence
production?  It never trains a model and never serves a user.  Evaluation is
allowed only against a hashed plan that names the frozen speaker-disjoint
dataset release, thresholds, baseline, and supported slices before results are
opened.  There are deliberately no default thresholds: inventing them after
seeing the test set is test-set tuning with paperwork around it.

Primary metric: macro-F1 over yes / in_between / no.  Each class therefore has
equal weight even when the corpus is imbalanced.  Per-class recall catches a
model that abandons the middle class.  Mean multiclass Brier score measures
probability calibration (mean squared error over the three class
probabilities; lower is better).  Supported slices are gated only when their
declared sample floors are met; sparse slices report insufficient evidence and
cannot be advertised as passed.

Pure: no DB, filesystem, network, model call, or user-facing serialization.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


CLASSES = ("yes", "in_between", "no")
SLICE_DIMENSIONS = ("language", "device", "source", "sex")
SCHEMA_VERSION = 1
POLICY_VERSION = "confidence-release-gate-v1"


class EvaluationError(ValueError):
    """Evaluation cannot prove the registered release claim."""


def _number(value: Any, name: str, *, minimum: float = 0.0,
            maximum: float = 1.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluationError(f"{name} must be numeric")
    out = float(value)
    if not minimum <= out <= maximum:
        raise EvaluationError(f"{name} must be between {minimum} and {maximum}")
    return out


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EvaluationError(f"{name} must be a positive integer")
    return value


def _canonical_plan(plan: Any) -> dict:
    if not isinstance(plan, dict):
        raise EvaluationError("plan must be an object")
    required_text = ("plan_id", "registered_at", "model_version",
                     "dataset_release_id", "baseline_name")
    out: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
    }
    for field in required_text:
        value = plan.get(field)
        if not isinstance(value, str) or not value.strip():
            raise EvaluationError(f"{field} is required")
        out[field] = value.strip()

    thresholds = plan.get("thresholds")
    if not isinstance(thresholds, dict):
        raise EvaluationError("thresholds are required; there are no defaults")
    recall = thresholds.get("min_recall")
    if not isinstance(recall, dict) or set(recall) != set(CLASSES):
        raise EvaluationError("min_recall must declare all three classes")
    out["thresholds"] = {
        "min_macro_f1": _number(
            thresholds.get("min_macro_f1"), "min_macro_f1"),
        "min_recall": {
            label: _number(recall.get(label), f"min_recall.{label}")
            for label in CLASSES
        },
        "max_mean_brier": _number(
            thresholds.get("max_mean_brier"), "max_mean_brier"),
        "min_macro_f1_over_baseline": _number(
            thresholds.get("min_macro_f1_over_baseline"),
            "min_macro_f1_over_baseline"),
        "max_slice_macro_f1_drop": _number(
            thresholds.get("max_slice_macro_f1_drop"),
            "max_slice_macro_f1_drop"),
        "min_test_n": _positive_int(
            thresholds.get("min_test_n"), "min_test_n"),
        "min_slice_n": _positive_int(
            thresholds.get("min_slice_n"), "min_slice_n"),
        "min_slice_class_n": _positive_int(
            thresholds.get("min_slice_class_n"), "min_slice_class_n"),
    }

    baseline = plan.get("baseline")
    if not isinstance(baseline, dict):
        raise EvaluationError("baseline metrics are required")
    out["baseline"] = {
        "macro_f1": _number(baseline.get("macro_f1"),
                            "baseline.macro_f1"),
        "mean_brier": _number(baseline.get("mean_brier"),
                              "baseline.mean_brier"),
    }

    slices = plan.get("supported_slices")
    if not isinstance(slices, dict):
        raise EvaluationError("supported_slices must be an object")
    canonical_slices: dict[str, list[str]] = {}
    for dimension, values in slices.items():
        if dimension not in SLICE_DIMENSIONS:
            raise EvaluationError(f"unsupported slice dimension {dimension!r}")
        if not isinstance(values, list) or not values:
            raise EvaluationError(f"supported_slices.{dimension} must be non-empty")
        cleaned = sorted({str(value).strip() for value in values
                          if str(value).strip()})
        if not cleaned:
            raise EvaluationError(f"supported_slices.{dimension} is empty")
        canonical_slices[dimension] = cleaned
    out["supported_slices"] = canonical_slices
    return out


def _fingerprint(canonical: dict) -> str:
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def register_plan(plan: Any) -> dict:
    """Validate and seal a plan before the frozen test result is opened."""
    canonical = _canonical_plan(plan)
    return {**canonical, "plan_hash": _fingerprint(canonical)}


def _registered_plan(plan: Any) -> dict:
    if not isinstance(plan, dict) or not isinstance(plan.get("plan_hash"), str):
        raise EvaluationError("a registered plan with plan_hash is required")
    canonical = _canonical_plan(plan)
    if plan["plan_hash"] != _fingerprint(canonical):
        raise EvaluationError("registered plan was modified after sealing")
    return {**canonical, "plan_hash": plan["plan_hash"]}


def _validated_rows(rows: Any) -> list[dict]:
    if not isinstance(rows, list) or not rows:
        raise EvaluationError("frozen test rows are required")
    out: list[dict] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise EvaluationError(f"row {index} must be an object")
        snippet_id = row.get("snippet_id") or row.get("id")
        if not isinstance(snippet_id, str) or not snippet_id.strip():
            raise EvaluationError(f"row {index} has no snippet_id")
        if snippet_id in seen:
            raise EvaluationError(f"duplicate snippet {snippet_id!r}")
        seen.add(snippet_id)
        truth, prediction = row.get("truth"), row.get("prediction")
        if truth not in CLASSES or prediction not in CLASSES:
            raise EvaluationError(f"row {index} has an invalid class")
        probabilities = row.get("probabilities")
        if not isinstance(probabilities, dict) or set(probabilities) != set(CLASSES):
            raise EvaluationError(
                f"row {index} probabilities must declare all three classes")
        probs = {
            label: _number(probabilities[label],
                           f"row {index} probabilities.{label}")
            for label in CLASSES
        }
        if abs(sum(probs.values()) - 1.0) > 1e-6:
            raise EvaluationError(f"row {index} probabilities must sum to 1")
        out.append({**row, "snippet_id": snippet_id,
                    "probabilities": probs})
    return out


def classification_metrics(rows: Any) -> dict:
    """Three-class metrics with an explicit zero for every missed class."""
    clean = _validated_rows(rows)
    by_class: dict[str, dict[str, float | int]] = {}
    for label in CLASSES:
        tp = sum(row["truth"] == label and row["prediction"] == label
                 for row in clean)
        fp = sum(row["truth"] != label and row["prediction"] == label
                 for row in clean)
        fn = sum(row["truth"] == label and row["prediction"] != label
                 for row in clean)
        support = tp + fn
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / support if support else 0.0
        f1 = (2 * precision * recall / (precision + recall)
              if precision + recall else 0.0)
        by_class[label] = {
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(f1, 6),
            "support": support,
        }
    brier = sum(
        (row["probabilities"][label] - (1.0 if row["truth"] == label else 0.0)) ** 2
        for row in clean for label in CLASSES
    ) / (len(clean) * len(CLASSES))
    return {
        "n": len(clean),
        "accuracy": round(sum(row["truth"] == row["prediction"]
                              for row in clean) / len(clean), 6),
        "macro_f1": round(sum(by_class[label]["f1"]
                              for label in CLASSES) / len(CLASSES), 6),
        "mean_multiclass_brier": round(brier, 6),
        "by_class": by_class,
    }


def _global_checks(metrics: dict, plan: dict) -> list[dict]:
    thresholds = plan["thresholds"]
    baseline = plan["baseline"]
    checks = [
        {"name": "test_sample_size", "passed":
         metrics["n"] >= thresholds["min_test_n"]},
        {"name": "macro_f1", "passed":
         metrics["macro_f1"] >= thresholds["min_macro_f1"]},
        {"name": "calibration", "passed":
         metrics["mean_multiclass_brier"] <= thresholds["max_mean_brier"]},
        {"name": "calibration_vs_declared_baseline", "passed":
         metrics["mean_multiclass_brier"] <= baseline["mean_brier"]},
        {"name": "beats_declared_baseline", "passed":
         metrics["macro_f1"] >= (
             baseline["macro_f1"]
             + thresholds["min_macro_f1_over_baseline"]
         )},
    ]
    for label in CLASSES:
        checks.append({
            "name": f"recall.{label}",
            "passed": (metrics["by_class"][label]["recall"]
                       >= thresholds["min_recall"][label]),
        })
    return checks


def _slice_result(rows: list[dict], *, overall: dict,
                  thresholds: dict) -> dict:
    if len(rows) < thresholds["min_slice_n"]:
        return {"status": "insufficient_evidence", "n": len(rows)}
    metrics = classification_metrics(rows)
    supported_labels = [
        label for label in CLASSES
        if metrics["by_class"][label]["support"]
        >= thresholds["min_slice_class_n"]
    ]
    if not supported_labels:
        return {"status": "insufficient_evidence", "n": len(rows),
                "metrics": metrics}
    supported_macro = sum(
        metrics["by_class"][label]["f1"] for label in supported_labels
    ) / len(supported_labels)
    checks = [{
        "name": "macro_f1_drop",
        "passed": supported_macro >= (
            overall["macro_f1"] - thresholds["max_slice_macro_f1_drop"]
        ),
    }]
    for label in supported_labels:
        checks.append({
            "name": f"recall.{label}",
            "passed": (metrics["by_class"][label]["recall"]
                       >= thresholds["min_recall"][label]),
        })
    return {
        "status": "passed" if all(check["passed"] for check in checks)
        else "failed",
        "n": len(rows),
        "supported_classes": supported_labels,
        "supported_macro_f1": round(supported_macro, 6),
        "checks": checks,
        "metrics": metrics,
    }


def evaluate_release(rows: Any, registered_plan: Any, *,
                     dataset_release_id: str) -> dict:
    """Evaluate one candidate; pass only on global and evidenced-slice gates."""
    plan = _registered_plan(registered_plan)
    if dataset_release_id != plan["dataset_release_id"]:
        raise EvaluationError("test data does not match the registered release")
    clean = _validated_rows(rows)
    overall = classification_metrics(clean)
    global_checks = _global_checks(overall, plan)
    slices: dict[str, dict[str, dict]] = {}
    evidenced_slice_failures = 0
    for dimension, values in plan["supported_slices"].items():
        slices[dimension] = {}
        for value in values:
            selected = [row for row in clean if str(row.get(dimension)) == value]
            result = _slice_result(
                selected, overall=overall, thresholds=plan["thresholds"])
            slices[dimension][value] = result
            if result["status"] == "failed":
                evidenced_slice_failures += 1
    passed = (all(check["passed"] for check in global_checks)
              and evidenced_slice_failures == 0)
    return {
        "status": "passed" if passed else "failed",
        "model_version": plan["model_version"],
        "dataset_release_id": dataset_release_id,
        "plan_id": plan["plan_id"],
        "plan_hash": plan["plan_hash"],
        "baseline_name": plan["baseline_name"],
        "overall": overall,
        "global_checks": global_checks,
        "slices": slices,
        "evidenced_slice_failures": evidenced_slice_failures,
    }
