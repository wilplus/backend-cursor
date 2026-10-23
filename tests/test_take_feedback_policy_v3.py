"""
STORY    As a speaker, I want one whole Take turned into my two best moments,
         each praised or corrected by how it sounded, and honest coverage of
         my slides, so that the feedback is fair and evidence-backed.
OUTCOME
  O1  The Take is cut into blocks of the right size; a block that cannot be
      cut well stays whole and says why.
  O2  The two highest blocks are shown and the score decides each: one at
      or above the floor is praised (the highest is marked), one below it
      gets the practice prompt; praise is anchored inside a praised block.
  O3  Coverage is counted per slide, a slide without a clip says why, and
      the bar is higher from Take 3.
  O4  A corrected moment opens on a Clearer version only when the rewrite
      passes the gate; a weak fallback opens the voice exercise instead, and
      only for a voice under the floor: a voice that cleared it is praised.
  O5  A shown moment whose own words hedge opens on a Clearer version with
      its hedges left out, nothing added, even when its voice cleared the
      floor; a hedge's words that are not a hedge where they stand stay.
  O6  A shown moment whose voice reached the floor offers its helper words,
      praised or corrected with its Clearer version; a voice under the
      floor does not (N113).
  O7  A shown moment whose sentence restarts or asks for approval opens on
      the Clearer version: with the undermining opener for an approval tag
      or a playing-down "just", with the plain opener for a restart.
PROVES   O1 -> test_a_whole_take_is_partitioned_read_marked_noted_and_covered
         O2 -> test_a_whole_take_is_partitioned_read_marked_noted_and_covered
         O3 -> test_a_whole_take_is_partitioned_read_marked_noted_and_covered
         O4 -> test_weak_words_open_on_the_rewrite_only_when_it_passes_the_gate
         O5 -> test_a_strong_voice_whose_words_hedge_opens_on_its_clearer_version
         O6 -> test_a_confident_voice_offers_its_helper_words_also_after_its_clearer_version
         O7 -> test_a_shown_restart_or_approval_tag_opens_on_the_clearer_version
WHY      Founder 2026-10-20 ("the score decides each", flow page C2, C4),
         2026-10-18 ("words first, then voice"), 2026-10-21 (N108, "the
         voice decides"; N112, "There was no single rewrite in the take"), 2026-10-22 (N113, "After the
         rewording"), 2026-10-23 (N124, "Let's do 1-4").
"""
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

    # The two highest moments are shown (slides 0 and 1) and the score
    # decides each (founder 2026-10-20): both reach the floor, so both are
    # praised and nothing is corrected; the highest is marked. Every other
    # block is written False.
    assert [b["most_confident"] for b in blocks] == [
        True, True, False, False, False, False, False, False, False, False]
    assert [b["highest_moment"] for b in blocks] == [
        True, False, False, False, False, False, False, False, False, False]
    assert not any(b["carries_exercise"] for b in blocks)
    assert sum(b["practice_prompt"] for b in blocks) == 0

    # Praise anchors only on praised moments, from inside the block; the
    # praised slide 1 has no note inside it, and says so (the walk's line
    # bank covers it). Nothing is corrected, so no rewrite anchors.
    lanes = frame["verbal_lanes"]
    rewrite, praise = lanes["rewrite_clarity"], lanes["great_formulation"]
    assert rewrite["selected_candidate_ids"] == []
    assert rewrite["outcome"] == "no_defensible_candidate"
    assert praise["selected_candidate_ids"] == ["p-best"]
    assert praise["anchors"] == [
        {"block_id": by_slide[0][0]["block_id"], "candidate_id": "p-best"}]
    assert praise["blocks_without_note"] == [
        {"block_id": by_slide[1][0]["block_id"], "reason": "no_defensible_candidate"}]

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


# ── words first, then voice (founder 2026-10-18, services/rewrite_gate) ──

_UMS = " ".join(["um we think it matters"] * 3 + ["w"] * 60)


