"""
STORY    As a speaker, I want a Clearer version offered only when my words
         need help, and whenever they do in the ways people really speak,
         so that I see a better way to say it and never a rewrite of words
         that were fine.
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
  O5  A restart in one sentence keeps its last attempt; a sentence said
      again on purpose ("I will say it again. ...") is never touched.
  O6  An approval tag at a sentence's end (", okay?", ", right?",
      ", you know?", ", yeah?") goes, and the sentence ends on a full stop.
  O7  A playing-down "just" goes; "just now", "just in time",
      "just before" and "just as" stay.
  O8  A weak opener ("So,", "And so,", "So yeah,", "Well,") goes with any
      other rewrite of its sentence; on its own it needs 3 or more per 100
      words; "so that" and "so far" stay.
  O9  On the founder's Take 4, the sentences a coach would reword get a
      Clearer version, each only taking words out and each passing the
      gate.
PROVES   O1 -> test_only_words_that_need_help_can_open_on_a_rewrite
         O2 -> test_a_rewrite_that_fixes_the_words_and_keeps_them_theirs_opens_the_moment,
               test_a_rewrite_that_fails_any_check_falls_back_to_the_voice_exercise
         O3 -> test_a_mended_sentence_counts_as_the_fix
         O4 -> test_only_words_that_need_help_can_open_on_a_rewrite,
               test_undermining_words_said_with_conviction_open_the_moment
         O5 -> test_a_restart_keeps_its_last_attempt_and_a_deliberate_repeat_stays
         O6 -> test_an_approval_tag_goes_and_the_sentence_ends_on_a_full_stop
         O7 -> test_a_playing_down_just_goes_and_a_just_of_time_stays
         O8 -> test_a_weak_opener_goes_with_its_sentence_and_alone_only_when_frequent
         O9 -> test_the_founders_take_4_gets_its_clearer_versions
WHY      Founder 2026-10-18: "words first, then voice"; 2026-10-23 (N124,
         "Let's do 1-4").
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
    ("We need to we need to fix the flow and we can we can ship it this week", 1.0, "repeats"),
    ("Sorry, we could match their price for the board, if that's okay", 1.0, "undermining"),
    ("This is just a small thing, but it saves the team a full day every week", 1.0, "undermining"),
    ("I'm not sure, but this plan cuts what we spend on support in half", 1.0, "undermining"),
    ("We need to we need to fix the onboarding flow for every new customer who "
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



def _rule(said):
    """The rule rewrites of these words, each with the gate's verdict on it
    (None: it passes and opens the moment)."""
    from services.take_feedback_manager import evidence_backed_rewrite_candidates
    rows = evidence_backed_rewrite_candidates(said, take_session_id="t", snippet_id="s")
    out = []
    for row in rows:
        item = {"candidate_id": row["id"], "document_span": {"start": 120, "end": 200},
                "evidence": {"fallback": False}}
        out.append((row["quote"], row["proposed_text"], row.get("rewrite_reason"),
                    rewrite_refusal(row, item, CLIP, row["quote"])))
    return out


def test_a_restart_keeps_its_last_attempt_and_a_deliberate_repeat_stays():
    said = "I want to, I want you to know the plan works for every team."
    assert words_need_help(said, 1.0) == "restart"
    assert _rule(said) == [(said, "I want you to know the plan works for every team.", None, None)]
    # Said again on purpose, or two things said the same way: never touched.
    for kept in ("Professional life is separate from the personal life, period. "
                 "I will say it again. Professional life is separate from the "
                 "personal life, and it should stay neutral.",
                 "We need vitality, we need emotions, but not from the work we do."):
        assert words_need_help(kept, 1.0) is None
        assert _rule(kept) == []


@pytest.mark.parametrize("tag", ["okay", "right", "you know", "yeah"])
def test_an_approval_tag_goes_and_the_sentence_ends_on_a_full_stop(tag):
    said = f"We need emotions, but not from the professional life, {tag}?"
    assert words_need_help(said, 1.0) == "undermining"
    assert _rule(said) == [(said, "We need emotions, but not from the professional life.",
                            "undermining", None)]
    for kept in ("Is that the right plan for the team this year?",
                 "We turn right at the end of the road and stop."):
        assert words_need_help(kept, 1.0) is None
        assert _rule(kept) == []


@pytest.mark.parametrize("said, clearer", [
    ("Startup is just a job to be done every day.", "Startup is a job to be done every day."),
    ("If you could just help me do that, that would be nice.",
     "If you could help me do that, that would be nice."),
    ("I just wanted to show you the numbers from the pilot.",
     "I wanted to show you the numbers from the pilot."),
])
def test_a_playing_down_just_goes_and_a_just_of_time_stays(said, clearer):
    assert words_need_help(said, 1.0) == "undermining"
    assert _rule(said) == [(said, clearer, "undermining", None)]
    for kept in ("We finished just in time for the launch in May.",
                 "She called just now to say the launch went well.",
                 "We fixed it just before the launch in May.",
                 "It went just as we planned it for the team.",
                 "Just do your work day after day, step by step.",
                 "A bird outside the window that just came to welcome you."):
        assert words_need_help(kept, 1.0) is None
        assert _rule(kept) == []


def test_a_weak_opener_goes_with_its_sentence_and_alone_only_when_frequent():
    # With any other rewrite of its sentence, the opener goes too.
    assert _rule("So, if you could just help me do that, that would be nice.") == [(
        "So, if you could just help me do that, that would be nice.",
        "If you could help me do that, that would be nice.", "undermining", None)]
    assert _rule("Well, I think we should ship it this week to every team.") == [(
        "Well, I think we should ship it this week to every team.",
        "We should ship it this week to every team.", None, None)]
    # On its own it counts with the fillers: once in a long clip is fine,
    # three times in under a hundred words is not.
    once = ("So, we cut onboarding from three weeks to four days and nobody had "
            "to work late. The team shipped it in May and every customer saw "
            "the change in the first week, because the new flow asks for one "
            "form instead of five and answers every question on the same day.")
    assert words_need_help(once, 1.0) is None
    often = ("So, we cut onboarding to four days. And so, nobody had to work "
             "late. Well, the team shipped it in May. So yeah, every customer "
             "saw it.")
    assert words_need_help(often, 1.0) == "fillers"
    assert _rule("So, we cut onboarding from three weeks to four days.") == [(
        "So, we cut onboarding from three weeks to four days.",
        "We cut onboarding from three weeks to four days.", None, None)]
    # "so that" and "so far" are not openers.
    for kept in ("So that we can ship it, we cut the scope in half.",
                 "So far the pilot has worked in every city we tried."):
        assert _rule(kept) == []


TAKE_4 = (
    "Hi, so recording a take 4 right now for the testing of the route ride., so, "
    "I'm just trying to test the route ride, nothing more right here, right now. "
    "So, if you could be just, if you could just, help me do that, that would be "
    "really nice. It's quite noisy outside, so I'm gonna skip it. Let's go! "
    "So, in startup you might have a rollercoaster sometimes really high up in the "
    "sky, the other times quite low. Close to the ground, or below. "
    "And the point is that it should not be a source of your vitality in life. "
    "Startup is just a job It's a job to be done every day. "
    "Step by step, no emotions, neutral approach, no hyperactivity, no hyper "
    "depression. Just do your work day after day. So where the vitality should be? "
    "Vitality should come from the moments, like family encounters. Like a bird "
    "outside the window that just came to welcome you in the morning, green leaves "
    "on the trees. These are the moments that are truly ground breaking, that are "
    "really needed, because we need vitality We need emotions, but not to source "
    "them from the professional life, okay? "
    "Professional life is separate from the personal life, period. "
    "I will say it again. Professional life is separate from the personal life, "
    "and the professional life should not be composed out of emotions It should "
    "be professional equals neutral. It should be neutral."
)


def test_the_founders_take_4_gets_its_clearer_versions():
    """The founder's own Take 4 (2026-10-23): the four rules before N124
    wrote nothing for it."""
    rows = _rule(TAKE_4)
    assert all(refused is None for *_, refused in rows)
    assert {quote: (proposed, reason) for quote, proposed, reason, _ in rows} == {
        ", so, I'm just trying to test the route ride, nothing more right here, right now.":
            ("I'm trying to test the route ride, nothing more right here, right now.",
             "undermining"),
        "So, if you could be just, if you could just, help me do that, that would be really nice.":
            ("If you could help me do that, that would be really nice.", "undermining"),
        "Startup is just a job It's a job to be done every day.":
            ("Startup is a job It's a job to be done every day.", "undermining"),
        "These are the moments that are truly ground breaking, that are really needed, "
        "because we need vitality We need emotions, but not to source them from the "
        "professional life, okay?":
            ("These are the moments that are truly ground breaking, that are really needed, "
             "because we need vitality We need emotions, but not to source them from the "
             "professional life.", "undermining"),
        # A weak opener on its own: offered, and shown only where the clip's
        # openers and fillers reach 3 per 100 words.
        "So, in startup you might have a rollercoaster sometimes really high up in the "
        "sky, the other times quite low.":
            ("In startup you might have a rollercoaster sometimes really high up in the "
             "sky, the other times quite low.", None),
        "So where the vitality should be?": ("Where the vitality should be?", None),
    }
    # The deliberate repeat, the parallel "we need ...", "Just do your work"
    # and "just came" stay as they were said.
