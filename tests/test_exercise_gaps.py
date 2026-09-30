"""The CMS gap view (founder 2026-09-28, step 5).

Pins:
  * a detected pattern that is spotted but that no exercise targets as its
    main target comes first ("film this next"), then trial-only, then covered;
  * shadow patterns show their silent measurements and are marked as being
    tested, never as a gap to fill today;
  * spotted counts come from the frozen records of exercise moments (traces
    and coach requests), open coach requests are counted per pattern, and a
    resolved request is no longer open;
  * a source that cannot be read is named, never read as zero;
  * the window is clamped; the route sits behind the CMS password.
"""
from __future__ import annotations

import unittest

from services import exercise_gaps as gaps

LIBRARY = [
    {"error_id": "rushing", "label": "Rushing", "status": "detected"},
    {"error_id": "ending_compression", "label": "Ending compression",
     "status": "detected"},
    {"error_id": "word_compression", "label": "Word compression",
     "status": "detected"},
    {"error_id": "hedging", "label": "Hedging", "status": "shadow"},
    {"error_id": "mumbling", "label": "Mumbling", "status": "observed"},
    {"error_id": "retired", "label": "Retired", "status": "detected",
     "active": False},
]

EXERCISES = [
    {"exercise_id": "room-to-follow", "acoustic_problem_tags": ["rushing"]},
    {"exercise_id": "hear-every-word",
     "acoustic_problem_tags": ["word_compression", "ending_compression"],
     "matching_criteria": {"primary_problem_tag": "word_compression"}},
]


def _view(**over):
    args = dict(library=LIBRARY, exercises=EXERCISES,
                spotted_tags=[["ending_compression"], ["ending_compression",
                                                       "rushing"],
                              ["rushing"], ["rushing"]],
                requests=[
                    {"reason": "nothing_targets_it",
                     "observed_tags": ["ending_compression"], "resolution": None},
                    {"reason": "nothing_targets_it",
                     "observed_tags": ["ending_compression"],
                     "resolution": "no_safe_match"},
                    {"reason": "nothing_spotted", "observed_tags": [],
                     "resolution": None},
                ],
                shadow={"hedging": {"clips_measured": 40, "clips_fired": 9}},
                days=30)
    args.update(over)
    return gaps.build_gap_view(**args)


class GapViewTests(unittest.TestCase):
    def test_the_patterns_to_film_next_come_first(self):
        rows = _view()["patterns"]
        self.assertEqual([r["error_id"] for r in rows], [
            "ending_compression",   # detected, spotted twice, trial-only
            "rushing",              # covered, spotted three times
            "word_compression",     # covered, not spotted
            "hedging",              # being tested
            "mumbling",             # nobody can detect it yet
        ])

    def test_coverage_reads_main_and_secondary_targets(self):
        by_id = {r["error_id"]: r for r in _view()["patterns"]}
        ending = by_id["ending_compression"]
        self.assertEqual(ending["coverage"], "trial_only")
        self.assertEqual(ending["main_exercises"], [])
        self.assertEqual(ending["secondary_exercises"], ["hear-every-word"])
        self.assertEqual(by_id["rushing"]["coverage"], "covered")
        self.assertEqual(by_id["rushing"]["main_exercises"], ["room-to-follow"])

    def test_a_spotted_pattern_nothing_targets_is_a_gap(self):
        rows = _view(exercises=[])["patterns"]
        self.assertEqual(rows[0]["error_id"], "rushing")
        self.assertEqual(rows[0]["coverage"], "no_exercise")
        self.assertEqual(rows[0]["spotted"], 3)

    def test_counts_come_from_the_frozen_moments(self):
        view = _view()
        by_id = {r["error_id"]: r for r in view["patterns"]}
        self.assertEqual(by_id["ending_compression"]["spotted"], 2)
        # Only the unresolved request is still open.
        self.assertEqual(by_id["ending_compression"]["open_coach_requests"], 1)
        self.assertEqual(view["nothing_spotted_open_requests"], 1)
        self.assertEqual(view["days"], 30)

    def test_a_shadow_pattern_shows_its_silent_measurements(self):
        hedging = next(r for r in _view()["patterns"]
                       if r["error_id"] == "hedging")
        self.assertEqual(hedging["coverage"], "being_tested")
        self.assertEqual(hedging["shadow"],
                         {"clips_measured": 40, "clips_fired": 9})
        self.assertNotIn("shadow", next(r for r in _view()["patterns"]
                                        if r["error_id"] == "rushing"))

    def test_a_retired_pattern_is_left_out(self):
        self.assertNotIn("retired",
                         [r["error_id"] for r in _view()["patterns"]])

    def test_the_window_is_clamped(self):
        self.assertEqual(gaps.window_days(None), gaps.DEFAULT_DAYS)
        self.assertEqual(gaps.window_days("7"), gaps.DEFAULT_DAYS)
        self.assertEqual(gaps.window_days(True), gaps.DEFAULT_DAYS)
        self.assertEqual(gaps.window_days(0), 1)
        self.assertEqual(gaps.window_days(365), gaps.MAX_DAYS)
        self.assertEqual(gaps.window_days(7), 7)


class _Db:
    def __init__(self, fail=()):
        self.fail = set(fail)

    def list_speaking_errors(self, active_only=True):
        return LIBRARY

    def list_diagnostic_exercises(self):
        return [{"exercise_id": e["exercise_id"]} for e in EXERCISES]

    def get_active_diagnostic_exercise(self, exercise_id):
        return next((dict(e) for e in EXERCISES
                     if e["exercise_id"] == exercise_id), None)

    def _maybe(self, name, value):
        if name in self.fail:
            raise RuntimeError("relation does not exist")
        return value

    def list_match_trace_tags(self, since):
        return self._maybe("match_traces", [["rushing"]])

    def list_exercise_coach_requests(self, since):
        return self._maybe("coach_requests", [])

    def count_verbal_cue_shadow(self, error_id, since):
        return self._maybe("shadow_observations",
                           {"clips_measured": 2, "clips_fired": 1})


class ReadTests(unittest.TestCase):
    def test_it_reads_every_source(self):
        view = gaps.gap_view(_Db(), days=7)
        self.assertEqual(view["unavailable"], [])
        self.assertEqual(view["days"], 7)
        rushing = next(r for r in view["patterns"] if r["error_id"] == "rushing")
        self.assertEqual(rushing["spotted"], 1)

    def test_an_unreadable_source_is_named_not_zeroed(self):
        view = gaps.gap_view(_Db(fail={"match_traces", "shadow_observations"}))
        self.assertEqual(view["unavailable"],
                         ["match_traces", "shadow_observations"])


