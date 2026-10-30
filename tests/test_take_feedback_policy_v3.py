"""
STORY    As a speaker, I want one whole Take turned into my two best moments,
         each praised or corrected by how it sounded, and honest coverage of
         my slides, so that the feedback is fair and evidence-backed.
OUTCOME
  O1  The Take is cut into blocks of the right size; when the two best clips
      fall in one block, the boundary between them moves (40 to 120 words,
      never across a slide, never cutting a clip); a one-block Take whose
      two clips have 5 or more words each becomes two blocks; and a short
      Take still shows me two moments: when no cut keeps 40 words a side and
      nothing else could be shown, the block is split between the two
      (N246); each such block names its typed exception.
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
  O9  On a plan, I get my two best moments and also the moment where this
      week's level shows most, practised with the level's own practice (the
      AI voice for pace), even when its voice was confident: a third
      moment, or one of the two when the level shows there; with nothing
      showing the level, just the two best (G7, N246).
  O10 A sentence that already has the helper words I had when I recorded
      gives its place to my next best moment; helper words I pick during the
      walk don't move my moments (N246).
PROVES   O1 -> test_a_whole_take_is_partitioned_read_marked_noted_and_covered
         O1 -> test_two_best_clips_in_one_block_get_a_block_each
         O1 -> test_a_one_block_take_is_split_for_two_moments
         O1 -> test_a_short_take_still_shows_two_moments
         O1 -> test_a_frozen_take_keeps_its_blocks
         O2 -> test_a_whole_take_is_partitioned_read_marked_noted_and_covered
         O3 -> test_a_whole_take_is_partitioned_read_marked_noted_and_covered
         O4 -> test_weak_words_open_on_the_rewrite_only_when_it_passes_the_gate
         O5 -> test_a_strong_voice_whose_words_hedge_opens_on_its_clearer_version
         O6 -> test_a_confident_voice_offers_its_helper_words_also_after_its_clearer_version
         O7 -> test_a_shown_restart_or_approval_tag_opens_on_the_clearer_version
         O8 -> test_a_shown_block_takes_its_best_clip_unless_frozen
         O9 -> test_on_a_plan_i_get_my_two_best_and_my_level
         O10 -> test_a_sentence_with_my_helper_words_gives_way_to_the_next
WHY      Founder 2026-10-20 ("the score decides each", flow page C2, C4),
         2026-10-18 ("words first, then voice"), 2026-10-21 (N108, "the
         voice decides"; N112, "There was no single rewrite in the take"), 2026-10-22 (N113, "After the
         rewording"), 2026-10-23 (N124, "Let's do 1-4"; N118 and N122, "S×W
         picks, voice names top"), 2026-10-24 (N128; N118); 2026-10-27
         (N209, the level's moment); 2026-10-28 (N246: "at least two
         confident moments"; "go for the next confident moment"; "Two best
         + level").
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

    # The three highest moments are shown (N284) and the voice decides each
    # (founder 2026-10-20): all reach the floor, so all are praised and
    # nothing is corrected; the highest is marked. Every other block is
    # written False.
    assert [b["most_confident"] for b in blocks] == [
        True, True, False, False, False, False, False, True, False, False]
    assert [b["highest_moment"] for b in blocks] == [
        True, False, False, False, False, False, False, False, False, False]
    assert not any(b["carries_exercise"] for b in blocks)
    assert sum(b["practice_prompt"] for b in blocks) == 0

    # Praise anchors only on praised moments, from inside the block; the
    # praised slide 1 and the third moment have no note inside them, and
    # say so (the walk's line bank covers it). Nothing is corrected, so no rewrite anchors.
    lanes = frame["verbal_lanes"]
    rewrite, praise = lanes["rewrite_clarity"], lanes["great_formulation"]
    assert rewrite["selected_candidate_ids"] == []
    assert rewrite["outcome"] == "no_defensible_candidate"
    assert praise["selected_candidate_ids"] == ["p-best"]
    assert praise["anchors"] == [
        {"block_id": by_slide[0][0]["block_id"], "candidate_id": "p-best"}]
    assert praise["blocks_without_note"] == [
        {"block_id": by_slide[1][0]["block_id"], "reason": "no_defensible_candidate"},
        {"block_id": blocks[7]["block_id"], "reason": "no_defensible_candidate"}]

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
    assert routed == [(1, "clearer"), (2, "voice")]
    assert frame["verbal_lanes"]["rewrite_clarity"]["selected_candidate_ids"] == ["r-clip"]

    # The tentative fallback never opens it: the same moment, the voice Exercise.
    fallback = _practise_frame({"tentative": True,
                                "_manager_evidence": {"specificity": 5, "fallback": True}})
    routed = [(b["slide_index"], b["exercise_kind"]) for b in fallback["blocks"] if b["carries_exercise"]]
    assert routed == [(1, "voice"), (2, "voice")]
    assert fallback["verbal_lanes"]["rewrite_clarity"]["selected_candidate_ids"] == []

    # A voice that cleared the floor is never sent to the voice exercise
    # (N108): with no rewrite that passes, it is praised.
    strong = _practise_frame({"tentative": True,
                              "_manager_evidence": {"specificity": 5, "fallback": True}},
                             scores=(0.9, 0.5, -0.6))
    # Only the third, whose voice is under the floor, is corrected.
    assert [b["slide_index"] for b in strong["blocks"] if b["carries_exercise"]] == [2]
    assert sorted(b["slide_index"] for b in strong["blocks"] if b["most_confident"]) == [0, 1]

    # Ums only the transcript heard (N121): the words on screen are clean,
    # so a "rewrite" of them fixes nothing and the voice exercise opens.
    clean = "We cut onboarding from three weeks to four days for all"
    unseen = _practise_frame({"quote": clean, "proposed_text": clean + "."}, shown=clean)
    assert [(b["slide_index"], b["exercise_kind"]) for b in unseen["blocks"]
            if b["carries_exercise"]] == [(1, "voice"), (2, "voice")]
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
                if b["carries_exercise"]] == [(1, "clearer"), (2, "voice")], said
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
    # A Take frozen with the softer clip, the one it showed, keeps that one
    # too: read again, the block never swaps in the louder clip, which the
    # frozen set would filter off the page.
    kept = _two_clip_frame(select_servable=True, frozen_candidate_ids={
        softer, "relative-confidence:take-2:p0", "relative-confidence:take-2:p2"})
    assert slide_1(kept) == (softer, [softer], True)


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
    # Both are shown, each in a block of its own, and slide 0 as the third.
    assert _moments(frame) == [(_clip("a0"), False), (_clip("b3"), True), (_clip("b5"), False)]
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


def test_a_short_take_still_shows_two_moments():
    """Founder 2026-10-28 (N246 item 1: "I've seen only one confident
    moment"): with no cut keeping 40 to 120 words a side, the blocks stayed
    as they were, and a Take whose clips all sat in one block showed one
    moment. With another block to show, they still stay: the Take shows
    two (N128)."""
    # f3 and f4 share slide 0's second block, and only 30 words follow f3.
    tight = _clips(("f0", 0, 25, -0.6), ("f1", 0, 25, -0.6), ("f2", 0, 25, -0.6),
                   ("f3", 0, 45, 0.9), ("f4", 0, 30, 0.8))
    # g1 and g2 are slide 1's one block; the cut before it is a slide's.
    across = _clips(("g0", 0, 75, -0.6), ("g1", 1, 30, 0.9), ("g2", 1, 45, 0.8))
    for take, plain in ((tight, _rescored(tight, f0=0.9, f3=-0.6)),
                        (across, _rescored(across, g0=0.9, g1=-0.6))):
        frame, before = _clips_frame(take), _clips_frame(plain)
        assert (_cut(frame), _ids(frame)) == (_cut(before), _ids(before)), take
        assert len(_moments(frame)) == 2
    # The only block with a clip that can be played: it is cut between the
    # two, at its most even boundary, the same way every time.
    alone = _rescored(across, g0=None)
    # h0 and h1 are a one-block Take of 60 words: no half reaches 40.
    halves = _clips(("h0", 0, 30, 0.9), ("h1", 0, 30, 0.8))
    apart = _clips(("i0", 0, 10, 0.9), ("i1", 0, 20, -0.6), ("i2", 0, 15, -0.6),
                   ("i3", 0, 10, 0.8))
    for take, cut, best in (
            (alone, [(0, 75, None), (1, 30, "moment_split"), (1, 45, "moment_split")], "g1 g2"),
            (halves, [(0, 30, "moment_split"), (0, 30, "moment_split")], "h0 h1"),
            (apart, [(0, 30, "moment_split"), (0, 25, "moment_split")], "i0 i3")):
        frame = _clips_frame(take)
        assert _cut(frame) == cut, take
        assert [clip for clip, _ in _moments(frame)] == [_clip(sid) for sid in best.split()]
        assert _clips_frame(take)["blocks"] == frame["blocks"]
    # The cut in range stays the first choice: ten more words after f3, or
    # g0 on slide 1, and the neighbour's cut moves.
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
    assert _moments(served) == [(_clip("a0"), False), (_clip("b3"), True), (_clip("b5"), False)]

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
            if b["carries_exercise"]] == [(1, "clearer"), (2, "voice")]
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
            if b["most_confident"] or b["carries_exercise"]] == [(0, True), (1, False), (2, False)]
    assert not any(b["confident_practice"] for b in strong["blocks"] if not b["most_confident"])


# ── on a plan, one moment is where the level shows (G7, N209) ────────────

def _paced_frame(wpms, **options):
    """Four slides, one clip each: p0 the best by far, p1 the second best,
    p3 the third, p2 the last; each clip said at its own pace."""
    scores = (0.95, 0.8, -0.2, 0.3)
    pieces, snippets, at = [], [], 0
    for index, (score, wpm) in enumerate(zip(scores, wpms)):
        sid = f"p{index}"
        text = " ".join(f"{sid}x{n}" for n in range(75)) + "."
        pieces.append({"snippet_id": sid, "take_session_id": "take-2", "slide_index": index,
                       "start": at, "end": at + len(text), "text": text,
                       "recording_id": "recording-1", "start_offset_ms": index * 5000,
                       "duration_ms": 5000})
        at += len(text) + 1
        snippets.append({"id": sid, "session_id": "take-2", "recording_id": "recording-1",
                         "start_offset_ms": index * 5000, "duration_ms": 5000,
                         "metrics": {"wpm": wpm, "voice_confidence": {
                             "version": "voice-confidence-universal-v3", "score": score}}})
    served = " ".join(piece["text"] for piece in pieces)
    return build_shadow_frame(
        take_document={"take_session_id": "take-2", "text": served, "pieces": pieces},
        snippets=snippets, suggestions={}, feedback_candidates=[],
        take_index=2, expected_recording_id="recording-1", served_text=served, **options)


def _walk(frame):
    return [(b["selected_candidate_id"].rsplit(":", 1)[-1], b["most_confident"],
             b["exercise_kind"], b.get("plan_level"))
            for b in frame["blocks"] if b["most_confident"] or b["carries_exercise"]]


def test_on_a_plan_i_get_my_three_best_and_my_level():
    rushed = (140, 140, 140, 200)  # p3 is said far faster than the speaker's own usual
    best = [("p0", True, None, None), ("p1", True, None, None), ("p3", True, None, None)]
    assert _walk(_paced_frame(rushed)) == best
    # The level shows most on one of the three: that one is practised with
    # the level's own practice, and there is no fourth.
    assert _walk(_paced_frame(rushed, plan_level="key_line")) == [
        *best[:2], ("p3", False, "voice", "key_line")]
    assert _walk(_paced_frame((140, 200, 140, 140), plan_level="key_line")) == [
        ("p0", True, None, None), ("p1", False, "voice", "key_line"), ("p3", True, None, None)]
    # The level shows on p2: the three best, and p2 practised as well (N246
    # item 3, N284).
    assert _walk(_paced_frame((140, 140, 200, 140), plan_level="key_line")) == [
        *best[:2], ("p2", False, "voice", "key_line"), best[2]]
    # No clip shows the level: the three best.
    even = (140, 141, 139, 140)
    assert _walk(_paced_frame(even, plan_level="key_line")) == best


def test_a_sentence_with_my_helper_words_gives_way_to_the_next():
    """Founder 2026-10-28 (N246 item 2): "if there is already a confident
    moment and helper words, go for the next confident moment"."""
    from services.slide_helper_words import held_at_take

    take = _clips(("q0", 0, 75, 0.95), ("q1", 1, 75, 0.8), ("q2", 2, 75, 0.5),
                  ("q3", 3, 75, 0.3))

    def shown(**options):
        return [clip for clip, _ in _moments(_clips_frame(take, **options))]

    assert shown() == [_clip("q0"), _clip("q1"), _clip("q2")]

    class Log:
        """Slide 0's locked sets: one from before the Take, one picked in
        its walk."""
        def list_slide_helper_words_log_for_slides(self, arc_id, user_id, slides):
            return {0: [{"phrases": ["Q0x3 q0x4 · q0x10,"], "created_at": "2026-10-28T09:00:00Z"},
                        {"phrases": ["q0x60"], "created_at": "2026-10-28T10:30:00Z"}],
                    1: [], 2: []}

    held = held_at_take(Log(), "arc", "user", {"created_at": "2026-10-28T10:00:00+00:00"},
                        {0, 1, 2})
    assert held == {0: ["Q0x3 q0x4 · q0x10,"]}
    # q0 says slide 0's helper words: the next three are shown.
    assert shown(held_words=held) == [_clip("q1"), _clip("q2"), _clip("q3")]
    # The same words on another slide, or words it does not say in order,
    # change nothing.
    assert shown(held_words={1: ["q0x3 q0x4"]}) == [_clip("q0"), _clip("q1"), _clip("q2")]
    assert shown(held_words={0: ["q0x10 · q0x3"]}) == [_clip("q0"), _clip("q1"), _clip("q2")]
    # Still shown when the Take has nothing else.
    assert [clip for clip, _ in _moments(_clips_frame(take[:2], held_words=held))] == [
        _clip("q0"), _clip("q1")]
