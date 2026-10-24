"""
STORY    As a speaker, I want one whole Take turned into my two best moments,
         each praised or corrected by how it sounded, and honest coverage of
         my slides, so that the feedback is fair and evidence-backed.
OUTCOME
  O1  The Take is cut into blocks of the right size; when the two best clips
      fall in one block, the boundary between them moves (40 to 120 words,
      never across a slide, never cutting a clip); a one-block Take whose
      two clips have 5 or more words each becomes two blocks; with no cut
      possible, nothing changes; each such block names its typed exception.
  O2  The two highest blocks are shown and the score decides each: one at
      or above the floor is praised (the highest is marked), one below it
      gets the practice prompt; praise is anchored inside a praised block.
  O3  Coverage is counted per slide, a slide without a clip says why, and
      the bar is higher from Take 3.
  O4  A corrected moment opens on a Clearer version only when the rewrite
      passes the gate; a weak fallback opens the voice exercise instead, and
      only for a voice under the floor: a voice that cleared it is praised.
      Hesitations only its transcript heard never open one (N121).
  O5  A shown moment whose own words hedge opens on a Clearer version with
      its hedges left out, nothing added, even when its voice cleared the
      floor; a hedge's words that are not a hedge where they stand stay.
  O6  A shown moment whose voice reached the floor offers its helper words,
      praised or corrected with its Clearer version; a voice under the
      floor does not (N113). A praised one also carries a practice
      (`confident_practice`, N122).
  O7  A shown moment whose sentence restarts or asks for approval opens on
      the Clearer version: with the undermining opener for an approval tag
      or a playing-down "just", with the plain opener for a restart.
  O8  In a shown block the moment is its highest-willfidence clip that can
      be served; a block already frozen keeps its clip.
PROVES   O1 -> test_a_whole_take_is_partitioned_read_marked_noted_and_covered
         O1 -> test_two_best_clips_in_one_block_get_a_block_each
         O1 -> test_a_one_block_take_is_split_for_two_moments
         O1 -> test_no_possible_cut_leaves_the_blocks_as_they_were
         O1 -> test_a_frozen_take_keeps_its_blocks
         O2 -> test_a_whole_take_is_partitioned_read_marked_noted_and_covered
         O3 -> test_a_whole_take_is_partitioned_read_marked_noted_and_covered
         O4 -> test_weak_words_open_on_the_rewrite_only_when_it_passes_the_gate
         O5 -> test_a_strong_voice_whose_words_hedge_opens_on_its_clearer_version
         O6 -> test_a_confident_voice_offers_its_helper_words_also_after_its_clearer_version
         O7 -> test_a_shown_restart_or_approval_tag_opens_on_the_clearer_version
         O8 -> test_a_shown_block_takes_its_best_clip_unless_frozen
WHY      Founder 2026-10-20 ("the score decides each", flow page C2, C4),
         2026-10-18 ("words first, then voice"), 2026-10-21 (N108, "the
         voice decides"; N112, "There was no single rewrite in the take"), 2026-10-22 (N113, "After the
         rewording"), 2026-10-23 (N124, "Let's do 1-4"; N118 and N122, "S×W
         picks, voice names top"), 2026-10-24 (N128; N118).
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


_SHOWN_HEDGED = "So I think we kind of maybe matter a lot to us here"


def _practise_frame(rewrite, scores=(0.9, -0.2, -0.6), shown=_SHOWN_HEDGED):
    """Three slides: the best is praised; the second's words on screen
    (``shown``) hedge, and its own transcript is full of ums, so it is
    corrected and may open on a clearer version when the rewrite passes
    (founder 2026-10-20; N121: the words on screen decide)."""
    pieces, snippets, at = [], [], 0
    for index, score in enumerate(scores):
        text = shown if index == 1 else " ".join(f"w{index}x{n}" for n in range(75))
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
            "kind": "replace", "quote": _SHOWN_HEDGED,
            "proposed_text": "We matter a lot to us here.",
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

    # Ums only the transcript heard (N121): the words on screen are clean,
    # so a "rewrite" of them fixes nothing and the voice exercise opens.
    clean = "We cut onboarding from three weeks to four days for all"
    unseen = _practise_frame({"quote": clean, "proposed_text": clean + "."}, shown=clean)
    assert [(b["slide_index"], b["exercise_kind"]) for b in unseen["blocks"]
            if b["carries_exercise"]] == [(1, "voice")]
    assert unseen["verbal_lanes"]["rewrite_clarity"]["selected_candidate_ids"] == []


_HEDGED = "I think maybe we could kind of start the pilot in two cities and see how it goes."


def _one_said_frame(said):
    """Three slides; the middle one's words are ``said`` and its voice
    clears the floor; returns the frame and the rule rows."""
    from services.take_feedback_manager import evidence_backed_rewrite_candidates
    pieces, snippets, at = [], [], 0
    for index, score in enumerate((0.9, 0.5, -0.6)):
        text = said if index == 1 else " ".join(f"w{index}x{n}" for n in range(75)) + "."
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


def _clips_frame(clips, **options):
    """A Take of ``clips``: (snippet id, slide, words, delivery score,
    transcript), each bound to its slide's Paragraph and served where it is
    said; a clip whose score is None has no snippet record, so it cannot be
    played."""
    pieces, snippets, at = [], [], 0
    for index, (sid, slide, words, score, transcript) in enumerate(clips):
        text = " ".join(f"{sid}x{n}" for n in range(words)) + "."
        pieces.append({"snippet_id": sid, "take_session_id": "take-2", "slide_index": slide,
                       "start": at, "end": at + len(text), "text": text,
                       "recording_id": "recording-1", "start_offset_ms": index * 5000,
                       "duration_ms": 5000, "part_id": f"part-{slide}",
                       "served_start": at, "served_end": at + len(text)})
        at += len(text) + 1
        if score is None:
            continue
        snippets.append({"id": sid, "session_id": "take-2", "recording_id": "recording-1",
                         "start_offset_ms": index * 5000, "duration_ms": 5000,
                         "transcript": transcript,
                         "metrics": {"voice_confidence": {
                             "version": "voice-confidence-universal-v3", "score": score}}})
    served = " ".join(piece["text"] for piece in pieces)
    return build_shadow_frame(
        take_document={"take_session_id": "take-2", "text": served, "pieces": pieces},
        snippets=snippets, suggestions={}, feedback_candidates=[],
        take_index=2, expected_recording_id="recording-1", served_text=served, **options)


def _two_clip_frame(**options):
    """Slide 1's block holds two clips: the louder one hedges in its own
    transcript, the softer one is clean, so the softer one's willfidence is
    the higher. Slides 0 and 2 hold one clip each."""
    return _clips_frame((("p0", 0, 75, 0.95, None), ("p1a", 1, 37, 0.9, _HEDGED * 2),
                         ("p1b", 1, 37, 0.6, None), ("p2", 2, 75, -0.8, None)), **options)


def test_a_shown_block_takes_its_best_clip_unless_frozen():
    """Founder 2026-10-23 (N118, N122): the Take's two best moments by
    willfidence; inside a block the louder clip used to win on its voice
    alone."""
    def slide_1(frame):
        (block,) = [b for b in frame["blocks"] if b["slide_index"] == 1]
        chosen = [r["candidate_id"] for r in frame["selected_confidence"]
                  if r["block_id"] == block["block_id"]]
        return block["selected_candidate_id"], chosen, block["highest_moment"] or block["carries_exercise"] or block["most_confident"]

    softer = "relative-confidence:take-2:p1b"
    assert slide_1(_two_clip_frame()) == (softer, [softer], True)
    assert slide_1(_two_clip_frame(select_servable=True)) == (softer, [softer], True)
    # A Take frozen with the louder clip keeps it.
    louder = "relative-confidence:take-2:p1a"
    frozen = _two_clip_frame(select_servable=True, frozen_candidate_ids={
        louder, "relative-confidence:take-2:p0", "relative-confidence:take-2:p2"})
    assert slide_1(frozen) == (louder, [louder], True)


# ── the two best moments get a block each (founder 2026-10-24, N128; N118) ──

def _clips(*rows):
    """(snippet id, slide, words, delivery score) rows as `_clips_frame`
    clips, with no transcript of their own."""
    return tuple((sid, slide, words, score, None) for sid, slide, words, score in rows)


def _rescored(take, **scores):
    return tuple((sid, slide, words, scores.get(sid, score), transcript)
                 for sid, slide, words, score, transcript in take)


def _clip(sid):
    return f"relative-confidence:take-2:{sid}"


def _cut(frame):
    return [(b["slide_index"], b["word_count"], b["partition_exception"])
            for b in frame["blocks"]]


def _ids(frame):
    return [b["block_id"] for b in frame["blocks"]]


def _moments(frame):
    """The shown moments: each block's clip, and whether it is the highest."""
    return [(b["selected_candidate_id"], b["highest_moment"]) for b in frame["blocks"]
            if b["most_confident"] or b["carries_exercise"]]


