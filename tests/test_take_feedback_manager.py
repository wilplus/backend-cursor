"""
STORY    As a speaker, I want every required kind of feedback (Confident
         Voice, a Clearer version, praise) to reach me, so that an old focus
         rule cannot silently drop one.
OUTCOME
  O1  With the current feedback contract, all three required kinds are
      kept even when an older focus rule points at one Paragraph.
PROVES   O1 -> test_mvp_contract_does_not_let_old_focus_gate_drop_a_required_lane
"""

from services.intervention_candidates import select


def _row(fid, family, start, **extra):
    return {
        "id": fid,
        "feedback_family": family,
        "span": {"start": start, "end": start + 4},
        "quote": "word",
        **extra,
    }


def test_mvp_contract_does_not_let_old_focus_gate_drop_a_required_lane():
    rows = [
        _row("cv", "confident_voice", 0, kind="bold", source="confident_voice",
             snippet_audio_ref="signed", snippet_id="s1"),
        _row("rewrite", "rewrite_clarity", 6, kind="replace", source="wording",
             proposed_text="Word."),
        _row("praise", "great_formulation", 12, kind="advice", source="structural"),
    ]
    result = select(
        rows,
        served_text="word\n\nword\n\nword",
        parts=[
            {"id": "p1", "text": "word", "locked_at": None},
            {"id": "p2", "text": "word", "locked_at": None},
            {"id": "p3", "text": "word", "locked_at": None},
        ],
        focus_part_id="p2",
        mvp_feedback_contract=True,
    )
    combined = [*result["changes"], *result.get("style_changes", [])]
    assert {row["feedback_family"] for row in combined} == {
        "confident_voice", "rewrite_clarity", "great_formulation",
    }
