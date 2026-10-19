"""Per-person exercise effectiveness (founder 2026-10-18, Linear WIL-29).

Two contracts the founder decided on:

  * exercise-held-next-take-v1: a practice's targeted problem is checked on
    the same passage in the speaker's next Take; it holds, comes back, or
    is unknown with a reason (a rewritten passage is unknown, never held);
  * the founder's per-person list: counts in words per exercise, the
    machine's, the coach's and the speaker's answers on their own lines,
    and "too few to read" below five practices.
"""
from services.confident_voice_practice import SIGNAL_RULES_VERSION
from services.exercise_held import decide
from services.practice_effects import summarize

PASSAGE = "we cut the waiting time for every patient in half this year"
PRACTICE = {"id": "p1", "snippet_id": "s0", "exercise_id": "pause-v1",
            "exact_passage": PASSAGE}
TRACE = {"signal_rules_version": SIGNAL_RULES_VERSION, "fit": "exact",
         "fallback": None, "vocabulary": [], "observed_tags": ["rushing"],
         "candidates": [{"exercise_id": "pause-v1", "outcome": "ranked",
                         "main_targets": ["rushing"], "secondary_targets": []}]}


def _clip(pause_ratio: float, transcript: str = PASSAGE) -> dict:
    return {"id": "n1", "transcript": transcript, "duration_ms": 5000,
            "audio_ref": "takes/n1.webm",
            "metrics": {"pause_ratio": pause_ratio, "pause_regularity": 0.9,
                        "voiced_ratio": 0.6}}


def _decide(clips, trace=TRACE):
    return decide(PRACTICE, trace, clips, signal_rules_version=SIGNAL_RULES_VERSION)


def test_held_when_the_targeted_problem_stays_away():
    got = _decide([_clip(0.20, "a different opening sentence"), _clip(0.20)])
    assert got["outcome"] == "held"
    assert got["targeted_problems"] == ["rushing"] and got["still_firing"] == []
    assert got["next_snippet_id"] == "n1"


def test_came_back_when_the_targeted_problem_fires_again():
    got = _decide([_clip(0.03)])
    assert got["outcome"] == "came_back" and got["still_firing"] == ["rushing"]


def test_a_rewritten_passage_is_unknown_never_held():
    got = _decide([_clip(0.20, "this year our patients waited far less than before")])
    assert (got["outcome"], got["unknown_reason"]) == ("unknown", "passage_not_found")


def test_a_rule_change_in_between_is_unknown():
    got = _decide([_clip(0.20)], trace={**TRACE, "signal_rules_version": "old"})
    assert (got["outcome"], got["unknown_reason"]) == ("unknown", "rules_changed")


def test_the_person_list_counts_in_words_and_keeps_each_voice_apart():
    practices = [
        {"id": "a", "exercise_id": "pause-v1", "status": "completed",
         "after_practice": {"next": "praise"}, "final_user_answer": "yes"},
        {"id": "b", "exercise_id": "pause-v1", "status": "completed",
         "after_practice": {"next": "moved_on"}, "final_user_answer": None},
        {"id": "c", "exercise_id": "pause-v1", "status": "dismissed",
         "after_practice": None, "final_user_answer": None},
    ]
    got = summarize(practices, tries={"a": 1, "b": 3},
                    coach={"a": "yes", "b": "no"},
                    held={"a": "held"}, titles={"pause-v1": "Pause before the point"})
    [row] = got["exercises"]
    assert row["title"] == "Pause before the point" and row["practices"] == 3
    assert row["too_few"] is True
    assert row["right_away"] == {"better": 1, "not_yet": 1, "not_checked": 1}
    assert row["coach"] == {"agreed": 1, "did_not": 1, "waiting": 1}
    assert row["own_answer"] == {"yes": 1, "no": 0, "none": 2}
    assert row["next_take"] == {"held": 1, "came_back": 0, "unknown": 0, "waiting": 2}
    assert row["tries"] == {"none": 1, "one": 1, "two": 0, "three": 1}
    assert row["skipped"] == 1
    assert not any(isinstance(v, float) for v in row.values())
