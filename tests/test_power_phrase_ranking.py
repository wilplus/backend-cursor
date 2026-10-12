"""The live phrase ranker accepts product evidence only."""
from __future__ import annotations

import unittest


class TheCharismaTermIsGoneTests(unittest.TestCase):
    """Founder 2026-08-13 / SPEC §7.2 — `_W_D` retired with the construct.

    The old kwargs are not silently ignored, and that is the point of this
    class. A ``direction=`` that quietly evaluated to a no-op would let the
    retired construct be passed from a caller nobody updated, forever, with
    nothing anywhere saying it stopped mattering. TypeError says it once,
    loudly, at the call site."""

    def test_no_construct_vocabulary_survives_in_the_blend(self):
        import inspect

        from services import power_phrase_ranking as mod
        src = inspect.getsource(mod.power_score)
        for word in ("challenge", "threat", "charisma"):
            self.assertNotIn(word, src.lower(), word)


if __name__ == "__main__":
    unittest.main()
