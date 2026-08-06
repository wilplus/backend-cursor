"""STEP 2 of the coaching chat is the PEER-REVIEW beat (founder-signed
2026-08-04).

It used to ask "would you label your voice here as Charismatic?" and wire its
Yes/No to POST /v2/user/snippets/<id>/label — a route deleted with the stress
lane, so the button had been inert. The beat now validates the AI's pick and
feeds the peer-review corpus.

What these tests actually guard:

1. Step2SignedCopyTests — the three strings are SIGNED user-facing copy
   (LIVE LOOP). A silent reword is the failure worth catching, so they are
   pinned as literals here rather than compared against the constants (which
   would pass no matter what anyone changed them to).
2. Step2PromptContractTests — the prompt tells the model the right question,
   the right trigger, and the right endpoint, and no longer names the deleted
   one.
3. Step2LabelPinningTests — the route STAMPS the signed labels over whatever
   the model returned. "The prompt asks nicely" is not a guarantee: a model
   that softens "Not quite" would ship unsigned copy into a live chat.

Pure-Python: prompt builder + schema + the pinning block, no LLM, no network.

Run: python3 -m unittest test_step2_peer_review
"""
from __future__ import annotations

import unittest

try:
    from services import coaching_state_machine as csm
    from services.coaching_state_machine import (
        CONFIDENCE_REVIEW_TRIGGER,
        STATE_MACHINE_RESPONSE_SCHEMA,
        STEP2_NO_LABEL,
        STEP2_QUESTION,
        STEP2_YES_LABEL,
        build_state_machine_system_prompt,
    )
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    csm = None
    _IMPORT_ERROR = e


def _step2_block(src: str) -> str:
    """Just the STEP 2 section of the prompt.

    Scoped on purpose: the prompt says "VERBATIM" in the Director's Script
    section too, so an unscoped `assertIn("VERBATIM", prompt)` passes even
    after the STEP 2 instruction is deleted — verified by mutation. Assert
    inside the block that owns the rule."""
    start = src.index("STEP 2 —")
    end = src.index("DIRECTOR'S SCRIPT —", start)
    return src[start:end]


