"""KEY MOMENTS — one selector, one construct (founder ruling 2026-08-14).

A key moment is confidence quorum = yes. Nothing else. These pins hold that
definition still, because FOUR surfaces now read it — the game's right answer,
the feedback page, the paid unlock, and the Voice Album's "coach agrees" leg —
and the failure mode that made this module necessary was those surfaces quietly
disagreeing about what they were selecting.

Run: python3 -m unittest test_key_moments
"""
from __future__ import annotations

import unittest

from services.key_moments import (
    KEY_VALUE, STATE_ID, confidence_verdicts, is_key_moment,
    is_key_resolution, key_snippet_ids,
)


def _rows(*values, lane="coach", state_id=STATE_ID):
    """Rating rows from DISTINCT raters — one rater voting twice is one rater
    (the ledger dedupes), which would never reach quorum."""
    return [{"rater_id": f"r{i}", "lane": lane, "state_id": state_id,
             "value": v} for i, v in enumerate(values)]


def _mixed_lanes(*values):
    lanes = ("coach", "game_peer")
    return [{"rater_id": f"r{i}", "lane": lanes[i % 2], "state_id": STATE_ID,
             "value": v} for i, v in enumerate(values)]


class _Db:
    def __init__(self, by_snippet=None, boom=False):
        self.by_snippet = by_snippet or {}
        self.boom = boom
        self.calls = []

    def get_confidence_labels_by_snippet_ids(self, ids):
        self.calls.append(list(ids))
        if self.boom:
            raise RuntimeError("db down")
        return {i: self.by_snippet.get(i, []) for i in ids}


class TheDefinitionTests(unittest.TestCase):
    def test_quorum_yes_is_the_whole_definition(self):
        db = _Db({"s1": _mixed_lanes("yes", "yes")})
        self.assertEqual(key_snippet_ids(db, ["s1"]), {"s1"})

    def test_quorum_NO_is_settled_and_is_not_key(self):
        # A real verdict, and the opposite of the one we select on.
        db = _Db({"s1": _mixed_lanes("no", "no")})
        self.assertEqual(key_snippet_ids(db, ["s1"]), set())
        self.assertEqual(confidence_verdicts(db, ["s1"]), {"s1": "no"})

    def test_a_SINGLE_yes_is_not_enough(self):
        # Ledger rule 3: one rating is weak supervision, never ground truth.
        # This is the pin that keeps one person's opinion out of a paywall.
        db = _Db({"s1": _rows("yes")})
        self.assertEqual(key_snippet_ids(db, ["s1"]), set())
        self.assertEqual(confidence_verdicts(db, ["s1"]), {})

    def test_a_SPLIT_panel_settles_nothing(self):
        db = _Db({"s1": _mixed_lanes("yes", "no")})
        self.assertEqual(key_snippet_ids(db, ["s1"]), set())
        self.assertEqual(confidence_verdicts(db, ["s1"]), {})

    def test_an_agreed_IDK_settles_AMBIGUOUS_and_is_not_key(self):
        # "We both find this ambiguous" is a finding about the moment — a
        # legitimate corpus row — but not a moment worth replaying.
        db = _Db({"s1": _mixed_lanes("neutral", "neutral")})
        self.assertEqual(confidence_verdicts(db, ["s1"]), {"s1": "ambiguous"})
        self.assertEqual(key_snippet_ids(db, ["s1"]), set())

    def test_an_unrated_snippet_is_absent_not_None(self):
        # Absent, so a caller cannot mistake a placeholder for a verdict.
        db = _Db({"s1": []})
        self.assertEqual(confidence_verdicts(db, ["s1"]), {})


class TheLedgerRulesStillApplyTests(unittest.TestCase):
    """`resolve` enforces these; these pins prove the selector did not route
    around them on its way to a user-facing surface."""

    def test_the_machine_lane_cannot_make_a_key_moment(self):
        # Rule 1: a proposal routes work, it never votes.
        db = _Db({"s1": _rows("yes", "yes", lane="machine")})
        self.assertEqual(key_snippet_ids(db, ["s1"]), set())

    def test_another_states_quorum_is_not_this_states_quorum(self):
        db = _Db({"s1": _rows("yes", "yes", state_id="some_other_state")})
        self.assertEqual(key_snippet_ids(db, ["s1"]), set())


