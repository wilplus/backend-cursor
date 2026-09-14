"""The typed degradation marker (audit Q-C1)."""
from __future__ import annotations

import logging

import pytest

from services.degradation import Degradation, DegradationLog


def test_a_healthy_log_adds_nothing_to_a_payload():
    log = DegradationLog("ideal_text")
    assert not log
    assert len(log) == 0
    assert log.payload() == {}


def test_run_returns_the_value_when_the_stage_succeeds():
    log = DegradationLog("ideal_text")
    assert log.run("stage", lambda: 42, default=0) == 42
    assert log.payload() == {}


def test_run_records_the_stage_and_returns_the_default_when_it_raises(caplog):
    log = DegradationLog("ideal_text")

    def boom():
        raise KeyError("snippet_id")

    with caplog.at_level(logging.WARNING, logger="services.degradation"):
        assert log.run("changes.praise_playback", boom, default=[]) == []
    assert log.payload() == {
        "degraded": [{"stage": "ideal_text.changes.praise_playback",
                      "kind": "KeyError"}],
    }
    # The message goes to the log, never into the marker (it can carry ids).
    assert "snippet_id" in caplog.text
    assert "snippet_id" not in str(log.payload())


def test_note_records_a_fallback_taken_without_an_exception():
    log = DegradationLog("ideal_text")
    log.note("changes.span_check", "span_check_failed")
    assert log.items == [
        Degradation("ideal_text.changes.span_check", "span_check_failed")]


def test_markers_keep_their_order():
    log = DegradationLog("take_analysis")
    log.run("cadence", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    log.note("swap_offer", "no_offer")
    log.record("auto_send", ValueError("y"))
    assert [d.stage for d in log.items] == [
        "take_analysis.cadence", "take_analysis.swap_offer",
        "take_analysis.auto_send",
    ]
    assert [d.kind for d in log.items] == [
        "RuntimeError", "no_offer", "ValueError"]


def test_run_lets_base_exceptions_through():
    log = DegradationLog("ideal_text")

    def interrupt():
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        log.run("stage", interrupt)
    assert not log


def test_an_empty_path_uses_the_bare_stage_name():
    log = DegradationLog("")
    log.note("only", "reason")
    assert log.items[0].stage == "only"
