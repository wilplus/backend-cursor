"""
STORY    As a speaker, I want each Take to show my strongest moment, praised,
         my weakest, practised with the AI voice, and the one whose words
         need help, with a clearer version, so that I know what to keep and
         get the one fix each moment needs.
OUTCOME
  O1  The strongest is the Take's highest willfidence clip, a block's best
      clip standing for it and a clip with enough words before a short
      one; it is praised whatever its voice and called my most confident.
  O2  The weakest is, from another block, the clip whose own voice shows
      the strongest problem the AI clip can teach (pace, pauses, a flat
      loudness range, fillers, against my own usual), with a whole thought
      and a sound read; it is practised with the voice. A clip that shows no
      such problem is never the weakest, however low its read (N425).
  O3  The between is the clip whose words need help the most; it gets the
      clearer version, and it is picked before the weakest, so a Take of
      two blocks gets the precise fix.
  O4  A slot nothing fills goes to the next best block, praised: three
      moments when the Take has three blocks, one per block, never fewer
      than two with two.
  O5  A clip with no sound read can be the strongest, never the weakest.
  O6  A sentence that already has my helper words is not the strongest
      again: the next best is, and it comes back only when nothing else can
      be shown.
  O7  On a plan, my level takes the slot it is given, never the
      strongest's block, never as a fourth moment.
  O8  A slide I already gave helper words to gives way in every slot:
      my best, the clearer version and the AI clip come from slides I have
      not touched, and a worked slide fills a slot only when nothing else
      can (N543).
PROVES   O1 -> test_the_strongest_is_praised_whatever_its_voice
         O2 -> test_the_weakest_is_the_lowest_whole_thought_i_was_heard_saying
         O3 -> test_words_that_need_help_get_the_between_first
         O4 -> test_an_empty_slot_goes_to_the_next_best
         O5 -> test_a_clip_with_no_sound_read_is_never_the_weakest
         O6 -> test_a_sentence_with_my_helper_words_gives_way_to_the_next
         O7 -> test_my_level_takes_its_slot_never_the_strongest
         O8 -> test_my_moments_come_from_slides_i_have_not_touched_first
WHY      Founder 2026-10-30 (N289: "the praise clips just get the praise",
         "a negative [word] has been spotted, or it was too fast, that's
         the second moment", "the third moment, the weakest one, is where
         we display the AI audio"); 2026-10-28 (N246, "go for the next
         confident moment"); 2026-10-30 (N284, three moments); 2026-11-03
         (N425, "go for A, B and C": the AI clip only where the voice shows
         the problem); 2026-11-06 (N543, "Untouched first").
"""
from services.moment_pick import pick, read


def _row(block, slide, s, *, w=1.0, words=12, help=None, sound=True, clip=None, voice=None):
    # The clip's measured voice problem (N425): by default it rises as the
    # voice read drops, as a rushed or flat clip's does.
    voice = max(0.0, round(1 - s, 3)) if voice is None else voice
    return {"block_id": block, "slide_index": slide, "word_count": words,
            "candidate_id": clip or f"{block}-clip", "voice": voice,
            "read": {"s": s, "w": w, "value": s * w, "sound": sound, "words_help": help}}


def _shown(picked):
    return [(m["block_id"], m["slot"], m["praise"], m["kind"], m["highest"])
            for m in picked["shown"]]


def test_the_strongest_is_praised_whatever_its_voice():
    # Willfidence picks: cleaner words put a softer voice first.
    picked = pick([_row("loud", 0, 0.9, w=0.3), _row("clean", 1, 0.7)])
    assert _shown(picked)[0] == ("clean", "strongest", True, None, True)
    # A whole Take under the floor still has a strongest, praised.
    weak = pick([_row("a", 0, 0.3), _row("b", 1, 0.1)])
    assert _shown(weak)[0] == ("a", "strongest", True, None, True)
    # One per block: a block's best clip stands for it.
    picked = pick([_row("a", 0, 0.9, clip="a1", w=0.5), _row("a", 0, 0.8, clip="a2"),
                   _row("b", 1, 0.3, clip="b1")])
    assert [(m["block_id"], m["candidate_id"]) for m in picked["shown"]] == [
        ("a", "a2"), ("b", "b1")]
    # Enough words before a short clip, however loud.
    assert _shown(pick([_row("short", 0, 0.99, words=3), _row("x", 1, 0.2)]))[0][0] == "x"


def test_the_weakest_is_the_lowest_whole_thought_i_was_heard_saying():
    picked = pick([_row("a", 0, 0.9), _row("b", 1, 0.6), _row("c", 2, 0.4),
                   _row("d", 3, 0.1, words=7)])
    # d is lower but under 8 words: c is the weakest.
    assert _shown(picked) == [("a", "strongest", True, None, True),
                              ("c", "weakest", False, "voice", False),
                              ("b", "next", True, None, False)]
    # From any block but the strongest's, and its lowest clip, not its best.
    picked = pick([_row("a", 0, 0.9, clip="a1"), _row("a", 0, 0.1, clip="a2"),
                   _row("b", 1, 0.7, clip="b1"), _row("b", 1, 0.2, clip="b2")])
    assert [(m["candidate_id"], m["slot"]) for m in picked["shown"]] == [
        ("a1", "strongest"), ("b2", "weakest")]
    # The strongest measured problem wins, not the lowest read (N425 A).
    picked = pick([_row("a", 0, 0.9), _row("b", 1, 0.3, voice=0.3), _row("c", 2, 0.5, voice=0.9)])
    assert [(m["block_id"], m["slot"]) for m in picked["shown"]][1] == ("c", "weakest")
    # A low read whose voice shows nothing the AI clip can teach is never
    # the weakest: no AI clip just because (N425 B).
    quiet = pick([_row("a", 0, 0.9), _row("b", 1, 0.2, voice=0.0), _row("c", 2, 0.4, voice=0.1)])
    assert [m["slot"] for m in quiet["shown"]] == ["strongest", "next", "next"]


