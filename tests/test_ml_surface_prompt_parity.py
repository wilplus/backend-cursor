"""A promoted model is bound to the prompt it was evaluated under.

H-1 (minor), audit 2026-09-22. The promotion gate runs the candidate through
the real serving adapter on golden cases, so a model that cannot answer in
the serving shape is rejected before ``runtime_config`` is written. What the
gate never recorded is *which prompt* that evaluation used. A later prompt
edit therefore re-points a promoted model at text it was never gated against,
and nothing anywhere can notice: the export JSONL carries no prompt version
and ``runtime_config`` stored only a model id.

The binding is a hash, not a re-evaluation — this closes the record-keeping
half of H-1. The export/serve prompt divergence itself is Workstream 6's.
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from config import Config
from services.ml_dpo_release import write_evaluation_report
from services.ml_surface_contracts import SURFACES, contract_for_surface


def _passing_report(directory: Path, surface: str) -> Path:
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


class EverySurfaceHasALockedPromptHash(unittest.TestCase):
    def test_locked_prompt_hash_is_defined_for_every_trainable_surface(self):
        from services.ml_surface_contracts import locked_prompt_hash

        for surface_id in SURFACES:
            with self.subTest(surface=surface_id):
                digest = locked_prompt_hash(surface_id)
                self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_two_surfaces_do_not_share_one_prompt_hash(self):
        from services.ml_surface_contracts import locked_prompt_hash

        digests = {locked_prompt_hash(s) for s in SURFACES}
        self.assertEqual(len(digests), len(SURFACES))


class PromotionRecordsThePromptItWasGatedUnder(unittest.TestCase):
    """The named regression test for H-1."""

    def test_promote_requires_locked_prompt_hash(self):
        import scripts.promote_openai_model as promote
        from services.ml_surface_contracts import locked_prompt_hash

        surface = "say_it_stronger"
        correct = locked_prompt_hash(surface)

        with tempfile.TemporaryDirectory() as tmp:
            report = _passing_report(Path(tmp), surface)
            base = [
                "promote_openai_model.py",
                "--surface", surface,
                "--model-id", "ft:gpt-4.1-mini:org:proj:abc123",
                "--evaluation-report", str(report),
            ]

            # A stale or absent hash is refused, before any write.
            for argv in (base, base + ["--prompt-hash", "0" * 64]):
                with mock.patch.object(Config, "MLC2_PROMOTION_ENABLED", True), \
                     mock.patch("services.db.db.upsert_runtime_config") as spy, \
                     mock.patch("sys.argv", argv):
                    with self.assertRaises(SystemExit):
                        promote.main()
                    spy.assert_not_called()

            # The current hash is accepted, and stored beside the model id.
            argv = base + ["--prompt-hash", correct]
            with mock.patch.object(Config, "MLC2_PROMOTION_ENABLED", True), \
                 mock.patch("services.db.db.upsert_runtime_config") as spy, \
                 mock.patch("sys.argv", argv):
                spy.return_value = {"key": "openai_surface_model_say_it_stronger"}
                promote.main()

        spy.assert_called_once()
        metadata = spy.call_args.kwargs["metadata"]
        self.assertEqual(metadata["prompt_lock_sha256"], correct)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