def _practise_frame(rewrite, scores=(0.9, -0.2, -0.6)):
    """Three slides: the best is praised; the second's own words carry
    fillers, so it is corrected and may open on a clearer version when the
    rewrite passes (founder 2026-10-20)."""
    pieces, snippets, at = [], [], 0
    for index, score in enumerate(scores):
        text = " ".join(f"w{index}x{n}" for n in range(75))
        pieces.append({"snippet_id": f"s{index}", "take_session_id": "take-2",
                       "slide_index": index, "start": at, "end": at + len(text),
                       "text": text, "recording_id": "recording-1",
                       "start_offset_ms": index * 5000, "duration_ms": 5000})
        at += len(text) + 1
        snippets.append({"id": f"s{index}", "session_id": "take-2", "recording_id": "recording-1",
                         "start_offset_ms": index * 5000, "duration_ms": 5000,
                         "transcript": _UMS if index == 1 else None,
                         "metrics": {"voice_confidence": {
                             "version": "voice-confidence-universal-v3", "score": score}}})
    start = pieces[1]["start"] + 10
    note = {"id": "r-clip", "feedback_family": "rewrite_clarity", "snippet_id": "s1",
            "take_session_id": "take-2", "span": {"start": start, "end": start + 40},
            "kind": "replace", "quote": "So um we think, uh, it matters a lot to us here",
            "proposed_text": "We think it matters a lot to us here.",
            "model_version": "rewrite-model-v1",
            "_manager_evidence": {"specificity": 5, "fallback": False}, **rewrite}
    text = " ".join(piece["text"] for piece in pieces)
    return build_shadow_frame(
        take_document={"take_session_id": "take-2", "text": text, "pieces": pieces},
        snippets=snippets, suggestions={}, feedback_candidates=[note],
        take_index=2, expected_recording_id="recording-1", served_text=text)


def test_weak_words_open_on_the_rewrite_only_when_it_passes_the_gate():
    frame = _practise_frame({})
    routed = [(b["slide_index"], b["exercise_kind"]) for b in frame["blocks"] if b["carries_exercise"]]
    assert routed == [(1, "clearer")]
    assert frame["verbal_lanes"]["rewrite_clarity"]["selected_candidate_ids"] == ["r-clip"]

    # The tentative fallback never opens it: the same moment, the voice Exercise.
    fallback = _practise_frame({"tentative": True,
                                "_manager_evidence": {"specificity": 5, "fallback": True}})
    routed = [(b["slide_index"], b["exercise_kind"]) for b in fallback["blocks"] if b["carries_exercise"]]
    assert routed == [(1, "voice")]
    assert fallback["verbal_lanes"]["rewrite_clarity"]["selected_candidate_ids"] == []

    # A voice that cleared the floor is never sent to the voice exercise
    # (N108): with no rewrite that passes, it is praised.
    strong = _practise_frame({"tentative": True,
                              "_manager_evidence": {"specificity": 5, "fallback": True}},
                             scores=(0.9, 0.5, -0.6))
    assert [b["slide_index"] for b in strong["blocks"] if b["carries_exercise"]] == []
    assert sorted(b["slide_index"] for b in strong["blocks"] if b["most_confident"]) == [0, 1]


_HEDGED = "I think maybe we could kind of start the pilot in two cities and see how it goes."


def _one_said_frame(said):
    """Three slides; the middle one's words are ``said`` and its voice
    clears the floor; returns the frame and the rule rows."""
    from services.take_feedback_manager import evidence_backed_rewrite_candidates
    pieces, snippets, at = [], [], 0
    for index, score in enumerate((0.9, 0.5, -0.6)):
        text = " ".join(f"w{index}x{n}" for n in range(75 - 17 * (index == 1))) + "."
        text = f"{said} {text}" if index == 1 else text
        pieces.append({"snippet_id": f"s{index}", "take_session_id": "take-2",
                       "slide_index": index, "start": at, "end": at + len(text),
                       "text": text, "recording_id": "recording-1",
                       "start_offset_ms": index * 5000, "duration_ms": 5000})
        at += len(text) + 1
        snippets.append({"id": f"s{index}", "session_id": "take-2", "recording_id": "recording-1",
                         "start_offset_ms": index * 5000, "duration_ms": 5000,
                         "transcript": said if index == 1 else None,
                         "metrics": {"voice_confidence": {
                             "version": "voice-confidence-universal-v3", "score": score}}})
    served = " ".join(piece["text"] for piece in pieces)
    rows = evidence_backed_rewrite_candidates(served, take_session_id="take-2", snippet_id="s0")
    frame = build_shadow_frame(
        take_document={"take_session_id": "take-2", "text": served, "pieces": pieces},
        snippets=snippets, suggestions={}, feedback_candidates=rows,
        take_index=2, expected_recording_id="recording-1", served_text=served)
    return frame, rows


