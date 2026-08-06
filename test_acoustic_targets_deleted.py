"""The numeric acoustic targets are GONE, and must not come back.

Founder decision 2026-08-06: "we don't want that, it is a wrong call."

WHAT WAS DELETED. STEP 8 of the coaching state machine used to compute
per-user prescriptive goals and instruct the model to keep the NUMBERS
verbatim:

    "keep your tempo at around 145 WPM (you were at 132 this time)"
    "push your vocal dynamic range to about 18.5 dB"
    "keep your filler words under 12 (you used 19 this time)"

WHY IT WAS THE WRONG SIDE OF THE LINE, since the rule is easy to misread:
the split-sink test is NOT "no digits" — SpeechDataPanel shows users wpm, Hz
and dB deliberately. Its own header states the real test: those are "reference
DATA, never a verdict. No best/worst flag, NO DIRECTION GUESS, no
characterization." A prescriptive target IS a direction, and pairing "you were
at 132" with a goal of 145 is a shortfall verdict wearing a suggestion's
clothes.

WHY DELETED RATHER THAN GATED. It spent two months behind a sign-off flag,
inert only because its inputs happened to be NULL. PM-9 repopulated those
inputs, which would have switched it on by accident. A flag someone can flip
is not a decision; removing the arithmetic is.

This suite is the ratchet. It replaces test_acoustic_targets_held.py, which
asserted the OPPOSITE (that the feature existed but was dark).

Run: python3 -m unittest test_acoustic_targets_deleted
"""
from __future__ import annotations

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).parent
SM = (ROOT / "services" / "coaching_state_machine.py").read_text()
COACHING = (ROOT / "routes" / "v2" / "coaching.py").read_text()


class TestTheMachineryIsGone(unittest.TestCase):

    def test_the_target_arithmetic_is_deleted(self):
        for symbol in ("compute_acoustic_targets",
                       "_format_acoustic_targets_for_prompt",
                       "_IDEAL_WPM_MIN", "_IDEAL_WPM_MAX",
                       "_TARGET_FILLERS_PER_MIN"):
            self.assertNotIn(symbol, SM, f"{symbol} is back")

    def test_the_card_trigger_is_not_in_the_schema(self):
        """The model cannot emit a trigger the enum does not contain."""
        self.assertNotIn("show_acoustic_targets_card", SM)

    def test_no_sign_off_flag_survives(self):
        """A flag is not a decision. If this reappears, the feature is one
        boolean away from shipping again."""
        self.assertNotIn("_ACOUSTIC_TARGETS_SIGNED_OFF", COACHING)
        self.assertNotIn("compute_acoustic_targets", COACHING)


class TestStep8SaysNothingNumeric(unittest.TestCase):

    def test_the_prompt_never_asks_for_verbatim_numbers(self):
        """The exact instruction that made this a verdict surface."""
        self.assertNotIn("keep the NUMBERS verbatim", SM)

    def test_the_seed_carries_no_digit(self):
        """The surviving phrasing seed is the one STEP 8 has actually emitted
        since 2026-06-01 — qualitative, no figure, no comparison."""
        seed = re.search(r"_NEXT_TAKE_SEED = \(\n(.*?)\n\)", SM, re.DOTALL)
        self.assertIsNotNone(seed, "_NEXT_TAKE_SEED not found")
        text = seed.group(1)
        self.assertFalse(any(c.isdigit() for c in text),
                         f"the seed contains a figure: {text}")
        for word in ("WPM", "dB", "filler words under"):
            self.assertNotIn(word, text)

    def test_step_8_and_9_forbid_figures_explicitly(self):
        """Deleting the arithmetic is not enough on its own — the model could
        still invent numbers. Both steps must say not to."""
        step8 = SM[SM.index("STEP 8"):SM.index("STEP 9 — THE RE-RECORD ASK")]
        self.assertIn("NO figure", step8)
        step9 = SM[SM.index("STEP 9 — THE RE-RECORD ASK"):]
        self.assertIn("NO figure", step9[:2000])

    def test_step_9_no_longer_quotes_a_target(self):
        """STEP 9 used to say: aim for X WPM ... under N fillers."""
        self.assertNotIn("aim for X WPM", SM)


class TestTheRegistryDoesNotStillPointAtIt(unittest.TestCase):

    def test_the_pending_prompt_entry_is_removed(self):
        """A SourceRef to a deleted function breaks the prompt-registry
        lockfile check rather than failing quietly."""
        pending = (ROOT / "services" / "prompts" / "pending.py").read_text()
        self.assertNotIn("acoustic_targets", pending)


if __name__ == "__main__":
    unittest.main()
