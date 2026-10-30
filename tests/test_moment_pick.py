"""
STORY    As a speaker, I want each Take to show my three best moments by
         willfidence, from any slide, and the stronger voice of them called
         my most confident, so that I always get at least two moments to
         practise and a confident voice is never asked to sound confident.
OUTCOME
  O1  The three highest willfidence clips are shown, however low, one per
      block, several on one slide allowed; a clip with enough words comes
      before a short one; fewer only with fewer clips.
  O2  Of those shown, the stronger voice is marked most confident, even when
      its willfidence is the lower.
  O3  The voice decides each: at the floor praised (the Clearer version
      when the words need help), under it corrected.
  O4  With no sound read the words order the clips, and both are
      corrected.
  O5  A sentence that already has my helper words is not picked again: I
      get the next best one, and it comes back only when nothing else can
      be shown.
PROVES   O1 -> test_the_three_best_by_willfidence_are_shown_from_any_slide
         O2 -> test_the_stronger_voice_shown_is_the_most_confident
         O3 -> test_a_voice_at_the_floor_is_praised_and_only_a_voice_under_it_practises
         O4 -> test_with_no_sound_read_the_words_order_the_clips_and_both_are_corrected
         O5 -> test_a_sentence_with_my_helper_words_gives_way_to_the_next
WHY      Founder 2026-10-23 (N118 "minimum 2, best two"; N122 "S×W picks,
         voice names top"); 2026-10-21 (N108, "the voice decides");
         2026-10-28 (N246, "go for the next confident moment");
         2026-10-30 (N284, "we need more moments at least 2", "Best three").
"""
from services.moment_pick import pick, read


def _row(block, slide, s, *, w=1.0, words=12, help=None, sound=True, clip=None):
    return {"block_id": block, "slide_index": slide, "word_count": words,
            "candidate_id": clip or f"{block}-clip",
            "read": {"s": s, "w": w, "value": s * w, "sound": sound, "words_help": help}}


def _blocks(picked):
    return [m["block_id"] for m in picked["shown"]]


def _shown(picked):
    return [(m["block_id"], m["praise"], m["kind"], m["highest"]) for m in picked["shown"]]


def test_the_three_best_by_willfidence_are_shown_from_any_slide():
    # Three on one long slide: all its blocks beat the other slide.
    assert _blocks(pick([_row("a", 0, 0.8), _row("b", 0, 0.7), _row("c", 0, 0.6),
                         _row("d", 1, 0.5)])) == ["a", "b", "c"]
    # One per block: a block's best clip by willfidence stands for it, and
    # its second clip is never shown beside it.
    picked = pick([_row("a", 0, 0.9, clip="a1", w=0.5), _row("a", 0, 0.8, clip="a2"),
                   _row("b", 1, 0.3, clip="b1")])
    assert [(m["block_id"], m["candidate_id"]) for m in picked["shown"]] == [("a", "a2"), ("b", "b1")]
    # However low: a Take that sounds weak everywhere still shows two.
    weak = pick([_row("a", 0, 0.1), _row("b", 1, 0.05, w=0.5), _row("c", 2, 0.02)])
    assert _shown(weak) == [("a", False, "voice", True), ("b", False, "voice", False),
                            ("c", False, "voice", False)]
    # Willfidence picks: cleaner words can put a softer voice first.
    picked = pick([_row("loud", 0, 0.9, w=0.3), _row("clean", 1, 0.7), _row("mid", 2, 0.5),
                   _row("low", 3, 0.4)])
    assert _blocks(picked) == ["clean", "mid", "low"]
    # A clip with enough words comes before a short one; fewer than three
    # only when the Take has fewer clips.
    assert _blocks(pick([_row("short", 0, 0.99, words=3), _row("x", 1, 0.2),
                         _row("y", 2, 0.1), _row("z", 3, 0.05)])) == ["x", "y", "z"]
    assert _shown(pick([_row("s", 0, 0.99, words=3)])) == [("s", False, "voice", True)]


def test_the_stronger_voice_shown_is_the_most_confident():
    # The founder's Take: slide 2's voice was stronger, its slide point made
    # only partly; slide 1's words were cleaner, so slide 1 ranks first and
    # slide 2 is still called the most confident.
    slide1 = _row("slide1", 1, 0.68)
    slide2 = _row("slide2", 2, 0.71, w=0.83)
    assert slide2["read"]["value"] < slide1["read"]["value"]
    assert _shown(pick([slide1, slide2, _row("c", 3, 0.5)])) == [
        ("slide1", True, None, False), ("slide2", True, None, True),
        ("c", False, "voice", False)]


def test_a_voice_at_the_floor_is_praised_and_only_a_voice_under_it_practises():
    strong = pick([_row("a", 0, 0.9), _row("b", 1, 0.62, w=0.9), _row("c", 2, 0.5)])
    assert _shown(strong) == [("a", True, None, True), ("b", True, None, False),
                              ("c", False, "voice", False)]
    assert [m["voice_clears"] for m in strong["shown"]] == [True, True, False]
    # Words that need help get the clearer version whatever the voice.
    worded = pick([_row("a", 0, 0.9, help="undermining"), _row("b", 1, 0.4)])
    assert _shown(worded) == [("a", False, "clearer", True), ("b", False, "voice", False)]
    assert [m["voice_clears"] for m in worded["shown"]] == [True, False]
    # Both weak: two corrections, each by its own words.
    weak = pick([_row("a", 0, 0.5), _row("b", 1, 0.4, help="hedges"), _row("c", 2, 0.1)])
    assert _shown(weak) == [("a", False, "voice", True), ("b", False, "clearer", False),
                            ("c", False, "voice", False)]
    # A clip too short to count is never praised.
    assert _shown(pick([_row("s", 0, 0.99, words=3), _row("t", 1, 0.2)]))[1] == (
        "s", False, "voice", False)


def test_with_no_sound_read_the_words_order_the_clips_and_both_are_corrected():
    """Founder 2026-10-17: a clip never stamped with a sound read is not
    dropped; its words alone order it. Such a clip is below the floor by
    construction, so it is corrected, the hedged one as a clearer version."""
    clean = read(None, "we think the timing matters because the window closes once", {})
    hedged = read(None, "um so I guess maybe we sort of kind of think it matters", {})
    assert clean["sound"] is False and clean["s"] == 0.5
    assert read(1.0, None, {})["value"] == 1.0 and read(1.0, None, {})["sound"] is True
    picked = pick([{"block_id": "a", "slide_index": 0, "word_count": 11, "read": hedged},
                   {"block_id": "b", "slide_index": 1, "word_count": 11, "read": clean}])
    assert [(m["block_id"], m["praise"]) for m in picked["shown"]] == [("b", False), ("a", False)]
    assert picked["shown"][0]["highest"] and picked["shown"][1]["kind"] == "clearer"


def test_a_sentence_with_my_helper_words_gives_way_to_the_next():
    held = {**_row("a", 0, 0.9), "held": True}
    assert _blocks(pick([held, _row("b", 1, 0.7), _row("c", 2, 0.6),
                         _row("d", 3, 0.5)])) == ["b", "c", "d"]
    # Still shown when the Take has nothing else, and still the stronger voice.
    assert _shown(pick([held, _row("b", 1, 0.7)])) == [
        ("b", True, None, False), ("a", True, None, True)]
