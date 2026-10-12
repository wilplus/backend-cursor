"""Regression tests for the surface-scoped, evaluation-gated DPO loop."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from services.ml_dpo_release import (
    load_evaluation_report,
    load_release_manifest,
    verify_release_file,
    write_evaluation_report,
    write_release_manifest,
)
from services.ml_surface_contracts import (
    clear_runtime_model_cache,
    contract_for_surface,
    evaluation_model_override,
    resolve_surface_model,
)


class SurfaceContractTests(unittest.TestCase):
    def tearDown(self) -> None:
        clear_runtime_model_cache()

    def test_rejected_canonical_alias_is_not_a_trainable_surface(self):
        """E-6: two registries disagreed and the legacy one was wired.

        ``ml_learning_surface_aliases`` records ``moment_suggestion`` as
        ambiguous legacy vocabulary that may not receive canonical writes,
        while ``SURFACES`` still offered it as something to export, fine-tune,
        promote and serve. One of the two has to be the authority.
        """
        from services.mlc2_foundation import REJECTED_LEARNING_ALIASES

        for alias in REJECTED_LEARNING_ALIASES:
            with self.subTest(alias=alias):
                with self.assertRaises(ValueError):
                    contract_for_surface(alias)

    def test_every_trainable_surface_maps_to_an_accepted_alias(self):
        """The four-id map must be a subset of what the DB registry takes."""
        from services.mlc2_foundation import (
            LEARNING_SURFACE_ALIASES,
            REJECTED_LEARNING_ALIASES,
        )
        from services.ml_surface_contracts import SURFACES

        for surface_id in SURFACES:
            with self.subTest(surface=surface_id):
                self.assertNotIn(surface_id, REJECTED_LEARNING_ALIASES)
                self.assertIn(surface_id, LEARNING_SURFACE_ALIASES)

    def test_eval_override_is_scoped_and_does_not_touch_runtime_config(self):
        """The override is process-local, and it outranks the stored row.

        LEGACY-1 changed the second half of this: outside the override, the
        stored row is served only when the founder has opened the promotion
        gate. Both postures are asserted, because "the gate is shut" and "the
        gate is open" must each do exactly one thing.
        """
        from unittest.mock import patch

        from config import Config

        calls: list[str] = []
        def get(key: str) -> str:
            calls.append(key)
            return "ft:promoted"

        # A golden evaluation runs with the gate still SHUT — passing it is
        # what the gate is opened on — so the override must win there.
        clear_runtime_model_cache()
        with patch.object(Config, "PROMOTION_SURFACES", frozenset()):
            with evaluation_model_override("ideal_text", "ft:candidate"):
                self.assertEqual(
                    resolve_surface_model(
                        "best_presentation", "base", config_getter=get,
                    ),
                    "ft:candidate",
                )
            # Outside it: the row is inert and is not even read.
            self.assertEqual(
                resolve_surface_model(
                    "best_presentation", "base", config_getter=get,
                ),
                "base",
            )
        self.assertEqual(calls, [])

        # With the gate open for this surface, the promoted model is served
        # as before.
        clear_runtime_model_cache()
        with patch.object(Config, "PROMOTION_SURFACES", frozenset({"ideal_text"})):
            self.assertEqual(
                resolve_surface_model(
                    "best_presentation", "base", config_getter=get,
                ),
                "ft:promoted",
            )
        self.assertEqual(calls, ["openai_surface_model_ideal_text"])

    def test_unregistered_surface_cannot_receive_promoted_model(self):
        calls: list[str] = []
        self.assertEqual(
            resolve_surface_model(
                "chat", "base", config_getter=lambda key: calls.append(key),
            ),
            "base",
        )
        self.assertEqual(calls, [])


class ImmutableReleaseTests(unittest.TestCase):
    def test_manifest_binds_surface_split_and_file_hashes(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            train = root / "train.jsonl"
            val = root / "val.jsonl"
            manifest_path = root / "release.json"
            train.write_text('{"x":1}\n', encoding="utf-8")
            val.write_text('{"x":2}\n', encoding="utf-8")
            written = write_release_manifest(
                manifest_path,
                surface="say_it_stronger",
                train_path=train,
                val_path=val,
                train_examples=1,
                val_examples=1,
                train_groups=1,
                val_groups=1,
            )
            loaded = load_release_manifest(
                manifest_path, expected_surface="say_it_stronger",
            )
            self.assertEqual(
                loaded["dataset_release_id"], written["dataset_release_id"],
            )
            verify_release_file(loaded, "train", train)
            train.write_text('{"x":3}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash"):
                verify_release_file(loaded, "train", train)

    def test_manifest_is_write_once(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            train = root / "train.jsonl"
            manifest = root / "release.json"
            train.write_text("{}\n", encoding="utf-8")
            kwargs = dict(
                surface="ideal_text", train_path=train, val_path=None,
                train_examples=1, val_examples=0,
                train_groups=1, val_groups=0,
            )
            write_release_manifest(manifest, **kwargs)
            with self.assertRaises(FileExistsError):
                write_release_manifest(manifest, **kwargs)

    def test_only_passing_untampered_evaluation_can_load_for_promotion(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            good = root / "good.json"
            write_evaluation_report(good, {
                "surface": "say_it_stronger",
                "golden_eval_surface": "say_it_stronger",
                "candidate_model_id": "ft:one",
                "dataset_release_id": "dpo-say_it_stronger-abc",
                "evaluated_at": "2026-08-26T10:00:00+00:00",
                "passed": True,
            })
            self.assertEqual(
                load_evaluation_report(good)["candidate_model_id"], "ft:one",
            )

            failed = root / "failed.json"
            write_evaluation_report(failed, {
                "surface": "say_it_stronger",
                "candidate_model_id": "ft:two",
                "passed": False,
            })
            with self.assertRaisesRegex(ValueError, "did not pass"):
                load_evaluation_report(failed)

            payload = json.loads(good.read_text(encoding="utf-8"))
            payload["candidate_model_id"] = "ft:tampered"
            good.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                load_evaluation_report(good)


if __name__ == "__main__":
    unittest.main()
