"""When the practise moment opens on the Clearer version (founder
2026-10-18, "words first, then voice"; services/rewrite_gate.py).

Pins what a speaker sees: good words never get a rewrite; weak words get
one only when it sits in the moment's own clip, is evidence-backed, really
fixes the words, stays theirs and is no harder to say. Every other case is
the voice Exercise.
"""
from __future__ import annotations

import pytest

from services.rewrite_gate import rewrite_refusal, words_need_help

CLIP = {"start": 100, "end": 400}
SAID = "So um we think, uh, it kind of matters a lot to the people here"


def _rewrite(quote=SAID, proposed="We think it matters a lot to the people here.", **extra):
    row = {"id": "r", "quote": quote, "proposed_text": proposed, "tentative": False}
    item = {"candidate_id": "r", "document_span": {"start": 120, "end": 200},
            "evidence": {"fallback": False}}
    row.update(extra.pop("row", {}))
    item.update(extra.pop("item", {}))
    return row, item


@pytest.mark.parametrize("text, fit, why", [
    ("We cut onboarding from three weeks to four days and nobody had to work late", 1.0, None),
    ("So um we cut uh onboarding from three weeks um to four days", 1.0, "fillers"),
    ("It is kind of the best plan I guess and it sort of works for us", 1.0, "hedges"),
    ("We cut onboarding from three weeks to four days and nobody had to work late", 0.0, "off_slide"),
    ("I don't want. A script for every single meeting we hold this year", 1.0, "broken_sentence"),
    ("We cut onboarding from three weeks to four days and nobody had to work late", None, None),
    ("So we need to we need to fix the flow and we can we can ship it this week", 1.0, "repeats"),
    ("So we need to we need to fix the onboarding flow for every new customer who "
     "signs up with us this quarter and the next one after that", 1.0, None),
])
def test_only_words_that_need_help_can_open_on_a_rewrite(text, fit, why):
    assert words_need_help(text, fit) == why


def test_a_rewrite_that_fixes_the_words_and_keeps_them_theirs_opens_the_moment():
    row, item = _rewrite()
    assert rewrite_refusal(row, item, CLIP, SAID) is None


@pytest.mark.parametrize("change, reason", [
    ({"item": {"document_span": {"start": 380, "end": 450}}}, "outside_the_clip"),
    ({"row": {"tentative": True}}, "fallback"),
    ({"item": {"evidence": {"fallback": True}}}, "fallback"),
    ({"row": {"quote": "We think it matters a lot here",
              "proposed_text": "We think it matters a lot here."}}, "no_real_fix"),
    ({"row": {"proposed_text": "Our whole team believes this changes everything for clients."}},
     "not_their_words"),
    ({"row": {"proposed_text": "We think it matters to 40 people here."}}, "not_their_words"),
    ({"row": {"proposed_text": "We think it matters to Acme people here."}}, "not_their_words"),
    ({"row": {"proposed_text": "It matters."}}, "hard_to_say"),
    ({"row": {"quote": "Um we think it kind of matters a lot to the people here today",
              "proposed_text": "We think it matters a lot to the people here today and to all of them."}},
     "hard_to_say"),
])
def test_a_rewrite_that_fails_any_check_falls_back_to_the_voice_exercise(change, reason):
    row, item = _rewrite(**change)
    assert rewrite_refusal(row, item, CLIP, row["quote"]) == reason


@pytest.mark.parametrize("quote, proposed", [
    ("I don't want. A script for every meeting", "I don't want a script for every meeting"),
    ("So we need to we need to fix the onboarding flow.", "So we need to fix the onboarding flow."),
])
def test_a_mended_sentence_counts_as_the_fix(quote, proposed):
    row, item = _rewrite(quote=quote, proposed=proposed)
    assert rewrite_refusal(row, item, CLIP, quote) is None
