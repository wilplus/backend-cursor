"""Coach-panel moment ordering — key moments first (founder 2026-07-24, T1 · 1.2).

Pure tests of services/coach_moment_order.py — no app / DB import, so they
run in CI (unlike the app-importing coach-session tests). They lock the
contract the coach panel depends on: the take's moments come back
most-significant-first (key → close-to-key → least distinctive), keyed ONLY
on the deterministic coach-only acoustic_read, with BOTH signed extremes
surfaced (never buried) and a stable chronological tiebreak.

Run: python3 -m unittest test_coach_moment_order
"""
from __future__ import annotations

import unittest

from services.coach_moment_order import (
    coach_moment_significance_key,
    order_coach_moments_by_significance,
)


def _snip(sid, start, pot=None, outside=False, ar=True):
    s = {"id": sid, "start_offset_ms": start}
    if ar:
        s["acoustic_read"] = {"potentiometer": pot,
                              "outside_normal_range": outside}
    return s


def _order(snips):
    return [s["id"] for s in order_coach_moments_by_significance(snips)]


class MomentSignificanceOrderTests(unittest.TestCase):
    def test_key_first_then_gradient(self):
        # Chronological input; expected: the outside_normal_range key moments
        # first (by |potentiometer| desc), then the rest by |potentiometer|
        # desc → key → close-to-key → least distinctive.
        snips = [
            _snip("flat", 0, pot=0.1, outside=False),    # least distinctive
            _snip("neg", 1000, pot=-0.8, outside=True),  # hyper-negative, key
            _snip("pos", 2000, pot=0.9, outside=True),   # hyper-positive, key
            _snip("mid", 3000, pot=0.4, outside=False),  # close-to-key
        ]
        self.assertEqual(_order(snips), ["pos", "neg", "mid", "flat"])

    def test_both_signed_extremes_not_buried(self):
        # Ordering is by MAGNITUDE, so a strong NEGATIVE (stress) outranks a
        # mild positive — and symmetrically a strong POSITIVE outranks a mild
        # negative. Neither signed extreme is ever buried under the other.
        self.assertEqual(
            _order([_snip("mild_pos", 0, pot=0.15),
                    _snip("hyper_neg", 1000, pot=-0.95, outside=True)]),
            ["hyper_neg", "mild_pos"])
        self.assertEqual(
            _order([_snip("mild_neg", 0, pot=-0.15),
                    _snip("hyper_pos", 1000, pot=0.95, outside=True)]),
            ["hyper_pos", "mild_neg"])

    def test_outside_flag_wins_over_raw_magnitude(self):
        # The explicit "potentially a key moment" flag is the top term: a
        # flagged moment leads even a slightly larger-magnitude unflagged one.
        snips = [
            _snip("unflagged_big", 0, pot=0.80, outside=False),
            _snip("flagged_smaller", 1000, pot=0.70, outside=True),
        ]
        self.assertEqual(_order(snips), ["flagged_smaller", "unflagged_big"])

    def test_chronological_fallback_when_no_acoustic_read(self):
        # No acoustic_read anywhere → degrades to chronological (start asc),
        # exactly as the panel reads today before the signal exists.
        snips = [_snip("b", 5000, ar=False),
                 _snip("a", 0, ar=False),
                 _snip("c", 9000, ar=False)]
        self.assertEqual(_order(snips), ["a", "b", "c"])

    def test_equal_significance_breaks_chronologically(self):
        # Same flag + same magnitude → the start_offset_ms tiebreak keeps the
        # honest "what happened" order.
        snips = [
            _snip("late", 4000, pot=0.5, outside=True),
            _snip("early", 1000, pot=0.5, outside=True),
        ]
        self.assertEqual(_order(snips), ["early", "late"])

    def test_malformed_acoustic_read_is_neutral_never_raises(self):
        # None / non-dict acoustic_read, or a non-numeric potentiometer → read
        # as neutral (magnitude 0, flag off), sorted after real key moments and
        # chronological among themselves, and never raising.
        snips = [
            _snip("key", 2000, pot=0.7, outside=True),
            {"id": "none_ar", "start_offset_ms": 0, "acoustic_read": None},
            {"id": "bad_ar", "start_offset_ms": 1000,
             "acoustic_read": {"potentiometer": "x", "outside_normal_range": None}},
        ]
        self.assertEqual(_order(snips), ["key", "none_ar", "bad_ar"])

    def test_missing_start_offset_is_safe(self):
        # A row with no start_offset_ms sorts as start 0 and never raises.
        snips = [
            _snip("key", 5000, pot=0.9, outside=True),
            {"id": "no_start"},  # no acoustic_read, no start
        ]
        self.assertEqual(_order(snips), ["key", "no_start"])

    def test_pure_reorder_same_objects_no_field_added(self):
        # It reorders the SAME dicts and attaches nothing (no score surfaced).
        a = _snip("a", 0, pot=0.1)
        b = _snip("b", 1000, pot=0.9, outside=True)
        out = order_coach_moments_by_significance([a, b])
        self.assertEqual([id(x) for x in out], [id(b), id(a)])
        # no new keys introduced on the moments
        self.assertEqual(set(a.keys()), {"id", "start_offset_ms", "acoustic_read"})
        self.assertNotIn("significance", b)

    def test_empty_and_none_safe(self):
        self.assertEqual(order_coach_moments_by_significance([]), [])
        self.assertEqual(order_coach_moments_by_significance(None), [])

    def test_key_is_negated_for_ascending_sort(self):
        # Guard the key's shape: higher significance → smaller tuple.
        strong = coach_moment_significance_key(
            {"acoustic_read": {"potentiometer": 0.9, "outside_normal_range": True},
             "start_offset_ms": 0})
        weak = coach_moment_significance_key(
            {"acoustic_read": {"potentiometer": 0.1, "outside_normal_range": False},
             "start_offset_ms": 0})
        self.assertLess(strong, weak)


if __name__ == "__main__":
    unittest.main()
