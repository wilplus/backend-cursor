"""
STORY    As the founder, I want my moment labels to measure both pickers, so
         that what I teach in the Pattern Library says how often the app
         picked the moment I would, and served an intervention where I
         chose one.
OUTCOME
  O1  An error or praise label agrees when the Take's frozen selection
      showed that clip; a control label agrees when it did not; an unsure
      label and a Take with no frozen selection are not counted as agreement.
  O2  On an error label, a served exercise and a chosen tool agree, and so
      do none and none; one without the other differs. The exercise and
      the tool are listed side by side, never mapped by guess.
  O3  Training Corpus labels are counted, not compared: they have no walk.
PROVES   O1 -> test_moment_agreement_follows_what_the_take_showed
         O2 -> test_intervention_agreement_is_served_against_chosen
         O3 -> test_corpus_labels_are_counted_not_compared
WHY      N702: the labels were saved and nothing read them.
"""
from services.picker_golden import compare


def _label(kind, clip, *, take="t1", source="take", tool=None):
    return {"id": f"x-{clip}", "source": source, "session_id": take, "snippet_id": clip,
            "kind": kind, "pattern": "rushed",
            "intervention": {"tool": tool} if tool else None}


def test_moment_agreement_follows_what_the_take_showed():
    labels = [_label("error", "s1"), _label("praise", "s2"), _label("control", "s3"),
              _label("control", "s1"), _label("unsure", "s1"), _label("error", "s9", take="t2")]
    got = compare(labels, {"t1": {"s1", "s2"}, "t2": None}, {"t1": {}, "t2": {}})
    assert got["moment"] == {"agree": 3, "differ": 1, "unknown": 1}
    assert [c["moment_agrees"] for c in got["cases"]] == [True, True, True, False, None]


def test_intervention_agreement_is_served_against_chosen():
    labels = [_label("error", "s1", tool="sniper"), _label("error", "s2"),
              _label("error", "s3", tool="ai_audio"), _label("error", "s4")]
    got = compare(labels, {"t1": set()}, {"t1": {"s1": "ex-7", "s4": "ex-2"}})
    assert got["intervention"] == {"agree": 2, "differ": 2, "unknown": 0}
    first = got["cases"][0]
    assert (first["your_tool"], first["served_exercise"], first["tool_agrees"]) == ("sniper", "ex-7", True)


def test_corpus_labels_are_counted_not_compared():
    got = compare([_label("error", "c1", source="corpus")], {}, {})
    assert got["corpus_labels"] == 1 and got["cases"] == []