def test_words_that_need_help_get_the_between_first():
    picked = pick([_row("a", 0, 0.9), _row("b", 1, 0.7, w=0.4, help="hedges"),
                   _row("c", 2, 0.3)])
    assert _shown(picked) == [("a", "strongest", True, None, True),
                              ("b", "between", False, "clearer", False),
                              ("c", "weakest", False, "voice", False)]
    # Two blocks: the clearer version, not the AI clip.
    two = pick([_row("a", 0, 0.9), _row("b", 1, 0.2, w=0.5, help="undermining")])
    assert _shown(two)[1] == ("b", "between", False, "clearer", False)


def test_an_empty_slot_goes_to_the_next_best():
    # No words need help: the between's place is the next best's.
    assert [m["slot"] for m in pick([_row("a", 0, 0.9), _row("b", 1, 0.6),
                                     _row("c", 2, 0.5), _row("d", 3, 0.2)])["shown"]] == [
        "strongest", "weakest", "next"]
    # Nothing heard with a whole thought: two next bests.
    short = pick([_row("a", 0, 0.9), _row("b", 1, 0.6, words=6), _row("c", 2, 0.5, words=6)])
    assert _shown(short) == [("a", "strongest", True, None, True),
                             ("b", "next", True, None, False), ("c", "next", True, None, False)]
    # Two blocks show two; one shows one.
    assert len(pick([_row("a", 0, 0.9), _row("b", 1, 0.2)])["shown"]) == 2
    assert len(pick([_row("a", 0, 0.9)])["shown"]) == 1


def test_a_clip_with_no_sound_read_is_never_the_weakest():
    """Founder 2026-10-17: a clip never stamped with a sound read is not
    dropped; its words alone order it. The machine never heard it, so it is
    never the room to grow."""
    clean = read(None, "we think the timing matters because the window closes once", {})
    assert clean["sound"] is False and clean["s"] == 0.5
    # Every clip shows a measured voice problem (N425): only the heard one
    # can be the weakest.
    picked = pick([{"block_id": "a", "slide_index": 0, "word_count": 10, "read": clean, "voice": 0.6},
                   {"block_id": "b", "slide_index": 1, "word_count": 10, "voice": 0.6,
                    "read": read(-0.8, "we think the timing matters because the window closes", {})},
                   {"block_id": "c", "slide_index": 2, "word_count": 10, "read": clean, "voice": 0.6}])
    assert [(m["block_id"], m["slot"]) for m in picked["shown"]] == [
        ("a", "strongest"), ("b", "weakest"), ("c", "next")]


def test_a_sentence_with_my_helper_words_gives_way_to_the_next():
    held = {**_row("a", 0, 0.9), "held": True}
    assert _shown(pick([held, _row("b", 1, 0.7), _row("c", 2, 0.6, words=6),
                        _row("d", 3, 0.5, words=6)])) == [
        ("b", "strongest", True, None, True), ("c", "next", True, None, False),
        ("d", "next", True, None, False)]
    # Still shown when the Take has nothing else.
    assert [m["block_id"] for m in pick([held, _row("b", 1, 0.7, words=6)])["shown"]] == ["b", "a"]


def test_my_level_takes_its_slot_never_the_strongest():
    rows = [_row("a", 0, 0.9), _row("b", 1, 0.7), _row("c", 2, 0.6), _row("d", 3, 0.2)]
    level = {"candidate_id": "b-clip", "slot": "weakest", "kind": "voice",
             "plan_level": "voice_moves"}
    picked = pick(rows, level=level)
    assert [(m["block_id"], m["slot"], m.get("plan_level")) for m in picked["shown"]] == [
        ("a", "strongest", None), ("b", "weakest", "voice_moves"), ("c", "next", None)]
    # On the strongest's block: the pick as off a plan.
    assert pick(rows, level={**level, "candidate_id": "a-clip"}) == pick(rows)


def test_my_moments_come_from_slides_i_have_not_touched_first():
    def worked(row):
        return {**row, "touched": True}
    # The best clip, the words that need help most and the loudest voice
    # problem all sit on worked slides: every slot goes to untouched ones.
    rows = [worked(_row("a", 0, 0.95)), _row("b", 1, 0.8),
            worked(_row("c", 2, 0.3, w=0.3, help="undermining")),
            _row("d", 3, 0.4, w=0.6, help="undermining"),
            worked({**_row("e", 4, 0.2), "voice": 0.9}), _row("f", 5, 0.5)]
    assert [(m["block_id"], m["slot"]) for m in pick(rows)["shown"]] == [
        ("b", "strongest"), ("d", "between"), ("f", "weakest")]
    # Every slide worked on: the pick is the one it always was, never fewer.
    every = [worked(row) for row in (_row("a", 0, 0.9), _row("b", 1, 0.6), _row("c", 2, 0.2))]
    assert [m["block_id"] for m in pick(every)["shown"]] == [
        m["block_id"] for m in pick([{**r, "touched": False} for r in every])["shown"]]
