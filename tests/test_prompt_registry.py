"""
GUARD      Every LLM prompt in services/prompts/ is hashed into
           prompts.lock.json, and the code matches the lockfile.
CATCHES    A prompt (or its builder logic) edited without regenerating the
           lockfile; the failure names the prompt ids that were added,
           removed or changed.
IF REMOVED A prompt can change without review and the speaker's feedback
           shifts silently. (The behavioural half, golden evals against the
           changed prompts, runs in the prompt-evals CI job.)
PROVES     test_lockfile_matches_code
WHY        Eval-harness plan, founder 2026-08-03.
"""
import unittest

from services.prompts import registry


class TestPromptRegistry(unittest.TestCase):

    def test_lockfile_matches_code(self):
        """If the change is intentional: python -m services.prompts.registry
        update, then commit the lockfile diff alongside the prompt edit."""
        ok, delta = registry.check()
        self.assertTrue(
            ok,
            "prompt drift detected — lockfile out of sync: "
            f"added={delta['added']} removed={delta['removed']} "
            f"changed={delta['changed']}. If intentional, run "
            "`python -m services.prompts.registry update` and commit "
            "the lockfile.",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
