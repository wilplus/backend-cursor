"""The Lane-2 promotion loop is dark until the founder says otherwise.

LEGACY-1 (blocker) and J1-2 (major), audit 2026-09-22.

``scripts/promote_openai_model.py`` writes ``runtime_config`` and
``services/llm.py`` serves that model on the very next request — including
the Take-1 Ideal Text composition (surface ``best_presentation``) and every
Say It Stronger card. Before the audit nothing on the path was read: an
operator with the service-role key could change the words in a speaker's
document, with the HTTP surface still answering "promotion is not active".

These tests are the gate. They assert refusal, never activation. The gate is
the founder's per-surface naming (``PROMOTION_SURFACES``; the global switch
``MLC2_PROMOTION_ENABLED`` was removed 2026-10-12, "remove the learning
doors"): since 2026-10-08 promotion ships open for the coach-answer and
coach-word surfaces only; the Ideal Text and Say It Stronger stay on their
stock model.
"""
from __future__ import annotations

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

    def test_promote_openai_model_refuses_when_no_surface_is_named(self):
        import scripts.promote_openai_model as promote

        with tempfile.TemporaryDirectory() as tmp:
            report = _passing_report(Path(tmp))
            argv = [
                "promote_openai_model.py",
                "--surface", "ideal_text",
                "--model-id", "ft:gpt-4.1-mini:org:proj:abc123",
                "--evaluation-report", str(report),
            ]
            with mock.patch.object(promote.Config, "PROMOTION_SURFACES", frozenset()), \
                 mock.patch("services.db.db.promote_runtime_surface_model") as spy, \
                 mock.patch("services.db.db.upsert_runtime_config") as legacy, \
                 mock.patch("sys.argv", argv):
                with self.assertRaises(SystemExit) as caught:
                    promote.main()

        self.assertIn("PROMOTION_SURFACES", str(caught.exception))
        spy.assert_not_called()
        legacy.assert_not_called()

    def test_resolve_surface_model_ignores_runtime_config_when_promotion_disabled(self):
        """The serving half. A row already in the table is not served."""
        with mock.patch("services.runtime_model_gate.promoted_keys",
                        return_value=frozenset()):
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

        self.assertIn("promoted_keys", inspect.getsource(llm))


class TheGateAsShipped(unittest.TestCase):
    """Nothing here authorizes anything; this records what the founder did.

    Doors 3 and 4 opened 2026-10-08 (founder: "turn it all ON") for the
    three coach-answer surfaces only. The retired DPO lane stays shut.
    """

    def test_the_promotion_surfaces_ship_as_the_founder_set_them(self):
        self.assertEqual(Config.PROMOTION_SURFACES, frozenset(
            {"exercise_script", "praise_line", "clearer_version",
             "coach_moment_line", "coach_take_word"}))

    def test_door_4_serves_only_the_named_surfaces(self):
        """The named surfaces are the decision.

        A stored row for the Ideal Text, Say It Stronger or the chat models
        is withheld: the founder named the coach-answer and coach-word
        surfaces, nothing else.
        """
        from services.runtime_model_gate import resolve_gated_model

        for key in ("openai_surface_model_ideal_text",
                    "openai_surface_model_say_it_stronger",
                    "openai_surface_model_coach_comment_draft",
                    "openai_chat_model", "openai_copilot_model"):
            self.assertEqual(resolve_gated_model(
                key, read=lambda k: "ft:unnamed", default="stock"), "stock", key)
        self.assertEqual(resolve_gated_model(
            "openai_surface_model_praise_line",
            read=lambda k: "ft:named", default="stock"), "ft:named")

    def test_the_promote_script_refuses_an_unnamed_surface(self):
        import scripts.promote_openai_model as promote

        with tempfile.TemporaryDirectory() as tmp:
            report = _passing_report(Path(tmp))
            argv = ["promote_openai_model.py", "--surface", "ideal_text",
                    "--model-id", "ft:gpt-4.1-mini:org:proj:abc123",
                    "--evaluation-report", str(report)]
            with mock.patch("services.db.db.promote_runtime_surface_model") as spy, \
                 mock.patch("services.db.db.upsert_runtime_config") as legacy, \
                 mock.patch("sys.argv", argv):
                with self.assertRaises(SystemExit) as caught:
                    promote.main()
        self.assertIn("PROMOTION_SURFACES", str(caught.exception))
        spy.assert_not_called()
        legacy.assert_not_called()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
