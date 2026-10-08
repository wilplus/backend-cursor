"""V4 B1.2: a Take's seeded random 20% of moments (build plan D-ML-7;
founder V2 A, V3 A; migration 0447). The pure rule; the database's copy of
it is pinned equal in tests/test_a_take_draws_its_random_moments_postgres.py.
"""
from __future__ import annotations

import pathlib

import pytest

from services import v4_random_moments as rm
from services.data_purge_registry import DEPENDENCIES
from services.take_feedback_policy_v3 import pick_seed

ROOT = pathlib.Path(__file__).resolve().parents[1]
TAKE = "3f2b8c1e-0d4a-4e57-9a51-1f0c6a9b7e20"


def _blocks(n):
    return [f"speech-block:{i:020d}" for i in range(n)]


@pytest.mark.parametrize("n,k", [
    (1, 1), (2, 1), (5, 1), (6, 2), (10, 2), (11, 3), (15, 3), (16, 4),
    (100, 20), (101, 21),
])
def test_twenty_percent_rounded_up(n, k):
    assert rm.draw_size(n) == k
    assert len(rm.draw_moments(pick_seed(TAKE), _blocks(n))) == k


def test_the_same_seed_draws_the_same_moments():
    seed = pick_seed(TAKE)
    blocks = _blocks(23)
    first = rm.draw_moments(seed, blocks)
    assert rm.draw_moments(seed, list(reversed(blocks))) == first
    assert rm.draw_moments(pick_seed(TAKE.upper()), blocks) == first


def test_another_take_draws_other_moments():
    blocks = _blocks(40)
    draws = {tuple(rm.draw_moments(pick_seed(f"take-{i}"), blocks))
             for i in range(20)}
    assert len(draws) > 15


def test_every_moment_can_be_drawn():
    """V2 A: drawn from all moments, roughly evenly across Takes."""
    blocks = _blocks(10)
    hits = {block: 0 for block in blocks}
    for i in range(2000):
        for block in rm.draw_moments(pick_seed(f"take-{i}"), blocks):
            hits[block] += 1
    # 2000 Takes x 2 draws over 10 blocks: about 400 each.
    assert all(300 < count < 500 for count in hits.values()), hits


def test_the_draw_follows_the_written_hash_order():
    seed = "123456789"
    blocks = ["b", "a", "c", "d", "e", "f"]
    import hashlib
    expected = sorted(blocks, key=lambda b: (hashlib.sha256(
        f"v4-random-draw-v1:{seed}:{b}".encode()).hexdigest(), b))[:2]
    assert rm.draw_moments(seed, blocks) == expected


@pytest.mark.parametrize("seed,blocks", [
    ("", ["a"]), ("-1", ["a"]), ("12345678901234567", ["a"]), ("1x", ["a"]),
    ("1", []), ("1", ["a", "a"]), ("1", ["a", ""]), ("1", ["a", None]),
])
def test_a_draw_the_database_would_refuse_is_refused(seed, blocks):
    with pytest.raises(ValueError):
        rm.draw_moments(seed, blocks)


class _Db:
    def __init__(self, error=None):
        self.error, self.calls = error, []

    def draw_v4_random_moments(self, take):
        self.calls.append(take)
        if self.error:
            raise self.error
        return {"outcome": "drawn", "drawn": 1}


def test_the_side_write_never_raises():
    assert rm.draw(_Db(RuntimeError("down")), TAKE) is None
    assert rm.draw(_Db(), "") is None
    db = _Db()
    assert rm.draw(db, TAKE) == {"outcome": "drawn", "drawn": 1}
    assert db.calls == [TAKE]


def test_the_draw_goes_with_the_take_in_the_purge_registry():
    row = {d.code: d for d in DEPENDENCIES}["v4_random_moments"]
    assert (row.relation, row.selector_column, row.locator_kind,
            row.disposition) == ("v4_random_moments", "take_session_id",
                                 "take", "delete")


def test_the_pipeline_draws_only_after_the_frame_is_stored():
    source = (ROOT / "services" / "ideal_text_changes.py").read_text()
    stored = source.index('_v3_saved.get("outcome") != "stored"')
    drawn = source.index("draw(db, _arm_sid)")
    assert stored < drawn


def test_no_route_reads_the_draw():
    """AC-9: the draw is internal; no route names its table or writer."""
    for path in (ROOT / "routes").rglob("*.py"):
        text = path.read_text()
        assert "v4_random_moments" not in text, path
        assert "draw_v4_random_moments" not in text, path