class TheReadTests(unittest.TestCase):
    def test_one_batched_read_for_the_whole_arc(self):
        # The reason this module exists as a set-returning helper: a surface
        # holding an arc's snippets must not fan out one query per snippet.
        db = _Db({f"s{i}": _mixed_lanes("yes", "yes") for i in range(50)})
        ids = [f"s{i}" for i in range(50)]
        self.assertEqual(len(key_snippet_ids(db, ids)), 50)
        self.assertEqual(len(db.calls), 1)

    def test_a_read_failure_degrades_to_empty_never_raises(self):
        # "No key moments yet" beats a 500 on the page — and we cannot claim a
        # moment is key when we could not read the votes.
        db = _Db(boom=True)
        self.assertEqual(key_snippet_ids(db, ["s1"]), set())
        self.assertEqual(confidence_verdicts(db, ["s1"]), {})

    def test_one_malformed_snippet_does_not_sink_the_arc(self):
        db = _Db({"good": _mixed_lanes("yes", "yes"), "bad": "not-rows"})
        self.assertEqual(key_snippet_ids(db, ["good", "bad"]), {"good"})

    def test_empty_input_never_touches_the_db(self):
        db = _Db()
        self.assertEqual(key_snippet_ids(db, []), set())
        self.assertEqual(key_snippet_ids(db, None), set())
        self.assertEqual(db.calls, [])

    def test_ids_are_normalised_to_str(self):
        db = _Db({"7": _mixed_lanes("yes", "yes")})
        self.assertEqual(key_snippet_ids(db, [7]), {"7"})

    def test_is_key_moment_agrees_with_the_set(self):
        db = _Db({"s1": _mixed_lanes("yes", "yes"),
                  "s2": _mixed_lanes("no", "no")})
        self.assertTrue(is_key_moment(db, "s1"))
        self.assertFalse(is_key_moment(db, "s2"))
        self.assertFalse(is_key_moment(db, None))


class TheResolutionPredicateTests(unittest.TestCase):
    def test_it_requires_BOTH_quorum_and_the_positive_value(self):
        from services.label_quorum import PERCEPTUALLY_AMBIGUOUS, QUORUM
        self.assertTrue(is_key_resolution(
            {"status": QUORUM, "value": KEY_VALUE}))
        self.assertFalse(is_key_resolution({"status": QUORUM, "value": "no"}))
        self.assertFalse(is_key_resolution(
            {"status": PERCEPTUALLY_AMBIGUOUS, "value": "ambiguous"}))
        self.assertFalse(is_key_resolution(
            {"status": "singleton", "value": KEY_VALUE}))

    def test_garbage_in_is_not_a_key_moment(self):
        for junk in (None, "yes", 1, [], {}):
            self.assertFalse(is_key_resolution(junk))


class NoRetiredConstructSurvivesTests(unittest.TestCase):
    """The point of the whole re-point: the surfaces stop reading fictions."""

    def test_the_selector_never_reads_training_labels(self):
        # challenge/threat — retired construct, corpus frozen 2026-08-07.
        import inspect

        from services import key_moments
        src = inspect.getsource(key_moments)
        code = "\n".join(ln for ln in src.splitlines()
                         if not ln.lstrip().startswith("#"))
        body = code.split('"""')[-1]          # past the module docstring
        for dead in ("training_labels", "challenge", "threat", "strong"):
            self.assertNotIn(dead, body, f"{dead} is back in key_moments")

    def test_the_strong_tag_is_gone_from_the_album_and_the_blend(self):
        import inspect

        from services import voice_album
        from services.power_phrase_ranking import _COACH_TERM
        self.assertNotIn("_STRONG_TAG", inspect.getsource(voice_album))
        self.assertNotIn("strong", _COACH_TERM)
        self.assertIn("to_work_on", _COACH_TERM)   # the real pick survives


if __name__ == "__main__":
    unittest.main()
