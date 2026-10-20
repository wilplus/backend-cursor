"""
STORY    As a speaker, I want each Take to show my two best moments and, for
         each, either praise or one thing to practise, decided by how that
         moment sounded, so that a strong Take is praised twice and a weak
         one gets help twice, never praise for show.
OUTCOME
  O1  The two highest moments are shown, at most one per slide (a clip with
      enough words before a short one); each at or above the floor is
      praised and each below it is corrected; the highest is marked.
  O2  Both strong: two praises and no practise. Both weak: two corrections,
      each by its own words (a clearer version when its words need help,
      else the voice exercise).
  O3  When no sound was read, the words alone order the clips, and both
      shown moments are corrected.
PROVES   O1 -> test_the_two_highest_moments_are_shown_one_strong_one_weak
         O2 -> test_both_strong_is_two_praises_and_both_weak_is_two_corrections
         O3 -> test_with_no_sound_read_the_words_order_the_clips_and_both_are_corrected
WHY      Founder 2026-10-20 ("the score decides each", flow page C2, C4, H1);
         founder lock 2026-10-12 section 6; founder 2026-10-17 and 2026-10-18.
"""
from services.moment_pick import pick, read


def _row(block, slide, value, *, words=12, s=None, w=None, help=None):
    s = value if s is None else s
    w = 1.0 if w is None else w
    return {"block_id": block, "slide_index": slide, "word_count": words,
            "read": {"s": s, "w": w, "value": value, "words_help": help}}


def _shown(picked):
    return [(m["block_id"], m["praise"], m["kind"], m["highest"]) for m in picked["shown"]]


def test_the_two_highest_moments_are_shown_one_strong_one_weak():
    reads = [_row("a", 0, 0.5, help="fillers"), _row("a2", 0, 0.3), _row("b", 1, 0.45),
             _row("c", 2, 0.2), _row("d", 3, 0.95), _row("short", 4, 0.99, words=3),
             _row("low", 5, 0.1, s=0.8, w=0.125)]
    # The best per slide, ranked: d (praised), then a (below the floor, its
    # words need help: a clearer version). The short clip is its slide's only
    # clip, so it is that slide's best, but it ranks third. One per slide:
    # a2 is never shown beside a.
    assert _shown(pick(reads)) == [("d", True, None, True), ("a", False, "clearer", False)]


def test_both_strong_is_two_praises_and_both_weak_is_two_corrections():
    strong = pick([_row("a", 0, 0.9), _row("b", 1, 0.7), _row("c", 2, 0.65)])
    assert _shown(strong) == [("a", True, None, True), ("b", True, None, False)]
    weak = pick([_row("a", 0, 0.4), _row("b", 1, 0.5, help="hedges"), _row("c", 2, 0.1)])
    assert _shown(weak) == [("b", False, "clearer", True), ("a", False, "voice", False)]
    # A Take with one slide shows one moment, by its own score.
    assert _shown(pick([_row("a", 0, 0.9), _row("a2", 0, 0.8)])) == [("a", True, None, True)]
    # A moment too short to count is never praised; it is corrected.
    assert _shown(pick([_row("s", 0, 0.99, words=3)])) == [("s", False, "voice", True)]


def test_with_no_sound_read_the_words_order_the_clips_and_both_are_corrected():
    """Founder 2026-10-17: a clip never stamped with a sound read is not
    dropped; its words alone order it. Such a clip is below the floor by
    construction, so under the 2026-10-20 rule it is corrected, the hedged
    one as a clearer version."""
    clean = read(None, "we think the timing matters because the window closes once", {})
    hedged = read(None, "um so I guess maybe we sort of kind of think it matters", {})
    assert clean["sound"] is False and clean["s"] == 0.5
    assert read(1.0, None, {})["value"] == 1.0 and read(1.0, None, {})["sound"] is True
    picked = pick([{"block_id": "a", "slide_index": 0, "word_count": 11, "read": hedged},
                   {"block_id": "b", "slide_index": 1, "word_count": 11, "read": clean}])
    assert [(m["block_id"], m["praise"]) for m in picked["shown"]] == [("b", False), ("a", False)]
    assert picked["shown"][0]["highest"] and picked["shown"][1]["kind"] == "clearer"
