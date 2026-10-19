"""A phrase said twice gets a clearer version in the speaker's own words
(WIL-26).

The speaker's outcome: when they say the same words again ("we need to we
need to", or a sentence that stops and starts over), the rewrite lane offers
the sentence with the words said once, adds no word of its own, and wins
the lane over the tentative fallback. Emphasis ("Thank you, thank you.") and
a complete sentence said again on purpose are left alone (founder
2026-10-19).
"""
from __future__ import annotations

from services.take_feedback_manager import (
    ensure_required_families,
    evidence_backed_rewrite_candidates,
    rank_family_pool,
)


def _rewrites(text: str) -> list[dict]:
    return evidence_backed_rewrite_candidates(
        text, take_session_id="take-1", snippet_id="snip-1")


def test_a_phrase_said_again_is_offered_once_in_the_speakers_words():
    text = "So we need to we need to fix the onboarding flow. Then we ship."
    [row] = _rewrites(text)
    assert row["quote"] == "So we need to we need to fix the onboarding flow."
    assert row["proposed_text"] == "So we need to fix the onboarding flow."
    assert text[row["span"]["start"]:row["span"]["end"]] == row["quote"]
    assert row["feedback_family"] == "rewrite_clarity"
    assert row["why_key"] == "clarity"
    assert not row["tentative"]


def test_a_sentence_that_starts_over_becomes_the_finished_one():
    text = "We need to. We need to fix the onboarding flow."
    [row] = _rewrites(text)
    assert row["quote"] == text
    assert row["proposed_text"] == "We need to fix the onboarding flow."


def test_emphasis_is_not_a_repeat_to_fix():
    assert _rewrites("Thank you, thank you.") == []
    assert _rewrites("No, no, no, that is the wrong plan for us.") == []
    assert _rewrites("We grew fast. We grew fast because people told friends.") == []


def test_the_repeat_wins_the_rewrite_lane_over_the_fallback():
    text = ("Our customers wait three days for an answer, and that is too "
            "long. So we need to we need to fix the onboarding flow.")
    rows = _rewrites(text)
    praise_and_voice = [{
        "id": "cv", "snippet_id": "snip-1", "take_session_id": "take-1",
        "span": {"start": 0, "end": 13}, "feedback_family": "confident_voice",
    }]
    pool = ensure_required_families(
        text, rows + praise_and_voice,
        take_session_id="take-1", snippet_id="snip-1")
    [rewrite] = [r for r in rank_family_pool(pool)
                 if r["feedback_family"] == "rewrite_clarity"]
    assert rewrite["proposed_text"] == "So we need to fix the onboarding flow."
