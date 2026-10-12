"""Every model name `runtime_config` can serve is enumerated and gated.

R-13 (minor, Job 1 review 2026-09-22), same class as LEGACY-1 for the
non-learned surfaces. ``OpenAIService._chat_model`` resolves
``openai_chat_model`` and ``openai_copilot_model`` straight out of
``runtime_config`` with a sixty-second cache. The table is service-role
writable, has no RLS and (before this workstream) no trigger, and the repo
contains no writer for either key — so a row that appeared in it would be
served to every chat and copilot call with no flag, no evaluation and no
provenance, and nothing in the codebase would be surprised.

Two properties, both of which must hold for the surface keys too:

  1. the set of runtime_config keys that can name a model is CLOSED — a new
     key cannot be read into a model id without being added here;
  2. reading one is GATED — the promotion flag decides, not the row.
"""
from __future__ import annotations

import unittest
from unittest import mock


class ReadingAModelKeyIsGated(unittest.TestCase):
    def test_chat_model_ignores_runtime_config_when_promotion_disabled(self):
        """R-13's own regression: the copilot/chat keys obey the same gate."""
        from services.openai_service import OpenAIService

        with mock.patch("services.runtime_model_gate.promoted_keys",
                        return_value=frozenset()), \
             mock.patch("services.db.db.get_runtime_config",
                        return_value="ft:gpt-4.1-mini:org:proj:smuggled"), \
             mock.patch("services.llm_client.build_openai_client", return_value=None):
            service = OpenAIService()
            self.assertNotEqual(service._chat_model("default"), "ft:gpt-4.1-mini:org:proj:smuggled")
            self.assertNotEqual(service._chat_model("copilot"), "ft:gpt-4.1-mini:org:proj:smuggled")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
