"""
STORY    As a speaker, I want each Take to show my two most confident moments
         and, for each, either praise or one thing to practise, decided by
         how my voice sounded, so that a moment that sounded confident is
         called confident and never asked to sound more confident.
OUTCOME
  O1  The two strongest voices are shown, at most one per slide (a clip
      with enough words before a short one); the strongest is marked, even
      when weaker words put its willfidence under another moment's.
  O2  A voice at the floor is praised, even when its words pull its
      willfidence under the floor; words that need help get the clearer
      version; the voice exercise only for a voice under the floor. Both
      strong: two praises. Both weak: two corrections.
  O3  When no sound was read, the words alone order the clips, and both
      shown moments are corrected.
PROVES   O1 -> test_the_strongest_voices_are_shown_and_the_first_is_marked
         O2 -> test_a_voice_at_the_floor_is_praised_and_only_a_voice_under_it_practises
         O3 -> test_with_no_sound_read_the_words_order_the_clips_and_both_are_corrected
WHY      Founder 2026-10-21 (N108, "the voice decides", flow page C2, C4,
         H1): a moment that "was a confident moment ... even more confident
         than the first one" was told "Say this one like your confident
         moment."; founder lock 2026-10-12 section 6; founder 2026-10-17
         and 2026-10-18.
"""
from services.moment_pick import pick, read


def _row(block, slide, s, *, w=1.0, words=12, help=None, sound=True):
    return {"block_id": block, "slide_index": slide, "word_count": words,
            "read": {"s": s, "w": w, "value": s * w, "sound": sound, "words_help": help}}


def _shown(picked):
    return [(m["block_id"], m["praise"], m["kind"], m["highest"]) for m in picked["shown"]]


def test_the_strongest_voices_are_shown_and_the_first_is_marked():
    # The founder's Take: slide 2's voice was stronger, its slide point made
    # only partly; slide 1's words were cleaner. The voice decides.
    slide1 = _row("slide1", 1, 0.68)
    slide2 = _row("slide2", 2, 0.71, w=0.83)
    assert slide2["read"]["value"] < slide1["read"]["value"]
    assert _shown(pick([slide1, slide2])) == [
        ("slide2", True, None, True), ("slide1", True, None, False)]
    reads = [_row("a", 0, 0.5, help="fillers"), _row("a2", 0, 0.3), _row("b", 1, 0.45),
             _row("c", 2, 0.2), _row("d", 3, 0.95), _row("short", 4, 0.99, words=3)]
    # One per slide (a2 is never shown beside a); the short clip is its
    # slide's only clip but ranks after every clip with enough words.
    assert _shown(pick(reads)) == [("d", True, None, True), ("a", False, "clearer", False)]


def test_a_voice_at_the_floor_is_praised_and_only_a_voice_under_it_practises():
    strong = pick([_row("a", 0, 0.9), _row("b", 1, 0.62, w=0.8), _row("c", 2, 0.5)])
    assert _shown(strong) == [("a", True, None, True), ("b", True, None, False)]
    assert [m["voice_clears"] for m in strong["shown"]] == [True, True]
    # Words that need help get the clearer version whatever the voice.
    worded = pick([_row("a", 0, 0.9, help="undermining"), _row("b", 1, 0.4)])
    assert _shown(worded) == [("a", False, "clearer", True), ("b", False, "voice", False)]
    assert [m["voice_clears"] for m in worded["shown"]] == [True, False]
    # Both weak: two corrections, each by its own words.
    weak = pick([_row("a", 0, 0.5), _row("b", 1, 0.4, help="hedges"), _row("c", 2, 0.1)])
    assert _shown(weak) == [("a", False, "voice", True), ("b", False, "clearer", False)]
    # A Take with one slide shows one moment; a clip too short to count is
    # never praised.
    assert _shown(pick([_row("a", 0, 0.9), _row("a2", 0, 0.8)])) == [("a", True, None, True)]
    assert _shown(pick([_row("s", 0, 0.99, words=3)])) == [("s", False, "voice", True)]


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