def test_a_shown_restart_or_approval_tag_opens_on_the_clearer_version():
    """The founder's Take 4 (2026-10-23, N124): a restart, an ask for
    approval and a playing-down "just", and no rule wrote a Clearer
    version for any of them."""
    for said, clearer, reason in (
        ("I want to, I want you to know the plan works for every team.",
         "I want you to know the plan works for every team.", None),
        ("We need emotions, but not from the professional life, okay?",
         "We need emotions, but not from the professional life.", "undermining"),
        ("Startup is just a job to be done every day by all of us.",
         "Startup is a job to be done every day by all of us.", "undermining"),
    ):
        frame, rows = _one_said_frame(said)
        assert [(b["slide_index"], b["exercise_kind"]) for b in frame["blocks"]
                if b["carries_exercise"]] == [(1, "clearer")], said
        (chosen,) = frame["verbal_lanes"]["rewrite_clarity"]["selected_candidate_ids"]
        (row,) = [r for r in rows if r["id"] == chosen]
        assert (row["quote"], row["proposed_text"], row.get("rewrite_reason")) == (
            said, clearer, reason)


def test_a_strong_voice_whose_words_hedge_opens_on_its_clearer_version():
    """The founder's Take (2026-10-21, N112): both shown moments had strong
    voices and one hedged, and no rule wrote its clearer version, so it was
    praised and the Take showed no rewrite."""
    from services.take_feedback_manager import evidence_backed_rewrite_candidates
    pieces, snippets, at = [], [], 0
    for index, score in enumerate((0.9, 0.5, -0.6)):
        text = " ".join(f"w{index}x{n}" for n in range(75 - 17 * (index == 1))) + "."
        text = f"{_HEDGED} {text}" if index == 1 else text
        pieces.append({"snippet_id": f"s{index}", "take_session_id": "take-2",
                       "slide_index": index, "start": at, "end": at + len(text),
                       "text": text, "recording_id": "recording-1",
                       "start_offset_ms": index * 5000, "duration_ms": 5000})
        at += len(text) + 1
        snippets.append({"id": f"s{index}", "session_id": "take-2", "recording_id": "recording-1",
                         "start_offset_ms": index * 5000, "duration_ms": 5000,
                         "transcript": _HEDGED if index == 1 else None,
                         "metrics": {"voice_confidence": {
                             "version": "voice-confidence-universal-v3", "score": score}}})
    served = " ".join(piece["text"] for piece in pieces)
    rows = evidence_backed_rewrite_candidates(served, take_session_id="take-2", snippet_id="s0")
    frame = build_shadow_frame(
        take_document={"take_session_id": "take-2", "text": served, "pieces": pieces},
        snippets=snippets, suggestions={}, feedback_candidates=rows,
        take_index=2, expected_recording_id="recording-1", served_text=served)

    assert [(b["slide_index"], b["exercise_kind"]) for b in frame["blocks"]
            if b["carries_exercise"]] == [(1, "clearer")]
    (chosen,) = frame["verbal_lanes"]["rewrite_clarity"]["selected_candidate_ids"]
    (row,) = [r for r in rows if r["id"] == chosen]
    assert (row["quote"], row["proposed_text"]) == (
        _HEDGED, "We could start the pilot in two cities and see how it goes.")
    assert "rewrite_reason" not in row      # the walk's own opener, not N85's

    # A hedge's words that are not a hedge where they stand stay whole.
    plain = "This kind of problem is what I think about every single day."
    assert evidence_backed_rewrite_candidates(plain, take_session_id="t", snippet_id="s") == []


def test_a_confident_voice_offers_its_helper_words_also_after_its_clearer_version():
    # Slide 1's voice reached the floor and its words carry fillers: the
    # Clearer version, and its helper words after it (founder 2026-10-22).
    strong = _practise_frame({}, scores=(0.9, 0.5, -0.6))
    offered = [(b["slide_index"], b["exercise_kind"]) for b in strong["blocks"] if b["helper_words_prompt"]]
    assert offered == [(0, None), (1, "clearer")]
    # The same words under a voice below the floor: the Clearer version only.
    weak = _practise_frame({})
    assert [b["slide_index"] for b in weak["blocks"] if b["helper_words_prompt"]] == [0]
