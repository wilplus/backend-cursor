from pathlib import Path

from services.take_feedback_policy_v3 import (
    build_shadow_frame,
)


def _piece(index, slide, words, score):
    text = " ".join(f"word{index}x{n}" for n in range(words))
    return {
        "snippet_id": f"snippet-{index}",
        "take_session_id": "take-2",
        "slide_index": slide,
        "start": index * 1000,
        "end": index * 1000 + len(text),
        "text": text,
        "recording_id": "recording-1",
        "start_offset_ms": index * 5000,
        "duration_ms": 5000,
        "score": score,
    }


def _frame(take_index=2):
    pieces = [
        _piece(0, 0, 25, -0.4),
        _piece(1, 0, 25, 0.2),
        _piece(2, 0, 25, 0.7),
        _piece(3, 1, 35, -0.5),
        _piece(4, 1, 35, -0.2),
    ]
    snippets = [{
        "id": piece["snippet_id"],
        "session_id": "take-2",
        "recording_id": "recording-1",
        "start_offset_ms": piece["start_offset_ms"],
        "duration_ms": piece["duration_ms"],
        "metrics": {
            "voice_confidence": {
                "version": "voice-confidence-universal-v3",
                "score": piece["score"],
            },
        },
    } for piece in pieces]
    suggestions = {
        "snippet-2": {"trigger": "confident", "cue_keys": ["full_volume"]},
    }
    feedback = [
        {
            "id": "weak-rewrite",
            "feedback_family": "rewrite_clarity",
            "snippet_id": "snippet-0",
            "take_session_id": "take-2",
            "span": {"start": 0, "end": 20},
            "quote": "a",
            "proposed_text": "b",
            "rule_version": "rewrite-generator-v1",
            "_manager_evidence": {"specificity": 1, "fallback": True},
        },
        {
            "id": "best-rewrite",
            "feedback_family": "rewrite_clarity",
            "snippet_id": "snippet-4",
            "take_session_id": "take-2",
            "span": {"start": 4050, "end": 4090},
            "quote": "a",
            "proposed_text": "b",
            "model_version": "rewrite-model-v1",
            "_manager_evidence": {"specificity": 5, "fallback": False},
        },
        {
            "id": "best-praise",
            "feedback_family": "great_formulation",
            "snippet_id": "snippet-2",
            "take_session_id": "take-2",
            "span": {"start": 100, "end": 130},
            "prompt_version": "praise-prompt-v1",
            "_manager_evidence": {"specificity": 4, "fallback": False},
        },
    ]
    return build_shadow_frame(
        take_document={
            "take_session_id": "take-2",
            "text": "x" * 5000,
            "pieces": pieces,
        },
        snippets=snippets,
        suggestions=suggestions,
        feedback_candidates=feedback,
        take_index=take_index,
        expected_recording_id="recording-1",
        # The Ideal Text IS this Take's transcript, so a served span is a
        # transcript span 1:1 (N48.1, Wave 1: verbal spans are mapped).
        served_text="x" * 5000,
    )


# ── merged from tests/test_take_feedback_policy_v3_integration.py (audit Q-T9) ──

MIGRATION = Path(
    "migrations/add_take_feedback_policy_universal_v3_transition.sql"
).read_text()


# ── the coverage ladder (founder 2026-09-18, contract 24c / Appendix H.13.1) ──


# ── one whole Take through the public frame (contracts 24a, 24c, 24e-24g) ──
#
# Replaces 30 tests that each called one private helper of the frame
# (founder 2026-10-12, "How to test": test the contract, not the helpers).
# Every rule they pinned is asserted here on what `build_shadow_frame`
# returns, so a refactor that keeps the frame right keeps this green.

# (piece index, slide, words, delivery score, has a snippet record)
_DECK = [
    (0, 0, 75, 0.9, True),     # high       -> confident, green
    (1, 1, 75, 0.6, True),     # high       -> confident, green
    (2, 2, 75, 0.2, True),     # mid-high   -> confident, NOT green (third)
    (3, 3, 75, 0.0, True),     # neutral    -> weak, exercise, no prompt
    (4, 4, 75, -0.7, True),    # low        -> weak, exercise, prompt
    (5, 5, 25, None, True),    # unread     -> neither; short_slide_run
    (6, 6, 120, -0.2, True),   # mid-low    -> weak; indivisible_long
    (7, 7, 50, 0.3, True),     # slide 7: two blocks, only one selectable
    (8, 7, 50, 0.3, False),
    (9, 7, 50, 0.3, False),
    (10, 8, 75, 0.5, False),   # slide 8: a block, but no clip -> uncovered
]


def _deck_note(note_id, family, snippet_id, start, end, specificity):
    row = {
        "id": note_id, "feedback_family": family, "snippet_id": snippet_id,
        "take_session_id": "take-2", "span": {"start": start, "end": end},
        "_manager_evidence": {"specificity": specificity, "fallback": False},
    }
    if family == "rewrite_clarity":
        row.update(quote="a", proposed_text="b", model_version="rewrite-model-v1")
    else:
        row.update(prompt_version="praise-prompt-v1")
    return row