def _prompt(**over) -> str:
    kwargs = {
        "snippet": {
            "id": "11111111-2222-3333-4444-555555555555",
            "transcript": "we shipped it on Friday",
            "admin_comment": "Good lift on 'shipped'.",
            "coach_label": "charisma",
        },
        "director_script_questions": ["What were you feeling there?"],
        "user_first_name": "Sam",
        "user_org_context": None,
        "coaching_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    }
    kwargs.update(over)
    return build_state_machine_system_prompt(**kwargs)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class Step2SignedCopyTests(unittest.TestCase):
    """The founder signed these exact strings. Pinned as literals on purpose:
    asserting STEP2_QUESTION == STEP2_QUESTION would pass through any edit."""

    def test_the_question(self):
        self.assertEqual(STEP2_QUESTION,
                         "Did the AI pick the right moment here?")

    def test_the_button_labels(self):
        self.assertEqual(STEP2_YES_LABEL, "Yes, accurate")
        self.assertEqual(STEP2_NO_LABEL, "Not quite")

    def test_the_trigger_name(self):
        self.assertEqual(CONFIDENCE_REVIEW_TRIGGER,
                         "show_confidence_review_buttons")

    def test_the_old_question_is_gone_from_the_prompt(self):
        """The retired construct must not survive anywhere in live copy."""
        src = _prompt()
        self.assertNotIn("label your voice here as", src)
        self.assertNotIn("Charismatic?", src)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class Step2PromptContractTests(unittest.TestCase):

    def test_prompt_carries_the_signed_question_verbatim(self):
        block = _step2_block(_prompt())
        self.assertIn(STEP2_QUESTION, block)
        # Marked VERBATIM *in the STEP 2 block* so the model doesn't
        # paraphrase signed copy. Scoped — see _step2_block.
        self.assertIn("VERBATIM", block)
        self.assertIn("do NOT reword", block)

    def test_prompt_names_the_new_trigger_and_endpoint(self):
        block = _step2_block(_prompt())
        self.assertIn(CONFIDENCE_REVIEW_TRIGGER, block)
        self.assertIn("confidence-review", block)
        self.assertIn("ai_correct", block)

    def test_prompt_no_longer_points_at_the_deleted_route(self):
        src = _prompt()
        self.assertNotIn("/v2/user/snippets/<id>/label", src)
        self.assertNotIn("show_charisma_label_buttons", src)

    def test_prompt_asks_for_the_signed_button_labels(self):
        src = _prompt()
        self.assertIn(STEP2_YES_LABEL, src)
        self.assertIn(STEP2_NO_LABEL, src)

    def test_schema_enum_swapped_the_trigger(self):
        enum = (STATE_MACHINE_RESPONSE_SCHEMA["schema"]["properties"]
                ["triggers"]["items"]["enum"])
        self.assertIn(CONFIDENCE_REVIEW_TRIGGER, enum)
        self.assertNotIn("show_charisma_label_buttons", enum)

    def test_the_question_is_about_the_pick_not_the_person(self):
        """The corpus records a judgement on the AI's SELECTION. If the prompt
        let the model frame it as "did you like your delivery", the peer-review
        rows would mean something else entirely."""
        src = _prompt()
        self.assertIn("RIGHT MOMENT", src)

    def test_stress_labelled_snippet_gets_the_same_question(self):
        """The old copy branched on coach_label ('Charismatic' vs 'a stress
        moment'). The construct is retired — one question, every snippet."""
        for label in ("charisma", "stress", "", None):
            src = _prompt(snippet={
                "id": "11111111-2222-3333-4444-555555555555",
                "transcript": "we shipped it on Friday",
                "admin_comment": "note",
                "coach_label": label,
            })
            self.assertIn(STEP2_QUESTION, src)
            self.assertNotIn("a stress moment?", src)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class Step2LabelPinningTests(unittest.TestCase):
    """The route stamps the signed labels over the model's. Exercised as the
    route does it, against the same constants the route imports."""

    @staticmethod
    def _pin(parsed: dict) -> dict:
        # Mirrors routes/v2_routes.py:v2_coaching_state_machine_turn.
        if CONFIDENCE_REVIEW_TRIGGER in (parsed.get("triggers") or []):
            buttons = parsed.get("label_buttons")
            if not isinstance(buttons, dict):
                buttons = {}
            buttons["yes_label"] = STEP2_YES_LABEL
            buttons["no_label"] = STEP2_NO_LABEL
            parsed["label_buttons"] = buttons
        return parsed

    def test_a_reworded_label_is_overwritten(self):
        out = self._pin({
            "triggers": [CONFIDENCE_REVIEW_TRIGGER],
            "label_buttons": {"snippet_id": "s1",
                              "yes_label": "Yep, nailed it!",
                              "no_label": "Hmm, not really"},
        })
        self.assertEqual(out["label_buttons"]["yes_label"], STEP2_YES_LABEL)
        self.assertEqual(out["label_buttons"]["no_label"], STEP2_NO_LABEL)

    def test_snippet_id_is_left_alone(self):
        """Only the two signed strings are pinned — snippet_id varies per turn
        and is the model's to supply."""
        out = self._pin({
            "triggers": [CONFIDENCE_REVIEW_TRIGGER],
            "label_buttons": {"snippet_id": "the-real-snippet"},
        })
        self.assertEqual(out["label_buttons"]["snippet_id"],
                         "the-real-snippet")

    def test_missing_label_buttons_are_created(self):
        out = self._pin({"triggers": [CONFIDENCE_REVIEW_TRIGGER]})
        self.assertEqual(out["label_buttons"]["yes_label"], STEP2_YES_LABEL)

    def test_malformed_label_buttons_do_not_crash(self):
        for junk in (None, "buttons", 7, []):
            out = self._pin({"triggers": [CONFIDENCE_REVIEW_TRIGGER],
                             "label_buttons": junk})
            self.assertEqual(out["label_buttons"]["no_label"], STEP2_NO_LABEL)

    def test_other_steps_are_untouched(self):
        """A non-STEP-2 turn has no buttons; the pin must not invent them.

        Used to sample show_acoustic_targets_card here — deleted 2026-08-06
        with the numeric targets, so this samples STEP 9's trigger instead.
        """
        out = self._pin({"triggers": ["show_trial_recording_mic"]})
        self.assertNotIn("label_buttons", out)


if __name__ == "__main__":
    unittest.main()
