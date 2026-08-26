"""Fail-closed rollout policy for a learned Confident Voice detector.

The model has only one possible product influence: nominate a possible
Confident Voice candidate.  It cannot create user feedback, style text, admit
audio to the Voice Album, write a coach verdict, or bypass Manager arbitration.

Stages are explicit and never advance themselves:

``off``
    Kill switch / deterministic system only.
``shadow``
    Run and record the model internally, but its output has no product effect.
``limited``
    A deterministic, versioned cohort may use a high-probability ``yes`` as a
    candidate nomination.  Everyone else remains on the deterministic route.

There is intentionally no ``full`` stage.  Expanding beyond a limited cohort
is a later explicit product/release decision, not an integer someone can turn
up accidentally.  A limited rollout requires a passing report from
``services.confidence_evaluation`` for the exact model and sealed plan.

All probabilities and rollout diagnostics are internal.  The returned
``candidate_nomination`` is an input to Manager, never a user payload.
Pure: no environment, DB, clock, model call, or network access.
"""
from __future__ import annotations

import hashlib
from typing import Any, Optional

from services.confidence_evaluation import CLASSES


STAGES = ("off", "shadow", "limited")
POLICY_VERSION = "confidence-controlled-rollout-v1"


class RolloutError(ValueError):
    """Rollout configuration or evidence cannot authorize model influence."""


def _text(value: Any, field: str, *, required: bool = True) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if required:
        raise RolloutError(f"{field} is required")
    return None


def _fraction(value: Any, field: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RolloutError(f"{field} must be numeric")
    out = float(value)
    if not minimum <= out <= 1.0:
        raise RolloutError(f"{field} must be between {minimum} and 1")
    return out


def validate_config(config: Any) -> dict:
    """Canonical rollout config.  Limited mode has no permissive defaults."""
    if not isinstance(config, dict):
        raise RolloutError("config must be an object")
    stage = config.get("stage")
    if stage not in STAGES:
        raise RolloutError(f"stage must be one of {', '.join(STAGES)}")
    enabled = config.get("enabled")
    if not isinstance(enabled, bool):
        raise RolloutError("enabled must be true or false")
    out = {
        "policy_version": POLICY_VERSION,
        "rollout_id": _text(config.get("rollout_id"), "rollout_id"),
        "stage": stage,
        "enabled": enabled,
        "model_version": _text(
            config.get("model_version"), "model_version",
            required=enabled and stage != "off",
        ),
    }
    if enabled and stage == "limited":
        out.update({
            "cohort_fraction": _fraction(
                config.get("cohort_fraction"), "cohort_fraction",
                minimum=0.000001,
            ),
            "cohort_salt": _text(config.get("cohort_salt"), "cohort_salt"),
            "min_nomination_probability": _fraction(
                config.get("min_nomination_probability"),
                "min_nomination_probability", minimum=0.5,
            ),
            "approved_plan_hash": _text(
                config.get("approved_plan_hash"), "approved_plan_hash"),
        })
    else:
        out.update({
            "cohort_fraction": 0.0,
            "cohort_salt": None,
            "min_nomination_probability": None,
            "approved_plan_hash": None,
        })
    return out


def _cohort_position(config: dict, subject_id: str) -> float:
    payload = ":".join((
        str(config["cohort_salt"]), str(config["rollout_id"]), subject_id,
    ))
    digest = hashlib.sha256(payload.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def in_limited_cohort(config: Any, subject_id: Any) -> bool:
    """Stable assignment on canonical user/guest owner identity."""
    current = validate_config(config)
    subject = _text(subject_id, "subject_id", required=False)
    if (not current["enabled"] or current["stage"] != "limited"
            or not subject):
        return False
    return _cohort_position(current, subject) < current["cohort_fraction"]


def _validate_prediction(model_output: Any) -> dict:
    if not isinstance(model_output, dict):
        raise RolloutError("model_output must be an object")
    prediction = model_output.get("prediction")
    if prediction not in CLASSES:
        raise RolloutError("prediction must be yes, in_between, or no")
    probabilities = model_output.get("probabilities")
    if not isinstance(probabilities, dict) or set(probabilities) != set(CLASSES):
        raise RolloutError("probabilities must declare all three classes")
    clean = {
        label: _fraction(probabilities[label], f"probabilities.{label}")
        for label in CLASSES
    }
    if abs(sum(clean.values()) - 1.0) > 1e-6:
        raise RolloutError("probabilities must sum to 1")
    if prediction != max(CLASSES, key=lambda label: clean[label]):
        raise RolloutError("prediction must match the highest probability")
    return {"prediction": prediction, "probabilities": clean}


def _release_evidence(config: dict, report: Any) -> tuple[bool, str]:
    if not isinstance(report, dict):
        return False, "release_evidence_missing"
    if report.get("status") != "passed":
        return False, "release_gate_not_passed"
    if report.get("model_version") != config["model_version"]:
        return False, "model_version_mismatch"
    if report.get("plan_hash") != config["approved_plan_hash"]:
        return False, "evaluation_plan_mismatch"
    return True, "release_gate_passed"


def decide(config: Any, *, subject_id: Any, model_output: Any = None,
           release_report: Any = None) -> dict:
    """Return internal routing evidence; never a feedback/user payload.

    ``candidate_nomination='yes'`` means only that the candidate builder may
    submit this exact clip to Manager.  Manager remains mandatory even in the
    treatment cohort.  All other outcomes retain the deterministic path.
    """
    current = validate_config(config)
    base = {
        "policy_version": POLICY_VERSION,
        "rollout_id": current["rollout_id"],
        "stage": current["stage"],
        "model_version": current["model_version"],
        "manager_required": True,
        "model_influence": False,
        "candidate_nomination": None,
        "route": "deterministic",
        "cohort_assigned": False,
        "shadow_prediction": None,
        "shadow_probabilities": None,
    }
    if not current["enabled"] or current["stage"] == "off":
        return {**base, "reason": "kill_switch_or_off"}

    prediction = _validate_prediction(model_output)
    observed = {
        **base,
        "shadow_prediction": prediction["prediction"],
        "shadow_probabilities": prediction["probabilities"],
    }
    if current["stage"] == "shadow":
        return {**observed, "reason": "shadow_only"}

    subject = _text(subject_id, "subject_id", required=False)
    if not subject or not in_limited_cohort(current, subject):
        return {**observed, "reason": "outside_limited_cohort"}
    observed["cohort_assigned"] = True
    evidence_ok, evidence_reason = _release_evidence(current, release_report)
    if not evidence_ok:
        return {**observed, "reason": evidence_reason}
    if prediction["prediction"] != "yes":
        return {**observed, "reason": "model_did_not_nominate"}
    probability = prediction["probabilities"]["yes"]
    if probability < current["min_nomination_probability"]:
        return {**observed, "reason": "model_abstained"}
    return {
        **observed,
        "reason": "learned_candidate_nomination",
        "model_influence": True,
        "candidate_nomination": "yes",
        "route": "learned_nomination_to_manager",
    }
