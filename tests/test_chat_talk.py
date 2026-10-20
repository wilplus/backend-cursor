"""
STORY    As a speaker, I want Will to read my whole talk slide by slide, so
         that his answers refer to what I actually said on each slide.
OUTCOME
  O1  Each slide lists its bullet points and what I said on it.
  O2  A slide I said nothing on reads "(nothing yet)".
  O3  Words not tied to a slide are listed on their own.
PROVES   O1, O2, O3 -> test_each_slide_carries_its_points_and_what_they_said
WHY      Founder 2026-10-15; Privacy 3.7 section 4.
"""
from services.chat_app_context import talk_by_slide


def test_each_slide_carries_its_points_and_what_they_said():
    contexts = [{"slides": [{"title": "Why churn fell", "body": "- We listened\n- Fixed onboarding"},
                            {"title": "What next", "body": "- Pricing"}]}]
    payload = {"pieces": [{"text": "Our churn fell because we listened.", "slide_index": 0},
                          {"text": "Thank you all.", "slide_index": None}]}
    talk = talk_by_slide(contexts, payload)
    assert "Slide 1: Why churn fell" in talk
    assert "on the slide: We listened / Fixed onboarding" in talk
    assert "they said: Our churn fell because we listened." in talk
    assert "Slide 2: What next" in talk and "they said: (nothing yet)" in talk
    assert "not tied to a slide: Thank you all." in talk
