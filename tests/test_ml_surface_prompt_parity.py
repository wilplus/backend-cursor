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

import unittest

from services.ml_surface_contracts import SURFACES


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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
