"""Which moments a Take shows (founder lock 2026-10-12, section 6)."""
from services.moment_pick import pick, read


def _row(block, slide, value, *, words=12, s=None, w=None):
    s = value if s is None else s
    w = 1.0 if w is None else w
    return {"block_id": block, "slide_index": slide, "word_count": words,
            "read": {"s": s, "w": w, "value": value}}


def test_one_praise_moment_and_the_second_best_to_practise():
    reads = [_row("a", 0, 0.9, s=1.0, w=0.9), _row("a2", 0, 0.7), _row("b", 1, 0.8),
             _row("c", 2, 0.65), _row("d", 3, 0.95), _row("short", 4, 0.99, words=3),
             _row("low", 5, 0.2, s=0.8, w=0.25)]
    picked = pick(reads)
    assert picked["green"] == ["d"]
    assert picked["soft"] is False
    # The second best (the short clip has too few words); its words are the
    # weaker half.
    assert picked["exercise"] == "a"
    assert picked["exercise_kind"] == "clearer"


def test_no_moment_above_the_floor_shows_the_single_best_softly():
    picked = pick([_row("a", 0, 0.4), _row("b", 1, 0.5, s=0.5), _row("c", 2, 0.1, s=0.1)])
    assert picked["green"] == ["b"]
    assert picked["soft"] is True
    assert (picked["exercise"], picked["exercise_kind"]) == ("a", "voice")


def test_a_clip_with_no_sound_read_is_not_read():
    assert read(None, "we will win", {}) is None
    assert read(1.0, None, {})["value"] == 1.0
