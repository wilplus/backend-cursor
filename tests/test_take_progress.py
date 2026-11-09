"""
STORY    As the founder, I want to see whether a speaker is really getting
         better and whether each fix the walk gave worked, so that I know the
         moments and interventions we pick move them forward.
OUTCOME
  O1  A speaker's progress is read against their own first Takes, frozen:
      a later Take that sounds stronger than those reads higher, even when
      it is no stronger than their recent Takes; with too few first Takes
      it is not measured.
  O2  The fixes a Take gave (the weakest and the one between) are each
      marked came back or gone on the next Take of the talk, same slide; not
      measured when that slide is not in it.
  O3  The One thing walk opens with the last Take's fix when it rose
      (N309): its kind and slide, and this Take's best clip there, played
      by a signed link; nothing when it came back or there is no Take
      before.
  O4  The pace game's fix worked when every clip on that slide in the next
      Take stays inside the green on the side the stretch leaned, the bar
      that picks a stretch: the Takes table marks it gone and the walk opens
      with it as the last fix; slower but still outside the green, it came
      back and nothing is said (N347 item 3, N350 item 3). Where it worked,
      the walk offers no tempo step on that slide again (N359). A slow
      stretch off a pace or pause week was never the Sniper, so it is no
      fix the walk gave (N323 item 6).
  O5  The next walk knows where in the talk the last one praised and
      fixed, its beginning, middle or ending, so its own praise and fix
      move through the talk (N546).
  O6  A fix counts as given only when the walk opened it on screen: Last
      time never names a fix I never saw, and names it by what I saw (the
      voice Exercise when its lost Clearer version gave it its place); with
      the walk's record unreadable, the frame's fixes stand (the audit's
      3.4).
PROVES   O1 -> test_progress_is_read_against_my_first_takes
         O2 -> test_each_fix_is_marked_came_back_or_gone_on_the_next_take
         O3 -> test_last_time_plays_the_fix_that_rose_on_this_take
         O4 -> test_the_pace_fix_worked_when_that_slide_stays_inside_the_green
         O5 -> test_the_next_walk_knows_where_the_last_one_praised_and_fixed
         O6 -> test_a_fix_i_never_saw_is_not_one_the_walk_gave
WHY      Founder 2026-10-31 (N291: "yes"; "ok go with the proposal"; N290:
         "the next time it chooses a moment it should take into account
         what the user answered"; N309 item 1: "Last time: {the tip}. You
         did."; N347 item 3: "Every fix gets its Last time, the pace game
         too"; N350 item 3: one rule for "the pace fix worked"; N359: "once
         a fix has worked on a slide, the walk stops picking the same issue
         on that slide, and picks it again only if it comes back");
         2026-11-06 (N546: "if I had already the ending praised I should
         have the beginning corrected").
"""
from unittest.mock import patch

from services.take_progress import (CAME_BACK, GONE, NOT_MEASURED, anchored_willfidence,
                                    fixes_of, frozen_reference, last_fix, outcome,
                                    pace_worked, walk_gave, walk_parts)

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


