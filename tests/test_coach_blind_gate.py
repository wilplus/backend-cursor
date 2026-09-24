from services.coach_blind_gate import (
    blind_label_progress,
    can_reveal_acoustic_features,
    has_committed_blind_label,
    redact_contextual_snippets,
    reveal_acoustic_features_after_commit,
    reveal_transcript_after_commit,
)


def test_committed_label_accepts_all_current_states_and_legacy_rows():
    assert has_committed_blind_label({"rating_value": "yes"})
    assert has_committed_blind_label({"rating_value": "in_between"})
    assert has_committed_blind_label({"rating_value": "not_sure"})
    assert has_committed_blind_label({"rating_value": "audio_unclear"})
    assert has_committed_blind_label({"rating_value": "neutral"})
    assert has_committed_blind_label({"rating_unrateable": True})
    assert not has_committed_blind_label({"rating_value": None})


def test_progress_requires_this_coach_to_finish_every_piece():
    progress = blind_label_progress([
        {"coach_state": {"rating_value": "yes"}},
        {"coach_state": {"rating_value": None}},
    ])
    assert progress == {"labelled": 1, "total": 2, "complete": False}


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


def test_acoustic_queue_requires_explicit_second_pass_and_every_answer():
    complete = [{"label": {"value": "yes"}}, {"label": {"value": "no"}}]
    incomplete = [{"label": {"value": "yes"}}, {"label": None}]
    assert not can_reveal_acoustic_features(complete, requested=False)
    assert not can_reveal_acoustic_features(incomplete, requested=True)
    assert can_reveal_acoustic_features(complete, requested=True)


def test_redaction_keeps_audio_its_own_answer_the_slide_and_the_bookmark():
    """What a blind rater may see — REWRITTEN 2026-09-24, not relaxed.

    This test used to assert that the slide was dropped, and that was the
    right assertion for the instrument that existed when it was written: the
    confidence label came from the voice alone. The founder moved that fence
    deliberately ("I want as a coach to see the slide at the top; to know on
    which slide they are talking about"), having been shown both the fence and
    the compliant alternative. Only the founder can move it, so the test
    follows the new rule rather than the old one.

    It is still a fence. Everything that says something ABOUT the speaker —
    acoustic features, rank, stickiness — stays out, as does every scrap of the
    coach's own authoring. `bookmarked` is the other addition and is a bare
    boolean: surfaced to the user, or not, never the tier behind it.
    """
    rows = redact_contextual_snippets([{
        "id": "s1",
        "index": 0,
        "transcript": "Exact words",
        "audio_ref": "https://audio",
        "start_offset_ms": 100,
        "duration_ms": 900,
        "slide": {"index": 2},
        "bookmarked": True,
        "features": {"f0": 3},
        "rank": 1,
        "stickiness": {"composite": 0.9},
        "coach_state": {
            "rating_value": "no",
            "rating_unrateable": False,
            "note": "Show this later",
            "tag": "to_work_on",
            "surfaced": True,
        },
    }])
    assert rows == [{
        "id": "s1",
        "index": 0,
        "transcript": "Exact words",
        "audio_ref": "https://audio",
        "start_offset_ms": 100,
        "duration_ms": 900,
        "slide": {"index": 2},
        "bookmarked": True,
        "coach_state": {
            "note": "",
            "tag": None,
            "surfaced": False,
            "rating_value": "no",
            "rating_unrateable": False,
        },
    }]


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


def test_a_row_with_no_bookmark_flag_reads_false_rather_than_missing():
    """Safe-ahead: an older shaped row simply is not a bookmark."""
    [row] = redact_contextual_snippets([{"id": "s3", "coach_state": {}}])
    assert row["bookmarked"] is False
    assert row["slide"] is None


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
