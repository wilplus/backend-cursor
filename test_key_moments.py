"""Live key moments use professional-coach evidence, never peer quorum."""
from __future__ import annotations

import unittest

from services.key_moments import (
    confidence_verdicts, is_key_moment, key_snippet_ids,
)
from services.professional_confidence import latest_professional_value


def _coach(value, **extra):
    return {"rater_id": "coach-1", "lane": "coach",
            "state_id": "confidence", "value": value, **extra}


def _peer(value, rater="peer-1"):
    return {"rater_id": rater, "lane": "game_peer",
            "state_id": "confidence", "value": value}


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


class ProductAuthorityTests(unittest.TestCase):
    def test_one_professional_yes_is_sufficient(self):
        db = _Db({"s1": [_coach("yes")]})
        self.assertEqual(key_snippet_ids(db, ["s1"]), {"s1"})

    def test_professional_no_is_a_verdict_but_not_key(self):
        db = _Db({"s1": [_coach("no")]})
        self.assertEqual(confidence_verdicts(db, ["s1"]), {"s1": "no"})
        self.assertEqual(key_snippet_ids(db, ["s1"]), set())

    def test_peer_quorum_has_zero_product_authority(self):
        db = _Db({"s1": [_peer("yes"), _peer("yes", "peer-2")]})
        self.assertEqual(confidence_verdicts(db, ["s1"]), {})
        self.assertEqual(key_snippet_ids(db, ["s1"]), set())

    def test_owner_self_report_and_bootstrap_are_excluded(self):
        db = _Db({"s1": [
            {**_coach("yes"), "self_report": True},
            {**_coach("yes"), "lane": "bootstrap"},
        ]})
        self.assertEqual(key_snippet_ids(db, ["s1"]), set())

    def test_wrong_state_neutral_and_unrateable_are_excluded(self):
        rows = [
            {**_coach("yes"), "state_id": "another-state"},
            _coach("neutral"),
            {**_coach("yes"), "unrateable": True},
        ]
        self.assertIsNone(latest_professional_value(rows))

    def test_latest_professional_judgment_wins(self):
        rows = [
            _coach("yes", updated_at="2026-08-20T10:00:00Z"),
            _coach("no", updated_at="2026-08-21T10:00:00Z"),
        ]
        self.assertEqual(latest_professional_value(rows), "no")

    def test_legacy_coach_source_is_supported_without_promoting_peers(self):
        legacy = {"source": "coach", "state_id": "confidence", "value": "yes"}
        self.assertEqual(latest_professional_value([legacy]), "yes")
        self.assertIsNone(latest_professional_value([_peer("yes")]))


class TheReadTests(unittest.TestCase):
    def test_one_batched_read_for_the_whole_arc(self):
        ids = [f"s{i}" for i in range(50)]
        db = _Db({value: [_coach("yes")] for value in ids})
        self.assertEqual(len(key_snippet_ids(db, ids)), 50)
        self.assertEqual(db.calls, [ids])

    def test_a_read_failure_degrades_to_empty_never_raises(self):
        # "No key moments yet" beats a 500 on the page — and we cannot claim a
        # moment is key when we could not read the votes.
        db = _Db(boom=True)
        self.assertEqual(key_snippet_ids(db, ["s1"]), set())
        self.assertEqual(confidence_verdicts(db, ["s1"]), {})

    def test_one_malformed_snippet_does_not_sink_the_arc(self):
        db = _Db({"good": [_coach("yes")], "bad": "not-rows"})
        self.assertEqual(key_snippet_ids(db, ["good", "bad"]), {"good"})

    def test_empty_input_never_touches_the_db(self):
        db = _Db()
        self.assertEqual(key_snippet_ids(db, []), set())
        self.assertEqual(key_snippet_ids(db, None), set())
        self.assertEqual(db.calls, [])

    def test_ids_are_normalised_to_str(self):
        db = _Db({"7": [_coach("yes")]})
        self.assertEqual(key_snippet_ids(db, [7]), {"7"})

    def test_is_key_moment_agrees_with_the_set(self):
        db = _Db({"s1": [_coach("yes")], "s2": [_coach("no")]})
        self.assertTrue(is_key_moment(db, "s1"))
        self.assertFalse(is_key_moment(db, "s2"))
        self.assertFalse(is_key_moment(db, None))


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
