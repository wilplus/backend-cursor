"""Pure regression tests for final-report history reduction."""
from services.openai_service import _build_recording_progress_context


def test_empty_history_has_no_progress_context():
    assert _build_recording_progress_context([]) is None


def test_history_preserves_metrics_and_detects_improvement():
    rows = [
        {
            "performance_scores": [{"final_kpi": 0.9}],
            "filler_words_count": {"total": 2},
            "words_per_minute": 145,
        },
        {
            "performance_scores": {"final_kpi": 0.8},
            "filler_words_count": 3,
            "words_per_minute": 140,
        },
        {"performance_scores": {"final_kpi": 0.4}},
        {"performance_scores": [{"final_kpi": 0.3}]},
    ]

    context = _build_recording_progress_context(rows)

    assert context == {
        "total_previous_recordings": 4,
        "trend_improving": True,
        "trend_stable": False,
        "trend_declining": False,
        "previous_scores": [0.9, 0.8, 0.4, 0.3],
        "previous_filler_counts": [2, 3],
        "previous_wpm": [145.0, 140.0],
    }


def test_two_scores_have_no_older_comparison_bucket():
    context = _build_recording_progress_context([
        {"performance_scores": {"final_kpi": 0.7}},
        {"performance_scores": {"final_kpi": 0.2}},
    ])

    assert context["trend_improving"] is False
    assert context["trend_stable"] is False
    assert context["trend_declining"] is False
