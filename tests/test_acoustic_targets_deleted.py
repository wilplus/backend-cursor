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

2026-09-15 (audit Q-A6): the coaching state machine itself was deleted with
the coaching lane, so the STEP 8/9 wording assertions went with it. What is
left to ratchet is the route module (no sign-off flag, no arithmetic) and the
prompt registry (no entry pointing at the deleted surface).

Run: python3 -m unittest tests.test_acoustic_targets_deleted
"""
from __future__ import annotations

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
COACHING = (ROOT / "routes" / "v2" / "coaching.py").read_text()


class TestTheMachineryIsGone(unittest.TestCase):


    def test_no_sign_off_flag_survives(self):
        """A flag is not a decision. If this reappears, the feature is one
        boolean away from shipping again."""
        self.assertNotIn("_ACOUSTIC_TARGETS_SIGNED_OFF", COACHING)
        self.assertNotIn("compute_acoustic_targets", COACHING)


class TestTheRegistryDoesNotStillPointAtIt(unittest.TestCase):

    def test_the_pending_prompt_entry_is_removed(self):
        """A SourceRef to a deleted function breaks the prompt-registry
        lockfile check rather than failing quietly."""
        pending = (ROOT / "services" / "prompts" / "pending.py").read_text()
        self.assertNotIn("acoustic_targets", pending)


if __name__ == "__main__":
    unittest.main()
