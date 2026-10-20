"""
STORY    As a speaker, I want each Take to show one moment to be proud of and the
         next-best one to practise, so that feedback always gives me praise and
         a next step.
OUTCOME
  O1  The best moment is the praise and the second best (long enough to
      count) is the exercise; if its words need help, it opens on a clearer
      version.
  O2  When no moment is strong enough, the single best is shown softly as the
      praise and the next one is a voice exercise.
  O3  When no sound was read, the words alone still pick a soft praise moment
      and an exercise.
PROVES   O1 -> test_one_praise_moment_and_the_second_best_to_practise
         O2 -> test_no_moment_above_the_floor_shows_the_single_best_softly
         O3 -> test_with_no_sound_read_the_words_still_pick_a_praise_and_a_practise
WHY      Founder lock 2026-10-12 section 6; founder 2026-10-17 and 2026-10-18.
"""
from services.moment_pick import pick, read


def _row(block, slide, value, *, words=12, s=None, w=None, help=None):
    s = value if s is None else s
    w = 1.0 if w is None else w
    return {"block_id": block, "slide_index": slide, "word_count": words,
            "read": {"s": s, "w": w, "value": value, "words_help": help}}


def test_one_praise_moment_and_the_second_best_to_practise():
    reads = [_row("a", 0, 0.9, s=1.0, w=0.9, help="fillers"), _row("a2", 0, 0.7), _row("b", 1, 0.8),
             _row("c", 2, 0.65), _row("d", 3, 0.95), _row("short", 4, 0.99, words=3),
             _row("low", 5, 0.2, s=0.8, w=0.25)]
    picked = pick(reads)
    assert picked["green"] == ["d"]
    assert picked["soft"] is False
    # The second best (the short clip has too few words); its words need
    # help (founder 2026-10-18), so it may open on a clearer version.
    assert picked["exercise"] == "a"
    assert picked["exercise_kind"] == "clearer"


def test_no_moment_above_the_floor_shows_the_single_best_softly():
    picked = pick([_row("a", 0, 0.4), _row("b", 1, 0.5, s=0.5), _row("c", 2, 0.1, s=0.1)])
    assert picked["green"] == ["b"]
    assert picked["soft"] is True
    assert (picked["exercise"], picked["exercise_kind"]) == ("a", "voice")


def test_with_no_sound_read_the_words_still_pick_a_praise_and_a_practise():
    """Founder 2026-10-17: always a praise moment and a practise moment.
    Clips never stamped with a sound read are ordered by their words alone:
    the cleanest shows softly as the praise, the next is the exercise, and
    the pick says the sound was not heard."""
    clean = read(None, "we think the timing matters because the window closes once", {})
    hedged = read(None, "um so I guess maybe we sort of kind of think it matters", {})
    assert clean["sound"] is False and clean["s"] == 0.5
    assert read(1.0, None, {})["value"] == 1.0 and read(1.0, None, {})["sound"] is True
    picked = pick([{"block_id": "a", "slide_index": 0, "word_count": 11, "read": hedged},
                   {"block_id": "b", "slide_index": 1, "word_count": 11, "read": clean}])
    assert picked["green"] == ["b"] and picked["soft"] is True
    assert picked["exercise"] == "a"
