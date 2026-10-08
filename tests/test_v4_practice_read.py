"""V4 B1.4: the fast read of every practise try, timed from Stop, never
blocking (build plan D-ML-9; founder O5, V7 A; migration 0450)."""
from __future__ import annotations

import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from services import v4_practice_read as pr
from services import willfidence as wf
from services.data_purge_registry import DEPENDENCIES

ROOT = pathlib.Path(__file__).resolve().parents[1]
T0 = datetime(2026, 1, 8, 12, 0, tzinfo=timezone.utc)


def _row(**kw):
    row = {"outcome": "read", "willfident": 0.7,
           "server_received_at": T0.isoformat(),
           "server_read_at": (T0 + timedelta(seconds=2)).isoformat(),
           "phone_wait_ms": None}
    row.update(kw)
    return row


def test_the_fast_read_is_s_and_the_two_lexical_signals():
    metrics = {"voice_confidence": {"version": wf.SOUND_VERSION, "score": 0.4}}
    read = pr.fast_read(metrics, "we grew forty percent um this year")
    assert read["s"] == pytest.approx(0.7)
    assert read["filler"] == wf.filler("we grew forty percent um this year")
    assert read["hedging"] == 1.0
    assert pr.fast_read({}, "")["s"] is None


def test_a_late_read_is_not_reached_yet():
    assert pr.reached_state(_row(phone_wait_ms=4999), 0.6) == "reached"
    assert pr.reached_state(_row(phone_wait_ms=5001), 0.6) == "not_reached_yet"
    assert pr.reached_state(_row(phone_wait_ms=1000, willfident=0.5), 0.6) == "not_reached_yet"


def test_a_failed_or_missing_read_is_not_reached_yet():
    assert pr.reached_state(_row(outcome="failed"), 0.0) == "not_reached_yet"
    assert pr.reached_state(None, 0.0) == "not_reached_yet"
    assert pr.reached_state(_row(willfident=None), 0.0) == "not_reached_yet"


def test_the_phone_clock_wins_and_the_server_stands_in():
    assert pr.wait_ms(_row(phone_wait_ms=3100)) == (3100, "phone")
    assert pr.wait_ms(_row()) == (2000, "server")
    assert pr.wait_ms({"outcome": "read"}) == (None, "none")
    assert pr.late({"outcome": "read"}) is True


def test_the_p90_report():
    rows = [_row(phone_wait_ms=ms) for ms in (1000, 2000, 3000, 3500, 4000,
                                                4200, 4400, 4600, 4800, 9000)]
    report = pr.p90_report(rows)
    assert report["tries"] == 10
    assert report["p90_ms"] == 4800
    assert report["meets_o5"] is True
    assert report["on_time_share"] == pytest.approx(0.9)
    assert report["clocks"] == {"phone": 10, "server": 0, "none": 0}
    worse = pr.p90_report(rows[:8] + [_row(outcome="failed"), _row(phone_wait_ms=7000)])
    assert worse["meets_o5"] is False
    assert pr.p90_report([])["p90_ms"] is None


class _Db:
    def __init__(self, error=None):
        self.error, self.reads, self.timings = error, [], []

    def record_v4_practice_read(self, attempt, **kw):
        if self.error:
            raise self.error
        self.reads.append((attempt, kw))
        return {"outcome": "stored"}

    def record_v4_practice_timing(self, *args):
        if self.error:
            raise self.error
        self.timings.append(args)
        return {"outcome": "stored"}


def test_recording_never_raises_and_stores_a_failed_read(monkeypatch):
    assert pr.record(_Db(RuntimeError("db down")), "a1", received_at=T0,
                     metrics={}, transcript="x") is None
    db = _Db()
    monkeypatch.setattr(pr, "fast_read", lambda *_: 1 / 0)
    pr.record(db, "a1", received_at=T0, metrics={}, transcript="x")
    attempt, kw = db.reads[0]
    assert kw["outcome"] == "failed" and kw["s"] is None
    assert kw["received_at"] == T0 and kw["read_at"] >= T0


@pytest.mark.parametrize("body", [
    None, {}, {"stopped_at_ms": 10, "shown_at_ms": 5},
    {"stopped_at_ms": 0, "shown_at_ms": 700_000},
    {"stopped_at_ms": "1", "shown_at_ms": 2}, {"stopped_at_ms": True, "shown_at_ms": 2},
    {"stopped_at_ms": float("nan"), "shown_at_ms": 2},
])
def test_a_bad_timing_is_refused_before_the_database(body):
    db = _Db()
    assert pr.record_timing(db, "a1", "u1", body) is False
    assert db.timings == []


def test_a_good_timing_is_stored_once_and_never_raises():
    db = _Db()
    assert pr.record_timing(db, "a1", "u1",
                            {"stopped_at_ms": 1_000, "shown_at_ms": 4_200}) is True
    assert db.timings == [("a1", "u1", 1000, 4200)]
    assert pr.record_timing(_Db(RuntimeError("x")), "a1", "u1",
                            {"stopped_at_ms": 1, "shown_at_ms": 2}) is False


def test_the_read_follows_the_saved_try_and_the_route_never_returns_it():
    saver = (ROOT / "services" / "practice_audio_objects.py").read_text()
    assert saver.index("_shadow_verdicts(database, inserted, practice)") < \
        saver.index("record_for_attempt(database, inserted)")
    source = (ROOT / "routes" / "v2" / "user_sessions.py").read_text()
    timing = source[source.index("def v2_confident_voice_practice_attempt_timing"):]
    timing = timing[:timing.index("\n@v2_bp.route")]
    assert 'return "", 204' in timing
    assert "willfident" not in timing and "jsonify({\"read" not in timing


def test_the_saved_try_is_read_from_its_own_row():
    db = _Db()
    pr.record_for_attempt(db, {"id": "a1", "transcript": "um we grew",
                               "acoustic_metrics": {"confidence": 0.2}})
    attempt, kw = db.reads[0]
    assert attempt == "a1" and kw["outcome"] == "read"
    assert kw["s"] == pytest.approx(0.6)
    assert kw["filler"] == wf.filler("um we grew")
    pr.record_for_attempt(db, {"id": "a2", "transcript": "x", "acoustic_metrics": {}})
    assert db.reads[1][1]["s"] is None
    assert pr.record_for_attempt(db, None) is None


def test_the_read_goes_with_the_try_in_the_purge_registry():
    row = {d.code: d for d in DEPENDENCIES}["v4_practice_reads"]
    assert (row.relation, row.selector_column, row.locator_kind,
            row.disposition) == ("v4_practice_reads", "attempt_id",
                                 "practice_attempt", "delete")
