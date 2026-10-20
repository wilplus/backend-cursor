"""
STORY    As a speaker, I want a Clearer version offered only when my words
         really need help and the rewrite stays mine, so that good words are
         left alone and practice opens on my voice otherwise.
OUTCOME
  O1  Good words never get a rewrite; fillers, hedges, broken sentences,
      repeats and off-slide words count as needing help.
  O2  A rewrite opens the moment only if it sits in the moment's clip, is
      backed by evidence, really fixes the words, uses only my words and is
      no harder to say; otherwise practice opens on my voice.
  O3  Mending a broken or repeated sentence counts as a real fix.
  O4  Words that undermine me (an apology or an ask for permission, the
      idea played down, self-doubt) need help even once; the same sentence
      said without them, nothing added, is a real fix that opens the
      moment, and a playing-down phrase that would need rewriting makes no
      rule rewrite (N85).
PROVES   O1 -> test_only_words_that_need_help_can_open_on_a_rewrite
         O2 -> test_a_rewrite_that_fixes_the_words_and_keeps_them_theirs_opens_the_moment,
               test_a_rewrite_that_fails_any_check_falls_back_to_the_voice_exercise
         O3 -> test_a_mended_sentence_counts_as_the_fix
         O4 -> test_only_words_that_need_help_can_open_on_a_rewrite,
               test_undermining_words_said_with_conviction_open_the_moment
WHY      Founder 2026-10-18: "words first, then voice".
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
    ("Sorry, we could match their price for the board, if that's okay", 1.0, "undermining"),
    ("This is just a small thing, but it saves the team a full day every week", 1.0, "undermining"),
    ("I'm not sure, but this plan cuts what we spend on support in half", 1.0, "undermining"),
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


def test_undermining_words_said_with_conviction_open_the_moment():
    from services.take_feedback_manager import evidence_backed_rewrite_candidates
    said = "We doubled growth. Sorry, I think we could maybe match their price, if that's okay. Thanks."
    rows = evidence_backed_rewrite_candidates(said, take_session_id="t", snippet_id="s")
    (row,) = [r for r in rows if r.get("rewrite_reason") == "undermining"]
    assert row["quote"] == "Sorry, I think we could maybe match their price, if that's okay."
    assert row["proposed_text"] == "We could match their price."
    item = {"candidate_id": row["id"], "document_span": {"start": 120, "end": 200},
            "evidence": {"fallback": False}}
    assert rewrite_refusal(row, item, CLIP, row["quote"]) is None
    # The reason reaches V3's input and the client's payload.
    from services.take_feedback_manager import exposure_snapshot, strip_internal_evidence
    assert [r.get("rewrite_reason") for r in exposure_snapshot([row])] == ["undermining"]
    assert strip_internal_evidence([row])[0]["rewrite_reason"] == "undermining"
    played_down = "This is just a small thing, but it saves the team a full day every week."
    assert not [r for r in evidence_backed_rewrite_candidates(played_down, take_session_id="t", snippet_id="s")
                if r.get("rewrite_reason")]

