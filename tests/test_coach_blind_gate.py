from services.coach_blind_gate import (
    blind_label_progress,
    has_committed_blind_label,
    redact_contextual_snippets,
)


def test_committed_label_accepts_ternary_or_explicit_abstention():
    assert has_committed_blind_label({"rating_value": "yes"})
    assert has_committed_blind_label({"rating_value": "neutral"})
    assert has_committed_blind_label({"rating_unrateable": True})
    assert not has_committed_blind_label({"rating_value": None})


def test_progress_requires_this_coach_to_finish_every_piece():
    progress = blind_label_progress([
        {"coach_state": {"rating_value": "yes"}},
        {"coach_state": {"rating_value": None}},
    ])
    assert progress == {"labelled": 1, "total": 2, "complete": False}


def test_redaction_keeps_evidence_and_own_answer_but_drops_context():
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
