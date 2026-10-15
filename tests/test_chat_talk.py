"""Will reads the speaker's whole talk, slide by slide (founder 2026-10-15,
Privacy 3.7 section 4). Pure: no model, no database."""
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
