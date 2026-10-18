"""Why a green moment landed (founder 2026-10-18): the reason is the
speaker's own words and plain facts, never a number or an invented quote,
it rides only a green row, and it is written off the request path."""
from services import praise_reason

SAID = "Every month we lost a full week. A full week. That is one person doing nothing else."
VOICE = {"said": SAID, "voice": ["Their voice sat lower than it usually does."],
         "words": ["There are no filler words in it."]}
WORDS_ONLY = {"said": SAID, "voice": [praise_reason._NO_SOUND],
              "words": ["There are no filler words in it."]}
GOOD = {"quote": "A full week. That is one person doing nothing else.",
        "paragraphs": ["When you said “A full week. That is one person doing nothing else.”",
                       "Your voice sat lower than usual and you went straight through.",
                       "It came out as a fact, not a question. No fillers."]}


def test_the_approved_shape_is_kept():
    assert praise_reason.clean_reason(GOOD, VOICE) == GOOD


def test_a_reason_never_carries_a_number_or_a_comparison_with_others():
    numbered = {**GOOD, "paragraphs": [GOOD["paragraphs"][0], "Your voice was 20% lower."]}
    others = {**GOOD, "paragraphs": [GOOD["paragraphs"][0], "Calmer than most speakers manage."]}
    assert praise_reason.clean_reason(numbered, VOICE) is None
    assert praise_reason.clean_reason(others, VOICE) is None


def test_the_quote_must_be_what_the_speaker_said():
    invented = {**GOOD, "quote": "We doubled revenue.",
                "paragraphs": ["When you said “We doubled revenue.”", "No fillers."]}
    assert praise_reason.clean_reason(invented, VOICE) is None


def test_no_voice_talk_without_a_voice_fact_and_paragraphs_stay_short():
    assert praise_reason.clean_reason(GOOD, WORDS_ONLY) is None
    long = {**GOOD, "paragraphs": [GOOD["paragraphs"][0], "word " * 30]}
    assert praise_reason.clean_reason(long, VOICE) is None


class _Db:
    def __init__(self, stored):
        self.stored = stored

    def list_green_moment_reasons(self, ids, version):
        return {sid: self.stored[sid] for sid in ids if sid in self.stored}

    def get_snippets_by_session(self, take):
        return [{"id": "s1"}, {"id": "s2"}] if take == "t1" else [{"id": "x9"}]


def test_only_a_green_row_carries_its_reason_and_a_missing_one_is_queued(monkeypatch):
    queued = []
    monkeypatch.setattr(praise_reason, "enqueue", lambda take, ids: queued.append((take, ids)))
    rows = [{"id": "a", "bookmark_tier": "confident", "snippet_id": "s1", "take_session_id": "t1"},
            {"id": "b", "bookmark_tier": "confident", "snippet_id": "s2", "take_session_id": "t1"},
            {"id": "c", "bookmark_tier": "standard", "snippet_id": "s3", "take_session_id": "t1"}]
    out = praise_reason.attach(_Db({"s1": {"paragraphs": GOOD["paragraphs"], "quote": GOOD["quote"]}}), rows)
    assert out[0]["praise_reason"] == {"paragraphs": GOOD["paragraphs"], "quote": GOOD["quote"]}
    assert "praise_reason" not in out[1] and "praise_reason" not in out[2]
    assert queued == [("t1", ["s2"])]


def test_the_walk_reads_only_its_own_takes_clips():
    db = _Db({"s1": {"paragraphs": ["x"], "quote": "q"}, "x9": {"paragraphs": ["y"], "quote": "q"}})
    assert praise_reason.reasons_for(db, "t1", ["s1", "s2", "x9"]) == {
        "reasons": {"s1": {"paragraphs": ["x"], "quote": "q"}}, "pending": ["s2"]}
