"""
STORY    As a coach, I want the speaker's words and the machine's
         measurements hidden until I commit my answer, so that I judge the
         voice blind.
OUTCOME
  O1  The speaker's words appear only after I commit my answer; before
      that I still get the audio.
  O2  The machine's measurements appear only after I commit my answer.
  O3  The machine's rank, score, stickiness and measurements are always
      removed from the list of moments.
PROVES   O1 -> test_transcript_is_released_only_after_a_committed_answer,
               test_redaction_withholds_unanswered_transcript_from_the_payload
         O2 -> test_acoustic_features_are_released_only_after_a_committed_answer
         O3 -> test_the_allowlist_still_drops_everything_that_judges_the_speaker
WHY      Never-rule 2 (N1): no coach sees the machine's guess before
         answering.
"""
from services.coach_blind_gate import (
    redact_contextual_snippets,
    reveal_acoustic_features_after_commit,
    reveal_transcript_after_commit,
)


def test_transcript_is_released_only_after_a_committed_answer():
    assert reveal_transcript_after_commit(
        "Exact words", committed=False) == ""
    assert reveal_transcript_after_commit(
        "Exact words", committed=True) == "Exact words"
    assert reveal_transcript_after_commit(None, committed=True) == ""


def test_acoustic_features_are_released_only_after_a_committed_answer():
    features = {"f0_mean": 146.4, "speech_rate": 132}
    assert reveal_acoustic_features_after_commit(
        features, committed=False) is None
    assert reveal_acoustic_features_after_commit(
        features, committed=True) == features
    assert reveal_acoustic_features_after_commit(
        "not-a-feature-object", committed=True) is None


def test_the_allowlist_still_drops_everything_that_judges_the_speaker():
    """The half of the fence the founder did NOT move.

    A slide is the speaker's own material and a bookmark is a fact about what
    they were shown. A rank, a stickiness composite and an acoustic vector are
    the machine's read of how well they did it, and none of them may reach a
    rater who has not answered yet — that is N1, and it is untouched.
    """
    [row] = redact_contextual_snippets([{
        "id": "s2",
        "transcript": "words",
        "features": {"f0_mean": 146.4},
        "rank": 1,
        "overall_score": 0.82,
        "slide_stickiness": {"composite": 0.91},
        "stickiness": {"composite": 0.9},
        "coach_state": {"rating_value": "yes"},
    }])
    for leaked in ("features", "rank", "overall_score",
                   "slide_stickiness", "stickiness"):
        assert leaked not in row, leaked


def test_redaction_withholds_unanswered_transcript_from_the_payload():
    rows = redact_contextual_snippets([{
        "id": "s1",
        "transcript": "Words must not anchor the voice judgment",
        "audio_ref": "https://audio",
        "start_offset_ms": 0,
        "duration_ms": 900,
        "coach_state": {
            "rating_value": None,
            "rating_unrateable": False,
        },
    }])
    assert rows[0]["transcript"] == ""
    assert rows[0]["audio_ref"] == "https://audio"
