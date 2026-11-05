"""
STORY    As a speaker, I want my earlier Takes read at once when my new Take
         is measured against them, so that my feedback is ready sooner.
OUTCOME
  O1  The confidence reference and the delivery reference are built from
      the same pool as before: every piece of my recent Takes, in the
      Takes' order.
  O2  The recurrence corpus is one text per spoken Take, in order.
  O3  Each Take's pieces are read at the same time as the others', not one
      database round trip after another.
PROVES   O1, O3 -> test_my_references_pool_every_recent_take_in_order
         O2, O3 -> test_the_recurrence_corpus_is_one_text_per_take_in_order
WHY      2026-11-05, the wait: these reads ran one after another inside
         the feedback moments, before the Ideal Text. Only the database is
         faked; its read needs a partner in flight to answer at all.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace

from services.delivery_stars import feature_stats, resolve_delivery_baseline
from services.protected_phrases import collect_take_texts, normalize_phrase
from services.voice_confidence import (
    feature_stats as confidence_stats,
    resolve_confidence_baseline,
)

TAKES = ["t1", "t2", "t3", "t4"]


def _metrics(take: int, piece: int) -> dict:
    return {"speech_rate": 100.0 + 9 * take + piece, "loudness_range": 15.0 + piece,
            "f0_sd": 18.0 + take + 2 * piece, "pause_ratio": 0.2 + 0.03 * piece,
            "f0_mean": 140.0 + 5 * take - piece, "voiced_ratio": 0.6 + 0.02 * piece,
            "mean_pause": 300.0 + 20 * take}


def _rows(sid: str) -> list:
    take = TAKES.index(sid)
    return [{"id": f"{sid}-{p}", "transcript": f"take {take} piece {p}",
             "metrics": _metrics(take, p)} for p in range(3)]


class _Db:
    """Four recent Takes. A read answers only once a second one is in
    flight: one after another, the first waits out its timeout and fails."""

    def __init__(self):
        self.in_flight = threading.Barrier(2, timeout=5)
        sessions = [{"id": sid, "recording_kind": "spoken"} for sid in TAKES]
        self.takes = SimpleNamespace(
            v2_list_user_lab_sessions=lambda *_a, **_k: sessions,
            get_arc_sessions=lambda _arc: sessions)

    def get_snippets_by_session(self, sid):
        self.in_flight.wait()
        return _rows(sid)


def _pool() -> list:
    return [row["metrics"] for sid in TAKES for row in _rows(sid)]


def test_my_references_pool_every_recent_take_in_order():
    confidence, kind = resolve_confidence_baseline("speaker-1", [], database=_Db())
    assert kind == "user"
    assert confidence == confidence_stats(_pool(), min_samples=8)

    delivery = resolve_delivery_baseline("speaker-1", [], database=_Db())
    assert delivery and delivery == feature_stats(_pool(), min_samples=8)


def test_the_recurrence_corpus_is_one_text_per_take_in_order():
    texts = collect_take_texts(_Db(), "arc-1")
    assert texts == [normalize_phrase(" ".join(r["transcript"] for r in _rows(sid)))
                     for sid in TAKES]
