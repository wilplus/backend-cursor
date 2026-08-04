"""Prompt-registry drift gate (unit tier — no credentials, no LLM).

THE deterministic half of the eval-harness plan (founder 2026-08-03):
every LLM prompt lives in services/prompts/ and is hashed into
prompts.lock.json. These tests make an un-reviewed prompt edit
impossible — touch a prompt without regenerating the lockfile and the
suite goes red with the exact prompt ids that drifted.

The behavioral half (golden evals against the changed prompts) runs in
the prompt-evals CI job — see tests/evals/run_prompt_evals.py.
"""
import unittest

from services.prompts import registry


class TestPromptRegistry(unittest.TestCase):
    def test_manifest_builds(self):
        """Discovery + hashing works and yields at least one prompt."""
        m = registry.manifest()
        self.assertTrue(m, "no prompt modules discovered in services/prompts/")

    def test_lockfile_matches_code(self):
        """prompts.lock.json is in sync with the prompt modules.

        Failing here means a prompt (or its builder logic) changed
        without the lockfile being regenerated. If the change is
        intentional:  python -m services.prompts.registry update
        then commit the lockfile diff alongside the prompt edit.
        """
        ok, delta = registry.check()
        self.assertTrue(
            ok,
            "prompt drift detected — lockfile out of sync: "
            f"added={delta['added']} removed={delta['removed']} "
            f"changed={delta['changed']}. If intentional, run "
            "`python -m services.prompts.registry update` and commit "
            "the lockfile.",
        )

    def test_prompt_ids_are_namespaced(self):
        """Every id is '<surface>.<part>' so eval datasets, llm.chat log
        lines, and llm_usage cost rows key on the same surface name."""
        for pid in registry.manifest():
            surface, _, part = pid.partition(".")
            self.assertTrue(surface and part,
                            f"prompt id {pid!r} is not '<surface>.<part>'")

    def test_static_prompts_nonempty(self):
        """A blank static prompt is always a mistake."""
        for mod_name, module in registry.iter_prompt_modules():
            for pid, entry in module.REGISTER.items():
                if isinstance(entry, str):
                    self.assertTrue(
                        entry.strip(),
                        f"{mod_name}: static prompt {pid!r} is empty",
                    )


if __name__ == "__main__":
    unittest.main()