def _deck_frame(take_index):
    pieces, snippets, at = [], [], 0
    for index, slide, words, score, has_snippet in _DECK:
        text = " ".join(f"w{index}x{n}" for n in range(words))
        pieces.append({
            "snippet_id": f"s{index}", "take_session_id": "take-2",
            "slide_index": slide, "start": at, "end": at + len(text),
            "text": text, "recording_id": "recording-1",
            "start_offset_ms": index * 5000, "duration_ms": 5000,
        })
        at += len(text) + 1
        if has_snippet:
            metrics = ({"voice_confidence": {
                "version": "voice-confidence-universal-v3", "score": score,
            }} if score is not None else {})
            snippets.append({
                "id": f"s{index}", "session_id": "take-2",
                "recording_id": "recording-1",
                "start_offset_ms": index * 5000, "duration_ms": 5000,
                "metrics": metrics,
            })
    text = " ".join(piece["text"] for piece in pieces)
    # Block spans: slide 0 is 0-439, slide 3 is 1320-1759, slide 4 is
    # 1760-2199, slide 5 (unread) is 2200-2339.
    notes = [
        _deck_note("p-worse", "great_formulation", "s0", 100, 140, 2),
        _deck_note("p-best", "great_formulation", "s0", 200, 240, 5),
        _deck_note("p-in-weak", "great_formulation", "s4", 1800, 1840, 9),
        _deck_note("p-unread", "great_formulation", "s5", 2210, 2250, 9),
        _deck_note("r-in-confident", "rewrite_clarity", "s0", 50, 90, 9),
        _deck_note("r-straddle", "rewrite_clarity", "s3", 1740, 1780, 9),
        _deck_note("r-unread", "rewrite_clarity", "s5", 2260, 2300, 9),
        _deck_note("r-weak", "rewrite_clarity", "s4", 1900, 1940, 3),
    ]
    return build_shadow_frame(
        take_document={"take_session_id": "take-2", "text": text,
                       "pieces": pieces},
        snippets=snippets, suggestions={}, feedback_candidates=notes,
        take_index=take_index, expected_recording_id="recording-1",
        served_text=text,
    )


def test_a_whole_take_is_partitioned_read_marked_noted_and_covered():
    frame = _deck_frame(take_index=2)
    blocks = frame["blocks"]
    by_slide = {}
    for block in blocks:
        by_slide.setdefault(block["slide_index"], []).append(block)

    # 24a: a block outside 60-90 words stays whole and says why.
    assert [(b["slide_index"], b["word_count"], b["partition_exception"])
            for b in blocks] == [
        (0, 75, None), (1, 75, None), (2, 75, None), (3, 75, None),
        (4, 75, None), (5, 25, "short_slide_run"), (6, 120, "indivisible_long"),
        (7, 50, "closest_outside_range"), (7, 100, "closest_outside_range"),
        (8, 75, None),
    ]

    # One praise moment per Take (founder 2026-10-14): the best, slide 0;
    # every other block is written False.
    assert [b["most_confident"] for b in blocks] == [
        True, False, False, False, False, False, False, False, False, False]
    assert not any(b["green_soft"] for b in blocks)

    # One practise moment per Take, the second best (slide 1); its sound is
    # the weaker half here (no transcript), so it is the voice exercise.
    routed = [(b["slide_index"], b["practice_prompt"], b["carries_exercise"],
               b["exercise_kind"]) for b in blocks if b["carries_exercise"]]
    assert routed == [(1, True, True, "voice")]
    assert sum(b["practice_prompt"] for b in blocks) == 1

    # Praise anchors only on green moments, from inside the block; a voice
    # exercise carries no rewrite.
    lanes = frame["verbal_lanes"]
    rewrite, praise = lanes["rewrite_clarity"], lanes["great_formulation"]
    assert rewrite["selected_candidate_ids"] == []
    assert rewrite["outcome"] == "no_defensible_candidate"
    assert praise["selected_candidate_ids"] == ["p-best"]
    assert praise["anchors"] == [
        {"block_id": by_slide[0][0]["block_id"], "candidate_id": "p-best"}]
    assert praise["blocks_without_note"] == []

    # 24c: the denominator is Slides with a block. Slide 7 is covered by its
    # one selected block; slide 8 formed a block but has no clip, and says so.
    coverage = frame["coverage"]
    assert coverage["assessable_slides"] == 9
    assert coverage["covered_slide_indexes"] == [0, 1, 2, 3, 4, 5, 6, 7]
    assert coverage["uncovered"] == [{
        "slide_index": 8, "block_count": 1,
        "reasons": ["no_exact_clip_lineage_candidate"],
    }]
    assert coverage["required_floor"] == 0.80
    assert coverage["meets_floor"] is True        # 8/9 clears Take 2's 80%
    assert _deck_frame(take_index=3)["coverage"]["meets_floor"] is False


# ── 25: an honest empty lane is typed, never merely absent ──


# ── the bookmark reaches the client (founder 2026-09-18, contract 24g) ──
#
# "There are no green bookmarks... none of that actually landed." It had not:
# the ladder was computed on the frame and dropped before the row was built, so
# the browser received no tier and every bookmark could only be one colour.