def test_the_pace_fix_worked_when_that_slide_stays_inside_the_green():
    # The last walk fixed no moment: its fix was the pace game, on slide 2,
    # where thirty seconds ran on without a pause.
    before = _frame({"slide_index": 1, "walk_slot": "strongest", "carries_exercise": False, "snippet_ids": ["a"]},
                    {"slide_index": 2, "carries_exercise": False, "snippet_ids": ["b"]})
    now = _frame({"slide_index": 1, "snippet_ids": ["n1"]}, {"slide_index": 2, "snippet_ids": ["n2"]})
    calm, end = _spoken("a", 0, 8, word_s=0.3, gap_s=0.5)
    rushed, _ = _spoken("b", end + 1, 120, word_s=0.2, gap_s=0.05)
    calm_now, end = _spoken("n1", 0, 8, word_s=0.3, gap_s=0.5)
    inside, _ = _spoken("n2", end + 1, 60, word_s=0.3, gap_s=0.3)
    still_out, _ = _spoken("n2", end + 1, 90, word_s=0.2, gap_s=0.1)
    (fix,) = fixes_of(before, [calm, rushed])
    assert (fix["kind"], fix["slide_index"]) == ("tempo", 2)

    class Db:
        def __init__(self, clips, said_before=(calm, rushed)):
            self.clips, self.said_before = clips, list(said_before)

        def get_v4_dark_frame(self, take):
            return {"t1": before, "t2": now}.get(take)

        def get_snippets_by_session(self, take):
            return {"t1": self.said_before, "t2": self.clips}.get(take, [])

        def v2_get_session_by_id(self, take):
            return {"id": take}           # on no plan

    with patch("services.audio_ref_resolver.resolve_playable_ref",
               lambda ref, expires_in=None, **_: f"https://signed.example/{ref}"):
        # Slide 2 back inside the green: the fix worked, in the Takes table
        # and in the walk, played with this Take's clip there.
        assert outcome(fix, now, [calm_now, inside]) == GONE
        last = last_fix(Db([calm_now, inside]), "t2", "t1")
        assert (last["kind"], last["slide_index"], last["clip"]["snippet_id"]) == ("tempo", 2, "n2")
        # Slower than before but still past the green: it came back, and
        # nothing is said.
        assert outcome(fix, now, [calm_now, still_out]) == CAME_BACK
        assert last_fix(Db([calm_now, still_out]), "t2", "t1") is None

    # It worked, and this Take's stretch is on slide 2 again, slow now: the
    # walk offers no tempo step there (N359). Still rushed there, it does,
    # and with no Take before, nothing changes.
    talk = [{"id": "t1", "take_index": 1}, {"id": "t2", "take_index": 2}]
    slow, _ = _spoken("n2", end + 1, 12, word_s=0.3, gap_s=6.0)
    assert pace_worked(Db([calm_now, slow]), talk, "t2") is True
    assert pace_worked(Db([calm_now, still_out]), talk, "t2") is False
    assert pace_worked(Db([calm_now, slow]), talk[1:], "t2") is False

    # The last walk's stretch ran slow, off a pace or pause week: it was not
    # the Sniper (N323 item 6), so it is no fix that walk gave. Nothing is
    # said, and the tempo step stays on that slide.
    slow_before, _ = _spoken("b", end + 1, 12, word_s=0.3, gap_s=6.0)
    with patch("services.audio_ref_resolver.resolve_playable_ref",
               lambda ref, expires_in=None, **_: f"https://signed.example/{ref}"):
        assert last_fix(Db([calm_now, inside], said_before=(calm, slow_before)), "t2", "t1") is None
    assert pace_worked(Db([calm_now, slow], said_before=(calm, slow_before)), talk, "t2") is False


def test_the_next_walk_knows_where_the_last_one_praised_and_fixed():
    # Six paragraphs: the ending praised, the beginning's AI clip the fix,
    # and the pace game on slide 1, in the middle.
    blocks = [{"slide_index": 0, "carries_exercise": True, "exercise_kind": "voice"},
              {"slide_index": 0}, {"slide_index": 1}, {"slide_index": 1},
              {"slide_index": 2}, {"slide_index": 2, "highest_moment": True}]
    fixes = [{"slide_index": 0, "kind": "voice"}, {"slide_index": 1, "kind": "tempo"}]
    assert walk_parts({"blocks": blocks}, fixes) == {"praise": 2, "fix": {0, 1}}
    # Nothing given: nothing known, and the walk picks as it always did.
    assert walk_parts({"blocks": []}, []) == {}


def test_a_fix_i_never_saw_is_not_one_the_walk_gave():
    take = _frame({"slide_index": 1, "walk_slot": "strongest", "carries_exercise": False,
                   "one_fix": "moment", "snippet_ids": ["a"]},
                  {"slide_index": 2, "walk_slot": "between", "carries_exercise": True,
                   "exercise_kind": "clearer", "snippet_ids": ["b", "b2"]})

    class Db:
        def __init__(self, events):
            self.events = events

        def list_moment_events_for_take(self, take_id):
            if self.events is None:
                raise RuntimeError("down")
            return self.events

    def opened(snippet, *shown):
        return {"snippet_id": snippet, "event": "opened", "co_exposed": {"shown": list(shown)}}

    # The walk never opened the fix: it gave none, so Last time says nothing.
    assert walk_gave(Db([opened("a", "praise")]), "t1", take) == []
    # Opened as its Clearer version: the Clearer version, as the frame says.
    assert walk_gave(Db([opened("b2", "rewrite")]), "t1", take) == [
        {"slide_index": 2, "kind": "clearer"}]
    # Its Clearer version was lost and the voice Exercise took its place.
    assert walk_gave(Db([opened("b", "exercise")]), "t1", take) == [
        {"slide_index": 2, "kind": "voice"}]
    # An older record that names nothing keeps the frame's kind.
    assert walk_gave(Db([{"snippet_id": "b", "event": "opened"}]), "t1", take) == [
        {"slide_index": 2, "kind": "clearer"}]
    # The walk's record unreadable: the frame's fixes stand.
    assert walk_gave(Db(None), "t1", take) == [{"slide_index": 2, "kind": "clearer"}]
