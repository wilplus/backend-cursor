import re

from services.intervention_candidates import enforce_mvp_feedback_mix, select
from services.take_feedback_manager import (
    evidence_backed_rewrite_candidates,
    ensure_required_families,
    exposure_snapshot,
    rank_family_pool,
    strip_internal_evidence,
)


def _row(fid, family, start, **extra):
    return {
        "id": fid,
        "feedback_family": family,
        "span": {"start": start, "end": start + 4},
        "quote": "word",
        **extra,
    }


def test_ranks_complete_pool_instead_of_accepting_first_fit():
    rows = [
        _row("cv-first", "confident_voice", 0,
             _manager_evidence={"detector_rank": 0}),
        _row("cv-best", "confident_voice", 8, cue_keys=["landed_ending"],
             _manager_evidence={"detector_rank": 2}),
        _row("rewrite", "rewrite_clarity", 16,
             proposed_text="Word.", _manager_evidence={"specificity": 2}),
        _row("praise", "great_formulation", 24,
             _manager_evidence={"specificity": 1}),
    ]
    selected = rank_family_pool(rows)
    assert len(selected) == 3
    assert {row["id"] for row in selected} == {"cv-best", "rewrite", "praise"}


def test_fallbacks_are_three_lane_ready_and_do_not_invent_lexical_words():
    text = "Actually this sentence has enough words, and it can become clearer. Short and direct."
    rows = ensure_required_families(
        text,
        [_row("cv", "confident_voice", 0,
              kind="bold", source="confident_voice", snippet_audio_ref="signed",
              snippet_id="00000000-0000-0000-0000-000000000001")],
        take_session_id="00000000-0000-0000-0000-000000000002",
        snippet_id="00000000-0000-0000-0000-000000000001",
    )
    selected = enforce_mvp_feedback_mix(rows)
    assert {row["feedback_family"] for row in selected} == {
        "confident_voice", "rewrite_clarity", "great_formulation",
    }
    rewrite = next(row for row in rows
                   if row.get("feedback_family") == "rewrite_clarity")
    def words(value):
        return re.findall(r"[^\W_]+", value.casefold())
    assert set(words(rewrite["proposed_text"])).issubset(words(rewrite["quote"]))
    praise = next(row for row in rows
                  if row.get("feedback_family") == "great_formulation")
    assert praise["tentative"] is True
    assert text[praise["span"]["start"]:praise["span"]["end"]] == praise["quote"]


def test_structural_deletion_scar_competes_even_when_a_rewrite_already_exists():
    text = (
        "I need it to be modern, so I don't want. "
        "A hair style that is from a previous century."
    )
    candidates = evidence_backed_rewrite_candidates(
        text,
        take_session_id="take-2",
        snippet_id="snippet-2",
    )
    assert len(candidates) == 1
    structural = candidates[0]
    assert structural["quote"] == text
    assert structural["proposed_text"] == (
        "I need it to be modern, so I don't want a hair style that is from "
        "a previous century."
    )
    assert structural["_manager_evidence"]["lexical_words_invented"] == 0

    weaker = _row(
        "model-rewrite",
        "rewrite_clarity",
        0,
        proposed_text="Different punctuation.",
        _manager_evidence={"specificity": 1},
    )
    cv = _row("cv", "confident_voice", 0)
    praise = _row("praise", "great_formulation", len(text) - 4)
    selected = rank_family_pool([weaker, *candidates, cv, praise])
    rewrite = next(
        row for row in selected
        if row.get("feedback_family") == "rewrite_clarity"
    )
    assert rewrite["id"] == structural["id"]


def test_structural_rewrite_detector_emits_all_matches_for_manager_ranking():
    text = (
        "I don't want. A script that sounds rehearsed. "
        "I don't need. The extra introduction before my point."
    )
    rows = evidence_backed_rewrite_candidates(
        text,
        take_session_id="take-3",
        snippet_id="snippet-3",
    )
    assert len(rows) == 2
    assert [row["span"]["start"] for row in rows] == sorted(
        row["span"]["start"] for row in rows
    )


def test_exposure_keeps_evidence_but_student_payload_strips_it():
    rows = [_row("cv", "confident_voice", 0,
                 _manager_evidence={"detector_rank": 2})]
    assert exposure_snapshot(rows)[0]["evidence"] == {"detector_rank": 2}
    public = strip_internal_evidence(rows)
    assert "_manager_evidence" not in public[0]


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
