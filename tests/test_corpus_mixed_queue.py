"""
STORY    As the founder judging the training corpus, I want the clips really
         mixed: never the same speaker twice in a row, and the machine's high,
         neutral and low reads all there, without anything on screen hinting
         which is which.
OUTCOME
  O1  Never one speaker twice in a row while another is left in the round.
  O2  The machine's bands in equal measure: up to the same number from
      each, all of a scarce band.
  O3  BLIND COACH: the order is the same whichever clip carries which band;
      the band decides only which clips come in.
  O4  The import the coach opened comes first.
  O5  The round's payload carries only the queue's allowlist and the topic:
      no import id, speaker, band or score; clips this coach answered, and
      imports not set up, are not in it.
PROVES   O1 -> test_never_one_speaker_twice_in_a_row
         O2 -> test_the_machines_reads_in_equal_measure
         O3 -> test_the_order_does_not_follow_the_band
         O4 -> test_the_opened_import_comes_first
         O5 -> test_the_round_carries_nothing_of_the_machine
WHY      Founder 2026-10-21 (N101): "they do not come from the same speaker;
         the fragments are really mixed, with different willfidence scores
         like really neutral, high, and low".
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from routes.v2 import coach as v2_coach
from services.corpus_mixed_queue import mixed_round
from tests.test_training_import_on import COACH, _call

HIGH, NEUTRAL, LOW = ("delivery_signal_high", "delivery_signal_neutral",
                      "delivery_signal_low")


def _clip(n: int, speaker: str, band: str, session: str = "s") -> dict:
    return {"snippet_id": f"clip-{n:03d}", "session_id": session,
            "speaker": speaker, "band": band}


def test_never_one_speaker_twice_in_a_row():
    clips = ([_clip(i, "ada", HIGH) for i in range(6)]
             + [_clip(10 + i, "bo", NEUTRAL) for i in range(5)]
             + [_clip(20 + i, "cy", LOW) for i in range(4)])
    order = [c["speaker"] for c in mixed_round(clips, seed="w", per_band=10)]
    assert sorted(order) == sorted(c["speaker"] for c in clips)
    assert all(a != b for a, b in zip(order, order[1:]))


def test_the_machines_reads_in_equal_measure():
    clips = ([_clip(i, f"h{i}", HIGH) for i in range(20)]
             + [_clip(30 + i, f"n{i}", NEUTRAL) for i in range(3)]
             + [_clip(40 + i, f"l{i}", LOW) for i in range(20)])
    bands = [c["band"] for c in mixed_round(clips, seed="w", per_band=5)]
    assert {b: bands.count(b) for b in set(bands)} == {HIGH: 5, NEUTRAL: 3, LOW: 5}


def test_the_order_does_not_follow_the_band():
    speakers = ["ada", "bo", "cy"]
    clips = [_clip(i, speakers[i % 3], (HIGH, NEUTRAL, LOW)[i % 3]) for i in range(12)]
    swapped = [{**c, "band": (LOW, HIGH, NEUTRAL)[i % 3]} for i, c in enumerate(clips)]
    first = [c["snippet_id"] for c in mixed_round(clips, seed="w", per_band=10)]
    again = [c["snippet_id"] for c in mixed_round(swapped, seed="w", per_band=10)]
    assert first == again


def test_the_opened_import_comes_first():
    clips = [_clip(i, f"sp{i}", HIGH, session=f"import-{i}") for i in range(8)]
    for start in ("import-3", "import-6"):
        assert mixed_round(clips, seed="w", start_session=start)[0]["session_id"] == start


# ── the route ─────────────────────────────────────────────────────────────

A, B, C = ("aaaaaaaa-0000-4000-8000-00000000000a", "bbbbbbbb-0000-4000-8000-00000000000b",
           "cccccccc-0000-4000-8000-00000000000c")


def _import(sid: str, speaker: str, clips: list, *, set_up: bool = True) -> dict:
    ctx = {"topic": f"Talk {sid[0]}", "speaker_label": speaker,
           "label_queue_selection": [{"snippet_id": c} for c in clips]}
    if set_up:
        ctx["language"] = "en"
    return {"id": sid, "source": "training_import", "recording_id": None, "intake_context": ctx}


class MixedDB:
    def __init__(self):
        self.imports = [_import(A, "Ada", ["a1", "a2", "a3"]),
                        _import(B, "Bo", ["b1", "b2"]),
                        _import(C, "Cy", ["c1"], set_up=False)]
        self.scores = {"a1": 0.9, "a2": -0.8, "a3": 0.0, "b1": 0.7, "b2": -0.6, "c1": 0.5}
        self.takes = SimpleNamespace(list_training_import_cohorts=lambda: list(self.imports))

    def get_user_proficient_languages(self, _uid):
        return ["en"]

    def get_recording_languages(self, _ids):
        return {}

    def get_snippet_scores_by_ids(self, ids):
        owner = {c["snippet_id"]: im["id"] for im in self.imports
                 for c in im["intake_context"]["label_queue_selection"]}
        return {i: {"session_id": owner[i], "score": self.scores[i]} for i in ids}

    def get_confidence_labels_by_snippet_ids(self, ids, strict=False):
        # This coach already answered a2.
        return {"a2": [{"rater_id": COACH, "value": "no"}]} if "a2" in ids else {}


def test_the_round_carries_nothing_of_the_machine(monkeypatch):
    monkeypatch.setattr(v2_coach, "db", MixedDB())
    status, body = _call(v2_coach.v2_coach_corpus_mixed_queue, method="GET",
                         path=f"/v2/coach/corpus/mixed-queue?start={B}")
    assert status == 200, body
    queue = body["queue"]
    assert sorted(q["snippet_id"] for q in queue) == ["a1", "a3", "b1", "b2"]
    assert queue[0]["snippet_id"] in ("b1", "b2")
    for row in queue:
        assert set(row) == {"snippet_id", "label", "re_review", "rating_locked",
                            "rating_lock_reason", "learning_exposures", "topic"}
    text = json.dumps(body)
    for word in ("score", "band", "delivery_signal", "Ada", "Bo", A, B, "speaker", "0.9"):
        assert word not in text, word
