"""Regression tests for the surface-scoped, evaluation-gated DPO loop."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from services.ml_dpo_export import (
    DpoFilterConfig,
    row_to_dpo_example,
    split_train_val,
)
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
    fields_for_surface,
    resolve_surface_model,
    runtime_config_key,
    surface_for_annotation_field,
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

    def test_annotation_fields_and_runtime_alias_share_one_surface(self):
        self.assertEqual(
            surface_for_annotation_field("ideal_text_sentence"), "ideal_text",
        )
        self.assertEqual(contract_for_surface("best_presentation").id, "ideal_text")
        self.assertEqual(
            runtime_config_key("best_presentation"),
            "openai_surface_model_ideal_text",
        )
        self.assertEqual(
            surface_for_annotation_field("coach_note"),
            "coach_comment_draft",
        )
        self.assertEqual(
            runtime_config_key("coach_comment_draft"),
            "openai_surface_model_coach_comment_draft",
        )

    def test_unknown_or_legacy_field_is_not_silently_grouped(self):
        self.assertIsNone(surface_for_annotation_field("email_draft"))
        with self.assertRaises(ValueError):
            contract_for_surface("copilot")

    def test_eval_override_is_scoped_and_does_not_touch_runtime_config(self):
        clear_runtime_model_cache()
        calls: list[str] = []
        def get(key: str) -> str:
            calls.append(key)
            return "ft:promoted"
        with evaluation_model_override("ideal_text", "ft:candidate"):
            self.assertEqual(
                resolve_surface_model(
                    "best_presentation", "base", config_getter=get,
                ),
                "ft:candidate",
            )
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


class DpoCorpusTests(unittest.TestCase):
    def _row(self, field: str = "say_it_stronger") -> dict:
        return {
            "field_name": field,
            "section_type": "snippet",
            "ai_original_text": "This is the machine's original draft.",
            "coach_final_text": "This is the coach's improved final version.",
        }

    def test_row_must_belong_to_requested_surface(self):
        cfg = DpoFilterConfig(surface="say_it_stronger")
        example, reason = row_to_dpo_example(self._row(), session=None, cfg=cfg)
        self.assertIsNotNone(example)
        self.assertIsNone(reason)
        wrong, reason = row_to_dpo_example(
            self._row("moment_suggestion"), session=None, cfg=cfg,
        )
        self.assertIsNone(wrong)
        self.assertEqual(reason, "surface_filtered_out")

    def test_split_is_owner_disjoint(self):
        examples = [
            {"event_id": f"e{i}-{j}", "_split_group": f"user:{i}"}
            for i in range(30)
            for j in range(3)
        ]
        train, val = split_train_val(examples, val_ratio=0.25)
        train_groups = {row["_split_group"] for row in train}
        val_groups = {row["_split_group"] for row in val}
        self.assertTrue(train)
        self.assertTrue(val)
        self.assertFalse(train_groups & val_groups)

    def test_split_refuses_event_level_fallback(self):
        with self.assertRaisesRegex(ValueError, "owner split group"):
            split_train_val([{"event_id": "event-only"}], val_ratio=0.1)

    def test_surface_field_sets_are_not_overlapping(self):
        surfaces = (
            "say_it_stronger",
            "ideal_text",
            "coach_comment_draft",
        )
        sets = [fields_for_surface(surface) for surface in surfaces]
        for idx, fields in enumerate(sets):
            for other in sets[idx + 1:]:
                self.assertFalse(fields & other)


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
