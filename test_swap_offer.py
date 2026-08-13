"""The swap offer's two gates (founder architecture 2026-08-13, stages 2-3).

Stage 1 says the VOICE landed. These two decide whether the WORDS are
offerable — one deterministically, one with a single LLM call — before the
student is ever asked to swap a locked paragraph for this take's version.

Run: python3 -m unittest test_swap_offer
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services import swap_offer as so


class FumbleFloorTests(unittest.TestCase):
    """Stage 2 — "was this said cleanly?"

    NOT a similarity check against the locked text, and that was the founder's
    call after the argument for it fell apart: similarity is inversely
    correlated with the value of a swap. It only passes when the new words are
    nearly identical — exactly when swapping changes nothing — and it rejects
    the improvised better formulation that is the whole point of the lane."""

    CLEAN = ("Hey everyone, I just want to share that I am expanding my "
             "online presence this year.")

    def test_a_clean_sentence_has_no_reason_to_be_refused(self):
        self.assertIsNone(so.fumble_reason(self.CLEAN))

    def test_fillers_are_counted_by_the_SHIPPED_definition(self):
        """Never a second word list. The smoothing fence is the product's one
        definition of a filler and it is language-aware; a private copy here
        would drift, and then two parts of the pipeline would disagree about
        what an 'um' is. The founder's standing rule on filler data applies to
        detectors, not only to stored labels."""
        import inspect
        src = inspect.getsource(so.filler_rate)
        self.assertIn("strip_fillers", src)
        self.assertGreater(
            so.filler_rate("um so uh I think um maybe uh we should go now"),
            so.MAX_FILLER_RATE)
        self.assertEqual(so.filler_rate(self.CLEAN), 0.0)

    def test_a_hesitant_take_is_refused(self):
        self.assertEqual(
            so.fumble_reason("um so uh I think um maybe uh we should go now."),
            "fillers")

    def test_a_false_start_is_refused_AND_named_correctly(self):
        """The order of the two checks is load-bearing. `strip_fillers`
        collapses immediate repeats as well as hesitations, so `filler_rate`
        counts them — and asking it first reported "We we we shipped it" as a
        filler problem in a sentence containing no fillers at all. A wrong
        reason is worse than no reason: the string exists so the lane can be
        tuned."""
        self.assertEqual(
            so.fumble_reason("We we we shipped it to the whole team today."),
            "false_start")
        # …and a genuine hesitation is still named a hesitation.
        self.assertEqual(
            so.fumble_reason("um so uh I think um maybe uh we should go now."),
            "fillers")

    def test_a_sentence_that_never_closes_is_refused(self):
        """Pieces carry restored punctuation by the time they reach here, so a
        missing terminal mark means the speaker was cut off or trailed away —
        not that punctuation was unavailable."""
        self.assertEqual(so.fumble_reason("And then we shipped it and"),
                         "truncated")
        self.assertIsNone(so.fumble_reason("And then we shipped it fast!"))
        self.assertIsNone(so.fumble_reason("And then we shipped it fast?"))

    def test_a_fragment_is_refused_rather_than_scoring_perfectly(self):
        # Without the floor a one-word fragment rates 0.0 on every measure
        # above and sails through as pristine.
        self.assertEqual(so.fumble_reason("Yes."), "too_short")

    def test_ONE_filler_in_a_long_paragraph_is_not_a_fumble(self):
        """The floor catches a STUMBLE, not a lack of fluency. Refusing a
        good take over a single 'so' would make the lane as silent as the
        blank screen it was built to fix."""
        long_clean = ("So I want to tell you about the thing we built this "
                      "year and why it matters to every single person who "
                      "has ever stood up in front of a room to speak.")
        self.assertIsNone(so.fumble_reason(long_clean))

    def test_the_reason_is_a_string_because_lanes_need_tuning(self):
        # A gate that can only say "rejected" cannot be tuned. The string is
        # internal — it rides the log, never a payload.
        for bad, why in (("Yes.", "too_short"),
                         ("we shipped it and", "truncated")):
            self.assertEqual(so.fumble_reason(bad), why)

    def test_junk_never_raises(self):
        for bad in (None, 42, "", "   ", {"a": 1}):
            self.assertIsNotNone(so.fumble_reason(bad))
            self.assertEqual(so.filler_rate(bad), 0.0)
            self.assertEqual(so.repeat_rate(bad), 0.0)
            self.assertTrue(so.is_truncated(bad))


class DocumentWithSwapTests(unittest.TestCase):
    """The gate is asked about the WHOLE document, not the candidate alone —
    because what breaks is the seam, and a seam is only visible next to the
    paragraphs that are staying."""

    PARTS = [{"id": "p0", "text": "First slide words."},
             {"id": "p1", "text": "Second slide words."},
             {"id": "p2", "text": "Third slide words."}]

    def test_the_candidate_replaces_its_part_in_place(self):
        out = so.document_with_swap(self.PARTS, "p1", "A brand new middle.")
        self.assertEqual(
            out,
            "First slide words.\n\nA brand new middle.\n\nThird slide words.")

    def test_an_unknown_part_evaluates_NOTHING(self):
        # Better to make no offer than to evaluate a document the swap does
        # not belong to.
        self.assertEqual(so.document_with_swap(self.PARTS, "nope", "x"), "")
        self.assertEqual(so.document_with_swap(self.PARTS, "", "x"), "")
        self.assertEqual(so.document_with_swap(None, "p1", "x"), "")

    def test_it_uses_the_documents_own_paragraph_join(self):
        out = so.document_with_swap(self.PARTS, "p0", "New opener.")
        self.assertEqual(len(out.split("\n\n")), 3)


class ContinuityGateTests(unittest.TestCase):
    """Stage 3 — one LLM call, and the only one in this lane.

    IT IS FENCE-CLEAN FOR A REASON WORTH RESTATING: verbal PRAISE was refused
    an LLM because it would publish a subjective verdict to the student. This
    gate only ever REMOVES an offer — nothing it decides is shown, quoted or
    implied. A private filter is not a surfaced verdict."""

    DOC = "One.\n\nTwo.\n\nThree."
    CAND = "And so the second point is this one."

    def _run(self, payload, *, raises=False):
        class _Res:
            text = payload

        def _fake(**kw):
            if raises:
                raise RuntimeError("boom")
            return None if payload is None else _Res()

        with patch("services.llm.chat_complete", side_effect=_fake), \
             patch("services.say_it_stronger._guard_copy",
                   side_effect=lambda s: s):
            return so.evaluate_continuity(self.DOC, self.CAND)

    def test_a_clean_fit_is_served_without_a_polish(self):
        out = self._run('{"fits": true, "polish": null}')
        self.assertEqual(out["verdict"], so.FITS)
        self.assertIsNone(out["polish"])

    def test_a_connective_fix_is_the_L1_light_polish(self):
        """L1 anticipated this outcome — "VERBATIM + a LIGHT AI continuity
        polish" — and it is the case that saves a good improvised line
        instead of discarding it over one connective."""
        out = self._run('{"fits": true, '
                        '"polish": "So the second point is this one."}')
        self.assertEqual(out["verdict"], so.FITS_WITH_POLISH)
        self.assertEqual(out["polish"], "So the second point is this one.")

    def test_a_REWRITE_dressed_as_a_polish_is_refused(self):
        """The prompt asks for one connective; L1 is a fence, not a request.
        A model that returns a rewritten paragraph gets its polish dropped and
        the candidate served verbatim — never the machine's words."""
        out = self._run('{"fits": true, "polish": "' + "z" * 400 + '"}')
        self.assertEqual(out["verdict"], so.FITS)
        self.assertIsNone(out["polish"])

    def test_a_refusal_makes_no_offer(self):
        self.assertEqual(self._run('{"fits": false}')["verdict"], so.NO_FIT)

    def test_EVERY_failure_declines_the_offer(self):
        """The opposite direction from the rest of the pipeline, on purpose. A
        feedback read that hiccups must never take the surface dark; a GATE
        that hiccups must never wave through a swap nobody checked."""
        for payload in (None, "", "not json", "[]", '{"fits": "yes"}',
                        '{"nope": 1}'):
            self.assertEqual(so.evaluate_continuity.__name__,
                             "evaluate_continuity")
            self.assertEqual(self._run(payload)["verdict"], so.NO_FIT)
        self.assertEqual(self._run("{}", raises=True)["verdict"], so.NO_FIT)

    def test_an_empty_candidate_or_document_never_calls_the_model(self):
        with patch("services.llm.chat_complete") as m:
            self.assertEqual(
                so.evaluate_continuity("", "x")["verdict"], so.NO_FIT)
            self.assertEqual(
                so.evaluate_continuity("doc", "")["verdict"], so.NO_FIT)
            m.assert_not_called()

    def test_a_polish_that_fails_the_COPY_GUARD_downgrades(self):
        """The construct fence and the digit ban apply here like every other
        LLM lane. A guarded-out polish costs the polish, not the offer — the
        candidate was fine, only the suggested connective was not."""
        class _Res:
            text = '{"fits": true, "polish": "So the second point is 3."}'
        with patch("services.llm.chat_complete", return_value=_Res()), \
             patch("services.say_it_stronger._guard_copy", return_value=None):
            out = so.evaluate_continuity(self.DOC, self.CAND)
        self.assertEqual(out["verdict"], so.FITS)
        self.assertIsNone(out["polish"])


class PromptFenceTests(unittest.TestCase):
    def test_the_prompt_judges_FIT_and_forbids_rewriting(self):
        from services.prompts.swap_continuity import CORE
        low = CORE.lower()
        self.assertIn("never rewrite", low)
        self.assertIn("judge fit only", low)
        # It must not ask the model to rate the speaker or the writing — that
        # would be a quality verdict, which is the thing this lane routes
        # around rather than through.
        self.assertIn("do not judge how good", low)

    def test_the_prompt_is_registered_and_hash_locked(self):
        from services.prompts.swap_continuity import REGISTER
        self.assertIn("swap_continuity.system", REGISTER)


if __name__ == "__main__":
    unittest.main()
