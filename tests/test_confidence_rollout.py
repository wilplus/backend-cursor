"""Controlled, Manager-gated rollout contract for Confident Voice."""
from __future__ import annotations

import unittest

from services import confidence_rollout as rollout


def _config(stage="limited", **overrides):
    config = {
        "rollout_id": "confidence-rollout-1",
        "stage": stage,
        "enabled": True,
        "model_version": "confidence-model-v1",
        "cohort_fraction": 1.0,
        "cohort_salt": "secret-versioned-salt",
        "min_nomination_probability": 0.75,
        "approved_plan_hash": "plan-hash-1",
    }
    config.update(overrides)
    return config


def _prediction(label="yes", probability=0.8):
    other = (1.0 - probability) / 2.0
    return {
        "prediction": label,
        "probabilities": {
            choice: probability if choice == label else other
            for choice in rollout.CLASSES
        },
    }


def _report(**overrides):
    report = {
        "status": "passed",
        "model_version": "confidence-model-v1",
        "plan_hash": "plan-hash-1",
    }
    report.update(overrides)
    return report


class ConfigTests(unittest.TestCase):

    def test_only_off_shadow_and_limited_exist(self):
        with self.assertRaisesRegex(rollout.RolloutError, "stage"):
            rollout.validate_config(_config(stage="full"))

    def test_limited_mode_has_no_implicit_threshold_or_salt(self):
        for field in ("cohort_fraction", "cohort_salt",
                      "min_nomination_probability", "approved_plan_hash"):
            config = _config()
            config.pop(field)
            with self.assertRaises(rollout.RolloutError, msg=field):
                rollout.validate_config(config)

    def test_cohort_is_deterministic(self):
        config = _config(cohort_fraction=0.4)
        self.assertEqual(
            rollout.in_limited_cohort(config, "owner-1"),
            rollout.in_limited_cohort(config, "owner-1"),
        )


class DecisionTests(unittest.TestCase):

    def test_kill_switch_preserves_deterministic_path(self):
        result = rollout.decide(
            _config(enabled=False), subject_id="owner-1",
            model_output=_prediction(), release_report=_report(),
        )
        self.assertFalse(result["model_influence"])
        self.assertEqual(result["route"], "deterministic")
        self.assertEqual(result["reason"], "kill_switch_or_off")

    def test_kill_switch_does_not_depend_on_learned_rollout_config(self):
        result = rollout.decide(
            {
                "rollout_id": "emergency-disable",
                "stage": "limited",
                "enabled": False,
            },
            subject_id="owner-1",
        )
        self.assertFalse(result["model_influence"])
        self.assertEqual(result["route"], "deterministic")
        self.assertEqual(result["reason"], "kill_switch_or_off")

    def test_shadow_records_prediction_but_cannot_influence(self):
        result = rollout.decide(
            _config(stage="shadow"), subject_id="owner-1",
            model_output=_prediction(),
        )
        self.assertEqual(result["shadow_prediction"], "yes")
        self.assertFalse(result["model_influence"])
        self.assertIsNone(result["candidate_nomination"])

    def test_limited_rollout_requires_exact_passing_release(self):
        cases = (
            (None, "release_evidence_missing"),
            (_report(status="failed"), "release_gate_not_passed"),
            (_report(model_version="other"), "model_version_mismatch"),
            (_report(plan_hash="other"), "evaluation_plan_mismatch"),
        )
        for report, reason in cases:
            result = rollout.decide(
                _config(), subject_id="owner-1",
                model_output=_prediction(), release_report=report,
            )
            self.assertFalse(result["model_influence"])
            self.assertEqual(result["reason"], reason)

    def test_outside_cohort_stays_deterministic(self):
        result = rollout.decide(
            _config(cohort_fraction=0.000001), subject_id="owner-1",
            model_output=_prediction(), release_report=_report(),
        )
        self.assertFalse(result["model_influence"])
        self.assertEqual(result["reason"], "outside_limited_cohort")

    def test_uncertain_yes_abstains(self):
        result = rollout.decide(
            _config(), subject_id="owner-1",
            model_output=_prediction(probability=0.70),
            release_report=_report(),
        )
        self.assertFalse(result["model_influence"])
        self.assertEqual(result["reason"], "model_abstained")

    def test_no_or_middle_never_nominates_confident_voice(self):
        for label in ("no", "in_between"):
            result = rollout.decide(
                _config(), subject_id="owner-1",
                model_output=_prediction(label), release_report=_report(),
            )
            self.assertFalse(result["model_influence"])
            self.assertIsNone(result["candidate_nomination"])

    def test_eligible_yes_only_nominates_to_manager(self):
        result = rollout.decide(
            _config(), subject_id="owner-1",
            model_output=_prediction(), release_report=_report(),
        )
        self.assertTrue(result["model_influence"])
        self.assertEqual(result["candidate_nomination"], "yes")
        self.assertEqual(result["route"], "learned_nomination_to_manager")
        self.assertTrue(result["manager_required"])

    def test_prediction_must_match_probability_argmax(self):
        bad = _prediction("yes")
        bad["probabilities"] = {"yes": 0.2, "in_between": 0.7, "no": 0.1}
        with self.assertRaisesRegex(rollout.RolloutError, "highest"):
            rollout.decide(
                _config(), subject_id="owner-1", model_output=bad,
                release_report=_report(),
            )

    def test_internal_result_contains_no_feedback_or_styling_action(self):
        result = rollout.decide(
            _config(), subject_id="owner-1",
            model_output=_prediction(), release_report=_report(),
        )
        for forbidden in ("feedback", "copy", "style", "voice_album",
                          "coach_verdict", "accepted_text"):
            self.assertNotIn(forbidden, result)


if __name__ == "__main__":
    unittest.main()
