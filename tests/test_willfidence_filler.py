"""WIL-28: the filler signal counts every filler and falls smoothly
(founder 2026-10-18: ambiguous fillers at half weight, a curve with its
midpoint at FILLER_MIDPOINT_PER_100, nothing flattened to zero)."""
from __future__ import annotations

from services import willfidence as wf

CLEAN = "we built the product and shipped it to ten customers last spring"


def test_no_fillers_reads_one_and_empty_reads_nothing():
    assert wf.filler(CLEAN) == 1.0
    assert wf.filler("") is None
    assert wf.filler(None) is None


def test_every_extra_filler_costs_a_little_and_never_reaches_zero():
    reads = [wf.filler(("um " * n) + CLEAN) for n in range(0, 40)]
    assert reads == sorted(reads, reverse=True)
    assert len(set(reads)) == len(reads)
    assert all(read is not None and read > 0 for read in reads)


def test_an_ambiguous_filler_costs_half_an_um():
    one_um = wf.filler("um " + CLEAN)
    two_likes = wf.filler("like like " + CLEAN)
    assert wf.filler(CLEAN) > wf.filler("like " + CLEAN) > one_um
    # two "like" at half weight weigh one "um", and the extra two tokens in
    # the denominator (13 vs 12 words) only soften it, never the other way.
    assert abs(two_likes - one_um) < 0.05


def test_the_midpoint_is_where_the_founder_set_it():
    text = " ".join(["um"] * wf.FILLER_MIDPOINT_PER_100 + ["word"] * (100 - wf.FILLER_MIDPOINT_PER_100))
    assert wf.filler(text) == 0.5
    assert wf.filler(" ".join(["um"] * 10 + ["word"] * 90)) == 1 / 3


def test_hedging_keeps_its_own_scale():
    assert wf.hedging("maybe " * 10 + "word " * 90) == 0.0
