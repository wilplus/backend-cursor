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


def test_redaction_keeps_audio_and_own_answer_but_drops_context():
    rows = redact_contextual_snippets([{
        "id": "s1",
        "index": 0,
        "transcript": "Exact words",
        "audio_ref": "https://audio",
        "start_offset_ms": 100,
        "duration_ms": 900,
        "slide": {"index": 2},
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
        "coach_state": {
            "note": "",
            "tag": None,
            "surfaced": False,
            "rating_value": "no",
            "rating_unrateable": False,
        },
    }]


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
