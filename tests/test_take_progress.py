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
  O3  The One thing walk opens with the last Take's fix when it rose
      (N309): its kind and slide, and this Take's best clip there, played
      by a signed link; nothing when it came back or there is no Take
      before.
  O4  When the last walk's fix was the pace game, it rose when that slide
      came out slower in this Take, read as the tempo step reads it, and
      the walk opens with it the same way; nothing when it did not
      (N347 item 3).
PROVES   O1 -> test_progress_is_read_against_my_first_takes
         O2 -> test_each_fix_is_marked_came_back_or_gone_on_the_next_take
         O3 -> test_last_time_plays_the_fix_that_rose_on_this_take
         O4 -> test_last_time_after_the_pace_game_when_that_slide_came_out_slower
WHY      Founder 2026-10-31 (N291: "yes"; "ok go with the proposal"; N290:
         "the next time it chooses a moment it should take into account
         what the user answered"; N309 item 1: "Last time: {the tip}. You
         did."; N347 item 3: "Every fix gets its Last time, the pace game
         too").
"""
from unittest.mock import patch

from services.take_progress import (CAME_BACK, GONE, NOT_MEASURED, anchored_willfidence,
                                    fixes_of, frozen_reference, last_fix, outcome)

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


def test_last_time_plays_the_fix_that_rose_on_this_take():
    before = _frame({"slide_index": 1, "walk_slot": "strongest", "carries_exercise": False, "snippet_ids": ["a"]},
                    {"slide_index": 2, "walk_slot": "weakest", "carries_exercise": True,
                     "exercise_kind": "voice", "snippet_ids": ["b"]})
    now = _frame({"slide_index": 2, "snippet_ids": ["n2", "n2b"]})
    strong = {**_clip(2, f0_sd=30, dynamic_db=12, score=0.8), "id": "n2",
              "audio_segment_path": "takes/n2.webm", "start_offset_ms": 4000, "duration_ms": 3000}
    short = {**_clip(5, f0_sd=30, dynamic_db=12, score=0.9, slide_words="yes we did"), "id": "n2b",
             "audio_segment_path": "takes/n2b.webm"}

    class Db:
        def __init__(self, clips):
            self.clips = clips

        def get_v4_dark_frame(self, take):
            return {"t1": before, "t2": now}.get(take)

        def get_snippets_by_session(self, take):
            return self.clips if take == "t2" else []

    with patch("services.audio_ref_resolver.resolve_playable_ref",
               lambda ref, expires_in=None, **_: f"https://signed.example/{ref}"):
        # Slide 2's voice now clears the floor: the fix rose, played with
        # this Take's best clip on that slide (a whole thought first).
        assert last_fix(Db([strong, short]), "t2", "t1") == {
            "kind": "voice", "slide_index": 2,
            "clip": {"snippet_id": "n2", "url": "https://signed.example/takes/n2.webm",
                     "start_offset_ms": 4000, "duration_ms": 3000}}
        # Still under the floor: it came back, and nothing is said.
        weak = {**strong, "metrics": {**strong["metrics"], "voice_confidence": {
            "version": "voice-confidence-universal-v3", "score": -0.6}}}
        assert last_fix(Db([weak]), "t2", "t1") is None
        # The first Take has none before it.
        assert last_fix(Db([strong]), "t2", None) is None


def _spoken(clip_id, start, n, *, word_s, gap_s, slide_words=_WORDS):
    """A clip of ``n`` timed words from ``start`` seconds; the end."""
    words, t = [], start
    for _ in range(n):
        words.append({"start": round(t, 3), "end": round(t + word_s, 3)})
        t += word_s + gap_s
    clip = {**_clip(1, f0_sd=30, dynamic_db=12, score=0.8, slide_words=slide_words), "id": clip_id,
            "words": words, "audio_segment_path": f"takes/{clip_id}.webm"}
    return clip, t


def test_last_time_after_the_pace_game_when_that_slide_came_out_slower():
    # The last walk fixed no moment: its fix was the pace game, on slide 2,
    # where thirty seconds ran on without a pause.
    before = _frame({"slide_index": 1, "walk_slot": "strongest", "carries_exercise": False, "snippet_ids": ["a"]},
                    {"slide_index": 2, "carries_exercise": False, "snippet_ids": ["b"]})
    now = _frame({"slide_index": 1, "snippet_ids": ["n1"]}, {"slide_index": 2, "snippet_ids": ["n2"]})
    calm, end = _spoken("a", 0, 8, word_s=0.3, gap_s=0.5)
    rushed, _ = _spoken("b", end + 1, 120, word_s=0.2, gap_s=0.05)
    calm_now, end = _spoken("n1", 0, 8, word_s=0.3, gap_s=0.5)
    slower, _ = _spoken("n2", end + 1, 60, word_s=0.3, gap_s=0.3)
    same, _ = _spoken("n2", end + 1, 120, word_s=0.2, gap_s=0.05)

    class Db:
        def __init__(self, clips):
            self.clips = clips

        def get_v4_dark_frame(self, take):
            return {"t1": before, "t2": now}.get(take)

        def get_snippets_by_session(self, take):
            return {"t1": [calm, rushed], "t2": self.clips}.get(take, [])

    with patch("services.audio_ref_resolver.resolve_playable_ref",
               lambda ref, expires_in=None, **_: f"https://signed.example/{ref}"):
        # Slide 2 came out slower: the pace game rose, played with this
        # Take's clip there.
        last = last_fix(Db([calm_now, slower]), "t2", "t1")
        assert (last["kind"], last["slide_index"], last["clip"]["snippet_id"]) == ("tempo", 2, "n2")
        # As rushed as before: nothing is said.
        assert last_fix(Db([calm_now, same]), "t2", "t1") is None
