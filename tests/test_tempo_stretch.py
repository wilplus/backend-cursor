"""
GUARD    The tempo step practises the stretch of the Take the pace scale reads
         furthest from the green, says whether it ran fast or slow, and names
         what it was about in a few plain words (founder 2026-10-26, N162, N166).
CATCHES
  C1  a Take spoken without a pause no longer picks that clip as rushed
  C2  a Take with long pauses no longer picks that clip as slow
  C3  a Take in the green picking a stretch anyway, so the step shows for nothing
  C4  a topic with a number, a quote or a whole sentence reaching the speaker
  C5  a failed topic call losing the step, instead of saying "that part"
  C6  a played tempo game no longer kept for Will, or kept with a number in his note
  C7  a broken or partial game kept as if it were whole
  C8  the tempo step reaching a speaker the rings panel has not switched on
  C9  the stretch losing its player (the speaker's orange clip, N166, locked
      prototype X4gDmGfHH7ivuoRZ9ufiy9), playing another clip, serving a
      cached signature, or a failed signing losing the step
  C10 the One thing walk's stretch waiting on a topic it never says (N435
      item 6, N452 item 2), its words carrying an "um" or a repeat the
      Ideal Text never shows (H3), or losing its slide
IF REMOVED  the tempo step could practise the wrong stretch, or put a number
         or a made-up sentence on screen (Never 1, Never 4).
PROVES   C1 -> test_a_clip_spoken_without_a_pause_is_rushed
         C2 -> test_a_clip_with_long_pauses_is_slow
         C3 -> test_a_take_in_the_green_has_no_stretch
         C4 -> test_only_a_short_plain_topic_is_kept
         C5 -> test_a_failed_topic_still_gives_the_step
         C6 -> test_a_played_game_is_kept_for_will_in_words
         C7 -> test_a_partial_game_is_not_kept
         C8 -> test_only_the_founder_and_the_ring_have_the_step
         C9 -> test_the_stretch_plays_as_the_speakers_clip
         C10 -> test_the_one_thing_walks_stretch_comes_without_a_topic_call_in_the_ideal_texts_words
"""
from services import speaker_memory, tempo_stretch


def _clip(start: float, words: int, word_s: float, gap_s: float, text: str) -> dict:
    """A clip of `words` words, each `word_s` long, `gap_s` apart."""
    timed, t = [], start
    for i in range(words):
        timed.append({"word": f"w{i}", "start": round(t, 3), "end": round(t + word_s, 3)})
        t += word_s + gap_s
    return {"transcript": text, "words": timed}


def _normal(start: float, text: str) -> dict:
    # Ordinary speech: a breath (0.6 s) after every five words.
    t, words = start, []
    for _ in range(3):
        words += _clip(t, 5, 0.3, 0.1, "")["words"]
        t = words[-1]["end"] + 0.6
    return {"transcript": text, "words": words}


def test_a_clip_spoken_without_a_pause_is_rushed():
    take = [_normal(0, "Our new store opens on Monday."),
            _clip(12, 60, 0.3, 0.1, "And the beds are on sale this week, every size."),
            _normal(40, "So come and see us.")]
    chosen = tempo_stretch.pick(take)
    assert chosen and chosen["index"] == 1 and chosen["reading"] == "rushed"


def test_a_clip_with_long_pauses_is_slow():
    take = [_normal(0, "Here's what changes."),
            # The scale sinks slowly (N142): it reads slow only on pauses of
            # several seconds, so these are eight.
            _clip(12, 8, 0.3, 8.0, "The new pricing starts in January."),
            _normal(90, "Questions so far?")]
    chosen = tempo_stretch.pick(take)
    assert chosen and chosen["index"] == 1 and chosen["reading"] == "slow"


def test_a_take_in_the_green_has_no_stretch():
    assert tempo_stretch.pick([_normal(0, "One."), _normal(10, "Two.")]) is None
    assert tempo_stretch.pick([]) is None


def test_only_a_short_plain_topic_is_kept():
    assert tempo_stretch.read_topic("The beds for sale.") == "the beds for sale"
    assert tempo_stretch.read_topic("your hiring plan") == "your hiring plan"
    assert tempo_stretch.read_topic("the 3 pricing plans") is None
    assert tempo_stretch.read_topic('"pricing"') is None
    assert tempo_stretch.read_topic("This passage is about how the new store sells beds") is None
    assert tempo_stretch.read_topic(None) is None


def test_a_failed_topic_still_gives_the_step(monkeypatch):
    take = [_normal(0, "Our new store opens on Monday. Big day."),
            {**_clip(12, 60, 0.3, 0.1, "And the beds are on sale this week."), "id": "s2"},
            _normal(40, "So come and see us. Thanks.")]

    class Db:
        def get_snippets_by_session(self, _take):
            return take

    def broken(*_a, **_k):
        raise RuntimeError("model down")

    monkeypatch.setattr("services.take_summary._under_authority", broken)
    tempo_stretch._CACHE.clear()
    tempo = tempo_stretch.tempo_for_take(Db(), take="t1", user_id="u", arc_id="a")
    assert tempo == {
        "reading": "rushed",
        "topic": "that part",
        "said": {"before": "Big day.", "stretch": "And the beds are on sale this week.",
                 "after": "So come and see us."},
        "snippet_id": "s2",
        "slide_index": None,
    }