# Slide 1's two best clips, b3 and b5, fall in its second ~75-word block.
_SHARED = _clips(("a0", 0, 75, -0.5), ("b0", 1, 25, -0.6), ("b1", 1, 25, -0.6),
                 ("b2", 1, 25, -0.6), ("b3", 1, 25, 0.9), ("b4", 1, 25, -0.6),
                 ("b5", 1, 25, 0.8))


def test_two_best_clips_in_one_block_get_a_block_each():
    """Founder 2026-10-24 (N128; N118, "Move the boundary"): one block
    shows one moment, so the second best of the Take was never shown."""
    plain = _clips_frame(_rescored(_SHARED, b0=0.9, b3=-0.6))   # the best two in two blocks
    assert _cut(plain) == [(0, 75, None), (1, 75, None), (1, 75, None)]

    frame = _clips_frame(_SHARED)
    # The cut between slide 1's blocks moves to between b3 and b5: each side
    # 40 to 120 words, every clip whole and in its order.
    assert _cut(frame) == [(0, 75, None), (1, 100, "moment_split"), (1, 50, "moment_split")]
    assert [b["snippet_ids"] for b in frame["blocks"]] == [
        ["a0"], ["b0", "b1", "b2", "b3"], ["b4", "b5"]]
    # Both are shown, each in a block of its own.
    assert _moments(frame) == [(_clip("b3"), True), (_clip("b5"), False)]
    # The moved blocks are new blocks with new ids, the others keep theirs,
    # and the same Take is cut the same way every time.
    assert _ids(frame)[0] == _ids(plain)[0]
    assert not set(_ids(frame)[1:]) & set(_ids(plain))
    assert _clips_frame(_SHARED)["blocks"] == frame["blocks"]


