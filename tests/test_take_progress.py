"""
STORY    As the founder, I want to see whether a speaker is really getting
         better and whether each fix the walk gave worked, so that I know the
         moments and interventions we pick move them forward.
OUTCOME
  O1  A speaker's progress is read against their own first Takes, frozen:
      a later Take that sounds stronger than those reads higher, even when
      it is no stronger than their recent Takes; with too few first Takes
      it is not measured.
  O2  The fixes a Take gave (the weakest and the one between, and its tempo
      stretch) are each marked came back or gone on the next Take of the
      talk, same slide; not measured when that slide is not in it.
PROVES   O1 -> test_progress_is_read_against_my_first_takes
         O2 -> test_each_fix_is_marked_came_back_or_gone_on_the_next_take
WHY      Founder 2026-10-31 (N291: "yes"; "ok go with the proposal"; N290:
         "the next time it chooses a moment it should take into account
         what the user answered").
"""
from services.take_progress import (CAME_BACK, GONE, NOT_MEASURED, anchored_willfidence,
                                    fixes_of, frozen_reference, outcome)

_WORDS = "we made our plan clear and we will deliver it on time for everyone"


def _clip(i, *, f0_sd, dynamic_db, slide_words=_WORDS, score=None):
    metrics = {"f0_sd": f0_sd, "dynamic_db": dynamic_db, "pause_ratio": 0.2 + (i % 2) / 50,
               "pause_ms": 300 + 10 * (i % 3), "f0_mean": 180 + i % 4, "wpm": 140 + i % 5}
    if score is not None:
        metrics["voice_confidence"] = {"version": "voice-confidence-universal-v3", "score": score}
    return {"id": f"c{i}", "transcript": slide_words, "metrics": metrics}


def test_progress_is_read_against_my_first_takes():
    # First Takes: a flat voice, a little variation from clip to clip.
    first = [[_clip(i, f0_sd=20 + i % 3, dynamic_db=8 + i % 2)["metrics"] for i in range(5)]
             for _ in range(2)]
    reference = frozen_reference(first)
    assert reference
    flat = [_clip(i, f0_sd=21, dynamic_db=8.5) for i in range(4)]
    lively = [_clip(i, f0_sd=40, dynamic_db=16) for i in range(4)]
    assert anchored_willfidence(lively, reference) > anchored_willfidence(flat, reference)
    # Too few first clips: not measured.
    assert frozen_reference([[first[0][0]]]) is None
    assert anchored_willfidence(lively, None) is None


def _frame(*blocks):
    return {"blocks": [dict(b) for b in blocks]}


def test_each_fix_is_marked_came_back_or_gone_on_the_next_take():
    take = _frame({"slide_index": 1, "walk_slot": "strongest", "carries_exercise": False, "snippet_ids": ["a"]},
                  {"slide_index": 2, "walk_slot": "weakest", "carries_exercise": True,
                   "exercise_kind": "voice", "snippet_ids": ["b"]},
                  {"slide_index": 3, "walk_slot": "between", "carries_exercise": True,
                   "exercise_kind": "clearer", "snippet_ids": ["c"]})
    fixes = fixes_of(take, [])
    assert fixes == [{"slide_index": 2, "kind": "voice"}, {"slide_index": 3, "kind": "clearer"}]
    # The next Take: slide 2's voice now clears the floor; slide 3 still hedges.
    nxt = _frame({"slide_index": 2, "snippet_ids": ["n2"]}, {"slide_index": 3, "snippet_ids": ["n3"]})
    strong = _clip(2, f0_sd=30, dynamic_db=12, score=0.8)
    strong["id"] = "n2"
    hedged = _clip(3, f0_sd=30, dynamic_db=12, score=0.8,
                   slide_words="I think maybe we sort of kind of could perhaps start soon")
    hedged["id"] = "n3"
    assert outcome(fixes[0], nxt, [strong, hedged]) == GONE
    assert outcome(fixes[1], nxt, [strong, hedged]) == CAME_BACK
    # The voice still under the floor on slide 2: came back.
    weak = {**strong, "metrics": {**strong["metrics"], "voice_confidence": {
        "version": "voice-confidence-universal-v3", "score": -0.6}}}
    assert outcome(fixes[0], nxt, [weak, hedged]) == CAME_BACK
    # No next Take, or the slide not in it: not measured.
    assert outcome(fixes[0], None, []) == NOT_MEASURED
    assert outcome({"slide_index": 9, "kind": "voice"}, nxt, [strong, hedged]) == NOT_MEASURED
