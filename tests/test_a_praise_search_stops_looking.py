"""The structural praise search is bounded (founder 2026-10-14, the wait).

One device on screen per Take does not need the whole take searched: the
search spends at most three waves of candidates, in document order, with the
same prompt — so a Take whose first pieces carry devices stores exactly what
it always did, and a Take whose pieces carry none stops asking.
"""
from __future__ import annotations

import services.moment_suggestions as ms


class _Db:
    def __init__(self):
        self.rows = []

    def upsert_moment_suggestion(self, snip_id, arc_id, kind, repl, quote,
                                 device):
        self.rows.append(snip_id)
        return True


def _search(monkeypatch, found):
    seen = []

    def _detect(transcript, user_id=None):
        seen.append(transcript)
        return ({"device": "contrast", "quote": transcript}
                if found(transcript) else None)

    monkeypatch.setattr(ms, "detect_structural_device", _detect)
    monkeypatch.setenv("STRUCTURAL_STARS_ENABLED", "1")
    monkeypatch.setenv("STRUCTURAL_STARS_MAX_PER_TAKE", "3")
    database = _Db()
    candidates = [(f"s{i}", f"piece {i}") for i in range(30)]
    stored = ms._generate_structural(database, "arc-1", candidates)
    return stored, seen, database.rows


def test_a_take_with_no_device_stops_after_three_waves(monkeypatch):
    stored, seen, rows = _search(monkeypatch, lambda t: False)
    assert stored == 0 and rows == []
    assert seen == [f"piece {i}" for i in range(9)]


def test_the_first_pieces_with_devices_are_stored_as_before(monkeypatch):
    stored, seen, rows = _search(
        monkeypatch, lambda t: t in ("piece 1", "piece 4", "piece 7"))
    assert stored == 3
    assert rows == ["s1", "s4", "s7"]
    assert len(seen) <= 9