def test_a_one_block_take_is_split_for_two_moments():
    """Founder 2026-10-24 (N128; N118, "Split into two"): a Take of one
    block showed one moment."""
    one = _clips(("d0", 0, 25, 0.9), ("d1", 0, 25, -0.6), ("d2", 0, 25, -0.6),
                 ("d3", 0, 25, 0.8))
    frame = _clips_frame(one)
    assert _cut(frame) == [(0, 50, "moment_split"), (0, 50, "moment_split")]
    assert _moments(frame) == [(_clip("d0"), True), (_clip("d3"), False)]
    # Not when one of the two clips is under 5 words: the block stays whole.
    short = _clips(("e0", 0, 4, 0.9), ("e1", 0, 45, None), ("e2", 0, 45, 0.5))
    assert _cut(_clips_frame(short)) == [(0, 94, "closest_outside_range")]


def test_no_possible_cut_leaves_the_blocks_as_they_were():
    """Founder 2026-10-24 (N128): the cut moves only where both sides keep
    40 to 120 words and no slide is crossed; otherwise nothing changes."""
    # f3 and f4 share slide 0's second block, and only 30 words follow f3.
    tight = _clips(("f0", 0, 25, -0.6), ("f1", 0, 25, -0.6), ("f2", 0, 25, -0.6),
                   ("f3", 0, 45, 0.9), ("f4", 0, 30, 0.8))
    # g1 and g2 are slide 1's one block; the cut before it is a slide's.
    across = _clips(("g0", 0, 75, -0.6), ("g1", 1, 30, 0.9), ("g2", 1, 45, 0.8))
    # h0 and h1 are a one-block Take of 60 words: no half reaches 40.
    halves = _clips(("h0", 0, 30, 0.9), ("h1", 0, 30, 0.8))
    for take, plain in ((tight, _rescored(tight, f0=0.9, f3=-0.6)),
                        (across, _rescored(across, g0=0.9, g1=-0.6)),
                        (halves, _rescored(halves, h1=None))):
        frame, before = _clips_frame(take), _clips_frame(plain)
        assert (_cut(frame), _ids(frame)) == (_cut(before), _ids(before)), take
    # Ten more words after f3, or g0 on slide 1, and the cut moves.
    roomier = tight[:4] + _clips(("f4", 0, 40, 0.8))
    assert _cut(_clips_frame(roomier)) == [(0, 120, "moment_split"), (0, 40, "moment_split")]
    one_slide = _clips(("g0", 1, 75, -0.6)) + across[1:]
    assert _cut(_clips_frame(one_slide)) == [(1, 105, "moment_split"), (1, 45, "moment_split")]