def test_the_one_thing_walks_stretch_comes_without_a_topic_call_in_the_ideal_texts_words(
        monkeypatch):
    take = [_normal(0, "Our new store opens on Monday. Big day."),
            {**_clip(12, 60, 0.3, 0.1, "And um the the beds are on sale this week."), "id": "s2",
             "language": "en", "metrics": {"piece": {"slide_index": 3}}},
            _normal(40, "So come and see us. Thanks.")]

    class Db:
        def get_snippets_by_session(self, _take):
            return take

        def get_v4_dark_frame(self, _take):
            return {"blocks": [{"walk_slot": "strongest"}, {"walk_slot": None}]}

    asked: list = []
    monkeypatch.setattr("services.take_summary._under_authority",
                        lambda *_a, **_k: asked.append(1) or "the beds")
    for one in (False, lambda: not tempo_stretch.walked_as_one_thing(Db(), "t1")):
        tempo_stretch._CACHE.clear()
        tempo = tempo_stretch.tempo_for_take(Db(), take="t1", user_id="u", arc_id="a", topic=one)
        assert tempo is not None
        assert (tempo["topic"], tempo["said"]["stretch"], tempo["slide_index"]) == (
            "that part", "And the beds are on sale this week.", 3)
    assert asked == []


def test_the_stretch_plays_as_the_speakers_clip():
    tempo = {"reading": "rushed", "topic": "the beds", "said": {}, "snippet_id": "s2"}
    asked = []

    def signer(ids):
        asked.append(ids)
        return {"s2": {"snippet_audio_ref": "https://r2/take.webm?sig", "start_offset_ms": 12000,
                       "duration_ms": 24000}}

    played = tempo_stretch.with_clip(tempo, signer)
    assert asked == [["s2"]]
    assert played == {**tempo, "snippet_audio_ref": "https://r2/take.webm?sig",
                      "start_offset_ms": 12000, "duration_ms": 24000}
    assert "snippet_audio_ref" not in tempo  # the cached answer never holds a signature

    def broken(_ids):
        raise RuntimeError("storage down")

    for signer in (broken, lambda _ids: {}, lambda _ids: {"s2": {"snippet_audio_ref": None}}):
        words_only = tempo_stretch.with_clip(tempo, signer)
        assert words_only["snippet_audio_ref"] is None and words_only["reading"] == "rushed"


class _MemoryDb:
    def __init__(self):
        self.events = []

    def insert_speaker_memory_event(self, row):
        self.events.append(row)


def test_a_played_game_is_kept_for_will_in_words(monkeypatch):
    monkeypatch.setattr("services.parallel.start_scoped_thread", lambda *_a, **_k: None)
    db = _MemoryDb()
    body = {"reading": "rushed", "close": "dynamic",
            "tries": [{"result": "rush", "path": [0.5, 0.9]}, {"result": "ok", "path": [0.5, 0.6]}]}
    assert tempo_stretch.keep_tries(db, user_id="u", take="t1", body=body)
    event = db.events[-1]
    assert event["kind"] == "take" and event["take_session_id"] == "t1"
    assert event["payload"]["tempo"]["paths"] == [[0.5, 0.9], [0.5, 0.6]]
    line = speaker_memory._event_line(event)
    assert line == ("- A take: a tempo game on a stretch they rushed: tries still rushed, "
                    "better, it ended dynamic.")
    assert not any(ch.isdigit() for ch in line)


def test_a_partial_game_is_not_kept():
    db = _MemoryDb()
    for body in ({"reading": "fast", "tries": [], "close": None},
                 {"reading": "rushed", "tries": [{"result": "ok", "path": [2]}], "close": "dynamic"},
                 {"reading": "rushed", "tries": [{"result": "ok", "path": []}], "close": None},
                 {"reading": "rushed", "tries": [{"result": "ok", "path": []}] * 4, "close": "dynamic"}):
        assert not tempo_stretch.keep_tries(db, user_id="u", take="t1", body=body)
    assert db.events == []
    # Skipped before a try: kept as skipped.
    assert tempo_stretch.read_tries({"reading": "slow", "tries": [], "close": None})["tries"] == []


def test_only_the_founder_and_the_ring_have_the_step(monkeypatch):
    reached: set[str] = set()
    monkeypatch.setattr("services.rings.feature_is_on_for_user",
                        lambda feature, user, **_k: feature == "tempo_step" and user in reached)
    assert tempo_stretch.tempo_is_on("founder", founder=True)
    assert not tempo_stretch.tempo_is_on("speaker", founder=False)
    reached.add("speaker")
    assert tempo_stretch.tempo_is_on("speaker", founder=False)
