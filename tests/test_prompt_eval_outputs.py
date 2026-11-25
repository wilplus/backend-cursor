"""
GUARD      The live grader sees the same wording and playback actions the
           speaker receives with the chat answer.
CATCHES    Losing the conditional sentence inside a wording card, or treating
           a false, missing or string playback flag as a displayed player.
IF REMOVED Correct artifact replies can fail the evals, or unavailable audio
           can be described to the grader as available.
PROVES     test_wording_conditions_remain_visible_to_the_grader
           test_only_a_strict_true_playback_flag_describes_a_player
WHY        Founder requested an eval audit after repeated generic coaching,
           2026-11-24; N694 keeps the exercise with its current source.
"""
import pytest

from tests.evals.harness import _semantic_output


def test_wording_conditions_remain_visible_to_the_grader():
    words = "Who could lead the pilot if it's approved?"
    view = _semantic_output({"answer": "Try this question.", "wording": {"words": words}})
    assert words in view.split("Full structured response:", 1)[0]
    assert "Try this question." in view


@pytest.mark.parametrize("flag", [True, False, None, "true"])
def test_only_a_strict_true_playback_flag_describes_a_player(flag):
    view = _semantic_output({"answer": "Listen to this line.", "voice_source": "clip", "playback": flag})
    assert ("Displayed audio player:" in view) is (flag is True)
