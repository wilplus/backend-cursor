"""What actually selects the served Take-feedback policy.

J1-3 (minor), audit 2026-09-22. ``TAKE_FEEDBACK_POLICY_V3_MODE`` is commented
"Take Feedback V3 dark mode" and reads like the switch between V2 and V3. It
is not. Its only reader is ``take_feedback_policy_v3.dark_enabled``, which
gates one founder-scoped *shadow frame write* and cannot change a single row
a speaker sees. The switch that decides whether V3 serves is
``MLC3_SERVICE_ENABLED``, through ``coach_guidance_delivery.runtime_is_enabled``.

An operator who sets the first flag to "off" expecting V2 back gets V3
anyway. That is a naming defect with an operational edge, so the fix is a
name and a comment that say "shadow write" — and these tests, so the two
flags cannot quietly trade jobs again.
"""
from __future__ import annotations

import inspect
import unittest


class TheV3ModeFlagOnlyGatesTheShadowWrite(unittest.TestCase):
    """The named regression test for J1-3."""

    def test_v3_mode_only_controls_shadow_write(self):
        import config as config_module
        from services import ideal_text_changes, take_feedback_policy_v3

        flag = "TAKE_FEEDBACK_POLICY_V3_MODE"

        # 1. Exactly one module reads it, and that reader is the shadow gate.
        self.assertIn(flag, inspect.getsource(take_feedback_policy_v3.dark_enabled))
        self.assertNotIn(flag, inspect.getsource(ideal_text_changes))

        # 2. The gate it opens reaches the shadow write and nothing else.
        readers = [
            name for name, member in vars(ideal_text_changes).items()
            if callable(member)
        ]
        self.assertNotIn("dark_enabled", readers)
        serving = inspect.getsource(
            ideal_text_changes._ChangesRun._first_client_feedback
        )
        self.assertNotIn("dark_enabled", serving)
        self.assertNotIn(flag, serving)

        shadow = inspect.getsource(ideal_text_changes._ChangesRun._v3_shadow)
        self.assertIn("dark_enabled", shadow)
        self.assertIn("record_take_feedback_policy_v3_shadow", shadow)

        # 3. Its name and its comment say what it does. A flag whose name
        #    claims a job it does not have is how an operator turns the wrong
        #    thing off during an incident.
        source = inspect.getsource(config_module)
        declaration = next(
            line for line in source.splitlines() if line.strip().startswith(flag)
        )
        context = source.split(declaration)[0].splitlines()[-1]
        self.assertIn("shadow", (context + declaration).lower())

    def test_the_served_policy_is_switched_by_the_service_flag(self):
        """The other half: name the flag that does decide."""
        from services import coach_guidance_delivery

        gate = inspect.getsource(coach_guidance_delivery.runtime_is_enabled)
        self.assertIn("MLC3_SERVICE_ENABLED", gate)
        self.assertIn(
            "runtime_is_enabled",
            inspect.getsource(coach_guidance_delivery.principal_is_allowlisted),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
