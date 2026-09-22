"""The Lane-2 promotion loop is dark until the founder says otherwise.

LEGACY-1 (blocker) and J1-2 (major), audit 2026-09-22.

``scripts/promote_openai_model.py`` writes ``runtime_config`` and
``services/llm.py`` serves that model on the very next request — including
the Take-1 Ideal Text composition (surface ``best_presentation``) and every
Say It Stronger card. The three ``MLC2_*`` constants that document this lane
as switched off were read by nothing on the path: an operator with the
service-role key could change the words in a speaker's document, with the
HTTP surface still answering "promotion is not active".

These tests are the gate. They assert refusal, never activation: every one
of them runs with the constants at their shipped ``False`` and expects the
lane to stand down.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from config import Config
from services.ml_dpo_release import write_evaluation_report
from services.ml_surface_contracts import (
    clear_runtime_model_cache,
    resolve_surface_model,
)


def _passing_report(directory: Path, *, surface: str = "ideal_text") -> Path:
    """An evaluation report that clears every check the promote script makes.

    The point of the fixture is that the *input* gate is satisfied, so a
    refusal can only come from the promotion flag itself.
    """
    from datetime import datetime, timezone

    from services.ml_surface_contracts import contract_for_surface

    contract = contract_for_surface(surface)
    path = directory / "eval.json"
    write_evaluation_report(path, {
        "surface": contract.id,
        "golden_eval_surface": contract.golden_eval_surface,
        "candidate_model_id": "ft:gpt-4.1-mini:org:proj:abc123",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "passed": True,
        "dataset_release_id": "rel-1",
    })
    return path


class PromotionRefusesWhileTheGateIsShut(unittest.TestCase):
    """LEGACY-1: no write reaches runtime_config while promotion is off."""

    def setUp(self) -> None:
        clear_runtime_model_cache()
        self.addCleanup(clear_runtime_model_cache)

    def test_promote_openai_model_refuses_when_mlc2_promotion_disabled(self):
        import scripts.promote_openai_model as promote

        with tempfile.TemporaryDirectory() as tmp:
            report = _passing_report(Path(tmp))
            argv = [
                "promote_openai_model.py",
                "--surface", "ideal_text",
                "--model-id", "ft:gpt-4.1-mini:org:proj:abc123",
                "--evaluation-report", str(report),
            ]
            with mock.patch.object(Config, "MLC2_PROMOTION_ENABLED", False), \
                 mock.patch("services.db.db.upsert_runtime_config") as spy, \
                 mock.patch("sys.argv", argv):
                with self.assertRaises(SystemExit) as caught:
                    promote.main()

        self.assertIn("MLC2_PROMOTION_ENABLED", str(caught.exception))
        spy.assert_not_called()

    def test_resolve_surface_model_ignores_runtime_config_when_promotion_disabled(self):
        """The serving half. A row already in the table is not served."""
        with mock.patch.object(Config, "MLC2_PROMOTION_ENABLED", False):
            resolved = resolve_surface_model(
                "best_presentation",
                "gpt-4o-mini",
                config_getter=lambda key: "ft:gpt-4.1-mini:org:proj:abc123",
            )
        self.assertEqual(resolved, "gpt-4o-mini")

    def test_the_serving_path_itself_consults_the_promotion_gate(self):
        """`llm.chat_complete` is the last thing before the provider call.

        The gate living one module away is correct but not sufficient: this
        is the function that picks the model a speaker's document is written
        with, and it must be readable here that it cannot be swapped.
        """
        import inspect

        from services import llm

        self.assertIn("MLC2_PROMOTION_ENABLED", inspect.getsource(llm))


class TrainingAndExportRefuseWhileTheirGatesAreShut(unittest.TestCase):
    """J1-2: the other two constants enforce something too."""

    def test_finetune_script_refuses_when_training_disabled(self):
        import scripts.run_openai_preference_finetune as finetune

        argv = [
            "run_openai_preference_finetune.py",
            "--surface", "say_it_stronger",
            "--train-file", "exports/train.jsonl",
            "--val-file", "exports/val.jsonl",
            "--manifest", "exports/rel.json",
        ]
        with mock.patch.object(Config, "MLC2_TRAINING_ENABLED", False), \
             mock.patch("sys.argv", argv):
            with self.assertRaises(SystemExit) as caught:
                finetune.main()
        self.assertIn("MLC2_TRAINING_ENABLED", str(caught.exception))

    def test_export_script_refuses_when_dataset_releases_disabled(self):
        import scripts.export_openai_preference_jsonl as export

        argv = [
            "export_openai_preference_jsonl.py",
            "--surface", "say_it_stronger",
            "--train-out", "exports/train.jsonl",
            "--val-out", "exports/val.jsonl",
            "--manifest-out", "exports/rel.json",
        ]
        with mock.patch.object(Config, "MLC2_DATASET_RELEASES_ENABLED", False), \
             mock.patch("sys.argv", argv):
            with self.assertRaises(SystemExit) as caught:
                export.main()
        self.assertIn("MLC2_DATASET_RELEASES_ENABLED", str(caught.exception))


class TheGateIsShutAsShipped(unittest.TestCase):
    """Nothing here authorizes anything; this records that."""

    def test_every_lane2_constant_ships_false(self):
        self.assertIs(Config.MLC2_DATASET_RELEASES_ENABLED, False)
        self.assertIs(Config.MLC2_TRAINING_ENABLED, False)
        self.assertIs(Config.MLC2_PROMOTION_ENABLED, False)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
