"""Confident Voice micro-practice: narrow eligibility and isolation fences."""
from __future__ import annotations

import unittest

from services import confident_voice_practice as cvp


def _words(*, compressed: bool) -> list[dict]:
    out = []
    at = 0.0
    for index, token in enumerate(
        "read the same exact passage and give every single word enough space now".split()
    ):
        duration = 0.12 if compressed and index >= 8 else 0.24
        out.append({"word": token, "start": at, "end": at + duration})
        at += duration + (0.025 if compressed else 0.12)
    return out


def _snippet(**over) -> dict:
    row = {
        "id": "snippet-a",
        "transcript": "Read the same exact passage and give every single word enough space now.",
        "duration_ms": 5000,
        "audio_segment_path": "snippets/a.webm",
        "words": _words(compressed=True),
        "metrics": {
            "wpm": 210.0,
            "pause_ratio": 0.03,
            "voiced_ratio": 0.78,
            "audio_quality": {"reliable": True, "noise_dominant": False},
            "voice_confidence": {
                "version": "voice-confidence-universal-v3",
                "score": 0.25,
            },
        },
    }
    row.update(over)
    return row


class PassageAndAssessmentTests(unittest.TestCase):


    def test_user_attempt_shape_never_exposes_scores_or_metrics(self):
        public = cvp.public_attempt({
            "id": "a", "attempt_index": 1, "audio_ref": "a.webm",
            "duration_ms": 2000, "assessment_key": "clearer_less_rushed",
            "acoustic_metrics": {"wpm": 999},
            "comparison": {"internal_strength": 999},
        })
        self.assertNotIn("acoustic_metrics", public)
        self.assertNotIn("comparison", public)
        self.assertNotIn("score", repr(public).casefold())


class _Db:
    def __init__(self, existing=None, supported_patterns=None):
        self.existing = existing
        self.supported_patterns = supported_patterns
        self.snippets = {
            "snippet-a": _snippet(id="snippet-a"),
            "snippet-b": _snippet(id="snippet-b"),
        }

    def get_active_diagnostic_exercise(self, _exercise_id):
        row = {
            "exercise_id": cvp.EXERCISE_ID,
            "version": 1,
            "title": cvp.TITLE,
            "instruction": cvp.INSTRUCTION,
            "introduction_copy": cvp.INTRO_NEAR,
            "confident_introduction_copy": cvp.INTRO_CONFIDENT,
            "explanation_video_url": "https://example.com/coach.mp4",
            # The seed row's claim (add_confident_voice_practice.sql). Without
            # tags an exercise is never offered (D1, 2026-09-28).
            "acoustic_problem_tags": [
                "rushing", "word_compression", "ending_compression"],
        }
        if self.supported_patterns is not None:
            row["supported_confidence_patterns"] = self.supported_patterns
        return row

    def get_confident_voice_practice_by_take(self, _take):
        return self.existing

    def get_confident_voice_practice_candidates(self, ids):
        return [self.snippets[i] for i in ids]

    def get_snippets_by_session(self, _take):
        return [{"metrics": {"wpm": 150.0}}]


if __name__ == "__main__":
    unittest.main()


class V3ExerciseFitTests(unittest.TestCase):
    """The V3 lane under D1/D5/D6, end to end through the 80/20 call."""

    class _Db(_Db):
        def __init__(self, rows, signals):
            super().__init__()
            self._rows = rows
            self.snippets["snippet-a"] = _snippet(id="snippet-a")
            self._signals = signals
            self.assigned = []

        def list_diagnostic_exercises(self):
            return [{"exercise_id": r["exercise_id"]} for r in self._rows]

        def get_active_diagnostic_exercise(self, exercise_id):
            return next((dict(r) for r in self._rows
                         if r["exercise_id"] == exercise_id), None)

        def list_speaker_exercise_ids(self, _owner):
            # The speaker's own set (N77): every row these tests hand in.
            return {r["exercise_id"] for r in self._rows}

        def list_speaking_errors(self):
            return [{"error_id": e, "status": "detected"} for e in
                    ("rushing", "word_compression", "ending_compression")]

        def assign_confident_voice_exercise(self, **kwargs):
            self.assigned.append(kwargs)
            return {"selected_exercise_id": kwargs["candidates"][0]["exercise_id"]}

        def completed_exercise_before(self, *_args):
            return False

    def _row(self, exercise_id, tags, primary=None):
        criteria = {} if primary is None else {"primary_problem_tag": primary}
        return {"exercise_id": exercise_id, "version": 1, "title": exercise_id,
                "instruction": "", "introduction_copy": "",
                "explanation_video_url": "https://cdn.example/x.mp4",
                "acoustic_problem_tags": tags, "matching_criteria": criteria,
                "supported_confidence_patterns": [
                    "low_confidence_rushing_dominant", "near_confident",
                    "confident"]}

    def _offer(self, db, fired):
        target = {"source": "confident_voice", "bookmark_tier": "exercise",
                  "snippet_id": "snippet-a"}
        # Read weak: the library video is for a clip the machine reads weak
        # (the follow-up matrix, founder 2026-09-29).
        verdict = {"eligible": True, "pattern": "low_confidence_rushing_dominant",
                   "priority": 1, "signals": fired, "snapshot": {}}
        original = cvp.exercise_eligibility
        cvp.exercise_eligibility = lambda *_a, **_k: verdict
        try:
            rows = cvp.attach_v3_exercise_offer(
                [target], take_session_id="take-1", owner_user_id="owner-1",
                database=db, ground=lambda _row: {"slide_index": 0})
        finally:
            cvp.exercise_eligibility = original
        return rows[0].get("practice_exercise")


class MatchTraceTests(unittest.TestCase):
    """Why an exercise was chosen, frozen with the draw (step 2, 2026-09-28)."""

    _Db = V3ExerciseFitTests._Db
    _row = V3ExerciseFitTests._row
    _offer = V3ExerciseFitTests._offer

    def _catalogue(self):
        return [
            self._row("exact", ["rushing"], primary="rushing"),
            self._row("trial", ["word_compression", "rushing"],
                      primary="word_compression"),
            self._row("elsewhere", ["ending_compression"]),
        ]

    def _trace(self):
        db = self._Db(self._catalogue(), {})
        offer = self._offer(db, {"insufficient_pauses": True})
        return offer, db.assigned[0]


    def test_the_trace_never_reaches_the_speaker(self):
        offer, _ = self._trace()
        text = repr(offer)
        for internal in ("trace", "candidates", "observed_tags", "signals"):
            self.assertNotIn(internal, text)