def test_a_frozen_take_keeps_its_blocks():
    """A Take's blocks are frozen with its selection (`take_feedback_set`,
    insert-once): frozen before the cut moved, it keeps the old blocks;
    frozen with the moved cut, it keeps the new ones (founder 2026-10-24,
    N128)."""
    served = _clips_frame(_SHARED, select_servable=True)
    assert _ids(served) == _ids(_clips_frame(_SHARED))     # the serve path cuts alike
    assert _moments(served) == [(_clip("b3"), True), (_clip("b5"), False)]

    plain = _clips_frame(_rescored(_SHARED, b0=0.9, b3=-0.6), select_servable=True)
    before = _clips_frame(_SHARED, select_servable=True, frozen_candidate_ids={
        _clip("a0"), _clip("b0"), _clip("b3")})
    assert (_cut(before), _ids(before)) == (_cut(plain), _ids(plain))
    assert [r["candidate_id"] for r in before["selected_confidence"]] == [
        _clip("a0"), _clip("b0"), _clip("b3")]

    after = _clips_frame(_SHARED, select_servable=True, frozen_candidate_ids={
        _clip("a0"), _clip("b3"), _clip("b5")})
    assert (_cut(after), _ids(after)) == (_cut(served), _ids(served))
    assert _moments(after) == _moments(served)


def test_a_strong_voice_whose_words_hedge_opens_on_its_clearer_version():
    """The founder's Take (2026-10-21, N112): both shown moments had strong
    voices and one hedged, and no rule wrote its clearer version, so it was
    praised and the Take showed no rewrite."""
    from services.take_feedback_manager import evidence_backed_rewrite_candidates
    pieces, snippets, at = [], [], 0
    for index, score in enumerate((0.9, 0.5, -0.6)):
        text = _HEDGED if index == 1 else " ".join(f"w{index}x{n}" for n in range(75)) + "."
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
    # A praised moment is practised too (N122); a corrected one is not marked.
    assert [(b["slide_index"], b["confident_practice"]) for b in strong["blocks"]
            if b["most_confident"] or b["carries_exercise"]] == [(0, True), (1, False)]
    assert not any(b["confident_practice"] for b in strong["blocks"] if not b["most_confident"])
